"""Preview playback that survives a busy UI thread.

`sd.play()` runs its callback in Python, so every buffer needs the GIL, and
playhead repaints hold the main thread long enough for the callback to miss
its deadline - playback crackles. PortAudio's blocking `write()` buffers in C,
so writing happens on a worker thread; nothing Python sits in the audio path.

One stream at a time: starting a clip replaces whatever was playing, on the
default output device.

Buffering stays as small as CoreAudio allows (~133 ms at 16 kHz): larger blocks
are audible lag. `play()` returns the stream's real latency so callers
can hold their playhead back by it.
"""
import threading
import time

import numpy as np
import sounddevice as sd

_CHUNK = 256   # frames per write: stop() takes effect within one


class PlaybackError(Exception):
    """The output device could not be opened."""


class _Player:
    def __init__(self):
        self._lock = threading.Lock()
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
        # The old writer may still be closing its stream
        self._join_writer()
        if samples is None or not sample_rate or len(samples) == 0:
            return 0.0
        try:
            stream = sd.OutputStream(samplerate=sample_rate, channels=1,
                                     dtype="float32", blocksize=0,
                                     latency="low")
        except Exception as exc:
            raise PlaybackError(str(exc)) from exc
        try:
            stream.start()
        except Exception as exc:
            stream.close(ignore_errors=True)
            raise PlaybackError(str(exc)) from exc
        token = object()
        worker = threading.Thread(target=self._run, args=(samples, stream, token),
                                  daemon=True)
        with self._lock:
            self._token = token
            self._thread = worker
        worker.start()
        return float(stream.latency)

    def stop(self):
        """Cut playback, without draining what PortAudio has buffered. The
        writer aborts its own stream between writes: aborting from here while
        it is inside write() crashes on Windows MME."""
        with self._lock:
            self._token = None

    def shutdown(self):
        """Stop, and wait for the writer to leave PortAudio. Call before
        quitting: the writer is a daemon thread, and tearing the interpreter
        down while it is inside stream.write() segfaults."""
        self.stop()
        self._join_writer()

    def _join_writer(self):
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
                # Ran to the end. Closing discards what is still buffered, so
                # wait that out. A sleep, not stream.stop(), so stop() can cut in
                deadline = time.monotonic() + stream.latency + 0.02
                while self._token is token and time.monotonic() < deadline:
                    time.sleep(0.01)
        except Exception:
            pass                    # device vanished, etc.
        finally:
            with self._lock:
                if self._token is token:
                    self._token = None
            stream.abort(ignore_errors=True)
            stream.close(ignore_errors=True)


_player = _Player()

play = _player.play
stop = _player.stop
shutdown = _player.shutdown
