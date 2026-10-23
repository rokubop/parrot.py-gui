import os
import wave
from datetime import datetime
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy
from gui.widgets.audio_preview import AudioPreviewWidget
from gui import theme


def _parse_when(session_name):
    """Filenames end in __<unix-timestamp>; decode it to a date and time. The
    time matters: several takes of one sound in a sitting is the normal way to
    record, and a date alone leaves those cards reading identically."""
    tail = session_name.rsplit("__", 1)[-1]
    if not tail.isdigit():
        return ""
    try:
        stamp = datetime.fromtimestamp(int(tail))
    except (ValueError, OSError, OverflowError):
        return ""
    # %-I / %#I differ between posix and Windows, so trim the zero by hand.
    hour = stamp.strftime("%I").lstrip("0") or "12"
    return stamp.strftime(f"%b %d, %Y, {hour}:%M %p")


def wav_duration(path):
    try:
        wf = wave.open(path, "rb")
        rate = wf.getframerate()
        frames = wf.getnframes()
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        wf.close()
        # Some recordings store a byte count in nframes, double the real
        # length. Cap to the frames the file can actually hold.
        if channels and sampwidth:
            data_bytes = max(0, os.path.getsize(path) - 44)  # standard PCM header
            size_frames = data_bytes // (channels * sampwidth)
            if size_frames and size_frames < frames:
                frames = size_frames
        return frames / rate if rate else 0.0
    except Exception:
        return 0.0


class SessionCard(QFrame):
    """One recording: when it was made, how long it is, and a waveform or
    spectrogram with detection overlaid."""

    PREVIEW_HEIGHT = 150

    def __init__(self, session_name, wav_path, srt_path, parent=None):
        super().__init__(parent)
        # The plot inside asks to grow even at a fixed height, so without
        # this a lone card soaks up the page's spare height around its title
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.wav_path = wav_path
        self.srt_path = srt_path

        t = theme.colors()
        self.setStyleSheet(
            "SessionCard { border: 1px solid %s; border-radius: %s; "
            "background-color: %s; }" % (t["border"], t["radius"], t["card"]))

        # A pyqtgraph plot per recording is the expensive part of switching
        # sounds (~50-220 ms each). A placeholder of the same height shows
        # instantly; the Sounds page calls load_preview() one card at a time.
        self.preview = None
        self._mode = "waveform"
        self._normalized = False

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 6, 10, 6)
        self._layout.setSpacing(4)
        self._layout.addLayout(self._build_header(session_name))

        self._placeholder = QLabel("…")
        self._placeholder.setFixedHeight(self.PREVIEW_HEIGHT)
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet(
            f"color: {t['text_dim']}; border: none; background: transparent;")
        self._layout.addWidget(self._placeholder)

    def _build_header(self, session_name):
        row = QHBoxLayout()
        t = theme.colors()
        # When it was recorded, not "mici_0": the mic index is a filename
        # disambiguator and tells the user nothing.
        name = QLabel(_parse_when(session_name) or session_name)
        name.setStyleSheet(f"color: {t['text']}; font-weight: bold; border: none; background: transparent;")
        row.addWidget(name)

        length = wav_duration(self.wav_path)
        if length:
            meta = QLabel(f"{length:.1f}s")
            meta.setStyleSheet(f"color: {t['text_dim']}; border: none; background: transparent;")
            row.addWidget(meta)

        row.addStretch()
        return row

    def load_preview(self):
        """Build the plot. No-op once built."""
        if self.preview is not None:
            return
        self.preview = AudioPreviewWidget()
        self.preview.setFixedHeight(self.PREVIEW_HEIGHT)
        self.preview.load(self.wav_path, self.srt_path)
        self.preview.set_mode(self._mode)
        self.preview.set_normalized(self._normalized)
        self._layout.replaceWidget(self._placeholder, self.preview)
        self._placeholder.setParent(None)
        self._placeholder.deleteLater()
        self._placeholder = None

    def set_mode(self, mode):
        # Remembered, so a preview built later starts in it
        self._mode = mode
        if self.preview is not None:
            self.preview.set_mode(mode)

    def set_normalized(self, normalized):
        self._normalized = normalized
        if self.preview is not None:
            self.preview.set_normalized(normalized)

    def cleanup(self):
        """Release plot items before deletion."""
        if self.preview is not None:
            self.preview.cleanup()
