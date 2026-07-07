# PRD: First-Party Talon Support

## Vision

You start Parrot.py to manage **everything** related to parrot: files, sounds,
models, thresholds, patterns, deployment, and live testing. Talon is not an
export target you copy files at — it's a first-class surface of the app. The
record → train → **test** → **deploy** → **tune** loop closes inside the GUI.

`talon-parrot-tester` (the user's Talon-side project) proved the observation
UX — especially the **live frames table**. It was never meant to be an editor.
This design ports that observation UX into the GUI and adds what the tester
deliberately never shipped: safe editing, validation, versioning, and A/B
comparison of `patterns.json`.

## Ground rules (learned the hard way, don't violate)

1. **Never evaluate patterns.json semantics on non-Talon data.** The
   `>power` / `f0/f1/f2` values in patterns.json are *Talon engine units*.
   parrot.py's own power/dBFS are different numbers. Simulating "would this
   threshold fire?" against our own mic pipeline produces confident nonsense.
   Pattern semantics are only ever evaluated against frames that came from
   Talon itself (live bridge or recorded captures).
2. **The integration file is the schema authority.** The user's
   `parrot_integration.py` declares `possible_keys = {sounds, detect_after,
   threshold, graceperiod, grace_threshold, throttle}` and
   `possible_thresholds = {>,<} × {power, f0, f1, f2, probability, ratio}`.
   The editor validates against *the parsed integration file* when available
   (falling back to this known set), so a future integration version with new
   keys doesn't get its data destroyed by us.
3. **Round-trip fidelity.** Reading and re-saving a patterns.json must
   preserve unknown keys and key order (ordered dicts everywhere). We are a
   guest in this file.
4. **Nothing is overwritten without a snapshot.** Every write to the deployed
   patterns.json goes through an automatic timestamped snapshot (same
   philosophy as the clip-edit UndoHistory).
5. **Two different questions, two different tools, never blurred:**
   - "Is my *model* good?" → standalone mic test with per-sound
     probabilities (parrot.py's own pipeline; no patterns semantics shown).
   - "Is my *deployed setup* right?" → Talon-truth frames via the bridge.

## Architecture

### New top-level tab: **Talon**

Sub-navigation within the tab: **Status · Patterns · Live · Captures**.

### Service layer (Qt-free, unit-testable, like `library_ops`)

- `gui/services/talon_discovery.py` — exists; gains: parse
  `possible_keys`/`possible_thresholds` from the integration file, and
  "which local model matches the deployed one" (compare_model_files exists).
- `gui/services/patterns_store.py` — load/save with round-trip fidelity;
  snapshot-on-write to `data/talon/snapshots/<timestamp>__<name>.json`;
  named **variants** in `data/talon/variants/<name>.json`; diff between any
  two versions; "deploy variant" = snapshot current + copy over the
  Talon-referenced path.
- `gui/services/patterns_schema.py` — validation:
  - *schema*: known keys, value types, threshold-op syntax;
  - *referential*: every `sounds` entry ∈ deployed model's classes; every
    `throttle` target ∈ pattern names; duplicate sound assignments flagged;
  - *sanity*: probability ∈ (0,1], power/f0 plausible ranges, throttle
    seconds ∈ (0, 5), graceperiod ranges;
  - severity levels: error (won't save) / warning (saves with badge).
- `gui/services/talon_bridge.py` — localhost socket client (JSONL frames),
  reconnect loop, session recording to `data/talon/captures/*.jsonl`.
- `talon_companion/parrot_gui_bridge.py` — a small Talon-side module (lives
  in THIS repo, GUI offers "Install into Talon" using discovery's user-dir).
  Wraps `parrot_delegate` exactly the way talon-parrot-tester's wrapper does
  and publishes per-frame JSON: ts, power, f0/f1/f2, per-pattern
  probability/status (detected / grace / throttled). Also accepts commands:
  `reload_patterns`, `ping`. Bidirectional but dumb on purpose.

### The A/B killer feature: offline replay

A recorded capture contains, per frame, everything patterns.json semantics
need (power, formants, per-sound probability). Therefore threshold edits can
be re-evaluated **against a recorded session without re-performing sounds**:

> Record a 2-minute session of your real usage once → edit `>probability`
> from 0.93 to 0.96 → the Captures view immediately shows which of the
> recorded detections would have fired / dropped under the edit, side by side
> with the current version.

Throttle/grace are sequential-state semantics — the replayer implements the
same state machine as the integration (PatternTimestamps logic, ~80 lines,
port faithfully with tests). This makes A/B comparison *deterministic and
free*, instead of "perform the same sounds twice and eyeball it".

## Views

### Status (discovery + health)
- Talon: Found/Not found, paths (integration, patterns.json, deployed model).
- Deployed model ↔ local models match (file compare), with "Deploy model…"
  (snapshot + copy + optional patterns sound-rename assist when classes
  differ).
- Companion: Installed/Not installed/Connected, version, Install/Update
  button.
- Health lints: patterns referencing sounds the deployed model lacks, unused
  model classes, throttle targets that aren't patterns.

### Patterns (the editor)
- Table: name · sounds (chips) · >power · >probability · other thresholds ·
  throttles (count, expandable) · grace · detect_after · lint badge.
- Edit panel (guided): sounds picker fed by deployed-model classes;
  threshold rows with op dropdown (from schema authority) + numeric field
  with range hints; throttle editor with pattern-name dropdown; live
  validation as you type.
- Raw JSON toggle with the same validation on save.
- Variants bar: current (deployed) + named variants; New/Duplicate/Diff/
  Deploy/Rollback (snapshots browsable).
- Every deploy → auto-snapshot → Talon reload via companion (or "touch
  integration file" fallback; manual instruction if neither).

### Live (ported tester UX, Talon-truth data)
- **Frames table** (the most valuable view, port faithfully): frame id ·
  Δts · pattern · power · prob · F0/F1/F2 (toggle) · status chip ·
  power×prob bar with threshold tick. Capture-buffered like the tester
  (bursts between silences group into captures).
- Detection log and per-pattern stats pages after the table works.
- Record button → saves session as a capture.
- Standalone model mic-test (no Talon required) lives under Models, not
  here, to keep the two questions separate (ground rule 5).

### Captures (A/B workbench)
- List of recorded sessions; open one → frames table of the recording.
- "Evaluate against…" → pick current/variant/edit → same table with
  fired/dropped/changed markers + summary (per pattern: detections before /
  after, throttles hit, grace saves).
- Side-by-side variant comparison on the same capture.

## Phasing

- **A. Foundation** — Talon tab + Status view (discovery, model match,
  health lints), patterns_store with snapshots, read-only patterns table
  with full validation/lint display. *Zero risk, immediately useful.*
- **B. Editor** — guided editing + raw JSON + variants + deploy/rollback.
- **C. Bridge** — companion module + install flow + Live frames table +
  capture recording.
- **D. A/B workbench** — replayer state machine (with unit tests against
  hand-built frame sequences) + Captures view + variant evaluation.

Each phase ships usable on its own. A+B alone already beat hand-editing JSON;
C ports the tester's value; D is the feature no one else has.

## Risks / notes

- Companion ↔ GUI protocol versioned from day one (`{"v": 1, ...}`).
- Companion must fail silent-and-safe inside Talon (never break voice).
- Integration variants in the wild differ; schema-from-integration parsing
  falls back to permissive known-set validation (ground rule 2).
- talon-parrot-tester stays the in-Talon ground-truth overlay; the companion
  is deliberately smaller (publisher, not UI). They can coexist; long term
  the tester could consume the same publisher.
- Windows-first: socket on 127.0.0.1 works from WSL-hosted GUI too, but the
  primary target is the native Windows run (`run.bat`).
