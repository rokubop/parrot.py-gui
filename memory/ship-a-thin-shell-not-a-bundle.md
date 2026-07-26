---
name: ship-a-thin-shell-not-a-bundle
description: Distribution ships a small launcher that installs heavy wheels on first run; a monolithic bundle has been costed and rejected
type: project
---

**Resist "just ship one executable."** torch pushes a PyInstaller-style bundle to
1-3+ GB and makes it hardware-specific (CPU vs CUDA wheels), so the heavy
dependencies are installed on the user's machine at first launch instead. This
has been costed and rejected once already.

The bootstrapper is built and validated clean-room; CLAUDE.md has the contract
and the no-sudo / pinned-build decisions, BACKLOG has what remains.
