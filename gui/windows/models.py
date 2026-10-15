"""Models tab - the library of trained models.

Shaped like the Sounds tab: list on the left, header panel + details on the
right.

Net count is listed alongside date and sounds because every net runs on every
frame and the scores are averaged (TinyAudioNetEnsemble.forward), so it is
part of what the model costs to run, not a spent training decision.
"""
import math
import time
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QSplitter, QMessageBox, QFrame
)

from config.config import BACKGROUND_LABEL, RECORD_SECONDS, SLIDING_WINDOW_AMOUNT
from gui import components, theme
from gui.services import library_ops


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


UNSURE_DATE_TIP = ("File date, not a training record. Copying or restoring "
                   "your data folder resets it.\nModels trained from now on "
                   "carry their real date inside the file.")


def _trained_when(when, source="checkpoint"):
    """Absolute date with year (gaps here are measured in months); relative
    only within a week. An "mtime" source is a file date, not a training
    record, so it gets a ~ and never a relative form."""
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


def _span(values, fmt):
    """One value, or lowest to highest. Nets that landed on the same number
    should not be made to look like a range."""
    low, high = fmt(min(values)), fmt(max(values))
    return low if low == high else f"{low}-{high}"


def _net_scores(meta):
    """Per-net accuracy span. Never averaged into one figure - the ensemble
    means probabilities, so its accuracy is not the mean of these."""
    nets = meta.get("nets") or []
    scores = [n["accuracy"] for n in nets if n.get("accuracy") is not None]
    if not scores:
        return ""
    return f"{_span(scores, lambda v: f'{v * 100:.1f}')}%"


def _best_epochs(meta):
    """+1 throughout: the trainer counts from zero, every screen from one.
    Each net's BEST checkpoint lands at its own peak epoch, hence the range."""
    epochs = [n["epoch"] for n in (meta.get("nets") or [])
              if n.get("epoch") is not None]
    if not epochs:
        return ""
    return _span(epochs, lambda v: str(v + 1))


def _combined_score(meta):
    """The ensemble's own score - the model's accuracy as it is used. Not
    bounded by the per-net span (an ensemble can beat every net in it).
    Highest epoch = the last measurement."""
    scored = [n for n in (meta.get("nets") or [])
              if n.get("combined_accuracy") is not None
              and n.get("epoch") is not None]
    if not scored:
        return ""
    latest = max(scored, key=lambda n: n["epoch"])
    return f"{latest['combined_accuracy'] * 100:.1f}%"


def _training_data(meta):
    """Roughly how much audio the run trained on, from label_frames.

    Post-balancing, so not what is on disk: repeated frames count every time
    the trainer sees them, and this can exceed what was recorded.
    """
    frames = next((n["label_frames"] for n in (meta.get("nets") or [])
                   if n.get("label_frames")), None)
    if not frames:
        return ""
    ms_per_frame = math.floor(RECORD_SECONDS / SLIDING_WINDOW_AMOUNT * 1000)
    minutes = round(sum(frames.values()) * ms_per_frame / 60000)
    return f"~{minutes} minute" + ("" if minutes == 1 else "s")


def _facts_sections(meta, sound_count=None):
    """[(heading, [(label, value)])], all read out of the model itself; nothing
    measured off the recordings folder. Sections come up short on old models
    rather than showing blanks."""
    t = theme.colors()
    # The pkl is the answer to "which file is this", even though the weights
    # are counted in Size alongside it.
    now = [("File", meta["name"] + ".pkl")]
    if sound_count:
        now.append(("Sounds", sound_count))
    # Models trained before combined_accuracy existed fall back to the per-net
    # span rather than showing nothing; the networks section then drops its own
    # copy instead of printing the same range twice.
    combined = _combined_score(meta)
    headline = combined or _net_scores(meta)
    if headline:
        now.append(("Accuracy", headline))
    if meta.get("trained_at"):
        when = _trained_when(meta["trained_at"], meta.get("trained_at_source"))
        # A file date is not a training date (a copied data dir restamps every
        # pkl), so lead with "Unknown" and give the date as the related fact.
        now.append(("Trained",
                    f"Unknown   <span style='color:{t['text_dim']};'>"
                    f"({when})</span>"
                    if meta.get("trained_at_source") == "mtime" else when))
    now.append(("Size", _human_size(meta["total_size_bytes"])))

    how = []
    # "Audio", not a bare duration: under "Trained: yesterday" it read as how
    # long the run took.
    audio = _training_data(meta)
    if audio:
        how.append(("Audio", audio))
    run = meta.get("run_settings") or {}
    if "balance_sounds" in run:
        how.append(("Balance sounds", "On" if run["balance_sounds"] else "Off"))
    if run.get("silence"):
        how.append(("Silence", {"all": "Include all", "balanced": "Balanced",
                                "none": "Omit"}.get(run["silence"],
                                                    run["silence"])))
    # One net is not an ensemble: its score is already the model's, above.
    # Its best epoch is still its own fact.
    count = len([n for n in (meta.get("nets") or []) if n.get("accuracy")])
    each = []
    if count > 1 and combined:
        each.append(("Accuracy", _net_scores(meta)))
    epochs = _best_epochs(meta)
    if epochs:
        each.append(("Best epoch", epochs))

    nets = meta["net_count"]
    heading = f"Neural networks ({nets})" if nets else "Neural networks"
    # "Training data", not "Recordings": the audio figure is post-balancing and
    # can exceed what is on disk. Balance and Silence ride here because they
    # are what made it differ.
    return [("Model info", now), ("Training data", how), (heading, each)]


