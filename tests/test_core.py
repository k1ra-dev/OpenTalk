import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch
import urllib.error
import wave

import opentalk


def wav_bytes(frames=3200, rate=16_000, channels=1, width=2):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(width)
        audio.setframerate(rate)
        audio.writeframes(b"\0" * frames * channels * width)
    return output.getvalue()


class ValidationTests(unittest.TestCase):
    def test_valid_wav_is_accepted(self):
        opentalk.validate_wav(wav_bytes())

    def test_corrupt_short_and_wrong_format_wav_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Ungültige"):
            opentalk.validate_wav(b"not wave data")
        with self.assertRaisesRegex(ValueError, "zu kurz"):
            opentalk.validate_wav(wav_bytes(frames=100))
        for options in ({"rate": 44_100}, {"channels": 2}, {"width": 1}):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, "16 kHz"):
                opentalk.validate_wav(wav_bytes(**options))

    def test_transcript_cleanup_removes_music_markers_case_insensitively(self):
        self.assertEqual(
            opentalk.clean_transcript("  Hallo  [Music]   Welt [MUSIK] "), "Hallo Welt"
        )

    def test_truncated_wav_is_rejected_even_with_valid_header(self):
        with self.assertRaisesRegex(ValueError, "unvollständig"):
            opentalk.validate_wav(wav_bytes()[:-200])


