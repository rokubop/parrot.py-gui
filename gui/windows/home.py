"""Home landing page. Re-orients a user returning after months away:
workflow steps with live state, expectations for new users, model + Talon status."""
import os
import time

from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QSizePolicy
)

from config.config import CLASSIFIER_FOLDER
from gui import components, theme
from gui.services import library_ops
from gui.widgets import help_dialog
from gui.services.talon_discovery import find_matching_local_model
from gui.content import program as program_content


def _ago(timestamp):
    """'4 months ago' style. Coarse on purpose."""
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


_recordings_since = library_ops.recordings_since


class _ModelSoundsWorker(QThread):
    """Reads model labels off-thread (unpickling stutters the UI).
    get_model_metadata because labels live in the pkl or the weight files."""
    loaded = pyqtSignal(str, object)   # model name, labels or None

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

    def __init__(self, number, title, action_text, parent=None):
        super().__init__(parent)
        self.setObjectName("stepCard")
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 16)
        v.setSpacing(6)

        # Number and title share a row; a bubble row of its own pushed the
        # status line down a step.
        self.bubble = QLabel(str(number))
        self.bubble.setObjectName("stepBubble")
        self.bubble.setFixedSize(36, 36)
        self.bubble.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bubble_row = QHBoxLayout()
        bubble_row.setSpacing(10)
        bubble_row.addWidget(self.bubble)
        self.number = number
        self.title = QLabel(title)
        self.title.setWordWrap(True)
        bubble_row.addWidget(self.title, 1,
                             Qt.AlignmentFlag.AlignVCenter)
        self.help_btn = QPushButton("?  Help")
        self.help_btn.setFlat(True)
        self.help_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        bubble_row.addWidget(self.help_btn, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(bubble_row)
        # No blurb; longer copy belongs behind ? Help.
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        v.addStretch()

        self.action = QPushButton(action_text)
        self.action.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        v.addWidget(self.action)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_state(self, done, current, status_text,
                  action_text=None, action_primary=False):
        """action_text swaps the button's job as the user progresses (step 3
        becomes Edit patterns once connected); action_primary keeps the bright
        styling on it even when the step is done - the ongoing main action."""
        t = theme.colors()
        self.bubble.setText("✓" if done else str(self.number))
        bubble_bg = t["accent"] if done else (t["button"] if not current else t["panel"])
        bubble_fg = t["accent_text"] if done else t["text_bright"]
        bubble_border = t["accent"] if (done or current) else t["border"]
        self.bubble.setStyleSheet(
            f"QLabel#stepBubble {{ background-color: {bubble_bg}; color: {bubble_fg}; "
            f"border: 2px solid {bubble_border}; border-radius: 18px; "
            f"font-size: {theme.TYPE_SCALE['card']}px; font-weight: bold; }}")
        border = t["accent"] if current else t["border"]
        self.setStyleSheet(
            f"QFrame#stepCard {{ background-color: {t['card']}; "
            f"border: 1px solid {border}; "
            f"border-radius: {t['radius_card']}; }}")
        self.title.setStyleSheet(
            components.heading_style("card") + " border: none;")
        self.help_btn.setStyleSheet(
            f"QPushButton {{ color: {t['text_dim']}; background: transparent; "
            f"border: none; padding: 2px 6px; }} "
            f"QPushButton:hover {{ color: {t['text_bright']}; }}")
        self.status.setStyleSheet(
            f"color: {t['accent'] if done else t['text']}; border: none;")
        self.status.setText(status_text)
        if action_text is not None:
            self.action.setText(action_text)
        self.action.setObjectName(
            "primaryAction" if (current or action_primary) else "")
        self.action.setStyleSheet(
            components.primary_button_style()
            if (current or action_primary) else "")


class HomePage(QWidget):
    navigate = pyqtSignal(str)   # tab name, handled by MainWindow

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self._sounds_worker = None
        self._loaded_sounds = {}   # model name -> labels ([] = unreadable)

        self._setup_ui()

        self.app_state.recordings_changed.connect(self._refresh)
        # retrained/renamed models may have different labels
        self.app_state.models_changed.connect(self._loaded_sounds.clear)
        self.app_state.models_changed.connect(self._refresh)
        self.app_state.talon_status_changed.connect(self._refresh)

        # first refresh runs Talon discovery (an rglob) - defer so the window paints first
        QTimer.singleShot(0, self._refresh)

    # ---- ui --------------------------------------------------------------

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        wrapper = QWidget()
        wrap_layout = QHBoxLayout(wrapper)
        wrap_layout.setContentsMargins(32, 28, 32, 28)
        body = QWidget()
        body.setMaximumWidth(980)
        # heavy body stretch: side gutters absorb only the space past maxWidth,
        # and collapse to ~0 when the window narrows (e.g. notes drawer open)
        wrap_layout.addStretch(1)
        wrap_layout.addWidget(body, 1000)
        wrap_layout.addStretch(1)
        scroll.setWidget(wrapper)

        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(16)

        self.hero_title = QLabel("Parrot.py")
        v.addWidget(self.hero_title)
        self.hero_sub = QLabel(
            "Turn noises into instant actions on your computer.")
        self.hero_sub.setWordWrap(True)
        v.addWidget(self.hero_sub)

        self.steps_widget = QWidget()
        steps_row = QHBoxLayout(self.steps_widget)
        steps_row.setContentsMargins(0, 0, 0, 0)
        steps_row.setSpacing(12)
        # Title says the step, button says where it happens.
        self.step_record = _StepCard(1, "Record sounds", "Open sounds")
        self.step_train = _StepCard(2, "Train a model", "Open models")
        self.step_connect = _StepCard(3, "Integrations", "Open integrations")
        self.step_record.action.clicked.connect(lambda: self.navigate.emit("Sounds"))
        self.step_train.action.clicked.connect(lambda: self.navigate.emit("Models"))
        self._talon_connected = False
        self.step_connect.action.clicked.connect(self._on_connect_action)
        self.step_record.help_btn.clicked.connect(lambda: self._show_help("record"))
        self.step_train.help_btn.clicked.connect(lambda: self._show_help("train"))
        self.step_connect.help_btn.clicked.connect(lambda: self._show_help("connect"))
        for card in (self.step_record, self.step_train, self.step_connect):
            steps_row.addWidget(card, 1)
        v.addWidget(self.steps_widget)

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

        # Only on a fresh empty install; gone for good once anything is
        # recorded or trained. Import stays reachable via Manage profiles.
        from gui.services import profiles as profiles_service
        self.import_panel, self.import_title, self.import_body = self._make_panel(
            "Already used Parrot.py before?")
        self.import_body.setText(
            "Copy sounds and models of an existing install in as a profile. "
            "Original folder is not changed.")
        import_row = QHBoxLayout()
        import_row.setContentsMargins(0, 10, 0, 0)
        find_setup_btn = QPushButton("Import my setup...")
        find_setup_btn.clicked.connect(self._on_find_setup)
        import_row.addWidget(find_setup_btn)
        dismiss_btn = QPushButton("No thanks")
        dismiss_btn.setFlat(True)
        dismiss_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        dismiss_btn.clicked.connect(self._on_dismiss_import)
        import_row.addWidget(dismiss_btn)
        import_row.addStretch()
        self.import_panel.layout().addLayout(import_row)
        self.import_panel.setVisible(self._import_card_due())
        v.addWidget(self.import_panel)

        status_title_row = QHBoxLayout()
        self.status_title = QLabel("Where you're at")
        status_title_row.addWidget(self.status_title)
        status_title_row.addStretch()
        self.open_talon_btn = QPushButton("Open Talon folder")
        self.open_talon_btn.setFlat(True)
        self.open_talon_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.open_talon_btn.setToolTip("Your Talon user folder")
        self.open_talon_btn.clicked.connect(self._on_open_talon_folder)
        self.open_talon_btn.setVisible(False)
        status_title_row.addWidget(self.open_talon_btn)
        self.open_data_btn = QPushButton("Open data folder")
        self.open_data_btn.setFlat(True)
        self.open_data_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.open_data_btn.setToolTip(program_content.DATA_FOLDER_SHORT)
        self.open_data_btn.clicked.connect(self._on_open_data_folder)
        status_title_row.addWidget(self.open_data_btn)
        v.addLayout(status_title_row)
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

        # Non-zero factor: leftover height goes to the bottom of the page, not
        # into the step cards.
        v.addStretch(1)
        self._apply_theme_styles()

    def _import_card_due(self):
        from config.config import DATA_DIR
        from gui.services import profiles as profiles_service
        if profiles_service.import_card_dismissed():
            return False
        return profiles_service.stats(DATA_DIR) == (0, 0)

    def _on_find_setup(self):
        from gui.services import profiles as profiles_service
        from gui.windows.profiles import ImportSetupDialog
        dialog = ImportSetupDialog(self)
        dialog.exec()
        window = self.window()
        if hasattr(window, "_refresh_profile_chip"):
            window._refresh_profile_chip()
        if dialog.imported:
            profiles_service.dismiss_import_card()
            self.import_panel.setVisible(False)

    def _on_open_data_folder(self):
        from config.config import DATA_DIR
        try:
            library_ops.open_in_file_manager(os.path.abspath(DATA_DIR))
        except library_ops.LibraryOpError:
            pass

    def _on_connect_action(self):
        """Step 3's button. Connected, it lands on the patterns editor, which
        is what there is to do once Talon is running your model."""
        self.navigate.emit("Integrations")
        if self._talon_connected:
            window = self.window()
            if hasattr(window, "_get_talon_page"):
                window._get_talon_page().focus_patterns()

    def _on_open_talon_folder(self):
        if getattr(self, "_talon_dir", None):
            try:
                library_ops.open_in_file_manager(self._talon_dir)
            except library_ops.LibraryOpError:
                pass

    def _on_dismiss_import(self):
        from gui.services import profiles as profiles_service
        profiles_service.dismiss_import_card()
        self.import_panel.setVisible(False)

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
        # A word-wrapped rich-text label reports its height for a much narrower
        # width than it gets, which left the panel padded with dead space. Ask
        # the layout for height-for-width and cap the panel at what it needs.
        for w in (body, panel):
            sp = w.sizePolicy()
            sp.setHeightForWidth(True)
            w.setSizePolicy(sp)
        panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        return panel, title_label, body

    def _apply_theme_styles(self):
        t = theme.colors()
        self.hero_title.setStyleSheet(components.heading_style("hero"))
        self.hero_sub.setStyleSheet(
            f"font-size: {theme.TYPE_SCALE['card']}px; color: {t['text_dim']};")
        self.guide_label.setStyleSheet(f"color: {t['text_dim']};")
        self.guide_btn.setStyleSheet(
            f"QPushButton {{ color: {t['accent']}; background: transparent; "
            f"border: none; padding: 2px 4px; text-decoration: underline; }}")
        self.status_title.setStyleSheet(
            components.heading_style("section") + " margin-top: 8px;")
        for panel in (self.model_panel, self.talon_panel, self.import_panel):
            panel.setStyleSheet(
                f"QFrame#homePanel {{ background-color: {t['card']}; "
                f"border: 1px solid {t['border']}; "
                f"border-radius: {t['radius_card']}; }}")
        for label in (self.model_panel_title, self.talon_panel_title,
                      self.import_title):
            label.setStyleSheet(
                components.heading_style("card") + " border: none;")

    def refresh_theme(self):
        self._apply_theme_styles()
        self._refresh()

    # ---- content ----------------------------------------------------------

    def _refresh(self):
        labels = self.app_state.get_sound_labels()
        model_names = self.app_state.get_model_names()
        talon = self.app_state.get_talon_status()
        t = theme.colors()
        self.import_panel.setVisible(self._import_card_due())

        deployed_name = None
        if talon.model_path_from_talon:
            deployed_name = find_matching_local_model(
                talon.model_path_from_talon, CLASSIFIER_FOLDER)

        first_run = not labels and not model_names

        step1_done = len(labels) >= 2
        if not labels:
            s1 = "No sounds yet."
        elif len(labels) == 1:
            s1 = "1 sound - a model needs at least 2."
        else:
            s1 = f"{len(labels)} sounds recorded."

        step2_done = bool(model_names)
        latest_name, latest_mtime = self._latest_model()
        if not model_names:
            s2 = "No models yet."
        else:
            noun = "model" if len(model_names) == 1 else "models"
            s2 = (f"{len(model_names)} {noun} · latest “{latest_name}” "
                  f"trained {_ago(latest_mtime)}.")

        step3_done = deployed_name is not None
        if step3_done:
            count = len(talon.patterns.get("patterns", talon.patterns) or {})
            # The card isn't titled Talon, so this line is the only place naming it.
            s3 = (f"Connected to Talon · {count} patterns using "
                  f"“{deployed_name}”." if count
                  else f"Connected to Talon · running “{deployed_name}”.")
        elif talon.talon_found:
            s3 = "Talon found, but no deployed model matches a local one."
        elif talon.talon_home:
            s3 = "Talon found · parrot integration not set up yet."
        else:
            s3 = "Talon not detected on this machine."

        current = next((i for i, done in enumerate(
            (step1_done, step2_done, step3_done)) if not done), None)
        self.step_record.set_state(step1_done, current == 0, s1)
        self.step_train.set_state(step2_done, current == 1, s2)
        self._talon_connected = step3_done
        self.step_connect.set_state(
            step3_done, current == 2, s3, action_primary=step3_done)
        self.step_connect.action.setToolTip(
            "Tune which sounds trigger what, thresholds and throttles"
            if step3_done else "Find Talon and set up the parrot integration")

        self.status_title.setVisible(not first_run)
        self.status_row_widget.setVisible(not first_run)
        self.open_talon_btn.setVisible(bool(talon.talon_home))
        self._talon_dir = talon.talon_user_dir or talon.talon_home
        if not first_run:
            self._refresh_model_panel(labels, deployed_name, latest_name, latest_mtime, t)
            self._refresh_talon_panel(talon, deployed_name, t)

    def _show_help(self, key):
        help_dialog.show_help(self, key)

    def _latest_model(self):
        best, best_mtime = None, 0
        for name in self.app_state.get_model_names():
            pkl = os.path.join(CLASSIFIER_FOLDER, name + ".pkl")
            if os.path.isfile(pkl):
                mtime = os.path.getmtime(pkl)
                if mtime > best_mtime:
                    best, best_mtime = name, mtime
        return best, best_mtime

    def _refresh_model_panel(self, labels, deployed_name, latest_name, latest_mtime, t):
        name = deployed_name or latest_name
        if name is None:
            self.model_panel_title.setText("Active model")
            self.model_panel_body.setText(
                f"<span style='color:{t['text_dim']};'>No models yet - train one "
                f"from your recorded sounds.</span>")
            return

        pkl = os.path.join(CLASSIFIER_FOLDER, name + ".pkl")
        mtime = os.path.getmtime(pkl) if os.path.isfile(pkl) else latest_mtime
        self.model_panel_title.setText(
            "Active model (deployed to Talon)" if deployed_name
            else "Latest model (not deployed)")

        lines = [f"<b style='color:{t['text_bright']}; "
                 f"font-size:{theme.TYPE_SCALE['card']}px;'>{name}</b>",
                 f"<span style='color:{t['text_dim']};'>Trained {_ago(mtime)}</span>"]

        stale = [(l, n) for l in labels
                 if (n := _recordings_since(l, mtime)[0])]
        if stale:
            takes = sum(n for _, n in stale)
            names = [l for l, _ in stale]
            shown = ", ".join(names[:4]) + ("…" if len(names) > 4 else "")
            noun = "recording" if takes == 1 else "recordings"
            lines.append(
                f"<span style='color:{t['text_dim']};'>{takes} new {noun} "
                f"since this model was trained: {shown}</span>")

        lines.append(self._model_sounds_html(name, labels, t))
        self.model_panel_body.setText("<br>".join(lines))

    def _model_sounds_html(self, name, labels, t):
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
        # [] = unreadable, prevents endless retry
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
                         f"<span style='color:{dim};'>- install Talon, or set it up "
                         f"later; recording and training work without it.</span>")
        if talon.integration_path:
            lines.append(f"<span style='color:{ok};'>✓</span> Parrot integration "
                         f"found")
        elif talon.talon_home:
            lines.append(f"<span style='color:{warn};'>○ No parrot integration "
                         f"yet</span> <span style='color:{dim};'>- the "
                         f"Integrations tab can bootstrap one.</span>")
        if talon.pattern_path_from_talon:
            count = len(talon.patterns.get("patterns", talon.patterns) or {})
            lines.append(f"<span style='color:{ok};'>✓</span> patterns.json "
                         f"<span style='color:{dim};'>({count} entries)</span>")
        if deployed_name:
            lines.append(f"<span style='color:{ok};'>✓</span> Deployed model "
                         f"matches local “{deployed_name}”")
        elif talon.model_path_from_talon:
            exists = os.path.isfile(talon.model_path_from_talon)
            msg = ("doesn't match any local model - retrained since deploying?"
                   if exists else "file is missing")
            lines.append(f"<span style='color:{warn};'>⚠ Talon's model {msg}</span>")
        self.talon_panel_body.setText("<br>".join(lines))

