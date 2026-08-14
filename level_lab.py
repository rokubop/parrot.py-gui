"""Side-by-side sketches of the dBFS lane, for picking one.

The shipped lane (``gui/widgets/level_lane.py``) draws one RMS trace on a linear
-96..0 axis. That axis spends three quarters of its pixels on a region nothing
ever occupies, and RMS alone cannot show a clipped sample. This is a bench for
trying the alternatives on a real take before any of them touch the app.

Run it::

    .venv/Scripts/python level_lab.py            # picks a recording itself
    .venv/Scripts/python level_lab.py sh         # a named label
    .venv/Scripts/python level_lab.py path.wav

Nothing here imports back into ``gui/``; it borrows the detector and the frame
grid so the numbers are the ones detection actually thresholds against, and
draws them ten different ways. Pick from the list on the left, drag the
threshold slider, and the variants that respond to it will.
"""
import os
import sys
import wave

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QLabel,
                             QListWidget, QMainWindow, QSlider, QSplitter,
                             QVBoxLayout, QWidget)

from config.config import RATE, RECORD_SECONDS, SLIDING_WINDOW_AMOUNT
from gui import theme
from gui.services.levels import FLOOR_DBFS, hop_samples
from lib.signal_processing import determine_dBFS

FLOOR = FLOOR_DBFS          # -96.0, where 16-bit silence bottoms out
DEFAULT_THRESHOLD = -40.0


# ---------------------------------------------------------------------------
# measurement
# ---------------------------------------------------------------------------

def analyse(wav_path):
    """Every series a variant might want, on detection's own frame grid.

    One pass, because the expensive part is the framing, not the arithmetic.
    ``det`` is what detection sees; ``rms`` and ``peak`` are what is actually
    in the samples. They disagree, which is the point of variant I.
    """
    wf = wave.open(wav_path, "rb")
    channels, rate = wf.getnchannels(), wf.getframerate()
    raw = wf.readframes(wf.getnframes())
    wf.close()

    data = np.frombuffer(raw, dtype=np.int16)
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1).astype(np.int16)

    hop = hop_samples(rate)
    window = hop * SLIDING_WINDOW_AMOUNT
    if hop <= 0 or len(data) < window:
        raise SystemExit(f"{wav_path}: shorter than one {window}-sample frame")

    starts = np.arange(0, len(data) - window + 1, hop)
    det = np.empty(len(starts), dtype=np.float64)
    rms = np.empty(len(starts), dtype=np.float64)
    peak = np.empty(len(starts), dtype=np.float64)

    for i, s in enumerate(starts):
        block = data[s:s + window]
        det[i] = determine_dBFS(block)
        f = block.astype(np.float64) / 32768.0
        rms[i] = np.sqrt(np.mean(f * f))
        peak[i] = np.abs(f).max()

    quiet = 1e-5        # -100 dB, below the floor everything is clipped to
    to_db = lambda v: 20.0 * np.log10(np.maximum(v, quiet))

    # A second, much finer peak series. The detection grid averages over 30 ms,
    # and an average is the one thing that cannot show a transient. This is what
    # the granular variants draw behind the trace the threshold actually cuts.
    fine_hop = max(1, int(rate * 0.001))            # 1 ms
    fine_win = max(fine_hop, int(rate * 0.004))     # 4 ms
    f_starts = np.arange(0, len(data) - fine_win + 1, fine_hop)
    strided = np.lib.stride_tricks.sliding_window_view(
        np.abs(data.astype(np.int32)), fine_win)[::fine_hop]
    fine = to_db(strided.max(axis=1) / 32768.0)

    return {
        "path": wav_path,
        "rate": rate,
        "seconds": len(data) / float(rate),
        "times": (starts + hop) / float(rate),
        "det": np.clip(det, FLOOR, 0.0),
        "rms": np.clip(to_db(rms), FLOOR, 0.0),
        "peak": np.clip(to_db(peak), FLOOR, 0.0),
        "fine_times": (f_starts + fine_win // 2) / float(rate),
        "fine": np.clip(fine, FLOOR, 0.0),
        # A frame holding a sample at full scale. RMS over 30 ms cannot show
        # this - it reads -12 dB while the samples are pinned.
        "clipped": peak >= (32767.0 / 32768.0),
    }


def content_range(d, span_db):
    """``(bottom, top)`` for a Pro-L2 style cropped scale, anchored to the take.

    A limiter can anchor at 0 because everything it sees was gain-staged to
    reach it. A microphone in a quiet room was not, so the same cropped window
    has to find its own top.
    """
    top = float(np.percentile(d["peak"], 99.9)) + 3.0
    top = min(0.0, np.ceil(top / 3.0) * 3.0)
    return top - span_db, top


# ---------------------------------------------------------------------------
# the warped axis, shared by several variants
# ---------------------------------------------------------------------------

GAMMA = 2.5     # >1 spends more pixels near 0 dB; 2.5 doubles the top 24 dB
WARP_TICKS = [0, -3, -6, -10, -15, -20, -25, -30, -40, -50, -65, -96]


def warp(db):
    """dBFS -> 0..1, with the loud end stretched.

    Speech sits between about -35 and -10 dBFS. Linearly that is the top
    quarter of the lane; here it is a little over half.
    """
    u = np.clip((np.asarray(db, dtype=float) - FLOOR) / (0.0 - FLOOR), 0.0, 1.0)
    return u ** GAMMA


def warp_ticks():
    return [[(float(warp(v)), str(v)) for v in WARP_TICKS]]


# ---------------------------------------------------------------------------
# variants
# ---------------------------------------------------------------------------

class Variant(QWidget):
    """A sketch. ``title``/``note`` are shown above it, and it may ignore the
    threshold entirely - several of these are about the level, not the line."""

    title = "unnamed"
    note = ""

    def __init__(self, d, parent=None):
        super().__init__(parent)
        self.d = d
        self.t = theme.colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self.body)
        self.build()

    def new_plot(self, height=None, x_label=True):
        p = pg.PlotWidget(background=self.t["plot_bg"])
        p.showGrid(x=True, y=True, alpha=self.t["grid_alpha"])
        p.setMenuEnabled(False)
        p.hideButtons()
        p.getAxis("left").setWidth(64)
        if x_label:
            p.setLabel("bottom", "Time", units="s")
        if height:
            p.setFixedHeight(height)
        self.body.addWidget(p)
        return p

    def build(self):
        raise NotImplementedError

    def set_threshold(self, value):
        pass

    def set_scale(self, span_db):
        """Only the cropped variants have a scale to set."""


