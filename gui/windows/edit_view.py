"""Edit a recording: redo detection (the blue overlay) and trim the waveform.

Two kinds of edit, both reflected immediately in the waveform + detection:

* Re-detect at a chosen threshold / duration type (writes a manual override and
  regenerates a ``.MANUAL.srt``), or reset back to automatic detection.
* Delete a selected time range from the source WAV (destructive, 2-step
  confirm), which rewrites the file and re-detects.

Includes lightweight playback (whole clip or the current selection) so you can
audition before and after an edit.
"""
import sounddevice as sd
from PyQt6.QtCore import Qt, QTimer, QElapsedTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QSlider, QComboBox,
    QGroupBox, QMessageBox
)

from gui import theme
from gui.widgets.audio_preview import AudioPreviewWidget
from gui.widgets.confirm_dialog import confirm_destructive
from gui.services import library_ops
from gui.workers.segment_worker import (
    ReSegmentWorker, ResetWorker, TrimWorker, read_min_dbfs,
)


class EditRecordingView(QWidget):
    done = pyqtSignal(str)   # closed; arg = label to reselect

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.wav_path = None
        self.label = None
        self.worker = None

        # playback
        self._audio = None
        self._sr = None
        self._duration = 0.0
        self._playing = False
        self._play_from = 0.0
        self._stop_at = None
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._clock = QElapsedTimer()

        self._setup_ui()

    # ---- entry ---------------------------------------------------------

    def start_for(self, wav_path):
        self.stop_playback()
        self.wav_path = wav_path
        self.label = library_ops.recording_label(wav_path)
        base = library_ops.recording_base(wav_path)
        self.title.setText(f"Edit:  {self.label}  /  {base}")
        srt = self._current_srt()
        self.preview.load(wav_path, srt)
        self.preview.fit_full()
        self._audio = None  # force re-decode on next play
        # Initialize the threshold slider from any existing override.
        existing = read_min_dbfs(wav_path)
        self.slider.blockSignals(True)
        self.slider.setValue(int(existing) if existing is not None else -40)
        self.slider.blockSignals(False)
        self._update_slider_label()
        self.duration_combo.setCurrentIndex(0)
        self._set_busy(False)
        self.status.setText("")

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
        root.addLayout(top)

        self.preview = AudioPreviewWidget()
        root.addWidget(self.preview, 1)

        # Playback row
        play_row = QHBoxLayout()
        self.play_btn = QPushButton("▶ Play")
        self.play_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.play_btn.clicked.connect(self._toggle_play)
        play_row.addWidget(self.play_btn)
        fit_btn = QPushButton("Fit")
        fit_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        fit_btn.clicked.connect(self.preview.fit)
        play_row.addWidget(fit_btn)
        hint = QLabel("Drag on the waveform to select a range — Play plays the "
                      "selection, Fit zooms to it.")
        hint.setStyleSheet(f"color: {theme.colors()['text_dim']};")
        play_row.addWidget(hint)
        play_row.addStretch()
        root.addLayout(play_row)

        # Detection (threshold) group
        det_group = QGroupBox("Detection (the blue overlay)")
        det = QHBoxLayout(det_group)
        det.addWidget(QLabel("Threshold:"))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(-96, 0)
        self.slider.setValue(-40)
        self.slider.setMinimumWidth(220)
        self.slider.valueChanged.connect(self._update_slider_label)
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
        self.apply_btn = QPushButton("Apply detection")
        self.apply_btn.clicked.connect(self._on_apply)
        det.addWidget(self.apply_btn)
        self.reset_btn = QPushButton("Reset to auto")
        self.reset_btn.clicked.connect(self._on_reset)
        det.addWidget(self.reset_btn)
        root.addWidget(det_group)

        # Trim group
        trim_group = QGroupBox("Edit audio")
        trim = QHBoxLayout(trim_group)
        self.delete_btn = QPushButton("Delete selected range")
        self.delete_btn.setToolTip("Remove the selected part of the waveform "
                                   "(also updates detection). Permanent.")
        self.delete_btn.clicked.connect(self._on_delete_range)
        trim.addWidget(self.delete_btn)
        trim_note = QLabel("Removes the selected audio from the recording and "
                           "re-detects. This can't be undone.")
        trim_note.setStyleSheet(f"color: {theme.colors()['text_dim']};")
        trim.addWidget(trim_note)
        trim.addStretch()
        root.addWidget(trim_group)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {theme.colors()['accent']};")
        root.addWidget(self.status)

    def _update_slider_label(self, *_):
        v = self.slider.value()
        self.slider_label.setText(f"{v} dBFS")

    # ---- detection edits ----------------------------------------------

    def _set_busy(self, busy):
        for b in (self.apply_btn, self.reset_btn, self.delete_btn):
            b.setEnabled(not busy)

    def _on_apply(self):
        if self.worker:
            return
        self.stop_playback()
        self._set_busy(True)
        self.status.setText("Re-detecting…")
        self.worker = ReSegmentWorker(
            self.wav_path, self.label, self.slider.value(),
            self.duration_combo.currentData())
        self.worker.finished_ok.connect(self._on_segment_done)
        self.worker.failed.connect(self._on_segment_failed)
        self.worker.start()

    def _on_reset(self):
        if self.worker:
            return
        self.stop_playback()
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
        start, end = sel
        if not confirm_destructive(
                self, title="Delete this part of the recording?",
                body=f"This permanently removes {end - start:.2f}s "
                     f"({start:.2f}s–{end:.2f}s) from the recording and "
                     f"re-detects the rest.",
                confirm_label="Delete audio"):
            return
        if self.worker:
            return
        self.stop_playback()
        self._set_busy(True)
        self.status.setText("Trimming & re-detecting…")
        self.worker = TrimWorker(self.wav_path, self.label, [(start, end)])
        self.worker.finished_ok.connect(self._on_trim_done)
        self.worker.failed.connect(self._on_segment_failed)
        self.worker.start()

    def _on_segment_done(self, srt_path):
        self.worker = None
        self.preview.load(self.wav_path, srt_path)
        self._audio = None
        self.app_state.recordings_changed.emit()
        self._set_busy(False)
        self.status.setText("Detection updated.")

    def _on_trim_done(self, srt_path):
        self.worker = None
        self.preview.load(self.wav_path, srt_path)
        self.preview.fit_full()
        self._audio = None
        self.app_state.recordings_changed.emit()
        self._set_busy(False)
        self.status.setText("Audio trimmed and re-detected.")

    def _on_segment_failed(self, message):
        self.worker = None
        self._set_busy(False)
        self.status.setText("")
        QMessageBox.warning(self, "Couldn't update detection", message)

    # ---- playback ------------------------------------------------------

    def _ensure_audio(self):
        if self._audio is not None:
            return
        samples, sr = self.preview.playback_audio()
        self._audio = samples
        self._sr = sr
        self._duration = self.preview.duration()

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
            self._play_from, self._stop_at = sel
        else:
            self._play_from, self._stop_at = 0.0, None
        start = int(self._play_from * self._sr)
        end = int(self._stop_at * self._sr) if self._stop_at else len(self._audio)
        sd.stop()
        sd.play(self._audio[start:end], self._sr)
        self._playing = True
        self.play_btn.setText("■ Stop")
        self.preview.set_playhead(self._play_from)
        self._clock.restart()
        self._timer.start()

    def stop_playback(self):
        if self._playing:
            sd.stop()
        self._playing = False
        self._timer.stop()
        self.play_btn.setText("▶ Play")

    def _tick(self):
        pos = self._play_from + self._clock.elapsed() / 1000.0
        limit = self._stop_at if self._stop_at is not None else self._duration
        if pos >= limit:
            self.preview.set_playhead(limit)
            self.stop_playback()
            return
        self.preview.set_playhead(pos)

    # ---- navigation ----------------------------------------------------

    def _on_back(self):
        self.stop_playback()
        self.done.emit(self.label or "")

    def refresh_theme(self):
        pass
