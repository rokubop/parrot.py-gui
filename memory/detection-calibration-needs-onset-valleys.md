---
name: detection-calibration-needs-onset-valleys
description: Auto-thresholding emits zero events until 10+ spectral-flux valleys exist, so synthetic or too-uniform audio silently produces an empty srt; the manual override path is the deterministic one
type: project
---

`determine_detection_state` (`lib/stream_processing.py`) only sets a dBFS
threshold once onset detection has produced **10+ spectral-flux valleys**;
until then `upper_bound_dBFS_threshold` stays `0` and the whole file yields an
empty srt with no error. Real recordings clear the bar; synthetic noise bursts
sit close enough to the edge that detection succeeded or failed *by RNG seed*.

This also closes the 2026-07-25 mystery of hand-built fixtures segmenting to
zero: it was never the strategy's minimum-length rule, it was calibration
never engaging.

**How to apply:** for generated or degenerate audio, skip calibration
entirely - write a thresholds file (`<label>_duration_type=discrete`,
`<label>_min_dbfs=-30`) and call `process_wav_file(..., override_file=...)`,
the same path a user's manual threshold takes. `gui/services/mock_states.py`
does this. Also: `segment_worker.redetect` derives its output paths from the
**active** data root, so anything writing into another profile's tree must
pass paths to `process_wav_file` explicitly.
