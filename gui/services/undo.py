"""Snapshot-based undo/redo for a single recording's files.

Audacity affords cheap deep undo via immutable block files; we don't have that,
but parrot clips are short, so we just snapshot the clip's files before each
destructive edit and restore them on undo. A snapshot is a copy of every file
belonging to the recording (the source wav + its segment-side srt/thresholds),
so restoring is exact regardless of which files an op added or removed.

Session/clip-scoped, like Audacity: bound to one clip, cleared when you switch
clips or leave. Snapshots live in a temp dir and are removed on clear().
"""
import os
import shutil
import tempfile

from gui.services import library_ops


class UndoHistory:
    def __init__(self, limit=15):
        self._root = None
        self.wav_path = None
        self._undo = []   # list of snapshots (pre-op states), oldest first
        self._redo = []
        self._limit = limit

    def bind(self, wav_path):
        """Point at a clip. Switching clips resets the history."""
        if wav_path == self.wav_path:
            return
        self.clear()
        self.wav_path = wav_path

    # ---- snapshot capture / restore -----------------------------------

    def _ensure_root(self):
        if self._root is None:
            self._root = tempfile.mkdtemp(prefix="parrot_undo_")

    def _capture(self):
        self._ensure_root()
        snapdir = tempfile.mkdtemp(dir=self._root)
        manifest = []
        for f in library_ops.recording_sibling_files(self.wav_path):
            name = os.path.basename(f)
            try:
                shutil.copy2(f, os.path.join(snapdir, name))
                manifest.append((name, f))   # remember the exact origin path
            except OSError:
                pass
        return (snapdir, manifest)

    def _restore(self, snap):
        snapdir, manifest = snap
        # Remove whatever's there now, then lay the snapshot back exactly.
        for f in library_ops.recording_sibling_files(self.wav_path):
            try:
                os.remove(f)
            except OSError:
                pass
        for name, dest in manifest:
            try:
                shutil.copy2(os.path.join(snapdir, name), dest)
            except OSError:
                pass

    def _drop(self, snap):
        shutil.rmtree(snap[0], ignore_errors=True)

    # ---- public API ----------------------------------------------------

    def checkpoint(self):
        """Record the current state BEFORE an edit, so it can be undone to."""
        if not self.wav_path:
            return
        self._undo.append(self._capture())
        while len(self._undo) > self._limit:
            self._drop(self._undo.pop(0))
        for snap in self._redo:
            self._drop(snap)
        self._redo = []

    def discard_last_checkpoint(self):
        """Drop the most recent checkpoint without restoring it — used when the
        op it was taken for ended up failing (no real change)."""
        if self._undo:
            self._drop(self._undo.pop())

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self):
        if not self._undo:
            return False
        self._redo.append(self._capture())   # so redo can come back here
        self._restore(self._undo.pop())
        return True

    def redo(self):
        if not self._redo:
            return False
        self._undo.append(self._capture())
        self._restore(self._redo.pop())
        return True

    def clear(self):
        if self._root:
            shutil.rmtree(self._root, ignore_errors=True)
        self._root = None
        self._undo = []
        self._redo = []

    def cleanup(self):
        self.clear()
        self.wav_path = None
