"""Talon tab - first-party Talon integration (see prd-talon.md).

Status (discovery, deployed-model match, health lints) + the patterns
editor: a working copy of the deployed patterns.json is edited through the
guided dialog (or raw JSON), can be stored as named variants, and is only
written back to Talon via Deploy - which snapshots the deployed file first.
Talon hot-reloads patterns.json (``@resource.watch``), so deploys apply live.

Discovery + model unpickling run off the UI thread; Refresh re-runs both.
"""
import json
import os

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox,
    QScrollArea, QFrame, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QComboBox, QMessageBox, QInputDialog, QDialog,
    QPlainTextEdit, QListWidget, QListWidgetItem, QTabWidget
)

from gui import theme
from gui.services import (talon_discovery, patterns_schema, patterns_store,
                          talon_companion, talon_setup, library_ops)
from gui.widgets.pattern_edit_dialog import PatternEditDialog
from gui.widgets import help_dialog
from gui.windows.talon_live import TalonLiveView
from gui.windows.talon_captures import TalonCapturesView
from config.config import CLASSIFIER_FOLDER


def _copy(patterns):
    return json.loads(json.dumps(patterns))


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
        self._deployed = {}     # what's on disk at the Talon path right now
        self.working = {}       # the copy being edited
        self._setup_ui()
        self.refresh()

    @property
    def dirty(self):
        return self.working != self._deployed

    @property
    def _patterns_path(self):
        result = self._bundle.get("result") if self._bundle else None
        return result.pattern_path_from_talon if result else None

    # ---- ui -------------------------------------------------------------

    def _setup_ui(self):
        t = theme.colors()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.tabs.addTab(scroll, "Setup && Patterns")

        self.live_view = TalonLiveView()
        live_wrap = QWidget()
        live_layout = QVBoxLayout(live_wrap)
        live_layout.setContentsMargins(16, 8, 16, 8)
        live_layout.addWidget(self.live_view)
        self.tabs.addTab(live_wrap, "Live")

        self.captures_view = TalonCapturesView(
            get_deployed=lambda: self._deployed,
            get_working=lambda: self.working)
        captures_wrap = QWidget()
        captures_layout = QVBoxLayout(captures_wrap)
        captures_layout.setContentsMargins(16, 8, 16, 8)
        captures_layout.addWidget(self.captures_view)
        self.tabs.addTab(captures_wrap, "Captures")
        self.tabs.currentChanged.connect(self._on_tab_changed)

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
        head.addWidget(help_dialog.help_button(self, "connect"))
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
                ("companion", "Companion"),
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
        self.companion_btn = QPushButton("Install companion")
        self.companion_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.companion_btn.setToolTip(
            "Copies parrot_gui_bridge.py into your Talon user directory so "
            "the Live tab can show real Talon detection frames")
        self.companion_btn.clicked.connect(self._on_install_companion)
        self.companion_btn.setEnabled(False)
        btn_row.addWidget(self.companion_btn)
        self.setup_btn = QPushButton("Set up parrot integration…")
        self.setup_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setup_btn.setToolTip(
            "Creates <talon user>/parrot/ with parrot_integration.py, one of "
            "your trained models, and a starter patterns.json")
        self.setup_btn.clicked.connect(self._on_setup_integration)
        self.setup_btn.setVisible(False)
        btn_row.addWidget(self.setup_btn)
        self.create_patterns_btn = QPushButton("Create patterns.json")
        self.create_patterns_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.create_patterns_btn.clicked.connect(self._on_create_patterns)
        self.create_patterns_btn.setVisible(False)
        btn_row.addWidget(self.create_patterns_btn)
        btn_row.addStretch()
        status_layout.addLayout(btn_row)
        layout.addWidget(self.status_group)

        # ---- patterns group
        self.patterns_group = QGroupBox("Patterns")
        pat_layout = QVBoxLayout(self.patterns_group)

        tools = QHBoxLayout()
        self.variant_combo = QComboBox()
        self.variant_combo.setMinimumWidth(160)
        self.variant_combo.setToolTip(
            "Named variants are stored in data/talon/variants - load one to "
            "edit it, then Deploy to make it live")
        tools.addWidget(self.variant_combo)
        self.load_variant_btn = self._tool_btn(tools, "Load", self._on_load_variant)
        tools.addSpacing(16)
        self.new_btn = self._tool_btn(tools, "New…", self._on_new)
        self.edit_btn = self._tool_btn(tools, "Edit…", self._on_edit)
        self.dup_btn = self._tool_btn(tools, "Duplicate", self._on_duplicate)
        self.del_btn = self._tool_btn(tools, "Delete", self._on_delete)
        self.raw_btn = self._tool_btn(tools, "Raw JSON…", self._on_raw_json)
        tools.addStretch()
        self.save_variant_btn = self._tool_btn(
            tools, "Save as variant…", self._on_save_variant)
        self.snapshots_btn = self._tool_btn(tools, "Snapshots…", self._on_snapshots)
        self.deploy_btn = self._tool_btn(tools, "Deploy to Talon", self._on_deploy)
        pat_layout.addLayout(tools)

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
        self.table.doubleClicked.connect(lambda _ix: self._on_edit())
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
                f"<span style='color:{ok};'>Found</span> - {result.talon_home}")
        else:
            self.status_rows["talon"].setText(
                f"<span style='color:{bad};'>Not found</span> - {result.error or ''}")
        self.status_rows["integration"].setText(result.integration_path or "-")
        self.status_rows["patterns"].setText(result.pattern_path_from_talon or "-")

        model_txt = result.model_path_from_talon or "-"
        match = bundle.get("local_match")
        sounds = bundle.get("model_sounds")
        if result.model_path_from_talon:
            if match:
                model_txt += (f"<br><span style='color:{ok};'>Matches local model "
                              f"'{match}'</span>")
            else:
                model_txt += (f"<br><span style='color:{bad};'>No identical local "
                              f"model - Talon may be running an old copy</span>")
            if sounds:
                model_txt += (f"<br><span style='color:{t['text_dim']};'>"
                              f"{len(sounds)} sounds: {', '.join(sounds)}</span>")
        self.status_rows["model"].setText(model_txt)

        self.open_folder_btn.setEnabled(bool(result.pattern_path_from_talon))
        self._refresh_companion_row()

        # Bootstrap buttons for whatever is missing
        user_dir = result.talon_user_dir
        self.setup_btn.setVisible(bool(user_dir) and not result.integration_path)
        patterns_missing = (result.integration_path
                            and result.intended_pattern_path
                            and not os.path.isfile(result.intended_pattern_path))
        self.create_patterns_btn.setVisible(bool(patterns_missing))
        if not result.integration_path and user_dir:
            self.status_rows["integration"].setText(
                f"<span style='color:{bad};'>Not found</span> - use "
                "'Set up parrot integration' to create one")
        elif patterns_missing:
            self.status_rows["patterns"].setText(
                f"<span style='color:{bad};'>Missing</span> - the integration "
                f"expects {result.intended_pattern_path}")
        self._deployed = _copy(result.patterns or {})
        self.working = _copy(result.patterns or {})
        self.live_view.set_patterns(self._deployed)
        self._refresh_variants()
        self._refresh_from_working()

    # ---- companion / live tab ---------------------------------------------

    def _talon_user_dir(self):
        result = self._bundle.get("result") if self._bundle else None
        return result.talon_user_dir if result else None

    def _refresh_companion_row(self):
        t = theme.colors()
        user_dir = self._talon_user_dir()
        if not user_dir:
            self.status_rows["companion"].setText("-")
            self.companion_btn.setEnabled(False)
            return
        info = talon_companion.status(user_dir)
        self.companion_btn.setEnabled(True)
        if not info["installed"]:
            self.status_rows["companion"].setText(
                "Not installed - needed for the Live tab")
            self.companion_btn.setText("Install companion")
        elif info["outdated"]:
            self.status_rows["companion"].setText(
                f"<span style='color:#d3a45c;'>v{info['installed_version']} installed, "
                f"v{info['available_version']} available</span> - {info['path']}")
            self.companion_btn.setText("Update companion")
        else:
            self.status_rows["companion"].setText(
                f"<span style='color:{t['accent']};'>Installed</span> "
                f"(v{info['installed_version']}) - {info['path']}")
            self.companion_btn.setText("Reinstall companion")

    def _on_install_companion(self):
        user_dir = self._talon_user_dir()
        if not user_dir:
            return
        dest = talon_companion.installed_path(user_dir)
        if QMessageBox.question(
                self, "Install companion",
                f"Copy parrot_gui_bridge.py to\n{dest}?\n\n"
                "Talon loads it immediately. It only observes detections and "
                "publishes them to this app on localhost - remove it any time "
                "by deleting the file.") != QMessageBox.StandardButton.Yes:
            return
        try:
            talon_companion.install(user_dir)
        except OSError as exc:
            QMessageBox.warning(self, "Install failed", str(exc))
            return
        self._refresh_companion_row()

    def _on_setup_integration(self):
        user_dir = self._talon_user_dir()
        if not user_dir:
            return
        models = self.app_state.get_model_names()
        if not models:
            QMessageBox.information(
                self, "No models yet",
                "Train a model first (Models tab) - the integration needs one.")
            return
        name, okd = QInputDialog.getItem(
            self, "Set up parrot integration",
            "Model to deploy with the integration:", models, 0, False)
        if not okd:
            return
        model_pkl = os.path.join(CLASSIFIER_FOLDER, f"{name}.pkl")
        scaffold = QMessageBox.question(
            self, "Starter patterns",
            "Create one starter pattern per model sound (strict thresholds, "
            "tune them in the editor)?\n\nChoosing No starts with an empty "
            "patterns.json.") == QMessageBox.StandardButton.Yes
        patterns = {}
        if scaffold:
            sounds = talon_discovery.load_model_sounds(model_pkl) or []
            patterns = talon_setup.scaffold_patterns(sounds)
        dest = os.path.join(user_dir, talon_setup.DEFAULT_SUBFOLDER)
        if QMessageBox.question(
                self, "Set up parrot integration",
                f"Create {dest} with parrot_integration.py, {name}.pkl and "
                f"patterns.json ({len(patterns)} patterns)?\n\n"
                "Talon loads the integration immediately.") != \
                QMessageBox.StandardButton.Yes:
            return
        try:
            talon_setup.install_integration(user_dir, model_pkl, patterns=patterns)
        except (OSError, patterns_store.PatternsError) as exc:
            QMessageBox.warning(self, "Setup failed", str(exc))
            return
        self.refresh()

    def _on_create_patterns(self):
        result = self._bundle.get("result") if self._bundle else None
        if not result or not result.intended_pattern_path:
            return
        sounds = self._bundle.get("model_sounds") or []
        scaffold = bool(sounds) and QMessageBox.question(
            self, "Starter patterns",
            "Create one starter pattern per model sound (strict thresholds)?"
            "\n\nChoosing No starts empty.") == QMessageBox.StandardButton.Yes
        patterns = talon_setup.scaffold_patterns(sounds) if scaffold else {}
        try:
            talon_setup.create_patterns_file(result.intended_pattern_path, patterns)
        except (OSError, patterns_store.PatternsError) as exc:
            QMessageBox.warning(self, "Couldn't create patterns.json", str(exc))
            return
        self.refresh()

    def _on_tab_changed(self, index):
        if self.tabs.widget(index) is not None and index == 1:
            self.live_view.start()
        else:
            self.live_view.stop()
        if index == 2:
            self.captures_view.refresh_sessions()

    def hideEvent(self, event):
        self.live_view.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        if self.tabs.currentIndex() == 1:
            self.live_view.start()
        super().showEvent(event)

    # ---- working-copy lifecycle ------------------------------------------

    def _validate_working(self):
        if not self._bundle:
            return []
        return patterns_schema.validate(
            self.working, self._bundle.get("schema"),
            model_sounds=self._bundle.get("model_sounds"))

    def _refresh_from_working(self):
        t = theme.colors()
        ok, bad = t["accent"], "#e06c75"
        issues = self._validate_working()
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]

        if not self.working:
            self.status_rows["health"].setText("-")
        elif not issues:
            self.status_rows["health"].setText(
                f"<span style='color:{ok};'>All good</span> - "
                f"{len(self.working)} patterns, no issues")
        else:
            parts = []
            if errors:
                parts.append(f"<span style='color:{bad};'>{len(errors)} errors</span>")
            if warnings:
                parts.append(f"<span style='color:#d3a45c;'>{len(warnings)} warnings</span>")
            self.status_rows["health"].setText(
                f"{len(self.working)} patterns - " + ", ".join(parts))

        self.patterns_group.setTitle(
            "Patterns - unsaved changes (Deploy to make live)" if self.dirty
            else "Patterns")
        editable = self._patterns_path is not None
        for btn in (self.new_btn, self.edit_btn, self.dup_btn, self.del_btn,
                    self.raw_btn, self.save_variant_btn, self.snapshots_btn):
            btn.setEnabled(editable)
        self.deploy_btn.setEnabled(editable and self.dirty
                                   and not patterns_schema.has_errors(issues))
        self._populate_table(self.working, issues)

    def _refresh_variants(self):
        current = self.variant_combo.currentText()
        self.variant_combo.clear()
        names = patterns_store.list_variants()
        self.variant_combo.addItems(names)
        idx = self.variant_combo.findText(current)
        if idx >= 0:
            self.variant_combo.setCurrentIndex(idx)
        has = bool(names)
        self.variant_combo.setVisible(True)
        self.load_variant_btn.setEnabled(has)

    def _selected_name(self):
        row = self.table.currentRow()
        if row < 0 or self.table.item(row, 0) is None:
            return None
        return self.table.item(row, 0).text()

    def _tool_btn(self, layout, label, slot):
        btn = QPushButton(label)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.clicked.connect(slot)
        layout.addWidget(btn)
        return btn

    # ---- pattern editing --------------------------------------------------

    def _edit_dialog(self, name, pattern):
        observed = self._session_stats().get(name) if name else None
        return PatternEditDialog(
            self, name, pattern, self.working,
            self._bundle.get("model_sounds") if self._bundle else [],
            self._bundle.get("schema") if self._bundle else None,
            observed=observed)

    def _session_stats(self):
        """Observed per-pattern stats from the newest recorded session,
        cached by (path, mtime). Empty dict when there are no sessions."""
        from gui.services import session_stats
        captures_dir = os.path.join("data", "talon", "captures")
        newest = None
        if os.path.isdir(captures_dir):
            sessions = [os.path.join(captures_dir, n)
                        for n in os.listdir(captures_dir) if n.endswith(".jsonl")]
            if sessions:
                newest = max(sessions, key=os.path.getmtime)
        if newest is None:
            self._stats_cache = None
            return {}
        key = (newest, os.path.getmtime(newest))
        cached = getattr(self, "_stats_cache", None)
        if cached and cached[0] == key:
            return cached[1]
        frames = []
        try:
            with open(newest, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            frames.append(json.loads(line))
                        except ValueError:
                            continue
        except OSError:
            return {}
        stats = session_stats.analyze(frames, self._deployed)
        self._stats_cache = (key, stats)
        return stats

    def _on_new(self):
        dialog = self._edit_dialog(None, None)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.working[dialog.result_name] = dialog.result_pattern
            self._refresh_from_working()

    def _on_edit(self):
        name = self._selected_name()
        if not name or name not in self.working:
            return
        dialog = self._edit_dialog(name, self.working[name])
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        new_name = dialog.result_name
        if new_name != name:
            # keep position + update every throttle that pointed at the old name
            self.working = {
                (new_name if key == name else key): value
                for key, value in self.working.items()}
            for pattern in self.working.values():
                throttle = pattern.get("throttle")
                if isinstance(throttle, dict) and name in throttle:
                    throttle[new_name] = throttle.pop(name)
        self.working[new_name] = dialog.result_pattern
        self._refresh_from_working()

    def _on_duplicate(self):
        name = self._selected_name()
        if not name or name not in self.working:
            return
        copy_name = f"{name} copy"
        counter = 2
        while copy_name in self.working:
            copy_name = f"{name} copy {counter}"
            counter += 1
        self.working[copy_name] = _copy(self.working[name])
        self._refresh_from_working()

    def _on_delete(self):
        name = self._selected_name()
        if not name or name not in self.working:
            return
        referrers = [p for p, pat in self.working.items()
                     if isinstance(pat.get("throttle"), dict) and name in pat["throttle"]]
        message = f"Delete pattern '{name}' from the working copy?"
        if referrers:
            message += ("\n\nThrottle references in "
                        f"{', '.join(referrers)} will also be removed.")
        if QMessageBox.question(self, "Delete pattern", message) != \
                QMessageBox.StandardButton.Yes:
            return
        del self.working[name]
        for pattern in self.working.values():
            throttle = pattern.get("throttle")
            if isinstance(throttle, dict):
                throttle.pop(name, None)
        self._refresh_from_working()

    def _on_raw_json(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("patterns.json - raw")
        dialog.setMinimumSize(640, 560)
        layout = QVBoxLayout(dialog)
        editor = QPlainTextEdit()
        editor.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        editor.setPlainText(patterns_store.dumps_patterns(self.working))
        layout.addWidget(editor, 1)
        note = QLabel("")
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(dialog.reject)
        row.addWidget(cancel)
        apply_btn = QPushButton("Apply")
        row.addWidget(apply_btn)
        layout.addLayout(row)

        def on_apply():
            try:
                data = json.loads(editor.toPlainText())
            except json.JSONDecodeError as exc:
                note.setText(f"Not valid JSON: {exc}")
                return
            if not isinstance(data, dict):
                note.setText("patterns.json must be a JSON object")
                return
            issues = patterns_schema.validate(
                data, self._bundle.get("schema") if self._bundle else None,
                model_sounds=self._bundle.get("model_sounds") if self._bundle else None)
            if patterns_schema.has_errors(issues):
                errors = [str(i) for i in issues if i.severity == "error"]
                note.setText("\n".join(errors[:6]))
                return
            self.working = data
            dialog.accept()

        apply_btn.clicked.connect(on_apply)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._refresh_from_working()

    # ---- variants / deploy / snapshots -------------------------------------

    def _on_save_variant(self):
        name, okd = QInputDialog.getText(
            self, "Save as variant",
            "Variant name (stored in data/talon/variants):",
            text=self.variant_combo.currentText() or "experiment")
        if not okd or not name.strip():
            return
        try:
            patterns_store.save_variant(name.strip(), self.working)
        except patterns_store.PatternsError as exc:
            QMessageBox.warning(self, "Couldn't save variant", str(exc))
            return
        self._refresh_variants()
        idx = self.variant_combo.findText(name.strip())
        if idx >= 0:
            self.variant_combo.setCurrentIndex(idx)

    def _on_load_variant(self):
        name = self.variant_combo.currentText()
        if not name:
            return
        if self.dirty and QMessageBox.question(
                self, "Discard changes?",
                "The working copy has unsaved changes. Load the variant anyway?") \
                != QMessageBox.StandardButton.Yes:
            return
        try:
            self.working = patterns_store.load_variant(name)
        except patterns_store.PatternsError as exc:
            QMessageBox.warning(self, "Couldn't load variant", str(exc))
            return
        self._refresh_from_working()

    def _on_deploy(self):
        path = self._patterns_path
        if not path:
            return
        diff = patterns_store.diff_patterns(self._deployed, self.working)
        lines = []
        for n in diff["added"]:
            lines.append(f"+ {n}")
        for n in diff["removed"]:
            lines.append(f"− {n}")
        for n, fields in diff["changed"].items():
            lines.append(f"~ {n}: {', '.join(f[0] for f in fields)}")
        summary = "\n".join(lines) or "(no changes)"
        if QMessageBox.question(
                self, "Deploy to Talon",
                f"Write these changes to\n{path}?\n\n{summary}\n\n"
                "The current file is snapshotted first, and Talon reloads "
                "patterns.json automatically.") != QMessageBox.StandardButton.Yes:
            return
        try:
            snap = patterns_store.deploy(self.working, path)
        except patterns_store.PatternsError as exc:
            QMessageBox.warning(self, "Deploy failed", str(exc))
            return
        self._deployed = _copy(self.working)
        self.live_view.set_patterns(self._deployed)
        self._refresh_from_working()
        QMessageBox.information(
            self, "Deployed",
            f"patterns.json updated - Talon picks it up automatically.\n"
            f"Previous version snapshotted to:\n{snap}")

    def _on_snapshots(self):
        snaps = patterns_store.list_snapshots()
        if not snaps:
            QMessageBox.information(self, "Snapshots",
                                    "No snapshots yet - one is taken on every deploy.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Snapshots")
        dialog.setMinimumSize(520, 420)
        layout = QVBoxLayout(dialog)
        listing = QListWidget()
        for path, _mtime in snaps:
            QListWidgetItem(os.path.basename(path), listing)
        layout.addWidget(listing, 1)
        row = QHBoxLayout()
        row.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(dialog.reject)
        row.addWidget(close)
        restore = QPushButton("Load into working copy")
        row.addWidget(restore)
        layout.addLayout(row)

        def on_restore():
            idx = listing.currentRow()
            if idx < 0:
                return
            try:
                self.working = patterns_store.load_patterns(snaps[idx][0])
            except patterns_store.PatternsError as exc:
                QMessageBox.warning(dialog, "Couldn't load snapshot", str(exc))
                return
            dialog.accept()

        restore.clicked.connect(on_restore)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._refresh_from_working()

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
