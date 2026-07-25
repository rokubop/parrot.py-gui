"""Persistent transport strip under the main toolbar: mic picker, live level
meter, record/play. Prototype to feel out an always-present audio surface.

Record and play delegate to the Sounds page context (selected sound / card);
the meter runs its own lightweight monitor stream and must be stopped by the
main window whenever another view needs the mic.
"""
import numpy as np
import sounddevice as sd
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QComboBox, QSizePolicy
)

from config.config import RATE, INPUT_DEVICE_INDEX
from gui import theme


class LevelMeter(QWidget):
    """Horizontal RMS bar with a slow-decay peak tick."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(140, 14)
        self._level = 0.0   # 0..1
        self._peak = 0.0

    def set_level(self, level):
        self._level = max(0.0, min(1.0, level))
        self._peak = max(self._peak * 0.95, self._level)
        self.update()

    def clear(self):
        self._level = 0.0
        self._peak = 0.0
        self.update()

    def paintEvent(self, _event):
        t = theme.colors()
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(t["base"]))
        filled = int(w * self._level)
        if filled > 0:
            color = QColor(t["accent"]) if self._level < 0.85 else QColor("#e0b020")
            p.fillRect(0, 2, filled, h - 4, color)
        peak_x = int(w * self._peak)
        if peak_x > 1:
            p.fillRect(peak_x - 1, 0, 2, h, QColor(t["text_bright"]))
        p.setPen(QColor(t["border"]))
        p.drawRect(0, 0, w - 1, h - 1)
        p.end()


class TransportBar(QWidget):
    record_clicked = pyqtSignal()
    play_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stream = None
        self._level = 0.0

        h = QHBoxLayout(self)
        h.setContentsMargins(12, 4, 12, 4)
        h.setSpacing(10)

        self.record_btn = QPushButton("●  Record")
        self.record_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.record_btn.setToolTip("Record a session for the selected sound")
        self.record_btn.clicked.connect(self.record_clicked)
        h.addWidget(self.record_btn)

        self.play_btn = QPushButton("▶  Play")
        self.play_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.play_btn.setToolTip("Play/pause the selected recording (Sounds page)")
        self.play_btn.clicked.connect(self.play_clicked)
        h.addWidget(self.play_btn)

        h.addSpacing(8)
        self.mic_combo = QComboBox()
        self.mic_combo.setMinimumWidth(220)
        self.mic_combo.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self._populate_mics()
        self.mic_combo.currentIndexChanged.connect(self._on_mic_changed)
        h.addWidget(self.mic_combo)

        self.monitor_btn = QPushButton("Monitor")
        self.monitor_btn.setCheckable(True)
        self.monitor_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.monitor_btn.setToolTip("Live input level from the selected mic")
        self.monitor_btn.toggled.connect(self._on_monitor_toggled)
        h.addWidget(self.monitor_btn)

        self.meter = LevelMeter()
        h.addWidget(self.meter)
        h.addStretch()

        # meter repaints on a timer; the audio callback only stores a number
        self._meter_timer = QTimer(self)
        self._meter_timer.setInterval(33)
        self._meter_timer.timeout.connect(lambda: self.meter.set_level(self._level))

        self._apply_theme_styles()

    def _apply_theme_styles(self):
        t = theme.colors()
        self.setStyleSheet(
            f"TransportBar {{ background-color: {t['toolbar']}; "
            f"border-bottom: 1px solid {t['border']}; }}")
        self.record_btn.setStyleSheet(f"color: #e05a5a; font-weight: bold;")

    def refresh_theme(self):
        self._apply_theme_styles()

    # ---- mic monitoring --------------------------------------------------

    def _populate_mics(self):
        self.mic_combo.blockSignals(True)
        self.mic_combo.clear()
        try:
            # default host API only: every device otherwise appears 3-4x
            # (MME / DirectSound / WASAPI duplicates)
            default_api = sd.default.hostapi
            for i, dev in enumerate(sd.query_devices()):
                if dev.get("max_input_channels", 0) > 0 and \
                        dev.get("hostapi") == default_api:
                    self.mic_combo.addItem(dev["name"], i)
        except Exception:
            pass
        idx = self.mic_combo.findData(INPUT_DEVICE_INDEX)
        if idx >= 0:
            self.mic_combo.setCurrentIndex(idx)
        self.mic_combo.blockSignals(False)

    def current_mic_index(self):
        return self.mic_combo.currentData()

    def _on_mic_changed(self, _index):
        if self.monitor_btn.isChecked():
            self._stop_stream()
            self._start_stream()

    def _on_monitor_toggled(self, on):
        if on:
            self._start_stream()
        else:
            self._stop_stream()

    def _start_stream(self):
        device = self.current_mic_index()
        if device is None:
            self.monitor_btn.setChecked(False)
            return

        def callback(indata, _frames, _time, _status):
            samples = indata[:, 0].astype(np.float32) / 32768.0
            rms = float(np.sqrt(np.mean(samples * samples)))
            # ~4x gain so normal speech reads mid-meter
            self._level = min(1.0, rms * 4.0)

        try:
            self._stream = sd.InputStream(
                samplerate=RATE, channels=1, dtype="int16",
                device=device, blocksize=1024, callback=callback)
            self._stream.start()
            self._meter_timer.start()
        except Exception:
            self._stream = None
            self.monitor_btn.setChecked(False)

    def _stop_stream(self):
        self._meter_timer.stop()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._level = 0.0
        self.meter.clear()

    def stop_monitor(self):
        """Release the mic (called when another view needs the device)."""
        self.monitor_btn.setChecked(False)
