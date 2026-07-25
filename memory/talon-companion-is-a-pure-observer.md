---
name: talon-companion-is-a-pure-observer
description: The Talon bridge wraps pattern_match and only observes - it must never change what Talon does; the replay state machine is verified frame-identical
type: project
---

`talon_companion/parrot_gui_bridge.py` (installed from the GUI) wraps Talon's
`pattern_match`, **calls the original**, and publishes per-frame JSON over UDP to
`127.0.0.1:8352` - power, formants, class probabilities, active, throttled,
grace - plus a heartbeat. It is a pure observer and must stay one: it runs
inside someone's live, working Talon setup, where changing behaviour would be a
real cost to them.

Two related invariants:

- **The A/B replay uses a port of the integration's state machine that is
  verified frame-identical** to the real thing (4000 random frames including
  grace and throttle, 0 mismatches, tested by exec'ing the real integration's
  classes with Talon stubbed). If the integration changes, re-run that
  equivalence check - a replay that silently diverges is worse than no replay.
- **Talon hot-reloads `patterns.json`** (`@resource.watch`), so Deploy applies
  live. Every deploy snapshots first (`data/talon/snapshots`).

**Validation earns its keep:** pattern validation caught 6 real dead throttles
in the live `patterns.json` - sound names written where pattern names are
required.

**How to apply:** Keep observation and control separate. If the GUI ever needs
to *change* live Talon behaviour, that is a new, explicit mechanism, not an
extension of the bridge. See `prd-talon.md` for the original intent.
