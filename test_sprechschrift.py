import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock
import urllib.error
import urllib.request
import wave

import sprechschrift as app


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
        with patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "Hyprland", "SPRECHSCHRIFT_INSERT": "auto"}), \
             patch.object(app.shutil, "which", side_effect=lambda name: "/bin/" + name), \
             patch.object(app.subprocess, "run") as run, patch.object(app, "inform"):
            app.insert_text("Grüß dich")
        self.assertEqual(run.call_args.args[0], ["wtype", "-"])
        self.assertEqual(run.call_args.kwargs["input"], "Grüß dich".encode("utf-8"))

    def test_auto_falls_back_to_clipboard(self):
        with patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "Hyprland", "SPRECHSCHRIFT_INSERT": "auto"}), \
             patch.object(app.shutil, "which", side_effect=lambda name: "/bin/" + name), \
             patch.object(app.subprocess, "run", side_effect=[app.subprocess.CalledProcessError(1, "wtype"),
                                                               app.subprocess.CalledProcessError(1, "kwtype"),
                                                               Mock(returncode=0)]) as run, \
             patch.object(app, "inform"):
            app.insert_text("Test")
        self.assertEqual(run.call_args.args[0][0], "wl-copy")

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

        with patch.object(app.subprocess, "Popen", side_effect=spawn), \
             patch.object(app, "transcribe", return_value="Hallo"), \
             patch.object(app, "insert_text", side_effect=insert), \
             patch.object(app.threading, "Timer"):
            self.assertIn("Aufnahme läuft", engine.toggle())
            original_session = engine.session
            self.assertIn("Erkenne Text", engine.toggle())
            self.assertTrue(done.wait(2))
            for _ in range(100):
                if not engine.busy:
                    break
                time.sleep(.01)
            self.assertFalse(engine.busy)
            self.assertIn("Aufnahme läuft", engine.toggle())
            with patch.object(engine, "toggle", side_effect=AssertionError("alter Timer")):
                engine.auto_stop(original_session)
            engine.recorder = None
            engine.temp.cleanup()

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

    def test_local_cli_reads_txt_and_preserves_unicode(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "model.bin").write_bytes(b"fake model")
            binary = path / "whisper-cli"
            binary.write_text("#!/usr/bin/env python3\nimport pathlib, sys\n"
                              "pathlib.Path(sys.argv[sys.argv.index('-of')+1] + '.txt').write_text('Grüß dich!\\n', encoding='utf-8')\n")
            binary.chmod(0o755)
            with patch.dict(os.environ, {"SPRECHSCHRIFT_MODEL": str(path / "model.bin"),
                                        "SPRECHSCHRIFT_WHISPER_CLI": str(binary)}):
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
                    urllib.request.urlopen(urllib.request.Request(url, data=b"invalid", headers=headers))
                self.assertEqual(invalid.exception.code, 400)
                with patch.object(app, "transcribe_local", return_value="Hallo, Welt!"):
                    with urllib.request.urlopen(urllib.request.Request(url, data=sample_wav(), headers=headers)) as result:
                        self.assertEqual(json.load(result), {"text": "Hallo, Welt!"})
            finally:
                server.shutdown()
                thread.join()


if __name__ == "__main__":
    unittest.main()
