"""Per-pattern min / average / max over a test session.

talon-parrot-tester's PatternsStats, including what counts as a sample: only
the winning pattern is credited per frame. So "average power" means "how loud
it was while this pattern was winning", not how loud the sound is.

Not session_stats.analyze, which answers what a pattern fired at and what
blocked the near misses, from a recorded file.
"""

METRICS = ("power", "probability", "f0", "f1", "f2")


def _sample(frame):
    winner = frame.winner
    if winner is None:
        return None
    return {
        "power": frame.power,
        "probability": winner["probability"],
        "f0": frame.f0,
        "f1": frame.f1,
        "f2": frame.f2,
    }


def compute(captures, pattern_names=()):
    """{name: {"count", "power": {"min","average","max"}, ...}}.

    Every pattern in ``pattern_names`` appears, count 0, so a pattern that
    never won is visible as a zero rather than as a missing row - that is the
    answer to "why does this one never fire".
    """
    totals = {}

    def bucket(name):
        if name not in totals:
            totals[name] = {"count": 0,
                            **{m: [None, 0.0, None] for m in METRICS}}
        return totals[name]

    for name in pattern_names:
        bucket(name)

    for capture in captures:
        for frame in capture.frames:
            values = _sample(frame)
            if values is None:
                continue
            entry = bucket(frame.winner["name"])
            entry["count"] += 1
            for metric in METRICS:
                value = values[metric]
                if value is None:
                    continue
                low, total, high = entry[metric]
                entry[metric] = [value if low is None else min(low, value),
                                 total + value,
                                 value if high is None else max(high, value)]

    out = {}
    for name, entry in totals.items():
        count = entry["count"]
        row = {"name": name, "count": count}
        for metric in METRICS:
            low, total, high = entry[metric]
            row[metric] = {"min": low or 0.0,
                           "average": total / count if count else 0.0,
                           "max": high or 0.0}
        out[name] = row
    return out


def as_text(row):
    """One pattern's numbers, for the clipboard. Same three-line-per-metric
    shape the tester copies out, so pasted numbers stay comparable."""
    lines = [f"{row['name']} - {row['count']} frames"]
    for metric in METRICS:
        stat = row[metric]
        places = 4 if metric == "probability" else 2
        lines.append(f"  {metric:12} min {stat['min']:.{places}f}   "
                     f"avg {stat['average']:.{places}f}   "
                     f"max {stat['max']:.{places}f}")
    return "\n".join(lines)
