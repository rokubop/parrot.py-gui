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
import sys
import shutil
import subprocess

from config.config import RECORDINGS_FOLDER
from lib import models, recordings
from lib.recordings import get_label_dir, relabel_segment_files, InvalidLabel


class LibraryOpError(Exception):
    """A user-facing problem performing a library operation."""


_INVALID_NAME_TEXT = {
    InvalidLabel.EMPTY: "Please enter a {kind}.",
    InvalidLabel.ILLEGAL_CHARACTER: "A {kind} can't contain any of: < > : \" / \\ | ? *",
    InvalidLabel.STARTS_WITH_DOT: "A {kind} can't start with a dot.",
}


def sanitize_name(name, *, kind="name"):
    """Validate and normalize a user-entered sound/model/recording name.

    Returns the trimmed name, or raises ``LibraryOpError``. One rule for all
    three: lib's ``clean_label``, worded here.
    """
    try:
        return recordings.clean_label(name)
    except InvalidLabel as exc:
        raise LibraryOpError(_INVALID_NAME_TEXT[exc.reason].format(kind=kind)) from None


# ---- path helpers ------------------------------------------------------

def source_dir(label):
    return os.path.join(RECORDINGS_FOLDER, label, "source")


def segments_dir(label):
    return os.path.join(RECORDINGS_FOLDER, label, "segments")


def sound_exists(label):
    return os.path.isdir(get_label_dir(label))


def model_exists(name):
    return os.path.isfile(models.get_model_path(name))


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
    try:
        return recordings.create_label(label)
    except InvalidLabel:
        raise LibraryOpError(f"A sound called '{label}' already exists.") from None


def rename_sound(old, new):
    """Rename a sound label directory. Returns the new label."""
    new_label = sanitize_name(new, kind="sound name")
    if not sound_exists(old):
        raise LibraryOpError(f"Sound '{old}' no longer exists.")
    if new_label == old:
        return old
    if sound_exists(new_label):
        raise LibraryOpError(f"A sound called '{new_label}' already exists.")
    os.rename(get_label_dir(old), get_label_dir(new_label))
    _relabel_sound(old, new_label)
    return new_label


def clone_sound(src, new):
    """Copy a sound label (all recordings + segments) to a new label."""
    new_label = sanitize_name(new, kind="sound name")
    if not sound_exists(src):
        raise LibraryOpError(f"Sound '{src}' no longer exists.")
    if sound_exists(new_label):
        raise LibraryOpError(f"A sound called '{new_label}' already exists.")
    shutil.copytree(get_label_dir(src), get_label_dir(new_label))
    _relabel_sound(src, new_label)
    return new_label


def _relabel_sound(old, new_label):
    seg = segments_dir(new_label)
    if os.path.isdir(seg):
        relabel_segment_files([os.path.join(seg, f) for f in os.listdir(seg)], old, new_label)


def delete_sound(label):
    """Delete a sound label and everything under it. Destructive."""
    if not sound_exists(label):
        raise LibraryOpError(f"Sound '{label}' no longer exists.")
    shutil.rmtree(get_label_dir(label))


def sound_recording_count(label):
    src = source_dir(label)
    if not os.path.isdir(src):
        return 0
    return len([f for f in os.listdir(src) if f.lower().endswith(".wav")])


# ---- recording operations ---------------------------------------------

# Every file of one recording, so delete and rename orphan nothing
recording_sibling_files = recordings.get_recording_files


def take_group(wav_path):
    """Every mic's wav for one take, the given one first.

    The shared time_string in ``mici_<n>__<time_string>.wav`` is the only link.
    Single-mic takes return themselves, so a take is always a group. Rewriting a
    take's audio must cover all of them or the files end up different lengths.
    """
    base = recording_base(wav_path)
    source = os.path.dirname(wav_path)
    if not base.startswith("mici_") or "__" not in base or not os.path.isdir(source):
        return [wav_path]
    time_string = base.split("__", 1)[1]
    group = [wav_path]
    for f in sorted(os.listdir(source)):
        if not f.lower().endswith(".wav") or f[:-4] == base:
            continue
        if f.startswith("mici_") and f[:-4].split("__", 1)[-1] == time_string:
            group.append(os.path.join(source, f))
    return group


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


def take_strategy(wav_path):
    """The detection strategy a take was recorded with, from its sidecar, or
    None for takes that predate strategy capture. Callers pass it to
    process_wav_file, whose None falls back to the configured default."""
    info = read_mic_info(wav_path)
    return info.get("strategy") if info else None


def mics_for_labels(labels):
    """What these sounds were recorded with, as
    {"names": [...], "indices": [...], "named": n, "takes": n}.

    Names come only from sidecars. Indices come from every filename but are
    never turned into names - device indices shift when hardware changes, so a
    late lookup would name the wrong microphone; they only count how many mics
    were involved. Callers should show names and fall back to a count.
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

    Never prints mici_<n>: an index looks like an identity and is not one.
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
    if not recordings.delete_recording(wav_path):
        raise LibraryOpError("This recording no longer exists.")


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
    old_label = recording_label(wav_path)
    moved = []
    for f in recording_sibling_files(wav_path):
        name = os.path.basename(f)
        dest = dest_src if name.lower().endswith(".wav") else dest_seg
        moved.append(shutil.move(f, os.path.join(dest, name)))
    relabel_segment_files(moved, old_label, dest_label)
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

def delete_model(name):
    """Delete a model's pkl and all weight files. Destructive."""
    files = models.get_model_files(name)
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
    for f in models.get_model_files(old):
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
    for f in models.get_model_files(old):
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
