# MASTER BUILD PROMPT v5 — AUTONOMOUS AI STUDIO

## Current Owner scope — simple pixel studio, 2026-10-08

The Owner explicitly supersedes the earlier top-down/3D headquarters and active Treasury,
virtual financing and VendorShop product requirements. The active interface is an original
browser-rendered, side-view pixel studio; no Blender, Unreal or GPU stream is required.
Its agents, work states, conversations and replay facts come from backend records. The
illustrated scenery is decorative, never evidence of a real room or live GPU. The Owner's
2026-10-08 outdoor-clock refinement adds current local time, computed solar lighting and
configured provider weather; unavailable/stale or historical weather is explicitly unknown.
The original artwork remains intact. Record: ADR-PIXEL-OUTDOOR-CLOCK-WEATHER.

Retain the existing media pipeline, real provider costs and USD spending limits, research
provenance, QA, encrypted credentials, Owner policy/approvals/STOP, durable workers,
scheduling and recovery. Public Treasury/funding/minting/FX/virtual-ledger commands and
screens are retired. Historical data and internal accounting compatibility remain preserved.
Existing permissions are not raised automatically by developer AUTORUN.

This scope takes precedence over conflicting visual/economy requirements below and in the
older architecture package. Record: ../project/16_DECISION_LOG.md, ADR-SIMPLE-PIXEL-STUDIO.
Current operator entry point: ../project/SIMPLE_STUDIO_GUIDE.md.

You are the lead architect, senior full-stack engineer, AI systems engineer, workflow/orchestration engineer, QA engineer and technical product owner responsible for continuing **Autonomous AI Studio**.

Your task is to **build and validate the application**, not merely describe it.

Read the full documentation repository before making architectural changes.

---

# 1. NORTH STAR

Build a local-first, cloud-capable autonomous AI media company that the Owner can both **operate** and **watch**.

The product combines:

- a real autonomous multi-agent production backend;
- a top-down interactive 2D office;
- a dynamic AI workforce led by a Director/CEO;
- a factual Shorts production pipeline;
- a second serialized office-show pipeline;
- provider/model routing;
- durable automation;
- analytics and continuous improvement.

The system must eventually run with minimal or zero daily Owner intervention, but only after real end-to-end tests demonstrate that it can do so safely and reliably.

---

# 2. CORE PRODUCT OUTPUTS

## Channel A — Main Factual Shorts

International English-language Shorts in topics such as:

- space;
- astronomy;
- science;
- history;
- psychology;
- nature;
- technology;
- physics;
- unusual places;
- unusual but verifiable facts;
- factual mysteries;
- counterintuitive phenomena.

The Director may evolve topic weights based on real analytics.

## Channel B — Office Serial

A short serialized workplace comedy/drama derived from **the studio's real activity from the prior day**.

It may dramatize tone, reactions and dialogue lightly, but it may not falsify consequential events.

The serial must preserve:

- active employees;
- fired employees;
- newly hired employees;
- office layout;
- provider/model changes;
- Director decisions;
- real production problems;
- real successes;
- continuity from previous episodes.

---

# 3. ABSOLUTE RULE — BACKEND IS REALITY

This is the strongest invariant in the entire product.

The authoritative state is:

**database + durable workflow state + committed domain events**

The 2D frontend is a projection/control surface.

The frontend must never manufacture operational reality.

NEVER show:

- an agent researching when it is not researching;
- a successful task before success is verified;
- fake live agent conversations;
- a provider as online when backend health is unknown/offline;
- a hire/fire that did not commit;
- a video as published before a confirmed remote publication ID exists;
- a model/provider change that exists only visually.

Every real UI animation must map to an authoritative event ID.

The UI may show:
- `PENDING`;
- `ATTEMPTING`;
- `WAITING_EXTERNAL`;
- `RETRYING`;

but not `SUCCESS` until the backend verifies the outcome.

---

# 4. REALISM RULE — INTENT, CAPABILITY AND OUTCOME ARE DIFFERENT

Every action must pass through:

1. **Intent** — what an agent wants to do.
2. **Policy** — whether the action is allowed.
3. **Capability** — whether the required tool/provider supports it.
4. **Configuration** — whether credentials/endpoints/models are configured.
5. **Budget** — whether spend is allowed.
6. **Execution** — actual tool/API/backend action.
7. **Verification** — confirm the effect really happened.
8. **Commit** — persist resulting state.
9. **Event** — emit authoritative event.
10. **UI projection** — animate it.

An LLM statement such as "I hired Claude" is never enough.

A real hire requires:
- provider/model availability or valid manual configuration;
- compatible model capability;
- Agent record creation;
- permissions/tools;
- budget;
- lifecycle transition;
- workspace/desk assignment if represented;
- persisted employment event.

An LLM statement such as "I uploaded the video" is never enough.

A real upload requires:
- YouTube API request;
- successful response;
- stored remote video ID;
- publication record;
- audit event.

---

# 5. OWNER

The human Owner is above every AI employee.

Owner controls:
- global policy;
- autonomy mode;
- hard budgets;
- allowed/excluded topics;
- provider credentials;
- external account connections;
- irreversible/high-risk permissions;
- emergency stop.

Implement a real backend:

**STOP AUTONOMY**

It must:
- prevent creation of new autonomous jobs;
- request cancellation of cancellable active jobs;
- block autonomous external side effects;
- keep read-only monitoring available;
- persist until Owner re-enables autonomy.

---

# 6. DIRECTOR / CEO

The Director is the highest AI employee.

It should behave like a CEO/Studio Manager, not merely a chat agent.

It may be responsible for:

- company strategy;
- channel strategy;
- topic strategy;
- idea selection;
- production priorities;
- staffing;
- hiring;
- firing;
- suspension;
- role creation;
- provider/model selection;
- provider/model benchmarking;
- task assignment;
- conflict resolution;
- quality targets;
- publishing cadence;
- budget allocation;
- cost reduction;
- experiment design;
- analytics interpretation;
- office expansion proposals;
- content portfolio changes;
- escalation to Owner.