class A_Baseline(Variant):
    title = "A - baseline (what ships)"
    note = ("RMS on a linear -96..0 axis, filled to the floor. Everything below "
            "the line is tinted out.")

    def build(self):
        d, t = self.d, self.t
        p = self.new_plot()
        p.setLabel("left", "dBFS")
        p.getAxis("left").setTicks([[(v, str(v)) for v in (0, -20, -40, -60, -80, -96)]])
        p.setYRange(FLOOR - 12, 12, padding=0)
        p.plot(d["times"], d["det"], pen=pg.mkPen(QColor(*t["wave"]), width=1),
               fillLevel=FLOOR, brush=QColor(*t["wave_fill"]))
        self.below = pg.LinearRegionItem(
            values=[FLOOR - 12, DEFAULT_THRESHOLD], orientation="horizontal",
            movable=False, pen=pg.mkPen(None),
            brush=QColor(*_rgba(t["plot_bg"], 150)))
        self.below.setZValue(10)
        p.addItem(self.below)
        self.line = pg.InfiniteLine(pos=DEFAULT_THRESHOLD, angle=0,
                                    pen=pg.mkPen(QColor(t["warn"]), width=2))
        self.line.setZValue(20)
        p.addItem(self.line)

    def set_threshold(self, v):
        self.line.setPos(v)
        self.below.setRegion((FLOOR - 12, v))


