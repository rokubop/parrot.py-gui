# 2026-07-25 - Models page onboarding, and replacing status.md

**Branch:** `sounds-ux-and-recording-perf` · **Machine:** macOS (fresh install -
1 sound `pop` ~4 s, 0 models)

Follows the previous session's sounds-first onboarding work (`064e91a`), same
treatment applied to Models for a user who has no models yet.

## What was done

**Models tab reshaped as a library** (`gui/windows/models.py`, rewritten)

- Training moved out into a sub-view, so a zero-model user no longer lands on a
  "Selected model" panel with seven disabled buttons sitting above the only
  action they can take.
- Per-model header: identity, then **Test live / Test accuracy** as the primary
  pair (they answer "does it work?"), with Rename / Clone / Combine / Open
  folder / Delete demoted to the quiet secondary row.
- `Inspect` removed - labels now load automatically off-thread on selection and
  cache per model name, including the unreadable result so a broken model does
  not retry forever.
- Detail body lists what the model recognises against what has been recorded
  since, plus a stale marker naming sounds recorded after training
  (`library_ops.newest_recording_mtime`, extracted from `home.py` and now shared).
- Three empty states, branching on what the user actually has: no sounds, one
  sound (names it and its detected seconds), and ready-to-train (with the
  rating breakdown).

**New training sub-view** (`gui/windows/train_view.py`)

- Left column is the decision (name, sound checklist, Advanced); right column is
  the outcome (status, plot, finish panel).
- Checklist is the same Sound / Data / Time tree as the Sounds tab, using
  `get_quantity_rating()` and the newly shared `theme.QUANTITY_COLORS`, so a thin
  sound is visible before training rather than as a bad accuracy after it.
- Readiness gate states what is missing continuously and keeps Train disabled
  until it is not, replacing the old "accept everything, then refuse on submit".
- Net count folded behind an Advanced disclosure with an explanation; model name
  prefilled; empty plot replaced by an explanation of what the curves will mean.
- Finish panel names the model and its held-out accuracy and routes onward
  (Test it live / Test accuracy / Train another / Done).

**Copy fixes, from live testing**

- `"You have 2 sounds: 2 Not enough"` parses as *"2 sounds is not enough"* -
  the count and the rating name collide, worst when every sound sits in one
  band so there is no second category to disambiguate. Now
  `help_dialog.quantity_summary()`: few sounds named with their rating, a
  single band spelled out (`"all 5 rated Not enough"`), a multi-band list left
  terse since it cannot misread.
- All-thin reads differently from one-weak-sound, and the consequence comes
  before the boilerplate rather than after it.
- **Training duration was wrong everywhere**, including in the shipped help
  before this session (`TRAIN_ROWS`: *"Time: Minutes, not hours"*), which then
  got echoed into three new places. It is 4-6 hrs for 14 sounds at 5 nets over
  300 epochs.
- **Stopping early is a supported workflow**, not an abort: `audio_net.py:245`
  saves on every accuracy improvement, so Stop keeps the best model so far.
  Now said in the help, readiness line, in-progress status and Stop tooltip -
  which is what makes the live plot actionable.

**Docs restructure**

- Added [`memory/`](../memory/MEMORY.md) - 9 durable facts plus an index,
  committed so they survive the cross-PC workflow. Assistant user-level memory
  is per machine and does not.
- Added `sessions/` (this file) and `BACKLOG.md`; retired `status.md`.

**The big one: GUI training could never have worked**

`TrainingWorker` did `from lib.machinelearning import load_data` - which does
not exist there. Every GUI training run died at the import. Because the worker
emits `training_finished` after `error_occurred`, the old Models page then
printed "Training complete." over the failure, so it looked like training ran
and quietly did nothing. That is the whole explanation for "checking sounds has
no effect for me".

Now mirrors `lib/learn_data.py`'s Audio Net branch: `load_pytorch_data` ->
`AudioDataset` -> `AudioNetTrainer`, settings from
`get_current_default_settings()` so a GUI-trained model matches a CLI-trained
one, and the model name carrying `.pkl` as both the trainer and `library_ops`
expect.

## Decisions

- **Training is a sub-view, not a panel.** Rejected: keeping both panels on one
  scrolling page and merely reordering them. The sub-view matches the existing
  Sounds → Recording/Edit pattern and gives the checklist and plot room, at the
  cost of one extra navigation step. Chosen by Roku from a side-by-side mockup.
