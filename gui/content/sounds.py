"""The Sounds tab: choosing sounds, recording them, and what detection
does with them.

Copy only. Edited here, drawn by `gui.widgets.help_dialog`.
"""
from gui.content import (tab, topic, MS_PER_FRAME, MIN_TRAIN_SECONDS,
                         GOOD_TRAIN_SECONDS, SUFFICIENT_S, GOOD_S,
                         EXCELLENT_S)
from config.config import (CURRENT_DETECTION_STRATEGY,
                           THRESHOLD_DETECTION)

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

TWO_PASS_SHORT = (
    "Thresholds calibrate as you record and need ~10 sounds to settle. "
    "Two-pass re-judges the whole take with the settled numbers when it is "
    "saved, so the start is segmented as well as the end. A manual threshold "
    "beats both.")

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


TAB = tab("sounds", "Sounds",
          "Recording the sounds a model learns. Everything here is also on "
          "the Sounds tab, behind ?  Help.", (
    topic("sounds", "Choosing sounds", rows=SOUNDS_ROWS, diagram="frames",
          short="Which noises work as triggers, and which fight with speech.",
          shown_on="New sound dialog"),
    topic("record", "Recording sounds", rows=RECORD_ROWS,
          short=f"Record each sound until it rates Excellent. "
                f"{MIN_TRAIN_SECONDS}s is the minimum, ~80s is plenty.",
          shown_on="Sounds tab"),
    topic("detection", "Detection: what counts as sound", rows=DETECTION_ROWS,
          short=TWO_PASS_SHORT, shown_on="Edit recording"),
    topic("quantity", "How much data you need", intro=QUANTITY_INTRO,
          bands=QUANTITY_BANDS, note=QUANTITY_NOTE,
          short=f"Detected sound per label. Under {MIN_TRAIN_SECONDS}s is "
                f"too little; around {GOOD_TRAIN_SECONDS}s is where a model "
                f"starts being usable."),
    topic("quality", "Sound quality", rows=QUALITY_ROWS,
          short="How far your sound stands above the room."),
))
