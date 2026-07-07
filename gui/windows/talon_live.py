"""Live view — Talon-truth frames, ported from talon-parrot-tester's frames
table (its most valuable view). Captures listed on the left, one row per
frame on the right with per-pattern probability, status, and a power bar.

Data arrives from the companion via BridgeWorker; capture grouping is the
shared capture_model. Record writes raw frame JSONL sessions into
data/talon/captures/ for the A/B workbench.
"""
import json
import os
import time

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QSplitter, QCheckBox
)

from gui import theme
from gui.services import capture_model
from gui.workers.bridge_worker import BridgeWorker
from gui.services.talon_companion import BRIDGE_PORT

CAPTURES_DIR = os.path.join("data", "talon", "captures")

_STATUS_COLOR = {"detected": "#41d97f", "grace_detected": "#5ab0f5",
                 "throttled": "#d3a45c", "": "#8a8f98"}


def _bar(fraction, width=10):
    filled = max(0, min(width, round(fraction * width)))
    return "▮" * filled + "▯" * (width - filled)


class TalonLiveView(QWidget):
    """Owns the bridge worker while visible; the Talon page starts/stops it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self.collection = capture_model.CaptureCollection({})
        self._recording = None    # open file handle while recording
        self._selected_capture = None
        self._power_scale = 40.0  # display scale for the power bar
        self._setup_ui()

    # ---- lifecycle -------------------------------------------------------

    def set_patterns(self, patterns_json):
        self.collection.set_patterns(patterns_json)

    def start(self):
        if self.worker is not None and self.worker.isRunning():
            return
        self.worker = BridgeWorker(BRIDGE_PORT)
        self.worker.status_changed.connect(self._on_status)
        self.worker.frames_received.connect(self._on_frames)
        self.worker.start()

    def stop(self):
        if self.worker is not None:
            self.worker.stop()
            self.worker.wait(1000)
            self.worker = None
        self._stop_recording()

    # ---- ui ----------------------------------------------------------------

    def _setup_ui(self):
        t = theme.colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)

        top = QHBoxLayout()
        self.status_label = QLabel("Waiting for the Talon companion…")
        self.status_label.setStyleSheet(f"color: {t['text_dim']};")
        top.addWidget(self.status_label, 1)
        self.formants_check = QCheckBox("Formants")
        self.formants_check.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.formants_check.stateChanged.connect(lambda _s: self._render_frames())
        top.addWidget(self.formants_check)
        self.record_btn = QPushButton("● Record session")
        self.record_btn.setCheckable(True)
        self.record_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.record_btn.setToolTip(
            "Save raw frames to data/talon/captures for offline A/B analysis")
        self.record_btn.toggled.connect(self._on_record_toggled)
        top.addWidget(self.record_btn)
        clear_btn = QPushButton("Clear")
        clear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        clear_btn.clicked.connect(self._on_clear)
        top.addWidget(clear_btn)
        layout.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, 1)

        self.capture_list = QListWidget()
        self.capture_list.setMinimumWidth(220)
        self.capture_list.currentRowChanged.connect(self._on_capture_selected)
        splitter.addWidget(self.capture_list)

        self.table = QTableWidget(0, 9)
        self._base_headers = ["Frame", "Δts", "Pattern", "Prob.", "Power",
                              "F0", "F1", "F2", "Status"]
        self.table.setHorizontalHeaderLabels(self._base_headers)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        splitter.addWidget(self.table)
        splitter.setStretchFactor(1, 1)

    # ---- bridge events ------------------------------------------------------

    def _on_status(self, status):
        t = theme.colors()
        if status.get("error"):
            self.status_label.setText(
                f"<span style='color:#e06c75;'>{status['error']}</span>")
        elif status.get("connected"):
            hello = status.get("hello") or {}
            wrapped = hello.get("wrapped")
            detail = (f"companion v{hello.get('version', '?')}, "
                      f"{hello.get('patterns', '?')} patterns")
            if wrapped:
                self.status_label.setText(
                    f"<span style='color:{t['accent']};'>Connected</span> — {detail}")
            else:
                self.status_label.setText(
                    f"<span style='color:#d3a45c;'>Connected, waiting for the "
                    f"parrot integration to load</span> — {detail}")
        else:
            self.status_label.setText(
                "Waiting for the Talon companion… (Talon running + companion "
                f"installed → frames appear here, port {BRIDGE_PORT})")

    def _on_frames(self, raw_frames):
        completed = False
        for raw in raw_frames:
            if self._recording is not None:
                self._recording.write(json.dumps(raw) + "\n")
            if self.collection.add_raw(raw) is not None:
                completed = True
        # While a capture is open, keep the view following it live.
        if completed or self.collection.current is not None:
            self._refresh_capture_list()

    # ---- captures + frames table --------------------------------------------

    def _refresh_capture_list(self):
        follow_latest = (self.capture_list.currentRow() <= 0)
        self.capture_list.blockSignals(True)
        self.capture_list.clear()
        for capture in reversed(self.collection.captures):
            names = ", ".join(capture.pattern_names) or "?"
            live = "  ●" if capture is self.collection.current else ""
            QListWidgetItem(f"{names}{live}   ({len(capture.frames)}f)",
                            self.capture_list)
        self.capture_list.blockSignals(False)
        if self.collection.captures and follow_latest:
            self.capture_list.setCurrentRow(0)
        else:
            self._render_frames()

    def _on_capture_selected(self, _row):
        self._render_frames()

    def _current_capture(self):
        row = self.capture_list.currentRow()
        if row < 0 or not self.collection.captures:
            return None
        index = len(self.collection.captures) - 1 - row
        if 0 <= index < len(self.collection.captures):
            return self.collection.captures[index]
        return None

    def _render_frames(self):
        capture = self._current_capture()
        show_formants = self.formants_check.isChecked()
        for col in (5, 6, 7):
            self.table.setColumnHidden(col, not show_formants)
        if capture is None:
            self.table.setRowCount(0)
            return

        frames = capture.frames
        first_detect_ts = capture.detect_frames[0].ts if capture.detect_frames else \
            (frames[0].ts if frames else 0)
        self.table.setRowCount(len(frames))
        for row, frame in enumerate(frames):
            winner = frame.winner
            delta = (frame.ts_delta if frame.ts_delta is not None
                     else frame.ts - first_detect_ts)
            power_fraction = min(1.0, frame.power / self._power_scale)
            names = "\n".join(p["name"] for p in frame.patterns)
            probs = "\n".join(f"{p['probability']:.4f}" for p in frame.patterns)
            status_text = "\n".join(
                (p["status"] or ("grace" if p["graceperiod"] else ""))
                for p in frame.patterns)
            cells = [
                str(frame.id if frame.id is not None else row + 1),
                f"{delta:+.3f}",
                names,
                probs,
                f"{frame.power:7.2f}  {_bar(power_fraction)}",
                f"{frame.f0:.0f}",
                f"{frame.f1:.0f}",
                f"{frame.f2:.0f}",
                status_text,
            ]
            for col, value in enumerate(cells):
                item = QTableWidgetItem(value)
                if col == 8 and winner is not None:
                    item.setForeground(QColor(
                        _STATUS_COLOR.get(winner["status"], "#8a8f98")))
                if col == 0 and frame.detected:
                    item.setForeground(QColor("#41d97f"))
                self.table.setItem(row, col, item)

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
        self.capture_list.clear()
        self.table.setRowCount(0)
