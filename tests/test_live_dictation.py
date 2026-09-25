import io
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import wave

import live_dictation as live


class LiveDictationTests(unittest.TestCase):
    def test_macos_uses_lower_latency_chunks_with_bounded_override(self):
        with (
            patch.object(live.platform, "system", return_value="Darwin"),
            patch.object(live.opentalk, "config", side_effect=lambda _name, default: default),
        ):
            self.assertEqual(live.chunk_bytes(), 3 * live.BYTES_PER_SECOND)
        with patch.object(live.opentalk, "config", return_value="0.1"):
            self.assertEqual(live.chunk_bytes(), live.BYTES_PER_SECOND)
        with patch.object(live.opentalk, "config", return_value="99"):
            self.assertEqual(live.chunk_bytes(), 10 * live.BYTES_PER_SECOND)
        for invalid in ("nan", "inf", "-inf", "kaputt"):
            with (
                self.subTest(value=invalid),
                patch.object(live.platform, "system", return_value="Darwin"),
                patch.object(live.opentalk, "config", return_value=invalid),
            ):
                self.assertEqual(live.chunk_bytes(), 3 * live.BYTES_PER_SECOND)

    def test_pcm_to_wav_has_expected_audio_format(self):
        data = b"\x01\x02" * 1600
        with wave.open(io.BytesIO(live.pcm_to_wav(data)), "rb") as audio:
            self.assertEqual(audio.getnchannels(), 1)
            self.assertEqual(audio.getsampwidth(), 2)
            self.assertEqual(audio.getframerate(), 16_000)
            self.assertEqual(audio.readframes(1600), data)

    def test_start_uses_platform_recorder_command(self):
        recorder = Mock()
        recorder.poll.return_value = None
        engine = live.LiveDictation(Mock(), Mock(), Mock(), source="selected-mic")
        with (
            patch.object(
                live.opentalk, "recorder_command", return_value=["native-recorder", "audio.raw"]
            ) as command,
            patch.object(live.subprocess, "Popen", return_value=recorder),
            patch.object(live.time, "sleep"),
            patch.object(live.threading, "Thread") as thread,
            patch.object(live.threading, "Timer"),
        ):
            engine.start()
        command.assert_called_once()
        self.assertEqual(command.call_args.args[1], "selected-mic")
        self.assertTrue(command.call_args.kwargs["raw"])
        thread.return_value.start.assert_called_once()
        engine.temp.cleanup()
        engine.temp = None

    def test_processes_full_chunks_and_short_final_tail_once(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "audio.raw"
            path.write_bytes(b"\x00\x10" * (16_000 * 9))
            recorder = Mock()
            recorder.poll.return_value = 0
            chunks = []
            errors = []
            finished = []
            engine = live.LiveDictation(chunks.append, errors.append, lambda: finished.append(True))
            engine.recorder = recorder
            engine.audio_path = path
            engine.stop_requested.set()
            with (
                patch.object(live.platform, "system", return_value="Linux"),
                patch.object(
                    live.opentalk, "transcribe", side_effect=["eins", "zwei"]
                ) as transcribe,
            ):
                engine._run()
            self.assertEqual(chunks, ["eins", "zwei"])
            self.assertEqual(errors, [])
            self.assertEqual(finished, [True])
            durations = []
            for call in transcribe.call_args_list:
                with wave.open(io.BytesIO(call.args[0]), "rb") as audio:
                    durations.append(audio.getnframes() / audio.getframerate())
            self.assertEqual(durations, [6, 3])

    def test_meter_keeps_up_while_recognition_is_blocked(self):
        recognizing, release, metered = threading.Event(), threading.Event(), threading.Event()

        def transcribe(_wav):
            recognizing.set()
            if not release.wait(3):
                raise RuntimeError("test timed out")
            return "Text"

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "audio.raw"
            path.write_bytes(b"\x00\x10" * (16_000 * 7))
            recorder = Mock()
            recorder.poll.return_value = None
            engine = live.LiveDictation(Mock(), Mock(), Mock(), on_level=lambda _level: metered.set())
            engine.recorder, engine.audio_path = recorder, path
            with patch.object(live.opentalk, "transcribe", side_effect=transcribe):
                worker = threading.Thread(target=engine._run)
                worker.start()
                try:
                    self.assertTrue(recognizing.wait(2))
                    threading.Event().wait(0.12)
                    metered.clear()
                    # Supply more microphone frames while the first inference is
                    # deliberately stalled. Metering must not depend on it.
                    with path.open("ab") as stream:
                        stream.write(b"\x00\x10" * 16_000)
                    self.assertTrue(metered.wait(1))
                    self.assertFalse(release.is_set())
                finally:
                    engine.stop_requested.set()
                    recorder.poll.return_value = 0
                    release.set()
                    worker.join(3)
                self.assertFalse(worker.is_alive())
                engine.on_error.assert_not_called()
                engine.on_finished.assert_called_once()

    def test_short_final_speech_is_padded_not_dropped(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "audio.raw"
            pcm = b"\x00\x10" * 800
            path.write_bytes(pcm)
            engine = live.LiveDictation(Mock(), Mock(), Mock())
            engine.recorder = Mock()
            engine.recorder.poll.return_value = 0
            engine.audio_path = path
            engine.stop_requested.set()
            with patch.object(live.opentalk, "transcribe", return_value="Ja") as transcribe:
                engine._run()
            with wave.open(io.BytesIO(transcribe.call_args.args[0])) as wav:
                self.assertEqual(wav.readframes(3200), pcm.ljust(live.MIN_BYTES, b"\0"))

    def test_digital_silence_never_invokes_whisper(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "audio.raw"
            path.write_bytes(b"\0" * live.BYTES_PER_SECOND * 5)
            engine = live.LiveDictation(Mock(), Mock(), Mock())
            engine.recorder = Mock()
            engine.recorder.poll.return_value = 0
            engine.audio_path = path
            engine.stop_requested.set()
            with patch.object(live.opentalk, "transcribe") as transcribe:
                engine._run()
            transcribe.assert_not_called()

    def test_no_audio_reports_actionable_permission_hint(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = live.LiveDictation(Mock(), Mock(), Mock())
            engine.recorder = Mock()
            engine.recorder.poll.return_value = None
            engine.audio_path = Path(folder) / "missing.raw"
            with (
                patch.object(live.time, "monotonic", side_effect=[0, 9]),
                patch.object(live.opentalk, "stop_recorder"),
            ):
                engine._run()
            self.assertIn("Keine Audiodaten", engine.on_error.call_args.args[0])
            self.assertIn("prüfen", engine.on_error.call_args.args[0])

    def test_start_rejects_parallel_recording(self):
        engine = live.LiveDictation(Mock(), Mock(), Mock())
        engine.recorder = Mock()
        with self.assertRaisesRegex(RuntimeError, "vorherige Aufnahme"):
            engine.start()

    def test_start_cleans_up_when_recorder_cannot_launch(self):
        engine = live.LiveDictation(Mock(), Mock(), Mock())
        with (
            patch.object(live.opentalk, "recorder_command", return_value=["missing"]),
            patch.object(live.subprocess, "Popen", side_effect=OSError),
        ):
            with self.assertRaisesRegex(RuntimeError, "nicht gestartet"):
                engine.start()
        self.assertIsNone(engine.recorder)
        self.assertIsNone(engine.audio_path)
        self.assertIsNone(engine.temp)

    def test_start_reports_recorder_that_exits_immediately(self):
        recorder = Mock()
        recorder.poll.return_value = 1
        engine = live.LiveDictation(Mock(), Mock(), Mock())
        with (
            patch.object(live.opentalk, "recorder_command", return_value=["recorder"]),
            patch.object(live.subprocess, "Popen", return_value=recorder),
            patch.object(live.time, "sleep"),
        ):
            with self.assertRaisesRegex(RuntimeError, "Quelle prüfen"):
                engine.start()
        self.assertIsNone(engine.recorder)
        self.assertIsNone(engine.temp)
        recorder.stdin.close.assert_called_once()

    def test_command_failure_cleans_temporary_recording(self):
        engine = live.LiveDictation(Mock(), Mock(), Mock())
        with patch.object(live.opentalk, "recorder_command", side_effect=RuntimeError("Quelle")):
            with self.assertRaisesRegex(RuntimeError, "Quelle"):
                engine.start()
        self.assertIsNone(engine.temp)
        self.assertIsNone(engine.audio_path)

    def test_stop_is_idempotent_and_cancels_timeout(self):
        recorder = Mock()
        recorder.poll.return_value = None
        timer = Mock()
        engine = live.LiveDictation(Mock(), Mock(), Mock())
        engine.recorder = recorder
        engine.timer = timer
        with (
            patch.object(live.opentalk, "stop_recorder") as stop,
            patch.object(live.threading, "Timer") as watchdog,
        ):
            engine.stop()
            engine.stop()
        timer.cancel.assert_called_once()
        stop.assert_called_once_with(recorder)
        self.assertTrue(engine.stop_requested.is_set())
        watchdog.assert_called_once()
        # The watchdog does not depend on the blocked transcription worker.
        watchdog.call_args.args[1](*watchdog.call_args.kwargs["args"])
        recorder.kill.assert_called_once()

    def test_unexpected_recorder_exit_reports_error_and_finishes(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder = Mock()
            recorder.poll.return_value = 1
            errors = []
            finished = []
            engine = live.LiveDictation(Mock(), errors.append, lambda: finished.append(True))
            engine.recorder = recorder
            engine.audio_path = Path(folder) / "audio.raw"
            engine.temp = None
            engine.timer = Mock()
            engine._run()
        self.assertEqual(len(errors), 1)
        self.assertIn("Mikrofonaufnahme wurde unerwartet beendet.", errors[0])
        self.assertEqual(finished, [True])
        engine.timer.cancel.assert_called_once()
        recorder.stdin.close.assert_called_once()

    def test_cancelled_run_suppresses_callbacks_and_kills_stuck_recorder(self):
        recorder = Mock()
        recorder.poll.return_value = None
        recorder.wait.side_effect = [subprocess.TimeoutExpired("recorder", 3), 0]
        engine = live.LiveDictation(Mock(), Mock(), Mock())
        engine.recorder = recorder
        engine.audio_path = Path("unused.raw")
        engine.temp = None
        engine.cancelled.set()
        with patch.object(live.opentalk, "stop_recorder"):
            engine._run()
        recorder.kill.assert_called_once()
        engine.on_error.assert_not_called()
        engine.on_finished.assert_not_called()


if __name__ == "__main__":
    unittest.main()
