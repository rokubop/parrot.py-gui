"""Replays a fixture wav through the live recording pipeline, without a mic.

    python tests/recording.py

tests/smoke.py covers the file path, process_wav_file over a wav on disk. This
covers the other one: StreamRecorder, what a recording session drives frame by
frame while you make noises at the microphone. Until now only checked by hand.

The mic is the only part that cannot run on a build machine, so it is the only
part faked. The recorder asks the audio handle for a sample width and terminates
it, and starts, stops and closes the stream. Everything else it does with the
frames it is handed, so stand-ins for those two drive the whole thing.

Checked: the wav describes itself correctly and holds the audio that went in,
pausing and clearing keep it that way, a session writes the srt and thresholds
files the trainer reads. Not checked: audio quality, and the real stream
callback, which needs a device.

Exits 0 when the happy path works, 1 when it does not.
"""
import atexit
import math
import os
import re
import shutil
import sys
import tempfile
import time
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# A pop, because a discrete sound gives the segmenter something to find. The
# same eight seconds tests/smoke.py segments from file: 533 frames.
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "recordings", "pop", "source", "pop.wav")
LABEL = "pop"

# Canonical PCM header. Before it, what the audio is said to be; after it, the
# audio.
DATA_OFFSET = 44

SECONDS_TO_CLEAR = 3

# Same loose bounds as tests/smoke.py, and for the same reason: tuning a
# threshold is supposed to move the count, and that should not fail a build.
MIN_EVENTS = 3
MAX_EVENTS = 200

failures = []

def check(description, condition, detail=""):
    print(("  ok   " if condition else "  FAIL ") + description + (" " + detail if detail else ""))
    if not condition:
        failures.append(description)

def stage(name):
    print("\n" + name)
    return time.time()

def count_events(srt_path):
    with open(srt_path) as handle:
        blocks = re.split(r"\n\s*\n", handle.read().strip())
    return len([block for block in blocks if block.strip()])

def declared_length(wav_path):
    """What the header says the audio is, in bytes."""
    with wave.open(wav_path, "rb") as handle:
        return handle.getnframes() * handle.getnchannels() * handle.getsampwidth()

def actual_length(wav_path):
    """What the audio in the file is, in bytes."""
    return os.path.getsize(wav_path) - DATA_OFFSET


class FakeAudio:
    """pyaudio.PyAudio(). Asked for a sample width, terminated at the end."""

    def __init__(self):
        self.terminated = False

    def get_sample_size(self, audio_format):
        return pyaudio.get_sample_size(audio_format)

    def terminate(self):
        self.terminated = True


class FakeStream:
    """pyaudio.Stream. A real one pushes frames through a callback; here they go
    to the recorder directly, so only the lifecycle is worth keeping."""

    def __init__(self):
        self.calls = []

    def start_stream(self):
        self.calls.append("start")

    def stop_stream(self):
        self.calls.append("stop")

    def close(self):
        self.calls.append("close")


def read_fixture_frames(bytes_per_frame):
    with wave.open(FIXTURE, "rb") as handle:
        audio = handle.readframes(handle.getnframes())
    return [audio[start:start + bytes_per_frame]
            for start in range(0, len(audio) - bytes_per_frame, bytes_per_frame)]


def new_recorder(workdir, name):
    labels = [DetectionLabel(LABEL, 0, 0, "", 0, 0, 0, 0, 0)]
    state = DetectionState(CURRENT_DETECTION_STRATEGY, "recording", MS_PER_FRAME,
                           0, False, 0, 0, 0, 0, labels, None, [])
    return StreamRecorder(FakeAudio(), FakeStream(),
                          os.path.join(workdir, name + ".wav"),
                          os.path.join(workdir, name + ".v" + str(CURRENT_VERSION) + ".srt"),
                          state)


started = time.time()

t = stage("Importing the configuration")
import pyaudio
from config.config import CHANNELS, RATE, RECORD_SECONDS, SLIDING_WINDOW_AMOUNT
from lib.stream_processing import CURRENT_VERSION, CURRENT_DETECTION_STRATEGY
from lib.stream_recorder import StreamRecorder
from lib.typing import DetectionLabel, DetectionState

