"""Every word of help in the app, in one file.

Organised the way the app is: a tab, then the topics inside it. A topic is
rendered in two places from this one definition - the ``?  Help`` modal beside
the control it explains, and the About page, which is just this file drawn
end to end. Add a topic here and both pick it up.

Copy only. No Qt, so anything may import it and nothing has to care about
widget lifetimes. A topic names its diagram with a string; `help_dialog` owns
the drawings and maps the names.

Numbers come from the same config the app runs on, never typed twice.
"""
from config.config import (
    RATE, RECORD_SECONDS, SLIDING_WINDOW_AMOUNT, CURRENT_DETECTION_STRATEGY,
    THRESHOLD_DETECTION,
)

# A frame is one sliding window, not a whole sample - same arithmetic as
# load_data, so help cannot quote a length the trainer does not use.
MS_PER_FRAME = int(RECORD_SECONDS / SLIDING_WINDOW_AMOUNT * 1000)

# Detected sound per label: under the first, get_quantity_rating says "Not
# enough" and training is a formality; the second is where a model starts
# being usable. Quoted in the Sounds empty state too.
MIN_TRAIN_SECONDS = 17
GOOD_TRAIN_SECONDS = 40

# The rating bands, mirrored from lib/print_status.get_quantity_rating so the
# help and the live ratings always agree.
SUFFICIENT_S = 16.5
GOOD_S = 41.25
EXCELLENT_S = 82.5

TAGLINE = ("Train a model on the sounds you make - clicks, pops, vowels, "
           "hisses - and use them to control your computer.")


def topic(key, title, rows=None, diagram=None, lede=None, intro=None,
          note=None, bands=None, shown_on=None):
    """One topic. `rows` are (label, body) pairs; a row with no body is a
    heading spanning both columns.

    Prose belongs in `lede` / `intro` / `note`, never in `rows`: a full-width
    paragraph sharing the table with label rows stretches the label column
    halfway across the page.

    `diagram` is a name from help_dialog.DIAGRAMS. `shown_on` says where the
    topic's Help button lives, for readers of the About page.
    """
    return dict(key=key, title=title, rows=rows, diagram=diagram, lede=lede,
                intro=intro, note=note, bands=bands, shown_on=shown_on)


def tab(key, title, blurb, topics):
    return dict(key=key, title=title, blurb=blurb, topics=topics)


# ---- overview -----------------------------------------------------------

SPEED_TEXT = (
    f"<p>Speech has to wait for you to stop talking before it can decide what "
    f"you said. Parrot judges every {MS_PER_FRAME} ms slice as it arrives, so "
    f"a sound fires while you are still making it, and the next one can fire "
    f"{MS_PER_FRAME} ms later instead of waiting out another speech "
    f"timeout.</p>")


# ---- sounds -------------------------------------------------------------

# Row bodies read as their own sentence, so they start capitalised. Literal
# names (sound labels, filenames) keep their own casing.
SOUNDS_ROWS = (
    ("How it works", f"The audio is cut into {MS_PER_FRAME} ms frames and "
                     f"each one is classified on its own."),
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
    ("Plan", "Use 📝 Notes to keep notes."),
)

RECORD_ROWS = (
    ("Good sounds", "Tongue clicks, lip pops, palate clicks, “sh” / “ss” "
                    "hisses, short vowels - distinct from each other and from "
                    "normal speech. “Choosing sounds”, on the New sound "
                    "dialog, goes into which ones work and why."),
    ("Goal", "Record each sound until its Data rating says Excellent "
             "(~80 s of detected sound). More data beats more sounds."),
    ("How many", "2 sounds minimum to train. A daily-driver setup is "
                 "usually 10-20."),
    ("Time", "A real commitment: 1 hr+ of recording spread over multiple "
             "days, 4 hr+ for a full model. Bursts are fine; every "
             "recording is saved as you go."),
    ("Mic", "A quiet room, and the mic you'll actually use day to day (pick "
            "it in Settings). Avoid dynamic mics - takes vary too much "
            "between sessions."),
    ("Where", "Sounds tab: “+ New sound”, then “+ Add recording”."),
)

