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
from gui.content import MS_PER_FRAME
from lib.print_status import get_quantity_rating


class WrappedBody(QLabel):
    """Word-wrapped rich text that keeps the height its copy actually needs.

    A word-wrapped QLabel reports a one-line sizeHint, so layouts clip it.
    Re-asking heightForWidth at whatever width it was just given stays correct
    through resizes and text changes, unlike a pinned width.
    """

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        components.enable_links(self)

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
    FRAME_MS = 15        # RATE * RECORD_SECONDS / SLIDING_WINDOW_AMOUNT samples

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

        chip_font = components.painter_font(self)

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


class PipelineDiagram(QWidget):
    """Record, train, connect, and the tab each happens on. Same order and
    names as Home's numbered steps, deliberately."""

    STEPS = (
        ("You record", "many takes of each sound", "Sounds"),
        ("Parrot trains", "one model, all your sounds", "Models"),
        ("You take it", "the model file goes where you need it", "Integrations"),
    )

    BOX_H = 52
    SUB_ROW = 17
    TAB_ROW = 18
    GAP = 34            # room for the arrow between boxes
    ARROW_HEAD = 7

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(150 * len(self.STEPS))
        self.setFixedHeight(self.BOX_H + self.SUB_ROW + self.TAB_ROW + 6)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)

    def _arrow(self, painter, x0, x1, y, color):
        pad = 7
        x0, x1 = x0 + pad, x1 - pad
        head = self.ARROW_HEAD
        painter.setPen(QPen(color, 1.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(QPointF(x0, y), QPointF(x1 - head + 1, y))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF([
            QPointF(x1, y),
            QPointF(x1 - head, y - head * 0.62),
            QPointF(x1 - head, y + head * 0.62)]))

    def paintEvent(self, _event):
        t = theme.colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        accent = QColor(t["accent"])
        dim = QColor(t["text_dim"])
        bright = QColor(t["text_bright"])
        small = components.painter_font(self)

        n = len(self.STEPS)
        span = (self.width() - self.GAP * (n - 1)) / n
        x = 0.0
        for index, (title, sub, tab) in enumerate(self.STEPS):
            rect = QRectF(x, 0, span, self.BOX_H)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t["plot_bg"]))
            p.drawRect(rect)
            p.setPen(QPen(accent, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))

            p.setFont(self.font())
            p.setPen(bright)
            p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), title)

            p.setFont(small)
            p.setPen(dim)
            p.drawText(QRectF(x, self.BOX_H + 1, span, self.SUB_ROW),
                       int(Qt.AlignmentFlag.AlignCenter), sub)
            p.setPen(accent)
            p.drawText(QRectF(x, self.BOX_H + self.SUB_ROW, span,
                              self.TAB_ROW),
                       int(Qt.AlignmentFlag.AlignCenter), f"{tab} tab")

            if index < n - 1:
                self._arrow(p, x + span, x + span + self.GAP,
                            self.BOX_H / 2, dim)
            x += span + self.GAP
        p.end()


def pipeline_diagram_widget():
    return PipelineDiagram()


def frames_diagram_widget():
    return FramesDiagram()


