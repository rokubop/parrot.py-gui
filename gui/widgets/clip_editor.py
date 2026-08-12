"""A clip preview plus every control that acts on it.

The recording view and the edit view do the same things to a saved wav - play
it, zoom it, select part of it, delete that part, undo - and used to do them
with two near-identical copies of the same ~130 lines. Both embed one of these
instead, so a fix lands in both and the keyboard and the buttons can never
disagree about what a key does.

What stays with the host: how a clip is found (``srt_provider``), what the words
for it are (``noun``), its own buttons, and which shortcuts are live in which
state - the recording view answers Space differently while it is recording.
"""
from PyQt6.QtCore import Qt, QTimer, QElapsedTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QFrame, QMessageBox
)

from gui import components, icons, theme
from gui.services import levels, playback
from gui.widgets.audio_preview import AudioPreviewWidget, view_after_cut
from gui.widgets.level_lane import LevelLane
from gui.workers.segment_worker import TrimWorker


def _separator():
    """A hairline between control groups, so a row of eight buttons reads as
    transport / selection / view / history rather than eight of one thing."""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.VLine)
    line.setFixedWidth(1)
    line.setStyleSheet(f"background: {theme.colors()['border']}; border: none;")
    return line


class ClipEditorWidget(QWidget):
    """Preview + controls for one saved wav. ``open`` binds a clip."""

    status = pyqtSignal(str)            # a line for the host's status/hint label
    edited = pyqtSignal()               # the clip's files changed on disk
    history_changed = pyqtSignal()      # undo/redo availability moved

    def __init__(self, history, noun="clip", show_levels=False, parent=None):
        super().__init__(parent)
        self.history = history
        self.noun = noun
        # Asked for by screens that own a threshold control. Elsewhere it is a
        # strip of chart nothing on the page can act on.
        self.lane = None
        self._show_levels = show_levels
        # Where to look up the clip's srt after an undo restores it. The two
        # views resolve it differently, so the host supplies it.
        self.srt_provider = lambda: None
        # What to suggest when the whole clip is selected for deletion; only the
        # host knows which of its own controls does that job.
        self.whole_clip_hint = ""

        self.wav_path = None
        self.label = None
        self.worker = None

        # view toggles (mirror AudioPreviewWidget defaults)
        self._norm = False
        self._mode = "waveform"

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

        # the visible window when a cut started, and what the cut removed
        self._view_before_cut = None
        self._cut_applied = False
        self._cut_note = ""

        self._setup_ui()

    # ---- ui ------------------------------------------------------------

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.preview = AudioPreviewWidget()
        self.preview.seeked.connect(self.on_seek)
        root.addWidget(self.preview, 1)

        if self._show_levels:
            self.lane = LevelLane()
            self.lane.link_x(self.preview.plot)
            root.addWidget(self.lane)

        row = QHBoxLayout()
        row.setSpacing(6)

        def button(text, slot, tip, checkable=False):
            btn = QPushButton(text)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setToolTip(tip)
            btn.setCheckable(checkable)
            btn.clicked.connect(slot)
            row.addWidget(btn)
            return btn

        # transport
        self.play_btn = button("Play", self.toggle_play,
                               "Play, or play the selection - Space")
        self.play_btn.setIcon(icons.play())
        # Pinned, or the row shifts sideways the moment playback starts.
        self._play_labels = ("Play", "Stop")
        components.lock_width(self.play_btn, *self._play_labels, floor=110)
        self.fit_btn = button("Fit", self.fit,
                              f"Zoom to the selection, or the whole {self.noun} - F")
        row.addWidget(_separator())

        # editing
        self._delete_tip = "Remove the selected range - Del"
        self.delete_btn = button("Delete selection", self.delete_selection,
                                 self._delete_tip)
        row.addWidget(_separator())

        # view. Checkable, because these are states: without a pressed button
        # nothing on screen says why the waveform looks the way it does.
        self.norm_btn = button("Normalize", self.toggle_normalize,
                               "Scale the waveform to its loudest peak - A",
                               checkable=True)
        self.spec_btn = button("Spectrum", self.toggle_spectrum,
                               "Show frequencies instead of the waveform - S",
                               checkable=True)
        row.addWidget(_separator())

        # history
        self.undo_btn = button("Undo", self.undo, "Undo the last edit - Ctrl+Z")
        self.redo_btn = button("Redo", self.redo, "Redo - Ctrl+Y")

        row.addStretch()
        root.addLayout(row)

    # ---- binding a clip -------------------------------------------------

    def open(self, wav_path, srt_path, label, reset_view=True):
        """Show a clip. ``reset_view`` False keeps the current zoom."""
        self.stop_playback()
        self.wav_path = wav_path
        self.label = label
        self._cut_note = ""
        self._view_before_cut = None
        self._audio = None
        self._play_from = 0.0
        self._stop_at = None
        view = None if reset_view else self.preview.view_range()
        self.preview.load(wav_path, srt_path, view=view)
        self.refresh_levels()
        if reset_view:
            self.preview.fit_full()
        self.preview.set_busy(False)
        self.refresh_history_buttons()

    def refresh_levels(self):
        """Recompute the lane from disk. Cheap next to a re-detect, and a trim
        or an undo changes the audio under it."""
        if self.lane is None:
            return
        if not self.wav_path:
            self.lane.clear()
            return
        self.lane.set_levels(*levels.frame_dbfs(self.wav_path))

    def set_regions(self, srt_path):
        """Refresh only the detection overlay."""
        self.preview.load_regions(srt_path)

    def clear(self):
        self.stop_playback()
        self.wav_path = None
        self._audio = None
        self._cut_note = ""
        self.preview.set_busy(False)
        if self.lane is not None:
            self.lane.clear()

    # ---- enabling -------------------------------------------------------

    def set_busy(self, busy, message=""):
        """Host work that reprocesses the clip (re-detection) uses this too, so
        the plot is inert for the whole of it and not just for our own edits."""
        self.preview.set_busy(busy, message)
        if self.lane is not None:
            self.lane.setEnabled(not busy)
        for btn in (self.play_btn, self.fit_btn, self.norm_btn, self.spec_btn):
            btn.setEnabled(not busy)
        self.delete_btn.setEnabled(not busy)
        if busy:
            self.undo_btn.setEnabled(False)
            self.redo_btn.setEnabled(False)
        else:
            self.refresh_history_buttons()

    def is_busy(self):
        return self.worker is not None

    # ---- view toggles ---------------------------------------------------

    def fit(self):
        self.preview.toggle_fit()

    def deselect_or_start(self):
        """D/Esc: drop the selection if there is one, else jump to the start."""
        if self.preview.current_selection() is not None:
            self.preview.clear_selection()
        else:
            self.on_seek(0.0)

    def toggle_normalize(self):
        self._norm = not self._norm
        self.norm_btn.setChecked(self._norm)
        self.preview.set_normalized(self._norm)

    def toggle_spectrum(self):
        self._mode = "spectrogram" if self._mode == "waveform" else "waveform"
        self.spec_btn.setChecked(self._mode == "spectrogram")
        self.preview.set_mode(self._mode)

    def keybinding_hint(self):
        return ("Space play  ·  click to seek  ·  X delete selection  ·  "
                "F fit (selection/all)  ·  A normalize  ·  S spectrum  ·  "
                "D deselect/start  ·  Ctrl+Z/Y undo")

    # ---- delete ---------------------------------------------------------

    def delete_selection(self):
        if self.worker or not self.wav_path:
            return
        sel = self.preview.current_selection()
        if not sel or sel[1] - sel[0] <= 0:
            self.status.emit(f"Select part of the {self.noun} first, then Delete.")
            return
        # A clip trimmed to nothing is a wav with no frames, which every view
        # downstream has to special-case. A drag across the whole thing still
        # reaches it (the selection auto-scrolls), so it's refused here.
        if sel[0] <= 0.0 and sel[1] >= self.preview.duration() - 1e-3:
            self.status.emit(f"That's the whole {self.noun}. "
                             f"{self.whole_clip_hint}".strip())
            return
        # No confirm dialog - this is undoable (Ctrl+Z). Confirms are reserved
        # for non-undoable deletes (whole recording / sound / model).
        self.stop_playback()
        self.history.checkpoint()
        # Kept until the cut lands so the view can be mapped through it, and so a
        # failed trim leaves the selection where it was to retry.
        self._view_before_cut = self.preview.view_range()
        self._cut_applied = False
        self.preview.mark_pending_cut(*sel)
        self.set_busy(True, "Deleting…")
        self.status.emit("Deleting…")
        self.worker = TrimWorker(self.wav_path, self.label, [sel])
        self.worker.trimmed.connect(self._on_trim_audio)
        self.worker.finished_ok.connect(self._on_trim_done)
        self.worker.failed.connect(self._on_trim_failed)
        self.worker.start()

    def _finish_worker(self):
        """Tear a finished thread down safely. The result signal fires before
        run() returns, so wait() before dropping the reference or a
        still-running QThread gets deleted (a hard crash)."""
        w = self.worker
        self.worker = None
        if w is not None:
            w.wait()
            w.deleteLater()

    def _on_trim_audio(self, cut_start, removed, new_duration):
        """The wav is rewritten; detection is still running. Show the new audio
        now, at the same zoom, with the playhead parked on the seam. The overlay
        is dropped rather than left at offsets the cut has invalidated."""
        view = view_after_cut(self._view_before_cut or self.preview.view_range(),
                              cut_start, removed, new_duration)
        self.preview.load(self.wav_path, None, view=view)
        self.refresh_levels()                  # the audio under the lane changed
        self.set_busy(True, "Re-detecting…")   # load repositions the scrim
        self.preview.clear_selection()
        self.preview.flash_seam(cut_start)
        self.preview.set_playhead(cut_start)
        self._audio = None          # the samples changed under us
        self._play_from = cut_start
        self._stop_at = None
        self._cut_applied = True
        self._cut_note = (f"Removed {removed:.2f} s at {cut_start:.2f} s. "
                          f"{new_duration:.2f} s left.")
        self.status.emit(f"{self._cut_note}  Re-detecting…")

    def _on_trim_done(self, srt_path):
        self._finish_worker()
        self.preview.load_regions(srt_path)
        self.set_busy(False)
        self.edited.emit()
        self.history_changed.emit()
        self.status.emit(f"{self._cut_note}  Space to hear the join, "
                         f"Ctrl+Z to undo.")

    def _on_trim_failed(self, message, changed=False):
        """A trim can fail after audio is written: re-detection dies, or one mic
        file of several is done. Keep the checkpoint whenever anything was
        written, or Ctrl+Z stops reaching a change that happened."""
        self._finish_worker()
        if not self._cut_applied and not changed:
            self.history.discard_last_checkpoint()
        self.set_busy(False)
        self.history_changed.emit()
        if self._cut_applied or changed:
            self.edited.emit()
            self.status.emit(f"{self._cut_note}  Detection is out of date.")
            QMessageBox.warning(self, "Couldn't re-detect",
                                f"{message}\nThe audio was cut. Ctrl+Z undoes it.")
        else:
            self.status.emit("")
            QMessageBox.warning(self, "Couldn't delete", message)

    # ---- undo / redo ----------------------------------------------------

    def refresh_history_buttons(self):
        allowed = not self.worker
        self.undo_btn.setEnabled(allowed and self.history.can_undo())
        self.redo_btn.setEnabled(allowed and self.history.can_redo())

    def undo(self):
        if self.worker or not self.history.can_undo():
            return
        self.stop_playback()
        self.history.undo()
        self._reload_after_history("Undone.")

    def redo(self):
        if self.worker or not self.history.can_redo():
            return
        self.stop_playback()
        self.history.redo()
        self._reload_after_history("Redone.")

    def _reload_after_history(self, message):
        self._cut_note = ""         # no longer describes what is on screen
        # Hold the zoom: undoing a cut should show you the seam coming back, not
        # the whole clip again.
        self.preview.load(self.wav_path, self.srt_provider(),
                          view=self.preview.view_range())
        self.refresh_levels()
        self._audio = None
        self.edited.emit()
        self.refresh_history_buttons()
        self.history_changed.emit()
        self.status.emit(message)

    # ---- playback -------------------------------------------------------

    def _ensure_audio(self):
        if self._audio is not None:
            return
        samples, sr = self.preview.playback_audio()
        self._audio = samples
        self._sr = sr
        self._duration = self.preview.duration()

    def on_seek(self, seconds):
        """Clicking the waveform moves the playhead; play starts from there."""
        self._ensure_audio()
        self._play_from = max(0.0, min(seconds, self._duration))
        self.preview.set_playhead(self._play_from)
        if self._playing:
            self.play()

    def toggle_play(self):
        if self.worker:
            return      # the samples are being rewritten under us
        if self._playing:
            self.stop_playback()
        else:
            self.play()

    def play(self):
        self._ensure_audio()
        if self._audio is None or not self._sr:
            return
        sel = self.preview.current_selection()
        if sel and sel[1] - sel[0] > 0:
            self._play_from, self._stop_at = sel
        else:
            self._stop_at = None
            self._play_from = max(0.0, min(self._play_from, self._duration))
        start = int(self._play_from * self._sr)
        end = int(self._stop_at * self._sr) if self._stop_at else len(self._audio)
        self._latency = playback.play(self._audio[start:end], self._sr)
        self._playing = True
        self.play_btn.setText(self._play_labels[1])
        self.play_btn.setIcon(icons.stop())
        self.preview.set_playhead(self._play_from)
        self._clock.restart()
        self._timer.start()

    def stop_playback(self):
        if self._playing:
            playback.stop()
        self._playing = False
        self._timer.stop()
        self.play_btn.setText(self._play_labels[0])
        self.play_btn.setIcon(icons.play())

    def _heard_position(self):
        """Where playback has actually reached, in seconds. Audio leaves the
        device a buffer after play(), so subtract that latency or the playhead
        runs ahead of what you're hearing."""
        return self._play_from + max(0.0, self._clock.elapsed() / 1000.0 - self._latency)

    def _tick(self):
        pos = self._heard_position()
        limit = self._stop_at if self._stop_at is not None else self._duration
        if pos >= limit:
            self.preview.set_playhead(limit)
            self.stop_playback()
            return
        self.preview.set_playhead(pos)

    def refresh_theme(self):
        """Icons take their colour from the theme, and a new font changes the
        width the label needs, so both are rebuilt."""
        self.play_btn.setIcon(icons.stop() if self._playing else icons.play())
        components.lock_width(self.play_btn, *self._play_labels, floor=110)

    def cleanup(self):
        self.stop_playback()
        # Unlink first, or pyqtgraph paints a ViewBox that has already gone.
        if self.lane is not None:
            self.lane.cleanup()
        self.preview.cleanup()
