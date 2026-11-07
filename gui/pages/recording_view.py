from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from gui import components


class RecordingView(QWidget):
    """Where a sound's recordings will be made. A placeholder until recording
    lands: the way in from Sounds and the way back out.

    ┌ header ──────────────────────────────────────────────────────────────┐
    │ back_btn  title                                                      │
    ├──────────────────────────────────────────────────────────────────────┤
    │                         placeholder                                  │
    └──────────────────────────────────────────────────────────────────────┘
    """

    done = pyqtSignal()

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        back_btn = QPushButton("← Back to Sounds")
        back_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        back_btn.clicked.connect(self.done.emit)
        header.addWidget(back_btn)
        self.title = QLabel("")
        self.title.setStyleSheet(components.heading_style("title"))
        header.addWidget(self.title)
        header.addStretch()
        root.addLayout(header)

        placeholder = QVBoxLayout()
        placeholder.addStretch()
        components.center_in(placeholder, components.EmptyState(
            "Recording isn't in the app yet",
            "For now, record from the terminal: run settings.py and pick [R]."))
        root.addLayout(placeholder, 1)

    def start_for(self, label):
        self.title.setText(f"Record:  {label}")
