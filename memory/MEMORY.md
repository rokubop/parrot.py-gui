# Project memory

Durable facts about this repo and how it is worked on, committed to git so they
survive across machines and across assistant sessions. **This replaces the role
`status.md` was serving.**

One file per fact. This index is the only thing meant to be read in full - open
an individual file when its line looks relevant.

## The rules

- **A memory is a fact that is true now**, revised in place when it stops being
  true. It is never a log of what happened on a given day; git history already
  holds that, and it cannot contradict itself the way a log can.
- **Write one only if a fresh agent could not work it out from the codebase.**
  Conventions visible in the code, and anything that happened in a session, do
  not belong here - `git log` and `sessions/` already hold those. What belongs is
  what the code cannot say: a decision and its rejected alternative, a trap that
  cost a debugging session, an empirical number, a "do not "fix" this".
- **Delete or rewrite** a memory that turns out to be wrong. A wrong memory is
  worse than a missing one.
- **Keep it short.** An entry nobody rereads is worse than no entry. If it needs
  a paragraph of background, the background probably belongs in a session record.
- Assistant-side: prefer writing here over user-level Claude memory, which is
  stored per machine and does not follow this workflow.

## Index

### How this project is worked on
- [Cross-PC workflow](cross-pc-workflow.md) - several machines, all three platforms; any checkout is a partial view, so whole features cannot be exercised locally
- [Discuss direction before implementing](discuss-direction-before-implementing.md) - design talk up front, then execute decisively without stacking questions
- [Sessions are recorded on "wrap"](../sessions/README.md) - dated, append-only session records; the newest entry's Next steps is where work resumes

### Conventions
- [UI copy style](ui-copy-style.md) - no em dashes; as few words as can be glanced at; say what someone has before what they lack
- [GUI design vocabulary](gui-design-vocabulary.md) - only the shape decisions that reading `gui/` does not already show: two-state sub-views, teaching beside the control, which knobs may hide
- [Training takes hours](training-takes-hours.md) - 4-6 hrs for a real run; the page measures its own ETA; stopping early keeps the best model so far
- [Qt traps paid for once](qt-traps.md) - top-level widget GC, stylesheet scoping, word-wrapped labels, pyqtgraph on the UI thread, showMessage hiding the status bar's widgets
- [Preview playback avoids sd.play()](preview-playback-avoids-sd-play.md) - its Python callback needs the GIL and crackles while the playhead repaints; latency is compensated, never buffered away
- [Detection calibration needs onset valleys](detection-calibration-needs-onset-valleys.md) - no threshold until 10+ spectral-flux valleys, so synthetic audio can silently segment to nothing; use the manual override path
- [App icon regeneration](app-icon-regeneration.md) - master file, macOS 824-grid tile geometry and colors, per-platform variants

### Decisions not to re-litigate
- [Audio runs at 16 kHz](audio-rate-is-16khz.md) - the rate the whole parrot ecosystem uses; 48 kHz was tried and reverted
- [Mic provenance is captured, not derived](mic-provenance-is-captured-not-derived.md) - `mici_<n>` is a mic index and must never be resolved to a device name after the fact; the name is written to a `_mic.json` sidecar at record time
- [No live-stream splicing](no-live-stream-splicing.md) - every edit happens on a saved file, never on the running capture
- [Two-pass detection is file-only](two-pass-detection-is-file-only.md) - live paths keep the online estimator, deliberately
- [Ship a thin shell, not a bundle](ship-a-thin-shell-not-a-bundle.md) - torch makes a monolithic bundle 1-3+ GB and hardware-specific; install heavy wheels on first run
- [The Talon companion is a pure observer](talon-companion-is-a-pure-observer.md) - it wraps `pattern_match` and must never change what Talon does

### Platform traps
- [Windows: torch before Qt](windows-torch-before-qt.md) - the reverse order breaks `c10.dll` silently, and only on Windows
