"""A two-step confirmation for destructive actions: type the exact name to
unlock the button, so a delete never happens on a single stray click."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton
)

from gui import components, theme


def confirm_destructive(parent, *, title, body, confirm_text, confirm_label="Delete"):
    """True only if the user typed `confirm_text` and accepted.

    title         short headline ("Delete sound 'pop'?")
    body          one-line consequence statement
    confirm_text  the exact text the user must type to proceed
    confirm_label the action button label
    """
    dialog = _ConfirmDialog(parent, title, body, confirm_text, confirm_label)
    return dialog.exec() == QDialog.DialogCode.Accepted


class _ConfirmDialog(QDialog):
    def __init__(self, parent, title, body, confirm_text, confirm_label):
        super().__init__(parent)
        self._confirm_text = confirm_text
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(420)
        t = theme.colors()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        heading = QLabel(title)
        heading.setWordWrap(True)
        heading.setStyleSheet(components.heading_style("section"))
        layout.addWidget(heading)

        body_label = QLabel(body)
        body_label.setWordWrap(True)
        body_label.setStyleSheet(f"color: {t['text']};")
        layout.addWidget(body_label)

        warn = QLabel("This can't be undone.")
        warn.setStyleSheet("color: #e05a5a; font-weight: bold;")
        layout.addWidget(warn)

        prompt = QLabel(f"Type <b>{confirm_text}</b> to confirm:")
        prompt.setStyleSheet(f"color: {t['text_dim']};")
        layout.addWidget(prompt)
        self._field = QLineEdit()
        self._field.setPlaceholderText(confirm_text)
        self._field.textChanged.connect(self._revalidate)
        layout.addWidget(self._field)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)

        self._confirm_btn = QPushButton(confirm_label)
        self._confirm_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._confirm_btn.setEnabled(False)
        self._confirm_btn.setStyleSheet(
            "QPushButton { background-color: #b03636; border: 1px solid #d14b4b;"
            " color: #ffffff; font-weight: bold; }"
            " QPushButton:hover { background-color: #c44141; }"
            # The button you are asked to unlock must be readable while still
            # locked: #ab9494 measures 4.42 on this fill and still reads as off.
            " QPushButton:disabled { background-color: #4c2a2a; color: #ab9494;"
            " border-color: #5e3636; }")
        self._confirm_btn.clicked.connect(self.accept)
        buttons.addWidget(self._confirm_btn)
        layout.addLayout(buttons)

    def _revalidate(self, *_):
        self._confirm_btn.setEnabled(self._field.text().strip() == self._confirm_text)
