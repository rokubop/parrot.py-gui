import os
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QSplitter, QScrollArea, QFrame, QPushButton, QButtonGroup,
    QMessageBox
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6 import sip
from gui.widgets.session_card import SessionCard, _wav_duration
from gui.services import library_ops
from gui import components, theme
from lib.srt import ms_to_srt_timestring
from lib.print_status import get_quantity_rating, QUANTITIES


class SoundLibraryPage(QWidget):
    """Read-only: browse recorded sounds and review each session's
    waveform/spectrogram with detection overlaid."""

    SEEK_STEP = 2.0  # seconds for arrow-key seeking

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

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # Left: sound list
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 8, 12)
        self.left_title = QLabel("Sounds")
        left_layout.addWidget(self.left_title)
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
        left_layout.addWidget(self.label_list)

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
        self.left_title.setStyleSheet(components.heading_style("card"))
        self.sound_title.setStyleSheet(components.heading_style("title"))
        self.sound_stats.setStyleSheet(f"color: {t['text_dim']};")
        self.sound_quantity.setStyleSheet(f"color: {t['text_dim']}; margin-top: 2px;")
        # Scope styles to the objects themselves: a selector-less stylesheet on an
        # ancestor silently breaks :checked background-color on descendant buttons.
        self.header_frame.setStyleSheet(
            f"QFrame#soundHeader {{ background-color: {t['toolbar']}; "
            f"border-bottom: 1px solid {t['border']}; }}")
        self.open_folder_btn.setStyleSheet(components.ghost_button_style())
        # View / Normalize are state toggles, not actions: the app-wide
        # :checked accent fill would make them read as calls to action, so they
        # get a quieter segmented look.
        toggle_style = (
            # $text, not $text_dim: dim on the $button fill measures 3.29, and
            # the unselected half of a segmented control still has to be read.
            f"QPushButton#viewToggle {{ background-color: {t['button']}; "
            f"color: {t['text']}; border: 1px solid {t['control_border']}; "
            f"border-radius: {t['radius']}; padding: 5px 14px; }} "
            f"QPushButton#viewToggle:checked {{ background-color: {t['panel']}; "
            f"color: {t['text_bright']}; border: 1px solid {t['accent']}; }} "
            f"QPushButton#viewToggle:hover {{ color: {t['text_bright']}; }}")
        for b in list(self._mode_buttons.values()) + [self.normalize_btn]:
            b.setStyleSheet(toggle_style)
        self.view_label.setStyleSheet(f"color: {t['text_dim']};")
        self.message_label.setStyleSheet(f"color: {t['text_dim']};")
        # A wide, always-present scrollbar plus a right-side gutter gives a
        # dedicated place to scroll the page even when waveforms fill the view.
        self.scroll.setStyleSheet(
            f"QScrollBar:vertical {{ width: 16px; background: {t['base']}; }}")

    def _build_header(self):
        """Per-sound header: title/stats, view toggles, open folder."""
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

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 10, 0, 0)
        self.open_folder_btn = QPushButton("Open folder")
        self.open_folder_btn.setObjectName("secondaryAction")
        self.open_folder_btn.setFlat(True)
        self.open_folder_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.open_folder_btn.setToolTip("Reveal this sound's folder")
        self.open_folder_btn.clicked.connect(self._on_open_sound_folder)
        actions.addWidget(self.open_folder_btn)
        actions.addStretch()

        self.view_label = QLabel("View:")
        actions.addWidget(self.view_label)
        self._mode_group = QButtonGroup(self)
        self._mode_buttons = {}
        for mode, text in (("waveform", "Waveform"), ("spectrogram", "Spectrogram")):
            btn = QPushButton(text)
            btn.setObjectName("viewToggle")
            btn.setCheckable(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setChecked(mode == self._mode)
            btn.setToolTip("Toggle waveform / spectrogram (S)")
            btn.clicked.connect(lambda _checked, m=mode: self._set_mode(m))
            self._mode_group.addButton(btn)
            self._mode_buttons[mode] = btn
            actions.addWidget(btn)

        self.normalize_btn = QPushButton("Normalize")
        self.normalize_btn.setObjectName("viewToggle")
        self.normalize_btn.setCheckable(True)
        self.normalize_btn.setChecked(self._normalized)
        self.normalize_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.normalize_btn.setToolTip("Toggle amplitude normalization (A)")
        self.normalize_btn.toggled.connect(self._set_normalized)
        actions.addSpacing(12)
        actions.addWidget(self.normalize_btn)
        v.addLayout(actions)
        return header

    # ---- data ----------------------------------------------------------

    def _populate_labels(self):
        self.label_list.blockSignals(True)
        self.label_list.clear()
        for label in self.app_state.get_sound_labels():
            duration_ms = self.app_state.get_label_duration_ms(label)
            duration = ms_to_srt_timestring(duration_ms, False).split(",")[0]
            quantity, _pct = get_quantity_rating(duration_ms)
            item = QTreeWidgetItem([label, quantity, duration])
            item.setData(0, Qt.ItemDataRole.UserRole, label)
            color = theme.QUANTITY_COLORS.get(quantity)
            if color:
                item.setForeground(1, QColor(color))
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.label_list.addTopLevelItem(item)
        self.label_list.blockSignals(False)

        if self.label_list.topLevelItemCount() == 0:
            # _build_for_item owns the empty state (header hidden, message in
            # the body) - don't paint over it with a plain message.
            self._build_for_item(None)
            return
        # Signals are unblocked again, so this fires the selection handler,
        # which builds the cards.
        self.label_list.setCurrentItem(self.label_list.topLevelItem(0))

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
            container, layout, message = self._new_container()
            self.cards_container = container
            self.cards_layout = layout
            self.message_label = message

            recordings = []
            if current is None:
                # Every header control is about *a* sound; with none selected
                # hide the panel entirely.
                self.header_frame.setVisible(False)
                message.setVisible(False)
                if self.label_list.topLevelItemCount() == 0:
                    components.center_in(layout, components.EmptyState(
                        "No sounds yet",
                        "Sounds recorded with settings.py show up here."))
                else:
                    message.setVisible(True)
                    message.setText("Select a sound to review its recordings.")
            else:
                self.header_frame.setVisible(True)
                label = current.data(0, Qt.ItemDataRole.UserRole)
                recordings = self.app_state.get_recordings_for_label(label)
                self._update_sound_header(label, recordings)
                if not recordings:
                    message.setVisible(False)
                    components.center_in(layout, components.EmptyState(
                        f"“{label}” has no recordings yet"))

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
                    card.failed.connect(self._on_card_failed)
                    card.selected.connect(self._select_card)
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
        """Stop and delete replaced cards, only after the new view is installed,
        so pyqtgraph never paints an item whose ViewBox is going away."""
        for card in cards:
            if not sip.isdeleted(card):
                card.cleanup()
        if container is not None and not sip.isdeleted(container):
            container.setParent(None)
            container.deleteLater()

    # ---- selection / playback coordination -----------------------------

    def _update_sound_header(self, label, recordings):
        self.sound_title.setText(label)
        count = len(recordings)
        recorded_s = sum(_wav_duration(r["wav_path"]) for r in recordings)
        detected_ms = self.app_state.get_label_duration_ms(label)
        detected_s = detected_ms / 1000.0
        noun = "recording" if count == 1 else "recordings"
        self.sound_stats.setText(
            f"{count} {noun}   ·   {recorded_s:.1f}s recorded   ·   "
            f"{detected_s:.1f}s detected sound"
        )
        self.sound_quantity.setVisible(count > 0)
        if count:
            self._update_quantity(detected_ms)

    def _update_quantity(self, detected_ms):
        quantity, percent_to_next = get_quantity_rating(detected_ms)
        color = theme.QUANTITY_COLORS.get(quantity, theme.colors()["text"])
        detected_str = ms_to_srt_timestring(int(detected_ms), False).split(",")[0]
        names = list(QUANTITIES.values())
        if quantity != QUANTITIES["excellent"]:
            next_quantity = names[names.index(quantity) + 1]
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

    def _on_card_failed(self, message):
        QMessageBox.warning(self, "Playback", message)

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
        else:
            super().keyPressEvent(event)

    def keybinding_hint(self):
        return ("Space play  ·  F fit  ·  A normalize  ·  S spectrum  ·  "
                "D deselect/start  ·  V expand  ·  ↑↓ select")

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

    # ---- sound-level actions -------------------------------------------

    def _current_label(self):
        item = self.label_list.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def _on_open_sound_folder(self):
        label = self._current_label()
        if not label:
            return
        try:
            library_ops.open_in_file_manager(library_ops.label_dir(label))
        except library_ops.LibraryOpError as exc:
            QMessageBox.warning(self, "Couldn't open folder", str(exc))
