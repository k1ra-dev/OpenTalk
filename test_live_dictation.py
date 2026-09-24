import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import wave

import live_dictation as live


class LiveDictationTests(unittest.TestCase):
    def test_start_uses_platform_recorder_command(self):
        recorder = Mock()
        recorder.poll.return_value = None
        engine = live.LiveDictation(Mock(), Mock(), Mock(), source="selected-mic")
        with patch.object(live.opentalk, "recorder_command",
                          return_value=["native-recorder", "audio.raw"]) as command, \
             patch.object(live.subprocess, "Popen", return_value=recorder), \
             patch.object(live.time, "sleep"), patch.object(live.threading, "Thread") as thread, \
             patch.object(live.threading, "Timer"):
            engine.start()
        command.assert_called_once()
        self.assertEqual(command.call_args.args[1], "selected-mic")
        self.assertTrue(command.call_args.kwargs["raw"])
        thread.return_value.start.assert_called_once()

    def test_processes_full_chunks_and_short_final_tail_once(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "audio.raw"
            path.write_bytes(b"\0\0" * (16_000 * 9))
            recorder = Mock()
            recorder.poll.return_value = 0
            chunks = []
            errors = []
            finished = []
            engine = live.LiveDictation(chunks.append, errors.append,
                                        lambda: finished.append(True))
            engine.recorder = recorder
            engine.audio_path = path
            engine.stop_requested.set()
            with patch.object(live.opentalk, "transcribe", side_effect=["eins", "zwei", "drei"]) as transcribe:
                engine._run()
            self.assertEqual(chunks, ["eins", "zwei", "drei"])
            self.assertEqual(errors, [])
            self.assertEqual(finished, [True])
            durations = []
            for call in transcribe.call_args_list:
                with wave.open(io.BytesIO(call.args[0]), "rb") as audio:
                    durations.append(audio.getnframes() / audio.getframerate())
            self.assertEqual(durations, [4, 4, 1])


if __name__ == "__main__":
    unittest.main()
