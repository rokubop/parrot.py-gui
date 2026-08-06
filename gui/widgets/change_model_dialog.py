"""Pick the model Talon runs, with the model in front of you.

This used to be a dropdown of names and then a confirm box: a dozen models with
nothing to tell them apart but what they were called. Same list, with what the
Models tab knows about the highlighted one beside it - what it scored, when it
was trained, how big it is, which sounds it knows and what each one scored.

Two things the Models tab does not say, because only this screen is asking:
which model Talon is running right now, and whether the patterns being edited
listen for sounds the highlighted model has never heard. A model that does not
know `cluck` is not a worse model, it is the wrong one for these patterns, and
that is only answerable here.

One decision, not two. The path being written and the warnings sit above the
button, so nothing behind it repeats them. The caller confirms separately in the
one case this cannot show: a deployed model with no copy in the library, where
the swap is the end of it.

The heavy read (accuracy, per-sound scores, mics) is a torch load per net, so it
runs off the UI thread and fills in; the cheap facts are on screen immediately.
AppState caches it, so coming back to a model is instant.
"""
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QTreeWidget, QHeaderView, QFrame, QWidget, QSplitter
)

from config.config import BACKGROUND_LABEL
from gui import theme


class _InspectWorker(QThread):
    """The slow half of a model's facts, off the UI thread."""
    loaded = pyqtSignal(str, object)

    def __init__(self, app_state, name, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.name = name

    def run(self):
        try:
            meta = self.app_state.get_model_metadata(self.name,
                                                     load_weights=True)
        except Exception:
            meta = None
        self.loaded.emit(self.name, meta)


class ChangeModelDialog(QDialog):
    """Accepted with `chosen` set to the model name Talon should run."""

    def __init__(self, parent, app_state, current, dest_path, patterns=None):
        super().__init__(parent)
        t = theme.colors()
        self.app_state = app_state
        self.current = current
        self.dest_path = dest_path
        self.chosen = None
        self._loaded = {}        # name -> full meta, once the worker has been
        self._worker = None
        # What the patterns being edited listen for. The draft, not the
        # deployed set: it is what the next deploy will run.
        self._wanted = sorted({s for cfg in (patterns or {}).values()
                               if isinstance(cfg, dict)
                               for s in (cfg.get("sounds") or [])})
        self._uses = {}
        for cfg in (patterns or {}).values():
            if isinstance(cfg, dict):
                for sound in (cfg.get("sounds") or []):
                    self._uses[sound] = self._uses.get(sound, 0) + 1

        self.setWindowTitle("Change model")
        self.setModal(True)
        self.resize(950, 580)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)

        title = QLabel("Which model should Talon run?")
        title.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {t['text_bright']};")
        layout.addWidget(title)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self._build_list())
        split.addWidget(self._build_details())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([220, 720])
        layout.addWidget(split, 1)

        self.warning = QLabel("")
        self.warning.setWordWrap(True)
        self.warning.setVisible(False)
        self.warning.setStyleSheet(f"color: {t['warn']};")
        layout.addWidget(self.warning)

        row = QHBoxLayout()
        row.setContentsMargins(0, 4, 0, 0)
        self.dest_label = QLabel(f"Replaces {dest_path}" if dest_path else "")
        self.dest_label.setWordWrap(True)
        self.dest_label.setStyleSheet(f"color: {t['text_dim']};")
        row.addWidget(self.dest_label, 1)
        cancel = QPushButton("Cancel")
        cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        from gui.windows.train_view import primary_button_style
        self.go = QPushButton("Use this model")
        self.go.setObjectName("primaryAction")
        self.go.setMinimumHeight(32)
        self.go.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.go.setStyleSheet(primary_button_style())
        self.go.clicked.connect(self._accept_selection)
        row.addWidget(self.go)
        layout.addLayout(row)

        self._populate()

    # ---- ui ---------------------------------------------------------------

    def _build_list(self):
        """Newest first, the same order as the Models tab - the model someone
        just trained is the one they came here to deploy."""
        t = theme.colors()
        self.list = QListWidget()
        self.list.setStyleSheet(
            f"QListWidget {{ background-color: {t['base']}; "
            f"border: 1px solid {t['border']}; border-radius: 6px; }} "
            f"QListWidget::item {{ padding: 6px 8px; }}")
        self.list.currentItemChanged.connect(self._on_select)
        self.list.itemDoubleClicked.connect(
            lambda _item: self._accept_selection())
        return self.list

    def _build_details(self):
        t = theme.colors()
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(14, 0, 0, 0)
        v.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(10)
        self.detail_title = QLabel("")
        self.detail_title.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {t['text_bright']};")
        head.addWidget(self.detail_title)
        self.live_badge = QLabel("In Talon now")
        self.live_badge.setStyleSheet(
            f"color: {t['accent']}; border: 1px solid {t['accent']}; "
            f"border-radius: 9px; padding: 1px 8px; font-size: 11px; "
            f"font-weight: bold;")
        self.live_badge.setVisible(False)
        head.addWidget(self.live_badge)
        head.addStretch()
        v.addLayout(head)

        columns = QHBoxLayout()
        columns.setSpacing(14)

        card = QFrame()
        card.setObjectName("factsCard")
        card.setFixedWidth(300)
        # The global QWidget rule paints an opaque box behind every child
        # unless they declare themselves transparent (memory/qt-traps.md).
        card.setStyleSheet(
            f"QFrame#factsCard {{ background-color: {t['panel']}; "
            f"border: 1px solid {t['border']}; border-radius: 8px; }} "
            f"QFrame#factsCard > QLabel {{ background: transparent; "
            f"border: none; }}")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 15, 16, 16)
        self.facts = QLabel("")
        self.facts.setWordWrap(True)
        self.facts.setTextFormat(Qt.TextFormat.RichText)
        self.facts.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.facts.setStyleSheet(f"color: {t['text']};")
        card_layout.addWidget(self.facts)
        card_layout.addStretch()
        columns.addWidget(card)

        sounds = QVBoxLayout()
        sounds.setSpacing(6)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Sound", "Accuracy", "Patterns"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        self.tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.tree.headerItem().setToolTip(
            1, "What each network scored on this sound, on the samples the\n"
               "trainer held back. Blank on models trained before it was kept.")
        self.tree.headerItem().setToolTip(
            2, "How many of your patterns listen for this sound")
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        sounds.addWidget(self.tree, 1)
        self.fit_label = QLabel("")
        self.fit_label.setWordWrap(True)
        self.fit_label.setStyleSheet(f"color: {t['text_dim']};")
        sounds.addWidget(self.fit_label)
        columns.addLayout(sounds, 1)

        v.addLayout(columns, 1)
        return panel

    def _populate(self):
        for name in sorted(self.app_state.get_model_names(),
                           key=self.app_state.model_sort_key):
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            if name == self.current:
                item.setText(f"{name}   ·  running")
                item.setToolTip("Talon is running this model right now")
            self.list.addItem(item)
            if name == self.current:
                self.list.setCurrentItem(item)
                self.list.scrollToItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)

    # ---- selection --------------------------------------------------------

    def _selected(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_select(self, *_args):
        name = self._selected()
        if name is None:
            return
        self.detail_title.setText(name)
        self.live_badge.setVisible(name == self.current)
        self.go.setEnabled(name != self.current)
        self.go.setText("Already running" if name == self.current
                        else "Use this model")
        meta = self._loaded.get(name)
        if meta is None:
            # The cheap facts (file, size, date) while the checkpoints load.
            self._render(self.app_state.get_model_metadata(name), full=False)
            self._start_inspect(name)
        else:
            self._render(meta, full=True)

    def _start_inspect(self, name):
        if self._worker is not None and self._worker.isRunning():
            return
        # Parented to the page, not to this dialog: the dialog can be closed
        # while the read is in flight, and a QThread whose parent has been
        # destroyed takes the process with it.
        self._worker = _InspectWorker(self.app_state, name, self.parent())
        self._worker.loaded.connect(self._on_inspected)
        self._worker.start()

    def _on_inspected(self, name, meta):
        self._worker = None
        if meta is not None:
            self._loaded[name] = meta
        current = self._selected()
        if current == name and meta is not None:
            self._render(meta, full=True)
        elif current is not None and current not in self._loaded:
            # The selection moved on while this one was loading, and that click
            # found the worker busy and gave up. Pick the current one up now.
            self._start_inspect(current)

    # ---- rendering --------------------------------------------------------

    def _render(self, meta, full):
        from gui.windows.models import facts_html, label_scores, SoundItem
        t = theme.colors()
        labels = meta.get("labels") or []
        spoken = [l for l in labels if l != BACKGROUND_LABEL]
        plus = f" + {BACKGROUND_LABEL}" if len(spoken) != len(labels) else ""
        count = f"{len(spoken)}{plus}" if labels else None
        self.facts.setText(facts_html(meta, count))

        per_sound = label_scores(meta)
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        for label in labels:
            score, worst = per_sound.get(label, ("", None))
            uses = self._uses.get(label, 0)
            item = SoundItem([label, score, str(uses) if uses else ""])
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight
                                  | Qt.AlignmentFlag.AlignVCenter)
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight
                                  | Qt.AlignmentFlag.AlignVCenter)
            if worst is not None:
                item.setData(1, Qt.ItemDataRole.UserRole, worst)
            item.setData(2, Qt.ItemDataRole.UserRole, uses)
            self.tree.addTopLevelItem(item)
        self.tree.setSortingEnabled(True)
        # A column of blanks costs the sound names their width. Models trained
        # before per-sound scores were kept have none, and a fresh setup has no
        # patterns to count.
        self.tree.setColumnHidden(1, not per_sound)
        self.tree.setColumnHidden(2, not self._uses)

        if not labels:
            self.fit_label.setText("Reading its sounds…" if not full
                                   else "Couldn't read this model's sound list.")
            self.fit_label.setStyleSheet(f"color: {t['text_dim']};")
            self.warning.setVisible(False)
            return

        # Say what it knows before what it lacks, and put the lack where the
        # decision is made rather than only in a message box after it.
        missing = [s for s in self._wanted if s not in labels]
        if not self._wanted:
            self.fit_label.setText("No patterns listen for anything yet.")
            self.fit_label.setStyleSheet(f"color: {t['text_dim']};")
        elif missing:
            known = len(self._wanted) - len(missing)
            self.fit_label.setText(
                f"Knows {known} of the {len(self._wanted)} sounds your "
                f"patterns listen for.")
            self.fit_label.setStyleSheet(f"color: {t['warn']};")
        else:
            self.fit_label.setText(
                "Knows every sound your patterns listen for.")
            self.fit_label.setStyleSheet(f"color: {t['accent']};")
        self._set_warning(missing)

    def _set_warning(self, missing):
        if not missing or self._selected() == self.current:
            self.warning.setVisible(False)
            return
        shown = ", ".join(missing[:6]) + ("…" if len(missing) > 6 else "")
        self.warning.setText(
            f"Patterns listening for {shown} will never fire on this model "
            f"until you change them.")
        self.warning.setVisible(True)

    # ---- leaving ----------------------------------------------------------

    def _accept_selection(self):
        name = self._selected()
        if not name or name == self.current:
            return
        self.chosen = name
        self.accept()

    def done(self, result):
        # The worker outlives the dialog by design; nothing left to deliver to.
        if self._worker is not None:
            try:
                self._worker.loaded.disconnect(self._on_inspected)
            except TypeError:
                pass
            self._worker = None
        super().done(result)
