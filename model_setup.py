"""Cross-platform model downloads used by packaged OpenTalk applications."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request

import opentalk

WHISPER_VERSION = "v1.9.4"

MODEL_SHA1 = {
    "tiny": "bd577a113a864445d4c299885e0cb97d4ba92b5f",
    "base": "465707469ff3a37a2b9b8d8f89f2f99de7299dac",
    "small": "55356645c2b361a969dfd0ef2c5a50d530afd8d5",
    "medium": "fd9727b6e1217c2f614f9b698455c4ffd82463b4",
    "large-v3": "ad82bf6a9043ceed055076d0fd39f5f186ff8062",
}


def download(url: str, destination: Path, minimum_size: int, sha1: str = "") -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    # A GUI download and manual setup can overlap. Each owns its partial file;
    # failure in one must never truncate or delete the other's progress.
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=destination.name + ".", suffix=".download", dir=destination.parent
    )
    temporary = Path(temporary_name)
    digest = hashlib.sha1()
    total = 0
    try:
        with os.fdopen(descriptor, "wb") as output, urllib.request.urlopen(url, timeout=60) as response:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
                total += len(chunk)
                if total % (25 * 1024 * 1024) < len(chunk):
                    print(f"{total // (1024 * 1024)} MiB geladen …", flush=True)
        if total < minimum_size:
            raise RuntimeError("Download ist unvollständig.")
        if sha1 and digest.hexdigest() != sha1:
            raise RuntimeError("Prüfsumme des Downloads stimmt nicht.")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def download_model(name: str) -> None:
    if name not in MODEL_SHA1:
        raise RuntimeError("Unbekanntes Whisper-Modell.")
    destination = opentalk.model_file(name)
    if opentalk.model_available(name):
        print(f"Modell {name} ist bereits installiert.", flush=True)
        return
    print(f"Lade das mehrsprachige Whisper-Modell {name} …", flush=True)
    download(
        f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{name}.bin",
        destination,
        opentalk.MODEL_MIN_BYTES[name],
        MODEL_SHA1[name],
    )
    print(f"Modell {name} ist bereit.", flush=True)


def setup_engine() -> None:
    """Build both helpers without mixing Git sources and downloaded models."""
    if platform.system() == "Darwin" and platform.machine() != "arm64":
        raise RuntimeError("macOS wird nur auf Macs mit M-Prozessor unterstützt.")
    if opentalk.bundled_executable("whisper-cli"):
        return
    for tool in ("git", "cmake"):
        if not shutil.which(tool):
            raise RuntimeError(f"{tool} fehlt. Bitte die Quellcode-Voraussetzungen aus README installieren.")
    data = opentalk.local_data_dir()
    source = data / "whisper-src"
    # Existing installations built in whisper.cpp; retain their CMake source
    # path and never reset, pull, or overwrite a user-maintained Git checkout.
    legacy_source = data / "whisper.cpp"
    if (legacy_source / "CMakeLists.txt").is_file():
        source = legacy_source
    elif not (source / ".git").is_dir():
        if source.exists():
            raise RuntimeError(f"Unvollständiger Quellordner: {source}. Bitte prüfen/umbenennen.")
        data.mkdir(parents=True, exist_ok=True)
        print(f"Lade whisper.cpp {WHISPER_VERSION} …", flush=True)
        subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", WHISPER_VERSION,
             "https://github.com/ggml-org/whisper.cpp.git", str(source)],
            check=True, **opentalk.subprocess_options(),
        )
    build = data / "whisper.cpp/build"
    print("Baue lokale Erkennung und Schnellmodus …", flush=True)
    subprocess.run(
        ["cmake", "-S", str(source), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release",
         "-DBUILD_SHARED_LIBS=OFF", "-DGGML_OPENMP=OFF"],
        check=True, **opentalk.subprocess_options(),
    )
    subprocess.run(
        ["cmake", "--build", str(build), "--config", "Release", "--target",
         "whisper-cli", "whisper-server", "--parallel", str(min(4, os.cpu_count() or 2))],
        check=True, **opentalk.subprocess_options(),
    )


def setup() -> None:
    download_model("small")
    vad = opentalk.local_data_dir() / "whisper.cpp/models/ggml-silero-v6.2.0.bin"
    if not vad.is_file() or vad.stat().st_size < 100_000:
        print("Lade Spracherkennung für Pausen und Hintergrundgeräusche …", flush=True)
        download(
            "https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v6.2.0.bin",
            vad,
            100_000,
        )
    print("Einrichtung abgeschlossen.", flush=True)


def main(arguments: list[str]) -> int:
    try:
        if arguments == ["--setup-models"]:
            setup()
        elif arguments == ["--setup-engine"]:
            setup_engine()
            setup()
        elif len(arguments) == 2 and arguments[0] == "--download-model":
            download_model(arguments[1])
        else:
            return 2
        return 0
    except Exception as exc:
        print(f"Fehler: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
