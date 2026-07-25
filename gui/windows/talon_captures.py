"""Captures workbench - evaluate recorded sessions against pattern variants.

Record a session of real usage in the Live tab once, then compare what the
deployed patterns.json did against what an edited working copy / variant
WOULD have done, frame for frame, using the ported integration state machine
(patterns_replay - verified frame-identical against the real integration).
"""
import json
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QSplitter
)

from gui import theme
from gui.services import patterns_replay, patterns_store, session_stats

CAPTURES_DIR = os.path.join("data", "talon", "captures")


class TalonCapturesView(QWidget):
    """``get_deployed`` / ``get_working`` are callables provided by the Talon
    page so the workbench always sees the latest editor state."""

    def __init__(self, get_deployed, get_working, parent=None):
        super().__init__(parent)
        self._get_deployed = get_deployed
        self._get_working = get_working
        self._setup_ui()
        self.refresh_sessions()

    def _setup_ui(self):
        t = theme.colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)

        top = QHBoxLayout()
        top.addWidget(QLabel("Session:"))
        self.session_combo = QComboBox()
        self.session_combo.setMinimumWidth(240)
        top.addWidget(self.session_combo)
        refresh = QPushButton("Refresh")
        refresh.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        refresh.clicked.connect(self.refresh_sessions)
        top.addWidget(refresh)
        top.addSpacing(24)
        top.addWidget(QLabel("Deployed  vs"))
        self.candidate_combo = QComboBox()
        self.candidate_combo.setMinimumWidth(180)
        top.addWidget(self.candidate_combo)
        self.eval_btn = QPushButton("Evaluate")
        self.eval_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.eval_btn.clicked.connect(self._on_evaluate)
        top.addWidget(self.eval_btn)
        top.addStretch()
        layout.addLayout(top)

        self.note = QLabel(
            "Record a session in the Live tab first, edit patterns in "
            "Setup && Patterns, then Evaluate to see what would change.")
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color: {t['text_dim']};")
        layout.addWidget(self.note)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, 1)

        self.summary = QTableWidget(0, 7)
        self.summary.setHorizontalHeaderLabels(
            ["Pattern", "Deployed fires", "Candidate fires", "Δ",
             "Power when fired", "Prob. when fired", "Near misses"])
        self.summary.horizontalHeaderItem(4).setToolTip(
            "Observed p10-p90 (median) across the recorded session")
        self.summary.horizontalHeaderItem(6).setToolTip(
            "Frames where probability was ≥ 0.5 but the pattern did not fire, "
            "with the rule that blocked it")
        self._style_table(self.summary)
        splitter.addWidget(self.summary)

        self.changes = QTableWidget(0, 3)
        self.changes.setHorizontalHeaderLabels(
            ["Time (s into session)", "Dropped (deployed only)",
             "Added (candidate only)"])
        self._style_table(self.changes)
        splitter.addWidget(self.changes)
        splitter.setStretchFactor(1, 1)

    def _style_table(self, table):
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)

    # ---- data -----------------------------------------------------------

    def refresh_sessions(self):
        current = self.session_combo.currentData()
        self.session_combo.clear()
        if os.path.isdir(CAPTURES_DIR):
            for name in sorted(os.listdir(CAPTURES_DIR), reverse=True):
                if name.endswith(".jsonl"):
                    self.session_combo.addItem(
                        name, os.path.join(CAPTURES_DIR, name))
        if current:
            idx = self.session_combo.findData(current)
            if idx >= 0:
                self.session_combo.setCurrentIndex(idx)

        self.candidate_combo.clear()
        self.candidate_combo.addItem("Working copy", "__working__")
        for name in patterns_store.list_variants():
            self.candidate_combo.addItem(f"Variant: {name}", name)

        has_session = self.session_combo.count() > 0
        self.eval_btn.setEnabled(has_session)

    def _load_session(self, path):
        frames = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        frames.append(json.loads(line))
                    except ValueError:
                        continue
        return frames

    # ---- evaluate ---------------------------------------------------------

    def _on_evaluate(self):
        t = theme.colors()
        path = self.session_combo.currentData()
        if not path or not os.path.isfile(path):
            return
        frames = self._load_session(path)
        if not frames:
            self.note.setText("That session file is empty.")
            return

        deployed = self._get_deployed() or {}
        key = self.candidate_combo.currentData()
        if key == "__working__":
            candidate = self._get_working() or {}
            candidate_label = "working copy"
        else:
            try:
                candidate = patterns_store.load_variant(key)
            except patterns_store.PatternsError as exc:
                self.note.setText(str(exc))
                return
            candidate_label = f"variant '{key}'"

        result_a, result_b, changes = patterns_replay.compare(
            frames, deployed, candidate, deployed_patterns=deployed)

        observed = session_stats.analyze(frames, deployed)
        names = sorted(set(result_a.fires) | set(result_b.fires))
        self.summary.setRowCount(len(names))
        for row, name in enumerate(names):
            fires_a = result_a.fires.get(name, 0)
            fires_b = result_b.fires.get(name, 0)
            delta = fires_b - fires_a
            entry = observed.get(name) or {}
            power = entry.get("fired_power")
            prob = entry.get("fired_prob")
            near = entry.get("near_misses", 0)
            blockers = entry.get("blockers") or {}
            cells = [
                name, str(fires_a), str(fires_b),
                f"{delta:+d}" if delta else "",
                f"{power[0]:.0f}-{power[2]:.0f}  ({power[1]:.0f})" if power else "",
                f"{prob[0]:.2f}-{prob[2]:.2f}" if prob else "",
                str(near) if near else "",
            ]
            for col, value in enumerate(cells):
                item = QTableWidgetItem(value)
                if col == 3 and delta:
                    item.setForeground(QColor(
                        "#41d97f" if delta > 0 else "#e06c75"))
                if col == 6 and near:
                    item.setToolTip("Blocked by: " + ", ".join(
                        f"{rule} ×{count}" for rule, count in blockers.items()))
                self.summary.setItem(row, col, item)

        t0 = frames[0].get("ts", 0.0)
        self.changes.setRowCount(len(changes))
        for row, change in enumerate(changes):
            self.changes.setItem(row, 0, QTableWidgetItem(
                f"{change['ts'] - t0:9.3f}"))
            dropped = QTableWidgetItem(", ".join(change["only_a"]))
            dropped.setForeground(QColor("#e06c75"))
            self.changes.setItem(row, 1, dropped)
            added = QTableWidgetItem(", ".join(change["only_b"]))
            added.setForeground(QColor("#41d97f"))
            self.changes.setItem(row, 2, added)

        total_a = sum(result_a.fires.values())
        total_b = sum(result_b.fires.values())
        parts = [f"{len(frames)} frames replayed - deployed fired {total_a}×, "
                 f"{candidate_label} would fire {total_b}× "
                 f"({len(changes)} frames differ)."]
        if result_b.power_floor_warning:
            parts.append(
                "⚠ The candidate lowers a >power threshold below the deployed "
                "one - frames quieter than the deployed floor were never "
                "recorded, so additions may be under-reported.")
        if result_b.skipped_patterns:
            parts.append(
                f"Skipped (unknown sounds): {', '.join(result_b.skipped_patterns)}")
        self.note.setText("  ".join(parts))
