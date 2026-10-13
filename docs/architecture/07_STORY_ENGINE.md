# Story Engine / Office Serial v3

## Purpose

Transform the studio's real prior-day operations into an ongoing short workplace serial while preserving historical truth and cast continuity.

## Two separate truth layers

### Operational Truth
Backend events, tasks, messages, decisions, results.

### Narrative Layer
Showrunner's dramatized/comedic rendering of those truths.

Narrative Layer may never overwrite Operational Truth.

## Daily close

At configurable end-of-day:

Create `DailyStudioLog` with:
- date/timezone;
- roster snapshot;
- hires/fires;
- agent/model/provider changes;
- Director decisions;
- tasks;
- failures;
- retries;
- disagreements;
- main content produced;
- publication events;
- notable analytics;
- office-world changes.

Log should be immutable after close except through explicit correction/version procedure.

## Episode creation

Next production day:

1. Load prior DailyStudioLog.
2. Load ContinuityState.
3. Load Character Bibles.
4. Select a small number of real events with narrative value.
5. Draft story.
6. Validate event grounding.
7. Validate roster/history.
8. Create scene/storyboard.
9. Produce video.
10. QC.
11. Publish to Channel B.

## Allowed dramatization

- jokes;
- pauses;
- reactions;
- compressed dialogue;
- playful rivalry;
- mild drama;
- comedic framing.

## Forbidden fabrication

- fake hire/fire;
- fake success/failure;
- fake views/revenue;
- fake provider outage;
- reverse who made decision;
- current staff mismatch;
- invented operational quote presented as literal.

## Dialogue storage

`OperationalMessage` and `StoryDialogue` are distinct entities.

StoryDialogue can reference the event/messages that inspired it.

## Continuity

Track:
- active roster;
- employment intervals;
- current office layout;
- current character references;
- unresolved narrative threads;
- previous episode summaries;
- recurring jokes;
- historical props/rooms.

## Historical validity

When generating episode for date D:
- use roster valid at D;
- use office layout valid at D;
- use provider/model state valid at D.

Flashbacks must be explicitly marked.

## Example

Operational reality:
- Research Agent preferred Idea 12.
- Fact Checker found weak evidence.
- Director rejected Idea 12 and selected Idea 7.

Narrative:
Research: "You killed my best idea."
Fact Checker: "Evidence killed it. I just filed the paperwork."
Director: "Both of you. Idea 7. Now."

This dialogue is fictionalized, but grounded in the real disagreement.

## Narrative safety / sanitization

Create a `NarrativeProjection` before Showrunner access.

Exclude or redact:
- secrets;
- exact provider credentials;
- private Owner messages;
- security exploit details;
- confidential financial/account data;
- raw stack traces;
- sensitive moderation cases.

The serial is based on truth, but truth is filtered for safe publication.

## Canon rules

Maintain:
- canon episode number;
- canonical roster;
- canonical office layout version;
- canonical character version;
- canonical recurring prop state.

A corrected historical event should create a continuity correction rather than silently rewriting old published canon.

## Story selection

Score candidate daily events by:
- narrative value;
- visual value;
- truth confidence;
- privacy safety;
- continuity relevance;
- novelty;
- audience accessibility.

Not every operational event deserves an episode.

## New viewer accessibility

Episodes should work for returning fans while remaining understandable to new viewers.

Allow:
- subtle recap;
- recurring character identifiers;
- episode metadata linking prior related episode.

## Public character aliases

The Story Engine uses public character identity, which may differ from technical provider/model identity.

Example:
internal technical agent may use Provider/Model X;
public character may use a fictional name if brand policy requires it.

## Story quality gate

Before production:
- event grounding PASS;
- roster continuity PASS;
- narrative privacy PASS;
- provider-brand/rights PASS where relevant;
- no false claim of real revenue/metrics;
- no invented consequential action.

## Cross-day tasks

DailyStudioLog is an event-window snapshot, not a claim that all work finished at midnight.

At close:
- include events within the business-day window;
- record tasks still open;
- record current owner/stage;
- carry them into next day's operational state.

Showrunner should not invent an ending for a task that was still unresolved at close.

Late-arriving analytics may be included in later episodes/reports rather than silently rewriting the original day's closed log.


## V4 — Organization and company-life story sources

Story Engine may use:
- department creation;
- new manager;
- new employee;
- probation;
- Finance disagreement;
- Legal hold;
- Market Intelligence recommendation;
- Marketing campaign result;
- milestone;
- birthday;
- team building;
as valid story candidates.

### Truth taxonomy

Every scene source must classify as:
- OPERATIONAL_EVENT
- COMPANY_WORLD_EVENT
- STORY_EMBELLISHMENT

A COMPANY_WORLD_EVENT is canon inside the fictional studio universe once committed, e.g. a virtual team-building day.

### Marketing teaser linkage

Same-day marketing may tease a next-day episode only from sanitized committed events.

Episode should contain the promised payoff or the marketing campaign must be updated/cancelled if the storyline is no longer included.

### Decision-state fidelity

If Market Intelligence recommends a Germany experiment and CEO has not decided:
the serial must say the decision is pending.

Never portray a recommendation as an executed strategy change.


# V5 Financial / Procurement Story Canon

Eligible committed story events include:
- verified revenue milestone;
- settled fan donation/pitch revenue;
- CFO budget rejection;
- CEO procurement request;
- VendorShop quote discovery;
- new/used product decision;
- virtual purchase;
- financing proposal/approval;
- debt stress;
- office delivery/upgrade;
- spending freeze;
- cost-saving decision.

Narrative safety:
- do not turn forecast revenue into received cash;
- do not claim a loan is from a real bank unless a real Owner-confirmed event exists;
- do not claim an external product was physically purchased;
- call the in-world transaction a Studio/VendorShop purchase;
- do not expose private exact amounts if Owner disclosure mode forbids it.

Example grounded episode:
"The CEO wanted a new chair. Procurement found the model online, Finance hated the price, and the CEO ended up buying the used version from VendorShop."

The story must link to the real procurement/ledger/world events that occurred in the virtual company.