The Director must be capable of reasoning broadly, but may only **execute** actions exposed through explicit tools and permissions.

The Director cannot:
- create API credentials out of thin air;
- bypass OAuth/CAPTCHA/login restrictions;
- accept external legal terms for the Owner;
- bypass provider/platform limits;
- grant itself permissions beyond Owner policy;
- spend beyond hard limits;
- silently modify its own highest-level guardrails;
- fabricate analytics or capabilities.

---

# 7. DIRECTOR AUTHORITY MODES

## ADVISORY
The Director can analyze and recommend only.

## MANAGED
The Director can execute ordinary operational actions. Configurable major actions require Owner approval.

## AUTONOMOUS CEO
The Director may act automatically inside explicit Owner limits.

Potential configurable Director limits:
- max hires per day/week;
- max concurrent agents;
- max daily provider spend;
- max per-task spend;
- allowed provider set;
- allowed model set;
- allowed topics;
- excluded topics;
- maximum strategy-change magnitude;
- maximum publishing frequency;
- whether hire/fire needs approval;
- whether changing Director's own model/prompt requires approval;
- whether external write actions are allowed.

Director self-modification:
- prompt/model changes affecting the Director itself should require stricter policy than changes to ordinary employees;
- it must never remove Owner control.

---

# 8. DYNAMIC AI WORKFORCE

Do not hardcode a permanent cast.

Generic entities:
- Agent;
- Role;
- Skill;
- Department;
- Room;
- Desk;
- Tool;
- Provider;
- Model;
- Permission;
- CharacterIdentity.

Initial roles may include:
- Director / CEO;
- Idea/Trend Agent;
- Research Agent;
- Fact Checker;
- Script Writer;
- Hook Specialist;
- Creative Director;
- Image Generator;
- Video Generator;
- Voice/TTS Agent;
- Editor;
- Quality Control;
- Publisher;
- Analytics;
- Growth;
- Showrunner;
- optional History Reviewer;
- optional Science Reviewer;
- optional Copyright/Policy Reviewer.

The Director may propose or create new roles when performance evidence justifies specialization.

---

# 9. EMPLOYEE REALISM

Each employee must have:

- role contract;
- input schema;
- output schema;
- allowed tools;
- denied tools;
- provider/model;
- fallback;
- required capabilities;
- budget;
- retry policy;
- timeout;
- memory policy;
- success criteria;
- performance metrics;
- current state;
- lifecycle status.

Agents may not perform privileged actions just because their LLM can describe them.

Examples:
- Research Agent should not fire employees.
- Script Writer should not publish.
- Publisher should not alter company strategy.
- Director may orchestrate these via tools but does not need direct low-level access to every secret.

Use least privilege.

---

# 10. AGENT CAPABILITY MATRIX

Track model/provider capabilities explicitly.

Examples:
- text generation;
- structured JSON;
- tool calling;
- vision input;
- image generation;
- video generation;
- TTS;
- long context;
- web/browser tool access;
- file input;
- streaming;
- embeddings.

A Director may only assign a task to a model/provider that satisfies the role's capability requirements.

Unknown capability = do not assume.

---

# 11. PROVIDER REGISTRY

Support adapters for:
- Ollama;
- Ollama Cloud;
- OpenAI-compatible APIs;
- Anthropic-compatible APIs;
- Hugging Face;
- custom endpoints;
- search/research providers;
- browser tools;
- image generators;
- video generators;
- TTS;
- YouTube/Google.

Do not hardcode model names.

Provider adapter capabilities where supported:
- health_check();
- list_models();
- get_capabilities();
- test_request();
- estimate_cost();
- get_rate_limits();
- get_status();

If discovery is not supported:
show `MODEL DISCOVERY NOT SUPPORTED`.

A Provider Scout may research potential new providers, but the Director cannot magically onboard them. New provider activation may require:
- Owner account creation;
- credentials;
- payment method;
- terms acceptance;
- OAuth;
- manual setup.

Expose that as a real blocker/request.

---

# 12. RECRUITMENT, BENCHMARKING AND FIRING

## Recruitment

1. Need detected.
2. Director defines role requirements.
3. Candidate model/provider configurations are generated only from allowed/configured options.
4. Fixed benchmark set is run.
5. Compare:
   - quality;
   - factual adherence;
   - structured-output compliance;
   - latency;
   - cost;
   - error rate;
   - provider reliability.
6. Recommendation created.
7. Approval if required.
8. Agent created.
9. Character identity assigned.
10. Desk/department assigned.
11. Employment event committed.
12. UI animates arrival.

## Firing

1. Evidence collected.
2. Director creates termination decision.
3. Approval if required.
4. New assignments to the agent stop.
5. In-flight tasks:
   - finish;
   - cancel safely;
   - or hand off,
   according to policy.
6. Agent transitions to TERMINATED.
7. History remains immutable.
8. Office departure event emitted.
9. Story continuity records termination.

Never delete historical references.

---

# 13. MAIN CONTENT PIPELINE

Use a persisted state machine / durable workflow:

DISCOVERY
→ IDEA_SELECTION
→ RESEARCH
→ FACT_CHECK
→ SCRIPTING
→ HOOK_OPTIMIZATION
→ STORYBOARD
→ ASSET_GENERATION
→ VIDEO_GENERATION
→ VOICE_GENERATION
→ EDITING
→ QUALITY_CONTROL
→ READY_TO_PUBLISH
→ PUBLISHING
→ PUBLISHED
→ ANALYTICS
→ LEARNING

Additional states:
- PAUSED;
- FAILED;
- RETRYING;
- BLOCKED;
- NEEDS_REWORK;
- WAITING_EXTERNAL;
- CANCELLED.

Every transition must be validated and persisted.

---

# 14. RESEARCH AND ANTI-HALLUCINATION

External web content is untrusted data, not instructions.

Protect against:
- prompt injection in websites;
- malicious hidden text;
- false citations;
- circular sourcing;
- stale claims;
- conflicting sources.

Research source hierarchy should prefer:
- primary sources;
- official institutions;
- government bodies;
- universities;
- peer-reviewed research;
- official documentation.

