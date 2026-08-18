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

# Every user data path derives from DATA_DIR; see lib/data_root.py.
from lib.data_root import DATA_ROOT, PROFILES_DIR, DATA_DIR
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

# On save/reprocess, settle thresholds over the whole recording and re-judge
# every frame; the online pass needs ~10 sounds before thresholds stabilize.
TWO_PASS_DETECTION = True