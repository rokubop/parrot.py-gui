"""Home page — orientation for a user who hasn't opened the app in months.

The page answers, at a glance:
  * What is the workflow?            -> the 1-2-3 step bubbles (Record / Train / Connect)
  * Where am I in it?                -> each bubble shows live state; the first
                                        unfinished step is highlighted
  * What model am I actually using?  -> active-model panel (deployed match, or
                                        the most recent local model)
  * What sounds does it know?        -> labels loaded from the pkl off-thread,
                                        diffed against the current library
  * Is it hooked up to Talon?        -> talon panel from the discovery service
  * What did past-me want to say?    -> the global notes, editable in place

Everything is recomputed from AppState on the relevant change signals, so the
page is always a truthful snapshot rather than a cached welcome screen.
"""
import os
import time

from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QTextEdit, QSizePolicy
)

from config.config import CLASSIFIER_FOLDER, RECORDINGS_FOLDER
from gui import theme
from gui.services.talon_discovery import find_matching_local_model


def _ago(timestamp):
    """Rough human 'how long ago' — precision is deliberately coarse; the
    6-months-later user cares about 'months ago', not minutes."""
    seconds = max(0, time.time() - timestamp)
    days = seconds / 86400
    if days < 1:
        return "today"
    if days < 2:
        return "yesterday"
    if days < 60:
        return f"{int(days)} days ago"
    months = days / 30.4
    if months < 24:
        return f"{int(months)} months ago"
    return f"{days / 365.25:.1f} years ago"


def _newest_wav_mtime(label):
    """Newest source recording mtime for a label, or None."""
    source_dir = os.path.join(RECORDINGS_FOLDER, label, "source")
    newest = None
    if os.path.isdir(source_dir):
        for f in os.listdir(source_dir):
            if f.endswith(".wav"):
                try:
                    mtime = os.path.getmtime(os.path.join(source_dir, f))
                except OSError:
                    continue
                if newest is None or mtime > newest:
                    newest = mtime
    return newest


class _ModelSoundsWorker(QThread):
    """Reading a model's labels means unpickling it (and possibly its torch
    weights) — slow enough to stutter the UI, so it runs off-thread. Uses
    get_model_metadata because labels may live in the pkl (sklearn classes_)
    OR in the weight files, depending on the model type; same pattern as the
    Models page's InspectWorker."""
    loaded = pyqtSignal(str, object)   # model name, list-of-labels or None

    def __init__(self, app_state, name, parent=None):
        super().__init__(parent)
        self._app_state = app_state
        self._name = name

    def run(self):
        try:
            meta = self._app_state.get_model_metadata(self._name, load_weights=True)
            self.loaded.emit(self._name, meta["labels"] or None)
        except Exception:
            self.loaded.emit(self._name, None)


class _StepCard(QFrame):
    """One numbered bubble in the Record -> Train -> Connect strip."""

    def __init__(self, number, title, description, action_text, parent=None):
        super().__init__(parent)
        self.setObjectName("stepCard")
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 16)
        v.setSpacing(6)

        self.bubble = QLabel(str(number))
        self.bubble.setObjectName("stepBubble")
        self.bubble.setFixedSize(44, 44)
        self.bubble.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bubble_row = QHBoxLayout()
        bubble_row.addWidget(self.bubble)
        bubble_row.addStretch()
        v.addLayout(bubble_row)

        self.number = number
        self.title = QLabel(title)
        v.addWidget(self.title)
        self.description = QLabel(description)
        self.description.setWordWrap(True)
        v.addWidget(self.description)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        v.addStretch()

        self.action = QPushButton(action_text)
        self.action.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        v.addWidget(self.action)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_state(self, done, current, status_text):
        """done -> checkmark bubble; current -> highlighted card + accent button."""
        t = theme.colors()
        self.bubble.setText("✓" if done else str(self.number))
        bubble_bg = t["accent"] if done else (t["button"] if not current else t["panel"])
        bubble_fg = t["accent_text"] if done else t["text_bright"]
        bubble_border = t["accent"] if (done or current) else t["border"]
        self.bubble.setStyleSheet(
            f"QLabel#stepBubble {{ background-color: {bubble_bg}; color: {bubble_fg}; "
            f"border: 2px solid {bubble_border}; border-radius: 22px; "
            f"font-size: 18px; font-weight: bold; }}")
        border = t["accent"] if current else t["border"]
        self.setStyleSheet(
            f"QFrame#stepCard {{ background-color: {t['card']}; "
            f"border: 1px solid {border}; border-radius: 8px; }}")
        self.title.setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {t['text_bright']}; border: none;")
        self.description.setStyleSheet(f"color: {t['text_dim']}; border: none;")
        self.status.setStyleSheet(
            f"color: {t['accent'] if done else t['text']}; border: none;")
        self.status.setText(status_text)
        if current:
            self.action.setStyleSheet(
                f"QPushButton {{ background-color: {t['accent']}; color: #ffffff; "
                f"font-weight: bold; border: none; border-radius: 4px; padding: 7px 14px; }}")
        else:
            self.action.setStyleSheet("")


