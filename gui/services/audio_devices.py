"""Session-global device selection, set by the device toolbar.

- input_index: the primary mic - drives the live recording UI
- extra_input_indices: additional mics recorded simultaneously (own file + SRT
  per mic, same take timestamp - matches the terminal recorder's multi-mic)
- output_index: playback device; sd.play() follows sd.default

Picks persist to the same user config the Settings page writes. Device
indices can shift when hardware changes; invalid saved picks are dropped.
"""
import sounddevice as sd
from config.config import INPUT_DEVICE_INDEX
from gui.services import user_config


def _device(index, key):
    try:
        dev = sd.query_devices(index)
        return dev if dev.get(key, 0) > 0 else None
    except Exception:
        return None


_saved = user_config.read_user_config()

input_index = INPUT_DEVICE_INDEX
try:
    output_index = sd.default.device[1]
except Exception:
    output_index = None

_saved_out = _saved.get("OUTPUT_DEVICE_INDEX")
if _saved_out is not None and _device(_saved_out, "max_output_channels"):
    output_index = _saved_out

extra_input_indices = [
    i for i in _saved.get("EXTRA_INPUT_DEVICE_INDICES", [])
    if i != input_index and _device(i, "max_input_channels")
]

try:
    sd.default.device = (input_index, output_index)
except Exception:
    pass


def _persist(updates):
    try:
        user_config.write_user_config(updates)
    except Exception:
        pass


def set_input(index):
    global input_index, extra_input_indices
    input_index = index
    if index in extra_input_indices:
        extra_input_indices = [i for i in extra_input_indices if i != index]
        _persist({"INPUT_DEVICE_INDEX": index,
                  "EXTRA_INPUT_DEVICE_INDICES": extra_input_indices})
    else:
        _persist({"INPUT_DEVICE_INDEX": index})
    try:
        sd.default.device = (index, output_index)
    except Exception:
        pass


def set_output(index):
    global output_index
    output_index = index
    _persist({"OUTPUT_DEVICE_INDEX": index})
    try:
        sd.default.device = (input_index, index)
    except Exception:
        pass


def set_extras(indices):
    global extra_input_indices
    extra_input_indices = [i for i in indices if i != input_index]
    _persist({"EXTRA_INPUT_DEVICE_INDICES": extra_input_indices})


def input_name(index):
    dev = _device(index, "max_input_channels")
    return dev["name"] if dev else f"device {index}"


def recording_mics():
    """(primary, extras) - what a recording session should capture."""
    return input_index, list(extra_input_indices)
