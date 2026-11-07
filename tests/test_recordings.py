import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from lib import recordings
from lib.srt import current_v_ending, manual_ending


class RecordingsFolder(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        patch = mock.patch.object(recordings, "RECORDINGS_FOLDER", self.dir)
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def touch(self, *parts):
        path = os.path.join(self.dir, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()
        return path


class TestRecordings(RecordingsFolder):

    def test_labels_are_folders_in_order(self):
        self.touch("pop", "source", "a.wav")
        os.makedirs(os.path.join(self.dir, "click"))
        os.makedirs(os.path.join(self.dir, ".hidden"))
        self.touch("notes.txt")
        self.assertEqual(recordings.get_labels(), ["click", "pop"])

    def test_no_recordings_folder(self):
        with mock.patch.object(recordings, "RECORDINGS_FOLDER", os.path.join(self.dir, "gone")):
            self.assertEqual(recordings.get_labels(), [])

    def test_each_wav_with_its_srt(self):
        wav = self.touch("pop", "source", "mici_1__100.wav")
        unsegmented = self.touch("pop", "source", "mici_1__200.wav")
        self.touch("pop", "source", "notes.txt")
        srt = self.touch("pop", "segments", "mici_1__100" + current_v_ending)
        self.assertEqual(recordings.get_recordings("pop"), [
            {"filename": "mici_1__100.wav", "wav_path": wav, "srt_path": srt},
            {"filename": "mici_1__200.wav", "wav_path": unsegmented, "srt_path": None},
        ])

    def test_manual_srt_wins(self):
        self.touch("pop", "source", "a.wav")
        self.touch("pop", "segments", "a" + current_v_ending)
        manual = self.touch("pop", "segments", "a" + manual_ending)
        self.assertEqual(recordings.get_recordings("pop")[0]["srt_path"], manual)

    def test_no_source_folder(self):
        os.makedirs(os.path.join(self.dir, "pop"))
        self.assertEqual(recordings.get_recordings("pop"), [])

    def test_detected_ms_skips_an_srt_it_cant_parse(self):
        good = self.touch("pop", "segments", "a" + current_v_ending)
        with open(good, "w") as f:
            f.write("1\n00:00:01,000 --> 00:00:01,600\npop\n\n")
        bad = self.touch("pop", "segments", "b" + current_v_ending)
        with open(bad, "w") as f:
            f.write("1\nnot a time --> also not\npop\n\n")
        self.assertEqual(recordings.get_detected_ms("pop"), 600)

    def test_detected_ms_without_segments(self):
        os.makedirs(os.path.join(self.dir, "pop"))
        self.assertEqual(recordings.get_detected_ms("pop"), 0)


class TestRecordedAt(unittest.TestCase):

    def test_from_the_name(self):
        self.assertEqual(recordings.get_recorded_at("mici_1__1693668038.wav"),
                         datetime.fromtimestamp(1693668038))

    def test_without_extension(self):
        self.assertEqual(recordings.get_recorded_at("mici_1__1693668038"),
                         datetime.fromtimestamp(1693668038))

    def test_no_time_in_the_name(self):
        for name in ("pop.wav", "mici_1__take2.wav", "mici_1__99999999999999999999.wav"):
            with self.subTest(name=name):
                self.assertIsNone(recordings.get_recorded_at(name))


class TestCleanLabel(unittest.TestCase):

    def test_trimmed(self):
        self.assertEqual(recordings.clean_label("  pop "), "pop")

    def test_rejected(self):
        InvalidLabel = recordings.InvalidLabel
        cases = [(None, InvalidLabel.EMPTY), ("  ", InvalidLabel.EMPTY),
                 ("a/b", InvalidLabel.ILLEGAL_CHARACTER), ("a\\b", InvalidLabel.ILLEGAL_CHARACTER),
                 ("a:b", InvalidLabel.ILLEGAL_CHARACTER), ("..", InvalidLabel.STARTS_WITH_DOT),
                 (".pop", InvalidLabel.STARTS_WITH_DOT)]
        for name, reason in cases:
            with self.subTest(name=name):
                with self.assertRaises(InvalidLabel) as raised:
                    recordings.clean_label(name)
                self.assertEqual(raised.exception.reason, reason)


class TestCreateLabel(RecordingsFolder):

    def test_source_and_segments(self):
        self.assertEqual(recordings.create_label(" pop "), "pop")
        self.assertTrue(os.path.isdir(os.path.join(self.dir, "pop", "source")))
        self.assertTrue(os.path.isdir(os.path.join(self.dir, "pop", "segments")))
        self.assertEqual(recordings.get_labels(), ["pop"])

    def test_exists(self):
        os.makedirs(os.path.join(self.dir, "pop"))
        with self.assertRaises(recordings.InvalidLabel) as raised:
            recordings.create_label("pop")
        self.assertEqual(raised.exception.reason, recordings.InvalidLabel.EXISTS)


class TestCreateRecordingPaths(RecordingsFolder):

    def test_read_back_by_get_recordings(self):
        wav, srt = recordings.create_recording_paths("pop", 1, "1786747776")
        self.assertEqual(wav, os.path.join(self.dir, "pop", "source", "mici_1__1786747776.wav"))
        self.assertEqual(srt, os.path.join(self.dir, "pop", "segments", "mici_1__1786747776" + current_v_ending))
        open(wav, "w").close()
        open(srt, "w").close()
        self.assertEqual(recordings.get_recordings("pop"),
                         [{"filename": "mici_1__1786747776.wav", "wav_path": wav, "srt_path": srt}])


class TestGetRecordingFiles(RecordingsFolder):

    def test_wav_then_segment_files(self):
        wav = self.touch("pop", "source", "mici_1__17.wav")
        srt = self.touch("pop", "segments", "mici_1__17" + current_v_ending)
        manual = self.touch("pop", "segments", "mici_1__17" + manual_ending)
        thresholds = self.touch("pop", "segments", "mici_1__17_thresholds.txt")
        self.touch("pop", "source", "mici_1__170.wav")
        self.touch("pop", "segments", "mici_1__170" + current_v_ending)
        self.assertEqual(recordings.get_recording_files(wav), [wav, manual, srt, thresholds])

    def test_wav_gone(self):
        srt = self.touch("pop", "segments", "mici_1__17" + current_v_ending)
        wav = os.path.join(self.dir, "pop", "source", "mici_1__17.wav")
        self.assertEqual(recordings.get_recording_files(wav), [srt])


class TestDeleteRecording(RecordingsFolder):

    def test_only_its_files(self):
        wav = self.touch("pop", "source", "mici_1__17.wav")
        srt = self.touch("pop", "segments", "mici_1__17" + current_v_ending)
        other = self.touch("pop", "segments", "mici_1__170" + current_v_ending)
        self.assertEqual(recordings.delete_recording(wav), [wav, srt])
        self.assertFalse(os.path.exists(wav) or os.path.exists(srt))
        self.assertTrue(os.path.exists(other))

    def test_already_gone(self):
        wav = os.path.join(self.dir, "pop", "source", "mici_1__17.wav")
        self.assertEqual(recordings.delete_recording(wav), [])



class TestRelabelSegmentFiles(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def write(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w", newline="") as f:
            f.write(text)
        return path

    def read(self, path):
        with open(path, newline="") as f:
            return f.read()

    def test_srt(self):
        path = self.write("a.v3.srt", "1\r\n00:00:00,250 --> 00:00:00,500\r\nPop\r\n\r\n"
                                      "2\r\n00:00:01,000 --> 00:00:01,250\r\npop\r\n\r\n")
        recordings.relabel_segment_files([path], "pop", "click")
        self.assertEqual(self.read(path), "1\r\n00:00:00,250 --> 00:00:00,500\r\nclick\r\n\r\n"
                                          "2\r\n00:00:01,000 --> 00:00:01,250\r\nclick\r\n\r\n")

    def test_srt_other_text_kept(self):
        text = "1\n00:00:00,250 --> 00:00:00,500\npopping\n\npop\n"
        path = self.write("a.MANUAL.srt", text)
        recordings.relabel_segment_files([path], "pop", "click")
        self.assertEqual(self.read(path), text)

    def test_thresholds(self):
        path = self.write("a_thresholds.txt", "pop_duration_type=discrete\npop_min_dbfs=-30.5\n")
        recordings.relabel_segment_files([path], "Pop", "Click")
        self.assertEqual(self.read(path), "click_duration_type=discrete\nclick_min_dbfs=-30.5\n")

    def test_other_files_untouched(self):
        wav = self.write("a.wav", "pop")
        comparison = self.write("a_comparison.wav", "pop")
        recordings.relabel_segment_files([wav, comparison], "pop", "click")
        self.assertEqual(self.read(wav), "pop")
        self.assertEqual(self.read(comparison), "pop")


if __name__ == "__main__":
    unittest.main()
