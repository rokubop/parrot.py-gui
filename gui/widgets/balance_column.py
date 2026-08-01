"""The balance bar, drawn inside the sound table instead of beside it.

The training page used to carry the checklist on the left and a separate bar
chart on the right, which is the same twenty labels drawn twice with the reader
doing the join. One column, painted per row, says it once.

Solid is what the trainer loads. Past the recorded length it is hatched, because
that part is the same audio again rather than anything new - the distinction
matters, since a sound at +100% has not learned twice as much, it has been
counted twice. Short of the recorded length it is a hollow tail: recorded, not
used. The dashed line is the target every label is being pulled toward.

A delegate rather than one widget per row: the table repaints on every tick of
the checklist, and twenty child widgets re-laid-out per tick is how a list starts
feeling heavy.
"""
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QPen, QPainter
from PyQt6.QtWidgets import QStyledItemDelegate, QWidget, QHBoxLayout, QLabel

from gui import theme

# (size, loaded, target, scale) lives here on the bar column's item.
BAR_ROLE = Qt.ItemDataRole.UserRole + 7

BAR_HEIGHT = 13
STRIPE_STEP = 4          # px between stripes, measured to stay legible at 13px
WARN = "#e0b020"


def _stripe(painter, rect, color, background):
    """Diagonal stripes drawn by hand.

    Qt's BDiagPattern is a 1px hatch on an 8px grid, which at bar height is a
    faint texture rather than a pattern - it read as "slightly different green"
    instead of "this part is repeated". These are 2px on a 4px pitch, clipped to
    the block, which survives being 13 pixels tall.
    """
    painter.save()
    painter.setClipRect(rect)
    painter.fillRect(rect, background)
    pen = QPen(color, 2)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    painter.setPen(pen)
    x = rect.left() - rect.height()
    while x < rect.right() + rect.height():
        painter.drawLine(int(x), int(rect.bottom()),
                         int(x + rect.height()), int(rect.top()))
        x += STRIPE_STEP
    painter.restore()


class BalanceBarDelegate(QStyledItemDelegate):
    """Paints one label's before/after against the shared target line.

    Carries the whole story on its own: the column that used to spell out
    "Oversampled +100%" beside it is gone. Twenty rows of that text turned a
    glanceable list into a wall of vocabulary, and the words are in the legend
    once, where they can be read once.
    """

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        data = index.data(BAR_ROLE)
        if not data:
            return
        size, loaded, target, scale, short = data
        if not scale:
            return

        t = theme.colors()
        rect = option.rect
        left = rect.left() + 4
        width = max(20, rect.width() - 12)
        y = rect.center().y() - BAR_HEIGHT / 2

        def x_of(value):
            return left + width * (min(value, scale) / scale)

        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing, False)

        accent = QColor(t["accent"])
        dim = QColor(t["text_dim"])
        base = QColor(t["base"])

        # What was recorded and is being used, whole.
        solid_to = min(size, loaded)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(WARN) if short else accent)
        painter.drawRect(QRectF(left, y, max(1.0, x_of(solid_to) - left),
                                BAR_HEIGHT))

        if loaded > size:
            # The same audio again. Striped, because it is not more recording -
            # a label at +100% has been counted twice, not learned twice.
            block = QRectF(x_of(size), y, x_of(loaded) - x_of(size), BAR_HEIGHT)
            tint = QColor(WARN if short else t["accent"])
            tint.setAlpha(70)
            _stripe(painter, block, QColor(WARN) if short else accent, tint)
        elif loaded < size:
            # Recorded, and left out of this run.
            block = QRectF(x_of(loaded), y, x_of(size) - x_of(loaded), BAR_HEIGHT)
            painter.setBrush(base)
            painter.setPen(QPen(dim, 1))
            painter.drawRect(block.adjusted(0, 0.5, -0.5, -0.5))

        if target:
            painter.setPen(QPen(dim, 1, Qt.PenStyle.DashLine))
            tx = x_of(target)
            painter.drawLine(int(tx), int(rect.top() + 1),
                             int(tx), int(rect.bottom() - 1))
        painter.restore()


class _Swatch(QWidget):
    """A sample painted by the same code as the column.

    Drawn rather than approximated in a stylesheet: a legend whose stripes are a
    slightly different gradient from the real ones teaches the wrong thing, and
    the stripe pitch is the whole point of this one.
    """
    WIDTH = 46

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(self.WIDTH, BAR_HEIGHT + 4)

    def paintEvent(self, _event):
        t = theme.colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        accent = QColor(t["accent"])
        y = 2
        half = self.WIDTH * 0.55
        painter.setPen(Qt.PenStyle.NoPen)

        if self.kind == "short":
            painter.setBrush(QColor(WARN))
            painter.drawRect(QRectF(0, y, half, BAR_HEIGHT))
            tint = QColor(WARN)
            tint.setAlpha(70)
            _stripe(painter, QRectF(half, y, self.WIDTH - half, BAR_HEIGHT),
                    QColor(WARN), tint)
        elif self.kind == "oversample":
            painter.setBrush(accent)
            painter.drawRect(QRectF(0, y, half, BAR_HEIGHT))
            tint = QColor(accent)
            tint.setAlpha(70)
            _stripe(painter, QRectF(half, y, self.WIDTH - half, BAR_HEIGHT),
                    accent, tint)
        elif self.kind == "undersample":
            painter.setBrush(accent)
            painter.drawRect(QRectF(0, y, half, BAR_HEIGHT))
            painter.setBrush(QColor(t["base"]))
            painter.setPen(QPen(QColor(t["text_dim"]), 1))
            painter.drawRect(QRectF(half, y + 0.5, self.WIDTH - half - 0.5,
                                    BAR_HEIGHT - 1))
        else:
            painter.setBrush(accent)
            painter.drawRect(QRectF(0, y, self.WIDTH, BAR_HEIGHT))
        painter.end()


def balance_legend(parent=None):
    """What each kind of bar means, once, instead of on every row.

    The terms are the trainer's own - the log prints "using oversampling: +27%"
    while the run goes - so they are taught here rather than replaced with
    something friendlier that would leave the two halves of the app disagreeing.
    """
    t = theme.colors()
    box = QWidget(parent)
    grid = QHBoxLayout(box)
    grid.setContentsMargins(2, 6, 2, 0)
    grid.setSpacing(18)
    # "Sampled" is left out: it means nothing was done, which the bar already
    # shows by sitting at its own size.
    for kind, term, meaning in (
            ("oversample", "Oversampled", "(repeat)"),
            ("undersample", "Undersampled", "(trim)"),
            ("short", "Still short", "(2x max repeat)")):
        cell = QHBoxLayout()
        cell.setSpacing(7)
        cell.addWidget(_Swatch(kind))
        text = QLabel(f"<b style='color:{t['text']};'>{term}</b> "
                      f"<span style='color:{t['text_dim']};'>{meaning}</span>")
        text.setTextFormat(Qt.TextFormat.RichText)
        cell.addWidget(text)
        grid.addLayout(cell)
    grid.addStretch()
    return box
