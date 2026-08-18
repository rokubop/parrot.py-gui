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

HANDOFF_INTRO = ("You do that by copying the model file into wherever that "
                 "application keeps it. <b>Open models folder</b> takes you "
                 "to it. Talon (beta version) has first party integration "
                 "support, and is the recommended integration path.")


MODEL_FILE_ROWS = (
    ("What", "One <code>.pkl</code> file. It carries its own nets, so "
             "nothing else has to travel with it."),
    ("Where", "<code>data/models/</code>, one file per model. The button on "
              "this tab opens that folder."),
    ("Taking it elsewhere", "Copy the file wherever the program that reads "
                            "parrot models expects it. Parrot reads and "
                            "writes nothing outside its own data folder."),
    ("Test it first", "Models tab, <b>Test live</b>. Runs the model against "
                      "your microphone here, so you can see what it detects "
                      "before it goes anywhere."),
)

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
          intro=HANDOFF_INTRO,
          short="A trained model needs another application to act on what it "
                "hears.",
          shown_on="Integrations tab"),
    topic("model_file", "Your model file", rows=MODEL_FILE_ROWS,
          short="A trained model is one .pkl file in data/models/.",
          shown_on="Integrations tab"),
    topic("talon", "Talon integration", rows=TALON_ROWS,
          short="Talon runs your model live and turns each sound into an "
                "action.",
          shown_on="Integrations tab"),
    topic("patterns", "What a pattern holds", rows=PATTERN_ROWS,
          note=PATTERN_NOTE,
          short="A trigger: the sounds that fire it, and the rules that "
                "decide when they count.",
          shown_on="Integrations tab"),
))
