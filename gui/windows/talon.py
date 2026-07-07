"""Talon tab — first-party Talon integration (see prd-talon.md).

Phase A: Status (discovery, deployed-model match, health lints) and a
read-only Patterns table with per-pattern lint badges. Discovery + model
unpickling run off the UI thread; Refresh re-runs everything.
"""
import os

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox,
    QScrollArea, QFrame, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView
)

from gui import theme
from gui.services import talon_discovery, patterns_schema, library_ops
from config.config import CLASSIFIER_FOLDER


class DiscoveryWorker(QThread):
    """Full discovery bundle off the UI thread (rglob + joblib unpickle)."""
    loaded = pyqtSignal(object)

    def run(self):
        bundle = {"result": None, "schema": None, "model_sounds": None,
                  "local_match": None, "issues": []}
        try:
            result = talon_discovery.discover_talon()
            bundle["result"] = result
            if result.integration_path:
                bundle["schema"] = patterns_schema.schema_from_integration(
                    result.integration_path)
            else:
                bundle["schema"] = patterns_schema.default_schema()
            if result.model_path_from_talon:
                bundle["local_match"] = talon_discovery.find_matching_local_model(
                    result.model_path_from_talon, CLASSIFIER_FOLDER)
                bundle["model_sounds"] = talon_discovery.load_model_sounds(
                    result.model_path_from_talon)
            if result.patterns:
                bundle["issues"] = patterns_schema.validate(
                    result.patterns, bundle["schema"],
                    model_sounds=bundle["model_sounds"])
        except Exception as exc:
            bundle["error"] = str(exc)
        self.loaded.emit(bundle)


def _fmt_threshold(rules):
    if not isinstance(rules, dict):
        return ""
    return "   ".join(f"{op} {value}" for op, value in rules.items())


