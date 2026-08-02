import pyqtgraph as pg
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from gui import theme


class TrainingPlotWidget(QWidget):
    """Loss and accuracy against epoch, on an axis each.

    They used to share one, under a left axis labelled "Value" - which is the
    tell, since they have no common unit. Loss is a sum across nets of a mean
    per sample, so it starts near ln(number of sounds) per net and runs to ~9
    with three nets, ~15 with five. Accuracy is a fraction of 1. On one axis the
    accuracy curve is pinned into the bottom tenth of the plot as a flat line,
    which is the half anyone actually wants to read.

    Accuracy keeps a fixed 0-100 range rather than autoscaling: the question is
    "is this any good", which needs the whole scale to be visible, not a curve
    stretched to fill whatever four points it has so far.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        t = theme.colors()
        # Every other plot in the app takes this; this one was left on
        # pyqtgraph's default black.
        self.plot_widget = pg.PlotWidget(background=t["plot_bg"])
        plot = self.plot_widget.plotItem
        plot.setLabel('bottom', 'Epoch')
        plot.setLabel('left', 'Loss')
        plot.showAxis('right')
        plot.setLabel('right', 'Accuracy %')
        plot.showGrid(x=True, y=True, alpha=0.3)
        layout.addWidget(self.plot_widget)

        # Accuracy rides in its own ViewBox so it can have its own Y range. It
        # is not in the PlotItem, so it has to be added to the legend by hand
        # and kept in step with the resizes of the box it is drawn over.
        self._accuracy_vb = pg.ViewBox()
        plot.scene().addItem(self._accuracy_vb)
        plot.getAxis('right').linkToView(self._accuracy_vb)
        self._accuracy_vb.setXLink(plot)
        self._accuracy_vb.setYRange(0, 100, padding=0)
        self._accuracy_vb.setMouseEnabled(x=False, y=False)
        plot.vb.sigResized.connect(self._sync_views)

        loss_pen = pg.mkPen(color=t["text_dim"], width=2)
        accuracy_pen = pg.mkPen(color=t["accent"], width=2)
        self.loss_curve = plot.plot(pen=loss_pen, name='Loss')
        self.accuracy_curve = pg.PlotCurveItem(pen=accuracy_pen, name='Accuracy')
        self._accuracy_vb.addItem(self.accuracy_curve)

        legend = plot.addLegend(offset=(-10, 10))
        legend.addItem(self.loss_curve, 'Loss')
        legend.addItem(self.accuracy_curve, 'Accuracy')

        self._epochs = []
        self._losses = []
        self._accuracies = []
        self._sync_views()

    def _sync_views(self):
        """The second ViewBox is a sibling in the scene, not a child, so it does
        not follow the plot's geometry on its own."""
        plot = self.plot_widget.plotItem
        self._accuracy_vb.setGeometry(plot.vb.sceneBoundingRect())
        self._accuracy_vb.linkedViewChanged(plot.vb, self._accuracy_vb.XAxis)

    def add_point(self, epoch, loss, accuracy):
        self._epochs.append(epoch)
        self._losses.append(loss)
        # Held as a percentage, matching the axis it is drawn against.
        self._accuracies.append(accuracy * 100)
        self.loss_curve.setData(self._epochs, self._losses)
        self.accuracy_curve.setData(self._epochs, self._accuracies)

    def clear(self):
        self._epochs = []
        self._losses = []
        self._accuracies = []
        self.loss_curve.setData([], [])
        self.accuracy_curve.setData([], [])
