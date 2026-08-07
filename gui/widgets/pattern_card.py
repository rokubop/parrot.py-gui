"""One pattern as a card: `threshold` left, `throttle` right.

Every label is a key out of patterns.json, never a friendlier word for one.
Whoever reads a card also edits that file.

Two columns so a card is as tall as the longer side, not the sum. Patterns
carry six or seven throttles and two threshold rules.

Struck-through target = not a pattern, so the integration ignores it. Struck
rather than red: the palette has reds in it.
"""
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QSizePolicy, QWidget)

from gui import components, theme
from gui.services import pattern_colors
from gui.widgets.session_card import _dots_icon

# theme.PATTERN_STATUS, so this and talon_test.py cannot drift apart.
_T = theme.colors()
THROTTLE_COLOR = theme.status_color("throttled")
GRACE_COLOR = theme.status_color("grace_detected")
BAD_COLOR = _T["bad"]
CHANGED_COLOR = _T["info"]

MONO = "Consolas, 'DejaVu Sans Mono', monospace"

# Floor for an empty grid only. The real one is measured (`_card_floor`) - it
# depends on the longest pattern name and the system font.
MIN_CARD_WIDTH = 300

# The two every pattern has and the two that get tuned. Rest keep file order.
_LEAD_OPS = (">power", ">probability")


def sounds_suffix(name, sounds):
    """`(Alveolar click)` beside the name, or "" when it would only repeat it."""
    sounds = [str(s) for s in sounds] if isinstance(sounds, list) else []
    if not sounds:
        return "(no sounds)"
    if sounds == [name]:
        return ""
    return f"({', '.join(sounds)})"


def order_rules(rules):
    """Threshold rules with the two everyone reads first at the top."""
    rules = rules if isinstance(rules, dict) else {}
    lead = [(op, rules[op]) for op in _LEAD_OPS if op in rules]
    rest = [(op, v) for op, v in rules.items() if op not in _LEAD_OPS]
    return lead + rest


def rule_rows(rules, was=None):
    """[(op, text, changed)] against the deployed pattern.

    A dropped rule still gets a row (`10 → off`), or the card cannot show it.
    """
    rules = rules if isinstance(rules, dict) else {}
    was = was if isinstance(was, dict) else {}
    rows = []
    for op, value in order_rules(rules):
        before = was.get(op)
        if before is not None and before != value:
            rows.append((op, f"{before} → {value}", True))
        else:
            rows.append((op, f"{value}", False))
    for op, value in was.items():
        if op not in rules:
            rows.append((op, f"{value} → off", True))
    return rows


def throttle_rows(name, throttle, was=None):
    """[(target, text, changed, is_self)], own name first.

    Its absence is the one that means something: pattern_detector fills a
    missing own-name entry with 0. So it prints `none`, not nothing.
    """
    throttle = throttle if isinstance(throttle, dict) else {}
    was = was if isinstance(was, dict) else {}

    before = was.get(name)
    if name in throttle:
        value = throttle[name]
        changed = before is not None and before != value
        text = f"{before} → {value}" if changed else f"{value}"
    else:
        changed = before is not None
        text = f"{before} → none" if changed else "none"
    rows = [(name, text, changed, True)]

    for target, value in throttle.items():
        if target == name:
            continue
        before = was.get(target)
        if before is not None and before != value:
            rows.append((target, f"{before} → {value}", True, False))
        else:
            rows.append((target, f"{value}", False, False))
    for target, value in was.items():
        if target != name and target not in throttle:
            rows.append((target, f"{value} → off", True, False))
    return rows


class _ElidedLabel(QLabel):
    """Shrinks by eliding instead of refusing to.

    A QLabel's minimum width is its whole text. The grid sizes columns off the
    widest card, so one long sound list would cost every card a column.
    """

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self._full = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored,
                           QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        shown = QFontMetrics(self.font()).elidedText(
            self._full, Qt.TextElideMode.ElideRight, self.width())
        if shown != self.text():
            self.setText(shown)   # guarded: setText here relayouts and re-enters
        if shown != self._full and not self.toolTip():
            self.setToolTip(self._full)


