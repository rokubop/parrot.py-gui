import os
import wave
from datetime import datetime
import numpy as np
import sounddevice as sd
from PyQt6.QtCore import Qt, QTimer, QElapsedTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
)
from gui.widgets.audio_preview import AudioPreviewWidget
from gui import theme


def _parse_date(session_name):
    """Filenames end in __<unix-timestamp>; decode it to a readable date."""
    tail = session_name.rsplit("__", 1)[-1]
    if not tail.isdigit():
        return ""
    try:
        return datetime.fromtimestamp(int(tail)).strftime("%b %d, %Y")
    except (ValueError, OSError, OverflowError):
        return ""


def _wav_duration(path):
    try:
        wf = wave.open(path, "rb")
        rate = wf.getframerate()
        frames = wf.getnframes()
        wf.close()
        return frames / rate if rate else 0.0
    except Exception:
        return 0.0


class SessionCard(QFrame):
    """Read-only view of one recording session: a large waveform/spectrogram
    preview with detection overlaid, plus play/pause and click-to-seek."""

    started = pyqtSignal(object)   # emits self when playback begins
    selected = pyqtSignal(object)  # emits self when the card is interacted with

    def __init__(self, session_name, wav_path, srt_path, thresholds_path, parent=None):
        super().__init__(parent)
        self.wav_path = wav_path

        self._audio = None
        self._sample_rate = None
        self._duration = 0.0
        self._position = 0.0       # playhead position in seconds (kept across pause)
        self._play_start = 0.0     # position playback began from
        self._playing = False

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._clock = QElapsedTimer()

        self._apply_border(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(4)
        layout.addLayout(self._build_header(session_name, thresholds_path))

        self.preview = AudioPreviewWidget()
        self.preview.setMinimumHeight(125)
        self.preview.load(wav_path, srt_path)
        self.preview.seeked.connect(self._on_seek)
        self.preview.pressed.connect(lambda: self.selected.emit(self))
        layout.addWidget(self.preview)

    def _build_header(self, session_name, thresholds_path):
        row = QHBoxLayout()
        self.play_btn = QPushButton("▶ Play")
        self.play_btn.setFixedWidth(90)
        self.play_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.play_btn.clicked.connect(self.toggle_play)
        row.addWidget(self.play_btn)

        t = theme.colors()
        title = session_name.split("__")[0]
        name = QLabel(title)
        name.setStyleSheet(f"color: {t['text']}; font-weight: bold; border: none; background: transparent;")
        row.addWidget(name)

        meta_text = self._build_meta_text(session_name)
        if meta_text:
            meta = QLabel(meta_text)
            meta.setStyleSheet(f"color: {t['text_dim']}; border: none; background: transparent;")
            row.addWidget(meta)

        row.addStretch()

        threshold_text = self._read_threshold(thresholds_path)
        if threshold_text:
            thr = QLabel(threshold_text)
            thr.setStyleSheet(f"color: {t['text_dim']}; border: none; background: transparent;")
            row.addWidget(thr)
        return row

    def _build_meta_text(self, session_name):
        parts = []
        date = _parse_date(session_name)
        if date:
            parts.append(date)
        length = _wav_duration(self.wav_path)
        if length:
            parts.append(f"{length:.1f}s")
        return "   ·   ".join(parts)

    def _read_threshold(self, path):
        if not path or not os.path.isfile(path):
            return ""
        dbfs = dtype = None
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if "=" not in line:
                        continue
                    key, value = line.strip().split("=", 1)
                    if key.endswith("_min_dbfs"):
                        dbfs = value
                    elif key.endswith("_duration_type"):
                        dtype = value
        except Exception:
            return ""
        parts = []
        if dbfs is not None:
            try:
                parts.append(f"{float(dbfs):.1f} dBFS")
            except ValueError:
                parts.append(f"{dbfs} dBFS")
        if dtype:
            parts.append(dtype)
        return "  ·  ".join(parts)

    # ---- selection / mode ---------------------------------------------

    def set_selected(self, selected):
        self._apply_border(selected)

    def _apply_border(self, selected):
        t = theme.colors()
        color = t["accent"] if selected else t["border"]
        self.setStyleSheet(
            "SessionCard { border: 1px solid %s; border-radius: %s; "
            "background-color: %s; } "
            "SessionCard:hover { border-color: %s; }"
            % (color, t["radius"], t["card"], t["accent"])
        )

    def set_mode(self, mode):
        self.preview.set_mode(mode)

    def set_normalized(self, normalized):
        self.preview.set_normalized(normalized)

    # ---- playback ------------------------------------------------------

    def _load_audio(self):
        if self._audio is not None:
            return
        wf = wave.open(self.wav_path, "rb")
        channels = wf.getnchannels()
        self._sample_rate = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)
        wf.close()
        data = np.frombuffer(raw, dtype=np.int16)
        if channels > 1:
            data = data.reshape(-1, channels)
        self._audio = data
        self._duration = n_frames / self._sample_rate if self._sample_rate else 0.0

    def toggle_play(self):
        if self._playing:
            self.pause()
        else:
            self.play()

    def play(self, from_seconds=None):
        try:
            self._load_audio()
        except Exception:
            return
        if self._audio is None or self._sample_rate is None:
            return
        if from_seconds is not None:
            self._position = from_seconds

        self.selected.emit(self)
        self.started.emit(self)

        self._position = max(0.0, min(self._position, self._duration))
        self._play_start = self._position
        start_sample = int(self._position * self._sample_rate)

        sd.stop()
        sd.play(self._audio[start_sample:], self._sample_rate)

        self._playing = True
        self.play_btn.setText("⏸ Pause")
        self.preview.set_playhead(self._position)
        self._clock.restart()
        self._timer.start()

    def pause(self):
        if self._playing:
            sd.stop()
            self._position = self._play_start + self._clock.elapsed() / 1000.0
            self._position = max(0.0, min(self._position, self._duration))
        self._playing = False
        self._timer.stop()
        self.play_btn.setText("▶ Play")
        self.preview.set_playhead(self._position)

    def stop(self):
        """Stop playback without preserving position (used when another card plays)."""
        if self._playing:
            sd.stop()
        self._playing = False
        self._timer.stop()
        self.play_btn.setText("▶ Play")

    def cleanup(self):
        """Release resources before deletion."""
        self.stop()
        self.preview.cleanup()

    def seek_relative(self, delta_seconds):
        pos = self._position
        if self._playing:
            pos = self._play_start + self._clock.elapsed() / 1000.0
        self.play(from_seconds=pos + delta_seconds)

    def _on_seek(self, seconds):
        self.play(from_seconds=seconds)

    def _tick(self):
        elapsed = self._play_start + self._clock.elapsed() / 1000.0
        if elapsed >= self._duration:
            self.preview.set_playhead(self._duration)
            self.stop()
            self._position = 0.0
            self.preview.set_playhead(0.0)
            return
        self._position = elapsed
        self.preview.set_playhead(elapsed)
