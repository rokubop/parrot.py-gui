"""Single source of truth for workflow help. Shown as a modal from the home
step cards and from the Sounds / Models / Talon page headers."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton

from gui import theme

RECORD_ROWS = (
    ("Setup", "a quiet room, and the mic you'll actually use day to day "
              "(pick it in Settings). Avoid dynamic mics: takes vary too "
              "much between sessions."),
    ("Good sounds", "tongue clicks, lip pops, palate clicks, “sh” / “ss” "
                    "hisses, short vowels. Distinct from each other and "
                    "from normal speech."),
    ("Goal", "record each sound until its Data rating says Excellent "
             "(~80 s of detected sound). More data beats more sounds."),
    ("How many", "2 sounds minimum to train. A daily-driver setup is "
                 "usually 10-20."),
    ("Time", "a real commitment: 1 hr+ of recording spread over multiple "
             "days, 4 hr+ for a full model. Bursts are fine; every "
             "recording is saved as you go."),
    ("Where", "Sounds tab: “+ New sound”, then “+ Add recording”."),
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

TOPICS = {
    "record": ("Recording sounds", RECORD_ROWS),
    "train": ("Training a model", TRAIN_ROWS),
    "connect": ("Connecting to Talon", CONNECT_ROWS),
}


def rows_html(rows):
    t = theme.colors()
    dim, text = t["text_dim"], t["text"]
    return "<table cellspacing='0' cellpadding='2'>" + "".join(
        f"<tr><td style='color:{dim}; font-weight:bold; padding-right:12px; "
        f"white-space:nowrap; vertical-align:top;'>{label}</td>"
        f"<td style='color:{text};'>{body}</td></tr>"
        for label, body in rows) + "</table>"


def show_help(parent, key):
    title, rows = TOPICS[key]
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    v = QVBoxLayout(dlg)
    v.setContentsMargins(20, 16, 20, 16)
    body = QLabel(rows_html(rows))
    body.setWordWrap(True)
    body.setTextFormat(Qt.TextFormat.RichText)
    body.setMaximumWidth(560)
    v.addWidget(body)
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
