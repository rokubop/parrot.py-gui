---
name: gui-omits-define-settings
description: The GUI deliberately skips the CLI's define_settings prompt - four of its five values describe how the audio was recorded, so overriding them builds a broken model
type: project
---

The CLI opens training with `settings = define_settings(get_current_default_settings())`
(`learn_data.py:29`). The GUI calls `get_current_default_settings()` directly
(`training_worker.py`), skipping that prompt entirely. This is deliberate, and
the recurring question "the CLI has more options, what is the GUI missing?"
resolves here.

`define_settings` exposes five values: `RATE`, `CHANNELS`, `RECORD_SECONDS`,
`SLIDING_WINDOW_AMOUNT`, `FEATURE_ENGINEERING_TYPE`. **Four of them are not
training options - they describe how the audio on disk was already recorded**,
and the prompt lets you assert things about your data that are not true:

- `RATE` / `CHANNELS` are fixed by the recorder at 16 kHz mono. Entering another
  value resamples nothing; it writes that number into the model, and
  `machinelearning.py` reads the settings back at inference and extracts
  features on the wrong assumption. That is the mismatch behind the mfsc crash
  in [[audio-rate-is-16khz]].
- `RECORD_SECONDS` / `SLIDING_WINDOW_AMOUNT` *are* the 15 ms detection frame the
  SRTs were segmented with. Changing them at train time desyncs the model from
  the segmentation that produced its own training samples.

`FEATURE_ENGINEERING_TYPE` is the one genuine per-model choice and is read back
correctly at inference, so it would not break anything - it is simply expert
surface with no guidance a GUI user could act on.

Algorithm choice is the other CLI-only option, also correctly omitted: Audio Net
is what Talon requires (`learn_data.py:39`).

Everything else the CLI asks, the GUI has. On sound selection the GUI is
strictly better - the CLI's `[S]kip` does `break`, silently dropping every
remaining sound, while the checklist is explicit.

**How to apply:** Do not "restore parity" by surfacing these in the GUI. The
prompt predates there being a recorder that fixes these values; it is a footgun
inherited from when parrot was a personal script, not a feature the GUI lacks.
