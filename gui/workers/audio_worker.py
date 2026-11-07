import time
from queue import Queue
from PyQt6.QtCore import QThread, pyqtSignal
from config.config import (
    RATE, CHANNELS, RECORD_SECONDS, SLIDING_WINDOW_AMOUNT, MS_PER_FRAME,
    INPUT_DEVICE_INDEX, CURRENT_DETECTION_STRATEGY
)
from lib.audio_input import open_input_stream
from lib.recordings import create_recording_paths
from lib.typing import DetectionLabel, DetectionState
from lib.stream_recorder import StreamRecorder


class AudioWorker(QThread):
    """Records one take of `label` from the default mic, as the CLI does: a wav
    and its srt, written by StreamRecorder when the take stops."""

    frame_recorded = pyqtSignal(bytes, bool)    # raw frame, detected as sound
    status_updated = pyqtSignal(object)         # DetectionState
    stream_ready = pyqtSignal()                 # first frame arrived
    recording_finished = pyqtSignal(str, str)   # wav_path, srt_path
    failed = pyqtSignal(str)                    # the mic would not open

    def __init__(self, label, previous_detected_ms=0, parent=None):
        super().__init__(parent)
        self.label = label
        self.previous_detected_ms = previous_detected_ms
        self._stop_requested = False

    def run(self):
        wav_path, srt_path = create_recording_paths(
            self.label, INPUT_DEVICE_INDEX, str(int(time.time())))
        labels = [DetectionLabel(self.label, 0, self.previous_detected_ms, "", 0, 0, 0, 0, 0)]
        detection_state = DetectionState(
            CURRENT_DETECTION_STRATEGY, "recording", MS_PER_FRAME, 0, True,
            0, 0, 0, 0, labels, None, [])

        audio_queue = Queue()
        try:
            stream = open_input_stream(
                INPUT_DEVICE_INDEX, rate=RATE, channels=CHANNELS,
                record_seconds=RECORD_SECONDS, sliding_window_amount=SLIDING_WINDOW_AMOUNT,
                callback=lambda indata, frames, time_info, status: audio_queue.put(indata.tobytes()))
            stream.start()
        except Exception as exc:
            # PortAudioError for a mic that won't open, ValueError for one that's gone
            self.failed.emit(str(exc))
            return
        recorder = StreamRecorder(stream, wav_path, srt_path, detection_state)
        try:
            first_frame = True
            while not self._stop_requested:
                while not audio_queue.empty() and not self._stop_requested:
                    frame = audio_queue.get()
                    if first_frame:
                        first_frame = False
                        self.stream_ready.emit()
                    recorder.add_audio_frame(frame)
                    frames = recorder.detection_frames
                    self.frame_recorded.emit(frame, bool(frames and frames[-1].positive))
                    self.status_updated.emit(recorder.get_detection_state())
                time.sleep(0.001)
        finally:
            # Writes the wav and srt. Deletes the wav if no frame arrived
            recorder.stop()
            self.recording_finished.emit(wav_path, srt_path)

    def request_stop(self):
        self._stop_requested = True
