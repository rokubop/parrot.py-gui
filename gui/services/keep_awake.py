"""Hold off system sleep for the length of a training run.

A sleep timer firing two hours into a 4-6 hour unattended run is the worst
failure the app has.

- Windows: ``SetThreadExecutionState``, per thread. The assertion dies with
  the thread that made it, so start and stop both belong on the GUI thread.
- macOS: ``caffeinate``. Linux: ``systemd-inhibit`` around ``tail --pid``.

System sleep only, never the display. Both subprocesses end with our pid, so
a crash can't leave a machine that refuses to sleep. Nothing here beats a lid
close, which is why the UI still says so.
"""
import atexit
import os
import shutil
import subprocess
import sys

# ES_CONTINUOUS marks the state as sticky rather than a one-shot nudge;
# ES_SYSTEM_REQUIRED is the system-sleep half on its own (ES_DISPLAY_REQUIRED
# is the one deliberately not asked for).
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001

_live = set()   # every holder still asserting, for the atexit sweep


def supported() -> bool:
    return unavailable_reason() is None


def unavailable_reason() -> str | None:
    """Why sleep cannot be held off here, phrased for a tooltip. None when it
    can."""
    if sys.platform == "win32":
        return None
    if sys.platform == "darwin":
        if shutil.which("caffeinate"):
            return None
        return "caffeinate was not found, so sleep cannot be held off here."
    if not shutil.which("systemd-inhibit"):
        return ("systemd-inhibit was not found, so sleep cannot be held off "
                "here.")
    if not shutil.which("tail"):
        return "tail was not found, so sleep cannot be held off here."
    return None


class KeepAwake:
    """One assertion, held between start() and stop(). Both are safe to call
    twice - the training page calls stop() from more than one ending."""

    def __init__(self, why: str = "Training a model"):
        self.why = why
        self._proc = None
        self._held = False

    @property
    def active(self) -> bool:
        return self._held

    def start(self) -> bool:
        """True if sleep is now being held off. False means the platform said
        no - callers should carry on with the run either way."""
        if self._held:
            return True
        try:
            ok = self._assert()
        except Exception:
            # Never worth failing a run over. Worst case the machine sleeps.
            ok = False
        if ok:
            self._held = True
            _live.add(self)
        return ok

    def stop(self) -> None:
        if not self._held:
            return
        self._held = False
        _live.discard(self)
        try:
            self._release()
        except Exception:
            pass

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

    # ---- per platform ----------------------------------------------------

    def _assert(self) -> bool:
        if sys.platform == "win32":
            import ctypes
            k32 = ctypes.windll.kernel32
            k32.SetThreadExecutionState.argtypes = [ctypes.c_uint]
            k32.SetThreadExecutionState.restype = ctypes.c_uint
            # Returns the previous state, or 0 for failure.
            return k32.SetThreadExecutionState(
                _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED) != 0

        if not supported():
            return False
        pid = os.getpid()
        if sys.platform == "darwin":
            # -i idle sleep, -s system sleep on AC, -w so it dies with us.
            cmd = ["caffeinate", "-i", "-s", "-w", str(pid)]
        else:
            # The lock lasts only as long as the child, which ends with us.
            cmd = ["systemd-inhibit", "--what=idle:sleep",
                   "--who=parrot.py", f"--why={self.why}", "--mode=block",
                   "tail", f"--pid={pid}", "-f", os.devnull]
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL)
        return True

    def _release(self) -> None:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(
                ctypes.c_uint(_ES_CONTINUOUS))
            return
        proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


@atexit.register
def _release_all():
    for holder in list(_live):
        holder.stop()