class NetsDiagram(QWidget):
    """Why net count is worth a thought: each net trains from its own random
    start on its own shuffle, so they disagree, and averaging dilutes the
    unlucky one.

    Not a vote, and the drawing has to stay honest about that: the nets output
    confidences and TinyAudioNetEnsemble takes their arithmetic mean, so a
    confident net outweighs two hesitant ones. Calling it voting is what makes
    people ask whether the count should be odd."""

    # Deterministic, picked so net 2 is confidently wrong - the case the
    # picture exists to explain. The averaged row is computed, never typed.
    CAPTION = (f"Example of 3 neural networks each scoring one frame "
               f"({MS_PER_FRAME} ms) on what it thinks the sound is.")

    LABELS = ("pop", "ah", "silence")
    TRUE_INDEX = 0
    VOTES = (
        (0.72, 0.18, 0.10),
        (0.38, 0.45, 0.17),   # this one hears "ah" - on its own it misfires
        (0.66, 0.21, 0.13),
    )

    TITLE_ROW = 16
    BAR_AREA = 62
    LABEL_ROW = 18
    PANEL_GAP = 8
    GROUP_GAP = 44       # holds the arrow into the averaged panel
    BAR_GAP = 4
    ARROW_HEAD = 7

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(88 * (len(self.VOTES) + 1))
        self.setFixedHeight(self.TITLE_ROW + self.BAR_AREA + self.LABEL_ROW + 6)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    @classmethod
    def averaged(cls):
        """What the ensemble actually does: sum the nets, divide by the count."""
        return tuple(sum(v[i] for v in cls.VOTES) / len(cls.VOTES)
                     for i in range(len(cls.LABELS)))

    def _panels(self):
        panels = [(f"Net {i + 1}", v) for i, v in enumerate(self.VOTES)]
        panels.append(("Averaged", self.averaged()))
        return panels

    def _draw_arrow(self, painter, x0, x1, y, color):
        """Into the averaged panel, so it reads as a consequence of the three
        to its left rather than a fourth net."""
        pad = 6
        x0, x1 = x0 + pad, x1 - pad
        head = self.ARROW_HEAD
        painter.setPen(QPen(color, 1.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(QPointF(x0, y), QPointF(x1 - head + 1, y))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF([
            QPointF(x1, y),
            QPointF(x1 - head, y - head * 0.62),
            QPointF(x1 - head, y + head * 0.62)]))

    def paintEvent(self, _event):
        t = theme.colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        panels = self._panels()
        n = len(panels)
        total_gap = self.PANEL_GAP * (n - 2) + self.GROUP_GAP
        span = (self.width() - total_gap) / n

        title_font = components.painter_font(self)

        accent = QColor(t["accent"])
        wrong = QColor(theme.QUANTITY_COLORS["Sufficient"])  # shared caution amber
        dim = QColor(t["text_dim"])

        x = 0.0
        for index, (title, votes) in enumerate(panels):
            combined = index == n - 1
            rect = QRectF(x, self.TITLE_ROW, span, self.BAR_AREA)

            p.setFont(title_font)
            p.setPen(dim)
            p.drawText(QRectF(x, 0, span, self.TITLE_ROW),
                       int(Qt.AlignmentFlag.AlignCenter), title)

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t["plot_bg"]))
            p.drawRect(rect)

            winner = max(range(len(votes)), key=lambda i: votes[i])
            correct = winner == self.TRUE_INDEX

            bar_span = (rect.width() - self.BAR_GAP * (len(votes) + 1)) / len(votes)
            for i, value in enumerate(votes):
                height = max(2.0, (rect.height() - 6) * value)
                bar = QRectF(rect.left() + self.BAR_GAP + i * (bar_span + self.BAR_GAP),
                             rect.bottom() - height - 3, bar_span, height)
                if i != winner:
                    p.setBrush(QColor(t["border"]))
                elif correct:
                    p.setBrush(accent)
                else:
                    p.setBrush(wrong)
                p.drawRect(bar)

            p.setPen(QPen(accent if combined else QColor(t["border"]), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))

            # What this net (or the ensemble) would fire. The amber one is the
            # whole argument for training more than one.
            p.setFont(title_font)
            p.setPen(accent if correct else wrong)
            p.drawText(QRectF(x, rect.bottom() + 2, span, self.LABEL_ROW),
                       int(Qt.AlignmentFlag.AlignCenter),
                       self.LABELS[winner] + ("" if correct else "  ✗"))

            if index == n - 2:
                self._draw_arrow(p, x + span, x + span + self.GROUP_GAP,
                                 self.TITLE_ROW + self.BAR_AREA / 2, dim)
            x += span + (self.GROUP_GAP if index == n - 2 else self.PANEL_GAP)

        p.end()


def nets_diagram_widget():
    return NetsDiagram()


