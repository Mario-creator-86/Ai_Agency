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

The research check answers whether the studio can find pages at all, not whether an
authorised site exists as a row (`research_health`, since 2026-09-18). It reports how many
hosts are authorised, how many were read successfully, how many carry a search address,
which are failing and under which reason code, whether a search engine is verified, and how
many verified claims are in hand. It reads the record and opens no connection, so it is safe
on every run. It is DEGRADING, and it degrades the day when no host passed, when there is no
way to find pages at all, or when fewer than ten verified claims remain. The counts are in
the check's detail as well as in the message a passing check shows, because the run they are
needed for is the one where the check failed.

Five further checks answer whether the day is worth having, not whether it can start
(since 2026-09-18). They name the things only the Owner can supply, and like the research
check each reads the record and opens no connection: `spending_budget`, whether any budget
is active at all, since with none the reservation still holds a film's money and has no
limit to refuse it against; `model_prices`, whether the models the day's employees think
with carry a price on both token units, since a cost priced on one side only is None and
every run of that employee is recorded without one; `vision_capability`, whether any active
employee's model the provider says can see, since without one the picture and character
checks stand down on every film and a film of blank fields passes every automatic check;
`character_references`, which characters hold no readable reference picture — a stored asset
id whose row exists and whose file is still on disk; and `serial_channel`, whether the
serial's slot is bound to a connected account and whether the Director has the Owner's leave
to approve episodes.

None of the five is BLOCKING, and two of them cannot degrade the day at all. A preflight
check must not refuse the day for something the Owner deliberately chose: a budget he has
not set while the studio is in TEST and a serial channel he has not created are answers of
his, so `serial_channel` is INFORMATIONAL always and `character_references` is DEGRADING
only where a character whose look is *locked* has no readable reference — that case really
does refuse a film, and it is a blocked day he can prevent the evening before. The verdict
is computed over BLOCKING and DEGRADING only, so this holds structurally and not by the
checks happening to pass.

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

Pages are found in this order (`find_pages`, since 2026-09-18): the Owner's own search
address for an authorised site; then the address the studio discovered on that site itself
(OpenSearch, stored as a finding, which never overrides the Owner's decision); then a
verified search engine, whose results are filtered against the allowlist before anything
downstream sees them, the rest dropped and counted. Every page is then read by the studio's
own DNS-pinned retriever — never the engine's cached copy, snippet or "answer", which would
be fetching through a third party what the studio would not fetch itself. The allowlist is
the Owner's rows: no agent, no request and no search result can widen it.

The weekly retest of authorised hosts lives inside this stage and not in a scheduled job of
its own (`retest_stale_hosts`, seven days): only hosts nobody has tested for a week are read,
one front page each, so on the other six days the pass fetches nothing and costs the sites
nothing. A retest that fails costs this stage and never the studio, by the Phase A fault
rule. Each retest looks again for the site's own search address, and a host that answers 403,
limits requests or serves a script-only shell is recorded FAILED with a reason from a closed
vocabulary the preflight can show without parsing prose.

## 5. Selection

Director chooses production candidate under policy.

## 6. Script/storyboard

Script → hook → storyboard.

Run claim/visual consistency checks.

## 7. Next-day serial queue

Prepare Channel B production job from previous-day safe narrative events.

Runs before Media (the order of `STAGES` in the runbook code since 2026-09-17) so that the
same run writes, reviews, films and routes the episode instead of leaving its storyboard for
the next day; it still prepares Channel B from the previous day's closed log, which is closed
at the start of the run, while today's log (§12) stays last.

## 8. Media

Reserve budget.

Generate assets/video/voice.

Use fallback if needed.

"Reserve budget" is literal since 2026-09-18. The film is priced before a frame is made —
the motion at the ceiling this render will be given, the narration at the dearest active
per-thousand price over the storyboard's own voiceover — and the sum is **held**: a
reservation row written behind the write lock, which every budget check counts until it ends,
so two films asked for in the same second cannot both be told the last ten dollars are free.
The day's remaining budget is read one line before the hold is written, so a film never
counts its own reservation against itself.

The hold is settled only after the real cost rows for that render are written: between the
two the film is counted twice rather than not at all, which is the error a budget may make.
It is released on every path where the film was not made — the Owner's stop read between two
scenes, an encoder that cannot run, a vendor's refusal, which is costed first because the
vendor charges for the shot it generated whether or not the film was finished. A hold left by
a process that died under a render is released by the watchdog once it is older than the
reservation TTL, six hours. A refusal by the budget is not a silent SKIPPED line: the
Accountant writes to the Owner once per business date.

## 9. Edit/QC

FFmpeg/render.

Technical + factual + rights + policy QC.

## 10. Publish

Create publication intent.

Check idempotency.

Publish/schedule if allowed.

Verify remote ID.

## 11. Post-run

Reconcile cost.

Persist provenance.

Update office/status.

The close writes the Owner one letter about the approval requests still standing, as its
first act and before any question is put to a model (`waiting_approvals_letter`, since
2026-09-18): one letter per business date, decided behind the write lock like the budget
refusal letter of §8, naming each question by what it is, with its cost — unknown where the
studio cannot compute one, never zero — and the hour the oldest expires. Nothing is written
when nothing is waiting, so a silent mailbox still means there is nothing to decide. A
vendor's invoice is reconciled against the estimates of §8 by the Owner and by nobody else,
because only he sees it; that act is not part of the day and is never performed by a stage.

## 12. Daily Studio Log

At configured end:
- close immutable log;
- sanitize narrative projection;
- save continuity.

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
