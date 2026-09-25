import ctypes
import os
import sys
import unittest
from unittest.mock import Mock, patch

import opentalk


class WindowsClipboardTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32" and os.environ.get("CI") == "true",
                         "Native clipboard check only on an isolated Windows CI runner")
    def test_native_windows_unicode_round_trip(self):
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        value = "OpenTalk – Grüße 🎤"
        opentalk.windows_copy_text(value)
        self.assertEqual(app.clipboard().text(), value)

    def fake_api(self):
        api = Mock()
        api.kernel32.GlobalAlloc.return_value = 1234
        api.kernel32.GlobalLock.return_value = 5678
        api.user32.CreateWindowExW.return_value = 9999
        api.user32.OpenClipboard.return_value = True
        api.user32.EmptyClipboard.return_value = True
        api.user32.SetClipboardData.return_value = 1234
        return api

    def test_clipboard_has_own_window_and_transfers_unicode_memory(self):
        api = self.fake_api()
        api.user32.OpenClipboard.side_effect = [False, True]
        with (
            patch.object(ctypes, "windll", api, create=True),
            patch.object(ctypes, "memmove") as copy,
            patch.object(opentalk.time, "sleep"),
        ):
            opentalk.windows_copy_text("Grüße 🎤")
        api.user32.OpenClipboard.assert_called_with(9999)
        self.assertEqual(api.user32.OpenClipboard.call_count, 2)
        self.assertEqual(copy.call_args.args[1], "Grüße 🎤\0".encode("utf-16-le"))
        api.kernel32.GlobalFree.assert_not_called()
        api.user32.CloseClipboard.assert_called_once()
        api.user32.DestroyWindow.assert_called_once_with(9999)

    def test_failed_transfer_releases_memory_and_window(self):
        api = self.fake_api()
        api.user32.SetClipboardData.return_value = None
        with (
            patch.object(ctypes, "windll", api, create=True),
            patch.object(ctypes, "memmove"),
        ):
            with self.assertRaisesRegex(RuntimeError, "geschrieben"):
                opentalk.windows_copy_text("Text")
        api.kernel32.GlobalFree.assert_called_once_with(1234)
        api.user32.CloseClipboard.assert_called_once()
        api.user32.DestroyWindow.assert_called_once_with(9999)

    def test_busy_clipboard_does_not_empty_it_or_leak_resources(self):
        api = self.fake_api()
        api.user32.OpenClipboard.return_value = False
        with (
            patch.object(ctypes, "windll", api, create=True),
            patch.object(ctypes, "memmove"),
            patch.object(opentalk.time, "sleep"),
        ):
            with self.assertRaisesRegex(RuntimeError, "belegt"):
                opentalk.windows_copy_text("Text")
        api.user32.EmptyClipboard.assert_not_called()
        api.user32.CloseClipboard.assert_not_called()
        api.kernel32.GlobalFree.assert_called_once_with(1234)
        api.user32.DestroyWindow.assert_called_once_with(9999)
