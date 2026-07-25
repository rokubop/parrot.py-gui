"""Dedicated training view - the whole screen for the one decision that
matters: which sounds go into this model.

Training used to be a group box below the (empty) model details on the Models
tab, which put a dead panel above the only action a user without models can
take. Here the checklist *is* the page, and it carries the same data-quantity
rating the Sounds tab teaches - so a thin sound is visible before training
rather than showing up as a disappointing accuracy number after it.

Left: what goes in (name, sounds, advanced). Right: what comes out (status,
loss/accuracy plot, and a finish panel that says what to do next).
"""
import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QLineEdit,
    QSpinBox, QTreeWidget, QTreeWidgetItem, QHeaderView, QFrame, QMessageBox
)

from config.config import CLASSIFIER_FOLDER
from gui import theme
from gui.services import library_ops
from gui.widgets import help_dialog
from gui.widgets.confirm_dialog import confirm_destructive
from gui.widgets.training_plot import TrainingPlotWidget
from gui.workers.training_worker import TrainingWorker
from lib.print_status import get_quantity_rating

WARN = "#e0b020"
BAD = "#e05a5a"


def _default_model_name():
    base = "my_model"
    if not library_ops.model_exists(base):
        return base
    n = 2
    while library_ops.model_exists(f"{base}_{n}"):
        n += 1
    return f"{base}_{n}"


