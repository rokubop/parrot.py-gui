"""Where playback goes, shown where you press play.

Audio pickers live where they are used. The mic picker moved into the
recording view; this is its other end, and was still only in Settings.

Visible rather than surfaced on failure, because the failure is undetectable:
a valid but inaudible output opens fine and plays into the void. Nothing can
notice that nobody heard it.
"""
import sounddevice as sd
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

from gui import theme
from gui.services import audio_devices


class OutputPicker(QWidget):
    output_changed = pyqtSignal(int)

    def __init__(self, label="Playback:", parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)

        self.caption = QLabel(label)
        self.caption.setStyleSheet(f"color: {theme.colors()['text_dim']};")
        h.addWidget(self.caption)

        self.combo = QComboBox()
        self.combo.setToolTip("Where previews play")
        self.combo.setMaximumWidth(240)
        h.addWidget(self.combo)

        self._populate()
        self.combo.currentIndexChanged.connect(self._on_changed)

    def _output_devices(self):
        """[(index, name)] for the default host API (others are duplicates)."""
        result = []
        try:
            default_api = sd.default.hostapi
            for i, dev in enumerate(sd.query_devices()):
                if dev.get("hostapi") == default_api and \
                        dev.get("max_output_channels", 0) > 0:
                    result.append((i, dev["name"]))
        except Exception:
            pass
        return result

    def _populate(self):
        self.combo.blockSignals(True)
        self.combo.clear()
        for i, name in self._output_devices():
            self.combo.addItem(name, i)
        idx = self.combo.findData(audio_devices.output_index)
        if idx >= 0:
            self.combo.setCurrentIndex(idx)
        self.combo.blockSignals(False)

    def refresh(self):
        """Indices shift when hardware changes. Blind to anything plugged in
        since launch; the mic picker's rescan is what finds that."""
        self._populate()

    def refresh_theme(self):
        self.caption.setStyleSheet(f"color: {theme.colors()['text_dim']};")

    def _on_changed(self, _index):
        device = self.combo.currentData()
        if device is None:
            return
        audio_devices.set_output(device)
        self.output_changed.emit(device)
