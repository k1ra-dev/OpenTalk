"""Chunked microphone transcription while recording continues."""

from __future__ import annotations

from contextlib import suppress
import io
import math
from pathlib import Path
import platform
import queue
import subprocess
import tempfile
import threading
import time
import wave

import opentalk
from audio_processing import PauseSegmenter, display_level, rms_level

SAMPLE_RATE = 16_000
BYTES_PER_SECOND = SAMPLE_RATE * 2
MIN_BYTES = BYTES_PER_SECOND // 5


def microphone_help() -> str:
    if platform.system() == "Darwin":
        return "Mikrofonquelle und Datenschutz & Sicherheit → Mikrofon (OpenTalk/Python) prüfen."
    if platform.system() == "Windows":
        return "Mikrofonquelle und Datenschutz → Mikrofon → Zugriff für Desktop-Apps prüfen."
    return "Mikrofonquelle, Stummschaltung und PipeWire prüfen."


def chunk_bytes() -> int:
    """Return the latency/throughput trade-off for the current platform."""
    default = "3" if platform.system() == "Darwin" else "4"
    try:
        seconds = float(opentalk.config("CHUNK_SECONDS", default))
    except ValueError:
        seconds = float(default)
    if not math.isfinite(seconds):
        seconds = float(default)
    # Shorter segments lose linguistic context; longer segments make live
    # dictation feel unresponsive. Keep overrides inside a useful range.
    seconds = max(1.0, min(seconds, 10.0))
    return int(seconds * BYTES_PER_SECOND) & ~1


