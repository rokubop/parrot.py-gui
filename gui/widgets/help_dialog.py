"""Help rendering: the diagrams, and one renderer for a help topic.

The words live in `gui/content/`. This module turns a topic from there
into a widget, and that same widget is what the ``?  Help`` modal shows and
what the About page stacks up - so a topic is written once and drawn the same
way wherever it appears.
"""
import math

from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QFrame, QSizePolicy
)

from gui import components, content, theme


class WrappedBody(QLabel):
    """Word-wrapped rich text that keeps the height its copy actually needs.

    A word-wrapped QLabel reports a one-line sizeHint, so layouts clip it.
    Re-asking heightForWidth at whatever width it was just given stays correct
    through resizes and text changes, unlike a pinned width.
    """

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        needed = self.heightForWidth(self.width())
        if needed > 0 and needed != self.minimumHeight():
            self.setMinimumHeight(needed)


class FramesDiagram(QWidget):
    """One “pop” cut into the 15 ms frames the model really works on, with the
    label each frame comes out as: a sound is never judged whole, and frames
    that no longer sound like it come out as background."""

    CAPTION = "One “pop”, as detection sees it:"

    # Illustration length only (10 x 15 ms = 150 ms, about a lip pop).
    # Deliberately not 16, which reads as if tied to the 16 kHz rate; it isn't.
    FRAMES = 10

    # Envelope tuned as a set so the strip comes out silence x2 / pop x4 /
    # silence x4, with the last pop frame nearly silent yet still detected -
    # that contrast is the whole point of the picture.
    SOUND_START = 0.21   # quiet lead-in before the pop
    SOUND_END = 0.60     # after this the room is genuinely silent again
    ATTACK = 0.015
    DECAY = 9.5          # steep collapse from the peak
    RELEASE = 0.02
    NOISE_FLOOR = 0.035  # room tone - what "true silence" looks like here
    MATCH_LEVEL = 0.025  # frame level that still classifies as the sound
    GAP = 5              # pixels between frames - they are drawn cut apart
    STRIP_HEIGHT = 78
    CHIP_ROW = 20        # room for the per-frame label under each frame

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(46 * self.FRAMES)
        self.setFixedHeight(self.STRIP_HEIGHT + self.CHIP_ROW)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    @classmethod
    def _sample(cls, t):
        """A plausible pop at time t in [0, 1]. Deterministic, so the
        illustration draws identically every time."""
        carrier = (0.80 * math.sin(t * 168.0)
                   + 0.20 * math.sin(t * 431.0 + 1.1)
                   + 0.09 * math.sin(t * 1187.0 + 0.4))
        room = cls.NOISE_FLOOR * (0.6 + 0.4 * math.sin(t * 211.0)) * carrier
        if t < cls.SOUND_START or t > cls.SOUND_END:
            return room

        u = t - cls.SOUND_START
        span = cls.SOUND_END - cls.SOUND_START
        if u < cls.ATTACK:
            env = u / cls.ATTACK
        else:
            env = math.exp(-(u - cls.ATTACK) * cls.DECAY)
        if span - u < cls.RELEASE:
            env *= max(0.0, (span - u) / cls.RELEASE)
        return max(-1.0, min(1.0, env * carrier + room))

    @classmethod
    def _frame_matches(cls, index):
        """Whether this frame still reads as the sound, from its own level -
        the same shape as the real thing, where each frame is judged alone."""
        t0, t1 = index / cls.FRAMES, (index + 1) / cls.FRAMES
        steps = 48
        total = sum(cls._sample(t0 + (t1 - t0) * s / steps) ** 2
                    for s in range(steps + 1))
        return math.sqrt(total / (steps + 1)) >= cls.MATCH_LEVEL

    def _frame_rect(self, index, width):
        """Frames are laid out with a real gap between them: the sound is cut
        into pieces here, and it should look cut, not ruled."""
        span = (width - self.GAP * (self.FRAMES - 1)) / self.FRAMES
        return QRectF(index * (span + self.GAP), 0, span, self.STRIP_HEIGHT)

    def paintEvent(self, _event):
        t = theme.colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        mid = self.STRIP_HEIGHT / 2
        half = self.STRIP_HEIGHT / 2 - 6
        wave_pen = QPen(QColor(*t["wave"]), 1.2)
        fill = QColor(*t["wave_fill"])
        border = QColor(t["border"])

        # Stylesheets don't reach QPainter text, so size it here
        chip_font = self.font()
        chip_font.setPixelSize(theme.TYPE_SCALE["body"])

        for i in range(self.FRAMES):
            rect = self._frame_rect(i, w)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t["plot_bg"]))
            p.drawRect(rect)

            # This frame's slice of the sound, drawn only within this frame.
            t0, t1 = i / self.FRAMES, (i + 1) / self.FRAMES
            steps = max(2, int(rect.width()))
            top_pts, bottom_pts = [], []
            for s in range(steps + 1):
                f = s / steps
                v = self._sample(t0 + (t1 - t0) * f)
                x = rect.left() + rect.width() * f
                top_pts.append(QPointF(x, mid - v * half))
                bottom_pts.append(QPointF(x, mid + v * half))
            p.setBrush(fill)
            p.drawPolygon(QPolygonF(top_pts + list(reversed(bottom_pts))))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(wave_pen)
            p.drawPolyline(QPolygonF(top_pts))
            p.drawPolyline(QPolygonF(bottom_pts))

            p.setPen(QPen(border, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))

            # What this frame comes out as. "silence" is the real background
            # label ( BACKGROUND_LABEL ), not a stand-in.
            matches = self._frame_matches(i)
            p.setFont(chip_font)
            p.setPen(QColor(*t["wave"]) if matches else QColor(t["text_dim"]))
            p.drawText(QRectF(rect.left(), self.STRIP_HEIGHT + 2,
                              rect.width(), self.CHIP_ROW),
                       int(Qt.AlignmentFlag.AlignCenter),
                       "pop" if matches else "silence")

        p.end()


