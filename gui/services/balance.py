"""The trainer's dataset balancing, asked for rather than reimplemented.

The rule is `generate_data_balance_strategy_map` in lib/load_data.py, ~134 ms
for 20 sounds. Run it off the UI thread anyway: it walks every .srt on disk.

Terms are chaosparrot's, unchanged - a label is *oversampled*, *undersampled*
or *sampled*. The training log prints those exact words, so the UI keeps them.

Frames, not seconds, are the trainer's unit. Frames times `ms_per_frame` is
~4% off the seconds the Sounds tab shows (sliding windows, trailing partials),
so the table never converts; `frames_as_minutes` is the one exception.
"""
import math

from config.config import RECORD_SECONDS, SLIDING_WINDOW_AMOUNT

# What the trainer would have to reach for a label to carry full weight. A label
# landing under this is under-represented however good its rating looks.
FULL_WEIGHT = 0.95


def ms_per_frame():
    return math.floor(RECORD_SECONDS / SLIDING_WINDOW_AMOUNT * 1000)


def frames_as_minutes(frames):
    """Frames as approximate minutes, for the two "Trained on" lines (setup
    screen and model card) which must read identically.

    Not distinct audio: an oversampled label's frames are counted every time
    the trainer will see them, so this can exceed the minutes recorded.
    """
    minutes = round(frames * ms_per_frame() / 60000)
    return f"~{minutes} minute" + ("" if minutes == 1 else "s")


def loaded_frames(plan):
    """What the trainer will actually be handed, silence included."""
    if not plan:
        return 0
    return (sum(r["loaded"] for r in plan["rows"])
            + (plan.get("silence") or {}).get("loaded", 0))


def plan_for(labels, silence="all", balance_sounds=None):
    """What the trainer will do to each label, as
    {"target": frames, "rows": [...], "counts": {...}, "silence": {...}}.

    A row is {label, strategy, size, loaded, percent, share, short}:
      strategy  one of "oversample" / "undersample" / "sample", the trainer's own
      percent   signed, matching the log line ( +27, -33, 0 )
      share     loaded / target, so 1.0 is full weight
      short     oversampled and still under full weight - the 2x cap bit

    Returns rows in the order given. Raises nothing: a label the trainer has no
    strategy for is skipped, which is what happens to one with no recordings.
    """
    from config.config import BACKGROUND_LABEL
    from lib.load_data import (get_grouped_data_directories,
                               generate_data_balance_strategy_map)
    from lib.srt import count_total_silence_frames

    grouped = get_grouped_data_directories(list(labels))
    strategies = generate_data_balance_strategy_map(grouped, silence,
                                                    balance_sounds)

    rows = []
    target = 0
    for label in labels:
        entry = strategies.get(label)
        if not entry:
            continue
        size = entry["total_size"]
        loaded = entry["total_loaded"]
        target = entry["truncate_after"] or target
        percent = round(loaded / size * 100) - 100 if size else 0
        rows.append({
            "label": label,
            "strategy": entry["strategy"],
            "size": size,
            "loaded": loaded,
            "percent": percent,
            "share": (loaded / target) if target else 0.0,
            "short": entry["strategy"] == "oversample" and bool(target)
                     and loaded < target * FULL_WEIGHT,
        })

    counts = {
        "oversample": sum(1 for r in rows if r["strategy"] == "oversample"),
        "undersample": sum(1 for r in rows if r["strategy"] == "undersample"),
        "sample": sum(1 for r in rows if r["strategy"] == "sample"),
        "short": sum(1 for r in rows if r["short"]),
    }
    # Never in `rows`: no recordings of its own, but usually the biggest class.
    ms = ms_per_frame()
    silence_size = sum(count_total_silence_frames(directory, ms)
                       for dirs in grouped.values() for directory in dirs)
    if silence == "none":
        silence_loaded = 0
    else:
        silence_loaded = strategies.get(BACKGROUND_LABEL, {}).get(
            "total_loaded", silence_size)
    total = sum(r["loaded"] for r in rows) + silence_loaded
    return {"target": target, "rows": rows, "counts": counts,
            "silence": {"size": silence_size, "loaded": silence_loaded,
                        "mode": silence,
                        "share": (silence_loaded / total) if total else 0.0}}
