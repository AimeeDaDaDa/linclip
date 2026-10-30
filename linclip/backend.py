"""Display-server integration. All methods are called on the Qt GUI thread."""

from __future__ import annotations

import base64
import binascii
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QObject, QTimer, Signal
from PySide6.QtGui import QClipboard, QGuiApplication, QImage, QImageReader

from .store import HistoryStore, MAX_ITEM_BYTES
from .i18n import tr


def is_wayland() -> bool:
    return QGuiApplication.platformName().lower().startswith("wayland")


def encode_image(image: QImage) -> bytes | None:
    if image.isNull() or image.width() * image.height() > 16_000_000:
        return None
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        return None
    payload = bytes(data)
    return payload if len(payload) <= MAX_ITEM_BYTES else None


def decode_image(payload: bytes) -> QImage:
    data = QByteArray(payload)
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer, b"png")
    size = reader.size()
    if not size.isValid() or size.width() * size.height() > 16_000_000:
        return QImage()
    return reader.read()


class ClipboardMonitor(QObject):
    changed = Signal()
    status_changed = Signal(str)

    def __init__(self, store: HistoryStore, socket_path: Path) -> None:
        super().__init__()
        self.store = store
        self.socket_path = socket_path
        self.clipboard = QGuiApplication.clipboard()
        self.paused = bool(store.setting("paused", False))
        self.status = ""
        self.watchers: list[tuple[subprocess.Popen, object]] = []
        self.health_timer = QTimer(self)
        self.health_timer.setInterval(1500)
        self.health_timer.timeout.connect(self.check_watchers)
        QImageReader.setAllocationLimit(64)

    def start(self) -> None:
        self.clipboard.dataChanged.connect(self.read_qt)
        if is_wayland():
            self.start_wayland()
        else:
            self.set_status(tr("X11 · 正在记录"))
        QTimer.singleShot(150, self.read_qt)

    def set_status(self, message: str) -> None:
        self.status = message
        self.status_changed.emit(message)

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        self.store.set_setting("paused", paused)
        self.status_changed.emit(self.status)

    def read_qt(self) -> None:
        if self.paused:
            return
        mime = self.clipboard.mimeData(QClipboard.Mode.Clipboard)
        if mime is None:
            return
        hint = bytes(mime.data("application/x-kde-passwordManagerHint"))
        if hint.lower() == b"secret":
            return
        if mime.hasImage():
            payload = encode_image(self.clipboard.image())
            if payload:
                self.record("image", payload)
        elif mime.hasText():
            value = mime.text()
            if len(value) <= MAX_ITEM_BYTES:
                self.record("text", value.encode("utf-8"))

    def receive(self, message: dict) -> None:
        if self.paused:
            return
        kind = message.get("kind")
        if kind not in {"text", "image"} or not isinstance(message.get("payload"), str):
            return
        try:
            payload = base64.b64decode(message["payload"], validate=True)
            if len(payload) > MAX_ITEM_BYTES:
                return
            if kind == "image" and decode_image(payload).isNull():
                return
            self.record(kind, payload)
        except (ValueError, UnicodeError, binascii.Error):
            return

    def record(self, kind: str, payload: bytes) -> None:
        try:
            entry_id = self.store.add(kind, payload)
        except UnicodeError:
            return
        if entry_id is not None:
            self.changed.emit()

    def start_wayland(self) -> None:
        executable = shutil.which("wl-paste")
        if not executable:
            self.set_status(tr("Wayland：请安装 wl-clipboard，随后重启 LinClip"))
            return
        for kind, mime in (("text", "text"), ("image", "image/png")):
            errors = tempfile.TemporaryFile()
            try:
                process = subprocess.Popen(
                    [executable, "--no-newline", "--type", mime, "--watch",
                     sys.executable, "-m", "linclip.capture", kind, str(self.socket_path)],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=errors, start_new_session=True,
                )
                self.watchers.append((process, errors))
            except OSError:
                errors.close()
                self.stop_watchers()
                self.set_status(tr("无法启动 wl-paste，请运行 linclip --doctor 检查"))
                return
        self.set_status(tr("Wayland · 正在连接后台监听"))
        self.health_timer.start()

    def check_watchers(self) -> None:
        if any(process.poll() is not None for process, _ in self.watchers):
            self.stop_watchers()
            self.set_status(tr("Wayland 后台监听不可用：桌面需支持 data-control 协议"))
            return
        self.set_status(tr("Wayland · 正在记录"))

    def stop_watchers(self) -> None:
        self.health_timer.stop()
        for process, errors in self.watchers:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=1)
            errors.close()
        self.watchers.clear()

    def close(self) -> None:
        self.clipboard.dataChanged.disconnect(self.read_qt)
        self.stop_watchers()


def active_x11_window() -> str | None:
    if is_wayland() or not shutil.which("xdotool"):
        return None
    try:
        result = subprocess.run(
            ["xdotool", "getactivewindow"], capture_output=True, text=True, timeout=0.6,
        )
        value = result.stdout.strip()
        return value if result.returncode == 0 and value.isdigit() else None
    except (OSError, subprocess.TimeoutExpired):
        return None


class PasteJob(QObject):
    """Restore focus without blocking the GUI, then send one paste shortcut."""

    finished = Signal()

    def __init__(self, window_id: str, *, terminal: bool) -> None:
        from PySide6.QtCore import QProcess

        super().__init__()
        self.window_id = window_id
        self.done = False
        self.shortcut = "ctrl+shift+v" if terminal else "ctrl+v"
        self.process = QProcess(self)
        self.process.finished.connect(self.activated)
        self.process.errorOccurred.connect(lambda *_: self.finish())
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(self.cancel)

    def start(self) -> None:
        self.timeout.start(1500)
        self.process.start("xdotool", ["windowactivate", "--sync", self.window_id])

    def activated(self, exit_code: int, _status) -> None:
        if self.done:
            return
        if exit_code != 0:
            self.finish()
            return
        self.process.finished.disconnect(self.activated)
        self.process.finished.connect(lambda *_: self.finish())
        self.process.start("xdotool", ["key", "--clearmodifiers", self.shortcut])

    def cancel(self) -> None:
        self.process.kill()
        self.finish()

    def finish(self) -> None:
        if self.done:
            return
        self.done = True
        self.timeout.stop()
        self.finished.emit()
