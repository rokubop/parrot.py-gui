"""Debug-only test profiles: the app's states on demand, from honest data.

Sounds are synthesized noise bursts written through the app's real
segmentation (``segment_worker.redetect`` -> ``process_wav_file``), so the
Sounds page, duration ratings and even training all see
genuine recordings. Models cannot be synthesized - a real pair is copied
from Main or any non-test profile when one exists; the model-bearing
profiles are skipped (with a note) otherwise. The Talon axis rides the
per-profile simulation hook: ``none``, or a path to a mock Talon home
bundled inside the profile, complete with a parseable
parrot_integration.py, patterns.json and the copied model.
"""
import json
import os
import shutil
import wave
import zlib

import numpy as np

from config.config import RATE
from gui.services import profiles

PREFIX = "test-"

_INTEGRATION = """# Mock parrot integration for GUI state testing.
PARROT_HOME = TALON_HOME / 'user/parrot'
pattern_path = str(PARROT_HOME / 'patterns.json')
model_path = str(PARROT_HOME / 'model.pkl')
"""


def _write_burst_wav(path, seconds, seed):
    """Discrete noise pops over a quiet floor: short varied bursts with soft
    envelopes, so detection's auto-calibration sees the same shape a real
    take of a popped sound has. A floor near the threshold estimate (or
    uniform, back-to-back bursts) makes calibration classify the whole file
    as one endless sound and emit no events."""
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    audio = rng.normal(0, 5, n)  # ~-76 dBFS floor, well under any threshold
    pos = int(0.4 * RATE)
    while pos < n - RATE // 2:
        burst_len = int(rng.integers(90, 220) * RATE // 1000)
        end = min(pos + burst_len, n)
        amp = rng.integers(4000, 13000)
        audio[pos:end] += rng.normal(0, amp, end - pos) * np.hanning(end - pos)
        pos = end + int(rng.integers(500, 1300) * RATE // 1000)
    data = np.clip(audio, -32000, 32000).astype(np.int16)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes(data.tobytes())


def _make_sound(profile_dir, label, seconds, seed):
    # Paths passed explicitly: segment_worker.redetect derives them from the
    # ACTIVE data root, which would write into the wrong profile's data.
    # Detection runs with a manual threshold override (the same path a user's
    # manual threshold takes): auto-calibration needs 10+ spectral-flux
    # valleys before it sets a threshold at all, and synthetic bursts sit
    # close enough to that edge that some seeds detected nothing.
    from lib.stream_processing import process_wav_file
    wav = os.path.join(profile_dir, "recordings", label, "source",
                       "mock_take_1.wav")
    _write_burst_wav(wav, seconds, seed)
    seg = os.path.join(profile_dir, "recordings", label, "segments")
    os.makedirs(seg, exist_ok=True)
    thresholds = os.path.join(seg, "mock_take_1_thresholds.txt")
    with open(thresholds, "w", encoding="utf-8") as f:
        f.write(f"{label}_duration_type=discrete\n{label}_min_dbfs=-30\n")
    process_wav_file(
        wav,
        os.path.join(seg, "mock_take_1.MANUAL.srt"),
        os.path.join(seg, "mock_take_1_comparison.wav"),
        None, [label], override_file=thresholds)


def _find_model_pair():
    """(pkl_path, pth_path_or_None) from Main or any non-test profile."""
    roots = [profiles.MAIN_DATA_DIR] + [
        profiles.profile_data_dir(n) for n in profiles.list_profiles()
        if not n.startswith(PREFIX)]
    for root in roots:
        models_dir = os.path.join(root, "models")
        if not os.path.isdir(models_dir):
            continue
        for name in sorted(os.listdir(models_dir)):
            if name.endswith(".pkl"):
                pkl = os.path.join(models_dir, name)
                pth = os.path.join(models_dir,
                                   name[:-len(".pkl")] + ".pth.tar")
                return pkl, (pth if os.path.isfile(pth) else None)
    return None


def _copy_model(profile_dir, pair):
    models_dir = os.path.join(profile_dir, "models")
    os.makedirs(models_dir, exist_ok=True)
    pkl, pth = pair
    shutil.copy2(pkl, models_dir)
    if pth:
        shutil.copy2(pth, models_dir)


def _make_mock_talon(profile_dir, pair, labels):
    """A fake Talon home inside the profile that real discovery accepts:
    integration file, patterns for each label, and the deployed model."""
    parrot = os.path.join(profile_dir, "mock-talon", "user", "parrot")
    os.makedirs(parrot, exist_ok=True)
    with open(os.path.join(parrot, "parrot_integration.py"), "w",
              encoding="utf-8") as f:
        f.write(_INTEGRATION)
    patterns = {label: {"sounds": [label],
                        "threshold": {">power": 6, ">probability": 0.9}}
                for label in labels}
    with open(os.path.join(parrot, "patterns.json"), "w",
              encoding="utf-8") as f:
        json.dump({"patterns": patterns}, f, indent=2)
    shutil.copy2(pair[0], os.path.join(parrot, "model.pkl"))
    return os.path.join(profile_dir, "mock-talon")


def create_test_profiles():
    """Build the fleet. Returns (created_names, notes). Existing test
    profiles are left alone, so this is safe to run repeatedly."""
    created, notes = [], []
    pair = _find_model_pair()
    existing = set(profiles.list_profiles())

    def build(name, labels_seconds, with_model, talon, mock_talon_labels=None):
        if name in existing:
            notes.append(f"{name} already exists, left as is")
            return
        profiles.create_empty(name)
        root = profiles.profile_data_dir(name)
        for i, (label, seconds) in enumerate(labels_seconds):
            _make_sound(root, label, seconds,
                        seed=zlib.crc32(name.encode()) % 10_000 + i)
        if with_model:
            _copy_model(root, pair)
        if mock_talon_labels is not None:
            talon = _make_mock_talon(root, pair, mock_talon_labels)
        meta = profiles.read_meta(name)
        meta["talon"] = talon
        profiles.write_meta(name, meta)
        profiles.freeze(name)  # reset returns to the pristine mock state
        created.append(name)

    build("test-empty", [], False, "none")
    build("test-2-sounds", [("pop", 60), ("hiss", 60)], False, "none")
    build("test-10-sounds",
          [(label, 35) for label in ("pop", "hiss", "ah", "oh", "ee", "cluck",
                                     "tut", "shush", "guh", "err")],
          False, "none")
    if pair:
        build("test-model-no-talon", [("pop", 60), ("hiss", 60)], True, "none")
        build("test-full-setup",
              [("pop", 75), ("hiss", 75), ("ah", 75), ("oh", 75)], True,
              "real", mock_talon_labels=["pop", "hiss", "ah", "oh"])
    else:
        notes.append("no model found on this machine, so test-model-no-talon "
                     "and test-full-setup were skipped; rerun once any "
                     "profile has a trained model")
    return created, notes
