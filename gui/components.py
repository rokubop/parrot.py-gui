"""Shared UI primitives.

Imports nothing from ``windows/`` or ``widgets/``, so anything may import it.

``x_style()`` returns the stylesheet string, ``x()`` builds the widget with it.
Colours and sizes come from ``theme``; nothing here hardcodes a hex or a px.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QFrame, QLabel, QPushButton, QVBoxLayout, QWidget)

from gui import theme


# ---- text ---------------------------------------------------------------

def heading_style(rank="card", color=None):
    """One of the ranks in ``theme.TYPE_SCALE``.

    `eyebrow` sits on the floor, so it carries rank without size: dim, bold,
    tracked. Without the tracking it reads as emphasis, not as a label.
    """
    t = theme.colors()
    size = theme.TYPE_SCALE[rank]
    ink = color or (t["text_dim"] if rank == "eyebrow" else t["text_bright"])
    css = f"font-size: {size}px; font-weight: bold; color: {ink};"
    if rank == "eyebrow":
        css += " letter-spacing: 0.6px;"
    return css


def heading(text, rank="card", color=None, parent=None):
    label = QLabel(text, parent) if parent is not None else QLabel(text)
    label.setStyleSheet(heading_style(rank, color))
    return label


def dim_label(text="", wrap=False):
    """Secondary copy. The single most-retyped line in the GUI."""
    label = QLabel(text)
    label.setWordWrap(wrap)
    label.setStyleSheet(f"color: {theme.colors()['text_dim']};")
    return label


def set_wrapped_text(label, text, width):
    """Set a word-wrapped label's text and the height that copy needs at `width`.

    A word-wrapped QLabel reports a one-line sizeHint, so an unasked layout
    clips it. heightForWidth is -1 before the label has ever held text, and
    setMinimumHeight(-1) is a Qt warning, hence the guard.
    """
    label.setText(text)
    needed = label.heightForWidth(width)
    label.setMinimumHeight(needed if needed > 0 else 0)


# ---- cards --------------------------------------------------------------

def card_style(object_name, surface="panel", children="> QLabel"):
    """A rounded panel with a border.

    Scoped to `object_name`: a selector-less stylesheet on an ancestor silently
    breaks :checked on descendant buttons.

    `children` must declare itself transparent or the global QWidget rule paints
    an opaque box behind each one. Direct children only by default; pass a
    descendant selector when the card nests them deeper.
    """
    t = theme.colors()
    return (f"QFrame#{object_name} {{ background-color: {t[surface]}; "
            f"border: 1px solid {t['border']}; "
            f"border-radius: {t['radius_card']}; }} "
            f"QFrame#{object_name} {children} {{ "
            f"background: transparent; border: none; }}")


CARD_MARGINS = (18, 16, 18, 18)


def card_frame(object_name, surface="panel", children="> QLabel", spacing=8):
    """Returns (frame, layout) with the card style and standard margins on."""
    card = QFrame()
    card.setObjectName(object_name)
    card.setStyleSheet(card_style(object_name, surface, children))
    layout = QVBoxLayout(card)
    layout.setContentsMargins(*CARD_MARGINS)
    layout.setSpacing(spacing)
    return card, layout


# ---- buttons ------------------------------------------------------------

def primary_button_style():
    """Accent-filled call to action. One per screen."""
    t = theme.colors()
    return (f"QPushButton#primaryAction {{ background-color: {t['accent']}; "
            f"color: {t['accent_text']}; font-weight: bold; border: none; "
            f"border-radius: {t['radius']}; padding: 6px 18px; }} "
            f"QPushButton#primaryAction:hover {{ "
            f"background-color: {t['accent']}; }} "
            # Matches the app-wide disabled rule: sunken fill, disabled_text.
            f"QPushButton#primaryAction:disabled {{ "
            f"background-color: {t['disabled_bg']}; "
            f"color: {t['disabled_text']}; }}")


def primary_button(text, slot=None, height=34):
    btn = QPushButton(text)
    btn.setObjectName("primaryAction")
    btn.setMinimumHeight(height)
    btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    btn.setStyleSheet(primary_button_style())
    if slot is not None:
        btn.clicked.connect(slot)
    return btn


def ghost_button_style():
    """Borderless, dim, second-class actions - Rename / Clone / Delete."""
    t = theme.colors()
    return (f"QPushButton#secondaryAction {{ color: {t['text_dim']}; "
            f"border: none; background: transparent; padding: 3px 8px; }} "
            f"QPushButton#secondaryAction:hover {{ color: {t['text_bright']}; }}")


def ghost_button(text, slot=None, tip=None):
    btn = QPushButton(text)
    btn.setObjectName("secondaryAction")
    btn.setFlat(True)
    btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    btn.setStyleSheet(ghost_button_style())
    if tip:
        btn.setToolTip(tip)
    if slot is not None:
        btn.clicked.connect(slot)
    return btn


# ---- empty states -------------------------------------------------------

class EmptyState(QWidget):
    """Centered title / body / action, for a page with nothing to show.

    Build once, re-word with ``set_state``.
    """

    # Measured line length for the body copy. Wider reads as a paragraph.
    BODY_WIDTH = 460

    def __init__(self, title="", body="", button_text=None, slot=None):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(8)

        self.title = heading("", "section")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.title)

        self.body = dim_label("", wrap=True)
        self.body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.setFixedWidth(self.BODY_WIDTH)
        v.addWidget(self.body, 0, Qt.AlignmentFlag.AlignHCenter)

        self.button = primary_button("")
        v.addSpacing(6)
        v.addWidget(self.button, 0, Qt.AlignmentFlag.AlignHCenter)

        self.set_state(title, body, button_text, slot)

    def set_state(self, title, body, button_text=None, slot=None):
        """Re-word in place. Disconnects first, or slots accumulate."""
        self.title.setText(title)
        self.set_body(body)
        try:
            self.button.clicked.disconnect()
        except TypeError:
            pass          # nothing connected yet
        self.button.setText(button_text or "")
        self.button.setVisible(bool(button_text))
        if slot is not None:
            self.button.clicked.connect(slot)

    def set_body(self, text):
        set_wrapped_text(self.body, text, self.BODY_WIDTH)


def center_in(layout, panel):
    """Center `panel` vertically in an otherwise empty container: springs above
    and below, ahead of the container's own trailing stretch."""
    layout.insertStretch(layout.count() - 1)
    layout.insertWidget(layout.count() - 1, panel, 0,
                        Qt.AlignmentFlag.AlignHCenter)
