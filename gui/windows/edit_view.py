"""Edit a recording: redo detection (the blue overlay) and trim the waveform.

Non-destructive until Save: on entry we snapshot the recording's last-saved
state (``UndoHistory.begin_baseline``). Edits do touch the files (so the preview
is always truthful) but Back offers Save / Discard / Cancel, and Discard reverts
to that baseline. The title shows a ``*`` whenever there are unsaved edits.

Two kinds of edit, both reflected immediately in the waveform + detection:

* Re-detect - set a threshold / duration type and click Apply (writes a manual
  override / ``.MANUAL.srt``); "Auto-detect" finds the threshold automatically
  and shows it on the slider.
* Delete a selected time range from the source WAV, which rewrites the file and
  re-detects. Every edit is undoable (Ctrl+Z / Undo button).

Includes lightweight playback (whole clip or the current selection) so you can
audition before and after an edit.
"""
from PyQt6.QtCore import Qt, QTimer, QElapsedTimer, pyqtSignal
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QComboBox,
    QGroupBox, QMessageBox
)

from gui import theme
from gui.widgets.audio_preview import AudioPreviewWidget
from gui.widgets.click_slider import ClickSlider
from gui.services import library_ops, playback
from gui.services.undo import UndoHistory
from gui.workers.segment_worker import (
    ReSegmentWorker, ResetWorker, TrimWorker, read_min_dbfs,
)


