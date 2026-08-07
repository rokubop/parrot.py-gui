import os
import sys
import re
import glob
import json
import filecmp
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

TALON_URL = "https://talonvoice.com/"
TALON_BETA_URL = "https://talon.wiki/Help/beta_talon/"

# Only the beta ships talon.experimental.parrot, and stable Talon fails on it
# in its own log where nothing here can see it. So look for it on disk.
#
# Stable ships the parrot/ folder EMPTY, so the folder existing proves nothing;
# the module file inside it is the check. Talon compiles its Python to .py4.
PARROT_API = os.path.join("talon", "experimental", "parrot", "__init__.py*")


@dataclass
class TalonDiscoveryResult:
    talon_found: bool = False
    talon_home: Optional[str] = None
    # None means couldn't tell, which is not False. Never tell someone their
    # beta is not a beta because we failed to find their site-packages.
    talon_beta: Optional[bool] = None
    talon_user_dir: Optional[str] = None
    integration_path: Optional[str] = None
    model_path_from_talon: Optional[str] = None
    pattern_path_from_talon: Optional[str] = None
    # Paths the integration file *references*, whether or not they exist yet -
    # what a bootstrap flow should create.
    intended_pattern_path: Optional[str] = None
    intended_model_path: Optional[str] = None
    patterns: dict = field(default_factory=dict)
    error: Optional[str] = None


def _is_wsl() -> bool:
    try:
        with open("/proc/version", "r") as f:
            return "microsoft" in f.read().lower()
    except Exception:
        return False


def _get_wsl_windows_appdata() -> Optional[str]:
    """Find Windows AppData from WSL via /mnt/c/Users/<username>/AppData/Roaming."""
    users_dir = "/mnt/c/Users"
    if not os.path.isdir(users_dir):
        return None
    for entry in os.listdir(users_dir):
        if entry in ("Public", "Default", "Default User", "All Users"):
            continue
        candidate = os.path.join(users_dir, entry, "AppData", "Roaming")
        if os.path.isdir(candidate):
            return candidate
    return None


def get_talon_home() -> Optional[str]:
    # Debug override set by the profile switcher: "none" simulates a machine
    # without Talon; any other value stands in for the real ~/.talon.
    override = os.environ.get("PARROT_TALON_HOME")
    if override is not None:
        if override.strip().lower() in ("", "none"):
            return None
        return override if os.path.isdir(override) else None

    candidates = []

    if sys.platform == "win32":
        base = os.environ.get("APPDATA", "")
        candidates.append(os.path.join(base, "talon"))
    else:
        candidates.append(os.path.expanduser("~/.talon"))
        # WSL: also check the Windows filesystem
        if _is_wsl():
            appdata = _get_wsl_windows_appdata()
            if appdata:
                candidates.append(os.path.join(appdata, "talon"))

    for candidate in candidates:
        if os.path.isdir(candidate):
            return candidate
    return None


def get_talon_user_dir() -> Optional[str]:
    talon_home = get_talon_home()
    if talon_home is None:
        return None
    candidate = os.path.join(talon_home, "user")
    return candidate if os.path.isdir(candidate) else None


def find_talon_python(talon_home: str) -> Optional[str]:
    """Talon's own bundled Python, from pyvenv.cfg's `home`. The only pointer
    from ~/.talon back to wherever the app was installed, on every platform."""
    cfg = os.path.join(talon_home or "", ".venv", "pyvenv.cfg")
    try:
        with open(cfg, "r", encoding="utf-8") as f:
            for line in f:
                key, _sep, value = line.partition("=")
                if key.strip() == "home":
                    value = value.strip()
                    return value if os.path.isdir(value) else None
    except OSError:
        return None
    return None


def has_parrot_api(talon_home: str) -> Optional[bool]:
    """The beta check. None if Talon's site-packages was not found at all."""
    python_home = find_talon_python(talon_home)
    if python_home is None:
        return None
    roots = (glob.glob(os.path.join(python_home, "lib", "python*",
                                    "site-packages"))
             + glob.glob(os.path.join(python_home, "Lib", "site-packages")))
    roots = [r for r in roots if os.path.isdir(os.path.join(r, "talon"))]
    if not roots:
        return None
    return any(glob.glob(os.path.join(r, PARROT_API)) for r in roots)


def find_parrot_integration(talon_user_dir: str) -> Optional[str]:
    for p in Path(talon_user_dir).rglob("parrot_integration.py"):
        return str(p)
    return None


