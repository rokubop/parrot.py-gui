"""The mic recordings use and the device playback goes to. For this session
only: each launch starts on the system defaults."""
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


def set_output(index):
    """Playback opens its stream on sd's default output."""
    global output_index
    output_index = index
    try:
        sd.default.device = (sd.default.device[0], index)
    except Exception:
        pass


def devices(channels_key):
    """[(index, name)] on the default host API, the others list the same
    hardware again. channels_key: "max_input_channels" or "max_output_channels"."""
    try:
        default_api = sd.default.hostapi
        return [(i, dev["name"]) for i, dev in enumerate(sd.query_devices())
                if dev.get("hostapi") == default_api and dev.get(channels_key, 0) > 0]
    except Exception:
        return []
