# AI Developer Handoff Protocol v3

## Before coding

Every new AI developer must:

1. Read `../architecture/README.md`.
2. Read `../architecture/00_MASTER_PROMPT.md`.
3. Read `CURRENT_STATUS.md`.
4. Read `13_ROADMAP_TODO.md`.
5. Read `16_DECISION_LOG.md`.
6. Read docs relevant to current phase.
7. Inspect code and git status/history.
8. Run baseline tests.

## Task claiming

Before modifying a subsystem, record in `CURRENT_STATUS.md`:
- active task;
- files/subsystem;
- owner/agent identifier if available;
- start time.

This reduces collisions when multiple coding AIs work in parallel.

## Forbidden

Do not:
- restart from scratch;
- create duplicate competing subsystem;
- silently change core invariants;
- mark TODO complete without tests;
- assume external provider behavior;
- replace durable backend behavior with frontend simulation.

## Architectural changes

Update `16_DECISION_LOG.md`.

Include:
- reason;
- alternatives;
- migration;
- test impact;
- rollback.

## End-of-session

Update `CURRENT_STATUS.md`:
- working;
- partial;
- not implemented;
- known bugs;
- external blockers;
- tests run;
- files changed;
- active milestone;
- risks discovered;
- exact next task.

Update:
- TODO;
- changelog;
- decision log if relevant.

## Handoff quality bar

A new coding AI should be able to answer:
- what works;
- what failed;
- which tests prove it;
- what provider credentials are missing;
- what task comes next;
without asking Owner to re-explain the product.

## Machine-readable handoff

Where practical maintain a small machine-readable state file, e.g. `PROJECT_STATE.json`, containing:
- current phase;
- active task;
- last green test commit;
- known blockers;
- configured-but-not-secret provider names;
- migration version;
- feature flags.

Markdown remains human-readable source, but machine-readable state reduces ambiguity for new coding agents.

## No private reasoning dependency

Handoff must contain decisions and evidence, not hidden chain-of-thought.

A future agent should know:
- what was chosen;
- why at a concise level;
- what alternatives were rejected;
- what tests support it.

## Scope claim

Before editing, record:
- subsystem;
- expected files;
- intended outcome.

After editing, remove/release claim.

## Baseline rule

If baseline tests already fail:
- record failures before changes;
- do not attribute them to new work incorrectly;
- avoid broad refactors until baseline state understood.

## Handoff integrity

Never update `CURRENT_STATUS` to "working" merely because code was generated.

Require:
- command run;
- result;
- environment;
- known limitations.
