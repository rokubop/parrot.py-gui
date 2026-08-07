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
from gui.content import program as program_content


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


def _ellipsis_left(text, limit):
    """Keep the tail of a path; the deep end is the informative end."""
    return text if len(text) <= limit else "..." + text[-(limit - 3):]


class _ScanWorker(QThread):
    """Walks folders the user asked for. Streams hits so the list fills as
    it goes, and stops the moment the dialog asks it to."""
    hit = pyqtSignal(dict)
    looking_at = pyqtSignal(str)
    done_scanning = pyqtSignal(bool)  # True if it ran to the end

    def __init__(self, roots, parent=None):
        super().__init__(parent)
        self._roots = roots
        self._stop = False
        self._seen = 0

    def stop(self):
        self._stop = True

    def run(self):
        def on_progress(directory):
            self._seen += 1
            if self._seen % 300 == 0:  # a whole drive is ~100k folders
                self.looking_at.emit(directory)

        try:
            profiles.scan(self._roots, on_hit=self.hit.emit,
                          should_cancel=lambda: self._stop,
                          on_progress=on_progress)
        except Exception:
            pass
        self.done_scanning.emit(not self._stop)


class ImportSetupDialog(QDialog):
    """Bring an outside Parrot.py setup in as a profile, by copy.

    A checkout can be anywhere and nothing records where it went, so
    pointing at the folder is the main action and no search runs unasked.
    The source folder is only ever read.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bring in an existing setup")
        self.resize(660, 470)
        self._worker = None
        self._folder_scan = None
        self.imported = None  # profile name on success

        t = theme.colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        note = QLabel(
            "Copy sounds and models of an existing install in as a profile. "
            "Original folder is not changed.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {t['text_dim']};")
        layout.addWidget(note)

        choose_btn = QPushButton("Choose your parrot.py folder...")
        choose_btn.setDefault(True)
        choose_btn.clicked.connect(self._on_choose)
        layout.addWidget(choose_btn)

        hint = QLabel("The parrot.py folder itself, wherever you keep it.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {t['text_dim']};")
        layout.addWidget(hint)

        self.found_label = QLabel("Not sure where it is? Search for it:")
        self.found_label.setStyleSheet(f"color: {t['text_dim']};")
        layout.addWidget(self.found_label, alignment=Qt.AlignmentFlag.AlignLeft)

        scan_row = QHBoxLayout()
        self.home_btn = QPushButton("Search my home folder")
        self.home_btn.setToolTip(os.path.expanduser("~"))
        self.home_btn.clicked.connect(self._on_scan_home)
        scan_row.addWidget(self.home_btn)
        self.scan_btn = QPushButton("Search another folder...")
        self.scan_btn.setToolTip(
            "Any folder or drive. Nothing is searched until you pick one.")
        self.scan_btn.clicked.connect(self._on_scan_folder)
        scan_row.addWidget(self.scan_btn)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self._on_stop_scan)
        self.stop_btn.setVisible(False)
        scan_row.addWidget(self.stop_btn)
        self.scan_status = QLabel("")
        self.scan_status.setStyleSheet(f"color: {t['text_dim']};")
        scan_row.addWidget(self.scan_status, stretch=1)
        layout.addLayout(scan_row)

        self.list = QListWidget()
        self.list.currentItemChanged.connect(lambda *_: self._update_buttons())
        self.list.itemDoubleClicked.connect(lambda _i: self._on_import())
        layout.addWidget(self.list, stretch=1)

        row = QHBoxLayout()
        row.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {t['text_dim']};")
        row.addWidget(self.status_label)
        self.import_btn = QPushButton("Import")
        self.import_btn.setToolTip(
            "Copies the sounds and models into a new profile here. "
            "The folder you picked is not touched.")
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._on_import)
        row.addWidget(self.import_btn)
        layout.addLayout(row)

    def _add_candidate(self, setup, select=False):
        text = (f"{setup['label']}    "
                f"{setup['sounds']} sounds, {setup['models']} models")
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, setup)
        self.list.addItem(item)
        if select:
            self.list.setCurrentItem(item)

    def _known_dirs(self):
        return {self.list.item(i).data(Qt.ItemDataRole.UserRole)["data_dir"]
                for i in range(self.list.count())}

    def _on_choose(self):
        path = QFileDialog.getExistingDirectory(self, "Your parrot.py folder")
        if not path:
            return
        setup = profiles.describe_setup(path)
        if setup is None:
            QMessageBox.warning(
                self, "Not a Parrot.py setup",
                "No recordings in there. Pick your parrot.py folder, the one "
                "with a data folder inside it.")
            return
        for i in range(self.list.count()):
            known = self.list.item(i).data(Qt.ItemDataRole.UserRole)
            if known["data_dir"] == setup["data_dir"]:
                self.list.setCurrentRow(i)
                return
        self._add_candidate(setup, select=True)

    # ---- searching, only where the user asked -----------------------------

    def _on_scan_home(self):
        self._start_scan(profiles.home_roots(), "your home folder")

    def _on_scan_folder(self):
        root = QFileDialog.getExistingDirectory(
            self, "Folder or drive to search")
        if root:
            self._start_scan([root], root)

    def _start_scan(self, roots, label):
        self.found_label.setText(f"Searching {label}. This can take a while.")
        self._folder_scan = _ScanWorker(roots, self)
        self._folder_scan.hit.connect(self._on_folder_hit)
        self._folder_scan.looking_at.connect(
            lambda d: self.scan_status.setText(_ellipsis_left(d, 52)))
        self._folder_scan.done_scanning.connect(
            lambda finished: self._on_folder_scan_done(label, finished))
        self.home_btn.setVisible(False)
        self.scan_btn.setVisible(False)
        self.stop_btn.setVisible(True)
        self._folder_scan.start()

    def _on_folder_hit(self, setup):
        if setup["data_dir"] not in self._known_dirs():
            self._add_candidate(setup, select=self.list.count() == 0)

    def _on_stop_scan(self):
        if self._folder_scan is not None:
            self._folder_scan.stop()
        self.stop_btn.setEnabled(False)

    def _on_folder_scan_done(self, label, finished):
        self._folder_scan = None
        self.home_btn.setVisible(True)
        self.scan_btn.setVisible(True)
        self.stop_btn.setVisible(False)
        self.stop_btn.setEnabled(True)
        self.scan_status.setText("")
        count = self.list.count()
        if count:
            self.found_label.setText(
                f"{count} setup{'s' if count != 1 else ''} found. Pick one:")
        elif finished:
            self.found_label.setText(
                f"No Parrot.py setup in {label}. Choose the folder above.")
        else:
            self.found_label.setText("Search stopped.")
        self._update_buttons()

    def done(self, code):
        # the thread must not outlive the dialog it reports into
        if self._folder_scan is not None:
            self._folder_scan.stop()
            self._folder_scan.wait(3000)
            self._folder_scan = None
        super().done(code)

    def _update_buttons(self):
        self.import_btn.setEnabled(
            self._worker is None and self.list.currentItem() is not None)

    def _on_import(self):
        item = self.list.currentItem()
        if item is None or self._worker is not None:
            return
        setup = item.data(Qt.ItemDataRole.UserRole)
        data_dir = setup["data_dir"]

        # Nothing here yet: this is their setup, not a second one alongside it.
        if profiles.current_profile() is None and profiles.main_is_empty():
            answer = QMessageBox.question(
                self, "Bring it in",
                f"Copy {setup['sounds']} sounds and {setup['models']} models "
                "into this setup?\n\nParrot restarts afterwards.")
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.status_label.setText("Copying...")
            self._worker = _OpWorker(
                lambda: profiles.import_into_main(data_dir), self)
            self._worker.done.connect(self._on_main_import_done)
            self._update_buttons()
            self._worker.start()
            return

        default = os.path.basename(setup["root"]) or "imported"
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

    def _on_main_import_done(self, error):
        self._worker = None
        self.status_label.setText("")
        if error:
            QMessageBox.warning(self, "Import failed", error)
            self._update_buttons()
            return
        profiles.spawn_into(None)
        QTimer.singleShot(0, QApplication.instance().quit)
        self.accept()

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
            program_content.PROFILE_SHORT
            + " Use one to try the app as a new user, or to keep setups apart.")
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
            test_btn = QPushButton("Create test profiles")
            test_btn.setToolTip(
                "One profile per app state: empty, 2 sounds, 10 sounds, "
                "model without Talon, fully set up with a mock Talon")
            test_btn.clicked.connect(self._on_create_test_profiles)
            debug_form.addWidget(test_btn)
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
                while self.talon_combo.count() > 2:
                    self.talon_combo.removeItem(2)
                idx = self.talon_combo.findData(sim)
                if idx < 0:  # a path: the profile bundles a mock Talon home
                    self.talon_combo.addItem("Mock Talon (bundled)", sim)
                    idx = 2
                self.talon_combo.setCurrentIndex(idx)

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

    def _on_create_test_profiles(self):
        from gui.services import mock_states
        result = {}

        def build():
            result["created"], result["notes"] = \
                mock_states.create_test_profiles()

        self.status_label.setText("Building test profiles...")
        self._worker = _OpWorker(build, self)
        self._worker.done.connect(
            lambda error: self._on_test_profiles_done(error, result))
        self._update_buttons()
        self._worker.start()

    def _on_test_profiles_done(self, error, result):
        self._worker = None
        self.status_label.setText("")
        if error:
            QMessageBox.warning(self, "Test profiles failed", error)
        else:
            notes = result.get("notes") or []
            created = result.get("created") or []
            summary = (f"Created {', '.join(created)}." if created
                       else "Nothing new to create.")
            if notes:
                summary += "\n\n" + "\n".join(notes)
            QMessageBox.information(self, "Test profiles", summary)
        self._refresh()

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
