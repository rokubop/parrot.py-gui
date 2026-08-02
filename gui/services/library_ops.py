"""Filesystem operations for sounds, recordings, and models.

Pure, Qt-free functions that mutate the on-disk library under
``data/recordings/`` and ``data/models/``. They raise ``LibraryOpError`` on
invalid input or conflicts so callers can surface a clean message. Slow audio
reprocessing (re-segmentation, trimming) lives in workers, not here - these are
all fast metadata/file moves.

On-disk layout (one sound label):
    data/recordings/<label>/source/<base>.wav
    data/recordings/<label>/segments/<base>.v<VERSION>.srt   (auto)
    data/recordings/<label>/segments/<base>.MANUAL.srt        (manual override)
    data/recordings/<label>/segments/<base>_thresholds.txt    (threshold I/O)
    data/recordings/<label>/segments/<base>_comparison.wav    (debug output)

A model:
    data/models/<name>.pkl
    data/models/<name>.pkl_<i>-weights.pth.tar
    data/models/<name>.pkl_<i>-BEST-weights.pth.tar
"""
import json
import os
import re
import sys
import shutil
import subprocess

from config.config import RECORDINGS_FOLDER, CLASSIFIER_FOLDER


class LibraryOpError(Exception):
    """A user-facing problem performing a library operation."""


# Characters that are illegal in a sound/model name on common filesystems, plus
# path separators (a name must never escape its parent directory).
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_name(name, *, kind="name"):
    """Validate and normalize a user-entered sound/model name.

    Returns the trimmed name, or raises ``LibraryOpError``. Rejects empty
    names, path separators, reserved dot-names, and illegal characters so a
    name can only ever refer to a direct child of its folder.
    """
    if name is None:
        raise LibraryOpError(f"Please enter a {kind}.")
    cleaned = name.strip()
    if not cleaned:
        raise LibraryOpError(f"Please enter a {kind}.")
    if cleaned in (".", ".."):
        raise LibraryOpError(f"'{cleaned}' is not a valid {kind}.")
    if _ILLEGAL.search(cleaned):
        raise LibraryOpError(
            f"A {kind} can't contain any of: < > : \" / \\ | ? *")
    if cleaned.startswith("."):
        raise LibraryOpError(f"A {kind} can't start with a dot.")
    return cleaned


# ---- path helpers ------------------------------------------------------

def label_dir(label):
    return os.path.join(RECORDINGS_FOLDER, label)


def source_dir(label):
    return os.path.join(RECORDINGS_FOLDER, label, "source")


def segments_dir(label):
    return os.path.join(RECORDINGS_FOLDER, label, "segments")


def sound_exists(label):
    return os.path.isdir(label_dir(label))


def model_pkl_path(name):
    return os.path.join(CLASSIFIER_FOLDER, name + ".pkl")


def model_exists(name):
    return os.path.isfile(model_pkl_path(name))


def recording_base(wav_path):
    """The shared filename stem for a recording (no .wav)."""
    return os.path.splitext(os.path.basename(wav_path))[0]


def recording_label(wav_path):
    """The sound label a recording belongs to, from its path
    (.../<label>/source/<base>.wav)."""
    return os.path.basename(os.path.dirname(os.path.dirname(wav_path)))


# ---- sound (label) operations -----------------------------------------

def create_sound(name):
    """Create an empty sound label (source/ + segments/). Returns the label."""
    label = sanitize_name(name, kind="sound name")
    if sound_exists(label):
        raise LibraryOpError(f"A sound called '{label}' already exists.")
    os.makedirs(source_dir(label), exist_ok=True)
    os.makedirs(segments_dir(label), exist_ok=True)
    return label


def rename_sound(old, new):
    """Rename a sound label directory. Returns the new label."""
    new_label = sanitize_name(new, kind="sound name")
    if not sound_exists(old):
        raise LibraryOpError(f"Sound '{old}' no longer exists.")
    if new_label == old:
        return old
    if sound_exists(new_label):
        raise LibraryOpError(f"A sound called '{new_label}' already exists.")
    os.rename(label_dir(old), label_dir(new_label))
    return new_label


def clone_sound(src, new):
    """Copy a sound label (all recordings + segments) to a new label."""
    new_label = sanitize_name(new, kind="sound name")
    if not sound_exists(src):
        raise LibraryOpError(f"Sound '{src}' no longer exists.")
    if sound_exists(new_label):
        raise LibraryOpError(f"A sound called '{new_label}' already exists.")
    shutil.copytree(label_dir(src), label_dir(new_label))
    return new_label


def delete_sound(label):
    """Delete a sound label and everything under it. Destructive."""
    if not sound_exists(label):
        raise LibraryOpError(f"Sound '{label}' no longer exists.")
    shutil.rmtree(label_dir(label))


