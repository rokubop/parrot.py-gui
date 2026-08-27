"""Resolve the data root that every user data path derives from.

A checkout (a ./data dir in cwd) keeps the classic relative paths, so the CLI
and existing setups never move. An installed app has no writable cwd, so the
root is the platform user-data dir. PARROT_DATA_DIR overrides everything;
otherwise data-profiles/current picks the active profile
(see gui/services/profiles.py).
"""
import os
import sys


def _default_data_root():
    if os.path.isdir("data"):
        return ""  # checkout: paths stay exactly "data/..."
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "parrot.py")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/parrot.py")
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "parrot.py")


def _read_current_profile(profiles_dir):
    # A stale pointer (deleted profile) falls back to Main.
    try:
        with open(os.path.join(profiles_dir, "current"), encoding="utf-8") as f:
            name = f.read().strip()
    except OSError:
        return None
    if name and os.path.isdir(os.path.join(profiles_dir, name)):
        return name
    return None


DATA_ROOT = _default_data_root()
PROFILES_DIR = os.path.join(DATA_ROOT, "data-profiles")

_env_data_dir = os.environ.get("PARROT_DATA_DIR")
_current_profile = None if _env_data_dir else _read_current_profile(PROFILES_DIR)
if _env_data_dir:
    DATA_DIR = _env_data_dir
elif _current_profile:
    DATA_DIR = os.path.join(PROFILES_DIR, _current_profile)
else:
    DATA_DIR = os.path.join(DATA_ROOT, "data")
