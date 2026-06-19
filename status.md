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

### Current Data
- **16 sounds**: ah, background, background_me, cluck, ee, eh, er, guh, mm, oh, palate, pop, sh, ss, t, tut
- **3 models**: toroto-1, totoro-2, totoro-b (each with 4-5 nets, best weights saved)

---

## Next Session: Approachable & Action-Oriented UI

The current UI works but feels intimidating — it drops you into a dense recording interface with no guidance. The goal is to make it welcoming for a new user and informative for a returning user.

### Priority Order

1. Home page with model/sound summary
2. Talon discovery & status display
3. First-run wizard
4. Patterns.json full editor

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

## File Structure Reference

```
gui/
├── __init__.py
├── __main__.py          # python -m gui
├── app.py               # QApplication + Fusion theme
├── windows/
│   ├── main_window.py   # QMainWindow + toolbar + QStackedWidget
│   ├── recording.py     # Recording page
│   └── training.py      # Training page
├── widgets/
│   ├── waveform.py      # pyqtgraph waveform viewer
│   ├── segment_bar.py   # pyqtgraph segment overlay
│   └── training_plot.py # Live loss/accuracy curves
├── workers/
│   ├── audio_worker.py  # QThread for recording
│   └── training_worker.py # QThread for training
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
