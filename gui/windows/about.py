"""About: the app's help, gathered in one place and split by tab.

Every block here is the same content the ``?  Help`` buttons open beside the
controls they explain - `help_dialog` owns the copy and the diagrams, this
page only arranges them. Nothing is retyped, so the two can never drift.

What is written here is the material that has nowhere else to live: how
detection decides what is sound, what the data ratings mean, what a pattern's
keys do, and where files are kept.
"""
from PyQt6.QtCore import Qt, QPoint, QPointF, QRectF, QUrl
from PyQt6.QtGui import QColor, QDesktopServices, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from config.config import (
    RATE, RECORD_SECONDS, SLIDING_WINDOW_AMOUNT, CURRENT_DETECTION_STRATEGY,
    THRESHOLD_DETECTION,
)
from gui import components, theme
from gui.widgets import help_dialog
from gui.widgets.help_dialog import WrappedBody, rows_html

# Data-quantity thresholds, mirrored from lib/print_status.get_quantity_rating
# so this page and the live ratings always agree.
_SUFFICIENT_S = 16.5
_GOOD_S = 41.25
_EXCELLENT_S = 82.5

_MS_PER_FRAME = int(RECORD_SECONDS / SLIDING_WINDOW_AMOUNT * 1000)

# A measure, not the window: help nobody scrolls is help nobody reads, but a
# 1400px line is unreadable too.
_BODY_WIDTH = 860


# ---- the shape of the whole thing --------------------------------------

