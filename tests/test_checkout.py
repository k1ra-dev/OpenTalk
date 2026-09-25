"""Launchers must work from a clean checkout, including paths containing spaces."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CheckoutTests(unittest.TestCase):
    @unittest.skipIf(sys.platform == "win32", "POSIX launchers")
    def test_launchers_use_checkout_venv_and_local_configuration(self):
        with tempfile.TemporaryDirectory(prefix="opentalk checkout ") as folder:
            project = Path(folder)
            scripts = project / "scripts"
            scripts.mkdir()
            for name in ("gui.sh", "python.sh", "setup-model.sh", "download-model.sh", "start.sh"):
                shutil.copy2(ROOT / "scripts" / name, scripts / name)
            venv_bin = project / ".venv/bin"
            venv_bin.mkdir(parents=True)
            (venv_bin / "python").symlink_to(sys.executable)
            (project / "config.local.sh").write_text('export OPENTALK_TEST_CONFIG="geladen"\n')
            probe = (
                "import json, os, sys; "
                "print(json.dumps([sys.argv[1:], os.getenv('OPENTALK_TEST_CONFIG')]))\n"
            )
            for name in ("opentalk_gui.py", "model_setup.py", "opentalk.py"):
                (project / name).write_text(probe)
            environment = os.environ.copy()
            environment.pop("OPENTALK_PYTHON", None)
            for name, arguments, expected in (
                ("gui.sh", [], []),
                ("setup-model.sh", [], ["--setup-engine"]),
                ("download-model.sh", ["base"], ["--download-model", "base"]),
                ("start.sh", [], ["toggle"]),
            ):
                with self.subTest(script=name):
                    result = subprocess.run(
                        ["sh", str(scripts / name), *arguments], cwd="/", env=environment,
                        capture_output=True, text=True, check=True, timeout=10,
                    )
                    self.assertEqual(json.loads(result.stdout), [expected, "geladen"])

    @unittest.skipIf(sys.platform == "win32", "POSIX shell syntax")
    def test_all_shell_scripts_parse(self):
        for script in (ROOT / "scripts").glob("*.sh"):
            with self.subTest(script=script.name):
                subprocess.run(["sh", "-n", str(script)], check=True, timeout=5)

    @unittest.skipUnless(sys.platform == "win32", "Native Windows PowerShell parser")
    def test_all_powershell_scripts_parse(self):
        for script in [*(ROOT / "scripts").glob("*.ps1"), ROOT / "config.example.ps1"]:
            with self.subTest(script=script.name):
                command = (
                    "$errors = $null; $tokens = $null; "
                    "[System.Management.Automation.Language.Parser]::ParseFile("
                    "$env:OPENTALK_PARSE_FILE, [ref]$tokens, [ref]$errors) | Out-Null; "
                    "if ($errors) { $errors; exit 1 }"
                )
                subprocess.run(
                    ["powershell.exe", "-NoProfile", "-Command", command],
                    env={**os.environ, "OPENTALK_PARSE_FILE": str(script)}, check=True, timeout=20,
                )

    def test_python_files_import_without_user_settings_or_built_artifacts(self):
        with tempfile.TemporaryDirectory(prefix="opentalk clean ") as folder:
            project = Path(folder)
            for source in ROOT.glob("*.py"):
                shutil.copy2(source, project / source.name)
            environment = {
                key: value for key, value in os.environ.items()
                if not key.startswith("OPENTALK_") and key != "PYTHONPATH"
            }
            environment.update({
                "XDG_DATA_HOME": str(project / "empty-data"),
                "XDG_CONFIG_HOME": str(project / "empty-config"),
                "QT_QPA_PLATFORM": "offscreen",
            })
            subprocess.run(
                [sys.executable, "-c",
                 "import opentalk, opentalk_gui, model_setup; "
                 "assert not opentalk.model_available('small'); "
                 "assert opentalk_gui.read_settings() == {}; "
                 "assert opentalk_gui.setup_problem() is not None"],
                cwd=project, env=environment, check=True, timeout=20,
            )


if __name__ == "__main__":
    unittest.main()
