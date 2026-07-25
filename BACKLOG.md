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
  - Synthetic fixtures are a dead end here: the active strategy
    (`auto_dBFS_secondary_dBFS_reject_cont_45ms_repair`) rejects anything that
    reads as continuous, and hand-built bursts kept segmenting to zero
    detections. Record two real sounds instead.

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