class B_Warped(Variant):
    title = "B - warped Y"
    note = ("Same data, same line. The axis is gamma-stretched so the top 25 dB "
            "- where every sound actually lives - gets half the pixels.")

    def build(self):
        d, t = self.d, self.t
        p = self.new_plot()
        p.setLabel("left", "dBFS")
        p.getAxis("left").setTicks(warp_ticks())
        p.setYRange(-0.04, 1.06, padding=0)
        p.plot(d["times"], warp(d["det"]),
               pen=pg.mkPen(QColor(*t["wave"]), width=1),
               fillLevel=0.0, brush=QColor(*t["wave_fill"]))
        self.below = pg.LinearRegionItem(
            values=[-0.04, float(warp(DEFAULT_THRESHOLD))],
            orientation="horizontal", movable=False, pen=pg.mkPen(None),
            brush=QColor(*_rgba(t["plot_bg"], 150)))
        self.below.setZValue(10)
        p.addItem(self.below)
        self.line = pg.InfiniteLine(pos=float(warp(DEFAULT_THRESHOLD)), angle=0,
                                    pen=pg.mkPen(QColor(t["warn"]), width=2))
        self.line.setZValue(20)
        p.addItem(self.line)

    def set_threshold(self, v):
        y = float(warp(v))
        self.line.setPos(y)
        self.below.setRegion((-0.04, y))


class C_PeakRms(Variant):
    title = "C - peak over RMS"
    note = ("Pro-L2's dual display. Peak envelope behind, RMS in front; the gap "
            "is crest factor. Red ticks are frames holding a full-scale sample.")

    def build(self):
        d, t = self.d, self.t
        p = self.new_plot()
        p.setLabel("left", "dBFS")
        p.getAxis("left").setTicks(warp_ticks())
        p.setYRange(-0.04, 1.06, padding=0)
        p.plot(d["times"], warp(d["peak"]),
               pen=pg.mkPen(QColor(*_rgba(t["info"], 120)), width=1),
               fillLevel=0.0, brush=QColor(*_rgba(t["info"], 45)))
        p.plot(d["times"], warp(d["rms"]),
               pen=pg.mkPen(QColor(*t["wave"]), width=1),
               fillLevel=0.0, brush=QColor(*t["wave_fill"]))
        clips = d["times"][d["clipped"]]
        if len(clips):
            p.plot(clips, np.full(len(clips), 1.03), pen=None, symbol="t",
                   symbolSize=7, symbolBrush=QColor("#e05a5a"),
                   symbolPen=pg.mkPen(None))
        self.line = pg.InfiniteLine(pos=float(warp(DEFAULT_THRESHOLD)), angle=0,
                                    pen=pg.mkPen(QColor(t["warn"]), width=2))
        p.addItem(self.line)

    def set_threshold(self, v):
        self.line.setPos(float(warp(v)))


class D_CrestBand(Variant):
    title = "D - crest band"
    note = ("Only the band between RMS and peak is drawn. A wide band is a "
            "transient (a pop); a narrow one is sustained noise.")

    def build(self):
        d, t = self.d, self.t
        p = self.new_plot()
        p.setLabel("left", "dBFS")
        p.getAxis("left").setTicks(warp_ticks())
        p.setYRange(-0.04, 1.06, padding=0)
        lo = p.plot(d["times"], warp(d["rms"]), pen=pg.mkPen(None))
        hi = p.plot(d["times"], warp(d["peak"]), pen=pg.mkPen(None))
        fill = pg.FillBetweenItem(lo, hi, brush=QColor(*_rgba(t["accent"], 110)))
        p.addItem(fill)
        p.plot(d["times"], warp(d["peak"]),
               pen=pg.mkPen(QColor(*t["wave"]), width=1))
        self.line = pg.InfiniteLine(pos=float(warp(DEFAULT_THRESHOLD)), angle=0,
                                    pen=pg.mkPen(QColor(t["warn"]), width=2))
        p.addItem(self.line)

    def set_threshold(self, v):
        self.line.setPos(float(warp(v)))


