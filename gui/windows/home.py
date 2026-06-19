import os
import subprocess
import sys
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QTextEdit, QGridLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread
from PyQt6.QtGui import QFont, QColor, QCursor
from gui.widgets.duration_bar import DurationBarWidget


class MetadataWorker(QThread):
    """Background thread to load heavy model metadata (joblib + torch)."""
    finished = pyqtSignal(list)  # list of metadata dicts

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state

    def run(self):
        results = []
        for name in self.app_state.get_model_names():
            results.append(self.app_state.get_model_metadata(name, load_weights=True))
        self.finished.emit(results)


class ActionCard(QFrame):
    """A clickable card with title, description, and optional subtitle."""
    clicked = pyqtSignal()

    def __init__(self, title, description, parent=None):
        super().__init__(parent)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet("""
            ActionCard {
                border: 1px solid #3a3a3a;
                border-radius: 8px;
                padding: 16px;
                background-color: #252525;
            }
            ActionCard:hover {
                border-color: #4285f4;
                background-color: #2a2a2a;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #eee; border: none; background: transparent;")
        text_layout.addWidget(title_label)
        desc_label = QLabel(description)
        desc_label.setStyleSheet("font-size: 12px; color: #888; border: none; background: transparent;")
        desc_label.setWordWrap(True)
        text_layout.addWidget(desc_label)
        layout.addLayout(text_layout, stretch=1)

        arrow = QLabel("\u203a")
        arrow.setStyleSheet("font-size: 22px; color: #555; border: none; background: transparent;")
        layout.addWidget(arrow)

    def mousePressEvent(self, event):
        self.clicked.emit()


class HomePage(QWidget):
    navigate_to_page = pyqtSignal(str)

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self._notes_save_timer = None
        self._current_active_model = None
        self._details_visible = False
        self._setup_ui()
        self._refresh()

        self.app_state.models_changed.connect(self._refresh)
        self.app_state.recordings_changed.connect(self._refresh_status)
        self.app_state.talon_status_changed.connect(self._refresh_status)

    def _setup_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer_layout.addWidget(scroll)

        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(40, 24, 40, 24)
        self.content_layout.setSpacing(16)
        scroll.setWidget(content)

        # -- Welcome (first-run) --
        self.welcome_widget = self._build_welcome()
        self.content_layout.addWidget(self.welcome_widget)

        # -- Returning user --
        self.main_widget = QWidget()
        main_layout = QVBoxLayout(self.main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(16)

        # Status summary (one line)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 14px; color: #ccc;")
        self.status_label.setWordWrap(True)
        main_layout.addWidget(self.status_label)

        # "What would you like to do?"
        prompt_label = QLabel("What would you like to do?")
        prompt_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #eee; margin-top: 8px;")
        main_layout.addWidget(prompt_label)

        # Action cards
        self.record_card = ActionCard(
            "Record Sounds",
            "Add or improve your sound recordings"
        )
        self.record_card.clicked.connect(lambda: self.navigate_to_page.emit("recording"))
        main_layout.addWidget(self.record_card)

        self.train_card = ActionCard(
            "Train Model",
            "Train a new model from your recordings"
        )
        self.train_card.clicked.connect(lambda: self.navigate_to_page.emit("training"))
        main_layout.addWidget(self.train_card)

        self.details_card = ActionCard(
            "Model Details",
            "View sounds, accuracy, recordings, and Talon status"
        )
        self.details_card.clicked.connect(self._toggle_details)
        main_layout.addWidget(self.details_card)

        # -- Expandable details section (hidden by default) --
        self.details_widget = QWidget()
        self.details_widget.setVisible(False)
        details_layout = QVBoxLayout(self.details_widget)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(12)

        # Model info grid
        self.model_info = QFrame()
        self.model_info.setStyleSheet("QFrame { border: 1px solid #3a3a3a; border-radius: 6px; padding: 12px; background-color: #222; }")
        info_layout = QVBoxLayout(self.model_info)

        info_title_row = QHBoxLayout()
        self.model_info_title = QLabel("Current Model")
        self.model_info_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #ddd; border: none; background: transparent;")
        info_title_row.addWidget(self.model_info_title)
        info_title_row.addStretch()

        self.open_models_btn = QPushButton("Open Models Folder")
        self.open_models_btn.setFixedWidth(160)
        self.open_models_btn.clicked.connect(self._open_models_folder)
        info_title_row.addWidget(self.open_models_btn)
        info_layout.addLayout(info_title_row)

        self.model_grid = QGridLayout()
        self.model_grid.setColumnStretch(1, 1)
        self.model_grid.setColumnStretch(3, 1)
        self.model_grid.setVerticalSpacing(6)
        self.model_grid.setHorizontalSpacing(12)

        self._info_labels = {}
        fields = [
            ("Name:", 0, 0), ("Accuracy:", 0, 2),
            ("Sounds:", 1, 0), ("Nets:", 1, 2),
            ("Size:", 2, 0), ("Talon:", 2, 2),
        ]
        for label_text, row, col in fields:
            key = QLabel(label_text)
            key.setStyleSheet("color: #777; font-weight: bold; border: none; background: transparent;")
            val = QLabel("\u2014")
            val.setStyleSheet("color: #ccc; border: none; background: transparent;")
            val.setWordWrap(True)
            self.model_grid.addWidget(key, row, col)
            self.model_grid.addWidget(val, row, col + 1)
            self._info_labels[label_text] = val

        info_layout.addLayout(self.model_grid)
        details_layout.addWidget(self.model_info)

        # Talon section
        self.talon_frame = QFrame()
        self.talon_frame.setStyleSheet("QFrame { border: 1px solid #3a3a3a; border-radius: 6px; padding: 12px; background-color: #222; }")
        talon_layout = QVBoxLayout(self.talon_frame)

        talon_title_row = QHBoxLayout()
        self.talon_title = QLabel("Talon Integration")
        self.talon_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #ddd; border: none; background: transparent;")
        talon_title_row.addWidget(self.talon_title)
        talon_title_row.addStretch()

        self.open_talon_btn = QPushButton("Open Talon Folder")
        self.open_talon_btn.setFixedWidth(160)
        self.open_talon_btn.clicked.connect(self._open_talon_folder)
        talon_title_row.addWidget(self.open_talon_btn)
        talon_layout.addLayout(talon_title_row)

        self.talon_info = QLabel("")
        self.talon_info.setStyleSheet("color: #aaa; border: none; background: transparent;")
        self.talon_info.setWordWrap(True)
        talon_layout.addWidget(self.talon_info)

        details_layout.addWidget(self.talon_frame)

        # Recording overview
        self.recording_frame = QFrame()
        self.recording_frame.setStyleSheet("QFrame { border: 1px solid #3a3a3a; border-radius: 6px; padding: 12px; background-color: #222; }")
        rec_layout = QVBoxLayout(self.recording_frame)
        rec_title = QLabel("Recordings")
        rec_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #ddd; border: none; background: transparent;")
        rec_layout.addWidget(rec_title)
        self.duration_bar = DurationBarWidget()
        rec_layout.addWidget(self.duration_bar)
        details_layout.addWidget(self.recording_frame)

        # All models table
        self.models_frame = QFrame()
        self.models_frame.setStyleSheet("QFrame { border: 1px solid #3a3a3a; border-radius: 6px; padding: 12px; background-color: #222; }")
        models_layout = QVBoxLayout(self.models_frame)
        models_title = QLabel("All Models")
        models_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #ddd; border: none; background: transparent;")
        models_layout.addWidget(models_title)

        self.models_table = QTableWidget()
        self.models_table.setColumnCount(4)
        self.models_table.setHorizontalHeaderLabels(["Name", "Sounds", "Accuracy", "Nets"])
        self.models_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.models_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.models_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.models_table.verticalHeader().setVisible(False)
        self.models_table.setAlternatingRowColors(True)
        models_layout.addWidget(self.models_table)
        details_layout.addWidget(self.models_frame)

        # Notes
        self.notes_frame = QFrame()
        self.notes_frame.setStyleSheet("QFrame { border: 1px solid #3a3a3a; border-radius: 6px; padding: 12px; background-color: #222; }")
        notes_layout = QVBoxLayout(self.notes_frame)
        notes_title = QLabel("Notes")
        notes_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #ddd; border: none; background: transparent;")
        notes_layout.addWidget(notes_title)
        self.global_notes_edit = QTextEdit()
        self.global_notes_edit.setMaximumHeight(80)
        self.global_notes_edit.setPlaceholderText("General notes and reminders...")
        self.global_notes_edit.textChanged.connect(self._schedule_save_notes)
        notes_layout.addWidget(self.global_notes_edit)
        details_layout.addWidget(self.notes_frame)

        main_layout.addWidget(self.details_widget)
        main_layout.addStretch()
        self.content_layout.addWidget(self.main_widget)

    def _build_welcome(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 40, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Welcome to Parrot.py")
        title.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Train custom voice commands for Talon Voice")
        subtitle.setStyleSheet("color: #888; font-size: 14px;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)
        layout.addSpacing(30)

        steps = [
            ("Step 1: Record Sounds", "Record mouth sounds like pop, cluck, and hiss", "recording"),
            ("Step 2: Train a Model", "Train a neural network to recognize your sounds", "training"),
            ("Step 3: Use with Talon", "Copy your model to Talon and set up patterns.json", None),
        ]

        for step_title, desc, page in steps:
            card = ActionCard(step_title, desc)
            if page:
                card.clicked.connect(lambda checked=False, p=page: self.navigate_to_page.emit(p))
            layout.addWidget(card)
            layout.addSpacing(4)

        layout.addStretch()
        return widget

    def _refresh(self):
        first_run = self.app_state.is_first_run()
        self.welcome_widget.setVisible(first_run)
        self.main_widget.setVisible(not first_run)

        if first_run:
            return

        self._refresh_status()
        if self._details_visible:
            self._refresh_details()
        self._refresh_notes()

    def _refresh_status(self):
        """Build the one-line status summary."""
        parts = []

        active = self.app_state.get_active_model_name()
        if active:
            self._current_active_model = active
            # Try full metadata if cached, otherwise use fast
            meta = self.app_state.get_model_metadata(active, load_weights=True) \
                if (active, True) in self.app_state._model_cache \
                else self.app_state.get_model_metadata(active)
            parts.append(f"Model: {active}")
            if meta["best_accuracy"] is not None:
                parts.append(f"{meta['best_accuracy'] * 100:.0f}% accuracy")
            if meta["labels"]:
                parts.append(f"{len(meta['labels'])} sounds")
            parts.append(f"{meta['net_count']} nets")

        labels = self.app_state.get_sound_labels()
        if labels:
            total_s = sum(self.app_state.get_label_duration_ms(l) for l in labels) / 1000
            parts.append(f"{len(labels)} recordings ({total_s:.0f}s total)")

        talon = self.app_state.get_talon_status()
        if talon.talon_found:
            parts.append("Talon: Connected")
        else:
            parts.append("Talon: Not found")

        self.status_label.setText("  \u00b7  ".join(parts))

    def _toggle_details(self):
        self._details_visible = not self._details_visible
        self.details_widget.setVisible(self._details_visible)
        if self._details_visible:
            # Show immediately with fast data (file sizes, net counts)
            self._refresh_details_fast()
            # Load heavy data (labels, accuracy) in background
            self._load_weights_async()

    def _refresh_details_fast(self):
        self._refresh_model_info()
        self._refresh_talon_info()
        self._refresh_recordings()
        self._refresh_models_table()

    def _load_weights_async(self):
        self._metadata_worker = MetadataWorker(self.app_state, self)
        self._metadata_worker.finished.connect(self._on_weights_loaded)
        self._metadata_worker.start()

    def _on_weights_loaded(self, models):
        """Update UI with full metadata after background load."""
        if not self._details_visible:
            return
        self._refresh_model_info()
        self._refresh_models_table()
        self._refresh_status()

    def _refresh_details(self):
        self._refresh_model_info()
        self._refresh_talon_info()
        self._refresh_recordings()
        self._refresh_models_table()

    def _get_meta(self, name):
        """Get best available metadata — full if cached, fast otherwise."""
        if (name, True) in self.app_state._model_cache:
            return self.app_state._model_cache[(name, True)]
        return self.app_state.get_model_metadata(name)

    def _refresh_model_info(self):
        active = self._current_active_model or self.app_state.get_active_model_name()
        if not active:
            self.model_info_title.setText("No models found")
            for v in self._info_labels.values():
                v.setText("\u2014")
            return

        meta = self._get_meta(active)
        self.model_info_title.setText(f"Current Model")

        self._info_labels["Name:"].setText(meta["name"])
        self._info_labels["Sounds:"].setText(", ".join(meta["labels"]) if meta["labels"] else "\u2014")
        self._info_labels["Nets:"].setText(str(meta["net_count"]))
        self._info_labels["Size:"].setText(f"{meta['total_size_bytes'] / (1024*1024):.1f} MB")

        if meta["best_accuracy"] is not None:
            self._info_labels["Accuracy:"].setText(f"{meta['best_accuracy'] * 100:.1f}%")
        else:
            self._info_labels["Accuracy:"].setText("\u2014")

        # Talon match
        talon = self.app_state.get_talon_status()
        if talon.model_path_from_talon and os.path.isfile(talon.model_path_from_talon):
            from gui.services.talon_discovery import compare_model_files
            cmp = compare_model_files(meta["pkl_path"], talon.model_path_from_talon)
            if cmp["matches"]:
                self._info_labels["Talon:"].setText("Matches deployed model")
                self._info_labels["Talon:"].setStyleSheet("color: #4CAF50; border: none; background: transparent;")
            else:
                self._info_labels["Talon:"].setText("Different from deployed")
                self._info_labels["Talon:"].setStyleSheet("color: #FF9800; border: none; background: transparent;")
        else:
            self._info_labels["Talon:"].setText("No Talon model found")
            self._info_labels["Talon:"].setStyleSheet("color: #666; border: none; background: transparent;")

    def _refresh_talon_info(self):
        talon = self.app_state.get_talon_status()
        if talon.talon_found:
            lines = []
            if talon.integration_path:
                lines.append(f"Integration: {talon.integration_path}")
            if talon.pattern_path_from_talon:
                lines.append(f"Patterns: {talon.pattern_path_from_talon}")
            if talon.model_path_from_talon:
                lines.append(f"Model: {talon.model_path_from_talon}")
            if talon.patterns:
                pattern_names = ", ".join(talon.patterns.keys())
                lines.append(f"Active patterns: {pattern_names}")
            self.talon_info.setText("\n".join(lines))
            self.open_talon_btn.setVisible(True)
        else:
            self.talon_info.setText(talon.error or "Talon installation not found")
            self.open_talon_btn.setVisible(False)

    def _refresh_recordings(self):
        labels = self.app_state.get_sound_labels()
        label_durations = {}
        for label in labels:
            label_durations[label] = self.app_state.get_label_duration_ms(label)
        self.duration_bar.set_data(label_durations)

    def _refresh_models_table(self):
        models = [self._get_meta(n) for n in self.app_state.get_model_names()]
        active = self.app_state.get_active_model_name()

        self.models_table.setRowCount(len(models))
        for row, meta in enumerate(models):
            name = meta["name"]
            prefix = "\u2605 " if name == active else ""
            acc = f"{meta['best_accuracy'] * 100:.1f}%" if meta["best_accuracy"] is not None else "\u2014"

            self.models_table.setItem(row, 0, QTableWidgetItem(f"{prefix}{name}"))
            self.models_table.setItem(row, 1, QTableWidgetItem(", ".join(meta["labels"]) if meta["labels"] else "\u2014"))
            self.models_table.setItem(row, 2, QTableWidgetItem(acc))
            self.models_table.setItem(row, 3, QTableWidgetItem(str(meta["net_count"])))

            if name == active:
                for col in range(4):
                    item = self.models_table.item(row, col)
                    if item:
                        item.setBackground(QColor(30, 50, 30))

        height = min(300, len(models) * 30 + 30)
        self.models_table.setFixedHeight(max(60, height))

    def _refresh_notes(self):
        notes = self.app_state.load_notes()
        self.global_notes_edit.blockSignals(True)
        self.global_notes_edit.setPlainText(notes.get("global_notes", ""))
        self.global_notes_edit.blockSignals(False)

    def _schedule_save_notes(self):
        if self._notes_save_timer is not None:
            self._notes_save_timer.stop()
        self._notes_save_timer = QTimer(self)
        self._notes_save_timer.setSingleShot(True)
        self._notes_save_timer.timeout.connect(self._save_notes)
        self._notes_save_timer.start(500)

    def _save_notes(self):
        notes = self.app_state.load_notes()
        notes["global_notes"] = self.global_notes_edit.toPlainText()
        self.app_state.save_notes(notes)

    def _open_models_folder(self):
        path = os.path.abspath("data/models")
        if os.path.isdir(path):
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])

    def _open_talon_folder(self):
        talon = self.app_state.get_talon_status()
        path = None
        if talon.model_path_from_talon:
            path = os.path.dirname(talon.model_path_from_talon)
        elif talon.integration_path:
            path = os.path.dirname(talon.integration_path)

        if path and os.path.isdir(path):
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
