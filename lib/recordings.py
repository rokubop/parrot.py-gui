"""Recorded sounds: their labels, recordings and detected time."""
import os
import re
from datetime import datetime
from typing import List, Tuple
from config.config import RECORDINGS_FOLDER, MS_PER_FRAME
from lib.srt import get_srt_paths, get_srt_path_for_wav, count_label_ms_in_srt, current_v_ending

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

class InvalidLabel(Exception):
    EMPTY = "empty"
    ILLEGAL_CHARACTER = "illegal_character"
    STARTS_WITH_DOT = "starts_with_dot"
    EXISTS = "exists"

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason

# Path separators and what Windows forbids, so a label is always one folder
_ILLEGAL_LABEL_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

def clean_label(name: str) -> str:
    """A new label, trimmed e.g. "  pop " -> "pop". Raises InvalidLabel. No leading
    dot: get_labels skips those"""
    label = (name or "").strip()
    if not label:
        raise InvalidLabel(InvalidLabel.EMPTY)
    if _ILLEGAL_LABEL_CHARACTERS.search(label):
        raise InvalidLabel(InvalidLabel.ILLEGAL_CHARACTER)
    if label.startswith("."):
        raise InvalidLabel(InvalidLabel.STARTS_WITH_DOT)
    return label

def create_label(name: str) -> str:
    """An empty label with its source and segments folders. Raises InvalidLabel,
    EXISTS if it is there already"""
    label = clean_label(name)
    if os.path.isdir(get_label_dir(label)):
        raise InvalidLabel(InvalidLabel.EXISTS)
    os.makedirs(os.path.join(get_label_dir(label), "source"))
    os.makedirs(os.path.join(get_label_dir(label), "segments"))
    return label

def create_recording_paths(label: str, mic_index: int, time_string: str) -> Tuple[str, str]:
    """Wav and srt paths for a new recording, folders made if missing. Mics
    recording together share a time_string

    e.g. ("pop", 1, "1786747776") -> ("data/recordings/pop/source/mici_1__1786747776.wav",
                                      "data/recordings/pop/segments/mici_1__1786747776.v3.srt")
    """
    base = f"mici_{mic_index}__{time_string}"
    source_dir = os.path.join(get_label_dir(label), "source")
    segments_dir = os.path.join(get_label_dir(label), "segments")
    os.makedirs(source_dir, exist_ok=True)
    os.makedirs(segments_dir, exist_ok=True)
    return os.path.join(source_dir, base + ".wav"), os.path.join(segments_dir, base + current_v_ending)

def get_recording_files(wav_path: str) -> List[str]:
    """A recording's wav and segment files, those that exist. mici_1__170.v3.srt
    is not mici_1__17's

    e.g. ".../pop/source/mici_1__17.wav" -> [".../pop/source/mici_1__17.wav",
                                             ".../pop/segments/mici_1__17.v3.srt",
                                             ".../pop/segments/mici_1__17_thresholds.txt"]
    """
    base = os.path.splitext(os.path.basename(wav_path))[0]
    segments_dir = os.path.join(os.path.dirname(os.path.dirname(wav_path)), "segments")
    files = [wav_path] if os.path.isfile(wav_path) else []
    if os.path.isdir(segments_dir):
        files += [os.path.join(segments_dir, filename) for filename in sorted(os.listdir(segments_dir))
                  if filename.startswith(base) and filename[len(base):len(base) + 1] in (".", "_")]
    return files

def delete_recording(wav_path: str) -> List[str]:
    """Deletes a recording's wav and segment files. Returns them, [] if already gone"""
    files = get_recording_files(wav_path)
    for path in files:
        os.remove(path)
    return files
