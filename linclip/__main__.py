"""Command-line entry point. Diagnostic and desktop commands work without Qt."""

from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import signal
import sys

from . import __version__
from .i18n import configure, tr


def doctor() -> int:
    print(f"LinClip {__version__}")
    print(f"Python: {sys.version.split()[0]}")
    print(f"Platform: {sys.platform}")
    session = os.environ.get("XDG_SESSION_TYPE") or ("wayland" if os.environ.get("WAYLAND_DISPLAY") else "x11")
    print(f"Session: {session}")
    print(f"DISPLAY: {os.environ.get('DISPLAY', '(unset)')}")
    print(f"WAYLAND_DISPLAY: {os.environ.get('WAYLAND_DISPLAY', '(unset)')}")
    qt = importlib.util.find_spec("PySide6") is not None
    print(f"PySide6: {'installed' if qt else 'MISSING: pip install PySide6'}")
    for name in ("wl-paste", "xdotool"):
        print(f"{name}: {shutil.which(name) or '(not installed)'}")
    print("Wayland: background history needs data-control; GNOME usually requires Xorg instead.")
    print("Bind Super+V in desktop keyboard settings to: linclip --toggle")
    return 0 if sys.platform == "linux" and qt else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=tr("LinClip · 剪贴板历史"))
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--toggle", action="store_true", help=tr("切换窗口；尚未运行时启动"))
    group.add_argument("--show", action="store_true", help=tr("显示窗口"))
    group.add_argument("--background", action="store_true", help=tr("后台启动，不显示窗口"))
    group.add_argument("--quit", action="store_true", help=tr("退出正在运行的实例"))
    group.add_argument("--doctor", action="store_true", help=tr("检查依赖和会话环境"))
    group.add_argument("--install-desktop", action="store_true", help=tr("安装应用菜单入口"))
    group.add_argument("--autostart", choices=("enable", "disable"), help=tr("启用或关闭登录自启动"))
    parser.add_argument("--version", action="version", version=f"LinClip {__version__}")
    args = parser.parse_args(argv)
    if args.doctor:
        return doctor()
    if sys.platform != "linux":
        print(tr("LinClip 的桌面程序仅支持 Linux。"), file=sys.stderr)
        return 1
    if args.install_desktop:
        from .desktop import install_desktop
        print(install_desktop())
        return 0
    if args.autostart:
        from .desktop import configure_autostart
        print(configure_autostart(args.autostart == "enable"))
        return 0

    from .ipc import AlreadyRunning, Server, request
    from .paths import data_directory, socket_path

    path = socket_path()
    action = "quit" if args.quit else "ping" if args.background else "toggle" if args.toggle else "show"
    try:
        response = request(path, {"action": action})
        return 0 if response.get("ok") else 1
    except (OSError, ValueError):
        if args.quit:
            print(tr("LinClip 未运行。"))
            return 0

    try:
        from PySide6.QtCore import QLocale, QTimer
        from PySide6.QtWidgets import QApplication
        from .backend import ClipboardMonitor
        from .store import HistoryStore
        from .ui import Bridge, Palette
    except ImportError as exc:
        print(tr("无法加载 Qt：{error}\n请先安装依赖：pip install .", error=exc), file=sys.stderr)
        return 1
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        print(tr("没有检测到图形会话，请在 Linux 桌面会话中运行。"), file=sys.stderr)
        return 1

    # Restrict new database/WAL/socket files before opening any of them.
    os.umask(0o077)
    app = QApplication([sys.argv[0]])
    configure(QLocale.system().name())
    app.setApplicationName("LinClip")
    app.setDesktopFileName("linclip")
    app.setQuitOnLastWindowClosed(False)
    bridge = Bridge()
    try:
        server = Server(path, bridge.message.emit)
    except AlreadyRunning:
        # Another startup won the race. Its server is already listening.
        try:
            return 0 if request(path, {"action": action}).get("ok") else 1
        except (OSError, ValueError):
            print(tr("LinClip 正在启动，请稍后重试。"), file=sys.stderr)
            return 1
    store = None
    monitor = None
    try:
        store = HistoryStore(data_directory() / "history.sqlite3")
        monitor = ClipboardMonitor(store, path)
        palette = Palette(store, monitor)

        def handle_message(message: dict) -> None:
            command = message.get("action")
            if command == "capture":
                monitor.receive(message)
            elif command == "toggle":
                palette.toggle()
            elif command == "show":
                palette.show_palette()
            elif command == "hide":
                palette.hide()
            elif command == "quit":
                app.quit()

        bridge.message.connect(handle_message)
        # Qt must return to Python periodically for SIGINT/SIGTERM handlers.
        pulse = QTimer()
        pulse.timeout.connect(lambda: None)
        pulse.start(250)
        signal.signal(signal.SIGINT, lambda *_: app.quit())
        signal.signal(signal.SIGTERM, lambda *_: app.quit())
        monitor.start()
        if not args.background:
            palette.show_palette()
        return app.exec()
    finally:
        if monitor:
            monitor.close()
        server.close()
        if store:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
