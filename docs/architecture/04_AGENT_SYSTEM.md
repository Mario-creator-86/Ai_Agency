# Agent System v3

## 1. Agent is not merely a prompt

An Agent is a managed runtime identity with:

- immutable ID;
- display identity;
- role;
- department;
- lifecycle;
- character identity;
- LLM provider/model;
- fallback route;
- capability requirements;
- allowed tools;
- denied tools;
- permissions;
- system prompt version;
- memory policy;
- cost limits;
- timeouts;
- retry policy;
- performance model;
- current assignments;
- employment history.

## 2. Role Contract

Each Role defines:
- mission;
- allowed task types;
- required input schema;
- output schema;
- required capabilities;
- tools;
- prohibited actions;
- success criteria;
- evaluation metrics.

This prevents "one model can do everything" drift.

## 3. Lifecycle

PROPOSED
CANDIDATE
HIRED
ACTIVE
PAUSED
SUSPENDED
TERMINATING
TERMINATED
ARCHIVED

## 4. Runtime states

IDLE
THINKING
WORKING
COMMUNICATING
WAITING_TOOL
WAITING_EXTERNAL
REVIEWING
RETRYING
BLOCKED
ERROR

These states drive UI animations.

## 5. Director

Director can:
- create/assign tasks;
- prioritize;
- request deeper research;
- reject ideas;
- choose production;
- compare employee performance;
- launch benchmarks;
- hire/fire subject to policy;
- change ordinary agent routing/prompts subject to policy;
- manage budgets within envelope;
- create experiments;
- change topic weights;
- propose new departments/roles;
- respond to outages.

Director cannot:
- self-escalate permissions;
- fabricate provider capability;
- obtain missing credentials;
- bypass external auth;
- declare tool success without receipts;
- silently overwrite audit history.

## 6. Initial roles

- Director / CEO
- Idea/Trend Agent
- Research Agent
- Fact Checker
- Script Writer
- Hook Specialist
- Creative Director
- Image Agent
- Video Agent
- Voice Agent
- Editor
- QC Agent
- Publisher
- Analytics
- Growth
- Showrunner
- optional History Reviewer
- optional Science Reviewer
- optional Rights/Policy Reviewer

## 7. Structured task assignment

Every assignment includes:
- task_id;
- objective;
- inputs;
- constraints;
- expected schema;
- deadline/timeout;
- cost budget;
- tools granted;
- evidence requirements;
- correlation_id.

## 8. Tool receipts

Agents must not self-report tool results as authoritative.

A tool execution returns a receipt:
- tool name;
- request ID;
- status;
- output reference;
- timestamps;
- cost;
- error;
- remote ID if any.

Agent reasoning may interpret receipts, but cannot invent them.

## 9. Memory

Memory types:
- VERIFIED_FACT
- STRATEGY
- OWNER_POLICY
- HISTORICAL_EVENT
- AGENT_OPINION
- TEMP_CONTEXT

Web text never enters VERIFIED_FACT without evidence validation.

## 10. Hiring

Need → role spec → candidates → benchmark → recommendation → approval/policy → hire transaction → character/desk assignment → event.

## 11. Firing

Termination must safely handle current work:
- block new task assignment;
- identify in-flight tasks;
- finish/cancel/reassign according to policy;
- terminate lifecycle;
- keep history.

## 12. Model change vs employee replacement

Configurable semantics:

### Same employee / model upgrade
Character remains.
Employment history continues.
Model change logged.

### New employee replacement
New Agent ID.
New CharacterIdentity.
Old employee terminated.

Director decision must explicitly choose which semantic applies.

## 13. Agent disagreements

Operational disagreements are valid only if actual agent outputs conflict.

Do not manufacture fake live conflict.

Serial Showrunner may dramatize a real disagreement later.

## 14. Performance evaluation

Role-specific scorecards.

Avoid one scalar "employee score" as sole firing basis.

Track:
- quality;
- reliability;
- cost;
- latency;
- compliance;
- downstream impact.

