"""Space presses the focused button, even on a page that binds Space.

The recording and edit views bind Space window-wide to play, and a window
shortcut beats a focused button. Tab would land on Finish, show the ring, and
Space would play instead. Accepting the ShortcutOverride hands the key back to
the button. A click never focuses a button (TabFocus), so mouse use is unchanged.
"""
from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import QAbstractButton


class _SpaceGuard(QObject):

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.Type.ShortcutOverride
                and event.key() == Qt.Key.Key_Space
                and not event.modifiers()
                and isinstance(obj, QAbstractButton)):
            event.accept()
            return True
        return super().eventFilter(obj, event)


def install(app):
    guard = _SpaceGuard(app)   # parented to the app so it outlives this frame
    app.installEventFilter(guard)
    return guard
