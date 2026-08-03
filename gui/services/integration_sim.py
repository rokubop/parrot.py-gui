"""Dev-only: the states a working machine cannot reach.

No Talon, no integration, no patterns, a stale bridge, Talon asleep. Each has
its own screen, and none of them show up on the machine they get written on.

Doctors the discovery bundle in memory. Writes nothing, so a simulation cannot
outlive the app. Debug builds only, from the page's ... menu.
"""
import copy
import os

from gui.services import profiles

# name -> what it changes about a bundle. Order is the order they appear in.
STATES = (
    ("off", "Real state"),
    ("no_talon", "Talon not installed"),
    ("no_integration", "Talon, no parrot integration"),
    ("no_patterns_file", "Integration, no patterns.json"),
    ("empty_patterns", "patterns.json with nothing in it"),
    ("model_mismatch", "Talon running an unknown model"),
)

BRIDGE_STATES = (
    ("off", "Real bridge state"),
    ("missing", "Bridge not installed"),
    ("outdated", "Bridge out of date"),
    ("installed", "Bridge installed"),
)

TALON_STATES = (
    ("off", "Real Talon state"),
    ("closed", "Talon not running"),
    ("asleep", "Talon asleep"),
    ("awake", "Talon awake, nothing firing"),
)


def enabled():
    return profiles.debug_enabled()


def apply_to_bundle(bundle, state):
    """A copy of the discovery bundle as it would look in ``state``."""
    if state in (None, "off") or not bundle:
        return bundle
    out = dict(bundle)
    result = copy.copy(out.get("result"))
    if result is None:
        return bundle

    if state == "no_talon":
        result.talon_found = False
        result.talon_home = None
        result.talon_user_dir = None
        result.integration_path = None
        result.pattern_path_from_talon = None
        result.model_path_from_talon = None
        result.patterns = {}
        out["local_match"] = None
        out["model_sounds"] = None
    elif state == "no_integration":
        result.integration_path = None
        result.pattern_path_from_talon = None
        result.model_path_from_talon = None
        result.patterns = {}
        out["local_match"] = None
        out["model_sounds"] = None
    elif state == "no_patterns_file":
        result.pattern_path_from_talon = None
        # A path that cannot exist, or the real patterns.json sitting next to
        # the integration makes "missing" false and this state unreachable.
        result.intended_pattern_path = os.path.join(
            os.path.dirname(result.integration_path or ""),
            "simulated-missing", "patterns.json")
        result.patterns = {}
    elif state == "empty_patterns":
        result.patterns = {}
    elif state == "model_mismatch":
        out["local_match"] = None

    out["result"] = result
    return out


def apply_to_bridge(status, state):
    if state in (None, "off") or status is None:
        return status
    out = dict(status)
    if state == "missing":
        out.update(installed=False, installed_version=None, outdated=False)
    elif state == "outdated":
        out.update(installed=True, installed_version="0.0.1", outdated=True)
    elif state == "installed":
        out.update(installed=True,
                   installed_version=out.get("available_version") or "0.2.0",
                   outdated=False)
    return out


def fake_frames(patterns_json, ts):
    """One detection, as the bridge would have sent it."""
    names = list(patterns_json or {})
    if not names:
        return []
    hot = names[0]
    hot_sounds = (patterns_json[hot] or {}).get("sounds") or [hot]
    other = names[1] if len(names) > 1 else hot
    other_sounds = (patterns_json[other] or {}).get("sounds") or [other]

    plan = [(0.02, 0.05, [], []), (0.04, 0.20, [], []),
            (8.10, 0.72, [], []), (11.00, 0.96, [], []),
            (12.40, 0.99, [hot], []), (11.90, 0.99, [], [hot]),
            (7.40, 0.51, [], []), (3.00, 0.20, [], []),
            (0.40, 0.02, [], [])]
    out = []
    for i, (power, probability, active, throttled) in enumerate(plan):
        classes = {s: probability / len(hot_sounds) for s in hot_sounds}
        classes.update({s: max(0.0, 0.35 - probability / 3) / len(other_sounds)
                        for s in other_sounds})
        out.append({"t": "frame", "ts": ts + i * 0.015,
                    "power": power, "f0": 268.0, "f1": 720.0, "f2": 1480.0,
                    "classes": classes, "active": list(active),
                    "throttled": list(throttled), "grace": []})
    return out
