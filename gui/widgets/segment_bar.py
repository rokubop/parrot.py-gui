import numpy as np
import wave
import pyqtgraph as pg
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from PyQt6.QtGui import QColor
from lib.srt import parse_srt_file
from config.config import RECORD_SECONDS, SLIDING_WINDOW_AMOUNT
import math


class SegmentBarWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(60)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel('left', '')
        self.plot_widget.setLabel('bottom', '')
        self.plot_widget.hideAxis('left')
        self.plot_widget.setYRange(0, 1)
        self.plot_widget.setMouseEnabled(x=True, y=False)
        layout.addWidget(self.plot_widget)

        self.bar_item = None

    def load_srt(self, srt_path, wav_path):
        """Parse SRT file and display segments as green bars."""
        self.plot_widget.clear()
        self.bar_item = None

        if srt_path is None:
            return

        try:
            ms_per_frame = math.floor(RECORD_SECONDS / SLIDING_WINDOW_AMOUNT * 1000)
            events = parse_srt_file(srt_path, ms_per_frame, show_errors=False)

            # Get wav duration for x-axis range
            wf = wave.open(wav_path, 'rb')
            duration_s = wf.getnframes() / wf.getframerate()
            wf.close()

            if not events:
                self.plot_widget.setXRange(0, duration_s)
                return

            # Build bar segments from transition events
            x_starts = []
            widths = []
            for i, event in enumerate(events):
                if event.label != "silence":
                    start_s = event.start_ms / 1000.0
                    # Find end: next event's start or end of file
                    if i + 1 < len(events):
                        end_s = events[i + 1].start_ms / 1000.0
                    else:
                        end_s = duration_s
                    x_starts.append(start_s)
                    widths.append(end_s - start_s)

            if x_starts:
                self.bar_item = pg.BarGraphItem(
                    x0=x_starts, width=widths,
                    height=[1.0] * len(x_starts), y0=[0.0] * len(x_starts),
                    brush=QColor(0, 200, 0, 150),
                    pen=pg.mkPen(None)
                )
                self.plot_widget.addItem(self.bar_item)

            self.plot_widget.setXRange(0, duration_s)

        except Exception:
            pass

    def clear_display(self):
        """Clear segments."""
        self.plot_widget.clear()
        self.bar_item = None

    def link_x_axis(self, waveform_widget):
        """Sync x-axis with waveform widget."""
        self.plot_widget.setXLink(waveform_widget.get_plot_widget())

    def get_plot_widget(self):
        return self.plot_widget