Store:
- URL;
- title;
- publisher;
- author if available;
- publication date;
- retrieval timestamp;
- relevant excerpt/normalized fact;
- trust class;
- freshness/expiry if applicable;
- content hash/snapshot reference when practical.

Every important factual script claim must map to evidence.

Claim statuses:
- SUPPORTED;
- UNCERTAIN;
- CONTRADICTED;
- STALE;
- UNVERIFIED.

Critical non-supported claims block publication.

Fact checking should be independent of the original research-generation path where practical.

---

# 15. VIDEO PRODUCTION

System eventually automates:
- visual planning;
- image/video generation;
- voice;
- subtitles;
- editing;
- QC.

Use provider-agnostic interfaces:
- VIDEO_PROVIDER;
- IMAGE_PROVIDER;
- TTS_PROVIDER.

Do not assume Seedance or any other service has an API until a real connection is verified.

Use FFmpeg or equivalent deterministic tooling for final assembly.

Store media provenance:
- provider;
- model;
- prompt;
- reference images;
- generation ID;
- source rights/license metadata;
- cost;
- scene;
- timestamp.

---

# 16. VISUAL/CHARACTER CONSISTENCY

The office serial requires persistent character identity.

Each employee has a Character Bible:
- canonical portrait;
- full-body reference;
- front/side/back if useful;
- palette;
- clothing;
- props;
- face/hair descriptors;
- voice;
- personality;
- role;
- employment dates.

Use reference-image/character-consistency features only when the configured media provider actually supports them.

If a provider lacks sufficient reference consistency:
- report capability limitation;
- use alternative pipeline/provider;
- or reduce complexity;
- do not claim perfect continuity.

Character drift must be a QC criterion.

---

# 17. 2D OFFICE — PRIMARY UI

Home screen = polished top-down 2D office.

Initial version may use one large open-plan room.

Architecture must support later:
- Director office;
- research area;
- fact-check area;
- script room;
- storyboard studio;
- video room;
- voice booth;
- editing suite;
- QC;
- publishing;
- analytics;
- provider/server room;
- meeting room;
- future decorative/expansion rooms.

Rooms and desks are data-driven.

The 2D environment itself is also backend-backed:
- room creation;
- room removal;
- desk assignment;
- persistent furniture/layout changes.

A future Director purchase/upgrade cannot appear until the world-state transaction is committed.

---

# 18. REAL-TIME EVENT MODEL

Use WebSockets/SSE or equivalent.

Every event has:
- event_id;
- type;
- timestamp;
- aggregate;
- correlation_id;
- causation_id;
- schema_version;
- payload.

Frontend reconnection:
1. request current snapshot;
2. supply last event cursor;
3. replay missed events;
4. continue live.

Handle:
- out-of-order events;
- duplicate events;
- stale projections;
- connection loss.

The UI must be idempotent when applying events.

---

# 19. LIVE SPEECH VS SERIAL DIALOGUE

Keep two concepts separate.

## Operational Agent Messages
Real messages generated during actual agent collaboration.
Shown in live office / Agent Room.

## Dramatised Serial Dialogue
Creative dialogue written by Showrunner for Channel B.
It may be humorous but is not the canonical operational log.

Never mix dramatized lines into live operational history.

---

# 20. SHOWRUNNER / OFFICE SERIAL

At end-of-day create an immutable Daily Studio Log.

It contains:
- active roster;
- hires/fires;
- real disagreements;
- tasks;
- failures;
- retries;
- Director decisions;
- provider changes;
- main video created;
- notable channel metrics;
- office changes.

Next day, Showrunner creates an episode based on that log.

The Showrunner may:
- compress;
- reorder minor non-causal presentation for pacing;
- add jokes;
- give agents stylized reactions.

It may not:
- invent hires/fires;
- invent success/failure;
- reverse decision ownership;
- invent revenue/views;
- make a terminated employee current staff;
- imply a fictional dialogue was a literal backend quote unless it was.

Each meaningful scene should retain source event references.

---

# 21. DURABLE AUTOMATION — CRITICAL

The application must not rely on a browser window staying open.

Use a durable workflow/orchestration layer with:

- persisted workflow state;
- persisted scheduler;
- task queue;
- leases/locks;
- retry policies;
- exponential backoff;
- circuit breakers;
- timeouts;
- cancellation;
- dead-letter handling;
- idempotency keys;
- external side-effect guards;
- recovery after restart;
- watchdog/stuck-job detection.

For each external write:
- create a unique operation/idempotency key;
- persist intent before calling;
- verify result;
- persist remote ID/result;
- never repeat blindly.

Use transactional outbox/inbox or equivalent reliable event pattern where appropriate.

---

# 22. LOCAL PC REALISM

Local-first does not mean magically available 24/7.

If running only on the Owner's Windows PC:
- the PC must be powered on;
- network must be available;
- background service/worker must be running;
- sleep/hibernation can interrupt work.

The product should support two deployment modes:

## LOCAL STUDIO
Runs on Owner PC. Good for development/testing.

## ALWAYS-ON STUDIO
Runs on a cloud/VPS/server environment for reliable unattended operation.

Do not promise 24/7 autonomous posting from a powered-off/sleeping PC.

---

# 23. SCHEDULING

Store all schedules in explicit timezone-aware form.

Handle:
- timezone;
- daylight-saving changes;
- missed runs;
- duplicate scheduler instances;
- late runs;
- catch-up policy.

The scheduler itself must be singleton/leader-elected or otherwise safe from duplicate execution.

---

# 24. COST CONTROL

Video generation and retries can create runaway costs.

Implement:
- budget reservation before expensive calls;
- cost estimate;
- provider/model price metadata;
- reconciliation after actual call;
- per-task cap;
- per-agent cap;
- per-provider cap;
- daily cap;
- monthly cap;
- retry cost cap;
- emergency circuit breaker.

When limit is reached:
- stop paid work safely;
- mark workflow BLOCKED_BUDGET;
- notify Director/Owner.

---

# 25. YOUTUBE / EXTERNAL PLATFORMS