# The names topics use for their pictures. A topic in gui/content names one
# of these; nothing outside this module knows a diagram is a widget.
DIAGRAMS = {
    "frames": FramesDiagram,
}


def rows_html(rows):
    """Label/body rows. A row whose body is None is a section header spanning
    both columns."""
    t = theme.colors()
    dim, text = t["text_dim"], t["text"]
    out = ["<table cellspacing='0' cellpadding='2'>"]
    for label, body in rows:
        if body is None:
            out.append(
                f"<tr><td colspan='2' style='color:{t['text_bright']}; "
                f"font-weight:bold; padding-top:10px;'>{label}</td></tr>")
        else:
            out.append(
                f"<tr><td style='color:{dim}; font-weight:bold; "
                f"padding-right:12px; white-space:nowrap; vertical-align:top;'>"
                f"{label}</td><td style='color:{text};'>{body}</td></tr>")
    out.append("</table>")
    return "".join(out)


def bands_html(bands):
    """Rating name + the span it covers, each in the colour that rating wears
    everywhere else in the app."""
    t = theme.colors()
    rows = "".join(
        f"<tr><td style='color:{theme.QUANTITY_COLORS[name]}; "
        f"font-weight:bold; padding:2px 14px 2px 0; white-space:nowrap;'>"
        f"{name}</td><td style='color:{t['text']}; padding:2px 0;'>{span}</td>"
        f"</tr>" for name, span in bands)
    return f"<table cellspacing='0' cellpadding='0'>{rows}</table>"


# Wider than a comfortable measure, so a long topic fits on one screen -
# which matters more for help nobody scrolls.
BODY_WIDTH = 860


def _prose(html):
    body = WrappedBody(html)
    body.setMaximumWidth(BODY_WIDTH)
    return body


