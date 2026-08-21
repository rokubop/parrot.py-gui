"""The Integrations tab: where a trained model is, and what runs it."""
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

# The two words come from two programs, and nothing on screen says so.
# Mixing them up is the common failure: a sound name where a pattern name
# belongs, in a throttle or in a .talon file.
PATTERN_LEDE = ("<b>Sounds</b> are your model's. <b>Patterns</b> are Talon's: "
                "a named rule over those sounds, and the name is what a "
                "<code>.talon</code> file binds.")

PATTERN_INTRO = ("One trigger in <code>patterns.json</code>, using every key "
                 "there is:")

PATTERN_EXAMPLE = """"hiss": {
  "sounds": ["ss"],
  "threshold": {
    ">power": 5,
    ">probability": 0.985,
    "<f0": 450
  },
  "detect_after": 0.05,
  "graceperiod": 0.03,
  "grace_threshold": {
    ">power": 3,
    ">probability": 0.4
  },
  "throttle": {
    "hiss": 0.15,
    "tut": 0.2
  }
}"""

# Complete on purpose: every key the integration reads, and the fact that
# there are no others. A threshold it does not know is a warning in Talon's
# log and nothing else, so a rule that looks written is a rule not applied.
PATTERN_ROWS = (
    ("The words", None),
    ("sound", "A label in your model, one per sound you recorded and "
              "trained. The model scores every one of them on every frame. "
              "This app's side."),
    ("pattern", "A named rule in <code>patterns.json</code>: which sounds "
                "count, and how sure and how loud they have to be. One sound "
                "or several. Talon's side. parrot.py's own modes use the "
                "word too, with different keys, so a pattern written for "
                "those does not run here."),
    ("pattern name", "The key the pattern is written under, and the only "
                     "thing a <code>.talon</code> file sees: "
                     "<code>parrot(hiss): mouse_click(0)</code>. Never a "
                     "sound name."),

    ("Top level", None),
    ("sounds", "Required. The model's own labels, and they have to match: a "
               "name the model does not have discards the whole pattern. "
               "Listing two adds their probabilities together, which is how "
               "two sounds it confuses can still fire one thing reliably."),
    ("threshold", "Required. The rules that must <i>all</i> pass for a frame "
                  "to fire."),
    ("detect_after", "Seconds the rules have to hold before the first fire, "
                     "which turns a pop into hold to activate. Left out, one "
                     "frame is enough."),
    ("grace_threshold", "Softer rules that take over once the pattern has "
                        "fired, so a sound you are holding does not stutter "
                        "as its probability wobbles. Same keys as "
                        "<code>threshold</code>."),
    ("graceperiod", "How long those softer rules last. 0.03 to 0.1 s."),
    ("throttle", "Seconds of silence after firing."),

    ("Inside threshold and grace_threshold", None),
    ("&gt;probability<br>&lt;probability", "Summed confidence across every "
                                           "sound listed, 0 to 1. Sits at "
                                           "0.9 to 0.99 in practice."),
    ("&gt;power<br>&lt;power", "Loudness, on Talon's own scale. 3 to 15 in "
                               "practice, 30 is loud. Not parrot.py's power, "
                               "which runs in the thousands."),
    ("&gt;f0<br>&lt;f0", "Pitch in Hz. Tells a high sound from a low one "
                         "without training a second sound for it."),
    ("&gt;f1, &gt;f2<br>&lt;f1, &lt;f2", "First and second formants in Hz. "
                                         "Vowels separate on these where "
                                         "pitch alone will not do it."),
    ("&gt;ratio<br>&lt;ratio", "The first listed sound's probability divided "
                               "by the second's, for splitting two patterns "
                               "that share sounds. Needs two sounds; with one "
                               "it is ignored."),
    ("Nothing else", "Those twelve are the whole set. <code>&gt;=</code>, "
                     "<code>&lt;=</code> and <code>=</code> are not "
                     "operators, and a key Talon does not know - "
                     "<code>&gt;rate</code>, or parrot.py's own "
                     "<code>percentage</code>, <code>frequency</code>, "
                     "<code>intensity</code>, <code>times</code> - is logged "
                     "as unknown and then ignored. The rule reads as written "
                     "and is not applied."),

    ("Inside throttle", None),
    ("a pattern name", "Seconds that pattern stays silent after this one "
                       "fires. Its own name included: 0.15 on itself is what "
                       "makes one utterance one action. A name that is not a "
                       "pattern is ignored, so a sound name here is a "
                       "throttle that never happens."),
)

PATTERN_NOTE = ("<p>Detection runs 60 times a second. "
                "<code>&gt;</code> means at or above, <code>&lt;</code> means "
                "below. Talon skips the model entirely while power sits below "
                "the lowest <code>&gt;power</code> you have written, so one "
                "low value costs a little CPU for every pattern.</p>")


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
    topic("patterns", "What a pattern holds", lede=PATTERN_LEDE,
          intro=PATTERN_INTRO,
          code=PATTERN_EXAMPLE, rows=PATTERN_ROWS, note=PATTERN_NOTE,
          short="A trigger: the sounds that fire it, and the rules that "
                "decide when they count.",
          shown_on="Integrations tab"),
))
