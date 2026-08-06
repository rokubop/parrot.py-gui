"""Dialogs for testing a model: offline accuracy against recorded segments,
and a live mic test with per-sound probability bars.

Both answer "is my model good?" with parrot.py's own pipeline - deliberately
separate from the Integrations tab, which shows what the deployed Talon setup
does.
"""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QListWidget, QScrollArea, QWidget, QFrame
)

from gui import theme
from gui.widgets.click_slider import ClickSlider, slider_qss
from gui.workers.eval_worker import AccuracyWorker, LiveTestWorker

WINNER_THRESHOLD = 0.5
# dBFS is bounded below by the bit depth (16-bit silence is -96), so the low end
# of the slider is "let everything through" rather than an arbitrary floor.
QUIET_OFF = -96
# On by default: the model answers on every frame, so an ungated dialog twitches
# at room noise the whole time. Same number the Edit view's detection slider
# starts at.
QUIET_DEFAULT = -40


class AccuracyDialog(QDialog):
    def __init__(self, parent, model_name, model_path, labels):
        super().__init__(parent)
        self.setWindowTitle(f"Accuracy - {model_name}")
        self.setMinimumSize(640, 480)
        t = theme.colors()

        layout = QVBoxLayout(self)
        self.status = QLabel("Starting…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Sound", "Samples", "Recall", "Precision", "Confused with"])
        self.table.horizontalHeaderItem(2).setToolTip(
            "Of this sound's recorded segments, how many the model labels correctly")
        self.table.horizontalHeaderItem(3).setToolTip(
            "When the model says this sound, how often it's right (within this test set)")
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        row = QHBoxLayout()
        row.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        layout.addLayout(row)

        self.worker = AccuracyWorker(model_path, labels)
        self.worker.progressed.connect(self.status.setText)
        self.worker.failed.connect(
            lambda msg: self.status.setText(f"Failed: {msg}"))
        self.worker.finished_ok.connect(self._on_result)
        self.worker.start()

    def _on_result(self, result):
        t = theme.colors()
        per_sound = result["per_sound"]
        self.table.setRowCount(len(per_sound))
        for row, (label, entry) in enumerate(
                sorted(per_sound.items(), key=lambda kv: kv[1]["recall"])):
            confusions = ", ".join(
                f"{k} ×{v}" for k, v in list(entry["confusions"].items())[:3])
            precision = result["precision"].get(label)
            cells = [label, str(entry["samples"]),
                     f"{entry['recall']:.1%}",
                     f"{precision:.1%}" if precision is not None else "-",
                     confusions]
            for col, value in enumerate(cells):
                item = QTableWidgetItem(value)
                if col == 2:
                    recall = entry["recall"]
                    item.setForeground(QColor(
                        t["ok"] if recall >= 0.9 else
                        t["warn"] if recall >= 0.75 else t["bad"]))
                self.table.setItem(row, col, item)
        parts = [f"Overall: {result['overall']:.1%} of "
                 f"{sum(e['samples'] for e in per_sound.values())} segments "
                 "labelled correctly."]
        if result["skipped"]:
            parts.append(f"Skipped (not in model / no data): "
                         f"{', '.join(result['skipped'])}.")
        if result["rate_mismatch"]:
            parts.append(f"⚠ Model expects {result['rate_mismatch']} Hz but "
                         "the app is configured differently - results are "
                         "unreliable.")
        self.status.setText(" ".join(parts))

    def closeEvent(self, event):
        if self.worker.isRunning():
            self.worker.wait(100)
        super().closeEvent(event)


