from PyQt6.QtWidgets import (
    QMainWindow, QToolBar, QStatusBar, QStackedWidget, QLabel, QWidget,
    QSizePolicy, QVBoxLayout, QToolButton, QMenu, QApplication, QPushButton,
    QMessageBox
)
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtCore import Qt, QTimer
from gui.models.app_state import AppState
from gui.services import profiles
from gui.windows.home import HomePage
from gui.windows.library import SoundLibraryPage
from gui import theme


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
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
        # "Integrations" rather than "Talon": Talon is the one that exists, but
        # the tab is the place where this app meets another, and naming it after
        # the only current occupant made a second one look like a redesign.
        for text in ("Home", "Sounds", "Models", "Integrations",
                     "Settings", "About"):
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
        # Profile chip: who you are + the switcher, Chrome-style. Hidden until
        # a profile exists so the common single-setup case never sees it;
        # the entry point for creating one is in Settings.
        self.profile_chip = QToolButton()
        self.profile_chip.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._profile_menu = QMenu(self)
        self._profile_menu.aboutToShow.connect(self._build_profile_menu)
        self.profile_chip.setMenu(self._profile_menu)
        toolbar.addWidget(self.profile_chip)
        self._refresh_profile_chip()
        notes_action = QAction("📝 Notes", self)
        notes_action.setCheckable(True)
        notes_action.toggled.connect(self.notes_dock.setVisible)
        self.notes_dock.visibilityChanged.connect(notes_action.setChecked)
        toolbar.addAction(notes_action)

        # Status bar: Audacity-style device pickers (left) + the active
        # keybindings for whatever view is showing (right). The keybinding hint
        # is the single, always-in-the-same-place home for shortcuts - each page
        # reports its own. Nothing may call showMessage() here: temporary
        # messages hide left-side (non-permanent) widgets, i.e. the pickers.
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        from gui.widgets.device_bar import DeviceBar
        self.device_bar = DeviceBar()
        self.status_bar.addWidget(self.device_bar)
        # A run survives leaving the training page, so something has to say so.
        # Without it a 4-6 hour job is invisible the moment you switch tabs, and
        # the only way back is + New model, which looks like starting over.
        self.training_chip = QPushButton("")
        self.training_chip.setFlat(True)
        self.training_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.training_chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.training_chip.setStyleSheet(
            f"QPushButton {{ color: {theme.colors()['accent']}; border: none; "
            f"padding: 0 8px; text-align: left; }}")
        self.training_chip.clicked.connect(self._open_train)
        self.training_chip.setVisible(False)
        self.status_bar.addPermanentWidget(self.training_chip)
        self.keys_label = QLabel("")
        self.keys_label.setStyleSheet(f"color: {theme.colors()['text_dim']}; padding-right: 8px;")
        self.status_bar.addPermanentWidget(self.keys_label)
        self._wire_keybindings(self.library_page)
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
            self.train_view.run_state.connect(self._on_training_state)
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
        elif name == "Integrations":
            self.stack.setCurrentWidget(self._get_talon_page())
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

    def _open_train(self):
        view = self._get_train_view()
        view.start()
        self.stack.setCurrentWidget(view)

    def _on_training_state(self, text):
        """Live run, or "" for none. Click returns to it.

        Worded rather than badged: a glyph here would be the only one in the
        status bar, and which glyphs actually resolve depends on the machine.
        """
        self.training_chip.setText(f"Training {text}" if text else "")
        self.training_chip.setVisible(bool(text))

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

    # ---- profile chip ---------------------------------------------------

    def _refresh_profile_chip(self):
        current = profiles.current_profile()
        self.profile_chip.setText(f"👤 {current or 'Main'}")
        self.profile_chip.setVisible(
            bool(profiles.list_profiles()) or current is not None)

    def _build_profile_menu(self):
        menu = self._profile_menu
        menu.clear()
        current = profiles.current_profile()
        for name in [None] + profiles.list_profiles():
            action = menu.addAction(name or "Main")
            action.setCheckable(True)
            action.setChecked(name == current)
            if name == current:
                action.setEnabled(False)
            else:
                action.triggered.connect(
                    lambda _checked, n=name: self._switch_profile(n))
        menu.addSeparator()
        menu.addAction("Manage profiles...", self.open_profiles_dialog)

    def _switch_profile(self, name):
        # Switching relaunches the app, which ends a run silently.
        if not self._confirm_over_training("Switch profile?", "Switch"):
            return
        profiles.spawn_into(name)
        QTimer.singleShot(0, QApplication.instance().quit)

    def _confirm_over_training(self, title, verb):
        """True if there is no live run, or the user accepts losing it."""
        if not self.training_chip.isVisible():
            return True
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(f"{self.training_chip.text()} is still running.\n"
                    f"It will be lost.")
        go = box.addButton(verb, QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Stay", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(box.buttons()[-1])
        box.exec()
        return box.clickedButton() is go

    def closeEvent(self, event):
        if self._confirm_over_training("Quit?", "Quit"):
            event.accept()
        else:
            event.ignore()

    def open_profiles_dialog(self):
        from gui.windows.profiles import ProfilesDialog
        dialog = ProfilesDialog(self.app_state, self)
        dialog.exec()
        self._refresh_profile_chip()

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
