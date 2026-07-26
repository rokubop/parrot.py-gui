"""How much of each sound goes in, and how much of it gets thrown away.

The trainer levels the dataset before it learns anything, so a model cannot learn
that guessing the most abundant sound is a good bet. It takes the mean of the per
sound frame counts plus half a standard deviation as a target, then cuts anything
more than 1.25x that back down to it and duplicates anything below target/1.25
( `generate_data_balance_strategy_map`, lib/load_data.py ).

The 1.25 band matters to the drawing: a sound moderately above the target keeps
everything it has, so shading it as waste would be a lie. Only the genuinely
truncated part is drawn hollow.

The consequence is worth seeing rather than reading: recording one sound to 200 s
while another sits at 30 s throws most of the 200 s away. The Sounds tab's
per sound seconds cannot show that, because it is about one sound at a time and
this is entirely about the comparison between them.
"""
import statistics

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPainter, QColor, QPen, QFontMetrics
from PyQt6.QtWidgets import QWidget, QSizePolicy

from gui import theme

ROW_HEIGHT = 20
BAR_HEIGHT = 9
SECONDS_WIDTH = 42
GUTTER = 8
LEGEND_ROW = 16

# lib/load_data.py truncates a label only once it is this far above the target.
TRUNCATE_ABOVE = 1.25


def trim_target(values):
    """The trainer's truncation point: mean + half a standard deviation.

    pstdev, not stdev: the trainer uses np.std, which is the population standard
    deviation ( ddof=0 ). The sample version puts the line several seconds too
    far right, which is exactly the kind of quiet wrongness a picture cannot
    admit to.
    """
    if not values:
        return 0
    if len(values) == 1:
        return values[0]
    return statistics.mean(values) + statistics.pstdev(values) / 2


def kept_seconds(value, target):
    """What actually reaches training, of a sound holding `value` seconds."""
    return target if value > target * TRUNCATE_ABOVE else value


class BalanceBars(QWidget):
    """One bar per sound. Solid up to the trim point, hollow past it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pairs = []
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(0)

    def set_pairs(self, pairs):
        """`pairs` is [(label, seconds), ...] in the order they should appear."""
        self._pairs = list(pairs)
        self.setFixedHeight(
            ROW_HEIGHT * len(self._pairs) + (LEGEND_ROW if self._pairs else 0))
        self.update()

    def paintEvent(self, _event):
        if not self._pairs:
            return
        t = theme.colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        seconds = [value for _label, value in self._pairs]
        target = trim_target(seconds)
        scale_max = max(max(seconds), target) or 1

        metrics = QFontMetrics(self.font())
        name_width = min(160, max(50, max(metrics.horizontalAdvance(label)
                                          for label, _v in self._pairs) + 8))
        bar_left = name_width + GUTTER
        bar_width = max(20, self.width() - bar_left - SECONDS_WIDTH - GUTTER)
        target_x = bar_left + bar_width * (target / scale_max)

        accent = QColor(t["accent"])
        discarded = QColor(t["text_dim"])

        for row, (label, value) in enumerate(self._pairs):
            top = row * ROW_HEIGHT
            y = top + (ROW_HEIGHT - BAR_HEIGHT) / 2

            p.setPen(QColor(t["text"]))
            p.drawText(QRectF(0, top, name_width, ROW_HEIGHT),
                       int(Qt.AlignmentFlag.AlignLeft
                           | Qt.AlignmentFlag.AlignVCenter), label)

            kept = kept_seconds(value, target)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(accent)
            p.drawRect(QRectF(bar_left, y, max(2.0, kept / scale_max * bar_width),
                              BAR_HEIGHT))
            if kept < value:
                # Drawn hollow because it is recorded, and not used.
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(discarded, 1))
                p.drawRect(QRectF(target_x, y + 0.5,
                                  (value - kept) / scale_max * bar_width,
                                  BAR_HEIGHT - 1))

            p.setPen(QColor(t["text_dim"]))
            p.drawText(QRectF(self.width() - SECONDS_WIDTH, top,
                              SECONDS_WIDTH, ROW_HEIGHT),
                       int(Qt.AlignmentFlag.AlignRight
                           | Qt.AlignmentFlag.AlignVCenter), f"{value:.0f}s")

        # The line is a reference mark rather than a promise that everything
        # crossing it gets cut, so it is always drawn and named for where it
        # sits. Labelling it "cut back to here" would be false for a sound
        # sitting inside the 1.25x band, which keeps everything it has.
        bottom = ROW_HEIGHT * len(self._pairs)
        p.setPen(QPen(discarded, 1, Qt.PenStyle.DashLine))
        p.drawLine(QRectF(target_x, 0, 0, bottom).topLeft(),
                   QRectF(target_x, 0, 0, bottom).bottomLeft())
        p.setPen(QColor(t["text_dim"]))
        p.drawText(QRectF(0, bottom, self.width(), LEGEND_ROW),
                   int(Qt.AlignmentFlag.AlignCenter), "a bit above average")
        p.end()
