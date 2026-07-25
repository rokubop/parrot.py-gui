---
name: no-live-stream-splicing
description: Every audio edit happens on a saved file, never on the running capture - a take is one growing WAV that later segments append onto
type: project
---

A recording is just a file when you are not live, so **all editing happens on
saved clips**. There is no mid-stream splicing anywhere.

How the record/review/edit loop achieves that without feeling modal: a "take" is
a single growing WAV. Each Record→Pause captures a *segment*; the first segment
becomes the take and later ones are appended onto it (`AppendWorker`). While
paused you are looking at the whole take in the same interactive preview widget
the read-only library uses, so play, scrub, select and Delete (`TrimWorker`) all
operate on a static file. The take is a real file in the sound from the first
segment on, so nothing is ever lost by stopping.

Undo is **snapshot-based** (`gui/services/undo.py`): the clip's files (wav +
srt/thresholds) are copied before each destructive edit and restored on undo,
rather than modelling inverse operations. Because in-clip edits are undoable,
their type-to-confirm dialogs were dropped; two-step confirms remain only for
the non-undoable whole-recording / sound / model deletes.

**Why:** Splicing a live capture is where this class of app corrupts user data,
and the recordings are the expensive thing here - hours of someone's time that
cannot be regenerated.

**How to apply:** Any new editing feature should operate on a file and go
through the worker + snapshot path. Re-detection runs over the whole take after
each segment or edit, which is fine for short takes and would need revisiting
for very long ones.

Related: [[two-pass-detection-is-file-only]]
