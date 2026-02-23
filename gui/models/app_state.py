import os
import glob
import math
from PyQt6.QtCore import QObject, pyqtSignal
from config.config import RECORDINGS_FOLDER, CLASSIFIER_FOLDER, RECORD_SECONDS, SLIDING_WINDOW_AMOUNT
from lib.srt import count_total_label_ms, ms_to_srt_timestring
from lib.stream_processing import CURRENT_VERSION


class AppState(QObject):
    recordings_changed = pyqtSignal()
    models_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

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

    def refresh(self):
        """Emit signals to refresh all views."""
        self.recordings_changed.emit()
        self.models_changed.emit()
