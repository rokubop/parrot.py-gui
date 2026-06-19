from PyQt6.QtWidgets import (
    QMainWindow, QToolBar, QStatusBar, QStackedWidget, QWidget, QComboBox, QLabel,
    QSizePolicy
)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
import sounddevice as sd
from config.config import INPUT_DEVICE_INDEX
from gui.models.app_state import AppState
from gui.windows.library import SoundLibraryPage
from gui.windows.recording import RecordingPage
from gui.windows.training import TrainingPage
from gui import theme


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

        # Theme switcher (right-aligned)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        toolbar.addWidget(QLabel("Theme: "))
        self.theme_combo = QComboBox()
        for name in theme.names():
            self.theme_combo.addItem(theme.THEMES[name]["name"], name)
        self.theme_combo.setCurrentIndex(theme.names().index(theme.current_name()))
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        toolbar.addWidget(self.theme_combo)

        # Start on the read-only Sounds library
        self.stack.setCurrentWidget(self.library_page)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._update_status_bar()

    def _on_theme_changed(self, index):
        name = self.theme_combo.itemData(index)
        theme.apply(QApplication.instance(), name)
        for page in (self.library_page, self.recording_page, self.training_page):
            if hasattr(page, "refresh_theme"):
                page.refresh_theme()

    def _update_status_bar(self):
        try:
            device_info = sd.query_devices(INPUT_DEVICE_INDEX)
            device_name = device_info['name'] if device_info else "Unknown"
        except Exception:
            device_name = "No device"
        self.status_bar.showMessage(f"Audio device: {device_name} (index {INPUT_DEVICE_INDEX})")
