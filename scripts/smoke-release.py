"""Check packaged Python imports and native helpers without a model or microphone."""

from pathlib import Path
import platform
import subprocess


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "dist"
    system = platform.system()
    suffix = ".exe" if system == "Windows" else ""
    if system == "Darwin":
        root = root / "OpenTalk.app/Contents"
        helper = root / "MacOS/opentalk-model-setup"
        binaries = root / "Frameworks/bin"
    else:
        root = root / "OpenTalk"
        helper = root / ("opentalk-model-setup" + suffix)
        binaries = root / "_internal/bin"
    result = subprocess.run(
        [str(helper), "--download-model", "__invalid_smoke_test_model__"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    if result.returncode != 1 or "Unbekanntes Whisper-Modell" not in result.stderr:
        raise RuntimeError(f"Packaged Python/helper startup failed: {result.stdout}\n{result.stderr}")
    for name in ("whisper-cli", "whisper-server"):
        subprocess.run(
            [str(binaries / (name + suffix)), "--help"], capture_output=True,
            check=True, timeout=30,
        )
    if system in ("Darwin", "Windows"):
        subprocess.run(
            [str(binaries / ("ffmpeg" + suffix)), "-version"], capture_output=True,
            check=True, timeout=30,
        )
    print("Packaged Python setup helper, whisper-cli, whisper-server and recorder: OK")


if __name__ == "__main__":
    main()
