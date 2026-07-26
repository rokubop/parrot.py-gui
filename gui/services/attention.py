"""Dashboard attention items - the relationships counts hide.

Only checks not already voiced elsewhere on Home: the model panel warns
about recordings newer than the model and about sounds it doesn't know,
so those are deliberately absent here. Every check returns [] when all is
well and is exception-guarded so a surprise on disk never breaks Home.

Model sound lists are read through ``model_sounds_of`` - Home's async
cache - because unpickling a model is too slow for the UI thread. A miss
just skips the check; the cache fill triggers another refresh.
"""
import os

from config.config import CLASSIFIER_FOLDER
from gui.services.talon_discovery import find_matching_local_model

THIN_MS = 60_000   # under a minute of audio per sound
FULL_MS = 90_000   # nag only once one sound shows what enough looks like


def compute(app_state, talon, model_sounds_of):
    items = []
    for check in (_thin_sounds, _talon_drift, _pattern_mismatch):
        try:
            items.extend(check(app_state, talon, model_sounds_of))
        except Exception:
            pass
    return items


def _fmt_s(ms):
    return f"{round(ms / 1000)}s"


def _thin_sounds(app_state, talon, model_sounds_of):
    labels = app_state.get_sound_labels()
    if len(labels) < 2:
        return []
    durations = {l: app_state.get_label_duration_ms(l) for l in labels}
    if max(durations.values()) < FULL_MS:
        return []  # everything is short; the 1-2-3 flow owns that story
    thin = sorted((l for l in labels if durations[l] < THIN_MS),
                  key=durations.get)
    if not thin:
        return []
    listed = ", ".join(f"{l} ({_fmt_s(durations[l])})" for l in thin[:4])
    more = "…" if len(thin) > 4 else ""
    return [{"text": f"Thin recordings: {listed}{more}. "
                     "Aim for a minute per sound.",
             "action": "Record more", "tab": "Sounds"}]


def _deployed_name(talon):
    if not talon.model_path_from_talon:
        return None
    return find_matching_local_model(
        talon.model_path_from_talon, CLASSIFIER_FOLDER)


def _newest_local_model(model_names):
    best, best_mtime = None, 0
    for name in model_names:
        pkl = os.path.join(CLASSIFIER_FOLDER, name + ".pkl")
        if os.path.isfile(pkl):
            mtime = os.path.getmtime(pkl)
            if mtime > best_mtime:
                best, best_mtime = name, mtime
    return best


def _talon_drift(app_state, talon, model_sounds_of):
    deployed = _deployed_name(talon)
    if deployed is None:
        return []
    newest = _newest_local_model(app_state.get_model_names())
    if newest is None or newest == deployed:
        return []
    return [{"text": f"Talon is running “{deployed}”; “{newest}” is newer.",
             "action": "Swap in Talon", "tab": "Talon"}]


def _pattern_mismatch(app_state, talon, model_sounds_of):
    deployed = _deployed_name(talon)
    patterns = (talon.patterns.get("patterns", talon.patterns)
                if talon.patterns else {})
    if deployed is None or not patterns:
        return []
    model_sounds = model_sounds_of(deployed)
    if not model_sounds:
        return []  # not read yet (or unreadable); next refresh retries
    referenced = set()
    for cfg in patterns.values():
        sounds = cfg.get("sounds") if isinstance(cfg, dict) else None
        if isinstance(sounds, list):
            referenced.update(s for s in sounds if isinstance(s, str))
    missing = sorted(referenced - set(model_sounds))
    if not missing:
        return []
    listed = ", ".join(missing[:4]) + ("…" if len(missing) > 4 else "")
    return [{"text": f"Patterns listen for {listed}, "
                     f"which “{deployed}” does not know.",
             "action": "Review patterns", "tab": "Talon"}]
