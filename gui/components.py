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


def link(url, text=None):
    """An anchor, coloured inline.

    A stylesheet on a label makes Qt ignore the palette's Link role, so anchors
    render the default pure blue (1.9:1 on the dark window). Only an inline
    style wins - so copy holding a link is built per call, never a constant.
    """
    return (f"<a href='{url}' style='color: {theme.colors()['accent']};'>"
            f"{text or url}</a>")


def enable_links(label):
    """A QLabel ignores clicks on <a> until told to accept them, so a link
    added to existing copy silently does nothing."""
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextBrowserInteraction)
    label.setOpenExternalLinks(True)
    return label


def painter_font(widget, rank="body"):
    """A font at a scale rank, for text drawn in a paintEvent.

    Stylesheets do not reach QPainter text. Size it in pixels: the stylesheet
    sets the widget font in pixels too, so ``pointSizeF()`` returns -1 and any
    arithmetic on it silently collapses.
    """
    font = widget.font()
    font.setPixelSize(theme.TYPE_SCALE[rank])
    return font


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


# ---- sections -----------------------------------------------------------

SECTION_MARGINS = (18, 16, 18, 16)


def section_card(title, surface="card", spacing=10, layout_cls=QVBoxLayout):
    """A titled section: the title above a filled card, not notched into it.

    `QGroupBox` cuts its title through its own top border, which is the Qt
    Designer default and the one shape in the app that still looks like one.
    Here the title is an eyebrow above the frame - what a settings page is
    expected to look like now, and the same card the rest of the app uses.

    Returns ``(wrapper, layout, restyle)``: add `wrapper` to the page, fill
    `layout`, and call `restyle()` from ``refresh_theme()`` - the card fill and
    the eyebrow are per-widget stylesheets, so the global sheet cannot repaint
    them on a theme switch.
    """
    name = "sec" + "".join(c for c in title.title() if c.isalnum())
    wrapper = QWidget()
    outer = QVBoxLayout(wrapper)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(6)

    label = QLabel(title)
    outer.addWidget(label)

    card = QFrame()
    card.setObjectName(name)
    layout = layout_cls(card)
    layout.setContentsMargins(*SECTION_MARGINS)
    layout.setSpacing(spacing)
    outer.addWidget(card)

    def restyle():
        label.setStyleSheet(heading_style("eyebrow"))
        card.setStyleSheet(card_style(name, surface))

    restyle()
    return wrapper, layout, restyle


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


def set_primary(button, primary=True):
    """Make, or unmake, a button the screen's call to action.

    The accent follows the next thing to do, so a button wears it only while it
    is that thing: Apply once the threshold has moved, Save once there are edits,
    Finish once there is a take. A button that is always green says nothing.

    objectName rather than a dynamic property, because Qt only re-evaluates
    property selectors after unpolish/polish, and that round trip drops other
    state on the way through.
    """
    primary = bool(primary)
    if (button.objectName() == "primaryAction") == primary:
        return      # called on every slider step; restyling is not free
    button.setObjectName("primaryAction" if primary else "")
    button.setStyleSheet(primary_button_style() if primary else "")


def refresh_primary(button):
    """Re-apply the accent after a theme switch, for a button that has it."""
    if button.objectName() == "primaryAction":
        button.setStyleSheet(primary_button_style())


def lock_width(button, *texts, floor=0):
    """Pin a button to one width for every label it will ever show.

    A button whose text changes - Play/Stop, Record/Pause/Resume - is otherwise
    re-measured on each click, and every button to its right jumps sideways at
    the moment you press it.

    Two traps make the obvious fixes not work:

    * ``setMinimumWidth`` stops a button shrinking, not growing, so a wider
      label still shoves the row along.
    * Measuring ``sizeHint`` per label does nothing: QPushButton caches it, and
      the cache does not always drop on ``setText``, so every label comes back
      the same width.

    ``floor`` sets a comfortable minimum for a button worth hitting quickly, and
    covers any label whose glyphs paint wider than they measure.
    """
    fm = button.fontMetrics()
    # Padding/border come from the stylesheet, so read them off rather than
    # hard-coding: the hint for the label it already has, less that label.
    chrome = max(0, button.sizeHint().width() - fm.horizontalAdvance(button.text()))
    widest = max(fm.horizontalAdvance(t) for t in texts) if texts else 0
    button.setFixedWidth(max(widest + chrome, floor))
    return button


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


# ---- badges -------------------------------------------------------------

def badge_style(tone="accent", outlined=True):
    """A small pill stating a fact about the thing beside it.

    `tone` is a theme colour key, so a badge stays on the measured palette.
    """
    t = theme.colors()
    css = (f"color: {t[tone]}; font-size: {theme.TYPE_SCALE['eyebrow']}px; "
           f"font-weight: bold;")
    if outlined:
        css += (f" border: 1px solid {t[tone]}; "
                f"border-radius: {t['radius_pill']}; padding: 2px 10px;")
    return css


def section_label(text, color=None):
    """An eyebrow with a rule under it. The lowercase file keys."""
    t = theme.colors()
    label = QLabel(text)
    label.setStyleSheet(
        heading_style("eyebrow", color)
        + f" border-bottom: 1px solid {t['border']}; padding-bottom: 3px;")
    return label


def badge(text, tone="accent", outlined=True, tip=None):
    label = QLabel(text)
    label.setStyleSheet(badge_style(tone, outlined))
    if tip:
        label.setToolTip(tip)
    return label


# ---- tables -------------------------------------------------------------

def style_table(table, *, stretch=None, single=True, fit=True):
    """Row selection, no editing, no row numbers. Every table wants this.

    `stretch` takes the leftover width, the rest size to contents. `fit=False`
    stretches every column evenly, for tables read side by side rather than
    scanned for a value.
    """
    from PyQt6.QtWidgets import QAbstractItemView, QHeaderView

    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(
        QAbstractItemView.SelectionMode.SingleSelection if single
        else QAbstractItemView.SelectionMode.ExtendedSelection)

    header = table.horizontalHeader()
    header.setSectionResizeMode(
        QHeaderView.ResizeMode.ResizeToContents if fit
        else QHeaderView.ResizeMode.Stretch)
    if stretch is not None:
        for col in ((stretch,) if isinstance(stretch, int) else stretch):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
    return table


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
