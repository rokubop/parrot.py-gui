"""Small monochrome icons, painted in the theme's own colours.

Text glyphs like ▶ and ⏸ differ in height from font to font and shift the
layout when swapped, and emoji are drawn in colours of their own, blind to the
theme. Painted paths take one colour from `theme.colors()` at whatever size
and device pixel ratio the button asks for.

Geometry is in fractions of the icon box, so an icon is one drawing at any
size rather than a bitmap that softens when the interface is scaled up.
"""
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import QApplication

from gui import theme


def _render(draw, colour, size, dpr):
    if dpr is None:
        app = QApplication.instance()
        dpr = app.devicePixelRatio() if app else 1.0
    pixmap = QPixmap(int(size * dpr), int(size * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(size, size)          # draw in a 0..1 box
    draw(painter, QColor(colour))
    painter.end()
    return pixmap


def _button_icon(draw, size=14, dpr=None):
    """Push-button icon: resting on `button`, hover on `button_hover`, and a
    greyed pixmap so a disabled control does not keep a full-strength glyph."""
    t = theme.colors()
    icon = QIcon()
    for colour, mode in ((t["text"], QIcon.Mode.Normal),
                         (t["text_bright"], QIcon.Mode.Active),
                         (t["disabled_text"], QIcon.Mode.Disabled)):
        icon.addPixmap(_render(draw, colour, size, dpr), mode, QIcon.State.Off)
    return icon


# ---- transport ----------------------------------------------------------

def _draw_play(painter, colour):
    """Filled triangle, nudged right: centred on the box it reads left-heavy."""
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(colour)
    path = QPainterPath()
    path.moveTo(0.30, 0.18)
    path.lineTo(0.82, 0.50)
    path.lineTo(0.30, 0.82)
    path.closeSubpath()
    painter.drawPath(path)


def _draw_pause(painter, colour):
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(colour)
    for x in (0.26, 0.58):
        painter.drawRoundedRect(QRectF(x, 0.20, 0.16, 0.60), 0.05, 0.05)


def play(size=14, dpr=None):
    return _button_icon(_draw_play, size, dpr)


def pause(size=14, dpr=None):
    return _button_icon(_draw_pause, size, dpr)
