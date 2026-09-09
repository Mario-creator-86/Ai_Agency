# Daily Autonomous Runbook

## 0. Preconditions

Scheduled Studio Business Date determined in configured timezone.

## 1. Preflight

Check:
- STOP AUTONOMY;
- unresolved P0;
- DB;
- workers;
- storage;
- budget;
- provider routes;
- research;
- media;
- TTS;
- YouTube auth/quota;
- policy versions.

Result:
READY / DEGRADED / BLOCKED.

## 2. Previous performance intake

Analytics snapshot ingestion if available.

Growth Agent creates evidence-based recommendations.

Director may update bounded strategy.

## 3. Idea generation

Generate candidate pool.

Deduplicate/similarity filter.

Score:
- interest;
- credibility;
- source availability;
- visual potential;
- novelty;
- cost.

## 4. Research and verification

Research selected candidates.

Fact-check.

Reject unsupported.

## 5. Selection

Director chooses production candidate under policy.

## 6. Script/storyboard

Script → hook → storyboard.

Run claim/visual consistency checks.

## 7. Media

Reserve budget.

Generate assets/video/voice.

Use fallback if needed.

## 8. Edit/QC

FFmpeg/render.

Technical + factual + rights + policy QC.

## 9. Publish

Create publication intent.

Check idempotency.

Publish/schedule if allowed.

Verify remote ID.

## 10. Post-run

Reconcile cost.

Persist provenance.

Update office/status.

## 11. Daily Studio Log

At configured end:
- close immutable log;
- sanitize narrative projection;
- save continuity.

## 12. Next-day serial queue

Prepare Channel B production job from previous-day safe narrative events.

## Abort behavior

At any stage:
- hard gate fail → block;
- retryable failure → bounded retry;
- ambiguous external effect → repair/reconcile;
- P0 → SAFE_MODE.


## V4 Marketing loop

During day:
- event sanitizer identifies TeaserEligibleEvent;
- Marketing may create same-day teaser;
- platform schedule executes within campaign policy.

End of day:
- DailyStudioLog closes;
- Showrunner chooses tomorrow episode;
- teaser promises are checked against selected episode.

Next day:
- episode produces/publishes;
- Marketing distributes follow-up;
- attribution begins.

## Company-event day

Preflight checks Company Calendar.

If `PAUSE_ORDINARY`:
- do not start normal production;
- keep essential system services;
- execute event-specific story/marketing plan;
- record EventOutcome;
- update continuity.


# V5 Daily Finance Cycle

Before ordinary production:
1. reconcile previous-day financial evidence;
2. process settled platform income and reversals;
3. post eligible VR$ ledger entries;
4. accrue interest/debt obligations;
5. refresh treasury balance and runway;
6. validate daily provider/content budgets;
7. expire stale procurement quotes;
8. create Finance brief for CEO;
9. apply treasury freeze rules if required.

End of day:
- close financial operational snapshot;
- record revenue/cost estimates separately from settlements;
- produce forecast delta;
- include public-safe financial events in Daily Studio Log when story-relevant.
