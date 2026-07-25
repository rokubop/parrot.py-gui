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
        """Mirror lib/learn_data.py's Audio Net branch exactly.

        This used to call a `load_data` that does not exist in
        lib.machinelearning, so every GUI training run died at the import. The
        real entry point is load_pytorch_data + an AudioDataset wrapper, and the
        settings dict comes from the same helper the CLI uses so a GUI-trained
        model is byte-comparable with a CLI-trained one.
        """
        # torch-importing modules stay function-local: pytorch is optional for
        # the rest of the app, and on Windows it must load before Qt.
        from lib.audio_net import AudioNetTrainer
        from lib.audio_dataset import AudioDataset
        from lib.load_data import load_pytorch_data
        from lib.combine_models import get_current_default_settings

        audio_settings = get_current_default_settings()

        data = load_pytorch_data(self.labels,
                                 audio_settings['FEATURE_ENGINEERING_TYPE'])
        dataset = AudioDataset(data)
        trainer = AudioNetTrainer(dataset, self.net_count, audio_settings)

        def progress_callback(epoch, loss, accuracy, per_label_accuracy, is_new_best):
            self.epoch_complete.emit(epoch, loss, accuracy, per_label_accuracy, is_new_best)

        def stop_check():
            return self._stop_requested

        # The trainer derives every weight file from this name, and the library
        # expects <name>.pkl + <name>.pkl_<i>-BEST-weights.pth.tar - so the
        # extension belongs in the filename, exactly as the CLI passes it.
        trainer.train(self.model_name + ".pkl",
                      progress_callback=progress_callback,
                      stop_check=stop_check)

    def request_stop(self):
        self._stop_requested = True
