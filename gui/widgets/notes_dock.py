"""Global notes drawer. Pops in/out of any page via the toolbar Notes button."""
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDockWidget, QTextEdit


class NotesDock(QDockWidget):
    def __init__(self, app_state, parent=None):
        super().__init__("Notes", parent)
        self.app_state = app_state
        self.setObjectName("notesDock")

        self.edit = QTextEdit()
        self.edit.setPlaceholderText(
            "Persistent notes to plan or track status. Saved automatically.")
        self.edit.setMinimumWidth(280)
        self.edit.setPlainText(app_state.load_notes().get("global_notes", ""))
        self.edit.textChanged.connect(self._queue_save)
        self.setWidget(self.edit)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)
        self._save_timer.timeout.connect(self._save)

    def _queue_save(self):
        self._save_timer.start()

    def _save(self):
        # re-read first: don't clobber model notes edited elsewhere
        notes = self.app_state.load_notes()
        notes["global_notes"] = self.edit.toPlainText()
        self.app_state.save_notes(notes)
