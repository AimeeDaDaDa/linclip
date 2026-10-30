"""Offscreen Qt smoke tests; no live clipboard or compositor is simulated here."""

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HAS_QT = importlib.util.find_spec("PySide6") is not None


@unittest.skipUnless(HAS_QT, "Install the project dependencies to run Qt tests")
class QtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from linclip.backend import ClipboardMonitor
        from linclip.store import HistoryStore
        from linclip.ui import Palette
        self.temp = tempfile.TemporaryDirectory()
        self.store = HistoryStore(Path(self.temp.name) / "history.sqlite3")
        self.monitor = ClipboardMonitor(self.store, Path(self.temp.name) / "control.sock")
        self.palette = Palette(self.store, self.monitor)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.store.close)
        self.addCleanup(self.palette.deleteLater)

    def test_render_search_pin_and_copy_text(self):
        from PySide6.QtCore import Qt
        self.store.add("text", "第一条测试\n第二行".encode())
        other = self.store.add("text", b"a different entry")
        self.palette.show_palette()
        self.app.processEvents()
        self.assertEqual(self.palette.items.count(), 2)
        self.palette.search.setText("different")
        self.palette.refresh()
        self.assertEqual(self.palette.items.count(), 1)
        self.palette.pin_current()
        self.assertTrue(self.store.entries()[0].pinned)
        self.assertEqual(self.palette.items.currentItem().data(Qt.ItemDataRole.UserRole), other)
        self.palette.activate_current()
        self.assertEqual(self.monitor.clipboard.text(), "a different entry")
        self.assertFalse(self.palette.isVisible())

    def test_image_roundtrip_and_card(self):
        from PySide6.QtGui import QColor, QImage
        from linclip.backend import decode_image, encode_image
        image = QImage(32, 24, QImage.Format.Format_ARGB32)
        image.fill(QColor("#7c8cff"))
        payload = encode_image(image)
        self.assertEqual(decode_image(payload).size(), image.size())
        self.store.add("image", payload)
        self.palette.refresh()
        self.palette.activate_current()
        self.assertEqual(self.monitor.clipboard.image().size(), image.size())
        self.assertTrue(decode_image(b"not a png").isNull())

    def test_paused_capture_and_invalid_capture(self):
        import base64
        packet = {"kind": "text", "payload": base64.b64encode(b"hello").decode()}
        self.monitor.set_paused(True)
        self.monitor.receive(packet)
        self.assertEqual(self.store.entries(), [])
        self.monitor.set_paused(False)
        self.monitor.receive(packet)
        self.assertEqual(len(self.store.entries()), 1)
        self.monitor.receive({"kind": "image", "payload": "invalid!"})
        self.assertEqual(len(self.store.entries()), 1)

    def test_system_language_applies_to_controls(self):
        from unittest.mock import patch
        from linclip import i18n
        from linclip.ui import Palette
        previous = i18n._language
        self.addCleanup(setattr, i18n, "_language", previous)
        for language, search, pause in (
            ("en_US", "Search clipboard history…", "Pause recording"),
            ("zh_CN", "搜索剪贴板历史…", "暂停记录"),
        ):
            with self.subTest(language=language), patch.dict(os.environ, {"LANGUAGE": language, "LC_ALL": language}):
                i18n.configure(language)
                candidate = Palette(self.store, self.monitor)
                try:
                    self.assertEqual(candidate.search.placeholderText(), search)
                    self.assertEqual(candidate.pause_action.text(), pause)
                finally:
                    candidate.deleteLater()
                    self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
