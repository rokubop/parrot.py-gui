"""Training data is read back in chunks sized from SLIDING_WINDOW_AMOUNT, which
the combine models menu prompts for. The read has to survive any value of it.
"""
import glob
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import config.config
import lib.stream_processing
import lib.wav

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "recordings", "pop", "source", "pop.wav")


class SlidingWindowTest(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="parrot_window_")
        self.addCleanup(shutil.rmtree, self.workdir, True)
        self.addCleanup(setattr, lib.wav, "SLIDING_WINDOW_AMOUNT",
                        lib.wav.SLIDING_WINDOW_AMOUNT)
        self.addCleanup(setattr, lib.stream_processing, "SLIDING_WINDOW_AMOUNT",
                        lib.stream_processing.SLIDING_WINDOW_AMOUNT)

    def samples_loaded(self, window):
        """Segment and load the fixture with both modules on the same window."""
        lib.wav.SLIDING_WINDOW_AMOUNT = window
        lib.stream_processing.SLIDING_WINDOW_AMOUNT = window

        name = "window%d" % window
        lib.stream_processing.process_wav_file(
            FIXTURE, os.path.join(self.workdir, name),
            os.path.join(self.workdir, name + "_segmented.wav"),
            os.path.join(self.workdir, name + "_thresholds.txt"), ["pop"])

        written = glob.glob(os.path.join(self.workdir, name + "*.srt"))
        self.assertEqual(len(written), 1, "no srt was written")
        return len(lib.wav.load_wav_data_from_srt(
            written[0], FIXTURE, config.config.FEATURE_ENGINEERING_TYPE, False))

    def test_the_default_window_loads_samples(self):
        self.assertGreater(self.samples_loaded(2), 0)

    def test_another_window_loads_samples(self):
        self.assertGreater(self.samples_loaded(4), 0)


if __name__ == "__main__":
    unittest.main()
