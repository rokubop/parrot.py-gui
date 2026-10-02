"""dBFS and spectral flux of every detection frame, as arrays that grow with
the recording instead of being rebuilt from the frame list on every call.

A frame's stats never change once it exists. The recorder does cut frames off
the end on pause and clear, so the cache checks its last frame is still there
and starts over if not.
"""
import numpy as np


def stat_arrays(detection_state, detection_frames):
    """(dBFS, spectral_flux) arrays over all frames."""
    n = len(detection_frames)
    cache = getattr(detection_state, "_stat_cache", None)
    if cache is None or cache["len"] > n or \
            (cache["len"] > 0 and detection_frames[cache["len"] - 1] is not cache["last"]):
        cache = {"dBFS": np.empty(max(64, n)), "sf": np.empty(max(64, n)), "len": 0, "last": None}
        detection_state._stat_cache = cache

    cached = cache["len"]
    if n > cached:
        if n > cache["dBFS"].size:
            for key in ("dBFS", "sf"):
                grown = np.empty(max(cache[key].size * 2, n))
                grown[:cached] = cache[key][:cached]
                cache[key] = grown
        for index in range(cached, n):
            cache["dBFS"][index] = detection_frames[index].dBFS
            cache["sf"][index] = detection_frames[index].spectral_flux
        cache["len"] = n
        cache["last"] = detection_frames[-1]
    return cache["dBFS"][:n], cache["sf"][:n]
