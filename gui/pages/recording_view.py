import os
import time
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QVBoxLayout, QWidget
)
from gui import components, icons, theme
from gui.formatters import duration_text
from gui.widgets.waveform import WaveformWidget
from gui.workers.audio_worker import AudioWorker
from lib import recordings
from lib.print_status import get_quantity_rating

INVALID_LABEL_TEXT = {
    recordings.InvalidLabel.EMPTY: "Name the sound first.",
    recordings.InvalidLabel.ILLEGAL_CHARACTER:
        "A sound name can't contain any of: < > : \" / \\ | ? *",
    recordings.InvalidLabel.STARTS_WITH_DOT: "A sound name can't start with a dot.",
}


class RecordingView(QWidget):
    """Records takes of one sound from the default mic. Each Record -> Stop is
    one recording, saved to the sound as it stops.

    ┌ header ──────────────────────────────────────────────────────────────┐
    │ back_btn  title                                          state_label │
    │ name_row                                                             │
    ├──────────────────────────────────────────────────────┬───────────────┤
    │ waveform                                             │ status_panel  │
    │                                                      │               │
    ├──────────────────────────────────────────────────────┴───────────────┤
    │ record_btn  hint                                                     │
    └──────────────────────────────────────────────────────────────────────┘
    """

    done = pyqtSignal()
    sound_changed = pyqtSignal(str)   # made, or recorded into

    # Status redraws at most this often. Frames arrive every 15 ms
    STATUS_REDRAW_SECONDS = 0.12

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.worker = None
        self._label = None
        self._leave_when_saved = False
        self._last_status_draw = 0.0
        self._setup_ui()

    def start_for(self, label):
        """Record more of an existing sound."""
        self._label = label
        self._reset()
        self.record_btn.setFocus()

    def start_new(self):
        """Name a new sound, then record it."""
        self._label = None
        self.name_input.clear()
        self._reset()
        self.name_input.setFocus()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        back_btn = QPushButton("← Back to Sounds")
        back_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        back_btn.clicked.connect(self._on_back)
        header.addWidget(back_btn)
        self.title = QLabel("")
        self.title.setStyleSheet(components.heading_style("title"))
        header.addWidget(self.title)
        header.addStretch()
        self.state_label = QLabel("")
        header.addWidget(self.state_label)
        root.addLayout(header)

        self.name_row = QWidget()
        name_layout = QHBoxLayout(self.name_row)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.addWidget(QLabel("Sound name:"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. pop")
        self.name_input.setAccessibleName("Sound name")
        self.name_input.returnPressed.connect(self._toggle_recording)
        name_layout.addWidget(self.name_input)
        name_layout.addStretch()
        root.addWidget(self.name_row)

        center = QHBoxLayout()
        self.waveform = WaveformWidget()
        center.addWidget(self.waveform, 3)
        center.addWidget(self._status_panel_build(), 1)
        root.addLayout(center, 1)

        controls = QHBoxLayout()
        self.record_btn = QPushButton("")
        self.record_btn.setObjectName("primaryAction")
        self.record_btn.setStyleSheet(components.primary_button_style())
        self.record_btn.setMinimumWidth(130)
        self.record_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.record_btn.clicked.connect(self._toggle_recording)
        controls.addWidget(self.record_btn)
        self.hint = QLabel("")
        self.hint.setStyleSheet(f"color: {theme.colors()['text_dim']};")
        controls.addWidget(self.hint, 1)
        root.addLayout(controls)

        # A focused name field keeps its typed R and Space
        for key in ("R", "Space"):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(self._toggle_recording)

    def _status_panel_build(self):
        group = QGroupBox("Status")
        form = QFormLayout(group)
        form.setSpacing(8)
        t = theme.colors()
        self.recorded_value = QLabel("")
        self.detected_value = QLabel("")
        self.quantity_value = QLabel("")
        for caption, value in (("Recorded", self.recorded_value),
                               ("Detected sound", self.detected_value),
                               ("Data quantity", self.quantity_value)):
            caption_label = QLabel(caption + ":")
            caption_label.setStyleSheet(f"color: {t['text_dim']};")
            value.setStyleSheet(f"color: {t['text_bright']}; font-weight: bold;")
            form.addRow(caption_label, value)
        group.setMaximumWidth(280)
        return group

    # ---- state ---------------------------------------------------------

    def _reset(self):
        self._leave_when_saved = False
        self.waveform.clear_display()
        self.waveform.clear_message()
        for value in (self.recorded_value, self.detected_value, self.quantity_value):
            value.setText("-")
        self._show_label()
        self._show_recording(False)
        self.hint.setText("")

    def _show_label(self):
        self.name_row.setVisible(self._label is None)
        self.title.setText(f"Record:  {self._label}" if self._label else "New sound")

    def _show_recording(self, recording):
        self.record_btn.setText(" Stop" if recording else " Record")
        self.record_btn.setIcon(icons.stop() if recording else icons.record())
        self.record_btn.setEnabled(True)
        self.state_label.setText("● Recording" if recording else "")
        self.state_label.setStyleSheet("color: #e0534f; font-weight: bold;")
        self.name_input.setEnabled(not recording)

    # ---- recording -----------------------------------------------------

    def _toggle_recording(self):
        if self.worker is None:
            self._record()
        else:
            self.stop_recording()

    def _record(self):
        label = self._label or self._label_from_name()
        if label is None:
            return
        self._label = label
        self._show_label()
        self.worker = AudioWorker(label, self.app_state.get_label_duration_ms(label), self)
        self.worker.frame_recorded.connect(self.waveform.append_live_data)
        self.worker.status_updated.connect(self._on_status)
        self.worker.stream_ready.connect(self._on_stream_ready)
        self.worker.recording_finished.connect(self._on_saved)
        self.worker.failed.connect(self._on_failed)
        self.waveform.clear_display()
        self.waveform.show_message("Waiting for mic…")
        self._show_recording(True)
        self.hint.setText("")
        self.worker.start()

    def _label_from_name(self):
        """The typed name, made into a sound if it isn't one yet. None if invalid."""
        try:
            label = recordings.clean_label(self.name_input.text())
            if label not in self.app_state.get_sound_labels():
                recordings.create_label(label)
                self.sound_changed.emit(label)
        except recordings.InvalidLabel as exc:
            QMessageBox.warning(self, "Sound name", INVALID_LABEL_TEXT.get(
                exc.reason, f"Couldn't make a sound called “{self.name_input.text()}”."))
            return None
        return label

    def stop_recording(self):
        """The take saves on the worker's thread. _on_saved follows."""
        if self.worker is None or not self.record_btn.isEnabled():
            return
        self.record_btn.setEnabled(False)
        self.hint.setText("Saving…")
        self.worker.request_stop()

    def _on_stream_ready(self):
        self.waveform.clear_message()
        self.hint.setText("Space or R to stop.")

    def _on_status(self, state):
        now = time.monotonic()
        if now - self._last_status_draw < self.STATUS_REDRAW_SECONDS:
            return
        self._last_status_draw = now
        self.recorded_value.setText(duration_text(state.ms_recorded / 1000.0))
        label = state.labels[0]
        self.detected_value.setText(duration_text(label.ms_detected / 1000.0))
        # The sound's, this take included: what training will see
        quantity, _percent = get_quantity_rating(label.ms_detected + label.previous_detected)
        self.quantity_value.setText(quantity)
        self.quantity_value.setStyleSheet(
            f"color: {theme.QUANTITY_COLORS.get(quantity, theme.colors()['text_bright'])}; "
            f"font-weight: bold;")

    def _on_saved(self, wav_path, _srt_path):
        self._worker_finish()
        self._show_recording(False)
        self.waveform.clear_message()
        # Stopped before the first frame: the recorder deleted its empty wav
        if os.path.isfile(wav_path):
            self.sound_changed.emit(self._label)
            self.hint.setText("Saved. Record another take, or go back to Sounds.")
        else:
            self.hint.setText("Nothing recorded, the mic had not started yet.")
        if self._leave_when_saved:
            self._leave()

    def _on_failed(self, message):
        self._worker_finish()
        self._show_recording(False)
        self.waveform.show_message("No mic")
        QMessageBox.warning(self, "Couldn't open the microphone", message)

    def _worker_finish(self):
        """Signals arrive as run() returns, so wait before dropping the thread."""
        self.worker.wait()
        self.worker.deleteLater()
        self.worker = None
        if self._label:
            self.app_state.forget_label_duration(self._label)

    def finish_recording(self):
        """Stop and save before the app quits. A take mid-save would lose its srt."""
        if self.worker is not None:
            self.worker.request_stop()
            self.worker.wait()

    # ---- navigation ----------------------------------------------------

    def _on_back(self):
        if self.worker is None:
            self._leave()
            return
        self._leave_when_saved = True
        self.stop_recording()

    def _leave(self):
        self._leave_when_saved = False
        self.done.emit()
