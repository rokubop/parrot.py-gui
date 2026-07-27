# Backlog

Open work with a longer horizon than one session. The *next* session's starting
point is the **Next steps** section of the newest entry in
[`sessions/`](sessions/README.md), not this file.

Carried over from `status.md` when it was retired on 2026-07-25. Items are
grouped by area, not prioritised beyond the first section.

## Verification owed

- **Windows pass.** The zero-install bootstrap path (`run.bat` → download
  CPython → `bootstrap.py` → launch) is written but only ever validated on
  macOS. Same for the Phase 6 preview/threading perf work - confirm the *feel*
  of switching sounds, not just that it runs.
- **Live recording on a real mic**, on Windows: record, pause, clear-last-3s,
  threshold re-detect, trim, and the device picker (87 input devices enumerated
  on that machine).
- **The Talon companion inside a running Talon.** Needs a real session: install
  companion → Live tab shows frames → record → A/B replay. Everything else in
  the Talon tab was verified offscreen against the real setup.
- **A real end-to-end training run** - blocking, and the first thing to do once
  proper sounds exist. GUI training was broken from the start (it imported a
  `load_data` that does not exist in `lib.machinelearning`); the worker now
  mirrors `lib/learn_data.py`'s Audio Net branch, but no full run has completed
  through the GUI yet. Also covers model details, stale markers and ensemble
  combine against real model files.
  - The 2026-07-25 synthetic-fixture mystery is **solved** (2026-07-26):
    auto-calibration sets no threshold until 10+ spectral-flux valleys exist,
    so hand-built bursts segmented to zero by seed luck. See
    `memory/detection-calibration-needs-onset-valleys.md`;
    `gui/services/mock_states.py` now generates working synthetic profiles
    via the manual-override path. A real training run still needs real
    sounds or the imported setup.

## Training performance

- **Check whether the GPU is actually used**, on the Windows box with the good
  GPU. Both requirements files install plain `torch` from PyPI with no CUDA
  index URL, so the wheel may well be CPU-only while `audio_net.py` politely
  falls back to CPU. If so, a CUDA wheel is the single biggest available win on
  a 4-6 hour run. See `memory/training-takes-hours.md` for the one-line check.
- **Apple silicon uses no GPU at all** - the trainer checks `torch.cuda` only,
  never `torch.backends.mps`. Worth trying MPS on the Mac, with the caveat that
  these ops need verifying against CPU output before trusting it.

## Terminal-only operations not yet in the GUI

All still reachable from `python settings.py`:

- Hierarchical model combine (needs a per-class tree UI)
- File-format conversion / resample (`convert_files`)
- "Upgrade model settings" (`combine_models` [U])

Note the CLI's own accuracy test ([A]) predates the `source/` `segments/` layout
and silently finds no files; the GUI's Test accuracy replaced it.

## Match what the CLI offers when training

Raised 2026-07-25, not yet designed. `lib/learn_data.py` offers three
algorithms and a settings pass; the GUI hardcodes Audio Net and exposes only
the net count.

- **Algorithm choice** - `[A]` Audio Net (PyTorch, *required by Talon*, so it
  stays the default and the recommendation), `[R]` Random Forest (sklearn,
  described in the CLI as "for quick verification"), `[M]` Multi Layer
  Perceptron (sklearn). Random Forest is the interesting one for UX: it trains
  in seconds where Audio Net takes 4-6 hours, so it answers "is my data
  actually learnable?" *before* committing a night to it. That also gives the
  sound checklist a real purpose - trying subsets becomes cheap.
- **Audio settings** (`define_settings` in `lib/combine_models.py`): RATE,
  CHANNELS, RECORD_SECONDS, SLIDING_WINDOW_AMOUNT and FEATURE_ENGINEERING_TYPE
  (RAW / MFCC / normalised MFCC / normalised MFSC). These are a footgun - they
  must match how the recordings were made and what Talon expects - so the
  proposal is a read-only summary line ("16 kHz, 30 ms frames, MFSC") with an
  Advanced override that says plainly what changing them breaks.
- Net count should only appear for Audio Net.
- The CLI's post-train confusion matrix is already superseded by the GUI's
  Test accuracy dialog.
- The training setup screen now has a column of its own and a live balance
  picture, so a "quick check vs full run" choice has somewhere to live. Random
  Forest must be framed as a test and never as a model, since Talon requires
  Audio Net.

## Profiles & data portability (roadmap agreed 2026-07-26)

Steps 1 (data root + pointer) and the backup story are done; remaining in
agreed order:

- **One-click model swap.** Talon has one active slot; parrot keeps the
  library. "Use with Talon" per model with the active one always visible,
  on Models and/or Home. Reuse the `TalonPage.focus_patterns()` deep-link
  pattern.
