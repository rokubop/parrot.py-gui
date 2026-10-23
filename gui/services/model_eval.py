"""Model evaluation core - shared by the accuracy test (recorded segments)
and the live mic test (streaming frames). Qt-free.

Features are extracted exactly the way training extracts them
(load_wav_data_from_srt / feature_engineering_raw with the model's own
settings), so the numbers here measure the model users actually deploy.
"""
import os

import joblib
import numpy as np

from config.config import (RECORDINGS_FOLDER, RECORD_SECONDS,
                           SLIDING_WINDOW_AMOUNT, RATE)
from lib.wav import load_wav_data_from_srt
from lib.machinelearning import feature_engineering_raw


def load_model(model_path):
    return joblib.load(model_path)


def model_input_type(model):
    settings = getattr(model, "settings", None) or {}
    return settings.get("FEATURE_ENGINEERING_TYPE", 4)


def model_rate_mismatch(model):
    """The model's expected sample rate when it differs from the config."""
    settings = getattr(model, "settings", None) or {}
    model_rate = settings.get("RATE")
    if model_rate and model_rate != RATE:
        return model_rate
    return None


def srt_for_source(label_dir):
    """{source_wav_path: srt_path} with the same choice rule as training:
    a .MANUAL.srt wins, otherwise the highest .v<N>.srt."""
    segments_dir = os.path.join(label_dir, "segments")
    source_dir = os.path.join(label_dir, "source")
    mapping = {}
    if not (os.path.isdir(segments_dir) and os.path.isdir(source_dir)):
        return mapping
    srt_files = [f for f in os.listdir(segments_dir) if f.endswith(".srt")]
    for source_file in os.listdir(source_dir):
        if not source_file.endswith(".wav"):
            continue
        key = source_file[:-4]
        candidates = [f for f in srt_files if f.startswith(key)]
        if not candidates:
            continue
        chosen = candidates[0]
        for candidate in candidates:
            if chosen.endswith(".MANUAL.srt"):
                break
            if candidate.endswith(".MANUAL.srt"):
                chosen = candidate
            else:
                try:
                    if int(candidate[:-4].replace(key + ".v", "")) > \
                            int(chosen[:-4].replace(key + ".v", "")):
                        chosen = candidate
                except ValueError:
                    continue
        mapping[os.path.join(source_dir, source_file)] = \
            os.path.join(segments_dir, chosen)
    return mapping


def sound_features(label, input_type, max_samples=2000):
    """Feature vectors for one sound's detected segments (no augmentation,
    no offsets - evaluation wants the plain samples)."""
    label_dir = os.path.join(RECORDINGS_FOLDER, label)
    features = []
    for source_wav, srt in sorted(srt_for_source(label_dir).items()):
        try:
            features.extend(load_wav_data_from_srt(
                srt, source_wav, input_type, with_offset=False))
        except Exception:
            continue
        if len(features) >= max_samples:
            break
    return features[:max_samples]


def evaluate_model(model_path, labels, progress_callback=None,
                   max_per_sound=2000, batch_size=512):
    """Classify every sound's recorded segments with the model.
    Returns {"per_sound": {label: {"samples", "recall", "confusions"}},
             "precision": {label: p}, "overall": fraction,
             "skipped": [labels], "rate_mismatch": int|None}"""
    model = load_model(model_path)
    input_type = model_input_type(model)
    classes = list(model.classes_)
    per_sound = {}
    skipped = []
    predicted_counts = {c: 0 for c in classes}      # all predictions of c
    correct_counts = {c: 0 for c in classes}        # predictions of c that were c
    total, total_correct = 0, 0

    for label in labels:
        if label not in classes:
            skipped.append(label)
            continue
        if progress_callback:
            progress_callback(f"Loading {label}…")
        features = sound_features(label, input_type, max_per_sound)
        if not features:
            skipped.append(label)
            continue
        if progress_callback:
            progress_callback(f"Classifying {label} ({len(features)} samples)…")
        X = np.array(features, dtype=np.float32)
        confusions = {}
        correct = 0
        for start in range(0, len(X), batch_size):
            probabilities = model.predict_proba(X[start:start + batch_size])
            winners = np.argmax(probabilities, axis=1)
            for w in winners:
                predicted = classes[int(w)]
                predicted_counts[predicted] += 1
                if predicted == label:
                    correct += 1
                    correct_counts[predicted] += 1
                else:
                    confusions[predicted] = confusions.get(predicted, 0) + 1
        per_sound[label] = {
            "samples": len(X),
            "recall": correct / len(X),
            "confusions": dict(sorted(confusions.items(), key=lambda kv: -kv[1])),
        }
        total += len(X)
        total_correct += correct

    precision = {}
    for label in per_sound:
        if predicted_counts[label]:
            precision[label] = correct_counts[label] / predicted_counts[label]
    return {
        "per_sound": per_sound,
        "precision": precision,
        "overall": (total_correct / total) if total else 0.0,
        "skipped": skipped,
        "rate_mismatch": model_rate_mismatch(model),
    }


class FrameClassifier:
    """Streaming classifier: feed raw int16 mono chunks (RECORD_SECONDS /
    SLIDING_WINDOW_AMOUNT each); once the sliding window fills, every chunk
    yields {label: probability}. Same windowing as recording/inference."""

    def __init__(self, model):
        self.model = model
        self.input_type = model_input_type(model)
        self.classes = list(model.classes_)
        self._window = []

    def add_chunk(self, raw_bytes):
        self._window.append(raw_bytes)
        if len(self._window) < SLIDING_WINDOW_AMOUNT:
            return None
        self._window = self._window[-SLIDING_WINDOW_AMOUNT:]
        wave_data = np.frombuffer(b"".join(self._window), dtype=np.int16)
        features = feature_engineering_raw(
            wave_data, RATE, 0, RECORD_SECONDS, self.input_type)[0]
        probabilities = self.model.predict_proba(
            np.array([features], dtype=np.float32))[0]
        return {self.classes[i]: float(p) for i, p in enumerate(probabilities)}
