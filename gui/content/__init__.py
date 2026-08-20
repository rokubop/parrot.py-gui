"""Every word the app teaches with, in one place.

Organised the way the app is: one module per tab, each ending in a ``TAB``
holding its topics. A topic is written once here and drawn in three places -
the ``?  Help`` modal beside the control, the About page (which is this
package end to end), and any tooltip that would otherwise re-explain the same
thing in its own words.

Copy only. No Qt, so anything may import it. A topic names its picture with a
string; `gui.widgets.help_dialog` owns the drawings and the rendering.

Numbers come from the config the app actually runs on, never typed twice.
"""
from config.config import RECORD_SECONDS, SLIDING_WINDOW_AMOUNT

# A frame is one sliding window, not a whole sample - same arithmetic as
# load_data, so help cannot quote a length the trainer does not use.
MS_PER_FRAME = int(RECORD_SECONDS / SLIDING_WINDOW_AMOUNT * 1000)

# Detected sound per label: under the first, get_quantity_rating says "Not
# enough" and training is a formality; the second is where a model starts
# being usable.
MIN_TRAIN_SECONDS = 17
GOOD_TRAIN_SECONDS = 40

# The rating bands, mirrored from lib/print_status.get_quantity_rating so the
# help and the live ratings always agree.
SUFFICIENT_S = 16.5
GOOD_S = 41.25
EXCELLENT_S = 82.5

TAGLINE = ("Train a model on the sounds you make - clicks, pops, vowels, "
           "hisses - and use them to control your computer.")

# Copy names a link as {token}; help_dialog swaps in an anchor coloured by the
# current theme. A constant anchor cannot work - a stylesheet makes Qt ignore
# the palette's Link role, so the colour has to be inlined at render time -
# and a token keeps this file free of Qt and readable to a translator.
TALON_URL = "https://talonvoice.com/"
TALON_BETA_URL = "https://talon.wiki/Help/beta_talon/"
TESTER_URL = "https://github.com/rokubop/parrot_tester"

LINKS = {
    "talon": (TALON_URL, "talonvoice.com"),
    "talon_beta": (TALON_BETA_URL, "How to get the beta"),
    "tester": (TESTER_URL, "Parrot Tester"),
}


def topic(key, title, rows=None, diagram=None, lede=None, intro=None,
          note=None, bands=None, code=None, short=None, shown_on=None):
    """One topic, in the two lengths the app needs.

    `short` is the one-line version a tooltip shows; everything else is the
    full version behind ``?  Help`` and on the About page. A control that
    would otherwise carry its own paragraph points at `short` instead, which
    is what keeps a tooltip and its help topic from drifting apart.

    `rows` are (label, body) pairs; a row with no body is a heading spanning
    both columns. Prose belongs in `lede` / `intro` / `note`, never in `rows`:
    a full-width paragraph sharing the table with label rows stretches the
    label column halfway across the page.

    `code` is a literal block - a file listing, a snippet - shown as typed,
    on its own surface. Plain text: the monospace font and the colours are
    help_dialog's, so a block does not carry markup it cannot theme.

    `diagram` names one of help_dialog.DIAGRAMS. `shown_on` says where the
    topic's Help button lives, for readers of the About page.
    """
    return dict(key=key, title=title, rows=rows, diagram=diagram, lede=lede,
                intro=intro, note=note, bands=bands, code=code, short=short,
                shown_on=shown_on)


def tab(key, title, blurb, topics):
    return dict(key=key, title=title, blurb=blurb, topics=topics)


def rows_of(entries, length="long"):
    """(label, body) rows from entries that carry both lengths.

    Lets one definition feed a narrow legend column and a full help topic.
    """
    return tuple((name, entry[length]) for name, entry in entries)


# Imported last: the modules below import the builders above.
from gui.content import overview, sounds, models, integrations, program  # noqa: E402

TABS = (overview.TAB, sounds.TAB, models.TAB, integrations.TAB, program.TAB)

# Every topic by key. Keys are the app-wide handle for a piece of help -
# help_button(self, "record") - so they outlive whichever tab a topic sits in.
TOPICS = {t["key"]: t for tb in TABS for t in tb["topics"]}

# What the training screen teaches inline, in its own order. Same topics, so
# editing one fixes both.
TRAINING_TOPICS = ("labels", "balance", "nets")


def get(key):
    return TOPICS[key]


def title(key):
    return TOPICS[key]["title"]


def short(key):
    """The one-line version, for a tooltip. Falls back to the title so a
    control never shows an empty hover."""
    return TOPICS[key]["short"] or TOPICS[key]["title"]
