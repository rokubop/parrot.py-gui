from PyQt6.QtWidgets import (
    QMainWindow, QToolBar, QStatusBar, QStackedWidget
)
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtCore import Qt
import sounddevice as sd
from config.config import INPUT_DEVICE_INDEX
from gui.models.app_state import AppState
from gui.windows.library import SoundLibraryPage
from gui.windows.models import ModelsPage
from gui.windows.settings import SettingsPage
from gui.windows.about import AboutPage
from gui.windows.recording_view import RecordingView


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Parrot.py")
        self.setMinimumSize(1200, 800)

        self.app_state = AppState(self)

        # Central stacked widget
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        # Four top-level pages: Sounds, Models, Settings, About.
        # Recording and editing live inside the Sounds page; training lives
        # inside the Models page.
        self.library_page = SoundLibraryPage(self.app_state, self)
        self.models_page = ModelsPage(self.app_state, self)
        self.settings_page = SettingsPage(self.app_state, self)
        self.about_page = AboutPage(self.app_state, self)
        for page in (self.library_page, self.models_page,
                     self.settings_page, self.about_page):
            self.stack.addWidget(page)

        # Full-screen sub-views of the Sounds workflow (not in the toolbar):
        # recording capture and recording editing.
        self.recording_view = RecordingView(self.app_state, self)
        self.stack.addWidget(self.recording_view)
        self.library_page.record_requested.connect(self._open_recording)
        self.recording_view.done.connect(self._return_to_sounds)
        # Leaving the recording view via the toolbar should stop (and save) any
        # take in progress rather than recording in the background.
        self.stack.currentChanged.connect(self._on_stack_changed)

        # Toolbar navigation — checkable actions so the current tab is obvious.
        toolbar = QToolBar("Navigation")
        toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
        nav_group = QActionGroup(self)
        nav_group.setExclusive(True)

        for text, page in (("Sounds", self.library_page),
                           ("Models", self.models_page),
                           ("Settings", self.settings_page),
                           ("About", self.about_page)):
            action = QAction(text, self)
            action.setCheckable(True)
            action.triggered.connect(
                lambda _checked, p=page: self.stack.setCurrentWidget(p))
            nav_group.addAction(action)
            toolbar.addAction(action)
            if page is self.library_page:
                action.setChecked(True)

        # Start on the Sounds library
        self.stack.setCurrentWidget(self.library_page)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._update_status_bar()

    def _open_recording(self, label):
        if label:
            self.recording_view.start_for(label)
        else:
            self.recording_view.start_new()
        self.stack.setCurrentWidget(self.recording_view)

    def _return_to_sounds(self, label):
        self.stack.setCurrentWidget(self.library_page)
        if label:
            self.library_page._select_label_by_name(label)

    def _on_stack_changed(self, _index):
        if self.stack.currentWidget() is not self.recording_view:
            self.recording_view.stop_worker()

    def _update_status_bar(self):
        try:
            device_info = sd.query_devices(INPUT_DEVICE_INDEX)
            device_name = device_info['name'] if device_info else "Unknown"
        except Exception:
            device_name = "No device"
        self.status_bar.showMessage(f"Audio device: {device_name} (index {INPUT_DEVICE_INDEX})")
