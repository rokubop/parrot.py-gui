import os
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QSplitter, QScrollArea, QFrame, QPushButton, QButtonGroup
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6 import sip
from gui.widgets.session_card import SessionCard, _wav_duration
from gui import theme
from lib.srt import ms_to_srt_timestring
from lib.print_status import get_quantity_rating


class SoundLibraryPage(QWidget):
    """Read-only landing page: browse recorded sounds and review each session's
    waveform/spectrogram with detection overlaid. No recording or editing."""

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
        self._select_timer.setInterval(60)
        self._select_timer.timeout.connect(self._build_current)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._setup_ui()
        self._populate_labels()
        self.app_state.recordings_changed.connect(self._populate_labels)

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # Left: sound list — three columns (sound / data quantity / detected time)
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

        # Right: toolbar + scrollable stack of session cards
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self._build_toolbar())

        # Per-sound header (title + stats)
        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 0)
        header_layout.setSpacing(2)
        self.sound_title = QLabel("")
        header_layout.addWidget(self.sound_title)
        self.sound_stats = QLabel("")
        header_layout.addWidget(self.sound_stats)
        self.sound_quantity = QLabel("")
        header_layout.addWidget(self.sound_quantity)
        right_layout.addWidget(header)

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
        # Scope this to the bar itself: a selector-less stylesheet on an ancestor
        # silently breaks :checked background-color on descendant QPushButtons.
        self.toolbar_bar.setStyleSheet(
            f"QWidget#toolbarBar {{ background-color: {t['toolbar']}; "
            f"border-bottom: 1px solid {t['border']}; }}")
        self.view_label.setStyleSheet(f"color: {t['text_dim']};")
        self.hint_label.setStyleSheet(f"color: {t['text_dim']};")
        self.message_label.setStyleSheet(f"color: {t['text_dim']};")
        # A wide, always-present scrollbar plus a right-side gutter gives a
        # dedicated place to scroll the page even when waveforms fill the view.
        self.scroll.setStyleSheet(
            f"QScrollBar:vertical {{ width: 16px; background: {t['base']}; }}")

    def refresh_theme(self):
        self._apply_theme_styles()
        # Rebuild cards so plot colors / borders pick up the new theme.
        self._build_for_item(self.label_list.currentItem())

    def _build_toolbar(self):
        bar = QWidget()
        bar.setObjectName("toolbarBar")
        self.toolbar_bar = bar
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(16, 8, 16, 8)

        self.view_label = QLabel("View:")
        bar_layout.addWidget(self.view_label)
        self._mode_group = QButtonGroup(self)
        self._mode_buttons = {}
        for mode, text in (("waveform", "Waveform"), ("spectrogram", "Spectrogram")):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setChecked(mode == self._mode)
            btn.setToolTip("Toggle waveform / spectrogram (V)")
            btn.clicked.connect(lambda _checked, m=mode: self._set_mode(m))
            self._mode_group.addButton(btn)
            self._mode_buttons[mode] = btn
            bar_layout.addWidget(btn)

        self.normalize_btn = QPushButton("Normalize")
        self.normalize_btn.setCheckable(True)
        self.normalize_btn.setChecked(self._normalized)
        self.normalize_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.normalize_btn.setToolTip("Toggle amplitude normalization (N)")
        self.normalize_btn.toggled.connect(self._set_normalized)
        bar_layout.addSpacing(16)
        bar_layout.addWidget(self.normalize_btn)

        bar_layout.addStretch()
        self.hint_label = QLabel(
            "Space play   ·   F fit   ·   E expand   ·   Home start   ·   Esc clear   ·   "
            "N normalize   ·   V view   ·   drag to select   ·   ↑↓ session")
        bar_layout.addWidget(self.hint_label)
        return bar

    # ---- data ----------------------------------------------------------

    def _populate_labels(self):
        had_selection = self.label_list.currentItem() is not None
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

        if self.label_list.topLevelItemCount() == 0:
            self.sound_title.setText("")
            self.sound_stats.setText("")
            self.sound_quantity.setText("")
            self._show_message("No recordings found in data/recordings/.")
        elif not had_selection:
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
        # Cards/container that are being replaced. We build the new view fully,
        # swap it in, and only THEN destroy these — so tearing down the old
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
                    self._cards.append(card)
                    layout.insertWidget(layout.count() - 1, card)

            # Atomic swap: the scroll area now owns the fully-built container.
            self.scroll.takeWidget()
            self.scroll.setWidget(container)

            if self._cards:
                self._select_card(self._cards[0])
            self.setFocus()
        finally:
            # Now that the new view is live, dismantle the old one.
            self._destroy_cards(old_cards, old_container)
            self._rebuilding = False

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

    def _select_card(self, card):
        if card is self._selected_card:
            return
        if self._selected_card is not None:
            self._selected_card.set_selected(False)
        self._selected_card = card
        card.set_selected(True)

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
            target.fit_view()
        elif key == Qt.Key.Key_E:
            target.toggle_expanded()
        elif key == Qt.Key.Key_Home:
            target.go_to_start()
        elif key == Qt.Key.Key_Escape:
            target.clear_selection()
        elif key == Qt.Key.Key_N:
            self.normalize_btn.setChecked(not self.normalize_btn.isChecked())
        elif key == Qt.Key.Key_V:
            self._toggle_mode()
        else:
            super().keyPressEvent(event)

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
