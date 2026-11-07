import os
import time
import numpy as np
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget, QWIDGETSIZE_MAX
)
from config.config import MS_PER_FRAME
from gui import components, icons, keys, theme
from gui.formatters import duration_text
from gui.services import audio_devices
from gui.widgets.mic_picker import MicPicker
from gui.widgets.output_picker import OutputPicker
from gui.widgets.recording_card import RecordingCard
from gui.widgets.waveform import WaveformWidget
from gui.workers.append_worker import AppendWorker
from gui.workers.audio_worker import AudioWorker
from lib import recordings
from lib.print_status import get_quantity_rating, QUANTITIES
from lib.srt import get_label_ranges_in_srt
from lib.wav import read_wav, wav_duration, UnreadableWav, INT16_FULL_SCALE

# The take's card, while paused. Space and R are the view's
CARD_KEYS = (
    (keys.is_go_to_start,                 RecordingCard.go_to_start),
    (keys.unmodified(Qt.Key.Key_Left),    RecordingCard.seek_back),
    (keys.unmodified(Qt.Key.Key_Right),   RecordingCard.seek_forward),
    (keys.unmodified(Qt.Key.Key_Z),       RecordingCard.toggle_zoom),
    (keys.unmodified(Qt.Key.Key_Escape),  RecordingCard.deselect_or_go_to_start),
)

# state -> (button, its fill, indicator, indicator colour, live trace colour).
# State colours, not text tiers, so literal. None is plain / dim text
STATES = {
    "idle":      ("Record", "#c0463f", "● Ready",     None,      (90, 230, 150)),
    "recording": ("Pause",  None,      "● Recording", "#e0534f", (224, 83, 79)),
    "review":    ("Resume", "#3a8f55", "● Paused",    "#e0b020", (224, 176, 32)),
}


def _filled_button_style(fill):
    t = theme.colors()
    return (f"QPushButton {{ background-color: {fill}; color: #ffffff; font-weight: bold; "
            f"border: none; border-radius: {t['radius']}; padding: 6px 16px; }} "
            # Else the app-wide hover greys it out
            f"QPushButton:hover {{ background-color: {fill}; }} "
            f"QPushButton:focus {{ border: 2px solid {t['focus']}; padding: 4px 14px; }} "
            f"QPushButton:disabled {{ background-color: {t['disabled_bg']}; "
            f"color: {t['disabled_text']}; }}")


def _toward_next(quantity, percent):
    """The " (40% → Good)" after a rating, nothing once it is Excellent."""
    names = list(QUANTITIES.values())
    if quantity == QUANTITIES["excellent"]:
        return ""
    return f" ({round(percent)}% → {names[names.index(quantity) + 1]})"


