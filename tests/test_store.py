from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from linclip.store import HistoryStore, MAX_ITEM_BYTES, MAX_PINS


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "history.sqlite3"
        self.store = HistoryStore(self.path)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.store.close)

    def test_persistence_and_exact_text(self):
        payload = "  第一行\n第二行\t😀  ".encode()
        entry_id = self.store.add("text", payload)
        other = HistoryStore(self.path)
        try:
            self.assertEqual(other.payload(entry_id), payload)
            self.assertEqual(other.entries()[0].text, payload.decode())
        finally:
            other.close()

    def test_duplicates_move_to_front_without_losing_pin(self):
        with patch("linclip.store.time.time_ns", side_effect=[10, 20, 30]):
            first = self.store.add("text", b"one")
            self.store.pin(first, True)
            self.store.add("text", b"two")
            self.assertEqual(self.store.add("text", b"one"), first)
        entries = self.store.entries()
        self.assertEqual(len(entries), 2)
        self.assertTrue(entries[0].pinned)
        self.assertEqual(entries[0].created_ns, 10)
        self.assertEqual(entries[0].updated_ns, 30)

    def test_count_eviction_keeps_pinned(self):
        self.store.limit = 3
        pinned = self.store.add("text", b"pinned")
        self.store.pin(pinned, True)
        old = self.store.add("text", b"old")
        self.store.add("text", b"new")
        self.store.add("text", b"newest")
        self.assertEqual(len(self.store.entries()), 3)
        self.assertIsNotNone(self.store.payload(pinned))
        self.assertIsNone(self.store.payload(old))

    def test_byte_eviction(self):
        self.store.max_bytes = 8
        old = self.store.add("text", b"12345")
        new = self.store.add("text", b"67890")
        self.assertIsNone(self.store.payload(old))
        self.assertEqual(self.store.payload(new), b"67890")

    def test_pinned_bytes_reject_without_eviction(self):
        self.store.max_bytes = 8
        entry = self.store.add("text", b"12345")
        self.store.pin(entry, True)
        self.assertIsNone(self.store.add("text", b"67890"))
        self.assertEqual(self.store.payload(entry), b"12345")

    def test_all_slots_pinned(self):
        self.store.limit = 1
        entry = self.store.add("text", b"keep")
        self.store.pin(entry, True)
        self.assertIsNone(self.store.add("text", b"extra"))
        self.assertEqual(len(self.store.entries()), 1)

    def test_pin_cap(self):
        for index in range(MAX_PINS):
            entry = self.store.add("text", f"{index}".encode())
            self.assertTrue(self.store.pin(entry, True))
        extra = self.store.add("text", b"extra")
        self.assertFalse(self.store.pin(extra, True))
        self.assertEqual(sum(e.pinned for e in self.store.entries()), MAX_PINS)

    def test_clear_preserves_pins_then_explicitly_clears_all(self):
        pinned = self.store.add("text", b"keep")
        self.store.pin(pinned, True)
        self.store.add("text", b"remove")
        self.store.clear()
        self.assertEqual([e.id for e in self.store.entries()], [pinned])
        self.store.clear(include_pinned=True)
        self.assertEqual(self.store.entries(), [])

    def test_literal_unicode_search(self):
        self.store.add("text", "你好 Straße 100%_".encode())
        self.store.add("text", b"unrelated")
        for query in ("你好", "STRASSE", "%_", "' OR 1=1 --"):
            self.assertEqual(len(self.store.entries(query)), 0 if query.startswith("'") else 1)

    def test_image_and_text_payloads_are_distinct(self):
        text = self.store.add("text", b"same bytes")
        image = self.store.add("image", b"same bytes")
        self.assertNotEqual(text, image)
        self.assertEqual(len(self.store.entries("图片")), 1)

    def test_reject_invalid_and_oversized_content(self):
        self.assertIsNone(self.store.add("text", b" \n\t"))
        self.assertIsNone(self.store.add("image", b""))
        self.assertIsNone(self.store.add("image", b"x" * (MAX_ITEM_BYTES + 1)))
        with self.assertRaises(UnicodeDecodeError):
            self.store.add("text", b"\xff")
        with self.assertRaises(ValueError):
            self.store.add("html", b"<b>hello</b>")

    def test_settings_and_delete(self):
        self.assertFalse(self.store.setting("paused", False))
        self.store.set_setting("paused", True)
        self.assertIs(self.store.setting("paused"), True)
        entry = self.store.add("text", b"delete")
        self.store.delete(entry)
        self.assertIsNone(self.store.payload(entry))
        self.assertFalse(self.store.pin(entry, True))


if __name__ == "__main__":
    unittest.main()
