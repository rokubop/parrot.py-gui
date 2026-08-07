"""Test integration - what Talon is hearing, live.

talon-parrot-tester's Activity, Frames, Detection log and Stats pages, as one
screen. Its palette and its power x probability bar, so a colour and a bar mean
the same thing in both tools.

Two of its features need code inside Talon and cannot be done from here:
silencing actions while you test, and drawing over a full-screen game.

Frames arrive from the bridge via BridgeWorker; grouping is capture_model.
"""
import json
import os
import time

from PyQt6.QtCore import Qt, pyqtSignal, QRect, QTimer, QThread
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QSplitter,
    QCheckBox, QStyledItemDelegate, QApplication, QFrame, QStackedWidget,
    QTreeWidget, QTreeWidgetItem
)

from gui import components, theme
from gui.services import (capture_model, live_stats, pattern_colors,
                          talon_companion)
from gui.workers.bridge_worker import BridgeWorker
from gui.services.talon_companion import BRIDGE_PORT
from config.config import DATA_DIR

CAPTURES_DIR = os.path.join(DATA_DIR, "talon", "captures")

# The tester's own scale: the bar is full at power 30, so bars from the two
# tools can be compared by eye.
POWER_SCALE = 30.0

# Words, not glyphs. The tester uses drawn icons; the nearest characters here
# are emoji on Windows, and a clock face rendered in full colour next to a
# monospace number reads as a bug. Colour still carries the meaning.
_STATUS_MARK = {"detected": "fired", "grace_detected": "grace",
                "throttled": "throttled"}


# theme.PATTERN_STATUS, so this and pattern_card.py cannot drift apart.
def _status_color(status):
    return theme.status_color(status) or theme.colors()["text_dim"]


def _status_of(row):
    """capture_model keeps 'detected' and the grace flag apart. One word here."""
    if row["status"] == "detected" and row["graceperiod"]:
        return "grace_detected"
    return row["status"]


class RatioBarDelegate(QStyledItemDelegate):
    """Bar length is power / POWER_SCALE, each pattern fills its probability
    share of it, red tick is the power threshold. Short of the tick = too
    quiet, however confident."""

    def paint(self, painter, option, index):
        data = index.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        rect = option.rect.adjusted(6, 0, -6, 0)
        height = 9
        top = rect.y() + (rect.height() - height) // 2
        full = rect.width()
        power_fraction = min(POWER_SCALE, max(0.0, data["power"])) / POWER_SCALE
        width = int(full * power_fraction)
        if width > 0:
            painter.fillRect(QRect(rect.x(), top, width, height),
                             QColor("#555555"))
        offset = rect.x()
        for probability, colour in data["segments"]:
            part = int(width * max(0.0, min(1.0, probability)))
            if part <= 0:
                continue
            painter.fillRect(QRect(offset, top, part, height), QColor(colour))
            offset += part
        threshold = data.get("threshold")
        if threshold:
            tick = int(full * min(POWER_SCALE, threshold) / POWER_SCALE)
            painter.fillRect(QRect(rect.x() + tick - 1, top - 3, 2, height + 6),
                             QColor("#d33333"))
        painter.restore()


