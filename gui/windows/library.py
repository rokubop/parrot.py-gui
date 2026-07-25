import os
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QSplitter, QScrollArea, QFrame, QPushButton, QButtonGroup,
    QMenu, QInputDialog, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6 import sip
from gui.widgets.session_card import SessionCard, _wav_duration
from gui.widgets.confirm_dialog import confirm_destructive
from gui.services import library_ops
from gui.widgets import help_dialog
from gui import theme
from lib.srt import ms_to_srt_timestring
from lib.print_status import get_quantity_rating


class SoundLibraryPage(QWidget):
    """Read-only landing page: browse recorded sounds and review each session's
    waveform/spectrogram with detection overlaid. No recording or editing."""

    SEEK_STEP = 2.0  # seconds for arrow-key seeking

    # Requests for the full-screen sub-views, handled by MainWindow.
    record_requested = pyqtSignal(str)   # "" = new sound, else add to this label
    edit_requested = pyqtSignal(str)     # wav_path of the recording to edit

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self._cards = []
        self._active_card = None     # currently playing
        self._selected_card = None   # keyboard target
        self._mode = "waveform"
        self._normalized = True
        self._rebuilding = False

        # Debounce selection: rapid clicks through the list collapse to a single
        # build of whatever is finally selected, instead of building (and tearing
        # down) cards for every item flown past.
        self._select_timer = QTimer(self)
        self._select_timer.setSingleShot(True)
        # Short debounce: just enough to collapse a burst of arrow-key scrolling
        # into one build. Builds are cheap now (placeholders), so this can be low.
        self._select_timer.setInterval(15)
        self._select_timer.timeout.connect(self._build_current)

        # Old views awaiting teardown. Destroying loaded pyqtgraph scenes costs
        # ~10 ms each; we defer it to after the new view paints so switching
        # never blocks on the *previous* sound's cleanup.
        self._garbage = []

        # Progressive preview loader: cards are created cheaply (placeholder),
        # then their waveforms are built one per event-loop tick so selecting a
        # sound feels instant instead of freezing while every plot is built.
        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.setInterval(0)
        self._load_timer.timeout.connect(self._load_next_pending)
        self._pending_loads = []

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._setup_ui()
        self._populate_labels()
        self.app_state.recordings_changed.connect(self._populate_labels)

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # Left: sound list - three columns (sound / data quantity / detected time)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 8, 12)
        title_row = QHBoxLayout()
        self.left_title = QLabel("Sounds")
        title_row.addWidget(self.left_title)
        title_row.addStretch()
        title_row.addWidget(help_dialog.help_button(self, "record"))
        left_layout.addLayout(title_row)
        self.label_list = QTreeWidget()
        self.label_list.setColumnCount(3)
        self.label_list.setHeaderLabels(["Sound", "Data", "Time"])
        self.label_list.setRootIsDecorated(False)
        self.label_list.setUniformRowHeights(True)
        header = self.label_list.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.label_list.currentItemChanged.connect(lambda *_: self._select_timer.start())
        self.label_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.label_list.customContextMenuRequested.connect(self._on_list_context_menu)
        left_layout.addWidget(self.label_list)

        new_sound_btn = QPushButton("+ New sound")
        new_sound_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        new_sound_btn.setToolTip("Create a new (empty) sound, then add recordings to it")
        new_sound_btn.clicked.connect(self._on_new_sound)
        left_layout.addWidget(new_sound_btn)

        left.setMinimumWidth(280)
        splitter.addWidget(left)

        # Right: a distinct per-sound header panel + scrollable stack of cards
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self._build_header())

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.cards_container, self.cards_layout, self.message_label = self._new_container()
        self.scroll.setWidget(self.cards_container)
        right_layout.addWidget(self.scroll)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 0)   # left panel keeps its width
        splitter.setStretchFactor(1, 1)   # right side absorbs extra space
        splitter.setSizes([300, 900])

        self._apply_theme_styles()
        self._show_message("Select a sound to review its recordings.")

    def _apply_theme_styles(self):
        t = theme.colors()
        self.left_title.setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {t['text_bright']};")
        self.sound_title.setStyleSheet(
            f"font-size: 20px; font-weight: bold; color: {t['text_bright']};")
        self.sound_stats.setStyleSheet(f"color: {t['text_dim']};")
        self.sound_quantity.setStyleSheet(f"color: {t['text_dim']}; margin-top: 2px;")
        # Scope styles to the objects themselves: a selector-less stylesheet on an
        # ancestor silently breaks :checked background-color on descendant buttons.
        self.header_frame.setStyleSheet(
            f"QFrame#soundHeader {{ background-color: {t['toolbar']}; "
            f"border-bottom: 1px solid {t['border']}; }}")
        # Add recording is the headline action - accent-filled, stands apart.
        self.add_recording_btn.setStyleSheet(
            f"QPushButton#primaryAction {{ background-color: {t['accent']}; color: #ffffff; "
            f"font-weight: bold; border: none; border-radius: 4px; padding: 6px 18px; }} "
            f"QPushButton#primaryAction:hover {{ background-color: {t['accent']}; }}")
        # Rename / Clone / Open / Delete are quiet, second-class actions.
        for b in self._secondary_btns:
            b.setStyleSheet(
                f"QPushButton#secondaryAction {{ color: {t['text_dim']}; border: none; "
                f"background: transparent; padding: 3px 8px; }} "
                f"QPushButton#secondaryAction:hover {{ color: {t['text_bright']}; }}")
        self.view_label.setStyleSheet(f"color: {t['text_dim']};")
        self.message_label.setStyleSheet(f"color: {t['text_dim']};")
        # A wide, always-present scrollbar plus a right-side gutter gives a
        # dedicated place to scroll the page even when waveforms fill the view.
        self.scroll.setStyleSheet(
            f"QScrollBar:vertical {{ width: 16px; background: {t['base']}; }}")

    def refresh_theme(self):
        self._apply_theme_styles()
        # Rebuild cards so plot colors / borders pick up the new theme.
        self._build_for_item(self.label_list.currentItem())

    def _build_header(self):
        """The per-sound header: a visually distinct panel holding the sound's
        title/stats, the primary 'Add recording' action, the view toggles, and
        the de-emphasized rename/clone/delete management actions."""
        header = QFrame()
        header.setObjectName("soundHeader")
        self.header_frame = header
        v = QVBoxLayout(header)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(2)

        self.sound_title = QLabel("")
        v.addWidget(self.sound_title)
        self.sound_stats = QLabel("")
        v.addWidget(self.sound_stats)
        self.sound_quantity = QLabel("")
        v.addWidget(self.sound_quantity)

        # Primary action (left, prominent) + view controls (right).
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 10, 0, 0)
        self.add_recording_btn = QPushButton("+ Add recording")
        self.add_recording_btn.setObjectName("primaryAction")
        self.add_recording_btn.setMinimumHeight(34)
        self.add_recording_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.add_recording_btn.setToolTip("Record a new session for this sound - R")
        self.add_recording_btn.clicked.connect(self._on_add_recording)
        actions.addWidget(self.add_recording_btn)
        actions.addStretch()

        self.view_label = QLabel("View:")
        actions.addWidget(self.view_label)
        self._mode_group = QButtonGroup(self)
        self._mode_buttons = {}
        for mode, text in (("waveform", "Waveform"), ("spectrogram", "Spectrogram")):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setChecked(mode == self._mode)
            btn.setToolTip("Toggle waveform / spectrogram (S)")
            btn.clicked.connect(lambda _checked, m=mode: self._set_mode(m))
            self._mode_group.addButton(btn)
            self._mode_buttons[mode] = btn
            actions.addWidget(btn)

        self.normalize_btn = QPushButton("Normalize")
        self.normalize_btn.setCheckable(True)
        self.normalize_btn.setChecked(self._normalized)
        self.normalize_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.normalize_btn.setToolTip("Toggle amplitude normalization (A)")
        self.normalize_btn.toggled.connect(self._set_normalized)
        actions.addSpacing(12)
        actions.addWidget(self.normalize_btn)
        v.addLayout(actions)

        # Second-class sound management - present but visually quiet.
        secondary = QHBoxLayout()
        secondary.setContentsMargins(0, 4, 0, 0)
        self._secondary_btns = []
        for text, slot, tip in (
                ("Rename", self._on_rename_sound, "Rename this sound"),
                ("Clone", self._on_clone_sound, "Make a copy of this sound under a new name"),
                ("Open folder", self._on_open_sound_folder, "Reveal this sound's folder"),
                ("Delete", self._on_delete_sound, "Delete this sound and all its recordings")):
            btn = QPushButton(text)
            btn.setObjectName("secondaryAction")
            btn.setFlat(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            secondary.addWidget(btn)
            self._secondary_btns.append(btn)
        secondary.addStretch()
        v.addLayout(secondary)
        return header

    # ---- data ----------------------------------------------------------

    def _populate_labels(self):
        # Remember the selected sound by name so an in-place change (a recording
        # added/renamed/deleted, or a sound renamed) keeps focus and rebuilds the
        # right-hand cards instead of leaving a stale view.
        prev_label = self._current_label()
        self.label_list.blockSignals(True)
        self.label_list.clear()
        for label in self.app_state.get_sound_labels():
            duration_ms = self.app_state.get_label_duration_ms(label)
            duration = ms_to_srt_timestring(duration_ms, False).split(",")[0]
            quantity, _pct, _next = get_quantity_rating(duration_ms)
            item = QTreeWidgetItem([label, quantity, duration])
            item.setData(0, Qt.ItemDataRole.UserRole, label)
            color = self._QUANTITY_COLORS.get(quantity)
            if color:
                item.setForeground(1, QColor(color))
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.label_list.addTopLevelItem(item)
        self.label_list.blockSignals(False)

        count = self.label_list.topLevelItemCount()
        if count == 0:
            self.sound_title.setText("")
            self.sound_stats.setText("")
            self.sound_quantity.setText("")
            self._build_for_item(None)
            self._show_message("No sounds yet - click “+ New sound” to start.")
            return

        # Reselect the previous sound if it still exists, else fall back to the
        # first. Setting the current item (signals now unblocked) fires the
        # selection handler, which rebuilds the cards for whatever is selected.
        target = None
        if prev_label is not None:
            for i in range(count):
                if self.label_list.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == prev_label:
                    target = self.label_list.topLevelItem(i)
                    break
        if target is None:
            target = self.label_list.topLevelItem(0)
        # Force a rebuild even when the same row index ends up current.
        self.label_list.setCurrentItem(None)
        self.label_list.setCurrentItem(target)

    def _build_current(self):
        self._build_for_item(self.label_list.currentItem())

    def _build_for_item(self, current):
        if self._rebuilding:
            # A build is already in progress (e.g. re-entered via processEvents).
            # Re-arm so we rebuild for the latest selection once it finishes.
            self._select_timer.start()
            return
        self._rebuilding = True
        # Cancel any in-flight progressive loads for the view we're replacing.
        self._load_timer.stop()
        self._pending_loads = []
        # Cards/container that are being replaced. We build the new view fully,
        # swap it in, and only THEN destroy these - so tearing down the old
        # pyqtgraph scenes can never disturb the layout we're inserting into.
        old_cards = self._cards
        old_container = self.cards_container
        if self._active_card is not None:
            self._active_card.stop()
        self._active_card = None
        self._selected_card = None
        self._cards = []
        try:
            # Build a brand-new container and populate it completely before it
            # is ever shown. Nothing is being deleted during this loop, so the
            # layout cannot die underneath us.
            container, layout, message = self._new_container()
            self.cards_container = container
            self.cards_layout = layout
            self.message_label = message

            recordings = []
            if current is None:
                self.sound_title.setText("")
                self.sound_stats.setText("")
                self.sound_quantity.setText("")
                message.setText("Select a sound to review its recordings.")
            else:
                label = current.data(0, Qt.ItemDataRole.UserRole)
                recordings = self.app_state.get_recordings_for_label(label)
                self._update_sound_header(label, recordings)
                if not recordings:
                    message.setText(f"No recordings for '{label}'.")

            if recordings:
                message.setVisible(False)
                for rec in recordings:
                    base = os.path.splitext(rec["filename"])[0]
                    segments_dir = os.path.join(os.path.dirname(os.path.dirname(rec["wav_path"])), "segments")
                    thresholds_path = os.path.join(segments_dir, base + "_thresholds.txt")
                    card = SessionCard(base, rec["wav_path"], rec["srt_path"], thresholds_path)
                    card.set_mode(self._mode)
                    card.set_normalized(self._normalized)
                    card.started.connect(self._on_card_started)
                    card.selected.connect(self._select_card)
                    card.action.connect(self._on_card_action)
                    self._cards.append(card)
                    layout.insertWidget(layout.count() - 1, card)

            # Atomic swap: the scroll area now owns the fully-built container.
            self.scroll.takeWidget()
            self.scroll.setWidget(container)

            if self._cards:
                # Mark the first card selected (border only - no plot build) so
                # the swap is instant, then queue every card to load in order
                # (selected one first) on subsequent event-loop ticks.
                self._mark_selected(self._cards[0])
                self._pending_loads = list(self._cards)
                self._load_timer.start()
            self.setFocus()
        finally:
            # Queue the old view's teardown for the next event-loop tick so the
            # new (placeholder) view paints first. Multiple rapid switches just
            # stack up and get collected together.
            if old_cards or old_container is not None:
                self._garbage.append((old_cards, old_container))
                QTimer.singleShot(0, self._collect_garbage)
            self._rebuilding = False

    def _collect_garbage(self):
        pending = self._garbage
        self._garbage = []
        for cards, container in pending:
            self._destroy_cards(cards, container)

    def _new_container(self):
        """Create a fresh card container/layout (with a centered message label)."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 12, 24, 12)
        layout.setSpacing(10)
        message = QLabel("")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setStyleSheet(f"color: {theme.colors()['text_dim']};")
        layout.addWidget(message)
        layout.addStretch()
        return container, layout, message

    def _show_message(self, text):
        self.message_label.setText(text)
        self.message_label.setVisible(True)

    def _destroy_cards(self, cards, container):
        """Clean up replaced cards (stop playback/animations, clear their plots)
        and delete the old container they lived in. Runs only after the new view
        is installed, so pyqtgraph never paints an item whose ViewBox is going
        away and the live layout is never touched."""
        for card in cards:
            if not sip.isdeleted(card):
                card.cleanup()
        if container is not None and not sip.isdeleted(container):
            container.setParent(None)
            container.deleteLater()

    # ---- selection / playback coordination -----------------------------

    # Color cues for the data-quantity rating, dimmest -> best.
    _QUANTITY_COLORS = {
        "Not enough": "#e05a5a",
        "Sufficient": "#e0b020",
        "Good": "#5ac8e0",
        "Excellent": "#41d97f",
    }

    def _update_sound_header(self, label, recordings):
        self.sound_title.setText(label)
        count = len(recordings)
        recorded_s = sum(_wav_duration(r["wav_path"]) for r in recordings)
        detected_ms = self.app_state.get_label_duration_ms(label)
        detected_s = detected_ms / 1000.0
        noun = "recording" if count == 1 else "recordings"
        self.sound_stats.setText(
            f"{count} {noun}   ·   {recorded_s:.1f}s recorded   ·   {detected_s:.1f}s detected sound"
        )
        self._update_quantity(detected_ms)

    def _update_quantity(self, detected_ms):
        quantity, percent_to_next, next_quantity = get_quantity_rating(detected_ms)
        color = self._QUANTITY_COLORS.get(quantity, theme.colors()["text"])
        detected_str = ms_to_srt_timestring(int(detected_ms), False).split(",")[0]
        if next_quantity:
            tail = f"   ·   {round(percent_to_next)}% toward “{next_quantity}”"
        else:
            tail = "   ·   plenty of data for training"
        self.sound_quantity.setText(
            f"Data quantity:  <b style='color:{color};'>{quantity}</b>"
            f"   ({detected_str} of detected sound){tail}"
        )

    def _set_mode(self, mode):
        self._mode = mode
        for card in self._cards:
            card.set_mode(mode)

    def _set_normalized(self, normalized):
        self._normalized = normalized
        for card in self._cards:
            card.set_normalized(normalized)

    def _on_card_started(self, card):
        if self._active_card is not None and self._active_card is not card:
            self._active_card.stop()
        self._active_card = card

    def _mark_selected(self, card):
        """Set the selection highlight only (no preview build) - used during a
        rebuild so swapping in the new view never blocks on a plot."""
        if (self._selected_card is not None
                and not sip.isdeleted(self._selected_card)):
            self._selected_card.set_selected(False)
        self._selected_card = card
        card.set_selected(True)

    def _select_card(self, card):
        if card is self._selected_card:
            # Already selected; make sure it's built (a click should show it).
            card.load_preview()
            return
        if self._selected_card is not None:
            self._selected_card.set_selected(False)
        self._selected_card = card
        # A selected card is about to be interacted with - build it now rather
        # than waiting for its turn in the progressive queue.
        card.load_preview()
        card.set_selected(True)

    def _load_next_pending(self):
        """Build one queued card's waveform, then yield to the event loop and
        re-arm for the next - so the UI stays responsive while previews fill in."""
        while self._pending_loads:
            card = self._pending_loads.pop(0)
            if sip.isdeleted(card):
                continue
            card.load_preview()
            if self._pending_loads:
                self._load_timer.start()
            return

    def play_selected(self):
        """Toggle playback of the selected (or first) card. Used by the
        transport bar."""
        target = self._selected_card or (self._cards[0] if self._cards else None)
        if target is not None:
            target.toggle_play()

    # ---- keyboard ------------------------------------------------------

    def keyPressEvent(self, event):
        if not self._cards:
            super().keyPressEvent(event)
            return
        key = event.key()
        target = self._selected_card or self._cards[0]
        if key == Qt.Key.Key_Space:
            target.toggle_play()
        elif key == Qt.Key.Key_Left and self._selected_card:
            self._selected_card.seek_relative(-self.SEEK_STEP)
        elif key == Qt.Key.Key_Right and self._selected_card:
            self._selected_card.seek_relative(self.SEEK_STEP)
        elif key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            self._step_selection(1 if key == Qt.Key.Key_Down else -1)
        elif key == Qt.Key.Key_F:
            target.fit_view()                  # toggle fit (selection / all)
        elif key == Qt.Key.Key_V:
            target.toggle_expanded()           # expand/collapse (taller) view
        elif key in (Qt.Key.Key_D, Qt.Key.Key_Escape):
            target.deselect_or_start()         # deselect, or jump to start
        elif key == Qt.Key.Key_Home:
            target.go_to_start()
        elif key == Qt.Key.Key_A:
            self.normalize_btn.setChecked(not self.normalize_btn.isChecked())
        elif key == Qt.Key.Key_S:
            self._toggle_mode()                # waveform <-> spectrum
        elif key == Qt.Key.Key_R:
            self._on_add_recording()           # record a new session for this sound
        else:
            super().keyPressEvent(event)
        # Note: no X/Delete here - deleting a whole recording is deliberate and
        # only via the button/menu, not a single keypress on a read-only view.

    def keybinding_hint(self):
        return ("Space play  ·  F fit  ·  A normalize  ·  S spectrum  ·  "
                "D deselect/start  ·  V expand  ·  R add recording  ·  ↑↓ select")

    def _toggle_mode(self):
        new_mode = "spectrogram" if self._mode == "waveform" else "waveform"
        self._mode_buttons[new_mode].setChecked(True)
        self._set_mode(new_mode)

    def _step_selection(self, delta):
        if self._selected_card in self._cards:
            index = self._cards.index(self._selected_card)
        else:
            index = 0
        index = max(0, min(len(self._cards) - 1, index + delta))
        card = self._cards[index]
        self._select_card(card)
        self.scroll.ensureWidgetVisible(card)

    # ---- sound-level management ----------------------------------------

    def _current_label(self):
        item = self.label_list.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def _select_label_by_name(self, name):
        for i in range(self.label_list.topLevelItemCount()):
            item = self.label_list.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == name:
                self.label_list.setCurrentItem(item)
                return

    def _on_list_context_menu(self, pos):
        item = self.label_list.itemAt(pos)
        if item is None:
            return
        self.label_list.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction("Add recording…", self._on_add_recording)
        menu.addAction("Rename…", self._on_rename_sound)
        menu.addAction("Clone…", self._on_clone_sound)
        menu.addAction("Open folder", self._on_open_sound_folder)
        menu.addSeparator()
        menu.addAction("Delete sound", self._on_delete_sound)
        menu.exec(self.label_list.viewport().mapToGlobal(pos))

    def _on_new_sound(self):
        name, ok = QInputDialog.getText(self, "New sound", "Name for the new sound:")
        if not ok:
            return
        try:
            label = self.app_state.create_sound(name)
        except library_ops.LibraryOpError as exc:
            QMessageBox.warning(self, "Couldn't create sound", str(exc))
            return
        self._select_label_by_name(label)

    def _on_rename_sound(self):
        label = self._current_label()
        if not label:
            return
        new, ok = QInputDialog.getText(self, "Rename sound", "New name:", text=label)
        if not ok:
            return
        try:
            new_label = self.app_state.rename_sound(label, new)
        except library_ops.LibraryOpError as exc:
            QMessageBox.warning(self, "Rename failed", str(exc))
            return
        self._select_label_by_name(new_label)

    def _on_clone_sound(self):
        label = self._current_label()
        if not label:
            return
        new, ok = QInputDialog.getText(self, "Clone sound",
                                       "Name for the copy:", text=f"{label}_copy")
        if not ok:
            return
        try:
            new_label = self.app_state.clone_sound(label, new)
        except library_ops.LibraryOpError as exc:
            QMessageBox.warning(self, "Clone failed", str(exc))
            return
        self._select_label_by_name(new_label)

    def _on_open_sound_folder(self):
        label = self._current_label()
        if not label:
            return
        try:
            library_ops.open_in_file_manager(library_ops.label_dir(label))
        except library_ops.LibraryOpError as exc:
            QMessageBox.warning(self, "Couldn't open folder", str(exc))

    def _on_delete_sound(self):
        label = self._current_label()
        if not label:
            return
        count = library_ops.sound_recording_count(label)
        body = (f"This permanently deletes the sound '{label}' and its "
                f"{count} recording(s).")
        if confirm_destructive(self, title=f"Delete sound '{label}'?", body=body,
                               confirm_text=label, confirm_label="Delete sound"):
            try:
                self.app_state.delete_sound(label)
            except library_ops.LibraryOpError as exc:
                QMessageBox.warning(self, "Delete failed", str(exc))

    # ---- recording-level management (from card menu) -------------------

    def _on_card_action(self, card, action):
        if action == "delete":
            self._delete_recording(card)
        elif action == "rename":
            self._rename_recording(card)
        elif action == "move":
            self._move_recording(card)
        elif action == "open":
            self._open_recording_folder(card)
        elif action == "edit":
            self._edit_recording(card)

    def _delete_recording(self, card):
        files = library_ops.recording_sibling_files(card.wav_path)
        detail = "\n".join(os.path.basename(f) for f in files)
        name = os.path.basename(card.wav_path)
        if confirm_destructive(
                self, title=f"Delete this recording from “{card.label}”?",
                body=f"This permanently deletes the recording '{name}' from the "
                     f"sound “{card.label}”, along with its detection data.",
                detail=detail, confirm_label="Delete recording"):
            try:
                card.cleanup()
                self.app_state.delete_recording(card.wav_path)
            except library_ops.LibraryOpError as exc:
                QMessageBox.warning(self, "Delete failed", str(exc))

    def _rename_recording(self, card):
        old_base = library_ops.recording_base(card.wav_path)
        new, ok = QInputDialog.getText(self, "Rename recording",
                                       "New name (no extension):", text=old_base)
        if not ok:
            return
        try:
            self.app_state.rename_recording(card.wav_path, new)
        except library_ops.LibraryOpError as exc:
            QMessageBox.warning(self, "Rename failed", str(exc))

    def _move_recording(self, card):
        others = [l for l in self.app_state.get_sound_labels() if l != card.label]
        if not others:
            QMessageBox.information(self, "Move recording",
                                    "There's no other sound to move it to.")
            return
        dest, ok = QInputDialog.getItem(self, "Move recording",
                                        "Move to sound:", others, 0, False)
        if not ok or not dest:
            return
        try:
            self.app_state.move_recording(card.wav_path, dest)
        except library_ops.LibraryOpError as exc:
            QMessageBox.warning(self, "Move failed", str(exc))

    def _open_recording_folder(self, card):
        try:
            library_ops.open_in_file_manager(card.wav_path)
        except library_ops.LibraryOpError as exc:
            QMessageBox.warning(self, "Couldn't open folder", str(exc))

    # ---- recording / editing (full-screen sub-views) -------------------

    def _on_add_recording(self):
        label = self._current_label()
        self.record_requested.emit(label or "")

    def _edit_recording(self, card):
        self.edit_requested.emit(card.wav_path)
