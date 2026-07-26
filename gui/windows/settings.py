"""Settings page.

Edits the user-overridable config (persisted to data/code/config.py) and
exposes the data folders. Most values are read by the engine at import time, so
changes apply on the next launch - the page states this rather than pretending
they're live.
"""
import os
import sounddevice as sd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QComboBox,
    QPushButton, QGroupBox, QScrollArea, QFrame
)

from config.config import (
    INPUT_DEVICE_INDEX, THRESHOLD_DETECTION, TWO_PASS_DETECTION,
    RECORDINGS_FOLDER, CLASSIFIER_FOLDER,
)
from gui import theme
from gui.services import user_config, strategies, library_ops


class SettingsPage(QWidget):
    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self._setup_ui()
        self.app_state.models_changed.connect(self._populate_models)

    def _setup_ui(self):
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

        title = QLabel("Settings")
        title.setStyleSheet(
            f"font-size: 20px; font-weight: bold; color: {theme.colors()['text_bright']};")
        layout.addWidget(title)

        note = QLabel(f"Changes are saved to {user_config.USER_CONFIG_PATH} "
                      "and take effect the next time you launch Parrot.py.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.colors()['text_dim']};")
        layout.addWidget(note)

        # ---- Audio / detection ----
        audio_group = QGroupBox("Audio & detection")
        form = QFormLayout(audio_group)
        form.setSpacing(10)

        self.device_combo = QComboBox()
        self._populate_devices()
        form.addRow("Input device:", self.device_combo)

        self.threshold_combo = QComboBox()
        self.threshold_combo.addItem("Strict - rapid back-to-back sounds", "strict")
        self.threshold_combo.addItem("Lenient - more space between sounds", "lenient")
        idx = self.threshold_combo.findData(THRESHOLD_DETECTION)
        if idx >= 0:
            self.threshold_combo.setCurrentIndex(idx)
        form.addRow("Threshold mode:", self.threshold_combo)

        self.two_pass_combo = QComboBox()
        self.two_pass_combo.addItem(
            "Two-pass - re-judge the whole recording once thresholds settle", True)
        self.two_pass_combo.addItem(
            "Single-pass - keep the live judgments as-is (legacy)", False)
        self.two_pass_combo.setCurrentIndex(0 if TWO_PASS_DETECTION else 1)
        form.addRow("Detection passes:", self.two_pass_combo)

        two_pass_desc = QLabel(
            "While you record, thresholds calibrate live and need roughly ten "
            "sounds before they settle - so the first sounds of a take are "
            "judged by weaker criteria. Two-pass re-judges the entire recording "
            "with the settled thresholds whenever it is saved or re-detected, "
            "so the start is segmented as accurately as the end. A manual "
            "threshold set in a recording's edit view always wins over either.")
        two_pass_desc.setWordWrap(True)
        two_pass_desc.setStyleSheet(
            f"color: {theme.colors()['text_dim']}; font-size: 12px;")
        form.addRow("", two_pass_desc)

        self.strategy_combo = QComboBox()
        for label in strategies.labels():
            self.strategy_combo.addItem(label)
        si = self.strategy_combo.findText(strategies.default_label())
        if si >= 0:
            self.strategy_combo.setCurrentIndex(si)
        self.strategy_combo.currentTextChanged.connect(self._on_strategy_changed)
        form.addRow("Default strategy:", self.strategy_combo)

        self.strategy_desc = QLabel(strategies.description_for_label(
            self.strategy_combo.currentText()))
        self.strategy_desc.setWordWrap(True)
        self.strategy_desc.setStyleSheet(
            f"color: {theme.colors()['text_dim']}; font-size: 12px;")
        form.addRow("", self.strategy_desc)

        layout.addWidget(audio_group)

        # ---- Default model ----
        model_group = QGroupBox("Playback")
        model_form = QFormLayout(model_group)
        self.model_combo = QComboBox()
        self._populate_models()
        model_form.addRow("Default model:", self.model_combo)
        layout.addWidget(model_group)

        # ---- Folders ----
        folder_group = QGroupBox("Data folders")
        folder_layout = QVBoxLayout(folder_group)
        folder_layout.addLayout(self._folder_row("Recordings", RECORDINGS_FOLDER))
        folder_layout.addLayout(self._folder_row("Models", CLASSIFIER_FOLDER))
        layout.addWidget(folder_group)

        # ---- Save ----
        save_row = QHBoxLayout()
        save_row.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {theme.colors()['accent']};")
        save_row.addWidget(self.status_label)
        save_btn = QPushButton("Save settings")
        save_btn.clicked.connect(self._on_save)
        save_row.addWidget(save_btn)
        layout.addLayout(save_row)

        layout.addStretch()

    def _folder_row(self, name, path):
        row = QHBoxLayout()
        lbl = QLabel(f"{name}:  {os.path.abspath(path)}")
        lbl.setStyleSheet(f"color: {theme.colors()['text_dim']};")
        row.addWidget(lbl)
        row.addStretch()
        btn = QPushButton("Open folder")
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.clicked.connect(lambda: self._open(path))
        row.addWidget(btn)
        return row

    def _open(self, path):
        try:
            os.makedirs(path, exist_ok=True)
            library_ops.open_in_file_manager(path)
        except library_ops.LibraryOpError as exc:
            self.status_label.setText(str(exc))

    def _populate_devices(self):
        self.device_combo.clear()
        try:
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if dev.get("max_input_channels", 0) > 0:
                    self.device_combo.addItem(f"[{i}] {dev['name']}", i)
        except Exception:
            pass
        if self.device_combo.count() == 0:
            self.device_combo.addItem(f"[{INPUT_DEVICE_INDEX}] Default",
                                      INPUT_DEVICE_INDEX)
        idx = self.device_combo.findData(INPUT_DEVICE_INDEX)
        if idx >= 0:
            self.device_combo.setCurrentIndex(idx)

    def _populate_models(self):
        if not hasattr(self, "model_combo"):
            return
        current = self.model_combo.currentData()
        self.model_combo.clear()
        self.model_combo.addItem("(none)", "")
        for name in self.app_state.get_model_names():
            self.model_combo.addItem(name, name)
        from config.config import DEFAULT_CLF_FILE
        want = current if current else DEFAULT_CLF_FILE
        idx = self.model_combo.findData(want)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)

    def _on_strategy_changed(self, label):
        self.strategy_desc.setText(strategies.description_for_label(label))

    def _on_save(self):
        updates = {
            "INPUT_DEVICE_INDEX": self.device_combo.currentData(),
            "THRESHOLD_DETECTION": self.threshold_combo.currentData(),
            "TWO_PASS_DETECTION": bool(self.two_pass_combo.currentData()),
            "CURRENT_DETECTION_STRATEGY": strategies.strategy_for_label(
                self.strategy_combo.currentText()),
            "DEFAULT_CLF_FILE": self.model_combo.currentData() or "",
        }
        try:
            user_config.write_user_config(updates)
            self.status_label.setText("Saved - applies on next launch.")
        except Exception as exc:
            self.status_label.setText(f"Couldn't save: {exc}")

    def refresh_theme(self):
        pass