- **`parrot_integration.py` snapshot-back** into `data/talon/` when the
  Talon-side copy differs - the last leak in "your data folder contains
  everything you've made or adjusted".
- **Model-only import**: accept a folder of `.pkl`s (the artifact repos
  veterans actually keep) as a profile with models and no sounds. Import
  currently requires the `data/recordings` shape.
- **Sound-merge import** (bring labels *into* an existing profile) needs its
  own design pass: label collisions, dedup across machines. Deferred until a
  real consolidation need shows up.
- **Windows/Linux verification** of the whole profile stack: pointer, spawn
  with `DETACHED_PROCESS`, AppData/XDG roots, scan. All logic-tested on
  macOS only.
- Attention thresholds (thin < 60 s, only once one sound has 90 s+) are
  guesses; tune against real use. Export covers the active profile only -
  an export-everything variant is easy if wanted.
- LFS guidance for wav corpora in git stays out of the UI deliberately;
  one line of docs somewhere when distribution lands.

## Smaller things noticed 2026-07-26

- **Per sound accuracy during training is the last net's**, not the ensemble's
  (`accuracy_batch` falls out of the per-net loop in `audio_net.py` and is what
  the progress callback passes). Fine for spotting which sound is failing, wrong
  if ever read as the model's real per sound accuracy.
- **`models.py`'s ready-to-train empty state still says "It runs unattended for
  hours"**, which the measured estimate can now contradict for a small library.
- **Nothing keeps the machine awake during a run.** The app says to turn sleep
  off; `caffeinate` on macOS and `SetThreadExecutionState` on Windows would do it
  properly.

## Models as things you can edit

Raised and scoped 2026-07-26, deliberately deferred in favour of the teaching
work. The diagnosis: a trained model is an immutable artifact ( the net's output
layer is sized to the label count, so adding a sound is a full retrain from
scratch, not an edit ), but nothing records *what it was trained from*. Labels
are recoverable by unpickling; net count is inferred by counting weight files;
the date, wall-clock duration, epochs run and audio settings are simply lost.

- **A `<name>.json` sidecar written at train time**, holding sounds, net count,
  settings, date, duration and epochs reached. Cheap, and it unlocks the rest.
- **Retrain**, opening the training page prefilled from the sidecar and
  suggesting a new name rather than overwriting. Retraining the same name
  currently overwrites a 4-6 hour asset that Talon may be running live, behind a
  single confirm.
- **A richer model header** from the sidecar: "trained 3 days ago, 4h20m, stopped
  at epoch 180", and a stale check that compares against a recorded timestamp
  instead of file mtimes.
- Framing to keep: the artifact is permanent, the *recipe* is editable. The verb
  is "Retrain", never "Edit", because the cost is hours.

## GUI features

- **Deploy to Talon as a per-model action**, from the Models tab.
- **Quick Record mode**: pick a sound, hit record, auto-stop after silence,
  repeat - for grinding out volume on one sound.
- **Named recording sessions / datasets** that can be combined at training time.
  The current architecture is a flat list per sound, so this is a real change.
- **Threshold mode (strict/lenient) is global** and applies on restart, while
  recording strategy is per-session. Inconsistent; unify if it ever bites.
- **Patterns.json editor** - the built editor covers guided per-pattern editing,
  raw JSON, variants and snapshots. Still on the wishlist: reordering patterns,
  and previewing changes before saving.
- Sound Quality (SNR) is computed at capture time but not persisted, so it
  cannot be shown in the read-only library. Would need storing at record time.

## Known rough edges

- **Switching sounds is synchronous.** The perf work made it fast (blocking
  build ~104 ms → ~14 ms) but did not make it async.
- **Selection drag feel** in the audio preview - edge auto-scroll speed (7% of
  view span per tick) and the click-vs-drag threshold (4 px) were tuned by
  guess. Confirm in real use.
- **Re-detection runs over the whole take** after each segment or edit. Fine for
  short takes; would need revisiting for very long ones.
- **Migration on GUI startup was deliberately skipped.** It only matters for
  pre-`source/segments` CLI data - revisit before any public release.

## Distribution

The bootstrapper is built (see `memory/ship-a-thin-shell-not-a-bundle.md`).
What remains is the presentation layer:

- **Windows:** Inno Setup or NSIS wrapping `run.bat` → Start-menu shortcut,
  icon, uninstaller. Estimated about half a day. Inno is Windows-only and cannot
  produce a macOS artifact.
- **macOS:** a `.app` whose executable is the launcher, shipped in a `.dmg`.
  Requires Apple Developer signing and notarization.
- **Linux:** AppImage or a `.desktop` file.
- **Possible optimization:** `uv` instead of pip, collapsing Python download,
  venv creation and install into one much faster tool. Matters because a
  progress window is waiting on it. Not decided.
