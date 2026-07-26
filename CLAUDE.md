# Parrot.py — Development Notes

## Where things live

| | Holds | Shape |
|---|---|---|
| [`memory/`](memory/MEMORY.md) | Facts that are true **now** | Revised in place, never appended to |
| [`sessions/`](sessions/README.md) | What was done and decided, per session | Dated, append-only, never edited after |
| [`BACKLOG.md`](BACKLOG.md) | Open work beyond the next session | Pruned as things land |
| `git log` | What happened when | — |

**Starting a session:** read `memory/MEMORY.md` (an index — open only what looks
relevant), then the newest entry in `sessions/` for its *Next steps*.

**"wrap"** — when Roku says this, write the session record before anything else,
following the protocol in [`sessions/README.md`](sessions/README.md): create the
dated file, promote anything durable into `memory/`, move longer-horizon items
to `BACKLOG.md`, update the index, and state what was *not* verified as plainly
as what was. "wrap" means all of it, not just the file.

## Project memory — read this first

Durable facts about this repo live in **`memory/`**, committed to git so they
survive across machines. Start at [`memory/MEMORY.md`](memory/MEMORY.md): it is
an index of one-line hooks, so read it in full and open only the entries that
look relevant.

Two that change how you should read everything else:

- **`data/` is gitignored and differs on every machine.** Never infer project
  state from a checkout — check `ls data/recordings data/models` first.
- **Write durable context to `memory/`, not to assistant user-level memory**,
  which is stored per machine and does not follow this workflow.

When something durable is learned, add a file to `memory/` and a line to its
index. Keep entries as facts that are true *now*, revised in place — `git log`
is the record of what happened when.

## Run Scripts: run.sh and run.bat

**IMPORTANT**: `run.sh` (Linux/WSL/macOS) and `run.bat` (Windows) must be kept in sync. When modifying one, always update the other to match. They should have feature parity for:

- Python version detection and acquisition (see **Python bootstrap** below)
- Cross-platform venv detection and recreation prompts
- Network connectivity checks
- Launch failure recovery menu (reinstall deps / recreate venv / exit)
- User confirmation before any destructive or long-running operation

### Division of labour: run scripts vs bootstrap.py

The run scripts do only what *must* be done in shell — everything else lives in
`bootstrap.py`, so venv/pip logic is written once instead of once per platform.

| Step | Owner | Why |
|---|---|---|
| Find or download Python 3.13 | run.sh / run.bat | Nothing else can run yet |
| Linux system libs via apt | run.sh | Needs sudo, Linux only |
| Create venv, install requirements | `bootstrap.py` | One implementation, two platforms |
| Launch `python -m gui`, recovery menu | run.sh / run.bat | Owns the terminal session |

`bootstrap.py` is **stdlib-only** — it runs before PyQt6 exists, so it must never
import from `gui/` or `lib/`. Its progress UI is tkinter, which ships with
CPython (including the downloaded builds). It falls back to text output when
tkinter or a display is unavailable, or with `--console`.

Contract: `bootstrap.py --check` exits 0 if the environment is ready, 3 if work
is needed. A full run exits 0 (ready), 1 (failed), or 2 (user cancelled). It
writes `.venv/.deps_installed` only on success, so a failed install can never
look complete.

### Python bootstrap

Neither script installs Python system-wide by default. Both download a
relocatable prebuilt CPython (python-build-standalone) into a user-level cache:

