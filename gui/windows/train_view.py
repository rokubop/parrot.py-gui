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
import re
import time
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QLineEdit,
    QSpinBox, QCheckBox, QTreeWidget, QTreeWidgetItem, QHeaderView, QFrame,
    QMessageBox, QStackedWidget, QProgressBar, QPlainTextEdit, QScrollArea,
    QMenu
)

from config.config import CLASSIFIER_FOLDER
from gui import theme
from gui.services import balance, keep_awake, library_ops
from gui.widgets import help_dialog
from gui.widgets.balance_column import (BalanceBarDelegate, balance_legend,
                                        BAR_ROLE)
from gui.widgets.per_label_accuracy import PerLabelAccuracy
from gui.widgets.training_plot import TrainingPlotWidget
from gui.workers.training_worker import TrainingWorker
from lib.print_status import get_quantity_rating

WARN = "#e0b020"
BAD = "#e05a5a"

STOP_HINT = "Stopping keeps the best model so far."
# Which one follows depends on whether the run got its sleep assertion.
AWAKE_HINT_HELD = "Sleep is held off until this ends. A closed lid still stops it."
AWAKE_HINT_MANUAL = "Leave it running and the machine has to stay awake."

# The column the balance delegate paints into.
BAR_COLUMN = 3

# Duplicated from AudioNetTrainer.max_epochs, deliberately. Reading the real one
# means importing lib.audio_net, which imports torch - one to two seconds, on a
# screen that has not decided to train anything yet. The run page does not guess:
# it takes the true ceiling from the worker's run_started signal.
MAX_EPOCHS = 300

# A full run prints tens of thousands of lines. Keeping the tail is what the
# view is for; keeping all of it is how a four hour run ends in swap.
LOG_MAX_LINES = 4000


class _PrepRow(QWidget):
    """One phase of getting the data ready: a name, a bar, and what it is on.

    The count comes from the trainer naming each label as it reaches it, so the
    bar only has a total once the selection is known - before that it is an
    honest indeterminate rather than a fake 0%.
    """

    def __init__(self, title, parent=None):
        super().__init__(parent)
        t = theme.colors()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.name = QLabel(title)
        self.name.setFixedWidth(140)
        self.name.setStyleSheet(f"color: {t['text_dim']};")
        row.addWidget(self.name)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(7)
        self.bar.setMaximumWidth(260)
        row.addWidget(self.bar)
        self.detail = QLabel("")
        self.detail.setStyleSheet(f"color: {t['text_dim']};")
        row.addWidget(self.detail, 1)
        self.set_idle()

    def set_idle(self):
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.detail.setText("")

    def set_progress(self, done, total, note=""):
        if total:
            self.bar.setRange(0, total)
            self.bar.setValue(done)
            self.detail.setText(f"{done} of {total}" + (f"  ·  {note}" if note else ""))
        else:
            self.bar.setRange(0, 0)      # indeterminate
            self.detail.setText(note)

    def set_done(self, note=""):
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.detail.setText(note)


