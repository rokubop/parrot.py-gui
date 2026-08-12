"""Edit a recording: redo detection (the blue overlay) and trim the waveform.

Edits touch the files immediately (so the preview is truthful) but are
non-destructive until Save: entry snapshots the last-saved state
(``UndoHistory.begin_baseline``), and Back's Discard reverts to it.

Playing, zooming, selecting, deleting and undo all live in ``ClipEditorWidget``;
re-detecting at a chosen threshold lives in ``DetectionPanel``. Both are shared
with the recording view. What is left here is what only this screen does: the
save/discard contract.
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QMessageBox
)

from gui import components, theme
from gui.widgets.clip_editor import ClipEditorWidget
from gui.widgets.detection_panel import DetectionPanel
from gui.services import library_ops
from gui.services.undo import UndoHistory


class EditRecordingView(QWidget):
    done = pyqtSignal(str)             # closed; arg = label to reselect

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.wav_path = None
        self.label = None
        self.history = UndoHistory()
        # Back is waiting on a re-detect it asked for.
        self._exit_after_apply = False

        self._setup_ui()

    # ---- entry ---------------------------------------------------------

    def start_for(self, wav_path):
        self.wav_path = wav_path
        self.label = library_ops.recording_label(wav_path)
        self.history.bind(wav_path)   # resets history when switching clips
        # Snapshot the saved state: every edit from here is reverted unless saved.
        self.history.begin_baseline()
        self._exit_after_apply = False
        self._base = library_ops.recording_base(wav_path)
        self._update_title()
        self.editor.open(wav_path, self._current_srt(), self.label)
        self.detection.bind(wav_path, self.label)
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

        self.editor = ClipEditorWidget(self.history, noun="clip", show_levels=True)
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
                ("L", self.editor.toggle_levels),
                ("F", self.editor.fit)):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(slot)

        self.detection = DetectionPanel(self.history)
        self.detection.attach_lane(self.editor.lane)
        self.detection.host_busy = self.editor.is_busy
        self.detection.status.connect(self.status_text)
        self.detection.busy_changed.connect(self._on_detection_busy)
        self.detection.changed.connect(self._on_detection_changed)
        self.detection.finished.connect(self._on_detection_finished)
        # An undo or a trim rewrites the files the panel is reporting on.
        self.editor.history_changed.connect(self.detection.resync)
        root.addWidget(self.detection)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {theme.colors()['accent']};")
        root.addWidget(self.status)

    def status_text(self, text):
        self.status.setText(text)

    # ---- detection edits ----------------------------------------------

    def _set_busy(self, busy, message=""):
        self.detection.set_busy(busy)
        self.save_btn.setEnabled(not busy)
        self.editor.set_busy(busy, message)
        if not busy:
            self._update_title()

    def _on_detection_busy(self, busy, message):
        if busy:
            self.editor.stop_playback()
        self._set_busy(busy, message)

    def _on_detection_changed(self, srt_path):
        # Only the overlay changed, so the waveform, zoom and playhead all stay.
        # An empty path means the pass died part way and disk is the only truth.
        self.editor.set_regions(srt_path or self._current_srt())
        self.app_state.recordings_changed.emit()

    # ---- save / dirty state --------------------------------------------

    def _update_title(self):
        dirty = self.history.is_dirty()
        star = " *" if dirty else ""
        self.title.setText(f"Edit:  {self.label}  /  {getattr(self, '_base', '')}{star}")
        self.save_btn.setEnabled(dirty and not self._busy())
        # Same rule as Apply: the accent marks the thing left to do.
        components.set_primary(self.save_btn, dirty)

    def _busy(self):
        return self.detection.is_busy() or self.editor.is_busy()

    def _on_save(self):
        if self._busy() or not self.history.is_dirty():
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
        """Leaving must account for both kinds of unfinished work.

        A threshold that has been applied is an edit, held by the baseline until
        Save. A threshold that has only been dialled in is not on disk at all,
        and used to be dropped without a word - so the green button was the one
        that vanished silently and the dark one was the one that stopped you.
        """
        if self._busy():
            return  # don't leave mid-edit
        self.editor.stop_playback()
        pending = self.detection.has_pending()
        dirty = self.history.is_dirty()
        if pending or dirty:
            choice = self._ask_before_leaving(pending, dirty)
            if choice == "cancel":
                return
            if choice == "discard":
                if dirty:
                    self.history.revert_to_baseline()
                    self.app_state.recordings_changed.emit()
            elif pending:
                # Runs the pass first; _on_detection_finished leaves after it.
                self._exit_after_apply = True
                self.detection.apply()
                return
            else:
                self.history.commit_baseline()
        self._finish_leaving()

    def _ask_before_leaving(self, pending, dirty):
        """One dialog, whichever combination is true. Two in a row for one Back
        is worse than a sentence with two clauses in it."""
        if pending and dirty:
            body = (f"Detection is set to {self.detection.pending_summary()} but "
                    f"has not been applied, and you have unsaved edits to "
                    f"“{self.label}”.")
            keep = "Apply and save"
        elif pending:
            body = (f"Detection is set to {self.detection.pending_summary()} but "
                    f"has not been applied.")
            keep = "Apply"
        else:
            body = f"You have unsaved edits to “{self.label}”."
            keep = "Save"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Before you go")
        box.setText(body)
        keep_btn = box.addButton(keep, QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(keep_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is cancel_btn:
            return "cancel"
        return "keep" if clicked is keep_btn else "discard"

    def _on_detection_finished(self, ok):
        """A pass ended. If Back is waiting on it, finish leaving - or stay put
        and let the panel's own warning stand."""
        if not self._exit_after_apply:
            return
        self._exit_after_apply = False
        if ok:
            self.history.commit_baseline()
            self._finish_leaving()

    def _finish_leaving(self):
        self.history.clear()   # undo history is per-editing-session
        self.editor.clear()
        self.detection.clear()
        self._exit_after_apply = False
        self.done.emit(self.label or "")

    def stop_playback(self):
        self.editor.stop_playback()

    def refresh_theme(self):
        self.editor.refresh_theme()
        self.detection.refresh_theme()
        components.refresh_primary(self.save_btn)
