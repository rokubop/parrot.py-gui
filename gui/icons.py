"""Icons

Prefer painted paths over text glyphs (▶ ⏸) or emoji, because of:
a) same height in every font, so swapping play/pause doesn't shift the button
b) theme colours, including focus and disabled
c) sharp at any size or screen scale
"""
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QApplication

from gui import theme


def _render(draw, colour, size):
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


def _button_icon(draw, size=14, colour=None):
    """colour: for a button that paints its own fill, e.g. white on red"""
    t = theme.colors()
    icon = QIcon()
    for colour, mode in ((colour or t["text"], QIcon.Mode.Normal),
                         (colour or t["text_bright"], QIcon.Mode.Active),
                         (t["disabled_text"], QIcon.Mode.Disabled)):
        icon.addPixmap(_render(draw, colour, size), mode, QIcon.State.Off)
    return icon


def _draw_play(painter, colour):
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


def _draw_record(painter, colour):
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(colour)
    painter.drawEllipse(QRectF(0.26, 0.26, 0.48, 0.48))


def _draw_stop(painter, colour):
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(colour)
    painter.drawRoundedRect(QRectF(0.24, 0.24, 0.52, 0.52), 0.06, 0.06)


def _draw_dots(painter, colour):
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(colour)
    for x in (0.24, 0.5, 0.76):
        painter.drawEllipse(QRectF(x - 0.09, 0.41, 0.18, 0.18))


def _draw_restart(painter, colour):
    """Open ring plus a head. The gap is what says "again" and not "loading"."""
    pen = QPen(colour, 0.13)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    # Qt angles: 0 at 3 o'clock, counter-clockwise, sixteenths of a degree
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


def play():
    return _button_icon(_draw_play)


def pause():
    return _button_icon(_draw_pause)


def dots():
    return _button_icon(_draw_dots)


def record(colour=None):
    return _button_icon(_draw_record, colour=colour)


def restart():
    return _button_icon(_draw_restart)


def check(colour=None):
    return _button_icon(_draw_check, colour=colour)


def stop():
    return _button_icon(_draw_stop)
