"""The Integrations tab: where a trained model is, and what runs it."""
import os

from gui.content import tab, topic

COPY_STEP = ("Open parrot.py's models folder and manually copy the model "
             "to where the integration expects it. For Talon Voice, see "
             "instructions below.")

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

# Three drafts of the pattern reference, chosen with PARROT_PATTERNS_VARIANT
# so they can be compared in the running app. One survives.
VARIANT = os.environ.get("PARROT_PATTERNS_VARIANT", "a").lower()

PATTERN_INTRO = ("One trigger in <code>patterns.json</code>. This one fires on "
                 "the model's <code>ss</code> sound:")

PATTERN_EXAMPLE = """"hiss": {
  "sounds": ["ss"],
  "threshold": {
    ">power": 5,
    ">probability": 0.985
  },
  "graceperiod": 0.03,
  "grace_threshold": {
    ">power": 3,
    ">probability": 0.4
  },
  "throttle": {
    "tut": 0.2,
    "t": 0.15
  }
}"""

PATTERN_ROWS = (
    ("sounds", "The model's sounds that count toward this trigger. Listing "
               "two adds their probabilities together, which is how two "
               "sounds it confuses can still fire one thing reliably."),
    ("threshold", "The rules that must <i>all</i> pass for a frame to fire. "
                  "<code>&gt;probability</code> is that summed confidence, 0 "
                  "to 1, and sits at 0.9 to 0.99 in practice. "
                  "<code>&gt;power</code> is loudness, 3 to 15. "
                  "<code>&gt;f0</code>, <code>&gt;f1</code> and "
                  "<code>&gt;f2</code> are pitch and formants in Hz, for "
                  "telling a high sound from a low one. "
                  "<code>&gt;ratio</code> compares the first listed sound to "
                  "the second. Each has a <code>&lt;</code> form."),
    ("detect_after", "Seconds the rules have to hold before the first fire, "
                     "which turns a pop into hold to activate. Left out, one "
                     "frame is enough."),
    ("grace_threshold", "Softer rules that take over once the pattern has "
                        "fired, so a sound you are holding does not stutter "
                        "as its probability wobbles."),
    ("graceperiod", "How long those softer rules last. 0.03 to 0.1 s."),
    ("throttle", "Seconds of silence after firing. 0.15 on itself is what "
                 "makes one utterance one action; naming another pattern "
                 "silences that one instead. Targets are pattern names, "
                 "never sound names."),
)

PATTERN_NOTE = ("<p>Detection runs 60 times a second. Talon skips the model "
                "entirely while power sits below the lowest "
                "<code>&gt;power</code> you have written, so one low value "
                "costs a little CPU for every pattern.</p>")

PATTERNS_TOPIC = topic("patterns", "What a pattern holds",
                       intro=PATTERN_INTRO, code=PATTERN_EXAMPLE,
                       rows=PATTERN_ROWS, note=PATTERN_NOTE,
                       short="A trigger: the sounds that fire it, and the "
                             "rules that decide when they count.",
                       shown_on="Integrations tab")

# Draft B: the reference, plus what to reach for when a trigger misbehaves.
# The reference says what a key is; this says which key a symptom calls for,
# which is the part nobody can look up.
TUNING_ROWS = (
    ("Fires when you were quiet", "Raise <code>&gt;power</code> first. Most "
                                  "stray detections are quiet noises the "
                                  "model has never heard: a hand through "
                                  "your hair, a mouse on a mat. Raise "
                                  "<code>&gt;probability</code> after."),
    ("Fires twice per sound", "Throttle it against itself. 0.15 s is about "
                              "one utterance; too long and a deliberate "
                              "double is swallowed."),
    ("Sets off a different trigger", "Name that pattern in this one's "
                                     "<code>throttle</code>. An echo often "
                                     "reads as another sound for a frame or "
                                     "two just after a real one."),
    ("Stutters while you hold it", "Add a <code>grace_threshold</code> "
                                   "looser than the threshold, with a "
                                   "<code>graceperiod</code> of 0.05. A held "
                                   "sound drifts as you run out of breath, "
                                   "and its probability drops with it."),
    ("Fires the moment you start", "<code>detect_after</code>, if you wanted "
                                   "hold to activate rather than a tap."),
    ("Two sounds fire each other", "Split them on pitch with "
                                   "<code>&gt;f0</code> or "
                                   "<code>&lt;f1</code>, or on "
                                   "<code>&gt;ratio</code> if one sound "
                                   "always leads the other."),
    ("It never fires at all", "Check the sound names against the model's "
                              "own labels. A name that is not in the model "
                              "makes Talon discard the whole pattern."),
)

TUNING_NOTE = ("<p>Every number here is one you read off a frame, not one you "
               "guess. {tester}, or the test screen, shows the power and "
               "probability of the sound you just made.</p>")

TUNING_TOPIC = topic("pattern_tuning", "When a trigger misbehaves",
                     rows=TUNING_ROWS, note=TUNING_NOTE,
                     short="Which threshold to reach for when a sound fires "
                           "twice, fires early, or fires on nothing.",
                     shown_on="Integrations tab")

# What the page draws for this variant: which topics get a ? button under
# Talon, and what it shows inline.
if VARIANT == "b":
    PATTERN_TOPICS = (PATTERNS_TOPIC, TUNING_TOPIC)
else:
    PATTERN_TOPICS = (PATTERNS_TOPIC,)
PATTERN_EXAMPLE_ON_PAGE = None


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
) + PATTERN_TOPICS)
