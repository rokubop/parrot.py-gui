from PyQt6.QtWidgets import (
    QMainWindow, QToolBar, QStatusBar, QStackedWidget, QLabel, QWidget,
    QSizePolicy, QVBoxLayout
)
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtCore import Qt
import sounddevice as sd
from config.config import INPUT_DEVICE_INDEX
from gui.models.app_state import AppState
from gui.windows.home import HomePage
from gui.windows.library import SoundLibraryPage
from gui import theme


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        from gui.services import profiles
        profile = profiles.current_profile()
        self.setWindowTitle(
            "Parrot.py" if profile is None else f"Parrot.py (profile: {profile})")
        self.setMinimumSize(1200, 800)

        self.app_state = AppState(self)

        # Central stacked widget
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        # only Home + Sounds build eagerly; other tabs cost 30-200 ms each
        # (some query audio devices), so they build lazily on first use
        self.home_page = HomePage(self.app_state, self)
        self.stack.addWidget(self.home_page)
        self.home_page.navigate.connect(self._go_to_tab)

        self.library_page = SoundLibraryPage(self.app_state, self)
        self.stack.addWidget(self.library_page)
        self.library_page.record_requested.connect(self._open_recording)
        self.library_page.edit_requested.connect(self._open_edit)

        self.models_page = None
        self.talon_page = None
        self.settings_page = None
        self.profiles_page = None
        self.about_page = None
        self.recording_view = None
        self.edit_view = None
        self.train_view = None

        self.stack.currentChanged.connect(self._on_stack_changed)

        # Toolbar navigation - checkable actions so the current tab is obvious.
        toolbar = QToolBar("Navigation")
        toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
        self._nav_group = QActionGroup(self)
        self._nav_group.setExclusive(True)

        self.nav_actions = {}
        for text in ("Home", "Sounds", "Models", "Talon", "Settings", "Profiles", "About"):
            action = QAction(text, self)
            action.setCheckable(True)
            action.triggered.connect(lambda _checked, t=text: self._show_tab(t))
            self._nav_group.addAction(action)
            toolbar.addAction(action)
            self.nav_actions[text] = action
        self.nav_actions["Home"].setChecked(True)
        self.stack.setCurrentWidget(self.home_page)

        # notes drawer: hidden until toggled, closable via its X too
        from gui.widgets.notes_dock import NotesDock
        self.notes_dock = NotesDock(self.app_state, self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.notes_dock)
        self.notes_dock.hide()
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        # Audacity-style device pickers, right side of the top bar
        from gui.widgets.device_bar import DeviceBar
        self.device_bar = DeviceBar()
        self.device_bar.input_changed.connect(lambda _i: self._update_status_bar())
        toolbar.addWidget(self.device_bar)
        notes_action = QAction("📝 Notes", self)
        notes_action.setCheckable(True)
        notes_action.toggled.connect(self.notes_dock.setVisible)
        self.notes_dock.visibilityChanged.connect(notes_action.setChecked)
        toolbar.addAction(notes_action)

        # Status bar: audio device (left) + the active keybindings for whatever
        # view is showing (right). The keybinding hint is the single, always-in-
        # the-same-place home for shortcuts - each page reports its own.
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.keys_label = QLabel("")
        self.keys_label.setStyleSheet(f"color: {theme.colors()['text_dim']}; padding-right: 8px;")
        self.status_bar.addPermanentWidget(self.keys_label)
        self._wire_keybindings(self.library_page)
        self._update_status_bar()
        self._refresh_keybindings()

    # ---- lazy page construction ---------------------------------------

    def _get_models_page(self):
        if self.models_page is None:
            from gui.windows.models import ModelsPage
            self.models_page = ModelsPage(self.app_state, self)
            self.models_page.train_requested.connect(self._open_train)
            self.models_page.navigate.connect(self._go_to_tab)
            self.stack.addWidget(self.models_page)
        return self.models_page

    def _get_talon_page(self):
        if self.talon_page is None:
            from gui.windows.talon import TalonPage
            self.talon_page = TalonPage(self.app_state, self)
            self.stack.addWidget(self.talon_page)
        return self.talon_page

    def _get_settings_page(self):
        if self.settings_page is None:
            from gui.windows.settings import SettingsPage
            self.settings_page = SettingsPage(self.app_state, self)
            self.stack.addWidget(self.settings_page)
        return self.settings_page

    def _get_profiles_page(self):
        if self.profiles_page is None:
            from gui.windows.profiles import ProfilesPage
            self.profiles_page = ProfilesPage(self.app_state, self)
            self.stack.addWidget(self.profiles_page)
        return self.profiles_page

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
            self._wire_keybindings(self.recording_view)
            self.stack.addWidget(self.recording_view)
            # its mic readout mirrors the top device bar
            view = self.recording_view
            self.device_bar.input_changed.connect(lambda _i: view.refresh_mic_label())
            self.device_bar.extras_changed.connect(lambda _e: view.refresh_mic_label())
        return self.recording_view

    def _get_edit_view(self):
        if self.edit_view is None:
            from gui.windows.edit_view import EditRecordingView
            self.edit_view = EditRecordingView(self.app_state, self)
            self.edit_view.done.connect(self._return_to_sounds)
            self._wire_keybindings(self.edit_view)
            self.stack.addWidget(self.edit_view)
        return self.edit_view

    def _get_train_view(self):
        if self.train_view is None:
            from gui.windows.train_view import TrainView
            self.train_view = TrainView(self.app_state, self)
            self.train_view.done.connect(self._return_to_models)
            self.train_view.navigate.connect(self._go_to_tab)
            self.stack.addWidget(self.train_view)
        return self.train_view

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
        elif name == "Talon":
            self.stack.setCurrentWidget(self._get_talon_page())
        elif name == "Settings":
            self.stack.setCurrentWidget(self._get_settings_page())
        elif name == "Profiles":
            page = self._get_profiles_page()
            page._refresh()
            self.stack.setCurrentWidget(page)
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

    def _open_train(self):
        view = self._get_train_view()
        view.start()
        self.stack.setCurrentWidget(view)

    def _return_to_models(self, model_name):
        page = self._get_models_page()
        self.stack.setCurrentWidget(page)
        self.nav_actions["Models"].setChecked(True)
        if model_name:
            page.select_model(model_name)

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
        self._refresh_keybindings()

    # ---- keybinding status bar -----------------------------------------

    def _wire_keybindings(self, page):
        """Let a page push live keybinding updates (e.g. when its mode changes)
        into the status bar, but only while it's the visible page."""
        sig = getattr(page, "keybindings_changed", None)
        if sig is not None:
            sig.connect(lambda p=page: self._refresh_keybindings()
                        if self.stack.currentWidget() is p else None)

    def _refresh_keybindings(self):
        page = self.stack.currentWidget()
        getter = getattr(page, "keybinding_hint", None)
        self.keys_label.setText(getter() if callable(getter) else "")

    def _update_status_bar(self):
        from gui.services import audio_devices
        index = audio_devices.input_index
        try:
            device_info = sd.query_devices(index)
            device_name = device_info['name'] if device_info else "Unknown"
        except Exception:
            device_name = "No device"
        self.status_bar.showMessage(f"Audio device: {device_name} (index {index})")
