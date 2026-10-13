# Failure and Recovery Playbook

## Philosophy

Failure is normal in an autonomous external-API system. Design recovery before autonomy.

## Common failures

### LLM
- timeout;
- malformed structured output;
- hallucinated tool result;
- context overflow;
- provider model removed;
- rate limit.

Response:
- validate schema;
- retry bounded;
- fallback if compatible;
- block if capability missing.

### Research
- page unavailable;
- JS-only page;
- paywall;
- robots restriction;
- contradictory sources;
- stale data;
- prompt injection.

Response:
- alternative source;
- mark uncertainty;
- never bypass restrictions.

### Video/Image
- provider job fails;
- reference drift;
- generation censored;
- wrong aspect ratio;
- invalid file;
- cost spike.

Response:
- retry bounded;
- alternate provider;
- simpler storyboard;
- QC fail.

### TTS
- unavailable voice;
- pronunciation issue;
- audio corruption.

Response:
- fallback voice/provider;
- regenerate segment;
- QC.

### FFmpeg
- missing codec;
- corrupted input;
- timing mismatch.

Response:
- validate inputs;
- capture stderr;
- re-render.

### YouTube
- OAuth expired;
- quota;
- upload timeout;
- remote upload succeeded but local response lost;
- scheduled publish rejected.

Response:
- reconcile remote state before retry;
- never blind-upload again.

### Database
- unavailable;
- migration failure;
- transaction conflict.

Response:
- do not proceed with external side effects if local state cannot be recorded safely.

### UI/WebSocket
- disconnected;
- stale;
- duplicate event.

Response:
snapshot + replay.

## Incident severity

P0:
risk of duplicate publish, uncontrolled spend, secret leak, corrupted audit state.
Action:
STOP AUTONOMY automatically.

P1:
production blocked, provider unavailable, repeated failures.
Action:
pause affected pipeline, route fallback, notify.

P2:
single task/content failure.
Action:
retry/rework.

## Automated stop conditions

Potential:
- budget anomaly;
- repeated duplicate-side-effect risk;
- DB unavailable during external-write stage;
- publishing reconciliation failure;
- security incident.

## Recovery record

Every incident:
- cause;
- affected workflow;
- action;
- final result;
- manual steps;
- prevention recommendation.

## Failure state matrix

Every subsystem should document:
- detection;
- retryable?;
- fallback?;
- compensation?;
- reconciliation?;
- escalation severity;
- Owner action?;
- data-at-risk?;
- side-effect-risk?.

## Ambiguous success

Treat ambiguous external writes as a special failure class.

Examples:
- upload may have succeeded;
- payment/real commerce future may have succeeded;
- provider job may exist even if client timed out.

Rule:
**reconcile before retry**.

## Safe mode

P0 can put studio into SAFE_MODE:
- no external writes;
- no new expensive generation;
- monitoring/read-only analysis allowed;
- repair/reconciliation prioritized.

SAFE_MODE is distinct from full application shutdown.

## Data integrity incident

If audit/event/DB consistency is doubtful:
- block new external writes;
- snapshot/backup if safe;
- run integrity checks;
- require repair before autonomy resumes.

## Provider-quality regression

A provider can be healthy but bad.

Trigger degraded role suitability on:
- schema failure spike;
- QC rejection spike;
- character drift;
- unexpected cost/latency.

## Human-required incident

Create persistent Owner task with:
- exact problem;
- why automation cannot resolve;
- safe steps;
- what remains paused;
- resume verification.


# V5 Financial Failure Recovery

## Duplicate revenue event
- quarantine duplicate;
- do not mint;
- log idempotency conflict.

## Chargeback after money spent
- post reversal;
- allow temporary deficit/liability according to policy;
- trigger treasury stress;
- do not rewrite history.

## Stale/unavailable product listing
- mark quote expired/unavailable;
- do not purchase;
- re-source quotes.

## FX source unavailable
- do not invent rate;
- retry alternate approved source or require manual rate evidence.

## Ledger imbalance
- reject transaction;
- enter financial safe mode if needed;
- alert Owner.

## Financing reference unavailable
- block financing proposal finalization;
- do not make up market rate.

## Asset generation fails after purchase
- purchase remains committed;
- create fulfillment issue;
- retry/replace Asset Architect workflow;
- do not refund automatically unless configured world-policy creates a VendorShop refund/reversal.
