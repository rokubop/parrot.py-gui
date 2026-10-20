"""About: every help topic in the app, drawn end to end.

The page has no copy of its own. It walks `gui.content.TABS` and asks
`help_dialog` to render each topic, which is the same widget the ``?  Help``
buttons open - so a topic added to the registry appears here without this
file being touched.

Its own part is the program itself: the version and the license.
"""
from PyQt6.QtCore import Qt, QPoint, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from gui import components, content, theme
from gui.widgets import help_dialog
from gui.widgets.help_dialog import WrappedBody
from version import __version__

_BODY_WIDTH = help_dialog.BODY_WIDTH


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

        for tab in content.TABS:
            section = self._build_section(tab)
            name = tab["title"]
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

    def _build_section(self, tab):
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 34)
        layout.setSpacing(0)

        title = components.heading(tab["title"], "title")
        layout.addWidget(title)
        if tab["blurb"]:
            caption = components.dim_label(tab["blurb"], wrap=True)
            caption.setMaximumWidth(_BODY_WIDTH)
            layout.addWidget(caption)
        rule = QFrame()
        rule.setFrameShape(QFrame.Shape.HLine)
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background-color: {theme.colors()['border']}; "
                           f"border: none;")
        layout.addSpacing(10)
        layout.addWidget(rule)

        for spec in tab["topics"]:
            layout.addSpacing(22)
            layout.addWidget(components.heading(spec["title"], "card"))
            layout.addSpacing(8)
            # The same widget the topic's own Help button opens.
            layout.addWidget(help_dialog.topic_content(spec, stretch=False))
        return section

    def _append_about_extras(self):
        """Version, update check and the project links: the one part of this
        page that is about the program rather than about using it."""
        section = self._sections[-1][1]
        layout = section.layout()

        layout.addSpacing(22)
        layout.addWidget(components.heading("This copy", "card"))
        layout.addSpacing(8)

        self.version_label = components.dim_label(__version__)
        layout.addWidget(self.version_label)

        layout.addSpacing(22)
        layout.addWidget(components.heading("Project", "card"))
        layout.addSpacing(8)
        self._links = []
        for text, url in (
            ("Parrot.py on GitHub", "https://github.com/rokubop/parrot.py-gui"),
            ("Report an issue", "https://github.com/rokubop/parrot.py-gui/issues"),
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



def _license_html():
    t = theme.colors()
    return (f"<span style='color:{t['text_dim']};'>MIT licensed. "
            f"Copyright (c) 2019 Kevin te Raa.</span>")