class E_Ballistics(Variant):
    title = "E - ballistics"
    note = ("Raw frames faint behind a PPM-style follower: fast attack, slow "
            "release. What every hardware meter does to be readable.")

    ATTACK_MS = 10.0
    RELEASE_MS = 300.0

    def build(self):
        d, t = self.d, self.t
        p = self.new_plot()
        p.setLabel("left", "dBFS")
        p.getAxis("left").setTicks(warp_ticks())
        p.setYRange(-0.04, 1.06, padding=0)
        p.plot(d["times"], warp(d["det"]),
               pen=pg.mkPen(QColor(*_rgba(t["wave"], 70)), width=1))
        p.plot(d["times"], warp(self._follow(d["det"])),
               pen=pg.mkPen(QColor(*t["wave"]), width=2))
        self.line = pg.InfiniteLine(pos=float(warp(DEFAULT_THRESHOLD)), angle=0,
                                    pen=pg.mkPen(QColor(t["warn"]), width=2))
        p.addItem(self.line)

    def _follow(self, db):
        """One-pole in linear amplitude, not in dB - smoothing decibels
        directly biases towards the quiet frames."""
        step_ms = 1000.0 * RECORD_SECONDS / SLIDING_WINDOW_AMOUNT
        a_up = 1.0 - np.exp(-step_ms / self.ATTACK_MS)
        a_dn = 1.0 - np.exp(-step_ms / self.RELEASE_MS)
        amp = 10.0 ** (db / 20.0)
        out = np.empty_like(amp)
        y = amp[0]
        for i, x in enumerate(amp):
            y += (a_up if x > y else a_dn) * (x - y)
            out[i] = y
        return 20.0 * np.log10(np.maximum(out, 1e-5))


class F_HeatStrip(Variant):
    title = "F - heat strip"
    note = ("The whole lane as one coloured row. Costs 28 px instead of 130, so "
            "it could live under the waveform permanently.")

    def build(self):
        d, t = self.d, self.t
        p = self.new_plot(height=90)
        p.setLabel("left", "")
        p.getAxis("left").setTicks([[]])
        p.setYRange(0, 1, padding=0)
        p.showGrid(x=True, y=False, alpha=t["grid_alpha"])

        u = warp(d["det"])
        img = pg.ImageItem(u.reshape(-1, 1))
        cmap = pg.ColorMap([0.0, 0.35, 0.7, 1.0],
                           [(21, 24, 28), (30, 90, 70),
                            (70, 215, 135), (230, 245, 200)])
        img.setLookupTable(cmap.getLookupTable(0.0, 1.0, 256))
        img.setLevels([0.0, 1.0])
        span = d["times"][-1] - d["times"][0] if len(d["times"]) > 1 else 1.0
        img.setRect(pg.QtCore.QRectF(float(d["times"][0]), 0.0,
                                     float(span), 1.0))
        p.addItem(img)

        # The threshold cannot be a horizontal line here - there is no vertical
        # axis. It is the boundary between "coloured" and "not", so it is drawn
        # as the frames that clear it.
        self.marks = pg.PlotDataItem(pen=None, symbol="s", symbolSize=4,
                                     symbolBrush=QColor(t["warn"]),
                                     symbolPen=pg.mkPen(None))
        p.addItem(self.marks)
        self.set_threshold(DEFAULT_THRESHOLD)

    def set_threshold(self, v):
        d = self.d
        over = d["times"][d["det"] >= v]
        self.marks.setData(over, np.full(len(over), 0.92))


class G_Hanging(Variant):
    title = "G - hanging from 0"
    note = ("Inverted, the way limiters draw gain reduction: 0 dB at the top, "
            "level hanging down. Depth reads as 'how far from full scale'.")

    def build(self):
        d, t = self.d, self.t
        p = self.new_plot()
        p.setLabel("left", "dB below FS")
        p.getAxis("left").setTicks([[(float(warp(v)), str(-v)) for v in WARP_TICKS]])
        p.setYRange(-0.04, 1.06, padding=0)
        p.getViewBox().invertY(True)
        p.plot(d["times"], warp(d["det"]),
               pen=pg.mkPen(QColor(*t["wave"]), width=1),
               fillLevel=1.0, brush=QColor(*t["wave_fill"]))
        self.line = pg.InfiniteLine(pos=float(warp(DEFAULT_THRESHOLD)), angle=0,
                                    pen=pg.mkPen(QColor(t["warn"]), width=2))
        p.addItem(self.line)

    def set_threshold(self, v):
        self.line.setPos(float(warp(v)))


