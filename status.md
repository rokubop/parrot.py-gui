# Parrot.py GUI — Status & Next Session

## What's Done

### Phase 1: Python 3.13 Migration
- Replaced `pyaudio` with `sounddevice` across all files (`default_config.py`, `stream_recorder.py`, `record_data.py`, `listen.py`, `stream_controls.py`, `test_data.py`, `convert_files.py`)
- Updated `requirements-windows.txt` and `requirements-posix.txt`
- Created `run.sh` (Linux/WSL/macOS) and `run.bat` (Windows) entry scripts that handle Python 3.13 install, venv, system deps, and launch

### Phase 2: GUI Foundation
- `gui/` package with PyQt6 + pyqtgraph
- Main window with toolbar navigation (Recording / Training)
- **Recording page**: sound library tree, device selector, record/stop, waveform viewer, segment bar, dBFS slider with live re-segmentation
- Workers: `AudioWorker` (QThread recording), `ResegmentWorker` (background re-segmentation)

### Phase 3: Training Interface
- **Training page**: sound label checklist with durations, model name input, net count spinner, live loss/accuracy plot, train/stop
- `TrainingWorker` wraps `AudioNetTrainer.train()` with `progress_callback` and `stop_check`
- CLI (`settings.py`, `play.py`) unchanged — callbacks are optional

