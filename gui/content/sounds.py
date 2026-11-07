"""The Sounds tab: how a sound is heard, which sounds to pick, and how much
of each a model needs.

One idea per topic, so a screen shows just the ones it needs.

Copy only. Edited here, drawn by `gui.widgets.help_dialog`.
"""
from gui.content import tab, topic, MS_PER_FRAME, SUFFICIENT_S, GOOD_S, EXCELLENT_S

FRAMES_INTRO = (f"<p>The audio is cut into {MS_PER_FRAME} ms frames and each "
                f"one is classified on its own. A sound is never judged whole: "
                f"frames that no longer sound like it come out as silence.</p>")

# Row bodies read as their own sentence, so they start capitalised. Literal
# names (sound labels, filenames) keep their own casing.
CHOOSING_ROWS = (
    ("Start unique", "The opening frames are the most important to keep "
                     "unique. It's ok if the tail overlaps other sounds, "
                     "because you can throttle them."),
    ("Suggestions", None),
    ("Safe with speech", "<b>pop</b>, <b>palate</b> (palatal click), "
                         "<b>cluck</b> (alveolar click), <b>tut</b> (dental "
                         "click)."),
    ("Conflicts with speech", "Vowels (<b>ah</b>, <b>oh</b>, <b>ee</b>) and "
                              "consonants (<b>mm</b>, <b>hiss</b>, "
                              "<b>shush</b>, <b>t</b>, <b>ff</b>, <b>guh</b>, "
                              "<b>er</b>, <b>eh</b>). Usable, but you give up "
                              "voice commands while they're live, and pairs "
                              "sharing an opening (<b>uh</b> vs <b>ah</b>) "
                              "misfire."),
    ("Distractors", "Record the noises you want ignored - table bumps, throat "
                    "clears, keyboard - as their own sound, and map them to "
                    "nothing."),
)

QUANTITY_INTRO = ("<p>Each sound is rated on its <b>detected</b> time - the "
                  "blue regions only, never the silence around them.</p>")

# (rating name, the span it covers). The colour comes from theme.QUANTITY_COLORS
# at render time, so this stays copy.
QUANTITY_BANDS = (
    ("Not enough", f"under {SUFFICIENT_S:g}s"),
    ("Sufficient", f"{SUFFICIENT_S:g}s to {GOOD_S:g}s"),
    ("Good", f"{GOOD_S:g}s to {EXCELLENT_S:g}s"),
    ("Excellent", f"{EXCELLENT_S:g}s and up"),
)

QUANTITY_NOTE = ("<p>Guidelines, not limits. Good is usually enough to train "
                 "something usable; Excellent gives the classifier variety. "
                 "The sound left at Not enough is the one the model will "
                 "confuse most, so it is where another recording pays "
                 "best.</p>")

TAB = tab("sounds", "Sounds", "The sounds a model learns.", (
    topic("frames", "How a sound is heard", intro=FRAMES_INTRO, diagram="frames"),
    topic("choosing", "Choosing sounds", rows=CHOOSING_ROWS),
    topic("quantity", "How much data you need", intro=QUANTITY_INTRO,
          bands=QUANTITY_BANDS, note=QUANTITY_NOTE),
))
