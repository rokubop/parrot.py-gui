import os
import glob
import math
import json
import filecmp
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal
from config.config import DATA_DIR, RECORDINGS_FOLDER, CLASSIFIER_FOLDER, RECORD_SECONDS, SLIDING_WINDOW_AMOUNT
from lib.srt import count_total_label_ms, ms_to_srt_timestring
from lib.stream_processing import CURRENT_VERSION
from gui.services import library_ops
from gui.services.talon_discovery import discover_talon, compare_model_files, TalonDiscoveryResult

NOTES_PATH = os.path.join(DATA_DIR, "notes.json")


class AppState(QObject):
    recordings_changed = pyqtSignal()
    models_changed = pyqtSignal()
    talon_status_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._talon_result = None
        self._model_cache = {}
        self.models_changed.connect(self._invalidate_model_cache)

    def get_sound_labels(self):
        """Returns list of sound label directory names from data/recordings/."""
        labels = []
        if os.path.exists(RECORDINGS_FOLDER):
            for entry in sorted(os.listdir(RECORDINGS_FOLDER)):
                full_path = os.path.join(RECORDINGS_FOLDER, entry)
                if os.path.isdir(full_path):
                    labels.append(entry)
        return labels

    def get_recordings_for_label(self, label):
        """Returns list of dicts with wav_path and srt_path for a label."""
        recordings = []
        source_dir = os.path.join(RECORDINGS_FOLDER, label, "source")
        segments_dir = os.path.join(RECORDINGS_FOLDER, label, "segments")
        if not os.path.isdir(source_dir):
            return recordings

        wav_files = sorted([f for f in os.listdir(source_dir) if f.endswith(".wav")])
        for wav_file in wav_files:
            wav_path = os.path.join(source_dir, wav_file)
            # Find matching SRT file
            base = wav_file.replace(".wav", "")
            srt_path = None
            if os.path.isdir(segments_dir):
                srt_candidates = [
                    os.path.join(segments_dir, base + ".MANUAL.srt"),
                    os.path.join(segments_dir, base + ".v" + str(CURRENT_VERSION) + ".srt"),
                ]
                for candidate in srt_candidates:
                    if os.path.exists(candidate):
                        srt_path = candidate
                        break
            recordings.append({"wav_path": wav_path, "srt_path": srt_path, "filename": wav_file})
        return recordings

    def get_label_duration_ms(self, label):
        """Returns total recorded ms for a label."""
        ms_per_frame = math.floor(RECORD_SECONDS / SLIDING_WINDOW_AMOUNT * 1000)
        return count_total_label_ms(label, os.path.join(RECORDINGS_FOLDER, label), ms_per_frame)

    def get_models(self):
        """Returns list of model files (.pkl and .pth.tar) in data/models/."""
        models = []
        if os.path.exists(CLASSIFIER_FOLDER):
            for f in sorted(os.listdir(CLASSIFIER_FOLDER)):
                if f.endswith(".pkl") or f.endswith(".pth.tar"):
                    models.append({"filename": f, "path": os.path.join(CLASSIFIER_FOLDER, f)})
        return models

    def get_model_names(self):
        """Returns list of unique model base names (without .pkl extension)."""
        names = set()
        if os.path.exists(CLASSIFIER_FOLDER):
            for f in os.listdir(CLASSIFIER_FOLDER):
                if f.endswith(".pkl") and not f.endswith(".pth.tar"):
                    names.add(f.replace(".pkl", ""))
        return sorted(names)

    def get_model_metadata(self, model_name, load_weights=False):
        """Load model metadata. Fast by default (file sizes only).
        Set load_weights=True to also load labels/accuracy from pkl/pth.tar (slow).
        """
        cache_key = (model_name, load_weights)
        if cache_key in self._model_cache:
            return self._model_cache[cache_key]

        pkl_path = os.path.join(CLASSIFIER_FOLDER, model_name + ".pkl")
        meta = {
            "name": model_name,
            "pkl_path": pkl_path,
            "labels": [],
            "net_count": 0,
            "nets": [],
            "best_accuracy": None,
            "total_size_bytes": 0,
            "pkl_exists": os.path.isfile(pkl_path),
            "weights_loaded": load_weights,
        }

        if meta["pkl_exists"]:
            meta["total_size_bytes"] += os.path.getsize(pkl_path)

        # Find matching BEST weight files (fast - just file listing)
        best_files = sorted(glob.glob(pkl_path + "_*-BEST-weights.pth.tar"))
        meta["net_count"] = len(best_files)

        for bf in best_files:
            meta["total_size_bytes"] += os.path.getsize(bf)
            meta["nets"].append({"path": bf, "accuracy": None, "loss": None, "epoch": None})

        # Count non-BEST weight file sizes
        all_weight_files = glob.glob(pkl_path + "_*-weights.pth.tar")
        for wf in all_weight_files:
            if wf not in best_files:
                meta["total_size_bytes"] += os.path.getsize(wf)

        # Heavy loading: labels from joblib, accuracy from torch
        if load_weights:
            # Labels from pkl
            if meta["pkl_exists"]:
                try:
                    import joblib
                    model = joblib.load(pkl_path)
                    if hasattr(model, "classes_"):
                        meta["labels"] = list(model.classes_)
                except Exception:
                    pass

            # Accuracy/labels from pth.tar
            for net_info in meta["nets"]:
                try:
                    import torch
                    state = torch.load(net_info["path"], map_location="cpu", weights_only=False)
                    net_info["accuracy"] = state.get("accuracy")
                    net_info["loss"] = state.get("loss")
                    net_info["epoch"] = state.get("epoch")
                    if not meta["labels"] and "labels" in state:
                        meta["labels"] = list(state["labels"])
                except Exception:
                    pass

            accuracies = [n["accuracy"] for n in meta["nets"] if n["accuracy"] is not None]
            if accuracies:
                meta["best_accuracy"] = max(accuracies)

        self._model_cache[cache_key] = meta
        return meta

    def get_all_model_details(self):
        """Returns list of metadata dicts for all models."""
        return [self.get_model_metadata(name) for name in self.get_model_names()]

    def get_talon_status(self) -> TalonDiscoveryResult:
        """Run talon discovery (cached). Call refresh_talon() to re-run."""
        if self._talon_result is None:
            self._talon_result = discover_talon()
        return self._talon_result

    def refresh_talon(self):
        """Force re-discovery of Talon setup."""
        self._talon_result = None
        self._talon_result = discover_talon()
        self.talon_status_changed.emit()

    def get_active_model_name(self):
        """Determine the active model name.
        1. Match Talon's model to a local model via file comparison
        2. Fallback to most recently modified .pkl
        3. None if no models
        """
        talon = self.get_talon_status()
        model_names = self.get_model_names()
        if not model_names:
            return None

        # Try matching Talon's model file to a local one
        if talon.model_path_from_talon and os.path.isfile(talon.model_path_from_talon):
            for name in model_names:
                local_pkl = os.path.join(CLASSIFIER_FOLDER, name + ".pkl")
                if os.path.isfile(local_pkl):
                    cmp = compare_model_files(local_pkl, talon.model_path_from_talon)
                    if cmp["matches"]:
                        return name

        # Fallback: most recently modified pkl
        best_name = None
        best_mtime = 0
        for name in model_names:
            pkl_path = os.path.join(CLASSIFIER_FOLDER, name + ".pkl")
            if os.path.isfile(pkl_path):
                mtime = os.path.getmtime(pkl_path)
                if mtime > best_mtime:
                    best_mtime = mtime
                    best_name = name
        return best_name

    def is_first_run(self):
        """True if no recordings AND no models exist."""
        return len(self.get_sound_labels()) == 0 and len(self.get_model_names()) == 0

    def load_notes(self):
        """Load notes from data/notes.json."""
        if os.path.isfile(NOTES_PATH):
            try:
                with open(NOTES_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"global_notes": "", "model_notes": {}}

    def save_notes(self, notes):
        """Save notes to data/notes.json."""
        os.makedirs(os.path.dirname(NOTES_PATH), exist_ok=True)
        with open(NOTES_PATH, "w", encoding="utf-8") as f:
            json.dump(notes, f, indent=2)

    def _invalidate_model_cache(self):
        self._model_cache.clear()

    def refresh(self):
        """Emit signals to refresh all views."""
        self.recordings_changed.emit()
        self.models_changed.emit()

    # ---- mutations (thin wrappers over library_ops + signal emit) -------
    # Each returns whatever the op returns (e.g. the new name) and emits the
    # relevant change signal so every view rebuilds. Errors propagate as
    # LibraryOpError for the caller to display.

    def create_sound(self, name):
        label = library_ops.create_sound(name)
        self.recordings_changed.emit()
        return label

    def rename_sound(self, old, new):
        label = library_ops.rename_sound(old, new)
        self.recordings_changed.emit()
        return label

    def clone_sound(self, src, new):
        label = library_ops.clone_sound(src, new)
        self.recordings_changed.emit()
        return label

    def delete_sound(self, label):
        library_ops.delete_sound(label)
        self.recordings_changed.emit()

    def delete_recording(self, wav_path):
        library_ops.delete_recording(wav_path)
        self.recordings_changed.emit()

    def rename_recording(self, wav_path, new_base):
        new_wav = library_ops.rename_recording(wav_path, new_base)
        self.recordings_changed.emit()
        return new_wav

    def move_recording(self, wav_path, dest_label):
        new_wav = library_ops.move_recording(wav_path, dest_label)
        self.recordings_changed.emit()
        return new_wav

    def delete_model(self, name):
        library_ops.delete_model(name)
        self.models_changed.emit()

    def rename_model(self, old, new):
        name = library_ops.rename_model(old, new)
        self.models_changed.emit()
        return name

    def clone_model(self, old, new):
        name = library_ops.clone_model(old, new)
        self.models_changed.emit()
        return name
