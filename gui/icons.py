"""Small monochrome icons, painted in the theme's own colours.

Emoji are drawn by the system emoji font in colours of its own choosing, out
of reach of any stylesheet and blind to the theme (the 👤 silhouette measured
1.28:1 on this toolbar). Painted paths take one colour from `theme.colors()`
at whatever size and device pixel ratio the button asks for.

A toolbar button has three backgrounds, so one colour is not enough: resting
`text_dim` measures 1.24:1 on the checked accent fill. Each icon carries a
pixmap per state and lets Qt pick - QToolButton asks for `State.On` when
checked and `Mode.Active` on hover, so no signal wiring is needed.

    state          background     icon colour     ratio
    resting        toolbar        text_dim         5.4
    hover          button_hover   text_bright      5.9
    checked        accent         accent_text      9.4

Geometry is in fractions of the icon box, so an icon is one drawing at any
size rather than a bitmap that softens when the interface is scaled up.
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


def _fixed_icon(draw, colour, size=14, dpr=None):
    """One colour for every state, for a button painting its own fill."""
    icon = QIcon()
    icon.addPixmap(_render(draw, colour, size, dpr))
    return icon


def _icon(draw, size, dpr, colour):
    return (_fixed_icon(draw, colour, size, dpr) if colour
            else _button_icon(draw, size, dpr))


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


def _draw_stop(painter, colour):
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(colour)
    painter.drawRoundedRect(QRectF(0.24, 0.24, 0.52, 0.52), 0.06, 0.06)


def _draw_pause(painter, colour):
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(colour)
    for x in (0.26, 0.58):
        painter.drawRoundedRect(QRectF(x, 0.20, 0.16, 0.60), 0.05, 0.05)


def _draw_record(painter, colour):
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(colour)
    painter.drawEllipse(QRectF(0.26, 0.26, 0.48, 0.48))


def _draw_restart(painter, colour):
    """Open ring plus a head. The gap is what says "again" and not "loading"."""
    pen = QPen(colour, 0.13)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    # Qt angles: 0 at 3 o'clock, counter-clockwise, sixteenths of a degree.
    painter.drawArc(QRectF(0.22, 0.22, 0.56, 0.56), 90 * 16, 300 * 16)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(colour)
    head = QPainterPath()
    head.moveTo(0.50, 0.06)
    head.lineTo(0.50, 0.32)
    head.lineTo(0.74, 0.19)
    head.closeSubpath()
    painter.drawPath(head)


def _draw_check(painter, colour):
    pen = QPen(colour, 0.14)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(0.20, 0.52)
    path.lineTo(0.41, 0.73)
    path.lineTo(0.80, 0.27)
    painter.drawPath(path)


def person(size=16, dpr=None):
    return _toolbar_icon(_draw_person, size, dpr)


def note(size=16, dpr=None):
    return _toolbar_icon(_draw_note, size, dpr)


def play(size=14, dpr=None, colour=None):
    return _icon(_draw_play, size, dpr, colour)


def stop(size=14, dpr=None, colour=None):
    return _icon(_draw_stop, size, dpr, colour)


def pause(size=14, dpr=None, colour=None):
    return _icon(_draw_pause, size, dpr, colour)


def record(size=14, dpr=None, colour=None):
    return _icon(_draw_record, size, dpr, colour)


def restart(size=14, dpr=None, colour=None):
    return _icon(_draw_restart, size, dpr, colour)


def check(size=14, dpr=None, colour=None):
    return _icon(_draw_check, size, dpr, colour)
