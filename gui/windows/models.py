"""Models tab - the library of trained models.

Shaped like the Sounds tab: a three-column list on the left with one primary
action under it, and a header panel on the right carrying the selected model's
identity, the two actions that answer "does it work?" (Test live / Test
accuracy), and a quiet row of management actions. Training itself is a sub-view
(train_view.py), so a user with no models sees an empty state and a single call
to action instead of a disabled details panel.

The list answers the questions someone has after months away - which one is
Talon running, which did I make last, does it know the sounds I record, what
does it cost to run - so it carries a date, a sound count, a net count and a
live tick, newest first.

Net count belongs here rather than only on the training page: every net runs on
every frame and the scores are averaged (TinyAudioNetEnsemble.forward), so it is
not a spent training decision but part of what the model costs to run. Hence
"5 nets averaged" rather than a bare "5 nets", which reads as a spec.

The "~2% of a CPU core per net" figure this file used to quote is not repeated
in any user-facing string, here or in the help: nobody has measured it on a
machine we can name. Put it back once someone has.

Destructive actions (delete) go through the two-step confirm dialog.
"""
import os
import time
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QListWidget, QListWidgetItem, QPushButton, QSplitter,
    QLineEdit, QInputDialog, QMessageBox, QScrollArea, QFrame, QDialog
)

from config.config import CLASSIFIER_FOLDER
from gui import theme
from gui.services import library_ops
from gui.widgets.confirm_dialog import confirm_destructive
from gui.widgets import help_dialog
from gui.windows.train_view import primary_button_style
from gui.workers.combine_worker import CombineWorker
from lib.print_status import get_quantity_rating

WARN = "#e0b020"


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


UNSURE_DATE_TIP = ("File date, not a training record. Copying or restoring "
                   "your data folder resets it.\nModels trained from now on "
                   "carry their real date inside the file.")


