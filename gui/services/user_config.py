"""Read/write user-overridable settings.

``config/config.py`` ends with ``from data.code.config import *``, so anything
assigned in ``data/code/config.py`` overrides ``lib/default_config.py``. This
module manages that file as a set of simple ``KEY = <repr>`` lines so the
Settings page can persist choices. Values that the app reads only at import
time take effect on the next launch - the Settings page says so.
"""
import os
import ast

USER_CONFIG_PATH = os.path.join("data", "code", "config.py")

# Keys the Settings page is allowed to manage. Anything else already in the file
# is preserved untouched.
MANAGED_KEYS = (
    "INPUT_DEVICE_INDEX",
    "THRESHOLD_DETECTION",
    "TWO_PASS_DETECTION",
    "CURRENT_DETECTION_STRATEGY",
    "DEFAULT_CLF_FILE",
    "STARTING_MODE",
    "MICROPHONE_SEPARATOR",
)


def read_user_config():
    """Parse ``data/code/config.py`` into a dict of {key: python value}.
    Only simple literal assignments are understood; anything else is ignored
    for reading but preserved on write."""
    values = {}
    if not os.path.isfile(USER_CONFIG_PATH):
        return values
    try:
        with open(USER_CONFIG_PATH, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError):
        return values
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                pass
    return values


def write_user_config(updates):
    """Merge ``updates`` (dict of key -> value) into the user config file,
    preserving any unmanaged lines. Rewrites managed keys with repr()."""
    os.makedirs(os.path.dirname(USER_CONFIG_PATH), exist_ok=True)

    # Preserve existing non-assignment lines and assignments we don't manage.
    preserved = []
    existing = read_user_config()
    if os.path.isfile(USER_CONFIG_PATH):
        with open(USER_CONFIG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                key = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
                if key and (key in MANAGED_KEYS or key in updates):
                    continue  # rewritten below
                if stripped == "" or stripped.startswith("#"):
                    continue
                preserved.append(line.rstrip("\n"))

    merged = dict(existing)
    merged.update(updates)

    lines = list(preserved)
    for key in MANAGED_KEYS:
        if key in merged:
            lines.append(f"{key} = {merged[key]!r}")
    # Any managed-by-caller key not in MANAGED_KEYS (future-proofing).
    for key, value in merged.items():
        if key not in MANAGED_KEYS:
            lines.append(f"{key} = {value!r}")

    with open(USER_CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