def sound_recording_count(label):
    src = source_dir(label)
    if not os.path.isdir(src):
        return 0
    return len([f for f in os.listdir(src) if f.lower().endswith(".wav")])


# ---- recording operations ---------------------------------------------

def recording_sibling_files(wav_path):
    """Every file that belongs to one recording: the source .wav plus all
    segment-side artifacts sharing its base (srt / manual srt / thresholds /
    comparison). Used by delete and rename so nothing is orphaned."""
    files = []
    if os.path.isfile(wav_path):
        files.append(wav_path)
    base = recording_base(wav_path)
    label = recording_label(wav_path)
    seg = segments_dir(label)
    if os.path.isdir(seg):
        for f in os.listdir(seg):
            # Belongs to this recording only if the remainder starts with a
            # separator ('.' or '_'); guards against base being a prefix of a
            # different, longer timestamp.
            if f.startswith(base) and f[len(base):len(base) + 1] in (".", "_"):
                files.append(os.path.join(seg, f))
    return files


def read_mic_info(wav_path):
    """What a take was recorded with, from its ``<base>_mic.json`` sidecar, or
    None. Recordings made before the sidecar existed return None rather than a
    guess: the mic index in the filename cannot be resolved after the fact,
    because device indices shift when hardware changes."""
    base = recording_base(wav_path)
    path = os.path.join(segments_dir(recording_label(wav_path)),
                        base + "_mic.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def mics_for_labels(labels):
    """What these sounds were recorded with, as
    {"names": [...], "indices": [...], "named": n, "takes": n}.

    Names come only from sidecars, so they cover the takes made since sidecars
    existed. Indices come from every filename but are never turned into names -
    device indices shift when hardware changes, so a late lookup would
    confidently name the wrong microphone. They are here to count *how many*
    mics are involved, which the names alone cannot say when most takes predate
    the sidecar. Callers should show names and fall back to a count.
    """
    names, indices, named, takes = [], [], 0, 0
    for label in labels:
        source = os.path.join(RECORDINGS_FOLDER, label, "source")
        if not os.path.isdir(source):
            continue
        for f in sorted(os.listdir(source)):
            if not f.endswith(".wav"):
                continue
            takes += 1
            base = f[:-4]
            if base.startswith("mici_"):
                index = base.split("__")[0]
                if index not in indices:
                    indices.append(index)
            info = read_mic_info(os.path.join(source, f)) or {}
            name = (info.get("mic_name") or "").strip()
            if name:
                named += 1
                if name not in names:
                    names.append(name)
    return {"names": names, "indices": indices, "named": named, "takes": takes}


def describe_mics(summary):
    """One line for a mic summary, or "" when there is nothing to say.

    Never prints mici_<n>: an index looks like an identity and is not one. When
    nothing is named it says how many were involved and no more, which is the
    whole of what the filenames can honestly support.
    """
    if not summary:
        return ""
    names, count = summary.get("names") or [], len(summary.get("indices") or [])
    if not names:
        if count > 1:
            return f"{count} microphones, none named"
        return "Not recorded" if count else ""
    shown = ", ".join(names[:2]) + ("…" if len(names) > 2 else "")
    extra = count - len(names)
    if extra > 0:
        noun = "other" if extra == 1 else "others"
        return f"{shown}  (+{extra} unnamed {noun})"
    return shown


def delete_recording(wav_path):
    """Delete a recording's wav and all its segment artifacts. Destructive."""
    files = recording_sibling_files(wav_path)
    if not files:
        raise LibraryOpError("This recording no longer exists.")
    for f in files:
        try:
            os.remove(f)
        except FileNotFoundError:
            pass


def rename_recording(wav_path, new_base):
    """Rename a recording (wav + every segment sibling) to a new base stem.
    Returns the new wav path."""
    new_base = sanitize_name(new_base, kind="recording name")
    label = recording_label(wav_path)
    old_base = recording_base(wav_path)
    if new_base == old_base:
        return wav_path
    new_wav = os.path.join(source_dir(label), new_base + ".wav")
    if os.path.exists(new_wav):
        raise LibraryOpError(f"A recording called '{new_base}' already exists.")
    for f in recording_sibling_files(wav_path):
        directory = os.path.dirname(f)
        renamed = os.path.basename(f).replace(old_base, new_base, 1)
        os.rename(f, os.path.join(directory, renamed))
    return new_wav


def move_recording(wav_path, dest_label):
    """Move a recording (wav + segment siblings) into another sound label.
    Returns the new wav path."""
    if not sound_exists(dest_label):
        raise LibraryOpError(f"Sound '{dest_label}' no longer exists.")
    base = recording_base(wav_path)
    dest_src = source_dir(dest_label)
    dest_seg = segments_dir(dest_label)
    os.makedirs(dest_src, exist_ok=True)
    os.makedirs(dest_seg, exist_ok=True)
    new_wav = os.path.join(dest_src, base + ".wav")
    if os.path.exists(new_wav):
        raise LibraryOpError(
            f"'{dest_label}' already has a recording called '{base}'.")
    for f in recording_sibling_files(wav_path):
        name = os.path.basename(f)
        dest = dest_src if name.lower().endswith(".wav") else dest_seg
        shutil.move(f, os.path.join(dest, name))
    return new_wav


def recordings_since(label, when):
    """(takes recorded after `when`, when the newest take was). A newest of None
    means the sound has no recordings at all.

    Counted rather than only compared, so a model can say how far behind it is
    instead of only that it is behind.

    Source wavs only. Re-segmenting a take rewrites segments/ and leaves its wav
    alone, so it does not show up here even though it changes what training
    reads - load_data pairs each wav with its highest-versioned .srt.
    """
    source_dir = os.path.join(RECORDINGS_FOLDER, label, "source")
    newest, count = None, 0
    if os.path.isdir(source_dir):
        for f in os.listdir(source_dir):
            if f.endswith(".wav"):
                try:
                    mtime = os.path.getmtime(os.path.join(source_dir, f))
                except OSError:
                    continue
                if newest is None or mtime > newest:
                    newest = mtime
                if mtime > when:
                    count += 1
    return count, newest


# ---- model operations -------------------------------------------------

def model_files(name):
    """Every file making up a model: the .pkl plus all weight checkpoints."""
    files = []
    pkl = model_pkl_path(name)
    if os.path.isfile(pkl):
        files.append(pkl)
    if os.path.isdir(CLASSIFIER_FOLDER):
        prefix = name + ".pkl_"
        for f in sorted(os.listdir(CLASSIFIER_FOLDER)):
            if f.startswith(prefix):
                files.append(os.path.join(CLASSIFIER_FOLDER, f))
    return files


def delete_model(name):
    """Delete a model's pkl and all weight files. Destructive."""
    files = model_files(name)
    if not files:
        raise LibraryOpError(f"Model '{name}' no longer exists.")
    for f in files:
        try:
            os.remove(f)
        except FileNotFoundError:
            pass


def rename_model(old, new):
    """Rename a model (pkl + all weight files). Returns the new name."""
    new_name = sanitize_name(new, kind="model name")
    if not model_exists(old):
        raise LibraryOpError(f"Model '{old}' no longer exists.")
    if new_name == old:
        return old
    if model_exists(new_name):
        raise LibraryOpError(f"A model called '{new_name}' already exists.")
    old_prefix = old + ".pkl"
    new_prefix = new_name + ".pkl"
    for f in model_files(old):
        directory = os.path.dirname(f)
        renamed = os.path.basename(f).replace(old_prefix, new_prefix, 1)
        os.rename(f, os.path.join(directory, renamed))
    return new_name


def clone_model(old, new):
    """Copy a model (pkl + all weight files) to a new name. Returns it."""
    new_name = sanitize_name(new, kind="model name")
    if not model_exists(old):
        raise LibraryOpError(f"Model '{old}' no longer exists.")
    if model_exists(new_name):
        raise LibraryOpError(f"A model called '{new_name}' already exists.")
    old_prefix = old + ".pkl"
    new_prefix = new_name + ".pkl"
    for f in model_files(old):
        directory = os.path.dirname(f)
        renamed = os.path.basename(f).replace(old_prefix, new_prefix, 1)
        shutil.copy2(f, os.path.join(directory, renamed))
    return new_name


# ---- reveal in OS file manager ----------------------------------------

def open_in_file_manager(path):
    """Open ``path`` (a directory, or the folder containing a file) in the
    platform's file manager. Best-effort; raises on a hard failure."""
    if not os.path.exists(path):
        raise LibraryOpError("That location no longer exists.")
    target = path if os.path.isdir(path) else os.path.dirname(path)
    abs_target = os.path.abspath(target)
    try:
        if sys.platform == "win32":
            os.startfile(abs_target)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", abs_target])
        else:
            # Linux/WSL: try wslview (opens Windows Explorer from WSL) first,
            # then fall back to xdg-open.
            for opener in ("wslview", "xdg-open"):
                if shutil.which(opener):
                    subprocess.Popen([opener, abs_target])
                    break
            else:
                raise LibraryOpError("No file manager found to open the folder.")
    except LibraryOpError:
        raise
    except Exception as exc:  # pragma: no cover - platform dependent
        raise LibraryOpError(f"Couldn't open the folder: {exc}")
