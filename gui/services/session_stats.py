"""Observed per-pattern statistics from a recorded bridge session.

Pure information, no suggestions: what power/probability values a pattern
actually fired at (recorded Talon ground truth, not replay), and how often it
*nearly* fired — probability was there but some rule said no — with the rule
that blocked it. This is what makes threshold numbers meaningful when editing.
"""

NEAR_MISS_PROBABILITY = 0.5


def _percentiles(values):
    """(p10, median, p90) without numpy — sessions are small."""
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)

    def pick(fraction):
        return ordered[min(n - 1, max(0, round(fraction * (n - 1))))]
    return (pick(0.10), pick(0.50), pick(0.90))


def _blocking_rule(frame, config, probability):
    """Which threshold rule fails this frame (first one, threshold order)?
    Returns a rule name, 'throttle/timing' when every rule passes (the block
    came from throttling, detect_after or grace state), or None."""
    thresholds = config.get("threshold") or {}
    sounds = config.get("sounds") or []
    classes = frame.get("classes", {})
    checks = {
        ">probability": lambda t: probability >= t,
        ">power": lambda t: frame.get("power", 0) >= t,
        ">f0": lambda t: frame.get("f0", 0) >= t,
        ">f1": lambda t: frame.get("f1", 0) >= t,
        ">f2": lambda t: frame.get("f2", 0) >= t,
        "<probability": lambda t: probability < t,
        "<power": lambda t: frame.get("power", 0) < t,
        "<f0": lambda t: frame.get("f0", 0) < t,
        "<f1": lambda t: frame.get("f1", 0) < t,
        "<f2": lambda t: frame.get("f2", 0) < t,
        ">ratio": lambda t: len(sounds) > 1 and classes.get(sounds[1], 0) > 0
        and classes.get(sounds[0], 0) / classes.get(sounds[1], 1) >= t,
        "<ratio": lambda t: len(sounds) > 1 and classes.get(sounds[1], 0) > 0
        and classes.get(sounds[0], 0) / classes.get(sounds[1], 1) < t,
    }
    for op, threshold in thresholds.items():
        check = checks.get(op)
        if check is not None and not check(threshold):
            return op
    return "throttle/timing"


def analyze(frames, patterns_json):
    """Per pattern: {"fires", "fired_power", "fired_prob", "fired_f0",
    "near_misses", "blockers": {rule: count}} — all from recorded ground
    truth (the 'active' sets Talon actually produced)."""
    stats = {}
    for name, config in (patterns_json or {}).items():
        if not isinstance(config, dict):
            continue
        sounds = config.get("sounds") or []
        fired_power, fired_prob, fired_f0 = [], [], []
        near_misses = 0
        blockers = {}
        for frame in frames:
            classes = frame.get("classes", {})
            probability = sum(classes.get(sound, 0.0) for sound in sounds)
            if name in frame.get("active", []):
                fired_power.append(frame.get("power", 0.0))
                fired_prob.append(probability)
                fired_f0.append(frame.get("f0", 0.0))
            elif probability >= NEAR_MISS_PROBABILITY:
                near_misses += 1
                rule = _blocking_rule(frame, config, probability)
                blockers[rule] = blockers.get(rule, 0) + 1
        stats[name] = {
            "fires": len(fired_power),
            "fired_power": _percentiles(fired_power),
            "fired_prob": _percentiles(fired_prob),
            "fired_f0": _percentiles(fired_f0),
            "near_misses": near_misses,
            "blockers": dict(sorted(blockers.items(),
                                    key=lambda kv: -kv[1])),
        }
    return stats


def describe(entry):
    """One dim info line for the edit dialog. Returns '' when nothing fired."""
    if not entry:
        return ""
    parts = []
    if entry["fires"]:
        p = entry["fired_power"]
        q = entry["fired_prob"]
        parts.append(f"fired {entry['fires']}× — power {p[0]:.0f}–{p[2]:.0f} "
                     f"(median {p[1]:.0f}), probability {q[0]:.2f}–{q[2]:.2f}")
        f0 = entry["fired_f0"]
        if f0 and f0[1] > 0:
            parts.append(f"f0 median {f0[1]:.0f} Hz")
    if entry["near_misses"]:
        top = next(iter(entry["blockers"]), None)
        top_txt = f", mostly {top}" if top else ""
        parts.append(f"{entry['near_misses']} near-misses "
                     f"(probability ≥ {NEAR_MISS_PROBABILITY}{top_txt})")
    return "Observed in last recorded session: " + "; ".join(parts) if parts else ""
