"""Guided editor for a single Talon pattern.

Laid out like the card it edits: threshold (with detect_after) then the grace
section (graceperiod with its rules) down the left, throttle down the right,
so the dialog reads as the card made editable. A legend column
sits past a rule on the far right, one entry per file key, so the areas are
explained without hunting for tooltips. The dialog opens sized to its content
and grows as rules are added, capped to the screen; the scroll area is
overflow safety, not the plan.

A rule's op is its identity: it is picked once from the Add menu (which lists
only the ops not already used) and then shown as a fixed label - the value
spinner is the only thing that changes. Changing an op is remove + re-add,
because ">power" never *becomes* ">probability"; the wheel and the keyboard
can therefore only ever touch a value.

Every field is constrained to what the integration can actually consume:
sounds come from the deployed model's classes, threshold ops from the schema
authority, throttle targets from the existing pattern names. The Add menus
keep an Other entry for future/unknown keys (warned, not blocked). Validation
runs live on the draft; errors disable Save, warnings are shown but allowed.

Number fidelity: values that are whole numbers are written back as ints for
power/formant fields (so ``">power": 6`` doesn't turn into ``6.0``), while
probability / ratio / seconds keep their float form.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QAbstractSpinBox, QDoubleSpinBox, QCheckBox, QGridLayout, QMenu,
    QInputDialog, QScrollArea, QWidget, QFrame
)

from gui import theme
from gui.services import patterns_schema
from gui.widgets.pattern_card import BAD_COLOR, GRACE_COLOR, MONO

_FLOAT_FIELDS = ("probability", "ratio")


def _coerce_number(op, value):
    """Ints stay ints where the file conventionally uses ints."""
    field = op.lstrip("<>")
    if field not in _FLOAT_FIELDS and float(value).is_integer():
        return int(value)
    return round(float(value), 6)


def _seconds(_target, value):
    """Throttle values are seconds and stay floats, whole or not."""
    return round(float(value), 6)


class _Spin(QDoubleSpinBox):
    """3.4 shows as 3.4, not 3.4000 - the card and the file both write it bare."""

    def textFromValue(self, value):
        text = f"{value:.{self.decimals()}f}".rstrip("0").rstrip(".")
        return text or "0"


def _mono(widget, color):
    widget.setStyleSheet(
        f"color: {color}; font-family: {MONO}; font-size: 12px;")
    return widget


def _check_row(check, spin):
    row = QHBoxLayout()
    row.setSpacing(6)
    row.addWidget(check)
    row.addWidget(spin)
    row.addStretch()
    return row


def _section(text, t, color=None):
    """Same idiom as the card: the lowercase file key, thin rule under it."""
    label = QLabel(text)
    label.setStyleSheet(
        f"color: {color or t['text_dim']}; font-size: 11px; "
        f"border-bottom: 1px solid {t['border']}; padding-bottom: 3px;")
    return label


# One entry per file key, led by "pattern" for the thing being edited.
# grace_threshold comes before graceperiod because graceperiod is defined in
# terms of it. Semantics per the integration template: rules are checked 60
# times a second, detect_after is a hold before the first trigger.
_LEGEND = (
    ("pattern", None,
     "What Talon recognizes. One or more sounds and their settings."),
    ("sounds", None,
     "Sounds from a parrot model."),
    ("threshold", None,
     "The conditions that trigger the pattern. "
     "Checked 60 times a second."),
    ("detect_after", None,
     "The sound must hold this long before the first trigger."),
    ("grace_threshold", GRACE_COLOR,
     "Secondary rules once the pattern has triggered. Lets a sound that "
     "starts loud sustain as it goes quieter."),
    ("graceperiod", GRACE_COLOR,
     "How long grace_threshold stays in effect after the first trigger."),
    ("throttle", None,
     "After a trigger, silences a pattern for N seconds. "
     "On itself: how soon it can trigger again."),
)


def _legend_panel(t):
    """A fixed column of key + one line each, behind a thin left rule."""
    panel = QFrame()
    panel.setObjectName("patternLegend")
    panel.setFixedWidth(220)
    panel.setStyleSheet(
        f"QFrame#patternLegend {{ border: none; "
        f"border-left: 1px solid {t['border']}; }}")
    col = QVBoxLayout(panel)
    col.setContentsMargins(16, 0, 0, 0)
    col.setSpacing(2)
    for i, (key, color, text) in enumerate(_LEGEND):
        if i:
            col.addSpacing(10)
        col.addWidget(_mono(QLabel(key), color or t["text_dim"]))
        line = QLabel(text)
        line.setWordWrap(True)
        line.setStyleSheet(
            f"color: {t['text_dim']}; font-size: 11px; border: none;")
        col.addWidget(line)
    col.addStretch()
    return panel


class _RuleRows:
    """A stack of [op][value][✕] rows under an Add menu of the unused ops."""

    def __init__(self, column, ops, on_change, t, coerce=_coerce_number,
                 add_label="Add rule", other_label="Other…"):
        self.ops = sorted(ops)
        self.on_change = on_change
        self.coerce = coerce
        self.t = t
        self.rows = []
        self.layout = QVBoxLayout()
        self.layout.setSpacing(3)
        column.addLayout(self.layout)
        self.add_btn = QPushButton(add_label)
        self.add_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        menu = QMenu(self.add_btn)
        menu.aboutToShow.connect(lambda: self._fill_menu(menu, other_label))
        self.add_btn.setMenu(menu)
        column.addWidget(self.add_btn, alignment=Qt.AlignmentFlag.AlignLeft)

    def _used(self):
        return {op for _w, op, _s in self.rows}

    def _fill_menu(self, menu, other_label):
        menu.clear()
        used = self._used()
        for op in self.ops:
            if op not in used:
                menu.addAction(op, lambda op=op: self._add_and_notify(op))
        if menu.actions():
            menu.addSeparator()
        menu.addAction(other_label, self._add_other)

    def _add_and_notify(self, op):
        self.add_row(op)
        self.on_change()

    def _add_other(self):
        op, ok = QInputDialog.getText(
            self.add_btn, self.add_btn.text(), "key:")
        op = op.strip()
        if ok and op and op not in self._used():
            self._add_and_notify(op)

    def add_row(self, op, value=None):
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        label = _mono(QLabel(op), self.t["text_dim"])
        spin = _Spin()
        spin.setDecimals(4)
        spin.setRange(-100000, 100000)
        # 3.4 steps to 3.5 and 12000 to 12100: step follows the magnitude.
        spin.setStepType(QAbstractSpinBox.StepType.AdaptiveDecimalStepType)
        spin.setValue(float(value) if value is not None else 0.0)
        spin.setMinimumWidth(90)
        remove = QPushButton("✕")
        # Sized and flattened here: the global QPushButton padding (6px 16px)
        # inside a fixed 24px would clip the glyph away to a plain grey box.
        remove.setFixedSize(24, 24)
        remove.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        remove.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; "
            f"padding: 0; color: {self.t['text_dim']}; font-size: 12px; }} "
            f"QPushButton:hover {{ color: {BAD_COLOR}; }}")
        remove.setToolTip(f"remove {op}")
        row.addWidget(label, 1)
        row.addWidget(spin)
        row.addWidget(remove)
        self.layout.addWidget(row_widget)
        # Shown explicitly: a widget added after the dialog is visible stays
        # hidden until the queued layout pass, and a hidden row is left out
        # of the size hint _fit reads on this same call stack.
        row_widget.show()
        entry = (row_widget, op, spin)
        self.rows.append(entry)
        remove.clicked.connect(lambda: self.remove_row(entry))
        spin.valueChanged.connect(lambda _v: self.on_change())

    def remove_row(self, entry):
        if entry in self.rows:
            self.rows.remove(entry)
            entry[0].setParent(None)
            entry[0].deleteLater()
            self.on_change()

    def value(self):
        rules = {}
        for _w, op, spin in self.rows:
            rules[op] = self.coerce(op, spin.value())
        return rules


class PatternEditDialog(QDialog):
    """Edit (or create) one pattern. ``exec()`` == Accepted means
    ``result_name`` / ``result_pattern`` hold the validated draft."""

    def __init__(self, parent, name, pattern, all_patterns, model_sounds,
                 schema=None, observed=None):
        super().__init__(parent)
        self.setWindowTitle(f"Edit pattern - {name}" if name else "New pattern")
        self.setMinimumSize(860, 540)
        self._original_name = name
        self._all_patterns = all_patterns
        self._model_sounds = model_sounds or []
        self._schema = schema or patterns_schema.default_schema()
        self.result_name = None
        self.result_pattern = None

        pattern = pattern or {}
        t = theme.colors()

        outer = QVBoxLayout(self)
        # Overflow safety only - the two-column body is built to fit without it.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll, 1)
        body = QWidget()
        self._body = body
        split = QHBoxLayout(body)
        split.setSpacing(20)
        layout = QVBoxLayout()
        layout.setSpacing(12)
        split.addLayout(layout, 1)
        split.addWidget(_legend_panel(t))
        scroll.setWidget(body)

        # ---- name
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Pattern name:"))
        self.name_edit = QLineEdit(name or "")
        self.name_edit.textChanged.connect(self._revalidate)
        name_row.addWidget(self.name_edit, 1)
        layout.addLayout(name_row)

        # ---- sounds
        layout.addWidget(_section("sounds", t))
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(4)
        self.sound_checks = {}
        current_sounds = pattern.get("sounds") or []
        known = list(self._model_sounds)
        for extra in current_sounds:            # keep unknown sounds visible
            if extra not in known:
                known.append(extra)
        for i, sound in enumerate(known):
            cb = QCheckBox(sound)
            cb.setChecked(sound in current_sounds)
            if sound not in self._model_sounds:
                cb.setStyleSheet(f"color: {BAD_COLOR};")
                cb.setToolTip("Not a sound the deployed model can produce")
            cb.stateChanged.connect(lambda _s: self._revalidate())
            self.sound_checks[sound] = cb
            grid.addWidget(cb, i // 4, i % 4)
        layout.addLayout(grid)

        # ---- two columns, same split as the card
        columns = QHBoxLayout()
        columns.setSpacing(24)
        layout.addLayout(columns)
        left = QVBoxLayout()
        left.setSpacing(6)
        right = QVBoxLayout()
        right.setSpacing(6)
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        layout.addStretch()

        # ---- thresholds (left)
        ops = self._schema["threshold_ops"]
        left.addWidget(_section("threshold", t))
        if observed:
            from gui.services import session_stats
            info = session_stats.describe(observed)
            if info:
                info_label = QLabel(info)
                info_label.setWordWrap(True)
                info_label.setStyleSheet(
                    f"color: {t['text_dim']}; font-size: 12px; border: none;")
                left.addWidget(info_label)
        self.threshold_rows = _RuleRows(left, ops, self._revalidate, t)
        for op, value in (pattern.get("threshold") or {}).items():
            self.threshold_rows.add_row(op, value)

        # ---- detect_after times the first trigger, so it stays with
        # threshold; graceperiod belongs to the grace section it times.
        self.detect_check, self.detect_spin = self._seconds_row(
            "detect_after (s)", t["text_dim"], pattern.get("detect_after"))
        left.addLayout(_check_row(self.detect_check, self.detect_spin))

        left.addWidget(_section("grace_threshold", t, color=GRACE_COLOR))
        self.grace_check, self.grace_spin = self._seconds_row(
            "graceperiod (s)", GRACE_COLOR, pattern.get("graceperiod"))
        left.addLayout(_check_row(self.grace_check, self.grace_spin))
        self.grace_rows = _RuleRows(left, ops, self._revalidate, t)
        for op, value in (pattern.get("grace_threshold") or {}).items():
            self.grace_rows.add_row(op, value)
        left.addStretch()

        # ---- throttles (right)
        right.addWidget(_section("throttle", t))
        pattern_names = [n for n in all_patterns.keys()]
        if name and name not in pattern_names:
            pattern_names.append(name)
        self.throttle_rows = _RuleRows(
            right, pattern_names, self._revalidate, t, coerce=_seconds,
            add_label="Add throttle", other_label="Other pattern…")
        for target, seconds in (pattern.get("throttle") or {}).items():
            self.throttle_rows.add_row(target, seconds)
        right.addStretch()

        # ---- validation + buttons
        self.issues_label = QLabel("")
        self.issues_label.setWordWrap(True)
        self.issues_label.setStyleSheet(f"color: {t['text_dim']}; font-size: 12px;")
        outer.addWidget(self.issues_label)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.save_btn = QPushButton("Save")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._on_save)
        buttons.addWidget(self.save_btn)
        outer.addLayout(buttons)

        self._revalidate()

    def _seconds_row(self, label, color, value):
        """A checkbox that enables a small seconds spinner beside it."""
        check = _mono(QCheckBox(label), color)
        spin = _Spin()
        spin.setDecimals(3)
        spin.setRange(0, 10)
        spin.setSingleStep(0.05)
        if value is not None:
            check.setChecked(True)
            spin.setValue(float(value))
        check.stateChanged.connect(lambda _s: self._revalidate())
        spin.valueChanged.connect(lambda _v: self._revalidate())
        return check, spin

    def _fit(self):
        """Grow (never shrink) until the body fits unscrolled, screen-capped."""
        # A row added after show is hidden until the queued layout pass runs,
        # and hidden widgets are left out of the size hint - flush it now.
        self._body.layout().activate()
        hint = self._body.sizeHint()
        outer = self.layout()
        m = outer.contentsMargins()
        fixed_h = (m.top() + m.bottom() + 2 * outer.spacing()
                   + self.issues_label.sizeHint().height()
                   + self.save_btn.sizeHint().height())
        want_w = hint.width() + m.left() + m.right()
        want_h = hint.height() + fixed_h + 8
        screen = self.screen()
        if screen is not None:
            avail = screen.availableGeometry()
            want_w = min(want_w, avail.width() - 60)
            want_h = min(want_h, avail.height() - 60)
        self.resize(max(want_w, self.width()), max(want_h, self.height()))

    # ---- draft assembly --------------------------------------------------

    def _draft(self):
        pattern = {}
        sounds = [s for s, cb in self.sound_checks.items() if cb.isChecked()]
        pattern["sounds"] = sounds
        pattern["threshold"] = self.threshold_rows.value()
        grace = self.grace_rows.value()
        if grace:
            pattern["grace_threshold"] = grace
        if self.grace_check.isChecked():
            pattern["graceperiod"] = round(self.grace_spin.value(), 6)
        if self.detect_check.isChecked():
            pattern["detect_after"] = round(self.detect_spin.value(), 6)
        throttle = self.throttle_rows.value()
        if throttle:
            pattern["throttle"] = throttle
        # Preserve unknown keys from the original pattern untouched
        original = self._all_patterns.get(self._original_name) or {}
        for key, value in original.items():
            if key not in self._schema["keys"] and key not in pattern:
                pattern[key] = value
        return self.name_edit.text().strip(), pattern

    def _validate_draft(self):
        name, pattern = self._draft()
        issues = []
        if not name:
            issues.append(patterns_schema.Issue(
                "error", "", "name", "a pattern name is required"))
        elif name != self._original_name and name in self._all_patterns:
            issues.append(patterns_schema.Issue(
                "error", name, "name", "a pattern with this name already exists"))
        merged = dict(self._all_patterns)
        if self._original_name:
            merged.pop(self._original_name, None)
        merged[name or "?"] = pattern
        for issue in patterns_schema.validate(
                merged, self._schema,
                model_sounds=self._model_sounds or None):
            if issue.pattern in (name, ""):
                issues.append(issue)
        return name, pattern, issues

    def _revalidate(self):
        _name, _pattern, issues = self._validate_draft()
        errors = [i for i in issues if i.severity == "error"]
        lines = [str(i) for i in issues[:6]]
        self.issues_label.setText("\n".join(lines))
        self.save_btn.setEnabled(not errors)
        self._fit()                    # rows added later must still fit

    def _on_save(self):
        name, pattern, issues = self._validate_draft()
        if any(i.severity == "error" for i in issues):
            return
        self.result_name = name
        self.result_pattern = pattern
        self.accept()