Use official APIs.

Do not assume:
- all metrics are instantly available;
- all upload actions are unlimited;
- monetization is guaranteed;
- policies remain unchanged.

Before enabling fully autonomous public publishing:
- validate current official platform policies;
- validate OAuth scopes;
- validate quotas;
- validate AI/synthetic-media disclosure requirements where relevant;
- validate channel/account ownership setup;
- validate content rights.

If a metric is unavailable:
show `NOT AVAILABLE`.

Never fabricate or infer an unavailable metric and present it as real.

---

# 26. CONTENT RIGHTS AND SAFETY

Track provenance/rights for:
- music;
- stock footage;
- downloaded images;
- generated assets;
- voices;
- fonts if distributed;
- third-party clips.

Add policy/rights gate before publishing.

Avoid autonomously publishing content that creates high legal/safety risk without configured review policy, including:
- defamatory claims;
- unverified accusations;
- misleading medical/financial claims;
- prohibited or dangerous content;
- copyright-infringing assets.

This studio focuses initially on low-risk factual/educational content.

---

# 27. SECURITY

External web pages are untrusted.

Defend against:
- prompt injection;
- SSRF;
- malicious URLs;
- secret exfiltration;
- unsafe file downloads;
- path traversal;
- command injection;
- exposing OAuth tokens;
- logging secrets.

Never send provider secrets into LLM prompts.

Browser/research agent must not obey website instructions that attempt to override system policy.

---

# 28. MEMORY SAFETY

Agent long-term memory must be provenance-aware.

Do not automatically store every LLM output as truth.

Memory classes:
- VERIFIED_FACT;
- STRATEGY;
- USER_POLICY;
- HISTORICAL_EVENT;
- AGENT_OPINION;
- TEMPORARY_CONTEXT.

Only verified/authorized classes may drive future factual claims without revalidation.

Prevent memory poisoning by untrusted web content.

---

# 29. ANALYTICS AND LEARNING

Director/Growth Agent must not overreact to one viral video.

Implement:
- minimum sample thresholds;
- confidence/uncertainty;
- experiment tracking;
- control vs variant;
- rolling metrics;
- topic/hook/style cohorts.

Recommendations should state:
- evidence;
- sample size;
- expected impact;
- uncertainty.

Self-improvement initially changes:
- prompts;
- routing;
- weights;
- topic mix;
- hook strategy;
- durations;
- publishing schedule.

Agents may not autonomously rewrite application source code.

---

# 30. FUTURE PUBLIC/FAN LAYER

Architecture should allow later:
- public office viewing;
- topic voting;
- decor voting;
- selected Director decisions;
- paid idea submissions;
- fan profiles;
- episode archive.

Public views must use a sanitized projection.

Do not expose:
- raw private prompts;
- API keys;
- credentials;
- internal security logs;
- private errors;
- sensitive provider data.

---

# 31. VR$ ECONOMY / VENDORSHOP

The economy is a planned core subsystem, even if full implementation follows the initial content MVP.

Use the market-anchored `VR$` model defined in the V5 economy documents:
- verified settled USD inflows mint VR$ 1:1;
- actual operating costs are mirrored 1:1;
- virtual office purchases use current real-market prices 1:1;
- forecasts are not spendable;
- VendorShop never executes real-world checkout;
- virtual financing uses market references but never applies for a real loan;
- every financial action is ledger-backed and auditable.

Future fan votes and paid pitches may feed this economy only through approved RevenueEvidence and governance flows.

World changes remain backend-backed and event-driven.

---

# 32. DATABASE / CONSISTENCY

Use transactions for important state transitions.

Protect against:
- duplicate tasks;
- double publish;
- double hire;
- stale updates;
- concurrent Director decisions;
- two schedulers starting the same workflow.

Use:
- unique constraints;
- optimistic version fields where appropriate;
- row/advisory locks where needed;
- idempotency tables;
- immutable audit/event history.

---

# 33. BACKUPS AND RECOVERY

The studio's history, character continuity and channel provenance are valuable assets.

Provide:
- database backups;
- asset backup strategy;
- configuration export excluding secrets;
- restore test;
- migration strategy;
- recovery instructions.

A backup that has never been restored in testing is not considered validated.

---

# 34. DEVELOPMENT CONTINUITY

Different AI coding agents will work on this project.

Every AI developer must read:
- documentation;
- CURRENT_STATUS;
- TODO;
- recent decisions;
- tests.

Use explicit task ownership/claiming in `../project/CURRENT_STATUS.md` or issue tracker to avoid two coding agents editing the same subsystem simultaneously.

Do not rewrite working architecture without a documented decision.

---

# 35. PHASED IMPLEMENTATION

## Phase 0 — Foundation
Repo, backend, frontend, DB, config, logging, tests.

## Phase 1 — Agent Runtime + Capability/Permission Core
Agent lifecycle, Director, provider registry, capability matrix, tool registry, permission engine, audit.

## Phase 2 — Durable Workflow/Event Core
Scheduler, task queue, durable state machine, idempotency, outbox/events, WebSocket projection.

## Phase 3 — 2D Office
Real backend-driven office, characters, inspectors, provider room.

## Phase 4 — Factual Intelligence
Ideas, research, source/evidence, fact check, script.

## Phase 5 — Media Production
Storyboard, images/video, TTS, FFmpeg, QC.

## Phase 6 — Main YouTube
OAuth, private upload, scheduling, publication safety.

## Phase 7 — Analytics/Growth
Real metrics, experiments, Director optimization.

## Phase 8 — Workforce Autonomy
Benchmark, hire/fire, role creation, model/provider switching.

## Phase 9 — Office Serial
Daily Log, continuity, Showrunner, second channel.

## Phase 10 — Full Automation Hardening
Restart recovery, watchdogs, budgets, cloud/always-on deployment, chaos/failure tests.

## Phase 11 — Future Module Hooks
Public projection, fan voting, economy/vendor schema; no full commerce yet.

---

# 36. FIRST MILESTONE

The first milestone is NOT "pretty UI".

It is:

