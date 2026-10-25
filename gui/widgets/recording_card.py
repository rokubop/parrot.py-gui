import os
from datetime import datetime
import numpy as np
from PyQt6.QtCore import Qt, QTimer, QElapsedTimer, QPointF, QRectF, QSize, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPolygonF, QColor
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMenu
)
from config.config import RATE
from gui.widgets.audio_graph import AudioGraph, MODE_WAVEFORM
from gui.services import library_ops, playback, strategies
from gui.services.wav_files import wav_duration
from gui import theme


_ICON_CACHE = {}


def _media_icon(kind, color, size=13):
    """Theme-colored play/pause glyph as a fixed-size QIcon: text glyphs ▶/⏸
    have different heights and shift the layout when swapped. Cached per
    (kind, color, size)."""
    key = (kind, color, size)
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached
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
    else:  # pause
        bw = size * 0.24
        gap = size * 0.18
        p.drawRect(QRectF(size / 2 - gap / 2 - bw, m, bw, size - 2 * m))
        p.drawRect(QRectF(size / 2 + gap / 2, m, bw, size - 2 * m))
    p.end()
    icon = QIcon(pm)
    _ICON_CACHE[key] = icon
    return icon


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


def _parse_when(session_name):
    """Filenames end in __<unix-timestamp>; decode it to a readable date and
    time. The time is not decoration: several takes of one sound in a sitting
    is the normal way to record, and a date alone leaves those cards reading
    identically."""
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