class H_Histogram(Variant):
    title = "H - lane + distribution"
    note = ("The lane with its own histogram beside it. Two humps - silence and "
            "sound - and the threshold belongs in the valley between them.")

    def build(self):
        d, t = self.d, self.t
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)

        p = pg.PlotWidget(background=t["plot_bg"])
        p.showGrid(x=True, y=True, alpha=t["grid_alpha"])
        p.setMenuEnabled(False); p.hideButtons()
        p.getAxis("left").setWidth(64)
        p.setLabel("bottom", "Time", units="s")
        p.setLabel("left", "dBFS")
        p.getAxis("left").setTicks(warp_ticks())
        p.setYRange(-0.04, 1.06, padding=0)
        p.plot(d["times"], warp(d["det"]),
               pen=pg.mkPen(QColor(*t["wave"]), width=1),
               fillLevel=0.0, brush=QColor(*t["wave_fill"]))
        row_layout.addWidget(p, 4)

        h = pg.PlotWidget(background=t["plot_bg"])
        h.setMenuEnabled(False); h.hideButtons()
        h.setMouseEnabled(x=False, y=False)
        h.getAxis("left").setTicks([[]])
        h.getAxis("bottom").setTicks([[]])
        h.setLabel("bottom", "frames")
        h.setYRange(-0.04, 1.06, padding=0)
        h.setFixedWidth(150)
        counts, edges = np.histogram(warp(d["det"]), bins=60, range=(0.0, 1.0))
        centres = (edges[:-1] + edges[1:]) / 2.0
        h.plot(counts, centres, pen=pg.mkPen(QColor(*t["wave"]), width=1),
               fillLevel=0, brush=QColor(*t["wave_fill"]))
        row_layout.addWidget(h, 1)
        self.body.addWidget(row)

        self.lines = []
        for plot in (p, h):
            line = pg.InfiniteLine(pos=float(warp(DEFAULT_THRESHOLD)), angle=0,
                                   pen=pg.mkPen(QColor(t["warn"]), width=2))
            plot.addItem(line)
            self.lines.append(line)

    def set_threshold(self, v):
        for line in self.lines:
            line.setPos(float(warp(v)))


class I_DetectorVsTruth(Variant):
    title = "I - detector vs truth"
    note = ("What detection measures against what is in the samples. The gap is "
            "a flat +6.02 dB - exactly 20*log10(2) - because audioop reads "
            "sample pairs as one int32 and the high word carries a factor of 2. "
            "Not noise, not aliasing: the axis is simply calibrated 6 dB hot.")

    def build(self):
        d, t = self.d, self.t
        p = self.new_plot()
        p.setLabel("left", "dBFS")
        p.getAxis("left").setTicks(warp_ticks())
        p.setYRange(-0.04, 1.06, padding=0)
        p.addLegend(offset=(-10, 10))
        p.plot(d["times"], warp(d["peak"]), name="true peak",
               pen=pg.mkPen(QColor(*_rgba(t["info"], 150)), width=1))
        p.plot(d["times"], warp(d["rms"]), name="true RMS",
               pen=pg.mkPen(QColor(t["warn"]), width=1))
        p.plot(d["times"], warp(d["det"]), name="determine_dBFS",
               pen=pg.mkPen(QColor(*t["wave"]), width=2))

        err = d["det"] - d["rms"]
        loud = d["det"] > -60      # the floor is all quantisation noise
        if loud.any():
            summary = (f"over frames above -60 dBFS:  mean {err[loud].mean():+.2f} dB   "
                       f"spread {err[loud].std():.2f} dB   "
                       f"worst {err[loud][np.argmax(np.abs(err[loud]))]:+.2f} dB")
        else:
            summary = "no frames above -60 dBFS in this take"
        label = QLabel(summary)
        label.setStyleSheet("color: #8b949e; padding: 2px 6px;")
        self.body.addWidget(label)


