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

Three more read the account behind each bound channel slot and the day's money (since
2026-09-18, after a rehearsal on a copy of the Owner's data found the YouTube lines green
from the stored status alone). `youtube_upload_access` is BLOCKING: it fails when the scopes
Google recorded lack the upload scope, or when a refusal Google gave for the slot's token
(`youtube.token_refresh_failed` with `auth_refused`) still stands — a reconnect or a
successful verification after it answers it — because a day that films and spends and then
cannot upload has spent for nothing, in TEST as in PRODUCTION. `youtube_statistics_access`
is DEGRADING: it fails when the statistics scope was not granted or a token or statistics
refusal stands, and never blocks, because the films do not depend on statistics. Both give
each grant's age and what a seven-day Testing-mode token life would mean, and neither calls
Google: a scope never recorded is unknown, and a failure Google never answered is not a
refusal. `daily_budget_films` is DEGRADING: it asks §8's own estimate for the hold each film
takes and fails when the active DAILY budget cannot hold the day's films at that hold; in
TEST, the PRODUCTION answer is an INFORMATIONAL line. The summary names the first check that
would stop the day or lose a film (`first_stop`), because the summary is what a run records
as its stop reason.

## 2. Previous performance intake

Analytics snapshot ingestion if available.

"If available" is literal (since 2026-09-18): a statistics read that cannot be made — Google
unreachable, a token refresh refused, a report refused for the account — is that
publication's "no data", recorded with the reason and the account to reconnect, and never
the stage's failure. When the account itself was refused, the remaining publications are
recorded with the same reason instead of being asked again, and the refusal is written to
the ledger once for §1 to read.

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
rule. Corrected 2026-09-18: under that rule a failed stage blocked every stage after it, so
"this stage" was in fact the rest of the day; the retest is caught inside the stage and
fails nothing, and since 2026-09-18 a failed stage costs only the stages that depend on it
(*Abort behavior*). Each retest looks again for the site's own search address, and a host that answers 403,
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
at the start of the run.

Tomorrow's script (since 2026-09-24, the Owner's done-condition: one click films today's
episode and writes the next). A second serial stage, `serial_next`, runs after today's log
is closed (§12) and is the last stage of the run. It writes, reviews and — under the
channel's policy on who may approve an episode — approves the episode of today, from
today's log as closed at the run's hour, and makes no storyboard: nothing of a day not yet
over is filmed or bought. The next run's §7 readies that approved episode for filming (an
approved episode with no storyboard is taken up before any new day is told) and its §8
films it. The media stage films a serial episode only once the day it tells is over, so a
same-day re-run films nothing of today, whoever approved it. `serial_next` writes nothing
when today's log is not closed (it waits on §12), when today already has an episode, or
when an earlier episode waits for the Owner's approval or the Director's reading, because
the episode number is fixed on approval.

Every episode carries a plan for the next one — premise, cold-open line, open question and
the threads to pay off — stored as PLANNED. The next writer is handed it and keeps it only
if the day's events support it (the teaser rule of `07_STORY_ENGINE`), says whether it did,
and the plan is closed as KEPT, DROPPED or UNSAID when that episode is approved.

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
studio cannot compute one, never zero, and with the caveat the stage wrote about a figure it
could price only in part — and the hour the oldest expires. Nothing is written when nothing
is waiting, so a silent mailbox still means there is nothing to decide. A vendor's invoice is
reconciled against the estimates of §8 by the Owner and by nobody else, because only he sees
it; that act is not part of the day and is never performed by a stage.

The letter leaves from both ends of the day (corrected the same day, 2026-09-18). The stage
that raises a question writes it in the minute it stops — §8's media stage, as soon as the
approval is recorded — because a question raised at 05:30 must not wait for the last stage
of the run, and a run that never reaches the close must not leave it unsaid until it expires.
The close's call stands, and the day still writes exactly one letter: the business date in
the letter's body is the lock, so whichever end of the day notices first is the one that
writes, and the other writes nothing.

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

What a failed stage costs (since 2026-09-18). Until then any failed stage blocked every stage
after it, and a hard fault in any stage opened SAFE_MODE and set STOP AUTONOMY: on a copy of
the Owner's data one statistics token refused at §2 left the day with nothing researched,
written or filmed, and an HTTP 4xx from Google would have halted the studio. A failed stage
now blocks only the stages that take their input from it, and the rest of the day runs.
Each stage needs what its work actually reads, not what comes before it in the order:

| Stage | Needs | Why |
|---|---|---|
| §2 performance intake | — | the channel slots and their published films; nothing of today |
| §3 idea generation | — | the topic pool and whatever snapshots are stored, empty when unknown |
| §4 research and verification | — | the whole backlog of topics, sources and unverified claims |
| §5 selection | §4 | it chooses only among topics with supported claims, which §4 writes |
| §6 script/storyboard | §5 | it writes for the selected topic |
| §7 serial queue | — | the previous day's log, closed on the preflight line |
| §8 media | §6 **or** §7 | an approved storyboard from either is a film; blocked only when both are lost |
| §9 edit/QC | §8 | the files §8 rendered |
| §10 publish | §9 | what §9 passed |
| §11 post-run | — | the report of whatever happened |
| §12 daily log | — | the record of whatever happened |
| §7 tomorrow's script | §12 | today's closed log, which it writes the next episode from |

A stage is blocked only when every prerequisite it lists failed or was itself blocked, and
its reason names the prerequisite and the fault at the root. A skipped prerequisite blocks
nothing. The Owner's STOP outranks the table — every stage after it is blocked, with no
safe mode and no letter — and a blocked preflight still blocks every stage.

SAFE_MODE follows `21_FAILURE_RECOVERY_PLAYBOOK`'s P0 and nothing else: a hard fault in §8
(the studio no longer knows what it spent), in §10 (it no longer knows what it uploaded) or
in §12 (the audit record), or a database integrity error in any stage. Any other hard fault
— a refused token at §2, a bug in §5 — is P1: it costs its stage and the stages that depend
on it, and the Director writes the Owner once.

The same-day re-attempt follows a blocked preflight, or a failure that cost the day's films
(§5 to §10) and whose cause was transient; a re-attempt runs the whole day again, and must
not choose a new subject and buy a second film to recover a report. A day whose films went
through while another stage failed is PARTIAL — the state the clock reads as a day that ran —
unless the failed stage is §12, which fails the day. Each stage records how many things it
produced, counted from what it returned, and the run's headline says how many stages ran,
how many produced something and how many films were published, so a day of completed
stages that made nothing says so.


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
