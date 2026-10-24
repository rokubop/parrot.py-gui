import os
import math
from config.config import (RECORDINGS_FOLDER, CLASSIFIER_FOLDER,
                           RECORD_SECONDS, SLIDING_WINDOW_AMOUNT)
from lib.srt import count_total_label_ms, srt_for_source


class AppState:
    """What the pages show, read off data/. Never writes, and reads once: a
    recording made while the app is open shows after a restart."""

    def __init__(self):
        self._duration_cache = {}

    def get_sound_labels(self):
        """Sound label directory names in data/recordings/."""
        if not os.path.isdir(RECORDINGS_FOLDER):
            return []
        return [entry for entry in sorted(os.listdir(RECORDINGS_FOLDER))
                if os.path.isdir(os.path.join(RECORDINGS_FOLDER, entry))]

    def get_recordings_for_label(self, label):
        """One dict per source wav: wav_path, srt_path (None if not segmented
        yet) and filename."""
        source_dir = os.path.join(RECORDINGS_FOLDER, label, "source")
        segments_dir = os.path.join(RECORDINGS_FOLDER, label, "segments")
        if not os.path.isdir(source_dir):
            return []
        recordings = []
        for wav_file in sorted(f for f in os.listdir(source_dir) if f.endswith(".wav")):
            srt_path = srt_for_source(segments_dir, wav_file[:-len(".wav")])
            recordings.append({"wav_path": os.path.join(source_dir, wav_file),
                               "srt_path": srt_path, "filename": wav_file})
        return recordings

    def get_label_duration_ms(self, label):
        """Detected ms for a label. Cached: it parses every srt the label has."""
        if label not in self._duration_cache:
            ms_per_frame = math.floor(RECORD_SECONDS / SLIDING_WINDOW_AMOUNT * 1000)
            self._duration_cache[label] = count_total_label_ms(
                label, os.path.join(RECORDINGS_FOLDER, label), ms_per_frame)
        return self._duration_cache[label]

    def get_model_names(self):
        """Model names in data/models/, without the .pkl extension."""
        if not os.path.isdir(CLASSIFIER_FOLDER):
            return []
        return sorted(f[:-len(".pkl")] for f in os.listdir(CLASSIFIER_FOLDER)
                      if f.endswith(".pkl"))
