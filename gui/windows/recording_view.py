"""Dedicated recording view — a record/review/edit loop.

The flow the screen supports:
  pick mic(s) -> Record -> make sounds -> Pause (space) -> scrub & play back the
  take -> drag-select a bad part and Delete it -> Resume to keep recording ->
  ... -> Done.

How it works without editing a live stream: a "take" is a single growing WAV
file. Each Record->Pause captures a *segment*; the first segment becomes the
take, later segments are appended onto it (AppendWorker). While paused you're
looking at the whole take in the interactive preview, so play/scrub/select and
Delete (TrimWorker) all operate on a static file — no risky mid-stream splicing.
Resume records the next segment. The take file lives in the sound from the first
segment on, so it's always saved.
"""
import time
import sounddevice as sd
from PyQt6.QtCore import Qt, QElapsedTimer, QTimer, pyqtSignal
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QComboBox,
    QLineEdit, QGroupBox, QFormLayout, QMessageBox
)

from config.config import INPUT_DEVICE_INDEX
from gui import theme
from gui.widgets.waveform import WaveformWidget
from gui.widgets.audio_preview import AudioPreviewWidget
from gui.workers.audio_worker import AudioWorker
from gui.workers.segment_worker import AppendWorker, TrimWorker
from gui.services import library_ops, strategies
from lib.srt import ms_to_srt_timestring
from lib.print_status import get_quantity_rating


def _quality_from_snr(snr, ms_recorded):
    """Mirror lib/print_status quality bands (needs a few seconds of audio)."""
    if ms_recorded <= 10000:
        return "—", theme.colors()["text_dim"]
    bands = [(25, "Excellent", "#41d97f"), (20, "Great", "#41d97f"),
             (15, "Good", "#5ac8e0"), (10, "Average", "#e0b020"),
             (7, "Poor", "#e0853a")]
    for threshold, name, color in bands:
        if snr >= threshold:
            return name, color
    return "Unusable", "#e05a5a"


