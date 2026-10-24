"""Tests which srt each recording uses: the .MANUAL.srt if there is one, else
the current version's.
"""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lib.srt import srt_for_source, srt_files_to_use, current_v_ending, manual_ending


class TestSrtChoice(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        for name in ("both" + current_v_ending, "both" + manual_ending,
                     "generated" + current_v_ending,
                     "manual" + manual_ending,
                     "old.v1.srt"):
            open(os.path.join(self.dir, name), "w").close()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def path(self, name):
        return os.path.join(self.dir, name)

    def test_manual_wins(self):
        self.assertEqual(srt_for_source(self.dir, "both"), self.path("both" + manual_ending))

    def test_generated_when_no_manual(self):
        self.assertEqual(srt_for_source(self.dir, "generated"),
                         self.path("generated" + current_v_ending))

    def test_manual_only(self):
        self.assertEqual(srt_for_source(self.dir, "manual"), self.path("manual" + manual_ending))

    def test_old_version_is_not_used(self):
        self.assertIsNone(srt_for_source(self.dir, "old"))

    def test_none_when_not_segmented(self):
        self.assertIsNone(srt_for_source(self.dir, "missing"))

    def test_one_srt_per_recording(self):
        self.assertEqual(sorted(srt_files_to_use(self.dir)), sorted([
            self.path("both" + manual_ending),
            self.path("generated" + current_v_ending),
            self.path("manual" + manual_ending),
        ]))

    def test_no_segments_folder(self):
        self.assertEqual(srt_files_to_use(self.path("nope")), [])


if __name__ == "__main__":
    unittest.main()
