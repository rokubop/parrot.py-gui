"""Per-sound accuracy for the epoch that just finished.

The trainer has always computed this and the worker has always emitted it (the
dict in `TrainingWorker.epoch_complete`); the training view threw it away and
showed a single averaged number. An average cannot tell you that one sound sits
at 40% while the rest are at 97%, which is the most actionable thing on screen
during a run that lasts hours: it says which sound to record more of, and it
says it in the first few minutes rather than after the whole run.

Note the trainer scores these on the last net's validation pass rather than on
the ensemble (`audio_net.py`, where `accuracy_batch` falls out of the per-net
loop), so a single sound can wobble between epochs more than the averaged
accuracy does. The gap that matters here is between sounds, not between epochs.
"""
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPainter, QColor, QFontMetrics
from PyQt6.QtWidgets import QWidget, QSizePolicy

from config.config import BACKGROUND_LABEL
from gui import theme

# Accuracy bands, borrowing the data-quantity colours so "green is fine, red
# needs work" means the same thing here as it does in the Sounds tree.
BANDS = ((0.95, "Excellent"), (0.85, "Good"), (0.70, "Sufficient"))

ROW_HEIGHT = 22
BAR_HEIGHT = 10
PERCENT_WIDTH = 48
GUTTER = 10


def band_color(value):
    for threshold, name in BANDS:
        if value >= threshold:
            return theme.QUANTITY_COLORS[name]
    return theme.QUANTITY_COLORS["Not enough"]


class PerLabelAccuracy(QWidget):
    """One row per sound: name, bar, percentage."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._values = {}
        self._order = []
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(0)

    def clear(self):
        self._values = {}
        self._order = []
        self.setFixedHeight(0)
        self.update()

    def set_values(self, values):
        """`values` is {label: 0..1}. The row order is fixed on the first call so
        rows do not swap places every epoch, which makes a moving bar unreadable."""
        if not values:
            self.clear()
            return
        if set(values) != set(self._order):
            # silence last: it is the class the app added, not one of theirs.
            self._order = sorted(values, key=lambda l: (l == BACKGROUND_LABEL, l))
            self.setFixedHeight(ROW_HEIGHT * len(self._order))
        self._values = dict(values)
        self.update()

    def paintEvent(self, _event):
        if not self._order:
            return
        t = theme.colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        metrics = QFontMetrics(self.font())
        name_width = min(200, max(60, max(metrics.horizontalAdvance(label)
                                          for label in self._order) + 8))
        bar_left = name_width + GUTTER
        bar_width = max(20, self.width() - bar_left - PERCENT_WIDTH - GUTTER)

        for row, label in enumerate(self._order):
            value = max(0.0, min(1.0, self._values.get(label, 0.0)))
            top = row * ROW_HEIGHT
            color = QColor(band_color(value))

            p.setPen(QColor(t["text"]))
            p.drawText(QRectF(0, top, name_width, ROW_HEIGHT),
                       int(Qt.AlignmentFlag.AlignLeft
                           | Qt.AlignmentFlag.AlignVCenter), label)

            track = QRectF(bar_left, top + (ROW_HEIGHT - BAR_HEIGHT) / 2,
                           bar_width, BAR_HEIGHT)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t["plot_bg"]))
            p.drawRoundedRect(track, 2, 2)
            if value > 0:
                filled = QRectF(track)
                filled.setWidth(max(2.0, track.width() * value))
                p.setBrush(color)
                p.drawRoundedRect(filled, 2, 2)

            p.setPen(color)
            p.drawText(QRectF(self.width() - PERCENT_WIDTH, top,
                              PERCENT_WIDTH, ROW_HEIGHT),
                       int(Qt.AlignmentFlag.AlignRight
                           | Qt.AlignmentFlag.AlignVCenter), f"{value:.0%}")

        p.end()
