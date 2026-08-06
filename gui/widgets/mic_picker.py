"""Mic picker for the recording view: primary mic combo + extras menu.

Primary mic is the combo; a "+" menu checks extra mics for simultaneous
multi-mic recording (each records to its own file). Selections persist via
audio_devices, so the live test dialogs follow the same primary mic.
"""
import sounddevice as sd
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QComboBox, QPushButton, QMenu

from gui.services import audio_devices


class MicPicker(QWidget):
    input_changed = pyqtSignal(int)
    extras_changed = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)

        self.input_combo = QComboBox()
        self.input_combo.setToolTip("Recording device")
        self.input_combo.setMaximumWidth(260)
        h.addWidget(self.input_combo)

        self.extras_btn = QPushButton("+")
        self.extras_btn.setToolTip("Record with additional mics at the same time")
        self.extras_btn.setMaximumWidth(48)
        self.extras_btn.clicked.connect(self._show_extras_menu)
        h.addWidget(self.extras_btn)

        self._populate()
        self._update_extras_button()
        self.input_combo.currentIndexChanged.connect(self._on_input_changed)

    def _input_devices(self):
        """[(index, name)] for the default host API (others are duplicates)."""
        result = []
        try:
            default_api = sd.default.hostapi
            for i, dev in enumerate(sd.query_devices()):
                if dev.get("hostapi") == default_api and \
                        dev.get("max_input_channels", 0) > 0:
                    result.append((i, dev["name"]))
        except Exception:
            pass
        return result

    def _populate(self):
        self.input_combo.blockSignals(True)
        self.input_combo.clear()
        for i, name in self._input_devices():
            self.input_combo.addItem(name, i)
        idx = self.input_combo.findData(audio_devices.input_index)
        if idx >= 0:
            self.input_combo.setCurrentIndex(idx)
        self.input_combo.blockSignals(False)

    def refresh(self):
        """Re-enumerate devices - indices shift when hardware changes."""
        self._populate()
        self._update_extras_button()

    # ---- extras ----------------------------------------------------------

    def _show_extras_menu(self):
        primary = self.input_combo.currentData()
        menu = QMenu(self)
        menu.addSection("Also record with")
        for i, name in self._input_devices():
            if i == primary:
                continue
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(i in audio_devices.extra_input_indices)
            action.toggled.connect(
                lambda on, dev=i: self._set_extra(dev, on))
        menu.exec(self.extras_btn.mapToGlobal(self.extras_btn.rect().bottomLeft()))

    def _set_extra(self, device, on):
        extras = [i for i in audio_devices.extra_input_indices if i != device]
        if on:
            extras.append(device)
        audio_devices.set_extras(extras)
        self._update_extras_button()
        self.extras_changed.emit(extras)

    def _update_extras_button(self):
        extras = audio_devices.extra_input_indices
        self.extras_btn.setText(f"+{len(extras)}" if extras else "+")
        if extras:
            names = ", ".join(audio_devices.input_name(i) for i in extras)
            self.extras_btn.setToolTip(f"Also recording with: {names}")
        else:
            self.extras_btn.setToolTip(
                "Record with additional mics at the same time")

    # ---- primary ---------------------------------------------------------

    def _on_input_changed(self, _index):
        device = self.input_combo.currentData()
        if device is not None:
            audio_devices.set_input(device)
            self._update_extras_button()   # primary may have been an extra
            self.input_changed.emit(device)
