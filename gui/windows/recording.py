import os
import math
import sounddevice as sd
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QLineEdit, QLabel, QComboBox, QSlider, QSplitter,
    QGroupBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from config.config import INPUT_DEVICE_INDEX, RECORD_SECONDS, SLIDING_WINDOW_AMOUNT, RECORDINGS_FOLDER
from gui.widgets.waveform import WaveformWidget
from gui.widgets.segment_bar import SegmentBarWidget
from gui.workers.audio_worker import AudioWorker
from lib.stream_processing import process_wav_file
from lib.srt import ms_to_srt_timestring


class ResegmentWorker(QThread):
    finished = pyqtSignal(str)  # srt_path

    def __init__(self, wav_path, label, parent=None):
        super().__init__(parent)
        self.wav_path = wav_path
        self.label = label
        self.srt_path = ""
        self.threshold_file = ""

    def run(self):
        # Re-process the wav file with current settings
        base = os.path.splitext(os.path.basename(self.wav_path))[0]
        label_dir = os.path.dirname(os.path.dirname(self.wav_path))
        segments_dir = os.path.join(label_dir, "segments")
        os.makedirs(segments_dir, exist_ok=True)

        from lib.stream_processing import CURRENT_VERSION
        self.srt_path = os.path.join(segments_dir, base + ".v" + str(CURRENT_VERSION) + ".srt")
        self.threshold_file = os.path.join(segments_dir, base + "_thresholds.txt")
        output_file = os.path.join(segments_dir, base + "_comparison.wav")

        process_wav_file(
            self.wav_path, self.srt_path, output_file,
            self.threshold_file, [self.label]
        )
        self.finished.emit(self.srt_path)


class RecordingPage(QWidget):
    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.audio_worker = None
        self.resegment_worker = None
        self._current_wav_path = None
        self._current_srt_path = None
        self._current_label = None

        self._setup_ui()
        self._populate_tree()
        self._populate_devices()

        self.app_state.recordings_changed.connect(self._populate_tree)

    def _setup_ui(self):
        main_layout = QHBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # Left panel
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        # Sound library tree
        left_layout.addWidget(QLabel("Sound Library"))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Duration"])
        self.tree.itemClicked.connect(self._on_tree_item_clicked)
        left_layout.addWidget(self.tree)

        # New sound input
        new_sound_group = QGroupBox("New Recording")
        new_sound_layout = QVBoxLayout(new_sound_group)

        self.sound_name_input = QLineEdit()
        self.sound_name_input.setPlaceholderText("Sound name...")
        new_sound_layout.addWidget(self.sound_name_input)

        self.device_combo = QComboBox()
        new_sound_layout.addWidget(QLabel("Microphone:"))
        new_sound_layout.addWidget(self.device_combo)

        btn_layout = QHBoxLayout()
        self.record_btn = QPushButton("Record")
        self.record_btn.clicked.connect(self._on_record)
        btn_layout.addWidget(self.record_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop)
        btn_layout.addWidget(self.stop_btn)

        new_sound_layout.addLayout(btn_layout)
        left_layout.addWidget(new_sound_group)

        splitter.addWidget(left_panel)

        # Right panel
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        self.info_label = QLabel("Select a recording to view")
        right_layout.addWidget(self.info_label)

        self.waveform = WaveformWidget()
        right_layout.addWidget(self.waveform, stretch=3)

        self.segment_bar = SegmentBarWidget()
        self.segment_bar.link_x_axis(self.waveform)
        right_layout.addWidget(self.segment_bar)

        # dBFS slider for re-segmentation
        slider_layout = QHBoxLayout()
        slider_layout.addWidget(QLabel("dBFS threshold:"))
        self.dbfs_slider = QSlider(Qt.Orientation.Horizontal)
        self.dbfs_slider.setRange(-96, 0)
        self.dbfs_slider.setValue(-30)
        self.dbfs_slider.valueChanged.connect(self._on_dbfs_changed)
        slider_layout.addWidget(self.dbfs_slider)
        self.dbfs_label = QLabel("-30 dBFS")
        slider_layout.addWidget(self.dbfs_label)
        right_layout.addLayout(slider_layout)

        splitter.addWidget(right_panel)
        splitter.setSizes([350, 850])

    def _populate_devices(self):
        self.device_combo.clear()
        try:
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if dev['max_input_channels'] > 0:
                    default_tag = " (default)" if i == INPUT_DEVICE_INDEX else ""
                    self.device_combo.addItem(f"[{i}] {dev['name']}{default_tag}", i)
        except Exception:
            self.device_combo.addItem(f"[{INPUT_DEVICE_INDEX}] Default", INPUT_DEVICE_INDEX)

    def _populate_tree(self):
        self.tree.clear()
        labels = self.app_state.get_sound_labels()
        for label in labels:
            duration_ms = self.app_state.get_label_duration_ms(label)
            duration_str = ms_to_srt_timestring(duration_ms, False).split(",")[0]
            label_item = QTreeWidgetItem([label, duration_str])
            label_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "label", "label": label})

            recordings = self.app_state.get_recordings_for_label(label)
            for rec in recordings:
                rec_item = QTreeWidgetItem([rec["filename"], ""])
                rec_item.setData(0, Qt.ItemDataRole.UserRole, {
                    "type": "recording",
                    "label": label,
                    "wav_path": rec["wav_path"],
                    "srt_path": rec["srt_path"]
                })
                label_item.addChild(rec_item)

            self.tree.addTopLevelItem(label_item)

    def _on_tree_item_clicked(self, item, column):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data["type"] == "recording":
            self._current_wav_path = data["wav_path"]
            self._current_srt_path = data["srt_path"]
            self._current_label = data["label"]
            self.info_label.setText(f"{data['label']} / {os.path.basename(data['wav_path'])}")
            self.waveform.load_wav(data["wav_path"])
            self.segment_bar.load_srt(data["srt_path"], data["wav_path"])

    def _on_record(self):
        label = self.sound_name_input.text().strip()
        if not label:
            return

        mic_index = self.device_combo.currentData()
        if mic_index is None:
            mic_index = INPUT_DEVICE_INDEX

        self.waveform.clear_display()
        self.segment_bar.clear_display()
        self.info_label.setText(f"Recording: {label}")

        self.audio_worker = AudioWorker(label, mic_index)
        self.audio_worker.frame_recorded.connect(self.waveform.append_live_data)
        self.audio_worker.recording_finished.connect(self._on_recording_finished)
        self.audio_worker.start()

        self.record_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def _on_stop(self):
        if self.audio_worker:
            self.audio_worker.request_stop()

    def _on_recording_finished(self, wav_path, srt_path):
        self.record_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

        self._current_wav_path = wav_path
        self._current_srt_path = srt_path
        self.info_label.setText(f"Recorded: {os.path.basename(wav_path)}")

        # Refresh display
        self.waveform.load_wav(wav_path)
        self.segment_bar.load_srt(srt_path, wav_path)

        self.app_state.recordings_changed.emit()
        self.audio_worker = None

    def _on_dbfs_changed(self, value):
        self.dbfs_label.setText(f"{value} dBFS")
        if self._current_wav_path and self._current_label:
            self._resegment()

    def _resegment(self):
        if self.resegment_worker and self.resegment_worker.isRunning():
            return

        self.resegment_worker = ResegmentWorker(self._current_wav_path, self._current_label)
        self.resegment_worker.finished.connect(self._on_resegment_finished)
        self.resegment_worker.start()

    def _on_resegment_finished(self, srt_path):
        self._current_srt_path = srt_path
        self.segment_bar.load_srt(srt_path, self._current_wav_path)
        self.resegment_worker = None
