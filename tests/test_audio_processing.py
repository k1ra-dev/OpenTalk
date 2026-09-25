import math
import struct
import unittest

from audio_processing import BYTES_PER_SECOND, PauseSegmenter, display_level, rms_level


def pcm(seconds, amplitude=1000):
    return struct.pack("<h", amplitude) * round(seconds * 16_000)


class AudioProcessingTests(unittest.TestCase):
    def test_levels_include_silence_and_full_signed_range(self):
        self.assertEqual(rms_level(b""), 0)
        self.assertEqual(rms_level(pcm(0.1, 0)), 0)
        self.assertEqual(rms_level(pcm(0.1, -32768)), 32768)
        self.assertEqual(display_level(0), 0)
        self.assertEqual(display_level(32768), 1)
        self.assertGreater(display_level(1000), display_level(100))
        self.assertAlmostEqual(rms_level(struct.pack("<hh", 0, 1000)), math.sqrt(500000))

    def test_pause_finishes_phrase_before_hard_limit(self):
        segmenter = PauseSegmenter(3 * BYTES_PER_SECOND)
        speech = pcm(1.0)
        self.assertEqual(segmenter.feed(speech), [])
        self.assertEqual(segmenter.feed(pcm(0.36, 0)), [speech + pcm(0.36, 0)])
        self.assertEqual(segmenter.finish(), b"")

    def test_short_pause_does_not_split_a_phrase(self):
        segmenter = PauseSegmenter(3 * BYTES_PER_SECOND)
        phrase = pcm(1) + pcm(0.1, 0) + pcm(1)
        self.assertEqual(segmenter.feed(phrase), [])
        self.assertEqual(segmenter.finish(), phrase)

    def test_continuous_speech_has_bounded_latency(self):
        segmenter = PauseSegmenter(3 * BYTES_PER_SECOND)
        self.assertEqual(segmenter.feed(pcm(5.2)), [pcm(5)])
        self.assertEqual(segmenter.finish(), pcm(0.2))

    def test_fragmented_and_quiet_audio_is_neither_lost_nor_duplicated(self):
        data = pcm(0.43, 10) + pcm(0.37, 0) + pcm(8.78, 30) + pcm(0.1, -12)
        segmenter = PauseSegmenter(3 * BYTES_PER_SECOND)
        chunks = []
        for offset in range(0, len(data), 317):
            chunks.extend(segmenter.feed(data[offset : offset + 317]))
        chunks.append(segmenter.finish())
        self.assertEqual(b"".join(chunks), data)
        self.assertTrue(all(len(chunk) <= 5 * BYTES_PER_SECOND for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
