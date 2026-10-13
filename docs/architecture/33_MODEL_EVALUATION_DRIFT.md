# Model Evaluation and Drift

## Problem

A model/provider can change quality, cost or behavior without changing application code.

## Evaluation layers

### Capability test
Can it technically do the required task?

### Contract test
Does adapter/API response conform?

### Quality benchmark
Is output good enough for the role?

### Live quality monitoring
Is production performance still within baseline?

## Benchmark suite

Each role has versioned benchmark cases.

Examples:
- research source selection;
- factual verification;
- schema adherence;
- script quality;
- hook quality;
- continuity reasoning.

Never benchmark only on one prompt.

## Drift signals

- structured-output failure;
- tool-call error;
- QC rejection;
- hallucination rate;
- latency;
- cost;
- refusal behavior;
- character consistency;
- provider model alias changed.

## Revalidation triggers

- provider announces version change;
- model ID changes;
- baseline worsens;
- prompt major version changes;
- provider API contract changes;
- periodic schedule.

## Role suitability

Status:
- APPROVED;
- APPROVED_DEGRADED;
- TESTING;
- UNSUITABLE;
- UNKNOWN;
- STALE.

Director may route only according to policy.

## A/B and shadow

A candidate can shadow production:
- same input;
- output not published;
- compare with incumbent.

This gives safer hiring decisions.

## Evaluation contamination

Do not allow a candidate to train/optimize directly on hidden test labels during the same evaluation loop.