DETECTION_ROWS = (
    ("Why", f"Most of a recording is the silence between sounds. Parrot cuts "
            f"each recording into {MS_PER_FRAME} ms frames and judges each "
            f"one as sound or silence, so training sees the sound and not "
            f"the room."),
    ("Blue bands", "The detected regions drawn over a waveform. Everything "
                   "outside them is ignored when training. Re-run detection "
                   "at a different threshold, or edit the regions by hand, "
                   "from a recording's edit view."),
    ("dBFS", "Loudness, in decibels relative to full scale: 0 is the loudest "
             "possible, more negative is quieter. The threshold is a dBFS "
             "value."),
    ("How the threshold is set", None),
    ("While recording", "Parrot listens to your noise floor and calibrates as "
                        "you go. It needs roughly ten finished sounds before "
                        "it settles, so the first few in a take are judged on "
                        "a provisional number."),
    ("On save", "The whole take is judged again with the threshold that "
                "settled over all of it, so the first sound is segmented on "
                "the same terms as the last. (Two-pass detection, on by "
                "default, switchable in Settings.)"),
    ("By hand", "A threshold you set in a recording's edit view wins over "
                "both, for that recording only."),
    ("Discrete or continuous", "Short and punchy (a click, a pop) against "
                               "sustained (a held vowel, a hiss). Parrot "
                               "estimates this per recording because it "
                               "changes how hard short detections are "
                               "rejected. Override it when editing."),
    ("Strategy", f"How onsets, rejections and gap-mending are handled while "
                 f"segmenting. Currently "
                 f"<code>{CURRENT_DETECTION_STRATEGY}</code> in "
                 f"<b>{THRESHOLD_DETECTION}</b> mode: <i>strict</i> suits "
                 f"rapid back-to-back sounds, <i>lenient</i> leaves more room "
                 f"to settle. Pick one when recording."),
)

