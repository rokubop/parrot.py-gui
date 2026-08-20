"""The Integrations tab: where a trained model is, and what runs it."""
from gui.content import tab, topic

COPY_STEP = ("Open parrot.py's models folder and manually copy the model "
             "to where the integration expects it. For Talon Voice, see "
             "instructions below.")

# The listing is the explanation. Every trained model lands in the same
# flat folder, so all a reader needs is which name to pick out of the pile.
FILES_LISTING = """data/models/

  your_model.pkl                          ← copy this
  your_model.pkl_1-BEST-weights.pth.tar
  your_model.pkl_1-weights.pth.tar
  your_model.pkl_2-BEST-weights.pth.tar
  older_model.pkl"""

TALON_INTRO = "Talon is the recommended integration path."

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
    topic("running_a_model", "Using your model", diagram="handoff",
          short="A trained model needs another application to act on what it "
                "hears.",
          shown_on="Integrations tab"),
    topic("model_file", "Copying your model", intro=COPY_STEP,
          code=FILES_LISTING,
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
