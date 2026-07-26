---
name: training-takes-hours
description: A full training run is 4-6 hours; the training page now measures its own ETA, and stopping early keeps the best model so far
type: project
---

**Roughly 4-6 hours** for Roku's real setup: 14 sounds, 5 nets, all 300 epochs
(`max_epochs`, `lib/audio_net.py`). Sound count, recorded volume and net count
each multiply it. The GUI help said *"Minutes, not hours"* until 2026-07-25 and
was simply wrong, so anything stating a duration should match this entry.

**The page measures the run rather than repeating that figure.** Since
2026-07-26 it shows time remaining and a finish clock, timed from the first
reported epoch so the one-off cost of loading recordings does not inflate it.
Prefer that number once a run has produced one.

Before a run starts there is only a guess:
`TRAIN_SECONDS_PER_AUDIO_SECOND_PER_NET` in `gui/windows/train_view.py`, anchored
on the figure above plus an unmeasured assumption about how much audio those 14
sounds held. **Replace it with a real value from the first completed run.**

**Stopping early is a real workflow, not an abort.** `AudioNetTrainer` saves
every time a net beats its own best accuracy, so the best-so-far checkpoint is
always on disk. Stop once the accuracy curve flattens and you keep a usable
rough model in a fraction of the time.

**The GPU may be idle for every one of those hours** - both requirements files
pin plain `torch` with no CUDA index URL, and the trainer never checks MPS. See
BACKLOG, "Training performance", for the one-line check.

Related: [[cross-pc-workflow]] · [[ship-a-thin-shell-not-a-bundle]]
