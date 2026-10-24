"""Regression tests for the srt count functions."""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from lib.srt import (count_label_ms_in_srt, count_frames_in_srt, count_total_label_ms,
                     count_total_frames, count_total_silence_frames,
                     current_v_ending, manual_ending)


def srt_text(*entries):
    r"""Example:
    input:  srt_text((0.9, 1.8, "pop"))
    output: "1\n00:00:00,900 --> 00:00:01,800\npop\n\n"
    """
    def time(seconds):
        return "00:00:" + f"{seconds:06.3f}".replace(".", ",")
    return "".join(f"{i}\n{time(start)} --> {time(end)}\n{label}\n\n"
                   for i, (start, end, label) in enumerate(entries, 1))


SRT_CASES = {
    "simple": srt_text((0.9, 1.8, "pop"), (3.0, 3.6, "ss")),
    "overlap": srt_text((1.0, 3.0, "pop"), (2.0, 4.0, "pop")),
    "mixed_case": srt_text((0.9, 1.2, "Pop"), (2.1, 2.4, "pop")),
    "back_to_back": srt_text((0.9, 1.8, "pop"), (1.8, 2.4, "ss")),
    "empty": srt_text(),
}

ROUNDING_MS = 15

# srt case: {label: (count_label_ms_in_srt, count_frames_in_srt)}
EXPECTED_COUNTS = {
    "simple": {"pop": (900, 59), "ss": (600, 39), "silence": (2100, 138)},
    "overlap": {"pop": (990, 65), "ss": (0, 0), "silence": (1005, 66)},
    "mixed_case": {"pop": (600, 38), "ss": (0, 0), "silence": (1800, 118)},
    "back_to_back": {"pop": (900, 59), "ss": (0, 0), "silence": (900, 59)},
    "empty": {"pop": (0, 0), "ss": (0, 0), "silence": (0, 0)},
}


class SrtCountsTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def write(self, path, content):
        with open(path, "w") as f:
            f.write(content)

    def test_counts_in_one_srt(self):
        for name, content in SRT_CASES.items():
            srt_path = os.path.join(self.dir, name + ".srt")
            self.write(srt_path, content)
            for label, (ms, frames) in EXPECTED_COUNTS[name].items():
                with self.subTest(srt=name, label=label):
                    self.assertEqual(count_label_ms_in_srt(label, srt_path, ROUNDING_MS), ms)
                    self.assertEqual(count_frames_in_srt(label, srt_path, ROUNDING_MS), frames)

    def test_totals_use_manual_over_generated(self):
        segments = os.path.join(self.dir, "segments")
        os.mkdir(segments)
        for name, content in {
            "both" + current_v_ending: srt_text((0.9, 1.8, "pop")),       # not used
            "both" + manual_ending: srt_text((0.9, 1.2, "pop")),          # 300 ms
            "generated" + current_v_ending: srt_text((0.9, 1.5, "pop")),  # 600 ms
            "manual" + manual_ending: srt_text((0.9, 1.05, "pop")),       # 150 ms
            "old.v1.srt": srt_text((0.9, 1.8, "pop")),                    # not used
        }.items():
            self.write(os.path.join(segments, name), content)
        self.assertEqual(count_total_label_ms("pop", self.dir, ROUNDING_MS), 1050)
        self.assertEqual(count_total_frames("pop", self.dir, ROUNDING_MS), 67)
        self.assertEqual(count_total_silence_frames(self.dir, ROUNDING_MS), 177)


if __name__ == "__main__":
    unittest.main()
