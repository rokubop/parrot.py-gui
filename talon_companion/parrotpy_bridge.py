"""Parrot.py bridge — companion module for Talon.

Installed into the Talon user directory by the Parrot.py app (Integrations →
Test integration). It observes parrot detection frames and publishes them as
UDP JSON datagrams to the app on localhost.

Idle unless the app is testing. The app touches a file in the temp dir every
couple of seconds while its test screen is open; this module polls it and only
then wraps pattern_match. Close the app, or leave that screen, and within ~6
seconds it unwraps and Talon is exactly as it was. Installed does not mean
running.

It is a pure observer whenever it is hooked up at all:

- the original ``parrot_delegate.pattern_match`` still does ALL detection —
  this module wraps it, calls it, and publishes what happened;
- every send is fire-and-forget UDP: if the app isn't running, datagrams
  vanish for free and Talon never blocks or breaks;
- every failure path is swallowed — voice control must never suffer.

Note: talon-parrot-tester replaces pattern_match with its own detection while
its overlay is open. Use one observer at a time; this bridge unhooks itself
when the app stops asking, and via ``parrotpy_bridge_disable``.

Wire format (one JSON object per datagram, all little/lossy on purpose):
  {"v": 1, "t": "hello", "version": "...", "wrapped": true, "patterns": 14,
   "modes": ["command"]}
  {"v": 1, "t": "frame", "ts": ..., "power": ..., "f0": ..., "f1": ...,
   "f2": ..., "classes": {label: probability}, "active": [...],
   "throttled": [...], "grace": [...]}
"""
import json
import os
import socket
import sys
import tempfile
import time

__version__ = "0.2.0"

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 8352
HEARTBEAT = "2s"
# Outside the Talon user dir on purpose: a file rewritten every 2 seconds in
# there would keep Talon's file watcher busy.
LISTEN_FILE = os.path.join(tempfile.gettempdir(), "parrotpy-bridge-listening")
LISTEN_TIMEOUT_S = 6.0

try:
    from talon import cron, scope, Module

    _sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    _sock.setblocking(False)
    _target = (BRIDGE_HOST, BRIDGE_PORT)

    _state = {"delegate": None, "original": None, "wrap_job": None,
              "forced": False}

    def _send(obj):
        try:
            _sock.sendto(json.dumps(obj).encode("utf-8"), _target)
        except Exception:
            pass

    def _find_delegate():
        """Find the parrot_integration module Talon already loaded (the same
        strategy talon-parrot-tester uses)."""
        for module in list(sys.modules.values()):
            if module is None:
                continue
            try:
                delegate = getattr(module, "parrot_delegate", None)
                if delegate is not None and hasattr(delegate, "pattern_match") \
                        and hasattr(delegate, "patterns"):
                    return delegate
            except Exception:
                continue
        return None

    def _make_wrapper(delegate, original):
        def pattern_match_with_bridge(frame):
            active = original(frame)
            try:
                throttled, grace = [], []
                for name, pattern in delegate.patterns.items():
                    ts = pattern.timestamps
                    if getattr(ts, "throttled_until", 0) > frame.ts:
                        throttled.append(name)
                    if getattr(ts, "graceperiod_until", 0) > frame.ts:
                        grace.append(name)
                _send({
                    "v": 1, "t": "frame",
                    "ts": frame.ts,
                    "power": round(float(frame.power), 3),
                    "f0": round(float(frame.f0), 1),
                    "f1": round(float(frame.f1), 1),
                    "f2": round(float(frame.f2), 1),
                    "classes": {k: round(float(v), 4)
                                for k, v in frame.classes.items()},
                    "active": sorted(active),
                    "throttled": throttled,
                    "grace": grace,
                })
            except Exception:
                pass
            return active
        pattern_match_with_bridge._parrotpy_bridge = True
        return pattern_match_with_bridge

    def _wrap():
        if _state["original"] is not None:
            return True
        delegate = _find_delegate()
        if delegate is None:
            return False
        original = delegate.pattern_match
        if getattr(original, "_parrotpy_bridge", False):
            return True  # already ours (e.g. after a partial reload)
        _state["delegate"] = delegate
        _state["original"] = original
        delegate.pattern_match = _make_wrapper(delegate, original)
        print(f"[parrotpy_bridge] wrapped parrot integration v{__version__}")
        return True

    def _unwrap():
        delegate, original = _state["delegate"], _state["original"]
        if delegate is not None and original is not None:
            delegate.pattern_match = original
        _state["delegate"] = None
        _state["original"] = None

    def _modes():
        """Talon's active modes, so the GUI can say "asleep" instead of
        leaving a silent screen unexplained. Read-only."""
        try:
            return sorted(scope.get("mode") or ())
        except Exception:
            return []

    def _wanted():
        """Is the app's test screen open right now?"""
        if _state["forced"]:
            return True
        try:
            return time.time() - os.path.getmtime(LISTEN_FILE) < LISTEN_TIMEOUT_S
        except OSError:
            return False

    def _tick():
        if not _wanted():
            if _state["original"] is not None:
                _unwrap()
                print("[parrotpy_bridge] detached")
            return
        if _state["original"] is None:
            _wrap()
        delegate = _state["delegate"]
        _send({
            "v": 1, "t": "hello",
            "version": __version__,
            "wrapped": _state["original"] is not None,
            "patterns": len(delegate.patterns) if delegate is not None else 0,
            "modes": _modes(),
        })

    mod = Module()

    @mod.action_class
    class Actions:
        def parrotpy_bridge_enable():
            """Publish parrot frames to Parrot.py until told otherwise"""
            _state["forced"] = True
            _wrap()

        def parrotpy_bridge_disable():
            """Stop publishing and restore the integration"""
            _state["forced"] = False
            _unwrap()

    # Attach while the app is testing, detach when it stops asking.
    cron.interval(HEARTBEAT, _tick)

except ImportError:
    # Imported outside Talon (e.g. by the GUI's install/version check) — the
    # module must parse cleanly but do nothing.
    pass
