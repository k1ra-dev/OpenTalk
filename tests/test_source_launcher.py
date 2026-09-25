import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/source-launcher.py"
SPEC = importlib.util.spec_from_file_location("source_launcher", SCRIPT)
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class SourceLauncherTests(unittest.TestCase):
    @unittest.skipIf(sys.platform == "win32", "macOS/POSIX bootstrap")
    def test_latest_checkout_code_and_configuration_are_used(self):
        with tempfile.TemporaryDirectory(prefix="opentalk ' source ") as folder:
            project = Path(folder)
            configuration = project / "config.local.sh"
            configuration.write_text('export OPENTALK_LAUNCH_TEST="configured"\n')
            entry = project / "opentalk_gui.py"
            for revision in ("first", "edited"):
                entry.write_text(
                    "import json, os; "
                    f"print(json.dumps([{revision!r}, os.getenv('OPENTALK_LAUNCH_TEST')]))\n"
                )
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), str(project)], cwd="/",
                    env={**os.environ, "OPENTALK_LAUNCH_TEST": "not configured"},
                    capture_output=True, text=True, check=True, timeout=10,
                )
                self.assertEqual(json.loads(result.stdout), [revision, "configured"])

    def test_permission_error_is_shown_instead_of_silent_exit(self):
        with (
            patch.object(launcher, "launch", side_effect=PermissionError("denied")),
            patch.object(launcher, "show_start_error") as show,
        ):
            self.assertEqual(launcher.main(["/protected/OpenTalk"]), 1)
            self.assertIsInstance(show.call_args.args[1], PermissionError)

    def test_moved_checkout_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(launcher, "show_start_error") as show:
                self.assertEqual(launcher.main([folder]), 1)
                self.assertIsInstance(show.call_args.args[1], FileNotFoundError)

    def test_invalid_arguments_do_not_start_application(self):
        with patch.object(launcher, "launch") as launch:
            for arguments in ([], ["/path", "--unknown"], ["/path", "a", "b"]):
                self.assertEqual(launcher.main(arguments), 2)
            launch.assert_not_called()
