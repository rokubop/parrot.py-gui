"""Validation for Talon patterns.json files.

The schema authority is the user's own ``parrot_integration.py`` — it declares
``possible_keys`` and ``possible_thresholds`` frozensets which we parse out
(`schema_from_integration`). When that fails we fall back to the known sets
from chaosparrot's integration. Unknown-but-present data is never an error on
its own: we are a guest in this file and must not fight a newer integration.

Severities:
- ``error``   — the integration would skip/crash on this pattern (won't save)
- ``warning`` — suspicious but functional (saves, shown with a badge)
"""
import re
from dataclasses import dataclass

# Fallbacks mirroring chaosparrot's parrot_integration.py
KNOWN_KEYS = frozenset(
    ["sounds", "detect_after", "threshold", "graceperiod", "grace_threshold", "throttle"])
KNOWN_THRESHOLD_OPS = frozenset(
    [f"{op}{field}" for op in (">", "<")
     for field in ("power", "f0", "f1", "f2", "probability", "ratio")])


@dataclass
class Issue:
    severity: str   # "error" | "warning"
    pattern: str    # pattern name, or "" for file-level issues
    field: str      # e.g. "threshold.>power"
    message: str

    def __str__(self):
        where = f"{self.pattern}: " if self.pattern else ""
        return f"[{self.severity}] {where}{self.field} — {self.message}"


def schema_from_integration(integration_path):
    """Parse possible_keys / possible_thresholds from the integration file.
    Returns {"keys": frozenset, "threshold_ops": frozenset} with fallbacks
    filled in for anything that can't be parsed."""
    keys, ops = None, None
    try:
        with open(integration_path, "r", encoding="utf-8") as f:
            content = f.read()
        keys_m = re.search(r"possible_keys\s*=\s*frozenset\(\[([^\]]*)\]\)", content)
        if keys_m:
            keys = frozenset(re.findall(r"['\"]([^'\"]+)['\"]", keys_m.group(1)))
        ops_m = re.search(r"possible_thresholds\s*=\s*frozenset\(\[([^\]]*)\]\)", content)
        if ops_m:
            ops = frozenset(re.findall(r"['\"]([^'\"]+)['\"]", ops_m.group(1)))
    except Exception:
        pass
    return {"keys": keys or KNOWN_KEYS, "threshold_ops": ops or KNOWN_THRESHOLD_OPS}


def default_schema():
    return {"keys": KNOWN_KEYS, "threshold_ops": KNOWN_THRESHOLD_OPS}


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_threshold_dict(name, field, value, schema, issues):
    if not isinstance(value, dict):
        issues.append(Issue("error", name, field, "must be an object of threshold rules"))
        return
    for op, num in value.items():
        f = f"{field}.{op}"
        if op not in schema["threshold_ops"]:
            issues.append(Issue("warning", name, f,
                                "unknown threshold key — the integration will ignore it"))
        if not _is_number(num):
            issues.append(Issue("error", name, f, "threshold values must be numbers"))
            continue
        if op.endswith("probability") and not (0 < num <= 1):
            issues.append(Issue("error", name, f, "probability must be between 0 and 1"))
        if op.endswith("power") and num < 0:
            issues.append(Issue("warning", name, f, "negative power never matches"))
        if op[1:] in ("f0", "f1", "f2") and not (0 <= num <= 8000):
            issues.append(Issue("warning", name, f, "formant frequency outside 0–8000 Hz"))


def validate(patterns, schema=None, model_sounds=None):
    """Validate a patterns dict. ``model_sounds`` (iterable of labels the
    deployed model can produce) enables referential checks when given.
    Returns a list of Issues, errors first."""
    schema = schema or default_schema()
    issues = []
    if not isinstance(patterns, dict):
        return [Issue("error", "", "", "patterns.json must be a JSON object")]

    pattern_names = set(patterns.keys())
    sound_owners = {}

    for name, pattern in patterns.items():
        if not isinstance(pattern, dict):
            issues.append(Issue("error", name, "", "pattern must be a JSON object"))
            continue

        for key in pattern:
            if key not in schema["keys"]:
                issues.append(Issue("warning", name, key,
                                    "unknown key — the integration will ignore it"))

        sounds = pattern.get("sounds")
        if not isinstance(sounds, list) or not sounds:
            issues.append(Issue("error", name, "sounds",
                                "at least one sound is required — the integration skips this pattern"))
        else:
            for sound in sounds:
                if not isinstance(sound, str):
                    issues.append(Issue("error", name, "sounds", "sounds must be strings"))
                    continue
                sound_owners.setdefault(sound, []).append(name)
                if model_sounds is not None and sound not in model_sounds:
                    issues.append(Issue("error", name, "sounds",
                                        f"'{sound}' is not a sound the deployed model can produce"))

        if "threshold" not in pattern:
            issues.append(Issue("error", name, "threshold",
                                "a threshold is required — the integration crashes without one"))
        else:
            _check_threshold_dict(name, "threshold", pattern["threshold"], schema, issues)
        if "grace_threshold" in pattern:
            _check_threshold_dict(name, "grace_threshold", pattern["grace_threshold"], schema, issues)

        for time_key in ("graceperiod", "detect_after"):
            if time_key in pattern:
                value = pattern[time_key]
                if not _is_number(value) or value < 0:
                    issues.append(Issue("error", name, time_key, "must be a non-negative number of seconds"))
                elif value > 2:
                    issues.append(Issue("warning", name, time_key, "unusually long (> 2 s)"))

        throttle = pattern.get("throttle")
        if throttle is not None:
            if not isinstance(throttle, dict):
                issues.append(Issue("error", name, "throttle", "must be an object of pattern -> seconds"))
            else:
                for target, seconds in throttle.items():
                    f = f"throttle.{target}"
                    if not _is_number(seconds) or seconds < 0:
                        issues.append(Issue("error", name, f, "throttle must be a non-negative number of seconds"))
                    elif seconds > 5:
                        issues.append(Issue("warning", name, f, "unusually long throttle (> 5 s)"))
                    if target not in pattern_names:
                        issues.append(Issue("warning", name, f,
                                            f"'{target}' is not a pattern name — this throttle does nothing"))

    for sound, owners in sound_owners.items():
        if len(owners) > 1:
            issues.append(Issue("warning", owners[0], "sounds",
                                f"'{sound}' is used by multiple patterns ({', '.join(owners)}) — "
                                "fine if intentional (different thresholds)"))

    issues.sort(key=lambda i: (0 if i.severity == "error" else 1, i.pattern, i.field))
    return issues


def has_errors(issues):
    return any(i.severity == "error" for i in issues)