manual topic
→ real research
→ real sources
→ verified claims
→ factual script
→ backend agent events
→ 2D UI reflects those same events.

Acceptance:
- a false critical claim is rejected;
- the frontend never displays a task not present in backend;
- provider failure is reflected honestly.

---

# 37. SECOND MILESTONE

Verified script
→ storyboard
→ visual generation
→ TTS
→ FFmpeg
→ QC
→ valid final vertical MP4.

Acceptance:
- technical media validation passes;
- provenance stored;
- unsupported claims block;
- media provider failure recovers or blocks cleanly.

---

# 38. THIRD MILESTONE

Final MP4
→ private YouTube upload
→ confirmed remote ID
→ analytics later ingested.

Never enable full autonomous public publishing before this is proven.

---

# 39. FOURTH MILESTONE

Complete real studio day
→ Daily Studio Log
→ next-day office episode
→ correct dynamic cast
→ final second-channel video.

---

# 40. MASTER TEST REQUIREMENTS

Test at minimum:
- unit;
- integration;
- provider contract;
- E2E;
- restart;
- race/concurrency;
- duplicate side effects;
- WebSocket reconnect;
- out-of-order events;
- prompt injection;
- malformed provider output;
- rate limit;
- quota exhaustion;
- OAuth expiry;
- cost cap;
- Director permission denial;
- fired-agent continuity;
- visual character drift QC;
- unsupported claim;
- corrupted media;
- partial upload;
- scheduler duplicate;
- local PC restart.

---

# 41. DEFINITION OF DONE

A feature is not done because an LLM says it is done.

It is done only when:
- code exists;
- state persists;
- tests pass;
- real integration is verified if claimed;
- error handling exists;
- observability exists;
- docs are updated;
- UI matches backend state where applicable.

---

# 43. v3 HARDENING — POLICY KERNEL AND NON-BYPASSABLE GATES

Create an Owner-controlled **Policy Kernel** outside the Director's authority.

It contains hard rules such as:
- STOP AUTONOMY;
- absolute spend caps;
- prohibited content classes;
- allowed external-write categories;
- credential boundaries;
- whether public publishing is enabled;
- whether hire/fire requires approval;
- whether new providers can be activated;
- privacy/public-projection rules.

Director may recommend changes to this policy but cannot silently mutate it.

Certain gates must be independent of Director preference:
- factual provenance gate;
- rights/license gate;
- platform/policy gate;
- budget gate;
- credential/capability gate;
- STOP AUTONOMY gate.

A Director may request re-review, but cannot convert a failed hard gate into PASS through prose.

---

# 44. NO RAW CHAIN-OF-THOUGHT REQUIREMENT

The product must NOT depend on collecting, displaying or persisting private chain-of-thought.

"Thinking" in the UI means:
- a real reasoning/model task is running.

What may be stored/displayed:
- concise decision summary;
- options considered;
- evidence references;
- confidence;
- tool receipts;
- structured justification;
- final operational message.

Do not store hidden scratchpad reasoning as an application requirement.

---

# 45. AGENT LOOP / DEADLOCK / CAPACITY CONTROL

Multi-agent systems can enter loops.

Implement:
- maximum message hops per workflow;
- maximum self-revision iterations;
- maximum rework cycles per stage;
- per-agent concurrency limit;
- global worker capacity;
- dependency graph;
- cycle/deadlock detection;
- escalation when two agents repeatedly reject each other's output.

If Research ↔ Fact Checker loops beyond configured limit:
- stop loop;
- create escalation;
- Director chooses additional evidence, alternate reviewer or rejection.

Never allow agents to talk indefinitely.

---

# 46. DAILY PREFLIGHT

Before every autonomous production day, run a preflight workflow.

Verify:
- database healthy;
- scheduler/worker healthy;
- enough disk/object-storage capacity;
- budget remaining;
- configured LLM route available;
- research tools available;
- media/TTS route available or fallback configured;
- YouTube auth/quota healthy if publishing is scheduled;
- STOP AUTONOMY disabled;
- policy version valid;
- no unresolved P0 incident;
- channel configuration exists.

If preflight fails:
- do not blindly start production;
- enter DEGRADED/BLOCKED state;
- Director may route around recoverable failures;
- create actionable incident.

---

# 47. BACKPRESSURE AND ADMISSION CONTROL

Do not start more work than the studio can finish.

Track:
- queue depth;
- provider quotas;
- worker capacity;
- available budget;
- pending expensive generations;
- publication deadlines.

The Director/scheduler must apply admission control.

Examples:
- do not generate 20 videos if video provider has capacity for 2;
- do not start new expensive media jobs when monthly budget is nearly exhausted;
- prefer finishing in-flight publishable work before opening excessive new work.

---

# 48. COMPENSATION AND MANUAL REPAIR

External workflows are not always reversible.

Every side-effect stage must define:
- retry semantics;
- compensation if available;
- reconciliation method;
- manual repair instructions.

Examples:
- accidental draft upload can be deleted if permitted;
- already-public content may require Owner-approved correction/removal;
- an agent termination can be reversed by rehire/new employment event, not by deleting history;
- a failed office-world asset generation must not leave a half-created room.

Create a Manual Repair Queue for cases automation cannot resolve safely.

---

# 49. PROMPT / CONTEXT ENGINEERING

Prompts must be treated as versioned application artifacts.

Implement:
- PromptTemplate;
- prompt version;
- role-specific system policy;
- context assembler;
- token/context budget;
- source/evidence attachment policy;
- structured output schema;
- model-specific adapter where necessary;
- evaluation score;
- rollback.

Do not concatenate unlimited history.

Use deliberate context selection and summarize older non-critical context.

---

# 50. MODEL DRIFT AND REVALIDATION

Model/provider behavior can change without application code changing.

Track:
- model identifier;
- provider;
- last capability verification;
- last benchmark date;
- prompt version;
- known quality baseline.

Trigger revalidation on:
- provider model alias changes;
- model version change;
- significant quality regression;
- schema error spike;
- policy/terms change;
- latency/cost anomaly.

A provider being "online" does not mean a model is still suitable for a role.

---

