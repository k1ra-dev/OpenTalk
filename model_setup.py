"""Cross-platform model downloads used by packaged OpenTalk applications."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import urllib.request

import opentalk

MODEL_SHA1 = {
    "tiny": "bd577a113a864445d4c299885e0cb97d4ba92b5f",
    "base": "465707469ff3a37a2b9b8d8f89f2f99de7299dac",
    "small": "55356645c2b361a969dfd0ef2c5a50d530afd8d5",
    "medium": "fd9727b6e1217c2f614f9b698455c4ffd82463b4",
    "large-v3": "ad82bf6a9043ceed055076d0fd39f5f186ff8062",
}


def download(url: str, destination: Path, minimum_size: int, sha1: str = "") -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".download")
    digest = hashlib.sha1()
    total = 0
    try:
        with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as output:
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
    download(f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{name}.bin",
             destination, opentalk.MODEL_MIN_BYTES[name], MODEL_SHA1[name])
    print(f"Modell {name} ist bereit.", flush=True)


def setup() -> None:
    download_model("small")
    vad = opentalk.local_data_dir() / "whisper.cpp/models/ggml-silero-v6.2.0.bin"
    if not vad.is_file() or vad.stat().st_size < 100_000:
        print("Lade Spracherkennung für Pausen und Hintergrundgeräusche …", flush=True)
        download("https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v6.2.0.bin",
                 vad, 100_000)
    print("Einrichtung abgeschlossen.", flush=True)


def main(arguments: list[str]) -> int:
    try:
        if arguments == ["--setup-models"]:
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
