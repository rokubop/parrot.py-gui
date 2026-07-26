from importlib.util import find_spec
import os
import sys

import numpy as np
import sounddevice as sd

if sys.platform == "darwin":
    # This is necessary to import before pyautogui
    # See https://github.com/asweigart/pyautogui/issues/495#issuecomment-778241850
    import AppKit

try:
    import pyautogui
    pyautogui.FAILSAFE = False
except Exception:
    pyautogui = None

try:
    default_audio = sd.query_devices(kind='input')
except sd.PortAudioError:
    default_audio = None
REPEAT_DELAY = 0.5
REPEAT_RATE = 33
SPEECHREC_ENABLED = False

FORMAT = np.int16
SAMPLE_WIDTH = 2  # 16-bit = 2 bytes
CHANNELS = 1
# 16000 is the rate the whole parrot ecosystem is built around: every
# existing recording, every trained model (the pkl settings say RATE: 16000),
# and Talon's feature extraction for those models. Changing it silently
# desyncs training features from Talon inference and breaks processing of
# existing 16 kHz recordings — recordings at other rates are resampled to
# RATE on read instead.
RATE = 16000
CHUNK = 1024
RECORD_SECONDS = 0.03
TEMP_FILE_NAME = "play.wav"
PREDICTION_LENGTH = 10
SILENCE_INTENSITY_THRESHOLD = 400
INPUT_DEVICE_INDEX = sd.default.device[0] if sd.default.device[0] is not None else 1
if (default_audio is not None):
    INPUT_DEVICE_INDEX = sd.default.device[0]

SLIDING_WINDOW_AMOUNT = 2
INPUT_TESTING_MODE = False
USE_COORDINATE_FILE = False

TYPE_FEATURE_ENGINEERING_RAW_WAVE = 1
TYPE_FEATURE_ENGINEERING_OLD_MFCC = 2
TYPE_FEATURE_ENGINEERING_NORM_MFCC = 3
TYPE_FEATURE_ENGINEERING_NORM_MFSC = 4
FEATURE_ENGINEERING_TYPE = TYPE_FEATURE_ENGINEERING_NORM_MFSC

# Every piece of user data lives under one root, so pointing it at a
# different folder makes the whole app act as a different user.
#
# The root: a checkout (a ./data dir in cwd, which .gitkeep guarantees)
# keeps today's relative paths so the CLI and existing setups never move;
# an installed app has no writable cwd, so the root is the platform
# user-data dir - the same three locations the Python bootstrap caches to.
def _default_data_root():
    if os.path.isdir("data"):
        return ""  # checkout: paths stay exactly "data/...", CLI-compatible
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "parrot.py")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/parrot.py")
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "parrot.py")


def _read_current_profile(profiles_dir):
    """data-profiles/current names the active profile so the choice survives
    a fresh launch (the switcher's env var only lives in its relaunch chain).
    A stale name (deleted profile) falls back to Main rather than erroring."""
    try:
        with open(os.path.join(profiles_dir, "current"), encoding="utf-8") as f:
            name = f.read().strip()
    except OSError:
        return None
    if name and os.path.isdir(os.path.join(profiles_dir, name)):
        return name
    return None


DATA_ROOT = _default_data_root()
PROFILES_DIR = os.path.join(DATA_ROOT, "data-profiles")

# Active data dir: explicit env override (dev / the switcher's relaunch)
# beats the persisted pointer, which beats the Main default.
_env_data_dir = os.environ.get("PARROT_DATA_DIR")
_current_profile = None if _env_data_dir else _read_current_profile(PROFILES_DIR)
if _env_data_dir:
    DATA_DIR = _env_data_dir
elif _current_profile:
    DATA_DIR = os.path.join(PROFILES_DIR, _current_profile)
else:
    DATA_DIR = os.path.join(DATA_ROOT, "data")
DATASET_FOLDER = os.path.join(DATA_DIR, "recordings")
RECORDINGS_FOLDER = DATASET_FOLDER
REPLAYS_FOLDER = os.path.join(DATA_DIR, "replays")
REPLAYS_AUDIO_FOLDER = os.path.join(REPLAYS_FOLDER, "audio")
REPLAYS_FILE = os.path.join(REPLAYS_FOLDER, "run.csv")
CLASSIFIER_FOLDER = os.path.join(DATA_DIR, "models")
OVERLAY_FOLDER = os.path.join(DATA_DIR, "overlays")
COORDINATE_FILEPATH = "config/current-coordinate.txt"
CONVERSION_OUTPUT_FOLDER = os.path.join(DATA_DIR, "output")
PATH_TO_FFMPEG = "ffmpeg/bin/ffmpeg"

DEFAULT_CLF_FILE = ""
STARTING_MODE = ""
MICROPHONE_SEPARATOR = None

SAVE_REPLAY_DURING_PLAY = True
SAVE_FILES_DURING_PLAY = False
EYETRACKING_TOGGLE = "f4"
OVERLAY_ENABLED = False

pytorch_spec = find_spec("torch")
PYTORCH_AVAILABLE = pytorch_spec is not None
IS_WINDOWS = sys.platform == 'win32'

dragonfly_spec = find_spec("dragonfly")
if( SPEECHREC_ENABLED == True ):
    SPEECHREC_ENABLED = dragonfly_spec is not None

BACKGROUND_LABEL = "silence"
AUTOMATIC_DATASET_BALANCING = True
SHOULD_FIT_INSIDE_RAM = True # Ensure the dataset fits inside RAM for faster training
# Turning this to FALSE might crash the dataloading
MAX_RAM = 7000000000 # 7GB of usable RAM is assumed to be the maximum size to be loaded in for data

# Detection strategies
CURRENT_VERSION = 3
CURRENT_DETECTION_STRATEGY = "auto_dBFS_secondary_dBFS_reject_cont_45ms_repair"

# Threshold detection strategies
# Lenient allows for more space between noises to gather a proper threshold
# Strict allows you to do rapid recordings
THRESHOLD_DETECTION = "strict" # "lenient"

# Two-pass detection: when a recording is saved or reprocessed, settle the
# thresholds over the WHOLE recording first and then re-judge every frame with
# them. The single online pass needs ~10 finished sounds before its thresholds
# stabilize, so the start of every recording was judged by weaker criteria.
TWO_PASS_DETECTION = True