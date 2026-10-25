"""The Overview tab: what Parrot is, and why it is quick.

Copy only. Edited here, drawn by `gui.widgets.help_dialog`.
"""
from gui.content import tab, topic, MS_PER_FRAME, TAGLINE

SPEED_TEXT = (
    f"<p>Speech has to wait for you to stop talking before it can decide what "
    f"you said. Parrot judges every {MS_PER_FRAME} ms slice as it arrives, so "
    f"a sound fires while you are still making it, and the next one can fire "
    f"{MS_PER_FRAME} ms later instead of waiting out another speech "
    f"timeout.</p>")


TAB = tab("overview", "Overview", None, (
    topic("how_it_works", "How Parrot works", diagram="pipeline",
          lede=TAGLINE),
    topic("speed", "Why Parrot is so much faster than voice commands",
          intro=SPEED_TEXT),
))
