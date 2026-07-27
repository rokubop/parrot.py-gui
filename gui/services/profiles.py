"""Profiles: each profile is a complete, self-contained data root.

Pointing the app at a different root makes every code path act as that user,
so a profile is simply a folder shaped like ``data/``:

    data-profiles/<name>/
        profile.json     {"talon": "real" | "none"}
        .baseline/       frozen copy of the data tree; Reset restores it
        recordings/  models/  code/  notes.json  ...

The original ``data/`` is the Main profile: it has no profile.json and no
baseline, and can never be reset or deleted from the app. Switching sets
``PARROT_DATA_DIR`` (and ``PARROT_TALON_HOME`` for Talon simulation) and
relaunches the GUI; ``lib/default_config.py`` derives every data path from
that env var at import time, which is why a restart is required.

All functions are Qt-free and raise ProfileError with a readable message.
"""
import json
import os
import re
import shutil
import subprocess
import sys

from config.config import DATA_DIR, DATA_ROOT, PROFILES_DIR

MAIN_DATA_DIR = os.path.join(DATA_ROOT, "data")
META_FILE = "profile.json"
BASELINE_DIR = ".baseline"
CURRENT_POINTER = os.path.join(PROFILES_DIR, "current")

# Names double as folder names, same rules as pattern variants.
_VALID_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,60}$")

# Entries that describe the profile rather than belong to its data tree.
_NON_DATA = (BASELINE_DIR, META_FILE, "__pycache__")


class ProfileError(Exception):
    pass


def debug_enabled():
    return bool(os.environ.get("PARROT_DEBUG"))


def current_profile():
    """Name of the active profile, or None when running on the real data/."""
    root = os.path.normpath(DATA_DIR)
    parent, name = os.path.split(root)
    if os.path.normpath(parent) == os.path.normpath(PROFILES_DIR):
        return name
    return None


def profile_data_dir(name):
    return os.path.join(PROFILES_DIR, name)


def list_profiles():
    if not os.path.isdir(PROFILES_DIR):
        return []
    return sorted(
        n for n in os.listdir(PROFILES_DIR)
        if os.path.isdir(os.path.join(PROFILES_DIR, n)) and not n.startswith(".")
    )


def stats(data_dir):
    """(sound labels, models) counted the same way the app itself does."""
    sounds = 0
    recordings = os.path.join(data_dir, "recordings")
    if os.path.isdir(recordings):
        sounds = sum(1 for n in os.listdir(recordings)
                     if os.path.isdir(os.path.join(recordings, n)))
    models = 0
    models_dir = os.path.join(data_dir, "models")
    if os.path.isdir(models_dir):
        models = sum(1 for n in os.listdir(models_dir) if n.endswith(".pkl"))
    return sounds, models


def read_meta(name):
    path = os.path.join(profile_data_dir(name), META_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_meta(name, meta):
    path = os.path.join(profile_data_dir(name), META_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def _check_new_name(name):
    if not _VALID_NAME.match(name or ""):
        raise ProfileError("Profile names use letters, numbers, spaces, . _ -")
    if name == "current":
        # would collide with the data-profiles/current pointer file
        raise ProfileError("current is reserved; pick another name")
    if name in list_profiles():
        raise ProfileError(f"A profile named {name} already exists")


def _copy_data_tree(src, dst):
    """Copy a data tree, leaving out profile bookkeeping and caches."""
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*_NON_DATA))


def create_empty(name):
    _check_new_name(name)
    root = profile_data_dir(name)
    for sub in ("recordings", "models", "code"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    write_meta(name, {"talon": "real"})
    freeze(name)


def duplicate(source_data_dir, name, talon="real"):
    """New profile from any data tree: the real data/ or another profile."""
    _check_new_name(name)
    if not os.path.isdir(source_data_dir):
        raise ProfileError(f"Nothing to copy at {source_data_dir}")
    _copy_data_tree(source_data_dir, profile_data_dir(name))
    write_meta(name, {"talon": talon})
    freeze(name)


def freeze(name):
    """Save the profile as it is now; Reset returns here."""
    root = profile_data_dir(name)
    if not os.path.isdir(root):
        raise ProfileError(f"No profile named {name}")
    baseline = os.path.join(root, BASELINE_DIR)
    staging = baseline + ".new"
    if os.path.isdir(staging):
        shutil.rmtree(staging)
    _copy_data_tree(root, staging)
    if os.path.isdir(baseline):
        shutil.rmtree(baseline)
    os.rename(staging, baseline)


def reset(name):
    """Throw away everything since the baseline was frozen."""
    root = profile_data_dir(name)
    baseline = os.path.join(root, BASELINE_DIR)
    if not os.path.isdir(baseline):
        raise ProfileError(f"{name} has no baseline to reset to")
    for entry in os.listdir(root):
        if entry in _NON_DATA:
            continue
        path = os.path.join(root, entry)
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
    for entry in os.listdir(baseline):
        src = os.path.join(baseline, entry)
        dst = os.path.join(root, entry)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)


