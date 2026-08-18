"""Settings page.

Edits the user-overridable config (persisted to data/code/config.py) and
exposes the data folders. Most values are read by the engine at import time, so
changes apply on the next launch - the page states this rather than pretending
they're live.
"""
import os
import sounddevice as sd
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QComboBox,
    QPushButton, QGroupBox, QScrollArea, QFrame, QMessageBox, QApplication
)

from config.config import (
    THRESHOLD_DETECTION, TWO_PASS_DETECTION,
    RECORDINGS_FOLDER, CLASSIFIER_FOLDER,
)
from gui import components, content, icons, theme
from gui.services import (user_config, strategies, library_ops, audio_devices,
                          ui_prefs, profiles)
from gui.content import program as program_content


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
        title.setStyleSheet(components.heading_style("title"))
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

        two_pass_desc = QLabel(content.short("detection"))
        two_pass_desc.setWordWrap(True)
        two_pass_desc.setStyleSheet(
            f"color: {theme.colors()['text_dim']}; ")
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
            f"color: {theme.colors()['text_dim']}; ")
        form.addRow("", self.strategy_desc)

        layout.addWidget(audio_group)

        # ---- Display ----
        display_group = QGroupBox("Display")
        display_form = QFormLayout(display_group)
        display_form.setSpacing(10)
        self.scale_combo = QComboBox()
        for value in ui_prefs.SCALES:
            self.scale_combo.addItem(f"{value:.0%}", value)
        self._scale_now = ui_prefs.scale()
        self.scale_combo.setCurrentIndex(self._scale_index(self._scale_now))
        self.scale_combo.setToolTip(
            "Text, spacing and controls together, so nothing crops")
        # Four short values. Stretched to the form's full width it reads as a
        # field waiting to be filled in.
        self.scale_combo.setMaximumWidth(150)
        self.scale_combo.currentIndexChanged.connect(self._on_scale_changed)
        display_form.addRow("Interface size:", self.scale_combo)
        scale_note = QLabel(
            "Ctrl + and Ctrl - anywhere in the app, Ctrl 0 for 100%. Scales "
            "the whole window at once. Kept per machine, not in your data "
            "folder, so it stays put when you switch profiles or copy your "
            "data somewhere else. Restarts Parrot.py.")
        scale_note.setWordWrap(True)
        scale_note.setStyleSheet(f"color: {theme.colors()['text_dim']};")
        display_form.addRow("", scale_note)
        layout.addWidget(display_group)

        # ---- Playback ----
        model_group = QGroupBox("Playback")
        model_form = QFormLayout(model_group)
        self.output_combo = QComboBox()
        self.output_combo.setToolTip("Where recordings play back - applies "
                                     "immediately, no save needed")
        self._populate_output_devices()
        self.output_combo.currentIndexChanged.connect(self._on_output_changed)
        out_row = QHBoxLayout()
        out_row.addWidget(self.output_combo, 1)
        self.rescan_btn = QPushButton()
        self.rescan_btn.setIcon(icons.restart())
        self.rescan_btn.setToolTip(
            "Scan for devices plugged in since Parrot.py started")
        self.rescan_btn.setMaximumWidth(48)
        self.rescan_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.rescan_btn.clicked.connect(self._on_rescan)
        out_row.addWidget(self.rescan_btn)
        model_form.addRow("Output device:", out_row)
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

        # ---- Profiles ----
        profiles_group = QGroupBox("Profiles")
        profiles_layout = QHBoxLayout(profiles_group)
        profiles_desc = QLabel(
            program_content.PROFILE_SHORT
            + " Once one exists, the switcher is in the top right.")
        profiles_desc.setWordWrap(True)
        profiles_layout.addWidget(profiles_desc, stretch=1)
        manage_profiles_btn = QPushButton("Manage profiles...")
        manage_profiles_btn.clicked.connect(self._on_manage_profiles)
        profiles_layout.addWidget(manage_profiles_btn)
        layout.addWidget(profiles_group)

        # ---- Back up ----
        backup_group = QGroupBox("Back up")
        backup_layout = QVBoxLayout(backup_group)
        backup_desc = QLabel(program_content.DATA_FOLDER_SHORT)
        backup_desc.setWordWrap(True)
        backup_layout.addWidget(backup_desc)
        backup_row = QHBoxLayout()
        open_data_btn = QPushButton("Open data folder")
        open_data_btn.clicked.connect(self._on_open_data_folder)
        backup_row.addWidget(open_data_btn)
        export_btn = QPushButton("Export a copy...")
        export_btn.setToolTip("A complete copy in a folder you pick")
        export_btn.clicked.connect(self._on_export_copy)
        backup_row.addWidget(export_btn)
        self.backup_status = QLabel("")
        self.backup_status.setStyleSheet(f"color: {theme.colors()['text_dim']};")
        backup_row.addWidget(self.backup_status)
        backup_row.addStretch()
        backup_layout.addLayout(backup_row)
        layout.addWidget(backup_group)

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

    def _scale_index(self, value):
        return list(ui_prefs.SCALES).index(value) if value in ui_prefs.SCALES else 0

    def _on_scale_changed(self, _index):
        """Qt reads the scale factor once, when the QApplication is built, so
        this cannot be applied in place - it is a relaunch or nothing. Asked
        rather than done: the app is quitting, and it might be mid-recording."""
        value = self.scale_combo.currentData()
        if value == self._scale_now:
            return
        # The main window can name what a restart would throw away; plain
        # question when this page is hosted elsewhere.
        window = self.window()
        if hasattr(window, "confirm_closing"):
            accepted = window.confirm_closing(
                "Interface size", "Restart now",
                restart_reason=f"apply the {value:.0%} interface size")
        else:
            accepted = QMessageBox.question(
                self, "Interface size",
                f"Parrot.py needs to restart to apply the "
                f"{value:.0%} interface size."
                ) == QMessageBox.StandardButton.Yes
        if not accepted:
            self.scale_combo.blockSignals(True)
            self.scale_combo.setCurrentIndex(self._scale_index(self._scale_now))
            self.scale_combo.blockSignals(False)
            return
        ui_prefs.set_scale(value)
        env = dict(os.environ)
        # This process carries the old factor; an explicit one beats the file.
        env.pop(ui_prefs.ENV, None)
        profiles.relaunch(env)
        QTimer.singleShot(0, QApplication.instance().quit)

    def _on_manage_profiles(self):
        window = self.window()
        if hasattr(window, "open_profiles_dialog"):
            window.open_profiles_dialog()  # also refreshes the toolbar chip
        else:
            from gui.windows.profiles import ProfilesDialog
            ProfilesDialog(self.app_state, self).exec()

    def _on_open_data_folder(self):
        from config.config import DATA_DIR
        try:
            library_ops.open_in_file_manager(os.path.abspath(DATA_DIR))
        except library_ops.LibraryOpError as exc:
            self.backup_status.setText(str(exc))

    def _on_export_copy(self):
        from PyQt6.QtWidgets import QFileDialog
        from config.config import DATA_DIR
        from gui.services import profiles
        from gui.windows.profiles import _OpWorker
        dest_parent = QFileDialog.getExistingDirectory(self, "Export to")
        if not dest_parent:
            return
        self.backup_status.setText("Copying...")
        result = {}

        def copy():
            result["path"] = profiles.export_copy(DATA_DIR, dest_parent)

        self._export_worker = _OpWorker(copy, self)
        self._export_worker.done.connect(
            lambda error: self._on_export_done(error, result))
        self._export_worker.start()

    def _on_export_done(self, error, result):
        self._export_worker = None
        if error:
            self.backup_status.setText(error)
            return
        path = result.get("path", "")
        self.backup_status.setText(f"Copied to {path}")
        try:
            library_ops.open_in_file_manager(path)
        except library_ops.LibraryOpError:
            pass

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

    def _populate_output_devices(self):
        self.output_combo.blockSignals(True)
        self.output_combo.clear()
        try:
            default_api = sd.default.hostapi
            for i, dev in enumerate(sd.query_devices()):
                if dev.get("hostapi") == default_api and \
                        dev.get("max_output_channels", 0) > 0:
                    self.output_combo.addItem(dev["name"], i)
        except Exception:
            pass
        idx = self.output_combo.findData(audio_devices.output_index)
        if idx >= 0:
            self.output_combo.setCurrentIndex(idx)
        self.output_combo.blockSignals(False)

    def _on_rescan(self):
        """Re-enumerate the hardware, then relist. Also picks up new mics - the
        scan is global, so the recording view's picker sees them too."""
        self.rescan_btn.setEnabled(False)
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.BusyCursor))
        try:
            audio_devices.rescan()
        finally:
            QApplication.restoreOverrideCursor()
            self.rescan_btn.setEnabled(True)
        self._populate_output_devices()

    def _on_output_changed(self, _index):
        device = self.output_combo.currentData()
        if device is not None:
            audio_devices.set_output(device)

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
