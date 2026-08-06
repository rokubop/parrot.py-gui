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
        # Selected rows. Deliberately translucent rather than a flat colour, so
        # it reads the same over the list's $base and over a gradient card, and
        # so whatever the row itself is coloured survives underneath it.
        "selection": "rgba(65, 217, 127, 0.22)",
        "border": "#5b6372",
        "button": "#4c5462",
        "button_hover": "#5c6577",
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
QUANTITY_COLORS = {
    "Not enough": "#e05a5a",
    "Sufficient": "#e0b020",
    "Good": "#5ac8e0",
    "Excellent": "#41d97f",
}


def names():
    return list(THEMES.keys())


def current_name():
    return _current


def colors():
    return THEMES[_current]


_STYLESHEET = Template("""
    * { font-size: 13px; }
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
        background-color: $button; border: 1px solid $border; color: $text;
    }
    QPushButton:hover { background-color: $button_hover; }
    QPushButton:checked { background-color: $accent; color: $accent_text; border-color: $accent; }
    QGroupBox {
        font-weight: bold; border: 1px solid $border; border-radius: $radius;
        margin-top: 12px; padding: 16px 12px 12px 12px;
    }
    QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: $text_dim; }
    QListWidget, QTreeWidget {
        border: 1px solid $border; border-radius: $radius;
        background-color: $base; font-size: 12px;
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
    /* No ::indicator rules on purpose. Styling any indicator property makes Qt
       take the stylesheet path for the whole thing, and a stylesheet indicator
       draws no tick unless given an image - which is how this ended up a plain
       green square with nothing in it. Fusion draws a proper checkbox with a
       proper tick, and now that selection is a tint it stays legible on a
       selected row, which is the only reason it was overridden. */
    QTableWidget { gridline-color: $border; border: none; font-size: 12px; background-color: $base; }
    QHeaderView::section {
        background-color: $toolbar; color: $text_dim; border: none;
        border-bottom: 1px solid $border; padding: 6px 8px; font-weight: bold;
    }
    QTextEdit { border: 1px solid $border; border-radius: $radius; padding: 4px; background-color: $base; }
    /* QAbstractSpinBox, not QSpinBox: a QSS selector matches by real
       inheritance, and QDoubleSpinBox is not a QSpinBox - with the narrower
       selector every double-spinner in the app rendered stock Fusion. */
    QLineEdit, QComboBox, QAbstractSpinBox {
        padding: 5px 8px; border: 1px solid $border; border-radius: $radius; background-color: $base;
    }
    QComboBox QAbstractItemView { background-color: $base; selection-background-color: $accent; }
    QScrollBar:vertical { background-color: $window; width: 12px; border: none; }
    QScrollBar::handle:vertical { background-color: $border; border-radius: 5px; min-height: 20px; }
    QScrollBar::handle:vertical:hover { background-color: $accent; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
    QScrollBar:horizontal { background-color: $window; height: 12px; border: none; }
    QScrollBar::handle:horizontal { background-color: $border; border-radius: 5px; min-width: 24px; }
    QScrollBar::handle:horizontal:hover { background-color: $accent; }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
    QStatusBar { background-color: $toolbar; color: $text_dim; border-top: 1px solid $border; font-size: 12px; }
    QSlider::groove:horizontal { height: 4px; background: $border; border-radius: 2px; }
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
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(t["text_dim"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(t["text_dim"]))
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
    app.setStyleSheet(_STYLESHEET.substitute(t))
