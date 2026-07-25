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
from lib.print_status import get_quantity_rating

# Detected sound per label: below the first, get_quantity_rating says "Not
# enough" (16.5s) and training is a formality; the second is where a model
# starts being usable. Quoted in the Sounds empty state too.
MIN_TRAIN_SECONDS = 17
GOOD_TRAIN_SECONDS = 40

# Row bodies read as their own sentence, not as a continuation of the label -
# so they start capitalised. Literal names ( sound labels, filenames ) keep
# their own casing wherever they fall.
RECORD_ROWS = (
    ("Setup", "A quiet room, and the mic you'll actually use day to day "
              "(pick it in Settings). Avoid dynamic mics: takes vary too "
              "much between sessions."),
    ("Good sounds", "Tongue clicks, lip pops, palate clicks, “sh” / “ss” "
                    "hisses, short vowels - distinct from each other and from "
                    "normal speech. “Choosing sounds”, on the New sound "
                    "dialog, goes into which ones work and why."),
    ("Goal", "Record each sound until its Data rating says Excellent "
             "(~80 s of detected sound). More data beats more sounds."),
    ("How many", "2 sounds minimum to train. A daily-driver setup is "
                 "usually 10-20."),
    ("Time", "A real commitment: 1 hr+ of recording spread over multiple "
             "days, 4 hr+ for a full model. Bursts are fine; every "
             "recording is saved as you go."),
    ("Where", "Sounds tab: “+ New sound”, then “+ Add recording”."),
)
# Shown on Home until there are 2+ sounds. Deliberately only the three things
# worth knowing *before* the first take - the full detail lives in the topics.
PREP_ROWS = (
    ("Set aside time", "Recording is a solid block of work, not five minutes - "
                       "1 hr+ spread over sessions. Every take is saved as you "
                       "go, so stopping is fine."),
    ("Find a quiet room", "Use the mic you'll actually use day to day (pick it "
                          "in Settings). Avoid dynamic mics - takes vary too "
                          "much between sessions."),
    ("Decide your sounds", "Pick the noises before you record. The New sound "
                           "dialog walks through what makes a good one."),
)
TRAIN_ROWS = (
    ("What", "Training reads every recording of every sound and produces "
             "a model file in data/models."),
    ("Needs", "2+ sounds. The more sounds rated Excellent, the better the "
              "model."),
    ("Time", "Hours, not minutes - roughly 4-6 hrs for 14 sounds at 5 nets "
             "running all 300 epochs. Sound count, how much you've recorded "
             "and the net count each multiply it. Runs unattended, so start "
             "it and leave it."),
    ("Rough draft", "You don't have to run it out. The best model so far is "
                    "saved every time accuracy improves, so Stop once the "
                    "curve flattens and you keep it - a usable first pass in "
                    "a fraction of the time. Let it finish when you're "
                    "chasing the last few points."),
    ("Nets", "Each net learns the same sounds from a different random start, "
             "so they disagree on the hard frames. The model fires on their "
             "average, which means a net that mishears something gets outvoted "
             "instead of deciding on its own. At 1 net there is nobody to "
             "outvote it. 3 is a good default and 5 is worth it once the "
             "sounds matter; each net multiplies the training time."),
    ("Where", "Models tab. Retrain any time; old models are kept."),
)
CONNECT_ROWS = (
    ("What", "Talon (talonvoice.com) runs your model live and maps each "
             "sound to an action."),
    ("Patterns", "Each trigger, and the sound that fires it, lives in "
                 "patterns.json. Edit and deploy from the Talon tab."),
    ("Setup", "The Talon tab finds your Talon install and can bootstrap "
              "the parrot integration from nothing."),
    ("Where", "Talon tab."),
)

SOUNDS_ROWS = (
    ("How it works", "The audio is cut into 15 ms frames and each one is "
                     "classified on its own."),
    ("Start unique", "The opening frames are the most important to keep unique. "
                     "It's ok if the tail overlaps other sounds, because you "
                     "can throttle them."),
    ("Suggestions", None),
    ("Safe with speech", "<b>pop</b>, <b>palate</b> (palatal click), "
                         "<b>cluck</b> (alveolar click), <b>tut</b> (dental "
                         "click)."),
    ("Conflicts with speech", "Vowels (<b>ah</b>, <b>oh</b>, <b>ee</b>) and "
                              "consonants (<b>mm</b>, <b>hiss</b>, <b>shush</b>, "
                              "<b>t</b>, <b>ff</b>, <b>guh</b>, <b>er</b>, "
                              "<b>eh</b>). Usable, but you give up voice "
                              "commands while they're live, and pairs sharing "
                              "an opening (<b>uh</b> vs <b>ah</b>) misfire."),
    ("Distractors", "Record the noises you want ignored - table bumps, throat "
                    "clears, keyboard - as their own sound, and map them to "
                    "nothing."),
    ("Plan", "Use 📝 Notes to keep notes."),
)

