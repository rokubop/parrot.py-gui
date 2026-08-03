"""May I add a file? Asked before Test integration navigates.

Landing on a screen that cannot do its job, with a button to fix that, is two
decisions where there is one.
"""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
)

from gui import theme

BODY_WIDTH = 520


def _tree_html(path):
    """`<talon user>/ + folder / + file`, marked new or existing."""
    t = theme.colors()
    folder = os.path.dirname(path)
    rows = [f"<span style='color:{t['text_dim']};'>"
            f"{os.path.dirname(folder)}{os.sep}</span>"]
    for indent, name, exists, tag in (
            (0, os.path.basename(folder) + os.sep, os.path.isdir(folder),
             "folder"),
            (4, os.path.basename(path), os.path.isfile(path), "file")):
        mark, colour = ("·", t["text_dim"]) if exists else ("+", t["accent"])
        label = ("existing " + tag if exists
                 else "replaced" if tag == "file" and exists
                 else "new " + tag)
        rows.append(f"{'&nbsp;' * indent}"
                    f"<span style='color:{colour};'>{mark} {name}</span>"
                    f"&nbsp;&nbsp;<span style='color:{t['text_dim']};'>"
                    f"{label}</span>")
    return (f"<div style='font-family: Consolas, monospace; font-size: 12px;'>"
            + "<br>".join(rows) + "</div>")


class BridgeDialog(QDialog):
    """Returns Accepted when the user wants the bridge written."""

    def __init__(self, parent, path, legacy=None, outdated=False,
                 versions=("", "")):
        super().__init__(parent)
        t = theme.colors()
        self.setWindowTitle("Update the bridge" if outdated
                            else "Install the bridge")
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(10)

        title = QLabel("Let parrot.py listen to Talon"
                       if not outdated else "The bridge is out of date")
        title.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {t['text_bright']};")
        title.setWordWrap(True)
        layout.addWidget(title)

        body = QLabel(
            f"v{versions[0]} is installed, this app expects v{versions[1]}."
            if outdated else
            "A file needs to be added to your Talon user directory for "
            "parrot.py to listen to Talon. This file is only used during "
            "integration testing and can be removed any time.")
        body.setWordWrap(True)
        body.setFixedWidth(BODY_WIDTH)
        body.setStyleSheet(f"color: {t['text']};")
        layout.addWidget(body)

        tree = QLabel(_tree_html(path))
        tree.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(tree)

        if legacy:
            note = QLabel(f"Also removes an older copy at\n{legacy}\n"
                          f"Two of them would publish every frame twice.")
            note.setWordWrap(True)
            note.setFixedWidth(BODY_WIDTH)
            note.setStyleSheet(f"color: {t['text_dim']};")
            layout.addWidget(note)

        row = QHBoxLayout()
        row.setContentsMargins(0, 8, 0, 0)
        row.addStretch()
        cancel = QPushButton("Not now")
        cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        from gui.windows.train_view import primary_button_style
        go = QPushButton("Update the bridge" if outdated
                         else "Add it and start testing")
        go.setObjectName("primaryAction")
        go.setMinimumHeight(32)
        go.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        go.setStyleSheet(primary_button_style())
        go.clicked.connect(self.accept)
        row.addWidget(go)
        layout.addLayout(row)