BYTES_PER_FRAME = round(RATE * RECORD_SECONDS / SLIDING_WINDOW_AMOUNT) * CHANNELS * 2
MS_PER_FRAME = math.floor(RECORD_SECONDS / SLIDING_WINDOW_AMOUNT * 1000)
print("  took %.1fs, with no input device attached" % (time.time() - t))

# Rebound so that a local run cannot touch your own recordings.
workdir = tempfile.mkdtemp(prefix="parrot_recording_")
atexit.register(shutil.rmtree, workdir, ignore_errors=True)

frames = read_fixture_frames(BYTES_PER_FRAME)
check("the fixture split into frames", len(frames) > 100, "(%d of %d bytes)" % (len(frames), BYTES_PER_FRAME))

t = stage("Recording %d frames through StreamRecorder" % len(frames))
recorder = new_recorder(workdir, "session")
recorder.resume()
for frame in frames:
    recorder.add_audio_frame(frame)
recorder.stop()
print("  took %.1fs" % (time.time() - t))

source_wav = os.path.join(workdir, "session.wav")
srt_file = os.path.join(workdir, "session.v" + str(CURRENT_VERSION) + ".srt")
thresholds_file = os.path.join(workdir, "session_thresholds.txt")

check("the source wav was written", os.path.exists(source_wav))
if os.path.exists(source_wav):
    with wave.open(source_wav, "rb") as handle:
        check("it is mono", handle.getnchannels() == CHANNELS, "(%d)" % handle.getnchannels())
        check("it is 16 bit", handle.getsampwidth() == 2, "(%d bytes)" % handle.getsampwidth())
        check("it is at the recording rate", handle.getframerate() == RATE, "(%d)" % handle.getframerate())

    # Read past the header, not through it: what the audio is has to stay a
    # separate question from what the header claims.
    with open(source_wav, "rb") as handle:
        written = handle.read()[DATA_OFFSET:]

    # The header is patched by hand after every append, so it can disagree with
    # the file underneath it and nothing would notice until the audio is read.
    check("the header declares the audio that is there",
          declared_length(source_wav) == actual_length(source_wav),
          "(says %d, holds %d)" % (declared_length(source_wav), actual_length(source_wav)))
    check("the audio is the fixture, in order", written == b"".join(frames)[:len(written)])

    # Frames append in batches of fifteen and pause() rolls back what is not
    # written yet, so a take loses its last part-batch, up to 210ms. Bounded,
    # not asserted exactly: this is the recorder as it stands, not a claim that
    # dropping the tail is right.
    dropped = len(frames) - len(written) // BYTES_PER_FRAME
    check("a take loses no more than the unwritten batch", 0 <= dropped < 15,
          "(%d frames, %dms)" % (dropped, dropped * MS_PER_FRAME))

check("the srt was written", os.path.exists(srt_file))
if os.path.exists(srt_file):
    events = count_events(srt_file)
    check("it holds a workable number of events", MIN_EVENTS <= events <= MAX_EVENTS, "(%d)" % events)
check("the thresholds file was written", os.path.exists(thresholds_file))

check("the stream was started, stopped and closed",
      recorder.stream.calls == ["start", "stop", "close"], str(recorder.stream.calls))
check("the audio handle was terminated", recorder.audio.terminated)

t = stage("Clearing the last %d seconds" % SECONDS_TO_CLEAR)
recorder = new_recorder(workdir, "cleared")
recorder.resume()
for frame in frames:
    recorder.add_audio_frame(frame)
recorder.pause()
cleared_wav = os.path.join(workdir, "cleared.wav")
length_before = actual_length(cleared_wav)
recorder.clear(SECONDS_TO_CLEAR)
print("  took %.1fs" % (time.time() - t))

removed = length_before - actual_length(cleared_wav)
expected_removed = math.floor(SECONDS_TO_CLEAR * 1000 / MS_PER_FRAME) * BYTES_PER_FRAME
check("the audio was dropped from the file", removed == expected_removed,
      "(%d bytes, wanted %d)" % (removed, expected_removed))
check("the header still declares the audio that is there",
      declared_length(cleared_wav) == actual_length(cleared_wav),
      "(says %d, holds %d)" % (declared_length(cleared_wav), actual_length(cleared_wav)))

print("\n" + "-" * 60)
if failures:
    print("FAILED after %.1fs" % (time.time() - started))
    for failure in failures:
        print("  " + failure)
    sys.exit(1)
print("Recorded, paused and cleared a session in %.1fs" % (time.time() - started))