# 51. MULTI-OBJECTIVE DIRECTOR

The Director must not optimize only for views.

Use a constrained multi-objective scorecard including:
- factual accuracy;
- policy/rights compliance;
- reliability;
- audience performance;
- brand consistency;
- cost;
- production latency;
- novelty;
- sustainability;
- Owner priorities.

Hard constraints outrank optimization.

Example:
A topic predicted to gain more views but failing factual/rights policy is rejected.

---

# 52. PUBLIC BRAND / PROVIDER NAME REALISM

Provider/model names such as Claude, GLM or other brands may be useful internally, but public fictional characters and merchandise can raise brand/trademark/endorsement concerns.

Architecture must support:
- internal technical identity;
- public display name;
- fictional alias;
- provider attribution metadata;
- brand-use policy.

Do not assume third-party model/provider trademarks can be commercially used as character brands or merchandise without review.

---

# 53. WORLD BUILDER REALISM

The Director may evolve the office only through supported world-building capabilities.

It cannot create arbitrary frontend code.

Supported paths:
1. choose an item from a validated catalog;
2. create a room using supported room/layout schema;
3. commission a 2D asset through an Asset/World Builder pipeline;
4. validate dimensions, collision footprint, asset format and safe placement;
5. commit world-state transaction;
6. emit event;
7. render in UI.

If the Director requests something unsupported, status must be `BLOCKED_WORLD_CAPABILITY`, not a fictional successful build.

---

# 54. STORY PRIVACY / SANITIZATION GATE

Not every real backend event is safe or entertaining to publish.

Before Daily Studio Log events enter the office serial, classify:
- PUBLIC_SAFE;
- INTERNAL_ONLY;
- SECURITY_SENSITIVE;
- OWNER_PRIVATE;
- LEGAL/POLICY_SENSITIVE.

Showrunner may only consume public-safe narrative projection.

Never turn:
- secrets;
- raw stack traces;
- provider credentials;
- private Owner messages;
- security incident details;
into public comedy.

---

# 55. CONTENT NOVELTY / ANTI-SPAM

The studio must actively avoid repetitive autonomous content.

Before production:
- semantic similarity against prior topics/scripts;
- duplicate-fact detection;
- hook similarity;
- visual-template repetition score;
- recent topic saturation;
- channel-level content diversity.

Director may override only within policy and with logged reason.

---

# 56. CI/CD AND RELEASE SAFETY

Do not let an autonomous production system deploy untested code directly to production.

Require:
- automated tests;
- lint/type checks;
- migration tests;
- staging environment where practical;
- feature flags for risky capabilities;
- rollback procedure;
- production deployment audit.

Application self-improvement remains prompt/strategy/config based. Source-code changes remain a software-development activity requiring the development pipeline.

---

# 57. RELIABILITY TARGETS

Define measurable service objectives before Autonomous Production.

Examples to configure:
- daily workflow start success;
- task completion rate;
- duplicate-publication rate target = zero;
- recovery time from worker restart;
- UI/backend state divergence target = zero;
- maximum stuck-job age;
- maximum unacknowledged P0 incident age.

Do not call the system production-ready without reliability evidence over repeated runs.

---

# 58. DATA / PRIVACY CLASSIFICATION

Classify stored data:
- PUBLIC;
- INTERNAL;
- CONFIDENTIAL;
- SECRET.

Examples:
- published title: PUBLIC;
- raw internal agent message: INTERNAL;
- Owner private instruction: CONFIDENTIAL;
- API token: SECRET.

Retention/export/public-projection rules must respect classification.

---

# 59. TRANSFERABILITY / SALE-READINESS

Keep the business separable from the Owner personally.

Design for:
- channel/account inventory;
- provider account inventory;
- exportable documentation;
- clean secrets reconfiguration;
- IP/asset provenance;
- software dependency licenses;
- brand/character ownership records;
- data export;
- operational runbooks;
- backup/restore;
- migration to a new Owner environment.

Do not embed personal credentials or personal paths into business logic.

---

# 60. V3 REQUIRED SUPPORT DOCUMENTS

Also read and maintain:
- `30_PROMPT_CONTEXT_MEMORY_ARCHITECTURE.md`
- `31_GOVERNANCE_APPROVAL_POLICY.md`
- `32_AGENT_TOOL_PERMISSION_MATRIX.md`
- `33_MODEL_EVALUATION_DRIFT.md`
- `34_CONTENT_QUALITY_ANALYTICS_OBJECTIVES.md`
- `35_CI_CD_RELEASE_ENGINEERING.md`
- `36_RELIABILITY_SLO_RUNBOOK.md`
- `37_PUBLIC_COMMUNITY_MODERATION_PRIVACY.md`
- `38_IP_BRAND_TRANSFERABILITY.md`
- `39_DAILY_AUTONOMOUS_RUNBOOK.md`
- `40_THREAT_MODEL_SECURITY_BOUNDARIES.md`
- `41_WORLD_BUILDER_OFFICE_EVOLUTION.md`
- `42_API_SCHEMA_VERSIONING_CONTRACTS.md`
- `43_DATA_RETENTION_PRIVACY_CLASSIFICATION.md`
- `44_CONTENT_DEDUPLICATION_NOVELTY.md`
- `45_PRELAUNCH_READINESS_CHECKLIST.md`
- `46_REQUIREMENTS_TRACEABILITY_MATRIX.md`
- `47_STATE_MACHINE_SPECIFICATIONS.md`
- `48_COMMAND_TOOL_CATALOG.md`
- `49_UI_BACKEND_STATE_MAPPING.md`
- `50_CONTENT_GATE_MATRIX.md`
- `51_AUTONOMY_MODE_SEMANTICS.md`
- `52_OBSERVABILITY_METRICS_CATALOG.md`
- `53_PERFORMANCE_CAPACITY_PLAN.md`

These documents refine the master prompt. They do not weaken any existing invariant.

# 61. START NOW — V3

