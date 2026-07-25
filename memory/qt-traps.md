---
name: qt-traps
description: PyQt6/pyqtgraph failure modes this project has already paid for once - widget GC, stylesheet scoping, word-wrapped labels, plot building on the UI thread
type: project
---

Each of these cost a real debugging session. They present as unrelated symptoms.

- **A top-level widget needs a strong Python reference or the GC deletes it
  mid-run.** `create_app()` once held only a local reference to `MainWindow`,
  which surfaced as intermittent `wrapped C/C++ object ... has been deleted`
  errors on child widgets, especially when clicking fast. Held now via
  `app._main_window = window` in `gui/app.py`. If "deleted C++ object" errors
  reappear, suspect a missing reference to a top-level widget, not teardown
  order.
- **A selector-less stylesheet on an ancestor silently breaks `:checked`
  background-color on descendant buttons.** Always scope container stylesheets:
  `QWidget#id { ... }`, never a bare `{ ... }`.
- **A word-wrapped `QLabel` reports a one-line `sizeHint`**, so a layout that is
  not asked for `heightForWidth` clips it. Pin the width and set
  `setMinimumHeight(label.heightForWidth(width))` - and re-set it whenever the
  text changes, since the needed height changes with the copy.
- **pyqtgraph plots must be built on the UI thread**, so the only wins available
  are *deferring and spreading* the work, never moving it off-thread. Cards
  build cheaply with a placeholder and load progressively, one per event-loop
  tick; teardown of a replaced view is deferred to the next tick, because
  destroying the previous view's plots blocks the new one from appearing.
- **Anything that unpickles a model (joblib/torch) stutters the UI.** Read model
  labels and accuracy in a `QThread` and cache per model name; cache the
  unreadable result too, so a broken model does not retry forever.

Related: [[gui-design-vocabulary]]
