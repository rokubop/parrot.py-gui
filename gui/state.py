import os
from PyQt6.QtCore import QObject, pyqtSignal
from gui.services import library_ops
from lib import models, recordings


class AppState(QObject):
    recordings_changed = pyqtSignal()
    models_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model_cache = {}
        self._label_cache = {}
        self._checkpoints = {}
        self._replay_times = None
        self._duration_cache = {}
        self.models_changed.connect(self._invalidate_model_cache)
        # Recording, trimming and re-segmenting all change these, and all of
        # them emit recordings_changed.
        self.recordings_changed.connect(self._invalidate_duration_cache)

    def get_sound_labels(self):
        return recordings.get_labels()

    def get_recordings_for_label(self, label):
        return recordings.get_recordings(label)

    def get_label_duration_ms(self, label):
        """Cached: it parses every srt the label has."""
        if label not in self._duration_cache:
            self._duration_cache[label] = recordings.get_detected_ms(label)
        return self._duration_cache[label]

    def get_model_names(self):
        return models.get_model_names()

    def get_model_metadata(self, model_name, load_weights=False):
        """Load model metadata. Fast by default (file sizes only).
        Set load_weights=True to also load labels/accuracy from pkl/pth.tar (slow).
        """
        cache_key = (model_name, load_weights)
        if cache_key in self._model_cache:
            meta = self._model_cache[cache_key]
            # Cheap, and a checkpoint read since the last call may have turned
            # up a better answer than the one cached here.
            meta["trained_at"], meta["trained_at_source"] = \
                self._trained_at(model_name)
            return meta

        pkl_path = models.get_model_path(model_name)
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
            "trained_at": None,
            "trained_at_source": None,
        }

        if meta["pkl_exists"]:
            meta["trained_at"], meta["trained_at_source"] = \
                self._trained_at(model_name)

        meta["total_size_bytes"] = sum(
            os.path.getsize(f) for f in models.get_model_files(model_name))

        best_files = models.get_best_checkpoint_paths(model_name)
        meta["net_count"] = len(best_files)
        for bf in best_files:
            meta["nets"].append({"path": bf, "accuracy": None, "loss": None,
                                 "epoch": None, "label_accuracy": None,
                                 "combined_accuracy": None, "label_frames": None})

        if load_weights:
            # A checkpoint is ~3.8 MB against the pkl's ~38 MB, so read labels
            # here; the pkl is the fallback for a model with no checkpoints
            # (one combined from other pkls).
            for net_info in meta["nets"]:
                checkpoint = models.read_checkpoint(net_info["path"])
                if checkpoint is None:
                    continue
                self._checkpoints.setdefault(model_name, checkpoint)
                net_info["accuracy"] = checkpoint.get("accuracy")
                net_info["loss"] = checkpoint.get("loss")
                net_info["epoch"] = checkpoint.get("epoch")
                # All None on anything trained before the fields existed.
                net_info["label_accuracy"] = checkpoint.get("label_accuracy")
                net_info["combined_accuracy"] = checkpoint.get("combined_accuracy")
                net_info["label_frames"] = checkpoint.get("label_frames")
                # One run made every net, so these describe the model
                # rather than the net. First one to carry them wins.
                if not meta.get("run_settings"):
                    meta["run_settings"] = checkpoint.get("run_settings") or {}
                if not meta.get("audio_settings"):
                    meta["audio_settings"] = checkpoint.get("audio_settings") or {}
                if not meta.get("source_mics"):
                    meta["source_mics"] = checkpoint.get("source_mics") or {}
                if not meta["labels"] and "labels" in checkpoint:
                    meta["labels"] = list(checkpoint["labels"])

            if not meta["labels"] and meta["pkl_exists"]:
                meta["labels"] = models.read_model_labels(model_name)

            if meta["labels"]:
                self._label_cache[model_name] = meta["labels"]

            accuracies = [n["accuracy"] for n in meta["nets"] if n["accuracy"] is not None]
            if accuracies:
                meta["best_accuracy"] = max(accuracies)

        self._model_cache[cache_key] = meta
        return meta

    def get_model_trained_at(self, model_name):
        """When a model was trained. See models.get_trained_at."""
        return self._trained_at(model_name)[0]

    def _trained_at(self, model_name):
        """models.get_trained_at from what is cached. Until a checkpoint is
        read only replay or mtime are known, so the list shows those first
        and improves once the off-thread read lands."""
        return models.get_trained_at(model_name,
                                     self._checkpoints.get(model_name),
                                     self._training_run_times())

    def model_sort_key(self, model_name):
        return models.get_newest_first_key(model_name,
                                           self._trained_at(model_name))

    def get_model_facts(self, model_name):
        """Labels and training time from one BEST checkpoint - much cheaper
        than unpickling the pkl. Cached; [] labels means unreadable, so
        callers don't retry forever.
        """
        if model_name in self._label_cache:
            when, source = self._trained_at(model_name)
            return {"labels": self._label_cache[model_name],
                    "trained_at": when, "trained_at_source": source}

        labels = []
        best_files = models.get_best_checkpoint_paths(model_name)
        if best_files:
            checkpoint = models.read_checkpoint(best_files[0])
            if checkpoint is not None:
                labels = list(checkpoint.get("labels") or [])
                self._checkpoints[model_name] = checkpoint
        if not labels:
            # No checkpoints, or unreadable ones: a combined model keeps its
            # classes only inside the pkl.
            labels = self.get_model_metadata(model_name,
                                             load_weights=True)["labels"]

        self._label_cache[model_name] = labels
        when, source = self._trained_at(model_name)
        return {"labels": labels, "trained_at": when,
                "trained_at_source": source}

    def get_all_model_details(self):
        """Returns list of metadata dicts for all models."""
        return [self.get_model_metadata(name) for name in self.get_model_names()]

    def get_latest_model_name(self):
        """Top of the Models list, None if there are no models."""
        return min(self.get_model_names(), key=self.model_sort_key, default=None)

    def is_first_run(self):
        """True if no recordings AND no models exist."""
        return len(self.get_sound_labels()) == 0 and len(self.get_model_names()) == 0

    def _invalidate_duration_cache(self):
        self._duration_cache.clear()

    def _invalidate_model_cache(self):
        self._model_cache.clear()
        self._label_cache.clear()
        self._checkpoints.clear()
        self._replay_times = None

    def _training_run_times(self):
        """Cached models.get_training_run_times."""
        if self._replay_times is None:
            self._replay_times = models.get_training_run_times()
        return self._replay_times

    def refresh(self):
        """Emit signals to refresh all views."""
        self.recordings_changed.emit()
        self.models_changed.emit()

    # ---- mutations (thin wrappers over library_ops + signal emit) -------
    # Errors propagate as LibraryOpError for the caller to display.

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
