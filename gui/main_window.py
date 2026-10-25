import os

from PyQt6.QtWidgets import (
    QMainWindow, QToolBar, QStatusBar, QStackedWidget, QLabel, QWidget,
    QSizePolicy, QVBoxLayout, QToolButton, QMenu, QApplication, QPushButton,
    QMessageBox, QScrollArea
)
from PyQt6.QtGui import QAction, QActionGroup, QShortcut, QKeySequence
from PyQt6.QtCore import Qt, QTimer, QSize
from gui.state import AppState
from gui.services import profiles
from gui.pages.home import HomePage
from gui.pages.library import SoundLibraryPage
from gui import theme, icons


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
        profile = profiles.current_profile()
        self.setWindowTitle(
            "Parrot.py" if profile is None else f"Parrot.py (profile: {profile})")
        self.setMinimumSize(1200, 800)

        self.app_state = AppState(self)

        self.page_stack = QStackedWidget()
        self.setCentralWidget(self.page_stack)

        # only Home + Sounds build eagerly; other tabs cost 30-200 ms each
        # (some query audio devices), so they build lazily on first use
        self.home_page = HomePage(self.app_state, self)
        self.page_stack.addWidget(self.home_page)
        self.home_page.navigate.connect(self._go_to_page)

        self.library_page = SoundLibraryPage(self.app_state, self)
        self.page_stack.addWidget(self.library_page)
        self.library_page.record_requested.connect(self._open_recording)
        self.library_page.edit_requested.connect(self._open_edit)

        self.models_page = None
        self.integrations_page = None
        self.settings_page = None
        self.about_page = None
        self.recording_view = None
        self.edit_view = None
        self.train_view = None

        self.page_stack.currentChanged.connect(self._on_stack_changed)

        # Toolbar navigation - checkable actions so the current tab is obvious.
        toolbar = self.toolbar = QToolBar("Navigation")
        toolbar.setMovable(False)
        # Without this, right-clicking the toolbar opens a Qt menu with a
        # "Navigation" checkbox. Unticking it hides the tabs, with no way to
        # get them back short of restarting.
        toolbar.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        # 16px against 13px text. The default 24 makes the profile chip's icon
        # shout over the six nav tabs, which carry no icon at all.
        toolbar.setIconSize(QSize(16, 16))
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
        self._nav_group = QActionGroup(self)
        self._nav_group.setExclusive(True)

        self.nav_actions = {}
        for text in ("Home", "Sounds", "Models", "Integrations",
                     "Settings", "About"):
            action = QAction(text, self)
            action.setCheckable(True)
            action.triggered.connect(lambda _checked, t=text: self._show_page(t))
            self._nav_group.addAction(action)
            toolbar.addAction(action)
            # Qt default is NoFocus. TabFocus so a click doesn't leave a ring
            toolbar.widgetForAction(action).setFocusPolicy(Qt.FocusPolicy.TabFocus)
            self.nav_actions[text] = action
        self.nav_actions["Home"].setChecked(True)
        self.page_stack.setCurrentWidget(self.home_page)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        # Profile chip: who you are + the switcher, Chrome-style. Hidden until
        # a profile exists so the common single-setup case never sees it;
        # the entry point for creating one is in Settings.
        self.profile_chip = QToolButton()
        self.profile_chip.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        # Set on the button, not inherited: the toolbar's toolButtonStyle only
        # reaches buttons it builds for actions, not one handed to addWidget.
        self.profile_chip.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._profile_menu = QMenu(self)
        self._profile_menu.aboutToShow.connect(self._build_profile_menu)
        self.profile_chip.setMenu(self._profile_menu)
        toolbar.addWidget(self.profile_chip)
        self._refresh_profile_chip()

        # Status bar: each page's keybindings. Nothing may call showMessage()
        # here - temporary messages hide the non-permanent widgets.
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        # A run survives leaving the training page; without this a multi-hour
        # job is invisible the moment you switch tabs.
        self.training_chip = QPushButton("")
        self.training_chip.setFlat(True)
        self.training_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.training_chip.setFocusPolicy(Qt.FocusPolicy.TabFocus)
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
        self._build_zoom_shortcuts()

    # ---- tab order ----------------------------------------------------

    def focusNextPrevChild(self, forward):
        """Tab walks toolbar, current page, status bar.

        Qt's own order is build order. Lazy pages and Sounds' cards are built
        after the toolbar, so Tab would jump from the toolbar into the middle
        of a page."""
        page = self.page_stack.currentWidget()
        order = [w for region in (self.toolbar, page, self.status_bar)
                 for w in self._focus_chain(region)]
        # a focus proxy (a spin box's line edit, a plot's viewport) hands
        # focus to its owner, which is in the list on its own
        stops = [w for w in order if w.focusPolicy() & Qt.FocusPolicy.TabFocus
                 and w.focusProxy() is None and w.isVisible() and w.isEnabled()]
        if not stops:
            return super().focusNextPrevChild(forward)
        focused = QApplication.focusWidget()
        # a page can step forward from somewhere else, e.g. Sounds from its
        # selected card
        if forward and hasattr(page, "tab_anchor"):
            focused = page.tab_anchor(focused)
        if focused in order:
            # step from where focus is, even when that is not a stop itself
            i = order.index(focused)
            ahead = (order[i + 1:] + order[:i] if forward
                     else order[:i][::-1] + order[i + 1:][::-1])
            target = next((w for w in ahead if w in stops), stops[0])
        else:
            target = stops[0] if forward else stops[-1]
        reason = Qt.FocusReason.TabFocusReason if forward else Qt.FocusReason.BacktabFocusReason
        target.setFocus(reason)
        scroll = target.parentWidget()
        while scroll is not None and not isinstance(scroll, QScrollArea):
            scroll = scroll.parentWidget()
        if scroll is not None:
            scroll.ensureWidgetVisible(target)
        return True

    def _focus_chain(self, region):
        """region and its descendants, in Qt's focus chain order."""
        found, w = [region], region.nextInFocusChain()
        while w is not region:
            if region.isAncestorOf(w):
                found.append(w)
            w = w.nextInFocusChain()
        return found

    # ---- lazy page construction ---------------------------------------

    def _get_models_page(self):
        if self.models_page is None:
            from gui.pages.models import ModelsPage
            self.models_page = ModelsPage(self.app_state, self)
            self.models_page.train_requested.connect(self._open_train)
            self.models_page.navigate.connect(self._go_to_page)
            self.page_stack.addWidget(self.models_page)
        return self.models_page

    def _get_integrations_page(self):
        if self.integrations_page is None:
            from gui.pages.integrations import IntegrationsPage
            self.integrations_page = IntegrationsPage(self.app_state, self)
            self.page_stack.addWidget(self.integrations_page)
        return self.integrations_page

    def _get_settings_page(self):
        if self.settings_page is None:
            from gui.pages.settings import SettingsPage
            self.settings_page = SettingsPage(self.app_state, self)
            self.page_stack.addWidget(self.settings_page)
        return self.settings_page

    def _get_about_page(self):
        if self.about_page is None:
            from gui.pages.about import AboutPage
            self.about_page = AboutPage(self.app_state, self)
            self.page_stack.addWidget(self.about_page)
        return self.about_page

    def _get_recording_view(self):
        if self.recording_view is None:
            from gui.pages.recording_view import RecordingView
            self.recording_view = RecordingView(self.app_state, self)
            self.recording_view.done.connect(self._return_to_sounds)
            self._wire_keybindings(self.recording_view)
            self.page_stack.addWidget(self.recording_view)
        return self.recording_view

    def _get_edit_view(self):
        if self.edit_view is None:
            from gui.pages.edit_view import EditRecordingView
            self.edit_view = EditRecordingView(self.app_state, self)
            self.edit_view.done.connect(self._return_to_sounds)
            self._wire_keybindings(self.edit_view)
            self.page_stack.addWidget(self.edit_view)
        return self.edit_view

    def _get_train_view(self):
        if self.train_view is None:
            from gui.pages.train_view import TrainView
            self.train_view = TrainView(self.app_state, self)
            self.train_view.done.connect(self._return_to_models)
            self.train_view.navigate.connect(self._go_to_page)
            self.train_view.run_state.connect(self._on_training_state)
            self.page_stack.addWidget(self.train_view)
        return self.train_view

    def _go_to_page(self, name):
        """Navigation from page buttons: keeps the toolbar checked state in sync."""
        if name in self.nav_actions:
            self.nav_actions[name].setChecked(True)
            self._show_page(name)

    def _show_page(self, name):
        if name == "Home":
            self.page_stack.setCurrentWidget(self.home_page)
        elif name == "Sounds":
            self.page_stack.setCurrentWidget(self.library_page)
        elif name == "Models":
            self.page_stack.setCurrentWidget(self._get_models_page())
        elif name == "Integrations":
            self.page_stack.setCurrentWidget(self._get_integrations_page())
        elif name == "Settings":
            self.page_stack.setCurrentWidget(self._get_settings_page())
        elif name == "About":
            self.page_stack.setCurrentWidget(self._get_about_page())

    # ---- sub-views -----------------------------------------------------

    def _open_recording(self, label):
        view = self._get_recording_view()
        if label:
            view.start_for(label)
        else:
            view.start_new()
        self.page_stack.setCurrentWidget(view)

    def _open_edit(self, wav_path):
        view = self._get_edit_view()
        view.start_for(wav_path)
        self.page_stack.setCurrentWidget(view)

    def _open_train(self):
        view = self._get_train_view()
        view.start()
        self.page_stack.setCurrentWidget(view)

    def _on_training_state(self, text):
        """Live run, or "" for none. Click returns to it. Worded, not a glyph:
        which glyphs resolve depends on the machine."""
        self.training_chip.setText(f"Training {text}" if text else "")
        self.training_chip.setVisible(bool(text))

    def _return_to_models(self, model_name):
        page = self._get_models_page()
        self.page_stack.setCurrentWidget(page)
        self.nav_actions["Models"].setChecked(True)
        if model_name:
            page.select_model(model_name)

    def _return_to_sounds(self, label):
        self.page_stack.setCurrentWidget(self.library_page)
        self.nav_actions["Sounds"].setChecked(True)
        if label:
            self.library_page._select_label_by_name(label)

    def _on_stack_changed(self, _index):
        current = self.page_stack.currentWidget()
        if self.recording_view is not None and current is not self.recording_view:
            self.recording_view.stop_worker()
        if self.edit_view is not None and current is not self.edit_view:
            self.edit_view.stop_playback()
        self._refresh_keybindings()

    # ---- profile chip ---------------------------------------------------

    def _refresh_profile_chip(self):
        current = profiles.current_profile()
        # Painted, not 👤: the emoji font drew it dark purple at 1.28:1 on this
        # toolbar and no stylesheet could reach it. Rebuilt here rather than
        # once at startup so it follows a theme change for free.
        self.profile_chip.setIcon(icons.person())
        self.profile_chip.setText(current or "Main")
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
        if not self.confirm_closing("Switch profile", "Restart now",
                                    restart_reason="switch profiles"):
            return
        profiles.spawn_into(name)
        QTimer.singleShot(0, QApplication.instance().quit)

    def at_risk(self):
        """Everything a relaunch or a quit would throw away, in words."""
        losses = []
        if self.training_chip.isVisible():
            losses.append(f"{self.training_chip.text()} is still running")
        if self.recording_view is not None and self.recording_view.worker:
            losses.append("a recording in progress")
        if self.edit_view is not None and self.edit_view.history.is_dirty():
            losses.append(f"unsaved edits to “{self.edit_view.label}”")
        for view in (self.edit_view, self.recording_view):
            if view is not None and view.detection.has_pending():
                losses.append(f"an unapplied threshold "
                              f"({view.detection.pending_summary()})")
        return losses

    def confirm_closing(self, title, verb, restart_reason=None):
        """True if the user accepts the app going away.

        `restart_reason` completes "Parrot.py needs to restart to ___" and
        makes this always ask: a restart always asks, quitting asks only when
        something is at stake.
        """
        losses = self.at_risk()
        if not losses and restart_reason is None:
            return True
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(
            (f"Parrot.py needs to restart to {restart_reason}."
             if restart_reason else "This closes Parrot.py.")
            + ("\n\nYou would lose:\n\n"
               + "\n".join(f"  ·  {item}" for item in losses) if losses else ""))
        go = box.addButton(verb, QMessageBox.ButtonRole.DestructiveRole
                           if losses else QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(go if not losses else box.buttons()[-1])
        box.exec()
        return box.clickedButton() is go

    def closeEvent(self, event):
        if self.confirm_closing("Quit?", "Quit"):
            event.accept()
        else:
            event.ignore()

    def open_profiles_dialog(self):
        from gui.pages.profiles import ProfilesDialog
        dialog = ProfilesDialog(self.app_state, self)
        dialog.exec()
        self._refresh_profile_chip()

    # ---- interface size --------------------------------------------------

    def _build_zoom_shortcuts(self):
        """Ctrl +/- steps the interface size; Ctrl+0 goes back to 100%.

        Qt reads the scale factor once, at QApplication build, so applying is a
        relaunch. The keys move a pending value; the restart fires ~1.5 s after
        the last press, and stepping back to the current size cancels it.
        """
        self._zoom_pending = None
        self._zoom_timer = QTimer(self)
        self._zoom_timer.setSingleShot(True)
        self._zoom_timer.setInterval(1500)
        self._zoom_timer.timeout.connect(self._commit_zoom)
        # A floating label rather than the status bar: showMessage() there
        # hides the permanent widgets (see the status bar comment above).
        self._zoom_toast = QLabel("", self)
        self._zoom_toast.setVisible(False)
        self._zoom_toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_toast.setStyleSheet(
            f"background-color: {theme.colors()['panel']}; "
            f"color: {theme.colors()['text_bright']}; "
            f"border: 1px solid {theme.colors()['control_border']}; "
            f"border-radius: {theme.colors()['radius_card']}; "
            f"padding: 10px 18px; "
            f"font-size: {theme.TYPE_SCALE['card']}px;")
        for keys, step in (("Ctrl+=", 1), ("Ctrl++", 1), ("Ctrl+-", -1),
                           ("Ctrl+0", 0)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(lambda s=step: self._step_zoom(s))

    def _step_zoom(self, step):
        from gui.services import ui_prefs
        sizes = list(ui_prefs.SCALES)
        current = self._zoom_pending or ui_prefs.scale()
        if step == 0:
            pending = 1.0
        else:
            index = min(max(sizes.index(current) + step, 0), len(sizes) - 1)
            pending = sizes[index]
        self._zoom_pending = pending
        if pending == ui_prefs.scale():
            self._zoom_timer.stop()
            self._show_zoom_toast(f"Interface size {pending:.0%}")
            return
        # Not "restarting…": a confirm comes first.
        self._show_zoom_toast(f"Interface size {pending:.0%}  ·  restart to apply")
        self._zoom_timer.start()

    def _show_zoom_toast(self, text):
        self._zoom_toast.setText(text)
        self._zoom_toast.adjustSize()
        self._zoom_toast.move((self.width() - self._zoom_toast.width()) // 2,
                              max(12, self.height() // 6))
        self._zoom_toast.raise_()
        self._zoom_toast.setVisible(True)
        QTimer.singleShot(2200, self._zoom_toast.hide)

    def _commit_zoom(self):
        from gui.services import ui_prefs
        pending, self._zoom_pending = self._zoom_pending, None
        if pending is None or pending == ui_prefs.scale():
            return
        if not self.confirm_closing(
                "Interface size", "Restart now",
                restart_reason=f"apply the {pending:.0%} interface size"):
            self._zoom_toast.hide()
            return
        ui_prefs.set_scale(pending)
        env = dict(os.environ)
        # This process carries the old factor; an explicit one beats the file.
        env.pop(ui_prefs.ENV, None)
        profiles.relaunch(env)
        QTimer.singleShot(0, QApplication.instance().quit)

    # ---- keybinding status bar -----------------------------------------

    def _wire_keybindings(self, page):
        """Let a page push live keybinding updates (e.g. when its mode changes)
        into the status bar, but only while it's the visible page."""
        sig = getattr(page, "keybindings_changed", None)
        if sig is not None:
            sig.connect(lambda p=page: self._refresh_keybindings()
                        if self.page_stack.currentWidget() is p else None)

    def _refresh_keybindings(self):
        page = self.page_stack.currentWidget()
        getter = getattr(page, "keybinding_hint", None)
        self.keys_label.setText(getter() if callable(getter) else "")
