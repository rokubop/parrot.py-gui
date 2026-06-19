# Parrot.py — Development Notes

## Run Scripts: run.sh and run.bat

**IMPORTANT**: `run.sh` (Linux/WSL/macOS) and `run.bat` (Windows) must be kept in sync. When modifying one, always update the other to match. They should have feature parity for:

- Python version detection and auto-install
- Virtual environment creation, cross-platform venv detection, and recreation prompts
- Network connectivity checks
- Dependency installation with user confirmation and progress feedback
- Launch failure recovery menu (reinstall deps / recreate venv / exit)
- User confirmation before any destructive or long-running operation

### Platform-specific differences (expected)

- `run.sh`: pyenv for Python install, apt for system deps, display server check, Qt platform selection for WSL
- `run.bat`: winget for Python install, PATH refresh from registry, direct path fallback for finding Python

## Project Structure

- `gui/` — PyQt6 GUI application (run with `python -m gui`)
- `lib/` — Core library (audio processing, ML training, SRT parsing)
- `config/` — Configuration (imports from lib/default_config.py + data/code/config.py)
- `data/recordings/` — Sound recordings (per-label directories with source/ and segments/)
- `data/models/` — Trained models (.pkl + .pth.tar weight files)
- `data/notes.json` — User notes (global + per-model)

## GUI Architecture

- **Pages**: QStackedWidget in MainWindow — **Sounds** (read-only library, default landing), Recording, Training. (`gui/windows/home.py` HomePage exists but is not wired in.)
- **State**: AppState (QObject with signals: recordings_changed, models_changed, talon_status_changed)
- **Widgets**: pyqtgraph-based (audio preview, session card, waveform, segment bar, duration bar, training plot)
- **Workers**: QThread subclasses for recording, training, re-segmentation
- **Services**: gui/services/talon_discovery.py — standalone Talon integration discovery
- **Theme**: gui/theme.py — live-switchable themes; pages may implement `refresh_theme()`
- **Lifetime gotcha**: top-level widgets need a strong Python reference or GC will delete them mid-run — the `MainWindow` is held via `app._main_window` in `gui/app.py`.

## Status & Planning

See `status.md` for current progress and next session plans.
