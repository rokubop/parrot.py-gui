---
name: discuss-direction-before-implementing
description: Talk through direction and trade-offs before writing code, then execute the agreed scope decisively without stacking further questions
type: feedback
---

For anything with a design dimension, lay out the diagnosis and the options
first, get a direction, and only then build. Once the direction is set, execute
it fully rather than returning with more questions.

**Why:** The UX work on this project is the substance, not a wrapper around it -
a wrong shape costs far more than the code does. Roku will engage in detail on
direction (page structure, empty-state copy, what a newcomer sees first) and
gives concrete steer when shown concrete options. But once a direction is
chosen, follow-up questions are drag; on 2026-07-25 the answer to a scope
question was *"i dont know, i just want to test something you suggest for UX"* -
the choice was being handed back deliberately.

**How to apply:** Open with what is actually wrong today, quoting real strings
and `file:line`, then a recommendation with the trade-off named. Offer options
only where the answer would change the work, and give a recommendation. After
that, pick sensible defaults, build the whole thing, and report what was and was
not verified. Judgement calls made along the way are fine to mention afterwards
rather than ask about beforehand.

Related: [[gui-design-vocabulary]]
