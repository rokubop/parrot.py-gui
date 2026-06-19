"""Central theme definitions and application.

A theme is a flat dict of colors/metrics consumed two ways:
  * UI chrome  — turned into a Qt stylesheet + palette applied to the app.
  * Plots      — read directly by the pyqtgraph widgets (background, waveform
                 pen/fill, detection tint, playhead).

Widgets read the active theme via ``colors()``; the main window switches
themes live via ``apply()``.
"""
from string import Template
from PyQt6.QtGui import QPalette, QColor, QFont


THEMES = {
    "studio_dark": {
        "name": "Studio Dark",
        "font": "Segoe UI",
        "window": "#1e1e1e",
        "base": "#1a1a1a",
        "panel": "#252525",
        "card": "#222222",
        "toolbar": "#252525",
        "text": "#dddddd",
        "text_dim": "#888888",
        "text_bright": "#ffffff",
        "accent": "#4285f4",
        "accent_text": "#ffffff",
        "border": "#3a3a3a",
        "button": "#353535",
        "button_hover": "#404040",
        "radius": "6px",
        # plot colors
        "plot_bg": "#1e1e1e",
        "wave": (120, 200, 255),
        "wave_fill": (90, 170, 230, 120),
        "detect_brush": (0, 200, 0, 60),
        "detect_pen": (0, 200, 0, 110),
        "playhead": (255, 220, 60),
        "grid_alpha": 0.2,
    },
    "fabfilter": {
        "name": "FabFilter",
        "font": "Segoe UI",
        "window": "#23272e",
        "base": "#15181c",
        "panel": "#2d323b",
        # glossy gradient cards/toolbar for the polished plugin-panel feel
        "card": "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #363c46, stop:1 #2b303a)",
        "toolbar": "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2f343d, stop:1 #262a31)",
        "text": "#d8dde3",
        "text_dim": "#8b939d",
        "text_bright": "#ffffff",
        "accent": "#41d97f",
        "accent_text": "#0c1f14",
        "border": "#3c424c",
        "button": "#363c46",
        "button_hover": "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #444b57, stop:1 #383e49)",
        "radius": "5px",
        # plot colors — glowing green curve on a dark analyzer, blue detection
        "plot_bg": "#15181c",
        "wave": (90, 230, 150),
        "wave_fill": (70, 215, 135, 60),
        "detect_brush": (90, 175, 245, 50),
        "detect_pen": (90, 175, 245, 120),
        "playhead": (255, 255, 255),
        "grid_alpha": 0.18,
    },
    "audio_console": {
        "name": "Audio Console",
        "font": "Consolas",
        "window": "#0d0f12",
        "base": "#0a0c0e",
        "panel": "#12161a",
        "card": "#12161a",
        "toolbar": "#0a0c0e",
        "text": "#c8d0d0",
        "text_dim": "#6a7a7a",
        "text_bright": "#eafff7",
        "accent": "#1ed79f",
        "accent_text": "#04120c",
        "border": "#1f2a2a",
        "button": "#16201f",
        "button_hover": "#1d2b29",
        "radius": "3px",
        # plot colors
        "plot_bg": "#0a0d10",
        "wave": (40, 220, 150),
        "wave_fill": (30, 200, 140, 90),
        "detect_brush": (255, 170, 40, 45),
        "detect_pen": (255, 170, 40, 110),
        "playhead": (230, 255, 245),
        "grid_alpha": 0.28,
    },
}

_current = "fabfilter"


def names():
    return list(THEMES.keys())


def current_name():
    return _current


def colors():
    return THEMES[_current]


_STYLESHEET = Template("""
    * { font-size: 13px; }
    QMainWindow, QWidget { background-color: $window; color: $text; }
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
    }
    QListWidget::item, QTreeWidget::item { padding: 4px 2px; }
    QListWidget::item:selected, QTreeWidget::item:selected {
        background-color: $accent; color: $accent_text;
    }
    QTableWidget { gridline-color: $border; border: none; font-size: 12px; background-color: $base; }
    QHeaderView::section {
        background-color: $toolbar; color: $text_dim; border: none;
        border-bottom: 1px solid $border; padding: 6px 8px; font-weight: bold;
    }
    QTextEdit { border: 1px solid $border; border-radius: $radius; padding: 4px; background-color: $base; }
    QLineEdit, QComboBox, QSpinBox {
        padding: 5px 8px; border: 1px solid $border; border-radius: $radius; background-color: $base;
    }
    QComboBox QAbstractItemView { background-color: $base; selection-background-color: $accent; }
    QScrollBar:vertical { background-color: $window; width: 12px; border: none; }
    QScrollBar::handle:vertical { background-color: $border; border-radius: 5px; min-height: 20px; }
    QScrollBar::handle:vertical:hover { background-color: $accent; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
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