class RecordingCard(QFrame):
    """One recording: when it was made, how long it is, and a waveform or
    spectrogram with detection overlaid. Plays, seeks, and fits, starts or
    expands from its controls."""

    AUDIO_GRAPH_HEIGHT = 150
    AUDIO_GRAPH_EXPANDED_HEIGHT = 440

    started = pyqtSignal(object)   # emits self when playback begins
    selected = pyqtSignal(object)  # emits self when the card is interacted with
    action = pyqtSignal(object, str)  # (card, action_name) for menu actions
    failed = pyqtSignal(str)       # playback could not start

    def __init__(self, session_name, wav_path, srt_path, thresholds_path, parent=None):
        super().__init__(parent)
        self.wav_path = wav_path
        self.srt_path = srt_path
        self.session_name = session_name
        self.label = library_ops.recording_label(wav_path)
        self._expanded = False
        self._edit_enabled = True  # set False to hide the Edit menu entry

        self._audio = None
        self._sample_rate = None
        self._duration = 0.0
        self._position = 0.0       # playhead position in seconds (kept across pause)
        self._play_start = 0.0     # position playback began from
        self._playing = False
        self._sel_start = None     # selected range (seconds), or None
        self._sel_end = None
        self._stop_at = None       # playback stop bound for the current play
        self._latency = 0.0        # output buffer delay of the current play

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._clock = QElapsedTimer()

        self._apply_border(False)

        # A placeholder until the Sounds page builds the audio graph
        self.audio_graph = None
        self._audio_graph_tried = False
        self._mode = MODE_WAVEFORM
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
        self.audio_graph = AudioGraph()
        height = self.AUDIO_GRAPH_EXPANDED_HEIGHT if self._expanded else self.AUDIO_GRAPH_HEIGHT
        self.audio_graph.setFixedHeight(height)
        problem = self.audio_graph.load(self.wav_path, self.srt_path)
        if problem:
            # Kept hidden, so the card's controls have an audio graph to talk
            # to. They do nothing without samples
            self.audio_graph.setParent(self)
            self.audio_graph.hide()
            # The name, not the date: it's the file to go and look at
            name = os.path.basename(self.wav_path)
            self._placeholder.setText(f"Can't read {name}\n{problem}")
            return
        self.audio_graph.set_mode(self._mode)
        self.audio_graph.set_normalized(self._normalized)
        self.audio_graph.seeked.connect(self._on_seek)
        self.audio_graph.pressed.connect(lambda: self.selected.emit(self))
        self.audio_graph.selection_changed.connect(self._on_selection_changed)
        self.audio_graph.selection_cleared.connect(self._on_selection_cleared)
        self._layout.replaceWidget(self._placeholder, self.audio_graph)
        self._placeholder.setParent(None)
        self._placeholder.deleteLater()
        self._placeholder = None

    def _on_selection_changed(self, start, end):
        self._sel_start, self._sel_end = start, end
        self.selected.emit(self)

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
        self._play_icon = _media_icon("play", t["text_bright"])
        self._pause_icon = _media_icon("pause", t["text_bright"])
        self.play_btn = QPushButton(self._play_icon, " Play")
        self.play_btn.setIconSize(QSize(13, 13))
        self.play_btn.setFixedWidth(90)
        self.play_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.play_btn.clicked.connect(self.toggle_play)
        row.addWidget(self.play_btn)

        # Play + Edit are the primary actions; fit / go-to-start / expand are
        # keyboard-only (F / Home / V) and the rest lives behind the … menu.
        if self._edit_enabled:
            self.edit_btn = self._icon_button(
                "Edit", "Edit this recording - trim, re-detect, append", self._on_edit)
            row.addWidget(self.edit_btn)

        # When it was recorded, not "mici_0": the mic index is a filename
        # disambiguator and tells the user nothing they can act on.
        title = _parse_when(session_name) or session_name
        name = QLabel(title)
        name.setStyleSheet(f"color: {t['text']}; font-weight: bold; border: none; background: transparent;")
        row.addWidget(name)

        meta_text = self._build_meta_text(session_name)
        if meta_text:
            meta = QLabel(meta_text)
            meta.setStyleSheet(f"color: {t['text_dim']}; border: none; background: transparent;")
            row.addWidget(meta)

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
        return row

    def _on_edit(self):
        self.selected.emit(self)
        self.action.emit(self, "edit")

    def _show_menu(self):
        self.selected.emit(self)
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

    def _build_meta_text(self, session_name):
        parts = []
        length = wav_duration(self.wav_path)
        if length:
            parts.append(f"{length:.1f}s")
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

    # ---- selection / mode ---------------------------------------------

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

    def set_mode(self, mode):
        # Remembered, so an audio graph built later starts in it
        self._mode = mode
        if self.audio_graph is not None:
            self.audio_graph.set_mode(mode)

    def set_normalized(self, normalized):
        self._normalized = normalized
        if self.audio_graph is not None:
            self.audio_graph.set_normalized(normalized)

    # ---- quick controls ------------------------------------------------

    def fit_view(self):
        self.selected.emit(self)
        self.build_audio_graph()
        self.audio_graph.toggle_fit()

    def go_to_start(self):
        self.selected.emit(self)
        self.build_audio_graph()
        if self._playing:
            self.play(from_seconds=0.0)
        else:
            self._position = 0.0
            self.audio_graph.set_playhead(0.0)

    def toggle_expanded(self):
        self._expanded = not self._expanded
        height = self.AUDIO_GRAPH_EXPANDED_HEIGHT if self._expanded else self.AUDIO_GRAPH_HEIGHT
        self.build_audio_graph()
        self.audio_graph.setFixedHeight(height)
        if hasattr(self, "expand_btn"):
            self.expand_btn.setText("Collapse" if self._expanded else "Expand")
        self.selected.emit(self)

    def clear_selection(self):
        if self.audio_graph is not None:
            self.audio_graph._clear_selection()

    def deselect_or_start(self):
        """D/Esc: drop the selection if there is one, else jump to the start."""
        self.selected.emit(self)
        self.build_audio_graph()
        if self.audio_graph is not None and self.audio_graph.current_selection() is not None:
            self.audio_graph._clear_selection()
        else:
            self.go_to_start()

    # ---- playback ------------------------------------------------------

    def _load_audio(self):
        if self._audio is not None:
            return
        # Reuse the samples the audio graph already decoded for the waveform instead
        # of re-reading the whole WAV on the UI thread (which froze the first
        # play). These are mono float32 in [-1, 1] - sounddevice plays them as-is.
        self.build_audio_graph()
        samples, sample_rate = self.audio_graph.playback_audio()
        if samples is None or sample_rate is None:
            return
        self._audio = samples
        self._sample_rate = sample_rate
        self._duration = self.audio_graph.duration()

    def toggle_play(self):
        if self._playing:
            self.pause()
        else:
            self.play()

    def play(self, from_seconds=None):
        try:
            self._load_audio()
        except Exception:
            return
        if self._audio is None or self._sample_rate is None:
            return

        # Space / Play with a selection plays just that range (resuming from the
        # current spot if we're paused inside it). An explicit seek ignores it.
        playing_selection = from_seconds is None and self._sel_start is not None
        if from_seconds is not None:
            self._position = from_seconds
        elif playing_selection and not (self._sel_start <= self._position < self._sel_end):
            self._position = self._sel_start

        self.selected.emit(self)
        self.started.emit(self)

        self._position = max(0.0, min(self._position, self._duration))
        self._play_start = self._position
        self._stop_at = self._sel_end if playing_selection else None
        start_sample = int(self._position * self._sample_rate)
        if self._stop_at is not None:
            clip = self._audio[start_sample:int(self._stop_at * self._sample_rate)]
        else:
            clip = self._audio[start_sample:]

        try:
            self._latency = playback.play(clip, self._sample_rate)
        except playback.PlaybackError:
            self.failed.emit("That playback device would not open. "
                             "Pick another above the cards.")
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
            self._position = self._heard_position()
            self._position = max(0.0, min(self._position, self._duration))
        self._playing = False
        self._timer.stop()
        self.play_btn.setIcon(self._play_icon)
        self.play_btn.setText(" Play")
        self.audio_graph.set_playhead(self._position)

    def stop(self):
        """Stop playback without preserving position (used when another card plays)."""
        if self._playing:
            playback.stop()
        self._playing = False
        self._timer.stop()
        self.play_btn.setIcon(self._play_icon)
        self.play_btn.setText(" Play")

    def cleanup(self):
        """Release resources before deletion."""
        self.stop()
        if self.audio_graph is not None:
            self.audio_graph.cleanup()

    def seek_relative(self, delta_seconds):
        pos = self._position
        if self._playing:
            pos = self._heard_position()
        self.play(from_seconds=pos + delta_seconds)

    def _on_seek(self, seconds):
        # Clicking/scrubbing positions the playhead; it only plays if already
        # playing (jump and continue). Use Play / Space to start from a stop.
        dur = self.audio_graph.duration()
        self._position = max(0.0, min(seconds, dur)) if dur else max(0.0, seconds)
        self.audio_graph.set_playhead(self._position)
        if self._playing:
            self.play(from_seconds=self._position)

    def _heard_position(self):
        """Where playback has actually reached, in seconds. The clock starts
        when play() is called but the audio only leaves the device a buffer
        later, so without subtracting that the playhead sits ahead of what
        you're hearing - and points past the blip you were auditioning."""
        return self._play_start + max(0.0, self._clock.elapsed() / 1000.0 - self._latency)

    def _tick(self):
        elapsed = self._heard_position()
        limit = self._stop_at if self._stop_at is not None else self._duration
        if elapsed >= limit:
            self.audio_graph.set_playhead(limit)
            self.stop()
            # Park at the selection start (loopable) or the clip start.
            self._position = self._sel_start if self._stop_at is not None else 0.0
            self.audio_graph.set_playhead(self._position)
            return
        self._position = elapsed
        self.audio_graph.set_playhead(elapsed)
