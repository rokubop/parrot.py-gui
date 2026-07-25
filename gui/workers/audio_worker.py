import json
import math
import os
import time
import numpy as np
import sounddevice as sd
from queue import Queue
from PyQt6.QtCore import QThread, pyqtSignal
from config.config import (
    RATE, CHANNELS, RECORD_SECONDS, SLIDING_WINDOW_AMOUNT,
    RECORDINGS_FOLDER, INPUT_DEVICE_INDEX
)
from lib.stream_processing import CURRENT_VERSION, CURRENT_DETECTION_STRATEGY
from lib.typing import DetectionLabel, DetectionState
from lib.stream_recorder import StreamRecorder


class AudioWorker(QThread):
    frame_recorded = pyqtSignal(bytes, bool)  # raw frame, detected-as-sound?
    status_updated = pyqtSignal(object)  # DetectionState
    recording_finished = pyqtSignal(str, str)  # wav_path, srt_path

    def __init__(self, label, mic_index=None, strategy=None, time_string=None, parent=None):
        super().__init__(parent)
        self.label = label
        self.mic_index = mic_index if mic_index is not None else INPUT_DEVICE_INDEX
        self.strategy = strategy or CURRENT_DETECTION_STRATEGY
        # shared across simultaneous multi-mic workers so files group as one take
        self.time_string = time_string or str(int(time.time()))
        self._stop_requested = False
        self._pause_requested = False
        self._clear_requested = False
        self._clear_seconds = 3.0
        self.recorder = None
        self.wav_path = ""
        self.srt_path = ""

    def run(self):
        # Ensure directories exist
        label_dir = os.path.join(RECORDINGS_FOLDER, self.label)
        source_dir = os.path.join(label_dir, "source")
        segments_dir = os.path.join(label_dir, "segments")
        for d in [label_dir, source_dir, segments_dir]:
            os.makedirs(d, exist_ok=True)

        time_string = self.time_string
        self.wav_path = os.path.join(source_dir, f"mici_{self.mic_index}__{time_string}.wav")
        self.srt_path = os.path.join(segments_dir, f"mici_{self.mic_index}__{time_string}.v{CURRENT_VERSION}.srt")

        ms_per_frame = math.floor(RECORD_SECONDS / SLIDING_WINDOW_AMOUNT * 1000)
        detection_labels = [DetectionLabel(self.label, 0, 0, "", 0, 0, 0, 0, 0)]
        detection_state = DetectionState(
            self.strategy, "recording", ms_per_frame, 0, True,
            0, 0, 0, 0, detection_labels, None, []
        )

        audio_queue = Queue(maxsize=0)

        def callback(indata, frames, time_info, status):
            audio_queue.put(indata.tobytes())

        # Resolve the mic's name now, while the stream is being opened on it.
        # Device indices shift when hardware changes (see audio_devices.py), so
        # mici_<n> in the filename cannot be turned back into a name later.
        try:
            mic_name = sd.query_devices(self.mic_index).get("name", "")
        except Exception:
            mic_name = ""

        stream = sd.InputStream(
            samplerate=RATE, channels=CHANNELS,
            dtype='int16', device=self.mic_index,
            blocksize=round(RATE * RECORD_SECONDS / SLIDING_WINDOW_AMOUNT),
            callback=callback
        )

        self.recorder = StreamRecorder(stream, self.wav_path, self.srt_path, detection_state)
        stream.start()

        try:
            while not self._stop_requested:
                while not audio_queue.empty() and not self._stop_requested:
                    frame = audio_queue.get()
                    self.recorder.add_audio_frame(frame)
                    detected = bool(self.recorder.detection_frames[-1].positive) \
                        if self.recorder.detection_frames else False
                    self.frame_recorded.emit(frame, detected)
                    self.status_updated.emit(self.recorder.get_detection_state())

                if self._clear_requested:
                    self._clear_requested = False
                    self.recorder.clear(self._clear_seconds)
                    self.recorder.resume()

                if self._pause_requested:
                    self.recorder.pause()
                    while self._pause_requested and not self._stop_requested:
                        # Drain queue while paused
                        while not audio_queue.empty():
                            audio_queue.get()
                        time.sleep(0.05)
                    if not self._stop_requested:
                        self.recorder.resume()

                time.sleep(0.001)
        except Exception as e:
            print(f"AudioWorker error: {e}")
        finally:
            self.recorder.stop()
            self._write_mic_info(mic_name)
            self.recording_finished.emit(self.wav_path, self.srt_path)

    def _write_mic_info(self, mic_name):
        """Record what this take was captured with, beside its segment files.

        Lives in segments/ as <base>_mic.json so library_ops picks it up by
        prefix: rename, move and delete all carry it automatically. Skipped when
        the take was empty and StreamRecorder deleted the wav, so no orphan is
        left behind.
        """
        if not os.path.exists(self.wav_path):
            return
        base = os.path.splitext(os.path.basename(self.wav_path))[0]
        path = os.path.join(os.path.dirname(self.srt_path), base + "_mic.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"mic_index": self.mic_index,
                           "mic_name": mic_name,
                           "sample_rate": RATE}, f)
        except OSError:
            pass

    def request_stop(self):
        self._stop_requested = True

    def request_pause(self):
        self._pause_requested = not self._pause_requested

    def request_clear(self, seconds=3.0):
        self._clear_seconds = float(seconds)
        self._clear_requested = True