def facts_html(meta, sound_count=None):
    """The sections as one table so the columns line up down the whole card."""
    t = theme.colors()
    parts = []
    for heading, facts in _facts_sections(meta, sound_count):
        if not facts:
            continue
        pad = "padding-top:14px;" if parts else ""
        parts.append(
            f"<tr><td colspan='2' style='color:{t['text']}; {pad}'>"
            f"<b>{heading}</b></td></tr>")
        parts.extend(
            f"<tr><td style='color:{t['text_dim']}; padding-right:20px;'>"
            f"{label}</td><td style='color:{t['text']};'>{value}</td></tr>"
            for label, value in facts)
    return "<table cellspacing='0' cellpadding='3'>" + "".join(parts) + "</table>"


def label_scores(meta):
    """Per sound, what each net scored on the held-back split: {label: (text,
    worst)}. Empty on models trained before the field existed."""
    per_net = [n["label_accuracy"] for n in (meta.get("nets") or [])
               if n.get("label_accuracy")]
    if not per_net:
        return {}
    out = {}
    for label in per_net[0]:
        scores = [p[label] for p in per_net if label in p]
        if scores:
            out[label] = (f"{_span(scores, lambda v: f'{v * 100:.0f}')}%",
                          min(scores))
    return out


class SoundItem(QTreeWidgetItem):
    """Sorts the accuracy column by number. As text, 100% sorts below 97%."""

    def __lt__(self, other):
        col = self.treeWidget().sortColumn()
        mine = self.data(col, Qt.ItemDataRole.UserRole)
        theirs = other.data(col, Qt.ItemDataRole.UserRole)
        if mine is None or theirs is None:
            return super().__lt__(other)
        return mine < theirs


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
    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.inspect_worker = None
        self.count_worker = None
        self._current = None
        self._dates_moved = False
        self._loaded = {}     # model name -> labels ([] = unreadable)
        self._inspected = {}  # model name -> full metadata, accuracy included
        self._items = {}      # model name -> its row

        self._setup_ui()
        self._populate_models()

    # ---- ui ------------------------------------------------------------

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # Left: the models.
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 8, 12)
        left_layout.addWidget(components.heading("Models", "card"))
        self.model_list = QTreeWidget()
        self.model_list.setColumnCount(4)
        self.model_list.setHeaderLabels(
            ["Model", "Trained", "Sounds", "Nets"])
        self.model_list.setRootIsDecorated(False)
        self.model_list.setUniformRowHeights(True)
        self.model_list.setAllColumnsShowFocus(True)
        head = self.model_list.headerItem()
        head.setToolTip(2, "How many sounds this model can tell apart")
        head.setToolTip(3, "How many neural networks the model owns. Every one "
                           "is consulted on every sound, and their scores are "
                           "averaged.")
        header = self.model_list.header()
        # Left to itself the header stretches the *last* section as well as the
        # one asked for, and the two together overflow the pane - the last
        # column ends up past the right edge behind a scrollbar.
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3):
            header.setSectionResizeMode(col,
                                        QHeaderView.ResizeMode.ResizeToContents)
        self.model_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.model_list.currentItemChanged.connect(self._on_select)
        left_layout.addWidget(self.model_list)

        # Wider than the Sounds tab's pane: more columns.
        left.setMinimumWidth(320)
        splitter.addWidget(left)

        # Right: per-model header panel + scrollable detail body.
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self._build_header())

        # Sounds beside their facts: the long list carries the width, a fixed
        # card holds what it adds up to.
        body = QWidget()
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(20, 16, 24, 16)
        self.body_layout.setSpacing(12)

        self.columns = QWidget()
        columns = QHBoxLayout(self.columns)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(22)
        columns.addWidget(self._build_sound_column(), 1)
        columns.addWidget(self._build_facts_column(), 0)
        self.body_layout.addWidget(self.columns, 1)

        # The empty panel lives inside its own springy wrapper so it sits in the
        # middle of the card area; with it hidden the wrapper collapses and the
        # trailing stretch keeps the model details at the top.
        self.empty_panel = components.EmptyState()
        self.empty_wrapper = QWidget()
        wrap = QVBoxLayout(self.empty_wrapper)
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.addStretch()
        wrap.addWidget(self.empty_panel, 0, Qt.AlignmentFlag.AlignHCenter)
        wrap.addStretch()
        self.body_layout.addWidget(self.empty_wrapper, 1)
        right_layout.addWidget(body)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([400, 800])

    def _build_sound_column(self):
        t = theme.colors()
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self.sound_tree = self._build_sound_tree()
        v.addWidget(self.sound_tree, 1)
        self.unused_label = QLabel("")
        self.unused_label.setWordWrap(True)
        self.unused_label.setStyleSheet(f"color: {t['text_dim']};")
        v.addWidget(self.unused_label)
        return col

    def _build_facts_column(self):
        t = theme.colors()
        col = QWidget()
        col.setFixedWidth(310)
        outer = QVBoxLayout(col)
        outer.setContentsMargins(0, 0, 0, 0)
        card, v = components.card_frame("factsCard")
        self.detail_body = QLabel("")
        self.detail_body.setWordWrap(True)
        self.detail_body.setTextFormat(Qt.TextFormat.RichText)
        self.detail_body.setStyleSheet(f"color: {t['text']};")
        self.detail_body.setAlignment(Qt.AlignmentFlag.AlignTop)
        v.addWidget(self.detail_body)
        outer.addWidget(card)
        outer.addStretch()
        return col

    def _build_sound_tree(self):
        """The sounds a model knows. A real tree rather than rich text because
        the accuracy column is worth sorting on."""
        tree = QTreeWidget()
        tree.setColumnCount(3)
        tree.setHeaderLabels(["Sound", "Accuracy", ""])
        tree.setRootIsDecorated(False)
        tree.setUniformRowHeights(True)
        tree.setAllColumnsShowFocus(True)
        tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tree.setSortingEnabled(True)
        tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        tree.headerItem().setToolTip(
            1, "What each network scored on this sound, on the samples the\n"
               "trainer held back. Blank on models trained before it was kept.")
        header = tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return tree

    def _fill_sound_tree(self, rows):
        t = theme.colors()
        tree = self.sound_tree
        # Sorting off while filling, or every insert re-sorts the tree.
        tree.setSortingEnabled(False)
        tree.clear()
        for label, score, worst, note in rows:
            item = SoundItem([label, score, note])
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight
                                  | Qt.AlignmentFlag.AlignVCenter)
            if worst is not None:
                item.setData(1, Qt.ItemDataRole.UserRole, worst)
            item.setForeground(2, QColor(t["text_dim"]))
            tree.addTopLevelItem(item)
        tree.setSortingEnabled(True)
        tree.setVisible(bool(rows))

    def _build_header(self):
        """The selected model's identity, and a way to its files."""
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

        self.detail_title = components.heading("", "title")
        v.addWidget(self.detail_title)
        # Not a warning: recording more is what the app asks for everywhere
        # else, so being told about it in amber punishes doing the right thing.
        self.stale_label = QLabel("")
        self.stale_label.setWordWrap(True)
        self.stale_label.setStyleSheet(
            f"color: {t['text_dim']}; margin-top: 2px;")
        v.addWidget(self.stale_label)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 4, 0, 0)
        actions.addWidget(components.ghost_button(
            "Open folder", self._on_open_folder, "Reveal data/models"))
        actions.addStretch()
        v.addLayout(actions)
        return header

    # ---- model list ----------------------------------------------------

    def _populate_models(self):
        """Newest first: the one made last."""
        prev = self._current
        t = theme.colors()
        details = sorted(self.app_state.get_all_model_details(),
                         key=lambda meta: self.app_state.model_sort_key(meta["name"]))

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
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, name)
            for col in (2, 3):
                item.setTextAlignment(col, Qt.AlignmentFlag.AlignRight
                                      | Qt.AlignmentFlag.AlignVCenter)
            for col in (1, 2, 3):
                item.setForeground(col, QColor(t["text_dim"]))
            # A long name is elided in this column, so keep the whole one
            # reachable on hover.
            item.setToolTip(0, name)
            if meta["trained_at_source"] == "mtime":
                item.setToolTip(1, UNSURE_DATE_TIP)
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

    # ---- details --------------------------------------------------------

    def _refresh_details(self):
        if self._current is None:
            self._show_empty_state()
            return
        self.header_frame.setVisible(True)
        self.empty_wrapper.setVisible(False)
        self.columns.setVisible(True)

        # The accuracy only exists once the checkpoints have been read, so use
        # the inspected copy when it has arrived and the cheap one until then -
        # asking for load_weights here would block the UI on every click, and
        # asking for the fast copy alone meant the accuracy never showed at all.
        meta = self._inspected.get(self._current)
        if meta is None:
            meta = self.app_state.get_model_metadata(self._current)
            self._start_inspect(self._current)
        self.detail_title.setText(meta["name"])
        html, stale, sounds, unused = self._detail_html(meta)
        self.detail_body.setText(html)
        self._fill_sound_tree(sounds)
        self.unused_label.setText(
            f"Recorded but not in this model: {', '.join(unused)}"
            if unused else "")
        self.unused_label.setVisible(bool(unused))
        if stale:
            takes = sum(count for _, count in stale)
            names = [label for label, _ in stale]
            shown = ", ".join(names[:4]) + ("…" if len(names) > 4 else "")
            noun = "recording" if takes == 1 else "recordings"
            self.stale_label.setText(
                f"{takes} new {noun} since this model was trained: {shown}")
        else:
            self.stale_label.setText("")

    def _detail_html(self, meta):
        """What this model knows, next to what's been recorded since - the two
        facts that decide whether it's worth retraining. Returns (html, stale
        labels, sound rows, unused labels)."""
        t = theme.colors()
        name = meta["name"]
        # Labels live inside the pkl/weights, so reading them is slow enough to
        # stutter the UI. The list's Sounds column fills this cache off-thread;
        # until it reaches this model, say so.
        if name not in self._loaded:
            return (f"<span style='color:{t['text_dim']};'>Reading its sounds…"
                    f"</span>", [], [], [])
        labels = self._loaded[name]
        if not labels:
            return (f"<span style='color:{t['text_dim']};'>Couldn't read this "
                    f"model's sound list.</span>", [], [], [])

        # Not the pkl mtime first: copying a data dir restamps every pkl, which
        # would mark every sound as newer than the model.
        trained = self.app_state.get_model_trained_at(name) or 0
        recorded = self.app_state.get_sound_labels()
        per_sound = label_scores(meta)
        rows = []
        stale = []
        for label in labels:
            score, worst = per_sound.get(label, ("", None))
            if label == BACKGROUND_LABEL:
                # Has no recordings folder, so the checks below would call it
                # missing. The model does answer with it, so it stays listed.
                rows.append((label, score, worst,
                             "built from the quiet parts of the others"))
                continue
            new_takes, newest = library_ops.recordings_since(label, trained)
            note = ""
            if newest is None:
                note = "no recordings any more"
            elif new_takes:
                stale.append((label, new_takes))
                note = f"{new_takes} new since"
            # Score column is the model's own; nothing measured off today's
            # recordings folder goes there.
            rows.append((label, score, worst, note))

        # A class, not a sound anyone made. Counting it overstates by one.
        spoken = [l for l in labels if l != BACKGROUND_LABEL]
        plus = f" + {BACKGROUND_LABEL}" if len(spoken) != len(labels) else ""
        html = facts_html(meta, f"{len(spoken)}{plus}")
        return (html, stale, rows, [l for l in recorded if l not in labels])

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

    # ---- empty state ----------------------------------------------------

    def _show_empty_state(self):
        self.header_frame.setVisible(False)
        self.columns.setVisible(False)
        self.stale_label.setText("")
        self.empty_wrapper.setVisible(True)
        self.empty_panel.set_state(
            "No models yet",
            "Models trained with settings.py show up here.")

    # ---- actions -------------------------------------------------------

    def _on_open_folder(self):
        try:
            library_ops.open_in_file_manager(
                library_ops.model_pkl_path(self._current))
        except library_ops.LibraryOpError as exc:
            QMessageBox.warning(self, "Couldn't open folder", str(exc))
