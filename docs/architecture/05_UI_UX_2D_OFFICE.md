# UI/UX — Top-Down 2D Office v3

## 1. Product role

The 2D office is a **primary product interface**, not a decorative screensaver.

It must make a complex autonomous backend understandable at a glance.

The user should immediately see:
- who is employed;
- who is working;
- what they are working on;
- who is communicating;
- where the current production is;
- what is blocked;
- what the Director is deciding;
- which providers are healthy;
- what changed recently.

## 2. Perspective

Use a polished **top-down / slightly isometric-feeling 2D office** only if the chosen art style supports readability. The user specifically needs to be able to see the whole office from above.

Initial version:
- one large, attractive open-plan room;
- Director area;
- role-specific desks/zones;
- provider/server corner;
- production flow visible.

Future:
- add rooms;
- remove rooms;
- expand office;
- meeting room;
- research room;
- video studio;
- sound booth;
- analytics room;
- Director private office;
- decorative areas.

The layout must be data-driven.

## 3. Visual quality

The office should feel coherent enough that a fan might leave the page open to watch it.

Avoid:
- generic admin dashboard aesthetic;
- random mismatched sprites;
- excessive flashing;
- unreadable tiny labels;
- animations unrelated to work;
- fake busywork.

Prefer:
- consistent art direction;
- clear silhouettes;
- subtle ambient animation;
- readable status indicators;
- persistent character identity;
- smooth camera pan/zoom;
- sensible room proportions.

## 4. Backend-backed state

The frontend does not decide whether an employee is working.

It renders a server projection.

Examples:

Backend says:
`WAITING_EXTERNAL(video_job_912)`

UI:
Video Agent visibly waits; status says "Waiting for Video Provider".

Backend says:
`RETRYING`

UI:
Agent may show retry/error animation.

Backend says:
`TERMINATED`

UI:
departure sequence begins only after termination committed.

## 5. Pending vs success

Important visual states:

- PENDING;
- ATTEMPTING;
- WAITING;
- CONFIRMED;
- FAILED;
- BLOCKED.

Do not animate a celebratory success before CONFIRMED.

## 6. Character system

Every active employee has a deterministic live-office CharacterIdentity.

For live office, prefer sprites/model sheets or other persistent 2D assets rather than regenerating characters through AI each session.

Character data:
- character ID;
- sprite sheet;
- palette;
- role prop;
- idle;
- walk;
- work;
- think;
- talk;
- wait;
- error;
- celebrate;
- leave.

Dynamic cast:
- fired employee removed from current roster;
- new employee receives a persistent new identity;
- history remains accessible.

## 7. Speech

### Live speech bubbles
Only from real operational agent messages.

### Serial dialogue
Never shown as live operational speech unless a matching actual message existed.

## 8. Agent Inspector

Click employee:
- name;
- role;
- employment state;
- backend runtime state;
- current task;
- task stage;
- provider/model;
- fallback;
- required/available capabilities;
- tools;
- permissions;
- prompt version;
- cost/budget;
- recent messages;
- errors;
- performance;
- employment history.

Owner controls where allowed:
- pause/resume;
- send instruction;
- change model/provider;
- benchmark;
- adjust tools/permissions;
- suspend;
- fire.

Every control sends a backend command and waits for authoritative result.

## 9. Director UI

Director should be visually distinctive.

Director area/screens:
- production;
- workforce;
- providers;
- budget;
- strategy;
- experiments;
- incidents.

When Director is deciding:
show real `THINKING/REVIEWING` state.

When decision requires Owner approval:
show an approval icon/state, not a fake executed change.

## 10. Provider / Server Room

Each provider object displays backend status:
- HEALTHY;
- DEGRADED;
- RATE_LIMITED;
- OFFLINE;
- NOT_CONFIGURED;
- UNKNOWN.

UNKNOWN must look different from HEALTHY.

## 11. Content movement

Represent each ContentItem as a persistent project token/card.

As backend stage changes:
the token moves between areas.

Click:
- topic;
- stage;
- agent;
- source/claim status;
- script;
- assets;
- cost;
- errors;
- timeline.

## 12. Office world changes

Rooms/furniture are persistent backend entities.

Future example:
Director buys a fountain.

Flow:
purchase command
→ budget/economy validation
→ backend world transaction
→ `office.item_purchased`
→ layout update
→ frontend renders fountain
→ Story Engine can use event next day.

No frontend-only purchases.

## 13. Camera / navigation

- fit whole office;
- pan;
- zoom;
- click-focus employee;
- "follow current production";
- "follow Director";
- reset view.

## 14. Activity timeline

A real event timeline should accompany animation.

