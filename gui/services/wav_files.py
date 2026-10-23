"""Reading parrot.py's wav files for display. Qt-free."""
import os
import wave

import numpy as np

DAMAGED = "Not a wav file, or a damaged one"


class UnreadableWav(Exception):
    """Why a recording can't be shown, worded for the user."""


def read_wav(path):
    """(mono float32 samples in [-1, 1], sample rate). Raises UnreadableWav."""
    try:
        with wave.open(path, "rb") as wf:
            bits = wf.getsampwidth() * 8
            if bits != 16:
                # What parrot.py records. Anything else would plot as noise
                raise UnreadableWav(f"{bits}-bit audio, parrot.py records 16-bit")
            channels = wf.getnchannels()
            rate = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
    except UnreadableWav:
        raise
    except OSError:
        raise UnreadableWav("The file couldn't be opened")
    except wave.Error as exc:
        if str(exc).startswith("unknown format"):
            raise UnreadableWav("A wav format parrot.py doesn't record")
        raise UnreadableWav(DAMAGED)
    except Exception:
        raise UnreadableWav(DAMAGED)
    if not rate:
        raise UnreadableWav(DAMAGED)

    # Cut off mid-write, say by a crash while recording: keep what's whole
    raw = raw[:len(raw) - len(raw) % (2 * channels)]
    if not raw:
        raise UnreadableWav("The recording is empty")
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data / 32768.0, rate


def _frames_the_file_holds(path, channels, sampwidth):
    """Recordings made before the wav header fix store a byte count in
    nframes, double the real length. The file size can't be wrong."""
    data_bytes = max(0, os.path.getsize(path) - 44)  # standard PCM header
    return data_bytes // (channels * sampwidth)


def wav_duration(path):
    """Seconds, from the header: decoding every file just for its length is
    too slow."""
    try:
        with wave.open(path, "rb") as wf:
            rate = wf.getframerate()
            frames = min(wf.getnframes(), _frames_the_file_holds(
                path, wf.getnchannels(), wf.getsampwidth()))
        return frames / rate if rate else 0.0
    except Exception:
        return 0.0
