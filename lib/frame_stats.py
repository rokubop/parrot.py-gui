"""Incrementally cached dBFS / spectral_flux arrays over detection frames.

A frame's stats never change after creation and frames are only appended or
truncated from the end, so the cached prefix stays valid. Replaces per-call
O(n) list comprehensions that made a whole recording O(n^2).
"""
import numpy as np


def stat_arrays(detection_state, detection_frames):
    """Return (dBFS, spectral_flux) numpy arrays over all frames."""
    n = len(detection_frames)
    buf = getattr(detection_state, "_stat_buf", None)
    if buf is None:
        buf = {"dBFS": np.empty(max(64, n), dtype=np.float64),
               "sf": np.empty(max(64, n), dtype=np.float64), "len": 0}
        detection_state._stat_buf = buf

    valid = buf["len"]
    if n < valid:
        # Frames were truncated from the end (pause/clear); prefix is still valid.
        buf["len"] = n
    elif n > valid:
        if n > buf["dBFS"].size:
            cap = max(buf["dBFS"].size * 2, n)
            for key in ("dBFS", "sf"):
                grown = np.empty(cap, dtype=np.float64)
                grown[:valid] = buf[key][:valid]
                buf[key] = grown
        for idx in range(valid, n):
            frame = detection_frames[idx]
            buf["dBFS"][idx] = frame.dBFS
            buf["sf"][idx] = frame.spectral_flux
        buf["len"] = n
    return buf["dBFS"][:n], buf["sf"][:n]


def drop_cache(detection_state):
    if hasattr(detection_state, "_stat_buf"):
        del detection_state._stat_buf