class PatternCard(QFrame):
    """Click selects, double-click edits, right-click is the row menu.
    The header's Edit and dots buttons are the same two, visible.

    Same three the table answers to: the view changes how a pattern looks,
    not what it does.
    """

    clicked = pyqtSignal(str)
    activated = pyqtSignal(str)
    menu_requested = pyqtSignal(str, object)

    def __init__(self, name, pattern, colors, deployed=None, issues=(),
                 model_sounds=None, is_new=False, parent=None):
        super().__init__(parent)
        self.name = name
        self._selected = False
        self.setObjectName("patternCard")
        self.setMinimumWidth(MIN_CARD_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Minimum)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        pattern = pattern if isinstance(pattern, dict) else {}
        was = deployed if isinstance(deployed, dict) else {}
        t = theme.colors()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 11)
        outer.setSpacing(5)

        outer.addLayout(
            self._header(name, pattern, colors, is_new, issues, model_sounds, t))

        body = QHBoxLayout()
        body.setContentsMargins(0, 3, 0, 0)
        body.setSpacing(18)
        outer.addLayout(body)
        body.addLayout(self._threshold_column(pattern, was, t), 1)
        body.addLayout(self._throttle_column(name, pattern, was, colors, t), 1)

        self._apply_style()

    # ---- columns ---------------------------------------------------------

    def _threshold_column(self, pattern, was, t):
        column = QVBoxLayout()
        column.setSpacing(3)
        column.addWidget(self._section("threshold", t))
        grid = self._grid(column)

        rows = rule_rows(pattern.get("threshold"), was.get("threshold"))
        if not rows:
            self._row(grid, "missing", "", BAD_COLOR, BAD_COLOR,
                      tip="the integration crashes without a threshold")
        for op, text, changed in rows:
            self._row(grid, op, text, t["text_dim"],
                      CHANGED_COLOR if changed else t["text"])

        if pattern.get("detect_after") is not None:
            self._row(grid, "detect_after", f"{pattern['detect_after']}",
                      t["text_dim"], t["text"])
        if pattern.get("graceperiod") is not None:
            self._row(grid, "graceperiod", f"{pattern['graceperiod']}",
                      GRACE_COLOR, t["text"])
        grace = rule_rows(pattern.get("grace_threshold"),
                          was.get("grace_threshold"))
        if grace:
            self._row(grid, "grace_threshold", "", GRACE_COLOR, GRACE_COLOR)
            for op, text, changed in grace:
                self._row(grid, f"  {op}", text, GRACE_COLOR,
                          CHANGED_COLOR if changed else t["text"])
        column.addStretch()
        return column

    def _throttle_column(self, name, pattern, was, colors, t):
        column = QVBoxLayout()
        column.setSpacing(3)
        column.addWidget(self._section("throttle", t))
        grid = self._grid(column)

        for target, text, changed, is_self in throttle_rows(
                name, pattern.get("throttle"), was.get("throttle")):
            known = target in colors
            label, value = self._row(
                grid, target, text,
                colors.get(target, t["text_dim"]) if known else t["text_dim"],
                CHANGED_COLOR if changed
                else t["text_dim"] if not known or text == "none"
                else THROTTLE_COLOR)
            if not known:
                tip = f"'{target}' is not a pattern - this throttle does nothing"
                for widget in (label, value):
                    widget.setStyleSheet(widget.styleSheet()
                                         + " text-decoration: line-through;")
                    widget.setToolTip(tip)
            elif is_self:
                tip = ("how long before this pattern can fire again"
                       if text != "none" else
                       "no throttle on itself, so it fires on every frame "
                       "that passes its threshold")
                label.setToolTip(tip)
                value.setToolTip(tip)
        column.addStretch()
        return column

    # ---- pieces ----------------------------------------------------------

    def _header(self, name, pattern, colors, is_new, issues, model_sounds, t):
        row = QHBoxLayout()
        row.setSpacing(7)
        chip = QLabel("■")
        chip.setStyleSheet(
            f"color: {colors.get(name, pattern_colors.UNKNOWN)}; "
            f"font-size: {theme.TYPE_SCALE['body']}px;")
        row.addWidget(chip)
        title = QLabel(name)
        title.setStyleSheet(components.heading_style("card"))
        row.addWidget(title)

        sounds = pattern.get("sounds")
        sounds = sounds if isinstance(sounds, list) else []
        suffix = sounds_suffix(name, sounds)
        unknown = [s for s in sounds if model_sounds and s not in model_sounds]
        if suffix:
            label = _ElidedLabel(suffix)
            if not sounds or unknown:
                label.setStyleSheet(f"color: {BAD_COLOR}; ")
                label.setToolTip(
                    "at least one sound is required" if not sounds else
                    f"the deployed model does not know {', '.join(unknown)}")
            else:
                label.setStyleSheet(f"color: {t['text_dim']}; ")
            row.addWidget(label, 1)
        else:
            row.addStretch()

        if is_new:
            row.addWidget(components.badge("new", "accent", outlined=False,
                                           tip="not deployed yet"))

        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        parts = []
        if errors:
            parts.append(f"{len(errors)} ✕")
        if warnings:
            parts.append(f"{len(warnings)} ⚠")
        if parts:
            row.addWidget(components.badge(
                "  ".join(parts), "bad" if errors else "warn",
                outlined=False,
                tip="\n".join(str(i) for i in issues)))

        # Same pair the sound cards carry: Edit direct, the rest behind dots.
        edit_btn = QPushButton("Edit")
        edit_btn.setToolTip("Edit this pattern (or double-click the card)")
        edit_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        edit_btn.clicked.connect(self._on_edit_clicked)
        row.addWidget(edit_btn)
        self.menu_btn = QPushButton()
        self.menu_btn.setIcon(_dots_icon(t["text"]))
        self.menu_btn.setIconSize(QSize(13, 13))
        self.menu_btn.setToolTip("Duplicate or delete this pattern")
        self.menu_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.menu_btn.setFixedWidth(40)
        self.menu_btn.clicked.connect(self._on_menu_clicked)
        row.addWidget(self.menu_btn)
        return row

    def _section(self, text, t):
        return components.section_label(text)

    def _grid(self, column):
        grid = QGridLayout()
        grid.setContentsMargins(0, 2, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(1, 1)
        column.addLayout(grid)
        return grid

    def _row(self, grid, label, value, label_color, value_color, tip=None):
        row = grid.rowCount()
        name = QLabel(label)
        name.setStyleSheet(
            f"color: {label_color}; font-family: {MONO}; ")
        val = QLabel(value)
        val.setStyleSheet(
            f"color: {value_color}; font-family: {MONO}; ")
        if tip:
            name.setToolTip(tip)
            val.setToolTip(tip)
        grid.addWidget(name, row, 0)
        grid.addWidget(val, row, 1)
        return name, val

    # ---- selection -------------------------------------------------------

    def set_selected(self, selected):
        if selected != self._selected:
            self._selected = selected
            self._apply_style()

    def _apply_style(self):
        t = theme.colors()
        border = t["accent"] if self._selected else t["border"]
        # Scoped: unscoped, this recolours every label inside.
        self.setStyleSheet(
            f"QFrame#patternCard {{ background-color: {t['panel']}; "
            f"border: 1px solid {border}; "
            f"border-radius: {t['radius_card']}; }} "
            f"QFrame#patternCard QLabel {{ background: transparent; "
            f"border: none; }}")

    # ---- input -----------------------------------------------------------

    def _on_edit_clicked(self):
        self.clicked.emit(self.name)
        self.activated.emit(self.name)

    def _on_menu_clicked(self):
        self.clicked.emit(self.name)
        self.menu_requested.emit(
            self.name,
            self.menu_btn.mapToGlobal(self.menu_btn.rect().bottomLeft()))

    def mousePressEvent(self, event):
        self.clicked.emit(self.name)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.activated.emit(self.name)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        self.clicked.emit(self.name)
        self.menu_requested.emit(self.name, event.globalPos())


class PatternCardGrid(QWidget):
    """Cards packed into columns shortest-first, kudoboard style.

    A grid row is as tall as its tallest card and the difference is dead
    space. Packing spends it on the next card.

    Cost: cards fill down columns, so no longer in file order. Colour is by
    file position and does not move, and nothing here is read as a sequence.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._outer = QHBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(12)
        self._cards = []
        self._columns = 0
        self._floor = MIN_CARD_WIDTH
        self._packed_for = None

    def cards(self):
        return list(self._cards)

    def set_cards(self, cards):
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards = list(cards)
        for card in self._cards:
            card.setParent(self)
        self._floor = self._card_floor()
        self._packed_for = None
        self._repack()

    def _card_floor(self):
        """Widest card's own minimum, so no column is narrower than its content.

        Measured per set_cards: minimumSizeHint walks every label, resizeEvent
        is hot.
        """
        if not self._cards:
            return MIN_CARD_WIDTH
        return max([MIN_CARD_WIDTH]
                   + [card.minimumSizeHint().width() for card in self._cards])

    def _column_count(self):
        gap = self._outer.spacing()
        width = max(self.width(), self._floor)
        return max(1, (width + gap) // (self._floor + gap))

    def _repack(self):
        columns = self._column_count()
        if (columns, len(self._cards), self._floor) == self._packed_for:
            return
        self._packed_for = (columns, len(self._cards), self._floor)
        self._columns = columns

        while self._outer.count():
            item = self._outer.takeAt(0)
            layout = item.layout()
            if layout is not None:
                while layout.count():
                    layout.takeAt(0)
                layout.deleteLater()

        lanes = []
        heights = []
        for _ in range(columns):
            lane = QVBoxLayout()
            lane.setContentsMargins(0, 0, 0, 0)
            lane.setSpacing(12)
            self._outer.addLayout(lane, 1)   # spare width to cards, not margin
            lanes.append(lane)
            heights.append(0)
        for card in self._cards:
            index = heights.index(min(heights))
            lanes[index].addWidget(card)
            heights[index] += card.sizeHint().height() + 12
        for lane in lanes:
            lane.addStretch()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._repack()