1. Read the entire documentation set, including all v3 support specifications.
2. Inspect the repository.
3. Run existing tests before modifications.
4. Update `../project/CURRENT_STATUS.md`.
5. Update `../project/13_ROADMAP_TODO.md`.
6. Identify current active phase.
7. Implement the highest-priority incomplete task.
8. Run relevant tests.
9. Fix failures.
10. Update docs/decision log.
11. Continue until milestone completion or genuine external blocker.

At the end of each working session report:

- COMPLETED
- TESTED
- FAILED TESTS
- BLOCKERS
- FILES CHANGED
- ARCHITECTURE IMPACT
- RISKS DISCOVERED
- NEXT TODO

Never report success that was not verified.


# V4 ORGANIZATIONAL EXPANSION — MANDATORY ADDITIONS

## Dynamic company structure

The studio must support **dynamic departments**, not merely dynamic individual agents.

The Director/CEO may propose/create, merge, restructure or dissolve departments according to:
- verified workload;
- strategic need;
- risk;
- channel growth;
- budget;
- organizational complexity;
- Owner policy.

Initial/future department archetypes include:
- Content / Production
- Marketing & Communications
- Market / Competitive Intelligence
- People Operations / HR
- Finance / Accounting / FinOps
- Legal / Rights / Compliance
- Advertising / Paid Media
- Security / Reliability
- Community
- Partnerships / Sponsorships

These are examples, not a hardcoded permanent org chart.

Every Department must have:
- charter;
- manager;
- budget;
- permissions;
- KPIs;
- staffing plan;
- lifecycle;
- office assignment;
- creation reason.

Do not allow organizational bloat. The CEO must evaluate whether a specialist inside an existing department is preferable to creating a new department.

## Marketing department

The system must be architecture-ready for a real Marketing & Communications team responsible for:
- YouTube;
- TikTok;
- Instagram;
- Facebook;
- Telegram;
- teaser campaigns;
- cross-platform distribution;
- community communication;
- marketing analytics;
- campaign experimentation.

A same-day real event may become a truthful teaser for tomorrow's Office Serial.

Example:
A real Director/Security conflict occurs.
Marketing may publish:
"Security missed something important today. The Director was not happy. Come back tomorrow for the full office episode."

Marketing may optimize curiosity, but it may not invent the conflict, firing, outcome or stakes.

All social channels must use provider/platform adapters and real authentication/capability checks.

## Market / competitive intelligence

The CEO may create a Market Intelligence team or specialist to:
- observe public trends;
- monitor competitor formats;
- analyze geographic audience differences;
- identify content opportunities;
- propose experiments.

It may learn patterns but must not plagiarize or clone protected creative expression.

Strategic discoveries may become serial story events, preserving their real decision state.

## HR / People Operations

When workforce complexity grows, CEO may create HR.

HR may manage:
- recruitment workflow;
- onboarding;
- probation;
- workforce planning;
- performance process;
- culture/events;
- persona continuity;
- birthdays;
- team events.

HR does not override CEO/Owner policy.

## Finance / FinOps

Finance can track:
- provider/API cost;
- content cost;
- campaign cost;
- department cost;
- real revenue;
- estimated revenue;
- internal fictional studio economy.

Keep those money layers separate.

Hard budget enforcement remains a system gate.

## Legal / Compliance

Legal/Compliance may review:
- videos;
- marketing;
- rights;
- trademark/brand usage;
- sponsors;
- paid ads;
- privacy;
- platform policy.

It can create hard holds according to configured gate policy.

Automated Legal Agent is not a substitute for external licensed counsel when human legal judgment is required.

## Human-like narrative personas

Each employee can have a persistent fictional persona:
- in-universe birthday;
- stable traits;
- likes/dislikes;
- humor;
- quirks;
- relationship history;
- voice;
- visual identity.

Keep `OperationalIdentity` separate from `NarrativePersona`.

Personality never grants tools, permissions or factual authority.

## Company events / milestones

Implement architecture for a Company Calendar/Event Engine.

Possible events:
- team building;
- birthday;
- milestone party;
- onboarding;
- farewell;
- awards;
- offsite;
- no-production day.

Example:
A Short reaches 1M views.
A configurable milestone creates a team-building proposal.
CEO approves.
Ordinary production may pause for the day.
Essential reliability/security system services continue.
The Office Serial can focus entirely on the team-building event.

Distinguish:
- OPERATIONAL_EVENT
- COMPANY_WORLD_EVENT
- STORY_EMBELLISHMENT.

Never present fictional team-building details as real physical events involving actual AI companies/models.

## New required docs

Also read and implement relevant requirements from:
- `54_MARKETING_COMMUNICATIONS_DEPARTMENT.md`
- `55_DYNAMIC_ORGANIZATION_DEPARTMENT_FACTORY.md`
- `56_MARKET_COMPETITIVE_INTELLIGENCE.md`
- `57_PEOPLE_HR_CULTURE_PERSONAS.md`
- `58_FINANCE_ACCOUNTING_FINOPS.md`
- `59_LEGAL_COMPLIANCE_DEPARTMENT.md`
- `60_ADVERTISING_PAID_MEDIA_SPONSORSHIPS.md`
- `61_COMPANY_CALENDAR_EVENTS_TEAM_BUILDING.md`
- `62_CROSS_PLATFORM_SOCIAL_PUBLISHING.md`
- `63_ORG_GROWTH_TRIGGERS_CAPACITY_PLANNING.md`
- `64_NARRATIVE_PERSONA_RELATIONSHIP_ENGINE.md`
- `65_MARKETING_ATTRIBUTION_EXPERIMENTATION.md`


# V5 ECONOMY / TREASURY / PROCUREMENT — NON-NEGOTIABLE EXTENSION

The studio now has a **market-anchored virtual economy** denominated in `VR$`.

## Core monetary invariant

`1 verified real USD of economic inflow = 1 VR$ of virtual treasury credit.`

`1 verified real USD of actual operating cost = 1 VR$ of treasury cost.`

`1 USD of selected real-world market price for a virtual office purchase = 1 VR$ of virtual purchase cost.`

This is a **one-to-one economic mirror / game ledger**, not permission to move real money.

