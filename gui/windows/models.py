"""Models tab - browse, manage, and train models.

Left: the list of trained models. Right: details for the selected model plus
management actions (rename / clone / delete / reveal / inspect), and a panel to
train a new model from recorded sounds. Inspired by the Sounds tab.

Destructive actions (delete) go through the two-step confirm dialog.
"""
import os
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QSplitter, QGroupBox, QLineEdit, QSpinBox, QInputDialog,
    QMessageBox, QScrollArea, QFrame, QSizePolicy, QDialog
)

from config.config import CLASSIFIER_FOLDER
from gui import theme
from gui.services import library_ops
from gui.widgets.confirm_dialog import confirm_destructive
from gui.widgets import help_dialog
from gui.widgets.training_plot import TrainingPlotWidget
from gui.workers.training_worker import TrainingWorker
from gui.workers.combine_worker import CombineWorker


def _human_size(num_bytes):
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


class InspectWorker(QThread):
    """Load the heavy model metadata (labels/accuracy from joblib + torch) off
    the UI thread."""
    loaded = pyqtSignal(object)

    def __init__(self, app_state, name, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.name = name

    def run(self):
        try:
            meta = self.app_state.get_model_metadata(self.name, load_weights=True)
        except Exception:
            meta = None
        self.loaded.emit(meta)


class ModelsPage(QWidget):
    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.training_worker = None
        self.inspect_worker = None
        self.combine_worker = None
        self._current = None

        self._setup_ui()
        self._populate_models()
        self._populate_train_labels()
        self.app_state.models_changed.connect(self._populate_models)
        self.app_state.recordings_changed.connect(self._populate_train_labels)

    # ---- ui ------------------------------------------------------------

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # Left: model list + new-sound-style header
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 8, 12)
        title_row = QHBoxLayout()
        title = QLabel("Models")
        title.setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {theme.colors()['text_bright']};")
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(help_dialog.help_button(self, "train"))
        left_layout.addLayout(title_row)
        self.model_list = QListWidget()
        self.model_list.currentItemChanged.connect(self._on_select)
        left_layout.addWidget(self.model_list)

        combine_btn = QPushButton("Combine models…")
        combine_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        combine_btn.setToolTip("Merge two or more models into one ensemble")
        combine_btn.clicked.connect(self._on_combine)
        left_layout.addWidget(combine_btn)

        left.setMinimumWidth(240)
        splitter.addWidget(left)

        # Right: scrollable details + train
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right = QWidget()
        self.right_layout = QVBoxLayout(right)
        self.right_layout.setContentsMargins(20, 16, 24, 16)
        self.right_layout.setSpacing(14)
        right_scroll.setWidget(right)

        self.right_layout.addWidget(self._build_details_group())
        self.right_layout.addWidget(self._build_train_group())
        self.right_layout.addStretch()
        splitter.addWidget(right_scroll)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 940])

    def _build_details_group(self):
        group = QGroupBox("Selected model")
        v = QVBoxLayout(group)

        self.detail_title = QLabel("Select a model")
        self.detail_title.setStyleSheet(
            f"font-size: 17px; font-weight: bold; color: {theme.colors()['text_bright']};")
        v.addWidget(self.detail_title)

        self.detail_stats = QLabel("")
        self.detail_stats.setStyleSheet(f"color: {theme.colors()['text_dim']};")
        v.addWidget(self.detail_stats)

        self.detail_labels = QLabel("")
        self.detail_labels.setWordWrap(True)
        self.detail_labels.setStyleSheet(f"color: {theme.colors()['text']};")
        v.addWidget(self.detail_labels)

        # Action buttons
        actions = QHBoxLayout()
        self.inspect_btn = self._action_btn("Inspect", self._on_inspect)
        self.accuracy_btn = self._action_btn("Test accuracy", self._on_test_accuracy)
        self.accuracy_btn.setToolTip(
            "Classify every sound's recorded segments with this model")
        self.live_test_btn = self._action_btn("Test live", self._on_test_live)
        self.live_test_btn.setToolTip(
            "Speak into the mic and watch the raw per-sound probabilities")
        self.rename_btn = self._action_btn("Rename", self._on_rename)
        self.clone_btn = self._action_btn("Clone", self._on_clone)
        self.open_btn = self._action_btn("Open folder", self._on_open_folder)
        self.delete_btn = self._action_btn("Delete", self._on_delete)
        for b in (self.inspect_btn, self.accuracy_btn, self.live_test_btn,
                  self.rename_btn, self.clone_btn, self.open_btn, self.delete_btn):
            actions.addWidget(b)
        actions.addStretch()
        v.addLayout(actions)
        self._set_actions_enabled(False)
        return group

    def _model_pkl_path(self):
        if not self._current:
            return None
        return os.path.join(CLASSIFIER_FOLDER, f"{self._current}.pkl")

    def _on_test_accuracy(self):
        path = self._model_pkl_path()
        if not path or not os.path.isfile(path):
            return
        from gui.widgets.model_test_dialogs import AccuracyDialog
        dialog = AccuracyDialog(self, self._current, path,
                                self.app_state.get_sound_labels())
        dialog.exec()

    def _on_test_live(self):
        path = self._model_pkl_path()
        if not path or not os.path.isfile(path):
            return
        from config.config import INPUT_DEVICE_INDEX
        from gui.widgets.model_test_dialogs import LiveTestDialog
        dialog = LiveTestDialog(self, self._current, path, INPUT_DEVICE_INDEX)
        dialog.exec()

    def _action_btn(self, label, slot):
        btn = QPushButton(label)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.clicked.connect(slot)
        return btn

    def _build_train_group(self):
        group = QGroupBox("Train a new model")
        v = QVBoxLayout(group)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Model name:"))
        self.train_name = QLineEdit()
        self.train_name.setPlaceholderText("my_model")
        name_row.addWidget(self.train_name)
        name_row.addWidget(QLabel("Nets:"))
        self.net_spin = QSpinBox()
        self.net_spin.setRange(1, 10)
        self.net_spin.setValue(1)
        name_row.addWidget(self.net_spin)
        v.addLayout(name_row)

        v.addWidget(QLabel("Sounds to include (need at least 2):"))
        self.train_labels = QListWidget()
        self.train_labels.setMaximumHeight(160)
        v.addWidget(self.train_labels)

        self.train_status = QLabel("Ready to train")
        self.train_status.setStyleSheet(f"color: {theme.colors()['text_dim']};")
        v.addWidget(self.train_status)

        self.train_plot = TrainingPlotWidget()
        self.train_plot.setMinimumHeight(220)
        self.train_plot.setSizePolicy(QSizePolicy.Policy.Expanding,
                                      QSizePolicy.Policy.Expanding)
        v.addWidget(self.train_plot)

        btn_row = QHBoxLayout()
        self.train_btn = QPushButton("Train")
        self.train_btn.clicked.connect(self._on_train)
        btn_row.addWidget(self.train_btn)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop_train)
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch()
        v.addLayout(btn_row)
        return group

    # ---- model list ----------------------------------------------------

    def _populate_models(self):
        prev = self._current
        self.model_list.blockSignals(True)
        self.model_list.clear()
        for meta in self.app_state.get_all_model_details():
            text = f"{meta['name']}"
            if meta["net_count"]:
                text += f"   ·   {meta['net_count']} net" + ("s" if meta['net_count'] != 1 else "")
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, meta["name"])
            self.model_list.addItem(item)
        self.model_list.blockSignals(False)

        # Restore selection if still present.
        if prev:
            for i in range(self.model_list.count()):
                if self.model_list.item(i).data(Qt.ItemDataRole.UserRole) == prev:
                    self.model_list.setCurrentRow(i)
                    return
        self._current = None
        self._show_details(None)

    def _on_select(self, current, _prev=None):
        if current is None:
            self._current = None
            self._show_details(None)
            return
        self._current = current.data(Qt.ItemDataRole.UserRole)
        meta = self.app_state.get_model_metadata(self._current)
        self._show_details(meta)

    def _show_details(self, meta):
        if not meta:
            self.detail_title.setText("Select a model")
            self.detail_stats.setText("")
            self.detail_labels.setText("")
            self._set_actions_enabled(False)
            return
        self.detail_title.setText(meta["name"])
        nets = meta["net_count"]
        size = _human_size(meta["total_size_bytes"])
        acc = (f"   ·   best accuracy {meta['best_accuracy']:.3f}"
               if meta.get("best_accuracy") is not None else "")
        self.detail_stats.setText(
            f"{nets} net" + ("s" if nets != 1 else "") + f"   ·   {size}{acc}")
        if meta.get("labels"):
            self.detail_labels.setText(
                "Recognizes: " + ", ".join(str(x) for x in meta["labels"]))
        else:
            self.detail_labels.setText(
                "Sounds unknown - click Inspect to load them.")
        self._set_actions_enabled(True)

    def _set_actions_enabled(self, on):
        for b in (self.inspect_btn, self.accuracy_btn, self.live_test_btn,
                  self.rename_btn, self.clone_btn, self.open_btn, self.delete_btn):
            b.setEnabled(on)

    # ---- actions -------------------------------------------------------

    def _on_inspect(self):
        if not self._current:
            return
        self.detail_labels.setText("Loading model details…")
        self.inspect_worker = InspectWorker(self.app_state, self._current)
        self.inspect_worker.loaded.connect(self._on_inspected)
        self.inspect_worker.start()

    def _on_inspected(self, meta):
        # Only apply if the selection didn't change while loading.
        if meta and meta["name"] == self._current:
            self._show_details(meta)
        self.inspect_worker = None

    def _on_rename(self):
        if not self._current:
            return
        new, ok = QInputDialog.getText(self, "Rename model", "New name:",
                                       text=self._current)
        if not ok:
            return
        try:
            self._current = self.app_state.rename_model(self._current, new)
        except library_ops.LibraryOpError as exc:
            QMessageBox.warning(self, "Rename failed", str(exc))

    def _on_clone(self):
        if not self._current:
            return
        new, ok = QInputDialog.getText(self, "Clone model", "Name for the copy:",
                                       text=f"{self._current}_copy")
        if not ok:
            return
        try:
            self.app_state.clone_model(self._current, new)
        except library_ops.LibraryOpError as exc:
            QMessageBox.warning(self, "Clone failed", str(exc))

    def _on_open_folder(self):
        try:
            library_ops.open_in_file_manager(
                library_ops.model_pkl_path(self._current))
        except library_ops.LibraryOpError as exc:
            QMessageBox.warning(self, "Couldn't open folder", str(exc))

    def _on_delete(self):
        if not self._current:
            return
        files = library_ops.model_files(self._current)
        detail = "\n".join(os.path.basename(f) for f in files)
        if confirm_destructive(
                self,
                title=f"Delete model '{self._current}'?",
                body=f"This permanently deletes the model and its "
                     f"{len(files)} file(s).",
                detail=detail,
                confirm_text=self._current,
                confirm_label="Delete model"):
            try:
                self.app_state.delete_model(self._current)
            except library_ops.LibraryOpError as exc:
                QMessageBox.warning(self, "Delete failed", str(exc))

    # ---- combine -------------------------------------------------------

    def _on_combine(self):
        names = self.app_state.get_model_names()
        if len(names) < 2:
            QMessageBox.information(self, "Combine models",
                                   "You need at least two models to combine.")
            return
        dialog = _CombineDialog(self, names)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = dialog.selected_models()
        new_name = dialog.new_name()
        if len(chosen) < 2:
            QMessageBox.information(self, "Combine models",
                                   "Pick at least two models.")
            return
        try:
            new_name = library_ops.sanitize_name(new_name, kind="model name")
        except library_ops.LibraryOpError as exc:
            QMessageBox.warning(self, "Combine models", str(exc))
            return
        if library_ops.model_exists(new_name):
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
        self._current = name
        self._populate_models()

    def _on_combine_failed(self, message):
        self.combine_worker = None
        QMessageBox.warning(self, "Combine failed", message)

    # ---- training ------------------------------------------------------

    def _populate_train_labels(self):
        checked = self._checked_train_labels()
        self.train_labels.clear()
        for label in self.app_state.get_sound_labels():
            ms = self.app_state.get_label_duration_ms(label)
            item = QListWidgetItem(f"{label}  ({ms // 1000}s)")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            state = Qt.CheckState.Checked if (not checked or label in checked) \
                else Qt.CheckState.Unchecked
            item.setCheckState(state)
            item.setData(Qt.ItemDataRole.UserRole, label)
            self.train_labels.addItem(item)

    def _checked_train_labels(self):
        out = []
        for i in range(self.train_labels.count()):
            item = self.train_labels.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.data(Qt.ItemDataRole.UserRole))
        return out

    def _on_train(self):
        name = self.train_name.text().strip()
        if not name:
            self.train_status.setText("Enter a model name.")
            return
        selected = self._checked_train_labels()
        if len(selected) < 2:
            self.train_status.setText("Select at least 2 sounds.")
            return
        if library_ops.model_exists(name):
            if not confirm_destructive(
                    self,
                    title=f"Overwrite model '{name}'?",
                    body="A model with this name already exists. Training will "
                         "overwrite it.",
                    confirm_label="Overwrite & train"):
                return
        os.makedirs(CLASSIFIER_FOLDER, exist_ok=True)
        self.train_plot.clear()
        self.train_status.setText("Training…")
        self.train_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.training_worker = TrainingWorker(name, selected, self.net_spin.value())
        self.training_worker.epoch_complete.connect(self._on_epoch)
        self.training_worker.training_finished.connect(self._on_train_done)
        self.training_worker.error_occurred.connect(self._on_train_error)
        self.training_worker.start()

    def _on_stop_train(self):
        if self.training_worker:
            self.training_worker.request_stop()

    def _on_epoch(self, epoch, loss, accuracy, per_label, is_best):
        self.train_plot.add_point(epoch, loss, accuracy)
        best = " (new best!)" if is_best else ""
        self.train_status.setText(
            f"Epoch {epoch + 1} - loss {loss:.4f} - accuracy {accuracy:.3f}{best}")

    def _on_train_done(self):
        self.train_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.train_status.setText("Training complete.")
        self.app_state.models_changed.emit()
        self.training_worker = None

    def _on_train_error(self, msg):
        self.train_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.train_status.setText(f"Error: {msg}")
        self.training_worker = None

    def refresh_theme(self):
        pass


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
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        ok = QPushButton("Combine")
        ok.clicked.connect(self.accept)
        buttons.addWidget(ok)
        layout.addLayout(buttons)

    def selected_models(self):
        out = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.text())
        return out

    def new_name(self):
        return self.name_input.text().strip() or "combined_model"
