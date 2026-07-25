"""Workers for model evaluation: the offline accuracy test and the live mic
test. Both are thin threads around gui/services/model_eval - the accuracy
worker drives it with recorded segments, the live worker with mic chunks.
"""
import math
from queue import Queue, Empty

import sounddevice as sd
from PyQt6.QtCore import QThread, pyqtSignal

from config.config import RATE, CHANNELS, RECORD_SECONDS, SLIDING_WINDOW_AMOUNT
from lib.signal_processing import determine_dBFS
from gui.services import model_eval

import numpy as np


class AccuracyWorker(QThread):
    progressed = pyqtSignal(str)
    finished_ok = pyqtSignal(object)     # evaluate_model() result
    failed = pyqtSignal(str)

    def __init__(self, model_path, labels, max_per_sound=2000, parent=None):
        super().__init__(parent)
        self.model_path = model_path
        self.labels = labels
        self.max_per_sound = max_per_sound

    def run(self):
        try:
            result = model_eval.evaluate_model(
                self.model_path, self.labels,
                progress_callback=self.progressed.emit,
                max_per_sound=self.max_per_sound)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit(result)


class LiveTestWorker(QThread):
    """Streams the mic through the model; emits {label: prob} + dBFS per
    frame. Same chunking as recording (RECORD_SECONDS / SLIDING_WINDOW)."""
    frame_classified = pyqtSignal(dict, float)   # probabilities, dBFS
    failed = pyqtSignal(str)

    def __init__(self, model_path, mic_index=None, parent=None):
        super().__init__(parent)
        self.model_path = model_path
        self.mic_index = mic_index
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            model = model_eval.load_model(self.model_path)
            classifier = model_eval.FrameClassifier(model)
        except Exception as exc:
            self.failed.emit(f"Couldn't load the model: {exc}")
            return

        queue = Queue()

        def callback(indata, _frames, _time, _status):
            queue.put(bytes(indata.tobytes()))

        try:
            stream = sd.InputStream(
                samplerate=RATE, channels=CHANNELS, dtype="int16",
                device=self.mic_index,
                blocksize=round(RATE * RECORD_SECONDS / SLIDING_WINDOW_AMOUNT),
                callback=callback)
            stream.start()
        except Exception as exc:
            self.failed.emit(f"Couldn't open the microphone: {exc}")
            return

        try:
            while not self._stop:
                try:
                    chunk = queue.get(timeout=0.2)
                except Empty:
                    continue
                probabilities = classifier.add_chunk(chunk)
                if probabilities is None:
                    continue
                wave_data = np.frombuffer(chunk, dtype=np.int16)
                dbfs = determine_dBFS(wave_data)
                if math.isinf(dbfs):
                    dbfs = -96.0
                self.frame_classified.emit(probabilities, float(dbfs))
        finally:
            stream.stop()
            stream.close()