QUALITY_ROWS = (
    ("Signal to noise", "How far your sound stands above the room. A quiet "
                        "room and a steady mic distance make the line between "
                        "sound and silence sharp; a noisy one blurs it. This "
                        "is separate from how much you have recorded."),
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


# ---- models -------------------------------------------------------------

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
# is really the shape of the model: every net loads into Talon and runs on
# every frame forever. Big picture first, training cost last.
NET_ROWS = (
    # No opening row restating the caption: the diagram renders above the
    # rows, so it has already said what a network does.
    (None, "If you choose 3, every sound detection consults all 3 and averages "
           "their predictions. Training has to train each of the 3 on every "
           "round (epoch), which is why more of them means a longer wait."),
    (None, "They score every frame while training, and again every day "
           "afterwards when Talon is listening. The number you pick stays part "
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
    ("It never fires", "No pattern names silence, and Talon drops quiet frames "
                       "on power before the model is even asked. That gate is "
                       "what stops quiet triggering things, not this class."),
    ("Include all", "Every quiet frame. Usually several times your largest "
                    "sound."),
    ("Balanced", "One sound's ration. The default."),
    ("Omit", "No silence class. Pair it with a recorded background sound (a "
             "fan, talking) so real noise still has somewhere harmless to land."),
    ("Which is best", "Unmeasured. Balanced is the default because it does the "
                      "same job for far less of the run."),
)


# ---- integrations -------------------------------------------------------

CONNECT_ROWS = (
    ("What", "Talon (talonvoice.com) runs your model live and maps each "
             "sound to an action."),
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

PATTERN_ROWS = (
    ("patterns.json", "Maps the model's sounds to the named triggers your "
                      ".talon files bind actions to. The Integrations tab "
                      "edits it with validation and keeps a snapshot of every "
                      "deploy."),
    ("What a pattern holds", None),
    ("sounds", "Which model sounds count toward it. Their probabilities are "
               "summed."),
    ("threshold", "Rules that must <i>all</i> pass for a frame to fire: "
                  "<code>&gt;probability</code> (summed confidence, 0-1), "
                  "<code>&gt;power</code> (loudness), "
                  "<code>&gt;f0/f1/f2</code> (pitch and formants in Hz, to "
                  "tell a high hiss from a low one), each also available as "
                  "<code>&lt;</code>."),
    ("throttle", "After firing, silence the listed patterns - itself "
                 "included - for N seconds. Targets are pattern names, never "
                 "sound names."),
    ("graceperiod", "Right after a detection, softer rules apply for N "
                    "seconds, so a sound you are holding does not stutter as "
                    "its probability wobbles."),
    ("detect_after", "The rules must hold this long before the first fire, "
                     "which turns a pop into a hold-to-activate."),
)

PATTERN_NOTE = ("<p>The Live and Captures views show the real power and "
                "probability your sounds produce - the numbers to judge a "
                "threshold against. Those are Talon-engine units, not the "
                "dBFS used elsewhere here.</p>")


# ---- the program itself -------------------------------------------------

DATA_ROWS = (
    ("Recordings", "<code>data/recordings/</code>, one folder per sound: the "
                   "source <code>.wav</code> plus a <code>.srt</code> marking "
                   "where the sound occurs."),
    ("Models", "<code>data/models/</code>. A trained model is a single "
               "<code>.pkl</code> carrying its own nets."),
    ("Notes", "<code>data/notes.json</code>, global and per model."),
    ("Profiles", "A profile is a whole separate data folder - its own "
                 "recordings, models and notes. Use one per person, mic or "
                 "experiment. Switch from the toolbar chip; create one from "
                 "Settings. Switching relaunches the app."),
    ("Audio", f"Captured at {RATE} Hz and processed in {MS_PER_FRAME} ms "
              f"frames."),
)


# ---- the registry -------------------------------------------------------

TABS = (
    tab("overview", "Overview", None, (
        topic("how_it_works", "How Parrot works", diagram="pipeline",
              lede=TAGLINE),
        topic("speed", "Why Parrot is so much faster than voice commands",
              intro=SPEED_TEXT),
    )),
    tab("sounds", "Sounds",
        "Recording the sounds a model learns. Everything here is also on the "
        "Sounds tab, behind ?  Help.", (
            topic("sounds", "Choosing sounds", rows=SOUNDS_ROWS,
                  diagram="frames", shown_on="New sound dialog"),
            topic("record", "Recording sounds", rows=RECORD_ROWS,
                  shown_on="Sounds tab"),
            topic("detection", "Detection: what counts as sound",
                  rows=DETECTION_ROWS, shown_on="Edit recording"),
            topic("quantity", "How much data you need", intro=QUANTITY_INTRO,
                  bands=QUANTITY_BANDS, note=QUANTITY_NOTE),
            topic("quality", "Sound quality", rows=QUALITY_ROWS),
        )),
    tab("models", "Models",
        "Turning recordings into a model. Also on the Models tab and the "
        "training screen.", (
            topic("train", "Training a model", rows=TRAIN_ROWS,
                  shown_on="Models tab"),
            topic("labels", "How it picks a sound", diagram="closed_set",
                  note=CLOSED_SET_NOTE),
            topic("nets", "Neural networks", rows=NET_ROWS, diagram="nets",
                  shown_on="Training setup"),
            topic("balance", "Balancing the data", rows=BALANCE_ROWS,
                  diagram="balance_legend", shown_on="Training setup"),
        )),
    tab("integrations", "Integrations",
        "Running a trained model live. Also on the Integrations tab.", (
            topic("connect", "Connecting to Talon", rows=CONNECT_ROWS,
                  shown_on="Integrations tab"),
            topic("patterns", "Patterns", rows=PATTERN_ROWS,
                  note=PATTERN_NOTE),
        )),
    tab("about", "About", "The program itself.", (
        topic("data", "Where your data lives", rows=DATA_ROWS),
    )),
)

# Every topic by key. Keys are the app-wide handle for a piece of help -
# help_button(self, "record") - so they outlive whichever tab a topic sits in.
TOPICS = {t["key"]: t for tb in TABS for t in tb["topics"]}

# What the training screen teaches inline, in its own order. Same topics, so
# editing one fixes both.
TRAINING_TOPICS = ("labels", "balance", "nets")


def get(key):
    return TOPICS[key]


def title(key):
    return TOPICS[key]["title"]
