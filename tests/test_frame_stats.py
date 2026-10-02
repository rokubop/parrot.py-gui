"""The cached frame stats match the frames, including after the recorder cuts
frames off the end and records more."""
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)

from lib.frame_stats import stat_arrays


def frames(start, count):
    return [types.SimpleNamespace(dBFS=-float(i), spectral_flux=float(i))
            for i in range(start, start + count)]


class FrameStatsTest(unittest.TestCase):
    def assertMatches(self, state, detection_frames):
        dBFS, spectral_flux = stat_arrays(state, detection_frames)
        self.assertEqual(list(dBFS), [frame.dBFS for frame in detection_frames])
        self.assertEqual(list(spectral_flux), [frame.spectral_flux for frame in detection_frames])

    def test_growing(self):
        state = types.SimpleNamespace()
        detection_frames = []
        for _ in range(20):
            detection_frames += frames(len(detection_frames), 15)
            self.assertMatches(state, detection_frames)

    def test_cut_then_recorded_past_the_cache(self):
        state = types.SimpleNamespace()
        detection_frames = frames(0, 100)
        self.assertMatches(state, detection_frames)
        detection_frames = detection_frames[:80] + frames(1000, 25)
        self.assertMatches(state, detection_frames)

    def test_cut_then_recorded_back_to_the_same_length(self):
        state = types.SimpleNamespace()
        detection_frames = frames(0, 100)
        self.assertMatches(state, detection_frames)
        detection_frames = detection_frames[:80] + frames(1000, 20)
        self.assertMatches(state, detection_frames)

    def test_cut(self):
        state = types.SimpleNamespace()
        detection_frames = frames(0, 100)
        self.assertMatches(state, detection_frames)
        self.assertMatches(state, detection_frames[:40])


if __name__ == "__main__":
    unittest.main()
