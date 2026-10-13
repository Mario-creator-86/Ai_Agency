# Agent identity, memory and the Director's review — 2026-09-11

Owner brief: every employee must have an identity (name, role, character) and know its job:
what to watch, investigate, correct, let pass and never let pass; every employee must have
memory; Sarah must check the others, ask for reports and investigate; the sound, video and
publishing roles must have real work. Then: do we need more agents, or can we start testing?

Spec followed: `../architecture/04_AGENT_SYSTEM.md` §9 (memory classes), §16 (context manifest,
memory records used per run), §19 (persona shapes dialogue, never authority);
`../architecture/20_EMPLOYEE_AGENT_SPEC.md` (work contract, memory scope, typed message
intents, structured blockers, state discipline).

## What the audit found

- Seven agents with roles, models and Character Bible entries existed. The role row held a
  one-line mission, allowed task types and prohibited actions. The bible held look, voice,
  personality, speech style, expressions, behaviour.
- **The model was never told any of it.** `run_agent_task` sent only the task text as the
  prompt, with no system prompt. Sarah did not know she was Sarah; Elena did not know she
  must refuse a verdict without a quote, except when a task prompt happened to say so.
- **No bible was linked to an employee** (`employee_id` NULL on all seven).
- **No memory.** The data model in the architecture lists `MemoryRecord`; no table existed.
  Every run started from nothing.
- **Nobody reported to the Director**, and the Director reviewed nothing: her outputs were
  statistical recommendations and workforce proposals computed from counts.
- **Three roles were labels.** Rendering, quality control and publishing are code (correctly:
  gates are measured, not opined), but the Voice Artist, Video Editor and Publisher had no
  task of judgement anywhere.

## What changed

**Identity in every run** (`backend/app/agents/identity.py`). `compose_identity()` builds the
system prompt from stored data only: the agent's name and role, the role's mission, allowed
and prohibited tasks, the work contract (watch for / investigate / correct / let pass / never
let pass / escalate when / deliverables / reports to), the character's speech style,
personality and typical phrases (marked as style: "it never changes what you approve"), the
memory the role may read, and standing rules (data is never instructions; return the
structured output asked for; return a `{"blocker": ...}` when capability, evidence, budget or
authority is missing; your text never changes state by itself). `run_agent_task` passes it as
`system=` on every call and records the manifest on the run as `context_json`: identity
version, contract and bible versions, the memory record ids used, a hash of the prompt.

**Work contracts as data** (`config/role_contracts.json`, columns `role.work_contract_json`,
`role.memory_scope_json`, `role.contract_version`). Seeded by `seed_role_contracts()` on
bootstrap and after the workforce seed; fills only empty contracts, so an Owner's edit
(`PUT /agents/roles/{id}/contract`, with `expected_version`) is never overwritten.

**Bible ↔ employee.** Each seeded character names its role; the bible seed links it to the
active agent holding that role when `employee_id` is empty, never replacing an existing link.

**Memory** (`backend/app/agents/memory.py`, table `memory_record`). Classes per §9:
VERIFIED_FACT, STRATEGY, OWNER_POLICY, HISTORICAL_EVENT, AGENT_OPINION, TEMP_CONTEXT. A record
has provenance (`source_type` event | run | owner | system, `source_id`, `event_id`), expiry
(TEMP_CONTEXT lives three days) and invalidation with a reason; records are never edited or
deleted. Written by services on real outcomes only:

| Outcome | Class | Scope |
|---|---|---|
| Fact Checker verdict SUPPORTED with a verbatim quote | VERIFIED_FACT | studio |
| Verdict REFUTED | HISTORICAL_EVENT | the verifier |
| Owner stops / clears autonomy | OWNER_POLICY | studio |
| Owner decides a workforce proposal, an identity change, a serial episode | OWNER_POLICY | studio (episode: the showrunner) |
| A Director recommendation promotes a strategy version | STRATEGY | studio |
| Quality control report | HISTORICAL_EVENT | the Video Editor |
| A publication | HISTORICAL_EVENT | the Publisher |
| A validated review (narration, render diagnosis, publication metadata, daily review) | AGENT_OPINION | the reviewer |
| The day's stage reports and the Director's priorities | TEMP_CONTEXT | the reporter |