class RecordingView(QWidget):
    """One take of a sound, recorded in stretches: Record, Pause to hear it,
    Resume to add more, Finish. A stretch is its own wav until it stops, then
    it is appended onto the take. The take is in the sound from its first
    stretch on, so leaving any time keeps it.

    ┌ header ──────────────────────────────────────────────────────────────┐
    │ back_btn  title  state_label                mic_note     mic_picker  │
    │                                                       output_picker  │
    ├──────────────────────────────────────────────────────┬───────────────┤
    │ waveform while recording, take_card while paused     │ status_panel  │
    │                                                      │               │
    ├──────────────────────────────────────────────────────┴───────────────┤
    │ record_btn  start_over_btn                       hint     finish_btn │
    └──────────────────────────────────────────────────────────────────────┘
    """

    done = pyqtSignal()
    sound_changed = pyqtSignal(str)   # recorded into
    keybindings_changed = pyqtSignal()

    # Status redraws at most this often. Frames arrive every 15 ms
    STATUS_REDRAW_SECONDS = 0.12

    # Most mics deliver in ~300 ms, too soon for words to be read, so the plot
    # is only veiled. A Bluetooth headset takes 1.4-3 s and gets the words.
    # Past MIC_SLOW_MS it is more likely off than slow: say so, keep waiting
    MIC_WORDS_MS = 700
    MIC_SLOW_MS = 5000

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.worker = None
        self._append_worker = None
        self._label = None
        self._take_wav = None
        self._take_card = None
        self._session_mic = None        # every stretch of a take uses one mic
        self._finish_when_saved = False
        self._state = "idle"
        self._stream_live = False
        self._take_seconds = 0.0
        self._take_detected_ms = 0
        self._take_sounds = 0
        self._live_sounds = 0
        self._was_detected = False
        # Loudest frame since the panel drew. One frame per redraw mostly
        # lands in the silence between short sounds
        self._peak_dbfs = None
        self._last_status_draw = 0.0

        self._mic_words_timer = QTimer(self)
        self._mic_words_timer.setSingleShot(True)
        self._mic_words_timer.timeout.connect(self._on_mic_words)
        self._mic_slow_timer = QTimer(self)
        self._mic_slow_timer.setSingleShot(True)
        self._mic_slow_timer.timeout.connect(self._on_mic_slow)
        self._setup_ui()

    def start_for(self, label):
        self._label = label
        self.title.setText(f"Record:  {label}")
        self.mic_picker.refresh()
        self._reset()
        self.record_btn.setFocus()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        back_btn = QPushButton("← Back to Sounds")
        back_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        back_btn.clicked.connect(self._on_finish)
        header.addWidget(back_btn)
        self.title = QLabel("")
        self.title.setStyleSheet(components.heading_style("title"))
        header.addWidget(self.title)
        header.addSpacing(12)
        self.state_label = QLabel("")
        header.addWidget(self.state_label)
        header.addStretch()
        header.addLayout(self._devices_build())
        root.addLayout(header)

        center = QHBoxLayout()
        left = QVBoxLayout()
        self.waveform = WaveformWidget()
        left.addWidget(self.waveform, 1)
        # Shown instead of the waveform while paused
        self.take_panel = QWidget()
        self.take_area = QVBoxLayout(self.take_panel)
        self.take_area.setContentsMargins(0, 0, 0, 0)
        left.addWidget(self.take_panel, 1)
        center.addLayout(left, 3)
        center.addWidget(self._status_panel_build(), 1)
        root.addLayout(center, 1)

        controls = QHBoxLayout()
        self.record_btn = QPushButton("")
        # Wide enough for every label, or Pause shoves Start over along
        self.record_btn.setMinimumWidth(150)
        self.record_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.record_btn.clicked.connect(self._on_record)
        controls.addWidget(self.record_btn)
        self.start_over_btn = QPushButton(icons.restart(), " Start over")
        self.start_over_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.start_over_btn.setToolTip("Delete this take and record it again")
        self.start_over_btn.clicked.connect(self._on_start_over)
        controls.addWidget(self.start_over_btn)
        controls.addStretch()
        self.hint = QLabel("")
        self.hint.setStyleSheet(f"color: {theme.colors()['text_dim']};")
        controls.addWidget(self.hint)
        controls.addSpacing(16)
        self.finish_btn = QPushButton("Finish")
        self.finish_btn.setMinimumWidth(130)
        self.finish_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.finish_btn.clicked.connect(self._on_finish)
        controls.addWidget(self.finish_btn)
        root.addLayout(controls)

        for key, slot in (("R", self._on_record), ("Space", self._on_space)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)

    def _devices_build(self):
        """Mic over playback, captions and combos lined up."""
        self.mic_picker = MicPicker()
        output_picker = OutputPicker()
        captions = (self.mic_picker.caption, output_picker.caption)
        width = max(c.sizeHint().width() for c in captions)
        for picker in (self.mic_picker, output_picker):
            picker.caption.setMinimumWidth(width)
            picker.caption.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            picker.combo.setFixedWidth(260)
        self.mic_note = QLabel("")
        self.mic_note.setStyleSheet(f"color: {theme.colors()['text_dim']};")
        grid = QGridLayout()
        grid.setVerticalSpacing(4)
        grid.addWidget(self.mic_note, 0, 0, Qt.AlignmentFlag.AlignRight)
        grid.addWidget(self.mic_picker, 0, 1)
        grid.addWidget(output_picker, 1, 1)
        return grid

    def _status_panel_build(self):
        group = QGroupBox("Live status")
        form = QFormLayout(group)
        form.setSpacing(8)
        t = theme.colors()
        self.recorded_value = QLabel("")
        self.level_value = QLabel("")
        self.detected_value = QLabel("")
        self.sounds_value = QLabel("")
        self.quantity_value = QLabel("")
        # "Not enough (16% → Sufficient)" outgrows the panel
        self.quantity_value.setWordWrap(True)
        for caption, value in (("Recorded", self.recorded_value),
                               ("Level (dBFS)", self.level_value),
                               ("Detected sound", self.detected_value),
                               ("Sounds", self.sounds_value),
                               ("Data quantity", self.quantity_value)):
            caption_label = QLabel(caption + ":")
            caption_label.setStyleSheet(f"color: {t['text_dim']};")
            value.setStyleSheet(f"color: {t['text_bright']}; font-weight: bold;")
            form.addRow(caption_label, value)
        group.setMaximumWidth(280)
        return group

    # ---- state ---------------------------------------------------------

    def _reset(self):
        self._take_card_drop()
        self._take_wav = None
        self._session_mic = None
        self._finish_when_saved = False
        self._take_seconds = 0.0
        self._take_detected_ms = 0
        self._take_sounds = 0
        for value in (self.recorded_value, self.level_value, self.detected_value,
                      self.sounds_value, self.quantity_value):
            value.setText("-")
        self.waveform.clear_display()
        self._set_state("idle")
        self.hint.setText("")

    def _set_state(self, state):
        self._state = state
        recording = state == "recording"
        waiting = recording and not self._stream_live
        has_take = self._take_wav is not None

        text, fill, indicator, colour, trace = STATES[state]
        icon = icons.pause() if recording else icons.record(colour="#ffffff")
        if waiting:
            # No fill: says "not live yet" without claiming a fault
            text, icon, indicator, colour = "Starting…", icons.record(), "● Waiting for mic", None
        self.record_btn.setText(" " + text)
        self.record_btn.setIcon(icon)
        self.record_btn.setStyleSheet(_filled_button_style(fill) if fill else "")
        self.state_label.setText(indicator)
        self.state_label.setStyleSheet(
            f"color: {colour or theme.colors()['text_dim']}; font-weight: bold;")
        self.waveform.set_trace_color(trace)
        # The accent only once there is a take: on an empty screen it points at
        # the one thing you can't have meant yet
        self.finish_btn.setObjectName("primaryAction" if has_take else "")
        self.finish_btn.setStyleSheet(components.primary_button_style() if has_take else "")
        self.finish_btn.setIcon(icons.check(theme.colors()["accent_text"] if has_take else None))

        self.waveform.setVisible(state != "review")
        self.take_panel.setVisible(state == "review")
        self.start_over_btn.setVisible(has_take)
        self.start_over_btn.setEnabled(state == "review")
        self.finish_btn.setToolTip("The take is already saved to the sound" if has_take
                                   else "Leave without recording")
        self.mic_picker.setEnabled(self._session_mic is None and not recording)
        self.mic_note.setText("locked for this take" if self._session_mic is not None else "")
        self.keybindings_changed.emit()

    def _set_busy(self, busy, text=""):
        """Saving or appending a stretch: the take's files are being written."""
        self.record_btn.setEnabled(not busy)
        self.finish_btn.setEnabled(not busy)
        self.start_over_btn.setEnabled(not busy and self._state == "review")
        if busy:
            self.hint.setText(text)

    def _busy(self):
        return not self.record_btn.isEnabled()

    def keybinding_hint(self):
        if self._state == "recording":
            return "Space / R  pause and review"
        if self._state == "review":
            return (f"Space play  ·  R resume  ·  ←→ seek  ·  {keys.go_to_start_key_name()} start"
                    "  ·  Z zoom  ·  Esc deselect/start")
        return "R (or Record) to start"

    # ---- recording -----------------------------------------------------

    def _on_record(self):
        if self._busy():
            return
        if self._state == "recording":
            self._pause()
        else:
            self._start_stretch()

    def _on_space(self):
        if self._state == "recording":
            self._pause()
        elif self._state == "review" and self._take_card is not None:
            self._take_card.toggle_play()

    def _start_stretch(self):
        if self._session_mic is None:
            self._session_mic = audio_devices.input_index
        self._stop_playback()
        self._seed_waveform()
        self._live_sounds = 0
        self._was_detected = False
        self._peak_dbfs = None
        self.worker = AudioWorker(self._label, self._session_mic,
                                  self.app_state.get_label_duration_ms(self._label), self)
        self.worker.frame_recorded.connect(self.waveform.append_live_data)
        self.worker.frame_recorded.connect(self._count_sound)
        self.worker.frame_level.connect(self._on_frame_level)
        self.worker.status_updated.connect(self._on_status)
        self.worker.stream_ready.connect(self._on_stream_ready)
        self.worker.recording_finished.connect(self._on_stretch_saved)
        self.worker.failed.connect(self._on_failed)
        self._stream_live = False
        self._set_state("recording")
        self.waveform.show_veil()
        self.hint.setText("")
        self._mic_words_timer.start(self.MIC_WORDS_MS)
        self._mic_slow_timer.start(self.MIC_SLOW_MS)
        self.worker.start()

    def _seed_waveform(self):
        """A resumed take continues its trace rather than starting blank."""
        if self._take_wav is None:
            self.waveform.clear_display()
            return
        try:
            samples, _rate = read_wav(self._take_wav)
        except UnreadableWav:
            self.waveform.clear_display()
            return
        self.waveform.seed_live((samples * INT16_FULL_SCALE).astype(np.int16))

    def _on_stream_ready(self):
        self._stop_wait_timers()
        self._stream_live = True
        self.waveform.clear_message()
        self._set_state("recording")
        self.hint.setText("Recording… Space (or Pause) to stop and review.")

    def _on_mic_words(self):
        self.waveform.show_message("Waiting for mic…")
        self.hint.setText("Waiting for mic…")

    def _on_mic_slow(self):
        self.waveform.show_message(
            "Still waiting for the mic\ncheck it is switched on and connected", STATES["recording"][3])

    def _stop_wait_timers(self):
        self._mic_words_timer.stop()
        self._mic_slow_timer.stop()

    def _pause(self):
        """The stretch saves on the worker's thread. _on_stretch_saved follows."""
        if self.worker is None or self._busy():
            return
        self._stop_wait_timers()
        self.waveform.clear_message()
        self._set_busy(True, "Saving…")
        self.worker.request_stop()

    def _on_stretch_saved(self, wav_path, _srt_path):
        self._worker_finish()
        if not os.path.isfile(wav_path):
            # Stopped before the mic delivered: the worker removed the empty files
            self._after_stretch("Nothing recorded, the mic had not started yet.")
        elif self._take_wav is None:
            self._take_wav = wav_path
            self._after_stretch()
        else:
            self._set_busy(True, "Adding it to the take…")
            self._append_worker = AppendWorker(self._take_wav, wav_path, self._label, self)
            self._append_worker.appended.connect(lambda _srt: self._on_appended())
            self._append_worker.failed.connect(self._on_append_failed)
            self._append_worker.start()

    def _on_appended(self):
        self._append_worker_finish()
        self._after_stretch()

    def _on_append_failed(self, message):
        self._append_worker_finish()
        QMessageBox.warning(self, "Couldn't add to the take",
                            f"{message}\nWhat you just recorded is kept as its own recording.")
        self._after_stretch()

    def _on_failed(self, message):
        """The mic would not open, so nothing was recorded."""
        self._worker_finish()
        self._stop_wait_timers()
        self.waveform.clear_message()
        if self._take_wav is None:
            # Free to pick another mic
            self._session_mic = None
        self._after_stretch(message)

    def _after_stretch(self, message=None):
        self.app_state.forget_label_duration(self._label)
        self._set_busy(False)
        if self._finish_when_saved:
            self._leave()
            return
        if self._take_wav is None:
            self._set_state("idle")
            self.hint.setText(message or "")
            return
        self._review()
        self.hint.setText(message or "Play to review, Resume to add more, Finish when done.")

    def _worker_finish(self):
        """Signals arrive as run() returns, so wait before dropping the thread."""
        if self.worker is not None:
            self.worker.wait()
            self.worker.deleteLater()
            self.worker = None

    def _append_worker_finish(self):
        self._append_worker.wait()
        self._append_worker.deleteLater()
        self._append_worker = None

    # ---- review --------------------------------------------------------

    def _review(self):
        """The take as Sounds shows it, re-detected from 0:00."""
        self._take_card_drop()
        srt_path = next((r["srt_path"] for r in recordings.get_recordings(self._label)
                         if r["wav_path"] == self._take_wav), None)
        name = os.path.splitext(os.path.basename(self._take_wav))[0]
        self._take_card = RecordingCard(name, self._label, self._take_wav, srt_path)
        # Start over deletes the take here
        self._take_card.menu_btn.setVisible(False)
        self._take_card.playback_failed.connect(
            lambda message: QMessageBox.warning(self, "Playback", message))
        # Fills the view, as the live waveform did
        self._take_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.take_area.addWidget(self._take_card)
        self._take_card.build_audio_graph()
        if self._take_card.audio_graph is not None:
            self._take_card.audio_graph.setMinimumHeight(RecordingCard.AUDIO_GRAPH_HEIGHT)
            self._take_card.audio_graph.setMaximumHeight(QWIDGETSIZE_MAX)
        self._take_summary_show(srt_path)
        self._set_state("review")

    def _take_summary_show(self, srt_path):
        """Pause re-judges the take from 0:00, so the live counts are replaced
        by what is now in its srt."""
        ranges = []
        if srt_path and os.path.isfile(srt_path):
            ranges = get_label_ranges_in_srt(self._label, srt_path, MS_PER_FRAME)
        self._take_seconds = wav_duration(self._take_wav)
        self._take_sounds = len(ranges)
        self._take_detected_ms = sum(end - start for start, end in ranges)
        self.recorded_value.setText(duration_text(self._take_seconds))
        self.detected_value.setText(duration_text(self._take_detected_ms / 1000.0))
        self.sounds_value.setText(str(self._take_sounds))
        self._quantity_show(self.app_state.get_label_duration_ms(self._label))

    def _take_card_drop(self):
        if self._take_card is not None:
            self._take_card.cleanup()
            self._take_card.setParent(None)
            self._take_card.deleteLater()
            self._take_card = None

    def _stop_playback(self):
        if self._take_card is not None:
            self._take_card.stop()

    def keyPressEvent(self, event):
        action = next((action for matches, action in CARD_KEYS if matches(event)), None)
        if self._state == "review" and self._take_card is not None and action is not None:
            if not event.isAutoRepeat() or action in (RecordingCard.seek_back, RecordingCard.seek_forward):
                action(self._take_card)
            return
        super().keyPressEvent(event)

    def _on_start_over(self):
        if self._state != "review" or self._busy():
            return
        self._stop_playback()
        box = QMessageBox(QMessageBox.Icon.Warning, "Start over?",
                          "This deletes the take and everything recorded into it, "
                          "so you can record it again.", parent=self)
        delete_btn = box.addButton("Delete take", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is not delete_btn:
            return
        try:
            recordings.delete_recording(self._take_wav)
        except OSError as exc:
            QMessageBox.warning(self, "Couldn't delete the take", exc.strerror or str(exc))
            return
        self.app_state.forget_label_duration(self._label)
        self._reset()
        self.hint.setText("Take deleted. Record again when you're ready.")

    # ---- live status ---------------------------------------------------

    def _count_sound(self, _frame, detected):
        """Rising edges of the detection flag. Provisional: Pause re-judges."""
        if detected and not self._was_detected:
            self._live_sounds += 1
            self.sounds_value.setText(str(self._take_sounds + self._live_sounds))
        self._was_detected = detected

    def _on_frame_level(self, dbfs):
        self._peak_dbfs = dbfs if self._peak_dbfs is None else max(self._peak_dbfs, dbfs)

    def _on_status(self, state):
        now = time.monotonic()
        if now - self._last_status_draw < self.STATUS_REDRAW_SECONDS:
            return
        self._last_status_draw = now
        self.recorded_value.setText(duration_text(self._take_seconds + state.ms_recorded / 1000.0))
        peak, self._peak_dbfs = self._peak_dbfs, None
        if peak is not None:
            # A muted or digital-silent input reads as no level at all
            self.level_value.setText("weak / muted?" if peak <= -100 else str(round(peak)))
        label = state.labels[0]
        self.detected_value.setText(
            duration_text((self._take_detected_ms + label.ms_detected) / 1000.0))
        # The sound's, this stretch included: what training will see
        self._quantity_show(label.ms_detected + label.previous_detected)

    def _quantity_show(self, detected_ms):
        quantity, percent = get_quantity_rating(detected_ms)
        self.quantity_value.setText(quantity + _toward_next(quantity, percent))
        self.quantity_value.setStyleSheet(
            f"color: {theme.QUANTITY_COLORS.get(quantity, theme.colors()['text_bright'])}; "
            f"font-weight: bold;")

    # ---- leaving -------------------------------------------------------

    def _on_finish(self):
        """Back and Finish both: the take is already in the sound."""
        if self._state == "recording":
            self._finish_when_saved = True
            self._pause()
        elif not self._busy():
            self._leave()

    def _leave(self):
        self._finish_when_saved = False
        self._stop_playback()
        self._take_card_drop()
        self.sound_changed.emit(self._label)
        self.done.emit()

    def stop_recording(self):
        """Left by switching tabs: the stretch saves and joins the take."""
        self._stop_playback()
        if self._state == "recording":
            self._pause()

    def finish_recording(self):
        """Before the app quits. A stretch mid-save would lose its srt."""
        if self.worker is not None:
            self.worker.request_stop()
            self.worker.wait()
        if self._append_worker is not None:
            self._append_worker.wait()
