# Governance and Approval Policy

## Authority hierarchy

1. Human Owner
2. Owner Policy Kernel
3. Hard gates
4. Director / CEO
5. Delegated managers
6. Employee agents

No lower layer can grant itself authority above a higher layer.

## Action risk tiers

### T0 — Read-only
Examples:
- read analytics;
- inspect provider health;
- search public sources.

May be autonomous if tool permitted.

### T1 — Reversible internal
Examples:
- create draft;
- change task priority;
- run benchmark.

Typically autonomous.

### T2 — Material internal
Examples:
- change employee model;
- change prompt;
- hire/suspend agent;
- create office room draft.

Configurable approval.

### T3 — External/financial/public
Examples:
- public publish;
- paid generation beyond threshold;
- fire employee;
- activate new provider;
- public world/story change.

Stricter policy.

### T4 — Owner-only
Examples:
- alter hard budget;
- change Policy Kernel;
- reveal/rotate certain credentials;
- accept legal terms;
- disable core audit/security protections.

Director cannot execute.

## Hard gates

A hard gate result cannot be overridden by Director prose.

Hard gates:
- autonomy;
- security;
- credential;
- capability;
- hard budget;
- factual provenance;
- rights;
- platform policy.

## Approval object

Fields:
- action;
- requester;
- risk tier;
- evidence;
- proposed diff;
- cost;
- reversibility;
- expiry;
- approver;
- result.

Expired approvals cannot be reused.

## Conflict resolution

If Director and a gate disagree:
- gate wins;
- Director may create remediation/re-review task.

If two reviewers disagree:
- escalate based on policy.

## Emergency control

P0 incident may:
- enter SAFE_MODE;
- STOP AUTONOMY;
- suspend affected provider/channel.

Only Owner or configured recovery policy can resume.

## Governance versioning

Every material autonomous action should record which PolicyVersion authorized it.


## V4 organizational risk tiers

Examples:

### T1
- create marketing draft;
- run market-intelligence scan;
- create low-risk internal persona metadata.

### T2
- hire specialist;
- create trial department;
- schedule low-cost internal company event;
- change organic marketing strategy.

### T3
- dissolve department with active staff;
- launch paid advertising;
- public cross-platform campaign;
- schedule production-stopping event;
- activate sponsor campaign.

### T4 / Owner-only where configured
- accept sponsor/legal contract;
- raise hard ad budget;
- expose private financial data;
- waive legal/compliance hard gate.

Department heads cannot self-expand their delegated scope.


# V5 Financial Governance

Suggested approval tiers:

### Tier F0 — automatic
- read revenue evidence;
- refresh forecasts;
- expire quote;
- accrue already-approved interest;
- read market prices.

### Tier F1 — Finance-controlled
- small virtual purchases within department budget;
- budget reallocations below configured threshold;
- reserves.

### Tier F2 — CEO + Finance
- material discretionary purchases;
- new room/furniture procurement;
- material department budget change.

### Tier F3 — CEO + Finance + Legal / Owner according to policy
- virtual financing;
- paid audience monetization terms;
- sponsorship financial structure;
- public financial disclosures;
- unusually large purchase or debt.

### Owner-only / forbidden-to-autonomy
- enabling real outbound payment capability;
- changing the no-real-money-spend invariant;
- connecting bank/card accounts with write authority;
- accepting a real credit agreement.

Financial hard gates cannot be bypassed by the CEO's narrative/operational authority.
