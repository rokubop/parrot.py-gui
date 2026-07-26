---
name: gui-omits-define-settings
description: The GUI deliberately skips the CLI's define_settings prompt - four of its five values describe how the audio was already recorded, so overriding them builds a broken model
type: project
---

The CLI opens training with `define_settings(...)`; the GUI calls
`get_current_default_settings()` directly. **This is deliberate - do not "restore
parity" by surfacing it.**

Four of the five values are not training options, they describe audio already on
disk. `RATE` / `CHANNELS` are fixed by the recorder at 16 kHz mono, and entering
another value resamples nothing: it writes that number into the model and
inference then extracts features on a false assumption. `RECORD_SECONDS` /
`SLIDING_WINDOW_AMOUNT` *are* the 15 ms detection frame the SRTs were segmented
with, so changing them desyncs the model from its own training samples. Only
`FEATURE_ENGINEERING_TYPE` is a genuine per-model choice.

The prompt predates there being a recorder that fixes these values. Note BACKLOG
proposes a read-only summary with an Advanced override; that is the most it
should ever become.

Related: [[audio-rate-is-16khz]]