class ClosedSetDiagram(QWidget):
    """Why a noise you do not want still needs recording.

    The model is a closed set: softmax spreads a frame's 100% across the
    trained sounds, with no share left for "none of these". This draws the
    consequence - the same table bump into two models that differ only by
    whether it was ever recorded. Unrecorded, the bump must come out as a real
    sound and fires it; recorded, it has somewhere harmless to land, and that
    spare class is a distractor.
    """

    SOURCE = "a table bump"
    # ( heading, boxes, index the bump lands in, is that the harmless outcome )
    GROUPS = (
        ("If you never recorded the bump", ("pop", "hiss"), 0, False),
        ("If you did", ("pop", "hiss", "table bump"), 2, True),
    )
    DISTRACTOR_NOTE = "distractor"

    HEAD_ROW = 17
    CHIP_ROW = 15
    ARROW_ROW = 18
    BOX_ROW = 32
    NOTE_ROW = 15
    GROUP_GAP = 12
    BOX_WIDTH = 118
    BOX_GAP = 8
    HEAD = 7             # arrowhead half-width

    def __init__(self, parent=None):
        super().__init__(parent)
        widest = max(len(boxes) for _h, boxes, _i, _ok in self.GROUPS)
        self.setMinimumWidth(widest * (self.BOX_WIDTH + self.BOX_GAP) + 20)
        self.setFixedHeight(len(self.GROUPS) * self._group_height()
                            + (len(self.GROUPS) - 1) * self.GROUP_GAP)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _group_height(self):
        return (self.HEAD_ROW + self.CHIP_ROW + self.ARROW_ROW + self.BOX_ROW
                + self.NOTE_ROW)

    def _box_rect(self, index, top):
        left = index * (self.BOX_WIDTH + self.BOX_GAP)
        return QRectF(left, top, self.BOX_WIDTH, self.BOX_ROW)

    def paintEvent(self, _event):
        t = theme.colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        accent = QColor(t["accent"])
        wrong = QColor(theme.QUANTITY_COLORS["Sufficient"])   # shared caution amber
        dim = QColor(t["text_dim"])

        small = components.painter_font(self)

        y = 0.0
        for heading, boxes, target, harmless in self.GROUPS:
            highlight = accent if harmless else wrong

            p.setFont(small)
            p.setPen(dim)
            p.drawText(QRectF(0, y, self.width(), self.HEAD_ROW),
                       int(Qt.AlignmentFlag.AlignLeft
                           | Qt.AlignmentFlag.AlignVCenter), heading)

            chip_top = y + self.HEAD_ROW
            box_top = chip_top + self.CHIP_ROW + self.ARROW_ROW
            landing = self._box_rect(target, box_top)

            # The incoming noise sits directly over the box it ends up in, so the
            # arrow can be a straight drop and never crosses a box it missed.
            p.setPen(highlight)
            p.drawText(QRectF(landing.left(), chip_top, landing.width(),
                              self.CHIP_ROW),
                       int(Qt.AlignmentFlag.AlignCenter), self.SOURCE)
            x = landing.center().x()
            top, bottom = chip_top + self.CHIP_ROW + 2, box_top - 3
            p.setPen(QPen(highlight, 1.2))
            p.drawLine(QPointF(x, top), QPointF(x, bottom))
            p.drawLine(QPointF(x - self.HEAD / 2, bottom - self.HEAD),
                       QPointF(x, bottom))
            p.drawLine(QPointF(x + self.HEAD / 2, bottom - self.HEAD),
                       QPointF(x, bottom))

            for index, name in enumerate(boxes):
                rect = self._box_rect(index, box_top)
                hit = index == target
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(t["plot_bg"]))
                p.drawRect(rect)
                p.setPen(QPen(highlight if hit else QColor(t["border"]), 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))

                p.setFont(self.font())
                p.setPen(highlight if hit else dim)
                mark = "" if not hit else ("  \u2713" if harmless else "  \u2717")
                p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), name + mark)

                if hit and harmless:
                    p.setFont(small)
                    p.setPen(dim)
                    p.drawText(QRectF(rect.left(), rect.bottom() + 1,
                                      rect.width(), self.NOTE_ROW),
                               int(Qt.AlignmentFlag.AlignCenter),
                               self.DISTRACTOR_NOTE)

            y += self._group_height() + self.GROUP_GAP

        p.end()