def delete(name):
    root = profile_data_dir(name)
    if not os.path.isdir(root):
        raise ProfileError(f"No profile named {name}")
    shutil.rmtree(root)
    # a stale pointer would fall back to Main anyway; keep it truthful
    try:
        with open(CURRENT_POINTER, encoding="utf-8") as f:
            if f.read().strip() == name:
                os.remove(CURRENT_POINTER)
    except OSError:
        pass


def set_current(name):
    """Persist which profile fresh launches should land on (None for Main)."""
    if name is None:
        try:
            os.remove(CURRENT_POINTER)
        except OSError:
            pass
        return
    os.makedirs(PROFILES_DIR, exist_ok=True)
    with open(CURRENT_POINTER, "w", encoding="utf-8") as f:
        f.write(name + "\n")


def export_copy(source_data_dir, dest_parent):
    """Complete copy of a data tree into dest_parent, for backups.
    Returns the created folder; auto-suffixes rather than overwriting."""
    if not os.path.isdir(source_data_dir):
        raise ProfileError(f"Nothing to export at {source_data_dir}")
    base = os.path.join(dest_parent, "parrot-data")
    dest = base
    counter = 2
    while os.path.exists(dest):
        dest = f"{base}-{counter}"
        counter += 1
    _copy_data_tree(source_data_dir, dest)
    return dest


# ---- bringing in an outside setup -------------------------------------
#
# CLI veterans have a year-old checkout somewhere on disk. Importing copies
# its data tree in as a profile via duplicate(); the original folder is
# never touched. The Home card offering this is dismissible per data root.

IMPORT_CARD_MARKER = ".import-card-dismissed"


def import_card_dismissed():
    return os.path.exists(os.path.join(DATA_DIR, IMPORT_CARD_MARKER))


def dismiss_import_card():
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, IMPORT_CARD_MARKER), "w"):
        pass


def resolve_setup_dir(path):
    """Accepts a checkout root or a data dir; returns the data dir or None."""
    for candidate in (os.path.join(path, "data"), path):
        if os.path.isdir(os.path.join(candidate, "recordings")):
            return candidate
    return None


_SCAN_SKIP = {"node_modules", "__pycache__", "Library", "Applications",
              "Movies", "Music", "Pictures", "AppData"}


def find_existing_setups():
    """Parrot data trees in the usual places: shallow scan of the home dir
    and common code folders, looking for the <dir>/data/recordings shape.
    Returns [{data_dir, label, sounds, models}], fullest setups first."""
    home = os.path.expanduser("~")
    roots = [home] + [os.path.join(home, d) for d in
                      ("dev", "code", "projects", "src", "repos", "git",
                       "Documents", "Desktop", "Downloads")]
    own = {os.path.realpath(DATA_DIR), os.path.realpath(PROFILES_DIR)}
    results, seen = [], set()

    def visit(directory, depth):
        data_dir = os.path.join(directory, "data")
        if os.path.isdir(os.path.join(data_dir, "recordings")):
            real = os.path.realpath(data_dir)
            if real not in seen and real not in own:
                seen.add(real)
                sounds, models = stats(data_dir)
                if sounds or models:
                    label = data_dir.replace(home, "~", 1)
                    results.append({"data_dir": os.path.abspath(data_dir),
                                    "label": label,
                                    "sounds": sounds, "models": models})
            return  # a checkout; no nested checkouts expected
        if depth == 0:
            return
        try:
            entries = os.scandir(directory)
        except OSError:
            return
        with entries:
            for entry in entries:
                if (entry.name.startswith(".") or entry.name in _SCAN_SKIP):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        visit(entry.path, depth - 1)
                except OSError:
                    continue

    for root in roots:
        if os.path.isdir(root):
            visit(root, 2)
    results.sort(key=lambda r: r["sounds"] + r["models"], reverse=True)
    return results


def spawn_into(name):
    """Start a fresh GUI process running as `name` (None for Main).

    The caller quits the current app afterwards; the new process is detached
    so it survives that. The choice is also persisted so launches from the
    dock/start menu land on the same profile.
    """
    set_current(name)
    env = dict(os.environ)
    if name is None:
        env.pop("PARROT_DATA_DIR", None)
        env.pop("PARROT_TALON_HOME", None)
    else:
        env["PARROT_DATA_DIR"] = profile_data_dir(name)
        # "real" uses the machine's Talon; "none" simulates its absence; any
        # other value is a path to a mock Talon home (test profiles bundle one)
        sim = read_meta(name).get("talon")
        if sim and sim != "real":
            env["PARROT_TALON_HOME"] = sim
        else:
            env.pop("PARROT_TALON_HOME", None)
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008  # DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([sys.executable, "-m", "gui"], env=env,
                     cwd=os.getcwd(), **kwargs)
