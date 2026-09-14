"""resample_audio is called directly here. Neither caller can reach it with
more than one channel: both over-read by number_channels and bail first."""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import config.config
from lib.wav import resample_audio

RATE = config.config.RATE
SOURCE_RATE = RATE * 3
FRAMES = 300
LEFT = 1000
RIGHT = -1000


def samples(fragment):
    return struct.unpack("<%dh" % (len(fragment) // 2), fragment)


class ResampleAudioTest(unittest.TestCase):
    def setUp(self):
        self.stereo = struct.pack("<%dh" % (FRAMES * 2), *([LEFT, RIGHT] * FRAMES))
        self.mono = struct.pack("<%dh" % FRAMES, *([LEFT] * FRAMES))

    def test_stereo_above_rate_comes_back_mono(self):
        resampled = resample_audio(self.stereo, SOURCE_RATE, 2)
        self.assertEqual(len(samples(resampled)), FRAMES * RATE // SOURCE_RATE)

    def test_the_downmix_keeps_the_left_channel(self):
        # tomono is called with factors 1 and 0, so the right channel is dropped
        resampled = resample_audio(self.stereo, SOURCE_RATE, 2)
        self.assertEqual(set(samples(resampled)), {LEFT})

    def test_mono_above_rate_is_resampled(self):
        resampled = resample_audio(self.mono, SOURCE_RATE, 1)
        self.assertEqual(len(samples(resampled)), FRAMES * RATE // SOURCE_RATE)
        self.assertEqual(set(samples(resampled)), {LEFT})

    def test_at_rate_the_fragment_is_untouched(self):
        self.assertIs(resample_audio(self.stereo, RATE, 2), self.stereo)


if __name__ == "__main__":
    unittest.main()
