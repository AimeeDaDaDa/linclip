"""A compact keyboard-friendly clipboard palette."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton,
    QSystemTrayIcon, QVBoxLayout, QWidget,
)

from .backend import (
    ClipboardMonitor, PasteJob, active_x11_window, decode_image, is_wayland,
)
from .store import Entry, HistoryStore, MAX_PINS
from .i18n import tr

ICON = Path(__file__).with_name("assets") / "linclip.svg"

STYLE = """
QWidget { color: #edf0fa; font-family: 'Noto Sans CJK SC', 'Noto Sans', sans-serif;
          font-size: 13px; }
QWidget#palette { background: #141721; border: 1px solid #343949; border-radius: 16px; }
QFrame#header { background: transparent; border: none; }
QLabel#brand { color: #f5f6ff; font-size: 23px; font-weight: 700; }
QLabel#subtitle, QLabel#meta, QLabel#footer { color: #949db4; font-size: 11px; }
QLabel#status { color: #aeb7ce; font-size: 11px; }
QLabel#emptyTitle { font-size: 19px; font-weight: 600; color: #d5dafa; }
QLabel#emptyBody { color: #8f99b1; }
QLineEdit { background: #202533; border: 1px solid #353e52; border-radius: 10px;
            padding: 12px 14px; color: #f0f2ff; selection-background-color: #5966bb; }
QLineEdit:focus { border-color: #8d9aff; }
QPushButton { background: #252b3a; border: 1px solid #363f52; border-radius: 7px;
              padding: 6px 10px; color: #bbc4dc; }
QPushButton:hover { background: #343d54; color: white; border-color: #7584d8; }
QPushButton#small { font-size: 11px; padding: 3px 7px; }
QPushButton#pinActive { background: #37345a; color: #c9beff; font-size: 11px; padding: 3px 7px; }
QPushButton#menuButton { font-size: 18px; padding: 3px 10px; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { background: #1d2230; border: 1px solid #2d3546;
                    border-radius: 10px; margin: 0px 0px 8px 0px; }
QListWidget::item:hover { background: #252d40; border-color: #54618a; }
QListWidget::item:selected { background: #2b3350; border-color: #8d9aff; }
QWidget#card { background: transparent; border: none; }
QLabel#preview { background: transparent; color: #e0e5f5; font-size: 13px; }
QScrollBar:vertical { background: transparent; width: 7px; }
QScrollBar::handle:vertical { background: #46506a; border-radius: 3px; min-height: 25px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QMenu { background: #232938; border: 1px solid #414b65; padding: 6px; }
QMenu::item { padding: 8px 20px; border-radius: 4px; }
QMenu::item:selected { background: #3c4665; }
QMenu::separator { height: 1px; background: #414b65; margin: 4px; }
QCheckBox { color: #adb7cf; spacing: 6px; }
QMessageBox { background: #202533; }
"""


class Bridge(QObject):
    message = Signal(dict)


def size_label(size: int) -> str:
    return f"{size / 1024:.1f} KB" if size >= 1024 else f"{size} B"


class Card(QWidget):
    pin_requested = Signal(int, bool)
    delete_requested = Signal(int)

    def __init__(self, entry: Entry, store: HistoryStore) -> None:
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 10, 13, 12)
        layout.setSpacing(8)
        top = QHBoxLayout()
        stamp = datetime.fromtimestamp(entry.updated_ns / 1e9).strftime("%m-%d %H:%M")
        label = tr("图片") if entry.kind == "image" else tr("文本")
        meta = QLabel(f"{label}  ·  {stamp}  ·  {size_label(entry.size)}")
        meta.setObjectName("meta")
        top.addWidget(meta, 1)
        pin = QPushButton(tr("已置顶") if entry.pinned else tr("置顶"))
        pin.setObjectName("pinActive" if entry.pinned else "small")
        pin.setToolTip(tr("切换置顶 · Ctrl+P"))
        pin.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        pin.clicked.connect(lambda: self.pin_requested.emit(entry.id, not entry.pinned))
        remove = QPushButton("×")
        remove.setObjectName("small")
        remove.setToolTip(tr("删除此条记录 · Delete"))
        remove.setAccessibleName(tr("删除此条记录"))
        remove.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        remove.clicked.connect(lambda: self.delete_requested.emit(entry.id))
        top.addWidget(pin)
        top.addWidget(remove)
        layout.addLayout(top)
        preview = QLabel()
        preview.setObjectName("preview")
        preview.setTextFormat(Qt.TextFormat.PlainText)
        preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        if entry.kind == "image":
            payload = store.payload(entry.id)
            image = decode_image(payload) if payload else None
            if image is not None and not image.isNull():
                preview.setPixmap(QPixmap.fromImage(image).scaled(
                    360, 80, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ))
            else:
                preview.setText(tr("图片无法预览"))
        else:
            lines = entry.text[:500].replace("\t", "    ").splitlines()
            visible = "\n".join(lines[:3])
            if len(visible) > 150:
                visible = visible[:150] + "…"
            elif len(lines) > 3 or len(entry.text) > 500:
                visible += "…"
            preview.setText(visible)
            preview.setWordWrap(True)
            preview.setMaximumHeight(62)
        layout.addWidget(preview)
        self.setMinimumHeight(125 if entry.kind == "image" else 108)


class Palette(QWidget):
    def __init__(self, store: HistoryStore, monitor: ClipboardMonitor) -> None:
        super().__init__()
        self.store = store
        self.monitor = monitor
        self.target_window = None
        self.paste_jobs: set[PasteJob] = set()
        self.entries_by_id: dict[int, Entry] = {}
        self.drag_offset = None
        self.setObjectName("palette")
        self.setWindowTitle(tr("LinClip · 剪贴板历史"))
        self.setWindowIcon(QIcon(str(ICON)))
        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.resize(450, 620)
        self.setMinimumSize(390, 420)
        self.setStyleSheet(STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(14)

        header = QFrame()
        header.setObjectName("header")
        header.installEventFilter(self)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout = QVBoxLayout()
        brand_layout.setSpacing(3)
        brand = QLabel("LinClip")
        brand.setObjectName("brand")
        brand.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        brand_layout.addWidget(brand)
        subtitle = QLabel(tr("每次复制，都能找回。"))
        subtitle.setObjectName("subtitle")
        subtitle.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        brand_layout.addWidget(subtitle)
        header_layout.addLayout(brand_layout, 1)
        self.menu_button = QPushButton("...")
        self.menu_button.setObjectName("menuButton")
        self.menu_button.setAccessibleName(tr("更多选项"))
        self.menu_button.setMenu(self.make_menu())
        header_layout.addWidget(self.menu_button)
        hide_button = QPushButton("×")
        hide_button.setAccessibleName(tr("隐藏窗口"))
        hide_button.setToolTip(tr("隐藏 · Esc"))
        hide_button.clicked.connect(self.hide)
        header_layout.addWidget(hide_button)
        layout.addWidget(header)

        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("搜索剪贴板历史…"))
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName(tr("搜索剪贴板历史"))
        self.search.installEventFilter(self)
        self.search.textChanged.connect(self.schedule_refresh)
        self.search.returnPressed.connect(self.activate_current)
        layout.addWidget(self.search)

        self.items = QListWidget()
        self.items.setSpacing(0)
        self.items.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.items.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.items.itemClicked.connect(self.activate_item)
        self.items.itemActivated.connect(self.activate_item)
        self.items.installEventFilter(self)
        layout.addWidget(self.items, 1)

        self.empty = QWidget()
        empty_layout = QVBoxLayout(self.empty)
        empty_layout.addStretch()
        empty_title = QLabel(tr("剪贴板，留一份记忆。"))
        empty_title.setObjectName("emptyTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_title)
        self.empty_body = QLabel(tr("复制一段文字或一张图片\n就会出现在这里"))
        self.empty_body.setObjectName("emptyBody")
        self.empty_body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_body.setWordWrap(True)
        empty_layout.addWidget(self.empty_body)
        empty_layout.addStretch()
        layout.addWidget(self.empty, 1)

        self.status_label = QLabel()
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        bottom = QHBoxLayout()
        self.count_label = QLabel()
        self.count_label.setObjectName("footer")
        bottom.addWidget(self.count_label, 1)
        hint = QLabel(tr("↑↓ 选择   Enter 复制   Esc 隐藏"))
        hint.setObjectName("footer")
        bottom.addWidget(hint)
        layout.addLayout(bottom)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(70)
        self.refresh_timer.timeout.connect(self.refresh)
        monitor.changed.connect(self.schedule_refresh)
        monitor.status_changed.connect(self.update_status)
        self.shortcut("Escape", self.hide)
        self.shortcut("Ctrl+F", self.search.setFocus)
        self.shortcut("Ctrl+P", self.pin_current)
        self.shortcut("Ctrl+Shift+Delete", self.clear_history)
        self.tray = self.make_tray()
        self.refresh()
        self.update_status()

    def shortcut(self, key: str, callback) -> None:
        shortcut = QShortcut(QKeySequence(key), self)
        shortcut.activated.connect(callback)

    def make_menu(self) -> QMenu:
        menu = QMenu(self)
        self.pause_action = menu.addAction(tr("继续记录") if self.monitor.paused else tr("暂停记录"))
        self.pause_action.setCheckable(True)
        self.pause_action.setChecked(self.monitor.paused)
        self.pause_action.toggled.connect(self.toggle_paused)
        self.auto_action = menu.addAction(tr("选择后自动粘贴（X11）"))
        self.auto_action.setCheckable(True)
        self.auto_action.setChecked(bool(self.store.setting("auto_paste", False)))
        self.auto_action.setEnabled(not is_wayland() and bool(shutil.which("xdotool")))
        self.auto_action.toggled.connect(lambda value: self.store.set_setting("auto_paste", value))
        self.terminal_action = menu.addAction(tr("自动粘贴使用 Ctrl+Shift+V（终端）"))
        self.terminal_action.setCheckable(True)
        self.terminal_action.setChecked(bool(self.store.setting("terminal_paste", False)))
        self.terminal_action.setEnabled(self.auto_action.isEnabled())
        self.terminal_action.toggled.connect(lambda value: self.store.set_setting("terminal_paste", value))
        menu.addSeparator()
        menu.addAction(tr("清空历史…"), self.clear_history)
        menu.addAction(tr("使用说明"), self.show_help)
        menu.addSeparator()
        menu.addAction(tr("退出 LinClip"), QApplication.instance().quit)
        return menu

    def make_tray(self) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(QIcon(str(ICON)), self)
        tray.setToolTip(tr("LinClip · 剪贴板历史"))
        menu = QMenu(self)
        menu.addAction(tr("打开剪贴板"), self.show_palette)
        menu.addAction(self.pause_action)
        menu.addSeparator()
        menu.addAction(tr("退出"), QApplication.instance().quit)
        tray.setContextMenu(menu)
        tray.activated.connect(self.tray_activated)
        if QSystemTrayIcon.isSystemTrayAvailable():
            tray.show()
        return tray

    def tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle()

    def toggle_paused(self, paused: bool) -> None:
        self.monitor.set_paused(paused)
        self.pause_action.setText(tr("继续记录") if paused else tr("暂停记录"))

    def update_status(self, *_args) -> None:
        self.status_label.setText(tr("Ⅱ 已暂停记录") if self.monitor.paused else self.monitor.status)
        self.tray.setToolTip(tr("LinClip · 已暂停") if self.monitor.paused else tr("LinClip · 正在运行"))

    def schedule_refresh(self, *_args) -> None:
        self.refresh_timer.start()

    def refresh(self) -> None:
        current = self.items.currentItem()
        selected_id = current.data(Qt.ItemDataRole.UserRole) if current else None
        entries = self.store.entries(self.search.text())
        self.entries_by_id = {entry.id: entry for entry in entries}
        self.items.clear()
        selected_item = None
        for entry in entries:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            item.setSizeHint(QSize(0, 139 if entry.kind == "image" else 122))
            self.items.addItem(item)
            card = Card(entry, self.store)
            card.pin_requested.connect(self.set_pin)
            card.delete_requested.connect(self.delete_entry)
            self.items.setItemWidget(item, card)
            if entry.id == selected_id:
                selected_item = item
        if selected_item:
            self.items.setCurrentItem(selected_item)
        elif self.items.count():
            self.items.setCurrentRow(0)
        self.items.setVisible(bool(entries))
        self.empty.setVisible(not entries)
        self.empty_body.setText(
            tr("没有找到匹配记录，换个关键词试试") if self.search.text().strip()
            else tr("复制一段文字或一张图片\n就会出现在这里")
        )
        self.count_label.setText(tr("{count} 条记录", count=len(entries)))

    def show_palette(self) -> None:
        if not self.isVisible():
            self.target_window = active_x11_window()
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            width = min(450, area.width() - 24)
            height = min(620, area.height() - 24)
            self.setMinimumSize(min(390, width), min(420, height))
            self.resize(width, height)
            self.move(area.center().x() - width // 2, area.center().y() - height // 2)
        self.search.clear()
        self.refresh()
        self.show()
        self.raise_()
        self.activateWindow()
        self.search.setFocus()

    def toggle(self) -> None:
        self.hide() if self.isVisible() else self.show_palette()

    def activate_current(self) -> None:
        item = self.items.currentItem()
        if item:
            self.activate_item(item)

    def activate_item(self, item: QListWidgetItem) -> None:
        entry_id = item.data(Qt.ItemDataRole.UserRole)
        entry = self.entries_by_id.get(entry_id)
        payload = self.store.payload(entry_id)
        if entry is None or payload is None:
            return
        if entry.kind == "text":
            self.monitor.clipboard.setText(payload.decode("utf-8"))
        else:
            image = decode_image(payload)
            if image.isNull():
                self.status_label.setText(tr("图片已损坏，无法复制"))
                return
            self.monitor.clipboard.setImage(image)
        self.store.touch(entry_id)
        self.hide()
        if self.auto_action.isEnabled() and self.auto_action.isChecked() and self.target_window:
            target = self.target_window
            QTimer.singleShot(160, lambda: self.start_paste(target))

    def start_paste(self, window_id: str) -> None:
        job = PasteJob(window_id, terminal=self.terminal_action.isChecked())
        self.paste_jobs.add(job)
        job.finished.connect(lambda: self.finish_paste(job))
        job.start()

    def finish_paste(self, job: PasteJob) -> None:
        self.paste_jobs.discard(job)
        job.deleteLater()

    def set_pin(self, entry_id: int, pinned: bool) -> None:
        if not self.store.pin(entry_id, pinned):
            self.status_label.setText(tr("最多可置顶 {count} 条记录", count=MAX_PINS))
        self.refresh()

    def pin_current(self) -> None:
        item = self.items.currentItem()
        if item:
            entry = self.entries_by_id[item.data(Qt.ItemDataRole.UserRole)]
            self.set_pin(entry.id, not entry.pinned)

    def delete_entry(self, entry_id: int) -> None:
        row = self.items.currentRow()
        self.store.delete(entry_id)
        self.refresh()
        if self.items.count():
            self.items.setCurrentRow(min(max(row, 0), self.items.count() - 1))

    def clear_history(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(tr("清空剪贴板历史"))
        box.setText(tr("清空已保存的历史记录？"))
        box.setInformativeText(tr("此操作无法撤销。当前系统剪贴板内容会保留。"))
        include_pinned = QCheckBox(tr("同时删除置顶记录"))
        box.setCheckBox(include_pinned)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        box.button(QMessageBox.StandardButton.Yes).setText(tr("清空"))
        box.button(QMessageBox.StandardButton.Cancel).setText(tr("取消"))
        if box.exec() == QMessageBox.StandardButton.Yes:
            self.store.clear(include_pinned=include_pinned.isChecked())
            self.refresh()

    def show_help(self) -> None:
        QMessageBox.information(self, tr("LinClip 使用说明"), tr("help_body"))

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if watched == self.search and key in {Qt.Key.Key_Down, Qt.Key.Key_Up}:
                if self.items.count():
                    self.items.setFocus()
                    if self.items.currentRow() < 0:
                        self.items.setCurrentRow(0)
                    elif key == Qt.Key.Key_Down:
                        self.items.setCurrentRow(min(self.items.currentRow() + 1, self.items.count() - 1))
                return True
            if watched == self.items and key == Qt.Key.Key_Delete:
                item = self.items.currentItem()
                if item:
                    self.delete_entry(item.data(Qt.ItemDataRole.UserRole))
                return True
        if watched.objectName() == "header":
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                if self.windowHandle() and self.windowHandle().startSystemMove():
                    return True
                self.drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            elif event.type() == QEvent.Type.MouseMove and self.drag_offset is not None:
                self.move(event.globalPosition().toPoint() - self.drag_offset)
                return True
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self.drag_offset = None
        return super().eventFilter(watched, event)

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()
