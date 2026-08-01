"""Runs a training job and reports what it is doing.

The trainer talks by printing. `load_pytorch_data` names every label and the
sampling strategy it picked; `AudioDataset` names every label again as it
indexes; the training loop prints loss and accuracy every ten minibatches, and
per net accuracy at each validation. All of it went to a terminal nobody was
looking at, while the GUI showed one sentence for the first several minutes and
then a single line per epoch.

So this captures stdout for the duration of the run and does two things with it:
re-emits every line verbatim, which is what the page's CLI view shows, and
matches the handful of lines that carry structure into typed signals. Capturing
rather than threading a callback through lib/ keeps `learn_data.py` and the rest
of the CLI untouched - the same words reach both, and there is no second format
to keep in sync.

Two things to know about the capture:

- `sys.stdout` is process global, so this swaps it for the length of the run and
  restores it in a finally. Anything else printing meanwhile lands in the log,
  which during a training run is the right place for it anyway.
- The batch line arrives roughly four times a second at this library's size, not
  the flood it looks like: 861 minibatches per net per epoch, printed one line in
  ten, over an epoch measured in minutes.
"""
import re
import sys

from PyQt6.QtCore import QThread, pyqtSignal

# "Loading in guh using undersampling: -33%" / "Loading in oo"
RE_LOADING = re.compile(
    r"^Loading in (?P<label>.+?)"
    r"(?: using (?P<how>over|under)sampling: (?P<pct>[+-]\d+)%"
    r"|(?P<other> by sampling from other labels))?$")
RE_INDEXING = re.compile(r"^Indexing (?P<label>.+?)\.\.\.$")
RE_BATCH = re.compile(
    r"^\[Net: (?P<net>\d+), (?P<epoch>\d+),\s*(?P<batch>\d+)\] "
    r"loss: (?P<loss>[\d.]+) acc: (?P<acc>[\d.]+)$")
RE_NET_VALID = re.compile(
    r"^\[Net: (?P<net>\d+)\] Validation loss: (?P<loss>[\d.]+) "
    r"accuracy (?P<acc>[\d.]+)$")
RE_EMPTY_SRT = re.compile(
    r"^Empty \.SRT file for (?P<source>.+?) - Consider deleting "
    r"(?P<srt>.+?) to resegment")
RE_PERSIST = re.compile(r"^Persisting new combined best in (?P<name>.+)$")


class _LineTee:
    """Feeds whole lines to a callback and to the original stream.

    print() arrives in fragments - the text, then the newline - so this buffers
    until it has a line. Keeping the original stream means a terminal-launched
    run still behaves exactly as it did.
    """

    def __init__(self, original, on_line):
        self._original = original
        self._on_line = on_line
        self._buffer = ""

    def write(self, text):
        if self._original is not None:
            try:
                self._original.write(text)
            except Exception:
                pass
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.rstrip("\r")
            if line:
                self._on_line(line)

    def flush(self):
        if self._original is not None:
            try:
                self._original.flush()
            except Exception:
                pass

    def isatty(self):
        return False


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

    # Everything below is lifted out of the trainer's own printing.
    log_line = pyqtSignal(str)                  # verbatim, for the CLI view
    label_loaded = pyqtSignal(str, str, int)    # label, "oversample"/"undersample"/"sample", percent
    label_indexed = pyqtSignal(str)
    batch_progress = pyqtSignal(int, int, int, float, float)  # net, epoch, batch, loss, acc
    net_validated = pyqtSignal(int, float)      # net number (1-based), accuracy
    best_saved = pyqtSignal()
    data_warning = pyqtSignal(str, str)         # source wav, srt to delete

    def __init__(self, model_name, labels, net_count=1, parent=None):
        super().__init__(parent)
        self.model_name = model_name
        self.labels = labels
        self.net_count = net_count
        self._stop_requested = False
        self._seen_warnings = set()

    def run(self):
        original = sys.stdout
        sys.stdout = _LineTee(original, self._on_line)
        try:
            self._train()
        except Exception as e:
            self.error_occurred.emit(str(e))
        finally:
            sys.stdout = original

        self.training_finished.emit()

    # ---- reading the trainer's own output --------------------------------

    def _on_line(self, line):
        self.log_line.emit(line)

        match = RE_BATCH.match(line)
        if match:
            self.batch_progress.emit(
                int(match["net"]), int(match["epoch"]), int(match["batch"]),
                float(match["loss"]), float(match["acc"]))
            return

        match = RE_LOADING.match(line)
        if match:
            how = match["how"]
            strategy = (f"{how}sample" if how
                        else "background" if match["other"] else "sample")
            self.label_loaded.emit(match["label"], strategy,
                                   int(match["pct"] or 0))
            return

        match = RE_INDEXING.match(line)
        if match:
            self.label_indexed.emit(match["label"])
            return

        match = RE_NET_VALID.match(line)
        if match:
            self.net_validated.emit(int(match["net"]), float(match["acc"]))
            return

        match = RE_EMPTY_SRT.match(line)
        if match:
            # The trainer reports the same file once per pass over it, so this
            # arrives four times for one problem. Report each file once.
            key = match["source"]
            if key not in self._seen_warnings:
                self._seen_warnings.add(key)
                self.data_warning.emit(match["source"], match["srt"])
            return

        if RE_PERSIST.match(line):
            self.best_saved.emit()

    # ---- the run ---------------------------------------------------------

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
        self.stage_changed.emit("Indexing…")
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
