---
name: repo-memory-not-user-memory
description: Durable project context belongs in memory/ committed to git, because assistant user-level memory is per machine and does not survive this workflow
type: project
---

Durable context for this project lives in **`memory/` in the repo**, committed
to git. Claude Code's own memory lives under
`~/.claude/projects/<project>/memory/` on whichever machine wrote it, so it does
not travel to the other PCs and is invisible to a fresh session elsewhere.

**Why:** On 2026-07-25 several memories were written to user-level memory during
a macOS session, including one about `data/` being per-machine - facts that were
useless on the Windows and Linux boxes the moment they were saved. Roku's own
framing: *"i work cross pc, so claude memory doesn't survive that workflow ...
maybe we need a memory for this repo instead of a status, committed to repo."*

This also replaced `status.md`, which had become a phase-by-phase narrative log:
append-only, written about the past, never revised. It reached the point of
containing corrections to its own earlier sections (a "Known open issues (start
here)" list whose first entry was already fixed, and a note warning that a
paragraph below it was "history, not current state").

**How to apply:** When something durable is learned about this project, write it
to `memory/` and add a line to `memory/MEMORY.md`, rather than to user-level
memory. Keep entries as facts that are true *now* and revise them in place;
leave the record of what happened when to `git log`. User-level memory is still
right for things that genuinely span projects.

Related: [[cross-pc-workflow]]
