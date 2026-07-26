from PyQt6.QtCore import QThread, pyqtSignal


class TrainingWorker(QThread):
    epoch_complete = pyqtSignal(int, float, float, dict, bool)  # epoch, loss, accuracy, per_label_dict, is_best
    training_finished = pyqtSignal()
    error_occurred = pyqtSignal(str)
    # Reading and feature-extracting every recording happens before the first
    # epoch and takes long enough to look like a hang, so it says so.
    stage_changed = pyqtSignal(str)
    # Emitted once the trainer exists, carrying its epoch ceiling. The view
    # needs it to turn elapsed time into "how much is left", and it comes from
    # the trainer rather than a copy of 300 in the GUI.
    run_started = pyqtSignal(int)

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

        noun = "sound" if len(self.labels) == 1 else "sounds"
        self.stage_changed.emit(
            f"Reading every recording of {len(self.labels)} {noun}…")
        data = load_pytorch_data(self.labels,
                                 audio_settings['FEATURE_ENGINEERING_TYPE'])
        dataset = AudioDataset(data)
        trainer = AudioNetTrainer(dataset, self.net_count, audio_settings)
        self.run_started.emit(trainer.max_epochs)

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
