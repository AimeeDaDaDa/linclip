"""Generate desktop and optional autostart entries for this Python installation."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys


def desktop_quote(value: str) -> str:
    value = value.replace("%", "%%")
    for char in ("\\", '"', "`", "$"):
        value = value.replace(char, "\\" + char)
    return '"' + value + '"'


def desktop_entry(*, background: bool = False) -> str:
    argument = "--background" if background else "--toggle"
    return (
        "[Desktop Entry]\nType=Application\nName=LinClip\n"
        "Comment=Clipboard history for Linux\n"
        "Comment[zh_CN]=Linux 剪贴板历史\nComment[zh_TW]=Linux 剪貼簿歷史\n"
        f"Exec={desktop_quote(sys.executable)} -m linclip {argument}\n"
        "Icon=linclip\nTerminal=false\nCategories=Utility;\n"
        "StartupNotify=false\nX-GNOME-Autostart-enabled=true\n"
    )


def install_desktop() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    applications = base / "applications"
    icons = base / "icons/hicolor/scalable/apps"
    applications.mkdir(parents=True, exist_ok=True)
    icons.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__).with_name("assets") / "linclip.svg", icons / "linclip.svg")
    target = applications / "linclip.desktop"
    target.write_text(desktop_entry(), encoding="utf-8")
    return target


def configure_autostart(enabled: bool) -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    target = base / "autostart/linclip.desktop"
    if enabled:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(desktop_entry(background=True), encoding="utf-8")
    else:
        target.unlink(missing_ok=True)
    return target
