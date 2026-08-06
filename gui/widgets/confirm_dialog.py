"""A deliberate two-step confirmation dialog for destructive actions.

Every destructive operation on a sound, recording, or model routes through
``confirm_destructive`` so deletion can never happen on a single stray click.
Two modes of second step:

* ``confirm_text`` set  -> the user must type the exact name to enable the
  action button (used for high-impact deletes: a whole sound or model).
* otherwise             -> the user must tick "I understand..." to enable it
  (used for single recordings).
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QCheckBox,
    QPushButton, QFrame
)

from gui import theme


def confirm_destructive(parent, *, title, body, detail=None,
                        confirm_text=None, confirm_label="Delete"):
    """Show a blocking confirmation. Returns True only if the user completes
    both steps and accepts.

    title         short headline ("Delete sound 'pop'?")
    body          one-line consequence statement
    detail        optional multi-line breakdown (e.g. files that will go)
    confirm_text  if given, the exact text the user must type to proceed
    confirm_label the action button label
    """
    dialog = _ConfirmDialog(parent, title, body, detail, confirm_text,
                            confirm_label)
    return dialog.exec() == QDialog.DialogCode.Accepted


class _ConfirmDialog(QDialog):
    def __init__(self, parent, title, body, detail, confirm_text, confirm_label):
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
        heading.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {t['text_bright']};")
        layout.addWidget(heading)

        body_label = QLabel(body)
        body_label.setWordWrap(True)
        body_label.setStyleSheet(f"color: {t['text']};")
        layout.addWidget(body_label)

        if detail:
            detail_label = QLabel(detail)
            detail_label.setWordWrap(True)
            detail_label.setStyleSheet(
                f"color: {t['text_dim']}; font-size: 12px;")
            frame = QFrame()
            frame.setStyleSheet(
                f"QFrame {{ background-color: {t['base']}; border: 1px solid "
                f"{t['border']}; border-radius: {t['radius']}; }}")
            frame_layout = QVBoxLayout(frame)
            frame_layout.setContentsMargins(10, 8, 10, 8)
            frame_layout.addWidget(detail_label)
            layout.addWidget(frame)

        warn = QLabel("This can't be undone.")
        warn.setStyleSheet("color: #e05a5a; font-weight: bold;")
        layout.addWidget(warn)

        # ---- step two: the explicit gate ----
        if confirm_text:
            prompt = QLabel(f"Type <b>{confirm_text}</b> to confirm:")
            prompt.setStyleSheet(f"color: {t['text_dim']};")
            layout.addWidget(prompt)
            self._field = QLineEdit()
            self._field.setPlaceholderText(confirm_text)
            self._field.textChanged.connect(self._revalidate)
            layout.addWidget(self._field)
            self._checkbox = None
        else:
            self._field = None
            self._checkbox = QCheckBox("I understand this is permanent.")
            self._checkbox.toggled.connect(self._revalidate)
            layout.addWidget(self._checkbox)

        # ---- buttons ----
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)

        self._confirm_btn = QPushButton(confirm_label)
        self._confirm_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._confirm_btn.setEnabled(False)
        # Red, destructive styling so it's visually distinct from a safe action.
        self._confirm_btn.setStyleSheet(
            "QPushButton { background-color: #b03636; border: 1px solid #d14b4b;"
            " color: #ffffff; font-weight: bold; }"
            " QPushButton:hover { background-color: #c44141; }"
            # The label of the button you are being asked to unlock has to be
            # readable while it is still locked. #8a7575 measured 2.92 on this
            # fill; #ab9494 is 4.42 and still reads as off.
            " QPushButton:disabled { background-color: #4c2a2a; color: #ab9494;"
            " border-color: #5e3636; }")
        self._confirm_btn.clicked.connect(self.accept)
        buttons.addWidget(self._confirm_btn)
        layout.addLayout(buttons)

    def _revalidate(self, *_):
        if self._confirm_text is not None:
            ok = self._field.text().strip() == self._confirm_text
        else:
            ok = self._checkbox.isChecked()
        self._confirm_btn.setEnabled(ok)
