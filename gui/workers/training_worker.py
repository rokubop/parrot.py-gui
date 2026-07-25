from PyQt6.QtCore import QThread, pyqtSignal


class TrainingWorker(QThread):
    epoch_complete = pyqtSignal(int, float, float, dict, bool)  # epoch, loss, accuracy, per_label_dict, is_best
    training_finished = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, model_name, labels, net_count=1, parent=None):
        super().__init__(parent)
        self.model_name = model_name
        self.labels = labels
        self.net_count = net_count
        self._stop_requested = False

    def run(self):
        # Placeholder - full implementation in Phase 3
        try:
            self._train()
        except Exception as e:
            self.error_occurred.emit(str(e))

        self.training_finished.emit()

    def _train(self):
        from lib.audio_net import AudioNetTrainer
        from lib.machinelearning import load_data
        from config.config import (
            RECORDINGS_FOLDER, RECORD_SECONDS, SLIDING_WINDOW_AMOUNT,
            FEATURE_ENGINEERING_TYPE, RATE, CHANNELS
        )

        audio_settings = {
            'version': 3,
            'RATE': RATE,
            'CHANNELS': CHANNELS,
            'RECORD_SECONDS': RECORD_SECONDS,
            'SLIDING_WINDOW_AMOUNT': SLIDING_WINDOW_AMOUNT,
            'FEATURE_ENGINEERING_TYPE': FEATURE_ENGINEERING_TYPE
        }

        dataset = load_data(self.labels, RECORDINGS_FOLDER, RECORD_SECONDS, FEATURE_ENGINEERING_TYPE)
        trainer = AudioNetTrainer(dataset, self.net_count, audio_settings)

        def progress_callback(epoch, loss, accuracy, per_label_accuracy, is_new_best):
            self.epoch_complete.emit(epoch, loss, accuracy, per_label_accuracy, is_new_best)

        def stop_check():
            return self._stop_requested

        trainer.train(self.model_name, progress_callback=progress_callback, stop_check=stop_check)

    def request_stop(self):
        self._stop_requested = True
