import pyqtgraph as pg
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from PyQt6.QtGui import QColor

MINIMUM_DURATION_MS = 15000  # 15 seconds recommended minimum per sound


class DurationBarWidget(QWidget):
    """Horizontal bar chart showing recording duration per sound label."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel('bottom', 'Duration (seconds)')
        self.plot_widget.getAxis('left').setWidth(0)
        self.plot_widget.getAxis('left').setTicks([])
        self.plot_widget.setMouseEnabled(x=False, y=False)
        self.plot_widget.setBackground('#2b2b2b')
        layout.addWidget(self.plot_widget)

        self._labels = []

    def set_data(self, label_durations: dict):
        """Update the bar chart. label_durations: {name: duration_ms}."""
        self.plot_widget.clear()
        self._labels = list(label_durations.keys())

        if not self._labels:
            return

        y_axis = self.plot_widget.getAxis('left')
        y_axis.setWidth(None)

        for i, label in enumerate(self._labels):
            dur_ms = label_durations[label]
            dur_s = dur_ms / 1000.0
            color = QColor(0, 180, 80, 200) if dur_ms >= MINIMUM_DURATION_MS else QColor(220, 60, 60, 200)
            bar = pg.BarGraphItem(
                x0=[0], width=[dur_s],
                y0=[i - 0.3], height=[0.6],
                brush=color, pen=pg.mkPen(None)
            )
            self.plot_widget.addItem(bar)

            # Duration text label at end of bar
            text = pg.TextItem(f"{dur_s:.1f}s", anchor=(0, 0.5), color='w')
            text.setPos(dur_s + 0.3, i)
            self.plot_widget.addItem(text)

        ticks = [[(i, label) for i, label in enumerate(self._labels)]]
        y_axis.setTicks(ticks)
        self.plot_widget.setYRange(-0.5, len(self._labels) - 0.5)

        # Set x range with some padding
        max_dur = max(label_durations.values()) / 1000.0 if label_durations else 1
        self.plot_widget.setXRange(0, max_dur * 1.2)

        # Adjust height based on number of labels
        height = max(80, len(self._labels) * 28 + 40)
        self.setFixedHeight(height)
