"""Local, opt-in recognition benchmarks against user-supplied reference audio."""

import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import re
import time
import unicodedata
import wave

import opentalk


def words(text: str) -> list[str]:
    """Case/punctuation-insensitive; spelling, numbers and word boundaries count."""
    return re.findall(r"\w+", unicodedata.normalize("NFC", text).casefold(), flags=re.UNICODE)


def word_errors(reference: str, hypothesis: str) -> tuple[int, int]:
    expected, actual = words(reference), words(hypothesis)
    previous = list(range(len(actual) + 1))
    for index, word in enumerate(expected, 1):
        current = [index]
        for offset, other in enumerate(actual, 1):
            current.append(min(current[-1] + 1, previous[offset] + 1,
                               previous[offset - 1] + (word != other)))
        previous = current
    return previous[-1], len(expected)


def measure(manifest: Path, *, warmup: bool = False) -> dict:
    cases = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("Manifest muss eine nicht leere Liste von audio/text-Einträgen sein.")
    # Validate the whole corpus before starting costly model work.
    prepared = []
    digest = hashlib.sha256()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("audio"), str) or not isinstance(case.get("text"), str):
            raise ValueError("Jeder Fall benötigt audio und text als Zeichenketten.")
        if not words(case["text"]) or len(case["text"]) > 10_000:
            raise ValueError("Referenztext muss 1–10000 Zeichen und mindestens ein Wort enthalten.")
        path = manifest.parent / case["audio"]
        with path.open("rb") as stream:
            audio = stream.read(opentalk.MAX_WAV_BYTES + 1)
        opentalk.validate_wav(audio)
        with wave.open(io.BytesIO(audio), "rb") as wav:
            duration = wav.getnframes() / wav.getframerate()
        digest.update(hashlib.sha256(audio).digest())
        digest.update(hashlib.sha256(case["text"].encode()).digest())
        prepared.append((audio, case["text"], duration))
    rows = []
    if warmup:
        # Use the same audio without including model load/first inference in timing.
        opentalk.transcribe_local(prepared[0][0])
    for index, (audio, reference, duration) in enumerate(prepared, 1):
        started = time.perf_counter()
        # Deliberately bypass remote mode: benchmarks never upload recordings.
        hypothesis = opentalk.transcribe_local(audio)
        seconds = time.perf_counter() - started
        errors, count = word_errors(reference, hypothesis)
        rows.append({"case": index, "errors": errors, "words": count,
                     "seconds": seconds, "audio_seconds": duration, "wer": errors / count})
    total_words = sum(row["words"] for row in rows)
    return {
        "schema": 1, "corpus": digest.hexdigest(), "platform": platform.system(),
        "model": opentalk.model_path().name, "language": opentalk.config("LANGUAGE", "de"),
        "vocabulary_enabled": bool(opentalk.vocabulary_prompt()),
        "threads": opentalk.config("WHISPER_THREADS", "4"), "warmup": warmup,
        "wer": sum(row["errors"] for row in rows) / total_words,
        "rtf": sum(row["seconds"] for row in rows) / sum(row["audio_seconds"] for row in rows),
        "cases": rows,
    }


def regressions(report: dict, baseline: dict, wer_increase: float, slowdown: float) -> list[str]:
    if not isinstance(baseline, dict) or baseline.get("schema") != 1 or baseline.get("corpus") != report["corpus"]:
        raise ValueError("Vergleich benötigt dasselbe Audio und dieselben Referenztexte.")
    for result in (baseline, report):
        for key in ("wer", "rtf"):
            value = result.get(key)
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError("Ungültige Vergleichsmetrik: " + key)
    failures = []
    if report["wer"] > baseline["wer"] + wer_increase:
        failures.append("Wortfehlerrate über Vergleichsgrenze.")
    if report["rtf"] > baseline["rtf"] * slowdown:
        failures.append("Erkennung langsamer als Vergleichsgrenze.")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--threads", type=int, help="CPU-Threads nur für diesen Benchmark (1–256)")
    parser.add_argument("--warmup", action="store_true", help="Ungewerteter Vorlauf vor der Messung")
    parser.add_argument("--max-wer-increase", type=float, default=0.02)
    parser.add_argument("--max-slowdown", type=float, default=1.2)
    args = parser.parse_args()
    previous_threads = os.environ.get("OPENTALK_WHISPER_THREADS")
    try:
        if args.threads is not None:
            if not 1 <= args.threads <= 256:
                raise ValueError("Thread-Anzahl muss zwischen 1 und 256 liegen.")
            os.environ["OPENTALK_WHISPER_THREADS"] = str(args.threads)
        if not 0 <= args.max_wer_increase <= 1 or not 1 <= args.max_slowdown <= 100:
            raise ValueError("WER-Toleranz: 0–1; maximaler Zeitfaktor: 1–100.")
        report = measure(args.manifest, warmup=args.warmup)
        report["regressions"] = regressions(
            report, json.loads(args.baseline.read_text(encoding="utf-8")),
            args.max_wer_increase, args.max_slowdown,
        ) if args.baseline else []
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return int(bool(report["regressions"]))
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        parser.exit(2, f"Benchmark fehlgeschlagen: {exc}\n")
    finally:
        opentalk.LOCAL_WHISPER_SERVER.shutdown()
        if previous_threads is None:
            os.environ.pop("OPENTALK_WHISPER_THREADS", None)
        else:
            os.environ["OPENTALK_WHISPER_THREADS"] = previous_threads


if __name__ == "__main__":
    raise SystemExit(main())
