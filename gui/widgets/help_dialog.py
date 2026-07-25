"""Single source of truth for workflow help. Shown as a modal from the home
step cards and from the Sounds / Models / Talon page headers."""
import math

from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QWidget, QFrame, QSizePolicy
)

from gui import theme

RECORD_ROWS = (
    ("Setup", "a quiet room, and the mic you'll actually use day to day "
              "(pick it in Settings). Avoid dynamic mics: takes vary too "
              "much between sessions."),
    ("Good sounds", "tongue clicks, lip pops, palate clicks, “sh” / “ss” "
                    "hisses, short vowels - distinct from each other and from "
                    "normal speech. “Choosing sounds”, on the New sound "
                    "dialog, goes into which ones work and why."),
    ("Goal", "record each sound until its Data rating says Excellent "
             "(~80 s of detected sound). More data beats more sounds."),
    ("How many", "2 sounds minimum to train. A daily-driver setup is "
                 "usually 10-20."),
    ("Time", "a real commitment: 1 hr+ of recording spread over multiple "
             "days, 4 hr+ for a full model. Bursts are fine; every "
             "recording is saved as you go."),
    ("Where", "Sounds tab: “+ New sound”, then “+ Add recording”."),
)
# Shown on Home until there are 2+ sounds. Deliberately only the three things
# worth knowing *before* the first take - the full detail lives in the topics.
PREP_ROWS = (
    ("Set aside time", "recording is a solid block of work, not five minutes - "
                       "1 hr+ spread over sessions. Every take is saved as you "
                       "go, so stopping is fine."),
    ("Find a quiet room", "and use the mic you'll actually use day to day (pick "
                          "it in Settings). Avoid dynamic mics - takes vary too "
                          "much between sessions."),
    ("Decide your sounds", "pick the noises before you record. The New sound "
                           "dialog walks through what makes a good one."),
)
TRAIN_ROWS = (
    ("What", "training reads every recording of every sound and produces "
             "a model file in data/models."),
    ("Needs", "2+ sounds. The more sounds rated Excellent, the better the "
              "model."),
    ("Time", "minutes, not hours. Retrain any time; old models are kept."),
    ("Where", "Models tab."),
)
CONNECT_ROWS = (
    ("What", "Talon (talonvoice.com) runs your model live and maps each "
             "sound to an action."),
    ("Patterns", "patterns.json names each trigger and which sound fires "
                 "it. Edit and deploy from the Talon tab."),
    ("Setup", "the Talon tab finds your Talon install and can bootstrap "
              "the parrot integration from nothing."),
    ("Where", "Talon tab."),
)

SOUNDS_ROWS = (
    ("How it works", "the audio is cut into 15 ms frames and each one is "
                     "classified on its own."),
    ("Start unique", "the opening frames are the most important to keep unique. "
                     "It's ok if the tail overlaps other sounds, because you "
                     "can throttle them."),
    ("Suggestions", None),
    ("Safe with speech", "<b>pop</b>, <b>palatal click</b> (tongue off the roof "
                         "of your mouth), <b>alveolar click</b> / <b>cluck</b>, "
                         "<b>tut</b>."),
    ("Conflicts with speech", "vowels (<b>ah</b>, <b>oh</b>, <b>ee</b>) and "
                              "consonants (<b>mm</b>, <b>hiss</b>, <b>shush</b>, "
                              "<b>t</b>, <b>ff</b>, <b>guh</b>, <b>er</b>, "
                              "<b>eh</b>). Usable, but you give up voice "
                              "commands while they're live, and pairs sharing "
                              "an opening (<b>uh</b> vs <b>ah</b>) misfire."),
    ("Distractors", "record the noises you want ignored - table bumps, throat "
                    "clears, keyboard - as their own sound, and map them to "
                    "nothing."),
    ("Plan", "use 📝 Notes to keep notes."),
)

class FramesDiagram(QWidget):
    """One “pop” drawn as a waveform, cut into the 15 ms frames the model really
    works on, with the label each frame comes out as. The point: your sound is
    never judged whole - it is judged 15 ms at a time, and the frames that no
    longer sound like it come out as background instead."""

    # How many frames to draw - purely an illustration length (10 x 15 ms =
    # 150 ms, about a lip pop). Deliberately not 16, which reads as if it were
    # tied to the 16 kHz rate or to the 15 ms frame; it isn't.
    FRAMES = 10
    FRAME_MS = 15        # RATE * RECORD_SECONDS / SLIDING_WINDOW_AMOUNT samples

    # Envelope of the drawn pop, tuned as a set so the strip comes out
    # silence x2 / pop x4 / silence x4. The last pop frame lands at ~3x the room
    # floor - nearly silent, still detected - and the very next frame is the
    # floor itself. That contrast is the whole point of the picture.
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
        """A plausible pop at time t in [0, 1]: quiet room, near-instant attack,
        a steep collapse that fades to just above the room floor, then real
        silence. Deterministic - it's an illustration, so it draws identically
        every time."""
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

        chip_font = self.font()
        chip_font.setPointSizeF(max(8.5, chip_font.pointSizeF() - 1.5))

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


def frames_diagram_widget():
    return FramesDiagram()


TOPICS = {
    "record": ("Recording sounds", RECORD_ROWS, None),
    "train": ("Training a model", TRAIN_ROWS, None),
    "connect": ("Connecting to Talon", CONNECT_ROWS, None),
    "sounds": ("Choosing sounds", SOUNDS_ROWS, frames_diagram_widget),
}


def rows_html(rows):
    """Label/body rows. A row whose body is None is a section header spanning
    both columns, for grouping a run of related rows."""
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


def topic_content(key, parent=None):
    """The topic's body (diagram, if it has one, plus its rows) as a widget, so
    it can be embedded where the advice is actually needed instead of only
    behind a modal."""
    _title, rows, diagram = TOPICS[key]
    content = QWidget(parent)
    inner = QVBoxLayout(content)
    inner.setContentsMargins(0, 0, 0, 0)
    inner.setSpacing(12)
    if diagram is not None:
        caption = QLabel("One “pop”, as detection sees it:")
        caption.setStyleSheet(f"color: {theme.colors()['text_dim']};")
        inner.addWidget(caption)
        inner.addWidget(diagram())
    body = QLabel(rows_html(rows))
    body.setWordWrap(True)
    body.setTextFormat(Qt.TextFormat.RichText)
    body.setMaximumWidth(700)
    inner.addWidget(body)
    # The scroll area resizes this to its viewport, so without a trailing spring
    # any spare height is shared out between the rows instead of sitting below.
    inner.addStretch(1)
    return content


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


def show_help(parent, key):
    title = TOPICS[key][0]
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    v = QVBoxLayout(dlg)
    v.setContentsMargins(20, 16, 20, 16)
    v.addWidget(scrolled(topic_content(key)))

    close = QPushButton("Close")
    close.clicked.connect(dlg.accept)
    row = QHBoxLayout()
    row.addStretch()
    row.addWidget(close)
    v.addLayout(row)
    dlg.exec()


def help_button(parent, key):
    """Flat '? Help' button wired to the topic's modal."""
    t = theme.colors()
    btn = QPushButton("?  Help", parent)
    btn.setFlat(True)
    btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    btn.setStyleSheet(
        f"QPushButton {{ color: {t['text_dim']}; background: transparent; "
        f"border: none; padding: 2px 6px; }} "
        f"QPushButton:hover {{ color: {t['text_bright']}; }}")
    btn.clicked.connect(lambda: show_help(parent, key))
    return btn
