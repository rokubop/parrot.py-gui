from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

from gui import theme
from gui.services import audio_devices


class MicPicker(QWidget):
    input_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.caption = QLabel("Microphone:")
        self.caption.setStyleSheet(f"color: {theme.colors()['text_dim']};")
        h.addWidget(self.caption)
        self.combo = QComboBox()
        self.combo.setAccessibleName("Microphone")
        self.combo.setMaximumWidth(260)
        h.addWidget(self.combo)
        self.refresh()
        self.combo.currentIndexChanged.connect(self._on_changed)

    def refresh(self):
        """Indices shift when hardware changes. PortAudio lists only what was
        there at launch."""
        self.combo.blockSignals(True)
        self.combo.clear()
        for i, name in audio_devices.devices("max_input_channels"):
            self.combo.addItem(name, i)
        self.combo.setCurrentIndex(self.combo.findData(audio_devices.input_index))
        self.combo.blockSignals(False)

    def _on_changed(self, _index):
        device = self.combo.currentData()
        if device is not None:
            audio_devices.set_input(device)
            self.input_changed.emit(device)
