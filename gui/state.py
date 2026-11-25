import contextlib
import os
from dataclasses import dataclass
from typing import List
from PyQt6.QtCore import QObject, pyqtSignal
from gui.services import library_ops
from lib import models, recordings
from lib.typing import Checkpoint, TrainedAt


@dataclass
class ModelDetails:
    """What a model's files say about it. checkpoints holds one per net that
    could be read, so it can be shorter than net_count."""
    labels: List[str]
    checkpoints: List[Checkpoint]
    net_count: int
    trained_at: TrainedAt
    pkl_bytes: int


class AppState(QObject):
    """What the pages show, read off data/, and the edits that change it.
    Detected time and model details are cached; each edit emits the signal
    that clears them."""
    recordings_changed = pyqtSignal()
    models_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._duration_cache = {}
        self._model_details_cache = {}
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

    def get_models_newest_first(self):
        """[(name, trained_at)]. A model whose details are read is dated by its
        checkpoint, the others by replay csv or file date."""
        run_times = models.get_training_run_times()
        dated = [(name, self._model_trained_at(name, run_times))
                 for name in models.get_model_names()]
        return sorted(dated, key=lambda pair: models.get_newest_first_key(*pair))

    def _model_trained_at(self, name, run_times):
        details = self._model_details_cache.get(name)
        if details:
            return details.trained_at
        return models.get_trained_at(name, None, run_times)

    def get_net_count(self, name):
        return len(models.get_best_checkpoint_paths(name))

    def get_model_details(self, name):
        """Slow: reads every net's checkpoint, ~4 MB each. Off the UI thread.
        Cached."""
        if name not in self._model_details_cache:
            try:
                details = self._model_details_load(name)
            except Exception:
                # e.g. torch won't load. Empty labels show as unreadable
                details = ModelDetails(labels=[], checkpoints=[], net_count=0,
                                       trained_at=(None, None), pkl_bytes=0)
                # Runs on the reader thread, where an exception aborts the app
                with contextlib.suppress(OSError):
                    details.net_count = self.get_net_count(name)
                    details.trained_at = models.get_trained_at(name)
            self._model_details_cache[name] = details
        return self._model_details_cache[name]

    def get_model_details_if_read(self, name):
        """None until get_model_details has read it."""
        return self._model_details_cache.get(name)

    def _model_details_load(self, name):
        paths = models.get_best_checkpoint_paths(name)
        checkpoints = [c for c in map(models.read_checkpoint, paths) if c is not None]
        labels = next((list(c["labels"]) for c in checkpoints if c.get("labels")), None)
        if labels is None:
            # An sklearn model, one combined from other pkls, or damaged checkpoints
            labels = models.read_model_labels(name)
        pkl_path = models.get_model_path(name)
        return ModelDetails(
            labels=labels,
            checkpoints=checkpoints,
            net_count=len(paths),
            trained_at=models.get_trained_at(
                name, next((c for c in checkpoints if c.get("trained_at")), None)),
            pkl_bytes=os.path.getsize(pkl_path) if os.path.isfile(pkl_path) else 0,
        )

    def get_latest_model(self):
        """(name, trained_at) at the top of the Models list, None if there
        are no models."""
        return next(iter(self.get_models_newest_first()), None)

    def get_latest_model_name(self):
        latest = self.get_latest_model()
        return latest[0] if latest else None

    def is_first_run(self):
        """True if no recordings AND no models exist."""
        return len(self.get_sound_labels()) == 0 and len(self.get_model_names()) == 0

    def _invalidate_duration_cache(self):
        self._duration_cache.clear()

    def _invalidate_model_cache(self):
        self._model_details_cache.clear()

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
