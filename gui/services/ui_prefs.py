"""Settings about the screen, not about the data.

Interface size belongs to the machine you are sitting at: a laptop and a 4K
monitor want different answers, and neither answer should travel when a data
folder is copied between them or swapped by the profile switcher. So this is
the one preference kept outside `DATA_DIR` - beside the profiles pointer in the
platform user-data dir, not inside any profile.

**Stdlib only, and it must stay that way.** `gui/__main__.py` reads this before
it imports anything else, because on Windows torch's DLLs have to load before
Qt's (see `_preload`), and `QT_SCALE_FACTOR` has to be set before the first
QApplication exists. Importing Qt from here would break both.
"""
import json
import os

from gui.services.profiles import installed_data_root

# What the Settings page offers. 100 is "off"; above 200 the window stops
# fitting on the display it is meant to help with.
SCALES = (1.0, 1.25, 1.5, 2.0)
ENV = "QT_SCALE_FACTOR"


def path():
    return os.path.join(installed_data_root(), "ui.json")


def read():
    try:
        with open(path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def scale():
    """The stored interface size, or 1.0. Anything not on the list is ignored
    rather than honoured: a hand-edited 8.0 would open a window with one
    button in it and no way back to this setting."""
    value = read().get("scale")
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 1.0
    return value if value in SCALES else 1.0


def set_scale(value):
    data = read()
    data["scale"] = float(value)
    target = path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = target + ".incoming"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, target)


def apply_scale_env():
    """Put the stored size into the environment Qt reads at startup.

    Called before any Qt import. An explicit QT_SCALE_FACTOR from the shell
    wins - someone debugging a display problem set it on purpose, and the
    relaunch after a change passes it down the same way.
    """
    if os.environ.get(ENV):
        return
    value = scale()
    if value != 1.0:
        os.environ[ENV] = str(value)
