"""Install/inspect the Talon-side bridge (talon_companion/parrotpy_bridge.py).

Copied into ``<talon_user>/talon-parrotpy-bridge/`` where Talon auto-loads it.
Installing is an explicit user action from the Integrations tab, never
automatic: dropping a .py into the user dir takes effect live.
"""
import os
import re
import shutil
import tempfile

COMPANION_BASENAME = "parrotpy_bridge.py"
COMPANION_DIRNAME = "talon-parrotpy-bridge"
# 0.1.0 shipped here. Left behind, it publishes duplicate frames, so install
# offers to remove it.
LEGACY_BASENAME = "parrot_gui_bridge.py"
LEGACY_DIRNAME = "parrot_gui_bridge"
BRIDGE_PORT = 8352


def source_path():
    """The bridge file shipped inside this repo."""
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(here, "talon_companion", COMPANION_BASENAME)


def installed_path(talon_user_dir):
    return os.path.join(talon_user_dir, COMPANION_DIRNAME, COMPANION_BASENAME)


def legacy_path(talon_user_dir):
    """Where 0.1.0 installed itself, or None if nothing is there."""
    if not talon_user_dir:
        return None
    path = os.path.join(talon_user_dir, LEGACY_DIRNAME, LEGACY_BASENAME)
    return path if os.path.isfile(path) else None


# The bridge attaches to Talon only while this file is fresh, so the app has
# to keep touching it for as long as the test screen is open. Same path is
# hardcoded in parrotpy_bridge.py; it lives outside the Talon user dir so
# rewriting it does not wake Talon's file watcher.
LISTEN_FILE = os.path.join(tempfile.gettempdir(), "parrotpy-bridge-listening")


def announce_listening():
    try:
        with open(LISTEN_FILE, "w", encoding="utf-8") as f:
            f.write("parrot.py test screen open\n")
    except OSError:
        pass


def stop_listening():
    try:
        os.remove(LISTEN_FILE)
    except OSError:
        pass


def _version_of(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            match = re.search(r"^__version__\s*=\s*['\"]([^'\"]+)['\"]",
                              f.read(), re.MULTILINE)
        return match.group(1) if match else None
    except OSError:
        return None


def status(talon_user_dir):
    """{"installed": bool, "path": str, "installed_version": str|None,
        "available_version": str|None, "outdated": bool, "legacy": str|None}"""
    path = installed_path(talon_user_dir) if talon_user_dir else None
    installed_version = _version_of(path) if path and os.path.isfile(path) else None
    available_version = _version_of(source_path())
    return {
        "installed": installed_version is not None,
        "path": path,
        "installed_version": installed_version,
        "available_version": available_version,
        "outdated": (installed_version is not None
                     and available_version is not None
                     and installed_version != available_version),
        "legacy": legacy_path(talon_user_dir),
    }


def install(talon_user_dir, remove_legacy=False):
    """Copy the bridge into the Talon user dir. Returns the installed path.
    Talon picks the file up automatically."""
    src = source_path()
    if not os.path.isfile(src):
        raise OSError(f"Bridge source missing: {src}")
    dest = installed_path(talon_user_dir)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(src, dest)
    if remove_legacy:
        _remove(legacy_path(talon_user_dir))
    return dest


def uninstall(talon_user_dir):
    _remove(installed_path(talon_user_dir))


def _remove(path):
    if not path or not os.path.isfile(path):
        return
    os.remove(path)
    parent = os.path.dirname(path)
    if os.path.isdir(parent) and not os.listdir(parent):
        os.rmdir(parent)
