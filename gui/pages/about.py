"""About: every help topic in the app, drawn end to end.

The page has no copy of its own. It walks `gui.content.TABS`, so a topic
added there appears here without this file being touched.
"""
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from gui import components, content, theme

NOT_WRITTEN = "Not written yet."


class AboutPage(QWidget):
    """
    ┌ nav ─────────┐┌ scroll ──────────────────────────────────────────────┐
    │ Overview     ││ section per tab                                      │
    │ Sounds       ││                                                      │
    │ Models       ││                                                      │
    │ ...          ││                                                      │
    └──────────────┘└──────────────────────────────────────────────────────┘
    """

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self._sections = []
        self._nav_buttons = []
        self._setup_ui()

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
        # No focus for About page scroll. Tab goes to its controls instead.
        self.scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        outer.addWidget(self.scroll, 1)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(28, 26, 28, 40)
        body_layout.setSpacing(0)
        self.scroll.setWidget(body)

        for tab in content.TABS:
            section = self._section_build(tab)
            self._sections.append(section)
            body_layout.addWidget(section)

            button = QPushButton(tab["title"])
            button.setFlat(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            button.clicked.connect(lambda _=False, s=section: self._go_to(s))
            nav_layout.addWidget(button)
            self._nav_buttons.append(button)
        body_layout.addStretch()
        nav_layout.addStretch()

        self.scroll.verticalScrollBar().valueChanged.connect(self._nav_sync)
        t = theme.colors()
        self.nav.setStyleSheet(
            f"QWidget {{ background-color: {t['base']}; "
            f"border-right: 1px solid {t['border']}; }}")
        self._nav_set_active(0)

    def _section_build(self, tab):
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 34)
        layout.setSpacing(0)

        t = theme.colors()
        title = QLabel(tab["title"])
        title.setStyleSheet(components.heading_style("title"))
        layout.addWidget(title)
        rule = QFrame()
        rule.setFrameShape(QFrame.Shape.HLine)
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background-color: {t['border']}; border: none;")
        layout.addSpacing(10)
        layout.addWidget(rule)

        layout.addSpacing(12)
        placeholder = QLabel(NOT_WRITTEN)
        placeholder.setStyleSheet(f"color: {t['text_dim']}; font-style: italic;")
        layout.addWidget(placeholder)
        return section

    # ---- navigation -----------------------------------------------------

    def _go_to(self, section):
        top = section.mapTo(self.scroll.widget(), QPoint(0, 0)).y()
        # Clear of the body's top margin, so a section header is not flush
        # against the viewport edge.
        self.scroll.verticalScrollBar().setValue(max(0, top - 18))

    def _nav_sync(self, value):
        """Highlight the section the viewport is actually showing."""
        bar = self.scroll.verticalScrollBar()
        if value >= bar.maximum() - 2:
            # The last section is shorter than the viewport, so its top can
            # never reach the top. At the bottom it is what you are reading.
            self._nav_set_active(len(self._sections) - 1)
            return
        current = 0
        for index, section in enumerate(self._sections):
            top = section.mapTo(self.scroll.widget(), QPoint(0, 0)).y()
            if top - 40 <= value:
                current = index
        self._nav_set_active(current)

    def _nav_set_active(self, index):
        t = theme.colors()
        for i, button in enumerate(self._nav_buttons):
            active = i == index
            button.setStyleSheet(
                f"QPushButton {{ text-align: left; border: none; "
                f"background: transparent; padding: 5px 10px; "
                f"border-left: 2px solid {t['accent'] if active else 'transparent'}; "
                f"color: {t['text_bright'] if active else t['text_dim']}; "
                f"font-weight: {'bold' if active else 'normal'}; }} "
                f"QPushButton:hover {{ color: {t['text_bright']}; }} "
                f"QPushButton:focus {{ border: 2px solid {t['focus']}; "
                f"border-radius: {t['radius']}; padding: 3px 8px 3px 10px; }}")
