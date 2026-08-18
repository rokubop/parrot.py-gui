"""Requirements down the side, the next thing to do in the middle.

bootstrap.py's shape while it installs. Shared so setup never looks like two
different apps.

A step is a dict:
    key    - id, comes back on the signal
    label  - one or two words for the checklist
    done   - True / False
    title, body, action - the main area, when this is the current step
    detail - optional rich-text block under the button (a file tree)
    note   - optional dim line under that
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
)

from gui import components, theme
from gui.components import primary_button_style

BODY_WIDTH = 460


class SetupPanel(QWidget):
    action_clicked = pyqtSignal(str)     # the current step's key

    def __init__(self, parent=None):
        super().__init__(parent)
        self._steps = []
        self._current = None
        self._setup_ui()

    def _setup_ui(self):
        t = theme.colors()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(28)

        side = QFrame()
        side.setObjectName("setupSide")
        side.setStyleSheet(
            f"QFrame#setupSide {{ background-color: {t['panel']}; "
            f"border: 1px solid {t['border']}; "
            f"border-radius: {t['radius_card']}; }} "
            f"QFrame#setupSide QLabel {{ background: transparent; "
            f"border: none; }}")
        side.setFixedWidth(260)
        self._side_layout = QVBoxLayout(side)
        self._side_layout.setContentsMargins(18, 16, 18, 18)
        self._side_layout.setSpacing(9)
        heading = components.heading("Setup", "card")
        self._side_layout.addWidget(heading)
        # Held by reference rather than by index: taking items back out of the
        # layout by position also takes the stretch, and the rows pile up on
        # each other.
        self._row_widgets = []
        row.addWidget(side, 0, Qt.AlignmentFlag.AlignTop)

        main = QVBoxLayout()
        main.setSpacing(8)
        # Top-aligned, so the step's title starts on the same line as the
        # checklist it belongs to.
        self.title = QLabel("")
        self.title.setWordWrap(True)
        self.title.setStyleSheet(components.heading_style("section"))
        self.title.setFixedWidth(BODY_WIDTH)
        main.addWidget(self.title, 0, Qt.AlignmentFlag.AlignLeft)
        self.body = QLabel("")
        self.body.setWordWrap(True)
        self.body.setFixedWidth(BODY_WIDTH)
        self.body.setStyleSheet(f"color: {t['text_dim']};")
        components.enable_links(self.body)
        main.addWidget(self.body, 0, Qt.AlignmentFlag.AlignLeft)
        self.button = QPushButton("")
        self.button.setObjectName("primaryAction")
        self.button.setMinimumHeight(32)
        self.button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.button.setStyleSheet(primary_button_style())
        self.button.clicked.connect(
            lambda: self.action_clicked.emit(self._current or ""))
        main.addSpacing(4)
        main.addWidget(self.button, 0, Qt.AlignmentFlag.AlignLeft)
        self.detail = QLabel("")
        self.detail.setTextFormat(Qt.TextFormat.RichText)
        main.addSpacing(4)
        main.addWidget(self.detail, 0, Qt.AlignmentFlag.AlignLeft)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setFixedWidth(BODY_WIDTH)
        self.note.setStyleSheet(f"color: {t['text_dim']};")
        components.enable_links(self.note)
        main.addWidget(self.note, 0, Qt.AlignmentFlag.AlignLeft)
        main.addStretch()
        row.addLayout(main, 1)

    def current_key(self):
        return self._current

    def set_steps(self, steps):
        """Redraw. The current step is the first one not done."""
        t = theme.colors()
        self._steps = list(steps)
        for widget in self._row_widgets:
            self._side_layout.removeWidget(widget)
            widget.deleteLater()
        self._row_widgets = []

        current = next((s for s in self._steps if not s["done"]), None)
        self._current = current["key"] if current else None
        # Ticks under a blocked step are still true and still worth nothing, so
        # they keep the ✓ and lose the green.
        blocked = any(s.get("blocked") for s in self._steps)
        for step in self._steps:
            is_current = current is not None and step["key"] == current["key"]
            # A blocked step is a wrong state, not an unreached one, so it
            # takes ✗ and red rather than the arrow every other step gets.
            mark, colour = (
                ("✓", t["text_dim"] if blocked else t["accent"]) if step["done"]
                else ("✗", t["bad"]) if step.get("blocked")
                else ("→", t["text_bright"]) if is_current
                else ("·", t["text_dim"]))
            label = QLabel(f"{mark}  {step['label']}")
            label.setWordWrap(True)
            label.setStyleSheet(
                f"color: {colour}; "
                f"font-weight: {'bold' if is_current else 'normal'};")
            self._side_layout.addWidget(label)
            self._row_widgets.append(label)

        if current is None:
            self.title.setText("")
            self.body.setText("")
            self.button.setVisible(False)
            self.detail.setText("")
            self.note.setText("")
            return
        self.title.setStyleSheet(components.heading_style(
            "section", color=t["bad"] if current.get("blocked") else None))
        self.title.setText(current.get("title", ""))
        components.set_wrapped_text(self.body, current.get("body", ""),
                                    BODY_WIDTH)
        action = current.get("action")
        self.button.setVisible(bool(action))
        if action:
            self.button.setText(action)
        self.detail.setText(current.get("detail") or "")
        self.detail.setVisible(bool(current.get("detail")))
        components.set_wrapped_text(self.note, current.get("note") or "",
                                    BODY_WIDTH)
        self.note.setVisible(bool(current.get("note")))
