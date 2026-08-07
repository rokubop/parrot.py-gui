"""Integrations tab - first-party Talon integration.

Talon is the only integration there is, so the page is the Talon page with a
name that leaves room for a second one; nothing here is generalised ahead of a
real second case.

Status (discovery, deployed-model match, health lints) + the patterns
editor: a working copy of the deployed patterns.json is edited through the
guided dialog (or raw JSON), can be stored as named variants, and is only
written back to Talon via Deploy - which snapshots the deployed file first.
Talon hot-reloads patterns.json (``@resource.watch``), so deploys apply live.

Discovery + model unpickling run off the UI thread; Refresh re-runs both.
"""
import json
import os

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox,
    QScrollArea, QFrame, QTableWidget, QTableWidgetItem,
    QComboBox, QMessageBox, QInputDialog, QDialog,
    QPlainTextEdit, QListWidget, QListWidgetItem, QStackedWidget, QMenu,
    QToolButton, QSizePolicy
)

from gui import components, theme
from gui.components import primary_button_style
from gui.services import (talon_discovery, patterns_schema, patterns_store,
                          talon_companion, talon_setup, library_ops,
                          pattern_colors, integration_sim)
from gui.widgets.pattern_edit_dialog import PatternEditDialog
from gui.widgets.pattern_card import PatternCard, PatternCardGrid
from gui.widgets.bridge_dialog import BridgeDialog
from gui.widgets.change_model_dialog import ChangeModelDialog
from gui.widgets.setup_panel import SetupPanel
from gui.widgets import help_dialog
from gui.windows.talon_test import TalonTestView
from gui.windows.talon_captures import TalonCapturesView
from config.config import CLASSIFIER_FOLDER


def _copy(patterns):
    return json.loads(json.dumps(patterns))


def _beta_links():
    return (components.link(talon_discovery.TALON_BETA_URL,
                            "How to get the beta")
            + " · "
            + components.link(talon_discovery.TALON_URL, "talonvoice.com"))


class DiscoveryWorker(QThread):
    """Full discovery bundle off the UI thread (rglob + joblib unpickle)."""
    loaded = pyqtSignal(object)

    def run(self):
        bundle = {"result": None, "schema": None, "model_sounds": None,
                  "local_match": None, "issues": []}
        try:
            result = talon_discovery.discover_talon()
            bundle["result"] = result
            if result.integration_path:
                bundle["schema"] = patterns_schema.schema_from_integration(
                    result.integration_path)
            else:
                bundle["schema"] = patterns_schema.default_schema()
            if result.model_path_from_talon:
                bundle["local_match"] = talon_discovery.find_matching_local_model(
                    result.model_path_from_talon, CLASSIFIER_FOLDER)
                bundle["model_sounds"] = talon_discovery.load_model_sounds(
                    result.model_path_from_talon)
            if result.patterns:
                bundle["issues"] = patterns_schema.validate(
                    result.patterns, bundle["schema"],
                    model_sounds=bundle["model_sounds"])
        except Exception as exc:
            bundle["error"] = str(exc)
        self.loaded.emit(bundle)


def _fmt_threshold(rules, was=None):
    """The rules, and where the draft moved one, `>probability 0.93 → 0.94`.

    Per rule rather than per pattern: printing the whole old threshold beside
    the whole new one makes the reader diff two identical-looking strings to
    find the digit that changed.
    """
    if not isinstance(rules, dict):
        return ""
    was = was if isinstance(was, dict) else {}
    parts = []
    for op, value in rules.items():
        before = was.get(op)
        if before is not None and before != value:
            parts.append(f"{op} {before} → {value}")
        else:
            parts.append(f"{op} {value}")
    for op, value in was.items():
        if op not in rules:
            parts.append(f"{op} {value} → off")
    return "   ".join(parts)


