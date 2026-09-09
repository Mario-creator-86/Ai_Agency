# Company Calendar, Milestones & Event Engine

## Goal

Allow the AI company to have scheduled in-universe life events that affect real workflow state and generate story material.

Examples:
- team building;
- birthday;
- company anniversary;
- milestone celebration;
- onboarding;
- farewell;
- awards;
- strategy offsite;
- hack day;
- maintenance day;
- emergency drill;
- no-production day.

## Event truth model

A CompanyEvent is a real backend object.

It can intentionally create a **fictional in-universe social event**, but the system must distinguish it from operational facts.

Truth categories:

### OPERATIONAL_EVENT
Something that genuinely happened in production/backend.

### COMPANY_WORLD_EVENT
A committed in-universe event, e.g. virtual team building.

### STORY_EMBELLISHMENT
Dialogue/comedic detail created by Showrunner.

The Story Engine must not confuse these categories.

## Milestone triggers

Configurable examples:
- first 100 subscribers;
- 10K subscribers;
- 1M total views;
- one Short reaches 1M views;
- revenue milestone;
- 100th episode;
- successful month;
- employee anniversary.

A trigger may create a proposal, not necessarily automatic execution.

Example:
`ShortViewsReached(1_000_000)`
→ CEO/HR receives "Team Building" proposal
→ budget/schedule check
→ CEO approves
→ CompanyEvent created.

## Team-building day

If policy says the studio takes the day off:

- ordinary creative production is paused;
- agent availability = OFFSITE / COMPANY_EVENT;
- scheduler does not start ordinary new production;
- essential infrastructure/watchdog/security automation remains running as system services;
- already scheduled public posts may run if policy permits;
- Showrunner may produce the event episode via a designated minimal production path or after the event.

Do not literally shut down reliability/security just to simulate "nobody works."

## Event simulation

For an in-universe event, Event Engine can generate a canonical event plan/outcome using:
- participating personas;
- relationships;
- location/template;
- random seed;
- allowed incident types;
- tone;
- safety rules.

Once approved/committed, event outcomes become `COMPANY_WORLD_EVENT` canon.

Example:
- "The team went bowling."
- "The Director lost to the Security Agent."
- "The Research Agent forgot the trophy."

These are fictional universe facts, not real physical claims about AI models.

## Serial

An event day may produce only the office/life serial.

Example episode:
"Nobody worked today. The studio hit one million views and the CEO took everyone on team building."

The UI can show:
- empty office;
- `TEAM BUILDING` banner;
- optional separate event scene/map later.

## Calendar

Persist:
- event type;
- start/end;
- participants;
- production impact;
- budget;
- approval;
- narrative visibility;
- public visibility;
- status.

Statuses:
PROPOSED
APPROVED
SCHEDULED
ACTIVE
COMPLETED
CANCELLED
ARCHIVED

## Birthdays

Each NarrativePersona may have an in-universe birthday.

Birthday triggers can:
- decorate office;
- generate greeting;
- create cake/party asset;
- create story candidate.

Birthday never changes technical capability or permissions.

## CEO authority

CEO may schedule low-risk world/culture events within budget and policy.

High-cost, public, sponsor-related or business-disruptive events may require Owner approval.


# V5 Event affordability

Milestone events are not automatically free.

Example:
1M-view milestone → HR proposes team building → Finance estimates a market-anchored virtual event budget → Treasury/runway check → CEO approval → VR$ event spend → CompanyEvent.

If Finance rejects it, the rejection itself can become story material.

This preserves the rule that even celebrations live inside the company's constrained economy.
