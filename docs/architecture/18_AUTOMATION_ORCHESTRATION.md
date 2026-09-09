# Automation and Orchestration

## Goal

Run unattended production without fragile prompt chains or dependence on an open browser.

## Durable workflow

A content production cycle is a workflow instance with persistent state.

Every stage has:
- task ID;
- owner agent;
- inputs;
- outputs;
- attempt;
- timeout;
- retry classification;
- idempotency key;
- cost reservation;
- timestamps.

## Retry policy

Classify errors:

### Retryable
- network timeout;
- 429/rate limit;
- transient 5xx;
- worker crash.

### Non-retryable
- invalid credential;
- unsupported capability;
- policy violation;
- missing required source;
- invalid configuration.

### Human/configuration required
- OAuth needed;
- new provider account;
- billing setup;
- missing API key.

Do not retry non-retryable errors endlessly.

## Backoff

Use bounded exponential backoff with jitter where appropriate.

Track retry cost.

## Circuit breaker

Provider/service enters DEGRADED/OPEN state after repeated failures.

Director may route to fallback.

## Leases

Workers claim tasks with leases.

If worker dies:
- lease expires;
- task becomes recoverable;
- idempotency prevents duplicated external effects.

## Exactly-once illusion for side effects

True exactly-once is often impossible across external APIs.

Achieve safe semantics through:
- idempotency key;
- persisted intent;
- remote operation ID;
- reconciliation before retry.

## Scheduler

Persist schedule rules.

Protect against duplicate scheduler leaders.

Store:
- timezone;
- next run;
- last run;
- missed-run policy;
- catch-up policy.

## Local PC

Background worker/service must keep running independently from browser UI.

If PC sleeps:
workflow pauses/fails according to environment.

Always-on mode should move worker/scheduler to server.

## STOP AUTONOMY

Semantics:
- atomic flag;
- new autonomous workflows rejected;
- queued autonomous work paused;
- external write steps blocked;
- active safe read-only tasks may be allowed according to policy.

## Watchdog

Detect:
- task past deadline;
- task stuck in same state;
- missing heartbeat;
- provider job never completing.

Generate incident/event and attempt recovery.

## Reconciliation jobs

Periodic reconciliation:
- pending YouTube publication vs remote state;
- async video generation job vs provider;
- budget reservation vs completed cost;
- stuck agent runtime;
- event outbox.

## Automation observability

Dashboard:
- current workflows;
- queued;
- running;
- blocked;
- retrying;
- failed;
- oldest pending;
- next scheduled;
- last successful daily cycle.

## Daily preflight workflow

Before production:
1. policy/autonomy check;
2. unresolved P0 check;
3. DB/storage health;
4. worker capacity;
5. budget;
6. required provider/auth;
7. channel quota/auth;
8. disk/object-storage;
9. schedule validity;
10. repair queue blocking items.

Only then admit the daily workflow.

## Backpressure

Define resource pools:
- LLM concurrency;
- browser/research concurrency;
- image/video concurrent jobs;
- TTS;
- render workers;
- publishing.

Queue priorities:
1. repair/reconciliation;
2. near-deadline publishable work;
3. current daily production;
4. experiments/benchmarks;
5. speculative idea generation.

## Loop limits

Workflow definition includes:
- max_rework_cycles;
- max_agent_messages;
- max_provider_retries;
- max_total_cost;
- max_total_wall_time.

Crossing limit creates escalation instead of continuing.

## Compensation

For each side-effect:
- compensation supported?;
- safe to retry?;
- reconciliation key?;
- manual repair instructions.

## Manual Repair Queue

Cases:
- external state ambiguous;
- compensation unavailable;
- repeated reconciliation failure;
- corrupt asset;
- credential/manual login required.

The Director can diagnose, but Owner may be required.

## Graceful shutdown

On service stop:
- stop admitting new tasks;
- extend/close leases correctly;
- checkpoint workflows;
- allow safe short tasks to complete or cancel;
- do not orphan external-job IDs.

## Clock/daily boundary

Daily Studio Log uses configured studio timezone.

Store UTC internally and explicit local business date.

Avoid DST creating duplicate/missing close jobs.


# V5 Financial Automation

Daily/periodic automation adds:

- ingest monetization evidence;
- reconcile estimates vs settlements;
- reconcile provider usage vs invoices where available;
- process refunds/chargebacks;
- post eligible ledger transactions;
- refresh treasury projection;
- accrue loan interest;
- check upcoming debt service;
- expire stale procurement quotes;
- update forecasts;
- trigger treasury warnings/freezes;
- prepare Finance/CEO daily financial brief.

Financial side effects require idempotency keys and transactional processing.

No scheduler job may initiate an external product purchase or real financing transaction.