def pcm_to_wav(data: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(SAMPLE_RATE)
        audio.writeframes(data)
    return output.getvalue()


class LiveDictation:
    def __init__(self, on_chunk, on_error, on_finished, source: str = "", on_level=None, on_notice=None):
        self.on_chunk = on_chunk
        self.on_error = on_error
        self.on_finished = on_finished
        self.source = source
        self.on_level = on_level or (lambda level: None)
        self.on_notice = on_notice or (lambda message: None)
        self.recorder: subprocess.Popen | None = None
        self.temp: tempfile.TemporaryDirectory | None = None
        self.audio_path: Path | None = None
        self.worker: threading.Thread | None = None
        self.timer: threading.Timer | None = None
        self.stop_timer: threading.Timer | None = None
        self.stop_requested = threading.Event()
        self.cancelled = threading.Event()

    @property
    def recording(self) -> bool:
        return self.recorder is not None and not self.stop_requested.is_set()

    @property
    def busy(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def start(self) -> None:
        if self.busy or self.recorder is not None:
            raise RuntimeError("Die vorherige Aufnahme wird noch verarbeitet.")
        self.temp = tempfile.TemporaryDirectory(prefix="opentalk-live-")
        self.audio_path = Path(self.temp.name) / "audio.raw"
        try:
            command = opentalk.recorder_command(self.audio_path, self.source, raw=True)
            self.recorder = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.PIPE if platform.system() == "Windows" else None,
                **opentalk.subprocess_options(),
            )
        except (OSError, RuntimeError) as exc:
            self.temp.cleanup()
            self.temp = self.audio_path = None
            if isinstance(exc, RuntimeError):
                raise
            raise RuntimeError("Mikrofon konnte nicht gestartet werden. " + microphone_help()) from exc
        time.sleep(0.12)
        if self.recorder.poll() is not None:
            if self.recorder.stdin is not None:
                self.recorder.stdin.close()
            self.temp.cleanup()
            self.temp = self.audio_path = self.recorder = None
            raise RuntimeError("Mikrofon konnte nicht gestartet werden. Quelle prüfen. " + microphone_help())
        self.stop_requested.clear()
        self.cancelled.clear()
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.timer = threading.Timer(opentalk.MAX_SECONDS, self.stop)
        self.timer.daemon = True
        self.timer.start()
        self.worker.start()

    def stop(self) -> None:
        if not self.recording:
            return
        self.stop_requested.set()
        if self.timer is not None:
            self.timer.cancel()
        if self.recorder is not None and self.recorder.poll() is None:
            # The transcription thread may be waiting for a slow server. Stop
            # microphone capture independently, even if FFmpeg ignores SIGINT/q.
            self.stop_timer = threading.Timer(3, self._force_stop, args=(self.recorder,))
            self.stop_timer.daemon = True
            self.stop_timer.start()
            with suppress(OSError):
                opentalk.stop_recorder(self.recorder)

    @staticmethod
    def _force_stop(recorder: subprocess.Popen) -> None:
        if recorder.poll() is None:
            with suppress(ProcessLookupError):
                recorder.kill()

    def cancel(self) -> None:
        self.cancelled.set()
        self.stop()

    def _recognize(self, segments: queue.Queue, failed: threading.Event) -> None:
        try:
            while not self.cancelled.is_set() and not failed.is_set():
                pcm = segments.get()
                if pcm is None or self.cancelled.is_set() or failed.is_set():
                    break
                # Only digital silence is skipped. Quiet speech is never gated.
                if not any(pcm):
                    continue
                pcm = pcm.ljust(MIN_BYTES, b"\0")
                result = opentalk.transcribe(pcm_to_wav(pcm))
                if result and not self.cancelled.is_set() and not failed.is_set():
                    self.on_chunk(result)
        except Exception as exc:
            failed.set()
            if not self.cancelled.is_set():
                self.on_error(str(exc))
                self.stop()

    def _run(self) -> None:
        """Read/meter independently of inference; keep ordered, lossless segments."""
        recorder = self.recorder
        path = self.audio_path
        temp = self.temp
        offset = 0
        segmenter = PauseSegmenter(chunk_bytes())
        # Capture is capped at 120 s (3.84 MB). A slow recognizer may queue that
        # audio, but can never grow the queue indefinitely or block the meter.
        segments = queue.Queue()
        failed = threading.Event()
        recognizer = threading.Thread(target=self._recognize, args=(segments, failed), daemon=True)
        recognizer.start()
        started = time.monotonic()
        last_meter = 0.0
        heard_signal = False
        warned = False
        try:
            while not self.cancelled.is_set() and not failed.is_set():
                if recorder.poll() is not None and not self.stop_requested.is_set():
                    raise RuntimeError("Mikrofonaufnahme wurde unerwartet beendet. " + microphone_help())
                size = min(path.stat().st_size if path.exists() else 0, opentalk.MAX_SECONDS * BYTES_PER_SECOND) & ~1
                available = size - offset
                finished_recording = self.stop_requested.is_set() and recorder.poll() is not None
                now = time.monotonic()
                if available:
                    count = min(available, BYTES_PER_SECOND // 10)
                    with path.open("rb") as stream:
                        stream.seek(offset)
                        pcm = stream.read(count)
                    if len(pcm) != count:
                        time.sleep(0.05)
                        continue
                    offset += count
                    rms = rms_level(pcm)
                    heard_signal |= rms >= 100
                    if now - last_meter >= 0.1:
                        self.on_level(display_level(rms))
                        last_meter = now
                    if heard_signal and warned:
                        self.on_notice("Mikrofonsignal erkannt · Aufnahme läuft")
                        warned = False
                    for segment in segmenter.feed(pcm):
                        segments.put(segment)
                    if offset >= opentalk.MAX_SECONDS * BYTES_PER_SECOND:
                        self.stop()
                    continue
                if finished_recording:
                    tail = segmenter.finish()
                    if tail:
                        segments.put(tail)
                    break
                if not offset and now - started >= 8:
                    raise RuntimeError("Keine Audiodaten vom Mikrofon. " + microphone_help())
                if not heard_signal and not warned and now - started >= 3:
                    self.on_notice("Kein Mikrofonpegel – sprechen oder Mikrofon/Stummschaltung prüfen.")
                    warned = True
                time.sleep(0.05)
        except Exception as exc:
            failed.set()
            if not self.cancelled.is_set():
                self.on_error(str(exc))
        finally:
            if self.timer is not None:
                self.timer.cancel()
            try:
                if recorder.poll() is None:
                    try:
                        opentalk.stop_recorder(recorder)
                        recorder.wait(timeout=3)
                    except (OSError, subprocess.TimeoutExpired):
                        self._force_stop(recorder)
                        recorder.wait(timeout=3)
            finally:
                if self.stop_timer is not None:
                    self.stop_timer.cancel()
                if recorder.stdin is not None:
                    recorder.stdin.close()
                try:
                    if temp is not None:
                        temp.cleanup()
                finally:
                    self.recorder = None
                    self.audio_path = None
                    self.temp = None
                    segments.put(None)
                    if not self.cancelled.is_set():
                        recognizer.join()
                        self.on_level(0.0)
                    if not self.cancelled.is_set():
                        self.on_finished()
