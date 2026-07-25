"""Bootstrap a Talon parrot setup when parts of it don't exist yet.

Closes the "get parrot_integration.py from the #beta channel on slack" gap:
the GUI can install a complete working integration folder into the Talon
user directory - integration file (shipped template), a trained model, and a
patterns.json (empty or scaffolded with one starter pattern per model sound).

Never overwrites an existing integration or patterns.json - these functions
create, the editor manages.
"""
import os
import re
import shutil

from gui.services import patterns_store

INTEGRATION_TEMPLATE = "parrot_integration_template.py"
DEFAULT_SUBFOLDER = "parrot"     # <talon_user>/parrot/

# Labels that are background/noise classes, not triggerable sounds
_NON_TRIGGER = {"background", "silence", "noise"}


def template_path():
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(here, "talon_companion", INTEGRATION_TEMPLATE)


def _pattern_name(sound):
    name = re.sub(r"[^a-z0-9]+", "_", sound.lower()).strip("_")
    return name or "sound"


def scaffold_patterns(model_sounds):
    """One conservative starter pattern per triggerable model sound.
    Thresholds err strict (high probability) - the editor + live view are
    how users tune down from safe, not up from noisy."""
    patterns = {}
    for sound in model_sounds or []:
        if sound.lower() in _NON_TRIGGER:
            continue
        name = _pattern_name(sound)
        counter = 2
        while name in patterns:
            name = f"{_pattern_name(sound)}_{counter}"
            counter += 1
        patterns[name] = {
            "sounds": [sound],
            "threshold": {">power": 10, ">probability": 0.95},
            "throttle": {name: 0.15},
        }
    return patterns


def create_patterns_file(path, patterns=None):
    """Create a patterns.json that doesn't exist yet."""
    if os.path.exists(path):
        raise patterns_store.PatternsError(f"{path} already exists")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    patterns_store.save_patterns(path, patterns or {}, snapshot_first=False)
    return path


def install_integration(talon_user_dir, model_source, subfolder=DEFAULT_SUBFOLDER,
                        patterns=None):
    """Create <talon_user>/<subfolder>/ with parrot_integration.py (template,
    PARROT_HOME rewritten to match), model.pkl and patterns.json.
    Returns {"integration": path, "model": path, "patterns": path}.
    Talon loads the integration as soon as the file lands."""
    if not os.path.isfile(model_source):
        raise OSError(f"Model file not found: {model_source}")
    dest_dir = os.path.join(talon_user_dir, subfolder)
    integration_dest = os.path.join(dest_dir, "parrot_integration.py")
    if os.path.exists(integration_dest):
        raise OSError(f"{integration_dest} already exists - refusing to overwrite")

    with open(template_path(), "r", encoding="utf-8") as f:
        source = f.read()
    subpath = f"user/{subfolder}".replace("\\", "/")
    source, count = re.subn(
        r"^PARROT_HOME\s*=\s*TALON_HOME\s*/\s*['\"][^'\"]+['\"]",
        f"PARROT_HOME = TALON_HOME / '{subpath}'",
        source, count=1, flags=re.MULTILINE)
    if count != 1:
        raise OSError("Integration template is missing its PARROT_HOME line")

    os.makedirs(dest_dir, exist_ok=True)
    model_dest = os.path.join(dest_dir, "model.pkl")
    patterns_dest = os.path.join(dest_dir, "patterns.json")
    shutil.copy2(model_source, model_dest)
    if not os.path.exists(patterns_dest):
        patterns_store.save_patterns(patterns_dest, patterns or {},
                                     snapshot_first=False)
    # The integration lands LAST: when Talon loads it, everything it
    # references already exists.
    with open(integration_dest, "w", encoding="utf-8") as f:
        f.write(source)
    return {"integration": integration_dest, "model": model_dest,
            "patterns": patterns_dest}
