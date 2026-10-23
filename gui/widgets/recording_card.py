import os
from datetime import datetime
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy
from gui.widgets.audio_display import AudioDisplay
from gui.services.wav_files import wav_duration
from gui import theme


def _parse_when(name):
    """Filenames end in __<unix-timestamp>; decode it to a date and time. The
    time matters: several takes of one sound in a sitting is the normal way to
    record, and a date alone leaves those cards reading identically."""
    tail = name.rsplit("__", 1)[-1]
    if not tail.isdigit():
        return ""
    try:
        stamp = datetime.fromtimestamp(int(tail))
    except (ValueError, OSError, OverflowError):
        return ""
    # %-I / %#I differ between posix and Windows, so trim the zero by hand.
    hour = stamp.strftime("%I").lstrip("0") or "12"
    return stamp.strftime(f"%b %d, %Y, {hour}:%M %p")


class RecordingCard(QFrame):
    """One recording: when it was made, how long it is, and a waveform or
    spectrogram with detection overlaid."""

    AUDIO_DISPLAY_HEIGHT = 150

    def __init__(self, name, wav_path, srt_path, parent=None):
        super().__init__(parent)
        # The audio display inside asks to grow even at a fixed height, so without
        # this a lone card soaks up the page's spare height around its title
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.wav_path = wav_path
        self.srt_path = srt_path

        t = theme.colors()
        self.setStyleSheet(
            "RecordingCard { border: 1px solid %s; border-radius: %s; "
            "background-color: %s; }" % (t["border"], t["radius"], t["card"]))

        # A pyqtgraph plot per recording is the expensive part of switching
        # sounds (~50-220 ms each). A placeholder of the same height shows
        # instantly; the Sounds page calls build_audio_display() one card at a time.
        self.audio_display = None
        self._audio_display_tried = False
        self._mode = "waveform"
        self._normalized = False

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 6, 10, 6)
        self._layout.setSpacing(4)
        self._layout.addLayout(self._build_header(name))

        self._placeholder = QLabel("…")
        self._placeholder.setFixedHeight(self.AUDIO_DISPLAY_HEIGHT)
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet(
            f"color: {t['text_dim']}; border: none; background: transparent;")
        self._layout.addWidget(self._placeholder)

    def _build_header(self, name):
        row = QHBoxLayout()
        t = theme.colors()
        # When it was recorded, not "mici_0": the mic index is a filename
        # disambiguator and tells the user nothing.
        title = QLabel(_parse_when(name) or name)
        title.setStyleSheet(f"color: {t['text']}; font-weight: bold; border: none; background: transparent;")
        row.addWidget(title)

        length = wav_duration(self.wav_path)
        if length:
            meta = QLabel(f"{length:.1f}s")
            meta.setStyleSheet(f"color: {t['text_dim']}; border: none; background: transparent;")
            row.addWidget(meta)

        row.addStretch()
        return row

    def build_audio_display(self):
        """Build it, or say the file can't be read. Runs once."""
        if self._audio_display_tried:
            return
        self._audio_display_tried = True
        display = AudioDisplay()
        display.setFixedHeight(self.AUDIO_DISPLAY_HEIGHT)
        problem = display.load(self.wav_path, self.srt_path)
        if problem:
            display.deleteLater()
            # The name, not the date: it's the file to go and look at
            name = os.path.basename(self.wav_path)
            self._placeholder.setText(f"Can't read {name}\n{problem}")
            return
        self.audio_display = display
        self.audio_display.set_mode(self._mode)
        self.audio_display.set_normalized(self._normalized)
        self._layout.replaceWidget(self._placeholder, self.audio_display)
        self._placeholder.setParent(None)
        self._placeholder.deleteLater()
        self._placeholder = None

    def set_mode(self, mode):
        # Remembered, so an audio display built later starts in it
        self._mode = mode
        if self.audio_display is not None:
            self.audio_display.set_mode(mode)

    def set_normalized(self, normalized):
        self._normalized = normalized
        if self.audio_display is not None:
            self.audio_display.set_normalized(normalized)

    def cleanup(self):
        """Release plot items before deletion."""
        if self.audio_display is not None:
            self.audio_display.cleanup()
