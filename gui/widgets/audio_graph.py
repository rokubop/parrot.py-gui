import math
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QVBoxLayout, QWidget, QScrollBar
from lib.srt import parse_srt_file
from gui.services.wav_files import read_wav, UnreadableWav
from config.config import RECORD_SECONDS, SLIDING_WINDOW_AMOUNT
from gui import theme
from gui.timing import debounced

_MS_PER_FRAME = math.floor(RECORD_SECONDS / SLIDING_WINDOW_AMOUNT * 1000)

# What the graph shows, set with set_mode()
WAVEFORM = "waveform"
SPECTROGRAM = "spectrogram"

pg.setConfigOptions(antialias=True)



class AudioGraph(QWidget):
    """A recording as a waveform or a spectrogram, with detection shaded over
    it. Both views share the time axis.

    Zoom and pan are X only. The waveform is re-rendered as a min/max envelope
    whenever the view changes, so detail sharpens on zoom instead of aliasing.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._samples = None      # mono float32 in [-1, 1]
        self._sample_rate = None
        self._duration = 0.0
        self._peak = 0.0          # max abs sample, for normalizing the view
        self._normalized = False
        self._mode = WAVEFORM
        self._spectrogram = None  # cached (image, levels)

        t = theme.colors()
        self._colors = t

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.plot = pg.PlotWidget(background=t["plot_bg"])
        self.plot.setLabel("bottom", "Time", units="s")
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        # Nothing to do with the keyboard, and no ring to show it had focus
        self.plot.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.plot.setMouseEnabled(x=True, y=False)
        self.plot.showGrid(x=True, y=False, alpha=t["grid_alpha"])
        layout.addWidget(self.plot)

        # Shown only when zoomed in. A fixed-height row, so showing it never
        # shifts the plot above.
        self._scroll_scale = 1000.0  # view seconds <-> scrollbar units (ms)
        self._updating_scroll = False
        self._scroll_row = QWidget()
        self._scroll_row.setFixedHeight(14)
        scroll_layout = QVBoxLayout(self._scroll_row)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.hscroll = QScrollBar(Qt.Orientation.Horizontal)
        self.hscroll.setVisible(False)
        self.hscroll.valueChanged.connect(self._on_hscroll)
        scroll_layout.addWidget(self.hscroll)
        layout.addWidget(self._scroll_row)

        self._vb = self.plot.getViewBox()
        # Wheel zooms time over the left axis too, so there's no dead zone
        self.plot.getAxis("left").wheelEvent = self._vb.wheelEvent

        # Filled waveform: the min/max envelope between two curves
        pen = pg.mkPen(QColor(*t["wave"]), width=1)
        self._max_curve = self.plot.plot(pen=pen)
        self._min_curve = self.plot.plot(pen=pen)
        self._fill = pg.FillBetweenItem(self._max_curve, self._min_curve,
                                        brush=QColor(*t["wave_fill"]))
        self.plot.addItem(self._fill)

        self._image = pg.ImageItem()
        self._image.setVisible(False)
        self.plot.addItem(self._image)

        self._regions = []

        # Hover crosshair and time readout
        cursor_pen = pg.mkPen(QColor(t["text_dim"]), width=1, style=Qt.PenStyle.DashLine)
        self.cursor = pg.InfiniteLine(pos=0, angle=90, movable=False, pen=cursor_pen)
        self.cursor.setZValue(15)
        self.cursor.setVisible(False)
        self.plot.addItem(self.cursor)
        self.readout = pg.TextItem(color=QColor(t["text_bright"]), anchor=(0, 1))
        self.readout.setZValue(16)
        self.readout.setVisible(False)
        self.plot.addItem(self.readout)
        self.plot.scene().sigMouseMoved.connect(self._on_mouse_moved)

        # Redraw once zooming or panning settles
        self._render_when_settled = debounced(
            self._render_waveform, wait_ms=15, owner=self)
        self._vb.sigXRangeChanged.connect(self._render_when_settled)
        self._vb.sigXRangeChanged.connect(lambda *_: self._sync_scrollbar())

        self.plot.scene().sigMouseClicked.connect(self._on_clicked)

    # ---- loading -------------------------------------------------------

    def load(self, wav_path, srt_path):
        """Why the wav can't be read, or None once it's on the plot."""
        self._spectrogram = None
        try:
            self._samples, self._sample_rate = read_wav(wav_path)
        except UnreadableWav as exc:
            return str(exc)
        self._peak = float(np.abs(self._samples).max()) if len(self._samples) else 0.0
        # From the samples, not the header: some recordings store a byte
        # count in nframes, which doubles the length.
        self._duration = len(self._samples) / self._sample_rate if self._sample_rate else 0.0

        self.plot.setLimits(xMin=0, xMax=self._duration)
        self._vb.setXRange(0.0, self._duration, padding=0)
        self._apply_y_range()
        self.load_regions(srt_path)
        self._render_waveform()
        return None

    def load_regions(self, srt_path):
        """Draw the detection overlay."""
        for region in self._regions:
            self.plot.removeItem(region)
        self._regions = []
        if not srt_path:
            return
        try:
            events = parse_srt_file(srt_path, _MS_PER_FRAME, show_errors=False)
        except Exception:
            return
        for i, event in enumerate(events):
            if event.label == "silence":
                continue
            start = event.start_ms / 1000.0
            end = events[i + 1].start_ms / 1000.0 if i + 1 < len(events) else self._duration
            region = pg.LinearRegionItem(
                values=[start, end], movable=False,
                brush=QColor(*self._colors["detect_brush"]),
                pen=pg.mkPen(QColor(*self._colors["detect_pen"])),
            )
            region.setZValue(-10)
            self.plot.addItem(region)
            self._regions.append(region)

    # ---- view mode -----------------------------------------------------

    def set_mode(self, mode):
        if mode == self._mode:
            return
        self._mode = mode
        is_wave = mode == WAVEFORM
        self._max_curve.setVisible(is_wave)
        self._min_curve.setVisible(is_wave)
        self._fill.setVisible(is_wave)
        self._image.setVisible(not is_wave)
        if is_wave:
            self.plot.setLabel("left", "")
            self._apply_y_range()
            self._render_waveform()
        else:
            self._render_spectrogram()

    def set_normalized(self, normalized):
        self._normalized = normalized
        if self._mode == WAVEFORM:
            self._apply_y_range()

    def _apply_y_range(self):
        if self._normalized and self._peak > 0:
            lim = max(self._peak, 0.02)
        else:
            lim = 1.0
        self.plot.setLimits(yMin=-lim * 1.08, yMax=lim * 1.08)
        self._vb.setYRange(-lim, lim, padding=0)

    def _render_spectrogram(self):
        if self._samples is None or self._sample_rate is None:
            return
        if self._spectrogram is None:
            self._spectrogram = self._compute_spectrogram()
        if self._spectrogram is None:
            return
        img, levels = self._spectrogram
        nyquist = self._sample_rate / 2.0
        self._image.setImage(img, autoLevels=False, levels=levels)
        self._image.setRect(QRectF(0, 0, self._duration, nyquist))
        self._image.setLookupTable(pg.colormap.get("inferno").getLookupTable(0.0, 1.0, 256))
        self.plot.setLabel("left", "Frequency", units="Hz")
        self.plot.setLimits(yMin=0, yMax=nyquist)
        self._vb.setYRange(0, nyquist, padding=0)

    def _compute_spectrogram(self, nfft=1024, hop=256):
        samples = self._samples
        if samples is None or len(samples) < nfft:
            return None
        frames = np.lib.stride_tricks.sliding_window_view(samples, nfft)[::hop]
        window = np.hanning(nfft).astype(np.float32)
        mag = np.abs(np.fft.rfft(frames * window, axis=1))
        db = 20.0 * np.log10(mag + 1e-6)  # shape (time, freq)
        top = float(db.max())
        return db, (top - 80.0, top)

    # ---- waveform envelope --------------------------------------------

    def _render_waveform(self):
        if self._mode != WAVEFORM or self._samples is None or self._sample_rate is None:
            return
        x0, x1 = self._vb.viewRange()[0]
        x0 = max(0.0, x0)
        x1 = min(self._duration, x1)
        if x1 <= x0:
            return

        sr = self._sample_rate
        i0 = int(x0 * sr)
        i1 = min(len(self._samples), int(x1 * sr))
        seg = self._samples[i0:i1]
        if len(seg) == 0:
            return

        width_px = max(self.plot.width(), 800)
        buckets = min(len(seg), width_px * 2)

        if len(seg) <= buckets:
            t = (i0 + np.arange(len(seg))) / sr
            self._max_curve.setData(t, seg)
            self._min_curve.setData(t, seg)
            return

        trim = len(seg) - (len(seg) % buckets)
        reshaped = seg[:trim].reshape(buckets, -1)
        env_max = reshaped.max(axis=1)
        env_min = reshaped.min(axis=1)
        step = (trim / buckets) / sr
        t = x0 + (np.arange(buckets) + 0.5) * step
        self._max_curve.setData(t, env_max)
        self._min_curve.setData(t, env_min)

    # ---- zoom ----------------------------------------------------------

    def fit_full(self):
        if self._duration <= 0:
            return
        self._vb.setXRange(0.0, self._duration, padding=0)
        if self._mode == WAVEFORM:
            self._apply_y_range()

    # ---- horizontal scrollbar -----------------------------------------

    def _sync_scrollbar(self):
        """Mirror the visible window onto the scrollbar; hidden when the whole
        clip is in view."""
        if self._updating_scroll or self._duration <= 0:
            return
        x0, x1 = self._vb.viewRange()[0]
        span = x1 - x0
        if span >= self._duration - 1e-6:
            self.hscroll.setVisible(False)
            return
        s = self._scroll_scale
        self._updating_scroll = True
        self.hscroll.setMinimum(0)
        self.hscroll.setMaximum(max(0, int((self._duration - span) * s)))
        self.hscroll.setPageStep(max(1, int(span * s)))
        self.hscroll.setSingleStep(max(1, int(span * s / 20)))
        self.hscroll.setValue(int(max(0.0, x0) * s))
        self.hscroll.setVisible(True)
        self._updating_scroll = False

    def _on_hscroll(self, value):
        if self._updating_scroll:
            return
        x0, x1 = self._vb.viewRange()[0]
        span = x1 - x0
        new_x0 = value / self._scroll_scale
        self._updating_scroll = True
        self._vb.setXRange(new_x0, new_x0 + span, padding=0)
        self._updating_scroll = False

    def cleanup(self):
        """Tear down plot items before deletion, so pyqtgraph never paints an
        item whose ViewBox has already gone."""
        self._render_when_settled.cancel()
        for signal in (self._vb.sigXRangeChanged, self.plot.scene().sigMouseMoved,
                       self.plot.scene().sigMouseClicked):
            try:
                signal.disconnect()
            except (TypeError, RuntimeError):
                pass
        self.plot.clear()

    def _on_mouse_moved(self, scene_pos):
        if self._samples is None:
            return
        if not self._vb.sceneBoundingRect().contains(scene_pos):
            self.cursor.setVisible(False)
            self.readout.setVisible(False)
            return
        point = self._vb.mapSceneToView(scene_pos)
        x = max(0.0, min(point.x(), self._duration))
        self.cursor.setPos(x)
        y_top = self._vb.viewRange()[1][1]
        self.readout.setText(f"{x:.3f}s")
        self.readout.setPos(x, y_top)
        self.cursor.setVisible(True)
        self.readout.setVisible(True)

    def _on_clicked(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.double():
            self.fit_full()
