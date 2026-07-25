---
name: two-pass-detection-is-file-only
description: Files are re-judged from 0:00 with settled thresholds; live streams keep the online estimator on purpose - do not unify the two paths
type: project
---

`TWO_PASS_DETECTION = True` (`lib/default_config.py`) applies **only to things
that are files**. The pipeline runs once purely to settle thresholds over the
whole recording (`settle_detection_state`), then re-judges every frame from 0:00
with them frozen (`DetectionState.frozen`).

**The live path is deliberately untouched.** A live stream cannot know its own
future, so it keeps the online estimator; the recorder un-freezes afterwards so
CLI pause→process→resume keeps recalculating.

**Why it exists:** the auto-threshold was an online estimator even for saved
files - its upper-bound dBFS threshold stays disabled until roughly ten sounds
have finished, so the start of every recording was judged by weaker criteria,
and the repair post-pass only ever *adds* detections, never demotes
settle-period junk. Measured on synthetic and real recordings: 40/40 bursts
detected versus 39/40 with all first-quarter bursts found, and real pop events
went from 100±335 ms (multi-second outliers) to a uniform 74±20 ms with 26 more
events found.

Single-pass output was verified **byte-identical** to pre-change, and that is
the property to preserve.

**How to apply:** Do not "simplify" this into one shared code path. When
touching detection, re-check byte-identical single-pass output before and after.
`process_wav_file` takes `two_pass=False` as the opt-out.

Related: [[audio-rate-is-16khz]] · [[no-live-stream-splicing]]
