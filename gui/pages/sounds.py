import os
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QSplitter, QScrollArea, QFrame, QPushButton, QRadioButton,
    QMessageBox, QMenu, QDialog, QDialogButtonBox, QLineEdit, QInputDialog
)
from PyQt6.QtCore import Qt, QEvent, pyqtSignal
from PyQt6.QtGui import QColor
from gui.widgets.recording_card import RecordingCard
from gui.widgets.audio_graph import GRAPH_DISPLAY_WAVEFORM, GRAPH_DISPLAY_SPECTROGRAM
from gui.widgets import help_dialog
from gui.widgets.confirm_dialog import confirm_destructive
from gui.services import library_ops
from gui import components, theme
from gui.formatters import duration_text, spoken_duration
from gui.timing import debounced, staggered, next_tick
from lib import recordings
from lib.recordings import get_label_dir
from lib.print_status import get_quantity_rating, QUANTITIES
from lib.wav import wav_duration

SOUND_COLUMN, DATA_COLUMN, DETECTED_COLUMN = 0, 1, 2

INVALID_LABEL_TEXT = {
    recordings.InvalidLabel.EMPTY: "Please enter a sound name.",
    recordings.InvalidLabel.ILLEGAL_CHARACTER:
        "A sound name can't contain any of: < > : \" / \\ | ? *",
    recordings.InvalidLabel.STARTS_WITH_DOT: "A sound name can't start with a dot.",
    recordings.InvalidLabel.EXISTS: "There's already a sound with that name.",
}


def _is_space(event):
    return (event.key() == Qt.Key.Key_Space
            and event.modifiers() == Qt.KeyboardModifier.NoModifier)


