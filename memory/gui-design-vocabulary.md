---
name: gui-design-vocabulary
description: The shared shape every GUI page follows - one primary accent action, a quiet secondary row, centered empty states, sub-views for focused work, and the data-quantity rating as common language
type: project
---

The GUI pages are deliberately built from one small vocabulary. A new page that
invents its own shape is the thing to avoid.

- **One primary action per screen**, accent-filled (`objectName="primaryAction"`)
  and visually distinct: `+ Add recording` on Sounds, `+ Train a model` on
  Models, `Test live` on a selected model. Everything else - rename, clone,
  open folder, delete, combine - is a flat, dim `secondaryAction` row. Rank is
  the message: the primary action is the one that moves the workflow forward.
- **Empty states are a centered title / body / call-to-action panel**, and they
  branch by what the user actually has. Models has three (nothing recorded, one
  sound, ready to train); Sounds has two. The page header hides entirely when
  nothing is selected, since every control in it acts on a selection.
- **Focused work is a full-screen sub-view, not a panel**: recording, editing,
  and training each take the whole window and return via `← Back to X`. The
  parent page stays a library. `MainWindow` owns the stack and the lazy getters;
  sub-views report completion with a `done` signal carrying what to reselect.
- **Gate before the click, not after.** State what is missing continuously and
  keep the action disabled until it is not, rather than accepting input and
  refusing on submit.
- **The data-quantity rating is the app's shared language for "is this enough?"**
  (`get_quantity_rating()` in `lib/print_status.py`, colours in
  `theme.QUANTITY_COLORS`, explained in About). It appears in the Sounds tree,
  the per-sound header, the training checklist, and the empty-state summaries -
  same words, same colours, everywhere. Reuse it rather than inventing another
  measure of readiness.
- **Expert knobs fold away.** Net count sits behind an "Advanced" disclosure,
  defaulted, with a sentence explaining what it buys.
- **Pages that render theme colours implement `refresh_theme()`.**

**Why:** The app is aimed at someone who has never made a model and will return
to it months later. Consistency of rank and vocabulary is what makes the second
page free to learn once the first has been.

Related: [[ui-copy-style]] · [[qt-traps]]
