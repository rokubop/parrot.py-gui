"""Preview playback that survives a busy UI thread.

`sd.play()` runs its callback in Python, so every buffer needs the GIL, and
playhead repaints hold the main thread long enough for the callback to miss
its deadline - playback crackles. PortAudio's blocking `write()` buffers in C,
so writing happens on a worker thread; nothing Python sits in the audio path.

One stream at a time, matching the old `sd.play()` / `sd.stop()` behaviour:
starting a clip replaces whatever was playing. The output device follows
`sd.default`, which the device toolbar sets (see audio_devices.py).

Buffering stays as small as CoreAudio allows (~133 ms at 16 kHz): auditioning
a few frames before deciding where to cut is a core interaction, and larger
blocks are audible lag. `play()` returns the stream's real latency so callers
can hold their playhead back by it.
"""
import threading

import numpy as np
import sounddevice as sd

_CHUNK = 256   # frames per write - small enough that stop() responds promptly


class PlaybackError(Exception):
    """The output device could not be opened.

    Raised, not swallowed: a caller with no stream still starts a playhead, so
    a device that has gone away looked exactly like a successful play. A merely
    inaudible device raises nothing, which is why the picker is visible.
    """


class _Player:
    def __init__(self):
        self._lock = threading.Lock()
        self._stream = None
        self._token = None   # identity of the current play() request
        self._thread = None  # the writer, so shutdown() can wait for it

    def play(self, samples, sample_rate):
        """Start playing mono float32 `samples`; returns immediately.

        Returns the output latency in seconds - audio reaches the speakers that
        long after this call, so a playhead clocked from now must lag by it.
        The stream is opened here rather than on the worker (~5 ms) so the
        figure is exact by the time the caller starts its clock.
        """
        self.stop()
        if samples is None or not sample_rate or len(samples) == 0:
            return 0.0
        try:
            stream = sd.OutputStream(samplerate=sample_rate, channels=1,
                                     dtype="float32", blocksize=0,
                                     latency="low")
            stream.start()
        except Exception as exc:
            raise PlaybackError(str(exc)) from exc
        token = object()
        worker = threading.Thread(target=self._run, args=(samples, stream, token),
                                  daemon=True)
        with self._lock:
            self._token = token
            self._stream = stream
            self._thread = worker
        worker.start()
        return float(stream.latency)

    def stop(self):
        """Cut playback now, without draining what PortAudio has buffered."""
        with self._lock:
            self._token = None
            stream = self._stream
        # Abort rather than stop/close: aborting is safe from another thread and
        # unblocks the writer, which then owns closing the stream. Closing it
        # here could pull it out from under a write() already in flight.
        if stream is not None:
            stream.abort(ignore_errors=True)

    def shutdown(self):
        """Stop, and wait for the writer to leave PortAudio. Call before quitting.

        The writer is a daemon thread, so quitting mid-playback tore the
        interpreter down while it was inside stream.write() - a segfault on
        roughly one quit in three. stop() only asks; this waits.
        """
        self.stop()
        with self._lock:
            worker = self._thread
        if worker is not None:
            worker.join(timeout=2.0)

    def _run(self, samples, stream, token):
        try:
            for i in range(0, len(samples), _CHUNK):
                if self._token is not token:
                    break
                block = np.ascontiguousarray(samples[i:i + _CHUNK],
                                             dtype=np.float32)
                stream.write(block.reshape(-1, 1))
            else:
                stream.stop()       # ran to the end - let the tail drain
        except Exception:
            pass                    # aborted by stop(), device vanished, etc.
        finally:
            with self._lock:
                if self._token is token:
                    self._token = None
                if self._stream is stream:
                    self._stream = None
            stream.close(ignore_errors=True)


_player = _Player()

play = _player.play
stop = _player.stop
shutdown = _player.shutdown