class PipelineDiagram(QWidget):
    """Record, train, connect, and the tab each happens on. Same order and
    names as Home's numbered steps, deliberately."""

    STEPS = (
        ("You record", "many takes of each sound", "Sounds"),
        ("Parrot trains", "one model, all your sounds", "Models"),
        ("Talon listens", "each sound does something", "Integrations"),
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


OVERVIEW_INTRO = (
    "<p>Noises you make - a pop, a click, a hiss - become actions. Not "
    "speech: sounds you pick for being quick to make and easy to tell "
    "apart.</p>")

SPEED_ROWS = (
    ("Never waits", f"Every {_MS_PER_FRAME} ms slice is judged on its own, "
                    f"~60 times a second, so a pop fires while the pop is "
                    f"still happening. A word can't be recognised until it's "
                    f"finished."),
    ("Less to weigh", "A handful of sounds you chose, not tens of thousands "
                      "of words."),
    ("The cost", "It only knows what you recorded, and always answers with "
                 "one of them. Hence distractors and throttles, below."),
)


# ---- copy that exists only here ----------------------------------------

DETECTION_ROWS = (
    ("Why", f"Most of a recording is the silence between sounds. Parrot cuts "
            f"each recording into {_MS_PER_FRAME} ms frames and judges each "
            f"one as sound or silence, so training sees the sound and not "
            f"the room."),
    ("Blue bands", "The detected regions drawn over a waveform. Everything "
                   "outside them is ignored when training. Re-run detection "
                   "at a different threshold, or edit the regions by hand, "
                   "from a recording's edit view."),
    ("dBFS", "Loudness, in decibels relative to full scale: 0 is the loudest "
             "possible, more negative is quieter. The threshold is a dBFS "
             "value."),
    ("How the threshold is set", None),
    ("While recording", "Parrot listens to your noise floor and calibrates as "
                        "you go. It needs roughly ten finished sounds before "
                        "it settles, so the first few in a take are judged on "
                        "a provisional number."),
    ("On save", "The whole take is judged again with the threshold that "
                "settled over all of it, so the first sound is segmented on "
                "the same terms as the last. (Two-pass detection, on by "
                "default, switchable in Settings.)"),
    ("By hand", "A threshold you set in a recording's edit view wins over "
                "both, for that recording only."),
    ("Discrete or continuous", f"Short and punchy (a click, a pop) against "
                               f"sustained (a held vowel, a hiss). Parrot "
                               f"estimates this per recording because it "
                               f"changes how hard short detections are "
                               f"rejected. Override it when editing."),
    ("Strategy", f"How onsets, rejections and gap-mending are handled while "
                 f"segmenting. Currently <code>{CURRENT_DETECTION_STRATEGY}</code> "
                 f"in <b>{THRESHOLD_DETECTION}</b> mode: <i>strict</i> suits "
                 f"rapid back-to-back sounds, <i>lenient</i> leaves more room "
                 f"to settle. Pick one when recording."),
)

QUALITY_ROWS = (
    ("Signal to noise", "How far your sound stands above the room. A quiet "
                        "room and a steady mic distance make the line between "
                        "sound and silence sharp; a noisy one blurs it. This "
                        "is separate from how much you have recorded."),
)

PATTERN_ROWS = (
    ("patterns.json", "Maps the model's sounds to the named triggers your "
                      ".talon files bind actions to. The Integrations tab "
                      "edits it with validation and keeps a snapshot of every "
                      "deploy."),
    ("What a pattern holds", None),
    ("sounds", "Which model sounds count toward it. Their probabilities are "
               "summed."),
    ("threshold", "Rules that must <i>all</i> pass for a frame to fire: "
                  "<code>&gt;probability</code> (summed confidence, 0-1), "
                  "<code>&gt;power</code> (loudness), <code>&gt;f0/f1/f2</code> "
                  "(pitch and formants in Hz, to tell a high hiss from a low "
                  "one), each also available as <code>&lt;</code>."),
    ("throttle", "After firing, silence the listed patterns - itself "
                 "included - for N seconds. Targets are pattern names, never "
                 "sound names."),
    ("graceperiod", "Right after a detection, softer rules apply for N "
                    "seconds, so a sound you are holding does not stutter as "
                    "its probability wobbles."),
    ("detect_after", "The rules must hold this long before the first fire, "
                     "which turns a pop into a hold-to-activate."),
)

PATTERN_NOTE = (
    "<p>The Live and Captures views show the real power and probability your "
    "sounds produce - the numbers to judge a threshold against. Those are "
    "Talon-engine units, not the dBFS used elsewhere here.</p>")

DATA_ROWS = (
    ("Recordings", "<code>data/recordings/</code>, one folder per sound: the "
                   "source <code>.wav</code> plus a <code>.srt</code> marking "
                   "where the sound occurs."),
    ("Models", "<code>data/models/</code>. A trained model is a single "
               "<code>.pkl</code> carrying its own nets."),
    ("Notes", "<code>data/notes.json</code>, global and per model."),
    ("Profiles", "A profile is a whole separate data folder - its own "
                 "recordings, models and notes. Use one per person, mic or "
                 "experiment. Switch from the toolbar chip; create one from "
                 "Settings. Switching relaunches the app."),
    ("Audio", f"Captured at {RATE} Hz and processed in {_MS_PER_FRAME} ms "
              f"frames."),
)


def _quantity_html():
    """The rating bands, in the colours the ratings use everywhere else."""
    t = theme.colors()
    q = theme.QUANTITY_COLORS
    bands = (
        (q["Not enough"], "Not enough", f"under {_SUFFICIENT_S:g}s"),
        (q["Sufficient"], "Sufficient", f"{_SUFFICIENT_S:g}s to {_GOOD_S:g}s"),
        (q["Good"], "Good", f"{_GOOD_S:g}s to {_EXCELLENT_S:g}s"),
        (q["Excellent"], "Excellent", f"{_EXCELLENT_S:g}s and up"),
    )
    rows = "".join(
        f"<tr><td style='color:{color}; font-weight:bold; padding:2px 14px "
        f"2px 0; white-space:nowrap;'>{name}</td>"
        f"<td style='color:{t['text']}; padding:2px 0;'>{span}</td></tr>"
        for color, name, span in bands)
    return (
        f"<div style='color:{t['text']};'>"
        f"<p>Each sound is rated on its <b>detected</b> time - the blue "
        f"regions only, never the silence around them.</p>"
        f"<table cellspacing='0' cellpadding='0'>{rows}</table>"
        f"<p style='color:{t['text_dim']};'>Guidelines, not limits. Good is "
        f"usually enough to train something usable; Excellent gives the "
        f"classifier variety. The sound left at Not enough is the one the "
        f"model will confuse most, so it is where another recording pays "
        f"best.</p></div>")


# ---- page structure -----------------------------------------------------

def _block(title, rows=None, diagram=None, intro=None, note=None):
    """One titled block. Drawn in this order: diagram (with its own caption),
    intro, rows, note.

    Prose is kept out of `rows` deliberately. A full-width paragraph sharing
    the table with label/body rows stretches the label column halfway across
    the page, so anything that is not a label goes in `intro` or `note`.
    """
    return dict(title=title, rows=rows, diagram=diagram, intro=intro,
                note=note)


# (section title, what the section is for, [blocks])
def _sections():
    return (
        ("Overview", None,
         (
             _block("How Parrot works", diagram=pipeline_diagram_widget,
                    intro=OVERVIEW_INTRO),
             _block("Why it's fast", SPEED_ROWS),
         )),
        ("Sounds",
         "Recording the sounds a model learns. Everything here is also on the "
         "Sounds tab, behind ?  Help.",
         (
             _block("Choosing sounds", help_dialog.SOUNDS_ROWS,
                    diagram=help_dialog.frames_diagram_widget),
             _block("Recording sounds", help_dialog.RECORD_ROWS),
             _block("Detection: what counts as sound", DETECTION_ROWS),
             _block("How much data you need", intro=_quantity_html()),
             _block("Sound quality", QUALITY_ROWS),
         )),
        ("Models",
         "Turning recordings into a model. Also on the Models tab and the "
         "training screen.",
         (
             _block("Training a model", help_dialog.TRAIN_ROWS),
             _block("How it picks a sound",
                    diagram=help_dialog.closed_set_diagram_widget,
                    note="<p>It always answers with one of the sounds it "
                         "knows. Nothing is ever rejected, which is why a "
                         "noise you want ignored still has to be "
                         "recorded.</p>"),
             _block("Neural networks", help_dialog.NET_ROWS,
                    diagram=help_dialog.nets_diagram_widget),
             _block("Balancing the data", help_dialog.BALANCE_ROWS),
         )),
        ("Integrations",
         "Running a trained model live. Also on the Integrations tab.",
         (
             _block("Connecting to Talon", help_dialog.CONNECT_ROWS),
             _block("Patterns", PATTERN_ROWS, note=PATTERN_NOTE),
         )),
        ("About",
         "The program itself.",
         (
             _block("Where your data lives", DATA_ROWS),
         )),
    )


class AboutPage(QWidget):
    """Contents down the left, the sections themselves scrolling on the right."""

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self._sections = []          # [(name, section widget)]
        self._nav_buttons = []
        self._setup_ui()

    # ---- build ----------------------------------------------------------

    def _setup_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.nav = QWidget()
        self.nav.setFixedWidth(180)
        nav_layout = QVBoxLayout(self.nav)
        nav_layout.setContentsMargins(20, 26, 8, 20)
        nav_layout.setSpacing(2)
        outer.addWidget(self.nav)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(self.scroll, 1)

        body = QWidget()
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(28, 26, 28, 40)
        self.body_layout.setSpacing(0)
        self.scroll.setWidget(body)

        for name, blurb, blocks in _sections():
            section = self._build_section(name, blurb, blocks)
            self._sections.append((name, section))
            self.body_layout.addWidget(section)

            button = QPushButton(name)
            button.setFlat(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(lambda _=False, s=section: self._go_to(s))
            nav_layout.addWidget(button)
            self._nav_buttons.append(button)

        self._append_about_extras()
        self.body_layout.addStretch()
        nav_layout.addStretch()

        self.scroll.verticalScrollBar().valueChanged.connect(
            self._sync_nav)
        self._apply_styles()
        self._set_active(0)

    def _build_section(self, name, blurb, blocks):
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 34)
        layout.setSpacing(0)

        title = components.heading(name, "title")
        layout.addWidget(title)
        if blurb:
            caption = components.dim_label(blurb, wrap=True)
            caption.setMaximumWidth(_BODY_WIDTH)
            layout.addWidget(caption)
        rule = QFrame()
        rule.setFrameShape(QFrame.Shape.HLine)
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background-color: {theme.colors()['border']}; "
                           f"border: none;")
        layout.addSpacing(10)
        layout.addWidget(rule)

        for block in blocks:
            layout.addSpacing(22)
            layout.addWidget(components.heading(block["title"], "card"))
            layout.addSpacing(8)
            if block["diagram"] is not None:
                widget = block["diagram"]()
                caption_text = getattr(widget, "CAPTION", "")
                if caption_text:
                    layout.addWidget(components.dim_label(caption_text))
                    layout.addSpacing(4)
                layout.addWidget(widget)
                layout.addSpacing(14)
            for key in ("intro", "rows", "note"):
                text = block[key]
                if not text:
                    continue
                if key != "intro":
                    layout.addSpacing(8)
                body = WrappedBody(rows_html(text) if key == "rows" else text)
                body.setMaximumWidth(_BODY_WIDTH)
                layout.addWidget(body)
        return section

    def _append_about_extras(self):
        """Version, update check and the project links: the one part of this
        page that is about the program rather than about using it."""
        section = self._sections[-1][1]
        layout = section.layout()

        layout.addSpacing(22)
        layout.addWidget(components.heading("This copy", "card"))
        layout.addSpacing(8)

        self.version_label = components.dim_label(_version_text())
        layout.addWidget(self.version_label)

        row = QHBoxLayout()
        row.setContentsMargins(0, 6, 0, 0)
        row.setSpacing(12)
        self.update_btn = _text_link("Check for updates", self._check_updates)
        row.addWidget(self.update_btn)
        self.update_label = components.dim_label("")
        row.addWidget(self.update_label)
        row.addStretch()
        layout.addLayout(row)

        layout.addSpacing(22)
        layout.addWidget(components.heading("Project", "card"))
        layout.addSpacing(8)
        self._links = []
        for text, url in (
            ("Parrot.py on GitHub", "https://github.com/rokubop/parrot.py"),
            ("Report an issue", "https://github.com/rokubop/parrot.py/issues"),
            ("Talon Voice", "https://talonvoice.com"),
        ):
            link = _text_link(text, lambda _=False, u=url:
                              QDesktopServices.openUrl(QUrl(u)))
            self._links.append(link)
            layout.addWidget(link)

        layout.addSpacing(16)
        self.license_label = WrappedBody(_license_html())
        self.license_label.setMaximumWidth(_BODY_WIDTH)
        layout.addWidget(self.license_label)

    # ---- navigation -----------------------------------------------------

    def _go_to(self, section):
        top = section.mapTo(self.scroll.widget(), QPoint(0, 0)).y()
        # Clear of the body's top margin, so a section header is not flush
        # against the viewport edge.
        self.scroll.verticalScrollBar().setValue(max(0, top - 18))

    def _sync_nav(self, value):
        """Highlight the section the viewport is actually showing."""
        bar = self.scroll.verticalScrollBar()
        if value >= bar.maximum() - 2:
            # The last section is shorter than the viewport, so its top can
            # never reach the top. At the bottom it is what you are reading.
            self._set_active(len(self._sections) - 1)
            return
        current = 0
        for index, (_name, section) in enumerate(self._sections):
            top = section.mapTo(self.scroll.widget(), QPoint(0, 0)).y()
            if top - 40 <= value:
                current = index
        self._set_active(current)

    def _set_active(self, index):
        for i, button in enumerate(self._nav_buttons):
            button.setProperty("active", i == index)
        self._style_nav()

    # ---- update check ---------------------------------------------------

    def _check_updates(self):
        from gui.services.update_check import UpdateCheckWorker

        if getattr(self, "_worker", None) is not None and self._worker.isRunning():
            return
        self.update_btn.setEnabled(False)
        self.update_label.setText("Checking...")
        # Held on self: a local would be collected mid-run (memory/qt-traps.md)
        self._worker = UpdateCheckWorker()
        self._worker.result.connect(self._update_result)
        self._worker.start()

    def _update_result(self, res):
        self.update_btn.setEnabled(True)
        n = res.get("behind_by")
        self.update_label.setText({
            "up_to_date": "Up to date.",
            "behind": (f"{n} new commit{'s' if n != 1 else ''} on the remote."
                       if n else "Update available."),
            "ahead": "Ahead of the remote - local commits.",
            "diverged": "Diverged from the remote.",
            "no_git": "Not a git checkout. See GitHub for the latest.",
            "error": "Couldn't reach the remote.",
        }[res["state"]])

    # ---- theme ----------------------------------------------------------

    def _style_nav(self):
        t = theme.colors()
        for button in self._nav_buttons:
            active = bool(button.property("active"))
            button.setStyleSheet(
                f"QPushButton {{ text-align: left; border: none; "
                f"background: transparent; padding: 5px 10px; "
                f"border-left: 2px solid "
                f"{t['accent'] if active else 'transparent'}; "
                f"color: {t['text_bright'] if active else t['text_dim']}; "
                f"font-weight: {'bold' if active else 'normal'}; }} "
                f"QPushButton:hover {{ color: {t['text_bright']}; }}")

    def _apply_styles(self):
        t = theme.colors()
        self.nav.setStyleSheet(
            f"QWidget {{ background-color: {t['base']}; "
            f"border-right: 1px solid {t['border']}; }}")
        self._style_nav()
        for link in getattr(self, "_links", ()):
            link.setStyleSheet(_link_style())
        self.update_btn.setStyleSheet(_link_style())
        self.license_label.setText(_license_html())

    def refresh_theme(self):
        self._apply_styles()


def _link_style():
    t = theme.colors()
    return (f"QPushButton {{ color: {t['accent']}; background: transparent; "
            f"border: none; text-align: left; padding: 2px 0; }} "
            f"QPushButton:hover {{ color: {t['text_bright']}; }}")


def _text_link(text, slot):
    """A link, not a button: nothing here is an action on your data."""
    button = QPushButton(text)
    button.setFlat(True)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.setStyleSheet(_link_style())
    button.clicked.connect(slot)
    return button


def _version_text():
    from gui.services.update_check import checkout_line

    line = checkout_line()
    return line or "Running from an installed build."


def _license_html():
    t = theme.colors()
    return (f"<span style='color:{t['text_dim']};'>MIT licensed. "
            f"Copyright (c) 2019 Kevin te Raa (chaosparrot); this is "
            f"rokubop's fork.</span>")
