from importlib.util import find_spec
import os
import sys

import numpy as np

try:
    import sounddevice as sd
except ImportError:
    raise SystemExit(
        "Parrot records audio through sounddevice.\n"
        "Update your environment with: pip install -r requirements-" +
        ("windows" if sys.platform == "win32" else "posix") + ".txt")
except OSError as error:
    # sounddevice needs PortAudio itself at run time. Its wheel carries a copy
    # on Windows and macOS, so only Linux can arrive here.
    raise SystemExit(
        "sounddevice could not load PortAudio: " + str(error) + "\n"
        "On Debian and Ubuntu: sudo apt-get install libportaudio2")

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
    default_audio = sd.query_devices(kind="input")
except (sd.PortAudioError, ValueError):
    default_audio = None
REPEAT_DELAY = 0.5
REPEAT_RATE = 33
SPEECHREC_ENABLED = False

FORMAT = "int16"
SAMPLE_WIDTH = np.dtype(FORMAT).itemsize
CHANNELS = 1
# Every existing recording and trained model assumes 16000. Recordings at
# other rates are resampled to RATE on read.
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

# DATA_DIR also follows the active profile; see lib/data_root.py.
from lib.data_root import DATA_ROOT, PROFILES_DIR, DATA_DIR
DATASET_FOLDER = DATA_DIR + "/recordings"
RECORDINGS_FOLDER = DATA_DIR + "/recordings"
REPLAYS_FOLDER = DATA_DIR + "/replays"
REPLAYS_AUDIO_FOLDER = DATA_DIR + "/replays/audio"
REPLAYS_FILE = REPLAYS_FOLDER + "/run.csv"
CLASSIFIER_FOLDER = DATA_DIR + "/models"
CODE_FOLDER = DATA_DIR + "/code"
# Ships with parrot, not user data
OVERLAY_FOLDER = "data/overlays"
COORDINATE_FILEPATH = "config/current-coordinate.txt"
CONVERSION_OUTPUT_FOLDER = DATA_DIR + "/output"
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
SILENCE_TRAINING_MODE = "all" # how much silence is used in training - "all", "balanced", "none"
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

# On save/reprocess, settle thresholds over the whole recording and re-judge
# every frame; the online pass needs ~10 sounds before thresholds stabilize.
TWO_PASS_DETECTION = True