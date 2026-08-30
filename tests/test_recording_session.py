"""A whole recording session, without a microphone.

test_stream_recorder.py covers the header the recorder patches by hand. This
covers the session around it: fixture audio in through add_audio_frame, an srt
and a thresholds file out through stop, and the stream and audio handle closed
on the way. The path a person drives by making noises at a mic, which is the
half tests/smoke.py does not reach.

The mic is faked because it is the only part a build machine cannot have. The
recorder asks the audio handle for a sample width and terminates it, and starts,
stops and closes the stream. Everything else it does with the frames it is
handed, so those two stand-ins are enough.
"""
import math
import os
import re
import shutil
import sys
import tempfile
import unittest
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import config.config
from lib.stream_recorder import StreamRecorder
from lib.typing import DetectionState, DetectionLabel

# A pop, because a discrete sound gives the segmenter something to find. The
# same eight seconds tests/smoke.py segments from file.
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "recordings", "pop", "source", "pop.wav")
LABEL = "pop"

FRAME_BYTES = round(config.config.RATE * config.config.RECORD_SECONDS
                    / config.config.SLIDING_WINDOW_AMOUNT) * 2
MS_PER_FRAME = math.floor(config.config.RECORD_SECONDS
                          / config.config.SLIDING_WINDOW_AMOUNT * 1000)
WAV_HEADER_SIZE = 44

# Frames append in batches of this many
FRAMES_PER_BATCH = 15

# Nothing means a broken segmenter, one means the whole clip was heard as a
# single sound. Loose at the top because tuning a threshold is supposed to move
# the count, and that should not fail a build.
MIN_EVENTS = 3
MAX_EVENTS = 200


class SampleWidthOnly:
    # The recorder only asks the audio interface how wide a sample is
    def __init__(self):
        self.terminated = False

    def get_sample_size(self, audio_format):
        return 2   # paInt16

    def terminate(self):
        self.terminated = True


class RecordingStream:
    # A real stream pushes frames through a callback. Here they go to the
    # recorder directly, so only the lifecycle is worth keeping.
    def __init__(self):
        self.calls = []

    def start_stream(self):
        self.calls.append("start")

    def stop_stream(self):
        self.calls.append("stop")

    def close(self):
        self.calls.append("close")


def read_fixture_frames():
    with wave.open(FIXTURE, "rb") as handle:
        audio = handle.readframes(handle.getnframes())
    return [audio[start:start + FRAME_BYTES]
            for start in range(0, len(audio) - FRAME_BYTES, FRAME_BYTES)]


def count_srt_events(path):
    with open(path) as handle:
        blocks = re.split(r"\n\s*\n", handle.read().strip())
    return len([block for block in blocks if block.strip()])


class RecordingSessionTest(unittest.TestCase):
    """One session recorded once, since it runs the real detection over eight
    seconds of audio."""

    @classmethod
    def setUpClass(cls):
        workdir = tempfile.mkdtemp(prefix="parrot_session_")
        cls.addClassCleanup(shutil.rmtree, workdir, True)
        cls.wav_file = os.path.join(workdir, "session.wav")
        cls.srt_file = os.path.join(workdir, "session.v%d.srt" % config.config.CURRENT_VERSION)
        cls.thresholds_file = os.path.join(workdir, "session_thresholds.txt")

        cls.frames = read_fixture_frames()
        label = DetectionLabel(LABEL, 0, 0, "", 0, 0, 0, 0, 0)
        # No override labels, and an empty valley list rather than the None the
        # dataclass defaults to, the same as lib/record_data.py builds
        state = DetectionState(config.config.CURRENT_DETECTION_STRATEGY, "recording",
                               MS_PER_FRAME, 0, False, 0, 0, 0, 0, [label], None, [])

        cls.audio = SampleWidthOnly()
        cls.stream = RecordingStream()
        recorder = StreamRecorder(cls.audio, cls.stream, cls.wav_file, cls.srt_file, state)
        recorder.resume()
        for frame in cls.frames:
            recorder.add_audio_frame(frame)
        recorder.stop()

        with open(cls.wav_file, "rb") as handle:
            cls.written = handle.read()[WAV_HEADER_SIZE:]

    def test_the_audio_is_what_went_in(self):
        self.assertEqual(self.written, b"".join(self.frames)[:len(self.written)])

    def test_a_take_loses_no_more_than_the_unwritten_batch(self):
        # pause rolls back frames that have not been appended yet, so the end of
        # a take goes with them. Bounded rather than asserted exactly: this is
        # the recorder as it stands, not a claim that dropping the tail is right.
        dropped = len(self.frames) - len(self.written) // FRAME_BYTES
        self.assertGreaterEqual(dropped, 0)
        self.assertLess(dropped, FRAMES_PER_BATCH)

    def test_the_session_writes_an_srt_with_events_in_it(self):
        self.assertTrue(os.path.exists(self.srt_file))
        events = count_srt_events(self.srt_file)
        self.assertGreaterEqual(events, MIN_EVENTS)
        self.assertLessEqual(events, MAX_EVENTS)

    def test_the_session_writes_the_thresholds_the_next_run_reads(self):
        self.assertTrue(os.path.exists(self.thresholds_file))

    def test_the_stream_is_started_stopped_and_closed(self):
        self.assertEqual(self.stream.calls, ["start", "stop", "close"])

    def test_the_audio_handle_is_terminated(self):
        self.assertTrue(self.audio.terminated)


if __name__ == "__main__":
    unittest.main()
