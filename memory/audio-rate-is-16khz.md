---
name: audio-rate-is-16khz
description: RATE is 16000 - the rate the whole parrot ecosystem runs on; 48 kHz was tried and reverted
type: project
---

`RATE = 16000` in `lib/default_config.py`. This is the rate the whole parrot
ecosystem runs on, including existing recordings, published models, and the
Talon side. A move to 48 kHz was made and then reverted (`ffe171c`, "RATE back
to 16000").

**The mfsc crash is fixed, and was a symptom of the mismatch.** While `RATE` was
48000, `process_wav_file` crashed on the (16 kHz) existing recordings in the mfsc
framing rather than the resample path, which also blocked GUI re-detection on
real data. Reverting to 16000 resolved it - 16 kHz recordings process natively,
verified two-pass end to end on real recordings, and the handful of 48 kHz files
recorded during that period downsample on read.

**How to apply:** Do not "modernise" the sample rate. If a resampling change is
ever needed, it has to account for every already-recorded WAV and every trained
model, not just the capture path.

Related: [[two-pass-detection-is-file-only]]
