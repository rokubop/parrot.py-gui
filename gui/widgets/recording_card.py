import os
from PyQt6.QtCore import Qt, QEvent, QTimer, QElapsedTimer, QPointF, QSize, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMenu, QSizePolicy
)
from config.config import RATE
from gui.widgets.audio_graph import AudioGraph, GRAPH_DISPLAY_WAVEFORM
from gui.services import library_ops, playback, strategies
from gui import icons, theme
from gui.formatters import recorded_at, duration_text
from lib.recordings import get_recorded_at
from lib.wav import wav_duration, UnreadableWav


_ICON_CACHE = {}


def _dots_icon(color, size=13):
    """Three horizontal dots for the per-card actions menu, drawn (not a font
    glyph) so it can't show up as a missing-glyph box like '⋯' does in Inter."""
    key = ("dots", color, size)
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    r = size * 0.11
    cy = size / 2
    for cx in (size * 0.24, size * 0.5, size * 0.76):
        p.drawEllipse(QPointF(cx, cy), r, r)
    p.end()
    icon = QIcon(pm)
    _ICON_CACHE[key] = icon
    return icon


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
    spectrogram with detection overlaid, and playback. Seeks, and fits,
    starts or expands from its controls."""

    AUDIO_GRAPH_HEIGHT = 150
    AUDIO_GRAPH_EXPANDED_HEIGHT = 440

    playback_started = pyqtSignal(object)
    playback_failed = pyqtSignal(str)
    picked = pyqtSignal(object)
    action = pyqtSignal(object, str)  # (card, action_name) for menu actions

    def __init__(self, session_name, wav_path, srt_path, thresholds_path, parent=None):
        super().__init__(parent)
        # The audio graph inside asks to grow even at a fixed height, so without
        # this a lone card soaks up the page's spare height around its title
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.wav_path = wav_path
        self.srt_path = srt_path
        self.session_name = session_name
        self.label = library_ops.recording_label(wav_path)
        self._expanded = False
        self._edit_enabled = True  # set False to hide the Edit button

        self._samples = None
        self._sample_rate = None
        self._duration = 0.0
        self._playhead_position = 0.0   # kept across pause
        self._play_start_position = 0.0
        self._playing = False
        self._output_latency = 0.0     # of the current play
        self._sel_start = None     # selected range (seconds), or None
        self._sel_end = None
        self._stop_at = None       # playback stop bound for the current play

        self._playhead_timer = QTimer(self)
        self._playhead_timer.setInterval(16)
        self._playhead_timer.timeout.connect(self._tick)
        self._play_clock = QElapsedTimer()

        self._apply_border(False)

        # A placeholder until the Sounds page builds the audio graph
        self.audio_graph = None
        self._audio_graph_tried = False
        self._graph_display = GRAPH_DISPLAY_WAVEFORM
        self._normalized = False

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 6, 10, 6)
        self._layout.setSpacing(4)
        self._layout.addLayout(self._build_header(session_name, thresholds_path))

        self._placeholder = QLabel("…")
        self._placeholder.setFixedHeight(self.AUDIO_GRAPH_HEIGHT)
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet(
            f"color: {theme.colors()['text_dim']}; border: none; background: transparent;")
        self._layout.addWidget(self._placeholder)

    def build_audio_graph(self):
        """Build it, or say the file can't be read. Runs once."""
        if self._audio_graph_tried:
            return
        self._audio_graph_tried = True
        graph = AudioGraph()
        height = self.AUDIO_GRAPH_EXPANDED_HEIGHT if self._expanded else self.AUDIO_GRAPH_HEIGHT
        graph.setFixedHeight(height)
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
        self.audio_graph.seek_requested.connect(self._on_seek_requested)
        self.audio_graph.pressed.connect(lambda: self.picked.emit(self))
        self.audio_graph.selection_changed.connect(self._on_selection_changed)
        self.audio_graph.selection_cleared.connect(self._on_selection_cleared)
        self._layout.replaceWidget(self._placeholder, self.audio_graph)
        self._placeholder.setParent(None)
        self._placeholder.deleteLater()
        self._placeholder = None

    def _on_selection_changed(self, start, end):
        self._sel_start, self._sel_end = start, end
        self.picked.emit(self)

    def _on_selection_cleared(self):
        self._sel_start = self._sel_end = None

    def _icon_button(self, label, tooltip, slot):
        # No fixed width: the global 16px button padding clipped short fixed-width
        # labels. Let the button size to its text.
        btn = QPushButton(label)
        btn.setToolTip(tooltip)
        btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        btn.clicked.connect(slot)
        return btn

    def _build_header(self, session_name, thresholds_path):
        row = QHBoxLayout()
        t = theme.colors()
        self._play_icon = icons.play()
        self._pause_icon = icons.pause()
        self.play_btn = QPushButton(self._play_icon, " Play")
        self.play_btn.setIconSize(QSize(14, 14))
        self.play_btn.setFixedWidth(90)
        self.play_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.play_btn.setToolTip("Play or pause (Space)")
        self.play_btn.clicked.connect(self.toggle_play)
        self.play_btn.installEventFilter(self)
        row.addWidget(self.play_btn)

        # Play + Edit are the primary actions; fit / go-to-start / expand are
        # keyboard-only (F / Home / V) and the rest lives behind the … menu.
        if self._edit_enabled:
            self.edit_btn = self._icon_button(
                "Edit", "Edit this recording - trim, re-detect, append", self._on_edit)
            row.addWidget(self.edit_btn)

        # When it was recorded, not "mici_0": the mic index is a filename
        # disambiguator and tells the user nothing they can act on.
        stamp = get_recorded_at(session_name)
        title_text = recorded_at(stamp) if stamp else session_name
        name = QLabel(title_text)
        name.setStyleSheet(f"color: {t['text']}; font-weight: bold; border: none; background: transparent;")
        row.addWidget(name)

        length = wav_duration(self.wav_path)
        meta_text = self._build_meta_text(length)
        if meta_text:
            meta = QLabel(meta_text)
            meta.setStyleSheet(f"color: {t['text_dim']}; border: none; background: transparent;")
            row.addWidget(meta)

        # Otherwise a recording with no srt looks like one where nothing was detected
        self._detection_note = QLabel("Not segmented yet")
        self._detection_note.setStyleSheet(f"color: {t['text_dim']}; border: none; background: transparent;")
        self._detection_note.setVisible(not self.srt_path)
        row.addWidget(self._detection_note)

        row.addStretch()

        threshold_text = self._read_threshold(thresholds_path)
        if threshold_text:
            thr = QLabel(threshold_text)
            thr.setStyleSheet(f"color: {t['text_dim']}; border: none; background: transparent;")
            row.addWidget(thr)

        self.menu_btn = QPushButton()
        self.menu_btn.setIcon(_dots_icon(t["text"]))
        self.menu_btn.setIconSize(QSize(13, 13))
        self.menu_btn.setToolTip("Rename, move, open folder, or delete this recording")
        self.menu_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.menu_btn.setFixedWidth(40)
        self.menu_btn.clicked.connect(self._show_menu)
        row.addWidget(self.menu_btn)

        self.play_btn.setAccessibleName(
            f"{title_text}, {duration_text(length)}" if length else title_text)
        return row

    def _on_edit(self):
        self.picked.emit(self)
        self.action.emit(self, "edit")

    def _show_menu(self):
        self.picked.emit(self)
        menu = QMenu(self)
        for label, name in (("Rename…", "rename"),
                            ("Move to another sound…", "move"),
                            ("Open folder", "open")):
            act = menu.addAction(label)
            act.triggered.connect(lambda _checked=False, n=name: self.action.emit(self, n))
        menu.addSeparator()
        delete_act = menu.addAction("Delete recording")
        delete_act.triggered.connect(lambda: self.action.emit(self, "delete"))
        menu.exec(self.menu_btn.mapToGlobal(self.menu_btn.rect().bottomLeft()))

    def _build_meta_text(self, length):
        parts = []
        if length:
            parts.append(duration_text(length))
        info = library_ops.read_mic_info(self.wav_path) or {}
        if info.get("mic_name"):
            parts.append(info["mic_name"])
        # Everything runs at 16 kHz by design, so the rate is worth showing
        # only when a file departs from it (a few 48 kHz strays exist).
        rate = info.get("sample_rate")
        if rate and rate != RATE:
            parts.append(f"{rate / 1000:g} kHz")
        # Like the rate: the strategy is worth showing only when a take
        # departs from the configured default.
        strat = info.get("strategy")
        if strat and strat != strategies.CURRENT_DETECTION_STRATEGY:
            parts.append(strategies.label_for_strategy(strat))
        return "   ·   ".join(parts)

    def _read_threshold(self, path):
        if not path or not os.path.isfile(path):
            return ""
        dbfs = dtype = None
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if "=" not in line:
                        continue
                    key, value = line.strip().split("=", 1)
                    if key.endswith("_min_dbfs"):
                        dbfs = value
                    elif key.endswith("_duration_type"):
                        dtype = value
        except Exception:
            return ""
        parts = []
        if dbfs is not None:
            try:
                parts.append(f"{float(dbfs):.1f} dBFS")
            except ValueError:
                parts.append(f"{dbfs} dBFS")
        if dtype:
            parts.append(dtype)
        return "  ·  ".join(parts)

    # ---- selection / graph display ------------------------------------

    def set_selected(self, selected):
        self._apply_border(selected)

    def _apply_border(self, selected):
        t = theme.colors()
        color = t["accent"] if selected else t["border"]
        self.setStyleSheet(
            "RecordingCard { border: 1px solid %s; border-radius: %s; "
            "background-color: %s; } "
            "RecordingCard:hover { border-color: %s; }"
            % (color, t["radius"], t["card"], t["accent"])
        )

    def set_graph_display(self, graph_display):
        # Remembered, so an audio graph built later starts in it
        self._graph_display = graph_display
        if self.audio_graph is not None:
            self.audio_graph.set_graph_display(graph_display)

    def set_normalized(self, normalized):
        self._normalized = normalized
        if self.audio_graph is not None:
            self.audio_graph.set_normalized(normalized)

    # ---- quick controls ------------------------------------------------

    def fit_view(self):
        self.picked.emit(self)
        self.build_audio_graph()
        if self.audio_graph is not None:
            self.audio_graph.toggle_fit()

    def go_to_start(self):
        self.picked.emit(self)
        self.build_audio_graph()
        if self.audio_graph is None:
            return
        if self._playing:
            self.play(from_position=0.0)
        else:
            self._playhead_position = 0.0
            self.audio_graph.set_playhead(0.0)

    def toggle_expanded(self):
        self._expanded = not self._expanded
        height = self.AUDIO_GRAPH_EXPANDED_HEIGHT if self._expanded else self.AUDIO_GRAPH_HEIGHT
        self.build_audio_graph()
        if self.audio_graph is not None:
            self.audio_graph.setFixedHeight(height)
        self.picked.emit(self)

    def clear_selection(self):
        if self.audio_graph is not None:
            self.audio_graph.clear_selection()

    def deselect_or_start(self):
        """D/Esc: drop the selection if there is one, else jump to the start."""
        self.picked.emit(self)
        self.build_audio_graph()
        if self.audio_graph is not None and self.audio_graph.current_selection() is not None:
            self.audio_graph.clear_selection()
        else:
            self.go_to_start()

    # ---- playback ------------------------------------------------------

    def playable(self):
        self.build_audio_graph()
        return self.audio_graph is not None

    def toggle_play(self):
        if self._playing:
            self.pause()
        else:
            self.play()

    def play(self, from_position=None):
        """Play from the playhead, or from `from_position`. With a selection,
        Space / Play plays just that range, resuming if paused inside it. An
        explicit position ignores the selection."""
        self.build_audio_graph()
        if self.audio_graph is None:
            return      # unreadable, the card already says why
        if self._samples is None:
            self._samples, self._sample_rate = self.audio_graph.playback_audio()
            self._duration = self.audio_graph.duration()

        playing_selection = from_position is None and self._sel_start is not None
        if from_position is not None:
            self._playhead_position = from_position
        elif playing_selection and not (self._sel_start <= self._playhead_position < self._sel_end):
            self._playhead_position = self._sel_start
        if self._playhead_position >= self._duration:
            self._playhead_position = 0.0
        self._playhead_position = max(0.0, self._playhead_position)
        # Emit before playback.play(), so another card stops first and doesn't stop this stream
        self.picked.emit(self)
        self.playback_started.emit(self)

        self._play_start_position = self._playhead_position
        self._stop_at = self._sel_end if playing_selection else None
        start = int(self._playhead_position * self._sample_rate)
        end = int(self._stop_at * self._sample_rate) if self._stop_at is not None else None
        try:
            self._output_latency = playback.play(self._samples[start:end], self._sample_rate)
        except playback.PlaybackError:
            self._show_stopped()
            self.playback_failed.emit("That playback device would not open. "
                                      "Pick another above the cards.")
            return

        self._playing = True
        self.play_btn.setIcon(self._pause_icon)
        self.play_btn.setText(" Pause")
        self.audio_graph.set_playhead(self._playhead_position)
        self._play_clock.restart()
        self._playhead_timer.start()

    def pause(self):
        if self._playing:
            playback.stop()
            self._playhead_position = min(self._heard_position(), self._duration)
        self._show_stopped()
        if self.audio_graph is not None:
            self.audio_graph.set_playhead(self._playhead_position)

    def stop(self):
        """Stop, leaving the playhead where it is."""
        if self._playing:
            playback.stop()
        self._show_stopped()

    def _show_stopped(self):
        self._playing = False
        self._playhead_timer.stop()
        self.play_btn.setIcon(self._play_icon)
        self.play_btn.setText(" Play")

    def seek_relative(self, delta_seconds):
        position = self._heard_position() if self._playing else self._playhead_position
        self.play(from_position=max(0.0, position + delta_seconds))

    def eventFilter(self, obj, event):
        if obj is self.play_btn and event.type() == QEvent.Type.FocusIn:
            self.picked.emit(self)
        return super().eventFilter(obj, event)

    def _on_seek_requested(self, position):
        self.picked.emit(self)
        self._playhead_position = position
        self.audio_graph.set_playhead(position)
        if self._playing or playback.is_playing():
            self.play(from_position=position)

    def _heard_position(self):
        """Where playback has reached, in seconds. Audio leaves the device a
        buffer after play() is called, so without subtracting that the
        playhead runs ahead of what you hear."""
        seconds_since_play_started = self._play_clock.elapsed() / 1000.0
        heard_seconds = max(0.0, seconds_since_play_started - self._output_latency)
        return self._play_start_position + heard_seconds

    def _tick(self):
        heard_position = self._heard_position()
        limit = self._stop_at if self._stop_at is not None else self._duration
        if heard_position >= limit:
            # The playback thread finishes the stream itself. Aborting here would race it
            self._show_stopped()
            # Park at the selection start, to loop it, or the clip start
            looping = self._stop_at is not None and self._sel_start is not None
            self._playhead_position = self._sel_start if looping else 0.0
            self.audio_graph.set_playhead(self._playhead_position)
            return
        self._playhead_position = heard_position
        self.audio_graph.set_playhead(heard_position)
        if playback.failed_mid_play():
            self._show_stopped()

    def cleanup(self):
        """Stop, and release plot items before deletion."""
        self.stop()
        if self.audio_graph is not None:
            self.audio_graph.cleanup()
