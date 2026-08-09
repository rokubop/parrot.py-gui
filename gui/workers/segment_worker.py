"""Background workers for re-segmenting and trimming a recording.

All three run ``process_wav_file`` (slow) off the UI thread:

* ReSegmentWorker - write a manual dBFS/duration-type override and re-detect,
  producing a ``.MANUAL.srt`` that takes precedence (the "blue overlay" redo).
* ResetWorker - drop any manual override and regenerate the automatic
  ``.v<VERSION>.srt``.
* TrimWorker - rewrite the source WAV with selected time ranges removed
  (destructive), then re-detect. The waveform and detection both update because
  both are derived from the rewritten file.
"""
import os
import wave
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from lib.stream_processing import process_wav_file, CURRENT_VERSION
from gui.services import library_ops


def _paths(wav_path):
    base = library_ops.recording_base(wav_path)
    label = library_ops.recording_label(wav_path)
    seg = library_ops.segments_dir(label)
    os.makedirs(seg, exist_ok=True)
    return base, label, seg


def _manual_srt(seg, base):
    return os.path.join(seg, base + ".MANUAL.srt")


def _auto_srt(seg, base):
    return os.path.join(seg, base + ".v" + str(CURRENT_VERSION) + ".srt")


def _thresholds(seg, base):
    return os.path.join(seg, base + "_thresholds.txt")


def _comparison(seg, base):
    return os.path.join(seg, base + "_comparison.wav")


def read_min_dbfs(wav_path):
    """Current override min_dbfs for a recording (from its thresholds file), or
    None if there's no manual override yet."""
    base, _label, seg = _paths(wav_path)
    path = _thresholds(seg, base)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line:
                    key, value = line.strip().split("=", 1)
                    if key.endswith("_min_dbfs"):
                        return float(value)
    except (OSError, ValueError):
        return None
    return None


def has_manual_override(wav_path):
    """Whether this recording's detection came from a threshold someone set,
    rather than one detection settled on. Same test ``redetect`` makes, so the
    two can never disagree about which the screen is showing."""
    base, _label, seg = _paths(wav_path)
    return os.path.isfile(_thresholds(seg, base)) and os.path.isfile(_manual_srt(seg, base))


def redetect(wav_path, label):
    """Re-run detection on a wav, preserving a manual threshold override if the
    recording has one (-> MANUAL.srt) else producing the automatic .v<N>.srt.
    Re-detection uses the strategy the take was recorded with (its sidecar).
    Returns the srt path written."""
    base, _label, seg = _paths(wav_path)
    strategy = library_ops.take_strategy(wav_path)
    if os.path.isfile(_thresholds(seg, base)) and os.path.isfile(_manual_srt(seg, base)):
        srt = _manual_srt(seg, base)
        process_wav_file(wav_path, srt, _comparison(seg, base), None, [label],
                         override_file=_thresholds(seg, base), strategy=strategy)
    else:
        srt = _auto_srt(seg, base)
        process_wav_file(wav_path, srt, _comparison(seg, base),
                         _thresholds(seg, base), [label], strategy=strategy)
    return srt


class ReSegmentWorker(QThread):
    """Re-run detection with a manual threshold override -> MANUAL.srt."""
    finished_ok = pyqtSignal(str)   # srt path
    failed = pyqtSignal(str)

    def __init__(self, wav_path, label, min_dbfs, duration_type, parent=None):
        super().__init__(parent)
        self.wav_path = wav_path
        self.label = label
        self.min_dbfs = min_dbfs
        self.duration_type = duration_type  # "", "discrete", or "continuous"

    def run(self):
        try:
            base, _label, seg = _paths(self.wav_path)
            override_path = _thresholds(seg, base)
            lines = []
            # min_dBFS is only honored when negative; clamp 0 to a tiny negative.
            value = self.min_dbfs if self.min_dbfs < 0 else -0.01
            if self.duration_type in ("discrete", "continuous"):
                lines.append(f"{self.label.lower()}_duration_type={self.duration_type}")
            lines.append(f"{self.label.lower()}_min_dbfs={value}")
            with open(override_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")

            srt = _manual_srt(seg, base)
            # thresholds_file=None so post_processing doesn't overwrite the
            # override we just wrote; override_file feeds it back in.
            process_wav_file(self.wav_path, srt, _comparison(seg, base), None,
                             [self.label], override_file=override_path,
                             strategy=library_ops.take_strategy(self.wav_path))
            self.finished_ok.emit(srt)
        except Exception as exc:
            self.failed.emit(str(exc))


class ResetWorker(QThread):
    """Discard manual overrides and regenerate the automatic segmentation."""
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, wav_path, label, parent=None):
        super().__init__(parent)
        self.wav_path = wav_path
        self.label = label

    def run(self):
        try:
            base, _label, seg = _paths(self.wav_path)
            for path in (_manual_srt(seg, base), _thresholds(seg, base)):
                if os.path.isfile(path):
                    os.remove(path)
            srt = _auto_srt(seg, base)
            process_wav_file(self.wav_path, srt, _comparison(seg, base),
                             _thresholds(seg, base), [self.label],
                             strategy=library_ops.take_strategy(self.wav_path))
            self.finished_ok.emit(srt)
        except Exception as exc:
            self.failed.emit(str(exc))


