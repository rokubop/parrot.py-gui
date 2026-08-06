"""The scroll wheel never edits a value. It scrolls.

A combo, a spin box and a slider all take the wheel, so scrolling a form past
one silently changes a setting - and the ones that bite are the ones you just
clicked, because focus was the only thing the old guard checked.

This application-level filter runs before the event reaches the widget and
drops it for those three types, focused or not. Then it hands the gesture to
the nearest enclosing scroll area, so a control is not a dead patch in a page
that otherwise scrolls.

An open combo popup still scrolls: the popup is a QListView, not a QComboBox.
"""
from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import (QAbstractScrollArea, QAbstractSpinBox,
                             QApplication, QComboBox, QSlider)

# QSlider, not QAbstractSlider: a scrollbar is a QAbstractSlider too, and a
# scrollbar is the one thing the wheel is actually for.
GUARDED = (QComboBox, QAbstractSpinBox, QSlider)


def _enclosing_scroller(widget):
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QAbstractScrollArea):
            return parent
        parent = parent.parentWidget()
    return None


class _WheelGuard(QObject):

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel and isinstance(obj, GUARDED):
            area = _enclosing_scroller(obj)
            if area is not None:
                QApplication.sendEvent(area.viewport(), event)
            return True
        return super().eventFilter(obj, event)


def install(app):
    guard = _WheelGuard(app)   # parented to the app so it outlives this frame
    app.installEventFilter(guard)
    return guard
