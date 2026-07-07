"""UDP listener for the Talon companion bridge (see prd-talon.md, Phase C).

Binds 127.0.0.1:<port>, parses the companion's JSON datagrams, and emits
them to the UI in ~50 ms batches (per-frame signals at Talon frame rates
would swamp the event loop). Also tracks the companion heartbeat so the UI
can show Connected / Waiting.
"""
import json
import socket
import time

from PyQt6.QtCore import QThread, pyqtSignal

from gui.services.talon_companion import BRIDGE_PORT

BATCH_S = 0.05
HEARTBEAT_TIMEOUT_S = 5.0


class BridgeWorker(QThread):
    frames_received = pyqtSignal(list)     # list of frame dicts (in order)
    status_changed = pyqtSignal(dict)      # {"connected": bool, "hello": dict|None,
                                           #  "error": str|None}

    def __init__(self, port=BRIDGE_PORT, parent=None):
        super().__init__(parent)
        self.port = port
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", self.port))
            sock.settimeout(BATCH_S)
        except OSError as exc:
            self.status_changed.emit(
                {"connected": False, "hello": None,
                 "error": f"Couldn't listen on 127.0.0.1:{self.port} — {exc}"})
            return

        connected = False
        last_hello = None
        last_seen = 0.0
        batch = []
        last_emit = time.monotonic()

        while not self._stop:
            try:
                data, _addr = sock.recvfrom(65536)
                try:
                    message = json.loads(data.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue
                kind = message.get("t")
                if kind == "frame":
                    batch.append(message)
                    last_seen = time.monotonic()
                elif kind == "hello":
                    last_seen = time.monotonic()
                    if not connected or message != last_hello:
                        connected = True
                        last_hello = message
                        self.status_changed.emit(
                            {"connected": True, "hello": message, "error": None})
            except socket.timeout:
                pass

            now = time.monotonic()
            if batch and now - last_emit >= BATCH_S:
                self.frames_received.emit(batch)
                batch = []
                last_emit = now
            if connected and now - last_seen > HEARTBEAT_TIMEOUT_S:
                connected = False
                last_hello = None
                self.status_changed.emit(
                    {"connected": False, "hello": None, "error": None})

        sock.close()
