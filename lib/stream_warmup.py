"""Throw away what a microphone delivers before it settles.

Opening a Bluetooth mic renegotiates the link to Hands-Free. PortAudio reports
success in 7 ms, then delivers nothing for 1.4-3 s, then two blocks clipped to
full scale with a large DC offset:

    first audio after start(): 1682.9 ms
    first 8 peaks: 32768, 32768, 1214, 134, 14, 16, 26, 26

Shokz OpenComm2, same through MME, WASAPI and DirectSound, so it is the link
and not the host API. Those frames are the loudest in the take: they anchor
the settled noise floor and read as a sound at 0:00. Wired mics show the same
shape a hundred times smaller.

The clock starts at the first frame, not at `start()`. The dead time varies
with the link and cannot be waited out in advance.
"""
import time

# Six times the longest burst measured (5 blocks, 75 ms). Nothing says
# "Recording" until it is over, so the wait is not lost time.
SECONDS = 0.25


class StreamWarmup:
    """Per-stream gate. `hold(frame)` is True while the frame should be dropped.

    One per open stream. `restart()` after any `stream.stop()`/`start()` pair,
    which renegotiates the link again.
    """

    def __init__(self, seconds=SECONDS):
        self.seconds = seconds
        self.restart()

    def restart(self):
        self._first = None
        self.ready = self.seconds <= 0

    def hold(self):
        """True while the stream is still warming up."""
        if self.ready:
            return False
        now = time.monotonic()
        if self._first is None:
            self._first = now
        if now - self._first < self.seconds:
            return True
        self.ready = True
        return False
