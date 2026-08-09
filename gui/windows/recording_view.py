"""Dedicated recording view - a record/review/edit loop.

A "take" is a single growing WAV: each Record->Pause captures a segment; the
first becomes the take, later ones are appended onto it (AppendWorker). While
paused the whole take shows in the interactive preview, so play/scrub/Delete
(TrimWorker) operate on a static file - no mid-stream splicing. The take lives
in the sound from the first segment on, so it's always saved.
"""
import time
import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QComboBox,
    QLineEdit, QGroupBox, QFormLayout, QMessageBox
)

from config.config import RATE
from gui import components, icons, theme
from gui.services import audio_devices
from gui.widgets.waveform import WaveformWidget
from gui.widgets.clip_editor import ClipEditorWidget
from gui.widgets.level_lane import LevelLane
from gui.widgets.confirm_dialog import confirm_destructive
from gui.widgets.mic_picker import MicPicker
from gui.workers.audio_worker import AudioWorker
from gui.workers.segment_worker import AppendWorker
from gui.services import library_ops, strategies
from gui.services.undo import UndoHistory
from lib.srt import ms_to_srt_timestring
from lib.print_status import get_quantity_rating


def _quality_from_snr(snr, ms_recorded):
    """Mirror lib/print_status quality bands (needs a few seconds of audio)."""
    if ms_recorded <= 10000:
        return "-", theme.colors()["text_dim"]
    t = theme.colors()
    # Ends from the theme, graded middle colors literal.
    bands = [(25, "Excellent", t["ok"]), (20, "Great", t["ok"]),
             (15, "Good", "#5ac8e0"), (10, "Average", "#e0b020"),
             (7, "Poor", "#e0853a")]
    for threshold, name, color in bands:
        if snr >= threshold:
            return name, color
    return "Unusable", t["bad"]


