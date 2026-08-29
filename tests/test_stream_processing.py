"""A recording is read with the channel count and rate stored in its own header.
Neither should change what the detector hears.
"""
import audioop
import glob
import os
import re
import shutil
import sys
import tempfile
import unittest
import wave

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import config.config
from lib.stream_processing import process_wav_file

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "recordings", "pop", "source", "pop.wav")


def count_events(srt_path):
    with open(srt_path) as handle:
        blocks = re.split(r"\n\s*\n", handle.read().strip())
    return len([block for block in blocks if block.strip()])


class ChannelAndRateTest(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="parrot_channels_")
        self.addCleanup(shutil.rmtree, self.workdir, True)
        with wave.open(FIXTURE) as handle:
            self.fixture_rate = handle.getframerate()
            self.mono = handle.readframes(handle.getnframes())

    def segment(self, name, frame_rate, channels):
        """The fixture audio, resampled and copied across channels, so only the
        two properties under test differ from the mono original."""
        raw = self.mono
        if frame_rate != self.fixture_rate:
            raw, _ = audioop.ratecv(raw, 2, 1, self.fixture_rate, frame_rate, None)
        samples = np.frombuffer(raw, dtype=np.int16)

        wav_path = os.path.join(self.workdir, name + ".wav")
        with wave.open(wav_path, "wb") as handle:
            handle.setnchannels(channels)
            handle.setsampwidth(2)
            handle.setframerate(frame_rate)
            handle.writeframes(np.repeat(samples, channels).tobytes())

        segmented = os.path.join(self.workdir, name + "_segmented.wav")
        process_wav_file(wav_path, os.path.join(self.workdir, name), segmented,
                         os.path.join(self.workdir, name + "_thresholds.txt"), ["pop"])

        written = glob.glob(os.path.join(self.workdir, name + "*.srt"))
        self.assertEqual(len(written), 1, "no srt was written")
        return count_events(written[0]), segmented

    def test_extra_channels_are_heard_the_same_as_mono(self):
        """Every channel holds the same audio, so the counts have to match."""
        expected, _ = self.segment("mono", self.fixture_rate, 1)
        self.assertGreater(expected, 1, "the mono control found nothing")

        for channels in (2, 4):
            with self.subTest(channels=channels):
                events, _ = self.segment("ch%d" % channels, self.fixture_rate, channels)
                self.assertEqual(events, expected)

    def test_a_higher_rate_is_heard(self):
        expected, _ = self.segment("rate_native", self.fixture_rate, 1)
        for channels in (1, 2):
            with self.subTest(channels=channels):
                events, _ = self.segment("rate_44100_%dch" % channels, 44100, channels)
                self.assertGreater(events, 1)

    def test_the_segmented_wav_is_mono(self):
        """resample_audio downmixes, so the frames written out are single channel
        and the file has to say so or it plays at the wrong length."""
        for channels in (1, 2, 4):
            with self.subTest(channels=channels):
                _, segmented = self.segment("out%d" % channels, self.fixture_rate, channels)
                with wave.open(segmented) as handle:
                    self.assertEqual(handle.getnchannels(), 1)


if __name__ == "__main__":
    unittest.main()
