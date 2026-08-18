"""Frame-by-frame dBFS for a saved wav, on the grid detection uses.

Two things it deliberately does not do:

- No decibels of its own. ``determine_dBFS`` reads samples as 4-byte ints over
  32767 squared. Not textbook dBFS, but it is what the threshold is compared
  against, so a formula here would draw the line in the wrong place.
- No re-framing. A frame is the last ``SLIDING_WINDOW_AMOUNT`` blocks, one block
  apart, and the srt places frame j at ``j * ms_per_frame``. Same grid, so a
  peak sits under the band it produced.
"""
import wave
import numpy as np

from config.config import RATE, RECORD_SECONDS, SLIDING_WINDOW_AMOUNT
from lib.signal_processing import determine_dBFS

# Where 16-bit silence bottoms out, and the low end of every threshold control.
FLOOR_DBFS = -96.0


def hop_samples(sample_rate=None):
    """Samples per detection frame step (one block)."""
    return round((sample_rate or RATE) * RECORD_SECONDS / SLIDING_WINDOW_AMOUNT)


def frame_dbfs(wav_path):
    """``(times, values)`` - one dBFS reading per detection frame.

    Times are frame starts in seconds, the grid the srt uses. Empty arrays for
    anything unreadable or shorter than a frame, so callers just draw nothing.
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

    # Frame j covers blocks j-1 and j, so a window at s belongs one hop later.
    starts = np.arange(0, len(data) - window + 1, hop)
    values = np.empty(len(starts), dtype=np.float32)
    for i, s in enumerate(starts):
        values[i] = determine_dBFS(data[s:s + window])
    np.clip(values, FLOOR_DBFS, 0.0, out=values)
    times = (starts + hop) / float(rate)
    return times, values
