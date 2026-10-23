"""Tests
- read_wav: what it gives back, and the reason it gives for each wav the
  Sounds tab can't show
- wav_duration, including recordings whose header overcounts

No Qt: gui/services is Qt-free, so this runs without the GUI requirements.
"""
import os
import shutil
import struct
import sys
import tempfile
import unittest
import wave

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from gui.services.wav_files import read_wav, wav_duration, UnreadableWav, DAMAGED


def write_wav(path, samples, rate=16000, channels=1, width=2):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(width)
        wf.setframerate(rate)
        wf.writeframes(samples)


def raw_wav(path, fmt=1, channels=1, rate=16000, bits=16, data=b"", nframes_bytes=None):
    """A wav written by hand, for headers the wave module won't write."""
    block = channels * bits // 8
    header = (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
              + b"fmt " + struct.pack("<IHHIIHH", 16, fmt, channels, rate, rate * block, block, bits)
              + b"data" + struct.pack("<I", len(data) if nframes_bytes is None else nframes_bytes))
    with open(path, "wb") as f:
        f.write(header + data)


class TestReadWav(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def path(self, name):
        return os.path.join(self.dir, name)

    def assertUnreadable(self, path, reason):
        with self.assertRaises(UnreadableWav) as ctx:
            read_wav(path)
        self.assertEqual(str(ctx.exception), reason)

    def test_mono_16_bit(self):
        write_wav(self.path("a.wav"), np.array([0, 16384, -32768], dtype=np.int16).tobytes())
        samples, rate = read_wav(self.path("a.wav"))
        self.assertEqual(rate, 16000)
        self.assertEqual(samples.dtype, np.float32)
        np.testing.assert_array_equal(samples, [0.0, 0.5, -1.0])

    def test_stereo_is_averaged_to_mono(self):
        frames = np.array([16384, 0, -16384, -16384], dtype=np.int16).tobytes()
        write_wav(self.path("a.wav"), frames, channels=2)
        samples, _ = read_wav(self.path("a.wav"))
        np.testing.assert_array_equal(samples, [0.25, -0.5])

    def test_cut_off_mid_sample_keeps_the_whole_samples(self):
        raw_wav(self.path("a.wav"), data=np.array([100, 200], dtype=np.int16).tobytes() + b"\x01",
                nframes_bytes=6)
        samples, _ = read_wav(self.path("a.wav"))
        self.assertEqual(len(samples), 2)

    def test_missing_file(self):
        self.assertUnreadable(self.path("gone.wav"), "The file couldn't be opened")

    def test_not_a_wav(self):
        with open(self.path("a.wav"), "w") as f:
            f.write("not audio")
        self.assertUnreadable(self.path("a.wav"), DAMAGED)

    def test_header_cut_short(self):
        with open(self.path("a.wav"), "wb") as f:
            f.write(b"RIFF\x00\x00\x00\x00WAVEfmt ")
        self.assertUnreadable(self.path("a.wav"), DAMAGED)

    def test_other_bit_depths(self):
        for width in (1, 3, 4):
            with self.subTest(bits=width * 8):
                write_wav(self.path("a.wav"), bytes(width * 10), width=width)
                self.assertUnreadable(self.path("a.wav"),
                                      f"{width * 8}-bit audio, parrot.py records 16-bit")

    def test_float_format(self):
        raw_wav(self.path("a.wav"), fmt=3, bits=32, data=bytes(40))
        self.assertUnreadable(self.path("a.wav"), "Unsupported wav format, parrot.py records 16-bit")

    def test_empty(self):
        write_wav(self.path("a.wav"), b"")
        self.assertUnreadable(self.path("a.wav"), "The recording is empty")

    def test_sample_rate_zero(self):
        raw_wav(self.path("a.wav"), rate=0, data=bytes(20))
        self.assertUnreadable(self.path("a.wav"), DAMAGED)


class TestWavDuration(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_from_the_header(self):
        path = os.path.join(self.dir, "a.wav")
        write_wav(path, bytes(2 * 8000))
        self.assertEqual(wav_duration(path), 0.5)

    def test_header_that_overcounts_is_capped_to_the_file(self):
        # Recordings made before the wav header fix: a byte count in nframes
        path = os.path.join(self.dir, "a.wav")
        raw_wav(path, data=bytes(2 * 8000), nframes_bytes=4 * 8000)
        self.assertEqual(wav_duration(path), 0.5)

    def test_unreadable_is_zero(self):
        self.assertEqual(wav_duration(os.path.join(self.dir, "gone.wav")), 0.0)


if __name__ == "__main__":
    unittest.main()
