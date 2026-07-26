"""Dedicated training view, in two states.

Setting a run up and watching one have almost nothing in common, so this page
swaps between them rather than showing both at once. It used to be a form on the
left and a progress column on the right, which meant half the screen was an
empty pair of axes for the whole time you were making the only decision that
matters, and then a disabled form for the four to six hours after it.

**Setup** is the decisions on the left ( name, which sounds, how many nets ) and
the explanation of those decisions on the right. That is the treatment the New
sound dialog already gets: the advice sits where the choice is made rather than
behind a button, because the choice is what decides how good the model can ever
be. Here it also fills a column that had nothing in it.

**Running** drops the form to a one-line summary and gives the screen to the
things that answer "how is it going and when will it be done": an estimate that
is measured rather than guessed, the loss and accuracy curves, and per sound
accuracy, which the worker has always emitted and the view used to discard.
"""
import os
import time
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QLineEdit,
    QSpinBox, QTreeWidget, QTreeWidgetItem, QHeaderView, QFrame, QMessageBox,
    QStackedWidget, QScrollArea
)

from config.config import CLASSIFIER_FOLDER
from gui import theme
from gui.services import library_ops
from gui.widgets import help_dialog
from gui.widgets.balance_bars import BalanceBars
from gui.widgets.confirm_dialog import confirm_destructive
from gui.widgets.per_label_accuracy import PerLabelAccuracy
from gui.widgets.training_plot import TrainingPlotWidget
from gui.workers.training_worker import TrainingWorker
from lib.print_status import get_quantity_rating

WARN = "#e0b020"
BAD = "#e05a5a"

# Rough estimate for *before* a run starts, anchored on the only measured run
# there is: 14 sounds at 5 nets over 300 epochs took 4-6 hrs on a CPU-only torch
# build ( memory/training-takes-hours.md ). Training cost is linear in audio x
# nets x epochs, so this is seconds of training per second of detected audio per
# net over a full run. It assumes those 14 sounds held around 80 s each, which is
# the Excellent target rather than a measurement, and it knows nothing about this
# machine - so it is shown as a wide range, framed as rough, and replaced by a
# measured estimate a minute into the run.
TRAIN_SECONDS_PER_AUDIO_SECOND_PER_NET = 3.2
ESTIMATE_SPREAD = 0.3


def _default_model_name():
    base = "my_model"
    if not library_ops.model_exists(base):
        return base
    n = 2
    while library_ops.model_exists(f"{base}_{n}"):
        n += 1
    return f"{base}_{n}"


def format_duration(seconds):
    """Coarse on purpose: nothing here is accurate to the minute, and a running
    "4 hr 09 min" invites watching a number that does not deserve it."""
    if seconds < 90:
        return f"{int(seconds)} sec"
    minutes = int(round(seconds / 60))
    if minutes < 60:
        return f"{minutes} min"
    hours, mins = divmod(minutes, 60)
    if mins >= 55:          # round up rather than say "5 hr 58 min"
        hours, mins = hours + 1, 0
    elif mins < 5:
        mins = 0
    return f"{hours} hr" if mins == 0 else f"{hours} hr {mins} min"


