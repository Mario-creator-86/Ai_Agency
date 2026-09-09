# Requirements Traceability Matrix

## Purpose

Prevent requirements from existing only as prose. Each critical requirement must map to:
- implementation subsystem;
- test class;
- roadmap phase;
- acceptance evidence.

## Critical traceability

| Requirement | Implementation | Tests | Phase |
|---|---|---|---|
| Backend = reality | Event/outbox/projection | E2E UI sync, golden replay | 2–3 |
| Director cannot bypass Owner | Policy Kernel/permissions | authority/property tests | 1 |
| No fake successful action | Tool receipts/action lifecycle | realism E2E | 1–2 |
| Durable automation | workflow/scheduler/leases | restart/chaos | 2 |
| Duplicate publish prevention | publication intent/idempotency/reconcile | fault-injected upload | 6 |
| Factual provenance | Source/Claim/Gates | false/conflict/stale tests | 4 |
| Visual factual truth | storyboard/QC | visual plan tests | 5 |
| Dynamic hiring/firing | workforce service | replacement E2E | 8 |
| Correct serial roster | continuity service | historical cast E2E | 9 |
| Private events not public | narrative/public projection | privacy leak tests | 9/11 |
| World changes are real | World Service | placement/commit/UI test | 11 |
| Cost bounds | reservations/budget gate | concurrency/cap tests | 2/10 |
| STOP AUTONOMY | Policy Kernel/orchestrator | external-write blocking E2E | 10 |
| Model drift | evaluation service | regression/revalidation tests | 7–8 |
| Novelty | similarity service | duplicate-topic tests | 4/7 |
| Transferability | export/inventory | export/restore checklist | 10+ |

## Rule

When adding a new critical FR:
1. add it to SRS;
2. add implementation owner/subsystem;
3. add test;
4. add roadmap task;
5. add acceptance criterion.

A requirement without a test/acceptance path is incomplete.


## V4 traceability additions

| Requirement | Primary spec | Supporting spec | Core tests |
|---|---|---|---|
| Dynamic departments | 55 | 19, 03 | org create/merge/dissolve |
| Marketing | 54 | 62, 65 | teaser grounding/campaign |
| Market Intelligence | 56 | 19 | evidence → hypothesis → CEO |
| HR/persona | 57 | 64 | persona isolation/continuity |
| Finance | 58 | 15 | ledger separation/cost control |
| Legal | 59 | 23, 50 | compliance hold |
| Company events | 61 | 07, 41 | event-day pause/story |
| Social adapters | 62 | 22 | capability/idempotency |
