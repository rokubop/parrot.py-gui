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
    QListWidgetItem, QGroupBox, QComboBox, QMessageBox,
    QApplication, QFileDialog, QWidget, QRadioButton, QLineEdit
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


def _counts(sounds, models):
    """What a data tree holds, worded the same in every list that shows one."""
    return (f"{sounds} sound{'' if sounds == 1 else 's'}, "
            f"{models} model{'' if models == 1 else 's'}")


def _name_problem(name):
    """Why this profile name will not work, or None.

    Asked per keystroke so a name is never a click that fails. Blank is not
    a complaint, it is just not finished, so it reads as None.
    """
    name = (name or "").strip()
    if not name:
        return None
    try:
        profiles.check_new_name(name)
    except profiles.ProfileError as exc:
        return str(exc)
    return None


def _suggested_name(setup):
    """A profile name from the folder it came from. Every one of them is
    called parrot.py, so that name suggests nothing and is not offered."""
    name = os.path.basename(setup["root"]).strip()
    if not name or name.lower() in ("parrot.py", "parrot", "data"):
        return "Imported"
    return name


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
    """Bring an outside Parrot.py setup in, by copy.

    A checkout can be anywhere and nothing records where it went, so
    pointing at the folder is the main action and no search runs unasked.
    The source folder is only ever read.

    Two picks: what to copy, and where it lands. The destination is a real
    choice because the app already sends someone here from inside a profile
    they just made, and an import that can only ever make another profile
    is a dead end there. It hides itself when there is nothing to choose.

    pick_only borrows the top half as a folder picker: NewProfileDialog
    needs the same "choose or search for it" machinery and should not own a
    second copy of it.
    """

    def __init__(self, parent=None, pick_only=False):
        super().__init__(parent)
        self._pick_only = pick_only
        self.setWindowTitle("Find an existing setup" if pick_only
                            else "Bring in an existing setup")
        self.resize(660, 500)
        self._worker = None
        self._folder_scan = None
        self._dest_labels = {}  # data dir -> the name shown for it
        self.imported = None  # destination name on success
        self.picked = None  # the setup chosen, when pick_only

        t = theme.colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        note = QLabel(
            "Point at an install you already have. Nothing in it is changed."
            if pick_only else
            "Copy the sounds and models of an existing install in. "
            "The original folder is not changed.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {t['text_dim']};")
        layout.addWidget(note)

        choose_btn = QPushButton("Choose your parrot.py folder...")
        choose_btn.setDefault(True)
        choose_btn.clicked.connect(self._on_choose)
        layout.addWidget(choose_btn)

        hint = QLabel("The parrot.py folder itself, or the data folder in it.")
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
        self.dest_widget = QWidget()
        dest_row = QHBoxLayout(self.dest_widget)
        dest_row.setContentsMargins(0, 0, 0, 0)
        dest_row.addWidget(QLabel("Copy into:"))
        self.dest_combo = QComboBox()
        self.dest_combo.setToolTip(
            "Where the copy lands. Whatever is already there is kept.")
        dest_row.addWidget(self.dest_combo)
        self.new_name_edit = QLineEdit()
        self.new_name_edit.setPlaceholderText("call it")
        self.new_name_edit.setMaximumWidth(150)
        self.new_name_edit.setVisible(False)
        self.new_name_edit.textChanged.connect(lambda *_: self._update_buttons())
        dest_row.addWidget(self.new_name_edit)
        self.dest_combo.currentIndexChanged.connect(
            lambda *_: self._on_dest_changed())
        row.addWidget(self.dest_widget)
        row.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {t['text_dim']};")
        row.addWidget(self.status_label)
        self.import_btn = QPushButton("Use this folder" if pick_only
                                      else "Import")
        self.import_btn.setToolTip(
            "Nothing is copied yet; this dialog closes with it chosen."
            if pick_only else
            "Copies the sounds and models in. "
            "The folder you picked is not touched.")
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._on_import)
        row.addWidget(self.import_btn)
        layout.addLayout(row)

        self._fill_destinations()

    # ---- where the copy lands ---------------------------------------------

    def _fill_destinations(self):
        """Every data tree that can take the copy, plus a new profile.

        Sorted the way the Profiles list is, so the two read alike. The tree
        the app is running on is marked, and is the default when it is still
        empty: someone who just made a profile and came here means this one.
        A root with content in it defaults to a new profile instead, so the
        safe answer stays the one you get by pressing Enter.

        The whole row hides when there is nothing to choose between, which
        is every first launch. "New profile" names a concept that person has
        not met, and offering it as their only alternative teaches it at the
        worst moment.
        """
        here = os.path.abspath(profiles.current_data_dir())
        entries = [("Main", os.path.abspath(profiles.MAIN_DATA_DIR))]
        entries += [(n, os.path.abspath(profiles.profile_data_dir(n)))
                    for n in profiles.list_profiles()]
        if all(d != here for _label, d in entries):
            # PARROT_DATA_DIR can point at a tree that is neither. Name it
            # after the folder holding it, since every one of them ends "data".
            named = os.path.basename(here)
            if named in ("", "data"):
                named = os.path.basename(os.path.dirname(here)) or "Here"
            entries.insert(0, (named, here))

        default = None
        for index, (label, data_dir) in enumerate(entries):
            self._dest_labels[data_dir] = label
            sounds, models = profiles.stats(data_dir)
            has = _counts(sounds, models) if sounds or models else "empty"
            text = f"{label} ({has})"
            if data_dir == here:
                text += "    (current)"
                if not (sounds or models):
                    default = index
            self.dest_combo.addItem(text, data_dir)
            self.dest_combo.setItemData(index, data_dir,
                                        Qt.ItemDataRole.ToolTipRole)
        self.dest_combo.addItem("New profile...", None)
        self.dest_combo.setCurrentIndex(
            self.dest_combo.count() - 1 if default is None else default)
        # one tree, empty, and it is the one we are on: no choice to offer
        only_here = len(entries) == 1 and default == 0
        self.dest_widget.setVisible(not (self._pick_only or only_here))

    def _is_here(self, data_dir):
        return data_dir == os.path.abspath(profiles.current_data_dir())

    def _on_dest_changed(self):
        making_new = self.dest_combo.currentData() is None
        self.new_name_edit.setVisible(making_new)
        self._suggest_name()
        self._update_buttons()

    def _suggest_name(self):
        if (self.dest_combo.currentData() is not None
                or self.new_name_edit.text().strip()):
            return
        item = self.list.currentItem()
        if item is not None:
            self.new_name_edit.setText(
                _suggested_name(item.data(Qt.ItemDataRole.UserRole)))

    def _add_candidate(self, setup, select=False):
        text = f"{setup['label']}    {_counts(setup['sounds'], setup['models'])}"
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, setup)
        self.list.addItem(item)
        if select:
            self.list.setCurrentItem(item)
            self._suggest_name()

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
        busy = self._worker is not None
        making_new = (not self._pick_only
                      and self.dest_combo.currentData() is None)
        name = self.new_name_edit.text().strip()
        problem = _name_problem(name) if making_new else None
        if not busy:
            self.status_label.setText(problem or "")
        self.import_btn.setEnabled(
            not busy
            and self.list.currentItem() is not None
            and problem is None
            and (bool(name) or not making_new))
        self.dest_widget.setEnabled(not busy)

    def _on_import(self):
        item = self.list.currentItem()
        if item is None or self._worker is not None:
            return
        setup = item.data(Qt.ItemDataRole.UserRole)
        if self._pick_only:
            self.picked = setup
            self.accept()
            return
        source = setup["data_dir"]
        dest_dir = self.dest_combo.currentData()

        if dest_dir is None:
            self._import_as_new_profile(setup)
            return

        label = self._dest_labels[dest_dir]
        sounds, models = profiles.stats(dest_dir)
        lines = [f"Copy {_counts(setup['sounds'], setup['models'])} "
                 f"into {label}?"]
        if sounds or models:
            lines.append(f"{label} keeps what it has. A sound or model of the "
                         "same name is replaced.")
        if self._is_here(dest_dir):
            lines.append("Parrot restarts afterwards.")
        answer = QMessageBox.question(self, "Bring it in", "\n\n".join(lines))
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start(lambda: profiles.import_into(dest_dir, source),
                    label, dest_dir)

    def _import_as_new_profile(self, setup):
        source = setup["data_dir"]
        name = self.new_name_edit.text().strip()
        self._start(lambda: profiles.duplicate(source, name), name,
                    os.path.abspath(profiles.profile_data_dir(name)))

    def _start(self, fn, label, dest_dir):
        self.status_label.setText("Copying...")
        self._worker = _OpWorker(fn, self)
        self._worker.done.connect(
            lambda error: self._on_import_done(label, dest_dir, error))
        self._update_buttons()
        self._worker.start()

    def _on_import_done(self, label, dest_dir, error):
        self._worker = None
        self.status_label.setText("")
        if error:
            QMessageBox.warning(self, "Import failed", error)
            self._update_buttons()
            return
        self.imported = label
        if self._is_here(dest_dir):
            # this process has the tree we just wrote into open in its caches
            self._relaunch_into(dest_dir)
            self.accept()
            return
        answer = QMessageBox.question(
            self, "Imported",
            f"{label} is ready. Switch to it now? Parrot restarts, "
            "about a second.")
        if answer == QMessageBox.StandardButton.Yes:
            self._relaunch_into(dest_dir)
        self.accept()

    def _relaunch_into(self, data_dir):
        """Restart on the tree just imported into.

        spawn_into() knows Main and profiles by name. A root that is neither
        got here through PARROT_DATA_DIR, so the env it already has is the
        only thing that points back at it.
        """
        name = profiles.profile_name_of(data_dir)
        if name is None and data_dir != os.path.abspath(profiles.MAIN_DATA_DIR):
            profiles.relaunch()
        else:
            profiles.spawn_into(name)
        QTimer.singleShot(0, QApplication.instance().quit)


