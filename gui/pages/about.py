"""About: every help topic in the app, drawn end to end.

The page has no copy of its own. It walks `gui.content.TABS` and asks
`help_dialog` to render each topic, which is the same widget the ``?  Help``
buttons open - so a topic added to the registry appears here without this
file being touched.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from gui import components, content, theme
from gui.widgets import help_dialog


class AboutPage(QWidget):
    """The sections scrolling, one per tab."""

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # No focus for About page scroll. Tab goes to its controls instead.
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        outer.addWidget(scroll)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(28, 26, 28, 40)
        body_layout.setSpacing(0)
        for tab in content.TABS:
            body_layout.addWidget(self._section_build(tab))
        body_layout.addStretch()
        scroll.setWidget(body)

    def _section_build(self, tab):
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 34)
        layout.setSpacing(0)

        t = theme.colors()
        title = QLabel(tab["title"])
        title.setStyleSheet(components.heading_style("title"))
        layout.addWidget(title)
        if tab["blurb"]:
            caption = QLabel(tab["blurb"])
            caption.setWordWrap(True)
            caption.setStyleSheet(f"color: {t['text_dim']};")
            caption.setMaximumWidth(help_dialog.BODY_WIDTH)
            layout.addWidget(caption)
        rule = QFrame()
        rule.setFrameShape(QFrame.Shape.HLine)
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background-color: {t['border']}; border: none;")
        layout.addSpacing(10)
        layout.addWidget(rule)

        layout.addSpacing(22)
        # The same widgets the Help buttons open
        layout.addWidget(help_dialog.topics_content(tab["topics"], stretch=False))
        return section