class TalonPage(QWidget):
    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.worker = None
        self._bundle = None
        self._setup_ui()
        self.refresh()

    # ---- ui -------------------------------------------------------------

    def _setup_ui(self):
        t = theme.colors()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        scroll.setWidget(body)

        head = QHBoxLayout()
        title = QLabel("Talon")
        title.setStyleSheet(
            f"font-size: 20px; font-weight: bold; color: {t['text_bright']};")
        head.addWidget(title)
        head.addStretch()
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.refresh_btn.clicked.connect(self.refresh)
        head.addWidget(self.refresh_btn)
        layout.addLayout(head)

        # ---- status group
        self.status_group = QGroupBox("Status")
        status_layout = QVBoxLayout(self.status_group)
        self.status_rows = {}
        for key, label in (
                ("talon", "Talon"),
                ("integration", "Integration"),
                ("patterns", "patterns.json"),
                ("model", "Deployed model"),
                ("health", "Health")):
            row = QHBoxLayout()
            name = QLabel(f"{label}:")
            name.setFixedWidth(130)
            name.setStyleSheet(f"color: {t['text_dim']};")
            value = QLabel("…")
            value.setWordWrap(True)
            value.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            row.addWidget(name, alignment=Qt.AlignmentFlag.AlignTop)
            row.addWidget(value, 1)
            self.status_rows[key] = value
            status_layout.addLayout(row)

        btn_row = QHBoxLayout()
        self.open_folder_btn = QPushButton("Open Talon folder")
        self.open_folder_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.open_folder_btn.clicked.connect(self._open_talon_folder)
        self.open_folder_btn.setEnabled(False)
        btn_row.addWidget(self.open_folder_btn)
        btn_row.addStretch()
        status_layout.addLayout(btn_row)
        layout.addWidget(self.status_group)

        # ---- patterns group
        self.patterns_group = QGroupBox("Patterns")
        pat_layout = QVBoxLayout(self.patterns_group)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Pattern", "Sounds", "Threshold", "Grace", "Throttles",
             "Detect after", "Issues"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(320)
        pat_layout.addWidget(self.table)

        self.lint_label = QLabel("")
        self.lint_label.setWordWrap(True)
        self.lint_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lint_label.setStyleSheet(f"color: {t['text_dim']}; font-size: 12px;")
        pat_layout.addWidget(self.lint_label)
        layout.addWidget(self.patterns_group)
        layout.addStretch()

    # ---- discovery ------------------------------------------------------

    def refresh(self):
        if self.worker is not None and self.worker.isRunning():
            return
        self.refresh_btn.setEnabled(False)
        self.status_rows["talon"].setText("Searching…")
        self.worker = DiscoveryWorker()
        self.worker.loaded.connect(self._on_loaded)
        self.worker.start()

    def _on_loaded(self, bundle):
        self.refresh_btn.setEnabled(True)
        self._bundle = bundle
        t = theme.colors()
        result = bundle.get("result")
        error = bundle.get("error")

        ok, bad = t["accent"], "#e06c75"
        if error or result is None:
            self.status_rows["talon"].setText(
                f"<span style='color:{bad};'>Discovery failed: {error}</span>")
            return
        if result.talon_found:
            self.status_rows["talon"].setText(
                f"<span style='color:{ok};'>Found</span> — {result.talon_home}")
        else:
            self.status_rows["talon"].setText(
                f"<span style='color:{bad};'>Not found</span> — {result.error or ''}")
        self.status_rows["integration"].setText(result.integration_path or "—")
        self.status_rows["patterns"].setText(result.pattern_path_from_talon or "—")

        model_txt = result.model_path_from_talon or "—"
        match = bundle.get("local_match")
        sounds = bundle.get("model_sounds")
        if result.model_path_from_talon:
            if match:
                model_txt += (f"<br><span style='color:{ok};'>Matches local model "
                              f"'{match}'</span>")
            else:
                model_txt += (f"<br><span style='color:{bad};'>No identical local "
                              f"model — Talon may be running an old copy</span>")
            if sounds:
                model_txt += (f"<br><span style='color:{t['text_dim']};'>"
                              f"{len(sounds)} sounds: {', '.join(sounds)}</span>")
        self.status_rows["model"].setText(model_txt)

        issues = bundle.get("issues") or []
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        if not result.patterns:
            self.status_rows["health"].setText("—")
        elif not issues:
            self.status_rows["health"].setText(
                f"<span style='color:{ok};'>All good</span> — "
                f"{len(result.patterns)} patterns, no issues")
        else:
            parts = []
            if errors:
                parts.append(f"<span style='color:{bad};'>{len(errors)} errors</span>")
            if warnings:
                parts.append(f"<span style='color:#d3a45c;'>{len(warnings)} warnings</span>")
            self.status_rows["health"].setText(
                f"{len(result.patterns)} patterns — " + ", ".join(parts))

        self.open_folder_btn.setEnabled(bool(result.pattern_path_from_talon))
        self._populate_table(result.patterns or {}, issues)

    def _populate_table(self, patterns, issues):
        t = theme.colors()
        by_pattern = {}
        for issue in issues:
            by_pattern.setdefault(issue.pattern, []).append(issue)

        self.table.setRowCount(len(patterns))
        for row, (name, pattern) in enumerate(patterns.items()):
            pattern = pattern if isinstance(pattern, dict) else {}
            sounds = pattern.get("sounds")
            throttle = pattern.get("throttle") or {}
            grace_bits = []
            if pattern.get("graceperiod") is not None:
                grace_bits.append(f"{pattern['graceperiod']}s")
            if pattern.get("grace_threshold"):
                grace_bits.append(_fmt_threshold(pattern["grace_threshold"]))
            cells = [
                name,
                ", ".join(sounds) if isinstance(sounds, list) else "",
                _fmt_threshold(pattern.get("threshold")),
                "  ".join(grace_bits),
                str(len(throttle)) if throttle else "",
                str(pattern.get("detect_after", "")),
            ]
            for col, textval in enumerate(cells):
                item = QTableWidgetItem(textval)
                if col == 4 and throttle:
                    item.setToolTip("\n".join(
                        f"{k}: {v}s" for k, v in throttle.items()))
                self.table.setItem(row, col, item)

            pattern_issues = by_pattern.get(name, [])
            n_err = sum(1 for i in pattern_issues if i.severity == "error")
            n_warn = len(pattern_issues) - n_err
            badge = []
            if n_err:
                badge.append(f"{n_err} ✕")
            if n_warn:
                badge.append(f"{n_warn} ⚠")
            issue_item = QTableWidgetItem("  ".join(badge))
            if pattern_issues:
                issue_item.setToolTip("\n".join(str(i) for i in pattern_issues))
                issue_item.setForeground(
                    Qt.GlobalColor.red if n_err else Qt.GlobalColor.darkYellow)
            self.table.setItem(row, 6, issue_item)

        file_level = by_pattern.get("", [])
        listed = file_level + [i for i in issues if i.severity == "error" and i.pattern]
        self.lint_label.setText("\n".join(str(i) for i in listed[:10]))

    # ---- actions ---------------------------------------------------------

    def _open_talon_folder(self):
        result = self._bundle.get("result") if self._bundle else None
        if result and result.pattern_path_from_talon:
            try:
                library_ops.open_in_file_manager(
                    os.path.dirname(result.pattern_path_from_talon))
            except library_ops.LibraryOpError:
                pass

    def keybinding_hint(self):
        return ""

    def refresh_theme(self):
        pass