class RatioBar(QWidget):
    """The same graphic, standalone, for the readout at the top."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(14)
        self.setMinimumWidth(160)
        self._data = None

    def set_frame(self, power, segments, threshold):
        self._data = {"power": power, "segments": segments,
                      "threshold": threshold}
        self.update()

    def clear(self):
        self._data = None
        self.update()

    def paintEvent(self, _event):
        if not self._data:
            return
        painter = QPainter(self)
        rect = self.rect()
        height = 12
        top = (rect.height() - height) // 2
        full = rect.width()
        power_fraction = min(POWER_SCALE,
                             max(0.0, self._data["power"])) / POWER_SCALE
        width = int(full * power_fraction)
        painter.fillRect(QRect(0, top, width, height), QColor("#555555"))
        offset = 0
        for probability, colour in self._data["segments"]:
            part = int(width * max(0.0, min(1.0, probability)))
            if part <= 0:
                continue
            painter.fillRect(QRect(offset, top, part, height), QColor(colour))
            offset += part
        threshold = self._data.get("threshold")
        if threshold:
            tick = int(full * min(POWER_SCALE, threshold) / POWER_SCALE)
            painter.fillRect(QRect(tick - 1, top - 3, 2, height + 6),
                             QColor("#d33333"))


class _TalonProbe(QThread):
    """Process check off the UI thread - tasklist takes ~100 ms."""
    result = pyqtSignal(object)

    def run(self):
        from gui.services import talon_process
        self.result.emit(talon_process.is_running())


class TalonTestView(QWidget):
    """Owns the bridge worker while visible; the page starts and stops it."""

    done = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self.collection = capture_model.CaptureCollection({})
        self.patterns = {}
        self.colors = {}
        self._connected = False
        self._asleep = False
        self._talon_running = None    # None = not checked / cannot tell
        self._probe = None
        self._sim_talon = None        # PARROT_DEBUG state override
        self._listen_timer = QTimer(self)
        self._listen_timer.setInterval(2000)
        self._listen_timer.timeout.connect(talon_companion.announce_listening)
        self._recording = None    # open file handle while recording
        self._last_detected = None    # (frame, ts) of the last real detection
        self._latest_ts = 0.0
        self._model_name = ""
        self._setup_ui()

    # ---- lifecycle -------------------------------------------------------

    def set_patterns(self, patterns_json):
        self.patterns = patterns_json or {}
        self.colors = pattern_colors.colors_for(self.patterns)
        self.collection.set_patterns(self.patterns)
        self._fill_pattern_list()

    def set_model(self, name):
        self._model_name = name or ""
        self._refresh_title()

    def refresh_state(self):
        self._refresh_empty()

    def start(self):
        # Ask Talon's bridge to attach, and keep asking: it detaches on its own
        # a few seconds after this stops, so leaving the screen (or killing the
        # app) puts Talon back the way it was.
        talon_companion.announce_listening()
        self._listen_timer.start()
        self._check_talon()
        if self.worker is not None and self.worker.isRunning():
            return
        self.worker = BridgeWorker(BRIDGE_PORT)
        self.worker.status_changed.connect(self._on_status)
        self.worker.frames_received.connect(self._on_frames)
        self.worker.start()

    def stop(self):
        self._listen_timer.stop()
        talon_companion.stop_listening()
        self._connected = False
        if self.worker is not None:
            self.worker.stop()
            self.worker.wait(1000)
            self.worker = None
        if self._probe is not None:
            self._probe.wait(4000)
            self._probe = None
        self._stop_recording()

    # ---- ui ----------------------------------------------------------------

    def _setup_ui(self):
        t = theme.colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(10)

        head = QHBoxLayout()
        back = QPushButton("‹  Back")
        back.setFlat(True)
        back.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        back.clicked.connect(self.done.emit)
        head.addWidget(back)
        self.title = components.heading("", "card")
        head.addWidget(self.title)
        self.status_label = QLabel("Waiting for Talon…")
        self.status_label.setStyleSheet(f"color: {t['text_dim']};")
        head.addWidget(self.status_label, 1)
        self.record_btn = QPushButton("● Record session")
        self.record_btn.setCheckable(True)
        self.record_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.record_btn.setToolTip(
            "Save raw frames to data/talon/captures, so a draft can be replayed "
            "against them later")
        self.record_btn.toggled.connect(self._on_record_toggled)
        head.addWidget(self.record_btn)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clear_btn.clicked.connect(self._on_clear)
        head.addWidget(self.clear_btn)
        layout.addLayout(head)

        # Two screens, not one screen with everything greyed out. Frames,
        # stats, thresholds and formants say nothing while the thing that
        # produces them is not connected yet.
        self.modes = QStackedWidget()
        layout.addWidget(self.modes, 1)

        self.modes.addWidget(self._build_empty_panel())

        testing = QWidget()
        testing_layout = QVBoxLayout(testing)
        testing_layout.setContentsMargins(0, 0, 0, 0)
        testing_layout.setSpacing(10)
        self.readout_card = self._build_readout()
        self.readout_card.setVisible(False)
        testing_layout.addWidget(self.readout_card)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_pattern_list())
        splitter.addWidget(self._build_tables())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 900])
        testing_layout.addWidget(splitter, 1)

        self.legend = QLabel("")
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        testing_layout.addWidget(self.legend)
        self.modes.addWidget(testing)

        self._refresh_legend()
        self._refresh_title()

    def _build_readout(self):
        """What just fired, big enough to read while you are making the sound
        rather than looking at the screen."""
        t = theme.colors()
        card = QFrame()
        card.setObjectName("readoutCard")
        card.setStyleSheet(components.card_style("readoutCard"))
        row = QHBoxLayout(card)
        row.setContentsMargins(*components.CARD_MARGINS)
        row.setSpacing(20)

        self.big_name = components.heading("–", "stat", color=t["accent"])
        self.big_name.setMinimumWidth(220)
        row.addWidget(self.big_name)

        numbers = QVBoxLayout()
        numbers.setSpacing(0)
        self.big_numbers = QLabel("")
        self.big_numbers.setStyleSheet(
            f"font-family: Consolas, monospace; "
            f"font-size: {theme.TYPE_SCALE['section']}px; "
            f"color: {t['text']};")
        numbers.addWidget(self.big_numbers)
        caption = QLabel("power / probability")
        caption.setStyleSheet(f"color: {t['text_dim']}; ")
        numbers.addWidget(caption)
        row.addLayout(numbers)

        self.readout_bar = RatioBar()
        row.addWidget(self.readout_bar, 1)

        self.ago_label = QLabel("")
        self.ago_label.setStyleSheet(f"color: {t['text_dim']};")
        row.addWidget(self.ago_label)
        return card

    def _build_pattern_list(self):
        """Every pattern, in its colour, with what it takes to fire it. Lit
        while it is winning frames in the capture on screen."""
        t = theme.colors()
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        label = QLabel("Patterns")
        label.setStyleSheet(f"color: {t['text_dim']};")
        v.addWidget(label)
        self.pattern_list = QTreeWidget()
        self.pattern_list.setColumnCount(2)
        self.pattern_list.setHeaderLabels(["Pattern", "Fires when"])
        self.pattern_list.setRootIsDecorated(False)
        self.pattern_list.setUniformRowHeights(True)
        self.pattern_list.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self.pattern_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header = self.pattern_list.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        v.addWidget(self.pattern_list, 1)
        return wrap

    def _build_tables(self):
        t = theme.colors()
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        tools = QHBoxLayout()
        self._tab_btns = {}
        for key, text in (("frames", "Frames"), ("stats", "Stats")):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setFlat(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.clicked.connect(lambda _c, k=key: self._show_tab(k))
            tools.addWidget(btn)
            self._tab_btns[key] = btn
        tools.addSpacing(14)
        self.capture_combo = QComboBox()
        self.capture_combo.setMinimumWidth(190)
        self.capture_combo.setToolTip(
            "Detections, newest first. The top one follows what is happening.")
        self.capture_combo.currentIndexChanged.connect(
            lambda _i: self._render_frames())
        tools.addWidget(self.capture_combo)
        tools.addStretch()
        self.thresholds_check = QCheckBox("Thresholds")
        self.thresholds_check.setChecked(True)
        self.thresholds_check.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.thresholds_check.setToolTip(
            "Show each pattern's own threshold next to the value it is measured "
            "against")
        self.thresholds_check.stateChanged.connect(lambda _s: self._render_frames())
        tools.addWidget(self.thresholds_check)
        self.formants_check = QCheckBox("F0 F1 F2")
        self.formants_check.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.formants_check.setToolTip(
            "Vocal formants. Off unless a pattern uses them - three columns of "
            "numbers most setups never threshold on")
        self.formants_check.stateChanged.connect(self._on_formants_toggled)
        tools.addWidget(self.formants_check)
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.copy_btn.setToolTip("Copy every pattern's numbers as text")
        self.copy_btn.clicked.connect(self._on_copy_stats)
        self.copy_btn.setVisible(False)
        tools.addWidget(self.copy_btn)
        v.addLayout(tools)

        self.stack = QStackedWidget()
        self.table = QTableWidget(0, 10)
        self._base_headers = ["Frame", "Δts", "Pattern", "Power", ">pow",
                              "Prob.", ">prob", "F0", "F1", "F2", "Status",
                              "Power × Prob."]
        self.table.setColumnCount(len(self._base_headers))
        self.table.setHorizontalHeaderLabels(self._base_headers)
        self.table.setItemDelegateForColumn(11, RatioBarDelegate(self.table))
        # Numbers sized to their contents; leftover width goes to the bar,
        # the column that gets more useful the wider it is.
        components.style_table(self.table, stretch=11)
        self.stack.addWidget(self.table)

        # min · avg · max on one line per pattern, so the table reads down a
        # column. The empty last column absorbs the slack; otherwise Qt
        # stretches a real column.
        self.stats_table = QTableWidget(0, 8)
        self.stats_table.setHorizontalHeaderLabels(
            ["Pattern", "Frames", "Power", "Probability", "F0", "F1", "F2", ""])
        for col in range(2, 7):
            self.stats_table.horizontalHeaderItem(col).setToolTip(
                "lowest · average · highest, over the frames where this "
                "pattern was the one winning")
        self.stats_table.horizontalHeaderItem(1).setToolTip(
            "how many frames this pattern won in this session")
        components.style_table(self.stats_table, stretch=7)
        self.stack.addWidget(self.stats_table)
        v.addWidget(self.stack, 1)
        self._show_tab("frames")
        return wrap

    _EMPTY_BODY_WIDTH = 520

    def _build_empty_panel(self):
        """This screen is empty for reasons that are not the user's fault and
        are invisible from here: no bridge file, Talon not running, or nobody
        has made a sound yet. Each one gets its own words and, where there is
        one, its button."""
        t = theme.colors()
        panel = QWidget()
        outer = QVBoxLayout(panel)
        outer.addStretch()
        inner = QVBoxLayout()
        inner.setSpacing(8)
        self.empty_title = QLabel("")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title.setStyleSheet(components.heading_style("section"))
        inner.addWidget(self.empty_title)
        # A word-wrapped label reports a one-line sizeHint, so a layout that is
        # not asked for heightForWidth clips it. Pin the width, ask for the
        # height this copy needs - same trap as the Models tab's empty state.
        self.empty_body = QLabel("")
        self.empty_body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_body.setWordWrap(True)
        self.empty_body.setFixedWidth(self._EMPTY_BODY_WIDTH)
        self.empty_body.setStyleSheet(f"color: {t['text_dim']};")
        inner.addWidget(self.empty_body, 0, Qt.AlignmentFlag.AlignHCenter)
        self.empty_note = QLabel("")
        self.empty_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_note.setWordWrap(True)
        self.empty_note.setStyleSheet(f"color: {t['text_dim']};")
        inner.addWidget(self.empty_note)
        outer.addLayout(inner)
        outer.addStretch()
        return panel

    def _refresh_empty(self):
        """Live state only. The bridge is settled before this screen opens, so
        nothing here is a setup step - it is Talon being closed, asleep, or
        quiet."""
        if not hasattr(self, "empty_title"):
            return
        waiting = not self._connected or not self.collection.captures
        self.modes.setCurrentIndex(0 if waiting else 1)
        self.record_btn.setVisible(not waiting)
        self.clear_btn.setVisible(not waiting)
        if not waiting:
            return

        if not self._connected and self._talon_running is False:
            title = "Talon is not running"
            body = "Start Talon and this connects on its own."
        elif not self._connected:
            title = "Waiting for Talon"
            body = ("Nothing is coming through yet. Restarting Talon is the "
                    "usual fix.")
        elif self._asleep:
            title = "Talon is asleep"
            body = ("Connected, but Talon is asleep. Say \"wake up\" if your "
                    "sounds are not getting through.")
        else:
            title = "Make a sound"
            body = ("Connected. Nothing has been loud or clear enough to "
                    "trigger a pattern yet.")
        self.empty_title.setText(title)
        components.set_wrapped_text(self.empty_body, body,
                                    self._EMPTY_BODY_WIDTH)
        self.empty_note.setVisible(False)

    def _show_tab(self, key):
        for name, btn in self._tab_btns.items():
            btn.setChecked(name == key)
        t = theme.colors()
        for name, btn in self._tab_btns.items():
            on = name == key
            btn.setStyleSheet(
                f"QPushButton {{ color: "
                f"{t['text_bright'] if on else t['text_dim']}; "
                f"border: none; border-bottom: 2px solid "
                f"{t['accent'] if on else 'transparent'}; "
                f"padding: 4px 10px; font-weight: {'bold' if on else 'normal'}; }}")
        frames = key == "frames"
        self.capture_combo.setVisible(frames and bool(self.collection.captures))
        self.thresholds_check.setVisible(frames)
        self.copy_btn.setVisible(not frames)
        if frames:
            self._render_frames()
        else:
            self.stack.setCurrentIndex(1)
            self._render_stats()

    # ---- dev simulation ------------------------------------------------

    def simulate_talon(self, state):
        """PARROT_DEBUG=1 only, driven from the page's ... menu."""
        if state == "off":
            self._sim_talon = None
            self._check_talon()
        else:
            self._sim_talon = state
            self._connected = state in ("asleep", "awake")
            self._asleep = state == "asleep"
            self._talon_running = state != "closed"
        self._refresh_empty()

    def simulate_frames(self):
        from gui.services import integration_sim
        self._latest_ts += 1.0
        self._on_frames(integration_sim.fake_frames(self.patterns,
                                                    self._latest_ts))

    def _check_talon(self):
        if self._sim_talon is not None:
            return
        if self._probe is not None and self._probe.isRunning():
            return
        self._probe = _TalonProbe(self)
        self._probe.result.connect(self._on_talon_checked)
        self._probe.start()

    def _on_talon_checked(self, running):
        self._talon_running = running
        self._refresh_empty()

    def _on_formants_toggled(self, _state):
        if self.stack.currentIndex() == 0:
            self._render_frames()
        else:
            self._render_stats()

    def _refresh_title(self):
        model = f" · {self._model_name}" if self._model_name else ""
        count = len(self.patterns)
        self.title.setText(f"Testing Talon{model} · {count} patterns")

    def _refresh_legend(self):
        t = theme.colors()
        parts = [
            f"<span style='color:{_status_color('detected')};'>fired</span>",
            f"<span style='color:{_status_color('grace_detected')};'>grace</span> "
            f"- fired under the softer rules after a detection",
            f"<span style='color:{_status_color('throttled')};'>throttled</span> "
            f"- would have fired, held back",
            f"<span style='color:#d33333;'>|</span> the pattern's power threshold",
        ]
        self.legend.setText(
            f"<span style='color:{t['text_dim']};'>"
            + "&nbsp;&nbsp;&nbsp; ".join(parts) + "</span>")

    # ---- bridge events ------------------------------------------------------

    def _on_status(self, status):
        t = theme.colors()
        if self._sim_talon is not None:
            return       # a simulated state is not overwritten by a real one
        self._connected = bool(status.get("connected"))
        modes = (status.get("hello") or {}).get("modes") or []
        self._asleep = "sleep" in modes
        if not self._connected:
            self._check_talon()
        if status.get("error"):
            self.status_label.setText(
                f"<span style='color:{t['bad']};'>{status['error']}</span>")
        elif status.get("connected"):
            hello = status.get("hello") or {}
            if hello.get("wrapped"):
                self.status_label.setText(
                    f"<span style='color:{t['accent']};'>receiving</span>")
            else:
                self.status_label.setText(
                    f"<span style='color:{t['warn']};'>connected, waiting for the "
                    f"parrot integration to load</span>")
        else:
            self.status_label.setText(
                f"<span style='color:{t['text_dim']};'>waiting for Talon</span>")
        self._refresh_empty()

    def _on_frames(self, raw_frames):
        completed = False
        for raw in raw_frames:
            if self._recording is not None:
                self._recording.write(json.dumps(raw) + "\n")
            if self.collection.add_raw(raw) is not None:
                completed = True
            self._latest_ts = max(self._latest_ts, raw.get("ts", 0.0))
        self._track_detection()
        if completed or self.collection.current is not None:
            self._refresh_captures()
        self._refresh_readout()

    def _track_detection(self):
        capture = self.collection.current or (
            self.collection.captures[-1] if self.collection.captures else None)
        if capture is None:
            return
        for frame in reversed(capture.frames):
            if frame.detected and frame.winner:
                self._last_detected = frame
                return

    # ---- readout -------------------------------------------------------------

    def _segments(self, frame):
        return [(row["probability"], self.colors.get(row["name"], "#ffffff"))
                for row in frame.patterns]

    def _threshold(self, name, key=">power"):
        pattern = self.patterns.get(name)
        if not isinstance(pattern, dict):
            return None
        value = (pattern.get("threshold") or {}).get(key)
        return value if isinstance(value, (int, float)) else None

    def _refresh_readout(self):
        frame = self._last_detected
        # Hidden until something fires: an empty readout is a big grey box
        # over the one screen that has to explain why it is empty.
        self.readout_card.setVisible(frame is not None and bool(frame.winner))
        if frame is None or not frame.winner:
            self.big_name.setText("–")
            self.big_numbers.setText("")
            self.ago_label.setText("")
            self.readout_bar.clear()
            return
        winner = frame.winner
        colour = self.colors.get(winner["name"], theme.colors()["accent"])
        self.big_name.setText(winner["name"])
        self.big_name.setStyleSheet(components.heading_style("stat", colour))
        self.big_numbers.setText(
            f"{frame.power:.2f} / {winner['probability']:.4f}")
        self.readout_bar.set_frame(frame.power, self._segments(frame),
                                   self._threshold(winner["name"]))
        gap = max(0.0, self._latest_ts - frame.ts)
        self.ago_label.setText("just now" if gap < 0.4 else f"{gap:.1f}s ago")

    # ---- patterns ------------------------------------------------------------

    def _fill_pattern_list(self):
        t = theme.colors()
        self.pattern_list.clear()
        for name, pattern in self.patterns.items():
            pattern = pattern if isinstance(pattern, dict) else {}
            rules = pattern.get("threshold") or {}
            summary = "  ".join(f"{op} {value}" for op, value in rules.items())
            item = QTreeWidgetItem([f"■  {name}", summary])
            item.setData(0, Qt.ItemDataRole.UserRole, name)
            item.setForeground(0, QColor(self.colors.get(name, "#ffffff")))
            item.setForeground(1, QColor(t["text_dim"]))
            sounds = pattern.get("sounds")
            if isinstance(sounds, list) and sounds:
                item.setToolTip(0, "listens for " + ", ".join(sounds))
            self.pattern_list.addTopLevelItem(item)
        self._light_patterns([])

    def _light_patterns(self, active_names):
        """Dim every pattern that had nothing to do with the capture on
        screen, so the ones that did are readable at a glance."""
        t = theme.colors()
        active = set(active_names)
        for i in range(self.pattern_list.topLevelItemCount()):
            item = self.pattern_list.topLevelItem(i)
            name = item.data(0, Qt.ItemDataRole.UserRole)
            lit = name in active
            colour = self.colors.get(name, "#ffffff")
            item.setForeground(0, QColor(colour if lit or not active
                                         else t["text_faint"]))
            font = item.font(0)
            font.setBold(lit)
            item.setFont(0, font)

    # ---- captures + frames table --------------------------------------------

    def _refresh_captures(self):
        follow_latest = self.capture_combo.currentIndex() <= 0
        self.capture_combo.blockSignals(True)
        self.capture_combo.clear()
        for capture in reversed(self.collection.captures):
            names = ", ".join(capture.pattern_names) or "?"
            live = " ●" if capture is self.collection.current else ""
            self.capture_combo.addItem(
                f"{names}{live}   ({len(capture.frames)} frames)")
        self.capture_combo.blockSignals(False)
        if self.collection.captures and follow_latest:
            self.capture_combo.setCurrentIndex(0)
        self.capture_combo.setVisible(bool(self.collection.captures)
                                      and self._tab_btns["frames"].isChecked())
        self._refresh_empty()
        self._render_frames()

    def _current_capture(self):
        row = self.capture_combo.currentIndex()
        if row < 0 or not self.collection.captures:
            return None
        index = len(self.collection.captures) - 1 - row
        if 0 <= index < len(self.collection.captures):
            return self.collection.captures[index]
        return None

    def _render_frames(self):
        if self._tab_btns["stats"].isChecked():
            return
        self.stack.setCurrentIndex(0)
        capture = self._current_capture()
        show_formants = self.formants_check.isChecked()
        show_thresholds = self.thresholds_check.isChecked()
        for col in (7, 8, 9):
            self.table.setColumnHidden(col, not show_formants)
        for col in (4, 6):
            self.table.setColumnHidden(col, not show_thresholds)
        if capture is None:
            self.table.setRowCount(0)
            self._light_patterns([])
            return

        self._light_patterns(capture.pattern_names)
        frames = capture.frames
        first_detect_ts = (capture.detect_frames[0].ts if capture.detect_frames
                           else (frames[0].ts if frames else 0))
        t = theme.colors()
        self.table.setRowCount(len(frames))
        for row, frame in enumerate(frames):
            delta = (frame.ts_delta if frame.ts_delta is not None
                     else frame.ts - first_detect_ts)
            names = "\n".join(p["name"] for p in frame.patterns)
            probs = "\n".join(f"{p['probability']:.4f}" for p in frame.patterns)
            statuses = "\n".join(_STATUS_MARK.get(_status_of(p), "–")
                                 for p in frame.patterns)
            pow_thresholds = "\n".join(
                _fmt_threshold_value(self._threshold(p["name"], ">power"))
                for p in frame.patterns)
            prob_thresholds = "\n".join(
                _fmt_threshold_value(self._threshold(p["name"], ">probability"))
                for p in frame.patterns)
            cells = [
                str(frame.id if frame.id is not None else row + 1),
                f"{delta:+.3f}",
                names,
                f"{frame.power:.2f}",
                pow_thresholds,
                probs,
                prob_thresholds,
                f"{frame.f0:.0f}",
                f"{frame.f1:.0f}",
                f"{frame.f2:.0f}",
                statuses,
                "",
            ]
            for col, value in enumerate(cells):
                item = QTableWidgetItem(value)
                if col in (4, 6):
                    item.setForeground(QColor(t["text_faint"]))
                if col == 10 and frame.patterns:
                    item.setForeground(
                        QColor(_status_color(_status_of(frame.patterns[0]))))
                if col == 0 and frame.detected:
                    item.setForeground(QColor(_status_color("detected")))
                self.table.setItem(row, col, item)
            winner = frame.winner
            self.table.item(row, 11).setData(
                Qt.ItemDataRole.UserRole,
                {"power": frame.power,
                 "segments": self._segments(frame),
                 "threshold": self._threshold(winner["name"]) if winner else None})
        self.table.resizeRowsToContents()

    # ---- stats ---------------------------------------------------------------

    def _render_stats(self):
        rows = live_stats.compute(self.collection.captures, self.patterns.keys())
        t = theme.colors()
        show_formants = self.formants_check.isChecked()
        for col in (4, 5, 6):
            self.stats_table.setColumnHidden(col, not show_formants)
        ordered = sorted(rows.values(), key=lambda r: -r["count"])
        self.stats_table.setRowCount(len(ordered))
        for row, entry in enumerate(ordered):
            silent = not entry["count"]
            cells = [entry["name"], str(entry["count"])]
            for metric in ("power", "probability", "f0", "f1", "f2"):
                stat = entry[metric]
                places = 4 if metric == "probability" else \
                    2 if metric == "power" else 0
                # Nothing rather than three zeroes: a pattern that never won a
                # frame has no numbers, and printing 0.00 three times says it
                # measured something.
                cells.append("" if silent else
                             f"{stat['min']:.{places}f} · "
                             f"{stat['average']:.{places}f} · "
                             f"{stat['max']:.{places}f}")
            cells.append("")
            for col, value in enumerate(cells):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setForeground(QColor(
                        t["text_faint"] if silent
                        else self.colors.get(entry["name"], "#ffffff")))
                elif col > 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                          | Qt.AlignmentFlag.AlignVCenter)
                if col == 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                          | Qt.AlignmentFlag.AlignVCenter)
                    if silent:
                        item.setForeground(QColor(t["text_faint"]))
                        item.setToolTip("never won a frame in this session")
                self.stats_table.setItem(row, col, item)

    def _on_copy_stats(self):
        rows = live_stats.compute(self.collection.captures, self.patterns.keys())
        text = "\n".join(live_stats.as_text(row)
                         for row in sorted(rows.values(),
                                           key=lambda r: -r["count"]))
        QApplication.clipboard().setText(text)
        self.copy_btn.setText("Copied")
        self.copy_btn.setEnabled(False)

    # ---- recording ------------------------------------------------------------

    def _on_record_toggled(self, on):
        if on:
            os.makedirs(CAPTURES_DIR, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            path = os.path.join(CAPTURES_DIR, f"session-{stamp}.jsonl")
            self._recording = open(path, "w", encoding="utf-8")
            self.record_btn.setText("■ Stop recording")
        else:
            self._stop_recording()

    def _stop_recording(self):
        if self._recording is not None:
            path = self._recording.name
            self._recording.close()
            self._recording = None
            self.record_btn.setChecked(False)
            self.record_btn.setText("● Record session")
            self.status_label.setText(f"Session saved: {path}")

    def _on_clear(self):
        self.collection.captures = []
        self.collection.current = None
        self._last_detected = None
        self.capture_combo.clear()
        self.table.setRowCount(0)
        self.stats_table.setRowCount(0)
        self._refresh_readout()
        self._light_patterns([])
        self.copy_btn.setText("Copy")
        self.copy_btn.setEnabled(True)

    def refresh_theme(self):
        self._refresh_legend()
        self._show_tab("frames" if self.stack.currentIndex() == 0 else "stats")


def _fmt_threshold_value(value):
    if value is None:
        return ""
    return f"{value:g}"
