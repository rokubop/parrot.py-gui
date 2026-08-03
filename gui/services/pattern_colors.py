"""One colour per pattern, the same colour everywhere.

talon-parrot-tester's palette and rule (ui/colors.py): by position in
patterns.json, wrapping after 20. Copied, not re-picked, so a pattern keeps the
colour you already know it by.
"""

PALETTE = (
    "#00FF88", "#FFA500", "#00CFFF", "#FF5C5C", "#FFD700",
    "#A75CFF", "#33FF57", "#66B2FF", "#FF66CC", "#80FF00",
    "#FFC573", "#FF0000", "#94EDFF", "#FFB3FF", "#DDB000",
    "#99FF99", "#00FFFF", "#CC66FF", "#FF9999", "#00B2AF",
)

UNKNOWN = "#FFFFFF"


def color_at(index):
    return PALETTE[index % len(PALETTE)]


def colors_for(patterns_json):
    """{pattern name: colour} in file order."""
    return {name: color_at(i)
            for i, name in enumerate(patterns_json or {})}


def color_for(name, patterns_json):
    return colors_for(patterns_json).get(name, UNKNOWN)