class HomePage(QWidget):
    navigate = pyqtSignal(str)          # tab name, handled by MainWindow
    record_requested = pyqtSignal(str)  # "" = new sound

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self._sounds_worker = None
        self._loaded_sounds = {}   # model name -> labels ([] = unreadable)
        self._notes_loaded = False

        self._setup_ui()

        # Debounced auto-save for notes: typing shouldn't hit disk per keystroke.
        self._notes_timer = QTimer(self)
        self._notes_timer.setSingleShot(True)
        self._notes_timer.setInterval(800)
        self._notes_timer.timeout.connect(self._save_notes)

        self.app_state.recordings_changed.connect(self._refresh)
        # A retrained/renamed model may have different labels — forget what we
        # read before, then rebuild.
        self.app_state.models_changed.connect(self._loaded_sounds.clear)
        self.app_state.models_changed.connect(self._refresh)
        self.app_state.talon_status_changed.connect(self._refresh)

        # First refresh runs Talon discovery (an rglob over the Talon user dir)
        # — defer it one event-loop tick so the window paints immediately.
        QTimer.singleShot(0, self._refresh)

    # ---- ui --------------------------------------------------------------

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        # Center a max-width column so the page reads well full-screen.
        wrapper = QWidget()
        wrap_layout = QHBoxLayout(wrapper)
        wrap_layout.setContentsMargins(32, 28, 32, 28)
        body = QWidget()
        body.setMaximumWidth(980)
        wrap_layout.addStretch(1)
        wrap_layout.addWidget(body, 10)
        wrap_layout.addStretch(1)
        scroll.setWidget(wrapper)

        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(16)

        # Hero
        self.hero_title = QLabel("Parrot.py")
        v.addWidget(self.hero_title)
        self.hero_sub = QLabel("")
        self.hero_sub.setWordWrap(True)
        v.addWidget(self.hero_sub)

        # 1-2-3 workflow bubbles
        steps_row = QHBoxLayout()
        steps_row.setSpacing(12)
        self.step_record = _StepCard(
            1, "Record sounds",
            "Record short noises — clicks, pops, hisses. Each sound becomes "
            "a label the model learns. You need at least two.",
            "Record a sound")
        self.step_train = _StepCard(
            2, "Train a model",
            "Turn your recorded sounds into a model that recognizes them "
            "live from the microphone.",
            "Train a model")
        self.step_connect = _StepCard(
            3, "Connect to Talon",
            "Deploy the model and patterns to Talon so your sounds trigger "
            "real actions.",
            "Open Talon setup")
        self.step_record.action.clicked.connect(lambda: self.record_requested.emit(""))
        self.step_train.action.clicked.connect(lambda: self.navigate.emit("Models"))
        self.step_connect.action.clicked.connect(lambda: self.navigate.emit("Talon"))
        for card in (self.step_record, self.step_train, self.step_connect):
            steps_row.addWidget(card, 1)
        v.addLayout(steps_row)

        # Guide link under the bubbles — the 'what do these words mean' escape hatch.
        guide_row = QHBoxLayout()
        self.guide_label = QLabel("New to this, or forgot how it works?")
        guide_row.addWidget(self.guide_label)
        self.guide_btn = QPushButton("Read the guide")
        self.guide_btn.setFlat(True)
        self.guide_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.guide_btn.clicked.connect(lambda: self.navigate.emit("About"))
        guide_row.addWidget(self.guide_btn)
        guide_row.addStretch()
        v.addLayout(guide_row)

        # Where you're at: model + talon panels side by side
        self.status_title = QLabel("Where you're at")
        v.addWidget(self.status_title)
        self.status_row_widget = QWidget()
        status_row = QHBoxLayout(self.status_row_widget)
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(12)
        self.model_panel, self.model_panel_title, self.model_panel_body = \
            self._make_panel("Active model")
        self.talon_panel, self.talon_panel_title, self.talon_panel_body = \
            self._make_panel("Talon")
        status_row.addWidget(self.model_panel, 1)
        status_row.addWidget(self.talon_panel, 1)
        v.addWidget(self.status_row_widget)

        # Notes to your future self
        self.notes_title = QLabel("Notes to your future self")
        v.addWidget(self.notes_title)
        self.notes_hint = QLabel(
            "Anything you'll want to know in six months — which model works "
            "best, what to avoid retraining, mic quirks. Saved automatically.")
        self.notes_hint.setWordWrap(True)
        v.addWidget(self.notes_hint)
        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("e.g. \"cluck model v3 is the good one — "
                                           "don't retrain whistle, it only got worse\"")
        self.notes_edit.setMaximumHeight(120)
        self.notes_edit.textChanged.connect(self._on_notes_changed)
        v.addWidget(self.notes_edit)

        v.addStretch()
        self._apply_theme_styles()

    def _make_panel(self, title):
        panel = QFrame()
        panel.setObjectName("homePanel")
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(16, 12, 16, 14)
        pv.setSpacing(4)
        title_label = QLabel(title)
        pv.addWidget(title_label)
        body = QLabel("")
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.RichText)
        pv.addWidget(body)
        pv.addStretch()
        return panel, title_label, body

    def _apply_theme_styles(self):
        t = theme.colors()
        self.hero_title.setStyleSheet(
            f"font-size: 28px; font-weight: bold; color: {t['text_bright']};")
        self.hero_sub.setStyleSheet(f"font-size: 14px; color: {t['text_dim']};")
        self.guide_label.setStyleSheet(f"color: {t['text_dim']};")
        self.guide_btn.setStyleSheet(
            f"QPushButton {{ color: {t['accent']}; background: transparent; "
            f"border: none; padding: 2px 4px; text-decoration: underline; }}")
        for label in (self.status_title, self.notes_title):
            label.setStyleSheet(
                f"font-size: 16px; font-weight: bold; color: {t['text_bright']}; "
                f"margin-top: 8px;")
        self.notes_hint.setStyleSheet(f"color: {t['text_dim']};")
        for panel in (self.model_panel, self.talon_panel):
            panel.setStyleSheet(
                f"QFrame#homePanel {{ background-color: {t['card']}; "
                f"border: 1px solid {t['border']}; border-radius: 8px; }}")
        for label in (self.model_panel_title, self.talon_panel_title):
            label.setStyleSheet(
                f"font-size: 14px; font-weight: bold; color: {t['text_bright']}; border: none;")

    def refresh_theme(self):
        self._apply_theme_styles()
        self._refresh()

    # ---- content ----------------------------------------------------------

    def _refresh(self):
        labels = self.app_state.get_sound_labels()
        model_names = self.app_state.get_model_names()
        talon = self.app_state.get_talon_status()
        t = theme.colors()

        # Which local model is actually deployed to Talon (byte-identical)?
        deployed_name = None
        if talon.model_path_from_talon:
            deployed_name = find_matching_local_model(
                talon.model_path_from_talon, CLASSIFIER_FOLDER)

        first_run = not labels and not model_names
        if first_run:
            self.hero_sub.setText(
                "Teach your computer to react to sounds you make — clicks, pops, "
                "hisses — for hands-free control. Three steps, top to bottom.")
        else:
            self.hero_sub.setText("Welcome back. Here's where you left off.")

        # ---- step bubbles ----
        step1_done = len(labels) >= 2
        if not labels:
            s1 = "No sounds yet."
        elif len(labels) == 1:
            s1 = "1 sound — a model needs at least 2."
        else:
            s1 = f"{len(labels)} sounds recorded."

        step2_done = bool(model_names)
        latest_name, latest_mtime = self._latest_model()
        if not model_names:
            s2 = "No models yet."
        else:
            noun = "model" if len(model_names) == 1 else "models"
            s2 = (f"{len(model_names)} {noun} — latest “{latest_name}” "
                  f"trained {_ago(latest_mtime)}.")

        step3_done = deployed_name is not None
        if step3_done:
            s3 = f"Hooked up — Talon is running “{deployed_name}”."
        elif talon.talon_found:
            s3 = "Talon found, but no deployed model matches a local one."
        elif talon.talon_home:
            s3 = "Talon found — parrot integration not set up yet."
        else:
            s3 = "Talon not detected on this machine."

        current = next((i for i, done in enumerate(
            (step1_done, step2_done, step3_done)) if not done), None)
        self.step_record.set_state(step1_done, current == 0, s1)
        self.step_train.set_state(step2_done, current == 1, s2)
        self.step_connect.set_state(step3_done, current == 2, s3)
        self.step_record.action.setText(
            "Record your first sound" if not labels else "Record a sound")

        # ---- status panels (hidden on a true first run — nothing to report) ----
        self.status_title.setVisible(not first_run)
        self.status_row_widget.setVisible(not first_run)
        if not first_run:
            self._refresh_model_panel(labels, deployed_name, latest_name, latest_mtime, t)
            self._refresh_talon_panel(talon, deployed_name, t)

        # ---- notes ----
        if not self._notes_loaded:
            notes = self.app_state.load_notes()
            self.notes_edit.blockSignals(True)
            self.notes_edit.setPlainText(notes.get("global_notes", ""))
            self.notes_edit.blockSignals(False)
            self._notes_loaded = True

    def _latest_model(self):
        """(name, mtime) of the most recently trained local model, or (None, 0)."""
        best, best_mtime = None, 0
        for name in self.app_state.get_model_names():
            pkl = os.path.join(CLASSIFIER_FOLDER, name + ".pkl")
            if os.path.isfile(pkl):
                mtime = os.path.getmtime(pkl)
                if mtime > best_mtime:
                    best, best_mtime = name, mtime
        return best, best_mtime

    def _refresh_model_panel(self, labels, deployed_name, latest_name, latest_mtime, t):
        # Prefer the model Talon actually runs; else fall back to the newest.
        name = deployed_name or latest_name
        if name is None:
            self.model_panel_title.setText("Active model")
            self.model_panel_body.setText(
                f"<span style='color:{t['text_dim']};'>No models yet — train one "
                f"from your recorded sounds.</span>")
            return

        pkl = os.path.join(CLASSIFIER_FOLDER, name + ".pkl")
        mtime = os.path.getmtime(pkl) if os.path.isfile(pkl) else latest_mtime
        self.model_panel_title.setText(
            "Active model (deployed to Talon)" if deployed_name
            else "Latest model (not deployed)")

        lines = [f"<b style='color:{t['text_bright']}; font-size:15px;'>{name}</b>",
                 f"<span style='color:{t['text_dim']};'>Trained {_ago(mtime)}</span>"]

        # Staleness: sounds whose newest recording postdates the model.
        stale = [l for l in labels
                 if (m := _newest_wav_mtime(l)) is not None and m > mtime]
        if stale:
            shown = ", ".join(stale[:4]) + ("…" if len(stale) > 4 else "")
            lines.append(
                f"<span style='color:#e0b020;'>⚠ {len(stale)} sound(s) have new "
                f"recordings since this model was trained: {shown}</span>")

        lines.append(self._model_sounds_html(name, labels, t))
        self.model_panel_body.setText("<br>".join(lines))

    def _model_sounds_html(self, name, labels, t):
        """The sounds the model knows — loaded off-thread on first request."""
        if name not in self._loaded_sounds:
            self._start_sounds_worker(name)
            return f"<span style='color:{t['text_dim']};'>Reading its sounds…</span>"
        model_labels = self._loaded_sounds[name]
        if not model_labels:
            return (f"<span style='color:{t['text_dim']};'>Couldn't read this "
                    f"model's sound list.</span>")
        listed = ", ".join(model_labels)
        parts = [f"<span style='color:{t['text']};'>Knows {len(model_labels)} sounds:</span> "
                 f"<span style='color:{t['text_dim']};'>{listed}</span>"]
        unused = [l for l in labels if l not in model_labels]
        if unused:
            shown = ", ".join(unused[:4]) + ("…" if len(unused) > 4 else "")
            parts.append(f"<br><span style='color:{t['text_dim']};'>Not in this model: "
                         f"{shown}</span>")
        return "".join(parts)

    def _start_sounds_worker(self, name):
        if self._sounds_worker is not None and self._sounds_worker.isRunning():
            return
        self._sounds_worker = _ModelSoundsWorker(self.app_state, name, self)
        self._sounds_worker.loaded.connect(self._on_sounds_loaded)
        self._sounds_worker.start()

    def _on_sounds_loaded(self, name, sounds):
        # [] means unreadable — remembered so we don't loop retrying forever.
        self._loaded_sounds[name] = sounds if sounds is not None else []
        self._refresh()

    def _refresh_talon_panel(self, talon, deployed_name, t):
        ok, warn, dim = t["accent"], "#e0b020", t["text_dim"]
        lines = []
        if talon.talon_home:
            lines.append(f"<span style='color:{ok};'>✓</span> Talon installed "
                         f"<span style='color:{dim};'>({talon.talon_home})</span>")
        else:
            lines.append(f"<span style='color:{warn};'>✗ Talon not found</span> "
                         f"<span style='color:{dim};'>— install Talon, or set it up "
                         f"later; recording and training work without it.</span>")
        if talon.integration_path:
            lines.append(f"<span style='color:{ok};'>✓</span> Parrot integration "
                         f"found")
        elif talon.talon_home:
            lines.append(f"<span style='color:{warn};'>○ No parrot integration "
                         f"yet</span> <span style='color:{dim};'>— the Talon tab can "
                         f"bootstrap one.</span>")
        if talon.pattern_path_from_talon:
            count = len(talon.patterns.get("patterns", talon.patterns) or {})
            lines.append(f"<span style='color:{ok};'>✓</span> patterns.json "
                         f"<span style='color:{dim};'>({count} entries)</span>")
        if deployed_name:
            lines.append(f"<span style='color:{ok};'>✓</span> Deployed model "
                         f"matches local “{deployed_name}”")
        elif talon.model_path_from_talon:
            exists = os.path.isfile(talon.model_path_from_talon)
            msg = ("doesn't match any local model — retrained since deploying?"
                   if exists else "file is missing")
            lines.append(f"<span style='color:{warn};'>⚠ Talon's model {msg}</span>")
        self.talon_panel_body.setText("<br>".join(lines))

    # ---- notes -------------------------------------------------------------

    def _on_notes_changed(self):
        self._notes_timer.start()

    def _save_notes(self):
        # Re-read at save time so per-model notes edited elsewhere aren't lost.
        notes = self.app_state.load_notes()
        notes["global_notes"] = self.notes_edit.toPlainText()
        self.app_state.save_notes(notes)
