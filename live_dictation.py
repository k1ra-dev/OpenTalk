"""Chunked microphone transcription while recording continues."""
from __future__ import annotations

import io
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time
import wave

import opentalk

SAMPLE_RATE = 16_000
BYTES_PER_SECOND = SAMPLE_RATE * 2
CHUNK_BYTES = 4 * BYTES_PER_SECOND
MIN_BYTES = BYTES_PER_SECOND // 5


def pcm_to_wav(data: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(SAMPLE_RATE)
        audio.writeframes(data)
    return output.getvalue()


class LiveDictation:
    def __init__(self, on_chunk, on_error, on_finished, source: str = ""):
        self.on_chunk = on_chunk
        self.on_error = on_error
        self.on_finished = on_finished
        self.source = source
        self.recorder: subprocess.Popen | None = None
        self.temp: tempfile.TemporaryDirectory | None = None
        self.audio_path: Path | None = None
        self.worker: threading.Thread | None = None
        self.timer: threading.Timer | None = None
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
        command = ["pw-record", "--raw", "--rate", str(SAMPLE_RATE), "--channels", "1",
                   "--format", "s16", *(["--target", self.source] if self.source else []),
                   str(self.audio_path)]
        try:
            self.recorder = subprocess.Popen(command, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL)
        except OSError as exc:
            self.temp.cleanup()
            self.temp = self.audio_path = None
            raise RuntimeError("Mikrofon konnte nicht gestartet werden.") from exc
        time.sleep(0.12)
        if self.recorder.poll() is not None:
            self.temp.cleanup()
            self.temp = self.audio_path = self.recorder = None
            raise RuntimeError("Mikrofon konnte nicht gestartet werden. Quelle prüfen.")
        self.stop_requested.clear()
        self.cancelled.clear()
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()
        self.timer = threading.Timer(opentalk.MAX_SECONDS, self.stop)
        self.timer.daemon = True
        self.timer.start()

    def stop(self) -> None:
        if not self.recording:
            return
        self.stop_requested.set()
        if self.timer is not None:
            self.timer.cancel()
        if self.recorder is not None and self.recorder.poll() is None:
            try:
                self.recorder.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass

    def cancel(self) -> None:
        self.cancelled.set()
        self.stop()

    def _run(self) -> None:
        recorder = self.recorder
        path = self.audio_path
        temp = self.temp
        offset = 0
        try:
            while not self.cancelled.is_set():
                if recorder.poll() is not None and not self.stop_requested.is_set():
                    raise RuntimeError("Mikrofonaufnahme wurde unerwartet beendet.")
                size = (path.stat().st_size if path.exists() else 0) & ~1
                available = size - offset
                finished_recording = self.stop_requested.is_set() and recorder.poll() is not None
                if available >= CHUNK_BYTES or (finished_recording and available >= MIN_BYTES):
                    count = min(available, CHUNK_BYTES)
                    with path.open("rb") as stream:
                        stream.seek(offset)
                        pcm = stream.read(count)
                    if len(pcm) != count:
                        time.sleep(0.05)
                        continue
                    offset += count
                    result = opentalk.transcribe(pcm_to_wav(pcm))
                    if result and not self.cancelled.is_set():
                        self.on_chunk(result)
                    continue
                if finished_recording:
                    break
                time.sleep(0.1)
        except Exception as exc:
            if not self.cancelled.is_set():
                self.on_error(str(exc))
        finally:
            if recorder.poll() is None:
                try:
                    recorder.send_signal(signal.SIGINT)
                    recorder.wait(timeout=3)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    recorder.kill()
                    recorder.wait()
            if temp is not None:
                temp.cleanup()
            self.recorder = None
            self.audio_path = None
            self.temp = None
            if not self.cancelled.is_set():
                self.on_finished()
