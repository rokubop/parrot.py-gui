"""Small monochrome icons, painted in the theme's own colours.

The toolbar carried two colour emoji, 👤 and 📝. An emoji is drawn by the
system emoji font in the colours that font chose, and ignores the colour its
label asks for: on this dark toolbar the person silhouette came out dark purple
(#442a6c), measuring **1.28:1** against the toolbar behind it. Nothing in a
stylesheet can reach it, and it does not change with the theme.

Painted paths instead - one colour, from `theme.colors()`, at whatever size and
device pixel ratio the button asks for. Same reasoning as the frame-status row
in talon_test.py, which dropped ⏱ for a word.

A toolbar button is three different backgrounds, though, so one colour is not
enough. Checked fills the button with the accent green, where the resting
`text_dim` measures **1.24:1** - the Notes icon vanished exactly when the
drawer was open. Each icon therefore carries a pixmap per state and lets Qt
pick, which needs no signal wiring: QToolButton asks for `State.On` when it is
checked and `Mode.Active` when the pointer is over it.

    state          background     icon colour     ratio
    resting        toolbar        text_dim         5.4
    hover          button_hover   text_bright      5.9
    checked        accent         accent_text      9.4

Geometry is in fractions of the icon box, so an icon is one drawing at any size
rather than a bitmap that softens when the interface is scaled up.
"""
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
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


def _toolbar_icon(draw, size=16, dpr=None):
    """One drawing, four pixmaps: resting, hover, checked, checked+hover."""
    t = theme.colors()
    icon = QIcon()
    for colour, mode, state in (
            (t["text_dim"], QIcon.Mode.Normal, QIcon.State.Off),
            (t["text_bright"], QIcon.Mode.Active, QIcon.State.Off),
            (t["accent_text"], QIcon.Mode.Normal, QIcon.State.On),
            (t["accent_text"], QIcon.Mode.Active, QIcon.State.On)):
        icon.addPixmap(_render(draw, colour, size, dpr), mode, state)
    return icon


def _draw_person(painter, colour):
    """Head and shoulders, filled. Reads at 16px where an outline would not."""
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(colour)
    painter.drawEllipse(QRectF(0.325, 0.14, 0.35, 0.35))
    shoulders = QPainterPath()
    # Top half of an ellipse wider than the head, clipped by the icon box, so
    # the silhouette ends flat at the bottom the way a bust does.
    shoulders.arcMoveTo(QRectF(0.12, 0.56, 0.76, 0.62), 0)
    shoulders.arcTo(QRectF(0.12, 0.56, 0.76, 0.62), 0, 180)
    shoulders.closeSubpath()
    painter.drawPath(shoulders)


def _draw_note(painter, colour):
    """A page with lines on it, outlined - a filled page at this size is a
    blob, and the lines are what say "notes" rather than "file"."""
    pen = QPen(colour, 0.085)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(0.17, 0.11, 0.66, 0.78), 0.1, 0.1)
    for y in (0.34, 0.5, 0.66):
        painter.drawLine(QPointF(0.32, y), QPointF(0.68, y))


def person(size=16, dpr=None):
    return _toolbar_icon(_draw_person, size, dpr)


def note(size=16, dpr=None):
    return _toolbar_icon(_draw_note, size, dpr)