class _NameDialog(QDialog):
    """One name field that says why a name will not work as it is typed."""

    def __init__(self, parent, title, action, initial=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(360)
        t = theme.colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        row = QHBoxLayout()
        row.addWidget(QLabel("Name"))
        self.edit = QLineEdit(initial)
        self.edit.textChanged.connect(lambda *_: self._update())
        row.addWidget(self.edit, stretch=1)
        layout.addLayout(row)

        self.problem_label = QLabel("")
        self.problem_label.setStyleSheet(f"color: {t['text_dim']};")
        layout.addWidget(self.problem_label)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        self.ok_btn = QPushButton(action)
        self.ok_btn.setDefault(True)
        self.ok_btn.clicked.connect(self.accept)
        buttons.addWidget(self.ok_btn)
        layout.addLayout(buttons)

        self.edit.selectAll()
        self._update()

    def _update(self):
        problem = _name_problem(self.edit.text())
        self.problem_label.setText(problem or "")
        self.ok_btn.setEnabled(
            bool(self.edit.text().strip()) and problem is None)

    def value(self):
        return self.edit.text().strip()


class NewProfileDialog(QDialog):
    """Name it, and say what it starts from.

    One dialog in place of three buttons (New empty, Duplicate, Import),
    which were one act with three sources. Splitting them across the row
    meant guessing which one hid "my old install", and the answer was the
    one word that did not sound like a source.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New profile")
        self.resize(560, 320)
        self._worker = None
        self._setup = None  # what the folder source resolved to
        self.created = None  # profile name on success

        t = theme.colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name"))
        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(lambda *_: self._update_buttons())
        name_row.addWidget(self.name_edit, stretch=1)
        layout.addLayout(name_row)

        layout.addSpacing(4)
        layout.addWidget(QLabel("Start from"))

        empty_row = QHBoxLayout()
        self.empty_radio = QRadioButton("Empty")
        self.empty_radio.setChecked(True)
        self.empty_radio.toggled.connect(lambda *_: self._update_buttons())
        empty_row.addWidget(self.empty_radio)
        empty_hint = QLabel("like a first launch")
        empty_hint.setStyleSheet(f"color: {t['text_dim']};")
        empty_row.addWidget(empty_hint)
        empty_row.addStretch()
        layout.addLayout(empty_row)

        copy_row = QHBoxLayout()
        self.copy_radio = QRadioButton("A copy of")
        self.copy_radio.toggled.connect(lambda *_: self._update_buttons())
        copy_row.addWidget(self.copy_radio)
        self.copy_combo = QComboBox()
        for label, data_dir in self._sources():
            sounds, models = profiles.stats(data_dir)
            has = _counts(sounds, models) if sounds or models else "empty"
            self.copy_combo.addItem(f"{label} ({has})", data_dir)
        # touching the combo is the same as saying you meant this row
        self.copy_combo.activated.connect(
            lambda *_: self.copy_radio.setChecked(True))
        copy_row.addWidget(self.copy_combo)
        copy_row.addStretch()
        layout.addLayout(copy_row)

        self.folder_radio = QRadioButton("A folder on this machine")
        self.folder_radio.toggled.connect(lambda *_: self._update_buttons())
        layout.addWidget(self.folder_radio)

        folder_row = QHBoxLayout()
        folder_row.addSpacing(26)
        self.choose_btn = QPushButton("Choose...")
        self.choose_btn.clicked.connect(self._on_choose)
        folder_row.addWidget(self.choose_btn)
        self.folder_label = QLabel("your parrot.py folder, or the data in it")
        self.folder_label.setStyleSheet(f"color: {t['text_dim']};")
        folder_row.addWidget(self.folder_label, stretch=1)
        layout.addLayout(folder_row)

        layout.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {t['text_dim']};")
        buttons.addWidget(self.status_label)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        self.create_btn = QPushButton("Create")
        self.create_btn.setDefault(True)
        self.create_btn.clicked.connect(self._on_create)
        buttons.addWidget(self.create_btn)
        layout.addLayout(buttons)

        self._update_buttons()

    def _sources(self):
        entries = [("Main", profiles.MAIN_DATA_DIR)]
        entries += [(n, profiles.profile_data_dir(n))
                    for n in profiles.list_profiles()]
        return entries

    def _update_buttons(self):
        busy = self._worker is not None
        name = self.name_edit.text().strip()
        problem = _name_problem(name)
        if not busy:
            self.status_label.setText(problem or "")
        ready = bool(name) and problem is None
        if self.folder_radio.isChecked() and self._setup is None:
            ready = False
        self.create_btn.setEnabled(ready and not busy)
        self.choose_btn.setEnabled(not busy)
        self.name_edit.setEnabled(not busy)

    def _on_choose(self):
        dialog = ImportSetupDialog(self, pick_only=True)
        dialog.exec()
        if dialog.picked is not None:
            self._setup = dialog.picked
            self.folder_label.setText(
                f"{self._setup['label']}    "
                f"{_counts(self._setup['sounds'], self._setup['models'])}")
            self.folder_radio.setChecked(True)
            if not self.name_edit.text().strip():
                self.name_edit.setText(_suggested_name(self._setup))
        self._update_buttons()

    def _on_create(self):
        name = self.name_edit.text().strip()
        if not name or self._worker is not None:
            return
        if self.copy_radio.isChecked():
            source = self.copy_combo.currentData()
            src_name = profiles.profile_name_of(source)
            talon = ("real" if src_name is None
                     else profiles.read_meta(src_name).get("talon", "real"))
            fn = lambda: profiles.duplicate(source, name, talon)
        elif self.folder_radio.isChecked():
            source = self._setup["data_dir"]
            fn = lambda: profiles.duplicate(source, name)
        else:
            fn = lambda: profiles.create_empty(name)
        self.status_label.setText("Creating...")
        self._worker = _OpWorker(fn, self)
        self._worker.done.connect(lambda error: self._on_created(name, error))
        self._update_buttons()
        self._worker.start()

    def _on_created(self, name, error):
        self._worker = None
        self.status_label.setText("")
        if error:
            QMessageBox.warning(self, "Could not create it", error)
            self._update_buttons()
            return
        self.created = name
        answer = QMessageBox.question(
            self, "Created",
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

        self.new_btn = QPushButton("New profile...")
        self.new_btn.setToolTip(
            "Empty, a copy of one here, or a parrot.py folder on this machine")
        self.new_btn.clicked.connect(self._on_new)
        actions.addWidget(self.new_btn)

        self.import_btn = QPushButton("Import into...")
        self.import_btn.setToolTip(
            "Add another Parrot.py's sounds and models to a profile that "
            "already exists")
        self.import_btn.clicked.connect(self._on_import)
        actions.addWidget(self.import_btn)

        self.rename_btn = QPushButton("Rename")
        self.rename_btn.clicked.connect(self._on_rename)
        actions.addWidget(self.rename_btn)

        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setToolTip("Back to how this profile started")
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
            text = f"{label}    {_counts(sounds, models)}"
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
        self.import_btn.setEnabled(not busy)
        self.rename_btn.setEnabled(not busy and is_profile)
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

    def _data_dir_of(self, name):
        return (profiles.MAIN_DATA_DIR if name is None
                else profiles.profile_data_dir(name))

    def _on_new(self):
        NewProfileDialog(self).exec()
        self._refresh()

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

    def _on_rename(self):
        name = self._selected()
        if name is None:
            return
        dialog = _NameDialog(self, f"Rename {name}", "Rename", name)
        if not dialog.exec() or dialog.value() == name:
            return
        new_name = dialog.value()
        if name == profiles.current_profile():
            # DATA_DIR still names the old folder in this process
            self._run(lambda: (profiles.rename(name, new_name),
                               profiles.spawn_into(new_name)), "Renaming...")
            self._worker.done.connect(self._quit_if_ok)
        else:
            self._run(lambda: profiles.rename(name, new_name), "Renaming...")

    def _on_reset(self):
        name = self._selected()
        if name is None:
            return
        answer = QMessageBox.question(
            self, "Reset profile",
            f"Put {name} back to how it started? Everything recorded or "
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
