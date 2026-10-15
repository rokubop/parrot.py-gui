"""Read-only filesystem helpers for sounds, recordings, and models.

Pure, Qt-free functions over the on-disk library under ``data/recordings/``
and ``data/models/``.

On-disk layout (one sound label):
    data/recordings/<label>/source/<base>.wav
    data/recordings/<label>/segments/<base>.v<VERSION>.srt   (auto)
    data/recordings/<label>/segments/<base>.MANUAL.srt        (manual override)
    data/recordings/<label>/segments/<base>_thresholds.txt    (threshold I/O)

A model:
    data/models/<name>.pkl
    data/models/<name>.pkl_<i>-weights.pth.tar
    data/models/<name>.pkl_<i>-BEST-weights.pth.tar
"""
import os
import sys
import shutil
import subprocess

from config.config import RECORDINGS_FOLDER, CLASSIFIER_FOLDER


class LibraryOpError(Exception):
    """A user-facing problem performing a library operation."""


def label_dir(label):
    return os.path.join(RECORDINGS_FOLDER, label)


def model_pkl_path(name):
    return os.path.join(CLASSIFIER_FOLDER, name + ".pkl")


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
