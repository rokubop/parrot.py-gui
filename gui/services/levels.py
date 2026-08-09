"""Frame-by-frame dBFS for a saved wav, framed the way detection frames it.

The threshold control is in dBFS and nothing on screen was, so a number had to
be applied before you could see what it did. A lane drawn from this carries the
threshold as a line over the level, which is the same question answered before
the re-detect instead of after it.

Two things this deliberately does not do:

* It does not compute its own decibels. ``determine_dBFS`` reads the samples as
  4-byte ints and divides by 32767 squared, which is not textbook dBFS - but it
  is what the detector compares its threshold against, so the lane has to agree
  with it rather than with a formula.
* It does not re-frame. A detection frame is the last ``SLIDING_WINDOW_AMOUNT``
  blocks, advancing one block at a time, and the srt places frame *j* at
  ``j * ms_per_frame``. Same grid here, so a peak in the lane sits under the
  blue band it produced.
"""
import wave
import numpy as np

from config.config import RATE, RECORD_SECONDS, SLIDING_WINDOW_AMOUNT
from lib.signal_processing import determine_dBFS

# 16-bit silence bottoms out around here, and it is the low end of every
# threshold control in the app.
FLOOR_DBFS = -96.0


def hop_samples(sample_rate=None):
    """Samples per detection frame step (one block)."""
    return round((sample_rate or RATE) * RECORD_SECONDS / SLIDING_WINDOW_AMOUNT)


def frame_dbfs(wav_path):
    """``(times, values)`` - one dBFS reading per detection frame.

    ``times`` are the frame start times in seconds, on the same grid the srt
    uses. Returns two empty arrays for anything unreadable or shorter than one
    frame; callers draw nothing rather than special-casing.
    """
    try:
        wf = wave.open(wav_path, "rb")
        channels = wf.getnchannels()
        rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
        wf.close()
    except Exception:
        return np.zeros(0), np.zeros(0)

    data = np.frombuffer(raw, dtype=np.int16)
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1).astype(np.int16)

    hop = hop_samples(rate)
    window = hop * SLIDING_WINDOW_AMOUNT
    if hop <= 0 or len(data) < window:
        return np.zeros(0), np.zeros(0)

    # Frame j covers blocks j-1 and j, so the window starting at s belongs to
    # the frame one hop later.
    starts = np.arange(0, len(data) - window + 1, hop)
    values = np.empty(len(starts), dtype=np.float32)
    for i, s in enumerate(starts):
        values[i] = determine_dBFS(data[s:s + window])
    np.clip(values, FLOOR_DBFS, 0.0, out=values)
    times = (starts + hop) / float(rate)
    return times, values