class RecordingView(QWidget):
    done = pyqtSignal(str)   # left the view; arg = label to select (may be "")

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.worker = None              # AudioWorker (recording a segment)
        self._seg_worker = None         # Append/Trim worker (re-detect)
        self._label = None
        self._new_mode = False
        self._take_wav = None           # the growing take file, or None
        self._take_srt = None
        self._pending_action = None     # 'pause' | 'done' while a segment stops
        self._state = "idle"
        self._last_status_draw = 0.0

        # playback (review mode)
        self._audio = None
        self._sr = None
        self._duration = 0.0
        self._playing = False
        self._play_from = 0.0
        self._stop_at = None
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(16)
        self._play_timer.timeout.connect(self._tick)
        self._clock = QElapsedTimer()

        self._setup_ui()

    # ---- entry points (called by MainWindow) --------------------------

    def start_for(self, label):
        """Add a recording to an existing sound (as a new take)."""
        self._new_mode = False
        self._label = label
        self.name_row.setVisible(False)
        self.title.setText(f"Record:  {label}")
        self._reset(take=None)

    def start_new(self):
        """Create a brand-new sound by recording it."""
        self._new_mode = True
        self._label = None
        self.name_row.setVisible(True)
        self.name_input.clear()
        self.title.setText("New sound")
        self._reset(take=None)

    def start_append(self, target_wav):
        """Add onto an existing recording: open it in review, ready to Resume."""
        self._new_mode = False
        self._label = library_ops.recording_label(target_wav)
        base = library_ops.recording_base(target_wav)
        self.name_row.setVisible(False)
        self.title.setText(f"Add to:  {self._label} / {base}")
        self._reset(take=target_wav)

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
        self.title = QLabel("Record")
        self.title.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {theme.colors()['text_bright']};")
        top.addWidget(self.title)
        top.addStretch()
        self.state_label = QLabel("")
        self.state_label.setStyleSheet("font-weight: bold;")
        top.addWidget(self.state_label)
        root.addLayout(top)

        # New-sound name row (hidden otherwise)
        self.name_row = QWidget()
        name_layout = QHBoxLayout(self.name_row)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.addWidget(QLabel("Sound name:"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. pop")
        name_layout.addWidget(self.name_input)
        name_layout.addStretch()
        root.addWidget(self.name_row)

        # Device + strategy
        opts = QHBoxLayout()
        opts.addWidget(QLabel("Microphone:"))
        self.device_combo = QComboBox()
        self._populate_devices()
        opts.addWidget(self.device_combo, 2)
        opts.addSpacing(12)
        opts.addWidget(QLabel("Strategy:"))
        self.strategy_combo = QComboBox()
        for lbl in strategies.labels():
            self.strategy_combo.addItem(lbl)
        si = self.strategy_combo.findText(strategies.default_label())
        if si >= 0:
            self.strategy_combo.setCurrentIndex(si)
        self.strategy_combo.setToolTip("How detection segments your sound")
        opts.addWidget(self.strategy_combo, 1)
        root.addLayout(opts)

        # Center: live monitor (recording) OR interactive preview (review)
        center = QHBoxLayout()
        left = QVBoxLayout()
        self.waveform = WaveformWidget()
        left.addWidget(self.waveform)
        self.preview = AudioPreviewWidget()
        self.preview.setVisible(False)
        self.preview.seeked.connect(self._on_seek)
        left.addWidget(self.preview)
        center.addLayout(left, 3)
        center.addWidget(self._build_status_panel(), 1)
        root.addLayout(center, 1)

        # Controls
        controls = QHBoxLayout()
        self.record_btn = QPushButton("● Record")
        self.record_btn.setMinimumWidth(150)
        self.record_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.record_btn.clicked.connect(self._on_primary)
        controls.addWidget(self.record_btn)
        self.done_btn = QPushButton("Done")
        self.done_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.done_btn.setToolTip("Finish — the take is already saved to the sound")
        self.done_btn.clicked.connect(self._on_done)
        controls.addWidget(self.done_btn)

        controls.addSpacing(20)
        self.play_btn = QPushButton("▶ Play")
        self.play_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.play_btn.setToolTip("Play the take, or the selection — Space")
        self.play_btn.clicked.connect(self._toggle_play)
        controls.addWidget(self.play_btn)
        self.delete_sel_btn = QPushButton("Delete selection")
        self.delete_sel_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.delete_sel_btn.setToolTip("Drag-select a range on the take, then "
                                       "remove it — Delete")
        self.delete_sel_btn.clicked.connect(self._on_delete_selection)
        controls.addWidget(self.delete_sel_btn)

        controls.addStretch()
        self.hint = QLabel("")
        self.hint.setStyleSheet(f"color: {theme.colors()['text_dim']};")
        controls.addWidget(self.hint)
        root.addLayout(controls)

        # Space = pause while recording / play-pause while reviewing.
        # Delete = delete the current selection while reviewing.
        sp = QShortcut(QKeySequence("Space"), self)
        sp.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sp.activated.connect(self._on_space)
        for k in ("Del", "Backspace"):
            sc = QShortcut(QKeySequence(k), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(self._on_delete_selection)

        self._set_state("idle")

    def _build_status_panel(self):
        group = QGroupBox("Live status")
        form = QFormLayout(group)
        form.setSpacing(8)
        dim = theme.colors()["text_dim"]

        def value_label():
            lbl = QLabel("—")
            lbl.setStyleSheet(
                f"color: {theme.colors()['text_bright']}; font-weight: bold;")
            return lbl

        self.v_time = value_label()
        self.v_quality = value_label()
        self.v_dbfs = value_label()
        self.v_noise = value_label()
        self.v_snr = value_label()
        self.v_detected = value_label()
        self.v_quantity = value_label()
        self.v_type = value_label()
        for caption, widget in (("Recorded", self.v_time),
                                ("Sound quality", self.v_quality),
                                ("Level (dBFS)", self.v_dbfs),
                                ("Noise floor", self.v_noise),
                                ("SNR", self.v_snr),
                                ("Detected sound", self.v_detected),
                                ("Data quantity", self.v_quantity),
                                ("Type", self.v_type)):
            cap = QLabel(caption + ":")
            cap.setStyleSheet(f"color: {dim};")
            form.addRow(cap, widget)
        group.setMaximumWidth(280)
        return group

    def _populate_devices(self):
        self.device_combo.clear()
        try:
            for i, dev in enumerate(sd.query_devices()):
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

    def _reset(self, take):
        self.stop_playback()
        self._take_wav = take
        self._take_srt = self._srt_for(take) if take else None
        self._pending_action = None
        self._audio = None
        self.name_input.setEnabled(take is None and self._new_mode)
        for w in (self.v_time, self.v_quality, self.v_dbfs, self.v_noise,
                  self.v_snr, self.v_detected, self.v_quantity, self.v_type):
            w.setText("—")
        if take:
            self._load_preview()
            self._set_state("review")
            self.hint.setText("Play to review, drag-select to delete, "
                              "Resume to add more.")
        else:
            self.waveform.clear_display()
            self._set_state("idle")
            self.hint.setText("")

    def _srt_for(self, wav_path):
        if not wav_path:
            return None
        for rec in self.app_state.get_recordings_for_label(self._label):
            if rec["wav_path"] == wav_path:
                return rec["srt_path"]
        return None

    # ---- state ---------------------------------------------------------

    # state -> (primary text, primary color, indicator text, indicator color,
    #           live trace color)
    _STATES = {
        "idle":      ("● Record", "#c0463f", "● Ready",     "#8b939d", (90, 230, 150)),
        "recording": ("❚❚ Pause", None,      "● Recording", "#e0534f", (224, 83, 79)),
        "review":    ("● Resume", "#3a8f55", "❚❚ Paused",  "#e0b020", (224, 176, 32)),
    }

    def _set_state(self, state):
        self._state = state
        text, color, ind_text, ind_color, trace = self._STATES[state]
        self.record_btn.setText(text)
        self.record_btn.setStyleSheet(
            (f"QPushButton {{ background-color: {color}; color: #ffffff; "
             f"font-weight: bold; border: none; }}"
             f" QPushButton:hover {{ background-color: {color}; }}") if color else "")
        self.state_label.setText(ind_text)
        self.state_label.setStyleSheet(f"color: {ind_color}; font-weight: bold;")
        self.waveform.set_trace_color(trace)

        recording = state == "recording"
        reviewing = state == "review"
        self.waveform.setVisible(not reviewing)
        self.preview.setVisible(reviewing)
        self.done_btn.setEnabled(state != "idle")
        self.play_btn.setVisible(reviewing)
        self.delete_sel_btn.setVisible(reviewing)
        # Lock device/strategy/name once a take exists.
        locked = state != "idle"
        self.device_combo.setEnabled(not locked)
        self.strategy_combo.setEnabled(not locked)
        if recording:
            self.name_input.setEnabled(False)

    # ---- recording lifecycle ------------------------------------------

    def _resolve_label(self):
        if self._new_mode and self._take_wav is None:
            try:
                label = library_ops.sanitize_name(self.name_input.text(),
                                                  kind="sound name")
            except library_ops.LibraryOpError as exc:
                QMessageBox.warning(self, "Name needed", str(exc))
                return None
            if not library_ops.sound_exists(label):
                try:
                    self.app_state.create_sound(label)
                except library_ops.LibraryOpError as exc:
                    QMessageBox.warning(self, "Couldn't create sound", str(exc))
                    return None
            return label
        return self._label

    def _on_primary(self):
        if self._state in ("idle", "review"):
            self._start_segment()
        elif self._state == "recording":
            self._pause()

    def _start_segment(self):
        label = self._resolve_label()
        if not label:
            return
        self._label = label
        mic = self.device_combo.currentData()
        strategy = strategies.strategy_for_label(self.strategy_combo.currentText())

        self.stop_playback()
        self.waveform.clear_display()

        self.worker = AudioWorker(label, mic, strategy)
        self.worker.frame_recorded.connect(self.waveform.append_live_data)
        self.worker.status_updated.connect(self._on_status)
        self.worker.recording_finished.connect(self._on_segment_finished)
        self.worker.start()

        self._set_state("recording")
        self.hint.setText("Recording… Space (or Pause) to stop and review.")

    def _pause(self):
        self._stop_segment("pause")

    def _on_done(self):
        if self._state == "recording":
            self._stop_segment("done")
        else:
            self._leave()

    def _stop_segment(self, action):
        if not self.worker:
            return
        self._pending_action = action
        self.record_btn.setEnabled(False)
        self.done_btn.setEnabled(False)
        self.hint.setText("Finalizing…")
        self.worker.request_stop()

    def _on_segment_finished(self, seg_wav, seg_srt):
        self.worker = None
        if self._take_wav is None:
            # First segment becomes the take.
            self._take_wav = seg_wav
            self._take_srt = seg_srt
            self.app_state.recordings_changed.emit()
            self._after_segment()
        else:
            # Append this segment onto the existing take, then re-detect.
            self.hint.setText("Stitching the take together…")
            self._seg_worker = AppendWorker(self._take_wav, seg_wav, self._label)
            self._seg_worker.finished_ok.connect(
                lambda srt, src=seg_wav: self._on_appended(src, srt))
            self._seg_worker.failed.connect(
                lambda msg, src=seg_wav, srt=seg_srt: self._on_append_failed(msg, src, srt))
            self._seg_worker.start()

    def _on_appended(self, source_wav, srt_path):
        self._seg_worker = None
        try:
            library_ops.delete_recording(source_wav)
        except library_ops.LibraryOpError:
            pass
        self._take_srt = srt_path
        self.app_state.recordings_changed.emit()
        self._after_segment()

    def _on_append_failed(self, msg, source_wav, source_srt):
        self._seg_worker = None
        # Keep what we had; the stray segment stays as its own clip.
        self.app_state.recordings_changed.emit()
        QMessageBox.warning(self, "Couldn't stitch the take",
                            f"{msg}\nThe last segment was kept as a separate "
                            f"recording.")
        self._after_segment()

    def _after_segment(self):
        action, self._pending_action = self._pending_action, None
        self.record_btn.setEnabled(True)
        self.done_btn.setEnabled(True)
        if action == "done":
            self._leave()
            return
        self._take_srt = self._srt_for(self._take_wav) or self._take_srt
        self._load_preview()
        self._set_state("review")
        self.hint.setText("Play to review, drag-select to delete, "
                          "Resume to add more, Done to finish.")

    # ---- review: preview + playback + delete ---------------------------

    def _load_preview(self):
        self._audio = None
        try:
            self.preview.load(self._take_wav, self._take_srt)
            self.preview.fit_full()
        except Exception:
            pass

    def _on_delete_selection(self):
        if self._state != "review" or self._seg_worker:
            return
        sel = self.preview.current_selection()
        if not sel or sel[1] - sel[0] <= 0:
            self.hint.setText("Drag-select a part of the take first, then Delete.")
            return
        self.stop_playback()
        self.hint.setText("Deleting & re-detecting…")
        self.delete_sel_btn.setEnabled(False)
        self.record_btn.setEnabled(False)
        self._seg_worker = TrimWorker(self._take_wav, self._label, [sel])
        self._seg_worker.finished_ok.connect(self._on_trimmed)
        self._seg_worker.failed.connect(self._on_trim_failed)
        self._seg_worker.start()

    def _on_trimmed(self, srt_path):
        self._seg_worker = None
        self._take_srt = srt_path
        self.app_state.recordings_changed.emit()
        self._load_preview()
        self.delete_sel_btn.setEnabled(True)
        self.record_btn.setEnabled(True)
        self.hint.setText("Deleted. Resume to add more, or Done.")

    def _on_trim_failed(self, msg):
        self._seg_worker = None
        self.delete_sel_btn.setEnabled(True)
        self.record_btn.setEnabled(True)
        QMessageBox.warning(self, "Couldn't delete", msg)

    def _on_seek(self, seconds):
        self._ensure_audio()
        self._play_from = max(0.0, min(seconds, self._duration))
        self.preview.set_playhead(self._play_from)
        if self._playing:
            self._play()

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
            self._stop_at = None
        start = int(self._play_from * self._sr)
        end = int(self._stop_at * self._sr) if self._stop_at else len(self._audio)
        sd.stop()
        sd.play(self._audio[start:end], self._sr)
        self._playing = True
        self.play_btn.setText("■ Stop")
        self.preview.set_playhead(self._play_from)
        self._clock.restart()
        self._play_timer.start()

    def stop_playback(self):
        if self._playing:
            sd.stop()
        self._playing = False
        self._play_timer.stop()
        self.play_btn.setText("▶ Play")

    def _tick(self):
        pos = self._play_from + self._clock.elapsed() / 1000.0
        limit = self._stop_at if self._stop_at is not None else self._duration
        if pos >= limit:
            self.preview.set_playhead(limit)
            self.stop_playback()
            return
        self.preview.set_playhead(pos)

    def _on_space(self):
        if self._state == "recording":
            self._pause()
        elif self._state == "review":
            self._toggle_play()

    # ---- live status ---------------------------------------------------

    def _on_status(self, state):
        now = time.monotonic()
        if now - self._last_status_draw < 0.12:
            return
        self._last_status_draw = now

        self.v_time.setText(ms_to_srt_timestring(state.ms_recorded, False))
        quality, color = _quality_from_snr(state.expected_snr, state.ms_recorded)
        self.v_quality.setText(quality)
        self.v_quality.setStyleSheet(f"color: {color}; font-weight: bold;")
        if state.latest_dBFS <= -100:
            self.v_dbfs.setText("weak / muted?")
        else:
            self.v_dbfs.setText(f"{round(state.latest_dBFS)}")
        self.v_noise.setText(f"{round(state.expected_noise_floor)}")
        self.v_snr.setText(f"{round(state.expected_snr)}")

        if state.labels:
            lab = state.labels[0]
            detected = lab.ms_detected + lab.previous_detected
            self.v_detected.setText(ms_to_srt_timestring(detected, False))
            quantity, pct, nxt = get_quantity_rating(detected)
            tail = f" ({round(pct)}% → {nxt})" if nxt else ""
            self.v_quantity.setText(quantity + tail)
            self.v_type.setText((lab.duration_type or "determining…").lower())

    # ---- navigation ----------------------------------------------------

    def _on_back(self):
        self._leave()

    def _leave(self):
        self.stop_worker()
        self.stop_playback()
        self.done.emit(self._label or "")

    def stop_worker(self):
        if self.worker:
            # Don't let a queued segment-finish run our handler after we've left;
            # the recorder still writes the file, so the take is saved either way.
            try:
                self.worker.recording_finished.disconnect()
            except TypeError:
                pass
            self.worker.request_stop()
            self.worker.wait(2000)
            self.worker = None
            self.app_state.recordings_changed.emit()

    def refresh_theme(self):
        pass