class LiveTestDialog(QDialog):
    def __init__(self, parent, model_name, model_path, mic_index=None):
        super().__init__(parent)
        self.setWindowTitle(f"Live test - {model_name}")
        self.setMinimumSize(560, 620)
        t = theme.colors()
        self._latest = None
        self._last_winner = None
        self._min_dbfs = QUIET_DEFAULT
        self._quiet_shown = False

        layout = QVBoxLayout(self)
        self.status = QLabel("Listening… make your sounds. This is the raw "
                             "model - no probability thresholds, no throttles.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {t['text_dim']};")
        layout.addWidget(self.status)

        # The model always answers with one of its sounds, so a quiet room
        # still produces a winner and the bars never settle. This gate is the
        # dialog's own, not the model's: it decides which frames are worth
        # reading, and never what the model is asked.
        quiet_row = QHBoxLayout()
        quiet_label = QLabel("Ignore quieter than:")
        quiet_label.setStyleSheet(f"color: {t['text_dim']};")
        quiet_row.addWidget(quiet_label)
        self.quiet_slider = ClickSlider(Qt.Orientation.Horizontal)
        self.quiet_slider.setRange(QUIET_OFF, 0)
        self.quiet_slider.setValue(QUIET_DEFAULT)
        self.quiet_slider.setMinimumWidth(180)
        self.quiet_slider.setMinimumHeight(24)
        self.quiet_slider.setStyleSheet(slider_qss())
        self.quiet_slider.setToolTip(
            "Below this level the bars sit still and nothing is logged. Drag "
            "it up until room noise stops moving them, then make your sound. "
            "All the way down is off.")
        self.quiet_slider.valueChanged.connect(self._on_quiet_changed)
        quiet_row.addWidget(self.quiet_slider, 1)
        self.quiet_value = QLabel("off")
        self.quiet_value.setMinimumWidth(72)
        self.quiet_value.setStyleSheet(f"color: {t['text']};")
        quiet_row.addWidget(self.quiet_value)
        layout.addLayout(quiet_row)

        # Live level, so the slider can be set against what the room actually
        # measures rather than by guessing at a number.
        self.dbfs_label = QLabel("dBFS: -")
        self.dbfs_label.setStyleSheet(f"color: {t['text_dim']};")
        layout.addWidget(self.dbfs_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        bars_widget = QWidget()
        self.bars_layout = QVBoxLayout(bars_widget)
        self.bars_layout.setSpacing(4)
        scroll.setWidget(bars_widget)
        layout.addWidget(scroll, 2)
        self.bars = {}

        self.log_title = QLabel("")
        layout.addWidget(self.log_title)
        self.log = QListWidget()
        layout.addWidget(self.log, 1)

        row = QHBoxLayout()
        row.addStretch()
        close = QPushButton("Stop && close")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        layout.addLayout(row)

        self._on_quiet_changed(QUIET_DEFAULT)

        self.worker = LiveTestWorker(model_path, mic_index)
        self.worker.failed.connect(
            lambda msg: self.status.setText(f"Failed: {msg}"))
        self.worker.frame_classified.connect(self._on_frame)
        self.worker.start()

        # Coalesce UI updates - frames arrive much faster than 30 fps.
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._render)
        self._timer.start()

    def _ensure_bars(self, labels):
        if self.bars:
            return
        for label in labels:
            row = QHBoxLayout()
            name = QLabel(label)
            name.setFixedWidth(140)
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setTextVisible(False)
            bar.setFixedHeight(14)
            value = QLabel("0.00")
            value.setFixedWidth(44)
            row.addWidget(name)
            row.addWidget(bar, 1)
            row.addWidget(value)
            self.bars_layout.addLayout(row)
            self.bars[label] = (name, bar, value)
        self.bars_layout.addStretch()

    def _on_quiet_changed(self, value):
        self._min_dbfs = value
        off = value <= QUIET_OFF
        self.quiet_value.setText("off" if off else f"{value} dBFS")
        self.log_title.setText(
            "Detections (probability ≥ 50%):" if off
            else f"Detections (probability ≥ 50%, above {value} dBFS):")
        # A frame that was the last winner may now be below the line; forget it
        # so the next loud one logs rather than being read as a repeat.
        self._last_winner = None
        # Redraw against the new line rather than waiting for a frame, or
        # dropping the slider to 0 leaves the bars mid-sound.
        self._quiet_shown = False

    def _on_frame(self, probabilities, dbfs):
        self._latest = (probabilities, dbfs)
        if dbfs < self._min_dbfs:
            # Too quiet to be one of your sounds. The model still ran on it -
            # what is dropped is showing the answer and calling it a detection.
            self._last_winner = None
            return
        winner = max(probabilities, key=probabilities.get)
        if probabilities[winner] >= WINNER_THRESHOLD:
            if winner != self._last_winner:
                self.log.insertItem(
                    0, f"{winner}   ({probabilities[winner]:.2f})")
                if self.log.count() > 200:
                    self.log.takeItem(200)
            self._last_winner = winner
        else:
            self._last_winner = None

    def _render(self):
        if self._latest is None:
            return
        probabilities, dbfs = self._latest
        self._ensure_bars(sorted(probabilities.keys()))
        t = theme.colors()

        # Below the line the bars are emptied once and then left alone, so the
        # panel is still whenever nothing is being said into the mic. Holding
        # the last values instead would read as a stuck reading, and letting
        # them run is the twitching this gate exists to stop. The level below
        # keeps updating - it is what you set the slider against.
        if dbfs < self._min_dbfs:
            if not self._quiet_shown:
                self._quiet_shown = True
                for name, bar, value in self.bars.values():
                    bar.setValue(0)
                    value.setText("-")
                    name.setStyleSheet(f"color: {t['text_dim']};")
            self.dbfs_label.setText(
                f"dBFS: {dbfs:.1f}   (below {self._min_dbfs}, ignored)")
            return

        self._quiet_shown = False
        winner = max(probabilities, key=probabilities.get)
        for label, (name, bar, value) in self.bars.items():
            p = probabilities.get(label, 0.0)
            bar.setValue(round(p * 1000))
            value.setText(f"{p:.2f}")
            highlight = label == winner and p >= WINNER_THRESHOLD
            name.setStyleSheet(
                f"color: {t['accent']}; font-weight: bold;" if highlight
                else f"color: {t['text']};")
        self.dbfs_label.setText(f"dBFS: {dbfs:.1f}")

    def closeEvent(self, event):
        self._timer.stop()
        self.worker.stop()
        self.worker.wait(1500)
        super().closeEvent(event)

    def reject(self):
        self._timer.stop()
        self.worker.stop()
        self.worker.wait(1500)
        super().reject()
