import os
from PyQt6.QtCore import Qt, QEvent, QTimer, QElapsedTimer, QPointF, QRectF, QSize, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPolygonF, QColor
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy, QPushButton
from gui.widgets.audio_graph import AudioGraph, GRAPH_DISPLAY_WAVEFORM
from gui.services import playback
from gui import theme
from gui.formatters import recorded_at, duration_text
from lib.recordings import get_recorded_at
from lib.wav import wav_duration, UnreadableWav


ICON_SIZE = 13


def _media_icon(draw, color):
    """Draw a glyph as a fixed-size icon: text glyphs differ in height and
    shift the layout when swapped."""
    scale = 2   # sharp on high-DPI screens
    pixmap = QPixmap(ICON_SIZE * scale, ICON_SIZE * scale)
    pixmap.setDevicePixelRatio(scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    draw(painter, ICON_SIZE * 0.16)
    painter.end()
    return QIcon(pixmap)


def _draw_play(painter, margin):
    painter.drawPolygon(QPolygonF([QPointF(margin, margin),
                                   QPointF(margin, ICON_SIZE - margin),
                                   QPointF(ICON_SIZE - margin, ICON_SIZE / 2)]))


def _draw_pause(painter, margin):
    bar_width = ICON_SIZE * 0.24
    gap = ICON_SIZE * 0.18
    height = ICON_SIZE - 2 * margin
    painter.drawRect(QRectF(ICON_SIZE / 2 - gap / 2 - bar_width, margin, bar_width, height))
    painter.drawRect(QRectF(ICON_SIZE / 2 + gap / 2, margin, bar_width, height))


def _unreadable(exc):
    if exc.reason == UnreadableWav.NOT_16_BIT:
        return f"{exc.bits}-bit audio, parrot.py records 16-bit"
    return {
        UnreadableWav.CANT_OPEN: "The file couldn't be opened",
        UnreadableWav.NOT_PCM: "Unsupported wav format, parrot.py records 16-bit",
        UnreadableWav.EMPTY: "The recording is empty",
    }.get(exc.reason, "Not a wav file, or a damaged one")


class RecordingCard(QFrame):
    """One recording: when it was made, how long it is, a waveform or
    spectrogram with detection overlaid, and playback."""

    AUDIO_GRAPH_HEIGHT = 150

    playback_started = pyqtSignal(object)   # self
    playback_failed = pyqtSignal(str)       # message
    picked = pyqtSignal(object)             # self, when its graph is clicked or Play focused

    def __init__(self, name, label, wav_path, srt_path, parent=None):
        super().__init__(parent)
        # The audio graph inside asks to grow even at a fixed height, so without
        # this a lone card soaks up the page's spare height around its title
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.label = label
        self.wav_path = wav_path
        self.srt_path = srt_path

        t = theme.colors()
        self.setStyleSheet(
            "RecordingCard { border: 1px solid %s; border-radius: %s; "
            "background-color: %s; }" % (t["border"], t["radius"], t["card"]))

        self.audio_graph = None
        self._audio_graph_tried = False
        self._graph_display = GRAPH_DISPLAY_WAVEFORM
        self._normalized = False

        self._audio = None
        self._sample_rate = None
        self._duration = 0.0
        self._position = 0.0       # playhead, kept across pause
        self._play_start = 0.0
        self._playing = False
        self._latency = 0.0        # output buffer delay of the current play

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._clock = QElapsedTimer()

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 6, 10, 6)
        self._layout.setSpacing(4)
        self._layout.addLayout(self._build_header(name))

        self._placeholder = QLabel("…")
        self._placeholder.setFixedHeight(self.AUDIO_GRAPH_HEIGHT)
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet(
            f"color: {t['text_dim']}; border: none; background: transparent;")
        self._layout.addWidget(self._placeholder)

    def _build_header(self, name):
        row = QHBoxLayout()
        t = theme.colors()
        self._play_icon = _media_icon(_draw_play, t["text_bright"])
        self._pause_icon = _media_icon(_draw_pause, t["text_bright"])
        self.play_btn = QPushButton(self._play_icon, " Play")
        self.play_btn.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.play_btn.setFixedWidth(90)
        self.play_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.play_btn.setToolTip("Space plays the last recording played, clicked or focused")
        self.play_btn.clicked.connect(self.toggle_play)
        # Tabbing to a card aims Space at it, same as clicking its graph
        self.play_btn.installEventFilter(self)
        row.addWidget(self.play_btn)

        # Example:
        # name  = "mici_1__1693668038"
        # title = "Sep 02, 2023, 10:20 AM", or the name if it has no timestamp
        stamp = get_recorded_at(name)
        title_text = recorded_at(stamp) if stamp else name
        title = QLabel(title_text)
        title.setStyleSheet(f"color: {t['text']}; font-weight: bold; border: none; background: transparent;")
        row.addWidget(title)

        length = wav_duration(self.wav_path)
        if length:
            meta = QLabel(duration_text(length))
            meta.setStyleSheet(f"color: {t['text_dim']}; border: none; background: transparent;")
            row.addWidget(meta)

        # Otherwise a recording with no srt looks like one where nothing was detected
        self._detection_note = QLabel("Not segmented yet")
        self._detection_note.setStyleSheet(f"color: {t['text_dim']}; border: none; background: transparent;")
        self._detection_note.setVisible(not self.srt_path)
        row.addWidget(self._detection_note)

        row.addStretch()
        # Which recording, for a screen reader: every card has a Play. Fixed,
        # so Play/Pause doesn't announce over the audio
        self.play_btn.setAccessibleName(
            f"{title_text}, {duration_text(length)}" if length else title_text)
        return row

    def build_audio_graph(self):
        """Build it, or say the file can't be read. Runs once."""
        if self._audio_graph_tried:
            return
        self._audio_graph_tried = True
        graph = AudioGraph()
        graph.setFixedHeight(self.AUDIO_GRAPH_HEIGHT)
        problem = graph.load(self.wav_path, self.srt_path, self.label)
        if problem:
            graph.deleteLater()
            self._detection_note.setVisible(False)
            self.play_btn.setEnabled(False)
            # The name, not the date: it's the file to go and look at
            name = os.path.basename(self.wav_path)
            self._placeholder.setText(f"Can't read {name}\n{_unreadable(problem)}")
            return
        if graph.regions_unreadable:
            self._detection_note.setText(f"Can't read {os.path.basename(self.srt_path)}")
            self._detection_note.setVisible(True)
        self.audio_graph = graph
        self.audio_graph.set_graph_display(self._graph_display)
        self.audio_graph.set_normalized(self._normalized)
        self.audio_graph.seeked.connect(self._on_seek)
        self._layout.replaceWidget(self._placeholder, self.audio_graph)
        self._placeholder.setParent(None)
        self._placeholder.deleteLater()
        self._placeholder = None

    def set_graph_display(self, graph_display):
        # Remembered, so an audio graph built later starts in it
        self._graph_display = graph_display
        if self.audio_graph is not None:
            self.audio_graph.set_graph_display(graph_display)

    def set_normalized(self, normalized):
        self._normalized = normalized
        if self.audio_graph is not None:
            self.audio_graph.set_normalized(normalized)

    def playable(self):
        self.build_audio_graph()
        return self.audio_graph is not None

    def toggle_play(self):
        if self._playing:
            self.pause()
        else:
            self.play()

    def play(self, from_seconds=None):
        self.build_audio_graph()
        if self.audio_graph is None:
            return      # unreadable, the card already says why
        if self._audio is None:
            self._audio, self._sample_rate = self.audio_graph.playback_audio()
            self._duration = self.audio_graph.duration()

        if from_seconds is not None:
            self._position = from_seconds
        if self._position >= self._duration:
            self._position = 0.0
        self._position = max(0.0, self._position)
        self.playback_started.emit(self)

        self._play_start = self._position
        clip = self._audio[int(self._position * self._sample_rate):]
        try:
            self._latency = playback.play(clip, self._sample_rate)
        except playback.PlaybackError:
            self._show_stopped()
            self.playback_failed.emit("The default playback device would not open.")
            return

        self._playing = True
        self.play_btn.setIcon(self._pause_icon)
        self.play_btn.setText(" Pause")
        self.audio_graph.set_playhead(self._position)
        self._clock.restart()
        self._timer.start()

    def pause(self):
        if self._playing:
            playback.stop()
            self._position = min(self._heard_position(), self._duration)
        self._show_stopped()
        self.audio_graph.set_playhead(self._position)

    def stop(self):
        """Stop, leaving the playhead where it is."""
        if self._playing:
            playback.stop()
        self._show_stopped()

    def _show_stopped(self):
        self._playing = False
        self._timer.stop()
        self.play_btn.setIcon(self._play_icon)
        self.play_btn.setText(" Play")

    def eventFilter(self, obj, event):
        if obj is self.play_btn and event.type() == QEvent.Type.FocusIn:
            self.picked.emit(self)
        return super().eventFilter(obj, event)

    def _on_seek(self, seconds):
        self.picked.emit(self)
        self._position = seconds
        self.audio_graph.set_playhead(seconds)
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
            # The writer finishes the stream itself. Aborting here would race it
            self._show_stopped()
            self._position = 0.0
            self.audio_graph.set_playhead(0.0)
            return
        self._position = heard
        self.audio_graph.set_playhead(heard)

    def cleanup(self):
        """Stop, and release plot items before deletion."""
        self.stop()
        if self.audio_graph is not None:
            self.audio_graph.cleanup()
