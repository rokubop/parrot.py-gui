"""Audacity-style device toolbar: recording + playback device pickers.
Lives in the main toolbar; no transport controls, just device selection."""
import sounddevice as sd
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QComboBox

from gui.services import audio_devices


class DeviceBar(QWidget):
    input_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 8, 0)
        h.setSpacing(6)

        h.addWidget(QLabel("🎙"))
        self.input_combo = QComboBox()
        self.input_combo.setToolTip("Recording device")
        self.input_combo.setMaximumWidth(220)
        h.addWidget(self.input_combo)

        h.addSpacing(6)
        h.addWidget(QLabel("🔊"))
        self.output_combo = QComboBox()
        self.output_combo.setToolTip("Playback device")
        self.output_combo.setMaximumWidth(220)
        h.addWidget(self.output_combo)

        self._populate()
        self.input_combo.currentIndexChanged.connect(self._on_input_changed)
        self.output_combo.currentIndexChanged.connect(self._on_output_changed)

    def _populate(self):
        try:
            # default host API only: every device otherwise appears 3-4x
            # (MME / DirectSound / WASAPI duplicates)
            default_api = sd.default.hostapi
            devices = list(enumerate(sd.query_devices()))
        except Exception:
            return
        for i, dev in devices:
            if dev.get("hostapi") != default_api:
                continue
            if dev.get("max_input_channels", 0) > 0:
                self.input_combo.addItem(dev["name"], i)
            if dev.get("max_output_channels", 0) > 0:
                self.output_combo.addItem(dev["name"], i)
        idx = self.input_combo.findData(audio_devices.input_index)
        if idx >= 0:
            self.input_combo.setCurrentIndex(idx)
        idx = self.output_combo.findData(audio_devices.output_index)
        if idx >= 0:
            self.output_combo.setCurrentIndex(idx)

    def _on_input_changed(self, _index):
        device = self.input_combo.currentData()
        if device is not None:
            audio_devices.set_input(device)
            self.input_changed.emit(device)

    def _on_output_changed(self, _index):
        device = self.output_combo.currentData()
        if device is not None:
            audio_devices.set_output(device)