class RecordingView(QWidget):
    done = pyqtSignal(str)   # left the view; arg = label to select (may be "")
    keybindings_changed = pyqtSignal()  # state changed -> status bar should refresh

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.worker = None              # primary AudioWorker (drives the UI)
        self._seg_worker = None         # AppendWorker; the editor owns trims
        self.history = UndoHistory()
        self._label = None
        self._new_mode = False
        self._take_wav = None           # the growing take file, or None
        self._take_srt = None
        # multi-mic session: extras record in parallel, one take file per mic
        self._session_mics = None       # (primary, [extras]) locked at first segment
        self._extra_workers = []        # live AudioWorkers for extra mics
        self._extra_takes = {}          # mic index -> {"wav": ..., "srt": ...}
        self._extra_seg_workers = []    # AppendWorkers stitching extra takes
        self._pending_action = None     # 'pause' | 'done' while a segment stops
        self._state = "idle"
        self._last_status_draw = 0.0

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
        self.title.setStyleSheet(components.heading_style("title"))
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

        # Mic picker + strategy
        opts = QHBoxLayout()
        opts.addWidget(QLabel("Microphone:"))
        self.mic_picker = MicPicker()
        opts.addWidget(self.mic_picker)
        self.mic_note = QLabel("")
        self.mic_note.setStyleSheet(f"color: {theme.colors()['text_dim']};")
        opts.addWidget(self.mic_note, 2)
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

        # Teach beside the control: what the chosen strategy does, one line.
        self.strategy_desc = QLabel(strategies.description_for_label(
            self.strategy_combo.currentText()))
        self.strategy_desc.setWordWrap(True)
        self.strategy_desc.setStyleSheet(
            f"color: {theme.colors()['text_dim']}; ")
        self.strategy_combo.currentTextChanged.connect(
            lambda lbl: self.strategy_desc.setText(
                strategies.description_for_label(lbl)))
        root.addWidget(self.strategy_desc)

        # Center: live monitor (recording) OR interactive preview (review)
        center = QHBoxLayout()
        left = QVBoxLayout()
        self.waveform = WaveformWidget()
        left.addWidget(self.waveform)
        # Level in dBFS under the live trace, with the threshold on it. The
        # trace says what was recorded; this says what detection is going to
        # call sound, while there is still time to change it.
        self.level_lane = LevelLane()
        self.level_lane.link_x(self.waveform.get_plot_widget())
        self.level_lane.threshold_moved.connect(self._on_threshold_moved)
        left.addWidget(self.level_lane)
        left.addWidget(self._build_threshold_row())
        self.editor = ClipEditorWidget(self.history, noun="take")
        self.editor.setVisible(False)
        self.editor.srt_provider = lambda: self._srt_for(self._take_wav)
        self.editor.whole_clip_hint = "Start over deletes it."
        self.editor.status.connect(self.hint_text)
        self.editor.edited.connect(self._on_editor_edited)
        self.editor.history_changed.connect(self.keybindings_changed.emit)
        left.addWidget(self.editor)
        center.addLayout(left, 3)
        center.addWidget(self._build_status_panel(), 1)
        root.addLayout(center, 1)

        # Controls
        controls = QHBoxLayout()
        self.record_btn = QPushButton("Record")
        # Pinned across all three labels, or Pause shoves Start over along.
        components.lock_width(self.record_btn, "Record", "Pause", "Resume",
                              floor=150)
        self.record_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.record_btn.clicked.connect(self._on_primary)
        controls.addWidget(self.record_btn)
        self.start_over_btn = QPushButton("Start over")
        self.start_over_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.start_over_btn.setIcon(icons.restart())
        self.start_over_btn.setToolTip("Delete this whole take and start again")
        self.start_over_btn.clicked.connect(self._on_start_over)
        controls.addWidget(self.start_over_btn)

        # Play / select / delete / undo live on the editor's own row, under the
        # take, so they sit with what they act on rather than beside Record.
        controls.addStretch()
        self.hint = QLabel("")
        self.hint.setStyleSheet(f"color: {theme.colors()['text_dim']};")
        controls.addWidget(self.hint)
        controls.addSpacing(16)
        # Finish is the way out, set apart from the take-editing controls.
        self.finish_btn = QPushButton("Finish")
        self.finish_btn.setMinimumWidth(130)
        self.finish_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.finish_btn.setIcon(icons.check(colour="#ffffff"))
        self.finish_btn.setToolTip("Done - the take is already saved to the sound")
        self.finish_btn.setStyleSheet(
            f"QPushButton {{ background-color: {theme.colors()['accent']}; "
            f"color: #ffffff; font-weight: bold; border: none; }}")
        self.finish_btn.clicked.connect(self._on_done)
        controls.addWidget(self.finish_btn)
        root.addLayout(controls)

        # Space = pause while recording / play-pause while reviewing.
        # X (or Delete/Backspace) = delete the current selection while reviewing.
        # Every clip key is the editor's, but only while reviewing - Space means
        # "pause" mid-recording, and the rest have nothing to act on.
        def in_review(slot):
            return lambda: self._state == "review" and slot()

        for seq, slot in (
                ("Space", self._on_space),
                ("R", self._on_primary),
                ("X", in_review(self.editor.delete_selection)),
                ("Del", in_review(self.editor.delete_selection)),
                ("Backspace", in_review(self.editor.delete_selection)),
                ("A", in_review(self.editor.toggle_normalize)),
                ("S", in_review(self.editor.toggle_spectrum)),
                ("D", in_review(self.editor.deselect_or_start)),
                ("Esc", in_review(self.editor.deselect_or_start)),
                ("F", in_review(self.editor.fit)),
                ("Ctrl+Z", in_review(self.editor.undo)),
                ("Ctrl+Y", in_review(self.editor.redo)),
                ("Ctrl+Shift+Z", in_review(self.editor.redo))):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(slot)

        self._set_state("idle")

    def _build_status_panel(self):
        group = QGroupBox("Live status")
        form = QFormLayout(group)
        form.setSpacing(8)
        dim = theme.colors()["text_dim"]

        def value_label():
            lbl = QLabel("-")
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

    def _build_threshold_row(self):
        """Automatic or a threshold you set, beside the lane that draws it.

        Automatic is not one number: detection picks a threshold per sound and
        only settles on a floor once ten onsets have been seen, so the line is
        dim and dashed and there is nothing to drag. Manual pins it, live -
        useful for a sound the automatic pass keeps missing, where the
        alternative is finishing the take and finding out afterwards.
        """
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Detection threshold:"))
        self.thr_mode = QComboBox()
        self.thr_mode.addItem("Automatic", None)
        self.thr_mode.addItem("Manual", "manual")
        self.thr_mode.setToolTip("Manual pins the threshold and lets you drag "
                                 "the line while recording")
        self.thr_mode.currentIndexChanged.connect(self._on_threshold_mode)
        layout.addWidget(self.thr_mode)
        self.thr_note = QLabel("")
        self.thr_note.setStyleSheet(f"color: {theme.colors()['text_dim']};")
        layout.addWidget(self.thr_note, 1)
        self._manual_dbfs = -40.0     # remembered across a switch back to auto
        self._threshold_row = row
        self._on_threshold_mode()
        return row

    def _threshold_override(self):
        """The value to run detection at, or None while it is automatic."""
        return self._manual_dbfs if self.thr_mode.currentData() == "manual" else None

    def _on_threshold_mode(self, *_):
        manual = self.thr_mode.currentData() == "manual"
        lane = self.level_lane
        lane.set_mode("manual" if manual else "auto")
        if manual:
            lane.set_threshold(self._manual_dbfs)
            lane.set_line_visible(True)
            self.thr_note.setText(f"{round(self._manual_dbfs)} dBFS - drag the "
                                  f"line to move it")
        else:
            # Nothing to draw until the automatic threshold settles; _on_status
            # brings the line back when it does.
            lane.set_line_visible(False)
            self.thr_note.setText("detection picks its own")
        self._push_threshold()

    def _on_threshold_moved(self, value):
        self._manual_dbfs = float(value)
        self.thr_note.setText(f"{round(value)} dBFS - drag the line to move it")
        self._push_threshold()

    def _push_threshold(self):
        """Every live mic, not just the one driving the view - the extras are
        writing their own srt files against the same take."""
        value = self._threshold_override()
        for worker in ([self.worker] if self.worker else []) + self._extra_workers:
            worker.set_threshold(value)

    def refresh_mic_label(self):
        """Once a take exists the session's mics are locked so every segment
        of the take uses the same devices - the picker greys out until reset."""
        if self._session_mics is not None:
            primary, extras = self._session_mics
            self.mic_picker.setEnabled(False)
            self.mic_note.setText("locked for this take")
            names = [audio_devices.input_name(i) for i in (primary, *extras)]
            self.mic_note.setToolTip("\n".join(names))
        else:
            self.mic_picker.setEnabled(True)
            self.mic_note.setText("")
            self.mic_note.setToolTip("")

    def _reset(self, take):
        self.stop_playback()
        self._take_wav = take
        self._take_srt = self._srt_for(take) if take else None
        self._pending_action = None
        self._session_mics = None
        self._extra_takes = {}
        self.mic_picker.refresh()   # indices shift when hardware changes
        self.refresh_mic_label()
        if take:
            self.history.bind(take)
        else:
            self.history.clear()
        self.name_input.setEnabled(take is None and self._new_mode)
        for w in (self.v_time, self.v_quality, self.v_dbfs, self.v_noise,
                  self.v_snr, self.v_detected, self.v_quantity, self.v_type):
            w.setText("-")
        if take:
            self.editor.open(take, self._take_srt, self._label)
            self._set_state("review")
            self.hint.setText(self._review_hint("Resume to add more."))
        else:
            self.editor.clear()
            self.waveform.clear_display()
            self.level_lane.clear()
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
    # None resolves to the theme's dim text; the rest are state colors, not
    # text tiers, so they stay literal.
    _STATES = {
        "idle":      ("Record", "#c0463f", "● Ready",     None,      (90, 230, 150)),
        "recording": ("Pause",  None,      "● Recording", "#e0534f", (224, 83, 79)),
        "review":    ("Resume", "#3a8f55", "● Paused",   "#e0b020", (224, 176, 32)),
    }

    # Record and Resume paint their own red/green fill, so their icon is white
    # rather than a theme text colour.
    _STATE_ICONS = {"idle": icons.record, "recording": icons.pause,
                    "review": icons.record}

    def _set_state(self, state):
        self._state = state
        text, color, ind_text, ind_color, trace = self._STATES[state]
        ind_color = ind_color or theme.colors()["text_dim"]
        self.record_btn.setText(text)
        self.record_btn.setIcon(
            self._STATE_ICONS[state](colour="#ffffff" if color else None))
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
        self.level_lane.setVisible(not reviewing)
        self._threshold_row.setVisible(not reviewing)
        self.editor.setVisible(reviewing)
        # Start over only makes sense once a take exists; you can finish anytime.
        self.start_over_btn.setVisible(self._take_wav is not None)
        self.start_over_btn.setEnabled(reviewing)
        # Selection editing only touches the primary take; with extra mics that
        # would desync the per-mic files, so it's off for multi-mic sessions.
        self.editor.set_editing_enabled(
            not self._multi_mic(),
            "Off for a multi-mic take: cutting the primary would desync the "
            "other mics' files.")
        if reviewing:
            self.editor.refresh_history_buttons()
        # Lock strategy/name once a take exists.
        locked = state != "idle"
        self.strategy_combo.setEnabled(not locked)
        if recording:
            self.name_input.setEnabled(False)
        self.keybindings_changed.emit()

    # ---- review view toggles + keybindings ----------------------------

    def hint_text(self, text):
        self.hint.setText(text)

    def _multi_mic(self):
        return bool(self._extra_takes) or (
            self._session_mics is not None and bool(self._session_mics[1]))

    def _review_hint(self, tail):
        """One place, because every caller used to overwrite the multi-mic line
        with an instruction to drag-select and delete - which is exactly what a
        multi-mic take cannot do."""
        if self._multi_mic():
            return ("Multi-mic take: cutting is off so the mic files stay in "
                    "sync. Play to review, " + tail)
        return "Play to review, drag-select to delete, " + tail

    def _on_editor_edited(self):
        """The editor rewrote the take's files. Re-resolve the srt so a later
        resume appends onto the right one."""
        self.app_state.recordings_changed.emit()
        self._take_srt = self._srt_for(self._take_wav)

    def keybinding_hint(self):
        if self._state == "recording":
            return "Space / R  pause and review"
        if self._state == "review":
            return "R resume recording  ·  " + self.editor.keybinding_hint()
        return "R (or Record) to start  ·  name the sound first for a new one"

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
        if self._seg_worker or self.editor.is_busy():
            return      # a cut or a stitch is still rewriting the take
        if self._state in ("idle", "review"):
            self._start_segment()
        elif self._state == "recording":
            self._pause()

    def _seed_or_clear_live(self):
        """Resuming an existing take shows that take in the live view so the new
        audio visibly continues it; a brand-new take starts from a blank trace."""
        if self._take_wav is None:
            self.waveform.clear_display()
            return
        try:
            # The editor already decoded the take for its preview; reuse that
            # rather than reading the wav a second time.
            samples, sr = self.editor.preview.playback_audio()
            if samples is None or not sr:
                self.waveform.clear_display()
                return
            ints = np.clip(np.asarray(samples) * 32768.0, -32768, 32767).astype(np.int16)
            if sr != RATE:   # match the recorder's rate so the splice lines up
                n_out = max(1, int(len(ints) * RATE / sr))
                ints = np.interp(np.linspace(0, len(ints), n_out, endpoint=False),
                                 np.arange(len(ints)), ints.astype(np.float32)).astype(np.int16)
            self.waveform.seed_live(ints, RATE)
        except Exception:
            self.waveform.clear_display()

    def _start_segment(self):
        label = self._resolve_label()
        if not label:
            return
        self._label = label
        if self._session_mics is None:
            self._session_mics = audio_devices.recording_mics()
            self.refresh_mic_label()
        mic, extras = self._session_mics
        strategy = strategies.strategy_for_label(self.strategy_combo.currentText())

        self.stop_playback()
        self._seed_or_clear_live()
        # Continue the take's time axis, so a resumed segment's levels line up
        # with the trace seeded above them instead of restarting at zero.
        self.level_lane.begin_live(self.waveform.total_seconds())

        # one timestamp for all mics: their files read as one take
        time_string = str(int(time.time()))
        threshold = self._threshold_override()
        self.worker = AudioWorker(label, mic, strategy, time_string, threshold)
        self.worker.frame_recorded.connect(self.waveform.append_live_data)
        self.worker.status_updated.connect(self._on_status)
        self.worker.recording_finished.connect(self._on_segment_finished)
        self.worker.start()

        # extra mics record headless; the primary drives the live view
        for extra in extras:
            w = AudioWorker(label, extra, strategy, time_string, threshold)
            w.recording_finished.connect(
                lambda wav, srt, m=extra, wk=w:
                    self._on_extra_segment_finished(m, wk, wav, srt))
            self._extra_workers.append(w)
            w.start()

        self._set_state("recording")
        if extras:
            self.hint.setText(f"Recording with {1 + len(extras)} mics… "
                              "Space (or Pause) to stop and review.")
        else:
            self.hint.setText("Recording… Space (or Pause) to stop and review.")

    def _pause(self):
        self._stop_segment("pause")

    def _on_done(self):
        if self.editor.is_busy():
            return      # don't leave while a cut is still being written
        if self._state == "recording":
            self._stop_segment("done")
        else:
            self._leave()

    def _on_start_over(self):
        if (self._state != "review" or not self._take_wav
                or self._seg_worker or self.editor.is_busy()):
            return
        self.stop_playback()
        name = library_ops.recording_base(self._take_wav)
        extra_note = (f" (including {len(self._extra_takes)} extra mic "
                      f"file(s))" if self._extra_takes else "")
        if not confirm_destructive(
                self, title="Start over?",
                body=f"This deletes the current take “{name}”{extra_note} and "
                     f"everything recorded into it, so you can record it again.",
                confirm_label="Delete take"):
            return
        try:
            library_ops.delete_recording(self._take_wav)
        except library_ops.LibraryOpError as exc:
            QMessageBox.warning(self, "Couldn't delete the take", str(exc))
            return
        for take in self._extra_takes.values():
            try:
                library_ops.delete_recording(take["wav"])
            except library_ops.LibraryOpError:
                pass
        self.history.clear()
        self.app_state.recordings_changed.emit()
        self._reset(take=None)
        self.hint.setText("Take deleted - record again when you're ready.")

    def _stop_segment(self, action):
        if not self.worker:
            return
        self._pending_action = action
        self.record_btn.setEnabled(False)
        self.finish_btn.setEnabled(False)
        self.hint.setText("Finalizing…")
        self.worker.request_stop()
        for w in self._extra_workers:
            w.request_stop()

    def _on_segment_finished(self, seg_wav, seg_srt):
        self.worker = None
        if self._take_wav is None:
            # First segment becomes the take.
            self._take_wav = seg_wav
            self._take_srt = seg_srt
            self.history.bind(seg_wav)
            self.app_state.recordings_changed.emit()
            self._after_segment()
        else:
            # Append this segment onto the existing take, then re-detect.
            # Checkpoint first so the resume can be undone.
            self.history.checkpoint()
            self.hint.setText("Stitching the take together…")
            self._seg_worker = AppendWorker(self._take_wav, seg_wav, self._label)
            self._seg_worker.finished_ok.connect(
                lambda srt, src=seg_wav: self._on_appended(src, srt))
            self._seg_worker.failed.connect(
                lambda msg, src=seg_wav, srt=seg_srt: self._on_append_failed(msg, src, srt))
            self._seg_worker.start()

    # ---- extra-mic takes (headless mirrors of the primary flow) ---------

    def _on_extra_segment_finished(self, mic, worker, seg_wav, seg_srt):
        if worker in self._extra_workers:
            self._extra_workers.remove(worker)
        worker.wait()
        worker.deleteLater()
        take = self._extra_takes.get(mic)
        if take is None:
            self._extra_takes[mic] = {"wav": seg_wav, "srt": seg_srt}
            self.app_state.recordings_changed.emit()
            return
        seg = AppendWorker(take["wav"], seg_wav, self._label)
        self._extra_seg_workers.append(seg)
        seg.finished_ok.connect(
            lambda srt, s=seg, m=mic, src=seg_wav:
                self._on_extra_appended(s, m, src, srt))
        # on failure the segment stays as its own recording, same as primary
        seg.failed.connect(lambda _msg, s=seg: self._finish_extra_seg_worker(s))
        seg.start()

    def _on_extra_appended(self, seg, mic, source_wav, srt_path):
        self._finish_extra_seg_worker(seg)
        try:
            library_ops.delete_recording(source_wav)
        except library_ops.LibraryOpError:
            pass
        if mic in self._extra_takes:
            self._extra_takes[mic]["srt"] = srt_path
        self.app_state.recordings_changed.emit()

    def _finish_extra_seg_worker(self, seg):
        if seg in self._extra_seg_workers:
            self._extra_seg_workers.remove(seg)
        seg.wait()
        seg.deleteLater()

    def _finish_seg_worker(self):
        """Tear down a finished Append/Trim thread safely - the worker emits its
        result as the last line of run(), so wait() before dropping the ref to
        avoid deleting a still-running QThread (a hard crash)."""
        w = self._seg_worker
        self._seg_worker = None
        if w is not None:
            w.wait()
            w.deleteLater()

    def _on_appended(self, source_wav, srt_path):
        self._finish_seg_worker()
        try:
            library_ops.delete_recording(source_wav)
        except library_ops.LibraryOpError:
            pass
        self._take_srt = srt_path
        self.app_state.recordings_changed.emit()
        self._after_segment()

    def _on_append_failed(self, msg, source_wav, source_srt):
        self._finish_seg_worker()
        # The append didn't happen - drop its checkpoint.
        self.history.discard_last_checkpoint()
        # Keep what we had; the stray segment stays as its own clip.
        self.app_state.recordings_changed.emit()
        QMessageBox.warning(self, "Couldn't stitch the take",
                            f"{msg}\nThe last segment was kept as a separate "
                            f"recording.")
        self._after_segment()

    def _after_segment(self):
        action, self._pending_action = self._pending_action, None
        self.record_btn.setEnabled(True)
        self.finish_btn.setEnabled(True)
        if action == "done":
            self._leave()
            return
        self._take_srt = self._srt_for(self._take_wav) or self._take_srt
        self.editor.open(self._take_wav, self._take_srt, self._label)
        self._set_state("review")
        self.hint.setText(self._review_hint("Resume to add more, Done to finish."))

    # ---- review: the take is edited through the shared editor ----------

    def stop_playback(self):
        self.editor.stop_playback()

    def _on_space(self):
        if self._state == "recording":
            self._pause()
        elif self._state == "review":
            self.editor.toggle_play()

    # ---- live status ---------------------------------------------------

    def _on_status(self, state):
        # Before the throttle: the lane wants every frame, and drawing it is
        # already throttled on its own clock. Skipping frames here would put
        # gaps in the level trace that the audio does not have.
        self.level_lane.push_level(state.ms_recorded / 1000.0, state.latest_dBFS)

        now = time.monotonic()
        if now - self._last_status_draw < 0.12:
            return
        self._last_status_draw = now

        # Automatic has no threshold to show until calibration engages (it
        # needs ten onset valleys), and 0 is how "not yet" is expressed.
        if self.thr_mode.currentData() != "manual":
            settled = state.upper_bound_dBFS_threshold or 0
            if settled < 0:
                self.level_lane.set_threshold(settled)
                self.level_lane.set_line_visible(True)
                self.thr_note.setText(f"detection settled on {round(settled)} dBFS")
            else:
                self.level_lane.set_line_visible(False)
                self.thr_note.setText("detection is still calibrating")

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
        self.history.clear()
        self.done.emit(self._label or "")

    def stop_worker(self):
        changed = False
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
            changed = True
        if self._extra_workers:
            changed = True
        for w in self._extra_workers:
            try:
                w.recording_finished.disconnect()
            except TypeError:
                pass
            w.request_stop()
            w.wait(2000)
        self._extra_workers = []
        if changed:
            self.app_state.recordings_changed.emit()

    def refresh_theme(self):
        self.editor.refresh_theme()
        self.start_over_btn.setIcon(icons.restart())
        self._set_state(self._state)
