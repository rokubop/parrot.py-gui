"""Edit a recording: redo detection (the blue overlay) and trim the waveform.

Edits touch the files immediately (so the preview is truthful) but are
non-destructive until Save: entry snapshots the last-saved state
(``UndoHistory.begin_baseline``), and Back's Discard reverts to it.

Playing, zooming, selecting, deleting and undo all live in ``ClipEditorWidget``,
shared with the recording view. What is left here is what only this screen does:
re-running detection at a chosen threshold, and the save/discard contract.
"""
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QComboBox,
    QGroupBox, QMessageBox
)

from gui import components, theme
from gui.widgets.clip_editor import ClipEditorWidget
from gui.widgets.click_slider import ClickSlider, slider_qss
from gui.services import library_ops
from gui.services.undo import UndoHistory
from gui.workers.segment_worker import ReSegmentWorker, ResetWorker, read_min_dbfs


class EditRecordingView(QWidget):
    done = pyqtSignal(str)             # closed; arg = label to reselect

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.wav_path = None
        self.label = None
        self.worker = None             # detection only; the editor owns trims
        self.history = UndoHistory()
        # (min_dbfs, duration_type) of the last detect, to skip redundant re-runs
        self._last_applied = None

        # Debounce live threshold drags: re-detect once the slider settles
        # instead of on every intermediate value.
        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(350)
        self._apply_timer.timeout.connect(self._on_apply)

        self._setup_ui()

    # ---- entry ---------------------------------------------------------

    def start_for(self, wav_path):
        self.wav_path = wav_path
        self.label = library_ops.recording_label(wav_path)
        self.history.bind(wav_path)   # resets history when switching clips
        # Snapshot the saved state: every edit from here is reverted unless saved.
        self.history.begin_baseline()
        self._last_applied = None
        self._base = library_ops.recording_base(wav_path)
        self._update_title()
        self.editor.open(wav_path, self._current_srt(), self.label)
        # Initialize the threshold slider from any existing override.
        self._sync_slider_from_file()
        self.duration_combo.blockSignals(True)
        self.duration_combo.setCurrentIndex(0)
        self.duration_combo.blockSignals(False)
        self._set_busy(False)
        self.status.setText("")
        self.setFocus()   # so hotkeys work immediately on entering the view

    def _current_srt(self):
        """The SRT the library would show for this recording (MANUAL wins)."""
        for rec in self.app_state.get_recordings_for_label(self.label):
            if rec["wav_path"] == self.wav_path:
                return rec["srt_path"]
        return None

    # ---- ui ------------------------------------------------------------

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        top = QHBoxLayout()
        back = QPushButton("← Back to Sounds")
        back.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        back.clicked.connect(self._on_back)
        top.addWidget(back)
        self.title = QLabel("Edit recording")
        self.title.setStyleSheet(components.heading_style("title"))
        top.addWidget(self.title)
        top.addStretch()
        self.save_btn = QPushButton("Save")
        self.save_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.save_btn.setMinimumWidth(120)
        self.save_btn.setToolTip("Commit your edits to this recording - Ctrl+S")
        self.save_btn.clicked.connect(self._on_save)
        top.addWidget(self.save_btn)
        root.addLayout(top)

        self.editor = ClipEditorWidget(self.history, noun="clip")
        self.editor.srt_provider = self._current_srt
        self.editor.whole_clip_hint = "Delete the recording from Sounds instead."
        self.editor.status.connect(self.status_text)
        self.editor.edited.connect(self.app_state.recordings_changed.emit)
        self.editor.history_changed.connect(self._update_title)
        root.addWidget(self.editor, 1)

        # Keybindings are shown in the window status bar (see keybinding_hint()).
        # WindowShortcut: active whenever this (visible) view is focused, so a key
        # works right away without clicking into the view first.
        for seq, slot in (
                ("Ctrl+Z", self.editor.undo),
                ("Ctrl+Y", self.editor.redo),
                ("Ctrl+Shift+Z", self.editor.redo),
                ("Ctrl+S", self._on_save),
                ("Space", self.editor.toggle_play),
                ("A", self.editor.toggle_normalize),
                ("S", self.editor.toggle_spectrum),
                ("D", self.editor.deselect_or_start),
                ("Esc", self.editor.deselect_or_start),
                ("X", self.editor.delete_selection),
                ("Del", self.editor.delete_selection),
                ("Backspace", self.editor.delete_selection),
                ("F", self.editor.fit)):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(slot)

        # Re-detection reprocesses the whole clip, so the threshold applies via
        # the button, not live on every drag.
        det_group = QGroupBox("Detection (the blue overlay)")
        det = QHBoxLayout(det_group)
        det.addWidget(QLabel("Threshold:"))
        self.slider = ClickSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(-96, 0)
        self.slider.setValue(-40)
        self.slider.setMinimumWidth(220)
        self.slider.setMinimumHeight(24)
        self.slider.valueChanged.connect(self._update_slider_label)
        self.slider.setStyleSheet(slider_qss())
        det.addWidget(self.slider, 1)
        self.slider_label = QLabel("-40 dBFS")
        self.slider_label.setMinimumWidth(80)
        det.addWidget(self.slider_label)
        det.addWidget(QLabel("Type:"))
        self.duration_combo = QComboBox()
        self.duration_combo.addItem("Auto", "")
        self.duration_combo.addItem("Discrete", "discrete")
        self.duration_combo.addItem("Continuous", "continuous")
        det.addWidget(self.duration_combo)
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.apply_btn.setToolTip("Re-detect at this threshold / type")
        self.apply_btn.clicked.connect(self._on_apply)
        det.addWidget(self.apply_btn)
        self.reset_btn = QPushButton("Auto-detect")
        self.reset_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.reset_btn.setToolTip("Let detection find the threshold automatically "
                                  "(drops the manual override); the slider then "
                                  "shows what it picked")
        self.reset_btn.clicked.connect(self._on_reset)
        det.addWidget(self.reset_btn)
        root.addWidget(det_group)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {theme.colors()['accent']};")
        root.addWidget(self.status)

    def status_text(self, text):
        self.status.setText(text)

    def _update_slider_label(self, *_):
        v = self.slider.value()
        self.slider_label.setText(f"{v} dBFS")

    def _sync_slider_from_file(self):
        """Move the slider to whatever threshold is on disk - so after Auto-detect
        it shows the value detection picked."""
        existing = read_min_dbfs(self.wav_path)
        self.slider.blockSignals(True)
        self.slider.setValue(int(existing) if existing is not None else -40)
        self.slider.blockSignals(False)
        self._update_slider_label()

    # ---- detection edits ----------------------------------------------

    def _set_busy(self, busy, message=""):
        for w in (self.apply_btn, self.reset_btn, self.slider,
                  self.duration_combo, self.save_btn):
            w.setEnabled(not busy)
        self.editor.set_busy(busy, message)
        if not busy:
            self._update_title()

    def _finish_worker(self):
        """Tear a finished detection thread down safely. The result signal fires
        before run() returns, so wait() before dropping the reference or a
        still-running QThread gets deleted (a hard crash)."""
        w = self.worker
        self.worker = None
        if w is not None:
            w.wait()
            w.deleteLater()

    def _on_apply(self):
        if self.worker or self.editor.is_busy():
            # A detect is still running; retry once it's free so the latest
            # threshold the user landed on is the one that sticks.
            self._apply_timer.start()
            return
        params = (self.slider.value(), self.duration_combo.currentData())
        if params == self._last_applied:
            self.status.setText("No change to apply.")
            return  # nothing changed since the last detect - skip the expensive work
        self.editor.stop_playback()
        self.history.checkpoint()
        self._last_applied = params
        self._set_busy(True, "Re-detecting…")
        self.status.setText("Re-detecting…")
        self.worker = ReSegmentWorker(self.wav_path, self.label, params[0], params[1])
        self.worker.finished_ok.connect(self._on_segment_done)
        self.worker.failed.connect(self._on_segment_failed)
        self.worker.start()

    def _on_reset(self):
        if self.worker or self.editor.is_busy():
            return
        self.editor.stop_playback()
        self.history.checkpoint()
        self._last_applied = None   # auto state - let the next threshold apply
        self._set_busy(True, "Auto-detecting…")
        self.status.setText("Resetting to automatic detection…")
        self.worker = ResetWorker(self.wav_path, self.label)
        self.worker.finished_ok.connect(self._on_segment_done)
        self.worker.failed.connect(self._on_segment_failed)
        self.worker.start()

    def _on_segment_done(self, srt_path):
        self._finish_worker()
        # Only the overlay changed, so the waveform, zoom and playhead all stay.
        self.editor.set_regions(srt_path)
        self._sync_slider_from_file()
        self.app_state.recordings_changed.emit()
        self._set_busy(False)
        self.status.setText("Detection updated.")

    def _on_segment_failed(self, message):
        self._finish_worker()
        self._last_applied = None   # let the user retry the same threshold
        # The op didn't change anything, so drop the checkpoint we took for it.
        self.history.discard_last_checkpoint()
        self._set_busy(False)
        self.status.setText("")
        QMessageBox.warning(self, "Couldn't update detection", message)

    # ---- save / dirty state --------------------------------------------

    def _update_title(self):
        star = " *" if self.history.is_dirty() else ""
        self.title.setText(f"Edit:  {self.label}  /  {getattr(self, '_base', '')}{star}")
        self.save_btn.setEnabled(self.history.is_dirty() and not self.worker
                                 and not self.editor.is_busy())

    def _on_save(self):
        if self.worker or self.editor.is_busy() or not self.history.is_dirty():
            return
        self.history.commit_baseline()
        self.editor.refresh_history_buttons()
        self._update_title()
        self.status.setText("Saved.")

    def keybinding_hint(self):
        return (self.editor.keybinding_hint() +
                "  ·  Ctrl+S save  ·  unsaved until Save")

    # ---- navigation ----------------------------------------------------

    def _on_back(self):
        if self.worker or self.editor.is_busy():
            return  # don't leave mid-edit
        self.editor.stop_playback()
        if self.history.is_dirty():
            choice = QMessageBox.question(
                self, "Unsaved edits",
                f"You have unsaved edits to “{self.label}”. Save them?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save)
            if choice == QMessageBox.StandardButton.Cancel:
                return
            if choice == QMessageBox.StandardButton.Save:
                self.history.commit_baseline()
            else:  # Discard
                self.history.revert_to_baseline()
                self.app_state.recordings_changed.emit()
        self.history.clear()   # undo history is per-editing-session
        self.editor.clear()
        self.done.emit(self.label or "")

    def stop_playback(self):
        self.editor.stop_playback()

    def refresh_theme(self):
        self.editor.refresh_theme()
