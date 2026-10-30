"""System-language selection with English fallback; no Qt dependency."""

from __future__ import annotations

import locale
import os
from typing import Mapping


def detect_language(
    environ: Mapping[str, str] | None = None, system_locale: str | None = None,
) -> str:
    environ = os.environ if environ is None else environ
    base = next((environ[key] for key in ("LC_ALL", "LC_MESSAGES", "LANG") if environ.get(key)), "")
    if base.split(".")[0].upper() in {"C", "POSIX"}:
        return "en"
    value = (environ.get("LANGUAGE") or base or system_locale or locale.getlocale()[0] or "en").split(":")[0]
    value = value.lower().replace("-", "_")
    return "zh" if value.startswith(("zh", "chinese")) else "en"


_language = detect_language()


def configure(system_locale: str) -> None:
    global _language
    _language = detect_language(system_locale=system_locale)


ENGLISH = {
    "剪贴板历史": "Clipboard history",
    "LinClip · 剪贴板历史": "LinClip · Clipboard history",
    "每次复制，都能找回。": "Everything you copy, within reach.",
    "更多选项": "More options",
    "隐藏窗口": "Hide window",
    "隐藏 · Esc": "Hide · Esc",
    "搜索剪贴板历史…": "Search clipboard history…",
    "搜索剪贴板历史": "Search clipboard history",
    "剪贴板，留一份记忆。": "A little memory for your clipboard.",
    "复制一段文字或一张图片\n就会出现在这里": "Copy some text or an image.\nIt will appear here.",
    "没有找到匹配记录，换个关键词试试": "No matching entries. Try another search.",
    "↑↓ 选择   Enter 复制   Esc 隐藏": "↑↓ Select   Enter Copy   Esc Hide",
    "暂停记录": "Pause recording",
    "继续记录": "Resume recording",
    "选择后自动粘贴（X11）": "Paste automatically after selection (X11)",
    "自动粘贴使用 Ctrl+Shift+V（终端）": "Use Ctrl+Shift+V for auto-paste (terminals)",
    "清空历史…": "Clear history…",
    "使用说明": "Help",
    "退出 LinClip": "Quit LinClip",
    "打开剪贴板": "Open clipboard history",
    "退出": "Quit",
    "Ⅱ 已暂停记录": "Ⅱ Recording paused",
    "LinClip · 已暂停": "LinClip · Paused",
    "LinClip · 正在运行": "LinClip · Running",
    "{count} 条记录": "{count} entries",
    "图片": "Image",
    "文本": "Text",
    "已置顶": "Pinned",
    "置顶": "Pin",
    "切换置顶 · Ctrl+P": "Toggle pin · Ctrl+P",
    "删除此条记录 · Delete": "Delete entry · Delete",
    "删除此条记录": "Delete entry",
    "图片无法预览": "Image preview unavailable",
    "图片已损坏，无法复制": "Cannot copy a damaged image",
    "最多可置顶 {count} 条记录": "You can pin up to {count} entries",
    "清空剪贴板历史": "Clear clipboard history",
    "清空已保存的历史记录？": "Clear saved clipboard history?",
    "此操作无法撤销。当前系统剪贴板内容会保留。": "This cannot be undone. The current system clipboard will be kept.",
    "同时删除置顶记录": "Also delete pinned entries",
    "清空": "Clear",
    "取消": "Cancel",
    "LinClip 使用说明": "LinClip help",
    "X11 · 正在记录": "X11 · Recording",
    "Wayland：请安装 wl-clipboard，随后重启 LinClip": "Wayland: install wl-clipboard, then restart LinClip",
    "无法启动 wl-paste，请运行 linclip --doctor 检查": "Cannot start wl-paste. Run linclip --doctor to check.",
    "Wayland · 正在连接后台监听": "Wayland · Connecting background monitor",
    "Wayland 后台监听不可用：桌面需支持 data-control 协议": "Wayland background monitor unavailable: your desktop needs data-control support",
    "Wayland · 正在记录": "Wayland · Recording",
    "切换窗口；尚未运行时启动": "Toggle the window; start if needed",
    "显示窗口": "Show the window",
    "后台启动，不显示窗口": "Start in the background",
    "退出正在运行的实例": "Quit the running instance",
    "检查依赖和会话环境": "Check dependencies and session",
    "安装应用菜单入口": "Install the application menu entry",
    "启用或关闭登录自启动": "Enable or disable login autostart",
    "LinClip 的桌面程序仅支持 Linux。": "The LinClip desktop application requires Linux.",
    "LinClip 未运行。": "LinClip is not running.",
    "LinClip 正在启动，请稍后重试。": "LinClip is starting. Please try again shortly.",
    "没有检测到图形会话，请在 Linux 桌面会话中运行。": "No graphical session detected. Run LinClip in a Linux desktop session.",
    "无法加载 Qt：{error}\n请先安装依赖：pip install .": "Cannot load Qt: {error}\nInstall the dependencies first: pip install .",
    "help_body": (
        "In desktop Settings → Keyboard → Custom shortcuts, bind Super+V to:\n"
        "linclip --toggle\n\n"
        "Click an entry or press Enter to copy it and hide this window.\n"
        "Return to your app and press Ctrl+V (usually Ctrl+Shift+V in a terminal).\n"
        "On X11, install xdotool and enable automatic pasting in the menu.\n\n"
        "Ctrl+F Search · Ctrl+P Pin · Delete Remove selected entry\n"
        "Ctrl+Shift+Delete Clear history · Esc Hide\n\n"
        "History is stored locally, up to 200 entries / 64 MiB of content by default.\n"
        "Pause recording for sensitive content. Wayland monitoring needs desktop support."
    ),
}

CHINESE = {
    "help_body": (
        "在桌面设置 → 键盘 → 自定义快捷键中，将 Super+V 绑定到：\n"
        "linclip --toggle\n\n"
        "点击一条记录或按 Enter：复制到系统剪贴板并隐藏窗口。\n"
        "返回原应用后按 Ctrl+V；终端通常使用 Ctrl+Shift+V。\n"
        "X11 下安装 xdotool 后，可在菜单开启自动粘贴。\n\n"
        "Ctrl+F 搜索 · Ctrl+P 置顶 · Delete 删除选中记录\n"
        "Ctrl+Shift+Delete 清空历史 · Esc 隐藏\n\n"
        "历史保存在本机，默认最多 200 条 / 64 MiB（按内容大小）。\n"
        "密码等敏感内容请暂停记录。Wayland 后台监听需要桌面支持。"
    ),
}


def tr(source: str, **values) -> str:
    catalogue = CHINESE if _language == "zh" else ENGLISH
    return catalogue.get(source, source).format(**values)