class J_Proposal(Variant):
    title = "J - proposal (B + C + clip)"
    note = ("The one worth shipping: warped axis, peak behind RMS, clip ticks, "
            "dead zone under the line. Everything else here is an ingredient.")

    def build(self):
        d, t = self.d, self.t
        p = self.new_plot()
        p.setLabel("left", "dBFS")
        p.getAxis("left").setTicks(warp_ticks())
        p.setYRange(-0.04, 1.06, padding=0)
        p.plot(d["times"], warp(d["peak"]),
               pen=pg.mkPen(QColor(*_rgba(t["info"], 110)), width=1),
               fillLevel=0.0, brush=QColor(*_rgba(t["info"], 38)))
        p.plot(d["times"], warp(d["det"]),
               pen=pg.mkPen(QColor(*t["wave"]), width=1),
               fillLevel=0.0, brush=QColor(*t["wave_fill"]))
        clips = d["times"][d["clipped"]]
        if len(clips):
            p.plot(clips, np.full(len(clips), 1.03), pen=None, symbol="t",
                   symbolSize=7, symbolBrush=QColor("#e05a5a"),
                   symbolPen=pg.mkPen(None))
        self.below = pg.LinearRegionItem(
            values=[-0.04, float(warp(DEFAULT_THRESHOLD))],
            orientation="horizontal", movable=False, pen=pg.mkPen(None),
            brush=QColor(*_rgba(t["plot_bg"], 150)))
        self.below.setZValue(10)
        p.addItem(self.below)
        self.line = pg.InfiniteLine(
            pos=float(warp(DEFAULT_THRESHOLD)), angle=0,
            pen=pg.mkPen(QColor(t["warn"]), width=2),
            label="{value:0.0f}", labelOpts={"position": 0.02,
                                             "color": t["warn"],
                                             "fill": QColor(t["plot_bg"])})
        self.line.setZValue(20)
        p.addItem(self.line)

    def set_threshold(self, v):
        y = float(warp(v))
        self.line.setPos(y)
        self.line.label.setFormat(f"{v:0.0f} dBFS")
        self.line.label.valueChanged()
        self.below.setRegion((-0.04, y))


class K_Cropped(Variant):
    title = "K - cropped scale"
    note = ("Pro-L2's actual model: a fixed-width window (it offers 16, 32 and "
            "48 dB, never 96) with linear dB inside it. A limiter anchors the "
            "top at 0 because the material was gain-staged to reach it; a mic "
            "was not, so this anchors to the take's own peak instead.")

    def build(self):
        d, t = self.d, self.t
        self.plot = p = self.new_plot()
        p.setLabel("left", "dBFS")
        p.plot(d["times"], d["det"], pen=pg.mkPen(QColor(*t["wave"]), width=1),
               fillLevel=FLOOR, brush=QColor(*t["wave_fill"]))
        self.below = pg.LinearRegionItem(
            values=[FLOOR, DEFAULT_THRESHOLD], orientation="horizontal",
            movable=False, pen=pg.mkPen(None),
            brush=QColor(*_rgba(t["plot_bg"], 150)))
        self.below.setZValue(10)
        p.addItem(self.below)
        self.line = pg.InfiniteLine(pos=DEFAULT_THRESHOLD, angle=0,
                                    pen=pg.mkPen(QColor(t["warn"]), width=2))
        self.line.setZValue(20)
        p.addItem(self.line)
        self.set_scale(48)

    def set_scale(self, span_db):
        self._bottom, self._top = content_range(self.d, span_db)
        step = 3 if span_db <= 16 else (6 if span_db <= 48 else 12)
        ticks = np.arange(np.ceil(self._bottom / step) * step,
                          self._top + step, step)
        self.plot.getAxis("left").setTicks(
            [[(float(v), str(int(v))) for v in ticks if v <= self._top]])
        self._apply_range()

    def _apply_range(self):
        # The line is allowed anywhere, so the window follows it out rather
        # than pinning it to the edge and lying about where it is.
        bottom = min(self._bottom, self._value - 2) if hasattr(self, "_value") \
            else self._bottom
        self.plot.setYRange(bottom, self._top, padding=0)
        self.below.setRegion((FLOOR, getattr(self, "_value", DEFAULT_THRESHOLD)))

    def set_threshold(self, v):
        self._value = v
        self.line.setPos(v)
        self._apply_range()