class ModelSoundsWorker(QThread):
    """Reads which sounds an existing model was trained on.

    Off-thread because the answer lives inside a checkpoint: the first call also
    pays for importing torch, which is a second or two, and this runs from a
    click on a screen that has not otherwise touched it.
    """
    ready = pyqtSignal(str, object, str)   # model name, labels or None, error

    def __init__(self, app_state, model_name, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.model_name = model_name

    def run(self):
        try:
            facts = self.app_state.get_model_facts(self.model_name)
            self.ready.emit(self.model_name, facts["labels"], "")
        except Exception as exc:
            self.ready.emit(self.model_name, None,
                            f"{type(exc).__name__}: {exc}")


class BalanceWorker(QThread):
    """Asks the trainer what it would do with this selection, off the UI thread.

    ~164 ms for 20 sounds, and it runs again on every tick of the checklist, so
    it cannot be on the UI thread and cannot be un-debounced either.
    """
    ready = pyqtSignal(object, object, str)   # labels, plan or None, error

    def __init__(self, labels, parent=None):
        super().__init__(parent)
        self.labels = list(labels)

    def run(self):
        try:
            self.ready.emit(self.labels, balance.plan_for(self.labels), "")
        except Exception as exc:
            # A swallowed failure here leaves the Balance column on "…" forever,
            # which reads as "still working" rather than "this is broken".
            self.ready.emit(self.labels, None, f"{type(exc).__name__}: {exc}")

# There is deliberately no estimate before a run starts.
#
# There was one: audio seconds x nets x a constant, anchored on a single measured
# run of a different library on a different machine, printed as "roughly 5 hr 6
# min to 9 hr 27 min". Every part of that was a guess wearing a number - the
# constant, the assumed seconds per sound, and the machine it would run on - and
# a range 30% wide either side cannot be rescued by putting minutes on it.
#
# The run page still says how long it has left, because by then it is measured:
# every epoch does the same work, so elapsed time over completed epochs is a real
# prediction rather than a multiplier. See _update_eta.


def _next_free_name(base="my_model"):
    """`base`, or base_2, base_3... whichever is free.

    Strips a trailing _<number> off first, so suggesting an alternative to
    "totoro_2" offers "totoro_3" rather than "totoro_2_2".
    """
    stem = re.sub(r"_\d+$", "", base) or base
    # Only hand back the bare stem when that is what was asked for. Stripping
    # the suffix off "totoro_2" and offering "totoro" suggests a name that is
    # free but reads like going backwards, and could be one the user had
    # already deliberately moved on from.
    if base == stem and not library_ops.model_exists(base):
        return stem
    n = 2
    while library_ops.model_exists(f"{stem}_{n}"):
        n += 1
    return f"{stem}_{n}"


def _default_model_name():
    return _next_free_name()


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


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _today():
    """Built by hand for the same reason clock_time is: the platform format for
    a non-padded day differs between Windows and everything else."""
    now = datetime.now()
    return f"{_MONTHS[now.month - 1]} {now.day}, {now.year}"


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
        self._plan = None           # what the trainer would do with the ticked set
        self._plan_worker = None
        self._copy_worker = None
        self._best_epoch = None
        self._loaded_labels = []
        self._indexed_labels = []
        self._warned_files = []
        self._expected_labels = 0
        self._batch_high = 0        # highest batch number seen, so the bar has a total
        self._net_accuracy = {}
        # GUI thread only: the Windows assertion dies with its thread.
        self._awake = keep_awake.KeepAwake("Training a model")

        self._setup_ui()

        # Ticking a box changes which sounds set the target, so the whole plan
        # is stale on every click. Coalesce a burst of them into one pass.
        self._plan_timer = QTimer(self)
        self._plan_timer.setSingleShot(True)
        self._plan_timer.setInterval(220)
        self._plan_timer.timeout.connect(self._start_plan)

    # ---- entry point (called by MainWindow) ----------------------------

    def start(self):
        """Fresh training run: repopulate from disk and clear the last result."""
        if self.worker is not None:
            # Re-entered while a run is going ( left to Models and came back ).
            # Resetting here would wipe the state of a run still in progress.
            self.stack.setCurrentWidget(self.run_page)
            return
        self._reset_run_state()
        self.name_input.setText(_default_model_name())
        self._populate_labels(check_all=True)
        self._set_status("")
        self.eta.setText("")
        self._update_readiness()
        self.stack.setCurrentWidget(self.setup_page)

    def _reset_run_state(self):
        """Everything a previous run left behind. Called from both entry points -
        they had drifted into two near-identical copies of this list, and the run
        page has enough moving parts now that a third would be a matter of time."""
        self._best_accuracy = None
        self._best_epoch = None
        self._stopped = False
        self._failed = False
        self._trained_name = None
        self._max_epochs = None
        self._first_epoch = None
        self._loaded_labels = []
        self._indexed_labels = []
        self._warned_files = []
        self._expected_labels = 0
        self._batch_high = 0
        self._net_accuracy = {}

        self.plot.clear()
        self.plot.setVisible(False)
        self.per_label.clear()
        self.per_label_box.setVisible(False)
        self.waiting_box.setVisible(True)
        self.success_frame.setVisible(False)
        self.controls_row.setVisible(True)
        self.recover_row.setVisible(False)
        self.best_banner.setVisible(False)
        self.prep_box.setVisible(True)
        self.prep_read.set_idle()
        self.prep_index.set_idle()
        self.prep_warn.setVisible(False)
        self.net_strip.setText("")
        self.log_view.clear()
        self.view_stack.setCurrentIndex(0)
        self.mode_btn.setText("Show log")

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
        title = QLabel("New model")
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
        """The list and what it adds up to, side by side.

        This used to be decisions on the left and a teaching column on the right,
        where the middle teaching block was a bar chart of the very labels the
        checklist beside it was already listing. The chart moved into the list as
        a column; the space it freed holds a running answer to "what am I about
        to train", which is the one thing the old page never showed.
        """
        page = QWidget()
        columns = QHBoxLayout(page)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(22)
        columns.addWidget(self._build_sound_column(), 1)
        columns.addWidget(self._build_action_column(), 0)
        return page

    def _build_sound_column(self):
        t = theme.colors()
        col = QWidget()
        col.setMinimumWidth(520)
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        list_head = QHBoxLayout()
        sounds_title = QLabel("Sounds to include")
        sounds_title.setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {t['text_bright']};")
        list_head.addWidget(sounds_title)
        self.selected_count = QLabel("")
        self.selected_count.setStyleSheet(f"color: {t['text_dim']};")
        list_head.addWidget(self.selected_count)
        list_head.addStretch()
        quiet = (f"QPushButton {{ color: {t['text_dim']}; background: transparent; "
                 f"border: none; padding: 2px 6px; }} "
                 f"QPushButton:hover {{ color: {t['text_bright']}; }} "
                 f"QPushButton::menu-indicator {{ width: 0px; }}")

        # "The same sounds as last time" is the common case for a second model,
        # and picking 18 boxes by hand to get there is not a thing anyone should
        # be asked to do. Every model already knows its own label list.
        self.copy_btn = QPushButton("Use sounds from…")
        self.copy_btn.setFlat(True)
        self.copy_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.copy_btn.setStyleSheet(quiet)
        self.copy_menu = QMenu(self.copy_btn)
        self.copy_menu.aboutToShow.connect(self._fill_copy_menu)
        self.copy_btn.setMenu(self.copy_menu)
        list_head.addWidget(self.copy_btn)

        for text, checked in (("All", True), ("None", False)):
            btn = QPushButton(text)
            btn.setFlat(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setStyleSheet(quiet)
            btn.clicked.connect(lambda _c, on=checked: self._set_all_checked(on))
            list_head.addWidget(btn)
        v.addLayout(list_head)

        self.labels_tree = QTreeWidget()
        self.labels_tree.setColumnCount(4)
        self.labels_tree.setHeaderLabels(
            ["Sound", "Data", "Recorded", "What goes into training"])
        self.labels_tree.setRootIsDecorated(False)
        self.labels_tree.setUniformRowHeights(True)
        # A row is the unit here, not a cell. QTreeView draws current-item
        # decoration on one column unless told otherwise.
        self.labels_tree.setAllColumnsShowFocus(True)
        header = self.labels_tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2):
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        # The bar is the point of the table, so it gets the room rather than
        # whatever is left over.
        header.setSectionResizeMode(BAR_COLUMN, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(BAR_COLUMN, 300)
        self.labels_tree.setItemDelegateForColumn(BAR_COLUMN,
                                                  BalanceBarDelegate(self))
        self.labels_tree.itemChanged.connect(self._on_item_changed)
        v.addWidget(self.labels_tree, 1)

        # Only speaks after a copy, and only about that copy.
        self.copy_note = QLabel("")
        self.copy_note.setWordWrap(True)
        self.copy_note.setVisible(False)
        v.addWidget(self.copy_note)

        self.legend = balance_legend()
        v.addWidget(self.legend)
        return col

    # ---- borrowing another model's sound list ---------------------------

    def _fill_copy_menu(self):
        """Newest first, same order the Models tab lists them in. Built on open
        rather than once, because a run can finish while this screen is up."""
        self.copy_menu.clear()
        names = sorted(self.app_state.get_model_names(),
                       key=self.app_state.model_sort_key)
        if not names:
            self.copy_menu.addAction("No models yet").setEnabled(False)
            return
        for name in names:
            self.copy_menu.addAction(name).triggered.connect(
                lambda _checked=False, n=name: self._copy_sounds_from(n))

    def _copy_sounds_from(self, model_name):
        if self._copy_worker is not None and self._copy_worker.isRunning():
            return
        self.copy_note.setVisible(True)
        self.copy_note.setStyleSheet(f"color: {theme.colors()['text_dim']};")
        self.copy_note.setText(f"Reading what “{model_name}” was trained on…")
        self._copy_worker = ModelSoundsWorker(self.app_state, model_name, self)
        self._copy_worker.ready.connect(self._on_model_sounds)
        self._copy_worker.start()

    def _on_model_sounds(self, model_name, labels, error):
        t = theme.colors()
        self._copy_worker = None
        if error or not labels:
            self.copy_note.setStyleSheet(f"color: {WARN};")
            self.copy_note.setText(
                f"Could not read which sounds “{model_name}” used."
                + (f" {error}" if error else ""))
            return

        wanted = set(labels)
        have = set(self._items)
        matched = wanted & have
        # A model can name sounds whose recordings are gone - model-N knows
        # "buh", which no longer exists here. Say so rather than silently
        # training something narrower than what was asked for.
        missing = sorted(wanted - have)

        self.labels_tree.blockSignals(True)
        for label, item in self._items.items():
            item.setCheckState(0, Qt.CheckState.Checked if label in matched
                               else Qt.CheckState.Unchecked)
            self._paint_row_state(item)
        self.labels_tree.blockSignals(False)

        # A second model like the first one wants a name like the first one's,
        # and the overwrite gate would block the bare name anyway.
        self.name_input.setText(_next_free_name(model_name))

        noun = "sound" if len(matched) == 1 else "sounds"
        note = f"Using the {len(matched)} {noun} from “{model_name}”."
        if missing:
            named = [f"“{m}”" for m in missing]
            listed = (named[0] if len(named) == 1
                      else " and ".join([", ".join(named[:-1]), named[-1]]))
            note += (f"  It also used {listed}, which you no longer have "
                     f"recordings for.")
        self.copy_note.setStyleSheet(
            f"color: {WARN if missing else t['text_dim']};")
        self.copy_note.setText(note)
        self._update_readiness()
        self._plan_timer.start()

    def _build_action_column(self):
        """Name, what it adds up to, the two knobs, and the commitment.

        Everything here is a consequence of the ticking going on to the left, so
        it sits in one card rather than as rows stacked under the list - which is
        where they were, below the fold, on a page whose list is twenty rows long.
        """
        t = theme.colors()
        col = QWidget()
        col.setFixedWidth(310)
        outer = QVBoxLayout(col)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("actionCard")
        # The global QWidget rule paints an opaque $window box behind every
        # child, which is what gave the checkbox its own rectangle inside the
        # card. Children declare themselves transparent so the card shows through.
        card.setStyleSheet(
            f"QFrame#actionCard {{ background-color: {t['panel']}; "
            f"border: 1px solid {t['border']}; border-radius: 8px; }} "
            f"QFrame#actionCard > QLabel, QFrame#actionCard > QCheckBox {{ "
            f"background: transparent; border: none; }}")
        v = QVBoxLayout(card)
        v.setContentsMargins(18, 17, 18, 18)
        v.setSpacing(14)

        heading = QLabel("New model")
        heading.setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {t['text_bright']};")
        v.addWidget(heading)

        # Label rather than a placeholder: a placeholder disappears the moment
        # the field has anything in it, and this one arrives pre-filled, so the
        # field would have sat there unnamed from the first frame.
        name_group = QVBoxLayout()
        name_group.setSpacing(4)
        name_label = QLabel("Name")
        name_label.setStyleSheet(
            f"color: {t['text_dim']}; background: transparent;")
        name_group.addWidget(name_label)
        self.name_input = QLineEdit()
        self.name_input.setMinimumHeight(30)
        self.name_input.textChanged.connect(lambda _t: self._update_readiness())
        name_group.addWidget(self.name_input)
        v.addLayout(name_group)

        # Spelled out rather than "Nets". The word is the jargon, so the label
        # is the first chance to expand it and the help title does the rest.
        nets_group = QVBoxLayout()
        nets_group.setSpacing(4)
        nets_head = QHBoxLayout()
        nets_head.setSpacing(6)
        nets_label = QLabel("Neural networks")
        nets_label.setStyleSheet(f"color: {t['text_dim']}; background: transparent;")
        nets_head.addWidget(nets_label)
        nets_head.addWidget(help_dialog.help_button(self, "nets"))
        nets_head.addStretch()
        nets_group.addLayout(nets_head)
        self.net_spin = QSpinBox()
        self.net_spin.setRange(1, 10)
        self.net_spin.setValue(3)
        self.net_spin.setFixedWidth(74)
        self.net_spin.setMinimumHeight(28)
        self.net_spin.valueChanged.connect(self._on_nets_changed)
        nets_group.addWidget(self.net_spin, 0, Qt.AlignmentFlag.AlignLeft)
        v.addLayout(nets_group)

        # Disabled rather than silently useless where the platform can't.
        self.awake_check = QCheckBox("Keep computer awake")
        awake_why = keep_awake.unavailable_reason()
        self.awake_check.setChecked(awake_why is None)
        self.awake_check.setEnabled(awake_why is None)
        self.awake_check.setToolTip(
            awake_why or "Holds off sleep until the run ends. Closing a laptop "
            "lid still stops it.")
        v.addWidget(self.awake_check)

        summary_head = QLabel("Model summary")
        summary_head.setStyleSheet(
            f"color: {t['text_dim']}; background: transparent; "
            f"border-top: 1px solid {t['border']}; padding-top: 10px;")
        v.addWidget(summary_head)
        self.summary = QLabel("")
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        # Not wrapped: every value here is short, and wrapping made the rich
        # text table squeeze its columns until "Aug 1, 2026" broke over two
        # lines in a card with room to spare.
        self.summary.setWordWrap(False)
        v.addWidget(self.summary)

        self.readiness = QLabel("")
        self.readiness.setWordWrap(True)
        v.addWidget(self.readiness)

        self.train_btn = QPushButton("Start training")
        self.train_btn.setObjectName("primaryAction")
        self.train_btn.setMinimumHeight(38)
        self.train_btn.setStyleSheet(primary_button_style())
        self.train_btn.clicked.connect(self._on_train)
        v.addWidget(self.train_btn)

        # Only routes to Sounds when there is genuinely nothing to train on -
        # otherwise it competes with the one button that matters.
        self.to_sounds_btn = QPushButton("Go to Sounds")
        self.to_sounds_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.to_sounds_btn.clicked.connect(lambda: self.navigate.emit("Sounds"))
        v.addWidget(self.to_sounds_btn)

        outer.addWidget(card)
        outer.addWidget(self._build_tips())
        outer.addStretch(1)

        # The column is taller than a small window, and the list on the left is
        # what should get the height. Scrolling this keeps the button reachable
        # instead of clipped off the bottom.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(col)
        scroll.setFixedWidth(330)
        return scroll

    def _build_tips(self):
        """Below the card, not in it: these do not change with the choices above.

        Set in the ordinary text colour, not the dim one. Dim is what the app
        uses for things it is de-emphasising, and someone about to spend a night
        on this should read these once - "General info" in grey read as fine
        print, which is the opposite of the intent.
        """
        t = theme.colors()
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(2, 16, 2, 0)
        v.setSpacing(8)

        head = QLabel("Tips")
        head.setStyleSheet(
            f"color: {t['text_bright']}; font-weight: bold; "
            f"border-top: 1px solid {t['border']}; padding-top: 14px;")
        v.addWidget(head)
        for line in (
                "Uneven amounts are evened out with oversampling and "
                "undersampling. Repeating is capped at 2x, so a very thin "
                "sound still goes in light.",
                "Expect it to run for hours.",
                f"It runs {MAX_EPOCHS} epochs, but you can stop at any time and "
                f"keep the best model so far.",
                "More neural networks means more time to train."):
            row = QLabel(f"<span style='color:{t['text_dim']};'>·</span>  {line}")
            row.setWordWrap(True)
            row.setStyleSheet(f"color: {t['text']};")
            v.addWidget(row)
        return box

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

        # The one thing worth knowing at any moment of a run this long: there is
        # already a model on disk and it is this good. It used to flash past
        # inside the status line as "new best, saved" and be gone by the time
        # anyone looked, which is the opposite of reassuring at 2am.
        self.best_banner = QLabel("")
        self.best_banner.setWordWrap(True)
        self.best_banner.setVisible(False)
        self.best_banner.setStyleSheet(
            f"background-color: {t['panel']}; border: 1px solid {t['accent']}; "
            f"border-radius: 6px; padding: 7px 11px; color: {t['text']};")
        v.addWidget(self.best_banner)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {t['text_dim']};")
        v.addWidget(self.status)

        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 2, 0, 0)
        self.net_strip = QLabel("")
        self.net_strip.setStyleSheet(f"color: {t['text_dim']};")
        mode_row.addWidget(self.net_strip)
        mode_row.addStretch()
        self.mode_btn = QPushButton("Show log")
        self.mode_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.mode_btn.setToolTip(
            "The trainer's own output, exactly as the terminal shows it")
        self.mode_btn.clicked.connect(self._toggle_mode)
        mode_row.addWidget(self.mode_btn)
        v.addLayout(mode_row)

        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self._build_details_view())
        self.view_stack.addWidget(self._build_log_view())
        v.addWidget(self.view_stack, 1)

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
        # Second sentence is rewritten per run, in _on_train.
        self.sleep_hint = QLabel(STOP_HINT + " " + AWAKE_HINT_MANUAL)
        self.sleep_hint.setWordWrap(True)
        self.sleep_hint.setStyleSheet(f"color: {t['text_dim']};")
        controls.addWidget(self.sleep_hint)
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

    def _build_details_view(self):
        """Preparing, then curves. The two never overlap, so they share the space
        rather than one sitting empty while the other works."""
        t = theme.colors()
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        # Preparing. This phase was a single sentence and several blank minutes;
        # the trainer names every label twice while it runs, so it can be a list.
        self.prep_box = QWidget()
        prep = QVBoxLayout(self.prep_box)
        prep.setContentsMargins(0, 4, 0, 0)
        prep.setSpacing(5)
        self.prep_read = _PrepRow("Reading recordings")
        self.prep_index = _PrepRow("Indexing")
        prep.addWidget(self.prep_read)
        prep.addWidget(self.prep_index)
        self.prep_warn = QLabel("")
        self.prep_warn.setWordWrap(True)
        self.prep_warn.setVisible(False)
        self.prep_warn.setStyleSheet(
            f"color: {t['text_dim']}; border-left: 2px solid {WARN}; "
            f"padding: 3px 0 3px 10px;")
        prep.addWidget(self.prep_warn)
        prep.addStretch(1)
        v.addWidget(self.prep_box, 1)

        # Kept for the code that shows and hides it; the prep rows above are what
        # now fills the wait, so this is only the closing line.
        self.waiting_box = QWidget()
        wait_layout = QVBoxLayout(self.waiting_box)
        wait_layout.setContentsMargins(0, 0, 0, 0)
        self.waiting = QLabel("Curves appear once the first epoch finishes.")
        self.waiting.setStyleSheet(f"color: {t['text_dim']};")
        wait_layout.addWidget(self.waiting)
        v.addWidget(self.waiting_box)

        self.plot = TrainingPlotWidget()
        self.plot.setMinimumHeight(220)
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
        return page

    def _build_log_view(self):
        """The trainer's own output, unedited.

        Not a debug affordance: the structured view above is a reading of these
        lines, and when a number there looks wrong this is the thing to check it
        against. It is also where the exact terms live - the log says
        "using oversampling: +27%" while the table says Oversampled +27%.
        """
        t = theme.colors()
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(LOG_MAX_LINES)
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_view.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {t['plot_bg']}; "
            f"color: {t['text_dim']}; border: 1px solid {t['border']}; "
            f"border-radius: 6px; }}")
        font = self.log_view.font()
        font.setFamily("Consolas")
        font.setStyleHint(font.StyleHint.Monospace)
        self.log_view.setFont(font)
        return self.log_view

    def _toggle_mode(self):
        showing_log = self.view_stack.currentIndex() == 1
        self.view_stack.setCurrentIndex(0 if showing_log else 1)
        self.mode_btn.setText("Show log" if showing_log else "Show details")

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
        # Nothing on this screen depends on the number any more: the caption is
        # gone and the estimate it also fed went with it. Kept as the one place
        # to hang anything that comes to depend on it.
        pass

    # ---- sound checklist ------------------------------------------------

    def _populate_labels(self, check_all=False):
        checked = set() if check_all else set(self.checked_labels())
        t = theme.colors()
        self.labels_tree.blockSignals(True)
        self.labels_tree.clear()
        self._items = {}
        for label in self.app_state.get_sound_labels():
            ms = self.app_state.get_label_duration_ms(label)
            quantity, _percent, _next = get_quantity_rating(ms)
            item = QTreeWidgetItem([label, quantity, f"{ms / 1000:.0f}s", ""])
            item.setData(0, Qt.ItemDataRole.UserRole, label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked
                               if (check_all or label in checked)
                               else Qt.CheckState.Unchecked)
            if quantity == "Not enough":
                item.setToolTip(
                    1, "Under 17s of detected sound. It can still go in, but it "
                       "will be the model's weakest sound - record more of it, "
                       "or leave it out.")
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight
                                  | Qt.AlignmentFlag.AlignVCenter)
            self.labels_tree.addTopLevelItem(item)
            self._items[label] = item
            self._paint_row_state(item)
        self.labels_tree.blockSignals(False)
        self._plan = None
        self._plan_timer.start()

    def _paint_row_state(self, item):
        """A row that is out of the run should look out of the run.

        The tick box is 13 px in a 300 px row, so on its own it was the only
        thing that changed and the table looked inert. Excluded rows lose their
        rating colour and drop to the dim text, which reads as "not part of
        this" at a glance and puts the included ones back in the foreground.
        """
        t = theme.colors()
        checked = item.checkState(0) == Qt.CheckState.Checked
        rating = item.text(1)
        for col in range(self.labels_tree.columnCount()):
            if col == 1 and checked:
                colour = theme.QUANTITY_COLORS.get(rating) or t["text"]
            elif not checked:
                colour = t["text_faint"]
            elif col == 0:
                colour = t["text"]
            else:
                colour = t["text_dim"]
            item.setForeground(col, QColor(colour))

    def _on_item_changed(self, _item, column):
        # Only the tick box, which reports as column 0. Writing the Balance and
        # In-training columns also raises this signal, so reacting to every
        # column meant filling in the plan re-triggered computing the plan:
        # 20 rows x 4 writes = 80 callbacks per tick, each one re-reading every
        # selected label off disk.
        if column != 0:
            return
        self.labels_tree.blockSignals(True)
        self._paint_row_state(_item)
        self.labels_tree.blockSignals(False)
        self._update_readiness()
        self._plan_timer.start()

    # ---- what the trainer would do with this selection -------------------

    def _start_plan(self):
        selected = self.checked_labels()
        if len(selected) < 2:
            self._plan = None
            self._apply_plan(None)
            return
        if self._plan_worker is not None and self._plan_worker.isRunning():
            # A newer selection landed mid-flight; re-ask once it is back.
            self._plan_timer.start()
            return
        self._plan_worker = BalanceWorker(selected, self)
        self._plan_worker.ready.connect(self._on_plan)
        self._plan_worker.start()

    def _on_plan(self, labels, plan, error):
        self._plan_worker = None
        if error:
            self._plan = None
            self._clear_plan_columns()
            self.labels_tree.headerItem().setText(
                BAR_COLUMN, "What goes into training  (unavailable)")
            self.labels_tree.headerItem().setToolTip(
                BAR_COLUMN, f"Could not read the balance plan.\n{error}")
            return
        # The selection may have moved on while this was computing; ask again
        # for the set that is actually ticked now.
        if labels != self.checked_labels():
            self._plan_timer.start()
            return
        self._plan = plan
        self._apply_plan(plan)
        self._update_summary()

    def _clear_plan_columns(self):
        self.labels_tree.blockSignals(True)
        for item in self._items.values():
            item.setData(BAR_COLUMN, BAR_ROLE, None)
        self.labels_tree.blockSignals(False)
        self.labels_tree.viewport().update()

    def _apply_plan(self, plan):
        """Write the trainer's verdict into the Balance and In-training columns."""
        rows = {r["label"]: r for r in plan["rows"]} if plan else {}
        scale = max([max(r["size"], r["loaded"]) for r in rows.values()] or [0])
        target = plan["target"] if plan else 0
        self.labels_tree.blockSignals(True)
        for label, item in self._items.items():
            row = rows.get(label)
            if row is None:
                item.setData(BAR_COLUMN, BAR_ROLE, None)
                item.setToolTip(BAR_COLUMN, "")
                continue
            item.setData(BAR_COLUMN, BAR_ROLE,
                         (row["size"], row["loaded"], target, scale,
                          row["short"]))
            # The words live in the legend and in the log. On the row itself
            # they are one hover away, which is where a term you already know
            # belongs.
            item.setToolTip(BAR_COLUMN, self._bar_tooltip(row))
        self.labels_tree.blockSignals(False)
        self.labels_tree.viewport().update()

    @staticmethod
    def _bar_tooltip(row):
        if row["short"]:
            return (f"Oversampled +{row['percent']}%, and still only "
                    f"{row['share']:.0%} of the target.\nRepeating stops at 2x, "
                    f"so this goes in as one of the weakest sounds.\nMore of it "
                    f"is worth more than another net.")
        if row["strategy"] == "oversample":
            return (f"Oversampled +{row['percent']}% - repeated to reach the "
                    f"target.")
        if row["strategy"] == "undersample":
            return (f"Undersampled {row['percent']}% - the excess is left out "
                    f"of this run.")
        return "Sampled - used as recorded."

    def _set_all_checked(self, on):
        state = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
        self.labels_tree.blockSignals(True)
        for i in range(self.labels_tree.topLevelItemCount()):
            item = self.labels_tree.topLevelItem(i)
            item.setCheckState(0, state)
            # Signals are blocked, so _on_item_changed will not repaint these.
            self._paint_row_state(item)
        self.labels_tree.blockSignals(False)
        self._update_readiness()
        self._plan_timer.start()

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

        self.selected_count.setText(
            f"{len(selected)} of {total}" if total else "")
        name = self.name_input.text().strip()
        self.train_btn.setText(
            f"Start training “{name}”" if name else "Start training")
        self._update_summary()

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
        # Check the name the trainer would actually write, not the one typed.
        # Otherwise a name that sanitises down onto an existing one passes here
        # and only gets caught after the click.
        try:
            name = library_ops.sanitize_name(name, kind="model name")
        except library_ops.LibraryOpError as exc:
            self._set_readiness(str(exc), BAD)
            self.train_btn.setEnabled(False)
            return
        # Training a name that exists used to overwrite it behind one confirm.
        # The thing being overwritten is four to six hours old and may be the
        # model Talon is running right now, and the trainer starts destroying it
        # long before it has anything to put back. There is no undo, so this is
        # a wall rather than a warning.
        if library_ops.model_exists(name):
            self._set_readiness(
                f"“{name}” already exists. Models can't be overwritten - "
                f"try “{_next_free_name(name)}”.", BAD)
            self.train_btn.setEnabled(False)
            return

        thin = counts.get("Not enough", 0)
        if thin:
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

    def _update_summary(self):
        """What this model will be, read back before committing to it.

        Deliberately restates the net count that the spinner above already
        shows: this is the last thing read before a four hour button, and a
        summary that quietly omits a field is worse than one that repeats it.
        """
        t = theme.colors()
        selected = self.checked_labels()
        if not selected:
            self.summary.setText("")
            return
        seconds = sum(self.app_state.get_label_duration_ms(label)
                      for label in selected) / 1000.0
        nets = self.net_spin.value()
        minutes = round(seconds / 60)
        rows = [
            # Not "date trained" - nothing has been trained. This is the date it
            # would carry, which is what gets stamped into its checkpoints.
            ("Date", _today()),
            ("Sounds", f"{len(selected)}"),
            ("Recorded", f"{minutes} minute" + ("" if minutes == 1 else "s")),
            ("Neural networks", f"{nets}"),
        ]
        self.summary.setText(
            "<table cellspacing='0' cellpadding='1'>" + "".join(
                f"<tr><td style='color:{t['text_dim']}; padding-right:14px;'>"
                f"{k}</td><td style='color:{t['text_bright']};'>{val}</td></tr>"
                for k, val in rows) + "</table>")


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
            # The button is disabled for this, so reaching here means the
            # library changed under us - another window, or a run that finished
            # while this screen sat open. Re-running the gate is cheap; losing a
            # model to a stale enabled state is not.
            self._update_readiness()
            return

        os.makedirs(CLASSIFIER_FOLDER, exist_ok=True)
        self._reset_run_state()
        self._trained_name = name
        self._expected_labels = len(selected)

        nets = self.net_spin.value()
        noun = "sound" if len(selected) == 1 else "sounds"
        net_noun = ("neural network" if nets == 1 else "neural networks")
        self.run_title.setText(f"Training “{name}”")
        self.run_subtitle.setText(
            f"{len(selected)} {noun}  ·  {nets} {net_noun}  ·  started "
            f"{clock_time(datetime.now())}")
        self._set_status("")
        self.eta.setText("Working out how long this will take…")
        self.stack.setCurrentWidget(self.run_page)

        # Released by both endings, so it can't outlive the run.
        held = self.awake_check.isChecked() and self._awake.start()
        self.sleep_hint.setText(
            f"{STOP_HINT} {AWAKE_HINT_HELD if held else AWAKE_HINT_MANUAL}")

        self.train_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.worker = TrainingWorker(name, selected, nets)
        self.worker.stage_changed.connect(self._on_stage)
        self.worker.run_started.connect(self._on_run_started)
        self.worker.epoch_complete.connect(self._on_epoch)
        self.worker.training_finished.connect(self._on_finished)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.log_line.connect(self._on_log_line)
        self.worker.label_loaded.connect(self._on_label_loaded)
        self.worker.label_indexed.connect(self._on_label_indexed)
        self.worker.batch_progress.connect(self._on_batch)
        self.worker.net_validated.connect(self._on_net_validated)
        self.worker.data_warning.connect(self._on_data_warning)
        self.worker.start()

    # ---- what the trainer says while it prepares -------------------------

    def _on_log_line(self, line):
        self.log_view.appendPlainText(line)

    def _on_label_loaded(self, label, strategy, percent):
        self._loaded_labels.append(label)
        # The trainer's own words, so this line and the log agree.
        how = (f"{strategy}d {percent:+d}%"
               if strategy in ("oversample", "undersample") else "")
        self.prep_read.set_progress(len(self._loaded_labels),
                                    self._expected_labels,
                                    f"{label} {how}".strip())

    def _on_label_indexed(self, label):
        self._indexed_labels.append(label)
        if self._loaded_labels:
            self.prep_read.set_done(f"{len(self._loaded_labels)} sounds")
        # Silence is indexed alongside the chosen sounds, so it is one more than
        # the selection - counting it in keeps the bar from finishing early.
        self.prep_index.set_progress(len(self._indexed_labels),
                                     self._expected_labels + 1, label)

    def _on_data_warning(self, source, srt):
        self._warned_files.append((source, srt))
        count = len(self._warned_files)
        noun = "recording" if count == 1 else "recordings"
        names = ", ".join(sorted({os.path.basename(os.path.dirname(
            os.path.dirname(s))) or "?" for s, _ in self._warned_files}))
        self.prep_warn.setText(
            f"{count} {noun} have empty segment files and added nothing to this "
            f"run ({names}). Re-segment them from the Sounds tab.")
        self.prep_warn.setVisible(True)

    def _on_batch(self, net, epoch, batch, loss, accuracy):
        """The finest signal the trainer gives, and the only one during the long
        first epoch. Its own line rather than the status, which the epoch summary
        owns."""
        self._batch_high = max(self._batch_high, batch)
        nets = self.net_spin.value()
        self._set_status(
            f"Epoch {epoch + 1}   ·   net {net} of {nets}   ·   "
            f"batch {batch} of {self._batch_high}   ·   loss {loss:.3f}   ·   "
            f"accuracy {accuracy:.1%}")

    def _on_net_validated(self, net, accuracy):
        self._net_accuracy[net] = accuracy
        parts = [f"net {n} {a:.1%}" for n, a in sorted(self._net_accuracy.items())]
        # Worth showing separately from the average: a single net that has gone
        # bad is invisible in a mean, and it is the reason to have more than one.
        self.net_strip.setText("   ·   ".join(parts))

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
            self._best_epoch = epoch
            self._update_best_banner()
        if self._first_epoch is None:
            self._first_epoch = (epoch, now)
            self.waiting_box.setVisible(False)
            self.plot.setVisible(True)
            # Preparing is over for good once an epoch has landed.
            self.prep_box.setVisible(False)

        total = f" of {self._max_epochs}" if self._max_epochs else ""
        best = "   ·   new best, saved" if is_best else ""
        self._set_status(
            f"Epoch {epoch + 1}{total}   ·   loss {loss:.4f}   ·   "
            f"accuracy {accuracy:.1%}{best}")
        self._update_eta(epoch, now)

    def _update_best_banner(self):
        """There is a model on disk and it is this good.

        Stays up for the rest of the run, including after it ends. "New best,
        saved" used to appear inside the status line and be overwritten by the
        next epoch, so the answer to "have I got anything yet" was only ever
        visible for a few seconds at a time.
        """
        if self._best_accuracy is None:
            return
        at = f" at epoch {self._best_epoch + 1}" if self._best_epoch is not None else ""
        tail = ("Stopping now keeps it." if self.worker is not None
                else "Saved.")
        self.best_banner.setText(
            f"<b>Best so far {self._best_accuracy:.1%}</b>{at}. {tail}")
        self.best_banner.setVisible(True)

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
        # Above the early return: a failed run reaches here too.
        self._awake.stop()
        # The worker emits training_finished *after* error_occurred, so a failed
        # run arrives here too - with no model to celebrate.
        if self._failed:
            return
        self.worker = None
        self.stop_btn.setEnabled(False)
        name = self._trained_name
        # The banner reads "stopping now keeps it" while a run is live; nothing
        # is being stopped any more.
        self._update_best_banner()
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
        self._awake.stop()
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
