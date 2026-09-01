import sounddevice as sd

def open_input_stream(
        device_index, *, rate, channels, record_seconds,
        sliding_window_amount, callback=None):
    """Open a microphone stream, for recording, listening or probing a device."""
    return sd.InputStream(
        samplerate=rate,
        channels=channels,
        dtype='int16',
        device=device_index,
        blocksize=round(rate * record_seconds / sliding_window_amount),
        callback=callback)
