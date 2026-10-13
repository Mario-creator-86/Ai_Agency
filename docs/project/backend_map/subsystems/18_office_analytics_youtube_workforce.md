# 18 — The office view backend (world, scene parameters, Unreal, weather, stream), analytics, YouTube connections and workforce

Mapped at commit 20abffd (first mapped at b00083c, refreshed 2026-10-12).

> Files (25, 8,413 lines):
> `backend/app/office/__init__.py` (0), `backend/app/office/kept_frame.py` (266), `backend/app/office/presentation.py` (122),
> `backend/app/office/router.py` (36), `backend/app/office/scene_params.py` (1288), `backend/app/office/services.py` (394),
> `backend/app/office/stream.py` (142), `backend/app/office/unreal.py` (1033), `backend/app/office/weather.py` (242),
> `backend/app/office/world.py` (377),
> `backend/app/analytics/__init__.py` (15), `backend/app/analytics/models.py` (246), `backend/app/analytics/performance.py` (706),
> `backend/app/analytics/router.py` (248), `backend/app/analytics/schemas.py` (119), `backend/app/analytics/services.py` (1033),
> `backend/app/analytics/trends.py` (303),
> `backend/app/youtube/__init__.py` (5), `backend/app/youtube/models.py` (97), `backend/app/youtube/router.py` (242),
> `backend/app/youtube/services.py` (817),
> `backend/app/workforce/__init__.py` (6), `backend/app/workforce/models.py` (81), `backend/app/workforce/router.py` (124),
> `backend/app/workforce/services.py` (471).
>
> Mapped 2026-10-12 from commit b00083c plus the working tree (HEAD was 3d49e9a when this was written; no commit after
> b00083c touches any file above, and none of them had uncommitted changes). 254 functions in the inventory, plus 17
> nested functions the inventory does not list: six route/socket handlers and eleven inner helpers, one of them the
> 38-line `propose_workforce_changes.add` (see "Oddities and gaps", item 19). Verified adversarially against the code
> on 2026-10-12; corrections are folded into the text below. No commit from b00083c to 20abffd touches
> any file above.

## In one paragraph

This group is the part of the backend that **looks outward and inward without making anything**. The **office** half
serves the Owner's live view of the studio: an authoritative desk layout with the agents that hold each desk
(`office/services.py`), a read-only "presentation" of each agent's real runtime state for the pixel renderer
(`presentation.py`), the real weather over Bucharest from an Open-Meteo-compatible host (`weather.py`), the real sun
computed with NOAA's equations (`world.py`), one large pure function that turns the real clock, sun and weather into
every light, colour and material value of the Unreal headquarters (`scene_params.py`), a bridge that pushes those values
and the seated employees to the running Unreal level over Remote Control (`unreal.py`), a WebSocket relay for the
Pixel Streaming signalling (`stream.py`) and a single kept WebP frame for the title page (`kept_frame.py`). The
**analytics** half reads what YouTube measured (through the adapter in `app.providers.youtube_analytics`), stores
snapshots, normalises them into rates against each channel's own rolling medians, classifies and diagnoses films,
detects anomalies, compares the studio's editorial predictions with the audience, reads Google's public "trending now"
feed, and keeps a versioned per-channel content strategy that deterministic rules can propose to move by at most
±0.20 and only the Owner's API call can apply. The **YouTube** half is the Owner's OAuth 2.0 connection flow (client
credentials in an encrypted vault blob, single-use 10-minute `state`, channel identity read from Google, verify,
disconnect, a reconnect card on `invalid_grant` or an upload refusal). The **workforce** half counts each agent's runs over 30 days and the
task queue, proposes suspensions and hires from fixed thresholds, and changes employment only on an explicit Owner
decision. **No function in these 25 files calls a language model** (inventory: 0 call sites, 0 functions with an
`llm_distance`); several of them, however, compute the numbers that later go *into* prompts of the Lead Researcher,
the Director and the weekly review, and two of them write memory rows that every agent's system prompt later
recalls (see "LLM involvement"). Nothing in scope spends or reserves money. **Measured split:** of the 254
inventoried functions plus 17 nested ones, none asks a model anything; every decision in the table below is
CODE_RULE, CONFIG, EXTERNAL or OWNER, and the LLM share of this group is zero.

## Why it exists

**The office view.**

- The architecture makes the office a projection of committed backend state: "2D office is a projection of committed
  backend state/events" (ADR-001, `docs/project/16_DECISION_LOG.md:720-721`) and "The frontend does not decide whether
  an employee is working. It renders a server projection." (`docs/architecture/05_UI_UX_2D_OFFICE.md:138-143`).
  `presentation.py`'s first line restates it: "Domain state remains the agent's actual state"
  (`backend/app/office/presentation.py:1`).
- The Owner's rule of 2026-09-18: the sky and light over the headquarters are the real ones outside — time, sun,
  temperature, rain, snow, wind (`backend/app/office/world.py:3-7`). Hence the NOAA solar position (no service, so
  "it cannot fail and cannot be stale", `world.py:9-13`), the weather never invented ("a variable the service does not
  return is None, never zero", `backend/app/office/weather.py:15-16`), and the rehearsal clock refused on the live
  database ("the scene he watches never shows an hour that is not now", `world.py:15-16`). The street in the page is
  "ambience of the real city, never an event" (decision 2026-09-24, `16_DECISION_LOG.md:3964`).
- `scene_params.py` carries its own incident history: the rejected rebuild of 2026-09-19 had one sun doing both the
  twilight key and the direct light, so at the real −2.5° the warm key was gone and the reference moment scored 10.3
  against a limit of 6.4 (`backend/app/office/scene_params.py:19-21`); the "power cut" of 2026-09-24 where the evening
  went dark before the dusk led to the golden-hour key (`scene_params.py:134-146`, CHANGELOG "The live headquarters
  follows a real clear day — 2026-09-24", `docs/project/CHANGELOG.md:867-873`); the art director's third read held
  the weather look off because no atlas cell is a grey deck (`scene_params.py:44-47`, `scene_params.py:370-376`,
  rules (c)-(e) in `16_DECISION_LOG.md:3978`); the towers' "blue cardboard" at noon led to the day state of 2026-09-26
  (`scene_params.py:296-343`, `16_DECISION_LOG.md:4012-4014`). Owner decisions D1/D2/D5/D6 are recorded "taken as
  proposed (2026-09-18)" at `scene_params.py:55-59`.
- `unreal.py` holds every seated employee on the loop frame that faces the viewer because the Owner wants every
  character facing the viewer; played on, the talking loop turned them towards the monitor (seen in the stream
  2026-09-15, `backend/app/office/unreal.py:9-13`, `unreal.py:135-138`). The eased light change was re-aimed on
  2026-09-24 because restarting the ease "held every continuously moving value … at its first value"
  (`16_DECISION_LOG.md:3960`; `unreal.py:753-760`).
- `stream.py` exists because the page's Content-Security-Policy allows only `connect-src 'self'`, so the backend
  relays Epic's signalling socket (`backend/app/office/stream.py:3-8`); the key moved from the URL to the first message
  on 2026-09-25 and a key in the query string is refused since 2026-10-01 (SEC-02: uvicorn logged handshake paths with
  their query, `stream.py:10-16`).
- `kept_frame.py` (W24/W25): a stranger's first visit opened on the page renderer's building; the Owner's signed-in
  page now sends its newest frame, and only a whole still WebP is accepted "so a leaked key cannot publish arbitrary
  bytes on the studio's origin" (`backend/app/office/kept_frame.py:1-16`, `16_DECISION_LOG.md:3998`,
  `CHANGELOG.md:802-804`).

**Analytics.**

- Normative: "Director/Growth Agent must not overreact to one viral video" — minimum sample thresholds, confidence,
  experiments, rolling metrics, cohorts (`docs/architecture/00_MASTER_PROMPT.md:895-925`); observation windows 1h/24h/
  7d/28d and "Use bounded weight changes and cooldown" (`docs/architecture/34_CONTENT_QUALITY_ANALYTICS_OBJECTIVES.md:24-71`).
  The database itself refuses a recommendation with fewer than 3 samples or a change beyond ±0.20
  (`backend/app/analytics/models.py:129-135`).
- No estimated audience, ever: "a fabricated view count would corrupt the learning loop … and, through the Director's
  recommendations, the editorial strategy itself" (`backend/app/analytics/router.py:1-7`).
- `performance.py`: "The studio measured its videos and could not read them" — a 30-day-old and a 4-hour-old film were
  the same row, channels with medians of 8 000 and 150 000 the same scale (`backend/app/analytics/performance.py:1-25`);
  shipped with "The Director runs a company, not a video — 2026-09-12" (`CHANGELOG.md:3032-3060`). `film_cost` was
  rewritten 2026-10-11 because a film whose RunPod shots were booked on the board (the Higgs film, 4.58 USD) "read as
  having no cost at all" (`performance.py:125-138`).
- Per-channel accounts (2026-09-17): one adapter built from the first bound slot measured every publication, so "the
  serial's retention was asked of the main channel's account"; `analytics_provider_for_channel` builds from the slot's
  bound row only (`backend/app/analytics/services.py:230-241`, `16_DECISION_LOG.md:1876-1878`).
- Trends: the Owner asked the studio to adapt to what is in vogue and to its own numbers, with the machinery in place
  before the numbers (`backend/app/analytics/trends.py:3-11`); on 2026-10-11 the Owner moved the countries from Romania
  to the audience's (US, GB, CA, AU) after "a month of Romanian football and television trends had been read as hints"
  (`backend/app/config.py:130-142`).
- `story_performance`: the studio's predictions (hook, retention, CTA, the Director's 3-second estimate, her editorial
  total) had never been compared with a measurement, "so the editorial judgement could be wrong for a year without
  anyone noticing" (`backend/app/analytics/services.py:521-533`).

**YouTube connections.** A channel id typed by hand "is a claim", one returned by `channels.list(mine=true)` "is
evidence" (`backend/app/youtube/services.py:3-6`). The statistics scope was missing until 2026-09-18 (both connections
lacked it, `youtube/services.py:48-52`, `youtube/services.py:60-64`); `youtube.force-ssl` was added after YouTube
answered 403 to two "make public" calls on 2026-10-11 (`youtube/services.py:67-71`). SELL-07: Google's `invalid_grant`
and the seven-day expiry of tokens from an OAuth app left in "Testing" are explained to the Owner
(`youtube/services.py:113-120`). A refused account becomes a decision card through the single "one door" of
`app.decisions.sources` (ADR-DECISION-SOURCES, `16_DECISION_LOG.md:4144`).

**Workforce.** D-P8-001 "The studio may recommend changes to its own staff, and nothing more" (2026-09-10): evidence is
counted, never asked for; no model is consulted about a colleague; fewer than five runs is an anecdote; failure proposes
suspension, not termination; the Owner decides and a caller cannot pass for the Owner by omission; employment is a
record, not a column (`16_DECISION_LOG.md:1632-1680`). The record-per-period design implements
`docs/architecture/47_STATE_MACHINE_SPECIFICATIONS.md:16` ("TERMINATED cannot become ACTIVE by editing state").

## Who decides here