def clock_time(when, now=None):
    """'3:40 am', or '3:40 am tomorrow' when the run crosses midnight - which is
    the whole question being asked when someone starts one of these at night.
    Built by hand because the platform format for a non-padded hour differs
    between Windows and everything else."""
    now = now or datetime.now()
    hour = when.hour % 12 or 12
    suffix = "am" if when.hour < 12 else "pm"
    text = f"{hour}:{when.minute:02d} {suffix}"
    days = (when.date() - now.date()).days
    if days == 1:
        return text + " tomorrow"
    if days > 1:
        return text + f" in {days} days"
    return text


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
        self._max_epochs = None
        self._first_epoch = None    # (epoch index, monotonic seconds) of the first
                                    # epoch to report back
        # Lives in the teaching column but is driven by the checklist, so it is
        # built before either of them.
        self.balance_bars = BalanceBars()

        self._setup_ui()

    # ---- entry point (called by MainWindow) ----------------------------

    def start(self):
        """Fresh training run: repopulate from disk and clear the last result."""
        if self.worker is not None:
            # Re-entered while a run is going ( left to Models and came back ).
            # Resetting here would wipe the state of a run still in progress.
            self.stack.setCurrentWidget(self.run_page)
            return
        self._best_accuracy = None
        self._stopped = False
        self._failed = False
        self._trained_name = None
        self._max_epochs = None
        self._first_epoch = None
        self.plot.clear()
        self.plot.setVisible(False)
        self.per_label.clear()
        self.per_label_box.setVisible(False)
        self.waiting_box.setVisible(True)
        self.success_frame.setVisible(False)
        self.controls_row.setVisible(True)
        self.recover_row.setVisible(False)
        self.name_input.setText(_default_model_name())
        self._populate_labels(check_all=True)
        self._set_status("")
        self.eta.setText("")
        self._update_readiness()
        self.stack.setCurrentWidget(self.setup_page)

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
        # Everything behind this is on the setup screen already; it is here for
        # reaching once a run is under way and that screen is gone.
        top.addWidget(help_dialog.training_help_button(self))
        root.addLayout(top)

        self.stack = QStackedWidget()
        self.setup_page = self._build_setup_page()
        self.run_page = self._build_run_page()
        self.stack.addWidget(self.setup_page)
        self.stack.addWidget(self.run_page)
        root.addWidget(self.stack, 1)

    # ---- setup state -----------------------------------------------------

    def _build_setup_page(self):
        page = QWidget()
        columns = QHBoxLayout(page)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(24)
        columns.addWidget(self._build_decision_column(), 0)
        columns.addWidget(self._build_teaching_column(), 1)
        return page

    def _build_teaching_column(self):
        """Three questions, three pictures, three lines: how it picks a sound,
        how much of each goes in, how many nets. The middle one is drawn from the
        sounds actually ticked, so it answers the question for this model rather
        than in general."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(help_dialog.training_sections(
            live={"balance": self.balance_bars}))
        return scroll

    def _build_decision_column(self):
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

        # Net count used to sit behind an "Advanced" disclosure, which read as
        # "you can ignore this". It is closer to the opposite: at 1 net a single
        # unlucky random start *is* the model, with nothing to outvote it. It is
        # a real decision, so it is on the page, with the diagram explaining what
        # averaging buys now sitting beside it rather than behind a button.
        nets_row = QHBoxLayout()
        nets_title = QLabel("Nets")
        nets_title.setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {t['text_bright']};")
        nets_row.addWidget(nets_title)
        self.net_spin = QSpinBox()
        self.net_spin.setRange(1, 10)
        self.net_spin.setValue(3)
        self.net_spin.valueChanged.connect(self._on_nets_changed)
        nets_row.addWidget(self.net_spin)
        usual = QLabel("3 is usual")
        usual.setStyleSheet(f"color: {t['text_dim']};")
        nets_row.addWidget(usual)
        nets_row.addStretch()
        v.addLayout(nets_row)

        self.nets_help = QLabel()
        self.nets_help.setWordWrap(True)
        self.nets_help.setStyleSheet(f"color: {t['text_dim']};")
        v.addWidget(self.nets_help)
        self._update_nets_help()

        self.readiness = QLabel("")
        self.readiness.setWordWrap(True)
        v.addWidget(self.readiness)

        self.estimate = QLabel("")
        self.estimate.setWordWrap(True)
        self.estimate.setStyleSheet(f"color: {t['text_dim']};")
        v.addWidget(self.estimate)

        self.train_row = QWidget()
        btn_row = QHBoxLayout(self.train_row)
        btn_row.setContentsMargins(0, 4, 0, 0)
        self.train_btn = QPushButton("Train")
        self.train_btn.setObjectName("primaryAction")
        self.train_btn.setMinimumHeight(34)
        self.train_btn.setStyleSheet(primary_button_style())
        self.train_btn.clicked.connect(self._on_train)
        btn_row.addWidget(self.train_btn)
        # Only route to Sounds when there is genuinely nothing to train on -
        # otherwise it competes with Train.
        self.to_sounds_btn = QPushButton("Go to Sounds")
        self.to_sounds_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.to_sounds_btn.clicked.connect(lambda: self.navigate.emit("Sounds"))
        btn_row.addWidget(self.to_sounds_btn)
        btn_row.addStretch()
        v.addWidget(self.train_row)
        return col

    # ---- running state ---------------------------------------------------

    def _build_run_page(self):
        t = theme.colors()
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        self.run_title = QLabel("")
        self.run_title.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {t['text_bright']};")
        v.addWidget(self.run_title)
        self.run_subtitle = QLabel("")
        self.run_subtitle.setStyleSheet(f"color: {t['text_dim']};")
        v.addWidget(self.run_subtitle)

        # The question actually being asked during a run of this length is "can
        # I go to bed", so it gets its own line and the accent colour.
        self.eta = QLabel("")
        self.eta.setWordWrap(True)
        self.eta.setStyleSheet(
            f"font-size: 15px; color: {t['accent']}; margin-top: 4px;")
        v.addWidget(self.eta)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {t['text_dim']};")
        v.addWidget(self.status)

        # Nothing exists to plot until the first epoch reports, and reading and
        # measuring a large library before it can take minutes. An empty pair of
        # axes for that whole time is the thing this rebuild set out to remove,
        # so the curves and the bars only appear once they have something in them.
        self.waiting = help_dialog.WrappedBody(
            "Curves and per sound bars appear after the first epoch.")
        self.waiting.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Centred in a stretchy box, a wrapped label otherwise takes its own
        # narrow sizeHint width and comes out as a tall thin ribbon.
        self.waiting.setMinimumWidth(460)
        self.waiting.setMaximumWidth(520)
        self.waiting.setStyleSheet(f"color: {t['text_dim']};")
        self.waiting_box = QWidget()
        wait_layout = QVBoxLayout(self.waiting_box)
        wait_layout.setContentsMargins(0, 0, 0, 0)
        wait_layout.addStretch()
        wait_layout.addWidget(self.waiting, 0, Qt.AlignmentFlag.AlignHCenter)
        wait_layout.addStretch()
        v.addWidget(self.waiting_box, 1)

        self.plot = TrainingPlotWidget()
        self.plot.setMinimumHeight(240)
        self.plot.setVisible(False)
        v.addWidget(self.plot, 1)

        self.per_label_box = QWidget()
        per_label_layout = QVBoxLayout(self.per_label_box)
        per_label_layout.setContentsMargins(0, 0, 0, 0)
        per_label_layout.setSpacing(4)
        per_label_title = QLabel("Accuracy by sound")
        per_label_title.setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {t['text_bright']}; "
            f"margin-top: 6px;")
        per_label_layout.addWidget(per_label_title)
        self.per_label = PerLabelAccuracy()
        per_label_layout.addWidget(self.per_label)
        self.per_label_box.setVisible(False)
        v.addWidget(self.per_label_box)

        self.controls_row = QWidget()
        controls = QVBoxLayout(self.controls_row)
        controls.setContentsMargins(0, 8, 0, 0)
        controls.setSpacing(4)
        stop_row = QHBoxLayout()
        self.stop_btn = QPushButton("Stop and keep the best model so far")
        self.stop_btn.setMinimumHeight(32)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.stop_btn.setToolTip("Finish after this epoch and keep the best model so far")
        self.stop_btn.clicked.connect(self._on_stop)
        stop_row.addWidget(self.stop_btn)
        stop_row.addStretch()
        controls.addLayout(stop_row)
        hint = QLabel("Stopping keeps the best model so far. Leave it running "
                      "and the machine has to stay awake.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {t['text_dim']};")
        controls.addWidget(hint)
        v.addWidget(self.controls_row)

        # Shown instead of the controls when a run ends with nothing to show for
        # it, so the only way back is not the browser-style Back button.
        self.recover_row = QWidget()
        recover = QHBoxLayout(self.recover_row)
        recover.setContentsMargins(0, 8, 0, 0)
        back_to_setup = QPushButton("← Change something and try again")
        back_to_setup.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        back_to_setup.clicked.connect(self._back_to_setup)
        recover.addWidget(back_to_setup)
        recover.addStretch()
        self.recover_row.setVisible(False)
        v.addWidget(self.recover_row)

        self.success_frame = self._build_success_frame()
        self.success_frame.setVisible(False)
        v.addWidget(self.success_frame)
        return page

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

    def _on_nets_changed(self, _value):
        self._update_nets_help()
        self._update_estimate()

    def _update_nets_help(self):
        """The diagram beside the spinner carries the argument; this only has to
        say what the number in the box means."""
        count = self.net_spin.value()
        self.nets_help.setText(
            "One net decides on its own." if count == 1
            else f"{count} nets vote. About {count}x the time of one.")

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

        if selected:
            pairs = [(label, self.app_state.get_label_duration_ms(label))
                     for label in selected]
            noun = "sound" if len(selected) == 1 else "sounds"
            self.summary.setText(
                f"{len(selected)} {noun} selected  ·  "
                f"{help_dialog.quantity_summary(pairs)}")
        else:
            self.summary.setText("")
        self._update_estimate()

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
            # All-thin is a different situation from one weak sound: there is no
            # strong sound left for it to be weak *against*.
            warning = help_dialog.thin_data_warning(thin, len(selected))
            self._set_readiness(
                "Ready, but " + warning[0].lower() + warning[1:], WARN)
        else:
            self._set_readiness("Ready to train.", t["accent"])
        self.train_btn.setEnabled(not running)

    def _set_readiness(self, text, color):
        self.readiness.setText(text)
        self.readiness.setStyleSheet(f"color: {color};")

    def _update_estimate(self):
        """How long this will take, before committing to it. "Hours" was all the
        page said, which is not enough to decide whether to start it at 11pm. A
        measured version replaces it a minute into the run, so this does not need
        to explain itself."""
        selected = self.checked_labels()
        pairs = [(label, self.app_state.get_label_duration_ms(label) / 1000.0)
                 for label in selected]
        self.balance_bars.set_pairs(pairs)
        if len(selected) < 2:
            self.estimate.setText("")
            return
        middle = (sum(seconds for _label, seconds in pairs)
                  * TRAIN_SECONDS_PER_AUDIO_SECOND_PER_NET
                  * self.net_spin.value())
        low = format_duration(middle * (1 - ESTIMATE_SPREAD))
        high = format_duration(middle * (1 + ESTIMATE_SPREAD))
        self.estimate.setText(
            f"Roughly {low} to {high}. Keep the machine awake for it.")

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
        self._max_epochs = None
        self._first_epoch = None
        self.plot.clear()
        self.plot.setVisible(False)
        self.per_label.clear()
        self.per_label_box.setVisible(False)
        self.waiting_box.setVisible(True)
        self.success_frame.setVisible(False)
        self.controls_row.setVisible(True)
        self.recover_row.setVisible(False)

        nets = self.net_spin.value()
        noun = "sound" if len(selected) == 1 else "sounds"
        net_noun = "net" if nets == 1 else "nets"
        self.run_title.setText(f"Training “{name}”")
        self.run_subtitle.setText(
            f"{len(selected)} {noun}  ·  {nets} {net_noun}  ·  started "
            f"{clock_time(datetime.now())}")
        self._set_status("")
        self.eta.setText("Working out how long this will take…")
        self.stack.setCurrentWidget(self.run_page)

        self.train_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.worker = TrainingWorker(name, selected, nets)
        self.worker.stage_changed.connect(self._on_stage)
        self.worker.run_started.connect(self._on_run_started)
        self.worker.epoch_complete.connect(self._on_epoch)
        self.worker.training_finished.connect(self._on_finished)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.start()

    def _on_stop(self):
        if self.worker:
            self._stopped = True
            self._set_status("Stopping after this epoch…")
            self.worker.request_stop()

    def _set_status(self, text, color=None):
        self.status.setText(text)
        self.status.setStyleSheet(
            f"color: {color or theme.colors()['text_dim']};")

    def _on_stage(self, message):
        self._set_status(message)

    def _on_run_started(self, max_epochs):
        self._max_epochs = max_epochs
        self._set_status(f"Training, up to {max_epochs} epochs.")

    def _on_epoch(self, epoch, loss, accuracy, per_label, is_best):
        now = time.monotonic()
        self.plot.add_point(epoch, loss, accuracy)
        if per_label:
            self.per_label.set_values(per_label)
            self.per_label_box.setVisible(True)
        if is_best or self._best_accuracy is None:
            self._best_accuracy = accuracy
        if self._first_epoch is None:
            self._first_epoch = (epoch, now)
            self.waiting_box.setVisible(False)
            self.plot.setVisible(True)

        total = f" of {self._max_epochs}" if self._max_epochs else ""
        best = "   ·   new best, saved" if is_best else ""
        self._set_status(
            f"Epoch {epoch + 1}{total}   ·   loss {loss:.4f}   ·   "
            f"accuracy {accuracy:.1%}{best}")
        self._update_eta(epoch, now)

    def _update_eta(self, epoch, now):
        """Measured, not guessed: every epoch does the same work, so the time the
        run has already taken is the best predictor of the time it has left. Timed
        from the *first reported epoch* rather than from the click, because
        reading and feature-extracting the recordings happens before it and would
        inflate every estimate after it."""
        first_epoch, first_time = self._first_epoch
        completed = epoch - first_epoch
        if not self._max_epochs or completed < 1:
            self.eta.setText("Timing the first epochs…")
            return
        per_epoch = (now - first_time) / completed
        remaining = max(0, self._max_epochs - (epoch + 1)) * per_epoch
        if remaining <= 0:
            self.eta.setText("Finishing up…")
            return
        finish = datetime.now() + timedelta(seconds=remaining)
        self.eta.setText(
            f"About {format_duration(remaining)} left if it runs to the end, "
            f"finishing around {clock_time(finish)}.")

    def _on_finished(self):
        # The worker emits training_finished *after* error_occurred, so a failed
        # run arrives here too - with no model to celebrate.
        if self._failed:
            return
        self.worker = None
        self.stop_btn.setEnabled(False)
        name = self._trained_name
        self.app_state.models_changed.emit()
        if self._stopped and not library_ops.model_exists(name):
            self.eta.setText("")
            self._set_status(
                "Stopped before the first epoch finished, so there was no model "
                "to save yet.")
            self._trained_name = None
            self.controls_row.setVisible(False)
            self.recover_row.setVisible(True)
            self._update_readiness()
            return
        self.eta.setText("")
        self._set_status("Training stopped." if self._stopped
                            else "Training complete.")
        # The heading has been reading "Training ..." in the present tense for
        # however many hours; it should not still say so once it is over.
        self.run_title.setText(f"Trained “{name}”")
        self._show_success(name)

    def _on_error(self, message):
        self._failed = True
        self.worker = None
        self.stop_btn.setEnabled(False)
        name = self._trained_name
        self._trained_name = None
        self.eta.setText("")
        if name:
            self.run_title.setText(f"“{name}” did not train")
        self._set_status(f"Training failed: {message}", BAD)
        self.controls_row.setVisible(False)
        self.recover_row.setVisible(True)
        self._update_readiness()

    def _back_to_setup(self):
        self._update_readiness()
        self.stack.setCurrentWidget(self.setup_page)

    def _show_success(self, name):
        acc = (f" It scored {self._best_accuracy:.1%} on its own held-back "
               f"samples." if self._best_accuracy is not None else "")
        self.success_title.setText(f"“{name}” is trained")
        self.success_body.setText(
            f"Saved to {CLASSIFIER_FOLDER}.{acc} Test it to see whether it really tells "
            f"your sounds apart, then map the sounds to actions in the Talon tab.")
        self.success_frame.setVisible(True)
        self.controls_row.setVisible(False)

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
