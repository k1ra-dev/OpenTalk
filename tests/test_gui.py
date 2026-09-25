import os
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QProcess, Qt
from PyQt6.QtWidgets import QApplication

import opentalk_gui


class GuiHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def make_overlay(self):
        with (
            patch.object(opentalk_gui, "apply_layer_shell", return_value=False),
            patch.object(opentalk_gui, "setup_problem", return_value=None),
            patch.object(opentalk_gui.Overlay, "configure_hotkey", return_value="Aktiv"),
        ):
            overlay = opentalk_gui.Overlay()
        self.addCleanup(overlay.close)
        return overlay

    def wait_until(self, condition, timeout=3):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertTrue(condition(), "Queued GUI operation did not finish")

    def capture_environment(self, engine):
        stack = ExitStack()
        for owner, name, value in (
            (opentalk_gui, "LiveDictation", engine),
            (opentalk_gui, "microphone_denied", False),
            (opentalk_gui, "setup_problem", None),
            (opentalk_gui, "active_target", ""),
            (opentalk_gui.shutil, "which", None),
            (opentalk_gui.opentalk, "warm_transcriber_async", None),
            (opentalk_gui.opentalk.LOCAL_WHISPER_SERVER, "begin_session", None),
            (opentalk_gui.opentalk.LOCAL_WHISPER_SERVER, "end_session", None),
        ):
            stack.enter_context(patch.object(owner, name, return_value=value))
        return stack

    def test_slow_insertion_is_serial_and_does_not_block_gui(self):
        overlay = self.make_overlay()
        entered, release = threading.Event(), threading.Event()
        threads = []

        def insert(*_args):
            threads.append(threading.get_ident())
            entered.set()
            release.wait(3)
            return "Text eingefügt."

        with patch.object(opentalk_gui, "insert_into_target", side_effect=insert) as paste:
            try:
                overlay.on_chunk("Eins")
                self.assertTrue(entered.wait(1))
                overlay.on_chunk("Zwei")
                overlay.on_finished()
                self.app.processEvents()
                self.assertEqual(paste.call_count, 1)
                self.assertTrue(overlay.inserting)
                with patch.object(opentalk_gui, "LiveDictation") as new_capture:
                    overlay.toggle_recording()
                    new_capture.assert_not_called()
            finally:
                release.set()
            self.wait_until(lambda: not overlay.inserting and not overlay.pending_parts)
            self.assertEqual([call.args[0] for call in paste.call_args_list], ["Eins", " Zwei"])
            self.assertNotIn(threading.get_ident(), threads)
            self.assertEqual(overlay.state, "idle")

    def test_push_to_talk_release_during_slow_start_is_not_lost(self):
        overlay = self.make_overlay()
        overlay.hold_to_talk = True
        engine = Mock(recording=False)
        entered, release = threading.Event(), threading.Event()

        def start():
            entered.set()
            release.wait(3)
            engine.recording = True

        engine.start.side_effect = start
        with self.capture_environment(engine):
            try:
                overlay.on_hotkey_pressed()
                self.assertTrue(entered.wait(1))
                self.assertTrue(overlay.starting)
                overlay.on_hotkey_released()
                self.assertTrue(overlay.stop_after_start)
                engine.stop.assert_not_called()
            finally:
                release.set()
            self.wait_until(lambda: not overlay.starting)
            engine.stop.assert_called_once()

    def test_failed_background_start_releases_session(self):
        overlay = self.make_overlay()
        engine = Mock(recording=False)
        engine.start.side_effect = RuntimeError("Mikrofon fehlt")
        with self.capture_environment(engine):
            overlay.toggle_recording()
            self.wait_until(lambda: overlay.engine is None)
            self.assertFalse(overlay.local_session)
            self.assertIn("Mikrofon fehlt", overlay.toolTip())

    def test_close_during_background_start_cancels_new_recorder(self):
        overlay = self.make_overlay()
        engine = Mock(recording=False)
        entered, release, done = threading.Event(), threading.Event(), threading.Event()

        def start():
            entered.set()
            release.wait(3)
            done.set()

        engine.start.side_effect = start
        with self.capture_environment(engine):
            try:
                overlay.toggle_recording()
                self.assertTrue(entered.wait(1))
                overlay.close()
            finally:
                release.set()
            self.wait_until(lambda: done.is_set() and engine.cancel.call_count >= 2)
            self.assertFalse(overlay.local_session)

    def test_microphone_discovery_does_not_block_gui_or_query_twice(self):
        overlay = self.make_overlay()
        entered, release = threading.Event(), threading.Event()

        def discover():
            entered.set()
            release.wait(3)
            raise RuntimeError("Kein Mikrofon")

        with patch.object(opentalk_gui.audio_sources, "list_sources", side_effect=discover) as query:
            try:
                overlay.show_sources()
                self.assertTrue(entered.wait(1))
                overlay.show_sources()
                self.assertFalse(overlay.mic_button.isEnabled())
                query.assert_called_once()
            finally:
                release.set()
            self.wait_until(lambda: not overlay.sources_loading)
            self.assertTrue(overlay.mic_button.isEnabled())
            self.assertIn("Kein Mikrofon", overlay.toolTip())

    def test_layer_shell_rejects_mismatched_system_qt_before_loading_bridge(self):
        with (
            patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0", "QT_QPA_PLATFORM": "wayland"}),
            patch.object(opentalk_gui, "qVersion", return_value="6.11.2"),
            patch.object(opentalk_gui.subprocess, "run", return_value=Mock(stdout="6.4.2\n")) as run,
            patch.object(opentalk_gui.ctypes, "CDLL") as load,
        ):
            self.assertFalse(opentalk_gui.apply_layer_shell(Mock()))
            run.assert_called_once()
            load.assert_not_called()

    def test_push_to_talk_starts_once_and_stops_on_release(self):
        overlay = self.make_overlay()
        overlay.hold_to_talk = True
        engine = Mock(recording=True)

        def toggle():
            if overlay.engine is None:
                overlay.engine = engine
            else:
                engine.stop()
                engine.recording = False

        with patch.object(overlay, "toggle_recording", side_effect=toggle) as action:
            overlay.on_hotkey_pressed()
            overlay.on_hotkey_pressed()
            self.assertEqual(action.call_count, 1)
            overlay.on_hotkey_released()
            overlay.on_hotkey_released()
            self.assertEqual(action.call_count, 2)
        engine.stop.assert_called_once()

    def test_push_to_talk_does_not_stop_a_mouse_started_recording(self):
        overlay = self.make_overlay()
        overlay.hold_to_talk = True
        overlay.engine = Mock(recording=True)
        with patch.object(overlay, "toggle_recording") as toggle:
            overlay.on_hotkey_pressed()
            overlay.on_hotkey_released()
        toggle.assert_not_called()

    def test_insertion_waits_until_hotkey_modifiers_are_released(self):
        overlay = self.make_overlay()
        overlay.hotkey_keys_held = True
        with patch.object(opentalk_gui, "insert_into_target", return_value="Text eingefügt.") as insert:
            overlay.on_chunk("Hallo")
            overlay.on_chunk("Welt")
            overlay.on_finished()
            insert.assert_not_called()
            overlay.on_hotkey_cleared()
            self.wait_until(lambda: not overlay.inserting and not overlay.pending_parts)
            self.assertEqual([call.args[0] for call in insert.call_args_list], ["Hallo", " Welt"])
            self.assertEqual(overlay.transcript_parts, ["Hallo", "Welt"])
            self.assertEqual(overlay.state, "idle")

    def test_permission_failure_does_not_start_microphone(self):
        overlay = self.make_overlay()
        with (
            patch.object(opentalk_gui, "microphone_denied", return_value=True),
            patch.object(opentalk_gui, "LiveDictation") as engine,
        ):
            overlay.toggle_recording()
        engine.assert_not_called()
        self.assertIn("Mikrofonzugriff fehlt", overlay.toolTip())

    def test_mac_microphone_check_distinguishes_denied_and_undetermined(self):
        for status, denied in (
            (Qt.PermissionStatus.Denied, True),
            (Qt.PermissionStatus.Undetermined, False),
            (Qt.PermissionStatus.Granted, False),
        ):
            with (
                self.subTest(status=status),
                patch.object(opentalk_gui.platform, "system", return_value="Darwin"),
                patch.object(opentalk_gui.QApplication, "instance") as app,
            ):
                app.return_value.checkPermission.return_value = status
                self.assertEqual(opentalk_gui.microphone_denied(), denied)

    def test_meter_renders_without_a_separate_window(self):
        overlay = self.make_overlay()
        overlay.engine = Mock(recording=True)
        overlay.on_level(0.75)
        self.assertEqual(overlay.mic_level, 0.75)
        self.assertFalse(overlay.grab().isNull())
        overlay.engine.recording = False
        overlay.on_level(0.8)
        self.assertEqual(overlay.mic_level, 0)

    def test_idle_timer_is_optional_on_all_platforms(self):
        overlay = self.make_overlay()
        for system, setting, expected in (
            ("Darwin", {}, True), ("Darwin", {"model_sleep": False}, False),
            ("Linux", {}, True), ("Windows", {}, True),
        ):
            with (
                self.subTest(system=system, setting=setting),
                patch.object(opentalk_gui.platform, "system", return_value=system),
                patch.object(opentalk_gui, "read_settings", return_value=setting),
            ):
                overlay.configure_model_sleep()
                self.assertEqual(overlay.model_idle_timer.isActive(), expected)

    def test_failed_insertion_retains_all_segments_without_retrying_paste(self):
        overlay = self.make_overlay()
        clipboard = Mock()
        with (
            patch.object(opentalk_gui.QApplication, "clipboard", return_value=clipboard),
            patch.object(opentalk_gui, "insert_into_target", return_value="Bedienungshilfen fehlen")
            as insert,
        ):
            overlay.on_chunk("Hallo")
            overlay.on_chunk("schöne Welt")
            overlay.on_finished()
            self.wait_until(lambda: overlay.clipboard_only and not overlay.inserting)
            insert.assert_called_once_with("Hallo", "")
            clipboard.setText.assert_called_with("Hallo schöne Welt")
            overlay.copy_last_transcript()
            clipboard.setText.assert_called_with("Hallo schöne Welt")
        self.assertEqual(overlay.state, "error")

    def test_clipboard_recovery_does_not_repeat_already_inserted_segments(self):
        overlay = self.make_overlay()
        clipboard = Mock()
        with (
            patch.object(opentalk_gui.QApplication, "clipboard", return_value=clipboard),
            patch.object(
                opentalk_gui, "insert_into_target", side_effect=["Text eingefügt.", "fehlgeschlagen"]
            ) as insert,
        ):
            overlay.on_chunk("Schon eingefügt.")
            overlay.on_chunk("Noch")
            overlay.on_chunk("offen.")
            self.wait_until(lambda: overlay.clipboard_only and not overlay.inserting)
            clipboard.setText.assert_called_with("Noch offen.")
            self.assertEqual(insert.call_count, 2)
            overlay.copy_last_transcript()
            clipboard.setText.assert_called_with("Schon eingefügt. Noch offen.")

    def test_new_recording_waits_for_queued_finished_callback(self):
        overlay = self.make_overlay()
        overlay.engine = Mock(recording=False, busy=False)
        with patch.object(opentalk_gui, "LiveDictation") as engine:
            overlay.toggle_recording()
        engine.assert_not_called()
        self.assertIsNotNone(overlay.engine)

    def test_missing_setup_helper_unlocks_controls(self):
        overlay = self.make_overlay()
        with (
            patch.object(opentalk_gui, "setup_problem", return_value="Erkennung fehlt"),
            patch.object(opentalk_gui.opentalk, "model_available", return_value=False),
            patch.object(opentalk_gui.opentalk, "config", return_value=""),
        ):
            dialog = opentalk_gui.SetupDialog(overlay)
            overlay.setup_dialog = dialog
            dialog.operation = "setup"
            dialog.slider.setEnabled(False)
            dialog.install_button.setEnabled(False)
            dialog.process.start("/nonexistent/opentalk-test-helper", [])
            self.assertFalse(dialog.process.waitForStarted(1000))
            self.assertEqual(dialog.process.error(), QProcess.ProcessError.FailedToStart)
            self.assertIsNone(dialog.operation)
            self.assertTrue(dialog.slider.isEnabled())
            self.assertTrue(dialog.install_button.isEnabled())
            self.assertIn("fehlgeschlagen", dialog.info.text())

    def test_status_refresh_keeps_hotkey_permission_error_visible(self):
        overlay = self.make_overlay()
        overlay.hotkey_error = "Bedienungshilfen fehlen"
        with patch.object(opentalk_gui, "setup_problem", return_value=None):
            overlay.update_status()
        self.assertEqual(overlay.state, "error")
        self.assertIn("Bedienungshilfen", overlay.toolTip())

    def test_default_hotkeys_for_every_platform(self):
        for system, expected in (
            ("Darwin", "Meta+Shift+Space"),
            ("Windows", "Ctrl+Alt+R"),
            ("Linux", "Ctrl+Alt+R"),
        ):
            with (
                self.subTest(system=system),
                patch.object(opentalk_gui.platform, "system", return_value=system),
            ):
                self.assertEqual(opentalk_gui.default_hotkey(), expected)

    def test_hotkey_conversion_and_validation(self):
        self.assertEqual(opentalk_gui.pynput_hotkey("Meta+Shift+Space"), "<cmd>+<shift>+<space>")
        self.assertEqual(opentalk_gui.pynput_hotkey("Ctrl+Alt+R"), "<ctrl>+<alt>+r")
        with self.assertRaisesRegex(ValueError, "Sondertaste"):
            opentalk_gui.pynput_hotkey("R")
        for invalid in ("Ctrl+Shift", "R+T", "Ctrl+R, Ctrl+T", "Ctrl+Ctrl+R"):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                opentalk_gui.pynput_hotkey(invalid)

    def test_macos_hotkey_editor_round_trip_preserves_command_and_control(self):
        for saved, qt_value, listener in (
            ("Meta+Shift+Space", "Ctrl+Shift+Space", "<cmd>+<shift>+<space>"),
            ("Ctrl+Alt+R", "Meta+Alt+R", "<ctrl>+<alt>+r"),
        ):
            with (
                self.subTest(saved=saved),
                patch.object(opentalk_gui.platform, "system", return_value="Darwin"),
            ):
                self.assertEqual(opentalk_gui.translate_qt_hotkey(saved), qt_value)
                self.assertEqual(opentalk_gui.translate_qt_hotkey(qt_value), saved)
                self.assertEqual(
                    opentalk_gui.pynput_hotkey(opentalk_gui.translate_qt_hotkey(qt_value)), listener
                )
        for system in ("Linux", "Windows"):
            with patch.object(opentalk_gui.platform, "system", return_value=system):
                self.assertEqual(opentalk_gui.translate_qt_hotkey("Ctrl+Alt+R"), "Ctrl+Alt+R")

    def test_macos_accessibility_check_can_request_permission(self):
        framework = ModuleType("ApplicationServices")
        framework.AXIsProcessTrusted = Mock(return_value=True)
        framework.AXIsProcessTrustedWithOptions = Mock(return_value=False)
        framework.kAXTrustedCheckOptionPrompt = "prompt"
        with (
            patch.object(opentalk_gui.platform, "system", return_value="Darwin"),
            patch.dict(sys.modules, {"ApplicationServices": framework}),
        ):
            self.assertTrue(opentalk_gui.macos_accessibility_trusted())
            self.assertFalse(opentalk_gui.macos_accessibility_trusted(prompt=True))
        framework.AXIsProcessTrustedWithOptions.assert_called_once_with({"prompt": True})

    def test_macos_hotkey_reports_missing_accessibility_permission(self):
        overlay = Mock()
        overlay.hotkey_listener = None
        with (
            patch.object(opentalk_gui, "selected_hotkey", return_value="Meta+Shift+Space"),
            patch.object(opentalk_gui, "macos_accessibility_trusted", return_value=False),
        ):
            status = opentalk_gui.Overlay.configure_hotkey(overlay)
        self.assertIn("nicht aktiv", status)
        overlay.set_status.assert_called_once()
        self.assertTrue(overlay.set_status.call_args.kwargs["error"])

    def test_settings_round_trip_preserves_existing_values(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.dict(os.environ, {"XDG_CONFIG_HOME": folder}),
            patch.object(opentalk_gui.platform, "system", return_value="Linux"),
        ):
            opentalk_gui.save_setting("source", "usb")
            opentalk_gui.save_setting("hotkey", "Ctrl+Alt+R")
            self.assertEqual(
                opentalk_gui.read_settings(), {"source": "usb", "hotkey": "Ctrl+Alt+R"}
            )
            self.assertFalse((Path(folder) / "opentalk/settings.json.tmp").exists())

    def test_invalid_settings_fall_back_to_defaults(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.dict(os.environ, {"XDG_CONFIG_HOME": folder}),
            patch.object(opentalk_gui.platform, "system", return_value="Windows"),
        ):
            path = Path(folder) / "opentalk/settings.json"
            path.parent.mkdir()
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(opentalk_gui.read_settings(), {})
            self.assertEqual(opentalk_gui.selected_hotkey(), "Ctrl+Alt+R")

    def test_setup_problem_reports_intel_mac_and_missing_dependencies(self):
        with (
            patch.object(opentalk_gui.platform, "system", return_value="Darwin"),
            patch.object(opentalk_gui.platform, "machine", return_value="x86_64"),
            patch.object(opentalk_gui.opentalk, "recorder_dependency", return_value="ffmpeg"),
        ):
            self.assertIn("M-Prozessor", opentalk_gui.setup_problem())

        with (
            patch.object(opentalk_gui.platform, "system", return_value="Linux"),
            patch.object(opentalk_gui.opentalk, "recorder_dependency", return_value="pw-record"),
            patch.object(opentalk_gui.shutil, "which", return_value=None),
        ):
            self.assertIn("Aufnahme-Abhängigkeit", opentalk_gui.setup_problem())

    def test_macos_overlay_stays_visible_when_another_app_activates(self):
        with (
            patch.object(opentalk_gui.platform, "system", return_value="Darwin"),
            patch.object(opentalk_gui, "apply_layer_shell", return_value=False),
            patch.object(opentalk_gui, "setup_problem", return_value=None),
            patch.object(opentalk_gui.Overlay, "configure_hotkey", return_value="Aktiv"),
        ):
            overlay = opentalk_gui.Overlay()
        try:
            self.assertTrue(overlay.testAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow))
            self.assertTrue(overlay.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
            self.assertTrue(overlay.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
            self.assertFalse(overlay.screen_timer.isActive())
        finally:
            overlay.close()

    def test_drag_does_not_disable_global_hotkey(self):
        overlay = Mock()
        overlay.drag_timer = Mock()
        overlay.hotkey_listener = Mock()
        overlay.anchor = Mock()
        with (
            patch.object(opentalk_gui.Overlay, "update_drag"),
            patch.object(opentalk_gui.Overlay, "releaseMouse"),
            patch.object(opentalk_gui.Overlay, "setCursor"),
            patch.object(opentalk_gui, "save_setting"),
        ):
            opentalk_gui.Overlay.end_drag(overlay)
        overlay.hotkey_listener.stop.assert_not_called()

    def test_instance_lock_recovers_stale_file_but_keeps_live_instance(self):
        recovered = Mock()
        recovered.tryLock.side_effect = [False, True]
        recovered.removeStaleLockFile.return_value = True
        with (
            patch.object(
                opentalk_gui.opentalk,
                "runtime_socket",
                return_value=Path("/tmp/opentalk-test/opentalk.sock"),
            ),
            patch.object(opentalk_gui, "QLockFile", return_value=recovered),
        ):
            self.assertIs(opentalk_gui.acquire_instance_lock(), recovered)
        self.assertEqual(recovered.tryLock.call_count, 2)

        active = Mock()
        active.tryLock.return_value = False
        active.removeStaleLockFile.return_value = False
        with (
            patch.object(
                opentalk_gui.opentalk,
                "runtime_socket",
                return_value=Path("/tmp/opentalk-test/opentalk.sock"),
            ),
            patch.object(opentalk_gui, "QLockFile", return_value=active),
        ):
            self.assertIsNone(opentalk_gui.acquire_instance_lock())
        self.assertEqual(active.tryLock.call_count, 1)


if __name__ == "__main__":
    unittest.main()