| Decision | Decided by | Where | Rule / check / threshold |
|---|---|---|---|
| Which agent sits at which desk in the layout | CODE_RULE + CONFIG | `backend/app/office/services.py:308-356` | Zones in fixed order, SERVER zone skipped; first unassigned visible agent whose role name is a substring of the desk's `name`, or whose role name contains the desk's `role_name` (an agent with no known role, role name "", matches every desk), else the first unassigned agent of any role (`services.py:313-329`); desks from `DEFAULT_OFFICE_LAYOUT` (`services.py:42-274`) |
| Which agents are drawn at all | CODE_RULE | `office/services.py:17`, `:286` | lifecycle in {HIRED, ACTIVE, PAUSED, SUSPENDED}; former staff keep their seat reservation but are not drawn |
| An employee's personal pixel seat | CODE_RULE + CONFIG (`config/pixel_office.json` stations) | `office/services.py:20-39` | Sorted by (hired_at, id); first hire of a seeded role gets its illustrated room, later hires annex slots; "researcher" aliased to "leadresearcher" (`:28`) |
| An agent's animation cycle and whether its monitor is on | CODE_RULE + CONFIG (`config/pixel_presentation.json` `cycles`) | `backend/app/office/presentation.py:27-45` | `runtime_state` aliased (EXECUTING/RUNNING→WORKING, PLANNING→THINKING, FAILED→ERROR); non-ACTIVE lifecycle → mode PAUSED, empty cycle, monitor off; phase seeded by SHA-256 of the agent id |
| Which films the office monitors may play | CODE_RULE + CONFIG (`media_max_bytes` 64 MiB) | `presentation.py:48-108` | YouTube: platform YOUTUBE, PUBLISHED, privacy public/unlisted, upload `processed`, 11-char id, newest 12; local: from the 12 newest RENDERED_VIDEO `video/mp4` rows, file inside the media roots, provider not FAKE/SIMULATED/DUMMY, size 1..64 MiB, at most 3 |
| Whether the page tries the live Unreal stream | CONFIG (`STUDIO_OFFICE_STREAM_SIGNALLING_URL`) | `backend/app/office/stream.py:54-69` | Only a ws/wss URL with a host |
| Whether a relay socket is let through | CODE_RULE | `stream.py:83-99` | Key in URL refused before handshake (SEC-02); first message must be the Owner key within `SOCKET_AUTH_TIMEOUT_S` 5 s (`backend/app/security.py:100-101`); no configured target or unreachable upstream → close 1013 |
| Whether a kept frame is stored | CODE_RULE (+ OWNER key) | `backend/app/office/kept_frame.py:242-264` | `require_owner`; content type `image/webp`; `X-Captured-At` a whole ms value not > 60 s ahead nor > 24 h old; body ≤ 768 KiB; `is_webp` structural check; stored only if newer than the kept one (`:177`) |
| What weather the scene shows | EXTERNAL (Open-Meteo-compatible host) + CONFIG (`STUDIO_OFFICE_WEATHER_HOST`) | `backend/app/office/weather.py:207-237` | No host → `not_configured`; unknown WMO code or missing `current` → `unreachable`; success cached 600 s, failure 120 s |
| Whether the last observation is still shown | CODE_RULE | `backend/app/office/world.py:217-234` | Kept up to `STALE_WEATHER_S` 3600 s, marked `stale`; then none |
| Where the sun stands | CODE_RULE (NOAA equations) + CONFIG (latitude, longitude, timezone) | `world.py:128-171` | Geometric elevation, no refraction; aware time required |
| Whether a rehearsal hour may replace "now" | CODE_RULE | `world.py:310-349`, `unreal.py:919-927` | Refused (`LiveOverrideRefused`) when the database is `data/studio.db` or not a SQLite file; caller keeps the real clock and logs `office_world_rehearsal_refused_live` |
| Every light, colour and material value of the Unreal level | CODE_RULE (pure function of real inputs) + CONFIG (`office_facade_heading_deg`, D1) | `backend/app/office/scene_params.py:1136-1288` | Measured anchor curves and constants (see "Hard rules"); exactly the build's values at the reference −2.5° |
| Whether weather (cloud deck, rain) changes the look | CODE_RULE (feature constant) | `scene_params.py:376`, `:883-896` | `WEATHER_LOOK = False`: overcast weight 0 and no rain look for every real weather; only the road follows real rain |
| Whether the road is wet, damp or dry | EXTERNAL (observation) + CODE_RULE | `scene_params.py:1082-1124` | Rain now or rain in last 3 h → wet; both known and zero → dry; unknown → today's damp road |
| Which Remote Control functions may be called | CONFIG (Unreal's `art-source/unreal/AMNReference/Config/DefaultRemoteControl.ini`, `bAllowAnyRemoteFunctionCall=False`) + CODE_RULE (by construction) | `unreal.py:124-155`, `:219-238`, `:485-518`, `:530-698` | The game itself refuses anything outside its 14 ini entries: the people pass's 3 (`SetActorHiddenInGame`, `SetPlayRate`, `SetPosition`, built in `calls_for`), the environment pass's 10 (`ENVIRONMENT_CALLS`) and the one clock read (`CLOCK_TIME_READ`). In the backend `ENVIRONMENT_CALLS` is documentation, not a runtime check: nothing in `unreal.py` consults it; `environment_calls` only builds those pairs and `EnvCall.body` raises on any other function name. The ini and the frozenset are held equal by `tests/test_remote_control_allowlist.py:54-89` and `tests/test_office_environment_bridge.py:283-286` |
| Which level objects are driven | CONFIG (`env_report.json` written by the rebuild) | `unreal.py:391-466` | Only objects the report names; no report → nothing sent ("an object path is never guessed") |
| Whether the environment is sent at all | CODE_RULE | `unreal.py:789-801` | No report → 0 calls; report's facade heading ≠ setting → 0 calls until they agree. A report that carries no heading is not checked and is driven (`:793`) |
| When a value is re-sent | CODE_RULE | `unreal.py:705-717`, `:804-806` | Sun rotation ≥ 0.25°, clock > 0.25 s, sky on any change, other values > 1 % (min 1e-4); everything again every 20 s |
| Which seated employees Unreal shows | CODE_RULE (from the layout) | `unreal.py:109-155` | Visible iff an assignment holds the desk; visible ones held at `front_s` with play rate 0 |
| Whether the manual ingest route may measure at all | CODE_RULE + OWNER (connection state) | `backend/app/analytics/router.py:66-81`, `:153` | Only `POST /analytics/ingest/{publication_id}` calls `get_analytics_provider`: exactly one CONNECTED connection, else environment credentials, else HTTP 503 and nothing recorded. Every other analytics route answers from stored rows whatever the connections are (the router docstring's "these endpoints return HTTP 503", `:3-4`, holds only for ingest) |
| Which account measures a channel (daily stage) | CODE_RULE + OWNER (slot binding) | `backend/app/analytics/services.py:230-270` | Only the slot's bound `YouTubeConnection`, status CONNECTED; no fallback |
| Whether a publication can be measured | CODE_RULE | `analytics/services.py:173-177`, `:378-390` | status PUBLISHED and a remote video id; per channel |
| The figures in a snapshot | EXTERNAL (YouTube Analytics API) | `analytics/services.py:182`, `:206-224` | Stored as returned; DB refuses negative counts and retention outside 0..100 (`analytics/models.py:27-33`) |
| Whether the rest of a channel is still asked after a refusal | CODE_RULE | `analytics/services.py:394-406` | Token refresh failure or `auth_refused` → every remaining publication recorded with the same reason, not asked |
| Whether an analytics refusal raises a reconnect card | CODE_RULE → OWNER | `analytics/services.py:314`, `:339-348` | `exc.auth_refused` (token refresh or report refused by Google) and the adapter carries a connection id → `youtube_refused(..., source="analytics")`; an unreachable Google writes only the event |
| A channel's baseline | CODE_RULE | `backend/app/analytics/performance.py:283-319` | Medians over measured films ≤ 90 days old, only with ≥ 3 |
| A film's verdict (STRONG_WINNER … INSUFFICIENT_DATA) | CODE_RULE | `performance.py:331-418` | Needs baseline, age ≥ 24 h, a comparable rate; ratios 3.0 / 1.5 / 0.6 / 0.3 and retention ratio 0.7 / 1.0 |
| A film's failure kind and which role is told | CODE_RULE | `performance.py:432-518` | CTR ratio < 0.7, or zero impressions with fewer than 10 views (`:465-466`) → REACH (VideoEditor); retention ratio < 0.8 → RETENTION (ScriptWriter); conversion ratio < 0.6 with views ≥ 0.6 → CONVERSION (ScriptWriter); views ratio < 0.6 → TOPIC (LeadResearcher) |
| A channel's binding growth constraint | CODE_RULE | `performance.py:574-635` | < 3 measured → NO_DATA; most frequent non-insufficient kind over the newest 10; HIGH confidence at ≥ 3 occurrences |
| What is an anomaly | CODE_RULE | `performance.py:638-706` | RETENTION_DROP ≥ 15 % below median over last 3; VIEW_SPIKE ≥ 3× median rate; COST_SPIKE ≥ 2× median cost |
| A strategy recommendation | CODE_RULE (no model, despite the name "Director") | `analytics/services.py:679-841` | Cohort n ≥ 3; topic retention < 40 % or clickbait → −0.15; ≥ 60 % → +0.15; hook retention ≥ 65 % → +0.10; one PROPOSED per target |
| Applying a recommendation (new strategy version) | OWNER (HTTP route with the Owner key) + CODE_RULE | `analytics/router.py:209-221`, `analytics/services.py:844-953` | Only PROPOSED; refused during cooldown; delta clamped to ±0.20; weight floor 0.1 |
| Trends read at all | CONFIG (`STUDIO_TRENDS_ENABLED`, `STUDIO_TRENDS_GEO`) | `backend/app/analytics/trends.py:144-148` | Disabled → SKIPPED |
| Trend items kept | EXTERNAL (Google feed) + CODE_RULE | `trends.py:172-226` | First 25 items, titles already kept today skipped; HTTP ≠ 200, non-XML or > 2 MB → `trends.unavailable` |
| Whether a YouTube connection may be created/edited | OWNER + CODE_RULE | `backend/app/youtube/services.py:300-409` | Unique name; client id and secret required; redirect URI http(s), no query/fragment; a new client id or any typed client secret drops the refresh token (oddity 23) |
| Whether consent is forced | CODE_RULE | `youtube/services.py:467` | `prompt=consent` when no refresh token is stored or on an explicit reconnect |
| Whether an OAuth callback is accepted | CODE_RULE | `youtube/services.py:495-505` | `state` exists, unused, not expired (600 s); spent before the code exchange |
| Which channel and scopes a connection holds | EXTERNAL (Google) | `youtube/services.py:604-645` | Read from the token answer and `channels.list(mine=true)`; an account with no channel is refused |
| Whether a reconnect card is raised | CODE_RULE → OWNER | `youtube/services.py:533-537`, `:572-574` | Verification/authorisation failure whose reason contains `invalid_grant`; any upload refusal (`mark_reconnect_needed`) |
| Whether an agent is proposed for suspension | CODE_RULE | `backend/app/workforce/services.py:189-213` | ACTIVE, ≥ 5 runs in 30 days, failure rate ≥ 0.5 |
| Whether a hire is proposed | CODE_RULE | `workforce/services.py:216-237` | Queue backlog per active agent ≥ 8 and backlog ≥ 5 |
| Whether a workforce change happens | OWNER | `backend/app/workforce/router.py:79-102`, `workforce/services.py:270-336` | Owner route only; non-Owner approval raises `AutonomousChangeBlocked`; rejection needs a written reason (checked in the route, 422 at `router.py:85-89`; the service itself accepts an empty note). Only SUSPEND_AGENT and TERMINATE_AGENT can be carried to APPLIED; a HIRE_ROLE/REASSIGN_AGENT approval raises and rolls back (oddity 1) |
| A rehire / start of employment | OWNER | `workforce/router.py:104-115`, `workforce/services.py:402-451` | Refused while an open period exists; sets lifecycle ACTIVE from any lifecycle (oddity 5) |

## LLM involvement

**None of the 25 files contains an LLM call site, and no function here reaches `run_agent_task` through any static
path** (inventory: every function has `llm_distance = null`, `llm_call_site = false`; package rows in
`docs/project/backend_map/STATS.md`: `app.office` 142 functions, `app.analytics` 60, `app.youtube` 36,
`app.workforce` 16, all with 0 call sites and 0 reach). Reading the code confirms it: no import of
`app.agents.services`, `app.agents.structured`, `app.agents.ensemble`, `app.agents.reviews` or
`app.media.prompt_agent` exists in these files. The only imports from `app.agents` are `remember` (a memory row
write, `backend/app/analytics/services.py:937`, `backend/app/workforce/services.py:24`) and the ORM models.

Two places are named as if a model decided and are in fact deterministic code:

- **"Director recommendations"** (`generate_director_recommendations`, `analytics/services.py:679-841`) are fixed
  thresholds on cohort means; the "Director" in the name is the role the output is addressed to.
- **Workforce proposals** are counted rows by design: "Nothing here asks a model what it thinks of an employee"
  (`workforce/services.py:5-8`); an LLM performance review is listed as a rejected alternative in D-P8-001
  (`16_DECISION_LOG.md:1671-1675`).

**Numbers computed here that become prompt input elsewhere** (the call site is outside this group; the values are
code-computed, so what enters the prompt is not decided by a model):

| Function(s) here | Read by | Reaches the model through |
|---|---|---|
| `trending_now` (`trends.py:244`), `compute_cohort_metrics` (`analytics/services.py:617`), active `ContentStrategy.topic_weights_json` | `research/agent.py:_signals` (`backend/app/research/agent.py:347-394`) and `propose_topics` (`research/agent.py:398`, strategy read at `:430-435`) | Lead Researcher's topic proposal, `run_agent_task` at `research/agent.py:450` |
| `channel_health`, `growth_diagnosis`, `anomalies` (`performance.py:521/574/638`), `measure_workforce` (`workforce/services.py:60`) | `agents/command.py:company_state` (`backend/app/agents/command.py:364-436`) → `findings` (`:536`) | The Director's choice among matters, `run_with_strategy` at `agents/command.py:1156` |
| `measure_workforce` | `agents/director.py:520-529` | The Director's inbox review, `structured_run` at `backend/app/agents/director.py:534` |
| `story_performance` (`analytics/services.py:521`), `trends_as_text` (`trends.py:288`), PROPOSED `DirectorRecommendation` rows | `runbook/weekly.py` digest (`backend/app/runbook/weekly.py:131-157`, `:195`) | Weekly review, `run_agent_task` at `runbook/weekly.py:322` |
| `video_performance`, `film_cost` (`performance.py:207`, `:125`) | Director's level-1 repair `agents/repairs/film_cost.py:122`, `:217` | A repair tool the Director's loop may invoke |
| `decide_proposal` → `remember(memory_class="OWNER_POLICY", agent_id=None)` (`workforce/services.py:317-328`); `apply_director_recommendation` → `remember(memory_class="STRATEGY")` (`analytics/services.py:937-948`) | `recall` in `compose_identity` (`backend/app/agents/identity.py:287`): the newest studio-wide rows of the classes a role may read. Every role in `config/role_contracts.json` reads OWNER_POLICY (also the default for a role with no contract, `backend/app/agents/memory.py:121`); STRATEGY is read by the Director, LeadResearcher, ScriptWriter, Publisher and Accountant | Every agent's system prompt, composed inside `run_agent_task` (`backend/app/agents/services.py:790`): a sentence such as "The Owner approved a workforce proposal (SUSPEND_AGENT): …" becomes standing context for later runs |

Trust of these inputs inside this group: not applicable (no answer comes back here). Whether a model fails, refuses or
returns junk has no effect on any function in this group.

## Hard rules and limits

**Office view and stream**

| Constant | Value | Where | Meaning |
|---|---|---|---|
| `KEPT_FRAME_MAX_BYTES` | 768 KiB | `kept_frame.py:41` | Largest accepted title frame |
| `FUTURE_SLACK_MS` | 60 000 | `kept_frame.py:43` | Capture time may be at most 60 s ahead |
| `MAX_AGE_MS` | 24 h | `kept_frame.py:45` | Older captures are refused |
| `MAX_FRAME_SIDE` | 4096 px | `kept_frame.py:79` | Picture side limit |
| `_VP8X_REFUSED_FLAGS` | animation, XMP, EXIF | `kept_frame.py:80` | Refused WebP features |
| `VISIBLE_LIFECYCLES` | HIRED, ACTIVE, PAUSED, SUSPENDED | `office/services.py:17` | Drawn agents |
| `ALIASES` | EXECUTING/RUNNING→WORKING, PLANNING→THINKING, FAILED→ERROR | `presentation.py:24` | Runtime state mapping |
| `media_max_bytes`, `valid_ms` | 67 108 864, 35 000 | `config/pixel_presentation.json` (read at `presentation.py:19-23`) | Monitor film size cap, presentation validity |
| `OPEN_TIMEOUT_S` | 5.0 s | `stream.py:41` | Upstream signalling connect |
| `SOCKET_AUTH_TIMEOUT_S` / `SOCKET_AUTH_MAX_PENDING` | 5.0 s / 16 | `security.py:101`, `:107` | First-message key wait; sockets waiting at once |
| `CACHE_SECONDS` / `FAILURE_SECONDS` | 600 / 120 | `weather.py:38-39` | Weather cache for success / failure |
| HTTP timeout to weather host | 10 s | `weather.py:202` | |
| `WMO` | 28 codes → (condition, intensity) | `weather.py:45-74` | Unknown code = unavailable |
| `STALE_WEATHER_S` | 3600 s | `world.py:41` | Kept observation lifetime |
| `REFERENCE_DUSK_ELEVATION` | −2.5° | `world.py:35` | The approved dusk |
| `HORIZON_ELEVATION` | −0.833° | `world.py:38` | Sunrise/sunset convention |
| `office_unreal_sync_seconds` | 5 s (1..300) | `config.py:224` | Bridge loop period |
| `office_unreal_env_refresh_seconds` | 20 s (5..600) | `config.py:238` | Full resend |
| `office_unreal_env_ease_seconds` | 30 s (0..600) | `config.py:239` | Light ease duration |
| `office_weather_refresh_seconds` | 600 s (60..3600) | `config.py:240` | Weather read cadence in the bridge; 120 s after a failure (`unreal.py:969`) |
| `office_facade_heading_deg` | 180 (D1) | `config.py:230` | Facade faces south |
| `CALL_TIMEOUT_S` / `REFRESH_S` | 2.0 s / 20 s | `unreal.py:54`, `:59` | Remote Control call timeout; seat resend |
| `SUN_STEP_DEG` / `VALUE_STEP` / `CLOCK_STEP_S` | 0.25° / 1 % / 0.25 s | `unreal.py:242-247` | Send-on-change thresholds |
| `ENVIRONMENT_CALLS` | 10 (class, function) pairs | `unreal.py:219-232` | The environment pass's share of the game's allow-list; not consulted at runtime (tests hold it equal to `DefaultRemoteControl.ini`, which also lists the people pass's 3 calls and the clock read) |
| `CLOCK_TIME_READ` | `GameplayStatics.GetTimeSeconds` | `unreal.py:238` | The one read |

**Scene parameters (all in `backend/app/office/scene_params.py`)** — the build's dusk: `SKY_GAIN` 1.1 (`:75`),
`SKY_LIGHT_DUSK` 0.6 (`:77`), SunDusk key 2.5 at 8°, colour (1.0, 0.62, 0.38) (`:82-84`), `TWILIGHT_END_ELEVATION` −6°
(`:92`), `FOG_DENSITY` 0.008 (`:94`), haze colours/opacity 0.55, far share 0.7 (`:98-101`), wet road roughness
0.14–0.38, dry 0.6–0.9 (first estimate, never built), rain film 0.08–0.24 (`:103-113`). Day: `CITY_DAY_EMISSION` 0.06
(`:118`), `DAY_FULL_ELEVATION` 6° (`:124`), `LIGHTS_ON_BELOW` −2° (`:127`), day sun 5800 K from 30° (`:130-132`).
Golden hour: key up to 6.0 by +1°, handed to the sun across 10–20° (`:144-146`), amber 3000 K (`:150`), warm rise/fade
(`:151-152`), air share 0.5 (`:158-160`). Measured fill curves `FACADE_CLEAR_ANCHORS` (`:185-193`) and
`STREET_CLEAR_ANCHORS` (`:208-216`), lamp ramp −2 → −2.5° (`:219`), `WALK_WASH_MAX` 1.0 (`:223`). Cloud deck:
`FILL_SUN_EQUIVALENT` 0.8, `OVERCAST_FILL_SHARE` 0.44, `RAIN_FILL_LOSS` 0.3, `DECK_SKY_LIGHT_LIFT` 20,
`RAIN_SKY_LIGHT_LOSS` 0.25 (`:234-253`). Built fill colours read over Remote Control (`:262-266`), warm share 0.7
(`:272-274`). Dawn: cooling 0.35, plate shift 2°, city windows 0.45 (`:281-294`). Towers: windows off above 15°, 0.7
lit at 2.5°, near-block floor 0.5 faded over 10→6°, evening 0.98 over 8→3°, ranks 0.02–0.95, gate sharpness 50
(`:315-343`). Night: gain boost 1.2 over −6→−12° (`:351-354`). Weather: `CONDITION_CLOUD` (`:358-367`),
`WEATHER_LOOK = False` (`:376`), overcast from 50 % cloud, sun loss 0.85, key loss 0.7 (`:378-381`), overcast plates
(2, 7) below 8° (`:399-401`), gain losses (`:406-408`), deck haze and fog factors (`:412-421`). Atlas cells at −18, −12,
−8, −5, −2.5, 0, 3, 8, 15, 35° (`:425`).

**Analytics**

| Constant | Value | Where | Meaning |
|---|---|---|---|
| `MIN_SAMPLE_THRESHOLD` / `MAX_WEIGHT_DELTA` | 3 / 0.20 | `analytics/services.py:43-44` | Recommendation evidence and bound |
| `ck_recommendation_has_evidence` / `_change_is_bounded` | sample ≥ 3; −0.20..0.20 | `analytics/models.py:131-135` | Database-level copy of the same rules |
| `ck_snapshot_counts_positive` / `_retention_is_a_percentage` | views, impressions ≥ 0; 0..100 | `analytics/models.py:29-33` | |
| `ck_decision_is_reviewable` | review condition required unless NEEDS_MORE_DATA | `analytics/models.py:186-190` | `DirectorDecision` |
| Topic thresholds | retention < 40 % or clickbait → −0.15; ≥ 60 % → +0.15 | `analytics/services.py:727-742` | |
| Hook threshold | retention ≥ 65 % → +0.10 | `analytics/services.py:800-801` | |
| Clickbait | mean CTR > 10 % and mean retention < 40 % | `analytics/services.py:654` | Score 0.5·ret + 0.5·ctr, else 0.7·ret + 1.5·ctr |
| Duration cohort | "45s" if `watch_time_seconds` < 50 else "60s" | `analytics/services.py:640` | |
| Recommendation confidence | min(0.95, 0.5 + 0.1·n) | `analytics/services.py:746`, `:803` | |
| Strategy weight floor | 0.1 | `analytics/services.py:890`, `:893` | |
| Baseline strategy | every weight 1.0; 45 s factual, 60 s serial | `analytics/services.py:57-90` | |
| `MINIMUM_BASELINE` | 3 films | `performance.py:52` | |
| `MINIMUM_JUDGEMENT_HOURS` | 24 h | `performance.py:56` | |
| `BASELINE_DAYS` | 90 | `performance.py:64` | |
| `WINNER/PROMISING/UNDERPERFORMER/FAILED_RATIO` | 3.0 / 1.5 / 0.6 / 0.3 | `performance.py:67-70` | Multiples of the channel median |
| Confidence | LOW (< 24 h or < 3 films); HIGH at ≥ 10 films and ≥ 72 h | `performance.py:322-328` | |
| Rates | views/hour only from 1 h of age | `performance.py:240-245` | |
| Anomalies | retention drop ≥ 15 %, view spike ≥ 3×, cost ≥ 2× | `performance.py:663`, `:678`, `:693` | |
| `TRENDS_HOST`, `MAX_BYTES`, `KEEP_PER_REFRESH`, `PROMPT_LIMIT` | trends.google.com, 2 MB, 25, 12 | `trends.py:35-39` | |
| Feed timeout / freshness / prompt window | 15 s / 20 h / 48 h | `trends.py:100`, `:229`, `:245` | |
| Performance intake batch | 5 newest publications per channel per run | `backend/app/runbook/stages.py:213`, `:429` | Caller outside scope |

**YouTube**

| Constant | Value | Where |
|---|---|---|
| `OAUTH_STATE_TTL_SECONDS` | 600 | `youtube/models.py:28` |
| `state` | `secrets.token_urlsafe(32)` (43 chars), single use | `youtube/services.py:454`, `:495-505` |
| `SCOPES` | youtube.readonly, youtube.upload, yt-analytics.readonly, youtube.force-ssl | `youtube/services.py:53-58` |
| Statuses | AUTH_REQUIRED, CONNECTED, ERROR (DB check) | `youtube/services.py:101-103`, `youtube/models.py:37-39` |
| Timeouts | 20 s token/API, 10 s revoke | `youtube/services.py:149`, `:176`, `:767` |
| Snapshot description cap | 500 chars | `youtube/services.py:224` |

**Workforce**

| Constant | Value | Where |
|---|---|---|
| `MIN_RUNS_FOR_JUDGEMENT` | 5 (DB: `ck_proposal_has_evidence` sample ≥ 5) | `workforce/services.py:33`, `workforce/models.py:23` |
| `OBSERVATION_DAYS` | 30 | `workforce/services.py:35` |
| `FAILURE_RATE_THRESHOLD` | 0.5 | `workforce/services.py:37` |
| `BACKLOG_PER_AGENT_THRESHOLD` | 8 | `workforce/services.py:39` |
| `need_score` | suspension: the failure rate; hire: min(1, backlog per agent / 16); DB 0..1 | `workforce/services.py:211`, `:236`, `workforce/models.py:24-26` |
| Proposal state machine | PROPOSED → APPROVED → APPLIED in one transaction, or PROPOSED → REJECTED; APPROVED is never committed on its own (an `_apply` refusal rolls it back) | `workforce/services.py:289-333` |
| `autonomous_firing_enabled` | `Literal[False]` | `backend/app/schemas.py:74` |

## Modules

### `app.office.kept_frame` — backend/app/office/kept_frame.py (266 lines)

One kept real frame of the live Unreal headquarters for the first visit's title page, outside the database, written
atomically, public to read and Owner-only to write (W24/W25, `kept_frame.py:1-16`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `kept_frame_dir` | 62 | Configured folder, else `office/` beside the SQLite file | Keep the frame out of the database | CONFIG (`office_kept_frame_dir`) |
| `_picture_size` | 84 | Size declared by a VP8 key frame or VP8L picture, or None | Part of the structural WebP check | CODE_RULE |
| `is_webp` | 101 | Accepts only RIFF/WEBP whose chunks fill the file exactly: optional VP8X first (no animation/XMP/EXIF, canvas = picture), optional ICCP/ALPH, exactly one picture 1..4096 px | "A key holder cannot park other bytes behind a WebP header" (`:107`) | CODE_RULE |
| `newest_kept` | 151 | Newest `kept-<ms>.webp` in the folder | Read side | CODE_RULE |
| `store_kept` | 168 | Under a lock: refuses an older-or-equal capture, writes a scratch file, fsyncs, `os.replace`s it, removes older frames | Readers see the old or the new frame, never half | CODE_RULE |
| `_captured_at` | 199 | Parses `X-Captured-At`; refuses > 60 s ahead or > 24 h old | No made-up capture times | CODE_RULE |
| `_body` | 209 | Reads the body, stops as soon as it exceeds the limit | Size cap before buffering | CODE_RULE |
| `create_kept_frame_router` | 224 | Builds the two routes below | | |
| `read_kept_frame` (GET `/api/v1/office/kept-frame`, public) | 228 | Returns the frame with `X-Captured-At`, or 204 | 204 keeps strangers' consoles clean (`:14-15`) | CODE_RULE |
| `keep_frame` (POST, `require_owner`) | 247 | 415 / 422 / 413 / 415 checks, then `store_kept` in a thread; 201 stored, 200 older | Only the Owner's page writes | OWNER key + CODE_RULE |

Data: one file `kept-<ms>.webp` in the office folder. No events, no database. External calls: none.

### `app.office.presentation` — backend/app/office/presentation.py (122 lines)

A read-only choreography of each agent's real state for the pixel renderer, and the list of real films the office
monitors may play.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `agent_presentation` | 27 | Maps `runtime_state` through `ALIASES` to a mode and a cycle from `config/pixel_presentation.json`; non-ACTIVE → PAUSED, monitor off; `phase_ms` = (now + SHA-256 seed) mod cycle length; `kind: presentation_only` | Agents animate from their real state, desynchronised deterministically | CODE_RULE + CONFIG |
| `monitor_media` | 48 | Up to 12 confirmed public/unlisted processed YouTube uploads with an 11-char id, and up to 3 local real mp4 renders (FAKE/SIMULATED/DUMMY excluded, ≤ 64 MiB); a Romanian `empty_reason` when none | "Only confirmed real public/unlisted publications, no provider call or simulation" (`:49`) | CODE_RULE + CONFIG |
| `presentation_snapshot` | 111 | `{schema 1, server_ms, valid_ms, agents, media}` from the layout | GET `/office/presentation` | CODE_RULE |

Data read: `ChannelRecord`, `PublicationRecord`, `MediaAsset`, the layout. Written: nothing. External: none.

### `app.office.router` — backend/app/office/router.py (36 lines)

Owner-only routes (`dependencies=[Depends(require_owner)]`, `router.py:16`).

| Function | Line | What it does | Decided by |
|---|---|---|---|
| `create_office_router` | 15 | Builds the routes | |
| `get_layout` (GET `/api/v1/office/layout`) | 19 | `get_office_layout_with_assignments` | CODE_RULE |
| `get_weather` (GET `/office/weather`) | 23 | `current_weather(settings)`; "Never invented." | EXTERNAL + CONFIG |
| `get_presentation` (GET `/office/presentation`) | 28 | `presentation_snapshot` with media roots | CODE_RULE |
| `get_stream` (GET `/office/stream`) | 32 | `stream_status` | CONFIG |

### `app.office.scene_params` — backend/app/office/scene_params.py (1288 lines)

"Every value the live headquarters takes, from the real world — one pure function" (`:1`): no clock, file or network is
read (`:3-6`). Its design rules — the approved dusk does not drift (every output equals the build's value at the
reference), the twilight keys are separate from the movable real sun, nothing is invented, a real day not a dusk with a
switch, the front ground on the noon's budget, the weather look held, the towers' day state — are spelled out in the
module docstring (`:8-53`), each constant with what it was measured against.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `scene_params` | 1136 | Returns sun (intensity, colour, rotation), both twilight keys, sky light, lights factors, fill colours, sky plates, emissive factors, window view, near-block/tower/tree/skyline day parameters, haze, fog, road, clock offset, `exposure: None` (D2), a Romanian weather note | The single source of every value sent to Unreal | CODE_RULE |
| `sky_plates` | 1015 | Picks the two atlas cells and the blend by projecting the real (daylight, dusk) pair between the cells' pairs; dawn takes a 2° deeper plate; night gain boost; overcast/rain branches (inactive while `WEATHER_LOOK` is False) | A blended plate reads as the plate compose would have made | CODE_RULE |
| `road` | 1082 | Roughness from real rain: falling (with weather look) → film; rain now or in 3 h → wet; known zero → dry; unknown → today's damp | Road follows only real rain | EXTERNAL + CODE_RULE |
| `sun_rotation` | 984 | Directional light rotation from azimuth/elevation via the level's measured axes and facade heading | Sun on the correct side (D1) | CODE_RULE + CONFIG |
| `twilight_keys` / `key_intensity` / `key_colour` | 727 / 711 / 718 | The key on the sun's side at max(twilight glow, golden low sun), the other dark; colour from the sky arch below the reference, the sun's above | No "hole" at the crossover (`:713-714`) | CODE_RULE |
| `twilight_intensity` / `golden_key_intensity` | 659 / 700 | Twilight glow normalised to 2.5 at reference, dark at −6° and from +6°; golden key 2.5→6.0 by +1°, handed over 10–20° | The "power cut" fix | CODE_RULE |
| `sun_intensity` / `direct_beam` / `air_mass` | 584 / 577 / 572 | Meinel clear-sky beam with Kasten–Young air mass, scaled to 2.5 at 8° | Relative sun at fixed exposure (D2) | CODE_RULE |
| `sun_colour` / `golden_warmth` / `dawn_cool` / `golden_air` | 631 / 592 / 620 / 603 | Warming toward 3000 K near the horizon, 5800 K by 30°, cooler mornings, warmer air in the golden hour | Measured looks | CODE_RULE |
| `fill_factor` / `facade_factor` / `walk_wash_factor` | 796 / 807 / 816 | StreetFill on `STREET_CLEAR_ANCHORS` above −2°, ramped to 1 with the lamps; FacadeLight on its own curve; WalkWash ≤ 1 | Front ground never brighter than at noon | CODE_RULE |
| `fill_colours` | 844 | Built colours, tinted toward the key's hue by up to 0.7 in the golden hour | Grey-lavender street fixed | CODE_RULE |
| `cloudiness` / `precipitating` / `overcast_weight` / `rain_look` | 865 / 875 / 883 / 893 | Real cloud and rain; overcast weight and rain look forced off by `WEATHER_LOOK` | Held weather look | CODE_RULE |
| `windows_share` / `tower_windows_share` / `near_windows_share` / `windows_on` | 920 / 935 / 957 / 970 | Lit-window share by real sun, dawn ceiling, near-block floor and evening lift, mapped to the material's rank gate | Day state of 2026-09-26 | CODE_RULE |
| `city_windows` / `night_weight` | 912 / 907 | Fewer city windows at dawn; night glow weight | | CODE_RULE |
| `clock_offset_s` | 1128 | (wall seconds − game time) mod 86 400 | Clock face shows the real time | CODE_RULE |
| `dawn_plate_elevation` | 1008 | Elevation shifted 2° deeper before the dawn glow peaks | Cooler dawn sky | CODE_RULE |
| `plate_stops` / `gradient_at` / `plate_mean_linear` / `sky_brightness` / `twilight_arch_linear` / `twilight_colour` | 520–697 | Re-implementations of `compose_sky_backdrop.py`'s gradient to derive light from the plate | Light from the scene's own sources | CODE_RULE |
| `anchored`, `clear_facade`, `clear_fill`, `sun_ground_share`, `deck_fill`, `sky_fill`, `deck_sky_light`, `fill_built_colour`, `fill_warmth`, `greyed`, `near_windows_floor`, `near_windows_lift`, `golden_amber`, `day_weight`, `night_scale`, `plate_daylight`, `plate_dusk`, `sunrise_side` | 744–1012 | Curve helpers | | CODE_RULE |

Helpers: `smoothstep`, `mix`, `mix3`, `scale3`, `srgb_bytes`, `to_linear`, `linear3`, `normalised`, `luminance`
(`:469-506`) — colour and interpolation arithmetic. Data: none read or written. External calls: none.

### `app.office.services` — backend/app/office/services.py (394 lines)

The authoritative office layout (world pixels of the Blender-built headquarters, kept in step with
`frontend/public/assets/hq/manifest.json` by `tests/test_office_layout_matches_scene.py`, `services.py:43-45`) and the
desk assignment that both the page and the Unreal bridge read.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `personal_pixel_slots` | 20 | Seat per agent from immutable hiring order; former staff keep their reservation | "pausing, leaving or hiring cannot move another employee" (`:24-25`); a seat is presentation metadata, never a capability | CODE_RULE + CONFIG (`config/pixel_office.json`) |
| `get_office_layout_with_assignments` | 277 | Copies `DEFAULT_OFFICE_LAYOUT`; assigns visible agents to desks by role substring, else first unassigned; extra staff get personal desks from stations; adds model name, availability and provider per agent (None when the Owner assigned none) | One layout for every renderer; never show a plausible default model (`:291-294`, `:344-345`) | CODE_RULE |

Data read: `Agent`, `Role`, `ModelRecord`, `ProviderRecord`; config `config/pixel_office.json` (loaded at import,
`:14-16`). Written: nothing.

### `app.office.stream` — backend/app/office/stream.py (142 lines)

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `signalling_target` | 54 | Configured ws/wss URL or None | | CONFIG |
| `stream_status` | 63 | `{available, relay: "/api/v1/office/stream/signalling", auth: "first_message"}` | Tells the page whether to try | CONFIG |
| `register_stream_gateway` | 72 | Registers the WebSocket `office_stream_signalling` (line 81): refuse key-in-URL, accept, first-message Owner key, connect upstream (5 s), send `relay_ready`, relay | CSP allows only the page's origin; key never forwarded, echoed or logged (`:10-16`) | CODE_RULE + OWNER key |
| `office_stream_signalling` (WebSocket `/api/v1/office/stream/signalling`, not in the inventory) | 81 | `refuse_key_in_url` (SEC-02) → `accept` → `socket_first_message_auth` against `owner_token` (5 s, at most 16 sockets waiting, `backend/app/security.py:101`, `:107`) → no target: close 1013 → `connect(target, open_timeout=5, max_size=None)`, failure: close 1013 and log the error class → `relay_ready` → `_relay`, upstream closed in `finally` | The relay's whole gate | CODE_RULE + OWNER key |
| `_relay` | 108 | Two tasks copying text/bytes both ways; first to finish cancels the other; logs unexpected errors by class only | | CODE_RULE |

External: the configured Pixel Streaming signalling server (local). No database.

### `app.office.unreal` — backend/app/office/unreal.py (1033 lines)

The background task that keeps the running Unreal level in step with the studio (seated employees) and with the real
world (environment pass). Started from the app's lifespan only when `STUDIO_OFFICE_UNREAL_REMOTE_URL` is a valid
http(s) URL (`backend/app/main.py:382-386`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `remote_control_target` | 64 | Configured http(s) URL or None | | CONFIG |
| `load_seats` | 73 | desk id → actor, body, animation, `front_s` from `seat_report.json`; incomplete seats dropped; a missing, negative or boolean `front_s` reads as 0.0; unreadable report → no seats | Object paths come from the seating script, never guessed | CONFIG (report file) |
| `state_of` | 101 | PAUSED for PAUSED/SUSPENDED lifecycle, else runtime state | Same reading as the page's `hq_agents.js` | CODE_RULE |
| `desired_states` | 109 | Per seated desk: visible iff assigned; moving iff not PAUSED | "an employee is on screen only while an agent holds that desk" (`:8-10`) | CODE_RULE |
| `calls_for` | 124 | `SetActorHiddenInGame`; if visible, `SetPlayRate 0` and `SetPosition front_s` | Every character faces the viewer | CODE_RULE |
| `http_sender` | 158 | One PUT to `/remote/object/call` | | |
| `UnrealBridge.sync` | 185 | Sends changed seats; on failure clears memory and returns 0; full resend every 20 s | A restarted level replays loops; resend keeps that window short (`:55-59`) | CODE_RULE |
| `_day_state` | 355 | Accepts `day_state` components only in the report's one world, only towers that the report scales as skyline/near blocks, only listed known parameters | Repeats the refusals of `day_state.py`'s merge | CODE_RULE |
| `load_env_report` | 391 | Parses `env_report.json`: labels → roles, axes, facade heading, emissive scaling, road, window view, day state; None when anything essential is missing | "Nothing is guessed: what the report does not name is not driven" (`:399-400`) | CONFIG (report) + CODE_RULE |
| `EnvCall.body` | 485 | Builds the Remote Control JSON body per function | | CODE_RULE |
| `environment_calls` | 530 | Turns `scene_params` output into calls for exactly the objects the report names (sun, twilight keys intensity/colour only, sky light, fog, light factors × the saved intensity, fill colours, sky plate group, clock offset, emissive factors where uniform, near-block/skyline Daylight, towers, trees, window view, road, haze) | Builds only the ten pairs of `ENVIRONMENT_CALLS` (by construction; the set is not checked here) | CODE_RULE |
| `_moved` | 705 | Change thresholds per kind | Avoid re-rendering shadows for tiny moves | CODE_RULE |
| `EnvironmentPass._eased` | 753 | Linear ease over `ease_s`, re-aimed (not restarted) when the target moves mid-ease | Decision 2026-09-24 (`16_DECISION_LOG.md:3960`) | CODE_RULE |
| `EnvironmentPass.sync` | 781 | Refuses without report or with heading mismatch (only when the report states a heading, `:793`); computes plan; eases `value` calls; sends changed calls (sky group whole) in one batch; records only 2xx; logs each refusal once | Keep the sun on the right side (D1) and re-render shadows only on real moves | CODE_RULE |
| `http_batch_sender` | 845 | One call → `/remote/object/call`; several → `/remote/batch`; HTTPError is an answer (status), not an outage | | |
| `http_game_time_reader` | 890 | Reads `GetTimeSeconds` for the level's world | Clock face needs the game's time; never estimated (`:233-238`) | EXTERNAL (Unreal) |
| `environment_clock` | 919 | Real clock, or a rehearsal clock on a copy; on the live studio the refusal is logged and the real clock kept | | CODE_RULE |
| `EnvironmentRunner._weather` / `tick` | 960 / 973 | Weather on its cadence (none during a rehearsal), stale keeping, game time read and mid-request corrected, world state, pass | | CODE_RULE |
| `run_unreal_bridge` | 1004 | Loop until stop: layout + seats sync, then environment tick, each guarded so a failure never ends the loop; sleeps `office_unreal_sync_seconds` | | CODE_RULE |

Helpers: `EnvReport.frame`, `EnvReport.of`, `EnvCall.key`, `_vector`, `_number`, `_object`, `_world_of`, `_scalar`,
`_colour`, `_as_tuple`, `_once`, `_without_rehearsal` (931; its `__getattr__`, 934, reads the settings through
but answers None for `office_world_rehearsal_at`, so the live studio keeps the real clock) — parsing and formatting. Data read: the layout (database),
`seat_report.json`, `env_report.json`, the weather. Written: nothing (logs only). External: Unreal Remote Control
(local HTTP), the weather host.

### `app.office.weather` — backend/app/office/weather.py (242 lines)

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `unavailable` | 77 | `{available: False, reason}` | | |
| `parse_observation` | 81 | Validates `current`, maps the WMO code, copies every variable as float or None, UTC timestamp, past-3-h precipitation | A missing value is None, never zero | CODE_RULE |
| `observation_utc` | 124 | Local ISO time + `utc_offset_seconds` → UTC ISO, else None | Browsers in other zones | CODE_RULE |
| `precipitation_last_hours` | 139 | Sum of the last N hourly values at or before the observation; None on gaps or fewer hours | Forecast hours never counted as rain that fell | CODE_RULE |
| `fetch_observation` | 163 | GET `/v1/forecast` with 15 current variables, 3 past hours + 1 forecast hour, 10 s timeout | | EXTERNAL |
| `current_weather` | 207 | Cached (600 s / 120 s) observation or unavailable reason; never raises | | CONFIG + EXTERNAL |
| `reset_cache` | 240 | Clears the module cache (tests) | | |

External: the configured Open-Meteo-compatible host (free tier licensed for non-commercial use, flagged for the Owner at
`weather.py:18-20`).

### `app.office.world` — backend/app/office/world.py (377 lines)

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `Weather.from_observation` | 74 | Typed copy of an observation; non-numbers and bools → None | | CODE_RULE |
| `solar_position` | 128 | NOAA solar calculator equations → elevation and azimuth | Real sun, no service | CODE_RULE |
| `build_world_state` | 178 | UTC instant, local wall clock (zoneinfo), sun, weather or reason, age, rehearsal flag | The only input of `scene_params` | CODE_RULE + CONFIG (coords, timezone) |
| `WeatherKeeper.observe` | 224 | Keeps the last real observation up to an hour as `stale` | Outage tolerance without invention | CODE_RULE |
| `_crossing` | 238 | First instant an elevation is crossed (5-min scan, 1-s bisection) | | CODE_RULE |
| `check_instants` | 265 | Sunrise, sunset, solar noon, ±6/−2.5/−6/−12/−18° crossings of a local date | On-screen checks on the day of the check, never hard-coded | CODE_RULE |
| `is_live_studio` | 310 | True for `data/studio.db` or any non-SQLite URL; False for `:memory:` or another file | Rehearsals only on a copy | CODE_RULE |
| `world_clock` | 332 | Real now, or anchor + monotonic elapsed on a copy; raises on live | | CODE_RULE |
| `main` | 352 | Prints today's check instants (Romanian labels) | Owner's check day | |

Helpers: `_julian_century` (123, Julian centuries since J2000.0 from a UTC instant, the time
argument of the NOAA equations), `_zone` (174, the configured `timezone` as a `ZoneInfo`, default
Europe/Bucharest).

### `app.analytics.models` — backend/app/analytics/models.py (246 lines)

Tables only: `AnalyticsSnapshot` (`:22`, windows 1h/24h/7d/28d/LIFETIME), `ContentExperiment` (`:66`, DRAFT/ACTIVE/
CONCLUDED/CANCELLED), `ContentStrategy` (`:99`, versioned weights, `cooldown_until`), `DirectorRecommendation`
(`:124`, PROPOSED/APPLIED/DISMISSED), `DirectorDecision` (`:164`, migration 0033 — written by `app.agents.command`
and `app.agents.repairs.desk`, not by this package), `TrendSnapshot` (`:227`, migration 0028). Database checks listed
under "Hard rules". `app.analytics.__init__` (15 lines) re-exports four of the models.

### `app.analytics.schemas` — backend/app/analytics/schemas.py (119 lines)

Pydantic views and commands: `AnalyticsSnapshotView`, `ContentExperimentView`, `CreateExperimentCommand`
(name 1..100, hypothesis 1..1000, `sample_size_target` 1..100, `:51-59`), `ContentStrategyView`,
`DirectorRecommendationView`, `CohortMetricView`, `ChannelAnalyticsSummaryView`, `IngestMetricsCommand`. No functions.

### `app.analytics.performance` — backend/app/analytics/performance.py (706 lines)

Reads only. Normalises, baselines, classifies, diagnoses. "Nothing is invented … one video is never a conclusion about a
category" (`:22-24`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `film_cost` | 125 | Sums `ProviderCostRecord` rows attributed to the storyboard, plus narration rows naming its render jobs and no board; split BILLED / reconciled estimate / estimate, per provider; `rows: 0` = unpriced | Higgs film read as free (`:136-138`) | CODE_RULE |
| `_cost_and_time` | 189 | Cost (USD, None if no rows) and render minutes for a media asset | "unpriced is not free" | CODE_RULE |
| `video_performance` | 207 | Every PUBLISHED publication with a remote id, newest first: latest snapshot (LIFETIME preferred), age, views/hour and /day (from 1 h), conversion, engagement, cost, views per dollar, CPM | Rates, not totals | CODE_RULE |
| `channel_baselines` | 283 | Rolling medians over measured films ≤ 90 days, only with ≥ 3 | Compare to the channel itself | CODE_RULE |
| `_confidence` | 322 | LOW / MEDIUM / HIGH by sample and age | | CODE_RULE |
| `classify` | 331 | Verdict vs baseline with reason in Romanian and evidence | | CODE_RULE |
| `diagnose` | 432 | REACH / RETENTION / CONVERSION / TOPIC / INSUFFICIENT_DATA and the role to assign | "two different assignments to two different departments" (`:435-438`) | CODE_RULE |
| `channel_health` | 521 | Last 7 days vs the 7 before: views, subscribers, cost, baseline | "the only version worth a decision" (`:524-525`) | CODE_RULE |
| `growth_diagnosis` | 574 | Binding constraint and role from the newest 10 diagnoses | The Owner's question "what prevents faster growth" (`:577-580`) | CODE_RULE |
| `anomalies` | 638 | Retention drop, view spike, cost spike per channel with a baseline | "a reason to look", not a verdict | CODE_RULE |

Helpers: `_hours_since`, `_ratio`, `_percent`, `_latest_snapshots`, `_verdict`. Data read: `AnalyticsSnapshot`,
`PublicationRecord`, `ChannelRecord`, `VideoRenderJob`, `ProviderCostRecord`. Written: nothing.

### `app.analytics.router` — backend/app/analytics/router.py (248 lines)

All routes under `/api/v1/analytics`, Owner-only (`:85`).

| Function | Line | What it does | Decided by |
|---|---|---|---|
| `get_analytics_provider` | 66 | Test-injected provider, else `YouTubeAnalyticsProvider.from_verified_settings` (exactly one CONNECTED row, else env credentials); none → 503. Called only by `ingest_metrics` (`:153`) | CODE_RULE + OWNER (connections) |
| `create_analytics_router` | 84 | Builds the routes | |
| `get_trends` (GET `/trends`) | 88 | Up to 25 recent trends | CONFIG |
| `post_trends_refresh` (POST `/trends/refresh`) | 100 | `refresh_trends` now (the page's button, `frontend/src/main.js:1989`) | OWNER (button) |
| `get_summary` (GET `/channels/{id}/summary`) | 107 | `get_channel_summary` | CODE_RULE |
| `read_performance` (GET `/performance`) | 114 | `video_performance` | CODE_RULE |
| `read_channel_health` (GET `/channel-health/{id}`) | 119 | `channel_health` | CODE_RULE |
| `read_growth` (GET `/growth/{id}`) | 124 | `growth_diagnosis` | CODE_RULE |
| `read_anomalies` (GET `/anomalies`) | 129 | `anomalies` | CODE_RULE |
| `read_story_performance` (GET `/story-performance`) | 134 | `story_performance` | CODE_RULE |
| `get_cohorts` (GET `/cohorts/{id}`) | 139 | `compute_cohort_metrics`, `cohort_by` topic/hook/duration | CODE_RULE |
| `ingest_metrics` (POST `/ingest/{publication_id}`) | 147 | Ingest one publication; 409 nothing measurable, 404 unknown (any `ValueError`, including the adapter's "Unsupported analytics window", oddity 22), 500 DB fault (Romanian), 502 platform silent | EXTERNAL + CODE_RULE |
| `get_strategy` (GET `/strategy/{id}`) | 180 | Active strategy or 404 | |
| `get_recommendations` (GET `/recommendations/{id}`) | 190 | List | |
| `generate_recommendations` (POST `/recommendations/{id}/generate`) | 199 | `generate_director_recommendations` | CODE_RULE |
| `apply_recommendation` (POST `/recommendations/{rec_id}/apply`) | 210 | `apply_director_recommendation`; 400 on refusal | OWNER |
| `get_experiments` (GET `/experiments/{id}`) | 224 | List | |
| `create_new_experiment` (POST `/experiments`) | 231 | `create_experiment` | OWNER |

### `app.analytics.services` — backend/app/analytics/services.py (1033 lines)

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `seed_default_strategy` | 93 | Neutral v1 strategy per seeded channel type that has none (called from `scripts/bootstrap.py:91`) | No preference before any measurement (`:54-56`) | CONFIG (in-code baseline) |
| `get_active_strategy` | 131 | Newest active strategy for a channel | | |
| `ingest_publication_metrics` | 156 | Refuses non-PUBLISHED or id-less publications (`MetricsUnavailable`); `asyncio.run(provider.fetch_video_metrics)`; writes `analytics.snapshot_ingested` and the snapshot in one transaction | The internal row id used to be sent to the provider (`:169-172`) | EXTERNAL + CODE_RULE |
| `analytics_provider_for_channel` | 230 | Adapter from the slot's bound CONNECTED connection and the vault, or (None, Romanian reason) | Decision 2026-09-17 | CODE_RULE + OWNER (binding) |
| `_record_account_refusal` | 273 | Romanian reason naming account and slot; event `youtube.token_refresh_failed` (`during == "token_refresh"`) or `youtube.analytics_refused` in its own transaction; a reconnect card only when `auth_refused` (an unreachable Google writes the event, no card); nothing is recorded when the adapter has no connection id (`:314`) | The preflight reads the newest one instead of calling Google (`:144-153`) | CODE_RULE → OWNER |
| `measure_channel_publications` | 355 | Ingests each PUBLISHED publication of one channel (limit); an account refusal stops asking and marks the rest | "fifteen seconds of timeout at a time" avoided (`:372-374`) | CODE_RULE |
| `get_channel_summary` | 417 | Totals and means over all snapshots of the channel | | CODE_RULE |
| `_resolve_publication_metadata` | 471 | Topic and selected hook via render job → storyboard → script → topic; tag fallback; default "general"/CURIOSITY_GAP | Cohort keys | CODE_RULE |
| `_editorial_total` | 507 | The Director's shipped editorial total (0–50) from the script or the episode review | Lay her score beside the views (2026-10-11) | CODE_RULE |
| `story_performance` | 521 | Per snapshot: predicted hook/retention/CTA, the Director's 3-s and end estimates, measured retention/CTR/engagement, editorial total; means and the retention gap | Detect systematic optimism | CODE_RULE |
| `compute_cohort_metrics` | 617 | Groups snapshots by topic, hook or duration; means; clickbait penalty; score; sorted. Applies no minimum sample, although its docstring says it "Enforces minimum sample size threshold (N >= 3)" (`:620`); callers filter (oddity 6) | Spec cohorts (`34_…:36-46`) | CODE_RULE |
| `generate_director_recommendations` | 679 | Rules over topic and hook cohorts (see "Hard rules"); one PROPOSED per target; event `analytics.recommendation_generated` | Bounded, evidence-backed suggestions | CODE_RULE |
| `apply_director_recommendation` | 844 | Checks PROPOSED, cooldown; clones weights; clamped delta; floor 0.1; deactivates old; new version; `strategy.version_promoted`; a STRATEGY memory row | Versioned strategy with audit trail | OWNER + CODE_RULE |
| `list_channel_recommendations` | 956 | List | | |
| `create_experiment` | 967 | Inserts an ACTIVE experiment with `experiment.created` | Experiment tracking (spec 00 §29) | OWNER |
| `list_channel_experiments` | 1025 | List | | |

Events emitted: `analytics.snapshot_ingested`, `youtube.token_refresh_failed`, `youtube.analytics_refused`,
`analytics.recommendation_generated`, `strategy.version_promoted`, `experiment.created`. Tables written:
`analytics_snapshot`, `director_recommendation`, `content_strategy`, `content_experiment`, `memory_record` (via
`remember`), `owner_decision` (via `youtube_refused`). External: YouTube Analytics API through the adapter (read-only,
no cost).

### `app.analytics.trends` — backend/app/analytics/trends.py (303 lines)

"A trend is a hook, never a fact: nothing here becomes a source or a claim" (`:9`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `trends_url` | 46 | Feed URL for a geo | | |
| `parse_trends_rss` | 54 | Items by local tag name (title ≤ 200, traffic digits, ≤ 3 news, pubDate) | A namespace change does not silently empty the view (`:55-56`) | CODE_RULE |
| `fetch_trends_feed` | 100 | Pinned HTTPS to the host's public address; 200, XML and ≤ 2 MB required | Same fetch discipline as research pages (`:10-11`) | EXTERNAL + CODE_RULE |
| `refresh_trends` | 132 | Per configured country; SKIPPED when disabled; COMPLETED if at least one country answered | Owner 2026-10-11: audience countries | CONFIG |
| `geos_of` | 161 | Upper-cased unique codes | | |
| `_refresh_one` | 172 | Reads one country; `trends.unavailable` or `trends.snapshot_recorded`; keeps first 25 new titles of the day | "no trends are made up" | EXTERNAL + CODE_RULE |
| `is_fresh` | 229 | Every country read in the last 20 h | Runbook decides whether to refresh before proposals (`runbook/stages.py:358-359`) | CODE_RULE |
| `trending_now` | 244 | Last 48 h, merged across countries, sorted by traffic, top 12 (or `limit`) | Prompt and page input | CODE_RULE |
| `trends_as_text` | 288 | Romanian text list for the weekly digest | | CODE_RULE |

Helpers: `_local`, `_country_codes`. Callers: `runbook/stages.py:359`, `workflows/worker.py:381-383` (job
`trends_refresh`), `research/agent.py:353`, `runbook/weekly.py:88`, `:195`.

### `app.youtube.models` — backend/app/youtube/models.py (97 lines)

`YouTubeConnection` (`:31`): Owner label (unique), client id, redirect URI, Fernet blob `encrypted_secrets`
(client secret and refresh token; never returned), `secret_fields`, status, Google-reported identity, snapshot,
granted scopes, timestamps, `last_error`. `YouTubeOAuthState` (`:79`): random state, connection, pinned redirect URI,
expiry, `used_at`. `app.youtube.__init__` (5 lines) re-exports nothing.

### `app.youtube.router` — backend/app/youtube/router.py (242 lines)

| Function | Line | What it does | Decided by |
|---|---|---|---|
| `_page` | 67 | Plain escaped HTML page for the browser Google redirected | |
| `create_youtube_router` | 88 | Owner-only `/api/v1/youtube` routes; `_guard` (line 92) maps `YouTubeConnectionError` to 409 | OWNER |
| `get_connections` (GET `/connections`) | 99 | `list_connections` | |
| `post_connection` (POST `/connections`) | 104 | `create_connection`; "Authorises nothing and contacts nobody" | OWNER |
| `get_one` (GET `/connections/{id}`) | 119 | 404 if absent | |
| `patch_connection` (PATCH) | 126 | `update_connection` | OWNER |
| `delete_one` (DELETE) | 141 | `delete_connection` | OWNER |
| `post_authorize` (POST `/authorize`) | 149 | Consent URL | OWNER |
| `post_reconnect` (POST `/reconnect`) | 158 | Consent URL with forced consent | OWNER |
| `post_verify` (POST `/verify`) | 170 | `verify_connection` | OWNER + EXTERNAL |
| `post_disconnect` (POST `/disconnect`) | 182 | `disconnect_connection` | OWNER |
| `create_youtube_callback_router` | 196 | Public `/auth/youtube/callback` | |
| `youtube_callback` (GET) | 201 | Google `error` → 400 page; missing code/state → 400; else `complete_authorization`; page names the channel | CODE_RULE (state) + EXTERNAL |

Request models: `CreateConnection` (`:43`, `extra="forbid"`, `command_id` UUID), `UpdateConnection` (`:55`, omitted
secret means "leave it").

### `app.youtube.services` — backend/app/youtube/services.py (817 lines)

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `granted_scope_set` | 83 | Stored granted scopes, None when not recorded | "None is 'not recorded', never 'nothing granted'" (`:86-87`); read by `runbook/preflight.py:822` | EXTERNAL (as stored) |
| `scope_label` | 93 | Last part of a scope URL | Owner-facing names; `preflight.py:857` | |
| `google_refusal_words` | 123 | Google's error word and description in Romanian; `invalid_grant` explained (Testing apps' 7-day tokens) | SELL-07 | CODE_RULE |
| `_post_form` | 149 | Form POST; HTTPError → `YouTubeConnectionError(google_refusal_words)`; never logs the body | | |
| `_get_json` | 176 | Bearer GET; errors quoted up to 500 chars | | |
| `fetch_channel` | 190 | `channels.list(mine=true)`; no channel → refusal | Identity is evidence | EXTERNAL |
| `_channel_snapshot` | 208 | Keeps custom URL, description ≤ 500, country, thumbnail, uploads playlist, counts | Bounded snapshot | |
| `connection_view` | 239 | The only rendering; no branch can include a secret | | CODE_RULE |
| `list_connections` / `get_connection` | 271 / 279 | Views | | |
| `_validate_redirect_uri` | 288 | http(s), host, no query/fragment | | CODE_RULE |
| `create_connection` | 300 | Validates, encrypts the client secret, AUTH_REQUIRED, `youtube.connection_created` | | OWNER + CODE_RULE |
| `update_connection` | 349 | Edits; a new client id, or any typed client secret (even the same one, `:383-385`), drops the refresh token → AUTH_REQUIRED with a Romanian `last_error`; `youtube.connection_updated` | An old token would fail "at the worst moment" (`:362-364`) | OWNER + CODE_RULE |
| `delete_connection` | 412 | Deletes states and row; `youtube.connection_deleted` | | OWNER |
| `begin_authorization` | 437 | Stores a state; builds the consent URL (offline, include granted scopes, consent when needed); `youtube.authorization_started` | | CODE_RULE |
| `_claim_state` | 495 | Single use within its window | "the whole CSRF defence" (`youtube/models.py:85-86`) | CODE_RULE |
| `_record_failure` | 508 | ERROR + reason + event in its own transaction; card if `invalid_grant` | Failure record must survive the raise (`:513-515`) | CODE_RULE → OWNER |
| `mark_reconnect_needed` | 540 | ERROR, `youtube.token_refresh_failed` with `during: upload`, `auth_refused: True`, card (`source="publishing"`) | PUB-01, SELL-07: readers say «Reconectează» | CODE_RULE → OWNER |
| `complete_authorization` | 577 | Spend state; exchange code; reuse stored refresh token if none returned, else refuse; read channel; store token + identity + scopes together; withdraw the card; `youtube.connected` | Three transactions in a reasoned order (`:582-588`) | EXTERNAL + CODE_RULE |
| `access_token_for` | 667 | Refresh-token grant → access token | | EXTERNAL |
| `verify_connection` | 692 | Fresh token + channel re-read; CONNECTED, card withdrawn, `youtube.verified`; on failure `_record_failure` | "the only honest way to answer 'is it still connected'" | EXTERNAL |
| `disconnect_connection` | 735 | Drops token and identity locally first, then best-effort revoke at Google; `youtube.disconnected` with `revoked_at_google` | Local credential must not outlive the Owner's request (`:740-742`) | OWNER |
| `provider_for_connection` | 791 | `YouTubeProvider` with the connection's credentials and uploads playlist; refuses unless CONNECTED | Bridge to publishing (`integrations/services.py:491`) | CODE_RULE |

Events: `youtube.connection_created/_updated/_deleted`, `youtube.authorization_started/_failed`, `youtube.connected`,
`youtube.verified`, `youtube.verification_failed`, `youtube.disconnected`, `youtube.token_refresh_failed`. External:
`accounts.google.com`, `oauth2.googleapis.com` (token, revoke), `www.googleapis.com/youtube/v3/channels`.

### `app.workforce.models` — backend/app/workforce/models.py (81 lines)

`WorkforceProposal` (`:11`): type HIRE_ROLE / TERMINATE_AGENT / SUSPEND_AGENT / REASSIGN_AGENT, agent or role, Romanian
summary, `evidence_json`, `sample_size ≥ 5`, `need_score` 0..1, status, Owner notes, timestamps. `EmploymentRecord`
(`:55`): one period per row, closed with `end_reason` and the proposal. `app.workforce.__init__` (6 lines) re-exports
nothing to avoid an import cycle.

### `app.workforce.router` — backend/app/workforce/router.py (124 lines)

All routes under `/api/v1/workforce`, Owner-only (`:48`).

| Function | Line | What it does | Decided by |
|---|---|---|---|
| `create_workforce_router` | 47 | Builds the routes | |
| `get_measurements` (GET `/measurements`) | 51 | `measure_workforce` | CODE_RULE |
| `get_proposals` (GET `/proposals`) | 56 | `list_proposals`, optional status | |
| `post_generate` (POST `/proposals/generate`) | 63 | `propose_workforce_changes`; empty list is normal | CODE_RULE |
| `post_decide` (POST `/proposals/{id}/decide`) | 80 | Rejection without notes → 422; `decide_proposal(owner_decision=True)`; 403 / 409 mapping | OWNER |
| `post_employment` (POST `/employment`) | 105 | `open_employment` | OWNER |
| `get_employment` (GET `/employment/{agent_id}`) | 118 | `employment_history` | |

Commands: `DecisionCommand` (`:24`, notes ≤ 2000), `EmploymentCommand` (`:39`).

### `app.workforce.services` — backend/app/workforce/services.py (471 lines)

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `measure_workforce` | 60 | Per ACTIVE/PAUSED/SUSPENDED agent: runs by status in 30 days, failed = not SUCCEEDED (policy blocks and runs in flight included, oddity 2), failure rate (None when no runs); queue backlog (QUEUED/RETRYING), dead letters, backlog per active agent, idle agents | "Measures only; proposes nothing" | CODE_RULE |
| `propose_workforce_changes` | 129 | SUSPEND_AGENT and HIRE_ROLE proposals from thresholds; skips a target with an open proposal; `workforce.change_proposed` | D-P8-001 | CODE_RULE |
| `propose_workforce_changes.add` (inner, not in the inventory) | 148 | 38 lines: skips a (type, agent, role) that already has a PROPOSED row; writes `workforce.change_proposed` (payload type and need only), then the `WorkforceProposal` row with the evidence, sample size and need score; the DB refuses sample < 5 or need outside 0..1 | One undecided proposal per target; the evidence travels with the row | CODE_RULE |
| `list_proposals` | 260 | Ordered by need, newest | | |
| `decide_proposal` | 270 | PROPOSED only; non-Owner approval → `AutonomousChangeBlocked` (a non-Owner rejection is not refused); APPROVED/REJECTED, event, OWNER_POLICY memory; on approval `_apply` then APPLIED, all in one transaction, so an `_apply` refusal undoes the decision, its event and its memory row | The Owner decides | OWNER |
| `_apply` | 339 | SUSPEND: lifecycle SUSPENDED, runtime IDLE, `agent.suspended`; TERMINATE: TERMINATED, closes the open employment period, `agent.terminated`; HIRE/REASSIGN: raises `WorkforceError` pointing to Settings → Agents | Role and model are the Owner's choice | CODE_RULE |
| `open_employment` | 402 | New period (refused if one is open); `workforce.employment_started`; lifecycle ACTIVE from any lifecycle, `terminated_at` cleared, version bumped, no `agent.*` event | Spec 47: rehire is an event | OWNER |
| `employment_history` | 454 | Periods newest first | | |

Helpers: `_window_start`, `_public`. Data read: `Agent`, `Role`, `AgentRun`, `TaskQueueItem`, `OwnerPolicy`.
Written: `workforce_proposal`, `employment_record`, `agent` (lifecycle), `memory_record`, events.

## Connections

**Into this group**

- `backend/app/main.py`: mounts the office (`:971`), kept-frame (`:974`), analytics (`:981`), YouTube (`:983`, callback
  `:986`) and workforce (`:987`) routers; registers the stream relay (`:969`); starts `run_unreal_bridge` in the
  lifespan when Remote Control is configured (`:382-386`).
- `backend/app/runbook/stages.py`: daily `performance_intake` (`:390-445`) uses `analytics_provider_for_channel` and
  `measure_channel_publications` (`:420`, `:429`); idea stage refreshes trends when stale (`:358-359`).
- `backend/app/workflows/worker.py:381-383`: the `trends_refresh` job.
- `backend/app/research/agent.py:347-435`: trends, cohorts and the newest active strategy's topic weights into the
  Lead Researcher's prompt.
- `backend/app/agents/command.py:364-436`: `company_state` reads `channel_health`, `growth_diagnosis`, `anomalies`,
  `measure_workforce`; `backend/app/agents/director.py:525` reads `measure_workforce`.
- `backend/app/runbook/weekly.py:85-195`: `trending_now`, `trends_as_text`, `story_performance`, PROPOSED
  recommendations into the weekly review.
- `backend/app/agents/repairs/film_cost.py:122`, `:217`: `film_cost`, `video_performance`.
- `backend/app/publishing/services.py:2078-2089`: `mark_reconnect_needed` on an upload refusal.
- `backend/app/integrations/services.py:472-491`: `provider_for_connection` for the publishing provider.
- `backend/app/runbook/preflight.py:68-69`, `:822`, `:857`: `granted_scope_set`, `scope_label`.
- `scripts/bootstrap.py:91`: `seed_default_strategy`.
- Frontend (`frontend/src`): `main.js` calls `/office/weather` and `/office/presentation` (`:1126-1127`, polled
  through `hq_weather.js`), `/office/layout` (`:1411`), `/analytics/trends` (`:1972`), POST
  `/analytics/trends/refresh` (`:1989`), `/analytics/performance` (`:4110`), `/workforce/measurements` (`:5120`),
  `/workforce/proposals` (`:5141`), `/workforce/proposals/{id}/decide` (`:5202`), `/workforce/proposals/generate`
  (`:5250`); `hq_stream_config.js` `/office/stream`; `studio_frame.js` `/office/kept-frame`; `hud_charts.js`
  `/analytics/performance`; `youtube_connections.js` the YouTube routes. No page calls `/analytics/ingest`,
  `/channels/{id}/summary`, `/cohorts`, `/strategy`, `/recommendations*`, `/experiments*`, `/story-performance`,
  `/channel-health`, `/growth` or `/anomalies` (the last four reach the Director through `company_state` instead).

**Out of this group**

- `app.providers.youtube_analytics` (`YouTubeAnalyticsProvider`, `MetricsUnavailable`), `app.providers.youtube`
  (`YouTubeProvider`), `app.providers.media_http.request` (weather), `app.research.retrieval` (`resolve_public`,
  `_PinnedHTTPS` for trends), `app.integrations.vault` (encryption), `app.decisions.sources` (`youtube_refused`,
  `youtube_reconnected`), `app.agents.memory.remember`, `app.services.append_event`, `app.security`
  (`require_owner`, socket auth), `app.publishing.services.bound_connection_id`, `app.media.storage`.

**Events emitted**: `analytics.snapshot_ingested`, `analytics.recommendation_generated`, `strategy.version_promoted`,
`experiment.created`, `trends.snapshot_recorded`, `trends.unavailable`, the `youtube.*` family listed above,
`workforce.change_proposed`, `workforce.change_approved`, `workforce.change_rejected`, `workforce.employment_started`,
`agent.suspended`, `agent.terminated`. **Events consumed**: none directly; `youtube.token_refresh_failed` and
`youtube.analytics_refused` are read by the preflight (outside scope).

## Owner touchpoints

- **YouTube connections** (Settings → social): the Owner types name, client id, client secret, redirect URI;
  presses Conectează/Reconectează (consent in the Owner's browser), Verifică, Deconectează, Șterge
  (`youtube/router.py:98-191`). Google decides what is granted.
- **Reconnect cards**: raised by `_record_failure` on `invalid_grant` (`youtube/services.py:533-537`), by
  `mark_reconnect_needed` on any upload refusal (`youtube/services.py:572-574`) and by `_record_account_refusal` when
  Google refuses the account during the daily measurement, at the token refresh or the report (`auth_refused`,
  `analytics/services.py:339-348`; an unreachable Google raises no card); withdrawn by authorisation or
  verification (`youtube/services.py:646-648`, `:719-721`).
- **Channel slot binding** (Distribution → channel slots) decides which account measures a channel
  (`analytics/services.py:246-258`).
- **Workforce**: generate proposals, approve or reject (a reason is required to reject), start or restart employment
  (`workforce/router.py:62-115`). A hire or reassignment cannot be approved here: the approval answers 409 and rolls
  back (oddity 1); the Owner hires or reassigns in Settings → Agents.
- **Trends refresh button** (`frontend/src/main.js:1989` → `analytics/router.py:99-104`).
- **Analytics API-only actions with the Owner key** (no page in `frontend/src` calls them): ingest a publication,
  generate and apply strategy recommendations, create experiments (`analytics/router.py:146-246`).
- **Settings in `.env`**: `STUDIO_OFFICE_WEATHER_HOST`, `STUDIO_OFFICE_STREAM_SIGNALLING_URL`,
  `STUDIO_OFFICE_UNREAL_REMOTE_URL`, `STUDIO_OFFICE_FACADE_HEADING_DEG` (decision D1), coordinates and timezone,
  `STUDIO_TRENDS_ENABLED`, `STUDIO_TRENDS_GEO` (`backend/app/config.py:136-244`).
- **The Owner's page** sends the kept frame with the Owner key (`kept_frame.py:242-264`) and authenticates the stream
  relay socket (`stream.py:86-89`).
- **Open questions left for the Owner** (W25): whether a stranger may learn the last live-watch time from the public
  frame, whether a night frame up to 24 h old may stand on tonight's title, a per-peer socket limit if exposed beyond
  localhost (`16_DECISION_LOG.md:3998`); the Open-Meteo free tier licence is non-commercial (`weather.py:18-20`).

## Oddities and gaps

1. **A hire or reassignment approval is not recorded, although the refusal says it is.** `decide_proposal` runs inside
   `with Session(engine) as session, session.begin()` (`backend/app/workforce/services.py:285`); for HIRE_ROLE and
   REASSIGN_AGENT `_apply` raises `WorkforceError` (`:396-399`) whose text ends "Aprobarea a fost înregistrată", but the
   raise rolls back the status change, the event and the memory row, so the proposal stays PROPOSED and the Owner's
   page receives a 409 carrying that sentence (`workforce/router.py:101-102`). D-P8-001 point 8
   says "approval is recorded" (`16_DECISION_LOG.md:1667-1670`). The test only asserts the exception
   (`tests/test_phase8_workforce.py:247-256`).
2. **Every non-SUCCEEDED run counts as a failure** (`workforce/services.py:84`), which feeds the suspension
   threshold. `run_agent_task` writes an `AgentRun` row for runs that never reached a model: the policy kernel's
   refusals are recorded with `status=exc.status` (`backend/app/agents/services.py:841`), among them BLOCKED_POLICY
   when the Owner has stopped autonomy (`:621`), when the agent is not ACTIVE (`:635-639`) or already has an active
   task (`:653`), a budget refusal's own status (`:830`) and BLOCKED_PROVIDER (`:648`, `:869`); RUNNING rows in flight
   (`:911`), EMPTY_OUTPUT (`:950`), FAILED (`:966`) and ABANDONED (`:583`) count too. So a stopped studio or a busy
   agent reads as a failing employee. (NOT_CONFIGURED, cited here before, is a `ProviderRecord` status at `:1627`,
   not a run status.)
3. **TERMINATE_AGENT and REASSIGN_AGENT are never proposed** by `propose_workforce_changes` (only SUSPEND_AGENT and
   HIRE_ROLE, `workforce/services.py:187-237`); the termination path is reachable only by a row edited outside it (as the
   test does, `tests/test_phase8_workforce.py:270-272`).
4. **The `autonomous_firing_enabled` flag is not read.** `decide_proposal` loads `OwnerPolicy` and discards it
   (`workforce/services.py:295-296`); any non-Owner approval is refused unconditionally. The flag is
   `Literal[False]` in the view schema `backend/app/schemas.py:74`; the `OwnerPolicy` table
   (`backend/app/models.py:35`) has no such column, so there is nothing to read. A non-Owner *rejection*
   (`approve=False, owner_decision=False`) is not refused and is remembered as "The Owner rejected …"
   (`workforce/services.py:294`, `:317-322`); no caller does this today (the only caller is the Owner route,
   `workforce/router.py:91-98`).
5. **`open_employment` sets any lifecycle to ACTIVE** (including SUSPENDED or HIRED) and does not compare `role_id`
   with the agent's role (`workforce/services.py:440-443`). Agents seeded without an employment row have no open
   period, so `POST /workforce/employment` reactivates a suspended one; unlike `_apply` it writes no `agent.*` event
   and leaves `agent.event_id` as it was (only `workforce.employment_started`, `:419-427`).
6. **Cohorts and the strategy rules count snapshots, not films.** `compute_cohort_metrics` groups every
   `AnalyticsSnapshot` row (`analytics/services.py:623-644`) and the daily performance intake inserts a new LIFETIME
   snapshot per publication on every run (`runbook/stages.py:429` → `ingest_publication_metrics`), so one film measured
   on three days satisfies "N ≥ 3" in `generate_director_recommendations` (`:710`), in the database check, and in the
   Lead Researcher's `_signals` filter (`research/agent.py:359-361`). `get_channel_summary` sums views over all snapshots
   (`:453`) and `story_performance` emits one row per snapshot (`:540-583`), so the weekly review's
   "editorial_accuracy" means weigh a film by how often it was measured. `performance.py` deduplicates correctly
   (latest per window, `performance.py:115-122`). `compute_cohort_metrics` itself applies no minimum, although its
   docstring says it "Enforces minimum sample size threshold (N >= 3)" (`analytics/services.py:617-620`): the
   `/analytics/cohorts` route returns cohorts of one snapshot, and only `generate_director_recommendations` and
   `research/agent.py:360` filter.
7. **The duration cohort uses total watch time.** `key = "45s" if s.watch_time_seconds < 50 else "60s"`
   (`analytics/services.py:640`), while `watch_time_seconds` is `estimatedMinutesWatched × 60` across all viewers
   (`backend/app/providers/youtube_analytics.py:357`).
8. **The cohort score comment does not match the formula**: "retention (70%) + CTR (30% weighted)" over
   `mean_ret * 0.7 + mean_ctr * 1.5` (`analytics/services.py:659-660`).
9. **The strategy cooldown never applies.** `apply_director_recommendation` refuses during `cooldown_until`
   (`:875-879`), but every strategy row is written with `cooldown_until=None` (`:120`, `:908`) and nothing else sets it;
   spec 34 asks for "bounded weight changes and cooldown" (`34_CONTENT_QUALITY_ANALYTICS_OBJECTIVES.md:67-71`).
10. **Experiments are created and never advanced.** No code outside creation writes `control_count`,
    `treatment_count`, `confidence_score`, `outcome_decision` or CONCLUDED (grep of `backend/app`).
11. **The learning loop has no caller besides the Owner's API.** `generate_director_recommendations`,
    `apply_director_recommendation`, `create_experiment`, `get_channel_summary`, the cohort and strategy routes have no
    caller in `backend/app` and no page in `frontend/src`; yet the newest active strategy's `topic_weights_json` goes
    into the Lead Researcher's prompt, read with no channel filter (`research/agent.py:430-435`).
12. **The manual ingest route does not use the channel's binding.** `POST /analytics/ingest/{publication_id}` takes
    `get_analytics_provider` (`analytics/router.py:66-81`, `:153`), i.e. `from_verified_settings` without a
    connection id: the only CONNECTED row whatever the publication's channel, or environment credentials when there are
    several (`providers/youtube_analytics.py:140-160`). The decision of 2026-09-17 removed that fallback for the daily
    stage only (`16_DECISION_LOG.md:1878`).
13. **`classify` has no production caller** (only `tests/test_director_command.py:41`); `channel_health`,
    `growth_diagnosis` and `anomalies` use `diagnose` and the baseline, not the verdict.
14. **Desk assignment falls back to any role.** A desk with no role match takes the first unassigned visible agent
    (`office/services.py:324-329`), so the Unreal bridge can show that agent at another department's desk;
    `unassigned_count` is always 0 (`:393`). Agents are read with no `ORDER BY` (`:285`), so which of two agents
    matching a desk takes it follows the database's row order, and an agent whose role is missing (role name "")
    matches the first desk it is tried against (`:318-320`).
15. **`moving` is computed and never used.** `desired_states` sets `moving` (`unreal.py:120`) and it is part of the
    resend key, but `calls_for` sends the same calls for working and paused employees (`unreal.py:134-154`).
16. **The weather look is fully written and switched off** (`WEATHER_LOOK = False`, `scene_params.py:376`): the
    overcast and rain branches of `sky_plates`, `fill_factor`, `facade_factor`, `deck_sky_light`, `road` and
    `scene_params` are dead in production until a rebuild adds grey deck cells; `DRY_ROAD_ROUGHNESS` is a first
    estimate never judged on a built road (`:104-107`). The FACADE/STREET anchor curves are "calibrated on level build 3
    and must be remeasured after a rebuild" (`16_DECISION_LOG.md:3978`).
17. **The 120 s weather retry is duplicated**: `FAILURE_SECONDS = 120` (`weather.py:39`) and a literal `120.0`
    (`unreal.py:969`).
18. **The kept frame's "at most every five minutes" is the page's rule, not the server's**: no rate limit exists in
    `keep_frame` (`kept_frame.py:247-264`); the read route is public by design.
19. **Inventory gaps**: `docs/project/backend_map/inventory.json` lists 254 functions for these files but not the
    route handlers `create_kept_frame_router.read_kept_frame` (`kept_frame.py:228`) and `.keep_frame` (`:247`), the
    WebSocket handler `register_stream_gateway.office_stream_signalling` (`stream.py:81`), `_relay`'s inner
    `page_to_upstream`/`upstream_to_page` (`stream.py:111`, `:122`), or `create_youtube_router._guard`
    (`youtube/router.py:92`). It also omits eleven inner helpers (AST scan of the 25 files): the 38-line
    `propose_workforce_changes.add` (`workforce/services.py:148`, now in the workforce table), `http_sender.send`
    (`unreal.py:162`), `http_batch_sender.put`/`.send` (`unreal.py:849`, `:867`), `http_game_time_reader.read`
    (`unreal.py:895`), `sun_rotation.unit` (`scene_params.py:996`), `parse_observation.number` (`weather.py:91`),
    `Weather.from_observation.number` (`world.py:75`), `channel_baselines.med` (`performance.py:296`),
    `channel_health.total` (`performance.py:532`) and `story_performance.mean` (`analytics/services.py:585`). None of
    them calls a model.
20. **OAuth states are deleted only on delete or disconnect** (`youtube/services.py:418-420`, `:760-762`); expired
    unused rows otherwise remain until a studio reset clears `youtube_oauth_state` (`backend/app/maintenance.py:69`).
21. **Duplicate event-type constants**: `TOKEN_REFRESH_FAILED` and `ANALYTICS_REFUSED` are defined in both
    `analytics/services.py:149-153` and `youtube/services.py:79-80` (held equal by `tests/test_readiness.py:844-845`,
    per `youtube/services.py:73-78`).
22. **An unsupported analytics window answers 404.** `IngestMetricsCommand.window` is an unconstrained string
    (`analytics/schemas.py:118-119`); the adapter raises `ValueError("Unsupported analytics window …")`
    (`backend/app/providers/youtube_analytics.py:244`), which `ingest_metrics` maps to 404 like an unknown
    publication (`analytics/router.py:165-166`).
23. **Retyping the same client secret drops the refresh token.** `update_connection` sets `client_changed` for any
    non-empty `client_secret`, equal to the stored one or not (`youtube/services.py:383-385`), so the connection
    returns to AUTH_REQUIRED and needs a new consent (`:389-396`). The page omits the field unless the Owner types it
    (`youtube/router.py:60-62`).
24. **The allow-list constant is not an enforcement point.** `ENVIRONMENT_CALLS` (`unreal.py:219-232`) is never read
    by the bridge; only tests compare it with the game's `DefaultRemoteControl.ini`
    (`tests/test_remote_control_allowlist.py:83-89`, `tests/test_office_environment_bridge.py:283-286`). The real
    gate is the ini inside the Unreal project (`bAllowAnyRemoteFunctionCall=False`, 14 entries including the people
    pass's 3 calls, which are outside `ENVIRONMENT_CALLS`).
25. **The analytics router's docstring overstates the 503.** "when no analytics provider is configured these endpoints
    return HTTP 503" (`analytics/router.py:3-4`): only `POST /ingest/{publication_id}` asks for a provider; the other
    fifteen routes work from stored rows (or the trends feed) and answer normally.
26. **A film of unknown age enters the baseline but not the weekly health.** `channel_baselines` keeps a measured
    film when `(age_hours or 0) <= 90 days` (`performance.py:293`), so a publication with no parseable
    `published_at` counts as brand new; `channel_health` uses `or 1e9` (`performance.py:529-530`) and leaves the
    same film out of both seven-day windows.
