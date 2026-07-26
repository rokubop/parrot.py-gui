---
name: ui-copy-style
description: No em dashes anywhere; as few words as can be glanced at; say what someone has before what they lack
type: feedback
---

Match the tone of surrounding strings for the ordinary things. These three are
not guessable from the code:

- **No em dashes**, in UI copy or repo docs. Use a spaced hyphen (` - `) or
  restructure.
- **As few words as can be glanced at.** A paragraph on a working screen is the
  same as an empty screen. Prefer a question, a picture that answers it, and one
  line. If something needs a paragraph it probably belongs on a different screen,
  so delete it rather than keep an abbreviated second copy. A term worth teaching
  gets attached to a picture as a label; one that cannot be stays out of the UI,
  however correct it is.
- **Say what someone has before what they lack**, and prefer a measurement to a
  verdict on a first attempt. A new sound scoring a red "Not enough" reads as
  failure rather than a starting point, so empty states quote seconds instead.

Workflow copy shared across pages lives in `gui/widgets/help_dialog.py`.

Related: [[gui-design-vocabulary]]