def _trained_when(when, source="checkpoint"):
    """Aimed at someone opening this after months away, so the anchor is the
    date, not "313 days ago". Always carries the year: a bare "Aug 22" reads as
    this year, and the gap between sessions here is measured in months. Relative
    only for the week where it beats a date at answering "is this the one I just
    made?".

    A "mtime" source is the file's date rather than a record of training, so it
    gets a ~ and never a relative form - "Yesterday" claims a precision we do
    not have, where "~Feb 22, 2026" reads as the approximation it is.
    """
    if not when:
        return ""
    stamp = time.localtime(when)
    on_date = f"{_MONTHS[stamp.tm_mon - 1]} {stamp.tm_mday}, {stamp.tm_year}"
    if source == "mtime":
        return f"~{on_date}"
    days = int((time.time() - when) // 86400)
    if days <= 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    if days < 7:
        return f"{days} days ago"
    return on_date


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


class FactsWorker(QThread):
    """Read what a checkpoint knows - sounds, and when it was trained - off the
    UI thread, emitting one model at a time so the columns fill in from the top
    rather than all at the end."""
    counted = pyqtSignal(str, list, object, object)

    def __init__(self, app_state, names, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.names = list(names)

    def run(self):
        for name in self.names:
            try:
                facts = self.app_state.get_model_facts(name)
            except Exception:
                facts = {"labels": [], "trained_at": None,
                         "trained_at_source": None}
            self.counted.emit(name, facts["labels"], facts["trained_at"],
                              facts["trained_at_source"])


class ModelsPage(QWidget):
    train_requested = pyqtSignal()   # open the training sub-view
    navigate = pyqtSignal(str)       # jump to another tab

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.inspect_worker = None
        self.combine_worker = None
        self.count_worker = None
        self._current = None
        self._dates_moved = False
        self._loaded = {}     # model name -> labels ([] = unreadable)
        self._inspected = {}  # model name -> full metadata, accuracy included
        self._items = {}      # model name -> its row

        self._setup_ui()
        self._populate_models()
        self.app_state.models_changed.connect(self._on_models_changed)
        self.app_state.recordings_changed.connect(self._refresh_details)

    # ---- ui ------------------------------------------------------------

    def _setup_ui(self):
        t = theme.colors()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # Left: the models, with the one action that creates another.
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 8, 12)
        title_row = QHBoxLayout()
        title = QLabel("Models")
        title.setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {t['text_bright']};")
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(help_dialog.help_button(self, "train"))
        left_layout.addLayout(title_row)
        self.model_list = QTreeWidget()
        self.model_list.setColumnCount(5)
        self.model_list.setHeaderLabels(
            ["Model", "Trained", "Sounds", "Nets", "Live"])
        self.model_list.setRootIsDecorated(False)
        self.model_list.setUniformRowHeights(True)
        self.model_list.setAllColumnsShowFocus(True)
        head = self.model_list.headerItem()
        head.setToolTip(2, "How many sounds this model can tell apart")
        head.setToolTip(3, "How many neural networks this model owns.\n"
                           "Every one of them is consulted on every sound, and "
                           "their scores are averaged.")
        head.setToolTip(4, "Which model Talon is running right now")
        header = self.model_list.header()
        # Left to itself the header stretches the *last* section as well as the
        # one asked for, and the two together overflow the pane - the last
        # column ends up past the right edge behind a scrollbar.
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3, 4):
            header.setSectionResizeMode(col,
                                        QHeaderView.ResizeMode.ResizeToContents)
        self.model_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.model_list.currentItemChanged.connect(self._on_select)
        left_layout.addWidget(self.model_list)

        # "+ New model", to the Sounds tab's "+ New sound" - the two lists are
        # built the same way and their one primary action should read the same.
        #
        # Plain, for the same reason "+ New sound" is. The accent marks the main
        # action of the panel you are looking at, and this tab's is Test live;
        # an accent-filled footer button gave the Models tab two of them
        # competing. Training's accent belongs on Start training, where the four
        # hours are actually committed to.
        self.train_btn = QPushButton("+ New model")
        self.train_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.train_btn.setToolTip("Train a new model from your recorded sounds")
        self.train_btn.clicked.connect(self.train_requested.emit)
        left_layout.addWidget(self.train_btn)

        # Four columns, three of them sized to their contents, leave the name
        # whatever is left - so the pane is wider than the Sounds tab's.
        left.setMinimumWidth(320)
        splitter.addWidget(left)

        # Right: per-model header panel + scrollable detail body.
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self._build_header())

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(20, 16, 24, 16)
        self.body_layout.setSpacing(12)
        self.detail_body = QLabel("")
        self.detail_body.setWordWrap(True)
        self.detail_body.setTextFormat(Qt.TextFormat.RichText)
        self.detail_body.setStyleSheet(f"color: {t['text']};")
        self.detail_body.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.body_layout.addWidget(self.detail_body)
        # The empty panel lives inside its own springy wrapper so it sits in the
        # middle of the card area; with it hidden the wrapper collapses and the
        # trailing stretch keeps the model details at the top.
        self.empty_panel = self._build_empty_panel()
        self.empty_wrapper = QWidget()
        wrap = QVBoxLayout(self.empty_wrapper)
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.addStretch()
        wrap.addWidget(self.empty_panel, 0, Qt.AlignmentFlag.AlignHCenter)
        wrap.addStretch()
        self.body_layout.addWidget(self.empty_wrapper, 1)
        self.body_layout.addStretch()
        self.scroll.setWidget(body)
        right_layout.addWidget(self.scroll)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([400, 800])

    def _build_header(self):
        """The selected model's identity, then its actions in two ranks: the two
        that answer 'does it work?' first, management second."""
        t = theme.colors()
        header = QFrame()
        header.setObjectName("modelHeader")
        header.setStyleSheet(
            f"QFrame#modelHeader {{ background-color: {t['toolbar']}; "
            f"border-bottom: 1px solid {t['border']}; }}")
        self.header_frame = header
        v = QVBoxLayout(header)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(2)

        self.detail_title = QLabel("")
        self.detail_title.setStyleSheet(
            f"font-size: 20px; font-weight: bold; color: {t['text_bright']};")
        v.addWidget(self.detail_title)
        self.detail_stats = QLabel("")
        self.detail_stats.setStyleSheet(f"color: {t['text_dim']};")
        v.addWidget(self.detail_stats)
        self.stale_label = QLabel("")
        self.stale_label.setWordWrap(True)
        self.stale_label.setStyleSheet(f"color: {WARN}; margin-top: 2px;")
        v.addWidget(self.stale_label)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 10, 0, 0)
        self.live_test_btn = QPushButton("Test live")
        self.live_test_btn.setObjectName("primaryAction")
        self.live_test_btn.setMinimumHeight(34)
        self.live_test_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.live_test_btn.setStyleSheet(primary_button_style())
        self.live_test_btn.setToolTip(
            "Make each sound into the mic and watch the raw per-sound probabilities")
        self.live_test_btn.clicked.connect(self._on_test_live)
        actions.addWidget(self.live_test_btn)
        self.accuracy_btn = QPushButton("Test accuracy")
        self.accuracy_btn.setMinimumHeight(34)
        self.accuracy_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.accuracy_btn.setToolTip(
            "Classify every sound's recorded segments with this model")
        self.accuracy_btn.clicked.connect(self._on_test_accuracy)
        actions.addWidget(self.accuracy_btn)
        actions.addStretch()
        v.addLayout(actions)

        secondary = QHBoxLayout()
        secondary.setContentsMargins(0, 4, 0, 0)
        self._secondary_btns = []
        for text, slot, tip in (
                ("Rename", self._on_rename, "Rename this model"),
                ("Clone", self._on_clone, "Make a copy under a new name"),
                ("Combine…", self._on_combine,
                 "Merge two or more models into one ensemble"),
                ("Open folder", self._on_open_folder, "Reveal data/models"),
                ("Delete", self._on_delete, "Delete this model and its files")):
            btn = QPushButton(text)
            btn.setObjectName("secondaryAction")
            btn.setFlat(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setToolTip(tip)
            btn.setStyleSheet(
                f"QPushButton#secondaryAction {{ color: {t['text_dim']}; border: none; "
                f"background: transparent; padding: 3px 8px; }} "
                f"QPushButton#secondaryAction:hover {{ color: {t['text_bright']}; }}")
            btn.clicked.connect(slot)
            secondary.addWidget(btn)
            self._secondary_btns.append(btn)
        secondary.addStretch()
        v.addLayout(secondary)
        return header

    # Measure line length for the empty-state body copy, as on the Sounds tab.
    _EMPTY_BODY_WIDTH = 460

    def _set_empty_body(self, text):
        """A word-wrapped QLabel reports a one-line sizeHint, so a layout that
        isn't asked for heightForWidth clips it. Pin the width (done once) and
        re-ask for the height this particular copy needs."""
        self.empty_body.setText(text)
        self.empty_body.setMinimumHeight(
            self.empty_body.heightForWidth(self._EMPTY_BODY_WIDTH))

    def _build_empty_panel(self):
        """Centered title/body/action, same shape as the Sounds tab's empty
        states. Its text is filled in per case by _show_empty_state."""
        t = theme.colors()
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(8)

        self.empty_title = QLabel("")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title.setStyleSheet(
            f"font-size: 17px; font-weight: bold; color: {t['text_bright']};")
        v.addWidget(self.empty_title)

        self.empty_body = QLabel("")
        self.empty_body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_body.setWordWrap(True)
        self.empty_body.setFixedWidth(self._EMPTY_BODY_WIDTH)
        self.empty_body.setStyleSheet(f"color: {t['text_dim']};")
        v.addWidget(self.empty_body, 0, Qt.AlignmentFlag.AlignHCenter)

        self.empty_btn = QPushButton("")
        self.empty_btn.setObjectName("primaryAction")
        self.empty_btn.setMinimumHeight(34)
        self.empty_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.empty_btn.setStyleSheet(primary_button_style())
        v.addSpacing(6)
        v.addWidget(self.empty_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        return panel

    def refresh_theme(self):
        pass

    # ---- model list ----------------------------------------------------

    def _on_models_changed(self):
        self._loaded.clear()
        self._inspected.clear()
        self._populate_models()

    def _order(self, meta):
        # The rule itself lives on AppState: the training page's "use sounds
        # from" menu lists the same models and has to agree with this.
        return self.app_state.model_sort_key(meta["name"])

    def _populate_models(self):
        """Newest first. Someone coming back after months wants the one they
        made last, and it is also what Talon falls back to - alphabetical put
        that answer in an arbitrary row."""
        prev = self._current
        t = theme.colors()
        live = self.app_state.get_talon_model_name()
        details = sorted(self.app_state.get_all_model_details(),
                         key=self._order)

        self.model_list.blockSignals(True)
        self.model_list.clear()
        self._items = {}
        for meta in details:
            name = meta["name"]
            item = QTreeWidgetItem([
                name,
                _trained_when(meta["trained_at"], meta["trained_at_source"]),
                str(len(self._loaded[name])) if name in self._loaded else "…",
                str(meta["net_count"]) if meta["net_count"] else "",
                "✓" if name == live else "",
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, name)
            for col in (2, 3):
                item.setTextAlignment(col, Qt.AlignmentFlag.AlignRight
                                      | Qt.AlignmentFlag.AlignVCenter)
            item.setTextAlignment(4, Qt.AlignmentFlag.AlignCenter)
            for col in (1, 2, 3):
                item.setForeground(col, QColor(t["text_dim"]))
            item.setForeground(4, QColor(t["accent"]))
            # A long name is elided in this column, so keep the whole one
            # reachable on hover.
            item.setToolTip(0, name)
            if meta["trained_at_source"] == "mtime":
                item.setToolTip(1, UNSURE_DATE_TIP)
            if name == live:
                item.setToolTip(4, "Talon is running this model")
            self.model_list.addTopLevelItem(item)
            self._items[name] = item
        self.model_list.blockSignals(False)

        if self.model_list.topLevelItemCount() == 0:
            self._current = None
            self._refresh_details()
            return
        target = self._items.get(prev) or self.model_list.topLevelItem(0)
        self.model_list.setCurrentItem(target)
        self._start_counting([m["name"] for m in details])

    def select_model(self, name):
        """Called after training so the fresh model is the one on screen."""
        item = self._items.get(name)
        if item is not None:
            self.model_list.setCurrentItem(item)

    def _on_select(self, current, _prev=None):
        self._current = (current.data(0, Qt.ItemDataRole.UserRole)
                         if current is not None else None)
        self._refresh_details()

    # ---- the Sounds and Trained columns ---------------------------------

    def _start_counting(self, names):
        """Fill the Sounds column, and correct Trained, off-thread. Both come
        out of a file read, so they arrive after the list rather than holding
        it up."""
        pending = [n for n in names if n not in self._loaded]
        if not pending:
            return
        if self.count_worker is not None and self.count_worker.isRunning():
            return
        self._dates_moved = False
        self.count_worker = FactsWorker(self.app_state, pending, self)
        self.count_worker.counted.connect(self._on_counted)
        self.count_worker.finished.connect(self._on_counting_done)
        self.count_worker.start()

    def _on_counted(self, name, labels, trained_at, source):
        self._loaded[name] = labels
        item = self._items.get(name)
        if item is not None:
            item.setText(2, str(len(labels)) if labels else "?")
            was = item.text(1)
            now = _trained_when(trained_at, source)
            if now and now != was:
                item.setText(1, now)
                item.setToolTip(1, UNSURE_DATE_TIP if source == "mtime" else "")
                self._dates_moved = True
        if name == self._current:
            self._refresh_details()

    def _on_counting_done(self):
        self.count_worker = None
        if self._dates_moved:
            # A checkpoint knew better than the mtime the rows were sorted on.
            # Re-sort once, at the end, rather than letting rows jump about as
            # each read lands.
            self._dates_moved = False
            self._populate_models()
            return
        # Models can appear while a sweep is running (training finishes), and
        # that populate found the worker busy. Sweep again for whatever is left.
        self._start_counting(list(self._items))

    # ---- details --------------------------------------------------------

    def _refresh_details(self):
        if self._current is None:
            self._show_empty_state()
            return
        self.header_frame.setVisible(True)
        self.empty_wrapper.setVisible(False)
        self.detail_body.setVisible(True)
        self.train_btn.setEnabled(True)

        # The accuracy only exists once the checkpoints have been read, so use
        # the inspected copy when it has arrived and the cheap one until then -
        # asking for load_weights here would block the UI on every click, and
        # asking for the fast copy alone meant the accuracy never showed at all.
        meta = self._inspected.get(self._current)
        if meta is None:
            meta = self.app_state.get_model_metadata(self._current)
            self._start_inspect(self._current)
        self.detail_title.setText(meta["name"])
        nets = meta["net_count"]
        bits = []
        if meta.get("trained_at"):
            when = _trained_when(meta["trained_at"],
                                 meta.get("trained_at_source"))
            # The ~ carries the doubt in the list, where there is no room to
            # explain; here there is, so say which it is outright.
            bits.append(f"file dated {when.lstrip('~')}"
                        if meta.get("trained_at_source") == "mtime"
                        else f"trained {when}")
        # "5 nets" alone reads as a spec. Every one of them is consulted on every
        # sound and the scores are averaged (TinyAudioNetEnsemble.forward), so
        # say what they do. "Voting" was the earlier wording and it is wrong in a
        # way that misleads: an average is not a count, so a confident net beats
        # two hesitant ones and there is no reason to prefer an odd number.
        bits.append("1 net deciding alone" if nets == 1
                    else f"{nets} neural networks averaged")
        bits.append(_human_size(meta["total_size_bytes"]))
        if meta.get("best_accuracy") is not None:
            bits.append(f"best accuracy {meta['best_accuracy']:.3f}")
        self.detail_stats.setText("   ·   ".join(bits))
        html, stale = self._detail_html(meta)
        self.detail_body.setText(html)
        if stale:
            noun = "sound has" if len(stale) == 1 else "sounds have"
            shown = ", ".join(stale[:4]) + ("…" if len(stale) > 4 else "")
            self.stale_label.setText(
                f"⚠ {len(stale)} {noun} new recordings since this model was "
                f"trained ({shown}) - retrain to use them.")
        else:
            self.stale_label.setText("")

    def _model_mtime(self):
        pkl = os.path.join(CLASSIFIER_FOLDER, f"{self._current}.pkl")
        return os.path.getmtime(pkl) if os.path.isfile(pkl) else 0

    def _detail_html(self, meta):
        """What this model knows, next to what's been recorded since - the two
        facts that decide whether it's worth retraining. Returns (html, stale
        labels)."""
        t = theme.colors()
        name = meta["name"]
        # Labels live inside the pkl/weights, so reading them is slow enough to
        # stutter the UI. The list's Sounds column fills this cache off-thread;
        # until it reaches this model, say so.
        if name not in self._loaded:
            return (f"<span style='color:{t['text_dim']};'>Reading its sounds…"
                    f"</span>", [])
        labels = self._loaded[name]
        if not labels:
            return (f"<span style='color:{t['text_dim']};'>Couldn't read this "
                    f"model's sound list.</span>", [])

        mtime = self._model_mtime()
        recorded = self.app_state.get_sound_labels()
        rows = []
        stale = []
        for label in labels:
            newest = library_ops.newest_recording_mtime(label)
            note = ""
            if newest is None:
                note = (f"<span style='color:{t['text_dim']};'>"
                        f"no recordings any more</span>")
            elif newest > mtime:
                stale.append(label)
                note = f"<span style='color:{WARN};'>new recordings since</span>"
            else:
                quantity, _p, _n = get_quantity_rating(
                    self.app_state.get_label_duration_ms(label))
                color = theme.QUANTITY_COLORS.get(quantity, t["text_dim"])
                note = f"<span style='color:{color};'>{quantity}</span>"
            rows.append(
                f"<tr><td style='color:{t['text']}; padding-right:16px;'>{label}"
                f"</td><td>{note}</td></tr>")

        html = [f"<b style='color:{t['text_bright']};'>Recognizes "
                f"{len(labels)} sounds</b>",
                "<table cellspacing='0' cellpadding='2'>" + "".join(rows) + "</table>"]

        unused = [l for l in recorded if l not in labels]
        if unused:
            html.append(
                f"<br><span style='color:{t['text_dim']};'>Recorded but not in "
                f"this model: {', '.join(unused)}</span>")
        return "".join(html), stale

    def _start_inspect(self, name):
        if self.inspect_worker is not None and self.inspect_worker.isRunning():
            return
        self.inspect_worker = InspectWorker(self.app_state, name, self)
        self.inspect_worker.loaded.connect(self._on_inspected)
        self.inspect_worker.start()

    def _on_inspected(self, meta):
        self.inspect_worker = None
        if not meta:
            return
        self._inspected[meta["name"]] = meta
        # [] = unreadable, so we don't retry forever
        self._loaded[meta["name"]] = meta["labels"] or []
        item = self._items.get(meta["name"])
        if item is not None:
            item.setText(2, str(len(meta["labels"])) if meta["labels"] else "?")
        if meta["name"] == self._current:
            self._refresh_details()
        elif self._current is not None and self._current not in self._inspected:
            # The selection moved on while this one was loading, and that click
            # found the worker busy and gave up. Pick the current one up now.
            self._start_inspect(self._current)

    # ---- empty states ---------------------------------------------------

    def _show_empty_state(self):
        """Three dead ends, and they need different answers: nothing recorded,
        one sound recorded, or everything ready and no model made. Telling
        someone who has recorded a sound to "record some sounds" reads as if
        their work went missing - name what they have, then what's missing."""
        self.header_frame.setVisible(False)
        self.detail_body.setVisible(False)
        self.stale_label.setText("")
        self.empty_wrapper.setVisible(True)

        labels = self.app_state.get_sound_labels()
        try:
            self.empty_btn.clicked.disconnect()
        except TypeError:
            pass
        if len(labels) < 2:
            self.train_btn.setEnabled(False)
            if labels:
                only = labels[0]
                # Seconds, not the rating: a first sound scoring "Not enough"
                # reads as a failure rather than a start.
                seconds = self.app_state.get_label_duration_ms(only) / 1000.0
                self.empty_title.setText("One more sound and you can train")
                self._set_empty_body(
                    f"You've recorded “{only}” - {seconds:.0f}s of detected sound "
                    f"so far. A model works by telling sounds apart, so it needs "
                    f"a second one to compare against. Record another in the "
                    f"Sounds tab and come back.")
            else:
                self.empty_title.setText("Record some sounds first")
                self._set_empty_body(
                    "A model learns to tell your sounds apart, so it needs at "
                    "least two of them to compare. Record a couple in the Sounds "
                    "tab and come back.")
            self.empty_btn.setText("Go to Sounds")
            self.empty_btn.clicked.connect(lambda: self.navigate.emit("Sounds"))
            return

        self.train_btn.setEnabled(True)
        pairs = [(label, self.app_state.get_label_duration_ms(label))
                 for label in labels]
        summary = help_dialog.quantity_summary(pairs)
        thin = sum(1 for _l, ms in pairs
                   if get_quantity_rating(ms)[0] == "Not enough")

        body = f"You have {len(labels)} sounds - {summary}."
        if thin:
            body += " " + help_dialog.thin_data_warning(thin, len(labels))
        body += (" Training reads every recording of the sounds you pick and "
                 "produces one model file. It runs unattended for hours - you "
                 "can stop it early for a rough first model, and retrain "
                 "whenever you record more.")
        self.empty_title.setText("Train your first model")
        self._set_empty_body(body)
        self.empty_btn.setText("+ New model")
        self.empty_btn.clicked.connect(self.train_requested.emit)

    # ---- actions -------------------------------------------------------

    def _model_pkl_path(self):
        if not self._current:
            return None
        path = os.path.join(CLASSIFIER_FOLDER, f"{self._current}.pkl")
        return path if os.path.isfile(path) else None

    def _on_test_accuracy(self):
        path = self._model_pkl_path()
        if not path:
            return
        from gui.widgets.model_test_dialogs import AccuracyDialog
        AccuracyDialog(self, self._current, path,
                       self.app_state.get_sound_labels()).exec()

    def _on_test_live(self):
        path = self._model_pkl_path()
        if not path:
            return
        from gui.services import audio_devices
        from gui.widgets.model_test_dialogs import LiveTestDialog
        LiveTestDialog(self, self._current, path, audio_devices.input_index).exec()

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
                self._current = None
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
            QMessageBox.information(self, "Combine models",
                                    "Pick at least two models.")
            return
        try:
            new_name = library_ops.sanitize_name(dialog.new_name(),
                                                 kind="model name")
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
        self._current = name
        self.app_state.models_changed.emit()

    def _on_combine_failed(self, message):
        self.combine_worker = None
        QMessageBox.warning(self, "Combine failed", message)


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
