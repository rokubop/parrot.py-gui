"""Helpers for doing work later, so the window keeps up with input."""
from PyQt6.QtCore import QTimer


def debounced(fn, wait_ms, owner):
    """fn, held back until calls stop for wait_ms. A burst of calls, like
    holding an arrow key, runs it once at the end. Arguments are dropped, so
    it can take any signal. `.cancel()` drops a pending call.

    owner is the widget the timer belongs to, so it's deleted with it.
    """
    timer = QTimer(owner)
    timer.setSingleShot(True)
    timer.setInterval(wait_ms)
    timer.timeout.connect(fn)

    def call(*_args):
        timer.start()   # restarts the wait if it's already running

    call.cancel = timer.stop
    return call