### Phase 4: Read-Only Sounds Library + Theming (current session)
- **Sounds library is now the landing page** (`gui/windows/library.py`, `SoundLibraryPage`). Read-only by design — browse recorded sounds with **no** record/edit/overwrite controls (safe first page over the user's real `data/recordings/`).
  - Left: narrow sound list with per-sound total duration.
  - Right: per-sound header (counts / recorded / detected seconds) + a vertical stack of **session cards**, one per recording.
- **Session card** (`gui/widgets/session_card.py`): date + length + threshold header, play/pause, click-to-seek. Loads audio lazily on first play.
- **Audio preview** (`gui/widgets/audio_preview.py`): min/max envelope waveform ⇄ spectrogram toggle, X-locked zoom with limits, detection regions overlaid from the `.srt`, hover time readout, animated fit, visual-only **Normalize** (rescales Y to the peak, since these sounds peak ~0.3).
- **Theme system** (`gui/theme.py`): live-switchable `fabfilter` (default, green accent) / `studio_dark` / `audio_console`. Switcher lives in the main toolbar; pages with `refresh_theme()` rebuild on switch.
- **Critical crash fix**: `create_app()` only held a *local* reference to `MainWindow`, so Python GC could delete the whole window (and every child widget) mid-event-loop — surfacing as intermittent `wrapped C/C++ object ... has been deleted` errors on `cards_layout`/`scroll`, especially when clicking fast. Fixed by holding a strong ref: `app._main_window = window` in `gui/app.py`. **If you see "deleted C++ object" errors again, suspect a missing Python reference to a top-level widget, not teardown order.**

### Phase 5: Sounds Library UX + Recording Performance (this session)

**All work is on branch `sounds-ux-and-recording-perf` (8 commits, NOT merged to master, NOT pushed).**

- **Recording performance (two O(n²) bugs fixed, both verified):**
  - Live recording waveform (`gui/widgets/waveform.py`) rebuilt a numpy array from a growing Python list every frame (~16 ms/frame at 15 s, ~129 ms/frame at 2 min, on the UI thread). Now an amortized-growth int16 buffer + fixed display-point cap + ~30 fps redraw throttle → flat ~0.05 ms/frame.
  - `determine_detection_state` (`lib/stream_processing.py`) re-iterated the entire `DetectionFrame` history in Python every 15 frames. Added a self-healing numpy cache on `detection_state` (`_stat_arrays`) that appends only new frames and shrinks on pause/clear truncation. **Detection output is byte-identical** (verified via SRT/sequence hash); per-frame p95 at 3 min: 5.6 ms → 0.7 ms.
- **Audio preview / session card UX** (`gui/widgets/audio_preview.py`, `session_card.py`):
  - Fixed-height previews with an inline **Expand/Collapse** toggle.
  - Draggable playhead; click positions the playhead **without auto-playing** (jumps & continues only if already playing).
  - **Duration now derived from decoded samples, not the WAV header** — several recordings store a byte count in `nframes`, which doubled the duration and made Fit show half-blank. Playback reuses the preview's already-decoded samples (no re-read on the UI thread → no first-play freeze).
  - Horizontal **scrollbar** appears when zoomed (in a fixed-height row so it never shifts the plot).
  - **Drag-to-select a time range**: highlighted band + duration; Fit zooms to selection (whole clip if none); Play/Space plays just the selection; auto-scrolls when dragging past the edge; click clears it.
  - Wheel zooms time everywhere (incl. the left axis).
  - **Play/pause use QPainter-drawn icons** (`_media_icon`) + plain text, fixed size — the old ▶/⏸ glyphs had different heights and shifted the layout on every toggle.
- **Sounds library** (`gui/windows/library.py`):
  - Left panel is now a **3-column tree (Sound / Data / Time)** with color-coded data-quantity rating; min width + stretch factors so it can't collapse.
  - Per-sound header shows a **Data quantity** rating (Not enough / Sufficient / Good / Excellent) using parrot's thresholds, extracted to `get_quantity_rating()` in `lib/print_status.py` (shared with the CLI status, output unchanged).
  - **Hotkeys** (on the selected card): `F` fit, `E` expand, `Home` start, `Esc` clear selection, `N` normalize, `V` waveform/spectrogram. Shown in the hint bar + tooltips. Space / ←→ / ↑↓ unchanged.
- **Theme**: consolidated to **FabFilter only** (`gui/theme.py`) — the theme selector and the other two themes were removed (supersedes Phase 4's live-switchable themes). UI font is **Inter**. Fixed invisible buttons (contrast + a Qt gotcha: a selector-less stylesheet on an ancestor silently breaks `:checked` background on descendant buttons → scope container stylesheets with `QWidget#id { ... }`).

**Open follow-ups from this session:**
- Selection drag *feel* (edge auto-scroll speed = 7% of view span/tick; click-vs-drag threshold = 4 px) is tuned by guess — confirm in real use.
- **Sound Quality (SNR)** metric exists in parrot but isn't surfaced in the read-only library (computed at capture time, not persisted). Would need to store SNR at record time.
- Per-card normalize/spectrogram overrides considered and deferred (kept global; `V` makes flipping fast).
- `process_wav_file` crashes standalone on the 16 kHz recordings (mfsc framing vs the 48 kHz config resample path) — pre-existing, unrelated, flagged.

### Current Data
- **20 sound directories** in `data/recordings/`
- **6 models** (`.pkl` + weights) in `data/models/`

### Phase 6: Editing, management & full 4-tab app (this session)

**Branch `sounds-ux-and-recording-perf` (continued).** Turned the read-only
library into a full editing app with four tabs: **Sounds, Models, Settings,
About** (`main_window.py` — Recording folded into Sounds, Training into Models).

- **Foundation**
  - `gui/services/library_ops.py` — Qt-free fs ops for sounds/recordings/models
    (create/rename/clone/delete/move + reveal-in-file-manager + name validation).
    Unit-tested against temp dirs.
  - `gui/widgets/confirm_dialog.py` — reusable **two-step** destructive confirm
    (type-the-name for sounds/models, checkbox for recordings). Every delete
    routes through it.
  - `AppState` mutation wrappers emit `recordings_changed` / `models_changed`.
- **Sounds tab** (`library.py`): New sound, Rename, Clone, Delete, Open folder
  (header buttons + left-list right-click). Per-recording `…` menu on each card:
  Edit, Rename, Move to another sound, Open folder, Delete. `_populate_labels`
  now preserves/restores selection so in-place edits rebuild the cards.
- **Recording view** (`recording_view.py`): Audacity-like live capture with live
  waveform + a live readout (time, SNR-based quality, dBFS, noise floor,
  detected time, data-quantity rating, duration type). Record / Pause /
  Clear-last-3s / Stop; device + strategy pickers. `AudioWorker` gained a
  `strategy` param.
- **Edit view** (`edit_view.py` + `workers/segment_worker.py`): **redo the blue
  overlay** for real — re-detect at a chosen dBFS threshold + duration type
  (writes `_thresholds.txt` override → `.MANUAL.srt`), Reset to auto, and
  **delete a selected time range** (rewrites the source WAV + re-detects).
  Lightweight playback. Verified end-to-end on synthetic audio. **This replaces
  the old `recording.py` dBFS slider, which never passed its value through.**
- **Models tab** (`models.py` + `workers/combine_worker.py`): list + details +
  Inspect (loads classes/accuracy off-thread) + Rename / Clone / Delete /
  Open folder + Train (reuses `TrainingWorker`) + **Combine into an ensemble**.
- **Settings** (`settings.py` + `services/user_config.py`): input device,
  threshold mode, default strategy, default model, data folders. Persists to
  `data/code/config.py` (applies on next launch).
- **About** (`about.py`): explains sounds/recordings, detection + the blue
  overlay, discrete/continuous, the **data-quantity rating** (Not enough /
  Sufficient / Good / Excellent), SNR, models, and strategies.
- **`strategies.py`** — curated detection-strategy presets.
- **Cleanup**: removed dead `windows/recording.py`, `windows/home.py`,
  `widgets/segment_bar.py`, `widgets/duration_bar.py`.

**Verification:** offscreen (`QT_QPA_PLATFORM=offscreen`) smoke tests build the
full window and navigate every tab + sub-view; `library_ops`, `user_config`,
the segment/trim/reset pipeline, and ensemble-combine were each functionally
tested. Live audio capture itself can't be exercised headless — **needs a manual
run on Windows with a mic.**

**Editing & appending (refinement):** A recording is just a file when you're
*not* live, so all real editing happens on saved clips (no risky live-stream
splicing). The **Edit view** does arbitrary delete/trim/threshold, and
**Append** records a take and concatenates it onto an existing clip + re-detects
(`AppendWorker`; rate-mismatched takes are resampled). Delete-recording
confirmation names the sound.

**Recording view = a record/review/edit loop.** The screen now supports:
Record → make sounds → **Space/Pause** → scrub & play the take → **drag-select +
Delete** a bad part → **Resume** (records more) → … → **Done**. Implemented
without live-stream splicing: a "take" is one growing WAV; each Record→Pause is a
*segment*, the first becomes the take and later ones are appended (`AppendWorker`)
so editing always happens on a static file. While reviewing, the same interactive
`AudioPreviewWidget` as read-only is shown (click-seek, drag-select, fit, zoom,
playback); Delete uses `TrimWorker`. The take is a real file in the sound from
the first segment, so it's always saved. (Re-detection runs on the whole take
after each segment/edit — fine for short takes; could get slow for very long
ones.)

**Undo/redo (snapshot-based, Audacity-style):** `gui/services/undo.py`
(`UndoHistory`) snapshots a clip's files (wav + srt/thresholds) before each
destructive edit and restores them on undo; bounded stack, session/clip-scoped,
temp-dir storage. Wired into the **Edit view** (trim / threshold apply / reset)
and the **recording review** (delete selection / resume-append) with **Undo/Redo
buttons + Ctrl+Z / Ctrl+Y**. Because in-clip audio edits are now undoable, their
type-to-confirm dialogs were dropped — confirms remain only for the
non-undoable whole-recording / sound / model deletes.

**Open follow-ups (Phase 6):**
- **Manual run-through on Windows** with a real mic: live recording, pause/clear,
  threshold re-detect, trim, and the device picker (87 input devices enumerated).
- Switching sounds is still synchronous (see "Known open issues" below) — the new
  edit/record flows didn't change that.
- **Terminal-only ops not yet in the GUI:** hierarchical model combine (needs a
  per-class tree UI), model accuracy testing (`settings.py` → [A]), file-format
  conversion / resample (`convert_files`), and "upgrade model settings"
  (`combine_models` [U]). All still available from `python settings.py`.
- Recording strategy is selectable per session but **threshold mode
  (strict/lenient) is global** (Settings, applies on restart).

### Phase 7: Two-pass detection (threshold quality)

**Problem:** the auto-threshold was an *online* estimator even for saved files —
its upper-bound dBFS threshold stays disabled until ~10 sounds have finished
(`dBFS_valleys`), so the start of every recording was judged by weaker criteria
("takes a while to settle, bad data at the start"), and the repair post-pass
only ever *adds* detections, never demoting the settle-period junk.

**Fix (`TWO_PASS_DETECTION = True` in `lib/default_config.py`):** for anything
that is a *file* (not a live stream), run the existing pipeline once purely to
settle the thresholds over the WHOLE recording (`settle_detection_state`), then
re-judge every frame from 0:00 with them frozen (`DetectionState.frozen`).
Applied in `process_wav_file` (re-detect / append / trim / migration; opt-out
via `two_pass=False`) and `StreamRecorder.stop()`/`.post_processing()`
(`rejudge_recording()` re-reads the take from disk — pause/clear truncate the
file too, so it always matches the frames). The recorder un-freezes afterwards
so CLI pause→process→resume keeps live recalculation. The online algorithm is
untouched (live paths can't know their future); single-pass output verified
**byte-identical** to pre-change.

**Measured (synthetic 40 identical bursts + real pop recording, Windows venv):**
detected 40/40 vs 39/40 with all first-quarter bursts found; real pop events went
from 100±335 ms (settle-period blobs, multi-second outliers) to a uniform
74±20 ms with 26 more events found. Pause/resume cycle + GUI offscreen smoke OK.

**Note:** all pre-existing recordings are 16 kHz while config RATE is 48 kHz —
`process_wav_file` crashes on them in the mfsc framing (pre-existing, also
blocks GUI re-detect on old data). Fixing that is now the natural next step so
old recordings can be re-segmented with the better algorithm.

### Phase 8: First-party Talon support (see prd-talon.md)

**New top-level Talon tab** (Sounds | Models | **Talon** | Settings | About)
with three sub-tabs, all verified offscreen against the real Talon setup:

- **Setup & Patterns** — discovery (integration / patterns.json / deployed
  model paths), deployed-model ↔ local-model byte-match, companion
  install/update, health lints, and a full **patterns.json editor**: guided
  per-pattern dialog (sounds from the deployed model's classes, threshold ops
  from the integration's own `possible_thresholds`, throttle targets from
  pattern names), raw-JSON mode, named variants (`data/talon/variants`),
  snapshot-before-every-deploy + snapshot browser (`data/talon/snapshots`).
  Rename/delete update throttle references everywhere. Validation caught 6
  real dead throttles in the live patterns.json (sound names where pattern
  names are required). Talon hot-reloads patterns.json (`@resource.watch`),
  so Deploy applies live.
- **Live** — port of talon-parrot-tester's frames table fed by a **companion
  module** (`talon_companion/parrot_gui_bridge.py`, installed from the GUI):
  a pure observer that wraps `pattern_match`, calls the original, and
  publishes per-frame UDP JSON (power/formants/class probabilities/active/
  throttled/grace) + heartbeat to 127.0.0.1:8352. Captures group with 0.3 s
  pre-roll / 350 ms timeout like the tester. **Record session** writes raw
  frames to `data/talon/captures/*.jsonl`.
- **Captures** — the A/B workbench: replay a recorded session against the
  working copy or any variant using a port of the integration's state
  machine that is **verified frame-identical** (4000 random frames incl.
  grace/throttle, 0 mismatches, tested by exec'ing the real integration's
  classes with Talon stubbed). Shows per-pattern fire counts, dropped/added
  frames, and warns when a lowered >power floor makes additions
  under-reportable.

**Not yet verified live:** the companion inside a running Talon (needs a
real session: install companion → Live tab shows frames → record → A/B).
Services: `patterns_store/schema/replay`, `capture_model`, `talon_companion`
(all Qt-free + sandbox-tested), `bridge_worker`, `pattern_edit_dialog`.

---

## Next Session

### 0. Known open issues (start here)
- **Switching sounds was slow — FIXED in Phase 6.** The cost was never the WAV decode (~15 ms); it was building a pyqtgraph plot per recording **synchronously on the UI thread** (~50–220 ms each → ~1 s freeze for a 5-recording sound). Fixes (pyqtgraph plots must be built on the UI thread, so the wins are from *deferring + spreading* the work):
  - `SessionCard` builds cheaply with a same-height placeholder + lazy `load_preview()`; previews fill in **progressively**, one per event-loop tick (`_load_timer` / `_pending_loads`), selected card first.
  - **Old view teardown is deferred** to the next tick (`_garbage` / `_collect_garbage`) — destroying the *previous* sound's loaded plots cost ~58 ms and was blocking the new view from appearing.
  - Selection debounce dropped 60 ms → 15 ms; play/pause icons cached (`_ICON_CACHE`).
  - Result: blocking build ~104 ms → ~14 ms; felt switch latency ~30 ms.
  - **Startup**: only the Sounds page is built eagerly; Models/Settings/About + recording/edit views construct on first use (`main_window` lazy getters). Window build ~1031 ms → ~322 ms (the remaining ~1.1 s is the unavoidable PyQt6/sounddevice import).
  - Verified responsive + rapid-switch-safe offscreen; **confirm the feel on Windows.** Further wins if ever needed: cache decoded audio, cap plotted points, drop antialias on dense envelopes.
- **Dead code removed in Phase 6:** `windows/home.py`, `windows/recording.py`, `widgets/segment_bar.py`, `widgets/duration_bar.py` are gone. Talon discovery (`gui/services/talon_discovery.py`) is still unsurfaced in the UI.

### Priority Order

1. Talon discovery & status display (`gui/services/talon_discovery.py` exists — wire its results into the UI)
2. Move `SessionCard`/preview decode off the UI thread (the slow-switch issue above)
3. Remaining terminal-only ops in the GUI (hierarchical combine, accuracy test, file conversion, upgrade-settings)
4. First-run wizard / Patterns.json editor

---

### 1. Landing / Home Page (Returning User)

Replace the current "open straight to recording" flow with a home page that orients the user.

**Active model (front and center):**
- Auto-detect from Talon's `patterns.json` if available, fallback to last-trained or user-selected
- Model name, sounds it was trained on, accuracy, net count, file size
- Whether this model matches what Talon is actually using (file-compare for copied models)
- Per-model notes (text field, e.g. "trained with new cluck samples")
- "Deploy to Talon" action per model

**All models list:**
- Show all trained models below the active one
- Active model highlighted / pinned at top
- Each model card shows: name, sound count, net count, notes
- Training action can be global or per-model

**Sound recording summary:**
- Visual bars per sound showing recording duration
- Color-coded: red/warning if below recommended minimum
- Last recorded date per sound

**User notes:**
- Global notes area on home page (general thoughts/reminders)
- Per-model notes on each model card

**Talon integration (prominent):**
- "Talon Integration: Found / Not Found" status displayed on home page
- Path to `parrot_integration.py`
- Path to `patterns.json` and which model it references
- Link to open patterns.json editor (see §4)

**Navigation:**
- Recording is global (not per-model) — can append to existing or start fresh without overwriting
- Training can be global or per-model
- Deploy is per-model or section-level

### 2. Talon Integration Discovery

Auto-discover the user's Talon parrot setup, similar to how `talon-parrot-tester` does it. This runs outside of Talon (standalone Python), so we can't use `talon_init.TALON_HOME` or `registry`. Instead:

**Discovery strategy (standalone):**
1. Find Talon user directory:
   - Windows: `%APPDATA%/talon/user/`
   - macOS: `~/.talon/user/`
   - Linux: `~/.talon/user/`
2. Search for `parrot_integration.py` via `rglob`
3. Parse it to extract `pattern_path` (regex for `pattern_path = str(...)` and `PARROT_HOME = TALON_HOME / "..."`)
4. Resolve `TALON_HOME` manually: `%APPDATA%/talon/` on Windows, `~/.talon/` on others
5. Fallback: check `<talon_home>/parrot/patterns.json`, then `rglob("patterns.json")` in user dir

Reference implementation: `talon-parrot-tester/parrot_integration_paths.py` — specifically `get_parrot_integration_path()`, `extract_pattern_path_from_parrot_integration()`, and `get_patterns_py_path()` (3-stage fallback)

**What to show in UI:**
- "Talon Integration: Found" / "Not Found" status
- Path to `parrot_integration.py`
- Path to `patterns.json` and which model it references
- Which sounds from `patterns.json` map to which actions (noise → action mapping)
- Whether the model referenced in `patterns.json` matches any model in `data/models/` (file comparison for copies)

### 3. Guided First-Run Experience (New User)

Step-by-step wizard for a brand new user with no data:

1. **"Welcome to Parrot.py"** — brief explanation of what it does (voice → actions via Talon)
2. **"Step 1: Record Sounds"** — guide them to record a few sounds (suggest starting with pop, cluck, hiss). Explain what a "sound" is and how much to record.
3. **"Step 2: Train a Model"** — one-click training with sensible defaults
4. **"Step 3: Deploy to Talon"** — show how to deploy the model, link to patterns.json setup

### 4. Patterns.json Full Editor (Lower Priority)

Full GUI editor for `patterns.json` so users don't have to hand-edit JSON:

- **View** all noise → action mappings in a structured table/list
- **Edit** action strings, thresholds per pattern
- **Add/remove/reorder** patterns
- **Guided input**: dropdowns or autocomplete for available sounds and action keys so users don't typo
- **Preview** changes before saving
- **Deploy**: save back to the Talon-referenced path

The idea: users may not know how to type specific keys and values. The GUI prevents mistakes and shows all available options.

### 5. Sound Library Improvements

Make the recording page less overwhelming:
- Visual bars showing duration per sound, color-coded (highlight sounds with too few samples)
- Show recommended minimum duration per sound (guide new users on how much to record)
- "Add Sound" flow should be more prominent and guided
- Recording can append to existing data or start fresh without overwriting old recordings
- Consider a "Quick Record" mode: pick a sound, hit record, it auto-stops after silence, repeat
- Future consideration: named recording sessions / datasets that can be combined when training (current architecture is flat-list per sound)

---

## Later: Packaging / Distribution (deferred — do near a release, NOT now)

Goal: a "download, double-click, taken care of" installable so end users never touch Python/clone/scripts.

- **Don't build it yet.** It's a recurring sync-tax (like run.sh/run.bat already are) and only worth testing once the app's shape stabilizes. Building/testing installs of a half-built app is wasted effort.
- **It won't hurt the dev loop** when we do it — keep dev as `python -m gui` / `run.sh`; the installer is a separate build recipe that *consumes* the repo, doesn't change code.
- **The bootstrapper already exists**: `run.bat`/`run.sh` already detect/install Python, create the venv, pip-install deps with confirmation + progress, and recover on launch failure. That IS the launcher pattern (same as ComfyUI / A1111 / Easy Diffusion). Gap to "installable" is mostly presentation, not capability.
- **Prefer bootstrapper over monolithic PyInstaller bundle** — because torch makes an all-in-one bundle 1–3+ GB and hardware-specific. Ship a tiny shell, pip-install the heavy/CPU-vs-CUDA wheels live on first run.
- **Likely path (Windows first):** Inno Setup (or NSIS) wraps current `run.bat` → Start-menu shortcut + icon + uninstaller; first run does the existing venv/pip flow (ideally in a small window vs console); subsequent runs launch instantly. Est. ~half-day for a working loop. Mac/Linux handled separately later.
- **Pay-off-now habit:** keep deps + entry point in obvious declared places (`requirements.txt`, single `gui/__main__`) so the future installer is trivial to point at. (Already doing this.)
- Bonus: a native Windows build sidesteps the WSL/Wayland combo-popup issue entirely (no Wayland on real Windows).

---

## File Structure Reference

```
gui/
├── __init__.py
├── __main__.py          # python -m gui
├── app.py               # QApplication + Fusion + theme; HOLDS the MainWindow ref
├── theme.py             # Live theme system (fabfilter/studio_dark/audio_console)
├── windows/
│   ├── main_window.py   # QMainWindow + toolbar + QStackedWidget (Sounds/Recording/Training)
│   ├── library.py       # SoundLibraryPage — read-only landing page (DEFAULT)
│   ├── home.py          # HomePage — BUILT BUT NOT WIRED IN (dead code, decide its fate)
│   ├── recording.py     # Recording page
│   └── training.py      # Training page
├── widgets/
│   ├── audio_preview.py # waveform/spectrogram preview w/ detection overlay + normalize
│   ├── session_card.py  # one recording session (preview + play/seek)
│   ├── duration_bar.py  # (verify usage)
│   ├── waveform.py      # pyqtgraph waveform viewer (recording page)
│   ├── segment_bar.py   # pyqtgraph segment overlay (recording page)
│   └── training_plot.py # Live loss/accuracy curves
├── workers/
│   ├── audio_worker.py  # QThread for recording
│   └── training_worker.py # QThread for training
├── services/
│   └── talon_discovery.py # standalone Talon integration discovery (not yet surfaced in UI)
└── models/
    └── app_state.py     # Reads data/recordings/ and data/models/
```

Key lib files for integration:
- `lib/audio_net.py` — `AudioNetTrainer.train(filename, progress_callback, stop_check)`
- `lib/stream_processing.py` — `process_wav_file()` for re-segmentation
- `lib/srt.py` — `parse_srt_file()`, `count_total_label_ms()`
- `lib/default_config.py` — all constants and paths

## Launch

```bash
# Linux / WSL / macOS
./run.sh

# Windows
run.bat
```
