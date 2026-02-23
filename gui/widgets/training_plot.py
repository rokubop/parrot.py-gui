import pyqtgraph as pg
from PyQt6.QtWidgets import QVBoxLayout, QWidget


class TrainingPlotWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel('left', 'Value')
        self.plot_widget.setLabel('bottom', 'Epoch')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.addLegend()
        layout.addWidget(self.plot_widget)

        self.loss_curve = self.plot_widget.plot(
            pen=pg.mkPen(color='r', width=2), name='Loss'
        )
        self.accuracy_curve = self.plot_widget.plot(
            pen=pg.mkPen(color='g', width=2), name='Accuracy'
        )

        self._epochs = []
        self._losses = []
        self._accuracies = []

    def add_point(self, epoch, loss, accuracy):
        self._epochs.append(epoch)
        self._losses.append(loss)
        self._accuracies.append(accuracy)
        self.loss_curve.setData(self._epochs, self._losses)
        self.accuracy_curve.setData(self._epochs, self._accuracies)

    def clear(self):
        self._epochs = []
        self._losses = []
        self._accuracies = []
        self.loss_curve.setData([], [])
        self.accuracy_curve.setData([], [])