Director should use thresholds, windows and minimum samples.

## 15. Capability mismatch

If an assigned model lacks required capability:
- task must not start;
- status = BLOCKED_CAPABILITY;
- Director receives actionable reason;
- fallback/candidate may be selected.

## 16. Agent execution envelope

Every agent run records:
- run_id;
- task_id;
- prompt template/version;
- model/provider;
- context manifest;
- memory records used;
- tools enabled;
- start/end;
- schema validation result;
- tool receipts;
- output artifact;
- cost;
- evaluation result.

This enables reproducibility without requiring private chain-of-thought.

## 17. Context discipline

Agents receive only context required for their role.

Use:
- token budget;
- evidence selection;
- recent-task summary;
- relevant long-term memories.

Avoid dumping the complete company history into every prompt.

## 18. Communication controls

Agent-to-agent communication is structured and bounded.

Configure:
- max hops;
- max messages per task;
- max rework iterations;
- recipient allowlist by role.

Repeated unresolved disagreement becomes an escalation, not an endless discussion.

## 19. Workload / capacity

Each agent:
- max concurrent tasks;
- queue priority;
- supported task complexity;
- expected latency.

Director must not overload one "best" employee while others sit idle unless strategy justifies it.

## 20. Evaluation and probation

Newly hired agent can enter `PROBATION`.

During probation:
- limited task class;
- lower spend;
- no critical external write;
- benchmark/live shadow comparison.

Promote to ACTIVE after passing configured evaluation.

## 21. Delegation

Director may delegate coordination to manager roles in the future.

Delegated managers:
- operate within inherited policy;
- cannot exceed Director/Owner boundaries;
- must produce the same auditable commands/events.

Avoid a single Director becoming a scalability bottleneck.

## 22. Decision explanation

Expose a concise structured explanation:
- decision;
- top evidence;
- rejected alternatives;
- confidence;
- constraints.

Do not require raw private reasoning traces.


## 18. V4 Department Heads

Agents can be managers with delegated authority.

Manager contract must define:
- department;
- staffing cap;
- budget;
- commands allowed;
- approval threshold;
- task classes;
- channels/providers allowed.

Potential managers:
- CMO / Marketing Director
- Head of Market Intelligence
- Head of People / HR
- CFO / Finance Director
- Legal/Compliance Lead

CEO remains above all department heads.

## 19. Personality / Persona layer

Each employee may have a separate `NarrativePersona`.

Do not place fictional traits inside permission logic.

Persona can influence:
- public dialogue;
- serial behavior;
- office social animation;
- company events.

Persona cannot influence:
- factual gate threshold;
- security scope;
- tool authorization;
- hard budget;
- legal/policy gates.

## 20. Department creation

CEO may create:
- specialist role inside existing department;
or
- a new department.

Prefer least organizational complexity that solves the need.

## 21. Market/marketing specialization example

If Marketing needs competitor monitoring:
CEO may:
1. add Competitive Marketing Scout inside Marketing;
2. evaluate workload;
3. later create Market Intelligence Department if justified.

The architecture must support both without code rewrites.


# V5 Finance / Procurement Agents

Potential roles as the studio grows:

- CFO / Finance Director
- Treasury Analyst
- Revenue Reconciliation Agent
- Cost Accountant / FinOps Analyst
- Procurement Director
- Procurement Research Agent / Buyer
- VendorShop Manager
- Asset Architect
- Financing Analyst

Role boundaries:

**CFO** may approve/reject budget usage within policy but may not mint VR$ without an eligible source event.

**Procurement Agent** may search prices and recommend products but may not post a ledger transaction or buy externally.

**VendorShop Manager** may create a virtual sale only after quote and finance approval requirements pass.

**Asset Architect** may create visual/world assets but may not change price or purchase state.

**Treasury Analyst** may model financing terms but may not create unlimited debt or represent a virtual loan as a real bank offer.

**CEO** may initiate spending/financing requests and make policy-permitted final decisions, but financial hard gates remain independent.