class TrainView(QWidget):
    done = pyqtSignal(str)       # left the view; arg = model to select ("" = none)
    navigate = pyqtSignal(str)   # jump to a tab (Sounds, when there's nothing to train on)

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.worker = None
        self._best_accuracy = None
        self._stopped = False
        self._failed = False
        self._trained_name = None

        self._setup_ui()

    # ---- entry point (called by MainWindow) ----------------------------

    def start(self):
        """Fresh training run: repopulate from disk and clear the last result."""
        self._best_accuracy = None
        self._stopped = False
        self._failed = False
        self._trained_name = None
        self.success_frame.setVisible(False)
        self.train_row.setVisible(True)
        self.plot.clear()
        self.plot.setVisible(False)
        self.placeholder_box.setVisible(True)
        self.name_input.setText(_default_model_name())
        self._populate_labels(check_all=True)
        self.status.setText("")
        self._update_readiness()

    # ---- ui ------------------------------------------------------------

    def _setup_ui(self):
        t = theme.colors()
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        top = QHBoxLayout()
        back = QPushButton("← Back to Models")
        back.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        back.clicked.connect(self._on_back)
        top.addWidget(back)
        title = QLabel("Train a model")
        title.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {t['text_bright']};")
        top.addWidget(title)
        top.addStretch()
        top.addWidget(help_dialog.help_button(self, "train"))
        root.addLayout(top)

        columns = QHBoxLayout()
        columns.setSpacing(20)
        columns.addWidget(self._build_input_column(), 0)
        columns.addWidget(self._build_output_column(), 1)
        root.addLayout(columns, 1)

    def _build_input_column(self):
        t = theme.colors()
        col = QWidget()
        col.setMinimumWidth(420)
        col.setMaximumWidth(520)
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Model name:"))
        self.name_input = QLineEdit()
        self.name_input.textChanged.connect(lambda _t: self._update_readiness())
        name_row.addWidget(self.name_input)
        v.addLayout(name_row)

        list_head = QHBoxLayout()
        sounds_title = QLabel("Sounds to include")
        sounds_title.setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {t['text_bright']};")
        list_head.addWidget(sounds_title)
        list_head.addStretch()
        for text, checked in (("All", True), ("None", False)):
            btn = QPushButton(text)
            btn.setFlat(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setStyleSheet(
                f"QPushButton {{ color: {t['text_dim']}; background: transparent; "
                f"border: none; padding: 2px 6px; }} "
                f"QPushButton:hover {{ color: {t['text_bright']}; }}")
            btn.clicked.connect(lambda _c, on=checked: self._set_all_checked(on))
            list_head.addWidget(btn)
        v.addLayout(list_head)

        # Same three columns as the Sounds list: a rating means the same thing
        # here, so it should look the same too.
        self.labels_tree = QTreeWidget()
        self.labels_tree.setColumnCount(3)
        self.labels_tree.setHeaderLabels(["Sound", "Data", "Time"])
        self.labels_tree.setRootIsDecorated(False)
        self.labels_tree.setUniformRowHeights(True)
        header = self.labels_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.labels_tree.itemChanged.connect(self._on_item_changed)
        v.addWidget(self.labels_tree, 1)

        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(f"color: {t['text_dim']};")
        v.addWidget(self.summary)

        # Net count is a tuning knob, not a first-model decision - one click of
        # noise for everyone else, so it starts folded away.
        self.advanced_btn = QPushButton("▸  Advanced")
        self.advanced_btn.setFlat(True)
        self.advanced_btn.setCheckable(True)
        self.advanced_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.advanced_btn.setStyleSheet(
            f"QPushButton {{ color: {t['text_dim']}; background: transparent; "
            f"border: none; padding: 2px 0px; text-align: left; }} "
            f"QPushButton:hover {{ color: {t['text_bright']}; }}")
        self.advanced_btn.toggled.connect(self._on_advanced_toggled)
        v.addWidget(self.advanced_btn, 0, Qt.AlignmentFlag.AlignLeft)

        self.advanced_box = QWidget()
        adv = QVBoxLayout(self.advanced_box)
        adv.setContentsMargins(14, 0, 0, 0)
        adv.setSpacing(4)
        nets_row = QHBoxLayout()
        nets_row.addWidget(QLabel("Nets:"))
        self.net_spin = QSpinBox()
        self.net_spin.setRange(1, 10)
        self.net_spin.setValue(1)
        nets_row.addWidget(self.net_spin)
        nets_row.addStretch()
        adv.addLayout(nets_row)
        nets_help = QLabel(
            "How many networks to train and keep as an ensemble. More nets take "
            "proportionally longer and buy a little accuracy. 1 is right for a "
            "first model.")
        nets_help.setWordWrap(True)
        nets_help.setStyleSheet(f"color: {t['text_dim']};")
        adv.addWidget(nets_help)
        self.advanced_box.setVisible(False)
        v.addWidget(self.advanced_box)

        self.readiness = QLabel("")
        self.readiness.setWordWrap(True)
        v.addWidget(self.readiness)

        self.train_row = QWidget()
        btn_row = QHBoxLayout(self.train_row)
        btn_row.setContentsMargins(0, 4, 0, 0)
        self.train_btn = QPushButton("Train")
        self.train_btn.setObjectName("primaryAction")
        self.train_btn.setMinimumHeight(34)
        self.train_btn.setStyleSheet(primary_button_style())
        self.train_btn.clicked.connect(self._on_train)
        btn_row.addWidget(self.train_btn)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.stop_btn.clicked.connect(self._on_stop)
        btn_row.addWidget(self.stop_btn)
        # Only route to Sounds when there is genuinely nothing to train on -
        # otherwise it competes with Train.
        self.to_sounds_btn = QPushButton("Go to Sounds")
        self.to_sounds_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.to_sounds_btn.clicked.connect(lambda: self.navigate.emit("Sounds"))
        btn_row.addWidget(self.to_sounds_btn)
        btn_row.addStretch()
        v.addWidget(self.train_row)
        return col

    def _build_output_column(self):
        t = theme.colors()
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        head = QLabel("Progress")
        head.setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {t['text_bright']};")
        v.addWidget(head)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {t['text_dim']};")
        v.addWidget(self.status)

        # An empty pair of axes is a poor thing to stare at before the first
        # epoch, and it says nothing about what the curve will mean.
        self.plot_placeholder = QLabel(
            "The loss and accuracy curves appear here once training starts.\n\n"
            "Accuracy is measured on samples held back from the training data, "
            "so it's a fair guess at how the model will do on sounds it hasn't "
            "heard.")
        self.plot_placeholder.setWordWrap(True)
        self.plot_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.plot_placeholder.setMaximumWidth(460)
        self.plot_placeholder.setStyleSheet(f"color: {t['text_dim']};")
        placeholder_box = QWidget()
        pv = QVBoxLayout(placeholder_box)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.addStretch()
        pv.addWidget(self.plot_placeholder, 0, Qt.AlignmentFlag.AlignHCenter)
        pv.addStretch()
        self.placeholder_box = placeholder_box
        v.addWidget(placeholder_box, 1)

        self.plot = TrainingPlotWidget()
        self.plot.setMinimumHeight(260)
        self.plot.setVisible(False)
        v.addWidget(self.plot, 1)

        self.success_frame = self._build_success_frame()
        self.success_frame.setVisible(False)
        v.addWidget(self.success_frame)
        return col

    def _build_success_frame(self):
        """Training ending in a silent status label left users with no idea
        whether it had worked or what to do next. This says both."""
        t = theme.colors()
        frame = QFrame()
        frame.setObjectName("successPanel")
        frame.setStyleSheet(
            f"QFrame#successPanel {{ background-color: {t['card']}; "
            f"border: 1px solid {t['accent']}; border-radius: 8px; }}")
        v = QVBoxLayout(frame)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(6)

        self.success_title = QLabel("")
        self.success_title.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {t['text_bright']}; "
            f"border: none;")
        v.addWidget(self.success_title)
        self.success_body = QLabel("")
        self.success_body.setWordWrap(True)
        self.success_body.setStyleSheet(f"color: {t['text']}; border: none;")
        v.addWidget(self.success_body)

        row = QHBoxLayout()
        row.setContentsMargins(0, 6, 0, 0)
        live = QPushButton("Test it live")
        live.setObjectName("primaryAction")
        live.setMinimumHeight(32)
        live.setStyleSheet(primary_button_style())
        live.setToolTip("Make each sound into the mic and watch the probabilities")
        live.clicked.connect(self._on_test_live)
        row.addWidget(live)
        accuracy = QPushButton("Test accuracy")
        accuracy.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        accuracy.setToolTip("Classify every sound's recorded segments with this model")
        accuracy.clicked.connect(self._on_test_accuracy)
        row.addWidget(accuracy)
        again = QPushButton("Train another")
        again.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        again.clicked.connect(self.start)
        row.addWidget(again)
        row.addStretch()
        finish = QPushButton("Done")
        finish.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        finish.clicked.connect(lambda: self.done.emit(self._trained_name or ""))
        row.addWidget(finish)
        v.addLayout(row)
        return frame

    def _on_advanced_toggled(self, on):
        self.advanced_btn.setText("▾  Advanced" if on else "▸  Advanced")
        self.advanced_box.setVisible(on)

    # ---- sound checklist ------------------------------------------------

    def _populate_labels(self, check_all=False):
        checked = set() if check_all else set(self.checked_labels())
        self.labels_tree.blockSignals(True)
        self.labels_tree.clear()
        for label in self.app_state.get_sound_labels():
            ms = self.app_state.get_label_duration_ms(label)
            quantity, _percent, _next = get_quantity_rating(ms)
            item = QTreeWidgetItem([label, quantity, f"{ms / 1000:.0f}s"])
            item.setData(0, Qt.ItemDataRole.UserRole, label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked
                               if (check_all or label in checked)
                               else Qt.CheckState.Unchecked)
            color = theme.QUANTITY_COLORS.get(quantity)
            if color:
                item.setForeground(1, QColor(color))
            if quantity == "Not enough":
                item.setToolTip(
                    1, "Under 17s of detected sound. It can still go in, but it "
                       "will be the model's weakest sound - record more of it, "
                       "or leave it out.")
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight
                                  | Qt.AlignmentFlag.AlignVCenter)
            self.labels_tree.addTopLevelItem(item)
        self.labels_tree.blockSignals(False)

    def _on_item_changed(self, _item, _column):
        self._update_readiness()

    def _set_all_checked(self, on):
        state = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
        self.labels_tree.blockSignals(True)
        for i in range(self.labels_tree.topLevelItemCount()):
            self.labels_tree.topLevelItem(i).setCheckState(0, state)
        self.labels_tree.blockSignals(False)
        self._update_readiness()

    def checked_labels(self):
        out = []
        for i in range(self.labels_tree.topLevelItemCount()):
            item = self.labels_tree.topLevelItem(i)
            if item.checkState(0) == Qt.CheckState.Checked:
                out.append(item.data(0, Qt.ItemDataRole.UserRole))
        return out

    def _ratings(self, labels):
        counts = {}
        for label in labels:
            quantity, _p, _n = get_quantity_rating(
                self.app_state.get_label_duration_ms(label))
            counts[quantity] = counts.get(quantity, 0) + 1
        return counts

    # ---- readiness gate --------------------------------------------------

    def _update_readiness(self):
        """Say what's missing *before* the click. The old page accepted a name,
        a selection and a Train press, then answered 'select at least 2 sounds'."""
        t = theme.colors()
        total = self.labels_tree.topLevelItemCount()
        selected = self.checked_labels()
        counts = self._ratings(selected)
        running = self.worker is not None

        parts = []
        if selected:
            order = ("Excellent", "Good", "Sufficient", "Not enough")
            breakdown = ", ".join(f"{counts[q]} {q}" for q in order if q in counts)
            noun = "sound" if len(selected) == 1 else "sounds"
            parts.append(f"{len(selected)} {noun} selected  ·  {breakdown}")
        self.summary.setText("  ".join(parts))

        self.to_sounds_btn.setVisible(total < 2)
        if total < 2:
            missing = "any sounds" if total == 0 else "a second sound"
            self._set_readiness(
                f"A model tells sounds apart, so it needs at least two. "
                f"You don't have {missing} yet.", BAD)
            self.train_btn.setEnabled(False)
            return
        if len(selected) < 2:
            self._set_readiness("Select at least 2 sounds to train on.", WARN)
            self.train_btn.setEnabled(False)
            return
        name = self.name_input.text().strip()
        if not name:
            self._set_readiness("Give the model a name.", WARN)
            self.train_btn.setEnabled(False)
            return

        thin = counts.get("Not enough", 0)
        if library_ops.model_exists(name):
            self._set_readiness(
                f"“{name}” already exists - training will overwrite it.", WARN)
        elif thin:
            noun = "sound has" if thin == 1 else "sounds have"
            self._set_readiness(
                f"Ready, but {thin} {noun} too little data and will be the "
                f"model's weak spot.", WARN)
        else:
            self._set_readiness("Ready to train. This takes a few minutes.",
                                t["accent"])
        self.train_btn.setEnabled(not running)

    def _set_readiness(self, text, color):
        self.readiness.setText(text)
        self.readiness.setStyleSheet(f"color: {color};")

    # ---- training --------------------------------------------------------

    def _on_train(self):
        name = self.name_input.text().strip()
        selected = self.checked_labels()
        try:
            name = library_ops.sanitize_name(name, kind="model name")
        except library_ops.LibraryOpError as exc:
            self._set_readiness(str(exc), BAD)
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
        self._best_accuracy = None
        self._stopped = False
        self._failed = False
        self._trained_name = name
        self.plot.clear()
        self.plot.setVisible(True)
        self.placeholder_box.setVisible(False)
        self.success_frame.setVisible(False)
        self.status.setText(
            f"Training “{name}” on {len(selected)} sounds… this usually takes a "
            f"few minutes.")
        self.train_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.labels_tree.setEnabled(False)
        self.name_input.setEnabled(False)
        self.worker = TrainingWorker(name, selected, self.net_spin.value())
        self.worker.epoch_complete.connect(self._on_epoch)
        self.worker.training_finished.connect(self._on_finished)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.start()

    def _on_stop(self):
        if self.worker:
            self._stopped = True
            self.status.setText("Stopping after this epoch…")
            self.worker.request_stop()

    def _on_epoch(self, epoch, loss, accuracy, _per_label, is_best):
        self.plot.add_point(epoch, loss, accuracy)
        if is_best or self._best_accuracy is None:
            self._best_accuracy = accuracy
        best = "  (new best)" if is_best else ""
        self.status.setText(
            f"Epoch {epoch + 1}  ·  loss {loss:.4f}  ·  accuracy {accuracy:.3f}{best}")

    def _on_finished(self):
        # The worker emits training_finished *after* error_occurred, so a failed
        # run arrives here too - with no model to celebrate.
        if self._failed:
            return
        self.worker = None
        self.stop_btn.setEnabled(False)
        self.labels_tree.setEnabled(True)
        self.name_input.setEnabled(True)
        self.app_state.models_changed.emit()
        name = self._trained_name
        if self._stopped and not library_ops.model_exists(name):
            self.status.setText("Training stopped - nothing was saved.")
            self._trained_name = None
            self._update_readiness()
            return
        self.status.setText("Training stopped." if self._stopped
                            else "Training complete.")
        self._show_success(name)

    def _on_error(self, message):
        self._failed = True
        self.worker = None
        self.stop_btn.setEnabled(False)
        self.labels_tree.setEnabled(True)
        self.name_input.setEnabled(True)
        self._trained_name = None
        self.status.setText(f"Training failed: {message}")
        self._update_readiness()

    def _show_success(self, name):
        acc = (f" It scored {self._best_accuracy:.1%} on its own held-back "
               f"samples." if self._best_accuracy is not None else "")
        self.success_title.setText(f"“{name}” is trained")
        self.success_body.setText(
            f"Saved to data/models.{acc} Test it to see whether it really tells "
            f"your sounds apart, then map the sounds to actions in the Talon tab.")
        self.success_frame.setVisible(True)
        self.train_row.setVisible(False)

    # ---- testing the fresh model ----------------------------------------

    def _model_path(self):
        if not self._trained_name:
            return None
        path = library_ops.model_pkl_path(self._trained_name)
        return path if os.path.isfile(path) else None

    def _on_test_live(self):
        path = self._model_path()
        if not path:
            return
        from gui.services import audio_devices
        from gui.widgets.model_test_dialogs import LiveTestDialog
        LiveTestDialog(self, self._trained_name, path,
                       audio_devices.input_index).exec()

    def _on_test_accuracy(self):
        path = self._model_path()
        if not path:
            return
        from gui.widgets.model_test_dialogs import AccuracyDialog
        AccuracyDialog(self, self._trained_name, path,
                       self.app_state.get_sound_labels()).exec()

    # ---- leaving ---------------------------------------------------------

    def _on_back(self):
        if self.worker is not None:
            answer = QMessageBox.question(
                self, "Stop training?",
                "Training is still running. Leave and stop it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
            self._on_stop()
        self.done.emit(self._trained_name or "")

    def refresh_theme(self):
        pass


def primary_button_style():
    """Accent-filled call to action - the same rank of button as the Sounds
    tab's 'Add recording' and the empty-state panels."""
    t = theme.colors()
    return (f"QPushButton#primaryAction {{ background-color: {t['accent']}; "
            f"color: {t['accent_text']}; font-weight: bold; border: none; "
            f"border-radius: 4px; padding: 6px 18px; }} "
            f"QPushButton#primaryAction:disabled {{ background-color: {t['button']}; "
            f"color: {t['text_dim']}; }}")
