---
name: qt-traps
description: PyQt6/pyqtgraph failure modes this project has already paid for once - widget GC, stylesheet scoping, word-wrapped labels, plot building on the UI thread
type: project
---

Each of these cost a real debugging session, and they present as unrelated
symptoms.

- **A top-level widget needs a strong Python reference or the GC deletes it
  mid-run**, surfacing as intermittent `wrapped C/C++ object ... has been
  deleted` on child widgets. Held via `app._main_window` in `gui/app.py`.
- **A selector-less stylesheet on an ancestor silently breaks `:checked`
  background-color on descendant buttons.** Always scope: `QWidget#id { ... }`.
- **A word-wrapped `QLabel` reports a one-line `sizeHint`**, so a layout not
  asked for `heightForWidth` clips it. Fixed width: set
  `setMinimumHeight(heightForWidth(width))`, and re-set it when the text changes.
  Variable width: use `help_dialog.WrappedBody`, which re-asks in `resizeEvent`;
  `sizePolicy.setHeightForWidth(True)` alone does **not** work, the parent chain
  does not propagate it. Centred in a stretchy box, also give it a minimum width
  or it collapses to a tall thin ribbon.
- **pyqtgraph plots must be built on the UI thread**, so the only wins are
  deferring and spreading the work, never moving it off-thread.
- **Anything that unpickles a model (joblib/torch) stutters the UI.** Read model
  labels and accuracy in a `QThread` and cache per name, including the unreadable
  result so a broken model does not retry forever.
