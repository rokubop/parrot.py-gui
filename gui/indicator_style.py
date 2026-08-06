"""Check boxes and radio buttons that can be seen.

Fusion derives its indicator from the palette, and on this palette that came
out at **1.5:1** against the window - an unchecked box was a hollow outline you
had to already know was there. Measured, not guessed: the box border rendered
#3c434f on #23272e. The non-text contrast rule wants 3:1 for the boundary of a
control, and a checkbox is the example the rule is written around.

Restyling the indicator in QSS is the obvious fix and is the wrong one: setting
any `::indicator` property makes Qt take the stylesheet path for the whole
control, and a stylesheet indicator draws no tick unless it is handed an image
file. That is how this app once ended up with a plain green square. So the box
is painted here instead - one primitive, over Fusion, with the palette Fusion
would have derived it from ignored.

Colours come from `theme.colors()` at paint time, so a live theme switch is
picked up without reinstalling anything.

  state       box            border               mark
  unchecked   base           control_border 4.8   -
  hover       base           text          11.5   -
  checked     accent         accent               accent_text 9.4
  partial     accent         accent               accent_text (dash)
  disabled    disabled_bg    border               disabled_text

Covers item views too: a checkable row in a tree draws through the same
primitive, which is where most of this app's checkboxes actually live.
"""
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QProxyStyle, QStyle, QStyleFactory

from gui import theme

_PE = QStyle.PrimitiveElement
_SF = QStyle.StateFlag

# The tick, in fractions of the box - so it scales with whatever rect Qt hands
# us (a widget checkbox and a tree row's indicator are not the same size).
_TICK = ((0.24, 0.54), (0.43, 0.72), (0.76, 0.30))


def _square(rect):
    """Qt hands item views a rect wider than the indicator. Centre a square in
    it, and keep it an odd-free half-pixel grid so the 1px border stays crisp."""
    side = min(rect.width(), rect.height())
    return QRectF(rect.x() + (rect.width() - side) / 2.0 + 0.5,
                  rect.y() + (rect.height() - side) / 2.0 + 0.5,
                  side - 1, side - 1)


def _colors(state):
    t = theme.colors()
    if not state & _SF.State_Enabled:
        return (QColor(t["disabled_bg"]), QColor(t["border"]),
                QColor(t["disabled_text"]))
    if state & (_SF.State_On | _SF.State_NoChange):
        return (QColor(t["accent"]), QColor(t["accent"]),
                QColor(t["accent_text"]))
    edge = t["text"] if state & _SF.State_MouseOver else t["control_border"]
    return QColor(t["base"]), QColor(edge), QColor(t["text"])


class IndicatorStyle(QProxyStyle):
    def drawPrimitive(self, element, option, painter, widget=None):
        if element in (_PE.PE_IndicatorCheckBox,
                       _PE.PE_IndicatorItemViewItemCheck):
            self._checkbox(option, painter)
        elif element == _PE.PE_IndicatorRadioButton:
            self._radio(option, painter)
        else:
            super().drawPrimitive(element, option, painter, widget)

    def _checkbox(self, option, painter):
        rect = _square(QRectF(option.rect))
        fill, edge, mark = _colors(option.state)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(fill)
        painter.setPen(QPen(edge, 1.4))
        painter.drawRoundedRect(rect, 3, 3)

        width = max(1.6, rect.width() * 0.13)
        if option.state & _SF.State_NoChange:
            # Partly checked - a dash, never a half-drawn tick.
            painter.setPen(QPen(mark, width, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap))
            y = rect.y() + rect.height() / 2
            painter.drawLine(QPointF(rect.x() + rect.width() * 0.26, y),
                             QPointF(rect.x() + rect.width() * 0.74, y))
        elif option.state & _SF.State_On:
            path = QPainterPath()
            for i, (fx, fy) in enumerate(_TICK):
                point = (rect.x() + rect.width() * fx,
                         rect.y() + rect.height() * fy)
                path.moveTo(*point) if i == 0 else path.lineTo(*point)
            painter.setPen(QPen(mark, width, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap,
                                Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        painter.restore()

    def _radio(self, option, painter):
        rect = _square(QRectF(option.rect))
        fill, edge, mark = _colors(option.state)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(fill)
        painter.setPen(QPen(edge, 1.4))
        painter.drawEllipse(rect)
        if option.state & _SF.State_On:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(mark)
            painter.drawEllipse(rect.adjusted(rect.width() * 0.28,
                                              rect.height() * 0.28,
                                              -rect.width() * 0.28,
                                              -rect.height() * 0.28))
        painter.restore()


def install(app):
    """Fusion, with the indicators repainted. Replaces app.setStyle("Fusion")."""
    app.setStyle(IndicatorStyle(QStyleFactory.create("Fusion")))