class TranscriptionTests(unittest.TestCase):
    def test_persistent_path_is_used_on_every_platform(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(opentalk, "model_path", return_value=Path(folder) / "model"),
            patch.object(opentalk.shutil, "which", return_value="helper"),
            patch.object(opentalk, "whisper_server", return_value="server"),
            patch.object(opentalk.LOCAL_WHISPER_SERVER, "transcribe", return_value="Schnell") as call,
            patch.object(opentalk.subprocess, "run") as cli,
        ):
            (Path(folder) / "model").touch()
            for system in ("Darwin", "Linux", "Windows"):
                with patch.object(opentalk.platform, "system", return_value=system):
                    self.assertEqual(opentalk.transcribe_local(wav_bytes()), "Schnell")
            self.assertEqual(call.call_count, 3)
            cli.assert_not_called()

    def test_local_http_never_uses_system_proxy(self):
        with patch.object(opentalk.urllib.request, "build_opener") as opener:
            opentalk.PersistentWhisperServer()
        self.assertEqual(opener.call_args.args[0].proxies, {})

    def test_failure_is_cleaned_up_under_lock_and_has_retry_cooldown(self):
        server = opentalk.PersistentWhisperServer()
        cleaned = []

        def stop():
            cleaned.append(server.lock.locked())

        with (
            patch.object(server, "_transcribe", side_effect=RuntimeError("failed")) as infer,
            patch.object(server, "stop", side_effect=stop),
            patch.object(opentalk.time, "monotonic", return_value=100),
        ):
            for _ in range(2):
                with self.assertRaises(RuntimeError):
                    server.transcribe(b"wav")
            infer.assert_called_once()
            self.assertEqual(cleaned, [True])
        with (
            patch.object(server, "_transcribe", return_value="Erholt"),
            patch.object(opentalk.time, "monotonic", return_value=131),
        ):
            self.assertEqual(server.transcribe(b"wav"), "Erholt")

    def test_cold_metal_start_is_not_killed_after_ten_seconds(self):
        server = opentalk.PersistentWhisperServer()
        process = Mock()
        process.poll.return_value = None
        reservation = MagicMock()
        reservation.__enter__.return_value.getsockname.return_value = ("127.0.0.1", 1234)
        with (
            patch.object(opentalk.socket, "socket", return_value=reservation),
            patch.object(opentalk.socket, "create_connection", return_value=MagicMock()),
            patch.object(opentalk.subprocess, "Popen", return_value=process),
            patch.object(opentalk.time, "monotonic", side_effect=[0, 13]),
        ):
            server._start("server", Path("model.bin"), "de")
        self.assertIn("127.0.0.1:1234", server.url)
        process.terminate.assert_not_called()

    def test_idle_model_is_released_but_active_session_is_protected(self):
        server = opentalk.PersistentWhisperServer()
        process = Mock()
        process.poll.return_value = None
        server.process = process
        with patch.object(opentalk.time, "monotonic", return_value=1000):
            server.last_used = 0
            server.begin_session()
            server.last_used = 0
            self.assertFalse(server.release_if_idle())
            process.terminate.assert_not_called()
            server.end_session()
            self.assertFalse(server.release_if_idle())
            server.last_used = 699
            self.assertTrue(server.release_if_idle())
        process.terminate.assert_called_once()
        self.assertIsNone(server.process)

    def test_idle_unload_does_not_interrupt_running_inference(self):
        server = opentalk.PersistentWhisperServer()
        server.last_used = 0
        server.process = Mock()
        with server.lock:
            self.assertFalse(server.release_if_idle())
        server.process.terminate.assert_not_called()

    def test_model_warms_again_after_idle_unload(self):
        server = opentalk.PersistentWhisperServer()
        process = Mock()
        process.poll.return_value = None
        server.process = process
        server.last_used = 0
        with patch.object(opentalk.time, "monotonic", return_value=1000):
            self.assertTrue(server.release_if_idle())
        with (
            patch.object(opentalk, "whisper_server", return_value="server"),
            patch.object(opentalk, "model_path") as model,
            patch.object(opentalk.shutil, "which", return_value="/server"),
            patch.object(server, "_start") as start,
        ):
            model.return_value.is_file.return_value = True
            server.warm()
        start.assert_called_once()

    def test_malformed_transcription_responses_are_readable_errors(self):
        for payload in (b"not json", b"[]", b"{}", b'{"text": null}', b'{"text": 7}'):
            with self.subTest(payload=payload), self.assertRaisesRegex(RuntimeError, "Erkennung"):
                opentalk.response_transcript(io.BytesIO(payload))

    def test_remote_mode_does_not_load_local_model(self):
        with (
            patch.dict(os.environ, {"OPENTALK_SERVER_URL": "https://server.local"}),
            patch.object(opentalk.platform, "system", return_value="Darwin"),
            patch.object(opentalk.threading, "Thread") as thread,
        ):
            opentalk.warm_transcriber_async()
        thread.assert_not_called()

    def test_server_shutdown_reaps_process_and_is_idempotent(self):
        server = opentalk.PersistentWhisperServer()
        process = Mock()
        process.poll.return_value = None
        server.process = process
        server.shutdown()
        server.shutdown()
        process.terminate.assert_called_once()
        process.wait.assert_called_once()
        self.assertTrue(server.closed.is_set())
        self.assertIsNone(server.process)
        with patch.object(opentalk.subprocess, "Popen") as spawn:
            server.warm()
            with self.assertRaisesRegex(RuntimeError, "beendet"):
                server.transcribe(b"wav")
        spawn.assert_not_called()

    def test_multipart_wav_contains_fields_and_audio(self):
        body, boundary = opentalk._multipart_wav(b"wave-bytes", {"language": "de"})
        self.assertIn(f"--{boundary}".encode(), body)
        self.assertIn(b'name="language"\r\n\r\nde', body)
        self.assertIn(b'filename="audio.wav"', body)
        self.assertIn(b"wave-bytes", body)
        self.assertTrue(body.endswith(f"--{boundary}--\r\n".encode()))

    def test_persistent_server_reuses_loaded_model(self):
        server = opentalk.PersistentWhisperServer()
        process = Mock()
        process.poll.return_value = None
        server.process = process
        server.url = "http://127.0.0.1:1234/secret/inference"
        server.signature = ("whisper-server", "/model.bin", "de")
        response = Mock()
        response.__enter__ = Mock(
            return_value=io.BytesIO(json.dumps({"text": " Hallo [MUSIK] Welt "}).encode())
        )
        response.__exit__ = Mock(return_value=False)
        with (
            patch.object(opentalk, "whisper_server", return_value="whisper-server"),
            patch.object(opentalk, "model_path", return_value=Path("/model.bin")),
            patch.object(server.http, "open", return_value=response) as request,
        ):
            self.assertEqual(server.transcribe(b"wav"), "Hallo Welt")
        self.assertEqual(request.call_count, 1)
        process.terminate.assert_not_called()

    def test_macos_server_failure_falls_back_to_cli(self):
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / "model.bin"
            cli = Path(folder) / "whisper-cli"
            model.touch()
            cli.touch()

            def fake_cli(command, **_kwargs):
                Path(command[command.index("-of") + 1] + ".txt").write_text(
                    "Fallback funktioniert", encoding="utf-8"
                )
                return Mock(returncode=0, stderr="")

            with (
                patch.object(opentalk.platform, "system", return_value="Darwin"),
                patch.object(opentalk, "model_path", return_value=model),
                patch.object(opentalk, "whisper_cli", return_value=str(cli)),
                patch.object(opentalk, "whisper_server", return_value="server"),
                patch.object(
                    opentalk.LOCAL_WHISPER_SERVER,
                    "transcribe",
                    side_effect=RuntimeError("server failed"),
                ),
                patch.object(opentalk.LOCAL_WHISPER_SERVER, "stop") as stop,
                patch.object(opentalk.subprocess, "run", side_effect=fake_cli),
            ):
                self.assertEqual(opentalk.transcribe_local(wav_bytes()), "Fallback funktioniert")
        stop.assert_not_called()  # Cleanup belongs to the serialized server operation.

    def test_background_warmup_failure_is_safely_ignored(self):
        with (
            patch.object(opentalk.platform, "system", return_value="Darwin"),
            patch.object(opentalk, "whisper_server", return_value="server"),
            patch.object(
                opentalk.LOCAL_WHISPER_SERVER,
                "warm",
                side_effect=PermissionError("blocked"),
            ),
            patch.object(opentalk.LOCAL_WHISPER_SERVER, "stop") as stop,
            patch.object(opentalk.threading, "Thread") as thread,
        ):
            opentalk.warm_transcriber_async()
            thread.call_args.kwargs["target"]()
        stop.assert_not_called()

    def test_local_transcription_reports_missing_model_and_cli(self):
        with patch.object(opentalk, "model_path", return_value=Path("/missing/model.bin")):
            with self.assertRaisesRegex(RuntimeError, "Modell fehlt"):
                opentalk.transcribe_local(wav_bytes())

        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / "model.bin"
            model.touch()
            with (
                patch.object(opentalk, "model_path", return_value=model),
                patch.object(opentalk, "whisper_cli", return_value="missing-whisper"),
                patch.object(opentalk.shutil, "which", return_value=None),
            ):
                with self.assertRaisesRegex(RuntimeError, "whisper-cli fehlt"):
                    opentalk.transcribe_local(wav_bytes())

    def test_local_transcription_reports_timeout_and_cli_error(self):
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / "model.bin"
            cli = Path(folder) / "whisper-cli"
            model.touch()
            cli.touch()
            with (
                patch.object(opentalk, "model_path", return_value=model),
                patch.object(opentalk, "whisper_cli", return_value=str(cli)),
                patch.object(opentalk, "whisper_server", return_value=""),
                patch.object(
                    opentalk.subprocess,
                    "run",
                    side_effect=opentalk.subprocess.TimeoutExpired("whisper", 1),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "zu lange"):
                    opentalk.transcribe_local(wav_bytes())
            with (
                patch.object(opentalk, "model_path", return_value=model),
                patch.object(opentalk, "whisper_cli", return_value=str(cli)),
                patch.object(opentalk, "whisper_server", return_value=""),
                patch.object(
                    opentalk.subprocess, "run", return_value=Mock(returncode=2, stderr="kaputt")
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "kaputt"):
                    opentalk.transcribe_local(wav_bytes())

    def test_remote_transcription_validates_url_and_token(self):
        data = wav_bytes()
        with patch.dict(
            os.environ, {"OPENTALK_SERVER_URL": "server.local", "OPENTALK_TOKEN": "secret"}
        ):
            with self.assertRaisesRegex(RuntimeError, "http://"):
                opentalk.transcribe(data)
        with patch.dict(
            os.environ, {"OPENTALK_SERVER_URL": "https://server.local", "OPENTALK_TOKEN": ""}
        ):
            with self.assertRaisesRegex(RuntimeError, "TOKEN"):
                opentalk.transcribe(data)

    def test_remote_transcription_sends_auth_and_cleans_result(self):
        response = Mock()
        response.__enter__ = Mock(
            return_value=io.BytesIO(json.dumps({"text": "Hallo [MUSIK] Welt"}).encode())
        )
        response.__exit__ = Mock(return_value=False)
        with (
            patch.dict(
                os.environ,
                {"OPENTALK_SERVER_URL": "https://server.local/", "OPENTALK_TOKEN": "secret"},
            ),
            patch.object(opentalk.urllib.request, "urlopen", return_value=response) as request,
        ):
            self.assertEqual(opentalk.transcribe(wav_bytes()), "Hallo Welt")
        sent = request.call_args.args[0]
        self.assertEqual(sent.full_url, "https://server.local/transcribe")
        self.assertEqual(sent.get_header("Authorization"), "Bearer secret")

    def test_remote_http_error_becomes_readable_runtime_error(self):
        error = urllib.error.HTTPError("https://server", 503, "down", {}, None)
        with (
            patch.dict(
                os.environ,
                {"OPENTALK_SERVER_URL": "https://server.local", "OPENTALK_TOKEN": "secret"},
            ),
            patch.object(opentalk.urllib.request, "urlopen", side_effect=error),
        ):
            with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
                opentalk.transcribe(wav_bytes())

    def test_remote_connection_failure_becomes_readable_error(self):
        with (
            patch.dict(
                os.environ,
                {"OPENTALK_SERVER_URL": "https://server.local", "OPENTALK_TOKEN": "secret"},
            ),
            patch.object(opentalk.urllib.request, "urlopen", side_effect=urllib.error.URLError("no")),
        ):
            with self.assertRaisesRegex(RuntimeError, "nicht erreichbar"):
                opentalk.transcribe(wav_bytes())


if __name__ == "__main__":
    unittest.main()
