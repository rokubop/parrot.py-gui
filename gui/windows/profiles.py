"""Manage-profiles dialog, reached from the toolbar profile chip and Settings.

Lists the Main data plus every profile under data-profiles/, with what each
one has (sounds, models). Switching relaunches the GUI with PARROT_DATA_DIR
pointing at the chosen profile; see gui/services/profiles.py for the layout
and the baseline freeze/reset story. With PARROT_DEBUG=1 a per-profile Talon
simulation toggle appears.
"""
import os

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QGroupBox, QComboBox, QInputDialog, QMessageBox,
    QApplication, QFileDialog
)

from gui import theme
from gui.services import profiles, library_ops


class _OpWorker(QThread):
    """Runs one profile operation (they copy whole data trees) off the UI
    thread. The page keeps a strong reference until done fires."""
    done = pyqtSignal(str)  # error text, empty on success

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            self._fn()
            self.done.emit("")
        except Exception as exc:
            self.done.emit(str(exc))


class _ScanWorker(QThread):
    found = pyqtSignal(list)

    def run(self):
        try:
            self.found.emit(profiles.find_existing_setups())
        except Exception:
            self.found.emit([])


class ImportSetupDialog(QDialog):
    """Bring an outside Parrot.py setup in as a profile, by copy.

    Scans common folders for the data/recordings shape on open; a folder
    picker covers everything the scan misses. The source is never modified.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bring in an existing setup")
        self.resize(640, 380)
        self._worker = None
        self.imported = None  # profile name on success

        t = theme.colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        note = QLabel(
            "Copies the sounds and models of another Parrot.py into a "
            "profile here. The original folder is not changed.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {t['text_dim']};")
        layout.addWidget(note)

        self.list = QListWidget()
        self.list.currentItemChanged.connect(lambda *_: self._update_buttons())
        self.list.itemDoubleClicked.connect(lambda _i: self._on_import())
        layout.addWidget(self.list, stretch=1)

        row = QHBoxLayout()
        choose_btn = QPushButton("Choose folder...")
        choose_btn.setToolTip("Pick a Parrot.py folder the scan didn't find")
        choose_btn.clicked.connect(self._on_choose)
        row.addWidget(choose_btn)
        row.addStretch()
        self.status_label = QLabel("Scanning the usual folders...")
        self.status_label.setStyleSheet(f"color: {t['text_dim']};")
        row.addWidget(self.status_label)
        self.import_btn = QPushButton("Import")
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._on_import)
        row.addWidget(self.import_btn)
        layout.addLayout(row)

        self._scanner = _ScanWorker(self)
        self._scanner.found.connect(self._on_scan_done)
        self._scanner.start()

    def _add_candidate(self, setup, select=False):
        text = (f"{setup['label']}    "
                f"{setup['sounds']} sounds, {setup['models']} models")
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, setup["data_dir"])
        self.list.addItem(item)
        if select:
            self.list.setCurrentItem(item)

    def _on_scan_done(self, setups):
        existing = {self.list.item(i).data(Qt.ItemDataRole.UserRole)
                    for i in range(self.list.count())}
        for setup in setups:
            if setup["data_dir"] not in existing:
                self._add_candidate(setup)
        self.status_label.setText(
            "" if self.list.count() else
            "Nothing found. Choose the folder yourself.")
        self._update_buttons()

    def _on_choose(self):
        path = QFileDialog.getExistingDirectory(self, "Parrot.py folder")
        if not path:
            return
        data_dir = profiles.resolve_setup_dir(path)
        if data_dir is None:
            QMessageBox.warning(
                self, "Not a Parrot.py setup",
                "No recordings there. Pick the folder that holds "
                "data/recordings, or the data folder itself.")
            return
        sounds, models = profiles.stats(data_dir)
        home = os.path.expanduser("~")
        self._add_candidate({
            "data_dir": os.path.abspath(data_dir),
            "label": data_dir.replace(home, "~", 1),
            "sounds": sounds, "models": models}, select=True)

    def _update_buttons(self):
        self.import_btn.setEnabled(
            self._worker is None and self.list.currentItem() is not None)

    def _on_import(self):
        item = self.list.currentItem()
        if item is None or self._worker is not None:
            return
        data_dir = item.data(Qt.ItemDataRole.UserRole)
        # the checkout folder usually carries the meaningful name
        default = os.path.basename(os.path.dirname(data_dir)) or "imported"
        name, ok = QInputDialog.getText(
            self, "Import as profile", "Profile name:", text=default)
        name = name.strip() if ok and name.strip() else None
        if not name:
            return
        self.status_label.setText("Copying...")
        self._worker = _OpWorker(
            lambda: profiles.duplicate(data_dir, name), self)
        self._worker.done.connect(
            lambda error: self._on_import_done(name, error))
        self._update_buttons()
        self._worker.start()

    def _on_import_done(self, name, error):
        self._worker = None
        self.status_label.setText("")
        if error:
            QMessageBox.warning(self, "Import failed", error)
            self._update_buttons()
            return
        self.imported = name
        answer = QMessageBox.question(
            self, "Imported",
            f"{name} is ready. Switch to it now? Parrot restarts, "
            "about a second.")
        if answer == QMessageBox.StandardButton.Yes:
            profiles.spawn_into(name)
            QTimer.singleShot(0, QApplication.instance().quit)
        self.accept()


class ProfilesDialog(QDialog):
    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self._worker = None
        self.setWindowTitle("Profiles")
        self.resize(720, 460)
        self._setup_ui()
        self._refresh()

    def _setup_ui(self):
        t = theme.colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        note = QLabel(
            "Each profile is a complete separate setup: sounds, models, notes, "
            "settings. Use one to try the app as a new user or to keep setups "
            "apart. Switching restarts the app, about a second.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {t['text_dim']};")
        layout.addWidget(note)

        self.list = QListWidget()
        self.list.currentItemChanged.connect(lambda *_: self._update_buttons())
        layout.addWidget(self.list, stretch=1)

        actions = QHBoxLayout()
        self.switch_btn = QPushButton("Switch")
        self.switch_btn.setToolTip("Restart the app as this profile")
        self.switch_btn.clicked.connect(self._on_switch)
        actions.addWidget(self.switch_btn)

        self.new_btn = QPushButton("New empty")
        self.new_btn.setToolTip("A profile with nothing in it yet, like a first launch")
        self.new_btn.clicked.connect(self._on_new)
        actions.addWidget(self.new_btn)

        self.dup_btn = QPushButton("Duplicate")
        self.dup_btn.setToolTip("A new profile copied from the selected one")
        self.dup_btn.clicked.connect(self._on_duplicate)
        actions.addWidget(self.dup_btn)

        self.import_btn = QPushButton("Import...")
        self.import_btn.setToolTip("Copy in the setup of another Parrot.py on this machine")
        self.import_btn.clicked.connect(self._on_import)
        actions.addWidget(self.import_btn)

        self.freeze_btn = QPushButton("Freeze")
        self.freeze_btn.setToolTip("Save the profile as it is now; Reset returns here")
        self.freeze_btn.clicked.connect(self._on_freeze)
        actions.addWidget(self.freeze_btn)

        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setToolTip("Back to how the profile was when last frozen")
        self.reset_btn.clicked.connect(self._on_reset)
        actions.addWidget(self.reset_btn)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self._on_delete)
        actions.addWidget(self.delete_btn)

        self.open_btn = QPushButton("Open folder")
        self.open_btn.clicked.connect(self._on_open_folder)
        actions.addWidget(self.open_btn)

        actions.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {t['text_dim']};")
        actions.addWidget(self.status_label)
        layout.addLayout(actions)

        if profiles.debug_enabled():
            debug_group = QGroupBox("Debug")
            debug_form = QHBoxLayout(debug_group)
            debug_form.addWidget(QLabel("Talon for this profile:"))
            self.talon_combo = QComboBox()
            self.talon_combo.addItem("As installed", "real")
            self.talon_combo.addItem("Pretend not installed", "none")
            self.talon_combo.activated.connect(self._on_talon_sim_changed)
            debug_form.addWidget(self.talon_combo)
            debug_form.addStretch()
            layout.addWidget(debug_group)
        else:
            self.talon_combo = None

    # ---- list -----------------------------------------------------------

    def _refresh(self):
        current = profiles.current_profile()
        selected = self._selected()
        self.list.clear()
        entries = [(None, profiles.MAIN_DATA_DIR)] + [
            (n, profiles.profile_data_dir(n)) for n in profiles.list_profiles()]
        for name, data_dir in entries:
            sounds, models = profiles.stats(data_dir)
            label = name if name is not None else "Main"
            text = f"{label}    {sounds} sounds, {models} models"
            if name == current:
                text += "    (current)"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list.addItem(item)
            if name == selected or (selected is None and name == current):
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._update_buttons()

    def _selected(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _update_buttons(self):
        name = self._selected()
        current = profiles.current_profile()
        busy = self._worker is not None
        is_profile = name is not None
        self.switch_btn.setEnabled(not busy and name != current)
        self.new_btn.setEnabled(not busy)
        self.dup_btn.setEnabled(not busy)
        self.import_btn.setEnabled(not busy)
        self.freeze_btn.setEnabled(not busy and is_profile)
        self.reset_btn.setEnabled(not busy and is_profile)
        self.delete_btn.setEnabled(not busy and is_profile and name != current)
        self.open_btn.setEnabled(self.list.currentItem() is not None)
        if self.talon_combo is not None:
            self.talon_combo.setEnabled(not busy and is_profile)
            if is_profile:
                sim = profiles.read_meta(name).get("talon", "real")
                idx = self.talon_combo.findData(sim)
                self.talon_combo.setCurrentIndex(idx if idx >= 0 else 0)

    # ---- operations -----------------------------------------------------

    def _run(self, fn, busy_text):
        self.status_label.setText(busy_text)
        self._worker = _OpWorker(fn, self)
        self._worker.done.connect(self._on_op_done)
        self._update_buttons()
        self._worker.start()

    def _on_op_done(self, error):
        self._worker = None
        self.status_label.setText("")
        if error:
            QMessageBox.warning(self, "Profile operation failed", error)
        self._refresh()

    def _ask_name(self, title):
        name, ok = QInputDialog.getText(self, title, "Name:")
        return name.strip() if ok and name.strip() else None

    def _data_dir_of(self, name):
        return (profiles.MAIN_DATA_DIR if name is None
                else profiles.profile_data_dir(name))

    def _on_new(self):
        name = self._ask_name("New empty profile")
        if name:
            self._run(lambda: profiles.create_empty(name), "Creating...")

    def _on_duplicate(self):
        src = self._selected()
        src_label = "Main" if src is None else src
        name = self._ask_name(f"Duplicate {src_label}")
        if name:
            talon = ("real" if src is None
                     else profiles.read_meta(src).get("talon", "real"))
            src_dir = self._data_dir_of(src)
            self._run(lambda: profiles.duplicate(src_dir, name, talon),
                      "Copying...")

    def _on_import(self):
        dialog = ImportSetupDialog(self)
        dialog.exec()
        self._refresh()

    def _on_freeze(self):
        name = self._selected()
        if name is not None:
            self._run(lambda: profiles.freeze(name), "Freezing...")

    def _on_reset(self):
        name = self._selected()
        if name is None:
            return
        answer = QMessageBox.question(
            self, "Reset profile",
            f"Put {name} back to its frozen baseline? Everything recorded or "
            "trained since then is deleted.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        if name == profiles.current_profile():
            # The running app has this profile's files open in caches; restart
            # into the freshly reset copy rather than serving stale state.
            self._run(lambda: (profiles.reset(name), profiles.spawn_into(name)),
                      "Resetting...")
            self._worker.done.connect(self._quit_if_ok)
        else:
            self._run(lambda: profiles.reset(name), "Resetting...")

    def _on_delete(self):
        name = self._selected()
        if name is None:
            return
        answer = QMessageBox.question(
            self, "Delete profile",
            f"Delete {name} and everything in it?")
        if answer == QMessageBox.StandardButton.Yes:
            self._run(lambda: profiles.delete(name), "Deleting...")

    def _on_switch(self):
        name = self._selected()
        profiles.spawn_into(name)
        QTimer.singleShot(0, QApplication.instance().quit)

    def _quit_if_ok(self, error):
        if not error:
            QTimer.singleShot(0, QApplication.instance().quit)

    def _on_open_folder(self):
        target = self._data_dir_of(self._selected())
        try:
            library_ops.open_in_file_manager(os.path.abspath(target))
        except library_ops.LibraryOpError as exc:
            QMessageBox.warning(self, "Couldn't open folder", str(exc))

    def _on_talon_sim_changed(self, _index):
        name = self._selected()
        if name is None or self.talon_combo is None:
            return
        meta = profiles.read_meta(name)
        meta["talon"] = self.talon_combo.currentData()
        profiles.write_meta(name, meta)
        if name == profiles.current_profile():
            self.status_label.setText("Applies the next time you switch in")
