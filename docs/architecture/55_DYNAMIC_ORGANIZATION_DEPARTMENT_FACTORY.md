# Dynamic Organization & Department Factory

## Goal

Allow the company to evolve organizationally as workload, channels, risk and revenue grow.

The Director/CEO must not be constrained to a fixed list of employees or departments.

## Organizational hierarchy

1. Human Owner
2. Owner Policy Kernel / hard gates
3. Director / CEO
4. Department Heads / delegated managers
5. Team Leads if created
6. Employee Agents

Delegation never grants authority beyond the delegator's policy envelope.

## Department entity

A Department must have:
- department_id;
- name;
- purpose / charter;
- lifecycle status;
- manager_agent_id;
- parent_department_id optional;
- budget envelope;
- permitted task categories;
- required capabilities;
- KPIs;
- staffing plan;
- office room/zone;
- creation reason;
- created_by;
- created_at;
- review date.

Lifecycle:
- PROPOSED
- TRIAL
- ACTIVE
- UNDER_REVIEW
- MERGING
- DISSOLVING
- DISSOLVED
- ARCHIVED

## Department creation

The CEO may create a department when a verified organizational need exists.

Triggers can include:
- sustained task backlog;
- high error/risk rate;
- growth in channels;
- new platform;
- new legal/compliance exposure;
- rising marketing workload;
- too many direct reports;
- cost control complexity;
- competitor intelligence need;
- sponsor/advertising revenue;
- security incidents;
- Owner instruction.

Creation flow:
1. Need assessment.
2. Department Charter.
3. Expected benefit.
4. Staffing proposal.
5. Budget/cost estimate.
6. Authority/permission design.
7. Duplication check against existing teams.
8. Trial-vs-permanent decision.
9. Approval according to governance tier.
10. Department transaction.
11. Manager/staff assignment.
12. Office zone/room assignment.
13. Events emitted.
14. Review after configured period.

## Anti-bureaucracy rule

The Director must not create departments merely because it can.

Every department carries:
- monetary cost;
- model/token cost;
- coordination overhead;
- latency cost;
- management complexity.

Create a `CoordinationOverhead` / `OrgComplexity` metric.

Before adding a new team, compare:
- create department;
- add specialist inside existing department;
- reassign work;
- automate tool;
- merge responsibilities;
- outsource to existing provider/tool.

## Department dissolution / merger

CEO can:
- merge departments;
- move roles;
- dissolve redundant teams;
- reduce headcount;
- archive a department.

Historical story continuity remains.

## Example growth path

Early:
- CEO
- Content/Production
- minimal Marketing

Growth:
- Marketing becomes full department.
- Market Intelligence added.
- HR/People Ops added after workforce threshold.
- Finance/FinOps added as spend/revenue complexity rises.
- Legal/Compliance added as publishing, sponsors and IP grow.
- Advertising/Paid Media splits from Marketing when spend justifies it.

These are not mandatory thresholds; they are configurable evidence-based triggers.

## Delegated managers

A Department Head has:
- charter;
- budget;
- staffing cap;
- permitted tools;
- allowed task types;
- approval limits.

Example:
CMO may create social campaigns but cannot change YouTube OAuth scopes or exceed paid-media budget.

## Organizational events

Department changes are real backend historical events:
- department.created
- department.manager_assigned
- department.staff_added
- department.staff_removed
- department.merged
- department.dissolved

They may become Office Serial story candidates.

## Office integration

When a new department is created:
- initially assign an open-plan zone if no room exists;
- World Builder may propose a dedicated room;
- room creation requires budget/world validation;
- UI reflects only committed org/world state.