class L_Granular(Variant):
    title = "L - cropped + granular"
    note = ("The same window, with a 1 ms peak envelope behind the 30 ms trace. "
            "The line still cuts the average, because that is what detection "
            "thresholds - but the detail behind it is no longer thrown away.")

    def build(self):
        d, t = self.d, self.t
        self.plot = p = self.new_plot()
        p.setLabel("left", "dBFS")
        fine = p.plot(d["fine_times"], d["fine"],
                      pen=pg.mkPen(QColor(*_rgba(t["info"], 90)), width=1),
                      fillLevel=FLOOR, brush=QColor(*_rgba(t["info"], 40)))
        fine.setDownsampling(auto=True, method="peak")
        fine.setClipToView(True)
        p.plot(d["times"], d["det"], pen=pg.mkPen(QColor(*t["wave"]), width=1))
        self.below = pg.LinearRegionItem(
            values=[FLOOR, DEFAULT_THRESHOLD], orientation="horizontal",
            movable=False, pen=pg.mkPen(None),
            brush=QColor(*_rgba(t["plot_bg"], 150)))
        self.below.setZValue(10)
        p.addItem(self.below)
        self.line = pg.InfiniteLine(pos=DEFAULT_THRESHOLD, angle=0,
                                    pen=pg.mkPen(QColor(t["warn"]), width=2))
        self.line.setZValue(20)
        p.addItem(self.line)
        self.set_scale(48)

    set_scale = K_Cropped.set_scale
    _apply_range = K_Cropped._apply_range
    set_threshold = K_Cropped.set_threshold


class M_Proposal2(Variant):
    title = "M - proposal v2"
    note = ("Cropped scale, 1 ms envelope behind the detector trace, clip ticks, "
            "dead zone. No warp: once the window is cropped to the content, "
            "there is nothing left for a warp to fix.")

    def build(self):
        d, t = self.d, self.t
        self.plot = p = self.new_plot()
        p.setLabel("left", "dBFS")
        fine = p.plot(d["fine_times"], d["fine"],
                      pen=pg.mkPen(QColor(*_rgba(t["info"], 80)), width=1),
                      fillLevel=FLOOR, brush=QColor(*_rgba(t["info"], 34)))
        fine.setDownsampling(auto=True, method="peak")
        fine.setClipToView(True)
        p.plot(d["times"], d["det"], pen=pg.mkPen(QColor(*t["wave"]), width=1),
               fillLevel=FLOOR, brush=QColor(*t["wave_fill"]))
        clips = d["times"][d["clipped"]]
        if len(clips):
            p.plot(clips, np.full(len(clips), -0.5), pen=None, symbol="t",
                   symbolSize=7, symbolBrush=QColor("#e05a5a"),
                   symbolPen=pg.mkPen(None))
        self.below = pg.LinearRegionItem(
            values=[FLOOR, DEFAULT_THRESHOLD], orientation="horizontal",
            movable=False, pen=pg.mkPen(None),
            brush=QColor(*_rgba(t["plot_bg"], 150)))
        self.below.setZValue(10)
        p.addItem(self.below)
        self.line = pg.InfiniteLine(
            pos=DEFAULT_THRESHOLD, angle=0,
            pen=pg.mkPen(QColor(t["warn"]), width=2),
            label="{value:0.0f} dBFS",
            labelOpts={"position": 0.02, "color": t["warn"],
                       "fill": QColor(t["plot_bg"])})
        self.line.setZValue(20)
        p.addItem(self.line)
        self.set_scale(48)

    set_scale = K_Cropped.set_scale
    _apply_range = K_Cropped._apply_range

    def set_threshold(self, v):
        K_Cropped.set_threshold(self, v)
        self.line.label.valueChanged()


VARIANTS = [A_Baseline, B_Warped, C_PeakRms, D_CrestBand, E_Ballistics,
            F_HeatStrip, G_Hanging, H_Histogram, I_DetectorVsTruth, J_Proposal,
            K_Cropped, L_Granular, M_Proposal2]

SCALES = [16, 32, 48, 96]       # Pro-L2 offers the first three


def _rgba(color, alpha):
    """``(r, g, b, alpha)`` from either a hex string or an rgb/rgba tuple."""
    if isinstance(color, str):
        c = QColor(color)
        return (c.red(), c.green(), c.blue(), alpha)
    return tuple(color[:3]) + (alpha,)


