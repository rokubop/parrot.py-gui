import os
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLineEdit, QLabel, QSpinBox, QSplitter, QGroupBox
)
from PyQt6.QtCore import Qt
from config.config import CLASSIFIER_FOLDER
from gui.models.app_state import AppState
from gui.widgets.training_plot import TrainingPlotWidget
from gui.workers.training_worker import TrainingWorker


class TrainingPage(QWidget):
    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.training_worker = None

        self._setup_ui()
        self._populate_labels()
        self.app_state.recordings_changed.connect(self._populate_labels)

    def _setup_ui(self):
        main_layout = QHBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        left_layout.addWidget(QLabel("Select sounds to train:"))
        self.label_list = QListWidget()
        left_layout.addWidget(self.label_list)

        splitter.addWidget(left_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        config_group = QGroupBox("Training Configuration")
        config_layout = QVBoxLayout(config_group)

        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Model name:"))
        self.model_name_input = QLineEdit()
        self.model_name_input.setPlaceholderText("my_model")
        name_layout.addWidget(self.model_name_input)
        config_layout.addLayout(name_layout)

        net_layout = QHBoxLayout()
        net_layout.addWidget(QLabel("Number of nets:"))
        self.net_count_spin = QSpinBox()
        self.net_count_spin.setRange(1, 10)
        self.net_count_spin.setValue(1)
        net_layout.addWidget(self.net_count_spin)
        config_layout.addLayout(net_layout)

        right_layout.addWidget(config_group)

        self.progress_label = QLabel("Ready to train")
        right_layout.addWidget(self.progress_label)

        self.training_plot = TrainingPlotWidget()
        right_layout.addWidget(self.training_plot, stretch=3)

        btn_layout = QHBoxLayout()
        self.train_btn = QPushButton("Train")
        self.train_btn.clicked.connect(self._on_train)
        btn_layout.addWidget(self.train_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop)
        btn_layout.addWidget(self.stop_btn)

        right_layout.addLayout(btn_layout)

        splitter.addWidget(right_panel)
        splitter.setSizes([350, 850])

    def _populate_labels(self):
        self.label_list.clear()
        labels = self.app_state.get_sound_labels()
        for label in labels:
            duration_ms = self.app_state.get_label_duration_ms(label)
            duration_str = f"{duration_ms // 1000}s" if duration_ms > 0 else "0s"
            item = QListWidgetItem(f"{label} ({duration_str})")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, label)
            self.label_list.addItem(item)

    def _get_selected_labels(self):
        selected = []
        for i in range(self.label_list.count()):
            item = self.label_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(item.data(Qt.ItemDataRole.UserRole))
        return selected

    def _on_train(self):
        model_name = self.model_name_input.text().strip()
        if not model_name:
            self.progress_label.setText("Please enter a model name")
            return

        selected = self._get_selected_labels()
        if len(selected) < 2:
            self.progress_label.setText("Select at least 2 sounds")
            return

        os.makedirs(CLASSIFIER_FOLDER, exist_ok=True)

        self.training_plot.clear()
        self.progress_label.setText("Training...")
        self.train_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        net_count = self.net_count_spin.value()
        self.training_worker = TrainingWorker(model_name, selected, net_count)
        self.training_worker.epoch_complete.connect(self._on_epoch_complete)
        self.training_worker.training_finished.connect(self._on_training_finished)
        self.training_worker.error_occurred.connect(self._on_training_error)
        self.training_worker.start()

    def _on_stop(self):
        if self.training_worker:
            self.training_worker.request_stop()

    def _on_epoch_complete(self, epoch, loss, accuracy, per_label_dict, is_best):
        self.training_plot.add_point(epoch, loss, accuracy)
        best_str = " (new best!)" if is_best else ""
        self.progress_label.setText(
            f"Epoch {epoch + 1} - Loss: {loss:.4f} - Accuracy: {accuracy:.3f}{best_str}"
        )

    def _on_training_finished(self):
        self.train_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_label.setText("Training complete")
        self.app_state.models_changed.emit()
        self.training_worker = None

    def _on_training_error(self, error_msg):
        self.train_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_label.setText(f"Error: {error_msg}")
        self.training_worker = None
