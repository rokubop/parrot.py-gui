---
name: cross-pc-workflow
description: Development happens on several machines across all three platforms; data/ is gitignored and differs per checkout
type: project
---

Roku develops parrot.py from **several machines and tests on all three
platforms** (Windows, macOS, Linux/WSL). Any given checkout is therefore a
partial view: a machine may be a fresh install, or the primary one with the full
library and a live Talon setup.

`data/` is gitignored (`data/recordings/*`, `data/models/*`, `data/talon/*`,
`data/code/*`, `data/notes.json`). Its contents describe **that machine**, not
the project.

**Why:** `status.md` recorded "20 sound directories / 6 models" as though it were
a project fact. On the 2026-07-25 macOS machine the truth was one sound (`pop`,
~4 s) and zero models, and that claim was about to be repeated back as the
current state. It also means whole categories of behaviour - model details,
stale-recording markers, ensembles, an actual training run - simply cannot be
reached on a fresh checkout.

**How to apply:** Run `ls data/recordings data/models` before making any claim
about available data, and say which machine a claim is about. Never write
per-machine counts into repo docs. When a populated-state path cannot be
exercised locally, say so plainly rather than implying it was verified. A
throwaway workspace is available if one is needed: the config resolves
`RECORDINGS_FOLDER` / `CLASSIFIER_FOLDER` relative to the current working
directory, so running from a temp dir gives an isolated library without touching
the real one.

Related: [[repo-memory-not-user-memory]]
