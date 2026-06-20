import numpy as np
import wave
import pyqtgraph as pg
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor


class WaveformWidget(QWidget):
    MAX_DISPLAY_POINTS = 100000   # for a one-shot loaded file
    LIVE_DISPLAY_POINTS = 6000    # capped resolution for the live view
    LIVE_REDRAW_EVERY = 2         # redraw every N frames (~30 fps at 15 ms/frame)
    LIVE_WINDOW_SECONDS = 10      # width of the scrolling live window
    LIVE_Y_RANGE = 16000          # fixed vertical scale (int16; ~0.5 of full)

    cut_point_changed = pyqtSignal()  # a cut mark was set or cleared

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel('left', 'Amplitude')
        self.plot_widget.setLabel('bottom', 'Time', units='s')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        layout.addWidget(self.plot_widget)

        # Live detection (the "blue overlay"): full-height shaded bands where the
        # recorder flagged the frame as sound, drawn with a recycled pool of
        # LinearRegionItems (same as the static waveforms). Preliminary — the
        # final regions are computed after Save.
        self._det_brush = QColor(90, 175, 245); self._det_brush.setAlpha(55)
        self._det_pen = pg.mkPen(QColor(90, 175, 245, 90))
        self._det_regions = []
        self.MAX_DET_REGIONS = 80

        # Cut mark: click the waveform to mark where to cut back to; everything
        # from there to the record head shades red and Backspace/Delete removes
        # it. Drawn above detection but below the trace.
        cut_brush = QColor(224, 83, 79); cut_brush.setAlpha(70)
        self.cut_region = pg.LinearRegionItem(
            values=[0, 0], movable=False, brush=cut_brush,
            pen=pg.mkPen(QColor(224, 83, 79), width=1))
        self.cut_region.setZValue(-3)
        self.cut_region.setVisible(False)
        self.cut_region.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        for _line in getattr(self.cut_region, "lines", []):
            _line.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.plot_widget.addItem(self.cut_region)

        self.plot_item = self.plot_widget.plot(pen=pg.mkPen(color='c', width=1))
        self._sample_rate = 48000

        # Live view behaves like a DAW recorder: a *fixed* vertical scale and a
        # fixed-width time window that scrolls to keep the record head at the
        # right edge. Auto-ranging both axes every frame (the old behavior) made
        # the waveform jump and constantly rescale, which was disorienting.
        self._vb = self.plot_widget.getViewBox()
        self._vb.disableAutoRange()
        self.plot_widget.setMouseEnabled(x=False, y=False)
        self.plot_widget.setYRange(-self.LIVE_Y_RANGE, self.LIVE_Y_RANGE, padding=0)
        self.plot_widget.setXRange(0, self.LIVE_WINDOW_SECONDS, padding=0)
        self.plot_widget.scene().sigMouseClicked.connect(self._on_click)

        self._reset_live()

    def _reset_live(self):
        # Growable int16 buffer (amortized doubling) so appending a frame is O(1)
        # and we never rebuild an array from a growing Python list per frame.
        # A parallel uint8 buffer tracks detection (1 = sound) per sample.
        self._live_buf = np.empty(48000, dtype=np.int16)
        self._det_buf = np.zeros(48000, dtype=np.uint8)
        self._live_len = 0
        self._frames_since_draw = 0
        self._cut_point = None        # seconds from start, or None
        if not hasattr(self, "_cut_enabled"):
            self._cut_enabled = False

    def load_wav(self, path):
        """Load a wav file and display its waveform."""
        self._reset_live()
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
            # Auto-range is disabled for the live view, so set both ranges here.
            self.plot_widget.setXRange(0, time_axis[-1] if len(time_axis) > 0 else 1,
                                       padding=0)
            peak = float(np.abs(data).max()) if len(data) else self.LIVE_Y_RANGE
            self.plot_widget.setYRange(-peak, peak, padding=0.05)
        except Exception:
            self.plot_item.setData([], [])

    def append_live_data(self, frame_bytes, detected=False):
        """Append live audio data during recording. Per-frame cost is constant
        regardless of how long the recording has run. ``detected`` flags whether
        the recorder classified this frame as sound (drawn as the blue overlay)."""
        data = np.frombuffer(frame_bytes, dtype=np.int16)

        # Grow both buffers geometrically if needed, then copy the frame in.
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

        # Throttle redraws; the work below is bounded by LIVE_DISPLAY_POINTS, not
        # by the recording length.
        self._frames_since_draw += 1
        if self._frames_since_draw < self.LIVE_REDRAW_EVERY:
            return
        self._frames_since_draw = 0
        self._redraw_live()

    def _redraw_live(self):
        buf = self._live_buf[:self._live_len]
        sr = self._sample_rate
        window_samples = int(self.LIVE_WINDOW_SECONDS * sr)

        # Decimate with a CONSTANT, window-based factor and align the start to
        # that grid, so the exact samples drawn don't shift frame-to-frame. A
        # buffer-based factor (the old way) re-picked different samples as the
        # buffer grew, making the whole waveform subtly wiggle while the first
        # window filled in.
        factor = max(1, window_samples // self.LIVE_DISPLAY_POINTS)
        start = max(0, buf.size - window_samples)
        start -= start % factor
        seg = buf[start::factor]
        t0 = start / sr
        step = factor / sr
        time_axis = t0 + np.arange(len(seg)) * step
        self.plot_item.setData(time_axis, seg.astype(np.float32))

        # Detection overlay: shaded bands where the frame was flagged sound.
        det = self._det_buf[start:self._live_len:factor][:len(seg)]
        self._draw_detection(time_axis, det)

        # Scroll the window so the newest sample stays at the right edge once we
        # pass the window length; before that, keep the full window in view.
        total_time = buf.size / sr
        if total_time <= self.LIVE_WINDOW_SECONDS:
            self.plot_widget.setXRange(0, self.LIVE_WINDOW_SECONDS, padding=0)
        else:
            self.plot_widget.setXRange(total_time - self.LIVE_WINDOW_SECONDS,
                                       total_time, padding=0)

        # Keep the cut band stretched to the current record head.
        if self._cut_point is not None:
            self._update_cut_region()

    def _draw_detection(self, time_axis, det):
        """Shade contiguous detected runs using a recycled region pool."""
        runs = []
        n = len(time_axis)
        if det.size and n:
            d = (det > 0).astype(np.int8)
            diffs = np.diff(np.concatenate(([0], d, [0])))
            starts = np.where(diffs == 1)[0]
            ends = np.where(diffs == -1)[0]
            for s, e in zip(starts, ends):
                if s >= n:
                    break
                ts, te = time_axis[s], time_axis[min(e, n - 1)]
                if te > ts:
                    runs.append((ts, te))
        runs = runs[:self.MAX_DET_REGIONS]
        for i, (ts, te) in enumerate(runs):
            if i >= len(self._det_regions):
                reg = pg.LinearRegionItem(movable=False, brush=self._det_brush,
                                          pen=self._det_pen)
                reg.setZValue(-10)
                reg.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                for _line in getattr(reg, "lines", []):
                    _line.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                self.plot_widget.addItem(reg)
                self._det_regions.append(reg)
            self._det_regions[i].setRegion((ts, te))
            self._det_regions[i].setVisible(True)
        for j in range(len(runs), len(self._det_regions)):
            self._det_regions[j].setVisible(False)

    def drop_last_seconds(self, seconds):
        """Remove the most recent N seconds from the live view (mirrors the
        recorder's 'clear last N seconds' so the waveform reflects the cut)."""
        drop = int(seconds * self._sample_rate)
        self._live_len = max(0, self._live_len - drop)
        self._redraw_live()

    def set_trace_color(self, color):
        """Recolor the live trace (used to signal recording / paused / idle)."""
        self.plot_item.setPen(pg.mkPen(color=color, width=1))

    def clear_display(self):
        """Clear the waveform display."""
        self._reset_live()
        self.plot_item.setData([], [])
        for reg in self._det_regions:
            reg.setVisible(False)
        self.cut_region.setVisible(False)
        self.plot_widget.setYRange(-self.LIVE_Y_RANGE, self.LIVE_Y_RANGE, padding=0)
        self.plot_widget.setXRange(0, self.LIVE_WINDOW_SECONDS, padding=0)

    # ---- cut mark (click to mark where to cut back to) ----------------

    def total_seconds(self):
        return self._live_len / self._sample_rate if self._sample_rate else 0.0

    def get_cut_point(self):
        return self._cut_point

    def set_cut_point(self, seconds):
        total = self.total_seconds()
        self._cut_point = max(0.0, min(seconds, total))
        self._update_cut_region()
        self.cut_region.setVisible(True)
        self.cut_point_changed.emit()

    def clear_cut_point(self):
        had = self._cut_point is not None
        self._cut_point = None
        self.cut_region.setVisible(False)
        if had:
            self.cut_point_changed.emit()

    def _update_cut_region(self):
        if self._cut_point is None:
            return
        self.cut_region.setRegion([self._cut_point, self.total_seconds()])

    def set_cut_enabled(self, enabled):
        """Allow/disallow click-to-mark. Off by default — the live recording
        view is a plain monitor; editing happens on the saved clip."""
        self._cut_enabled = enabled

    def _on_click(self, event):
        if not self._cut_enabled:
            return
        if event.button() != Qt.MouseButton.LeftButton or event.double():
            return
        if self._live_len == 0:
            return
        x = self._vb.mapSceneToView(event.scenePos()).x()
        self.set_cut_point(x)

    def get_plot_widget(self):
        """Return the internal PlotWidget for axis linking."""
        return self.plot_widget