- **Empty states branch on what the user has, and quote seconds rather than a
  rating.** A first sound scoring red "Not enough" reads as failure rather than
  a start - the same trap `library.py` already documents. Promoted to
  `memory/ui-copy-style.md`.
- **`theme.QUANTITY_COLORS` is now shared** by `library.py`, `about.py` and the
  training checklist, replacing three copies of the same four hex values.
- **Scope was left to me** ("i just want to test something you suggest for UX"),
  so all four candidate improvements landed rather than a subset - they turned
  out to be one idea, not four.
- **Postponed the end-to-end training verification** rather than keep tuning a
  synthetic fixture. Hand-built bursts segmented to zero detections and the
  cause was never found; real recordings will settle it in minutes. Roku's
  existing `pop` recording is coffee-shop placeholder audio and is not a
  quality reference or a usable fixture.
- **`status.md` retired rather than maintained.** Its phase-log form is
  append-only and cannot be revised, and it had reached the point of
  contradicting itself. Split into `memory/` (facts, revised in place),
  `sessions/` (dated records), and `BACKLOG.md` (open work). Promoted to
  `memory/repo-memory-not-user-memory.md`.

## Verified / not verified

**Verified**, offscreen (`QT_QPA_PLATFORM=offscreen`), on this machine:

- All six tabs build and navigate.
- Every Models and TrainView state driven with its copy read back: no sounds,
  one sound, ready-to-train, and a selected model with both a stale and an
  unused sound.
- Train → epochs → finish, → stop, and → error paths, using a stub worker.
- Rendered the screens to PNG and inspected them, which caught two layout bugs
  the text assertions could not: a clipped word-wrapped body label, and the
  empty panel pinned to the top instead of centred.

**Bug found and fixed:** `TrainingWorker` emits `training_finished` *after*
`error_occurred`, so a failed run fell straight through into the success panel -
it would have announced `"None" is trained`. `TrainView` now latches `_failed`
and returns early from `_on_finished`.

**Not verified** - and this is the important part:

- **The training fix has not completed a single run.** The broken import is
  proven (running it raises `ImportError`) and the replacement mirrors the CLI
  path Roku actually uses, but no full GUI run has finished. This is the first
  thing to do next session.
- Model details, stale markers, and ensemble combine against real model files -
  driven with faked `AppState` reads.
- Anything on Windows or Linux.

**Two corrections made to my own earlier claims this session:** status.md said
in one section that `process_wav_file` still crashed on rate-mismatched
recordings and in another that it was fixed and verified - the second is
correct, and the wrong one had already been copied into
`memory/audio-rate-is-16khz.md`. Separately I wrote into BACKLOG that the
default strategy "rejects anything continuous"; `reject_cont_45ms` actually
drops continuous blips *under 45 ms* and keeps short discrete sounds. Both
fixed.

**Original note:** it claimed in one section that
`process_wav_file` still crashed on rate-mismatched recordings and in another
that the crash was fixed and verified. The second is correct; the first had
already been copied into `memory/audio-rate-is-16khz.md` and was fixed there.

## Next steps

1. **Record two proper sounds, then train end to end through the GUI.** Roku
   offered to record these. Everything else here is downstream of knowing the
   training fix works. Then check the per-model detail body, the stale marker
   (record a sound after training) and Combine with two models.
2. **Check whether the GPU is actually used** - one line on the Windows box:
   `.venv\Scripts\python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"`.
   Both requirements files install plain `torch` with no CUDA index URL, so a
   4-6 hour run may be sitting on the CPU with a good GPU idle. Potentially the
   largest single win available on this project.
3. **Design the training-settings work** - Roku's open ask: offer what the CLI
   offers (Random Forest / MLP / Audio Net, plus the audio settings), with
   Audio Net recommended since Talon requires it. Sketched in `BACKLOG.md` under
   "Match what the CLI offers when training"; the Random Forest quick-check
   angle is the part worth leading with, and it is also what would give the
   sound checklist a real purpose.
4. **Windows pass** - the bootstrap path and the Phase 6 preview/threading perf
   work are written but only ever validated on macOS. Confirm the
   torch-before-Qt preload still holds (`memory/windows-torch-before-qt.md`).
5. Consider whether Home's step 2 should open the train sub-view directly
   rather than landing on the Models tab; currently the empty state's
   explanation is worth the extra click, but that is a guess.

## Commits

`ae131c0` models-first onboarding · `cdcd7ed` docs restructure ·
`10ed5ee` copy fixes · `d625089` training import fix. All pushed to
`origin/sounds-ux-and-recording-perf`.
