"""Curated detection-strategy presets.

The segmenter is driven by a strategy string (see lib/stream_processing.py),
e.g. ``auto_dBFS_secondary_dBFS_reject_cont_45ms_repair``. Rather than expose
the raw grammar, the GUI offers a few named presets covering the common cases.
The active default lives in config (``CURRENT_DETECTION_STRATEGY``); a recording
session or re-segmentation may pick a different one.
"""
from config.config import CURRENT_DETECTION_STRATEGY

# (key, label, strategy_string, description)
PRESETS = [
    (
        "balanced",
        "Balanced (default)",
        "auto_dBFS_secondary_dBFS_reject_cont_45ms_repair",
        "Good all-rounder. Rejects very short continuous blips and repairs "
        "missed frames. Best starting point for most sounds.",
    ),
    (
        "rapid",
        "Rapid / discrete",
        "auto_dBFS_secondary_dBFS_reject_cont_45ms_repair",
        "For short, punchy sounds (clicks, pops) recorded back-to-back. Pair "
        "with the 'strict' threshold mode in Settings.",
    ),
    (
        "keep_short",
        "Keep short sounds",
        "auto_dBFS_secondary_dBFS_repair",
        "No minimum-length rejection — keeps even the briefest detections. "
        "Use when valid sounds are being dropped as too short.",
    ),
    (
        "sustained",
        "Sustained / continuous",
        "auto_dBFS_secondary_dBFS_reject_cont_45ms_mend_60ms_repair",
        "For held sounds (vowels, hisses). Mends small gaps so one sound isn't "
        "split into several detections.",
    ),
    (
        "strict_long",
        "Strict (longer minimum)",
        "auto_dBFS_secondary_dBFS_reject_75ms_repair",
        "Rejects anything under ~75 ms. Cuts spurious noise at the cost of "
        "possibly dropping genuinely short sounds.",
    ),
]


def labels():
    return [p[1] for p in PRESETS]


def strategy_for_label(label):
    for _key, lbl, strategy, _desc in PRESETS:
        if lbl == label:
            return strategy
    return CURRENT_DETECTION_STRATEGY


def description_for_label(label):
    for _key, lbl, _strategy, desc in PRESETS:
        if lbl == label:
            return desc
    return ""


def default_label():
    """The preset whose strategy matches the configured default, else the
    first preset."""
    for _key, lbl, strategy, _desc in PRESETS:
        if strategy == CURRENT_DETECTION_STRATEGY:
            return lbl
    return PRESETS[0][1]
