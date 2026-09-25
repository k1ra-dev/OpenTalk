import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import benchmark
import diagnostics
import opentalk
from tests.test_core import wav_bytes


class VocabularyTests(unittest.TestCase):
    def test_normalization_limits_and_empty_dictionary(self):
        self.assertEqual(opentalk.normalize_vocabulary(" Kira, OpenTalk\nKira\n  Pipe Wire "),
                         ["Kira", "OpenTalk", "Pipe Wire"])
        self.assertEqual(opentalk.normalize_vocabulary(" \n, "), [])
        for text in ("a" * 401, ",".join(str(n) for n in range(33))):
            with self.assertRaises(ValueError):
                opentalk.normalize_vocabulary(text)

    def test_malformed_settings_do_not_break_recognition(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            with patch.object(opentalk, "settings_path", return_value=path):
                for contents in ('null', '[]', '{"vocabulary": "wrong"}', '{"vocabulary": [4]}'):
                    path.write_text(contents)
                    self.assertEqual(opentalk.vocabulary_prompt(), "")
                path.write_text(json.dumps({"vocabulary": ["Kira", "OpenTalk"]}))
                self.assertEqual(opentalk.vocabulary_prompt(), "Kira, OpenTalk")

    def test_cli_receives_optional_prompt_as_one_argument(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(opentalk, "model_path", return_value=Path(folder) / "model"),
            patch.object(opentalk, "whisper_server", return_value=""),
            patch.object(opentalk.shutil, "which", return_value="cli"),
            patch.object(opentalk, "vocabulary_prompt", return_value="Kira, OpenTalk"),
            patch.object(opentalk.subprocess, "run", return_value=Mock(returncode=0)) as run,
        ):
            (Path(folder) / "model").touch()
            opentalk.transcribe_local(wav_bytes())
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("--prompt") + 1], "Kira, OpenTalk")

    def test_server_clears_prompt_without_reloading_model(self):
        server = opentalk.PersistentWhisperServer()
        server.process = Mock()
        server.process.poll.return_value = None
        server.signature = ("server", "model", "de")
        server.url = "http://127.0.0.1:1/test"
        with (
            patch.object(opentalk, "whisper_server", return_value="server"),
            patch.object(opentalk, "model_path", return_value=Path("model")),
            patch.object(opentalk, "config", side_effect=lambda _name, default="": default),
            patch.object(opentalk, "vocabulary_prompt", side_effect=["Kira", ""]),
            patch.object(server.http, "open"),
            patch.object(opentalk, "response_transcript", return_value="Text"),
            patch.object(opentalk, "_multipart_wav", return_value=(b"audio", "boundary")) as multipart,
            patch.object(server, "_start") as start,
        ):
            server.transcribe(b"wav")
            server.transcribe(b"wav")
            self.assertEqual([call.args[1]["prompt"] for call in multipart.call_args_list], ["Kira", ""])
            start.assert_not_called()


class DiagnosticTests(unittest.TestCase):
    def test_missing_dependencies_are_reported_without_recording_or_network(self):
        with (
            patch.object(diagnostics, "scan_hardware", return_value=diagnostics.Hardware("Linux", "x86_64", "CPU", 4, 8)),
            patch.object(opentalk, "recorder_dependency", return_value="/missing/recorder"),
            patch.object(diagnostics.shutil, "which", return_value=None),
            patch.object(opentalk, "model_path", return_value=Path("/missing/model")),
            patch.object(opentalk, "whisper_cli", return_value=""),
            patch.object(opentalk, "whisper_server", return_value=""),
            patch.object(opentalk, "config", side_effect=lambda _name, default="": default),
            patch.object(opentalk.subprocess, "Popen") as spawn,
            patch.object(opentalk.urllib.request, "urlopen") as network,
        ):
            result = "\n".join(diagnostics.check_system())
            self.assertIn("Aufnahmeprogramm fehlt", result)
            self.assertIn("Modell fehlt", result)
            self.assertIn("Nicht geprüft", result)
            spawn.assert_not_called()
            network.assert_not_called()

    def test_remote_token_never_appears_in_report(self):
        values = {"SERVER_URL": "https://private-host", "TOKEN": "my-secret"}
        with (
            patch.object(opentalk, "config", side_effect=lambda name, default="": values.get(name, default)),
            patch.object(diagnostics.shutil, "which", return_value="recorder"),
            patch.object(diagnostics.audio_sources, "list_sources", return_value=[]),
        ):
            result = "\n".join(diagnostics.check_system())
            self.assertIn("Token fehlt oder", result)
            self.assertNotIn("my-secret", result)
            self.assertNotIn("private-host", result)


