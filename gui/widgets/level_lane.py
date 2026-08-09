"""A dBFS lane with the detection threshold drawn on it.

The waveform above answers "what did I record". This answers "what is that
number doing": drag the line, and the bumps that clear it end up blue.

A strip, not a second chart. Shares the X axis of the plot above (``link_x``),
same left-axis width so the grids line up, and its mouse moves the threshold and
nothing else. Panning and zooming stay with the waveform, where selection lives.

Two modes:

- **manual** - the value being applied. Draggable, amber.
- **auto** - what detection settled on. Dashed, blue, inert. It is the floor of
  a threshold that moves per sound, not a cutoff you chose.
"""
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from gui import theme
from gui.services.levels import FLOOR_DBFS

# Applied to the plot above too, so both left axes end at the same pixel. Sized
# for the widest thing either prints, the live trace's "-15000".
AXIS_WIDTH = 64
LANE_HEIGHT = 132

# Live: only what the scrolling window can show. A take runs for minutes.
LIVE_POINTS = 1600      # ~24 s of frames, past the 10 s window
LIVE_REDRAW_EVERY = 2


class LevelLane(QWidget):
    """Level over time in dBFS, with a threshold line."""

    threshold_moved = pyqtSignal(float)      # during a drag, every step
    threshold_committed = pyqtSignal(float)  # on release

    def __init__(self, parent=None):
        super().__init__(parent)
        t = theme.colors()
        self._colors = t
        self._mode = None       # set_mode below is the first real one
        self._editable = True
        self._value = -40.0
        self._setting_line = False
        self._live_t = []
        self._live_v = []
        self._live_since_draw = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.plot = pg.PlotWidget(background=t["plot_bg"])
        self.plot.setFixedHeight(LANE_HEIGHT)
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        # The threshold line is the only thing here that answers the mouse.
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.showGrid(x=True, y=True, alpha=t["grid_alpha"])
        self.plot.setLabel("bottom", "Time", units="s")
        left = self.plot.getAxis("left")
        left.setWidth(AXIS_WIDTH)
        left.setTicks([[(v, str(v)) for v in (0, -20, -40, -60, -80, -96)]])
        self.plot.setLabel("left", "dBFS")
        self._vb = self.plot.getViewBox()
        # Air top and bottom, or the 0 and -96 ticks print half outside.
        self._vb.setYRange(FLOOR_DBFS - 12, 12, padding=0)
        self._vb.setLimits(yMin=FLOOR_DBFS - 12, yMax=12)
        layout.addWidget(self.plot)

        # Filled to the floor: the fill is what the threshold line cuts through.
        self.curve = self.plot.plot(
            pen=pg.mkPen(QColor(*t["wave"]), width=1),
            fillLevel=FLOOR_DBFS, brush=QColor(*t["wave_fill"]))
        # A six-minute take is ~25k frames. Peak downsampling keeps the spikes.
        self.curve.setDownsampling(auto=True, method="peak")
        self.curve.setClipToView(True)

        # Under the line is ignored by detection. Drawn over the level, not
        # behind it: a tint behind the fill is invisible under a dense trace.
        self.below = pg.LinearRegionItem(values=[FLOOR_DBFS - 12, self._value],
                                         orientation="horizontal", movable=False,
                                         brush=self._below_brush(True),
                                         pen=pg.mkPen(None))
        self.below.setZValue(10)
        self.below.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        for line in getattr(self.below, "lines", []):
            line.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.plot.addItem(self.below)

        self.line = pg.InfiniteLine(
            pos=self._value, angle=0, movable=True,
            pen=pg.mkPen(QColor(t["warn"]), width=2),
            label="{value:0.0f} dBFS",
            labelOpts={"position": 0.02, "anchors": [(0, 0), (0, 1)],
                       "color": t["warn"], "fill": QColor(t["plot_bg"]),
                       "movable": False})
        self.line.setHoverPen(pg.mkPen(QColor(t["warn"]), width=4))
        self.line.setBounds([FLOOR_DBFS, 0])
        self.line.setZValue(20)
        self.line.sigDragged.connect(self._on_dragged)
        self.line.sigPositionChangeFinished.connect(self._on_released)
        self.plot.addItem(self.line)

        # Live redraws are throttled the same way the waveform's are.
        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.setInterval(30)
        self._live_timer.timeout.connect(self._redraw_live)

        self.set_mode("manual")

    # ---- the plot above -------------------------------------------------

    def link_x(self, plot_widget):
        """Follow another plot's time axis, and pad its left axis to match."""
        item = plot_widget.getPlotItem() if hasattr(plot_widget, "getPlotItem") \
            else plot_widget
        item.getAxis("left").setWidth(AXIS_WIDTH)
        # The lane carries the time axis: two stacked axes read as a mistake.
        item.showAxis("bottom", False)
        self.plot.setXLink(item)

    # ---- threshold ------------------------------------------------------

    def value(self):
        return self._value

    def set_threshold(self, value, notify=False):
        """Move the line without pretending the user did it, unless asked."""
        value = float(max(FLOOR_DBFS, min(float(value), 0.0)))
        self._value = value
        self._setting_line = True
        self.line.setPos(value)
        self._setting_line = False
        self.below.setRegion((FLOOR_DBFS - 12, value))
        if notify:
            self.threshold_moved.emit(value)

    def set_mode(self, mode):
        """``manual`` - a value being applied. ``auto`` - what detection found."""
        if mode == self._mode:
            return      # called on every step of a drag; nothing below is free
        self._mode = mode
        t = self._colors
        manual = mode == "manual"
        # Amber chosen, blue found. Neither is the green the level is drawn in.
        color = t["warn"] if manual else t["info"]
        style = Qt.PenStyle.SolidLine if manual else Qt.PenStyle.DashLine
        self.line.setPen(pg.mkPen(QColor(color), width=2, style=style))
        self.line.setHoverPen(pg.mkPen(QColor(color), width=4 if manual else 2,
                                       style=style))
        self.line.setMovable(manual and self._editable)
        self.line.label.setFormat(
            "{value:0.0f} dBFS" if manual else "auto  {value:0.0f} dBFS")
        self.line.label.setColor(QColor(color))
        # setFormat waits for the next move, and a mode switch is not one.
        self.line.label.valueChanged()
        self.below.setBrush(self._below_brush(manual))
        self.below.update()
        self._refresh_tooltip()

    def set_editable(self, editable):
        """Off where nothing acts on a new value. A line that moves and changes
        nothing is a lie."""
        self._editable = editable
        self.line.setMovable(self._mode == "manual" and editable)
        self._refresh_tooltip()

    def _refresh_tooltip(self):
        if not self._editable:
            self.plot.setToolTip("The threshold this take was detected at. "
                                 "Anything under it is not detected.")
        elif self._mode == "manual":
            self.plot.setToolTip("Drag the line to change the threshold. "
                                 "Anything under it is not detected.")
        else:
            self.plot.setToolTip("The threshold detection settled on. "
                                 "Set one yourself to move it.")

    def _below_brush(self, manual):
        """Fades the sub-threshold half towards the background. Stronger for a
        manual value, which is the one being judged."""
        color = QColor(self._colors["plot_bg"])
        color.setAlpha(150 if manual else 105)
        return color

    def set_line_visible(self, visible):
        """Hidden until auto settles: a line at 0 reads as unclearable."""
        self.line.setVisible(visible)
        self.below.setVisible(visible)
        if visible:
            # The label skips reformatting while hidden; it lands now.
            self.line.label.valueChanged()

    def _on_dragged(self):
        if self._setting_line:
            return
        # Whole decibels: the control it feeds is integer.
        value = round(self.line.value())
        self.set_threshold(value)
        self.threshold_moved.emit(self._value)

    def _on_released(self):
        if self._setting_line:
            return
        self.threshold_committed.emit(self._value)

    # ---- a saved clip ---------------------------------------------------

    def set_levels(self, times, values):
        self._live_timer.stop()
        self._live_t, self._live_v = [], []
        if times is None or len(times) == 0:
            self.curve.setData([], [])
            return
        self.curve.setData(np.asarray(times), np.asarray(values))

    # ---- a live take ----------------------------------------------------

    def begin_live(self, offset_seconds=0.0):
        """Start a live trace. ``offset_seconds`` is where the take already
        reaches, so a resumed segment continues the same time axis."""
        self._live_t, self._live_v = [], []
        self._live_offset = offset_seconds
        self._live_since_draw = 0
        self.curve.setData([], [])

    def push_level(self, seconds, dbfs):
        """One detection frame. Called for every frame, drawn less often."""
        if dbfs is None:
            return
        self._live_t.append(getattr(self, "_live_offset", 0.0) + seconds)
        self._live_v.append(max(FLOOR_DBFS, min(float(dbfs), 0.0)))
        if len(self._live_t) > LIVE_POINTS:
            del self._live_t[:len(self._live_t) - LIVE_POINTS]
            del self._live_v[:len(self._live_v) - LIVE_POINTS]
        self._live_since_draw += 1
        if self._live_since_draw >= LIVE_REDRAW_EVERY and not self._live_timer.isActive():
            self._live_timer.start()

    def _redraw_live(self):
        self._live_since_draw = 0
        if not self._live_t:
            return
        self.curve.setData(np.asarray(self._live_t), np.asarray(self._live_v))

    def clear(self):
        self._live_timer.stop()
        self._live_t, self._live_v = [], []
        self.curve.setData([], [])

    def cleanup(self):
        self._live_timer.stop()
        self.plot.setXLink(None)
        try:
            self.line.sigDragged.disconnect()
            self.line.sigPositionChangeFinished.disconnect()
        except (TypeError, RuntimeError):
            pass
        self.plot.clear()