def closed_set_diagram_widget():
    return ClosedSetDiagram()


def _balance_legend_widget():
    # Imported here rather than at module scope: this module is imported by
    # nearly every page, and the legend only matters on one of them.
    from gui.widgets.balance_column import balance_legend
    return balance_legend()


# The names topics use for their pictures. A topic in gui/content names one
# of these; nothing outside this module knows a diagram is a widget.
DIAGRAMS = {
    "pipeline": pipeline_diagram_widget,
    "frames": frames_diagram_widget,
    "nets": nets_diagram_widget,
    "closed_set": closed_set_diagram_widget,
    # The training page's own live column cannot be borrowed by a modal, so
    # the legend that explains the same bars stands in for it.
    "balance_legend": _balance_legend_widget,
}


def quantity_summary(pairs, max_named=3):
    """Describe a set of sounds by data quantity, as a sentence fragment.

    `pairs` is [(label, detected_ms), ...].

    Never render a bare count next to a rating name: "2 sounds: 2 Not enough"
    reads as "2 sounds is not enough". Few sounds are named individually; many
    are counted with an explicit "rated".
    """
    if not pairs:
        return ""
    rated = [(label, get_quantity_rating(ms)[0]) for label, ms in pairs]
    if len(rated) <= max_named:
        return ", ".join(f"{label} ({quantity})" for label, quantity in rated)
    counts = {}
    for _label, quantity in rated:
        counts[quantity] = counts.get(quantity, 0) + 1
    order = ("Excellent", "Good", "Sufficient", "Not enough")
    present = [q for q in order if q in counts]
    # A bare "N Quantity" only misreads when it stands alone; a list of several
    # is obviously a breakdown, so spell it out only in the single-band case.
    if len(present) == 1:
        return f"all {len(rated)} rated {present[0]}"
    return ", ".join(f"{counts[q]} {q}" for q in present)


def thin_data_warning(count, total):
    """The consequence of training on sounds under the minimum. It never blocks -
    it says what will happen. All-thin is a different situation from one weak
    sound: there is no strong sound left for it to be weak against."""
    if count < total:
        noun = "sound has" if count == 1 else "sounds have"
        return (f"{count} {noun} too little data and will be the model's weak "
                f"spot.")
    subject = "Both are" if total == 2 else "They are all"
    return (f"{subject} under {content.MIN_TRAIN_SECONDS}s of detected "
            f"sound, so expect a lot of misfires. Around "
            f"{content.GOOD_TRAIN_SECONDS}s each is where a model starts "
            f"being usable.")


def with_links(text):
    """Swap a copy token like {docs} for a themed anchor.

    Replacement rather than str.format: copy is full of HTML and a stray brace
    would raise, and a token nobody defined should render as itself rather
    than take the app down.
    """
    if "{" not in text:
        return text
    for token, (url, label) in content.LINKS.items():
        text = text.replace("{" + token + "}", components.link(url, label))
    return text


def rows_html(rows):
    """Label/body rows. A row whose body is None is a section header spanning
    both columns; a row whose *label* is None is a plain paragraph, also
    spanning both, for a topic that reads better as prose than as a glossary."""
    t = theme.colors()
    dim, text = t["text_dim"], t["text"]
    out = ["<table cellspacing='0' cellpadding='2'>"]
    for label, body in rows:
        if body is None:
            out.append(
                f"<tr><td colspan='2' style='color:{t['text_bright']}; "
                f"font-weight:bold; padding-top:10px;'>{label}</td></tr>")
        elif label is None:
            out.append(
                f"<tr><td colspan='2' style='color:{text}; "
                f"padding-bottom:9px;'>{with_links(body)}</td></tr>")
        else:
            out.append(
                f"<tr><td style='color:{dim}; font-weight:bold; "
                f"padding-right:12px; white-space:nowrap; vertical-align:top;'>"
                f"{label}</td><td style='color:{text};'>"
                f"{with_links(body)}</td></tr>")
    out.append("</table>")
    return "".join(out)