class EditRecordingView(QWidget):
    done = pyqtSignal(str)             # closed; arg = label to reselect

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.wav_path = None
        self.label = None
        self.worker = None
        self.history = UndoHistory()

        # view toggles (mirror AudioPreviewWidget defaults)
        self._norm = False
        self._mode = "waveform"
        # (min_dbfs, duration_type) of the last detect, to skip redundant re-runs
        self._last_applied = None

        # playback
        self._audio = None
        self._sr = None
        self._duration = 0.0
        self._playing = False
        self._play_from = 0.0
        self._stop_at = None
        self._latency = 0.0       # output buffer delay of the current play
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._clock = QElapsedTimer()

        # Debounce live threshold drags: re-detect once the slider settles
        # instead of on every intermediate value.
        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(350)
        self._apply_timer.timeout.connect(self._on_apply)

        self._setup_ui()

    # ---- entry ---------------------------------------------------------

    def start_for(self, wav_path):
        self.stop_playback()
        self.wav_path = wav_path
        self.label = library_ops.recording_label(wav_path)
        self.history.bind(wav_path)   # resets history when switching clips
        # Snapshot the saved state: every edit from here is reverted unless saved.
        self.history.begin_baseline()
        self._last_applied = None
        self._base = library_ops.recording_base(wav_path)
        self._update_title()
        srt = self._current_srt()
        self.preview.load(wav_path, srt)
        self.preview.fit_full()
        self._audio = None  # force re-decode on next play
        self._play_from = 0.0
        self._stop_at = None
        # Initialize the threshold slider from any existing override.
        existing = read_min_dbfs(wav_path)
        self.slider.blockSignals(True)
        self.slider.setValue(int(existing) if existing is not None else -40)
        self.slider.blockSignals(False)
        self._update_slider_label()
        self.duration_combo.blockSignals(True)
        self.duration_combo.setCurrentIndex(0)
        self.duration_combo.blockSignals(False)
        self._set_busy(False)
        self._update_undo_buttons()
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
        self.title.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {theme.colors()['text_bright']};")
        top.addWidget(self.title)
        top.addStretch()
        self.save_btn = QPushButton("Save")
        self.save_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.save_btn.setMinimumWidth(120)
        self.save_btn.setToolTip("Commit your edits to this recording - Ctrl+S")
        self.save_btn.clicked.connect(self._on_save)
        top.addWidget(self.save_btn)
        root.addLayout(top)

        self.preview = AudioPreviewWidget()
        self.preview.seeked.connect(self._on_seek)
        root.addWidget(self.preview, 1)

        # Playback row
        play_row = QHBoxLayout()
        self.play_btn = QPushButton("▶ Play")
        self.play_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.play_btn.clicked.connect(self._toggle_play)
        play_row.addWidget(self.play_btn)
        fit_btn = QPushButton("Fit")
        fit_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        fit_btn.clicked.connect(self.preview.toggle_fit)
        play_row.addWidget(fit_btn)
        play_row.addSpacing(16)
        self.undo_btn = QPushButton("Undo")
        self.undo_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.undo_btn.setToolTip("Undo the last edit - Ctrl+Z")
        self.undo_btn.clicked.connect(self._on_undo)
        play_row.addWidget(self.undo_btn)
        self.redo_btn = QPushButton("Redo")
        self.redo_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.redo_btn.setToolTip("Redo - Ctrl+Y")
        self.redo_btn.clicked.connect(self._on_redo)
        play_row.addWidget(self.redo_btn)
        play_row.addStretch()
        root.addLayout(play_row)

        # Keybindings are shown in the window status bar (see keybinding_hint()).
        # WindowShortcut: active whenever this (visible) view is focused, so a key
        # works right away without clicking into the view first.
        for seq, slot in (
                ("Ctrl+Z", self._on_undo),
                ("Ctrl+Y", self._on_redo),
                ("Ctrl+Shift+Z", self._on_redo),
                ("Ctrl+S", self._on_save),
                ("Space", self._toggle_play),
                ("A", self._toggle_normalize),
                ("S", self._toggle_spectrum),
                ("D", self._deselect_or_start),
                ("Esc", self._deselect_or_start),
                ("X", self._on_delete_range),
                ("Del", self._on_delete_range),
                ("Backspace", self._on_delete_range),
                ("F", self.preview.toggle_fit)):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(slot)

        # Detection (threshold) group - dragging the threshold re-detects live.
        # Re-detection is expensive (it reprocesses the whole clip), so the
        # threshold is applied on demand via the button, not live on every drag.
        det_group = QGroupBox("Detection (the blue overlay)")
        det = QHBoxLayout(det_group)
        det.addWidget(QLabel("Threshold:"))
        self.slider = ClickSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(-96, 0)
        self.slider.setValue(-40)
        self.slider.setMinimumWidth(220)
        self.slider.setMinimumHeight(24)
        self.slider.valueChanged.connect(self._update_slider_label)
        self.slider.setStyleSheet(self._slider_qss())
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

        # Trim group
        trim_group = QGroupBox("Edit audio")
        trim = QHBoxLayout(trim_group)
        self.delete_btn = QPushButton("Delete selected range")
        self.delete_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.delete_btn.setToolTip("Remove the selected part of the waveform "
                                   "(also updates detection) - undoable, and not "
                                   "saved until you click Save. Del")
        self.delete_btn.clicked.connect(self._on_delete_range)
        trim.addWidget(self.delete_btn)
        trim_note = QLabel("Nothing is saved until you click Save - Back lets you "
                           "discard. Drag-select a range, then Delete it.")
        trim_note.setStyleSheet(f"color: {theme.colors()['text_dim']};")
        trim.addWidget(trim_note)
        trim.addStretch()
        root.addWidget(trim_group)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {theme.colors()['accent']};")
        root.addWidget(self.status)

    def _slider_qss(self):
        t = theme.colors()
        # A tall groove + big round handle so the whole bar is an easy target
        # (ClickSlider already lets you click anywhere along it to jump there).
        return (
            f"QSlider::groove:horizontal {{ height: 8px; border-radius: 4px; "
            f"background: {t['border']}; }}"
            f"QSlider::sub-page:horizontal {{ background: {t['accent']}; "
            f"border-radius: 4px; }}"
            f"QSlider::handle:horizontal {{ width: 16px; height: 16px; "
            f"margin: -6px 0; border-radius: 8px; background: {t['text_bright']}; "
            f"border: 2px solid {t['accent']}; }}"
            f"QSlider::handle:horizontal:hover {{ background: {t['accent']}; }}")

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

    def _set_busy(self, busy):
        for w in (self.apply_btn, self.reset_btn, self.delete_btn,
                  self.slider, self.duration_combo, self.save_btn):
            w.setEnabled(not busy)

    def _finish_worker(self):
        """Tear a finished detection thread down safely. The worker emits its
        result as the LAST line of run(), so without waiting for the thread to
        actually return, dropping the reference here could delete a still-running
        QThread (a hard crash) - wait() returns near-instantly and prevents it."""
        w = self.worker
        self.worker = None
        if w is not None:
            w.wait()
            w.deleteLater()

    def _on_apply(self):
        if self.worker:
            # A detect is still running; retry once it's free so the latest
            # threshold the user landed on is the one that sticks.
            self._apply_timer.start()
            return
        params = (self.slider.value(), self.duration_combo.currentData())
        if params == self._last_applied:
            self.status.setText("No change to apply.")
            return  # nothing changed since the last detect - skip the expensive work
        self.stop_playback()
        self.history.checkpoint()
        self._last_applied = params
        self._set_busy(True)
        self.status.setText("Re-detecting…")
        self.worker = ReSegmentWorker(self.wav_path, self.label, params[0], params[1])
        self.worker.finished_ok.connect(self._on_segment_done)
        self.worker.failed.connect(self._on_segment_failed)
        self.worker.start()

    def _on_reset(self):
        if self.worker:
            return
        self.stop_playback()
        self.history.checkpoint()
        self._last_applied = None   # auto state - let the next threshold apply
        self._set_busy(True)
        self.status.setText("Resetting to automatic detection…")
        self.worker = ResetWorker(self.wav_path, self.label)
        self.worker.finished_ok.connect(self._on_segment_done)
        self.worker.failed.connect(self._on_segment_failed)
        self.worker.start()

    def _on_delete_range(self):
        sel = self.preview.current_selection()
        if not sel or sel[1] - sel[0] <= 0:
            self.status.setText("Select a range on the waveform first.")
            return
        # No confirm dialog - this is undoable (Ctrl+Z). Confirms are reserved
        # for non-undoable deletes (whole recording / sound / model).
        if self.worker:
            return
        self.stop_playback()
        self.history.checkpoint()
        self._set_busy(True)
        self.status.setText("Trimming & re-detecting…")
        self.worker = TrimWorker(self.wav_path, self.label, [sel])
        self.worker.finished_ok.connect(self._on_trim_done)
        self.worker.failed.connect(self._on_segment_failed)
        self.worker.start()

    def _on_segment_done(self, srt_path):
        self._finish_worker()
        self.preview.load(self.wav_path, srt_path)
        self._audio = None
        self._sync_slider_from_file()
        self.app_state.recordings_changed.emit()
        self._set_busy(False)
        self._update_undo_buttons()
        self.status.setText("Detection updated.")

    def _on_trim_done(self, srt_path):
        self._finish_worker()
        self._last_applied = None   # the audio changed under the threshold
        self.preview.load(self.wav_path, srt_path)
        self.preview.fit_full()
        self._audio = None
        self.app_state.recordings_changed.emit()
        self._set_busy(False)
        self._update_undo_buttons()
        self.status.setText("Audio trimmed and re-detected.")

    def _on_segment_failed(self, message):
        self._finish_worker()
        self._last_applied = None   # let the user retry the same threshold
        # The op didn't change anything, so drop the checkpoint we took for it.
        self.history.discard_last_checkpoint()
        self._set_busy(False)
        self._update_undo_buttons()
        self.status.setText("")
        QMessageBox.warning(self, "Couldn't update detection", message)

    # ---- undo / redo ---------------------------------------------------

    def _update_undo_buttons(self):
        self.undo_btn.setEnabled(self.history.can_undo())
        self.redo_btn.setEnabled(self.history.can_redo())
        self._update_title()

    # ---- save / dirty state --------------------------------------------

    def _update_title(self):
        star = " *" if self.history.is_dirty() else ""
        self.title.setText(f"Edit:  {self.label}  /  {getattr(self, '_base', '')}{star}")
        self.save_btn.setEnabled(self.history.is_dirty() and not self.worker)

    def _on_save(self):
        if self.worker or not self.history.is_dirty():
            return
        self.history.commit_baseline()
        self._update_undo_buttons()
        self.status.setText("Saved.")

    def _deselect_or_start(self):
        """D/Esc: drop the selection if there is one, else jump to the start."""
        if self.preview.current_selection() is not None:
            self.preview.clear_selection()
        else:
            self._on_seek(0.0)

    def _toggle_normalize(self):
        self._norm = not self._norm
        self.preview.set_normalized(self._norm)
        self.status.setText("Normalized." if self._norm else "Normalize off.")

    def _toggle_spectrum(self):
        self._mode = "spectrogram" if self._mode == "waveform" else "waveform"
        self.preview.set_mode(self._mode)
        self.status.setText("Spectrogram." if self._mode == "spectrogram" else "Waveform.")

    def keybinding_hint(self):
        return ("Space play  ·  click to seek  ·  X delete selection  ·  "
                "F fit (selection/all)  ·  A normalize  ·  S spectrum  ·  "
                "D deselect/start  ·  Ctrl+Z/Y undo  ·  Ctrl+S save  ·  "
                "unsaved until Save")

    def _on_undo(self):
        if self.worker or not self.history.can_undo():
            return
        self.stop_playback()
        self.history.undo()
        self._reload_after_history("Undone.")

    def _on_redo(self):
        if self.worker or not self.history.can_redo():
            return
        self.stop_playback()
        self.history.redo()
        self._reload_after_history("Redone.")

    def _reload_after_history(self, status):
        self._last_applied = None   # restored state may differ from the slider
        self.preview.load(self.wav_path, self._current_srt())
        self.preview.fit_full()
        self._audio = None
        self.app_state.recordings_changed.emit()
        # Resync the threshold slider with whatever override the restored state has.
        existing = read_min_dbfs(self.wav_path)
        self.slider.blockSignals(True)
        self.slider.setValue(int(existing) if existing is not None else -40)
        self.slider.blockSignals(False)
        self._update_slider_label()
        self._update_undo_buttons()
        self.status.setText(status)

    # ---- playback ------------------------------------------------------

    def _ensure_audio(self):
        if self._audio is not None:
            return
        samples, sr = self.preview.playback_audio()
        self._audio = samples
        self._sr = sr
        self._duration = self.preview.duration()

    def _on_seek(self, seconds):
        """Clicking the waveform moves the playhead; play starts from there."""
        self._ensure_audio()
        self._play_from = max(0.0, min(seconds, self._duration))
        self.preview.set_playhead(self._play_from)
        if self._playing:
            self._play()

    def _toggle_play(self):
        if self._playing:
            self.stop_playback()
        else:
            self._play()

    def _play(self):
        self._ensure_audio()
        if self._audio is None or not self._sr:
            return
        sel = self.preview.current_selection()
        if sel and sel[1] - sel[0] > 0:
            # A selection plays as a range…
            self._play_from, self._stop_at = sel
        else:
            # …otherwise play from where the playhead was clicked, to the end.
            self._stop_at = None
            self._play_from = max(0.0, min(self._play_from, self._duration))
        start = int(self._play_from * self._sr)
        end = int(self._stop_at * self._sr) if self._stop_at else len(self._audio)
        self._latency = playback.play(self._audio[start:end], self._sr)
        self._playing = True
        self.play_btn.setText("■ Stop")
        self.preview.set_playhead(self._play_from)
        self._clock.restart()
        self._timer.start()

    def stop_playback(self):
        if self._playing:
            playback.stop()
        self._playing = False
        self._timer.stop()
        self.play_btn.setText("▶ Play")

    def _heard_position(self):
        """Where playback has actually reached, in seconds. The clock starts
        when play() is called but the audio only leaves the device a buffer
        later, so without subtracting that the playhead sits ahead of what
        you're hearing - and points past the blip you were auditioning."""
        return self._play_from + max(0.0, self._clock.elapsed() / 1000.0 - self._latency)

    def _tick(self):
        pos = self._heard_position()
        limit = self._stop_at if self._stop_at is not None else self._duration
        if pos >= limit:
            self.preview.set_playhead(limit)
            self.stop_playback()
            return
        self.preview.set_playhead(pos)

    # ---- navigation ----------------------------------------------------

    def _on_back(self):
        if self.worker:
            return  # don't leave mid-detect
        self.stop_playback()
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
            else:  # Discard - restore the recording to its last-saved state.
                self.history.revert_to_baseline()
                self.app_state.recordings_changed.emit()
        self.history.clear()   # undo history is per-editing-session
        self.done.emit(self.label or "")

    def refresh_theme(self):
        pass
