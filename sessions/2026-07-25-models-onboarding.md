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

**Docs restructure**

- Added [`memory/`](../memory/MEMORY.md) - 9 durable facts plus an index,
  committed so they survive the cross-PC workflow. Assistant user-level memory
  is per machine and does not.
- Added `sessions/` (this file) and `BACKLOG.md`; retired `status.md`.

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

**Not verified** - impossible on this machine:

- A real end-to-end training run. Needs ≥ 2 recorded sounds; this checkout has
  one. Everything up to and after `TrainingWorker.start()` was exercised.
- Model details, stale markers, and ensemble combine against real model files -
  those paths were driven with faked `AppState` reads.
- Anything on Windows or Linux.

**Correction made while mining status.md:** it claimed in one section that
`process_wav_file` still crashed on rate-mismatched recordings and in another
that the crash was fixed and verified. The second is correct; the first had
already been copied into `memory/audio-rate-is-16khz.md` and was fixed there.

## Next steps

1. **Run the Models flow on a machine with real data** - the primary PC. Train a
   model end to end, then check the per-model detail body, the stale marker
   (record a sound after training), and Combine with two models.
2. **Windows pass** - the bootstrap path and the Phase 6 preview/threading perf
   work are both written but only ever validated on macOS. Also confirm the
   torch-before-Qt preload still holds (see `memory/windows-torch-before-qt.md`).
3. **Nothing is committed.** This branch holds one session's work in two logical
   parts - the Models/train-view change, and the docs restructure - and is worth
   splitting into two commits.
4. Consider whether Home's step 2 should open the train sub-view directly rather
   than landing on the Models tab; currently the empty state's explanation is
   worth the extra click, but that is a guess.
