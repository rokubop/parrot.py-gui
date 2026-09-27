"""Background worker that combines several models into one ensemble.

Mirrors the ensemble path of lib/combine_models.combine_models without the
interactive prompts: load each selected .pkl, wrap them in an EnsembleClassifier
inside an AudioModel using the current audio settings, and save a new .pkl.
"""
import os
import joblib
from PyQt6.QtCore import QThread, pyqtSignal

from config.config import (
    CLASSIFIER_FOLDER, RATE, CHANNELS, RECORD_SECONDS, SLIDING_WINDOW_AMOUNT,
    FEATURE_ENGINEERING_TYPE,
)
from gui.services import library_ops


def _current_settings():
    return {
        "version": 1,
        "RATE": RATE,
        "CHANNELS": CHANNELS,
        "RECORD_SECONDS": RECORD_SECONDS,
        "SLIDING_WINDOW_AMOUNT": SLIDING_WINDOW_AMOUNT,
        "FEATURE_ENGINEERING_TYPE": FEATURE_ENGINEERING_TYPE,
    }


class CombineWorker(QThread):
    finished_ok = pyqtSignal(str)   # new model name
    failed = pyqtSignal(str)

    def __init__(self, new_name, source_names, parent=None):
        super().__init__(parent)
        self.new_name = new_name
        self.source_names = source_names

    def run(self):
        try:
            from lib.ensemble_classifier import EnsembleClassifier
            from lib.audio_model import AudioModel

            classifier_map = {}
            for i, name in enumerate(self.source_names):
                pkl = library_ops.model_pkl_path(name)
                classifier_map[f"classifier_{i}"] = joblib.load(pkl)

            ensemble = EnsembleClassifier(classifier_map)
            model = AudioModel(_current_settings(), ensemble)
            os.makedirs(CLASSIFIER_FOLDER, exist_ok=True)
            joblib.dump(model, library_ops.model_pkl_path(self.new_name))
            self.finished_ok.emit(self.new_name)
        except Exception as exc:
            self.failed.emit(str(exc))
