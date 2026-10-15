from PyQt6.QtWidgets import QMainWindow, QToolBar, QStatusBar, QStackedWidget, QLabel
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtCore import Qt
from gui.models.app_state import AppState
from gui.windows.home import HomePage
from gui.windows.library import SoundLibraryPage
from gui import theme


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Parrot.py")
        self.setMinimumSize(1200, 800)

        self.app_state = AppState()

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        # Home + Sounds build eagerly; Models reads every checkpoint, so it
        # builds on first use
        self.home_page = HomePage(self.app_state, self)
        self.stack.addWidget(self.home_page)
        self.home_page.navigate.connect(self._go_to_tab)

        self.library_page = SoundLibraryPage(self.app_state, self)
        self.stack.addWidget(self.library_page)

        self.models_page = None

        self.stack.currentChanged.connect(self._refresh_keybindings)

        # Toolbar navigation - checkable actions so the current tab is obvious.
        toolbar = QToolBar("Navigation")
        toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
        self._nav_group = QActionGroup(self)
        self._nav_group.setExclusive(True)

        self.nav_actions = {}
        for text in ("Home", "Sounds", "Models"):
            action = QAction(text, self)
            action.setCheckable(True)
            action.triggered.connect(lambda _checked, t=text: self._show_tab(t))
            self._nav_group.addAction(action)
            toolbar.addAction(action)
            self.nav_actions[text] = action
        self.nav_actions["Home"].setChecked(True)
        self.stack.setCurrentWidget(self.home_page)

        # Status bar: each page's keybindings. Nothing may call showMessage()
        # here - temporary messages hide the non-permanent widgets.
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.keys_label = QLabel("")
        self.keys_label.setStyleSheet(f"color: {theme.colors()['text_dim']}; padding-right: 8px;")
        self.status_bar.addPermanentWidget(self.keys_label)
        self._refresh_keybindings()

    def _get_models_page(self):
        if self.models_page is None:
            from gui.windows.models import ModelsPage
            self.models_page = ModelsPage(self.app_state, self)
            self.stack.addWidget(self.models_page)
        return self.models_page

    def _go_to_tab(self, name):
        """Navigation from page buttons: keeps the toolbar checked state in sync."""
        if name in self.nav_actions:
            self.nav_actions[name].setChecked(True)
            self._show_tab(name)

    def _show_tab(self, name):
        if name == "Home":
            self.stack.setCurrentWidget(self.home_page)
        elif name == "Sounds":
            self.stack.setCurrentWidget(self.library_page)
        elif name == "Models":
            self.stack.setCurrentWidget(self._get_models_page())

    def _refresh_keybindings(self, _index=None):
        page = self.stack.currentWidget()
        getter = getattr(page, "keybinding_hint", None)
        self.keys_label.setText(getter() if callable(getter) else "")
