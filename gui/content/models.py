"""The Models tab: training, nets, and how the data is balanced.

Copy only. Edited here, drawn by `gui.widgets.help_dialog`.
"""
from gui.content import tab, topic


TRAIN_ROWS = (
    ("What", "Training reads every recording of every sound and produces "
             "a model file in data/models."),
    ("Needs", "2+ sounds. The more sounds rated Excellent, the better the "
              "model."),
    ("Time", "Hours, not minutes - roughly 4-6 hrs for 14 sounds at 5 nets "
             "running all 300 epochs. Sound count, how much you've recorded "
             "and the net count each multiply it. Runs unattended, so start "
             "it and leave it."),
    ("Rough draft", "You don't have to run it out. The best model so far is "
                    "saved every time accuracy improves, so Stop once the "
                    "curve flattens and you keep it - a usable first pass in "
                    "a fraction of the time. Let it finish when you're "
                    "chasing the last few points."),
    ("Neural networks", "How many the model owns. Each one is trained on "
                        "every round, and every one of them is consulted on "
                        "every sound the model hears afterwards. 3 is a good "
                        "default; the ? beside the setting explains the rest."),
    ("Stay awake", "The app has to stay open for the whole run. Keep computer "
                   "awake holds sleep off while it goes, so there is nothing "
                   "to turn off first. Closing a laptop lid still stops it."),
    ("Where", "Models tab, + New model. Training again never replaces what "
              "you have; old models are kept."),
)

CLOSED_SET_NOTE = ("<p>It always answers with one of the sounds it knows. "
                   "Nothing is ever rejected, which is why a noise you want "
                   "ignored still has to be recorded.</p>")

# Nets get their own topic because the number reads as a per-run setting and
# is really the shape of the model: every net loads with it and runs on
# every frame forever. Big picture first, training cost last.
NET_ROWS = (
    # No opening row restating the caption: the diagram renders above the
    # rows, so it has already said what a network does.
    (None, "If you choose 3, every sound detection consults all 3 and averages "
           "their predictions. Training has to train each of the 3 on every "
           "round (epoch), which is why more of them means a longer wait."),
    (None, "They score every frame while training, and again every day "
           "afterwards whenever the model runs. The number you pick stays part "
           "of the model, not just the training run, so changing it means "
           "training again."),
    (None, "More than one is worth it because each net starts from different "
           "random values, so they don't end up wrong about the same sounds. "
           "Averaging them means one net getting a sound wrong doesn't decide "
           "the answer on its own."),
    (None, "<b>2 to 5 is the useful range</b>, 3 by default. Use 1 to find out "
           "quickly whether your recordings are good enough: it trains fastest, "
           "though one net has nothing to average with."),
)

# The three names here are the combo's own items. They were "Balance it" and
# "Leave out" in the tooltip and "Balanced" / "Omit" in the control, which is
# the kind of drift this file exists to stop.
SILENCE_SHORT = (
    "Assembled from the quiet parts of your recordings; you never record it. "
    "Include all is usually the biggest class by far, Balanced gives it one "
    "sound's ration, Omit drops the class.")

BALANCE_SHORT = (
    "Repeats sounds you have little of and trims the ones you have most of, "
    "so no sound dominates by volume alone. Repeating stops at 2x.")

BALANCE_ROWS = (
    ("Why", "A model can guess. Give it 99 examples of one sound and 1 of "
            "another, and always answering the first is right 99% of the time - "
            "while the second never fires. Even amounts take that shortcut away."),
    ("Balance sounds", "Repeats the thin ones, trims the fat ones. Repeating "
                       "stops at 2x, so a very thin sound still goes in light. "
                       "Off means each sound goes in exactly as recorded."),
    ("Better fix", "Record more of the thin sound. Trimming throws away data "
                   "you already have."),
    ("Silence", "You never record it: the trainer collects the quiet between "
                "your recordings. It becomes a sound the model can answer with."),
    ("It never fires", "Quiet frames are gated on power before the model is "
                       "even asked. That gate is what stops quiet triggering "
                       "things, not this class."),
    ("Include all", "Every quiet frame. Usually several times your largest "
                    "sound."),
    ("Balanced", "One sound's ration. The default."),
    ("Omit", "No silence class. Pair it with a recorded background sound (a "
             "fan, talking) so real noise still has somewhere harmless to land."),
    ("Which is best", "Unmeasured. Balanced is the default because it does the "
                      "same job for far less of the run."),
)


TAB = tab("models", "Models",
          "Turning recordings into a model. Also on the Models tab and the "
          "training screen.", (
    topic("train", "Training a model", rows=TRAIN_ROWS,
          short="Reads every recording of every sound and writes a model. "
                "Hours, not minutes.",
          shown_on="Models tab"),
    topic("labels", "How it picks a sound", diagram="closed_set",
          note=CLOSED_SET_NOTE,
          short="It always answers with one of the sounds it knows. Nothing "
                "is ever rejected."),
    topic("nets", "Neural networks", rows=NET_ROWS, diagram="nets",
          short="How many the model owns. Every one is consulted on every "
                "sound, and their scores are averaged.",
          shown_on="Training setup"),
    topic("balance", "Balancing the data", rows=BALANCE_ROWS,
          diagram="balance_legend", short=BALANCE_SHORT,
          shown_on="Training setup"),
))
