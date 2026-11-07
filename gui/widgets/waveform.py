import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QGridLayout, QLabel, QWidget
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from config.config import RATE
from gui import theme


class WaveformWidget(QWidget):
    """The take as it records, scrolling like a DAW: fixed vertical scale, the
    newest sample at the right edge. Frames detected as sound are shaded."""

    LIVE_DISPLAY_POINTS = 6000    # capped resolution for the live view
    LIVE_REDRAW_EVERY = 2         # redraw every N frames (~30 fps at 15 ms/frame)
    LIVE_WINDOW_SECONDS = 10      # width of the scrolling live window
    LIVE_Y_RANGE = 16000          # fixed vertical scale (int16; ~0.5 of full)
    MAX_DETECTION_REGIONS = 160

    def __init__(self, parent=None):
        super().__init__(parent)
        # A grid so the message shares the plot's cell and stays centred on it
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.plot_widget = pg.PlotWidget(background=theme.colors()["plot_bg"])
        # a plot keeps Tab for itself, so Tab could never leave it
        self.plot_widget.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.plot_widget.setLabel('left', 'Amplitude')
        self.plot_widget.setLabel('bottom', 'Time', units='s')
        self.plot_widget.showGrid(x=True, y=True, alpha=theme.colors()["grid_alpha"])
        layout.addWidget(self.plot_widget, 0, 0)

        # Over the plot while there is nothing to draw yet, e.g. waiting for the mic
        self.message = QLabel("")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.message.setVisible(False)
        layout.addWidget(self.message, 0, 0)

        t = theme.colors()
        self._detection_brush = QColor(*t["detect_brush"])
        self._detection_pen = pg.mkPen(QColor(*t["detect_pen"]))
        self._detection_regions = []

        self.provisional = pg.TextItem(color=QColor(*t["detect_pen"]), anchor=(0, 0))
        self.provisional.setText("provisional until you stop")
        self.provisional.setZValue(25)
        self.provisional.setVisible(False)
        self.plot_widget.addItem(self.provisional)

        self.plot_item = self.plot_widget.plot(pen=pg.mkPen(color=t["wave"], width=1))

        self._vb = self.plot_widget.getViewBox()
        self._vb.disableAutoRange()
        self.plot_widget.setMouseEnabled(x=False, y=False)
        self.clear_display()

    def _reset_live(self):
        # Growable buffers (amortized doubling) so appending a frame is O(1).
        # The uint8 one flags detection (1 = sound) per sample.
        self._live_buf = np.empty(48000, dtype=np.int16)
        self._det_buf = np.zeros(48000, dtype=np.uint8)
        self._live_len = 0
        self._frames_since_draw = 0

    def append_live_data(self, frame_bytes, detected=False):
        """Per-frame cost is constant, however long the take has run."""
        data = np.frombuffer(frame_bytes, dtype=np.int16)

        end = self._live_len + len(data)
        if end > self._live_buf.size:
            new_size = max(self._live_buf.size * 2, end)
            grown = np.empty(new_size, dtype=np.int16)
            grown[:self._live_len] = self._live_buf[:self._live_len]
            self._live_buf = grown
            grown_det = np.zeros(new_size, dtype=np.uint8)
            grown_det[:self._live_len] = self._det_buf[:self._live_len]
            self._det_buf = grown_det
        self._live_buf[self._live_len:end] = data
        self._det_buf[self._live_len:end] = 1 if detected else 0
        self._live_len = end

        self._frames_since_draw += 1
        if self._frames_since_draw < self.LIVE_REDRAW_EVERY:
            return
        self._frames_since_draw = 0
        self._redraw_live()

    def _redraw_live(self):
        buf = self._live_buf[:self._live_len]
        window_samples = int(self.LIVE_WINDOW_SECONDS * RATE)

        # Decimate by a window-based factor on a fixed grid, so the samples drawn
        # don't shift frame to frame and the waveform doesn't wiggle
        factor = max(1, window_samples // self.LIVE_DISPLAY_POINTS)
        start = max(0, buf.size - window_samples)
        start -= start % factor
        seg = buf[start::factor]
        time_axis = start / RATE + np.arange(len(seg)) * factor / RATE
        self.plot_item.setData(time_axis, seg.astype(np.float32))

        det = self._det_buf[start:self._live_len:factor][:len(seg)]
        self._draw_detection(time_axis, det)

        total_time = buf.size / RATE
        if total_time <= self.LIVE_WINDOW_SECONDS:
            self.plot_widget.setXRange(0, self.LIVE_WINDOW_SECONDS, padding=0)
        else:
            self.plot_widget.setXRange(total_time - self.LIVE_WINDOW_SECONDS, total_time, padding=0)

    def _draw_detection(self, time_axis, det):
        """Shade contiguous detected runs, from a recycled pool of regions."""
        runs = []
        n = len(time_axis)
        if det.size and n:
            diffs = np.diff(np.concatenate(([0], (det > 0).astype(np.int8), [0])))
            starts = np.where(diffs == 1)[0]
            ends = np.where(diffs == -1)[0]
            for s, e in zip(starts, ends):
                if s >= n:
                    break
                ts, te = time_axis[s], time_axis[min(e, n - 1)]
                if te > ts:
                    runs.append((ts, te))
        # Merge runs under a pixel apart, or a dense take runs past the cap
        # and its tail goes unshaded
        if runs:
            span = time_axis[-1] - time_axis[0] if len(time_axis) > 1 else 0.0
            min_gap = span / max(1, self.plot_widget.width())
            merged = [list(runs[0])]
            for ts, te in runs[1:]:
                if ts - merged[-1][1] <= min_gap:
                    merged[-1][1] = te
                else:
                    merged.append([ts, te])
            runs = merged
        runs = runs[:self.MAX_DETECTION_REGIONS]
        for i, (ts, te) in enumerate(runs):
            if i >= len(self._detection_regions):
                region = pg.LinearRegionItem(movable=False, brush=self._detection_brush,
                                             pen=self._detection_pen)
                region.setZValue(-10)
                region.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                for line in region.lines:
                    line.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                self.plot_widget.addItem(region)
                self._detection_regions.append(region)
            self._detection_regions[i].setRegion((ts, te))
            self._detection_regions[i].setVisible(True)
        for region in self._detection_regions[len(runs):]:
            region.setVisible(False)
        self.provisional.setVisible(bool(runs))
        if runs:
            self.provisional.setPos(self._vb.viewRange()[0][0], self.LIVE_Y_RANGE)

    def show_message(self, text):
        """Mutes the plot, with `text` over it."""
        self.message.setText(text)
        # A neutral scrim reads on a dark plot and a light one
        self.message.setStyleSheet(
            f"color: {theme.colors()['text_dim']}; font-weight: bold;"
            " background: rgba(128, 128, 128, 0.14);")
        self.message.setVisible(True)
        self.message.raise_()

    def clear_message(self):
        self.message.setVisible(False)

    def clear_display(self):
        self._reset_live()
        self.plot_item.setData([], [])
        for region in self._detection_regions:
            region.setVisible(False)
        self.provisional.setVisible(False)
        self.plot_widget.setYRange(-self.LIVE_Y_RANGE, self.LIVE_Y_RANGE, padding=0)
        self.plot_widget.setXRange(0, self.LIVE_WINDOW_SECONDS, padding=0)