- macOS: `~/Library/Application Support/parrot.py/python/3.13`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/parrot.py/python/3.13`
- Windows: `%LOCALAPPDATA%\parrot.py\python\3.13`

Override with `PARROT_PYTHON_DIR`; override the download with `PARROT_PYTHON_URL`.

Two decisions worth not re-litigating:

- **No sudo, ever, on the default path.** A GUI progress window cannot answer a
  password prompt — it would either hang on a hidden `Password:` or throw an
  unexplained modal over the UI. This is why the default is a download rather
  than Homebrew/apt/winget, which remain as manual escape hatches.
- **The build is pinned** (`PBS_TAG` / `PBS_PY`, kept in sync across both
  scripts) rather than resolved via the GitHub "latest release" API. The API is
  rate-limited to 60 req/hr per IP, so a shipped app behind a shared NAT could
  fail to bootstrap at all, and two users installing a week apart would
  otherwise get different interpreters.

User-level rather than project-local because an installed bundle is read-only
and code-signed, so it cannot store an interpreter inside itself.

**Clean-room test.** Because nothing lands outside the cache dir, a true
first-run state is repeatable:

```bash
rm -rf .venv "~/Library/Application Support/parrot.py"   # macOS
```

Don't install a system Python or Homebrew on a machine you want to keep as a
clean-room target — that's what makes it a valid test of the zero-install path.
Validated end to end on macOS 14 arm64 from a machine with no Python 3.13, no
Homebrew and no build toolchain: download → venv → ~1.4 GB of deps → app
launches.

### Platform-specific differences (expected)

- `run.sh` (Linux/WSL): pyenv for Python install, apt for system deps, display server check, Qt platform selection for WSL
- `run.sh` (macOS): Homebrew for Python install (pyenv offered as a slower fallback), no system deps, no display server check
- `run.bat`: winget for Python install, PATH refresh from registry, direct path fallback for finding Python

### macOS gotchas

`run.sh` branches on `OS_FAMILY` (`macos` / `wsl` / `linux`), set from `$OSTYPE`. Things that bite if you add a new posix code path:

- **Never call `apt` unguarded.** `/usr/bin/apt` exists on macOS but is Apple's stub launcher for the *Java* annotation processing tool — it links `JavaLaunching.framework` and fails with "Unable to locate a Java Runtime". `command -v apt` therefore succeeds on a Mac with no package manager at all. Use the `has_apt()` helper, which also requires `dpkg`.
- **No `DISPLAY`/`WAYLAND_DISPLAY`.** Qt uses the native Cocoa backend, so the display-server check must be skipped or it aborts before launch.
- **No system audio/Qt libs needed.** The `sounddevice` wheel bundles PortAudio and PyQt6 ships its own Qt frameworks, so the `libportaudio2`/`libgl1`/etc. list is Linux-only.
- **`ping -W` is milliseconds on macOS**, seconds on Linux. Use `-t <seconds>` for a deadline instead.
- Java and Node/npm are **not** dependencies of this project — there is no `package.json`.

## Project Structure

- `gui/` — PyQt6 GUI application (run with `python -m gui`)
- `lib/` — Core library (audio processing, ML training, SRT parsing)
- `config/` — Configuration (imports from lib/default_config.py + data/code/config.py)
- `data/recordings/` — Sound recordings (per-label directories with source/ and segments/)
- `data/models/` — Trained models (.pkl + .pth.tar weight files)
- `data/notes.json` — User notes (global + per-model)

## GUI Architecture

- **Pages**: QStackedWidget in MainWindow — **Home** (default landing: 1-2-3 workflow bubbles, active-model/Talon status, notes), **Sounds** (read-only library), Models, Talon, Settings, About, plus Recording/Edit sub-views.
- **Profiles**: every data path derives from `DATA_DIR` in `lib/default_config.py`, resolved at import: `PARROT_DATA_DIR` env → `data-profiles/current` pointer file → `<root>/data` (Main). The root is `""` in a checkout (a `./data` in cwd keeps legacy relative paths, CLI-compatible) and the platform user-data dir otherwise (AppData / Application Support / XDG — same locations as the Python bootstrap cache). A profile is a full data tree under `data-profiles/<name>/`; switching writes the pointer and relaunches (`gui/services/profiles.py`), so the choice survives dock/start-menu launches. UI is a toolbar chip (hidden until a profile exists) whose dropdown switches; management is a dialog reached from the chip or Settings. `PARROT_TALON_HOME=none` simulates no Talon; the toggle for it shows with `PARROT_DEBUG=1`.
- **State**: AppState (QObject with signals: recordings_changed, models_changed, talon_status_changed)
- **Widgets**: pyqtgraph-based (audio preview, session card, waveform, segment bar, duration bar, training plot)
- **Workers**: QThread subclasses for recording, training, re-segmentation
- **Services**: gui/services/talon_discovery.py — standalone Talon integration discovery
- **Theme**: gui/theme.py — live-switchable themes; pages may implement `refresh_theme()`
- **Lazy construction**: only Home + Sounds build eagerly; every other tab and sub-view constructs on first use via `main_window` getters (window build ~1031 ms → ~322 ms; the remaining ~1.1 s is the unavoidable PyQt6/sounddevice import).
- **Lifetime gotcha**: top-level widgets need a strong Python reference or GC will delete them mid-run — the `MainWindow` is held via `app._main_window` in `gui/app.py`. More traps of this kind in [`memory/qt-traps.md`](memory/qt-traps.md).

## Status & Planning

See `status.md` for current progress and next session plans.
