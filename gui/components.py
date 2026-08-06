"""Shared UI primitives - the pieces that were being retyped per page.

Sits below ``windows/`` and ``widgets/`` and imports neither, so anything may
import it. That is half the point: ``primary_button_style`` used to live in
``windows/train_view.py``, and five modules reached it through a function-local
import to dodge the circular dependency that a module-level one would have made.

Each primitive comes in two forms:

  * ``x_style()`` returns the stylesheet string, for restyling a widget that
    already exists (the ``refresh_theme`` paths).
  * ``x()`` builds the widget with that style already on it.

Colours and sizes come from ``theme`` - nothing here hardcodes a hex or a px.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QFrame, QLabel, QPushButton, QVBoxLayout, QWidget)

from gui import theme


# ---- text ---------------------------------------------------------------

def heading_style(rank="card", color=None):
    """One of the ranks in ``theme.TYPE_SCALE``.

    `eyebrow` is the same size as body copy - the scale has a floor and it is
    at the bottom of it - so it carries its rank without size: dim ink, bold,
    and a little letter-spacing. That last one is what still reads as "label
    naming the thing below" once the 11px is gone; bold dim text at body size
    on its own reads as emphasis instead.
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


def painter_font(widget, rank="body"):
    """A font at a scale rank, for text drawn in a paintEvent.

    Stylesheets do not reach QPainter text, so a diagram that annotates itself
    has to size its own font - and the three that do got it wrong in the same
    way. They each did

        f.setPointSizeF(max(8.5, f.pointSizeF() - 1.5))

    meaning "a point and a half under the base". The stylesheet sets the widget
    font in *pixels*, so pointSizeF() returns -1, the subtraction goes negative
    and max() pins every one of them at exactly 8.5pt - about 11px, under the
    floor, and not what the arithmetic says.
    """
    font = widget.font()
    font.setPixelSize(theme.TYPE_SCALE[rank])
    return font


def set_wrapped_text(label, text, width):
    """Set a word-wrapped label's text and give it the height that copy needs.

    A word-wrapped QLabel reports a one-line sizeHint, so a layout that is not
    asked for heightForWidth clips it. Pin the width once, then re-ask what
    height this particular copy needs at that width.

    The guard is the point. heightForWidth returns -1 on a label that has never
    held text, and passing that straight to setMinimumHeight prints

        QWidget::setMinimumSize: (/QLabel) Negative sizes (460,-1)

    which is what an empty state built before its copy arrives does. Four
    places in the app pin a width this way and only the help dialog's
    WrappingLabel checked the return value.
    """
    label.setText(text)
    needed = label.heightForWidth(width)
    label.setMinimumHeight(needed if needed > 0 else 0)


# ---- cards --------------------------------------------------------------

def card_style(object_name, surface="panel", children="> QLabel"):
    """A rounded panel with a border.

    Scoped to `object_name` rather than written bare: a selector-less stylesheet
    on an ancestor silently breaks :checked on descendant buttons.

    `children` is the selector for what inside the card must declare itself
    transparent. The global ``QWidget`` rule paints an opaque $window box behind
    every child otherwise, so each one gets its own dark rectangle inside the
    card - see memory/qt-traps.md. Direct children only by default; pass a
    descendant selector (no ``>``) when the card nests them deeper.
    """
    t = theme.colors()
    return (f"QFrame#{object_name} {{ background-color: {t[surface]}; "
            f"border: 1px solid {t['border']}; "
            f"border-radius: {t['radius_card']}; }} "
            f"QFrame#{object_name} {children} {{ "
            f"background: transparent; border: none; }}")


# The card interior. Was five different tuples across six cards, none of them
# deliberately different from the others.
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
    """Accent-filled call to action - Sounds' "Add recording", Models' "Test
    live", the training button, the empty-state panels.

    There were two of these, and they had drifted: one carried the :disabled
    rule and no :hover, the other the reverse, so the same rank of button
    greyed out differently depending on which page it was on. Both are here.
    """
    t = theme.colors()
    return (f"QPushButton#primaryAction {{ background-color: {t['accent']}; "
            f"color: {t['accent_text']}; font-weight: bold; border: none; "
            f"border-radius: {t['radius']}; padding: 6px 18px; }} "
            f"QPushButton#primaryAction:hover {{ "
            f"background-color: {t['accent']}; }} "
            # Disabled matches the app-wide rule: sunken fill, disabled_text.
            # text_dim on the live $button fill measured 3.29.
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


# ---- badges -------------------------------------------------------------

def badge_style(tone="accent", outlined=True):
    """A small pill stating a fact about the thing beside it - "Live in Talon".

    `tone` is a theme colour key, so a badge can be accent/ok/warn/bad/info and
    stay on the measured palette. Outlined badges get the border; a plain one is
    just coloured text at badge size, which is what the pattern-card issue
    counts already were.
    """
    t = theme.colors()
    css = (f"color: {t[tone]}; font-size: {theme.TYPE_SCALE['eyebrow']}px; "
           f"font-weight: bold;")
    if outlined:
        # Padding grew with the type: at the old 11px a 1px inset made a pill,
        # at body size it made a box with the text touching the border.
        css += (f" border: 1px solid {t[tone]}; "
                f"border-radius: {t['radius_pill']}; padding: 2px 10px;")
    return css


def section_label(text, color=None):
    """An eyebrow with a rule under it - the lowercase file keys on the pattern
    cards and in the pattern editor, which had this idiom twice, by hand."""
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
    """The behaviour every table in the app wants, applied in one place.

    Six tables set this up by hand and four of them agreed. The two that did
    not (the accuracy dialog, the live tester's stats tab) never asked for row
    selection, so a click lit a single cell rather than the row it was in -
    which, before the theme grew a ::item:selected rule, meant one cell of
    solid accent green in the middle of a row.

    `stretch` is the column, or columns, that absorb the leftover width; the
    rest size to their contents when `fit`. Pass ``fit=False`` to stretch every
    column evenly instead - the captures view wants that, because its two
    tables are read side by side in a splitter rather than scanned for a value.
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
    """Centered title / body / action, used wherever a page has nothing to show.

    Built once and re-worded via ``set_state`` rather than rebuilt, because the
    Models tab has four of these and swapping the copy is cheaper than swapping
    the widget. The Sounds tab builds one per state and just never re-words it.
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
        """Re-word in place. Disconnects the previous action first, or a panel
        re-used across states accumulates every slot it has ever been given."""
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
