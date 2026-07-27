# 2026-07-26 - Profiles become the app's spine; logo; dashboard grows up

**Branch:** `sounds-ux-and-recording-perf` · **Machine:** macOS (2 real sounds, 0 models)

Second session this day. Twelve commits, `3ecb304`..`4db7bf2` (the first of
which committed the *previous* session's uncommitted work).

## What was done

**Profiles, end to end.** Every data path now derives from `DATA_DIR`
(`lib/default_config.py`), resolved at import: `PARROT_DATA_DIR` env →
`data-profiles/current` pointer file → `<root>/data` (Main). A checkout keeps
exact legacy relative paths (CLI-compatible); anywhere else roots at the
platform user-data dir (AppData / Application Support / XDG - same locations
as the Python bootstrap cache). A profile is a full data tree under
`data-profiles/<name>/` with a frozen `.baseline/` for one-click Reset;
switching writes the pointer and relaunches (~1.4 s), so the choice survives
dock launches. UI: a toolbar chip (hidden until a profile exists) whose
dropdown switches; management is `ProfilesDialog` (create / duplicate /
freeze / reset / delete / import / open), reached from the chip or Settings.
Talon can be simulated per profile (`PARROT_TALON_HOME` = `none` or a mock
home path); the toggle shows under `PARROT_DEBUG=1`.

**Import / export / backup.** Import copies any data-shaped folder in as a
profile (scan of common dirs, or folder picker); a dismissible Home card
advertises it only while the app is empty. Settings gained a Back up group
("everything is one folder") with Open data folder and Export a copy;
Home gained Open data folder and Open Talon folder buttons.

**Test profiles** (`gui/services/mock_states.py`, Manage profiles → Debug):
one profile per app state - empty, 2 sounds, 10 sounds, and (when a real
model exists to copy) model-without-Talon and full-setup with a bundled mock
Talon home that real discovery accepts. Sounds are synthetic noise pops
segmented by the real pipeline under a manual threshold override.
`test-empty`, `test-2-sounds`, `test-10-sounds` exist on this machine now.

**Dashboard.** Attention panel (`gui/services/attention.py`: thin sounds,
Talon running an older model, patterns referencing sounds the deployed model
lacks - renders only when something fires). Step 3's card action evolves into
a primary-styled **Edit patterns** once connected, deep-linking to the Talon
tab's editor via `TalonPage.focus_patterns()`. "Before you start" panel
removed (its unique mic advice moved into the Record help as a Mic row).

**Chrome.** Device pickers moved from the toolbar into the bottom status bar,
replacing the redundant "Audio device: ..." text. Logo landed:
`gui/assets/parrot.png` (1024 master) → `.ico`, `.icns`, runtime
`setWindowIcon`; macOS uses a dark-slate rounded tile at Apple's 824-grid,
Windows/Linux the free-form head.

## Decisions

- **Switching relaunches; no live switch.** Paths are imported by value into
  a dozen modules; live switching = refactor everything plus rebuild every
  page, to save ~1.4 s and gain stale-state bugs. Not re-litigating.
- **Main stays plain `data/`, not "everything is a profile"** - CLI reads
  `data/` relative paths, and the un-deletable/un-resettable Main is a
  safety feature, not an inconsistency.
- **Chip + dialog, not a Profiles tab.** A list row that switches on click
  conflates selecting with becoming; menu semantics don't. Tab was built
  first and removed the same day.
- **Import copies, never links.** Link-in-place would let the GUI edit the
  "pristine" original - the exact thing the user feared. Copies fork; noted.
- **The import card is onboarding-only** (empty app, or dismissed, or one
  import done). Two earlier visibility rules (no-profiles-yet, then
  until-dismissed) both proved wrong in use.
- **Step cards never collapse** (variant B, chosen from screenshots) and
  **Edit patterns is the one bright button** for a set-up user - Roku: it is
  the #1 action for anyone with a model; a flat link undersold it.
- **Backup = the data root itself.** No in-app git (auth, binary merges,
  LFS); Open-folder + Export-a-copy covers it.
- **macOS icon follows Apple's 824/1024 grid** even though some third-party
  apps draw bigger; promoted to memory with regeneration numbers.
- **Mock sounds use the manual-threshold override**, never auto-calibration
  (see memory below); mock models are only ever copies of real ones.

Promoted to `memory/`: `detection-calibration-needs-onset-valleys.md`,
`app-icon-regeneration.md`, a status-bar line in `qt-traps.md`.

## Verified / not verified

**Verified** (offscreen Qt + subprocess suites, all on this macOS): full
profile lifecycle incl. name validation and reserved `current`; data-root
resolution in checkout and packaged modes (sandboxed HOME) and Windows/Linux
branch logic (function-level); pointer persistence, staleness fallback, env
precedence; import scan finding a planted checkout while excluding own data;
export copy with auto-suffix and bookkeeping exclusion; chip menu, dialog,
Settings entry; attention checks and Edit patterns deep link; test-profile
fleet with real detected durations (~5 s/sound) and Main left clean; icon
loads, `.icns`/`.ico` generated. Roku used the real app during the session
(UserB profile + pointer exist from real switches, so the relaunch handoff
works in practice).

**Not verified:** any of it on Windows/Linux (incl. `DETACHED_PROCESS`
spawn); true packaged mode (no bundle exists - the `./data`-in-cwd install
signal gets its real test then); a real end-to-end import of a big setup and
the folder-picker path; `test-model-no-talon` / `test-full-setup` and the
whole mock-Talon home path (no model on this machine - code has never run);
attention thresholds (60 s / 90 s are guesses); how the new status bar,
attention panel and tile icon actually look on a real display (Roku saw and
approved the icon and dashboard via screenshots only).

## Next steps

1. **Bring the real setup over from the other PC** - drop the `data/` folder
   anywhere, Manage profiles → Import (first real E2E of the scan/copy path),
   then Create test profiles again to get the two model-bearing states, and
   verify `test-full-setup`'s mock Talon shows all-green on Home.
2. **One-click model swap** (roadmap item 2): Talon has one active slot;
   give Models/Home a "Use with Talon" that deploys and shows which is
   active. Reuse the `focus_patterns()` deep-link pattern.
3. **`parrot_integration.py` snapshot-back** into `data/talon/` so the
   "one folder has everything" claim closes its last gap.
4. Then: model-only import (artifact repos), and the icon size question
   (compare against Finder in the dock; bump tile 824 → ~880 only if it
   reads smaller than Apple's own).
