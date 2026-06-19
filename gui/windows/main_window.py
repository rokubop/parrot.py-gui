from PyQt6.QtWidgets import (
    QMainWindow, QToolBar, QStatusBar, QStackedWidget
)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt
import sounddevice as sd
from config.config import INPUT_DEVICE_INDEX
from gui.models.app_state import AppState
from gui.windows.library import SoundLibraryPage
from gui.windows.recording import RecordingPage
from gui.windows.training import TrainingPage


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Parrot.py")
        self.setMinimumSize(1200, 800)

        self.app_state = AppState(self)

        # Central stacked widget
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        # Pages
        self.library_page = SoundLibraryPage(self.app_state, self)
        self.recording_page = RecordingPage(self.app_state, self)
        self.training_page = TrainingPage(self.app_state, self)
        self.stack.addWidget(self.library_page)
        self.stack.addWidget(self.recording_page)
        self.stack.addWidget(self.training_page)

        # Toolbar
        toolbar = QToolBar("Navigation")
        toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

        self.library_action = QAction("Sounds", self)
        self.library_action.triggered.connect(lambda: self.stack.setCurrentWidget(self.library_page))
        toolbar.addAction(self.library_action)

        self.recording_action = QAction("Recording", self)
        self.recording_action.triggered.connect(lambda: self.stack.setCurrentWidget(self.recording_page))
        toolbar.addAction(self.recording_action)

        self.training_action = QAction("Training", self)
        self.training_action.triggered.connect(lambda: self.stack.setCurrentWidget(self.training_page))
        toolbar.addAction(self.training_action)

        # Start on the read-only Sounds library
        self.stack.setCurrentWidget(self.library_page)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._update_status_bar()

    def _update_status_bar(self):
        try:
            device_info = sd.query_devices(INPUT_DEVICE_INDEX)
            device_name = device_info['name'] if device_info else "Unknown"
        except Exception:
            device_name = "No device"
        self.status_bar.showMessage(f"Audio device: {device_name} (index {INPUT_DEVICE_INDEX})")
