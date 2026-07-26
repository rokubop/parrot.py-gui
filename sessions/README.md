# Session records

One file per working session, committed. **Newest is the one that matters** -
the normal way to start work is to read the latest entry's *Next steps*.

Sessions are **archival**. They are dated records of what was true and what was
decided on a given day, they are never edited after the fact, and it is fine for
an old one to be out of date - the date is right there. That is what makes them
safe.

This is the opposite of [`memory/`](../memory/MEMORY.md), which holds facts that
are true *now* and is revised in place. Anything durable that comes out of a
session gets promoted into `memory/`; the session file records that it happened.
Keeping the two apart is the whole point: `status.md` collapsed them into one
append-only document and rotted into self-contradiction, with a "start here"
section whose first item was already fixed and a warning that the paragraph
below it was "history, not current state".

## Wrapping a session

When Roku says **"wrap"**, write the session record before doing anything else:

1. Create `sessions/YYYY-MM-DD-short-slug.md` (add `-2`, `-3` for more than one
   session in a day) from the template below.
2. Promote anything durable into `memory/` - a new file plus its index line, or
   an edit to an existing entry. Prefer editing an existing memory over adding a
   near-duplicate.
3. Move anything longer-horizon into [`BACKLOG.md`](../BACKLOG.md); keep *Next
   steps* to what the very next session should actually pick up.
4. Add the new file to the index below, newest first.
5. Report what was **not** verified as plainly as what was. A session record
   that overstates is worse than none, because the next session builds on it.

Do not wait to be asked for the parts after step 1 - "wrap" means all of it.

## Template

```markdown
# YYYY-MM-DD - <title>

**Branch:** <branch> · **Machine:** <macOS / Windows / Linux>

## What was done
<Grouped by area. Link file:line for anything specific.>

## Decisions
<Each with the alternative that was rejected and why. Note which were
promoted to memory/.>

## Verified / not verified
<What was actually run, and what could not be checked on this machine.>

## Next steps
<What the next session should pick up first. Be specific enough to act on
without re-deriving context.>
```

## Index

- [2026-07-26 - The training page teaches, in pictures rather than paragraphs](2026-07-26-training-page-teaches.md)
- [2026-07-25 - Models page onboarding, and replacing status.md](2026-07-25-models-onboarding.md)
