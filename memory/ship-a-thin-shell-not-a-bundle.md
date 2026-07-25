---
name: ship-a-thin-shell-not-a-bundle
description: Distribution ships a small launcher that installs heavy wheels on first run, never a monolithic PyInstaller bundle - torch makes that 1-3+ GB and hardware-specific
type: project
---

The distribution plan is a **thin shell plus a live first-run install**, not an
all-in-one bundle. torch pushes a PyInstaller-style bundle to 1-3+ GB and makes
it hardware-specific (CPU vs CUDA wheels), so the heavy dependencies are
installed on the user's machine at first launch instead.

The bootstrapper half is built and validated clean-room on a fresh Mac:
`run.sh` / `run.bat` fetch a relocatable prebuilt CPython into a user-level
cache, and `bootstrap.py` owns venv creation and dependency install behind a
tkinter progress window. See CLAUDE.md § *Division of labour: run scripts vs
bootstrap.py* for the contract and the no-sudo / pinned-build decisions.

**This does not change the dev loop** - development stays `python -m gui` or
`run.sh`. The presentation shells (Inno Setup on Windows, a `.app` in a `.dmg`
on macOS, AppImage on Linux) *consume* the repo and do not change code, which is
why deferring them is cheap. The macOS shell is the expensive one: it drags in
Apple Developer signing and notarization, which is the main reason it keeps
being deferred.

**How to apply:** Resist "just ship one executable" - it has been costed and
rejected. If dependency install speed becomes the bottleneck behind the progress
window, `uv` in place of pip is the identified next optimization, deliberately
not decided yet.
