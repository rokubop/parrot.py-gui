"""Central theme definitions and application.

A theme is a flat dict of colors/metrics consumed two ways:
  * UI chrome  - turned into a Qt stylesheet + palette applied to the app.
  * Plots      - read directly by the pyqtgraph widgets (background, waveform
                 pen/fill, detection tint, playhead).

Widgets read the active theme via ``colors()``; the main window switches
themes live via ``apply()``.
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
        # Three tiers of text, and every one of them is measured rather than
        # picked by eye. The surfaces they land on are base #15181c, window
        # #23272e, panel #2d323b and the top of the card gradient #363c46.
        #
        #   token       base   window  panel  card(top)
        #   text        13.7    11.5    9.9    8.5     AAA everywhere
        #   text_dim     7.7     6.5    5.6    4.8     AA everywhere
        #   text_faint   5.0     4.2    3.6    3.1     AA on base only
        #
        # text_dim used to be #8b939d, which measured 4.14 on a panel and 3.57
        # on a card - below AA, and cards are exactly where the app puts its
        # secondary copy. text_faint used to be #5d646e at 2.98 on base, which
        # is not a de-emphasis, it is unreadable.
        "text": "#dde2e8",
        "text_dim": "#a3abb6",
        "text_bright": "#ffffff",
        # For a row that is present but excluded - the training checklist's
        # unticked sounds. Only ever used on `base`, where it clears AA; it is
        # not for panels, and it is not a fourth general-purpose grey.
        "text_faint": "#808995",
        "accent": "#41d97f",
        "accent_text": "#0c1f14",
        # Status colours, measured the same way as the text tiers and against
        # the same worst case - the top of the card gradient, #363c46, which is
        # where most of them are actually printed.
        #
        #   token   card  panel  window  base
        #   ok       6.1    7.0     8.2   9.7
        #   warn     4.9    5.7     6.6   7.8
        #   info     4.7    5.5     6.4   7.6
        #   bad      4.5    5.3     6.1   7.3
        #
        # `bad` was #e06c75, which is 3.47 on a card - and a card is exactly
        # where this app prints "Discovery failed" and "Not found". Lightened
        # along its own hue rather than swapped for a different red.
        "ok": "#41d97f",
        "warn": "#d3a45c",
        "info": "#5ab0f5",
        "bad": "#e78c93",
        # Selected rows. Deliberately translucent rather than a flat colour, so
        # it reads the same over the list's $base and over a gradient card, and
        # so whatever the row itself is coloured survives underneath it.
        "selection": "rgba(65, 217, 127, 0.22)",
        # `selection` pre-composited over `base`, for tables only.
        #
        # A table paints the palette Highlight under the item before
        # ::item:selected lands on top; lists and trees do not. A translucent
        # tint there composites over solid $accent, not over $base, and comes
        # back out the same green - the rule applies and changes nothing.
        #
        # The measured value from a tree, not the arithmetic one (#1f4232), so
        # a selected row is the same pixels in both.
        "selection_opaque": "#1e4332",
        # Two boundary colours, because a border does two different jobs and
        # only one of them is information.
        #
        # `border` groups things: group boxes, card edges, splitters, the line
        # under the toolbar, gridlines. Decorative, and WCAG says so - nothing
        # is unidentifiable without it. 2.1-2.9 against the surfaces it sits on.
        #
        # `control_border` is the edge that says "this is a control you can
        # operate" - text inputs, combos, spinners, buttons, the slider groove,
        # the scrollbar handle, and the check/radio indicators. That is the
        # non-text contrast rule's own example, so it clears 3:1 on every
        # surface: 3.5 card, 4.1 panel, 4.8 window, 5.7 base. It used to be
        # `border` at 2.1-2.9, and an unchecked checkbox drawn from it measured
        # 1.5 - a box you had to already know was there.
        "border": "#5b6372",
        "control_border": "#8a929e",
        "button": "#4c5462",
        "button_hover": "#5c6577",
        # Cards are rounder than controls. A pill is always a half-circle.
        "radius_card": "8px",
        "radius_pill": "9px",
        # Disabled was text_dim on an unchanged button fill, which measured the
        # same as an enabled button and read as one. Sunken and dimmer: the
        # fill drops below the window, and 3.6 of text on it is legible without
        # looking live.
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

# Data-quantity rating colors, dimmest -> best. Shared so a rating means the
# same thing (and looks the same) wherever it appears - the Sounds list, the
# per-sound header, and the training checklist.
#
# All four are printed as text as well as drawn as bars, so all four clear 4.5
# on a card: 4.5, 5.5, 5.7, 6.1. "Not enough" was #e05a5a, which cleared it on
# the Sounds list's dark $base and nowhere else - 3.1 on a card, 4.1 on the
# window, and it is the one rating that has to be read.
QUANTITY_COLORS = {
    "Not enough": "#e98b8b",
    "Sufficient": "#e0b020",
    "Good": "#5ac8e0",
    "Excellent": "#41d97f",
}

# What a pattern's state looks like, wherever it is shown: the live tester's
# rows and legend, the throttle and grace values on a pattern card.
#
# The invariant is "throttled is the same colour in both places", not
# "throttled happens to be warn". A state maps to a token, never to a hex.
PATTERN_STATUS = {
    "detected": "ok",
    "grace_detected": "info",
    "throttled": "warn",
}


def status_color(state):
    """The colour for a pattern state, or None if it is not one of them."""
    token = PATTERN_STATUS.get(state)
    return colors()[token] if token else None

# Type scale. Every size in the app comes from here.
#
#   hero      the Home landing title. One in the app.
#   stat      a big numeric readout: "84%", the live-test sound name.
#   title     what a page or sub-view is about. The largest thing on it.
#   section   a titled region, an empty state, a dialog's question.
#   card      a heading inside a card or panel.
#   eyebrow   the dim label naming the value under it.
#   body      running copy, and the floor.
#
# Two rules. Nothing below `body`: the contrast tiers above assume normal-size
# text, and interface size is a uniform QT_SCALE_FACTOR that never rescues the
# small end. And steps of two, because at a one pixel gap a heading reads as
# body copy rendered wrong.
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
    /* Was indistinguishable from an enabled button: the palette dimmed the
       label to $text_dim and left the fill alone. */
    QPushButton:disabled {
        background-color: $disabled_bg; color: $disabled_text;
        border-color: $border;
    }
    QGroupBox {
        font-weight: bold; border: 1px solid $border; border-radius: $radius;
        margin-top: 12px; padding: 16px 12px 12px 12px;
    }
    QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: $text_dim; }
    QListWidget, QTreeWidget {
        border: 1px solid $border; border-radius: $radius;
        background-color: $base;
        /* Kills the focus rectangle the style draws around the *current cell*.
           It was always there; a solid selection fill was opaque enough to hide
           it, and a tint is not - so clicking a row lit one cell a shade
           brighter than the rest of it, which reads as "this cell is special"
           in a table where cells are not selectable. */
        outline: none;
    }
    QListWidget::item, QTreeWidget::item { padding: 4px 2px; }
    /* Selection is a tint, not a fill.
       It used to be solid $accent with $accent_text on top, which on a list of
       checkable rows fought everything in the row: a green row under a green
       tick box, and any colour the row used to mean something (a rating, a
       warning) repainted to near-black. A tint keeps the row's own colours
       readable and still reads as selected. It also removes the reason the
       indicator had to be restyled at all - see below. */
    QListWidget::item:selected, QTreeWidget::item:selected {
        background-color: $selection; color: $text_bright;
    }
    /* Still no ::indicator rules, and still for the same reason: styling any
       indicator property makes Qt take the stylesheet path for the whole
       thing, and a stylesheet indicator draws no tick unless given an image.
       Fusion's own checkbox is drawn instead - but its box is derived from the
       palette and came out at 1.5:1 against the window, so indicator_style.py
       paints that one primitive over the top. See its docstring. */
    /* Same treatment as the lists above, which tables had none of. Without an
       ::item:selected rule a selected row falls through to the palette's
       Highlight, which is solid $accent.

       $selection_opaque, not $selection: see its comment.

       Gridlines stay. These tables are read across as well as down. */
    QTableWidget {
        gridline-color: $border; border: 1px solid $border;
        border-radius: $radius; background-color: $base;
        outline: none;
    }
    QTableWidget::item { padding: 4px 2px; }
    QTableWidget::item:selected {
        background-color: $selection_opaque; color: $text_bright;
    }
    QHeaderView::section {
        background-color: $toolbar; color: $text_dim; border: none;
        border-bottom: 1px solid $border; padding: 6px 8px; font-weight: bold;
    }
    QTextEdit { border: 1px solid $border; border-radius: $radius; padding: 4px; background-color: $base; }
    /* QAbstractSpinBox, not QSpinBox: a QSS selector matches by real
       inheritance, and QDoubleSpinBox is not a QSpinBox - with the narrower
       selector every double-spinner in the app rendered stock Fusion. */
    QLineEdit, QComboBox, QAbstractSpinBox {
        padding: 5px 8px; border: 1px solid $control_border; border-radius: $radius; background-color: $base;
    }
    QLineEdit:disabled, QComboBox:disabled, QAbstractSpinBox:disabled {
        color: $disabled_text; border-color: $border;
    }
    QComboBox QAbstractItemView { background-color: $base; selection-background-color: $accent; }
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
    QSlider::groove:horizontal { height: 4px; background: $control_border; border-radius: 2px; }
    QSlider::handle:horizontal { background: $accent; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }
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
    # Disabled used to be text_dim, which is the colour of live secondary copy
    # everywhere else in the app - so "off" and "quiet" looked identical.
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
    # The type scale goes in as $fs_<rank>, so the stylesheet states the
    # floor from the same table everything else reads.
    subs = dict(t, **{f"fs_{k}": v for k, v in TYPE_SCALE.items()})
    app.setStyleSheet(_STYLESHEET.substitute(subs))
