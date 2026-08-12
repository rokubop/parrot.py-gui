"""Session-global device selection, set by the device toolbar.

- input_index: the primary mic - drives the live recording UI
- extra_input_indices: additional mics recorded simultaneously (own file + SRT
  per mic, same take timestamp - matches the terminal recorder's multi-mic)
- output_index: playback device; sd.play() follows sd.default

Picks persist to the same user config the Settings page writes. Device
indices can shift when hardware changes; invalid saved picks are dropped.

`rescan()` is what sees hardware plugged in after launch - see its docstring.
"""
import sounddevice as sd
from config.config import INPUT_DEVICE_INDEX
from gui.services import playback, user_config


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


# ---- rescan --------------------------------------------------------------

def _describe(index, key):
    """(name, hostapi) for a pick, so it can be found again at a new index."""
    dev = _device(index, key)
    return (dev["name"], dev.get("hostapi")) if dev else None


def _resolve(described, key):
    """The index `described` sits at now, or None if it is gone.

    Names repeat across host APIs, so the API is matched first; a device that
    moved between APIs still resolves on name alone.
    """
    if described is None:
        return None
    name, api = described
    try:
        devices = list(sd.query_devices())
    except Exception:
        return None
    candidates = [i for i, d in enumerate(devices)
                  if d["name"] == name and d.get(key, 0) > 0]
    for i in candidates:
        if devices[i].get("hostapi") == api:
            return i
    return candidates[0] if candidates else None


def _reinitialize():
    """Tear PortAudio down and bring it back up. False if it is now down."""
    try:
        sd._terminate()
    except Exception:
        return False          # never torn down, so nothing is broken
    try:
        sd._initialize()
    except Exception:
        try:
            sd._initialize()  # down with no PortAudio is fatal; one more go
        except Exception:
            return False
    return True


def rescan():
    """Re-enumerate the hardware.

    PortAudio takes its device list once, at Pa_Initialize, so a mic plugged in
    after launch stays invisible however many times a picker re-queries. Only a
    terminate/initialize cycle sees it - about 340 ms on Windows with 183
    devices, which is why this is a button and not something done on every view.

    That cycle is undefined behaviour with a stream open. Playback is stopped
    here; callers must not offer this while recording.

    Indices shift underneath, so the current picks are re-resolved by name and
    persisted at their new ones - which also repairs a saved index that hardware
    changes had already moved.
    """
    global input_index, output_index, extra_input_indices

    playback.shutdown()

    want_in = _describe(input_index, "max_input_channels")
    want_out = _describe(output_index, "max_output_channels")
    want_extras = [_describe(i, "max_input_channels")
                   for i in extra_input_indices]

    if not _reinitialize():
        return

    # A pick whose device is gone falls back to whatever PortAudio now calls
    # default, rather than to an index that is some other machine's mic.
    try:
        fallback_in, fallback_out = sd.default.device
    except Exception:
        fallback_in, fallback_out = None, None

    resolved_in = _resolve(want_in, "max_input_channels")
    resolved_out = _resolve(want_out, "max_output_channels")
    input_index = resolved_in if resolved_in is not None else fallback_in
    output_index = resolved_out if resolved_out is not None else fallback_out
    extra_input_indices = [
        i for i in (_resolve(w, "max_input_channels") for w in want_extras)
        if i is not None and i != input_index]

    try:
        sd.default.device = (input_index, output_index)
    except Exception:
        pass
    _persist({"INPUT_DEVICE_INDEX": input_index,
              "OUTPUT_DEVICE_INDEX": output_index,
              "EXTRA_INPUT_DEVICE_INDICES": extra_input_indices})


def recording_mics():
    """(primary, extras) - what a recording session should capture."""
    return input_index, list(extra_input_indices)
