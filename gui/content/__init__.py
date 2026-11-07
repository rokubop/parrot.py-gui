"""Every word the app teaches with, in one place.

One module per tab, each ending in a ``TAB`` holding its topics. A topic is
written once here and drawn wherever it appears: the ``?  Help`` modal beside
a control, a dialog that teaches at the moment it matters, and the About page,
which is this package end to end.

Copy only. No Qt, so anything may import it. A topic names its picture with a
string; `gui.widgets.help_dialog` owns the drawings and the rendering.

Numbers come from the config the app actually runs on, never typed twice.
"""
from config.config import MS_PER_FRAME
from lib.print_status import (QUANTITY_SUFFICIENT_MS, QUANTITY_GOOD_MS,
                              QUANTITY_EXCELLENT_MS)

# The bands get_quantity_rating uses, so the help and the live ratings agree
SUFFICIENT_S = QUANTITY_SUFFICIENT_MS / 1000
GOOD_S = QUANTITY_GOOD_MS / 1000
EXCELLENT_S = QUANTITY_EXCELLENT_MS / 1000


def topic(key, title, rows=None, diagram=None, intro=None, note=None, bands=None):
    """One topic.

    `rows` are (label, body) pairs; a row with no body is a heading spanning
    both columns. Prose belongs in `intro` / `note`, never in `rows`: a
    full-width paragraph sharing the table with label rows stretches the label
    column halfway across the page.

    `diagram` names one of help_dialog.DIAGRAMS.
    """
    return dict(key=key, title=title, rows=rows, diagram=diagram, intro=intro,
                note=note, bands=bands)


def tab(key, title, blurb, topics):
    return dict(key=key, title=title, blurb=blurb, topics=topics)


# Imported last: the modules below import the builders above.
from gui.content import sounds  # noqa: E402

TABS = (sounds.TAB,)

# Every topic by key. Keys are the app-wide handle for a piece of help -
# help_button(self, "record") - so they outlive whichever tab a topic sits in.
TOPICS = {t["key"]: t for tb in TABS for t in tb["topics"]}


def get(key):
    return TOPICS[key]


def title(key):
    return TOPICS[key]["title"]
