"""Helpers for doing work later, so the window keeps up with input."""
from PyQt6.QtCore import QTimer


def debounced(fn, wait_ms, owner):
    """Useful to prevent rapid inputs from calling expensive renders,
    e.g. held arrow key or scroll zoom. fn runs once after last wait_ms.

    Arguments are dropped. Can use .cancel() to skip pending call. Timer is
    deleted with owner.
    """
    timer = QTimer(owner)
    timer.setSingleShot(True)
    timer.setInterval(wait_ms)
    timer.timeout.connect(fn)

    def call(*_args):
        timer.start()   # restarts the wait if it's already running

    call.cancel = timer.stop
    return call


def staggered(fn, owner):
    """Returns run(items), which calls fn on each item, one per event loop
    tick, so the window stays responsive. run.cancel() skips the rest.

    The timer is deleted along with owner.
    """
    timer = QTimer(owner)
    timer.setSingleShot(True)
    timer.setInterval(0)    # the next tick, once waiting input and repaints are done
    pending = []

    def next_item():
        if pending:
            fn(pending.pop(0))
        if pending:
            timer.start()

    timer.timeout.connect(next_item)

    def run(items):
        pending[:] = items
        timer.start()

    def cancel():
        timer.stop()
        pending.clear()

    run.cancel = cancel
    return run
