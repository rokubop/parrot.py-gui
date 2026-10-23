"""Sounds tab. Read-only: every recorded sound with how much data it has, and
each recording with what detection found in it, to look at and play."""
import os
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QSplitter, QScrollArea, QFrame, QPushButton, QButtonGroup,
    QMessageBox
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6 import sip
from gui.widgets.session_card import SessionCard, wav_duration
from gui.services import library_ops
from gui import components, theme
from lib.srt import ms_to_srt_timestring
from lib.print_status import get_quantity_rating, QUANTITIES


class SoundsPage(QWidget):

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self._cards = []
        self._playing_card = None
        self._mode = "waveform"
        self._normalized = True

        # Arrowing down the list collapses to one build of where it stops,
        # not a build and teardown per sound passed.
        self._select_timer = QTimer(self)
        self._select_timer.setSingleShot(True)
        self._select_timer.setInterval(15)
        self._select_timer.timeout.connect(self._build_current)

        # Cards go in as placeholders, then one plot is built per event loop
        # tick, so picking a sound with many recordings doesn't freeze.
        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.setInterval(0)
        self._load_timer.timeout.connect(self._load_next_pending)
        self._pending_loads = []

        # Replaced views, torn down after the new one paints. A loaded plot
        # costs ~10 ms to destroy.
        self._garbage = []

        self._setup_ui()
        self._populate_labels()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 8, 12)
        self.left_title = QLabel("Sounds")
        left_layout.addWidget(self.left_title)
        self.label_list = QTreeWidget()
        self.label_list.setAccessibleName("Sounds")
        self.label_list.setColumnCount(3)
        self.label_list.setHeaderLabels(["Sound", "Data", "Time"])
        self.label_list.setRootIsDecorated(False)
        self.label_list.setUniformRowHeights(True)
        header = self.label_list.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.label_list.currentItemChanged.connect(lambda *_: self._select_timer.start())
        left_layout.addWidget(self.label_list)

        left.setMinimumWidth(280)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self._build_header())

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        # Always on, and wide: somewhere to scroll the page from when plots
        # fill the view, since the wheel over a plot zooms it.
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.cards_container, self.cards_layout = self._new_container()
        self.scroll.setWidget(self.cards_container)
        right_layout.addWidget(self.scroll)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 900])

        t = theme.colors()
        self.left_title.setStyleSheet(components.heading_style("card"))
        self.sound_title.setStyleSheet(components.heading_style("title"))
        self.sound_stats.setStyleSheet(f"color: {t['text_dim']};")
        self.sound_quantity.setStyleSheet(f"color: {t['text_dim']}; margin-top: 2px;")
        self.header_frame.setStyleSheet(
            f"QFrame#soundHeader {{ background-color: {t['toolbar']}; "
            f"border-bottom: 1px solid {t['border']}; }}")
        self.open_folder_btn.setStyleSheet(components.ghost_button_style())
        # View and Normalize are settings, not actions: the app-wide :checked
        # accent fill would make them read as calls to action.
        toggle_style = (
            # $text, not $text_dim: dim on the $button fill measures 3.29, and
            # the unselected half of a segmented control still has to be read.
            f"QPushButton#viewToggle {{ background-color: {t['button']}; "
            f"color: {t['text']}; border: 1px solid {t['control_border']}; "
            f"border-radius: {t['radius']}; padding: 5px 14px; }} "
            f"QPushButton#viewToggle:checked {{ background-color: {t['panel']}; "
            f"color: {t['text_bright']}; border: 1px solid {t['accent']}; }} "
            f"QPushButton#viewToggle:hover {{ color: {t['text_bright']}; }} "
            f"QPushButton#viewToggle:focus {{ "
            f"border: 2px solid {t['focus']}; padding: 4px 13px; }}")
        for b in list(self._mode_buttons.values()) + [self.normalize_btn]:
            b.setStyleSheet(toggle_style)
        self.view_label.setStyleSheet(f"color: {t['text_dim']};")
        self.scroll.setStyleSheet(
            f"QScrollBar:vertical {{ width: 16px; background: {t['base']}; }}")

    def _build_header(self):
        """Title and stats for the selected sound, view toggles, open folder."""
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
        self.open_folder_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.open_folder_btn.setToolTip("This sound's folder")
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
            btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            btn.setChecked(mode == self._mode)
            btn.clicked.connect(lambda _checked, m=mode: self._set_mode(m))
            self._mode_group.addButton(btn)
            self._mode_buttons[mode] = btn
            actions.addWidget(btn)

        self.normalize_btn = QPushButton("Normalize")
        self.normalize_btn.setObjectName("viewToggle")
        self.normalize_btn.setCheckable(True)
        self.normalize_btn.setChecked(self._normalized)
        self.normalize_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.normalize_btn.setToolTip("Scale each waveform to its loudest point")
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
            self._build_for_item(None)
            return
        # Fires the selection handler, which builds the cards
        self.label_list.setCurrentItem(self.label_list.topLevelItem(0))

    def _build_current(self):
        self._build_for_item(self.label_list.currentItem())

    def _build_for_item(self, current):
        self._load_timer.stop()
        self._pending_loads = []
        # Build the new view fully and swap it in before destroying the old
        # one, so teardown never touches the layout being filled.
        old_cards = self._cards
        old_container = self.cards_container
        if self._playing_card is not None:
            self._playing_card.stop()
            self._playing_card = None
        self._cards = []
        try:
            container, layout = self._new_container()
            self.cards_container = container
            self.cards_layout = layout

            recordings = []
            if current is None:
                # Everything in the header is about a sound
                self.header_frame.setVisible(False)
                components.center_in(layout, components.EmptyState(
                    "No sounds yet",
                    "Sounds recorded with settings.py show up here."))
            else:
                self.header_frame.setVisible(True)
                label = current.data(0, Qt.ItemDataRole.UserRole)
                recordings = self.app_state.get_recordings_for_label(label)
                self._update_sound_header(label, recordings)
                if not recordings:
                    components.center_in(layout, components.EmptyState(
                        f"“{label}” has no recordings yet"))

            for rec in recordings:
                base = os.path.splitext(rec["filename"])[0]
                card = SessionCard(base, rec["wav_path"], rec["srt_path"])
                card.set_mode(self._mode)
                card.set_normalized(self._normalized)
                card.started.connect(self._on_card_started)
                card.failed.connect(self._on_card_failed)
                self._cards.append(card)
                layout.insertWidget(layout.count() - 1, card)

            self.scroll.takeWidget()
            self.scroll.setWidget(container)

            if self._cards:
                self._pending_loads = list(self._cards)
                self._load_timer.start()
        finally:
            if old_cards or old_container is not None:
                self._garbage.append((old_cards, old_container))
                QTimer.singleShot(0, self._collect_garbage)

    def _collect_garbage(self):
        pending = self._garbage
        self._garbage = []
        for cards, container in pending:
            for card in cards:
                if not sip.isdeleted(card):
                    card.cleanup()
            if container is not None and not sip.isdeleted(container):
                container.setParent(None)
                container.deleteLater()

    def _new_container(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 12, 24, 12)
        layout.setSpacing(10)
        layout.addStretch()
        return container, layout

    def _load_next_pending(self):
        """Build one queued plot, then yield to the event loop."""
        while self._pending_loads:
            card = self._pending_loads.pop(0)
            if sip.isdeleted(card):
                continue
            card.load_preview()
            if self._pending_loads:
                self._load_timer.start()
            return

    # ---- header --------------------------------------------------------

    def _update_sound_header(self, label, recordings):
        self.sound_title.setText(label)
        count = len(recordings)
        recorded_s = sum(wav_duration(r["wav_path"]) for r in recordings)
        detected_ms = self.app_state.get_label_duration_ms(label)
        noun = "recording" if count == 1 else "recordings"
        self.sound_stats.setText(
            f"{count} {noun}   ·   {recorded_s:.1f}s recorded   ·   "
            f"{detected_ms / 1000.0:.1f}s detected sound"
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
        if self._playing_card is not None and self._playing_card is not card:
            self._playing_card.stop()
        self._playing_card = card

    def _on_card_failed(self, message):
        QMessageBox.warning(self, "Playback", message)

    def _on_open_sound_folder(self):
        item = self.label_list.currentItem()
        if item is None:
            return
        label = item.data(0, Qt.ItemDataRole.UserRole)
        try:
            library_ops.open_in_file_manager(library_ops.label_dir(label))
        except library_ops.LibraryOpError as exc:
            QMessageBox.warning(self, "Couldn't open folder", str(exc))
