---
name: gui-design-vocabulary
description: The few GUI shape decisions that are not visible by reading gui/ - two-state sub-views, teaching beside the control, and which knobs are allowed to hide
type: project
---

Reading `gui/` shows the vocabulary: one accent `primaryAction` per screen, a dim
`secondaryAction` row, centered empty states, full-screen sub-views, the
`get_quantity_rating()` colours as shared language, `refresh_theme()`. Copy those
by looking at an existing page. What follows is only the parts a new page cannot
infer:

- **A sub-view with two jobs is two states, not two columns.** Training is set up
  once and then watched for hours; those screens share nothing, so the page swaps
  layouts. If half a screen is empty in one phase and dead in the other, that is
  the signal.
- **Teach beside the control, with a picture**, not behind a `?`. A drawing that
  restates something the code computes has to compute it the same way, or it
  quietly lies.
- **Gate before the click:** say what is missing continuously and keep the action
  disabled until it is not, rather than accepting input and refusing on submit.
- **A knob folds away only when getting it wrong is cheap.** Net count is not
  such a knob: at 1 net an unlucky random start *is* the model, and you find out
  hours later.

**Why:** The app is aimed at someone who has never made a model and will return
to it months later.

Related: [[ui-copy-style]]
