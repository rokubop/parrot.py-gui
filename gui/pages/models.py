"""Models tab - the library of trained models.

Shaped like the Sounds tab: list on the left, header panel + details on the
right. Training itself is a sub-view (train_view.py).

Net count is listed alongside date and sounds because every net runs on every
frame and the scores are averaged (TinyAudioNetEnsemble.forward), so it is
part of what the model costs to run, not a spent training decision.
"""
import html
import os
import threading
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QSplitter, QFrame, QPushButton, QMessageBox, QApplication,
    QListWidget, QListWidgetItem, QLineEdit, QInputDialog, QDialog, QMenu
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from config.config import BACKGROUND_LABEL, CLASSIFIER_FOLDER
from gui.services import balance, library_ops
from gui import components, theme
from gui.formatters import trained_when, file_size_text, percent_span
from gui.widgets.confirm_dialog import confirm_destructive
from gui.widgets import help_dialog
from gui.workers.combine_worker import CombineWorker
from lib import models

MODEL_COLUMN, TRAINED_COLUMN, SOUNDS_COLUMN, NETS_COLUMN = 0, 1, 2, 3
SOUND_COLUMN, ACCURACY_COLUMN, NOTE_COLUMN = 0, 1, 2


class ModelsPage(QWidget):
    """
    ┌ model_list ──────────────────────┐┌ model_header ───────────────────────────────────┐
    │                                  ││ model_title                                     │
    │                                  ││ model_stats                                     │
    │                                  ││ stale_label                                     │
    │                                  ││ test actions, then management actions           │
    │                                  │├ details ────────────────────────────────────────┤
    │                                  ││ ┌ sound_tree ────────────────┐┌ facts ─────────┐│
    │                                  ││ │                            ││                ││
    │                                  ││ │                            ││                ││
    │                                  ││ └────────────────────────────┘│                ││
    │                                  ││ unused_label                  └────────────────┘│
    ├ train_btn ───────────────────────┤│                                                 │
    └──────────────────────────────────┘└─────────────────────────────────────────────────┘
    """
    train_requested = pyqtSignal()   # open the training sub-view
    navigate = pyqtSignal(str)       # jump to another tab

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.reader = ModelDetailsReader(app_state, self)
        self.reader.model_read.connect(self._on_model_read)
        self.reader.all_read.connect(self._on_all_read)
        self.combine_worker = None
        self._items = {}
        self._setup_ui()
        self._model_show(None)
        self.app_state.models_changed.connect(self._on_models_changed)
        self.app_state.recordings_changed.connect(self._on_recordings_changed)

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 8, 12)
        title_row = QHBoxLayout()
        self.left_title = QLabel("Models")
        title_row.addWidget(self.left_title)
        title_row.addStretch()
        title_row.addWidget(help_dialog.help_button(self, "train"))
        left_layout.addLayout(title_row)
        self.model_list = QTreeWidget()
        self.model_list.setAccessibleName("Models")
        self.model_list.setHeaderLabels(["Model", "Trained", "Sounds", "Nets"])
        self.model_list.setRootIsDecorated(False)
        self.model_list.setUniformRowHeights(True)
        header = self.model_list.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(MODEL_COLUMN, QHeaderView.ResizeMode.Stretch)
        for column in (TRAINED_COLUMN, SOUNDS_COLUMN, NETS_COLUMN):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.model_list.currentItemChanged.connect(self._on_model_selected)
        self.model_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.model_list.customContextMenuRequested.connect(self._on_model_list_context_menu)
        left_layout.addWidget(self.model_list)
        self.setFocusProxy(self.model_list)

        # Plain, like "+ New sound": the accent marks the panel's main action
        # (Test live here, Start training on the training page).
        self.train_btn = QPushButton("+ New model")
        self.train_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.train_btn.setToolTip("Train a new model from your recorded sounds")
        self.train_btn.clicked.connect(self.train_requested.emit)
        left_layout.addWidget(self.train_btn)

        left.setMinimumWidth(340)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self._model_header_build())
        right_layout.addWidget(self._details_build(), 1)
        self.empty_state = QWidget()
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.addStretch()
        components.center_in(empty_layout, components.EmptyState("No models yet"))
        right_layout.addWidget(self.empty_state, 1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([380, 820])

        t = theme.colors()
        self.left_title.setStyleSheet(components.heading_style("card"))
        self.model_title.setStyleSheet(components.heading_style("title"))
        self.model_stats.setStyleSheet(f"color: {t['text_dim']};")
        # Not a warning: recording more is what the app asks for everywhere
        # else, so being told about it in amber punishes doing the right thing.
        self.stale_label.setStyleSheet(f"color: {t['text_dim']}; margin-top: 2px;")
        self.unused_label.setStyleSheet(f"color: {t['text_dim']};")
        self.model_header.setStyleSheet(
            f"QFrame#modelHeader {{ background-color: {t['toolbar']}; "
            f"border-bottom: 1px solid {t['border']}; }}")
        self.open_folder_btn.setStyleSheet(components.ghost_button_style())

    def _model_header_build(self):
        """The selected model's identity, then its actions in two ranks: the two
        that answer 'does it work?' first, management second."""
        header = QFrame()
        header.setObjectName("modelHeader")
        self.model_header = header
        v = QVBoxLayout(header)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(2)

        self.model_title = QLabel("")
        self.model_title.setTextFormat(Qt.TextFormat.PlainText)
        v.addWidget(self.model_title)
        self.model_stats = QLabel("")
        v.addWidget(self.model_stats)
        self.stale_label = QLabel("")
        self.stale_label.setWordWrap(True)
        v.addWidget(self.stale_label)

        tests = QHBoxLayout()
        tests.setContentsMargins(0, 10, 0, 0)
        self.live_test_btn = components.primary_button("Test live")
        self.live_test_btn.setToolTip(
            "Make each sound into the mic and watch the raw per-sound probabilities")
        self.live_test_btn.clicked.connect(self._on_test_live)
        tests.addWidget(self.live_test_btn)
        self.accuracy_btn = QPushButton("Test accuracy")
        self.accuracy_btn.setMinimumHeight(34)
        self.accuracy_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.accuracy_btn.setToolTip("Classify every sound's recorded segments with this model")
        self.accuracy_btn.clicked.connect(self._on_test_accuracy)
        tests.addWidget(self.accuracy_btn)
        tests.addStretch()
        v.addLayout(tests)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 4, 0, 0)
        for text, slot, tip in (
                ("Rename", self._on_rename, "Rename this model"),
                ("Clone", self._on_clone, "Make a copy under a new name"),
                ("Combine…", self._on_combine, "Merge two or more models into one ensemble")):
            actions.addWidget(components.ghost_button(text, slot, tip))
        self.open_folder_btn = QPushButton("Open models folder")
        self.open_folder_btn.setObjectName("secondaryAction")
        self.open_folder_btn.setFlat(True)
        self.open_folder_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.open_folder_btn.setToolTip(os.path.normpath(os.path.abspath(CLASSIFIER_FOLDER)))
        self.open_folder_btn.clicked.connect(self._on_open_models_folder)
        actions.addWidget(self.open_folder_btn)
        actions.addWidget(components.ghost_button(
            "Delete", self._on_delete, "Delete this model and its files"))
        actions.addStretch()
        v.addLayout(actions)
        return header

    def _details_build(self):
        """sound_tree carries the width, facts beside it is fixed."""
        self.details = QWidget()
        columns = QHBoxLayout(self.details)
        columns.setContentsMargins(20, 16, 24, 16)
        columns.setSpacing(22)
        sounds = QVBoxLayout()
        sounds.setSpacing(6)
        sounds.addWidget(self._sound_tree_build(), 1)
        self.unused_label = QLabel("")
        self.unused_label.setWordWrap(True)
        sounds.addWidget(self.unused_label)
        columns.addLayout(sounds, 1)
        self.facts = QLabel("")
        self.facts.setTextFormat(Qt.TextFormat.RichText)
        self.facts.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.facts.setFixedWidth(300)
        columns.addWidget(self.facts, 0)
        return self.details

    def _sound_tree_build(self):
        """A tree rather than rich text, so accuracy sorts."""
        tree = QTreeWidget()
        self.sound_tree = tree
        tree.setAccessibleName("Sounds in this model")
        tree.setHeaderLabels(["Sound", "Accuracy", ""])
        tree.setRootIsDecorated(False)
        tree.setUniformRowHeights(True)
        tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        # Nothing in it to act on
        tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tree.setSortingEnabled(True)
        tree.sortByColumn(SOUND_COLUMN, Qt.SortOrder.AscendingOrder)
        header = tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(SOUND_COLUMN, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(ACCURACY_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(NOTE_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        return tree

    def refresh_theme(self):
        pass

    # ---- model list ----------------------------------------------------

    def showEvent(self, event):
        """A model trained from the command line while the app is open shows
        on the next visit."""
        super().showEvent(event)
        self._model_list_refresh()
        self._train_btn_update()

    def _on_models_changed(self):
        """AppState has dropped its cache, so every row is read again."""
        self._model_list_populate(self.app_state.get_models_newest_first())

    def _on_recordings_changed(self):
        self._train_btn_update()
        self._model_show(self._current_model_name())

    def _train_btn_update(self):
        """A model tells sounds apart, so it needs two."""
        self.train_btn.setEnabled(len(self.app_state.get_sound_labels()) >= 2)

    def _model_list_refresh(self):
        """Only if the models or their order changed."""
        models_newest_first = self.app_state.get_models_newest_first()
        names = [name for name, _trained_at in models_newest_first]
        if names != list(self._items):
            self._model_list_populate(models_newest_first)

    def _model_list_populate(self, models_newest_first):
        current = self._current_model_name()
        now = datetime.now()
        self.model_list.blockSignals(True)
        self.model_list.clear()
        self._items = {}
        for name, trained_at in models_newest_first:
            item = QTreeWidgetItem([name, "", "", ""])
            item.setData(MODEL_COLUMN, Qt.ItemDataRole.UserRole, name)
            # Long names are cut off in the column
            item.setToolTip(MODEL_COLUMN, name)
            for column in (SOUNDS_COLUMN, NETS_COLUMN):
                item.setTextAlignment(column, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._items[name] = item
            self._model_row_update(name, now, trained_at)
            self.model_list.addTopLevelItem(item)
        self.model_list.blockSignals(False)

        if not self._items:
            self._model_show(None)
            return
        self._reader_start(list(self._items))
        # Fires the selection handler, which shows the model
        self.model_list.setCurrentItem(self._items.get(current) or self.model_list.topLevelItem(0))

    def _model_row_update(self, name, now, trained_at=(None, None)):
        """Sounds is "…" until the checkpoints are read, "?" if they can't be.
        trained_at (replay csv or file date) shows until then."""
        item = self._items[name]
        details = self.app_state.get_model_details_if_read(name)
        when, source = details.trained_at if details else trained_at
        net_count = details.net_count if details else self.app_state.get_net_count(name)
        if details is None:
            sounds = "…"
        else:
            sounds = str(_sound_count(details.labels)) if details.labels else "?"
        trained = trained_when(when, source, now) if when else ""
        item.setText(TRAINED_COLUMN, trained)
        item.setText(SOUNDS_COLUMN, sounds)
        item.setText(NETS_COLUMN, str(net_count) if net_count else "")
        # A screen reader reads only the first column otherwise
        item.setData(MODEL_COLUMN, Qt.ItemDataRole.AccessibleTextRole,
                     f"{name}, trained {trained or 'unknown'}, {sounds} sounds, {net_count} nets")

    def _reader_start(self, names):
        # Before the reader's first torch.load: torch imported off the main
        # thread has segfaulted alongside Qt. Already loaded on Windows.
        try:
            import torch  # noqa: F401
        except Exception:
            pass  # Models with checkpoints then read as unreadable
        self.reader.read([name for name in names
                          if self.app_state.get_model_details_if_read(name) is None])

    def _current_model_name(self):
        item = self.model_list.currentItem()
        return item.data(MODEL_COLUMN, Qt.ItemDataRole.UserRole) if item else None

    def select_model(self, name):
        """After training, renaming or combining, so the new model is the one
        on screen."""
        if name not in self._items:
            self._model_list_refresh()
        item = self._items.get(name)
        if item is not None:
            self.model_list.setCurrentItem(item)

    def _on_model_selected(self, item, _previous=None):
        name = item.data(MODEL_COLUMN, Qt.ItemDataRole.UserRole) if item else None
        if name:
            self.reader.read_first(name)
        self._model_show(name)

    def _on_model_read(self, name):
        if name in self._items:
            self._model_row_update(name, datetime.now())
        if name == self._current_model_name():
            self._model_show(name)

    def _on_all_read(self):
        """Checkpoint dates can reorder the list. Once, at the end, so rows
        don't jump while being read."""
        self._model_list_refresh()

    def _on_model_list_context_menu(self, pos):
        """Same actions as the header. Right-clicking selects the row first,
        so the panel behind the menu is the model the menu is about."""
        item = self.model_list.itemAt(pos)
        if item is None:
            return
        self.model_list.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction("Test live", self._on_test_live)
        menu.addAction("Test accuracy", self._on_test_accuracy)
        menu.addSeparator()
        menu.addAction("Rename…", self._on_rename)
        menu.addAction("Clone…", self._on_clone)
        menu.addAction("Combine…", self._on_combine)
        menu.addAction("Open models folder", self._on_open_models_folder)
        menu.addSeparator()
        menu.addAction("Delete model", self._on_delete)
        menu.exec(self.model_list.viewport().mapToGlobal(pos))

    # ---- details -------------------------------------------------------

    def _model_show(self, name):
        self.model_header.setVisible(name is not None)
        self.details.setVisible(name is not None)
        self.empty_state.setVisible(name is None)
        if name is None:
            return
        self.model_title.setText(name)
        details = self.app_state.get_model_details_if_read(name)
        if details is None or not details.labels:
            self.model_stats.setText("Reading…" if details is None else "Couldn't read this model")
            self.facts.setText(self._facts_html(name, details) if details else "")
            self.sound_tree.clear()
            self.stale_label.setText("")
            self.unused_label.setVisible(False)
            return
        self.model_stats.setText(self._model_stats_text(details))
        self.facts.setText(self._facts_html(name, details))
        new_since = self._recordings_since_training(details)
        self._sound_tree_fill(details, new_since)
        self.stale_label.setText(_stale_text(new_since))
        unused = [label for label in self.app_state.get_sound_labels()
                  if label not in details.labels]
        self.unused_label.setText(f"Recorded but not in this model: {', '.join(unused)}")
        self.unused_label.setVisible(bool(unused))

    def _model_stats_text(self, details):
        count = _sound_count(details.labels)
        sounds = f"{count} {'sound' if count == 1 else 'sounds'}"
        if BACKGROUND_LABEL in details.labels:
            sounds += f" + {BACKGROUND_LABEL}"
        if not details.net_count:
            return sounds
        nets = f"{details.net_count} {'net' if details.net_count == 1 else 'nets'}"
        return f"{sounds}   ·   {nets}"

    def _recordings_since_training(self, details):
        """{label: (takes recorded since, newest take or None if none left)}.
        By training date, not pkl mtime: copying a data dir restamps every
        pkl, which would mark every sound as newer than the model."""
        trained_at = details.trained_at[0] or 0
        return {label: library_ops.recordings_since(label, trained_at)
                for label in details.labels if label != BACKGROUND_LABEL}

    def _facts_rows(self, name, details):
        """[(label, value)], only the ones the model's files record."""
        rows = []
        accuracy = _model_accuracy(details.checkpoints, details.net_count)
        if accuracy is not None:
            rows.append(("Accuracy", percent_span([accuracy], 1)))
        when, source = details.trained_at
        if when:
            trained = trained_when(when, source, datetime.now())
            rows.append(("Trained", f"{trained} (file date)" if source == "mtime" else trained))
        rows.append(("File", html.escape(f"{name}.pkl")))
        if details.pkl_bytes:
            rows.append(("Size", file_size_text(details.pkl_bytes)))
        net_accuracies = _net_accuracies(details.checkpoints)
        if len(net_accuracies) > 1:
            rows.append(("Each net", percent_span(net_accuracies, 1)))
        epochs = _best_epochs_text(details.checkpoints)
        if epochs:
            rows.append(("Best epoch", epochs))
        return rows

    def _facts_html(self, name, details):
        """The model's own rows, then how it was trained, as one table so the
        columns line up down the whole card."""
        t = theme.colors()
        rows = self._facts_rows(name, details)
        training_rows = _training_data_rows(details.checkpoints)
        if training_rows:
            rows.append((f"<b style='color:{t['text']};'>Training data</b>", ""))
            rows += training_rows
        return "<table cellspacing='0' cellpadding='3'>" + "".join(
            f"<tr><td style='color:{t['text_dim']}; padding-right:20px;'>{label}</td>"
            f"<td style='color:{t['text']};'>{value}</td></tr>"
            for label, value in rows) + "</table>"

    def _sound_tree_fill(self, details, new_since):
        t = theme.colors()
        accuracies = _sound_accuracies(details.checkpoints)
        # Off while filling, or every insert re-sorts
        self.sound_tree.setSortingEnabled(False)
        self.sound_tree.clear()
        for label in details.labels:
            scores = accuracies.get(label)
            item = SoundItem([label, percent_span(scores, 0) if scores else "",
                              _sound_note(label, new_since.get(label))])
            item.setTextAlignment(ACCURACY_COLUMN, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if scores:
                item.setData(ACCURACY_COLUMN, Qt.ItemDataRole.UserRole, min(scores))
            item.setForeground(NOTE_COLUMN, QColor(t["text_dim"]))
            self.sound_tree.addTopLevelItem(item)
        self.sound_tree.setSortingEnabled(True)

    # ---- actions -------------------------------------------------------

    def _model_pkl_path(self):
        name = self._current_model_name()
        if not name:
            return None
        path = models.get_model_path(name)
        return path if os.path.isfile(path) else None

    def _on_test_accuracy(self):
        path = self._model_pkl_path()
        if not path:
            return
        from gui.widgets.model_test_dialogs import AccuracyDialog
        AccuracyDialog(self, self._current_model_name(), path,
                       self.app_state.get_sound_labels()).exec()

    def _on_test_live(self):
        path = self._model_pkl_path()
        if not path:
            return
        from gui.services import audio_devices
        from gui.widgets.model_test_dialogs import LiveTestDialog
        LiveTestDialog(self, self._current_model_name(), path, audio_devices.input_index).exec()

    def _on_rename(self):
        name = self._current_model_name()
        if not name:
            return
        new, ok = QInputDialog.getText(self, "Rename model", "New name:", text=name)
        if not ok:
            return
        try:
            self.select_model(self.app_state.rename_model(name, new))
        except library_ops.LibraryOpError as exc:
            QMessageBox.warning(self, "Rename failed", str(exc))

    def _on_clone(self):
        name = self._current_model_name()
        if not name:
            return
        new, ok = QInputDialog.getText(self, "Clone model", "Name for the copy:",
                                       text=f"{name}_copy")
        if not ok:
            return
        try:
            self.app_state.clone_model(name, new)
        except library_ops.LibraryOpError as exc:
            QMessageBox.warning(self, "Clone failed", str(exc))

    def _on_open_models_folder(self):
        try:
            library_ops.open_in_file_manager(CLASSIFIER_FOLDER)
        except library_ops.LibraryOpError as exc:
            QMessageBox.warning(self, "Couldn't open folder", str(exc))

    def _on_delete(self):
        name = self._current_model_name()
        if not name:
            return
        files = models.get_model_files(name)
        detail = "\n".join(os.path.basename(f) for f in files)
        if confirm_destructive(
                self,
                title=f"Delete model '{name}'?",
                body=f"This permanently deletes the model and its {len(files)} file(s).",
                detail=detail,
                confirm_text=name,
                confirm_label="Delete model"):
            try:
                self.app_state.delete_model(name)
            except library_ops.LibraryOpError as exc:
                QMessageBox.warning(self, "Delete failed", str(exc))

    # ---- combine -------------------------------------------------------

    def _on_combine(self):
        names = self.app_state.get_model_names()
        if len(names) < 2:
            QMessageBox.information(
                self, "Combine models",
                "Combining fuses two or more models into one ensemble - you "
                "only have one, so there's nothing to combine it with.")
            return
        dialog = _CombineDialog(self, names)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = dialog.selected_models()
        if len(chosen) < 2:
            QMessageBox.information(self, "Combine models", "Pick at least two models.")
            return
        try:
            new_name = library_ops.sanitize_name(dialog.new_name(), kind="model name")
        except library_ops.LibraryOpError as exc:
            QMessageBox.warning(self, "Combine models", str(exc))
            return
        if models.model_exists(new_name):
            QMessageBox.warning(self, "Combine models",
                                f"A model called '{new_name}' already exists.")
            return
        self.combine_worker = CombineWorker(new_name, chosen)
        self.combine_worker.finished_ok.connect(self._on_combined)
        self.combine_worker.failed.connect(self._on_combine_failed)
        self.combine_worker.start()

    def _on_combined(self, name):
        self.combine_worker = None
        self.app_state.models_changed.emit()
        self.select_model(name)

    def _on_combine_failed(self, message):
        self.combine_worker = None
        QMessageBox.warning(self, "Combine failed", message)


def _sound_count(labels):
    """Silence is a class the trainer makes, not a sound anyone recorded."""
    return len([label for label in labels if label != BACKGROUND_LABEL])


def _sound_note(label, since):
    """since: (takes recorded since training, newest take or None)."""
    if label == BACKGROUND_LABEL:
        return "from all your recordings"
    new_takes, newest = since
    if newest is None:
        return "no recordings any more"
    if new_takes:
        return f"{new_takes} new since"
    return ""


def _stale_text(new_since):
    stale = [(label, takes) for label, (takes, _newest) in new_since.items() if takes]
    if not stale:
        return ""
    takes = sum(count for _label, count in stale)
    names = [label for label, _count in stale]
    shown = ", ".join(names[:4]) + ("…" if len(names) > 4 else "")
    noun = "recording" if takes == 1 else "recordings"
    return f"{takes} new {noun} since this model was trained: {shown}"


def _model_accuracy(checkpoints, net_count):
    """combined_accuracy from the net whose best epoch came last, else a lone
    net's accuracy. None if not recorded."""
    scored = [c for c in checkpoints
              if c.get("combined_accuracy") is not None and c.get("epoch") is not None]
    if scored:
        return max(scored, key=lambda c: c["epoch"])["combined_accuracy"]
    if net_count == 1 and checkpoints:
        return checkpoints[0].get("accuracy")
    return None


def _net_accuracies(checkpoints):
    return [c["accuracy"] for c in checkpoints if c.get("accuracy") is not None]


def _best_epochs_text(checkpoints):
    """'12' or '9-14'. +1: the trainer counts epochs from zero."""
    epochs = [c["epoch"] + 1 for c in checkpoints if c.get("epoch") is not None]
    if not epochs:
        return ""
    low, high = min(epochs), max(epochs)
    return str(low) if low == high else f"{low}-{high}"


def _sound_accuracies(checkpoints):
    """{label: [each net's accuracy on it]}, on the samples the trainer held
    back. Empty for models trained before label_accuracy was saved."""
    scores = {}
    for checkpoint in checkpoints:
        for label, accuracy in (checkpoint.get("label_accuracy") or {}).items():
            scores.setdefault(label, []).append(accuracy)
    return scores


def _training_data_rows(checkpoints):
    """[(label, value)] for how the run was set up. One run made every net,
    so the first checkpoint to carry a field speaks for the model. Empty on
    models trained before the fields existed."""
    def first(key):
        return next((c[key] for c in checkpoints if c.get(key)), None)

    rows = []
    # Post-balancing, so not the setup screen's "Recorded": repeated frames
    # count every time the trainer sees them, and this can exceed what is on
    # disk. "Audio", not a bare duration: under "Trained" it read as how long
    # the run took.
    label_frames = first("label_frames")
    if label_frames:
        rows.append(("Audio", balance.frames_as_minutes(sum(label_frames.values()))))
    # A model runs against whatever mic is live, so this is the first
    # question when it works on one setup and not another.
    mics = library_ops.describe_mics(first("source_mics"))
    if mics:
        rows.append(("Microphones", mics))
    # Wording follows the training screen's own controls
    run = first("run_settings") or {}
    if "balance_sounds" in run:
        rows.append(("Balance sounds", "On" if run["balance_sounds"] else "Off"))
    if run.get("silence"):
        rows.append(("Silence", {"all": "Include all", "balanced": "Balanced",
                                 "none": "Omit"}.get(run["silence"], run["silence"])))
    return rows


class SoundItem(QTreeWidgetItem):
    """Sorts the accuracy column by its lowest net. As text, 100% sorts below 97%."""

    def __lt__(self, other):
        column = self.treeWidget().sortColumn()
        mine = self.data(column, Qt.ItemDataRole.UserRole)
        theirs = other.data(column, Qt.ItemDataRole.UserRole)
        if mine is None or theirs is None:
            return super().__lt__(other)
        return mine < theirs


class ModelDetailsReader(QThread):
    """Reads models' checkpoints off the UI thread, one model at a time so rows
    fill in from the top. read() queues more, read_first() jumps the queue."""
    model_read = pyqtSignal(str)
    all_read = pyqtSignal()

    def __init__(self, app_state, parent):
        super().__init__(parent)
        self.app_state = app_state
        self._pending = []
        self._lock = threading.Lock()
        self.finished.connect(self._on_finished)
        QApplication.instance().aboutToQuit.connect(self._stop)

    def read(self, names):
        with self._lock:
            self._pending += [name for name in names if name not in self._pending]
        if names and not self.isRunning():
            self.start()

    def read_first(self, name):
        with self._lock:
            if name in self._pending:
                self._pending.remove(name)
                self._pending.insert(0, name)

    def run(self):
        while (name := self._pending_pop()) is not None:
            self.app_state.get_model_details(name)
            self.model_read.emit(name)

    def _pending_pop(self):
        with self._lock:
            return self._pending.pop(0) if self._pending else None

    def _on_finished(self):
        # read() can arrive after the last pop, while still running, and not restart
        with self._lock:
            more = bool(self._pending)
        if more:
            self.start()
        else:
            self.all_read.emit()

    def _stop(self):
        """The read in progress finishes, the rest are dropped. A QThread
        deleted while running aborts the app."""
        with self._lock:
            self._pending.clear()
        self.wait()


class _CombineDialog(QDialog):
    """Pick two or more models and a name to fuse them into one ensemble."""

    def __init__(self, parent, model_names):
        super().__init__(parent)
        self.setWindowTitle("Combine models")
        self.setModal(True)
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Select the models to combine into an ensemble:"))
        self.list = QListWidget()
        for name in model_names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.list.addItem(item)
        layout.addWidget(self.list)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("New model name:"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("combined_model")
        name_row.addWidget(self.name_input)
        layout.addLayout(name_row)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        ok = QPushButton("Combine")
        ok.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        ok.clicked.connect(self.accept)
        buttons.addWidget(ok)
        layout.addLayout(buttons)

    def selected_models(self):
        return [self.list.item(i).text() for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]

    def new_name(self):
        return self.name_input.text().strip() or "combined_model"
