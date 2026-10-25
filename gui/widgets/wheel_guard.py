"""The scroll wheel never edits a value. It scrolls.

Combos, spin boxes and sliders all take the wheel, so scrolling a form past one
silently changes a setting. Focus is no exception: a control you just clicked is
the one you scroll over next.

Blocking alone would make each control a dead patch, so the gesture is forwarded
to the enclosing scroll area. An open combo popup still scrolls; it is a
QListView.
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
