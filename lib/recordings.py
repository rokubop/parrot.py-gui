"""Recorded sounds: their labels, recordings and detected time."""
import os
from datetime import datetime
from config.config import RECORDINGS_FOLDER, MS_PER_FRAME
from lib.srt import get_srt_paths, get_srt_path_for_wav, count_label_ms_in_srt

def get_label_dir(label):
    return os.path.join(RECORDINGS_FOLDER, label)

# Example: -> ["hiss", "pop", ...]
def get_labels():
    if not os.path.isdir(RECORDINGS_FOLDER):
        return []
    return [entry for entry in sorted(os.listdir(RECORDINGS_FOLDER))
            if not entry.startswith(".") and os.path.isdir(os.path.join(RECORDINGS_FOLDER, entry))]

# Example: "pop" -> [{"filename": "mici_0__1786747776.wav",
#                     "wav_path": "data/recordings/pop/source/mici_0__1786747776.wav",
#                     "srt_path": "data/recordings/pop/segments/mici_0__1786747776.v3.srt"}]
def get_recordings(label):
    source_dir = os.path.join(get_label_dir(label), "source")
    if not os.path.isdir(source_dir):
        return []
    srt_paths = get_srt_paths(os.path.join(get_label_dir(label), "segments"))
    return [{"filename": wav_file,
             "wav_path": os.path.join(source_dir, wav_file),
             "srt_path": get_srt_path_for_wav(srt_paths, wav_file[:-len(".wav")])}
            for wav_file in sorted(f for f in os.listdir(source_dir) if f.endswith(".wav"))]

# Detected ms across a label's srts. One that can't be parsed (hand-edited,
# cut short) counts as 0 rather than failing the whole label.
def get_detected_ms(label):
    total = 0
    for srt_path in get_srt_paths(os.path.join(get_label_dir(label), "segments")):
        try:
            total += count_label_ms_in_srt(label, srt_path, MS_PER_FRAME)
        except (OSError, ValueError, IndexError):
            pass
    return total

# Example: "mici_0__1786747776.wav" -> datetime(2026, 8, 14, 17, 49, 36), local time
def get_recorded_at(filename):
    tail = os.path.splitext(filename)[0].rsplit("__", 1)[-1]
    if not tail.isdigit():
        return None
    try:
        return datetime.fromtimestamp(int(tail))
    except (ValueError, OSError, OverflowError):
        return None

# A sound's name is also written inside its srts (the event text) and
# thresholds files (the keys, e.g. pop_min_dbfs). Detected time, the overlay
# and threshold overrides match on it, so a renamed or moved sound rewrites them.
def relabel_segment_files(paths, old_label, new_label):
    for path in paths:
        if path.endswith(".srt"):
            _rewrite_lines(path, lambda lines: _relabel_srt(lines, old_label, new_label))
        elif path.endswith("_thresholds.txt"):
            _rewrite_lines(path, lambda lines: _relabel_thresholds(lines, old_label, new_label))

def _relabel_srt(lines, old_label, new_label):
    out = []
    for i, line in enumerate(lines):
        is_event_text = i > 0 and "-->" in lines[i - 1]
        if is_event_text and line.strip().lower() == old_label.lower():
            line = new_label + line[len(line.rstrip("\r\n")):]
        out.append(line)
    return out

def _relabel_thresholds(lines, old_label, new_label):
    prefix = old_label.lower() + "_"
    return [new_label.lower() + "_" + line[len(prefix):] if line.lower().startswith(prefix) else line
            for line in lines]

def _rewrite_lines(path, change):
    with open(path, "r", encoding="utf-8", newline="") as f:
        lines = f.read().splitlines(keepends=True)
    changed = change(lines)
    if changed == lines:
        return
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8", newline="") as f:
        f.writelines(changed)
    os.replace(temp, path)
