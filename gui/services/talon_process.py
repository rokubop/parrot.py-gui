"""Is Talon running?

Asked when the bridge says nothing, to tell "Talon is closed" from "Talon is
running but has not loaded the bridge". Same silence, different fix.

Returns None when the check itself failed, which is not False.
"""
import os
import subprocess
import sys

WINDOWS_NAMES = ("talon.exe",)
POSIX_NAMES = ("talon", "Talon")

_NO_WINDOW = 0x08000000     # CREATE_NO_WINDOW, or a console flashes on Windows


def _run(command):
    try:
        return subprocess.run(
            command, capture_output=True, text=True, timeout=4,
            creationflags=_NO_WINDOW if os.name == "nt" else 0).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def is_running():
    """True / False / None when it cannot be determined."""
    if sys.platform == "win32":
        out = _run(["tasklist", "/FO", "CSV", "/NH"])
        if out is None:
            return None
        lowered = out.lower()
        return any(name in lowered for name in WINDOWS_NAMES)
    out = _run(["ps", "-A", "-o", "comm="])
    if out is None:
        return None
    names = {os.path.basename(line.strip()) for line in out.splitlines()}
    return any(name in names for name in POSIX_NAMES)
