"""Guided editor for a single Talon pattern.

Every field is constrained to what the integration can actually consume:
sounds come from the deployed model's classes, threshold ops from the schema
authority, throttle targets from the existing pattern names. Validation runs
live on the draft; errors disable Save, warnings are shown but allowed.

Number fidelity: values that are whole numbers are written back as ints for
power/formant fields (so ``">power": 6`` doesn't turn into ``6.0``), while
probability / ratio / seconds keep their float form.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QDoubleSpinBox, QCheckBox, QGroupBox, QGridLayout,
    QScrollArea, QWidget, QFrame
)

from gui import theme
from gui.services import patterns_schema

_FLOAT_FIELDS = ("probability", "ratio")


def _coerce_number(op, value):
    """Ints stay ints where the file conventionally uses ints."""
    field = op.lstrip("<>")
    if field not in _FLOAT_FIELDS and float(value).is_integer():
        return int(value)
    return round(float(value), 6)


class _RuleRows:
    """A stack of [op combo][value spin][remove] rows inside a group box."""

    def __init__(self, group, ops, on_change, add_label="Add rule"):
        self.ops = sorted(ops)
        self.on_change = on_change
        self.rows = []
        self.layout = QVBoxLayout()
        group_layout = group.layout()
        group_layout.addLayout(self.layout)
        add_btn = QPushButton(add_label)
        add_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        add_btn.clicked.connect(lambda: (self.add_row(), on_change()))
        group_layout.addWidget(add_btn, alignment=Qt.AlignmentFlag.AlignLeft)

    def add_row(self, op=None, value=None):
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 0)
        op_combo = QComboBox()
        op_combo.addItems(self.ops)
        op_combo.setEditable(True)  # allow future/unknown ops (warned, not blocked)
        if op:
            idx = op_combo.findText(op)
            if idx >= 0:
                op_combo.setCurrentIndex(idx)
            else:
                op_combo.setEditText(op)
        spin = QDoubleSpinBox()
        spin.setDecimals(4)
        spin.setRange(-100000, 100000)
        spin.setValue(float(value) if value is not None else 0.0)
        remove = QPushButton("✕")
        remove.setFixedWidth(30)
        remove.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        row.addWidget(op_combo, 2)
        row.addWidget(spin, 1)
        row.addWidget(remove)
        self.layout.addWidget(row_widget)
        entry = (row_widget, op_combo, spin)
        self.rows.append(entry)
        remove.clicked.connect(lambda: self.remove_row(entry))
        op_combo.currentTextChanged.connect(lambda _t: self.on_change())
        spin.valueChanged.connect(lambda _v: self.on_change())

    def remove_row(self, entry):
        if entry in self.rows:
            self.rows.remove(entry)
            entry[0].setParent(None)
            entry[0].deleteLater()
            self.on_change()

    def value(self):
        rules = {}
        for _w, op_combo, spin in self.rows:
            op = op_combo.currentText().strip()
            if op:
                rules[op] = _coerce_number(op, spin.value())
        return rules


class PatternEditDialog(QDialog):
    """Edit (or create) one pattern. ``exec()`` == Accepted means
    ``result_name`` / ``result_pattern`` hold the validated draft."""

    def __init__(self, parent, name, pattern, all_patterns, model_sounds,
                 schema=None, observed=None):
        super().__init__(parent)
        self.setWindowTitle(f"Edit pattern - {name}" if name else "New pattern")
        self.setMinimumSize(680, 640)
        self._original_name = name
        self._all_patterns = all_patterns
        self._model_sounds = model_sounds or []
        self._schema = schema or patterns_schema.default_schema()
        self.result_name = None
        self.result_pattern = None

        pattern = pattern or {}
        t = theme.colors()

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll, 1)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setSpacing(12)
        scroll.setWidget(body)

        # ---- name
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Pattern name:"))
        self.name_edit = QLineEdit(name or "")
        self.name_edit.textChanged.connect(self._revalidate)
        name_row.addWidget(self.name_edit, 1)
        layout.addLayout(name_row)

        # ---- sounds
        sounds_group = QGroupBox("Sounds (from the deployed model)")
        sounds_layout = QVBoxLayout(sounds_group)
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
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
                cb.setStyleSheet("color: #e06c75;")
                cb.setToolTip("Not a sound the deployed model can produce")
            cb.stateChanged.connect(lambda _s: self._revalidate())
            self.sound_checks[sound] = cb
            grid.addWidget(cb, i // 4, i % 4)
        sounds_layout.addLayout(grid)
        layout.addWidget(sounds_group)

        # ---- thresholds
        ops = self._schema["threshold_ops"]
        thr_group = QGroupBox("Threshold - every rule must pass for a detection")
        QVBoxLayout(thr_group)
        if observed:
            from gui.services import session_stats
            info = session_stats.describe(observed)
            if info:
                info_label = QLabel(info)
                info_label.setWordWrap(True)
                info_label.setStyleSheet(
                    f"color: {t['text_dim']}; font-size: 12px; border: none;")
                thr_group.layout().addWidget(info_label)
        self.threshold_rows = _RuleRows(thr_group, ops, self._revalidate)
        for op, value in (pattern.get("threshold") or {}).items():
            self.threshold_rows.add_row(op, value)
        layout.addWidget(thr_group)

        grace_group = QGroupBox("Grace threshold - softer rules right after a detection")
        QVBoxLayout(grace_group)
        self.grace_rows = _RuleRows(grace_group, ops, self._revalidate)
        for op, value in (pattern.get("grace_threshold") or {}).items():
            self.grace_rows.add_row(op, value)
        layout.addWidget(grace_group)

        # ---- timing
        timing_group = QGroupBox("Timing")
        timing = QGridLayout(timing_group)
        self.grace_check = QCheckBox("Grace period (s):")
        self.grace_spin = QDoubleSpinBox()
        self.grace_spin.setDecimals(3)
        self.grace_spin.setRange(0, 10)
        self.grace_spin.setSingleStep(0.05)
        if pattern.get("graceperiod") is not None:
            self.grace_check.setChecked(True)
            self.grace_spin.setValue(float(pattern["graceperiod"]))
        self.detect_check = QCheckBox("Detect after (s):")
        self.detect_spin = QDoubleSpinBox()
        self.detect_spin.setDecimals(3)
        self.detect_spin.setRange(0, 10)
        self.detect_spin.setSingleStep(0.05)
        if pattern.get("detect_after") is not None:
            self.detect_check.setChecked(True)
            self.detect_spin.setValue(float(pattern["detect_after"]))
        for i, (check, spin) in enumerate(
                ((self.grace_check, self.grace_spin),
                 (self.detect_check, self.detect_spin))):
            timing.addWidget(check, i, 0)
            timing.addWidget(spin, i, 1)
            check.stateChanged.connect(lambda _s: self._revalidate())
            spin.valueChanged.connect(lambda _v: self._revalidate())
        timing.setColumnStretch(2, 1)
        layout.addWidget(timing_group)

        # ---- throttles
        throttle_group = QGroupBox(
            "Throttle - after this fires, silence these patterns for N seconds")
        QVBoxLayout(throttle_group)
        pattern_names = [n for n in all_patterns.keys()]
        if name and name not in pattern_names:
            pattern_names.append(name)
        self.throttle_rows = _RuleRows(
            throttle_group, pattern_names, self._revalidate, "Add throttle")
        for target, seconds in (pattern.get("throttle") or {}).items():
            self.throttle_rows.add_row(target, seconds)
        layout.addWidget(throttle_group)
        layout.addStretch()

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
        throttle = {}
        for _w, combo, spin in self.throttle_rows.rows:
            target = combo.currentText().strip()
            if target:
                throttle[target] = round(spin.value(), 6)
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

    def _on_save(self):
        name, pattern, issues = self._validate_draft()
        if any(i.severity == "error" for i in issues):
            return
        self.result_name = name
        self.result_pattern = pattern
        self.accept()
