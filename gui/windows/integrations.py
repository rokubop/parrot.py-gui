"""Integrations: where a trained model is, and how to take it somewhere else.

Information only. This tab reads and writes nothing outside the app's own
data folder - it names the model file and opens the folder holding it. What
consumes the model is the other program's business, not this one's.
"""
import os

from PyQt6.QtWidgets import (
    QFrame, QScrollArea, QVBoxLayout, QWidget,
)

from config.config import CLASSIFIER_FOLDER
from gui import components, content, theme
from gui.services import library_ops
from gui.widgets import help_dialog


class IntegrationsPage(QWidget):
    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self._setup_ui()
        self.app_state.models_changed.connect(self._refresh)

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        layout.addWidget(components.heading("Your model file", "title"))

        self.model_label = components.dim_label("", wrap=True)
        layout.addWidget(self.model_label)

        self.path_label = components.dim_label("", wrap=True)
        layout.addWidget(self.path_label)

        self.open_btn = components.primary_button(
            "Open models folder", self._on_open_folder)
        components.lock_width(self.open_btn, "Open models folder")
        layout.addWidget(self.open_btn, 0)

        layout.addSpacing(12)
        layout.addWidget(help_dialog.topic_content(content.get("model_file"),
                                                   stretch=False))
        layout.addStretch()
        scroll.setWidget(body)
        self._refresh()

    def _refresh(self):
        names = self.app_state.get_model_names()
        active = self.app_state.get_active_model_name()
        if not names:
            self.model_label.setText(
                "No models yet. Train one on the Models tab.")
        elif active:
            self.model_label.setText(f"Latest model: {active}.pkl")
        else:
            self.model_label.setText(f"{len(names)} models.")
        self.path_label.setText(os.path.abspath(CLASSIFIER_FOLDER))

    def _on_open_folder(self):
        library_ops.open_in_file_manager(CLASSIFIER_FOLDER)

    def refresh_theme(self):
        components.refresh_primary(self.open_btn)