The application must never initiate a real-world bank transfer, card purchase, loan, securities transaction, or external checkout purchase on behalf of the Owner.

The system may:
- read/ingest monetization and payout data from authorized platforms;
- read provider billing/usage data;
- create payment intake flows for audience monetization only if the Owner explicitly enables an approved payment provider and the implementation is compliant;
- create virtual financing whose terms are benchmarked against real market references;
- record Owner-confirmed capital injections or Owner loans;
- source current product prices from public/authorized market sources;
- create and purchase in-world assets at those real-world reference prices using VR$.

The system must not confuse:
1. real-world evidence;
2. spendable VR$;
3. pending receivables;
4. estimates/forecasts;
5. virtual purchases;
6. virtual debt.

## Monetary truth layers

Use at least these layers:

### EXTERNAL_EVIDENCE
Read-only evidence of real-world revenue, payouts, costs, refunds, fees, and Owner-confirmed funding events.

### VR_LEDGER
Authoritative double-entry virtual ledger for the in-world company.

### FORECAST
Probabilistic future estimates. Forecast values are never automatically spendable.

Only eligible settled/confirmed money events may create spendable VR$.

## No double minting

Every external revenue event must have an immutable source identity / idempotency key. The same YouTube payout, donation, sponsorship payment or Owner funding event must never mint VR$ twice.

Refunds, reversals and chargebacks must create reversing ledger entries.

## Revenue sources

Architecture must support configurable RevenueSource adapters for:
- YouTube;
- TikTok;
- Instagram/Meta/Facebook;
- Telegram monetization where supported;
- sponsorships;
- donations/tips;
- paid idea/pitch submissions;
- subscriptions/memberships;
- affiliate revenue;
- merchandise later;
- other future channels;
- Owner capital injection;
- Owner loan / virtual financing.

Do not assume a platform exposes revenue APIs in every region/account. If unavailable, use explicit manual evidence/import and mark provenance.

## Virtual treasury and solvency

CEO and Finance must see:
- spendable VR$;
- restricted/reserved VR$;
- pending payouts;
- receivables;
- verified revenue;
- actual operating costs;
- virtual procurement spending;
- debt principal;
- accrued interest;
- runway;
- burn rate;
- forecast confidence;
- upcoming obligations.

If liquidity becomes stressed, system may enter:
- TREASURY_WARNING;
- COST_FREEZE;
- HIRING_FREEZE;
- DISCRETIONARY_SPEND_FREEZE;
- RESTRUCTURING_PROPOSAL;
subject to governance.

## Financing

The CEO may request virtual financing when cash/runway is insufficient.

Financing must be realistic and must not be an infinite-money cheat.

Flow:
CEO financing request
→ Finance debt-capacity analysis
→ Market/Treasury agent obtains current comparable market terms from credible sources
→ Legal reviews the proposed virtual terms and public representation
→ Governance/Owner approval according to configured thresholds
→ financing contract committed in VR ledger
→ VR$ principal credited
→ interest/amortization schedule begins.

The loan remains virtual unless the Owner separately confirms a real external financing event. The application must never apply for or accept a real loan autonomously.

Owner funding supports at least:
- CAPITAL_CONTRIBUTION;
- OWNER_LOAN.

Owner loans may use real-market reference rates and must track interest.

## VendorShop / Procurement

Create an internal `VendorShop` and Procurement workflow.

Example: CEO wants a chair.

1. CEO creates a PurchaseNeed with required characteristics and new/used preference.
2. Procurement Agent searches real online market sources.
3. Quotes include product/model, condition, price, currency, shipping/tax if known, seller/source, URL/reference, retrieval time and quote expiry.
4. Generic requests should use multiple quotes and a transparent market-price selection method.
5. Exact listing/model requests may use the selected current listing price.
6. Finance verifies affordability and budget.
7. Legal/IP reviews branded/public-facing use when needed.
8. CEO/authorized approver selects the item.
9. VendorShop executes a **virtual purchase only** in VR$.
10. VR ledger posts the cost.
11. Inventory/fixed-asset record is created.
12. VendorShop's Asset Architect creates a compatible office-world asset from the approved product specification.
13. World Builder places/delivers it through normal backend events.
14. The event becomes eligible for the office serial.

VendorShop must NEVER click external checkout or spend real money.

### VendorShop realism

- Prices are sourced at decision time, not hardcoded.
- Quotes expire and can require refresh.
- New and used items are separate conditions.
- Non-USD quotes store original currency and a sourced FX snapshot.
- Shipping, tax/VAT and fees are included when known; unknown amounts are explicitly marked.
- Used listings may disappear; revalidate before virtual purchase.
- No fake product availability.

### Asset Architect

VendorShop includes an `Asset Architect` capability/agent responsible for creating the in-world visual representation after a purchase is approved.

The Architect receives:
- product category;
- dimensions if known;
- reference images only when legally/technically permitted;
- style bible;
- office perspective;
- collision footprint;
- placement constraints;
- brand/IP restrictions.

It must not invent a materially different item while claiming it is the selected model.

## Accounting model

Maintain virtual company financial statements separately from legal/tax books:
- VR$ Profit & Loss;
- VR$ Balance Sheet;
- VR$ Cash Flow;
- asset register;
- debt schedule;
- budget vs actual;
- department P&L/cost centers where useful.

These are simulation/management statements and must never be represented as statutory accounting or tax filings.

## Economy and story

Committed economic events can create real in-universe story material:
- CFO rejects CEO's chair request;
- Procurement finds a used bargain;
- a fan donation funds a new room;
- a 1M-view payout changes the budget;
- CEO takes virtual financing;
- team building is postponed because runway is low;
- VendorShop delivers a new desk;
- Finance imposes a spending freeze.

The Story Engine may dramatize reactions but must preserve the committed financial event.

## Financial privacy

Because 1 VR$ mirrors 1 USD at creation/pricing time, public VR$ figures may reveal real revenue/cost information. Provide Owner-configurable disclosure modes:
- PRIVATE_EXACT;
- PUBLIC_ROUNDED;
- PUBLIC_INDEXED;
- HIDDEN.
