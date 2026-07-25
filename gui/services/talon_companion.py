"""Install/inspect the Talon-side companion (talon_companion/parrot_gui_bridge.py).

The companion is copied into ``<talon_user>/parrot_gui_bridge/`` where Talon
auto-loads it. Installing is an explicit user action from the Talon tab -
never automatic, since dropping a .py into the user dir takes effect live.
"""
import os
import re
import shutil

COMPANION_BASENAME = "parrot_gui_bridge.py"
COMPANION_DIRNAME = "parrot_gui_bridge"
BRIDGE_PORT = 8352


def source_path():
    """The companion file shipped inside this repo."""
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(here, "talon_companion", COMPANION_BASENAME)


def installed_path(talon_user_dir):
    return os.path.join(talon_user_dir, COMPANION_DIRNAME, COMPANION_BASENAME)


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
        "available_version": str|None, "outdated": bool}"""
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
    }


def install(talon_user_dir):
    """Copy the companion into the Talon user dir. Returns the installed path.
    Talon picks the file up automatically."""
    src = source_path()
    if not os.path.isfile(src):
        raise OSError(f"Companion source missing: {src}")
    dest = installed_path(talon_user_dir)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def uninstall(talon_user_dir):
    dest = installed_path(talon_user_dir)
    if os.path.isfile(dest):
        os.remove(dest)
    parent = os.path.dirname(dest)
    if os.path.isdir(parent) and not os.listdir(parent):
        os.rmdir(parent)
