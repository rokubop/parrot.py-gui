import numpy as np
import wave
import pyqtgraph as pg
from PyQt6.QtWidgets import QVBoxLayout, QWidget


class WaveformWidget(QWidget):
    MAX_DISPLAY_POINTS = 100000   # for a one-shot loaded file
    LIVE_DISPLAY_POINTS = 6000    # capped resolution for the live view
    LIVE_REDRAW_EVERY = 2         # redraw every N frames (~30 fps at 15 ms/frame)
    LIVE_WINDOW_SECONDS = 10      # width of the scrolling live window
    LIVE_Y_RANGE = 16000          # fixed vertical scale (int16; ~0.5 of full)

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

        # Live view behaves like a DAW recorder: a *fixed* vertical scale and a
        # fixed-width time window that scrolls to keep the record head at the
        # right edge. Auto-ranging both axes every frame (the old behavior) made
        # the waveform jump and constantly rescale, which was disorienting.
        vb = self.plot_widget.getViewBox()
        vb.disableAutoRange()
        self.plot_widget.setMouseEnabled(x=False, y=False)
        self.plot_widget.setYRange(-self.LIVE_Y_RANGE, self.LIVE_Y_RANGE, padding=0)
        self.plot_widget.setXRange(0, self.LIVE_WINDOW_SECONDS, padding=0)

        self._reset_live()

    def _reset_live(self):
        # Growable int16 buffer (amortized doubling) so appending a frame is O(1)
        # and we never rebuild an array from a growing Python list per frame.
        self._live_buf = np.empty(48000, dtype=np.int16)
        self._live_len = 0
        self._frames_since_draw = 0

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

    def append_live_data(self, frame_bytes):
        """Append live audio data during recording. Per-frame cost is constant
        regardless of how long the recording has run."""
        data = np.frombuffer(frame_bytes, dtype=np.int16)

        # Grow the buffer geometrically if needed, then copy the frame in.
        end = self._live_len + len(data)
        if end > self._live_buf.size:
            new_size = max(self._live_buf.size * 2, end)
            grown = np.empty(new_size, dtype=np.int16)
            grown[:self._live_len] = self._live_buf[:self._live_len]
            self._live_buf = grown
        self._live_buf[self._live_len:end] = data
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

        # Scroll the window so the newest sample stays at the right edge once we
        # pass the window length; before that, keep the full window in view.
        total_time = buf.size / sr
        if total_time <= self.LIVE_WINDOW_SECONDS:
            self.plot_widget.setXRange(0, self.LIVE_WINDOW_SECONDS, padding=0)
        else:
            self.plot_widget.setXRange(total_time - self.LIVE_WINDOW_SECONDS,
                                       total_time, padding=0)

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
        self.plot_widget.setYRange(-self.LIVE_Y_RANGE, self.LIVE_Y_RANGE, padding=0)
        self.plot_widget.setXRange(0, self.LIVE_WINDOW_SECONDS, padding=0)

    def get_plot_widget(self):
        """Return the internal PlotWidget for axis linking."""
        return self.plot_widget
