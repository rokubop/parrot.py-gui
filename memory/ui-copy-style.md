---
name: ui-copy-style
description: No em dashes anywhere in UI copy or docs; sentence case; actions name their target; state what someone has before what they lack
type: feedback
---

House style for every user-visible string, and for repo docs:

- **No em dashes.** Use a spaced hyphen (` - `) or restructure the sentence.
  There are currently zero em dashes in `gui/` and that is deliberate
  (commit `5a5f1d3`, "no em dashes").
- **Sentence case** for help-row bodies and panel copy; literal sound names and
  filenames keep their own casing wherever they fall.
- **A row body reads as its own sentence**, not as a continuation of its label
  (`help_dialog.py:14`).
- **Actions name their target**: `+ Add recording to "pop"`, not `Add recording`.
  A take always belongs to a sound, and a bare verb reads as free-floating.
- **Say what someone has before what they lack.** Telling a user who has
  recorded a sound to "record some sounds" reads as though their work went
  missing.
- **Prefer a neutral measurement to a verdict on someone's first attempt.** A
  brand-new sound scoring a red "Not enough" reads as failure rather than as a
  starting point, so the empty states quote seconds of detected sound instead
  (`library.py`, `models.py`).

**Why:** The copy is the interface for a tool whose whole difficulty is that the
user cannot see what the model hears. Tone in the empty and blocked states is
what decides whether a newcomer keeps going.

**How to apply:** When adding any label, tooltip, status line, or help row,
check it against the list above before wiring it up. Workflow copy shared across
pages belongs in `gui/widgets/help_dialog.py`, which is the single source of
truth for it.

Related: [[gui-design-vocabulary]]
