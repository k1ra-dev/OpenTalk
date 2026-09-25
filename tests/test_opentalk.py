import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock
import urllib.error
import urllib.request
import wave

import opentalk as app
import audio_sources


def sample_wav():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 3200)
    return stream.getvalue()


class PipelineTests(unittest.TestCase):
    def test_hyprland_types_unicode_through_wtype_stdin(self):
        with (
            patch.object(app.platform, "system", return_value="Linux"),
            patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "Hyprland", "OPENTALK_INSERT": "auto"}),
            patch.object(app.shutil, "which", side_effect=lambda name: "/bin/" + name),
            patch.object(app.subprocess, "run") as run,
            patch.object(app, "inform"),
        ):
            app.insert_text("Grüß dich")
        self.assertEqual(run.call_args.args[0], ["wtype", "-"])
        self.assertEqual(run.call_args.kwargs["input"], "Grüß dich".encode("utf-8"))

    def test_auto_falls_back_to_clipboard(self):
        with (
            patch.object(app.platform, "system", return_value="Linux"),
            patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "Hyprland", "OPENTALK_INSERT": "auto"}),
            patch.object(app.shutil, "which", side_effect=lambda name: "/bin/" + name),
            patch.object(
                app.subprocess,
                "run",
                side_effect=[
                    app.subprocess.CalledProcessError(1, "wtype"),
                    app.subprocess.CalledProcessError(1, "kwtype"),
                    Mock(returncode=0),
                ],
            ) as run,
            patch.object(app, "inform"),
        ):
            app.insert_text("Test")
        self.assertEqual(run.call_args.args[0][0], "wl-copy")
        self.assertEqual(run.call_args.kwargs["stdout"], app.subprocess.DEVNULL)
        self.assertEqual(run.call_args.kwargs["stderr"], app.subprocess.DEVNULL)

    def test_hotkey_start_stop_and_previous_timer(self):
        engine = app.Dictation()
        recorder = Mock()
        recorder.poll.return_value = None
        recorder.communicate.return_value = (b"", b"")
        done = threading.Event()

        def spawn(command, **kwargs):
            Path(command[-1]).write_bytes(sample_wav())
            return recorder

        def insert(value):
            self.assertEqual(value, "Hallo")
            done.set()

        with (
            patch.object(app.platform, "system", return_value="Linux"),
            patch.object(app.subprocess, "Popen", side_effect=spawn),
            patch.object(app, "transcribe", return_value="Hallo"),
            patch.object(app, "insert_text", side_effect=insert),
            patch.object(app.threading, "Timer"),
        ):
            self.assertIn("Aufnahme läuft", engine.toggle())
            original_session = engine.session
            self.assertIn("Erkenne Text", engine.toggle())
            self.assertTrue(done.wait(2))
            for _ in range(100):
                if not engine.busy:
                    break
                time.sleep(0.01)
            self.assertFalse(engine.busy)
            self.assertIn("Aufnahme läuft", engine.toggle())
            with patch.object(engine, "toggle", side_effect=AssertionError("alter Timer")):
                engine.auto_stop(original_session)
            engine.recorder = None
            engine.temp.cleanup()

    def test_window_can_cancel_recording(self):
        recorder = Mock()
        recorder.poll.return_value = None
        with (
            patch.object(app.platform, "system", return_value="Linux"),
            patch.object(app.subprocess, "Popen", return_value=recorder) as spawn,
            patch.object(app.threading, "Timer"),
        ):
            engine = app.Dictation(on_result=Mock(), source="mic.node")
            engine.toggle()
            self.assertEqual(spawn.call_args.args[0][-3:-1], ["--target", "mic.node"])
            temp_path = Path(engine.temp.name)
            engine.cancel()
            self.assertIn("verworfen", engine.toggle())
        self.assertIsNone(engine.recorder)
        self.assertFalse(temp_path.exists())
        recorder.send_signal.assert_called_once()
        recorder.communicate.assert_called_once()

    def test_recorder_commands_are_separate_for_linux_and_apple_silicon(self):
        destination = Path("/tmp/opentalk-audio.raw")
        with patch.object(app.platform, "system", return_value="Linux"):
            linux = app.recorder_command(destination, "mic.node", raw=True)
        self.assertEqual(linux[0], "pw-record")
        self.assertIn("--target", linux)
        self.assertIn("mic.node", linux)

        with (
            patch.object(app.platform, "system", return_value="Darwin"),
            patch.object(app.platform, "machine", return_value="arm64"),
        ):
            mac = app.recorder_command(destination, "2", raw=True)
        self.assertEqual(mac[0], "ffmpeg")
        self.assertIn(":2", mac)
        self.assertIn("s16le", mac)

        with (
            patch.object(app.platform, "system", return_value="Darwin"),
            patch.object(app.platform, "machine", return_value="x86_64"),
        ):
            with self.assertRaisesRegex(RuntimeError, "M-Prozessor"):
                app.recorder_command(destination)

        with (
            patch.object(app.platform, "system", return_value="Windows"),
            patch.object(app, "bundled_executable", return_value=None),
        ):
            windows = app.recorder_command(destination, "USB Microphone", raw=True)
        self.assertEqual(windows[0], "ffmpeg")
        self.assertIn("dshow", windows)
        self.assertIn("audio=USB Microphone", windows)

    def test_mac_auto_insert_copies_and_pastes(self):
        with (
            patch.object(app.platform, "system", return_value="Darwin"),
            patch.dict(os.environ, {"OPENTALK_INSERT": "auto"}),
            patch.object(app.shutil, "which", side_effect=lambda name: "/usr/bin/" + name),
            patch.object(
                app.subprocess, "run", side_effect=[Mock(returncode=0), Mock(returncode=0)]
            ) as run,
            patch.object(app, "inform"),
        ):
            app.insert_text("Grüß dich")
        self.assertEqual(run.call_args_list[0].args[0], ["pbcopy"])
        self.assertEqual(run.call_args_list[0].kwargs["input"], "Grüß dich".encode("utf-8"))
        self.assertEqual(run.call_args_list[1].args[0][0], "osascript")

    def test_source_list_ignores_speaker_monitors_and_unplugged_inputs(self):
        sources = [
            {"name": "speaker.monitor", "description": "Monitor"},
            {"name": "mic.usb", "description": "USB-Mikrofon", "monitor_source": ""},
            {
                "name": "mic.unplugged",
                "description": "Nicht verbunden",
                "active_port": "mic",
                "ports": [{"name": "mic", "availability": "not available"}],
            },
        ]
        self.assertEqual(
            audio_sources.parse_sources(json.dumps(sources)), [("USB-Mikrofon", "mic.usb")]
        )

    def test_mac_source_list_reads_avfoundation_audio_devices(self):
        output = """[AVFoundation indev @ 0x1] AVFoundation video devices:
[AVFoundation indev @ 0x1] [0] Screen
[AVFoundation indev @ 0x1] AVFoundation audio devices:
[AVFoundation indev @ 0x1] [0] MacBook Pro Microphone
[AVFoundation indev @ 0x1] [1] USB Mic
"""
        with (
            patch.object(audio_sources.platform, "system", return_value="Darwin"),
            patch.object(audio_sources.platform, "machine", return_value="arm64"),
            patch.object(audio_sources.subprocess, "run", return_value=Mock(stderr=output)),
        ):
            self.assertEqual(
                audio_sources.list_sources(), [("MacBook Pro Microphone", "0"), ("USB Mic", "1")]
            )

    def test_windows_source_list_reads_directshow_audio_devices(self):
        output = """[dshow @ 0001] "Integrated Microphone" (audio)
[dshow @ 0001]   Alternative name "@device_cm_1"
[dshow @ 0001] "USB Mic" (audio)
"""
        with (
            patch.object(audio_sources.platform, "system", return_value="Windows"),
            patch.object(audio_sources.subprocess, "run", return_value=Mock(stderr=output)),
        ):
            self.assertEqual(
                audio_sources.list_sources(),
                [("Integrated Microphone", "Integrated Microphone"), ("USB Mic", "USB Mic")],
            )

    def test_saved_microphone_is_used_by_hotkey(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.dict(os.environ, {"XDG_CONFIG_HOME": folder}, clear=False),
        ):
            path = app.settings_path()
            path.parent.mkdir(parents=True)
            path.write_text('{"source": "mic.saved"}', encoding="utf-8")
            with patch.dict(os.environ, {"OPENTALK_SOURCE": ""}, clear=False):
                self.assertEqual(app.Dictation().source, "")
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("OPENTALK_SOURCE", None)
                self.assertEqual(app.Dictation().source, "mic.saved")

    def test_model_selection_and_custom_override(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.dict(
                os.environ, {"XDG_CONFIG_HOME": folder, "XDG_DATA_HOME": folder}, clear=False
            ),
        ):
            settings = app.settings_path()
            settings.parent.mkdir(parents=True)
            settings.write_text('{"model": "base", "source": "mic.saved"}', encoding="utf-8")
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("OPENTALK_MODEL", None)
                self.assertEqual(app.selected_model(), "base")
                self.assertEqual(app.model_path(), app.model_file("base"))
                app.model_file("base").parent.mkdir(parents=True)
                with app.model_file("base").open("wb") as model:
                    model.truncate(app.MODEL_MIN_BYTES["base"])
                self.assertTrue(app.model_available("base"))
                settings.write_text('{"model": "unknown"}', encoding="utf-8")
                self.assertEqual(app.selected_model(), "small")
            with patch.dict(os.environ, {"OPENTALK_MODEL": "/tmp/custom-whisper.bin"}):
                self.assertEqual(app.model_path(), Path("/tmp/custom-whisper.bin"))

    def test_wav_rejects_wrong_rate_and_oversize(self):
        app.validate_wav(sample_wav())
        with self.assertRaises(ValueError):
            app.validate_wav(sample_wav() * 1000)
        stream = io.BytesIO()
        with wave.open(stream, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(44100)
            wav.writeframes(b"\0\0" * 4410)
        with self.assertRaises(ValueError):
            app.validate_wav(stream.getvalue())

    def test_music_only_result_is_ignored(self):
        self.assertEqual(app.clean_transcript("[MUSIK] [MUSIK]"), "")
        self.assertEqual(app.clean_transcript("Hallo [MUSIK] Welt"), "Hallo Welt")

    def test_local_cli_reads_txt_and_preserves_unicode(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "model.bin").write_bytes(b"fake model")

            def fake_cli(command, **_kwargs):
                Path(command[command.index("-of") + 1] + ".txt").write_text(
                    "Grüß dich!\n", encoding="utf-8"
                )
                return Mock(returncode=0, stderr="")

            with (
                patch.dict(
                    os.environ,
                    {
                        "OPENTALK_MODEL": str(path / "model.bin"),
                        "OPENTALK_WHISPER_CLI": sys.executable,
                    },
                ),
                patch.object(app, "whisper_server", return_value=""),
                patch.object(app.subprocess, "run", side_effect=fake_cli),
            ):
                self.assertEqual(app.transcribe(sample_wav()), "Grüß dich!")

    def test_server_auth_and_wav_handling(self):
        from http.server import HTTPServer

        with HTTPServer(("127.0.0.1", 0), app.make_handler("a" * 32)) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{server.server_port}/transcribe"
            try:
                with self.assertRaises(urllib.error.HTTPError) as unauthorized:
                    urllib.request.urlopen(urllib.request.Request(url, data=sample_wav()))
                self.assertEqual(unauthorized.exception.code, 401)
                headers = {"Authorization": "Bearer " + "a" * 32}
                with self.assertRaises(urllib.error.HTTPError) as invalid:
                    urllib.request.urlopen(
                        urllib.request.Request(url, data=b"invalid", headers=headers)
                    )
                self.assertEqual(invalid.exception.code, 400)
                with patch.object(app, "transcribe_local", return_value="Hallo, Welt!"):
                    with urllib.request.urlopen(
                        urllib.request.Request(url, data=sample_wav(), headers=headers)
                    ) as result:
                        self.assertEqual(json.load(result), {"text": "Hallo, Welt!"})
            finally:
                server.shutdown()
                thread.join()


if __name__ == "__main__":
    unittest.main()
