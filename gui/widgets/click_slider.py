"""A horizontal slider with modern click-to-position behaviour.

Default QSliders only step a page at a time when you click the groove, and the
clickable target is the thin handle. ClickSlider instead jumps the handle to
wherever you press (anywhere along its length, at any height) and tracks the
cursor while dragging - what you'd expect from a modern slider.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QSlider, QStyle, QStyleOptionSlider


class ClickSlider(QSlider):
    def _value_at(self, pos):
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt,
            QStyle.SubControl.SC_SliderGroove, self)
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt,
            QStyle.SubControl.SC_SliderHandle, self)
        if self.orientation() == Qt.Orientation.Horizontal:
            span = groove.width() - handle.width()
            x = int(pos.x()) - groove.x() - handle.width() // 2
            return QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(), x, span, opt.upsideDown)
        span = groove.height() - handle.height()
        y = int(pos.y()) - groove.y() - handle.height() // 2
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), y, span, opt.upsideDown)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setSliderDown(True)
            self.setValue(self._value_at(event.position()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.setValue(self._value_at(event.position()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setSliderDown(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)