# ---------------------------------------------------------------------------
# window
# ---------------------------------------------------------------------------

class Lab(QMainWindow):
    def __init__(self, wavs):
        super().__init__()
        self.setWindowTitle("level lane - representations")
        self.resize(1220, 720)
        self._wavs = wavs
        self._cache = {}
        self._current = None
        t = theme.colors()

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)

        top = QHBoxLayout()
        top.addWidget(QLabel("Recording"))
        self.picker = QComboBox()
        for path in wavs:
            self.picker.addItem(_pretty(path), path)
        self.picker.currentIndexChanged.connect(lambda _: self._show())
        top.addWidget(self.picker, 2)
        top.addSpacing(16)
        top.addWidget(QLabel("Scale"))
        self.scale = QComboBox()
        for span in SCALES:
            self.scale.addItem(f"{span} dB", span)
        self.scale.setCurrentIndex(SCALES.index(48))
        self.scale.currentIndexChanged.connect(self._scale_changed)
        top.addWidget(self.scale)
        top.addSpacing(16)
        top.addWidget(QLabel("Threshold"))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(int(FLOOR), 0)
        self.slider.setValue(int(DEFAULT_THRESHOLD))
        self.slider.valueChanged.connect(self._threshold_changed)
        top.addWidget(self.slider, 3)
        self.slider_label = QLabel(f"{int(DEFAULT_THRESHOLD)} dBFS")
        self.slider_label.setMinimumWidth(80)
        top.addWidget(self.slider_label)
        outer.addLayout(top)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.list = QListWidget()
        for cls in VARIANTS:
            self.list.addItem(cls.title)
        self.list.setFixedWidth(230)
        self.list.currentRowChanged.connect(lambda _: self._show())
        split.addWidget(self.list)

        right = QWidget()
        self.right_layout = QVBoxLayout(right)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color: {t['info']}; padding: 2px 4px;")
        self.right_layout.addWidget(self.note)
        self.holder = QVBoxLayout()
        self.right_layout.addLayout(self.holder, 1)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        outer.addWidget(split, 1)

        self.list.setCurrentRow(len(VARIANTS) - 1)      # open on the proposal

    def _data(self):
        path = self.picker.currentData()
        if path not in self._cache:
            self._cache[path] = analyse(path)
        return self._cache[path]

    def _show(self):
        row = self.list.currentRow()
        if row < 0:
            return
        if self._current is not None:
            self._current.setParent(None)
            self._current.deleteLater()
        cls = VARIANTS[row]
        self._current = cls(self._data())
        self._current.set_scale(self.scale.currentData())
        self._current.set_threshold(float(self.slider.value()))
        self.note.setText(f"{cls.title} - {cls.note}")
        self.holder.addWidget(self._current)

    def _scale_changed(self, _):
        if self._current is not None:
            self._current.set_scale(self.scale.currentData())
            self._current.set_threshold(float(self.slider.value()))

    def _threshold_changed(self, value):
        self.slider_label.setText(f"{value} dBFS")
        if self._current is not None:
            self._current.set_threshold(float(value))


def _pretty(path):
    parts = path.replace("\\", "/").split("/")
    return f"{parts[-3]}/{parts[-1]}" if len(parts) >= 3 else path


def find_wavs(arg=None):
    """A path, a label name, or everything under ``data/recordings``."""
    if arg and arg.lower().endswith(".wav"):
        return [arg]
    root = os.path.join("data", "recordings")
    labels = [arg] if arg else sorted(
        d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
    found = []
    for label in labels:
        source = os.path.join(root, label, "source")
        if not os.path.isdir(source):
            continue
        found += [os.path.join(source, f) for f in sorted(os.listdir(source))
                  if f.lower().endswith(".wav")]
    return found


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    wavs = find_wavs(arg)
    if not wavs:
        raise SystemExit("no recordings found under data/recordings")
    pg.setConfigOptions(antialias=True)
    app = QApplication(sys.argv)
    theme.apply(app, next(iter(theme.THEMES)))
    win = Lab(wavs)
    win.show()
    app._lab = win      # top-level widgets need a strong reference (qt-traps)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
