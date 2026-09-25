import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import audio_sources
import opentalk


class PlatformPathTests(unittest.TestCase):
    def test_windows_engine_paths_support_ninja_and_visual_studio(self):
        for subdirectory in ("bin", "bin/Release"):
            with (
                self.subTest(subdirectory=subdirectory),
                tempfile.TemporaryDirectory() as folder,
                patch.object(opentalk.platform, "system", return_value="Windows"),
                patch.object(opentalk, "bundled_executable", return_value=None),
                patch.object(opentalk, "local_data_dir", return_value=Path(folder)),
                patch.dict(os.environ, {}, clear=True),
            ):
                binaries = Path(folder) / "whisper.cpp/build" / subdirectory
                binaries.mkdir(parents=True)
                for name in ("whisper-cli", "whisper-server"):
                    (binaries / (name + ".exe")).touch()
                    self.assertEqual(opentalk.engine_executable(name), str(binaries / (name + ".exe")))

    def test_windows_helpers_do_not_open_console_windows(self):
        for system, expected in (("Windows", {"creationflags": 0x08000000}), ("Darwin", {}), ("Linux", {})):
            with patch.object(opentalk.platform, "system", return_value=system):
                self.assertEqual(opentalk.subprocess_options(), expected)

    def test_packaged_engine_takes_precedence_over_old_local_install(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            local = root / "whisper.cpp/build/bin"
            local.mkdir(parents=True)
            for name in ("whisper-cli", "whisper-server"):
                (local / name).touch()
            with (
                patch.object(opentalk, "local_data_dir", return_value=root),
                patch.object(opentalk, "bundled_executable", side_effect=lambda name: root / name),
                patch.dict(os.environ, {"OPENTALK_WHISPER_CLI": "", "OPENTALK_WHISPER_SERVER": ""}),
            ):
                # Explicit overrides, including an empty one, are preserved.
                self.assertEqual(opentalk.whisper_server(), "")
                os.environ.pop("OPENTALK_WHISPER_CLI")
                os.environ.pop("OPENTALK_WHISPER_SERVER")
                self.assertEqual(opentalk.whisper_cli(), str(root / "whisper-cli"))
                self.assertEqual(opentalk.whisper_server(), str(root / "whisper-server"))

    def test_malformed_saved_microphone_falls_back_to_auto(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            with patch.object(opentalk, "settings_path", return_value=path):
                for value in ("null", "17", "[]", "{}"):
                    path.write_text('{"source": ' + value + '}', encoding="utf-8")
                    self.assertEqual(opentalk.saved_source(), "")

    def test_data_and_settings_paths_for_all_supported_systems(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder) / "home"
            cases = (
                (
                    "Linux",
                    {},
                    home / ".local/share/opentalk",
                    home / ".config/opentalk/settings.json",
                ),
                (
                    "Darwin",
                    {},
                    home / "Library/Application Support/OpenTalk",
                    home / "Library/Application Support/OpenTalk/settings.json",
                ),
                (
                    "Windows",
                    {"LOCALAPPDATA": str(home / "AppData/Local")},
                    home / "AppData/Local/OpenTalk",
                    home / "AppData/Local/OpenTalk/settings.json",
                ),
            )
            for system, environment, data_path, settings_path in cases:
                with (
                    self.subTest(system=system),
                    patch.object(opentalk.platform, "system", return_value=system),
                    patch.object(opentalk.Path, "home", return_value=home),
                    patch.dict(os.environ, environment, clear=True),
                ):
                    self.assertEqual(opentalk.local_data_dir(), data_path)
                    self.assertEqual(opentalk.settings_path(), settings_path)

    def test_xdg_paths_override_native_defaults(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.dict(
                os.environ,
                {"XDG_DATA_HOME": folder + "/data", "XDG_CONFIG_HOME": folder + "/config"},
                clear=True,
            ),
        ):
            for system in ("Linux", "Darwin", "Windows"):
                with (
                    self.subTest(system=system),
                    patch.object(opentalk.platform, "system", return_value=system),
                ):
                    self.assertEqual(opentalk.local_data_dir(), Path(folder) / "data/opentalk")
                    self.assertEqual(
                        opentalk.settings_path(), Path(folder) / "config/opentalk/settings.json"
                    )

    def test_bundled_executable_uses_windows_suffix_only_on_windows(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(opentalk, "resource_dir", return_value=Path(folder)),
        ):
            binary_dir = Path(folder) / "bin"
            binary_dir.mkdir()
            (binary_dir / "ffmpeg.exe").touch()
            with patch.object(opentalk.platform, "system", return_value="Windows"):
                self.assertEqual(opentalk.bundled_executable("ffmpeg"), binary_dir / "ffmpeg.exe")
            with patch.object(opentalk.platform, "system", return_value="Linux"):
                self.assertIsNone(opentalk.bundled_executable("ffmpeg"))


class RecorderTests(unittest.TestCase):
    def test_windows_default_resolves_to_an_actual_microphone(self):
        with (
            patch.object(opentalk.platform, "system", return_value="Windows"),
            patch.object(audio_sources, "list_sources", return_value=[("USB", "USB Mic")]),
        ):
            command = opentalk.recorder_command(Path("audio.raw"), raw=True)
        self.assertIn("audio=USB Mic", command)
        self.assertIn("-flush_packets", command)
        with (
            patch.object(opentalk.platform, "system", return_value="Windows"),
            patch.object(audio_sources, "list_sources", return_value=[]),
        ):
            with self.assertRaisesRegex(RuntimeError, "Kein Mikrofon"):
                opentalk.recorder_command(Path("audio.raw"))

    def test_linux_recorder_default_and_selected_source(self):
        destination = Path("/tmp/audio.wav")
        with patch.object(opentalk.platform, "system", return_value="Linux"):
            default = opentalk.recorder_command(destination)
            selected = opentalk.recorder_command(destination, "usb.mic", raw=True)
        self.assertEqual(
            default,
            [
                "pw-record",
                "--rate",
                "16000",
                "--channels",
                "1",
                "--format",
                "s16",
                str(destination),
            ],
        )
        self.assertEqual(
            selected,
            [
                "pw-record",
                "--raw",
                "--rate",
                "16000",
                "--channels",
                "1",
                "--format",
                "s16",
                "--target",
                "usb.mic",
                str(destination),
            ],
        )

    def test_macos_and_windows_recorder_formats(self):
        destination = Path("audio.raw")
        with (
            patch.object(opentalk.platform, "system", return_value="Darwin"),
            patch.object(opentalk.platform, "machine", return_value="arm64"),
            patch.object(opentalk, "recorder_dependency", return_value="mac-ffmpeg"),
        ):
            command = opentalk.recorder_command(destination, "2", raw=True)
        self.assertEqual(
            command[:8],
            ["mac-ffmpeg", "-nostdin", "-loglevel", "error", "-f", "avfoundation", "-i", ":2"],
        )
        self.assertIn("s16le", command)
        self.assertEqual(command[command.index("-flush_packets") + 1], "1")

        with (
            patch.object(opentalk.platform, "system", return_value="Windows"),
            patch.object(opentalk, "recorder_dependency", return_value="ffmpeg.exe"),
        ):
            command = opentalk.recorder_command(destination, "USB Mic")
        self.assertEqual(
            command[:7], ["ffmpeg.exe", "-loglevel", "error", "-f", "dshow", "-i", "audio=USB Mic"]
        )
        self.assertNotIn("-nostdin", command)
        self.assertIn("pcm_s16le", command)

    def test_intel_mac_is_rejected(self):
        with (
            patch.object(opentalk.platform, "system", return_value="Darwin"),
            patch.object(opentalk.platform, "machine", return_value="x86_64"),
        ):
            with self.assertRaisesRegex(RuntimeError, "M-Prozessor"):
                opentalk.recorder_command(Path("audio.wav"))

    def test_windows_stop_prefers_q_and_falls_back_to_terminate(self):
        recorder = Mock()
        recorder.stdin = Mock()
        with patch.object(opentalk.platform, "system", return_value="Windows"):
            opentalk.stop_recorder(recorder)
        recorder.stdin.write.assert_called_once_with(b"q\n")
        recorder.send_signal.assert_not_called()

        recorder = Mock()
        recorder.stdin.write.side_effect = OSError
        with patch.object(opentalk.platform, "system", return_value="Windows"):
            opentalk.stop_recorder(recorder)
        recorder.terminate.assert_called_once()

    def test_posix_stop_uses_sigint(self):
        recorder = Mock(stdin=None)
        with patch.object(opentalk.platform, "system", return_value="Linux"):
            opentalk.stop_recorder(recorder)
        recorder.send_signal.assert_called_once_with(signal.SIGINT)


class TextInsertionTests(unittest.TestCase):
    def test_empty_text_only_informs(self):
        with patch.object(opentalk, "inform") as inform:
            opentalk.insert_text("")
        inform.assert_called_once_with("Keine Sprache erkannt.")

    def test_macos_clipboard_does_not_paste(self):
        with (
            patch.object(opentalk.platform, "system", return_value="Darwin"),
            patch.dict(os.environ, {"OPENTALK_INSERT": "clipboard"}),
            patch.object(opentalk.shutil, "which", return_value="/usr/bin/pbcopy"),
            patch.object(opentalk.subprocess, "run") as run,
            patch.object(opentalk, "inform") as inform,
        ):
            opentalk.insert_text("Hallo")
        run.assert_called_once()
        inform.assert_called_once_with("Text in Zwischenablage – mit Cmd+V einfügen.")

    def test_macos_missing_pbcopy_is_reported(self):
        with (
            patch.object(opentalk.platform, "system", return_value="Darwin"),
            patch.object(opentalk.shutil, "which", return_value=None),
        ):
            with self.assertRaisesRegex(RuntimeError, "pbcopy fehlt"):
                opentalk.insert_text("Hallo")

    def test_windows_auto_and_clipboard_modes(self):
        with (
            patch.object(opentalk.platform, "system", return_value="Windows"),
            patch.object(opentalk, "windows_copy_text") as copy,
            patch.object(opentalk, "windows_paste") as paste,
            patch.object(opentalk, "inform") as inform,
            patch.dict(os.environ, {"OPENTALK_INSERT": "auto"}),
        ):
            opentalk.insert_text("Grüße")
            copy.assert_called_once_with("Grüße")
            paste.assert_called_once()
            inform.assert_called_once_with("Text eingefügt.")

        with (
            patch.object(opentalk.platform, "system", return_value="Windows"),
            patch.object(opentalk, "windows_copy_text") as copy,
            patch.object(opentalk, "windows_paste") as paste,
            patch.object(opentalk, "inform") as inform,
            patch.dict(os.environ, {"OPENTALK_INSERT": "clipboard"}),
        ):
            opentalk.insert_text("Text")
            copy.assert_called_once_with("Text")
            paste.assert_not_called()
            inform.assert_called_once_with("Text in Zwischenablage – mit Strg+V einfügen.")

    def test_linux_stdout_and_explicit_tool_failure(self):
        with (
            patch.object(opentalk.platform, "system", return_value="Linux"),
            patch.dict(os.environ, {"OPENTALK_INSERT": "stdout"}),
            patch("builtins.print") as output,
        ):
            opentalk.insert_text("sichtbar")
        output.assert_called_once_with("sichtbar", flush=True)

        with (
            patch.object(opentalk.platform, "system", return_value="Linux"),
            patch.dict(os.environ, {"OPENTALK_INSERT": "wtype"}),
            patch.object(opentalk.shutil, "which", return_value="/bin/wtype"),
            patch.object(
                opentalk.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "wtype")
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "wtype konnte nicht schreiben"):
                opentalk.insert_text("Text")


class AudioSourceTests(unittest.TestCase):
    def test_linux_sources_are_filtered_and_sorted(self):
        sources = [
            {"name": "z.mic", "description": "Zulu"},
            {"name": "a.monitor", "description": "Monitor"},
            {"name": "a.mic", "description": "alpha"},
            {"name": "", "description": "Ungültig"},
        ]
        self.assertEqual(
            audio_sources.parse_sources(json.dumps(sources)),
            [("alpha", "a.mic"), ("Zulu", "z.mic")],
        )

    def test_linux_source_parser_rejects_wrong_shape_and_ignores_bad_entries(self):
        with self.assertRaisesRegex(ValueError, "Quellenliste"):
            audio_sources.parse_sources('{"name": "not-a-list"}')
        self.assertEqual(
            audio_sources.parse_sources('[null, "bad", {"name": "mic"}]'), [("mic", "mic")]
        )

    def test_source_discovery_failures_have_platform_specific_messages(self):
        for system, machine, expected in (
            ("Linux", "x86_64", "pactl / PipeWire"),
            ("Darwin", "arm64", "ffmpeg prüfen"),
            ("Windows", "AMD64", "FFmpeg/DirectShow"),
        ):
            with (
                self.subTest(system=system),
                patch.object(audio_sources.platform, "system", return_value=system),
                patch.object(audio_sources.platform, "machine", return_value=machine),
                patch.object(audio_sources.subprocess, "run", side_effect=OSError),
            ):
                with self.assertRaisesRegex(RuntimeError, expected):
                    audio_sources.list_sources()

    def test_intel_mac_source_discovery_is_rejected(self):
        with (
            patch.object(audio_sources.platform, "system", return_value="Darwin"),
            patch.object(audio_sources.platform, "machine", return_value="x86_64"),
        ):
            with self.assertRaisesRegex(RuntimeError, "M-Prozessor"):
                audio_sources.list_sources()


if __name__ == "__main__":
    unittest.main()