class SoundsPage(QWidget):
    """
    ┌ sound_list ─────────┐┌ sound_header ────────────────────────────────────────────┐
    │ Sound  Data  Detect.││ sound_title                                              │
    │ pop    Good  1m 04s ││ sound_stats                                              │
    │ ss     Good   51.0s ││ sound_quantity                                           │
    │                     ││ add_recording_btn open_folder_btn _graph_display_buttons │
    │                     │├ cards_scroll ────────────────────────────────────────────┤
    │                     ││ ┌ cards_container ─────────────────────────────────────┐ │
    │                     ││ │ ┌ RecordingCard ───────────────────────────────────┐ │ │
    │                     ││ │ │ header                                           │ │ │
    │                     ││ │ │ .:|:..:||:..:|:.. audio_graph ..:|:..:||:..:|:.. │ │ │
    │                     ││ │ └──────────────────────────────────────────────────┘ │ │
    │                     ││ │ ┌ RecordingCard ───────────────────────────────────┐ │ │
    │                     ││ │ │ header                                           │ │ │
    │                     ││ │ │ .:|:..:||:..:|:.. audio_graph ..:|:..:||:..:|:.. │ │ │
    │                     ││ │ └──────────────────────────────────────────────────┘ │ │
    │ new_sound_btn       ││ └──────────────────────────────────────────────────────┘ │
    └─────────────────────┘└──────────────────────────────────────────────────────────┘
    """

    record_requested = pyqtSignal(str)   # the sound to record

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self._cards = []
        self._active_card = None
        self._graph_display = GRAPH_DISPLAY_WAVEFORM
        self._normalized = True

        # Stagger audio graph builds to not stall the main thread (50-220 ms each)
        self._audio_graphs_build = staggered(RecordingCard.build_audio_graph, owner=self)
        # Same for switching display: a long take's spectrogram is ~60 ms
        self._graph_displays_set = staggered(
            lambda card: card.set_graph_display(self._graph_display), owner=self)

        self._setup_ui()
        self._sound_list_populate()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 8, 12)
        title_row = QHBoxLayout()
        self.left_title = QLabel("Sounds")
        title_row.addWidget(self.left_title)
        title_row.addStretch()
        title_row.addWidget(help_dialog.help_button(self, "record"))
        left_layout.addLayout(title_row)
        self.sound_list = QTreeWidget()
        self.sound_list.setAccessibleName("Sounds")
        self.sound_list.setAccessibleDescription("Space plays or pauses a recording")
        self.sound_list.setHeaderLabels(["Sound", "Data", "Detected"])
        self.sound_list.setRootIsDecorated(False)
        self.sound_list.setUniformRowHeights(True)
        header = self.sound_list.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(SOUND_COLUMN, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(DATA_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(DETECTED_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        # Debounce sound change in case arrow key is held
        self.sound_list.currentItemChanged.connect(
            debounced(self._cards_show_selected, wait_ms=15, owner=self))
        self.sound_list.installEventFilter(self)
        self.sound_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sound_list.customContextMenuRequested.connect(self._sound_menu_show)
        left_layout.addWidget(self.sound_list)
        new_sound_btn = QPushButton("+ New sound")
        new_sound_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        new_sound_btn.setToolTip("Name a new sound, then add recordings to it")
        new_sound_btn.clicked.connect(self._on_new_sound)
        left_layout.addWidget(new_sound_btn)
        # Where keyboard navigation to this page lands
        self.setFocusProxy(self.sound_list)

        left.setMinimumWidth(280)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self._sound_header_build())

        self.cards_scroll = QScrollArea()
        self.cards_scroll.setWidgetResizable(True)
        self.cards_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.cards_scroll.setObjectName("cardsScroll")
        self.cards_scroll.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.cards_scroll.setAccessibleName("Recordings")
        # Always on: wheel scroll over a graph zooms it instead of scrolling the page
        self.cards_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.cards_scroll.setWidget(self._cards_container_new()[0])
        right_layout.addWidget(self.cards_scroll)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 900])

        t = theme.colors()
        self.left_title.setStyleSheet(components.heading_style("card"))
        self.sound_title.setStyleSheet(components.heading_style("title"))
        self.sound_stats.setStyleSheet(f"color: {t['text_dim']};")
        self.sound_quantity.setStyleSheet(f"color: {t['text_dim']}; margin-top: 2px;")
        self.sound_header.setStyleSheet(
            f"QFrame#soundHeader {{ background-color: {t['toolbar']}; "
            f"border-bottom: 1px solid {t['border']}; }}")
        self.add_recording_btn.setStyleSheet(components.primary_button_style())
        self.open_folder_btn.setStyleSheet(components.ghost_button_style())
        setting_toggle_style = (
            # t['text'], not t['text_dim'], for color contrast
            f"#settingToggle {{ background-color: {t['button']}; "
            f"color: {t['text']}; border: 1px solid {t['control_border']}; "
            f"border-radius: {t['radius']}; padding: 5px 14px; spacing: 0px; }} "
            f"#settingToggle::indicator {{ width: 0px; height: 0px; }} "
            f"#settingToggle:checked {{ background-color: {t['panel']}; "
            f"color: {t['text_bright']}; border: 1px solid {t['accent']}; }} "
            f"#settingToggle:hover {{ color: {t['text_bright']}; }} "
            f"#settingToggle:focus {{ "
            f"border: 2px solid {t['focus']}; padding: 4px 13px; }} "
            f"#settingToggle:disabled {{ background-color: {t['disabled_bg']}; "
            f"color: {t['disabled_text']}; border: 1px solid {t['control_border']}; }}")
        for b in list(self._graph_display_buttons.values()) + [self.normalize_btn]:
            b.setStyleSheet(setting_toggle_style)
        self.graph_display_label.setStyleSheet(f"color: {t['text_dim']};")
        self.cards_scroll.setStyleSheet(
            f"QScrollBar:vertical {{ width: 16px; background: {t['base']}; }} "
            # Transparent until focused, so the ring doesn't shift the cards
            f"QScrollArea#cardsScroll {{ border: 2px solid transparent; }} "
            f"QScrollArea#cardsScroll:focus {{ border: 2px solid {t['focus']}; }}")

    def _sound_header_build(self):
        header = QFrame()
        header.setObjectName("soundHeader")
        self.sound_header = header
        v = QVBoxLayout(header)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(2)

        self.sound_title = QLabel("")
        v.addWidget(self.sound_title)
        self.sound_stats = QLabel("")
        v.addWidget(self.sound_stats)
        self.sound_quantity = QLabel("")
        v.addWidget(self.sound_quantity)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 10, 0, 0)
        self.add_recording_btn = QPushButton("+ Add recording")
        self.add_recording_btn.setObjectName("primaryAction")
        self.add_recording_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.add_recording_btn.clicked.connect(self._on_add_recording)
        actions.addWidget(self.add_recording_btn)
        self.open_folder_btn = QPushButton("Open folder")
        self.open_folder_btn.setObjectName("secondaryAction")
        self.open_folder_btn.setFlat(True)
        self.open_folder_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.open_folder_btn.clicked.connect(self._on_open_sound_folder)
        actions.addWidget(self.open_folder_btn)
        actions.addStretch()

        self.graph_display_label = QLabel("View:")
        actions.addWidget(self.graph_display_label)
        # Radio buttons styled as toggles: a screen reader hears one choice of
        # two, and arrow keys switch. Siblings in one parent are exclusive.
        graph_display_box = QWidget()
        graph_display_box.setAccessibleName("View")
        box_layout = QHBoxLayout(graph_display_box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        self._graph_display_buttons = {}
        for graph_display, text in ((GRAPH_DISPLAY_WAVEFORM, "Waveform"),
                                    (GRAPH_DISPLAY_SPECTROGRAM, "Spectrogram")):
            btn = QRadioButton(text)
            btn.setObjectName("settingToggle")
            btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            btn.setChecked(graph_display == self._graph_display)
            btn.toggled.connect(
                lambda checked, m=graph_display: checked and self._cards_set_graph_display(m))
            self._graph_display_buttons[graph_display] = btn
            box_layout.addWidget(btn)
        actions.addWidget(graph_display_box)

        self.normalize_btn = QPushButton("Normalize")
        self.normalize_btn.setObjectName("settingToggle")
        self.normalize_btn.setCheckable(True)
        self.normalize_btn.setChecked(self._normalized)
        self.normalize_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.normalize_btn.setToolTip("Scale each waveform to its loudest point")
        self.normalize_btn.toggled.connect(self._cards_set_normalized)
        actions.addSpacing(12)
        actions.addWidget(self.normalize_btn)
        v.addLayout(actions)
        return header

    # ---- data ----------------------------------------------------------

    def _sound_list_populate(self):
        self.sound_list.blockSignals(True)
        self.sound_list.clear()
        for label in self.app_state.get_sound_labels():
            duration_ms = self.app_state.get_label_duration_ms(label)
            duration = duration_text(duration_ms / 1000.0)
            quantity, _pct = get_quantity_rating(duration_ms)
            item = QTreeWidgetItem([label, quantity, duration])
            item.setData(SOUND_COLUMN, Qt.ItemDataRole.UserRole, label)
            # A screen reader reads only the first column otherwise
            item.setData(SOUND_COLUMN, Qt.ItemDataRole.AccessibleTextRole,
                         f"{label}, {quantity} data, {spoken_duration(duration_ms / 1000.0)} detected")
            color = theme.QUANTITY_COLORS.get(quantity)
            if color:
                item.setForeground(DATA_COLUMN, QColor(color))
            item.setTextAlignment(DETECTED_COLUMN, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.sound_list.addTopLevelItem(item)
        self.sound_list.blockSignals(False)

        if self.sound_list.topLevelItemCount() == 0:
            self._cards_populate(None)
            return
        # Fires the selection handler, which shows the sound
        self.sound_list.setCurrentItem(self.sound_list.topLevelItem(0))

    # ---- cards: one per recording of the selected sound -----------------

    def _cards_show_selected(self):
        self._cards_populate(self.sound_list.currentItem())

    def _cards_populate(self, item):
        """Builds a new container of placeholder cards off-screen and swaps it
        in, so the sound shows in one repaint. Audio graphs fill in after, and
        the old container is freed once the new one is on screen.

        sound_list change (debounced) -> _cards_show_selected -> here
            _sound_header_update
            _cards_build
                _cards_container_new
                _card_new, per recording
            _cards_swap_in
            _cards_set_tab_order
            _audio_graphs_build (staggered)
            _cards_destroy_later -> _cards_destroy
        """
        self._audio_graphs_build.cancel()
        self._graph_displays_set.cancel()
        label = item.data(SOUND_COLUMN, Qt.ItemDataRole.UserRole) if item else None
        recordings = self.app_state.get_recordings_for_label(label) if label else []
        self._sound_header_update(label, recordings)
        for card in self._cards:
            card.stop()
        self._active_card = None
        old_cards = self._cards
        cards_container, self._cards = self._cards_build(label, recordings)
        old_cards_container = self._cards_swap_in(cards_container)
        self._cards_set_tab_order()
        self._audio_graphs_build(self._cards)
        self._cards_destroy_later(old_cards, old_cards_container)

    def _cards_build(self, label, recordings):
        """A placeholder card per recording, no audio graphs. Or the empty state."""
        cards_container, layout = self._cards_container_new()
        if label is None:
            components.center_in(layout, components.EmptyState(
                "No sounds yet", "Start with “+ New sound”."))
        elif not recordings:
            components.center_in(layout, components.EmptyState(
                f"“{label}” has no recordings yet"))

        cards = [self._card_new(label, rec) for rec in recordings]
        for card in cards:
            layout.insertWidget(layout.count() - 1, card)
        return cards_container, cards

    def _card_new(self, label, rec):
        """One recording's card, in the current graph display and normalize setting."""
        base = os.path.splitext(rec["filename"])[0]
        card = RecordingCard(base, label, rec["wav_path"], rec["srt_path"])
        card.set_graph_display(self._graph_display)
        card.set_normalized(self._normalized)
        card.playback_started.connect(self._on_card_playback_started)
        card.picked.connect(self._on_card_picked)
        card.playback_failed.connect(self._on_card_playback_failed)
        return card

    def _cards_container_new(self):
        """The empty container the cards stack in, top-aligned. Goes in cards_scroll."""
        cards_container = QWidget()
        layout = QVBoxLayout(cards_container)
        layout.setContentsMargins(20, 12, 24, 12)
        layout.setSpacing(10)
        layout.addStretch()
        return cards_container, layout

    def _cards_swap_in(self, cards_container):
        """Returns the container it replaced."""
        old = self.cards_scroll.takeWidget()
        self.cards_scroll.setWidget(cards_container)
        return old

    def _cards_set_tab_order(self):
        """Order: cards_scroll, Play 1, Play 2 ..."""
        previous = self.cards_scroll
        for card in self._cards:
            QWidget.setTabOrder(previous, card.play_btn)
            previous = card.play_btn

    def _cards_destroy_later(self, cards, cards_container):
        """Once the new cards have painted: a built audio graph takes ~10 ms to free,
        and switching sounds shouldn't wait on the last one's cleanup."""
        next_tick(lambda: self._cards_destroy(cards, cards_container))

    def _cards_destroy(self, cards, cards_container):
        for card in cards:
            card.cleanup()
        cards_container.setParent(None)
        cards_container.deleteLater()

    # ---- header --------------------------------------------------------

    def _sound_header_update(self, label, recordings):
        self.sound_header.setVisible(label is not None)
        if label is None:
            self.cards_scroll.setAccessibleName("Recordings")
            return
        self.sound_title.setText(label)
        self.open_folder_btn.setAccessibleName(f"Open folder for {label}")
        self.open_folder_btn.setToolTip(os.path.normpath(os.path.abspath(get_label_dir(label))))
        count = len(recordings)
        recorded_s = sum(wav_duration(r["wav_path"]) for r in recordings)
        detected_ms = self.app_state.get_label_duration_ms(label)
        noun = "recording" if count == 1 else "recordings"
        self.cards_scroll.setAccessibleName(f"{count} {noun} of {label}")
        self.sound_stats.setText(f"{count} {noun}   ·   {duration_text(recorded_s)} recorded")
        self.sound_quantity.setVisible(count > 0)
        if count:
            self._sound_quantity_update(detected_ms)

    def _sound_quantity_update(self, detected_ms):
        quantity, percent_to_next = get_quantity_rating(detected_ms)
        color = theme.QUANTITY_COLORS.get(quantity, theme.colors()["text"])
        tail = ""
        if quantity != QUANTITIES["excellent"]:
            names = list(QUANTITIES.values())
            next_quantity = names[names.index(quantity) + 1]
            tail = f"   ·   {int(percent_to_next)}% toward “{next_quantity}”"
        self.sound_quantity.setText(
            f"Data quantity:  <b style='color:{color};'>{quantity}</b>"
            f"   ({duration_text(detected_ms / 1000.0)} of detected sound){tail}"
        )

    def _cards_set_graph_display(self, graph_display):
        self._graph_display = graph_display
        # Normalize scales the waveform's height. Spectrograms are always scaled
        # to each take's loudest bin
        self.normalize_btn.setEnabled(graph_display == GRAPH_DISPLAY_WAVEFORM)
        self._graph_displays_set(self._cards)

    def _cards_set_normalized(self, normalized):
        self._normalized = normalized
        for card in self._cards:
            card.set_normalized(normalized)

    def _on_card_playback_started(self, card):
        for other in self._cards:
            if other is not card:
                other.stop()
        self._active_card = card

    def _on_card_picked(self, card):
        self._active_card = card

    def _on_card_playback_failed(self, message):
        QMessageBox.warning(self, "Playback", message)

    def eventFilter(self, obj, event):
        if (obj is self.sound_list and event.type() == QEvent.Type.KeyPress
                and _is_space(event)):
            if not event.isAutoRepeat():
                self._toggle_play()
            return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if _is_space(event):
            if not event.isAutoRepeat():
                self._toggle_play()
        else:
            super().keyPressEvent(event)

    def _toggle_play(self):
        card = self._active_card or next((c for c in self._cards if c.playable()), None)
        if card is not None:
            card.toggle_play()

    def _on_open_sound_folder(self):
        label = self._current_label()
        if not label:
            return
        try:
            library_ops.open_in_file_manager(get_label_dir(label))
        except library_ops.LibraryOpError as exc:
            QMessageBox.warning(self, "Couldn't open folder", str(exc))

    # ---- sound management ------------------------------------------------

    def _current_label(self):
        item = self.sound_list.currentItem()
        return item.data(SOUND_COLUMN, Qt.ItemDataRole.UserRole) if item else None

    def _sound_show(self, label):
        """Re-read the sounds and select `label`, or the first if it's gone."""
        self._sound_list_populate()
        for i in range(self.sound_list.topLevelItemCount()):
            item = self.sound_list.topLevelItem(i)
            if item.data(SOUND_COLUMN, Qt.ItemDataRole.UserRole) == label:
                self.sound_list.setCurrentItem(item)
                return

    def stop_playback(self):
        for card in self._cards:
            card.stop()

    def _sound_menu_show(self, pos):
        item = self.sound_list.itemAt(pos)
        if item is None:
            return
        self.sound_list.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction("Add recording…", self._on_add_recording)
        menu.addAction("Rename…", self._on_rename_sound)
        menu.addAction("Clone…", self._on_clone_sound)
        menu.addAction("Open folder", self._on_open_sound_folder)
        menu.addSeparator()
        menu.addAction("Delete sound", self._on_delete_sound)
        menu.exec(self.sound_list.viewport().mapToGlobal(pos))

    def _on_add_recording(self):
        label = self._current_label()
        if label:
            self.record_requested.emit(label)

    def _on_new_sound(self):
        name = self._new_sound_prompt()
        if name is None:
            return
        self._sound_change("Couldn't create sound", recordings.create_label, name)

    def _on_rename_sound(self):
        label = self._current_label()
        if not label:
            return
        name, ok = QInputDialog.getText(self, "Rename sound", "New name:", text=label)
        if ok:
            self._sound_change("Rename failed", recordings.rename_label, label, name)

    def _on_clone_sound(self):
        label = self._current_label()
        if not label:
            return
        name, ok = QInputDialog.getText(self, "Clone sound", "Name for the copy:",
                                        text=f"{label}_copy")
        if ok:
            self._sound_change("Clone failed", recordings.clone_label, label, name)

    def _on_delete_sound(self):
        label = self._current_label()
        if not label:
            return
        count = len(self.app_state.get_recordings_for_label(label))
        noun = "recording" if count == 1 else "recordings"
        if confirm_destructive(self, title=f"Delete sound '{label}'?",
                               body=f"This permanently deletes the sound '{label}' "
                                    f"and its {count} {noun}.",
                               confirm_text=label, confirm_label="Delete sound"):
            self._sound_change("Delete failed", recordings.delete_label, label)

    def _sound_change(self, failed_title, change, *args):
        """Runs a lib change to a sound, then shows the sound it returns.
        Cards stop first: a playing sound may be the one renamed or deleted."""
        self.stop_playback()
        try:
            label = change(*args)
        except recordings.InvalidLabel as exc:
            QMessageBox.warning(self, failed_title, INVALID_LABEL_TEXT[exc.reason])
            return
        except OSError as exc:
            QMessageBox.warning(self, failed_title, str(exc))
            return
        self.app_state.forget_label_durations()
        self._sound_show(label)

    def _new_sound_prompt(self):
        """Name prompt for a new sound. Not a bare QInputDialog: *which* noise
        you choose decides how well the model can ever do, and this is the one
        moment the app can say so."""
        t = theme.colors()
        dlg = QDialog(self)
        dlg.setWindowTitle("New sound")
        # Wide enough that the diagram reads and the tips don't fight a scrollbar.
        dlg.setMinimumWidth(760)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(8)

        prompt = QLabel("Name for the new sound")
        prompt.setStyleSheet(f"color: {t['text_bright']}; font-weight: bold;")
        v.addWidget(prompt)

        edit = QLineEdit()
        edit.setPlaceholderText("e.g. pop, cluck, hiss")
        edit.setMinimumWidth(300)
        v.addWidget(edit)

        tips_title = QLabel("Choosing a sound")
        tips_title.setStyleSheet(
            f"color: {t['text_bright']}; font-weight: bold; margin-top: 6px;")
        v.addWidget(tips_title)
        v.addWidget(help_dialog.scrolled(
            help_dialog.topic_content("sounds"), max_height=520))

        row = QHBoxLayout()
        row.setContentsMargins(0, 6, 0, 0)
        row.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setObjectName("primaryAction")
        # setDefault alone isn't enough: the box re-picks a default on show and
        # Cancel wins, so Enter silently cancelled. Take Cancel out of the
        # running and accept straight from the field.
        ok.setDefault(True)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setAutoDefault(False)
        row.addWidget(buttons)
        v.addLayout(row)

        def sync_ok():
            """Ok (and Enter) only work once the field holds a name."""
            ready = bool(edit.text().strip())
            ok.setEnabled(ready)
            ok.setStyleSheet(components.primary_button_style() if ready else "")

        edit.textChanged.connect(sync_ok)
        edit.returnPressed.connect(lambda: dlg.accept() if ok.isEnabled() else None)
        sync_ok()
        edit.setFocus()
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        return edit.text()
