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

# The two words come from two programs, and nothing on screen said so.
# Mixing them up is the common failure: a sound name where a pattern name
# belongs, in a throttle or in a .talon file.
VOCABULARY_TABLE = (
    "Sound vs Pattern",
    None,
    (
        ("sound", "A sound from parrot.py, one of the labels your model was "
                  "trained on."),
        ("pattern", "A named rule in <code>patterns.json</code>, and what "
                    "Talon works in: which sounds, which thresholds, when it "
                    "fires. The name is what a <code>.talon</code> file "
                    "binds."),
    ),
)

PATTERN_INTRO = "Example of one pattern:"

PATTERN_EXAMPLE = """"hiss": {
  "sounds": ["ss"],
  "threshold": {
    ">power": 5,
    ">probability": 0.985,
    "<f0": 450
  },
  "throttle": {
    "hiss": 0.15,
    "tut": 0.2
  },
  "detect_after": 0.05,
  "grace_threshold": {
    ">power": 3,
    ">probability": 0.4
  },
  "graceperiod": 0.03
}"""

PROPERTY_TABLE = (
    "Pattern properties",
    ("Property", "Required", "Format", "What it does"),
    (
        ("sounds", "Yes", "list of labels",
         "The model's sounds that count toward this pattern. Two or more are "
         "added together."),
        ("threshold", "Yes", "object",
         "The rules a frame has to pass for the pattern to fire."),
        ("throttle", "No", "pattern name: seconds",
         "How long each named pattern stays silent after this one fires. "
         "Naming itself is the usual case, and what makes one utterance one "
         "action."),
        ("detect_after", "No", "seconds",
         "How long the rules must hold before the first fire. Turns a tap "
         "into hold to activate."),
        ("grace_threshold", "No", "object",
         "Looser rules that take over once the pattern has fired, so a sound "
         "you hold does not stutter."),
        ("graceperiod", "No", "seconds",
         "How long those looser rules last. 0.03 to 0.1 in practice."),
    ),
)

# One table for both objects: grace_threshold takes the same keys, and
# saying so twice is how the two lists drift apart.
THRESHOLD_TABLE = (
    "Threshold keys, in threshold and grace_threshold",
    ("Key", "Format", "What it compares"),
    (
        ("&gt;power<br>&lt;power", "number",
         "Loudness on Talon's scale, where 3 to 15 is usual and 30 is loud. "
         "Nearly every pattern sets it: it is what keeps quiet noises the "
         "model has never heard from firing."),
        ("&gt;probability<br>&lt;probability", "0 to 1",
         "Confidence, summed across the pattern's sounds. Most sit at 0.9 to "
         "0.99."),
        ("&gt;f0<br>&lt;f0", "Hz",
         "Pitch, for telling a high sound from a low one."),
        ("&gt;f1, &gt;f2<br>&lt;f1, &lt;f2", "Hz",
         "First and second formants, which separate vowels that share a "
         "pitch."),
        ("&gt;ratio<br>&lt;ratio", "number",
         "The first sound's probability divided by the second's. Needs two "
         "sounds."),
    ),
)

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
    topic("patterns", "Understanding Talon's patterns.json",
          intro=PATTERN_INTRO, code=PATTERN_EXAMPLE,
          tables=(VOCABULARY_TABLE, PROPERTY_TABLE, THRESHOLD_TABLE),
          short="A trigger: the sounds that fire it, and the rules that "
                "decide when they count.",
          shown_on="Integrations tab"),))
