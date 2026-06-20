from PyQt6.QtWidgets import (
    QMainWindow, QToolBar, QStatusBar, QStackedWidget
)
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtCore import Qt
import sounddevice as sd
from config.config import INPUT_DEVICE_INDEX
from gui.models.app_state import AppState
from gui.windows.library import SoundLibraryPage


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Parrot.py")
        self.setMinimumSize(1200, 800)

        self.app_state = AppState(self)

        # Central stacked widget
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        # Only the landing page (Sounds) is built eagerly. The other tabs and
        # the recording/edit sub-views are constructed on first use so startup
        # shows the library as fast as possible (each of the others costs
        # ~30-200 ms to build, incl. an audio-device query for the recording
        # views). See _page() / the lazy getters below.
        self.library_page = SoundLibraryPage(self.app_state, self)
        self.stack.addWidget(self.library_page)
        self.library_page.record_requested.connect(self._open_recording)
        self.library_page.edit_requested.connect(self._open_edit)
        self.library_page.append_requested.connect(self._open_append)

        self.models_page = None
        self.settings_page = None
        self.about_page = None
        self.recording_view = None
        self.edit_view = None

        self.stack.currentChanged.connect(self._on_stack_changed)

        # Toolbar navigation — checkable actions so the current tab is obvious.
        toolbar = QToolBar("Navigation")
        toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
        self._nav_group = QActionGroup(self)
        self._nav_group.setExclusive(True)

        self.nav_actions = {}
        for text in ("Sounds", "Models", "Settings", "About"):
            action = QAction(text, self)
            action.setCheckable(True)
            action.triggered.connect(lambda _checked, t=text: self._show_tab(t))
            self._nav_group.addAction(action)
            toolbar.addAction(action)
            self.nav_actions[text] = action
        self.nav_actions["Sounds"].setChecked(True)

        # Start on the Sounds library
        self.stack.setCurrentWidget(self.library_page)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._update_status_bar()

    # ---- lazy page construction ---------------------------------------

    def _get_models_page(self):
        if self.models_page is None:
            from gui.windows.models import ModelsPage
            self.models_page = ModelsPage(self.app_state, self)
            self.stack.addWidget(self.models_page)
        return self.models_page

    def _get_settings_page(self):
        if self.settings_page is None:
            from gui.windows.settings import SettingsPage
            self.settings_page = SettingsPage(self.app_state, self)
            self.stack.addWidget(self.settings_page)
        return self.settings_page

    def _get_about_page(self):
        if self.about_page is None:
            from gui.windows.about import AboutPage
            self.about_page = AboutPage(self.app_state, self)
            self.stack.addWidget(self.about_page)
        return self.about_page

    def _get_recording_view(self):
        if self.recording_view is None:
            from gui.windows.recording_view import RecordingView
            self.recording_view = RecordingView(self.app_state, self)
            self.recording_view.done.connect(self._return_to_sounds)
            self.stack.addWidget(self.recording_view)
        return self.recording_view

    def _get_edit_view(self):
        if self.edit_view is None:
            from gui.windows.edit_view import EditRecordingView
            self.edit_view = EditRecordingView(self.app_state, self)
            self.edit_view.done.connect(self._return_to_sounds)
            self.edit_view.append_requested.connect(self._open_append)
            self.stack.addWidget(self.edit_view)
        return self.edit_view

    def _show_tab(self, name):
        if name == "Sounds":
            self.stack.setCurrentWidget(self.library_page)
        elif name == "Models":
            self.stack.setCurrentWidget(self._get_models_page())
        elif name == "Settings":
            self.stack.setCurrentWidget(self._get_settings_page())
        elif name == "About":
            self.stack.setCurrentWidget(self._get_about_page())

    # ---- sub-views -----------------------------------------------------

    def _open_recording(self, label):
        view = self._get_recording_view()
        if label:
            view.start_for(label)
        else:
            view.start_new()
        self.stack.setCurrentWidget(view)

    def _open_edit(self, wav_path):
        view = self._get_edit_view()
        view.start_for(wav_path)
        self.stack.setCurrentWidget(view)

    def _open_append(self, wav_path):
        view = self._get_recording_view()
        view.start_append(wav_path)
        self.stack.setCurrentWidget(view)

    def _return_to_sounds(self, label):
        self.stack.setCurrentWidget(self.library_page)
        self.nav_actions["Sounds"].setChecked(True)
        if label:
            self.library_page._select_label_by_name(label)

    def _on_stack_changed(self, _index):
        current = self.stack.currentWidget()
        if self.recording_view is not None and current is not self.recording_view:
            self.recording_view.stop_worker()
        if self.edit_view is not None and current is not self.edit_view:
            self.edit_view.stop_playback()

    def _update_status_bar(self):
        try:
            device_info = sd.query_devices(INPUT_DEVICE_INDEX)
            device_name = device_info['name'] if device_info else "Unknown"
        except Exception:
            device_name = "No device"
        self.status_bar.showMessage(f"Audio device: {device_name} (index {INPUT_DEVICE_INDEX})")
