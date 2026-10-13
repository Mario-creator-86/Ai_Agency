# Employee Agent Specification

## Purpose

Make every employee predictable, replaceable, testable and observable.

## Employee template

### Identity
- Agent ID
- display name
- role
- character ID

### Technical
- provider/model
- required capabilities
- fallback
- timeout
- retry policy

### Permissions
- tools allowed
- external writes allowed?
- sensitive data access?
- provider configuration access?

### Work contract
- accepted task types
- input schema
- output schema
- evidence requirements
- success criteria

### Memory
- allowed classes
- retention
- provenance rules

### Performance
- quality metrics
- reliability
- latency
- cost
- downstream impact

## State discipline

Agent text cannot directly mutate business state.

It produces:
- recommendations;
- structured outputs;
- commands requested through allowed tool interface.

State mutations occur in backend services.

## Role examples

### Research
Allowed:
search/read sources, create evidence records.
Not allowed:
publish, hire/fire, modify budget.

### Fact Checker
Allowed:
read evidence, update claim verification through validated API.
Not allowed:
invent source, publish.

### Script Writer
Allowed:
consume verified claims, create script versions.
Not allowed:
change claim status.

### Publisher
Allowed:
publish approved artifact with configured credentials.
Not allowed:
override QC.

### Showrunner
Allowed:
read Daily Studio Log and continuity, create dramatized story assets.
Not allowed:
write fictional dialogue into operational message log.

## Fallback behavior

Fallback must preserve role contract.

If fallback model cannot comply with required schema/capability:
do not use it.

## Termination

Terminated employee:
- receives no new work;
- loses privileged tool grants;
- remains in historical queries;
- retains character/history for archives/flashbacks.

## Output validation

Every role output must be validated before downstream use:
- schema;
- required fields;
- content constraints;
- references/evidence;
- max size.

Malformed output is a failed attempt, not a valid artifact.

## Capacity

Per employee:
- max concurrent tasks;
- max daily task count if needed;
- priority class;
- expected role latency.

## Training / probation

A new employee may:
- shadow incumbent;
- run benchmark-only tasks;
- handle low-risk tasks;
before critical production.

## Communication

Employees communicate through typed message intents such as:
- REQUEST_INFO;
- REQUEST_REVIEW;
- CHALLENGE;
- HANDOFF;
- STATUS;
- ESCALATE.

This makes real disagreements inspectable without relying on free-form chatter.

## Escalation

If employee lacks:
- capability;
- evidence;
- budget;
- authority;
it should return a structured blocker rather than improvise.

## Memory scope

Role contract defines what memory classes can be read/written.

Publisher, for example, should not need research-web memory to upload an approved render.

## Removal from tool access

Termination/suspension revokes:
- new task assignment;
- privileged tool grants;
- secret access references;
before visual departure completes.


## V4 — Employee persona

Each employee may have a stable fictional persona separate from technical identity.

Possible persona data:
- birthday;
- communication style;
- likes/dislikes;
- humor;
- quirks;
- relationships.

Persona:
- affects narrative/public presentation;
- does not affect authorization;
- does not change tool capabilities;
- is versioned for continuity.

Employees may belong to dynamically created departments and report to delegated managers.
