"""Small, dependency-free helpers for 16 kHz, little-endian mono PCM."""

from array import array
import math
import sys

SAMPLE_RATE = 16_000
BYTES_PER_SECOND = SAMPLE_RATE * 2
FRAME_BYTES = BYTES_PER_SECOND // 50  # 20 ms; never split a PCM sample.


def rms_level(pcm: bytes) -> float:
    if not pcm:
        return 0.0
    samples = array("h", pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def display_level(rms: float) -> float:
    """Map -60..0 dBFS to a readable meter, not a speech/no-speech verdict."""
    return max(0.0, min(1.0, (20 * math.log10(max(rms, 1) / 32768) + 60) / 60))


class PauseSegmenter:
    """Prefer pauses without dropping quiet speech or duplicating overlap.

    Energy only chooses boundaries; it is not a speech filter. Continuous speech
    gets two extra seconds beyond the target before a bounded fallback cut.
    Whisper's existing VAD remains responsible for recognising actual speech.
    """

    def __init__(self, target_bytes: int):
        self.maximum = target_bytes + 2 * BYTES_PER_SECOND
        self.minimum = min(target_bytes, int(1.2 * BYTES_PER_SECOND))
        self.pause_bytes = int(0.36 * BYTES_PER_SECOND)
        self.buffer = bytearray()
        self.tail = bytearray()
        self.quiet_bytes = 0
        self.saw_signal = False

    def feed(self, pcm: bytes) -> list[bytes]:
        self.tail.extend(pcm)
        result = []
        offset = 0
        while len(self.tail) - offset >= FRAME_BYTES:
            frame = self.tail[offset : offset + FRAME_BYTES]
            offset += FRAME_BYTES
            self.buffer.extend(frame)
            quiet = rms_level(frame) < 100
            self.saw_signal |= not quiet
            self.quiet_bytes = self.quiet_bytes + FRAME_BYTES if quiet else 0
            if (
                self.saw_signal and len(self.buffer) >= self.minimum
                and self.quiet_bytes >= self.pause_bytes
            ) or len(self.buffer) >= self.maximum:
                result.append(bytes(self.buffer))
                self.buffer.clear()
                self.quiet_bytes = 0
                self.saw_signal = False
        del self.tail[:offset]
        return result

    def finish(self) -> bytes:
        self.buffer.extend(self.tail)
        result = bytes(self.buffer)
        self.buffer.clear()
        self.tail.clear()
        self.quiet_bytes = 0
        self.saw_signal = False
        return result
