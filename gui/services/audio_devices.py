"""Session-global device selection, set by the device toolbar.

sd.play() and any stream that doesn't pass an explicit device follow
sd.default; recording views read input_index as their starting mic.
"""
import sounddevice as sd
from config.config import INPUT_DEVICE_INDEX

input_index = INPUT_DEVICE_INDEX
try:
    output_index = sd.default.device[1]
except Exception:
    output_index = None


def set_input(index):
    global input_index
    input_index = index
    sd.default.device = (index, output_index)


def set_output(index):
    global output_index
    output_index = index
    sd.default.device = (input_index, index)
