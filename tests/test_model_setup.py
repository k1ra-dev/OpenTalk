import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import model_setup


class DownloadResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class ModelSetupTests(unittest.TestCase):
    def test_source_setup_keeps_existing_models_and_builds_both_helpers(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(model_setup.opentalk, "local_data_dir", return_value=Path(folder)),
            patch.object(model_setup.opentalk, "bundled_executable", return_value=None),
            patch.object(model_setup.platform, "system", return_value="Windows"),
            patch.object(model_setup.shutil, "which", return_value="tool"),
            patch.object(model_setup.subprocess, "run") as run,
        ):
            model = Path(folder) / "whisper.cpp/models/ggml-small.bin"
            model.parent.mkdir(parents=True)
            model.write_bytes(b"keep existing download")
            model_setup.setup_engine()
            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual(commands[0][-1], str(Path(folder) / "whisper-src"))
            self.assertIn(model_setup.WHISPER_VERSION, commands[0])
            self.assertIn("whisper-cli", commands[2])
            self.assertIn("whisper-server", commands[2])
            self.assertIn("Release", commands[2])
            self.assertEqual(model.read_bytes(), b"keep existing download")

    def test_source_setup_reuses_legacy_checkout_without_resetting_it(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(model_setup.opentalk, "local_data_dir", return_value=Path(folder)),
            patch.object(model_setup.opentalk, "bundled_executable", return_value=None),
            patch.object(model_setup.shutil, "which", return_value="tool"),
            patch.object(model_setup.subprocess, "run") as run,
        ):
            source = Path(folder) / "whisper.cpp"
            source.mkdir()
            (source / "CMakeLists.txt").touch()
            model_setup.setup_engine()
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args_list[0].args[0][2], str(source))

    def test_source_setup_reports_missing_build_tools(self):
        with (
            patch.object(model_setup.opentalk, "bundled_executable", return_value=None),
            patch.object(model_setup.shutil, "which", return_value=None),
            patch.object(model_setup.subprocess, "run") as run,
        ):
            with self.assertRaisesRegex(RuntimeError, "git fehlt"):
                model_setup.setup_engine()
            run.assert_not_called()

    def test_source_setup_stops_before_downloads_when_build_fails(self):
        with (
            patch.object(model_setup, "setup_engine", side_effect=RuntimeError("build failed")),
            patch.object(model_setup, "setup") as setup,
        ):
            self.assertEqual(model_setup.main(["--setup-engine"]), 1)
            setup.assert_not_called()

    def test_download_does_not_touch_another_partial_file(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "model.bin"
            other_download = destination.with_name("model.bin.download")
            other_download.write_bytes(b"other download in progress")
            with patch.object(model_setup.urllib.request, "urlopen", side_effect=OSError("offline")):
                with self.assertRaises(OSError):
                    model_setup.download("https://example.invalid/model", destination, 100)
            self.assertEqual(other_download.read_bytes(), b"other download in progress")
            self.assertEqual(list(Path(folder).iterdir()), [other_download])

    def test_download_is_atomic_and_checks_digest(self):
        payload = b"valid model bytes"
        digest = hashlib.sha1(payload).hexdigest()
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(
                model_setup.urllib.request, "urlopen", return_value=DownloadResponse(payload)
            ),
        ):
            destination = Path(folder) / "models/model.bin"
            model_setup.download("https://example.invalid/model", destination, len(payload), digest)
            self.assertEqual(destination.read_bytes(), payload)
            self.assertFalse(destination.with_name("model.bin.download").exists())
            self.assertEqual(list(destination.parent.iterdir()), [destination])

    def test_failed_download_removes_partial_file(self):
        payload = b"short"
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(
                model_setup.urllib.request, "urlopen", return_value=DownloadResponse(payload)
            ),
        ):
            destination = Path(folder) / "model.bin"
            with self.assertRaisesRegex(RuntimeError, "unvollständig"):
                model_setup.download("https://example.invalid/model", destination, 100)
            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_name("model.bin.download").exists())
            self.assertEqual(list(destination.parent.iterdir()), [])

    def test_checksum_mismatch_does_not_replace_existing_model(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(
                model_setup.urllib.request,
                "urlopen",
                return_value=DownloadResponse(b"new corrupt bytes"),
            ),
        ):
            destination = Path(folder) / "model.bin"
            destination.write_bytes(b"existing model")
            with self.assertRaisesRegex(RuntimeError, "Prüfsumme"):
                model_setup.download(
                    "https://example.invalid/model",
                    destination,
                    1,
                    hashlib.sha1(b"expected").hexdigest(),
                )
            self.assertEqual(destination.read_bytes(), b"existing model")

    def test_download_model_validates_name_and_skips_installed_model(self):
        with self.assertRaisesRegex(RuntimeError, "Unbekanntes"):
            model_setup.download_model("not-a-model")
        with (
            patch.object(model_setup.opentalk, "model_file", return_value=Path("model.bin")),
            patch.object(model_setup.opentalk, "model_available", return_value=True),
            patch.object(model_setup, "download") as download,
        ):
            model_setup.download_model("small")
        download.assert_not_called()

    def test_main_dispatches_commands_and_returns_errors(self):
        with patch.object(model_setup, "setup") as setup:
            self.assertEqual(model_setup.main(["--setup-models"]), 0)
            setup.assert_called_once()
        with patch.object(model_setup, "download_model") as download:
            self.assertEqual(model_setup.main(["--download-model", "base"]), 0)
            download.assert_called_once_with("base")
        self.assertEqual(model_setup.main([]), 2)
        with patch.object(model_setup, "setup", side_effect=RuntimeError("kaputt")):
            self.assertEqual(model_setup.main(["--setup-models"]), 1)


if __name__ == "__main__":
    unittest.main()
