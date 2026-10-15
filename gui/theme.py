"""Central theme definitions and application.

A theme is a flat dict of colors/metrics consumed two ways:
  * UI chrome  - turned into a Qt stylesheet + palette applied to the app.
  * Plots      - read directly by the pyqtgraph widgets (background, waveform
                 pen/fill, detection tint, playhead).

Widgets read the active theme via ``colors()``; ``apply()`` sets it on the
app once, at startup.
"""
from string import Template
from PyQt6.QtGui import QPalette, QColor, QFont


THEMES = {
    "fabfilter": {
        "name": "FabFilter",
        "font": "Inter",
        "window": "#23272e",
        "base": "#15181c",
        "panel": "#2d323b",
        # glossy gradient cards/toolbar for the polished plugin-panel feel
        "card": "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #363c46, stop:1 #2b303a)",
        "toolbar": "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2f343d, stop:1 #262a31)",
        # Text tiers, contrast measured against base #15181c, window #23272e,
        # panel #2d323b and the top of the card gradient #363c46:
        #
        #   token       base   window  panel  card(top)
        #   text        13.7    11.5    9.9    8.5     AAA everywhere
        #   text_dim     7.7     6.5    5.6    4.8     AA everywhere
        "text": "#dde2e8",
        "text_dim": "#a3abb6",
        "text_bright": "#ffffff",
        "accent": "#41d97f",
        "accent_text": "#0c1f14",
        # Translucent so a selected row reads the same over $base and over a
        # gradient card, and the row's own colours survive underneath.
        "selection": "rgba(65, 217, 127, 0.22)",
        # `border` groups things (cards, gridlines) - decorative, 2.1-2.9
        # against its surfaces. `control_border` marks an operable control
        # (buttons, scrollbar handle) and clears the 3:1 non-text contrast rule
        # on every surface: 3.5 card, 4.1 panel, 4.8 window, 5.7 base.
        "border": "#5b6372",
        "control_border": "#8a929e",
        "button": "#4c5462",
        "button_hover": "#5c6577",
        # Cards are rounder than controls.
        "radius_card": "8px",
        # Sunken and dimmer: the fill drops below the window, and 3.6:1 text on
        # it is legible without looking live.
        "disabled_text": "#828a96",
        "disabled_bg": "#2f343c",
        "radius": "5px",
        # plot colors - glowing green curve on a dark analyzer, blue detection
        "plot_bg": "#15181c",
        "wave": (90, 230, 150),
        "wave_fill": (70, 215, 135, 60),
        "detect_brush": (90, 175, 245, 50),
        "detect_pen": (90, 175, 245, 120),
        "playhead": (255, 255, 255),
        "grid_alpha": 0.18,
    },
}

_current = "fabfilter"

# Data-quantity rating colors, dimmest -> best. Shared so a rating looks the
# same wherever it appears. All four are printed as text as well as drawn as
# bars, so all four clear 4.5 on a card: 4.5, 5.5, 5.7, 6.1.
QUANTITY_COLORS = {
    "Not enough": "#e98b8b",
    "Sufficient": "#e0b020",
    "Good": "#5ac8e0",
    "Excellent": "#41d97f",
}

# Type scale. Every size in the app comes from here.
#
#   hero      the Home landing title. One in the app.
#   stat      a big numeric readout: "84%".
#   title     what a page or sub-view is about. The largest thing on it.
#   section   a titled region, an empty state, a dialog's question.
#   card      a heading inside a card or panel.
#   eyebrow   the dim label naming the value under it.
#   body      running copy, and the floor.
#
# Nothing below `body` (the contrast tiers assume normal-size text), and
# steps of two - at a one pixel gap a heading reads as body copy rendered
# wrong.
TYPE_SCALE = {
    "hero": 28,
    "stat": 26,
    "title": 20,
    "section": 18,
    "card": 16,
    "eyebrow": 14,
    "body": 14,
}


def names():
    return list(THEMES.keys())


def current_name():
    return _current


def colors():
    return THEMES[_current]


_STYLESHEET = Template("""
    * { font-size: ${fs_body}px; }
    QMainWindow, QWidget { background-color: $window; color: $text; }
    /* QWidget rule matches subclasses: without this, every QLabel paints
       an opaque box over gradient panels */
    QLabel { background-color: transparent; }
    QToolBar {
        background-color: $toolbar;
        border-bottom: 1px solid $border;
        spacing: 4px; padding: 4px 8px;
    }
    QToolBar QToolButton {
        color: $text_dim; padding: 6px 16px;
        border-radius: $radius; font-weight: bold;
    }
    QToolBar QToolButton:hover { background-color: $button_hover; color: $text_bright; }
    QToolBar QToolButton:checked { background-color: $accent; color: $accent_text; }
    QPushButton {
        padding: 6px 16px; border-radius: $radius;
        background-color: $button; border: 1px solid $control_border; color: $text;
    }
    QPushButton:hover { background-color: $button_hover; }
    QPushButton:checked { background-color: $accent; color: $accent_text; border-color: $accent; }
    QPushButton:disabled {
        background-color: $disabled_bg; color: $disabled_text;
        border-color: $border;
    }
    QListWidget, QTreeWidget {
        border: 1px solid $border; border-radius: $radius;
        background-color: $base;
        /* Kill the current-cell focus rectangle: a solid selection fill hid
           it, the translucent tint does not. */
        outline: none;
    }
    QListWidget::item, QTreeWidget::item { padding: 4px 2px; }
    /* Selection is a tint, not a fill, so any colour a row uses to mean
       something (a rating, a warning) stays readable while selected. */
    QListWidget::item:selected, QTreeWidget::item:selected {
        background-color: $selection; color: $text_bright;
    }
    QHeaderView::section {
        background-color: $toolbar; color: $text_dim; border: none;
        border-bottom: 1px solid $border; padding: 6px 8px; font-weight: bold;
    }
    /* Handle and groove are $control_border, not $border: they are the part
       you grab, and at $border they sat at 2.5 against the window. */
    QScrollBar:vertical { background-color: $window; width: 12px; border: none; }
    QScrollBar::handle:vertical { background-color: $control_border; border-radius: 5px; min-height: 20px; }
    QScrollBar::handle:vertical:hover { background-color: $accent; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
    QScrollBar:horizontal { background-color: $window; height: 12px; border: none; }
    QScrollBar::handle:horizontal { background-color: $control_border; border-radius: 5px; min-width: 24px; }
    QScrollBar::handle:horizontal:hover { background-color: $accent; }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
    QStatusBar { background-color: $toolbar; color: $text_dim; border-top: 1px solid $border; }
    QSplitter::handle { background-color: $border; }
""")


def _palette(t):
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(t["window"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(t["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(t["base"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(t["panel"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(t["panel"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(t["text"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(t["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(t["button"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(t["text"]))
    palette.setColor(QPalette.ColorRole.Link, QColor(t["accent"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(t["accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(t["accent_text"]))
    # Disabled must not match text_dim, the colour of live secondary copy -
    # or "off" and "quiet" look identical.
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(t["disabled_text"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(t["disabled_text"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(t["disabled_text"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, QColor(t["disabled_bg"]))
    return palette


def apply(app, name):
    """Apply a theme to the whole application."""
    global _current
    if name not in THEMES:
        return
    _current = name
    t = THEMES[name]
    font = QFont(t["font"], 10)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    app.setPalette(_palette(t))
    subs = dict(t, **{f"fs_{k}": v for k, v in TYPE_SCALE.items()})
    app.setStyleSheet(_STYLESHEET.substitute(subs))