def topic_content(key, parent=None, stretch=True):
    """A topic drawn as a widget: diagram, intro, bands, rows, note.

    The one renderer for help. The ``?  Help`` modal shows this, and the About
    page stacks one per topic, so a topic looks the same in both.
    """
    spec = content.get(key) if isinstance(key, str) else key
    panel = QWidget(parent)
    inner = QVBoxLayout(panel)
    inner.setContentsMargins(0, 0, 0, 0)
    inner.setSpacing(12)

    if spec["diagram"]:
        widget = DIAGRAMS[spec["diagram"]]()
        # The caption belongs to the drawing, not to this slot.
        text = getattr(widget, "CAPTION", "")
        if text:
            caption = QLabel(text)
            caption.setStyleSheet(f"color: {theme.colors()['text_dim']};")
            inner.addWidget(caption)
        inner.addWidget(widget)
    if spec["intro"]:
        inner.addWidget(_prose(spec["intro"]))
    if spec["bands"]:
        inner.addWidget(_prose(bands_html(spec["bands"])))
    if spec["rows"]:
        inner.addWidget(_prose(rows_html(spec["rows"])))
    if spec["note"]:
        inner.addWidget(_prose(spec["note"]))

    if stretch:
        # A scroll area resizes this to its viewport; without a trailing spring
        # spare height is shared between the rows instead of sitting below.
        inner.addStretch(1)
    return panel


def topics_content(keys, parent=None, stretch=True):
    """Several topics, each under its own title. How a screen shows just the
    help it needs, and how About shows a tab's."""
    panel = QWidget(parent)
    inner = QVBoxLayout(panel)
    inner.setContentsMargins(0, 0, 0, 0)
    inner.setSpacing(0)
    for i, key in enumerate(keys):
        spec = content.get(key) if isinstance(key, str) else key
        if i:
            inner.addSpacing(22)
        heading = QLabel(spec["title"])
        heading.setStyleSheet(components.heading_style("card"))
        inner.addWidget(heading)
        inner.addSpacing(8)
        inner.addWidget(topic_content(spec, stretch=False))
    if stretch:
        inner.addStretch(1)
    return panel


def scrolled(content, max_height=560):
    """Wrap embedded topic content so a long topic scrolls instead of growing
    its dialog past the screen. Short content still sizes to fit."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    # No focus for help topic scroll. Tab goes to its controls instead.
    scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    scroll.setWidget(content)
    scroll.setMaximumHeight(max_height)
    scroll.setMinimumWidth(content.sizeHint().width() + 8)
    return scroll


def _fit_to_screen(dlg, content_widget, width=760):
    """Open at the size the content wants, capped by a fraction of the actual
    screen - help you have to scroll is help you skim."""
    screen = dlg.screen() or QApplication.primaryScreen()
    available = screen.availableGeometry() if screen else None
    max_h = int(available.height() * 0.85) if available else 720
    max_w = int(available.width() * 0.7) if available else width
    wanted = content_widget.sizeHint()
    dlg.resize(min(max(width, wanted.width() + 56), max_w),
               min(wanted.height() + 96, max_h))


def show_help(parent, title, keys):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    v = QVBoxLayout(dlg)
    v.setContentsMargins(20, 16, 20, 16)
    panel = topics_content(keys)
    v.addWidget(scrolled(panel, max_height=16777215))

    close = QPushButton("Close")
    close.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    close.clicked.connect(dlg.accept)
    row = QHBoxLayout()
    row.addStretch()
    row.addWidget(close)
    v.addLayout(row)
    _fit_to_screen(dlg, panel)
    dlg.exec()


def help_button(parent, title, keys):
    """Flat '? Help' button opening these topics in a modal."""
    t = theme.colors()
    btn = QPushButton("?  Help", parent)
    btn.setFlat(True)
    btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    btn.setStyleSheet(
        f"QPushButton {{ color: {t['text_dim']}; background: transparent; "
        f"border: none; padding: 2px 6px; }} "
        f"QPushButton:hover {{ color: {t['text_bright']}; }} "
        f"QPushButton:focus {{ border: 2px solid {t['focus']}; "
        f"border-radius: {t['radius']}; padding: 0px 4px; }}")
    btn.clicked.connect(lambda: show_help(parent, title, keys))
    return btn
