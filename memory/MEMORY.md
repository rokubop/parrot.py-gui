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
- **Write one only if it is not derivable** from the code, the tests, or
  `git log`. "We fixed X in phase 7" is derivable. "The live and file detection
  paths are deliberately different, and unifying them breaks byte-identical
  output" is not.
- **Delete or rewrite** a memory that turns out to be wrong. A wrong memory is
  worse than a missing one.
- Assistant-side: prefer writing here over user-level Claude memory, which is
  stored per machine and does not follow this workflow. See
  [repo-memory-not-user-memory](repo-memory-not-user-memory.md).

## Index

### How this project is worked on
- [Cross-PC workflow](cross-pc-workflow.md) - several machines, all three platforms; `data/` is gitignored and per-machine, so never infer project state from a checkout
- [Repo memory, not user memory](repo-memory-not-user-memory.md) - why durable context is committed here instead of Claude's own memory
- [Discuss direction before implementing](discuss-direction-before-implementing.md) - design talk up front, then execute decisively without stacking questions
- [Sessions are recorded on "wrap"](../sessions/README.md) - dated, append-only session records; the newest entry's Next steps is where work resumes

### Conventions
- [UI copy style](ui-copy-style.md) - no em dashes anywhere, sentence case, actions name their target
- [GUI design vocabulary](gui-design-vocabulary.md) - one primary accent action per screen, quiet secondary row, centered empty states, the data-quantity rating as shared language
- [Training takes hours, not minutes](training-takes-hours.md) - 4-6 hrs for a real run; stopping early keeps the best model so far
- [Qt traps paid for once](qt-traps.md) - top-level widget GC, stylesheet scoping, word-wrapped labels, pyqtgraph on the UI thread

### Decisions not to re-litigate
- [Audio runs at 16 kHz](audio-rate-is-16khz.md) - the rate the whole parrot ecosystem uses; 48 kHz was tried and reverted
- [No live-stream splicing](no-live-stream-splicing.md) - every edit happens on a saved file, never on the running capture
- [Two-pass detection is file-only](two-pass-detection-is-file-only.md) - live paths keep the online estimator, deliberately
- [Ship a thin shell, not a bundle](ship-a-thin-shell-not-a-bundle.md) - torch makes a monolithic bundle 1-3+ GB and hardware-specific; install heavy wheels on first run
- [The Talon companion is a pure observer](talon-companion-is-a-pure-observer.md) - it wraps `pattern_match` and must never change what Talon does

### Platform traps
- [Windows: torch before Qt](windows-torch-before-qt.md) - the reverse order breaks `c10.dll` silently, and only on Windows
