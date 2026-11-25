"""Where playback goes, shown where you press play. Visible rather than
reported on failure: an inaudible output opens fine and plays into the void."""
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

from gui import theme
from gui.services import audio_devices


class OutputPicker(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.caption = QLabel("Playback:")
        self.caption.setStyleSheet(f"color: {theme.colors()['text_dim']};")
        h.addWidget(self.caption)
        self.combo = QComboBox()
        self.combo.setAccessibleName("Playback device")
        self.combo.setMaximumWidth(240)
        h.addWidget(self.combo)
        self.refresh()
        self.combo.currentIndexChanged.connect(self._on_changed)

    def showEvent(self, event):
        # The recording view and Sounds each have one, and either may have changed it
        self.refresh()
        super().showEvent(event)

    def refresh(self):
        self.combo.blockSignals(True)
        self.combo.clear()
        for i, name in audio_devices.devices("max_output_channels"):
            self.combo.addItem(name, i)
        self.combo.setCurrentIndex(self.combo.findData(audio_devices.output_index))
        self.combo.blockSignals(False)

    def _on_changed(self, _index):
        device = self.combo.currentData()
        if device is not None:
            audio_devices.set_output(device)