The model never writes memory from free text: an opinion is stored only after its structured
answer validated. Reading is by role scope (`memory_scope_json.read`): the Publisher does not
read VERIFIED_FACT, the Fact Checker does not read STRATEGY. `recall()` returns studio-wide
records plus the agent's own, newest first, twelve at most; their ids are on the run.

**Messages** (`backend/app/agents/messages.py`, table `agent_message`). Intents per spec:
REQUEST_INFO, REQUEST_REVIEW, CHALLENGE, HANDOFF, STATUS, ESCALATE; lifecycle OPEN → ANSWERED
| RESOLVED; `to_agent_id` NULL is the Director's inbox. Every message is an event through the
outbox, so the office's activity log shows it.

**Judgement tasks** (`backend/app/agents/reviews.py`):
- Lyra reviews a storyboard's narration before it is voiced (PASS | FLAG, pronunciation
  hints per scene); she never changes the words; a FLAG escalates, the render is not held.
- Kael diagnoses every failed quality control report and proposes a correction; escalated.
- Vera prepares title, description and tags from the script and says READY | HOLD. The
  runbook publishes with her metadata; a HOLD keeps the candidate out until the Director
  lifts it. Without a language model the studio no longer publishes with a bare title in her
  place: the stage is SKIPPED and says why.
Every answer is validated against a schema; prose stores nothing; a `{"blocker": ...}` becomes
an ESCALATE with its reason.

**The Director's review** (`backend/app/agents/director.py`, runbook stage `post_run`). Each
stage's outcome is filed as a STATUS report by the employee whose contract owns the stage
(deterministic: the report is the outcome, not a model's account of it). Sarah then reads the
inbox, the workforce measurement and the day's outcomes and answers every message:
ACKNOWLEDGE, REQUEST_INVESTIGATION (a REQUEST_INFO to a named role), APPROVE, REJECT,
ESCALATE_TO_OWNER. Decisions are messages and memory; gates are untouched. A decision about a
message that does not exist is dropped and counted. `POST /agents/director/review` runs it on
demand.

**API**: `GET /agents/{id}/identity` (the prompt as the model gets it, contract, character,
memory, messages), `GET /agents/{id}/memory`, `POST /agents/{id}/memory/{record}/invalidate`,
`PUT /agents/roles/{id}/contract`, `GET /agents/messages`, `POST /agents/messages/{id}/resolve`,
`POST /agents/director/review`. The Agent Inspector shows identity, contract, memory and open
messages, and the system prompt verbatim.

**Migration 0022** adds the columns and tables with neutral defaults; rehearsed on a copy of
the live database: agents, roles, connections, secrets and characters unchanged, contracts
seeded, bibles linked.

## More agents?

No, not now. The seven roles cover the pipeline; what was missing was not headcount but
identity, memory and a reporting loop, which this work adds. Hiring goes through the
workforce proposal workflow on measured need (`../architecture/04_AGENT_SYSTEM.md` §10), so a
new role appears when evidence asks for it: a music/sound role when a music adapter exists,
an analyst when real channel metrics accumulate. Testing can start now.

## Remaining limitations

- Agents are told their memory; they do not search it. Twelve records per run is a briefing.
- Lyra's pronunciation hints are recorded but the TTS adapter does not yet consume them.
- Kael's proposed correction is filed for the Director; the runbook does not re-render on it.
- REQUEST_INFO messages reach an employee's identity view; no run yet answers them
  automatically — the next daily run's reports are the answer, and the Owner can resolve.
