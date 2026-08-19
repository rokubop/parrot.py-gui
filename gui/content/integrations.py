"""The Integrations tab: where a trained model is, and what runs it.

Copy only. Edited here, drawn by `gui.widgets.help_dialog`.

Information, deliberately, and no more. This app trains a model and hands you
the file; putting it into Talon happens on Talon's side. So the copy here says
what to expect and never implies a button that does it for you.

The long versions live in docs/: TALON_VOICE.md for the setup, PATTERNS.md for
every field a pattern can carry.
"""
from gui.content import tab, topic


# The tab's opening claim, because nothing below it makes sense without it:
# this program ends at a file, and moving that file is a manual step. Said
# plainly, because it is also what the Open models folder button is for.
HANDOFF_LEDE = ("After training a model, you'll need to integrate it with "
                "another application in order to make use of it to do actions "
                "on your computer.")

# The whole procedure, because it is two steps and pretending otherwise
# would be padding. The button below it is the first step.
# "parrot's", not "data/models": the real path moves with the profile and
# with whether this is a checkout or an installed build, and the label under
# the button prints whichever one it actually is.
COPY_STEP = ("Go to parrot's models folder and copy the model to where the "
             "integration expects it.")

# The folder has more in it than the one file, and the extras look like they
# might matter. Named here so nobody copies a checkpoint and wonders why
# nothing loads: only the .pkl leaves.
FILES_NOTE = ("The folder holds one <code>.pkl</code> per model - that is "
              "the model, and the only file you copy. It carries its own "
              "nets, so nothing else travels with it. The "
              "<code>.pth.tar</code> files beside it are per-net training "
              "checkpoints the <code>.pkl</code> was built from "
              "(<code>-BEST</code> is that net's most accurate so far). "
              "They stay here.")

TALON_INTRO = "Talon is the recommended integration path."

# What Talon needs, in the order someone hits it: what it does for you, the
# thing that stops most people (the beta), then where the file goes.
TALON_ROWS = (
    ("What", "Talon ({talon}) runs your model live, with first-party parrot "
             "support. It listens with the model you trained, and each sound "
             "becomes a trigger your <code>.talon</code> files bind an action "
             "to."),
    ("Requires", "The Talon <b>beta</b>. Parrot support is not in the stable "
                 "build. {talon_beta}."),
    ("What you copy", "The <code>.pkl</code>, named <code>model.pkl</code>, "
                      "into a <code>parrot</code> folder in your Talon user "
                      "directory - beside <code>parrot_integration.py</code> "
                      "and <code>patterns.json</code>."),
    ("Binding a sound", "<code>patterns.json</code> names each trigger and "
                        "the sounds that fire it. A <code>.talon</code> file "
                        "then binds the name: "
                        "<code>parrot(name): mouse_click(0)</code>."),
    ("Setting it up", "By hand, on Talon's side. Nothing here installs into "
                      "Talon or changes what Talon does."),
    ("Tuning it", "{tester} shows what Talon detects frame by frame, which "
                  "is how you find the numbers a threshold should use."),
)

# Enough to read someone else's patterns.json and write your own. The full
# field list, with worked examples, is docs/PATTERNS.md.
PATTERN_ROWS = (
    ("sounds", "Which of the model's sounds count toward this trigger. Their "
               "probabilities are summed."),
    ("threshold", "The rules that must <i>all</i> pass for a frame to fire: "
                  "<code>&gt;probability</code> (summed confidence, 0-1), "
                  "<code>&gt;power</code> (loudness), and "
                  "<code>&gt;f0/f1/f2</code> (pitch and formants, in Hz, to "
                  "tell a high hiss from a low one). Each has a "
                  "<code>&lt;</code> form too."),
    ("detect_after", "The rules have to hold this long before the first fire, "
                     "which turns a pop into hold-to-activate."),
    ("grace_threshold", "Softer rules that take over once the pattern has "
                        "fired, so a sound you are holding does not stutter "
                        "as its probability wobbles."),
    ("graceperiod", "How long grace_threshold stays in effect afterwards."),
    ("throttle", "After firing, how long this pattern stays silent. Name "
                 "other patterns to silence those instead. Targets are "
                 "pattern names, never sound names."),
)

PATTERN_NOTE = ("<p>Detection runs 60 times a second, so a throttle is what "
                "makes one utterance one action.</p>")


TAB = tab("integrations", "Integrations",
          "The model you trained, and the program that runs it.", (
    topic("running_a_model", "Using your model", lede=HANDOFF_LEDE,
          diagram="handoff",
          short="A trained model needs another application to act on what it "
                "hears.",
          shown_on="Integrations tab"),
    topic("model_file", "Copying your model", intro=COPY_STEP,
          note=FILES_NOTE,
          short="A trained model is one .pkl file in data/models/.",
          shown_on="Integrations tab"),
    topic("talon", "Talon integration", intro=TALON_INTRO, rows=TALON_ROWS,
          short="Talon runs your model live and turns each sound into an "
                "action.",
          shown_on="Integrations tab"),
    topic("patterns", "What a pattern holds", rows=PATTERN_ROWS,
          note=PATTERN_NOTE,
          short="A trigger: the sounds that fire it, and the rules that "
                "decide when they count.",
          shown_on="Integrations tab"),
))
