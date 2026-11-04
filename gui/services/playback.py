import threading
import time

import numpy as np
import sounddevice as sd

_CHUNK = 256


class PlaybackError(Exception):
    pass


class _Player:
    def __init__(self):
        self._lock = threading.Lock()
        self._token = None
        self._thread = None

    def play(self, samples, sample_rate):
        self.stop()
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
        with self._lock:
            self._token = None

    def shutdown(self):
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
                deadline = time.monotonic() + stream.latency + 0.02
                while self._token is token and time.monotonic() < deadline:
                    time.sleep(0.01)
        except Exception:
            pass
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
