"""Scroll-wheel over an unfocused combo or spin box scrolls the page, not the value.

Both widget types accept wheel events without focus, so scrolling a form past
one silently edits it. This application-level filter runs before the event is
delivered (and before wheel-focus is granted), drops it unless the widget was
clicked into first, and leaves it ignored - an ignored wheel propagates to the
enclosing scroll area, which is what the gesture meant.
"""
from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QAbstractSpinBox, QComboBox


class _WheelGuard(QObject):

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.Type.Wheel
                and isinstance(obj, (QComboBox, QAbstractSpinBox))
                and not obj.hasFocus()):
            event.ignore()
            return True
        return super().eventFilter(obj, event)


def install(app):
    guard = _WheelGuard(app)   # parented to the app so it outlives this frame
    app.installEventFilter(guard)
    return guard
