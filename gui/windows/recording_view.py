"""Dedicated recording view.

A focused, Audacity-like capture screen reached from the Sounds tab ("Add
recording" / "New sound"). Shows a live waveform and a live detection readout
(time, sound quality from SNR, dBFS, noise floor, and per-sound detected time +
data-quantity rating) so the GUI is at least as informative as the terminal
recorder. Controls: Record / Pause / Clear last 3s / Stop, plus device and
detection-strategy selection.
"""
import time
import sounddevice as sd
from PyQt6.QtCore import Qt, QElapsedTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QComboBox,
    QLineEdit, QGroupBox, QFormLayout, QMessageBox
)

from config.config import INPUT_DEVICE_INDEX
from gui import theme
from gui.widgets.waveform import WaveformWidget
from gui.widgets.audio_preview import AudioPreviewWidget
from gui.workers.audio_worker import AudioWorker
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
    done = pyqtSignal(str)   # finished/closed; arg = label to select (may be "")

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.worker = None
        self._label = None
        self._new_mode = False
        self._paused = False
        self._last_status_draw = 0.0
        self._setup_ui()

    # ---- entry points (called by MainWindow) --------------------------

    def start_for(self, label):
        """Add a recording to an existing sound."""
        self._new_mode = False
        self._label = label
        self.name_row.setVisible(False)
        self.title.setText(f"Record:  {label}")
        self._reset()

    def start_new(self):
        """Create a brand-new sound by recording it."""
        self._new_mode = True
        self._label = None
        self.name_row.setVisible(True)
        self.name_input.clear()
        self.title.setText("New sound")
        self._reset()

    # ---- ui ------------------------------------------------------------

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        # Top: back + title
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
        root.addLayout(top)

        # New-sound name row (hidden in add-recording mode)
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

        # Center: live waveform (left) + status panel (right)
        center = QHBoxLayout()
        left = QVBoxLayout()
        self.waveform = WaveformWidget()
        left.addWidget(self.waveform)
        # After a take, the segmented result is shown here instead.
        self.result_preview = AudioPreviewWidget()
        self.result_preview.setVisible(False)
        left.addWidget(self.result_preview)
        center.addLayout(left, 3)
        center.addWidget(self._build_status_panel(), 1)
        root.addLayout(center, 1)

        # Controls
        controls = QHBoxLayout()
        self.record_btn = QPushButton("● Record")
        self.record_btn.clicked.connect(self._on_record)
        controls.addWidget(self.record_btn)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._on_pause)
        controls.addWidget(self.pause_btn)
        self.clear_btn = QPushButton("Clear last 3s")
        self.clear_btn.setEnabled(False)
        self.clear_btn.setToolTip("Drop the last 3 seconds (e.g. a mistake)")
        self.clear_btn.clicked.connect(self._on_clear)
        controls.addWidget(self.clear_btn)
        self.stop_btn = QPushButton("■ Stop & save")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop)
        controls.addWidget(self.stop_btn)
        controls.addStretch()
        self.hint = QLabel("")
        self.hint.setStyleSheet(f"color: {theme.colors()['text_dim']};")
        controls.addWidget(self.hint)
        root.addLayout(controls)

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

    def _reset(self):
        self.waveform.clear_display()
        self.waveform.setVisible(True)
        self.result_preview.setVisible(False)
        self._paused = False
        self.record_btn.setEnabled(True)
        self.record_btn.setText("● Record")
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("Pause")
        self.clear_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        for w in (self.v_time, self.v_quality, self.v_dbfs, self.v_noise,
                  self.v_snr, self.v_detected, self.v_quantity, self.v_type):
            w.setText("—")
        self.hint.setText("")

    # ---- recording lifecycle ------------------------------------------

    def _resolve_label(self):
        if self._new_mode:
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

    def _on_record(self):
        label = self._resolve_label()
        if not label:
            return
        self._label = label
        # Lock the name once we start so the file lands in the right place.
        self.name_input.setEnabled(False)
        mic = self.device_combo.currentData()
        strategy = strategies.strategy_for_label(self.strategy_combo.currentText())

        self.waveform.clear_display()
        self.waveform.setVisible(True)
        self.result_preview.setVisible(False)

        self.worker = AudioWorker(label, mic, strategy)
        self.worker.frame_recorded.connect(self.waveform.append_live_data)
        self.worker.status_updated.connect(self._on_status)
        self.worker.recording_finished.connect(self._on_finished)
        self.worker.start()

        self.record_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.clear_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        self.hint.setText("Recording… make your sound, with silence between repeats.")

    def _on_pause(self):
        if not self.worker:
            return
        self.worker.request_pause()
        self._paused = not self._paused
        self.pause_btn.setText("Resume" if self._paused else "Pause")
        self.hint.setText("Paused." if self._paused else "Recording…")

    def _on_clear(self):
        if self.worker:
            self.worker.request_clear()
            self.hint.setText("Dropped the last 3 seconds.")

    def _on_stop(self):
        if self.worker:
            self.stop_btn.setEnabled(False)
            self.pause_btn.setEnabled(False)
            self.clear_btn.setEnabled(False)
            self.hint.setText("Saving & segmenting…")
            self.worker.request_stop()

    def _on_status(self, state):
        # Throttle: status fires every ~15 ms; redraw the readout ~8x/sec.
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

    def _on_finished(self, wav_path, srt_path):
        self.worker = None
        # Surface the segmented take and let the library/list pick it up.
        self.app_state.recordings_changed.emit()
        self.waveform.setVisible(False)
        self.result_preview.setVisible(True)
        try:
            self.result_preview.load(wav_path, srt_path)
            self.result_preview.fit_full()
        except Exception:
            pass
        self.record_btn.setEnabled(True)
        self.record_btn.setText("● Record another")
        self.name_input.setEnabled(True)
        self.hint.setText("Saved. Record another take, or go back to Sounds.")

    # ---- navigation ----------------------------------------------------

    def _on_back(self):
        self.stop_worker()
        self.done.emit(self._label or "")

    def stop_worker(self):
        if self.worker:
            self.worker.request_stop()
            self.worker.wait(2000)
            self.worker = None

    def refresh_theme(self):
        pass
