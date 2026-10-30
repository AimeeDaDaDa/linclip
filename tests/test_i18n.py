import unittest
from unittest.mock import patch

from linclip import i18n


class LanguageTests(unittest.TestCase):
    def test_system_locales(self):
        for value in ("zh_CN.UTF-8", "zh_TW", "zh-HK", "Chinese_China"):
            with self.subTest(value=value):
                self.assertEqual(i18n.detect_language({}, value), "zh")
        for value in ("en_US", "fr_FR", "de_DE", "ja_JP"):
            self.assertEqual(i18n.detect_language({}, value), "en")

    def test_linux_locale_precedence(self):
        self.assertEqual(i18n.detect_language({"LANG": "zh_CN.UTF-8"}), "zh")
        self.assertEqual(i18n.detect_language({"LANG": "en_US", "LC_MESSAGES": "zh_TW"}), "zh")
        self.assertEqual(i18n.detect_language({"LANG": "zh_CN", "LC_ALL": "en_US"}), "en")
        self.assertEqual(i18n.detect_language({"LANG": "en_US", "LANGUAGE": "zh_CN:en"}), "zh")
        self.assertEqual(i18n.detect_language({"LANG": "zh_CN", "LC_ALL": "C.UTF-8", "LANGUAGE": "zh"}), "en")

    def test_translation_and_formatting(self):
        previous = i18n._language
        self.addCleanup(setattr, i18n, "_language", previous)
        with patch.dict("os.environ", {}, clear=True):
            i18n.configure("en_US")
            self.assertEqual(i18n.tr("{count} 条记录", count=3), "3 entries")
            self.assertEqual(i18n.tr("暂停记录"), "Pause recording")
            i18n.configure("zh_CN")
            self.assertEqual(i18n.tr("{count} 条记录", count=3), "3 条记录")
            self.assertEqual(i18n.tr("暂停记录"), "暂停记录")


if __name__ == "__main__":
    unittest.main()
