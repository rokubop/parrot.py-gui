"""The program itself: where its files live.

Copy only. Edited here, drawn by `gui.widgets.help_dialog`.
"""
from config.config import RATE
from gui.content import tab, topic, MS_PER_FRAME

# The one-line version, for the Home button and the Settings backup note.
# Keep the list in step with DATA_ROWS below.
DATA_FOLDER_SHORT = ("Everything you make, in one folder: sounds, models, "
                     "patterns, settings, notes. Copy it anywhere, or make it "
                     "a git repo, and you have all of it.")

# A profile is a whole data folder, and user settings live inside it
# (data/code/config.py), so switching profiles switches settings too.
PROFILE_SHORT = ("A complete separate setup: sounds, models, notes and "
                 "settings kept apart. Switching restarts the app, about a "
                 "second.")

DATA_ROWS = (
    ("Recordings", "<code>data/recordings/</code>, one folder per sound: the "
                   "source <code>.wav</code> plus a <code>.srt</code> marking "
                   "where the sound occurs."),
    ("Models", "<code>data/models/</code>. A trained model is a single "
               "<code>.pkl</code> carrying its own nets."),
    ("Patterns", "<code>data/talon/</code>, alongside the snapshot taken on "
                 "every deploy."),
    ("Settings", "<code>data/code/config.py</code>. Anything set in Settings "
                 "is written here, which is why it is per profile."),
    ("Notes", "<code>data/notes.json</code>, global and per model."),
    ("Profiles", PROFILE_SHORT + " Use one per person, mic or experiment. "
                 "Switch from the toolbar chip; create one from Settings."),
    ("Backup", DATA_FOLDER_SHORT),
    ("Audio", f"Captured at {RATE} Hz and processed in {MS_PER_FRAME} ms "
              f"frames."),
)


TAB = tab("program", "About", "The program itself.", (
    topic("data", "Where your data lives", rows=DATA_ROWS,
          short=DATA_FOLDER_SHORT),
))