# Wider than a comfortable measure, so a long topic fits on one screen -
# which matters more for help nobody scrolls.
BODY_WIDTH = 860


def _prose(html, rank=None):
    body = WrappedBody(with_links(html))
    body.setMaximumWidth(BODY_WIDTH)
    if rank:
        body.setStyleSheet(f"color: {theme.colors()['text']}; "
                           f"font-size: {theme.TYPE_SCALE[rank]}px;")
    return body


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


def topic_content(key, parent=None, stretch=True):
    """A topic drawn as a widget: lede, diagram, intro, rows, note.

    The one renderer for help. The ``?  Help`` modal shows this, and the About
    page stacks one per topic, so a topic looks the same in both and gains
    nothing by being defined twice.
    """
    spec = content.get(key) if isinstance(key, str) else key
    panel = QWidget(parent)
    inner = QVBoxLayout(panel)
    inner.setContentsMargins(0, 0, 0, 0)
    inner.setSpacing(12)

    if spec["lede"]:
        inner.addWidget(_prose(spec["lede"], rank="card"))
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
    if spec.get("bands"):
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


def training_sections(parent=None, live=None):
    """What the training screen teaches, in its own order.

    `live` maps a topic key to a widget built by the caller, so the training
    page can drop in a picture of the sounds actually selected in place of the
    stock diagram.
    """
    live = live or {}
    panel = QWidget(parent)
    v = QVBoxLayout(panel)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(18)
    for key in content.TRAINING_TOPICS:
        spec = content.get(key)
        heading = QLabel(spec["title"], panel)
        heading.setStyleSheet(components.heading_style("card"))
        v.addWidget(heading)
        if key in live:
            v.addWidget(live[key])
            spec = dict(spec, diagram=None)
        v.addWidget(topic_content(spec, panel, stretch=False))
    v.addStretch(1)
    return panel


def scrolled(content, max_height=560):
    """Wrap embedded topic content so a long topic scrolls instead of growing
    its dialog past the screen. Short content still sizes to fit."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
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


def show_help(parent, key):
    title = content.title(key)
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    v = QVBoxLayout(dlg)
    v.setContentsMargins(20, 16, 20, 16)
    panel = topic_content(key)
    v.addWidget(scrolled(panel, max_height=16777215))

    close = QPushButton("Close")
    close.clicked.connect(dlg.accept)
    row = QHBoxLayout()
    row.addStretch()
    row.addWidget(close)
    v.addLayout(row)
    _fit_to_screen(dlg, panel)
    dlg.exec()


def show_training_help(parent):
    """The training page's own help: the same three sections it shows inline,
    for reaching once a run is under way and the setup screen is gone."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("Training a model")
    v = QVBoxLayout(dlg)
    v.setContentsMargins(20, 16, 20, 16)
    sections = training_sections()
    v.addWidget(scrolled(sections, max_height=16777215))
    _fit_to_screen(dlg, sections)
    close = QPushButton("Close")
    close.clicked.connect(dlg.accept)
    row = QHBoxLayout()
    row.addStretch()
    row.addWidget(close)
    v.addLayout(row)
    dlg.exec()


def _flat_help_button(parent):
    t = theme.colors()
    btn = QPushButton("?  Help", parent)
    btn.setFlat(True)
    btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    btn.setStyleSheet(
        f"QPushButton {{ color: {t['text_dim']}; background: transparent; "
        f"border: none; padding: 2px 6px; }} "
        f"QPushButton:hover {{ color: {t['text_bright']}; }}")
    return btn


def help_button(parent, key):
    """Flat '? Help' button wired to the topic's modal."""
    btn = _flat_help_button(parent)
    btn.clicked.connect(lambda: show_help(parent, key))
    return btn


def training_help_button(parent):
    """Same button, opening the three training sections rather than one topic."""
    btn = _flat_help_button(parent)
    btn.clicked.connect(lambda: show_training_help(parent))
    return btn
