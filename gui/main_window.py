from PyQt6.QtWidgets import QMainWindow, QToolBar, QStackedWidget, QWidget, QApplication
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtCore import Qt
from gui.state import AppState
from gui.pages.home import HomePage
from gui.pages.sounds import SoundsPage


class MainWindow(QMainWindow):
    """
    ┌ toolbar ─────────────────────────────────────────────────┐
    │ [ Home ] [ Sounds ] ...    nav_actions                   │
    ├ page_stack ──────────────────────────────────────────────┤
    │ individual page shown by _show_page()                    │
    │                                                          │
    └──────────────────────────────────────────────────────────┘
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Parrot.py")
        self.resize(1200, 800)
        self.setMinimumSize(900, 600)

        self.app_state = AppState()

        self.page_stack = QStackedWidget()
        self.setCentralWidget(self.page_stack)

        self.home_page = HomePage(self.app_state, self)
        self.home_page.navigate.connect(self._go_to_page)
        self.sounds_page = SoundsPage(self.app_state, self)
        self.sounds_page.record_requested.connect(self._open_recording)
        self.pages = {
            "Home": self.home_page,
            "Sounds": self.sounds_page,
            "Models": QWidget(),
        }
        for page in self.pages.values():
            self.page_stack.addWidget(page)
        # Built on first use
        self.recording_view = None
        self.page_stack.currentChanged.connect(self._on_page_changed)

        toolbar = QToolBar("Navigation")
        toolbar.setMovable(False)
        # Without this, right-clicking the toolbar opens a Qt menu with a
        # "Navigation" checkbox. Unticking it hides the tabs, with no way to
        # get them back short of restarting.
        toolbar.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
        group = QActionGroup(self)
        group.setExclusive(True)

        self.nav_actions = {}
        for name in self.pages:
            action = QAction(name, self)
            action.setCheckable(True)
            group.addAction(action)
            toolbar.addAction(action)
            button = toolbar.widgetForAction(action)
            # Qt default is NoFocus. TabFocus so a click doesn't leave a ring
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            action.triggered.connect(
                lambda _checked, n=name, b=button: self._show_page(n, focus_page=b.hasFocus()))
            self.nav_actions[name] = action
        self.nav_actions["Home"].setChecked(True)

    def _go_to_page(self, name):
        """Navigation from page buttons: keeps the toolbar checked state in sync."""
        self.nav_actions[name].setChecked(True)
        focused = QApplication.focusWidget()
        self._show_page(name, focus_page=focused is not None
                        and self.page_stack.currentWidget().isAncestorOf(focused))

    def _show_page(self, name, focus_page=False):
        """focus_page: navigated by keyboard. Focus follows into the page, so a
        screen reader announces where it landed instead of just "checked"."""
        page = self.pages[name]
        self.page_stack.setCurrentWidget(page)
        if focus_page and page.focusProxy():
            page.setFocus(Qt.FocusReason.TabFocusReason)

    def _open_recording(self, label):
        """Recording is a sub-view of Sounds: the Sounds tab stays checked."""
        # Or the mic records it
        self.sounds_page.stop_playback()
        view = self._recording_view_get()
        if label:
            view.start_for(label)
        else:
            view.start_new()
        self.page_stack.setCurrentWidget(view)

    def _recording_view_get(self):
        if self.recording_view is None:
            from gui.pages.recording_view import RecordingView
            self.recording_view = RecordingView(self.app_state, self)
            self.recording_view.done.connect(
                lambda: self.page_stack.setCurrentWidget(self.sounds_page))
            self.recording_view.sound_changed.connect(self.sounds_page.show_sound)
            self.page_stack.addWidget(self.recording_view)
            QApplication.instance().aboutToQuit.connect(self.recording_view.finish_recording)
        return self.recording_view

    def _on_page_changed(self, _index):
        """A take keeps recording only while it is on screen."""
        if self.recording_view is not None and self.page_stack.currentWidget() is not self.recording_view:
            self.recording_view.stop_recording()
