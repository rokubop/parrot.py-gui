import os
import wave
from datetime import datetime
from PyQt6.QtCore import Qt, QTimer, QElapsedTimer, QPointF, QRectF, QSize, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPolygonF, QColor
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from gui.widgets.audio_preview import AudioPreviewWidget
from gui.services import playback
from gui import theme


def _media_icon(kind, color, size=13):
    """Play or pause glyph as a fixed-size icon: the text glyphs differ in
    height and shift the layout when swapped."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    m = size * 0.16
    if kind == "play":
        p.drawPolygon(QPolygonF([QPointF(m, m), QPointF(m, size - m),
                                 QPointF(size - m, size / 2)]))
    else:
        bw = size * 0.24
        gap = size * 0.18
        p.drawRect(QRectF(size / 2 - gap / 2 - bw, m, bw, size - 2 * m))
        p.drawRect(QRectF(size / 2 + gap / 2, m, bw, size - 2 * m))
    p.end()
    return QIcon(pm)


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
    """One recording: when it was made, how long it is, a waveform or
    spectrogram with detection overlaid, and playback."""

    PREVIEW_HEIGHT = 150

    started = pyqtSignal(object)   # self, when playback begins
    failed = pyqtSignal(str)       # playback could not start
    picked = pyqtSignal(object)    # self, when its plot is clicked

    def __init__(self, session_name, wav_path, srt_path, parent=None):
        super().__init__(parent)
        self.wav_path = wav_path
        self.srt_path = srt_path

        self._audio = None
        self._sample_rate = None
        self._duration = 0.0
        self._position = 0.0       # playhead, kept across pause
        self._play_start = 0.0     # where the current play began
        self._playing = False
        self._latency = 0.0        # output buffer delay of the current play

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._clock = QElapsedTimer()

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
        self._play_icon = _media_icon("play", t["text_bright"])
        self._pause_icon = _media_icon("pause", t["text_bright"])
        self.play_btn = QPushButton(self._play_icon, " Play")
        self.play_btn.setIconSize(QSize(13, 13))
        self.play_btn.setFixedWidth(90)
        self.play_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.play_btn.setToolTip("Space plays the last recording played or clicked")
        self.play_btn.clicked.connect(self.toggle_play)
        row.addWidget(self.play_btn)

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
        self.preview.seeked.connect(self._on_seek)
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

    # ---- playback ------------------------------------------------------

    def toggle_play(self):
        if self._playing:
            self.pause()
        else:
            self.play()

    def play(self, from_seconds=None):
        self.load_preview()
        if self._audio is None:
            # The samples the plot already decoded, so the first play doesn't
            # re-read the file on the UI thread
            self._audio, self._sample_rate = self.preview.playback_audio()
            self._duration = self.preview.duration()
        if self._audio is None or not self._sample_rate:
            return

        if from_seconds is not None:
            self._position = from_seconds
        if self._position >= self._duration:
            self._position = 0.0
        self._position = max(0.0, self._position)
        self.started.emit(self)

        self._play_start = self._position
        clip = self._audio[int(self._position * self._sample_rate):]
        try:
            self._latency = playback.play(clip, self._sample_rate)
        except playback.PlaybackError:
            self.failed.emit("The default playback device would not open.")
            return

        self._playing = True
        self.play_btn.setIcon(self._pause_icon)
        self.play_btn.setText(" Pause")
        self.preview.set_playhead(self._position)
        self._clock.restart()
        self._timer.start()

    def pause(self):
        if self._playing:
            playback.stop()
            self._position = min(self._heard_position(), self._duration)
        self._show_stopped()
        self.preview.set_playhead(self._position)

    def stop(self):
        """Stop without moving the playhead, when another card starts."""
        if self._playing:
            playback.stop()
        self._show_stopped()

    def _show_stopped(self):
        self._playing = False
        self._timer.stop()
        self.play_btn.setIcon(self._play_icon)
        self.play_btn.setText(" Play")

    def _on_seek(self, seconds):
        # Moves the playhead. Keeps playing if it was, else waits for Play.
        self.picked.emit(self)
        self._position = seconds
        self.preview.set_playhead(seconds)
        if self._playing:
            self.play(from_seconds=seconds)

    def _heard_position(self):
        """Where playback has reached, in seconds. Audio leaves the device a
        buffer after play() is called, so without subtracting that the
        playhead runs ahead of what you hear."""
        return self._play_start + max(0.0, self._clock.elapsed() / 1000.0 - self._latency)

    def _tick(self):
        heard = self._heard_position()
        if heard >= self._duration:
            self.stop()
            self._position = 0.0
            self.preview.set_playhead(0.0)
            return
        self._position = heard
        self.preview.set_playhead(heard)

    def cleanup(self):
        """Stop, and release plot items before deletion."""
        self.stop()
        if self.preview is not None:
            self.preview.cleanup()