class BenchmarkTests(unittest.TestCase):
    def test_warmup_is_not_scored(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "sample.wav").write_bytes(wav_bytes())
            manifest = root / "cases.json"
            manifest.write_text(json.dumps([{"audio": "sample.wav", "text": "Hallo"}]))
            with patch.object(opentalk, "transcribe_local", side_effect=["falsch", "Hallo"]) as infer:
                report = benchmark.measure(manifest, warmup=True)
            self.assertEqual(infer.call_count, 2)
            self.assertEqual(report["wer"], 0)
            self.assertTrue(report["warmup"])
            self.assertEqual(len(report["cases"]), 1)

    def test_threads_are_temporary_and_validated(self):
        with (
            patch.dict(benchmark.os.environ, {"OPENTALK_WHISPER_THREADS": "3"}),
            patch("sys.argv", ["benchmark.py", "cases.json", "--threads", "8", "--warmup"]),
            patch.object(benchmark, "measure", side_effect=lambda *a, **kw: {
                "threads": opentalk.config("WHISPER_THREADS"), "warmup": kw["warmup"]}) as measure,
            patch.object(opentalk.LOCAL_WHISPER_SERVER, "shutdown"),
            patch("builtins.print") as output,
        ):
            self.assertEqual(benchmark.main(), 0)
            self.assertEqual(json.loads(output.call_args.args[0])["threads"], "8")
            self.assertEqual(opentalk.config("WHISPER_THREADS"), "3")
            measure.reset_mock()
            with patch("sys.argv", ["benchmark.py", "cases.json", "--threads", "0"]):
                with self.assertRaises(SystemExit):
                    benchmark.main()
            measure.assert_not_called()
            self.assertEqual(opentalk.config("WHISPER_THREADS"), "3")

    def test_invalid_baseline_cannot_silently_pass_regression_check(self):
        report = {"schema": 1, "corpus": "same", "wer": 0.1, "rtf": 0.2}
        for baseline in ([], {**report, "wer": float("nan")}, {**report, "rtf": -1}):
            with self.assertRaises(ValueError):
                benchmark.regressions(report, baseline, 0.02, 1.2)

    def test_word_errors_count_insertions_deletions_substitutions(self):
        for reference, actual, expected in (
            ("Hallo, WELT!", "hallo welt", (0, 2)),
            ("eins zwei drei", "eins vier", (2, 3)),
            ("eins", "eins zwei drei", (2, 1)),
            ("eins zwei", "", (2, 2)),
        ):
            self.assertEqual(benchmark.word_errors(reference, actual), expected)

    def test_corpus_weighting_privacy_and_local_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "sample.wav").write_bytes(wav_bytes())
            manifest = root / "cases.json"
            manifest.write_text(json.dumps([
                {"audio": "sample.wav", "text": "eins"},
                {"audio": "sample.wav", "text": "zwei drei vier"},
            ]))
            with (
                patch.object(opentalk, "transcribe_local", side_effect=["falsch", "zwei drei vier"]),
                patch.object(opentalk, "transcribe") as remote,
            ):
                report = benchmark.measure(manifest)
            self.assertEqual(report["wer"], 0.25)
            self.assertNotIn("falsch", json.dumps(report))
            remote.assert_not_called()
            baseline = {**report, "wer": 0, "rtf": report["rtf"] / 2}
            self.assertEqual(len(benchmark.regressions(report, baseline, 0.02, 1.2)), 2)
            with self.assertRaises(ValueError):
                benchmark.regressions(report, {**baseline, "corpus": "different"}, 0.02, 1.2)

    def test_invalid_corpus_fails_before_inference(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder) / "cases.json"
            with patch.object(opentalk, "transcribe_local") as infer:
                for contents in ([], {}, [{"audio": "missing.wav", "text": ""}], [None]):
                    manifest.write_text(json.dumps(contents))
                    with self.assertRaises(ValueError):
                        benchmark.measure(manifest)
                infer.assert_not_called()
