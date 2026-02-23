import numpy as np
import wave
import pyqtgraph as pg
from PyQt6.QtWidgets import QVBoxLayout, QWidget


class WaveformWidget(QWidget):
    MAX_DISPLAY_POINTS = 100000

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel('left', 'Amplitude')
        self.plot_widget.setLabel('bottom', 'Time', units='s')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        layout.addWidget(self.plot_widget)

        self.plot_item = self.plot_widget.plot(pen=pg.mkPen(color='c', width=1))
        self._sample_rate = 48000
        self._live_data = []

    def load_wav(self, path):
        """Load a wav file and display its waveform."""
        self._live_data = []
        try:
            wf = wave.open(path, 'rb')
            n_frames = wf.getnframes()
            self._sample_rate = wf.getframerate()
            raw = wf.readframes(n_frames)
            wf.close()

            data = np.frombuffer(raw, dtype=np.int16).astype(np.float32)

            # Downsample for display if needed
            if len(data) > self.MAX_DISPLAY_POINTS:
                factor = len(data) // self.MAX_DISPLAY_POINTS
                data = data[::factor]
                effective_rate = self._sample_rate / factor
            else:
                effective_rate = self._sample_rate

            time_axis = np.arange(len(data)) / effective_rate
            self.plot_item.setData(time_axis, data)
            self.plot_widget.setXRange(0, time_axis[-1] if len(time_axis) > 0 else 1)
        except Exception:
            self.plot_item.setData([], [])

    def append_live_data(self, frame_bytes):
        """Append live audio data during recording."""
        data = np.frombuffer(frame_bytes, dtype=np.int16).astype(np.float32)
        self._live_data.extend(data.tolist())

        display = np.array(self._live_data)
        if len(display) > self.MAX_DISPLAY_POINTS:
            factor = len(display) // self.MAX_DISPLAY_POINTS
            display = display[::factor]
            effective_rate = self._sample_rate / factor
        else:
            effective_rate = self._sample_rate

        time_axis = np.arange(len(display)) / effective_rate
        self.plot_item.setData(time_axis, display)

    def clear_display(self):
        """Clear the waveform display."""
        self._live_data = []
        self.plot_item.setData([], [])

    def get_plot_widget(self):
        """Return the internal PlotWidget for axis linking."""
        return self.plot_widget