def parse_integration_file(integration_path: str) -> dict:
    """Parse parrot_integration.py to extract model_path, pattern_path, and parrot_home.

    Looks for lines like:
        PARROT_HOME = TALON_HOME / 'user/my-parrot-model'
        pattern_path = str(PARROT_HOME / 'patterns.json')
        model_path = str(PARROT_HOME / 'model.pkl')
    """
    result = {"model_path": None, "pattern_path": None, "parrot_home": None}

    try:
        with open(integration_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return result

    talon_home = get_talon_home()
    if talon_home is None:
        return result

    parrot_home_match = re.search(
        r'^\s*PARROT_HOME\s*=\s*TALON_HOME\s*/\s*[\'"]([^\'"]+)[\'"]',
        content, re.MULTILINE
    )
    parrot_home_dir = None
    if parrot_home_match:
        parrot_subpath = parrot_home_match.group(1)
        parrot_home_dir = str(Path(talon_home) / parrot_subpath)
        result["parrot_home"] = parrot_home_dir

    pattern_match = re.search(
        r'^\s*pattern_path\s*=\s*str\(PARROT_HOME\s*/\s*[\'"]([^\'"]+)[\'"]\)',
        content, re.MULTILINE
    )
    if pattern_match and parrot_home_dir:
        result["pattern_path"] = str(Path(parrot_home_dir) / pattern_match.group(1))

    model_match = re.search(
        r'^\s*model_path\s*=\s*str\(PARROT_HOME\s*/\s*[\'"]([^\'"]+)[\'"]\)',
        content, re.MULTILINE
    )
    if model_match and parrot_home_dir:
        result["model_path"] = str(Path(parrot_home_dir) / model_match.group(1))

    # Fallback: direct string assignments
    if result["pattern_path"] is None:
        direct = re.search(r'^\s*pattern_path\s*=\s*[\'"]([^\'"]+)[\'"]', content, re.MULTILINE)
        if direct:
            result["pattern_path"] = direct.group(1)

    if result["model_path"] is None:
        direct = re.search(r'^\s*model_path\s*=\s*[\'"]([^\'"]+)[\'"]', content, re.MULTILINE)
        if direct:
            result["model_path"] = direct.group(1)

    return result


def load_patterns_json(pattern_path: str) -> dict:
    try:
        with open(pattern_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def discover_talon() -> TalonDiscoveryResult:
    """Full Talon discovery pipeline with 3-stage fallback for patterns.json."""
    result = TalonDiscoveryResult()

    talon_home = get_talon_home()
    if talon_home is None:
        result.error = "Talon home directory not found"
        return result

    result.talon_home = talon_home
    result.talon_beta = has_parrot_api(talon_home)

    talon_user_dir = get_talon_user_dir()
    if talon_user_dir is None:
        result.error = "Talon user directory not found"
        return result

    result.talon_user_dir = talon_user_dir

    integration_path = find_parrot_integration(talon_user_dir)
    if integration_path:
        result.integration_path = integration_path
        result.talon_found = True

        parsed = parse_integration_file(integration_path)
        result.model_path_from_talon = parsed["model_path"]
        result.intended_pattern_path = parsed["pattern_path"]
        result.intended_model_path = parsed["model_path"]

        # Stage 1: pattern_path from parsing integration file
        if parsed["pattern_path"] and os.path.isfile(parsed["pattern_path"]):
            result.pattern_path_from_talon = parsed["pattern_path"]
            result.patterns = load_patterns_json(parsed["pattern_path"])
            return result

    # Stage 2: common location <talon_home>/parrot/patterns.json
    common_path = os.path.join(talon_home, "parrot", "patterns.json")
    if os.path.isfile(common_path):
        result.talon_found = True
        result.pattern_path_from_talon = common_path
        result.patterns = load_patterns_json(common_path)
        return result

    # Stage 3: rglob in user directory
    if talon_user_dir:
        matches = list(Path(talon_user_dir).rglob("patterns.json"))
        if matches:
            result.talon_found = True
            result.pattern_path_from_talon = str(matches[0])
            result.patterns = load_patterns_json(str(matches[0]))
            return result

    if not result.talon_found:
        result.error = "No parrot integration or patterns.json found"

    return result


def find_matching_local_model(talon_model_path: str, classifier_folder: str) -> Optional[str]:
    """Which local model (by name) is byte-identical to the model Talon uses?
    Returns the model name (pkl basename without extension) or None."""
    if not talon_model_path or not os.path.isfile(talon_model_path):
        return None
    if not os.path.isdir(classifier_folder):
        return None
    talon_size = os.path.getsize(talon_model_path)
    for name in sorted(os.listdir(classifier_folder)):
        if not name.endswith(".pkl"):
            continue
        local = os.path.join(classifier_folder, name)
        try:
            if os.path.getsize(local) == talon_size and \
                    filecmp.cmp(local, talon_model_path, shallow=False):
                return name[:-4]
        except OSError:
            continue
    return None


def load_model_sounds(model_path: str) -> Optional[list]:
    """The class labels the deployed model can produce (joblib pkl), or None.
    Heavy (unpickles the model) - call it off the UI thread."""
    if not model_path or not os.path.isfile(model_path):
        return None
    try:
        import joblib
        model = joblib.load(model_path)
        if hasattr(model, "classes_"):
            return [str(c) for c in model.classes_]
    except Exception:
        return None
    return None


def compare_model_files(local_path: str, talon_path: str) -> dict:
    """Compare a local model file to the one referenced by Talon."""
    result = {
        "matches": False,
        "talon_path": talon_path,
        "local_exists": os.path.isfile(local_path),
        "talon_exists": os.path.isfile(talon_path) if talon_path else False,
    }

    if result["local_exists"] and result["talon_exists"]:
        result["local_size"] = os.path.getsize(local_path)
        result["talon_size"] = os.path.getsize(talon_path)
        if result["local_size"] == result["talon_size"]:
            result["matches"] = filecmp.cmp(local_path, talon_path, shallow=False)

    return result