class TalonPage(QWidget):
    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.worker = None
        self._bundle = None
        self._deployed = {}     # what's on disk at the Talon path right now
        self.working = {}       # the copy being edited
        self._patterns_missing = False
        self._raw_bundle = None
        self._sim = {"bundle": "off", "bridge": "off"}
        # Two views of one selection, and only one of them is a table.
        self._selected = None
        self._view = "cards"
        self._setup_ui()
        self.refresh()

    @property
    def dirty(self):
        return self.working != self._deployed

    @property
    def _patterns_path(self):
        result = self._bundle.get("result") if self._bundle else None
        return result.pattern_path_from_talon if result else None

    # ---- ui -------------------------------------------------------------

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        # Three whole screens rather than tabs: testing wants the window, and
        # the A/B workbench is where a draft goes to be tried, not a place you
        # browse to.
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.stack.addWidget(scroll)

        self.test_view = TalonTestView()
        self.test_view.done.connect(self._show_main)
        self.stack.addWidget(self.test_view)

        self.captures_view = TalonCapturesView(
            get_deployed=lambda: self._deployed,
            get_working=lambda: self.working)
        captures_wrap = QWidget()
        captures_layout = QVBoxLayout(captures_wrap)
        captures_layout.setContentsMargins(16, 10, 16, 10)
        back_row = QHBoxLayout()
        captures_back = QPushButton("‹  Back")
        captures_back.setFlat(True)
        captures_back.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        captures_back.clicked.connect(self._show_main)
        back_row.addWidget(captures_back)
        back_row.addWidget(QLabel("Try a draft against a recorded session"), 1)
        captures_layout.addLayout(back_row)
        captures_layout.addWidget(self.captures_view, 1)
        self.stack.addWidget(captures_wrap)

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(28, 22, 28, 24)
        layout.setSpacing(14)
        scroll.setWidget(body)

        layout.addWidget(self._build_connection_card())
        layout.addWidget(self._build_details())
        layout.addWidget(self._build_draft_banner())
        layout.addWidget(self._build_patterns_section(), 1)
        self._build_hidden_controls()

    # ---- main page pieces ------------------------------------------------

    def _build_connection_card(self):
        t = theme.colors()
        card = QFrame()
        card.setObjectName("connCard")
        # Gradient, not flat $panel: this one sits directly on the window.
        card.setStyleSheet(components.card_style(
            "connCard", surface="card", children="QLabel"))
        row = QHBoxLayout(card)
        row.setContentsMargins(*components.CARD_MARGINS)
        row.setSpacing(16)

        who = QVBoxLayout()
        who.setSpacing(2)
        self.conn_name = components.heading("Talon", "section")
        who.addWidget(self.conn_name)
        self.conn_facts = QLabel("…")
        self.conn_facts.setWordWrap(True)
        self.conn_facts.setTextFormat(Qt.TextFormat.RichText)
        who.addWidget(self.conn_facts)
        row.addLayout(who, 1)

        # Loud on purpose: a simulated state that looks real is worse than no
        # simulation. Only ever visible with PARROT_DEBUG=1.
        self.sim_chip = QLabel("")
        self.sim_chip.setStyleSheet(
            f"color: {t['window']}; background-color: {t['warn']}; "
            f"border-radius: {t['radius_pill']}; padding: 3px 12px; "
            f"font-weight: bold;")
        self.sim_chip.setVisible(False)
        row.addWidget(self.sim_chip)

        self.change_model_btn = QPushButton("Change model…")
        self.change_model_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.change_model_btn.setToolTip(
            "Put a different trained model in the Talon folder")
        self.change_model_btn.clicked.connect(self._on_change_model)
        row.addWidget(self.change_model_btn)

        self.test_btn = QPushButton("Test integration")
        self.test_btn.setObjectName("primaryAction")
        self.test_btn.setMinimumHeight(32)
        self.test_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.test_btn.setStyleSheet(primary_button_style())
        self.test_btn.setToolTip(
            "Watch what Talon actually hears, sound by sound")
        self.test_btn.clicked.connect(self._show_test)
        row.addWidget(self.test_btn)
        row.addWidget(help_dialog.help_button(self, "connect"))

        self.more_btn = QToolButton()
        self.more_btn.setText("⋯")
        self.more_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.more_btn.setToolTip("Files, variants, snapshots, the bridge")
        self.more_btn.setStyleSheet(
            f"QToolButton {{ color: {t['text_dim']}; border: none; "
            f"padding: 6px 10px; font-size: {theme.TYPE_SCALE['card']}px; }} "
            f"QToolButton::menu-indicator {{ image: none; }} "
            f"QToolButton:hover {{ color: {t['text_bright']}; }}")
        self._more_menu = QMenu(self)
        self._more_menu.aboutToShow.connect(self._build_more_menu)
        self.more_btn.setMenu(self._more_menu)
        row.addWidget(self.more_btn)
        return card

    def _build_details(self):
        """The paths. Off by default: they answer a question nobody asks twice."""
        t = theme.colors()
        self.details_group = QGroupBox("Files")
        self.details_group.setVisible(False)
        details_layout = QVBoxLayout(self.details_group)
        self.status_rows = {}
        for key, label in (
                ("talon", "Talon"),
                ("integration", "Integration"),
                ("patterns", "patterns.json"),
                ("model", "Deployed model"),
                ("companion", "Bridge")):
            line = QHBoxLayout()
            name = QLabel(f"{label}:")
            name.setFixedWidth(120)
            name.setStyleSheet(f"color: {t['text_dim']};")
            value = QLabel("…")
            value.setWordWrap(True)
            value.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            line.addWidget(name, alignment=Qt.AlignmentFlag.AlignTop)
            line.addWidget(value, 1)
            self.status_rows[key] = value
            details_layout.addLayout(line)
        return self.details_group

    def _build_draft_banner(self):
        """Edits go to a working copy; Talon still runs the deployed set, and
        the two ways out of that are the two buttons here."""
        t = theme.colors()
        banner = QFrame()
        banner.setObjectName("draftBanner")
        banner.setStyleSheet(
            f"QFrame#draftBanner {{ background-color: rgba(90, 175, 245, 0.10); "
            f"border: 1px solid rgba(90, 175, 245, 0.45); "
            f"border-radius: {t['radius_card']}; }} "
            f"QFrame#draftBanner QLabel {{ background: transparent; "
            f"border: none; color: {t['text']}; }}")
        row = QHBoxLayout(banner)
        row.setContentsMargins(14, 9, 14, 9)
        row.setSpacing(8)
        self.draft_label = QLabel("")
        self.draft_label.setWordWrap(True)
        row.addWidget(self.draft_label, 1)
        self.discard_btn = QPushButton("Discard")
        self.discard_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.discard_btn.clicked.connect(self._on_discard_draft)
        row.addWidget(self.discard_btn)
        self.try_btn = QPushButton("Try it on a recording")
        self.try_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.try_btn.setToolTip(
            "Replay a recorded session through this draft and the deployed set, "
            "frame for frame - no deploy needed to find out")
        self.try_btn.clicked.connect(self._show_captures)
        row.addWidget(self.try_btn)
        self.deploy_btn = QPushButton("Deploy to Talon")
        self.deploy_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.deploy_btn.clicked.connect(self._on_deploy)
        row.addWidget(self.deploy_btn)
        self.draft_banner = banner
        banner.setVisible(False)
        return banner

    def _build_patterns_section(self):
        t = theme.colors()
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        head = QHBoxLayout()
        self.patterns_title = QLabel("Patterns")
        self.patterns_title.setTextFormat(Qt.TextFormat.RichText)
        self.patterns_title.setStyleSheet(components.heading_style("card"))
        head.addWidget(self.patterns_title)
        self.health_label = QLabel("")
        self.health_label.setTextFormat(Qt.TextFormat.RichText)
        head.addWidget(self.health_label)
        head.addStretch()
        self.hint_label = QLabel("double-click to edit · right-click for more")
        self.hint_label.setStyleSheet(f"color: {t['text_dim']};")
        head.addWidget(self.hint_label)
        head.addWidget(self._build_view_toggle())
        self.new_btn = QPushButton("+ New pattern")
        self.new_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.new_btn.clicked.connect(self._on_new)
        head.addWidget(self.new_btn)
        v.addLayout(head)

        # Cards group a pattern into one block. The table is the one that
        # reads down a column, for "which of these is the odd one out".
        self.card_grid = PatternCardGrid()
        self.table = self._build_table()
        self.views = QStackedWidget()
        self.views.addWidget(self.card_grid)
        self.views.addWidget(self.table)
        v.addWidget(self.views, 1)
        self._set_view(self._view)

        self.lint_label = QLabel("")
        self.lint_label.setWordWrap(True)
        self.lint_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lint_label.setStyleSheet(f"color: {t['text_dim']}; ")
        v.addWidget(self.lint_label)

        # Until the integration exists, this page IS the setup: checklist down
        # the side, the next thing to do in the middle. The patterns table is
        # not a lesser version of that, so it hides entirely.
        self.setup_panel = SetupPanel()
        self.setup_panel.action_clicked.connect(self._on_setup_action)
        self.setup_panel.setVisible(False)
        v.addWidget(self.setup_panel)
        return wrap

    def _build_view_toggle(self):
        t = theme.colors()
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 8, 0)
        row.setSpacing(0)
        self.view_buttons = {}
        for key, label in (("cards", "Cards"), ("table", "Table")):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setChecked(key == self._view)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setObjectName(f"view{key.title()}")
            # Scoped: an unscoped sheet on the wrap kills :checked.
            button.setStyleSheet(
                f"QPushButton#view{key.title()} {{ padding: 4px 12px; "
                f"border: 1px solid {t['control_border']}; "
                f"background: transparent; color: {t['text_dim']}; }} "
                f"QPushButton#view{key.title()}:checked {{ "
                f"background-color: {t['button']}; color: {t['text_bright']}; }}")
            button.clicked.connect(lambda _c=False, k=key: self._set_view(k))
            row.addWidget(button)
            self.view_buttons[key] = button
        self.view_toggle = wrap
        return wrap

    def _set_view(self, key):
        self._view = key
        for name, button in self.view_buttons.items():
            button.setChecked(name == key)
        index = 0 if key == "cards" else 1
        self.views.setCurrentIndex(index)
        # A QStackedWidget takes every page's size hint, so the card stack
        # would reserve its height under the table. Only the shown page counts.
        for i in range(self.views.count()):
            page = self.views.widget(i)
            policy = (QSizePolicy.Policy.Preferred if i == index
                      else QSizePolicy.Policy.Ignored)
            page.setSizePolicy(policy, policy)
        self.views.widget(index).adjustSize()

    def _build_table(self):
        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels(
            ["Pattern", "Listens for", "Fires when", "Throttle", "Grace",
             "Issues"])
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self._on_table_menu)
        # "Fires when" and "Throttle" run long.
        components.style_table(table, stretch=(2, 3))
        table.setMinimumHeight(300)
        table.doubleClicked.connect(lambda _ix: self._on_edit())
        table.itemSelectionChanged.connect(self._on_table_selection)
        return table

    def _build_hidden_controls(self):
        """Controls the ⋯ menu drives; widgets rather than plain methods
        because the variant picker has state (which variant)."""
        self.variant_combo = QComboBox(self)
        self.variant_combo.setVisible(False)

    # ---- discovery ------------------------------------------------------

    def focus_patterns(self):
        """Deep link from Home's step 3: land on the page, not in a sub-view."""
        self._show_main()

    # ---- which screen ----------------------------------------------------

    def _show_main(self):
        self.test_view.stop()
        self.stack.setCurrentIndex(0)

    def _show_test(self):
        # The bridge is asked for here, not on the test screen: landing on a
        # screen that cannot do its job is not where to answer a yes/no.
        if not self._ensure_bridge():
            return
        self.test_view.set_patterns(self._deployed)
        self.test_view.set_model(self._deployed_model_name())
        self.test_view.refresh_state()
        self.stack.setCurrentIndex(1)
        # Only while the page is on screen; showEvent picks it up otherwise.
        if self.isVisible():
            self.test_view.start()

    def _show_captures(self):
        self.test_view.stop()
        self.captures_view.refresh_sessions()
        self.stack.setCurrentIndex(2)

    def _deployed_model_name(self):
        return (self._bundle or {}).get("local_match") or ""

    def refresh(self):
        if self.worker is not None and self.worker.isRunning():
            return
        self.conn_facts.setText("Looking for Talon…")
        self.worker = DiscoveryWorker()
        self.worker.loaded.connect(self._on_loaded)
        self.worker.start()

    def _on_loaded(self, bundle):
        self._raw_bundle = bundle
        self._apply_bundle()

    def _apply_bundle(self):
        bundle = integration_sim.apply_to_bundle(self._raw_bundle,
                                                 self._sim["bundle"])
        self._bundle = bundle
        t = theme.colors()
        result = bundle.get("result")
        error = bundle.get("error")

        ok, bad = t["ok"], t["bad"]
        if error or result is None:
            self.conn_facts.setText(
                f"<span style='color:{bad};'>Discovery failed: {error}</span>")
            return
        if result.talon_home:
            build = ("beta" if result.talon_beta else
                     "not beta" if result.talon_beta is False else
                     "build unknown")
            colour = bad if result.talon_beta is False else ok
            talon_txt = (f"<span style='color:{colour};'>Found ({build})</span>"
                         f" - {result.talon_home}")
            if result.talon_beta is False:
                talon_txt += (
                    f"<br><span style='color:{t['text_dim']};'>no parrot module "
                    f"under "
                    f"{talon_discovery.find_talon_python(result.talon_home)}"
                    f"</span>")
            self.status_rows["talon"].setText(talon_txt)
        else:
            self.status_rows["talon"].setText(
                f"<span style='color:{bad};'>Not found</span> - {result.error or ''}")
        self.status_rows["integration"].setText(result.integration_path or "-")
        self.status_rows["patterns"].setText(result.pattern_path_from_talon or "-")

        model_txt = result.model_path_from_talon or "-"
        match = bundle.get("local_match")
        sounds = bundle.get("model_sounds")
        if result.model_path_from_talon:
            if match:
                model_txt += (f"<br><span style='color:{ok};'>Matches local model "
                              f"'{match}'</span>")
            else:
                model_txt += (f"<br><span style='color:{bad};'>No identical local "
                              f"model - Talon may be running an old copy</span>")
            if sounds:
                model_txt += (f"<br><span style='color:{t['text_dim']};'>"
                              f"{len(sounds)} sounds: {', '.join(sounds)}</span>")
        self.status_rows["model"].setText(model_txt)

        self._refresh_companion_row()

        user_dir = result.talon_user_dir
        self._patterns_missing = bool(
            result.integration_path and result.intended_pattern_path
            and not os.path.isfile(result.intended_pattern_path))
        if not result.integration_path and user_dir:
            self.status_rows["integration"].setText(
                f"<span style='color:{bad};'>Not found</span>")
        elif self._patterns_missing:
            self.status_rows["patterns"].setText(
                f"<span style='color:{bad};'>Missing</span> - the integration "
                f"expects {result.intended_pattern_path}")
        self._deployed = _copy(result.patterns or {})
        self.working = _copy(result.patterns or {})
        self.test_view.set_patterns(self._deployed)
        self.test_view.set_model(self._deployed_model_name())
        self._refresh_variants()
        self._refresh_connection()
        self._refresh_from_working()

    def _refresh_connection(self):
        t = theme.colors()
        result = (self._bundle or {}).get("result")
        warn, bad = t["warn"], t["bad"]
        if result is None:
            return
        if not result.talon_home:
            self.conn_facts.setText(
                f"<span style='color:{warn};'>not found on this machine</span> "
                f"<span style='color:{t['text_dim']};'>- recording and training "
                f"work without it</span>")
            # This return skips the setEnabled calls at the end.
            self.change_model_btn.setEnabled(False)
            self.test_btn.setEnabled(False)
            return
        match = (self._bundle or {}).get("local_match")
        sounds = (self._bundle or {}).get("model_sounds") or []
        bits = []
        if result.talon_beta is False:
            bits.append(f"<span style='color:{bad};'>not using the beta, so no "
                        f"parrot support</span>")
        elif not result.integration_path:
            bits.append(f"<span style='color:{warn};'>installed, no parrot "
                        f"integration yet</span>")
        elif match:
            bits.append(f"running <b style='color:{t['text']};'>{match}</b>")
            if sounds:
                bits.append(f"{len(sounds)} sounds")
        elif result.model_path_from_talon:
            bits.append(f"<span style='color:{warn};'>running a model that is "
                        f"not in your library</span>")
        else:
            bits.append("no model deployed")
        if result.integration_path:
            count = len(self.working)
            bits.append(f"{count} pattern{'' if count == 1 else 's'}")
            # Surfaced here too, not only after clicking Test integration.
            info = self._companion_status()
            if info is not None and not info["installed"]:
                bits.append(f"<span style='color:{warn};'>test bridge not "
                            f"installed</span>")
        self.conn_facts.setText(
            f"<span style='color:{t['text_dim']};'>"
            + " · ".join(bits) + "</span>")
        self.change_model_btn.setEnabled(bool(result.model_path_from_talon))
        # The bridge wraps the parrot API, so there is nothing to watch without
        # the beta however complete the rest of the setup looks.
        can_test = bool(result.integration_path) and result.talon_beta is not False
        self.test_btn.setEnabled(can_test)
        if not can_test and result.talon_beta is False:
            self.test_btn.setToolTip("Needs the Talon beta")

    # ---- companion / live tab ---------------------------------------------

    def _talon_user_dir(self):
        result = self._bundle.get("result") if self._bundle else None
        return result.talon_user_dir if result else None

    def _companion_status(self):
        user_dir = self._talon_user_dir()
        real = talon_companion.status(user_dir) if user_dir else None
        return integration_sim.apply_to_bridge(real, self._sim["bridge"])

    def _parts(self):
        """What this integration is made of, and which pieces exist."""
        result = (self._bundle or {}).get("result")
        if result is None:
            return []
        info = self._companion_status()
        return [
            ("parrot_integration.py", bool(result.integration_path)),
            ("model", bool(result.model_path_from_talon)),
            ("patterns.json", bool(result.pattern_path_from_talon)),
            ("test bridge", bool(info and info["installed"])),
        ]

    def _refresh_companion_row(self):
        t = theme.colors()
        info = self._companion_status()
        if info is None:
            self.status_rows["companion"].setText("-")
            return
        if not info["installed"]:
            self.status_rows["companion"].setText(
                "Not installed - Test integration needs it")
        elif info["outdated"]:
            self.status_rows["companion"].setText(
                f"<span style='color:{t['warn']};'>v{info['installed_version']} installed, "
                f"v{info['available_version']} available</span> - {info['path']}")
        else:
            self.status_rows["companion"].setText(
                f"<span style='color:{t['accent']};'>Installed</span> "
                f"(v{info['installed_version']}) - {info['path']}")

    def _ensure_bridge(self):
        """True when testing can go ahead: the bridge is current, or the user
        just said yes to writing it."""
        info = self._companion_status()
        if info is None or (info["installed"] and not info["outdated"]):
            return True
        user_dir = self._talon_user_dir()
        if not user_dir or self._simulating():
            return False
        dialog = BridgeDialog(
            self, info["path"], legacy=talon_companion.legacy_path(user_dir),
            outdated=info["outdated"],
            versions=(info["installed_version"], info["available_version"]))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        try:
            talon_companion.install(
                user_dir,
                remove_legacy=bool(talon_companion.legacy_path(user_dir)))
        except OSError as exc:
            QMessageBox.warning(self, "Couldn't add the bridge", str(exc))
            return False
        self._refresh_companion_row()
        self._refresh_connection()
        return True

    def _on_install_companion(self):
        """From the ... menu, where it is maintenance rather than a step on
        the way to testing."""
        self._ensure_bridge()

    def _on_setup_integration(self):
        user_dir = self._talon_user_dir()
        if not user_dir or self._simulating():
            return
        models = self.app_state.get_model_names()
        if not models:
            QMessageBox.information(
                self, "No models yet",
                "Train a model first (Models tab) - the integration needs one.")
            return
        name, okd = QInputDialog.getItem(
            self, "Set up parrot integration",
            "Model to deploy with the integration:", models, 0, False)
        if not okd:
            return
        model_pkl = os.path.join(CLASSIFIER_FOLDER, f"{name}.pkl")
        # Always scaffolded. An empty patterns.json is an integration that
        # does nothing, which reads as a failed setup.
        sounds = talon_discovery.load_model_sounds(model_pkl) or []
        patterns = talon_setup.scaffold_patterns(sounds)
        dest = os.path.join(user_dir, talon_setup.DEFAULT_SUBFOLDER)
        if QMessageBox.question(
                self, "Set up parrot integration",
                f"Create {dest} with parrot_integration.py, {name}.pkl and "
                f"patterns.json ({len(patterns)} patterns)?\n\n"
                "Talon loads the integration immediately.") != \
                QMessageBox.StandardButton.Yes:
            return
        try:
            talon_setup.install_integration(user_dir, model_pkl, patterns=patterns)
        except (OSError, patterns_store.PatternsError) as exc:
            QMessageBox.warning(self, "Setup failed", str(exc))
            return
        self.refresh()

    def _on_create_patterns(self):
        """The scaffolder, as the answer to an empty screen rather than as a
        yes/no inside a yes/no. It writes the file Talon expects, filled."""
        result = self._bundle.get("result") if self._bundle else None
        if not result or not result.intended_pattern_path or self._simulating():
            return
        sounds = self._bundle.get("model_sounds") or []
        patterns = talon_setup.scaffold_patterns(sounds)
        try:
            talon_setup.create_patterns_file(result.intended_pattern_path, patterns)
        except (OSError, patterns_store.PatternsError) as exc:
            QMessageBox.warning(self, "Couldn't create patterns.json", str(exc))
            return
        self.refresh()

    def _on_scaffold_into_draft(self):
        """Same starter set, but into the draft when patterns.json exists and
        is empty - so it is reviewed before Talon ever sees it."""
        sounds = (self._bundle or {}).get("model_sounds") or []
        self.working = talon_setup.scaffold_patterns(sounds)
        self._refresh_from_working()

    def hideEvent(self, event):
        self.test_view.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        if self.stack.currentIndex() == 1:
            self.test_view.start()
        super().showEvent(event)

    # ---- working-copy lifecycle ------------------------------------------

    def _validate_working(self):
        if not self._bundle:
            return []
        return patterns_schema.validate(
            self.working, self._bundle.get("schema"),
            model_sounds=self._bundle.get("model_sounds"))

    def _refresh_from_working(self):
        t = theme.colors()
        ok, bad, warn = t["ok"], t["bad"], t["warn"]
        issues = self._validate_working()
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]

        # Card view has no last row number to read the count off.
        self.patterns_title.setText(
            f"Patterns <span style='color:{t['text_dim']}; "
            f"font-weight: normal;'>({len(self.working)})</span>")

        if not self.working:
            self.health_label.setText("")
        elif not issues:
            self.health_label.setText(
                f"<span style='color:{ok};'>· no issues</span>")
        else:
            parts = []
            if errors:
                parts.append(f"<span style='color:{bad};'>{len(errors)} errors</span>")
            if warnings:
                parts.append(f"<span style='color:{warn};'>{len(warnings)} warnings</span>")
            self.health_label.setText("· " + ", ".join(parts))

        editable = self._patterns_path is not None
        self.new_btn.setEnabled(editable)
        self._refresh_draft_banner(issues)
        # Filling rows moves the current cell and raises the same signal the
        # user does, overwriting the selection restored below.
        self.table.blockSignals(True)
        self._populate_table(self.working, issues)
        self.table.blockSignals(False)
        self._populate_cards(self.working, issues)
        if self._selected not in self.working:
            self._selected = None
        self._select(self._selected)
        self._refresh_empty_state()
        self._refresh_connection()

    def _refresh_draft_banner(self, issues):
        """Counts the changes rather than saying "unsaved": three edits and a
        new pattern is a different thing to notice than a typo."""
        if not self.dirty:
            self.draft_banner.setVisible(False)
            return
        diff = patterns_store.diff_patterns(self._deployed, self.working)
        changes = (len(diff["added"]) + len(diff["removed"])
                   + len(diff["changed"]))
        noun = "change" if changes == 1 else "changes"
        self.draft_label.setText(
            f"<b>Draft</b> - {changes} {noun}. Talon is still running the "
            f"deployed set.")
        blocked = patterns_schema.has_errors(issues)
        self.deploy_btn.setEnabled(self._patterns_path is not None and not blocked)
        self.deploy_btn.setToolTip(
            "Fix the errors first - the integration crashes on them" if blocked
            else "Write the draft to Talon's patterns.json")
        self.draft_banner.setVisible(True)

    def _talon_step(self, result):
        """Talon, and specifically the beta. Stable Talon only says so with an
        ImportError in its own log, which nobody clicking Set up will read."""
        beta = result.talon_beta if result else None
        if result and result.talon_home and beta is not False:
            return {"key": "talon",
                    # Only claim the beta where the module was actually found.
                    "label": "Talon beta" if beta else "Talon installed",
                    "done": True, "title": "", "body": "", "action": None}
        if result and result.talon_home:
            # Red where the other unfinished steps are not: this one is a
            # wrong install rather than a step you have not reached, and every
            # tick under it is worth nothing until it changes.
            return {"key": "talon", "label": "Talon beta", "done": False,
                    "blocked": True,
                    "title": "Not using Talon beta",
                    "body": "Parrot support is beta only, and this install has "
                            "no <code>talon.experimental.parrot</code> for the "
                            "integration to import. The beta comes with a "
                            "Patreon tier and the #beta channel on Slack."
                            f"<br><br>{_beta_links()}",
                    "action": None,
                    # How it decided, so a wrong verdict is not a mystery.
                    "note": "Checked Talon's own Python for the parrot module."}
        return {"key": "talon", "label": "Talon beta", "done": False,
                "title": "Talon beta is not installed here",
                "body": "Recording and training work without it. Parrot support "
                        "is beta only: a Patreon tier, then the #beta channel "
                        f"on Slack.<br><br>{_beta_links()}",
                "action": None}

    def _setup_steps(self):
        """The integration, as the four files it is made of plus the patterns
        that make it do anything. Every row is a fact on disk, so the checklist
        cannot claim a step is done when the file is not there."""
        result = (self._bundle or {}).get("result")
        sounds = (self._bundle or {}).get("model_sounds") or []
        starters = len(talon_setup.scaffold_patterns(sounds))
        model = self._deployed_model_name()

        beta = result.talon_beta if result else None
        return [
            self._talon_step(result),
            {"key": "integration", "label": "Parrot integration",
             "done": bool(result and result.integration_path),
             "title": "Nothing connects Talon to parrot.py yet",
             "body": "The integration is a folder in your Talon user "
                     "directory holding three things: the integration file, "
                     "one of your trained models, and a patterns.json. This "
                     "makes all three.",
             "action": "Set up parrot integration…",
             "detail": self._integration_tree_html(),
             "note": None if beta else
                     f"Needs the Talon beta. {_beta_links()}"},
            {"key": "model", "label": "Model deployed",
             "done": bool(result and result.model_path_from_talon),
             "title": "The integration has no model to run",
             "body": "Talon needs one of your trained models in that folder "
                     "before it can hear anything.",
             "action": "Change model…"},
            {"key": "patterns_file", "label": "patterns.json",
             "done": bool(result and result.integration_path
                          and not self._patterns_missing),
             "title": "No patterns.json yet",
             "body": "The integration expects one and it is not there. Start "
                     "from one pattern per sound the model knows, at safe "
                     "thresholds you tune down later.",
             "action": f"Create {starters} starter patterns"},
            {"key": "patterns", "label": "At least one pattern",
             "done": bool(self.working),
             "title": f"Talon can hear {model or 'your model'}, but nothing "
                      f"is mapped to it",
             "body": "A pattern is a sound plus the rules that decide when it "
                     "counts. Start from one per sound the model knows, at "
                     "safe thresholds you tune down later.",
             "action": f"Create {starters} starter patterns",
             "note": "Written as a draft. Nothing reaches Talon until you "
                     "deploy."},
        ]

    def _integration_tree_html(self):
        result = (self._bundle or {}).get("result")
        user_dir = result.talon_user_dir if result else None
        if not user_dir:
            return ""
        folder = os.path.join(user_dir, talon_setup.DEFAULT_SUBFOLDER)
        t = theme.colors()
        rows = [f"<span style='color:{t['text_dim']};'>{user_dir}{os.sep}</span>",
                f"<span style='color:{t['accent']};'>+ "
                f"{talon_setup.DEFAULT_SUBFOLDER}{os.sep}</span>"
                f"&nbsp;&nbsp;<span style='color:{t['text_dim']};'>"
                f"new folder</span>"]
        for name in ("parrot_integration.py", "model.pkl", "patterns.json"):
            rows.append(f"&nbsp;&nbsp;&nbsp;&nbsp;"
                        f"<span style='color:{t['accent']};'>+ {name}</span>")
        return (f"<div style='font-family: Consolas, monospace; "
                f"'>" + "<br>".join(rows) + "</div>")

    def _on_setup_action(self, key):
        {"integration": self._on_setup_integration,
         "model": self._on_change_model,
         "patterns_file": self._on_create_patterns,
         "patterns": self._on_scaffold_into_draft}.get(key, lambda: None)()

    def _refresh_empty_state(self):
        """Setting the integration up and editing its patterns are two jobs,
        not one screen with holes in it."""
        steps = self._setup_steps()
        setting_up = any(not step["done"] for step in steps)
        self.setup_panel.setVisible(setting_up)
        self.views.setVisible(not setting_up)
        self.lint_label.setVisible(not setting_up)
        self.new_btn.setVisible(not setting_up)
        self.view_toggle.setVisible(not setting_up)
        self.hint_label.setVisible(not setting_up)
        self.health_label.setVisible(not setting_up)
        self.patterns_title.setVisible(not setting_up)
        if setting_up:
            self.setup_panel.set_steps(steps)

    def _refresh_variants(self):
        current = self.variant_combo.currentText()
        self.variant_combo.clear()
        self.variant_combo.addItems(patterns_store.list_variants())
        idx = self.variant_combo.findText(current)
        if idx >= 0:
            self.variant_combo.setCurrentIndex(idx)

    def _selected_name(self):
        return self._selected if self._selected in self.working else None

    def _on_table_selection(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        if item is not None:
            self._select(item.data(Qt.ItemDataRole.UserRole))

    def _select(self, name):
        """One selection, shown in whichever view is up."""
        self._selected = name
        for card in self.card_grid.cards():
            card.set_selected(card.name == name)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == name:
                if self.table.currentRow() != row:
                    self.table.selectRow(row)
                break

    # ---- the ⋯ menu -------------------------------------------------------

    def _build_more_menu(self):
        """Ordered by how often it is wanted, destructive-adjacent ones last."""
        menu = self._more_menu
        menu.clear()
        result = (self._bundle or {}).get("result")
        editable = self._patterns_path is not None

        variants = patterns_store.list_variants()
        if variants:
            load = menu.addMenu("Load variant")
            for name in variants:
                load.addAction(name,
                               lambda _c=False, n=name: self._load_variant(n))
        action = menu.addAction("Save as variant…", self._on_save_variant)
        action.setEnabled(editable)
        action = menu.addAction("Snapshots…", self._on_snapshots)
        action.setEnabled(editable)
        action = menu.addAction("Edit patterns.json directly…", self._on_raw_json)
        action.setEnabled(editable)
        menu.addSeparator()

        if result is not None and result.talon_user_dir:
            info = self._companion_status()
            if info is not None:
                label = ("Install the test bridge" if not info["installed"]
                         else "Update the test bridge" if info["outdated"]
                         else "Reinstall the test bridge")
                menu.addAction(label, self._on_install_companion)
        if result is not None and not result.integration_path \
                and result.talon_user_dir:
            menu.addAction("Set up parrot integration…",
                           self._on_setup_integration)
        if self._patterns_missing:
            menu.addAction("Create patterns.json", self._on_create_patterns)
        menu.addSeparator()
        show = menu.addAction("Show file paths")
        show.setCheckable(True)
        show.setChecked(self.details_group.isVisible())
        show.toggled.connect(self.details_group.setVisible)
        action = menu.addAction("Open Talon folder", self._open_talon_folder)
        action.setEnabled(bool(result and result.pattern_path_from_talon))
        menu.addAction("Refresh", self.refresh)
        if integration_sim.enabled():
            self._add_sim_menu(menu)

    def _add_sim_menu(self, menu):
        """PARROT_DEBUG=1 only. Every state this page has is on a machine that
        does not have the setup working, which is not the machine it gets
        written on."""
        menu.addSeparator()
        sim = menu.addMenu("Simulate")
        for key, states, label in (
                ("bundle", integration_sim.STATES, "Setup"),
                ("bridge", integration_sim.BRIDGE_STATES, "Bridge")):
            group = sim.addMenu(label)
            for name, text in states:
                action = group.addAction(text)
                action.setCheckable(True)
                action.setChecked(self._sim[key] == name)
                action.triggered.connect(
                    lambda _c=False, k=key, n=name: self._set_sim(k, n))
        talon = sim.addMenu("Talon")
        for name, text in integration_sim.TALON_STATES:
            talon.addAction(
                text, lambda n=name: self.test_view.simulate_talon(n))
        sim.addAction("Feed a detection into the test screen",
                      lambda: self.test_view.simulate_frames())

    def _set_sim(self, key, name):
        self._sim[key] = name
        self._apply_bundle()
        self._refresh_sim_chip()

    def _simulating(self):
        """True while any state on this page is faked. Every action that
        writes to disk checks it: a simulated path is a real path with a
        pretend fact attached, and creating files at one is how a dev tool
        breaks a working Talon setup."""
        if not any(v != "off" for v in self._sim.values()):
            return False
        QMessageBox.information(
            self, "Simulated state",
            "This page is showing a simulated state, so nothing is written.\n\n"
            "Turn the simulation off in ⋯ > Simulate to use this for real.")
        return True

    def _refresh_sim_chip(self):
        on = [v for v in self._sim.values() if v != "off"]
        self.sim_chip.setVisible(bool(on))
        self.sim_chip.setText("simulated: " + ", ".join(on))

    def _load_variant(self, name):
        idx = self.variant_combo.findText(name)
        if idx >= 0:
            self.variant_combo.setCurrentIndex(idx)
        self._on_load_variant()

    def _on_table_menu(self, pos):
        item = self.table.itemAt(pos)
        if item is None:
            return
        self.table.selectRow(item.row())
        self._pattern_menu(self.table.viewport().mapToGlobal(pos))

    def _pattern_menu(self, global_pos):
        """Same three actions from a row or a card.

        Selection has already moved to the pattern under the cursor, so the
        menu and the thing behind it match.
        """
        menu = QMenu(self)
        menu.addAction("Edit…", self._on_edit)
        menu.addAction("Duplicate", self._on_duplicate)
        menu.addSeparator()
        menu.addAction("Delete pattern", self._on_delete)
        menu.exec(global_pos)

    def _on_discard_draft(self):
        if QMessageBox.question(
                self, "Discard draft",
                "Throw away the changes and go back to what Talon is running?") \
                != QMessageBox.StandardButton.Yes:
            return
        self.working = _copy(self._deployed)
        self._refresh_from_working()

    def _on_change_model(self):
        """Swap the model Talon runs, without rebuilding the integration.

        The picker is the decision - no confirm behind it - except a deployed
        model with no library copy exists only at that path, so overwriting
        that one asks.
        """
        result = (self._bundle or {}).get("result")
        if result is None or not result.model_path_from_talon or self._simulating():
            return
        if not self.app_state.get_model_names():
            QMessageBox.information(self, "No models", "Train a model first.")
            return
        current = self._deployed_model_name()
        dialog = ChangeModelDialog(self, self.app_state, current,
                                   result.model_path_from_talon, self.working)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.chosen:
            return
        name = dialog.chosen
        if not current and QMessageBox.question(
                self, "Change model",
                f"The model Talon is running now is not in your library, so "
                f"replacing it is the end of that copy.\n\n"
                f"Overwrite {result.model_path_from_talon} with '{name}'?"
                ) != QMessageBox.StandardButton.Yes:
            return
        source = os.path.join(CLASSIFIER_FOLDER, f"{name}.pkl")
        try:
            talon_setup.deploy_model(source, result.model_path_from_talon,
                                     result.integration_path)
        except OSError as exc:
            QMessageBox.warning(self, "Couldn't change the model", str(exc))
            return
        self.refresh()

    # ---- pattern editing --------------------------------------------------

    def _edit_dialog(self, name, pattern):
        observed = self._session_stats().get(name) if name else None
        return PatternEditDialog(
            self, name, pattern, self.working,
            self._bundle.get("model_sounds") if self._bundle else [],
            self._bundle.get("schema") if self._bundle else None,
            observed=observed)

    def _session_stats(self):
        """Observed per-pattern stats from the newest recorded session,
        cached by (path, mtime). Empty dict when there are no sessions."""
        from gui.services import session_stats
        from config.config import DATA_DIR
        captures_dir = os.path.join(DATA_DIR, "talon", "captures")
        newest = None
        if os.path.isdir(captures_dir):
            sessions = [os.path.join(captures_dir, n)
                        for n in os.listdir(captures_dir) if n.endswith(".jsonl")]
            if sessions:
                newest = max(sessions, key=os.path.getmtime)
        if newest is None:
            self._stats_cache = None
            return {}
        key = (newest, os.path.getmtime(newest))
        cached = getattr(self, "_stats_cache", None)
        if cached and cached[0] == key:
            return cached[1]
        frames = []
        try:
            with open(newest, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            frames.append(json.loads(line))
                        except ValueError:
                            continue
        except OSError:
            return {}
        stats = session_stats.analyze(frames, self._deployed)
        self._stats_cache = (key, stats)
        return stats

    def _on_new(self):
        dialog = self._edit_dialog(None, None)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.working[dialog.result_name] = dialog.result_pattern
            self._refresh_from_working()

    def _on_edit(self):
        name = self._selected_name()
        if not name or name not in self.working:
            return
        dialog = self._edit_dialog(name, self.working[name])
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        new_name = dialog.result_name
        if new_name != name:
            # keep position + update every throttle that pointed at the old name
            self.working = {
                (new_name if key == name else key): value
                for key, value in self.working.items()}
            for pattern in self.working.values():
                throttle = pattern.get("throttle")
                if isinstance(throttle, dict) and name in throttle:
                    throttle[new_name] = throttle.pop(name)
        self.working[new_name] = dialog.result_pattern
        self._refresh_from_working()

    def _on_duplicate(self):
        name = self._selected_name()
        if not name or name not in self.working:
            return
        copy_name = f"{name} copy"
        counter = 2
        while copy_name in self.working:
            copy_name = f"{name} copy {counter}"
            counter += 1
        self.working[copy_name] = _copy(self.working[name])
        self._refresh_from_working()

    def _on_delete(self):
        name = self._selected_name()
        if not name or name not in self.working:
            return
        referrers = [p for p, pat in self.working.items()
                     if isinstance(pat.get("throttle"), dict) and name in pat["throttle"]]
        message = f"Delete pattern '{name}' from the working copy?"
        if referrers:
            message += ("\n\nThrottle references in "
                        f"{', '.join(referrers)} will also be removed.")
        if QMessageBox.question(self, "Delete pattern", message) != \
                QMessageBox.StandardButton.Yes:
            return
        del self.working[name]
        for pattern in self.working.values():
            throttle = pattern.get("throttle")
            if isinstance(throttle, dict):
                throttle.pop(name, None)
        self._refresh_from_working()

    def _on_raw_json(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("patterns.json - raw")
        dialog.setMinimumSize(640, 560)
        layout = QVBoxLayout(dialog)
        editor = QPlainTextEdit()
        editor.setStyleSheet("font-family: Consolas, monospace; ")
        editor.setPlainText(patterns_store.dumps_patterns(self.working))
        layout.addWidget(editor, 1)
        note = QLabel("")
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(dialog.reject)
        row.addWidget(cancel)
        apply_btn = QPushButton("Apply")
        row.addWidget(apply_btn)
        layout.addLayout(row)

        def on_apply():
            try:
                data = json.loads(editor.toPlainText())
            except json.JSONDecodeError as exc:
                note.setText(f"Not valid JSON: {exc}")
                return
            if not isinstance(data, dict):
                note.setText("patterns.json must be a JSON object")
                return
            issues = patterns_schema.validate(
                data, self._bundle.get("schema") if self._bundle else None,
                model_sounds=self._bundle.get("model_sounds") if self._bundle else None)
            if patterns_schema.has_errors(issues):
                errors = [str(i) for i in issues if i.severity == "error"]
                note.setText("\n".join(errors[:6]))
                return
            self.working = data
            dialog.accept()

        apply_btn.clicked.connect(on_apply)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._refresh_from_working()

    # ---- variants / deploy / snapshots -------------------------------------

    def _on_save_variant(self):
        name, okd = QInputDialog.getText(
            self, "Save as variant",
            "Variant name (stored in data/talon/variants):",
            text=self.variant_combo.currentText() or "experiment")
        if not okd or not name.strip():
            return
        try:
            patterns_store.save_variant(name.strip(), self.working)
        except patterns_store.PatternsError as exc:
            QMessageBox.warning(self, "Couldn't save variant", str(exc))
            return
        self._refresh_variants()
        idx = self.variant_combo.findText(name.strip())
        if idx >= 0:
            self.variant_combo.setCurrentIndex(idx)

    def _on_load_variant(self):
        name = self.variant_combo.currentText()
        if not name:
            return
        if self.dirty and QMessageBox.question(
                self, "Discard changes?",
                "The working copy has unsaved changes. Load the variant anyway?") \
                != QMessageBox.StandardButton.Yes:
            return
        try:
            self.working = patterns_store.load_variant(name)
        except patterns_store.PatternsError as exc:
            QMessageBox.warning(self, "Couldn't load variant", str(exc))
            return
        self._refresh_from_working()

    def _on_deploy(self):
        path = self._patterns_path
        if not path or self._simulating():
            return
        diff = patterns_store.diff_patterns(self._deployed, self.working)
        lines = []
        for n in diff["added"]:
            lines.append(f"+ {n}")
        for n in diff["removed"]:
            lines.append(f"− {n}")
        for n, fields in diff["changed"].items():
            lines.append(f"~ {n}: {', '.join(f[0] for f in fields)}")
        summary = "\n".join(lines) or "(no changes)"
        if QMessageBox.question(
                self, "Deploy to Talon",
                f"Write these changes to\n{path}?\n\n{summary}\n\n"
                "The current file is snapshotted first, and Talon reloads "
                "patterns.json automatically.") != QMessageBox.StandardButton.Yes:
            return
        try:
            snap = patterns_store.deploy(self.working, path)
        except patterns_store.PatternsError as exc:
            QMessageBox.warning(self, "Deploy failed", str(exc))
            return
        self._deployed = _copy(self.working)
        self.test_view.set_patterns(self._deployed)
        self._refresh_from_working()
        QMessageBox.information(
            self, "Deployed",
            f"patterns.json updated - Talon picks it up automatically.\n"
            f"Previous version snapshotted to:\n{snap}")

    def _on_snapshots(self):
        snaps = patterns_store.list_snapshots()
        if not snaps:
            QMessageBox.information(self, "Snapshots",
                                    "No snapshots yet - one is taken on every deploy.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Snapshots")
        dialog.setMinimumSize(520, 420)
        layout = QVBoxLayout(dialog)
        listing = QListWidget()
        for path, _mtime in snaps:
            QListWidgetItem(os.path.basename(path), listing)
        layout.addWidget(listing, 1)
        row = QHBoxLayout()
        row.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(dialog.reject)
        row.addWidget(close)
        restore = QPushButton("Load into working copy")
        row.addWidget(restore)
        layout.addLayout(row)

        def on_restore():
            idx = listing.currentRow()
            if idx < 0:
                return
            try:
                self.working = patterns_store.load_patterns(snaps[idx][0])
            except patterns_store.PatternsError as exc:
                QMessageBox.warning(dialog, "Couldn't load snapshot", str(exc))
                return
            dialog.accept()

        restore.clicked.connect(on_restore)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._refresh_from_working()

    def _populate_table(self, patterns, issues):
        """Pattern, what it listens for, what it takes to fire. The colour
        square is the same one the test view uses, so a row and a bar are
        recognisably the same pattern.

        Deployed values, and the draft's on top of them: a changed number reads
        `0.99 → 0.94` in the row itself rather than only in the deploy dialog.
        """
        t = theme.colors()
        by_pattern = {}
        for issue in issues:
            by_pattern.setdefault(issue.pattern, []).append(issue)
        colors = pattern_colors.colors_for(patterns)
        model_sounds = (self._bundle or {}).get("model_sounds") or []

        self.table.setRowCount(len(patterns))
        for row, (name, pattern) in enumerate(patterns.items()):
            pattern = pattern if isinstance(pattern, dict) else {}
            was = self._deployed.get(name)
            was = was if isinstance(was, dict) else {}
            sounds = pattern.get("sounds")
            throttle = pattern.get("throttle") or {}
            grace_bits = []
            if pattern.get("graceperiod") is not None:
                grace_bits.append(f"{pattern['graceperiod']}s")
            if pattern.get("grace_threshold"):
                grace_bits.append(_fmt_threshold(pattern["grace_threshold"]))
            fires = _fmt_threshold(pattern.get("threshold"),
                                   was.get("threshold") if was else None)
            if pattern.get("detect_after"):
                fires += f"   after {pattern['detect_after']}s"
            # Spelled out, not counted: a count reads the same for a 0.12s
            # throttle on itself and six patterns muted at 0.2s. Own name
            # first, `none` when missing - the detector fills it with 0.
            throttles = ([(name, throttle.get(name, "none"))] if throttle else
                         []) + [(target, seconds)
                                for target, seconds in throttle.items()
                                if target != name]
            cells = [
                f"■  {name}" if name in self._deployed else f"■  {name}   new",
                ", ".join(sounds) if isinstance(sounds, list) else "",
                fires,
                # Throttle before grace: grace is the column that sits empty.
                "  ".join(f"{target} {seconds}" for target, seconds in throttles),
                "  ".join(grace_bits),
            ]
            for col, textval in enumerate(cells):
                item = QTableWidgetItem(textval)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, name)
                    item.setForeground(QColor(colors.get(name, "#ffffff")))
                    if name not in self._deployed:
                        item.setToolTip("not deployed yet")
                if col == 1 and isinstance(sounds, list):
                    unknown = [s for s in sounds if model_sounds
                               and s not in model_sounds]
                    if unknown:
                        item.setForeground(QColor(t["bad"]))
                        item.setToolTip(
                            f"the deployed model does not know "
                            f"{', '.join(unknown)}")
                if col in (2, 3, 4):
                    item.setForeground(QColor(t["text_dim"]))
                if col == 3 and throttles:
                    # The column stretches, a seven-entry list still outruns it.
                    tip = "\n".join(f"{target}: {seconds}"
                                    for target, seconds in throttles)
                    if name not in throttle:
                        tip += (f"\n\nno throttle on itself, so '{name}' fires "
                                f"on every frame that passes its threshold")
                    item.setToolTip(tip)
                self.table.setItem(row, col, item)

            pattern_issues = by_pattern.get(name, [])
            n_err = sum(1 for i in pattern_issues if i.severity == "error")
            n_warn = len(pattern_issues) - n_err
            badge = []
            if n_err:
                badge.append(f"{n_err} ✕")
            if n_warn:
                badge.append(f"{n_warn} ⚠")
            issue_item = QTableWidgetItem("  ".join(badge))
            if pattern_issues:
                issue_item.setToolTip("\n".join(str(i) for i in pattern_issues))
                issue_item.setForeground(
                    QColor(t["bad"]) if n_err else QColor(t["warn"]))
            self.table.setItem(row, 5, issue_item)

        file_level = by_pattern.get("", [])
        listed = file_level + [i for i in issues if i.severity == "error" and i.pattern]
        self.lint_label.setText("\n".join(str(i) for i in listed[:10]))

    def _populate_cards(self, patterns, issues):
        """Rebuilt whole, not diffed: cheaper than tracking what a rename hit."""
        by_pattern = {}
        for issue in issues:
            by_pattern.setdefault(issue.pattern, []).append(issue)
        colors = pattern_colors.colors_for(patterns)
        model_sounds = (self._bundle or {}).get("model_sounds") or []

        cards = []
        for name, pattern in patterns.items():
            card = PatternCard(
                name, pattern, colors,
                deployed=self._deployed.get(name),
                issues=by_pattern.get(name, []),
                model_sounds=model_sounds,
                is_new=name not in self._deployed)
            card.clicked.connect(self._select)
            card.activated.connect(lambda _n: self._on_edit())
            card.menu_requested.connect(
                lambda _n, pos: self._pattern_menu(pos))
            cards.append(card)
        self.card_grid.set_cards(cards)

    # ---- actions ---------------------------------------------------------

    def _open_talon_folder(self):
        result = self._bundle.get("result") if self._bundle else None
        if result and result.pattern_path_from_talon:
            try:
                library_ops.open_in_file_manager(
                    os.path.dirname(result.pattern_path_from_talon))
            except library_ops.LibraryOpError:
                pass

    def keybinding_hint(self):
        return ""

    def refresh_theme(self):
        pass
