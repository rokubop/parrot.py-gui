from PyQt6.QtCore import QThread, pyqtSignal
from lib.recordings import append_recording


class AppendWorker(QThread):
    """append_recording off the UI thread: re-detecting the whole take takes
    seconds on a long one."""

    appended = pyqtSignal(str)   # the take's srt
    failed = pyqtSignal(str)

    def __init__(self, take_wav, segment_wav, label, parent=None):
        super().__init__(parent)
        self.take_wav = take_wav
        self.segment_wav = segment_wav
        self.label = label

    def run(self):
        try:
            self.appended.emit(append_recording(self.take_wav, self.segment_wav, self.label))
        except Exception as exc:
            self.failed.emit(str(exc))
