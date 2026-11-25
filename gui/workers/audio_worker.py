import os
import time
from queue import Queue
import sounddevice as sd
from PyQt6.QtCore import QThread, pyqtSignal
from config.config import (
    RATE, CHANNELS, RECORD_SECONDS, SLIDING_WINDOW_AMOUNT, MS_PER_FRAME,
    CURRENT_DETECTION_STRATEGY
)
from lib.audio_input import open_input_stream
from lib.recordings import create_recording_paths, delete_recording
from lib.typing import DetectionLabel, DetectionState
from lib.stream_recorder import StreamRecorder
from lib.stream_warmup import StreamWarmup


class AudioWorker(QThread):
    """Records one stretch of `label` from mic `mic_index`, as the CLI does: a
    wav and its srt, written by StreamRecorder when it stops."""

    frame_recorded = pyqtSignal(bytes, bool)    # raw frame, detected as sound
    frame_level = pyqtSignal(float)             # that frame's dBFS
    status_updated = pyqtSignal(object)         # DetectionState
    # Past the mic's warm-up: what it delivers from here is kept. Seconds
    # late on a Bluetooth headset, see lib/stream_warmup.py
    stream_ready = pyqtSignal()
    recording_finished = pyqtSignal(str, str)   # wav_path, srt_path
    failed = pyqtSignal(str)                    # the mic would not open

    def __init__(self, label, mic_index, previous_detected_ms=0, parent=None):
        super().__init__(parent)
        self.label = label
        self.mic_index = mic_index
        self.previous_detected_ms = previous_detected_ms
        self._stop_requested = False

    def run(self):
        wav_path, srt_path = create_recording_paths(
            self.label, self.mic_index, str(int(time.time())))
        labels = [DetectionLabel(self.label, 0, self.previous_detected_ms, "", 0, 0, 0, 0, 0)]
        detection_state = DetectionState(
            CURRENT_DETECTION_STRATEGY, "recording", MS_PER_FRAME, 0, True,
            0, 0, 0, 0, labels, None, [])

        audio_queue = Queue()
        try:
            mic_name = sd.query_devices(self.mic_index).get("name", "")
        except Exception:
            mic_name = ""
        try:
            stream = open_input_stream(
                self.mic_index, rate=RATE, channels=CHANNELS,
                record_seconds=RECORD_SECONDS, sliding_window_amount=SLIDING_WINDOW_AMOUNT,
                callback=lambda indata, frames, time_info, status: audio_queue.put(indata.tobytes()))
            stream.start()
        except Exception as exc:
            # PortAudio's reason, without "Error opening InputStream: ". An
            # output-only device gives "Invalid number of channels"
            reason = str(exc.args[0] if exc.args else exc).split(": ")[-1]
            self.failed.emit(f"Couldn't open {mic_name or f'mic {self.mic_index}'} ({reason}).")
            return
        recorder = StreamRecorder(stream, wav_path, srt_path, detection_state)
        warmup = StreamWarmup()
        try:
            ready = False
            while not self._stop_requested:
                while not audio_queue.empty() and not self._stop_requested:
                    frame = audio_queue.get()
                    if warmup.hold():
                        continue
                    if not ready:
                        ready = True
                        self.stream_ready.emit()
                    recorder.add_audio_frame(frame)
                    frames = recorder.detection_frames
                    self.frame_recorded.emit(frame, bool(frames and frames[-1].positive))
                    # power is 0 on the first frame, which has no window behind it
                    if frames and frames[-1].power:
                        self.frame_level.emit(float(frames[-1].dBFS))
                    self.status_updated.emit(recorder.get_detection_state())
                time.sleep(0.001)
        finally:
            recorder.stop()
            if not os.path.exists(wav_path):
                # Nothing recorded: the recorder drops the wav but still writes
                # its srt and thresholds, which would be orphans
                delete_recording(wav_path)
            self.recording_finished.emit(wav_path, srt_path)

    def request_stop(self):
        self._stop_requested = True