class TrimWorker(QThread):
    """Remove time ranges from a take, then re-detect. Destructive.

    Every microphone's file gets the same ranges cut. They are one take
    recorded in parallel, so trimming only the one on screen leaves the others
    a different length and the take no longer lines up with itself.

    All the audio is rewritten before any of it is re-detected: a failure part
    way through detection leaves a take whose audio is still consistent, and a
    wrong srt is recoverable in a way a half-trimmed take is not.

    Two results, because they take wildly different times: rewriting a wav is a
    mask and a write, while re-detection reprocesses the whole clip. ``trimmed``
    fires once the audio is cut so the waveform can update at once, and
    ``finished_ok`` follows with the srt for the overlay.
    """
    trimmed = pyqtSignal(float, float, float)  # cut start, removed, new duration
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str, bool)             # message, files already changed

    def __init__(self, wav_path, label, ranges, parent=None):
        super().__init__(parent)
        self.wav_path = wav_path
        self.label = label
        self.ranges = ranges  # list of (start_s, end_s)
        self.group = library_ops.take_group(wav_path)

    def run(self):
        written = False
        try:
            removed = new_duration = 0.0
            for index, wav in enumerate(self.group):
                result = self._trim_wav(wav)
                written = True
                if index == 0:
                    removed, new_duration = result
            cut_start = min((r[0] for r in self.ranges), default=0.0)
            self.trimmed.emit(cut_start, removed, new_duration)

            srt = None
            for index, wav in enumerate(self.group):
                result = redetect(wav, self.label)
                if index == 0:
                    srt = result
            self.finished_ok.emit(srt)
        except Exception as exc:
            extra = ""
            if written and len(self.group) > 1:
                extra = (f"\n\nThis take has {len(self.group)} microphone files "
                         f"and they may no longer match. Undo restores all of "
                         f"them.")
            self.failed.emit(str(exc) + extra, written)

    def _trim_wav(self, wav_path):
        wf = wave.open(wav_path, "rb")
        nch = wf.getnchannels()
        sw = wf.getsampwidth()
        fr = wf.getframerate()
        n = wf.getnframes()
        raw = wf.readframes(n)
        wf.close()

        arr = np.frombuffer(raw, dtype=np.int16)
        total = len(arr) // nch          # actual frame count (header may overcount)
        arr = arr[:total * nch].reshape(total, nch)

        keep = np.ones(total, dtype=bool)
        for start_s, end_s in self.ranges:
            i0 = max(0, int(start_s * fr))
            i1 = min(total, int(end_s * fr))
            if i1 > i0:
                keep[i0:i1] = False
        trimmed = arr[keep]

        out = wave.open(wav_path, "wb")
        out.setnchannels(nch)
        out.setsampwidth(sw)
        out.setframerate(fr)
        out.writeframes(trimmed.tobytes())
        out.close()

        # Measured off the mask, not the requested range: what was asked for is
        # clamped to the clip and rounded to whole frames.
        kept = int(keep.sum())
        removed = (total - kept) / fr if fr else 0.0
        return removed, (kept / fr if fr else 0.0)


class AppendWorker(QThread):
    """Concatenate one recording's audio onto another, then re-detect the
    combined clip. Used to extend an existing recording with a fresh take.
    Not destructive to data - it grows the target."""
    finished_ok = pyqtSignal(str)   # srt path of the (longer) target
    failed = pyqtSignal(str)

    def __init__(self, target_wav, source_wav, label, parent=None):
        super().__init__(parent)
        self.target_wav = target_wav
        self.source_wav = source_wav
        self.label = label

    def run(self):
        try:
            self._concat()
            self.finished_ok.emit(redetect(self.target_wav, self.label))
        except Exception as exc:
            self.failed.emit(str(exc))

    def _concat(self):
        t_nch, t_sw, t_fr, t = self._read(self.target_wav)
        s_nch, s_sw, s_fr, s = self._read(self.source_wav)
        if s_nch != t_nch or s_sw != t_sw:
            raise ValueError("Can't append: channel/sample-width mismatch.")
        if s_fr != t_fr and len(s):
            # Resample the new audio to the target's rate so they splice cleanly.
            n_out = max(1, int(len(s) * t_fr / s_fr))
            s = np.interp(np.linspace(0, len(s), n_out, endpoint=False),
                          np.arange(len(s)), s.astype(np.float32)).astype(np.int16)
        combined = np.concatenate([t, s])
        out = wave.open(self.target_wav, "wb")
        out.setnchannels(t_nch)
        out.setsampwidth(t_sw)
        out.setframerate(t_fr)
        out.writeframes(combined.tobytes())
        out.close()

    @staticmethod
    def _read(path):
        wf = wave.open(path, "rb")
        nch, sw, fr = wf.getnchannels(), wf.getsampwidth(), wf.getframerate()
        raw = wf.readframes(wf.getnframes())
        wf.close()
        arr = np.frombuffer(raw, dtype=np.int16)
        # Average to mono if needed so the splice is always mono int16.
        if nch > 1:
            usable = (len(arr) // nch) * nch
            arr = arr[:usable].reshape(-1, nch).mean(axis=1).astype(np.int16)
            nch = 1
        return nch, sw, fr, arr
