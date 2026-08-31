from config.config import FORMAT

def open_input_stream(
        audio, device_index, *, rate, channels, record_seconds,
        sliding_window_amount, callback=None):
    """Open a microphone stream, for recording, listening or probing a device."""
    return audio.open(
        format=FORMAT,
        channels=channels,
        rate=rate,
        input=True,
        input_device_index=device_index,
        frames_per_buffer=round(rate * record_seconds / sliding_window_amount),
        stream_callback=callback)
