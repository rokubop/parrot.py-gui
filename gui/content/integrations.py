"""The Integrations tab: Talon, and what a pattern holds.

Copy only. Edited here, drawn by `gui.widgets.help_dialog`.
"""
from gui.content import rows_of, tab, topic


CONNECT_ROWS = (
    ("What", "Talon ({talon}) runs your model live and maps each sound to an "
             "action."),
    # Second, because nothing below it works without the beta.
    ("Requires", "The <b>Talon beta</b>. Parrot support is not in the stable "
                 "build: it comes with a Patreon tier and the #beta channel "
                 "on Slack. {talon_beta}."),
    ("Patterns", "Each trigger, and the sound that fires it, lives in "
                 "patterns.json. Edit and deploy from the Integrations tab."),
    ("Throttle", "Detection runs 60 times a second. A pattern's throttle on "
                 "itself is how long before it fires again, so one utterance "
                 "is one action. On another pattern, it silences that one "
                 "instead."),
    ("Setup", "The Integrations tab finds your Talon install and can "
              "bootstrap the parrot integration from nothing."),
    ("Where", "Integrations tab."),
)

# One entry per pattern key, in two lengths: `short` for the edit dialog's
# 220px legend column, `long` for help and the About page. Order follows the
# file, led by the pattern itself; grace_threshold precedes graceperiod
# because graceperiod is defined in terms of it.
PATTERN_KEYS = (
    ("pattern", dict(
        short="What Talon recognizes. One or more sounds and their settings.",
        long="A trigger your .talon files bind an action to. The Integrations "
             "tab edits these with validation and snapshots every deploy.")),
    ("sounds", dict(
        short="Sounds from a parrot model.",
        long="Which model sounds count toward it. Their probabilities are "
             "summed.")),
    ("threshold", dict(
        short="The conditions that trigger the pattern. Checked 60 times a "
              "second.",
        long="Rules that must <i>all</i> pass for a frame to fire: "
             "<code>&gt;probability</code> (summed confidence, 0-1), "
             "<code>&gt;power</code> (loudness), <code>&gt;f0/f1/f2</code> "
             "(pitch and formants in Hz, to tell a high hiss from a low one), "
             "each also available as <code>&lt;</code>. Checked 60 times a "
             "second.")),
    ("detect_after", dict(
        short="The sound must hold this long before the first trigger.",
        long="The rules must hold this long before the first fire, which "
             "turns a pop into a hold-to-activate.")),
    ("grace_threshold", dict(
        short="Secondary rules once the pattern has triggered. Lets a sound "
              "that starts loud sustain as it goes quieter.",
        long="Softer rules that apply once the pattern has fired, so a sound "
             "you are holding does not stutter as its probability wobbles.")),
    ("graceperiod", dict(
        short="How long grace_threshold stays in effect after the first "
              "trigger.",
        long="How many seconds grace_threshold stays in effect after the "
             "first fire.")),
    ("throttle", dict(
        short="After a trigger, silences a pattern for N seconds. On itself: "
              "how soon it can trigger again.",
        long="After firing, silence the listed patterns - itself included - "
             "for N seconds. Targets are pattern names, never sound names.")),
)

PATTERN_ROWS = (
    ("patterns.json", "Maps the model's sounds to the named triggers your "
                      ".talon files bind actions to. The Integrations tab "
                      "edits it with validation and keeps a snapshot of every "
                      "deploy."),
    ("What a pattern holds", None),
) + rows_of(PATTERN_KEYS)

PATTERN_NOTE = ("<p>The Live and Captures views show the real power and "
                "probability your sounds produce - the numbers to judge a "
                "threshold against. Those are Talon-engine units, not the "
                "dBFS used elsewhere here.</p>")


TAB = tab("integrations", "Integrations",
          "Running a trained model live. Also on the Integrations tab.", (
    topic("connect", "Connecting to Talon", rows=CONNECT_ROWS,
          short="Talon runs your model live and maps each sound to an action.",
          shown_on="Integrations tab"),
    topic("patterns", "Patterns", rows=PATTERN_ROWS, note=PATTERN_NOTE,
          short="A sound, plus the rules that decide when it counts."),
))
