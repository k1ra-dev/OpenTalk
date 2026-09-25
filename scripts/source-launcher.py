"""Finder bootstrap kept inside the app, outside a possibly protected checkout."""

from pathlib import Path
import os
import runpy
import sys


def launch(project: Path, configured: bool = False) -> None:
    entry = project / "opentalk_gui.py"
    # Check access before executing another shell script from Desktop/Documents.
    # Otherwise macOS can reject that script before Python can show any error.
    with entry.open("rb"):
        pass
    configuration = project / "config.local.sh"
    if not configured and configuration.is_file():
        # Keep the user's shell configuration semantics. All paths are positional
        # arguments, not interpolated shell code (spaces/quotes are safe).
        os.execv("/bin/sh", [
            "/bin/sh", "-c", 'set -e; . "$1"; exec "$2" "$3" "$4" --configured',
            "opentalk-source", str(configuration), sys.executable,
            str(Path(__file__).resolve()), str(project),
        ])
    sys.path.insert(0, str(project))
    sys.argv = [str(entry)]
    runpy.run_path(str(entry), run_name="__main__")


def show_start_error(project: Path, error: Exception) -> None:
    if isinstance(error, PermissionError):
        message = (
            "macOS verweigert OpenTalk den Zugriff auf den Quellcode:\n\n"
            f"{project}\n\n"
            "Unter Systemeinstellungen → Datenschutz & Sicherheit → Dateien und Ordner "
            "den Zugriff auf den betreffenden Ordner für OpenTalk bzw. Python erlauben "
            "und die App neu starten.\n\n"
            "Alternativ den Checkout außerhalb von Schreibtisch, Dokumente und Downloads "
            "ablegen (z. B. ~/Developer/OpenTalk) und install-macos.sh --dev erneut ausführen."
        )
    else:
        message = (
            f"OpenTalk konnte nicht aus {project} gestartet werden:\n\n{error}\n\n"
            "Falls der Projektordner verschoben wurde, install-macos.sh --dev erneut ausführen."
        )
    print(message, file=sys.stderr, flush=True)
    from PyQt6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance() or QApplication([])
    app.setApplicationName("OpenTalk")
    QMessageBox.critical(None, "OpenTalk – Start nicht möglich", message)


def main(arguments: list[str]) -> int:
    if not arguments or len(arguments) > 2 or (
        len(arguments) == 2 and arguments[1] != "--configured"
    ):
        return 2
    project = Path(arguments[0]).absolute()
    try:
        launch(project, configured=len(arguments) == 2)
        return 0
    except Exception as exc:
        show_start_error(project, exc)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
