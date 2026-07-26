# 2026-07-26 - The training page teaches, in pictures rather than paragraphs

**Branch:** `sounds-ux-and-recording-perf` · **Machine:** macOS (2 thin sounds,
0 models)

Roku opened by saying the Models flow does not feel right next to Sounds, and
listed what the app never tells a newcomer: how the model picks a sound, why you
would record a noise you *don't* want, how many nets, how long it takes, whether
to leave it overnight, what an epoch is, what to watch.

## What was done

**Trainer bug: every second run in a session was broken** (`lib/audio_net.py`)

`nets`, `optimizers`, `train_loaders`, `validation_loaders`, `random_seeds` and
`train_indices` were class attributes that `__init__` only appended to, so all
trainers in a process shared them. The CLI never noticed (one process, one
model); the GUI shares a process, so a second run's `range(net_count)` reached
into the *first* run's trained nets, wired to the first run's loaders and sized
to its label count. Now instance lists. Repro'd both ways before fixing.

**The training page is two states, not two columns** (`train_view.py`, rewritten
on a `QStackedWidget`). Setup: decisions left, pictures right. Running: the form
collapses to a summary line and the screen goes to ETA, curves and per sound
accuracy. A failed run gets a route back to setup.

**Teaching went on the page, then was cut by ~90%.** First version was three
topics of label/body rows, ~450 words. Roku: *"if i have to read paragraphs,
that is the same as putting no info on the page."* Now three blocks of question +
picture + one line, ~40 words total:

- `ClosedSetDiagram` - the same table bump into two models differing only by
  whether it was recorded: `pop ✗` vs `table bump ✓`, sub-labelled `distractor`.
  Replaced a first attempt that drew the vocabulary with a crossed-out "none of
  these" box: correct, and it taught nobody anything.
- `BalanceBars` (new) - live from the ticked sounds. Dataset balancing had never
  been surfaced anywhere: `generate_data_balance_strategy_map` targets
  `mean + std/2`, truncates above `1.25x` it, oversamples below `target/1.25`. So
  240s of one sound against 40s of the rest throws away half that session.
- `NetsDiagram` - moved out of the `?` modal, `3 is usual` beside the spinner.

**The run says what it is doing.** Measured ETA and finish clock, timed from the
first reported epoch so the load does not inflate it. Per sound accuracy bars -
the worker always emitted the dict, the view discarded it. `stage_changed` and
`run_started(max_epochs)` added to the worker. No more empty axes before epoch 1.

**Two of my own errors, caught in-session.** `BalanceBars` first shaded
everything above target as waste (truncation only applies above `1.25x`), then
computed target with `statistics.stdev` while the trainer uses `np.std`
(population), putting the line ~5s off.

## Decisions

- **Two states, not two columns.** Rejected: keeping the form beside a progress
  panel and filling the empty half. The form is disabled during the run anyway.
- **No pre-dialog like `+ New sound`.** That dialog exists because the
  alternative was a bare text prompt with nowhere to put advice; this page has a
  whole column.
- **Cut, don't shorten.** Advice about which noises make good sounds was deleted
  rather than trimmed - it already lives in "Choosing sounds".
- **`distractor` in the UI, "closed set" not.** The picture teaches the concept;
  the term isn't glanceable. Offered, not taken up.
- **Not "discriminative classifier"** (Roku's half-memory) - that contrasts with
  *generative*. The property that bites is the closed set.
- **The balance line is a reference mark** ("a bit above average"), always drawn,
  after versions that hid it and that called it "cut back to here". Both worse.
- **A guessed pre-run estimate beats none**, shown as a wide range, because
  "hours" cannot answer "can I start this at 11pm".

## Verified / not verified

Verified offscreen on this machine: the trainer bug and fix by running a repro;
all six tabs build against the real `AppState`; seven training states rendered to
PNG and inspected (renders caught clipped help copy, a ribbon of centred text,
and the balance line drawn through bars keeping all their data); balance maths
against the trainer's rule; duration and clock formatting including midnight.

**Not verified** - unchanged from last session and still blocking:

- **No training run has ever completed through the GUI.** ETA, per sound bars and
  the stage message have only seen fabricated epochs. Making a second run
  *possible* is not the same as a first run working.
- `TRAIN_SECONDS_PER_AUDIO_SECOND_PER_NET = 3.2` rests on one measured run and a
  guess about how much audio it held.
- The per sound dict is the last net's validation pass, not the ensemble (read,
  not observed).
- Nothing committed; two new widget files untracked. Nothing on Windows or Linux.

## Also

Pruned `memory/` at Roku's request against a harder test - an entry earns its
place only if a fresh agent could not work it out from the codebase. Deleted
`repo-memory-not-user-memory.md` (duplicated CLAUDE.md); cut seven entries by
roughly half; wrote the test into the rules in `MEMORY.md`. The 2026-07-25
session file still links the deleted entry, which is correct - session records
are archival and describe what was true that day.

## Next steps

1. **Record two proper sounds and train end to end.** Also validates the trainer
   fix, the ETA, the per sound bars and the stage message. Then press "Train
   another" to confirm a second run works.
2. **Replace the estimate constant** with a measured value from that run.
3. **Commit** - the work is unstaged, `balance_bars.py` and
   `per_label_accuracy.py` untracked.
4. **GPU check on Windows** - carried over, one line, likely the largest win
   available.
