"""Re-detect a saved clip at a threshold you choose.

Both screens that show a take need this. Sounds -> edit view is where you come
back to a recording weeks later; the recording view needs it the moment you hit
Pause, which is when you can still see what detection missed and record it
again. Before this was shared, the recording view had nothing and sent you to a
second screen, and the same idea had two vocabularies: an Automatic/Manual combo
in one place, a slider with Apply and Auto-detect in the other.

The lane is the same number as the slider, drawn on the audio. Dragging the line
moves the slider and re-detects on release; both write a ``.MANUAL.srt`` that
takes precedence over the automatic one.

What stays with the host: taking the clip busy while a pass runs, and what to do
with the srt that comes back.
"""
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QVBoxLayout
)

from gui import theme
from gui.widgets.click_slider import ClickSlider, slider_qss
from gui.workers.segment_worker import (
    ReSegmentWorker, ResetWorker, has_manual_override, read_override
)


class DetectionPanel(QGroupBox):
    """Threshold + type + Apply, driving the re-detection workers."""

    status = pyqtSignal(str)            # a line for the host's status/hint label
    busy_changed = pyqtSignal(bool, str)  # a pass started/finished, with a caption
    changed = pyqtSignal(str)           # a new srt was written

    def __init__(self, history, parent=None):
        super().__init__("Detection (the blue overlay)", parent)
        self.history = history
        self.wav_path = None
        self.label = None
        self.worker = None
        self.lane = None
        # Whether the host is already rewriting these files (a trim). Asked
        # before every pass, because the panel cannot see the host's work.
        self.host_busy = lambda: False
        # (min_dbfs, duration_type) of the last detect, to skip redundant re-runs
        self._last_applied = None

        # Debounce live threshold drags: re-detect once the line settles instead
        # of on every intermediate value.
        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(350)
        self._apply_timer.timeout.connect(self.apply)

        self._setup_ui()

    # ---- ui ------------------------------------------------------------

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(6)
        row = QHBoxLayout()
        root.addLayout(row)
        row.addWidget(QLabel("Threshold:"))
        self.slider = ClickSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(-96, 0)
        self.slider.setValue(-40)
        self.slider.setMinimumWidth(220)
        self.slider.setMinimumHeight(24)
        self.slider.valueChanged.connect(self._on_slider)
        self.slider.setStyleSheet(slider_qss())
        row.addWidget(self.slider, 1)
        self.slider_label = QLabel("-40 dBFS")
        self.slider_label.setMinimumWidth(80)
        row.addWidget(self.slider_label)
        row.addWidget(QLabel("Type:"))
        self.duration_combo = QComboBox()
        self.duration_combo.addItem("Auto", "")
        self.duration_combo.addItem("Discrete", "discrete")
        self.duration_combo.addItem("Continuous", "continuous")
        row.addWidget(self.duration_combo)
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.apply_btn.setToolTip("Re-detect at this threshold / type")
        self.apply_btn.clicked.connect(self.apply)
        row.addWidget(self.apply_btn)
        self.reset_btn = QPushButton("Auto-detect")
        self.reset_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.reset_btn.setToolTip("Let detection find the threshold automatically "
                                  "(drops the manual override); the slider then "
                                  "shows what it picked")
        self.reset_btn.clicked.connect(self.reset)
        row.addWidget(self.reset_btn)

        # Warn, do not fence. The floor is per clip, and a quiet recording can
        # legitimately want a value this one would call too low.
        self.warning = QLabel("")
        self.warning.setStyleSheet(f"color: {theme.colors()['warn']};")
        self.warning.setVisible(False)
        root.addWidget(self.warning)

    def _check_noise_floor(self):
        """Under the clip's own floor, detection does not find more, it finds
        nothing: every frame reads as sound and the pass writes an empty srt."""
        floor = self.lane.noise_floor() if self.lane is not None else None
        under = floor is not None and self.slider.value() < floor
        if under:
            self.warning.setText(
                f"Under this clip's noise floor ({round(floor)} dBFS). "
                f"Detection finds nothing down here.")
        self.warning.setVisible(under)

    def attach_lane(self, lane):
        """Wire the clip's dBFS lane to the slider. The line and the number are
        the same value, so only one of them may be the source of truth: the line
        pushes into the slider, never the reverse."""
        self.lane = lane
        lane.threshold_moved.connect(self._on_lane_moved)
        lane.threshold_committed.connect(lambda _v: self._apply_timer.start())

    def refresh_theme(self):
        self.slider.setStyleSheet(slider_qss())
        self.warning.setStyleSheet(f"color: {theme.colors()['warn']};")

    # ---- binding a clip -------------------------------------------------

    def bind(self, wav_path, label, threshold=None):
        """Point at a clip.

        ``threshold`` is for a take that was just recorded against a threshold
        someone pinned live: the srt on disk came from that value, but no
        ``.MANUAL.srt`` exists yet, so disk alone would report it as automatic.
        """
        self.wav_path = wav_path
        self.label = label
        self._apply_timer.stop()
        self._last_applied = None
        if threshold is None:
            self.sync_from_file()
        else:
            self._set_slider(threshold)
            self._set_type("")
            self._show_on_lane("manual")
        self.set_busy(False)

    def clear(self):
        self.wav_path = None
        self.label = None
        self.warning.setVisible(False)
        self._apply_timer.stop()
        self._last_applied = None

    def resync(self):
        """The files moved under us - an undo, a redo, a trim.

        Re-read them, and let the next Apply run even if it repeats the last
        value: what was applied and what is on disk have just come apart, so
        "no change to apply" would refuse a pass that would change everything.
        """
        if not self.wav_path:
            return
        self._last_applied = None
        self.sync_from_file()

    def sync_from_file(self):
        """Move the slider to whatever threshold is on disk - so after
        Auto-detect it shows the value detection picked.

        The lane follows, and says which of the two it is: a value someone set,
        or the floor detection settled on for a threshold that moves per sound.
        """
        existing, duration_type = read_override(self.wav_path)
        manual = has_manual_override(self.wav_path)
        self._set_slider(existing if existing is not None else -40)
        # Automatic writes a duration_type too, with what it found. Only a
        # manual override makes it a value someone chose.
        self._set_type(duration_type if manual else "")
        # A settled 0 means calibration never engaged: it needs ten onset
        # valleys. A line at 0 would claim a cutoff nothing can clear.
        self._show_on_lane("manual" if manual else "auto",
                           visible=manual or (existing is not None and existing < 0))

    def _set_slider(self, value):
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(value)))
        self.slider.blockSignals(False)
        self.slider_label.setText(f"{self.slider.value()} dBFS")
        self._check_noise_floor()

    def _set_type(self, duration_type):
        index = self.duration_combo.findData(duration_type or "")
        self.duration_combo.blockSignals(True)
        self.duration_combo.setCurrentIndex(max(0, index))
        self.duration_combo.blockSignals(False)

    def _show_on_lane(self, mode, visible=True):
        if self.lane is None:
            return
        self.lane.set_threshold(self.slider.value())
        self.lane.set_mode(mode)
        self.lane.set_editable(True)
        self.lane.set_line_visible(visible)

    def _on_slider(self, *_):
        self.slider_label.setText(f"{self.slider.value()} dBFS")
        self._check_noise_floor()
        # Touching the slider is choosing, so the lane stops reporting what
        # detection found and starts showing what is about to be applied.
        self._show_on_lane("manual")

    def _on_lane_moved(self, value):
        """Dragging the line moves the slider, not the other way round."""
        self.slider.setValue(int(round(value)))

    # ---- running a pass -------------------------------------------------

    def is_busy(self):
        return self.worker is not None

    def set_busy(self, busy):
        for w in (self.apply_btn, self.reset_btn, self.slider,
                  self.duration_combo):
            w.setEnabled(not busy)

    def _finish_worker(self):
        """Tear a finished detection thread down safely. The result signal fires
        before run() returns, so wait() before dropping the reference or a
        still-running QThread gets deleted (a hard crash)."""
        w = self.worker
        self.worker = None
        if w is not None:
            w.wait()
            w.deleteLater()

    def _start(self, worker, caption, message):
        self.history.checkpoint()
        self.worker = worker
        self.set_busy(True)
        self.busy_changed.emit(True, caption)
        self.status.emit(message)
        worker.finished_ok.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        worker.start()

    def apply(self):
        if not self.wav_path:
            return
        if self.worker or self.host_busy():
            # Something is still writing; retry once it's free so the latest
            # threshold the user landed on is the one that sticks.
            self._apply_timer.start()
            return
        params = (self.slider.value(), self.duration_combo.currentData())
        if params == self._last_applied:
            self.status.emit("No change to apply.")
            return  # nothing changed since the last detect - skip the slow work
        self._last_applied = params
        self._start(ReSegmentWorker(self.wav_path, self.label, *params),
                    "Re-detecting…", "Re-detecting…")

    def reset(self):
        if self.worker or self.host_busy() or not self.wav_path:
            return
        self._apply_timer.stop()
        self._last_applied = None   # auto state - let the next threshold apply
        self._start(ResetWorker(self.wav_path, self.label),
                    "Auto-detecting…", "Resetting to automatic detection…")

    def _on_done(self, srt_path):
        self._finish_worker()
        self.sync_from_file()
        self.set_busy(False)
        self.busy_changed.emit(False, "")
        self.changed.emit(srt_path)
        self.status.emit("Detection updated.")

    def _on_failed(self, message, wrote_files):
        self._finish_worker()
        self._last_applied = None   # let the user retry the same threshold
        if wrote_files:
            # Part of the take was rewritten before it died. Keep the checkpoint
            # so Ctrl+Z still reaches a change that happened, and re-read what
            # is actually on disk now.
            self.sync_from_file()
            self.changed.emit("")   # "" = whatever the host resolves for itself
        else:
            self.history.discard_last_checkpoint()
        self.set_busy(False)
        self.busy_changed.emit(False, "")
        self.status.emit("")
        QMessageBox.warning(self, "Couldn't update detection", message)

    def cleanup(self):
        self._apply_timer.stop()
        if self.worker is not None:
            self.worker.wait()
            self.worker = None