Examples:
- 09:01 Idea Agent started.
- 09:03 Research #42 assigned.
- 09:06 Source added.
- 09:10 Fact Checker requested rework.
- 09:14 Director selected Idea #7.

Clicking entry opens provenance.

## 15. Failure visualization

Errors should be understandable.

Example:
`HTTP 429 / video provider`

UI:
Video Agent warning.
Provider Room RATE_LIMITED.
Task = RETRYING in 120s.

## 16. Public fan view — future

Public view must be a sanitized projection.

It may show:
- characters;
- safe activity;
- non-sensitive status;
- polls.

It must not show:
- secrets;
- raw prompts if private;
- stack traces;
- internal security details;
- credentials;
- private Owner commands.

## 17. Performance

- 60fps target where practical;
- avoid full scene rerender;
- asset atlases/caching;
- cap expensive effects;
- reduced motion mode.

## 18. UI acceptance invariant

Given a backend state snapshot and event stream, the UI must reconstruct the same operational office state deterministically.

## 19. Thinking visualization without private reasoning

A THINKING animation only means an actual agent/model job is running.

The UI may show:
- "Comparing 3 providers";
- "Reviewing 6 research sources";
- "Evaluating Script Writer benchmark";
- progress/stage.

Do not expose or fabricate raw hidden chain-of-thought.

## 20. Live vs replay mode

The office must visibly distinguish:
- LIVE;
- PAUSED VIEW;
- HISTORY REPLAY;
- DEMO/MOCK.

Pausing the camera/replay must not imply pausing backend workflows.

Historical replay should use recorded events and timestamp watermark.

## 21. Animation queue semantics

Animations are derived presentation.

If backend produces events faster than animations:
- compress/skips intermediate cosmetic movements;
- never delay authoritative displayed status;
- show latest committed state.

Operational accuracy outranks watching every walk animation.

## 22. State badges

Each agent should expose small status badges for:
- task;
- provider/model;
- waiting reason;
- error/retry;
- public/private visibility where relevant.

Avoid forcing users to infer important operational state from animation alone.

## 23. Responsive/public viewing

Owner desktop is primary.

Future public view should also support:
- responsive web;
- spectator-focused layout;
- simplified inspector;
- low-bandwidth mode;
- reduced motion.

## 24. Office editor constraints

Future Director/world-builder changes must use a supported layout grid/schema.

The UI should validate:
- room overlap;
- inaccessible desks;
- object collision;
- invalid asset;
- missing sprite;
before committing the final layout.

## 25. Visual truth QA

Add automated/debug overlay:
- entity ID;
- event ID;
- task ID;
- state version.

Developer mode can compare frontend projection with backend snapshot in real time.


## V4 — Departments, culture and event days

The office must visualize committed organizational growth.

Examples:
- Marketing team gets a new area/room.
- Finance appears as a new desk/department.
- Legal room opens.
- Market Intelligence team meets with CEO.
- HR conducts onboarding.

Department rooms/labels derive from backend Department + World State.

### Event-day mode

For a team-building/no-production day:
- office may be visibly empty;
- banner/sign shows the CompanyEvent;
- agents may have OFFSITE state;
- optional event scene/map can be added later.

Do not show agents working at desks if workflow admission says ordinary production is paused.

### Personal touches

Agent persona may influence:
- desk decorations;
- birthday decoration;
- avatar expression;
- harmless props.

Persistent props require backend World/Persona state if they affect continuity.


# V5 Financial UI

Add Owner/CEO-accessible financial surfaces:

## Treasury panel
- Spendable VR$
- Restricted/reserved VR$
- Pending payouts
- Receivables
- Current debt
- Accrued interest
- Runway
- Burn rate
- Today's/month's revenue and spend
- Alerts

## Forecast panel
- 30 / 90 / 180 day views
- BASE / BULL / BEAR scenarios
- confidence range
- channel/platform contribution
- upcoming provider costs
- planned procurement
- debt service

Forecast values must be visually distinct from posted ledger cash.

## Procurement / VendorShop

Create a storefront-like interface that shows only quoted/approved market-backed items:
- image/reference if permitted;
- model;
- NEW/USED;
- source;
- price;
- VR$ equivalent;
- shipping/tax status;
- quote age/expiry;
- Finance status;
- Legal/IP status if needed.

Clicking `BUY WITH VR$` creates a backend command. It never opens/executes an external checkout.

## Office representation

Finance/Procurement actions can be visible in-world:
- CFO reviewing budget;
- Procurement searching;
- VendorShop quote received;
- Asset Architect building an item;
- delivery/placement event.

These animations still obey backend-event truth.
