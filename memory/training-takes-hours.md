---
name: training-takes-hours
description: A full training run is 4-6 hours, not minutes; stopping early is a supported workflow because the best checkpoint is saved on every improvement
type: project
---

**Roughly 4-6 hours** for Roku's real setup: 14 sounds, 5 nets, running all 300
epochs (`max_epochs = 300`, `lib/audio_net.py:76`). Sound count, recorded volume
and net count each multiply it, and it varies with how far you push for the last
few accuracy points.

The GUI help said *"Minutes, not hours"* until 2026-07-25 - it was simply wrong,
and got echoed into the new Models copy before Roku caught it. Anything stating a
duration should now match this entry.

**Stopping early is a real workflow, not an abort.** `AudioNetTrainer` calls
`torch.save` every time a net beats its own best accuracy (`audio_net.py:245-250`),
so the best-so-far checkpoint is always on disk. Stop once the accuracy curve
flattens and you keep a usable rough model in a fraction of the time; let it run
out when chasing the last few points. The live plot exists to make that call
visible, and `Stop` is worded and tooltipped accordingly.

**Open question - is the GPU actually being used?** The trainer selects CUDA when
`torch.cuda.is_available()` (`audio_net.py:79`), but both requirements files pin
plain `torch` from PyPI with no CUDA index URL, and on this macOS machine
`torch.version.cuda` is `None` (CPU-only build; the code does not use MPS either,
so Apple GPUs go unused regardless). If the Windows box is also on a CPU-only
wheel, those 4-6 hour runs are leaving a good GPU idle. Check on Windows with:

```
.venv\Scripts\python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
```

Related: [[cross-pc-workflow]] · [[ship-a-thin-shell-not-a-bundle]]