class FramesDiagram(QWidget):
    """One “pop” drawn as a waveform, cut into the 15 ms frames the model really
    works on, with the label each frame comes out as. The point: your sound is
    never judged whole - it is judged 15 ms at a time, and the frames that no
    longer sound like it come out as background instead."""

    CAPTION = "One “pop”, as detection sees it:"

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


class NetsDiagram(QWidget):
    """Why net count is worth a thought: each net is trained from its own random
    start on its own shuffle of the data, so they disagree. One net can be the
    unlucky one - and with a net count of 1, the unlucky one is the model you
    ship. Averaging their votes lets the others outvote it."""

    # One frame of one sound, as scored by three independently trained nets.
    # Deterministic, and picked so net 2 is confidently wrong: that is the case
    # the picture exists to explain. The averaged row is computed, never typed,
    # so the illustration cannot drift from the arithmetic it is claiming.
    CAPTION = "One frame of a “pop”, scored by three separately trained nets:"

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
    LEGEND_ROW = 16      # without it the three bars are unexplained shapes
    PANEL_GAP = 8
    GROUP_GAP = 26       # wider gap sets the averaged panel apart from the nets
    BAR_GAP = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(88 * (len(self.VOTES) + 1))
        self.setFixedHeight(self.TITLE_ROW + self.BAR_AREA + self.LABEL_ROW
                            + self.LEGEND_ROW + 6)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    @classmethod
    def averaged(cls):
        """What the ensemble actually does - TinyAudioNetEnsemble sums the nets
        and divides by how many there are."""
        return tuple(sum(v[i] for v in cls.VOTES) / len(cls.VOTES)
                     for i in range(len(cls.LABELS)))

    def _panels(self):
        panels = [(f"Net {i + 1}", v) for i, v in enumerate(self.VOTES)]
        panels.append(("Averaged", self.averaged()))
        return panels

    def paintEvent(self, _event):
        t = theme.colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        panels = self._panels()
        n = len(panels)
        total_gap = self.PANEL_GAP * (n - 2) + self.GROUP_GAP
        span = (self.width() - total_gap) / n

        title_font = self.font()
        title_font.setPointSizeF(max(8.5, title_font.pointSizeF() - 1.5))

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

            x += span + (self.GROUP_GAP if index == n - 2 else self.PANEL_GAP)

        p.setFont(title_font)
        p.setPen(dim)
        p.drawText(QRectF(0, self.TITLE_ROW + self.BAR_AREA + self.LABEL_ROW + 2,
                          self.width(), self.LEGEND_ROW),
                   int(Qt.AlignmentFlag.AlignCenter),
                   "bar heights are how sure that net is of "
                   + ", ".join(self.LABELS))

        p.end()


def nets_diagram_widget():
    return NetsDiagram()


TOPICS = {
    "record": ("Recording sounds", RECORD_ROWS, None),
    "train": ("Training a model", TRAIN_ROWS, nets_diagram_widget),
    "connect": ("Connecting to Talon", CONNECT_ROWS, None),
    "sounds": ("Choosing sounds", SOUNDS_ROWS, frames_diagram_widget),
}


def quantity_summary(pairs, max_named=3):
    """Describe a set of sounds by data quantity, as a sentence fragment.

    `pairs` is [(label, detected_ms), ...].

    Never render a bare count next to a rating name: "2 sounds: 2 Not enough"
    reads as "2 sounds is not enough", and it is worst in the case that matters
    most - every sound in the same band, so there is no second category to
    disambiguate. Few sounds are named individually; many are counted with an
    explicit "rated".
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
    return (f"{subject} under {MIN_TRAIN_SECONDS}s of detected sound, so expect "
            f"a lot of misfires. Around {GOOD_TRAIN_SECONDS}s each is where a "
            f"model starts being usable.")


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
        # The caption belongs to the drawing, not to this slot - it was hard
        # coded here and captioned the second diagram as if it were the first.
        widget = diagram()
        text = getattr(widget, "CAPTION", "")
        if text:
            caption = QLabel(text)
            caption.setStyleSheet(f"color: {theme.colors()['text_dim']};")
            inner.addWidget(caption)
        inner.addWidget(widget)
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
