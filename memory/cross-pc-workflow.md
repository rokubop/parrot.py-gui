---
name: cross-pc-workflow
description: Several machines across all three platforms, so any checkout is a partial view and whole features cannot be exercised locally
type: project
---

Roku develops from **several machines and tests on all three platforms**. A given
checkout may be a fresh install or the primary machine with a full library and a
live Talon setup, so whole categories of behaviour - model details, stale
markers, ensembles, a real training run - are simply unreachable on some of them.

Say which machine a claim is about, and never write per-machine counts into repo
docs. When a populated-state path cannot be exercised locally, say so rather than
implying it was verified.

An isolated workspace is available when one is needed: the config resolves
`RECORDINGS_FOLDER` / `CLASSIFIER_FOLDER` relative to the working directory, so
running from a temp dir gives a throwaway library.
