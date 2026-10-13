# Agent Tool and Permission Matrix

## Principle

Role is not authority. Tool grants determine side-effect capability.

## Tool risk classes

- READ_PUBLIC
- READ_INTERNAL
- WRITE_INTERNAL
- EXTERNAL_READ
- EXTERNAL_WRITE
- FINANCIAL
- WORKFORCE
- WORLD_CHANGE
- CREDENTIAL_ADMIN
- POLICY_ADMIN

## Default role matrix

| Role | Public research | Internal read | Draft/write internal | External publish | Workforce | Provider config | World change |
|---|---|---|---|---|---|---|---|
| Director | Yes | Yes | Yes | Via governed command | Yes, governed | Yes, governed | Yes, governed |
| Idea | Optional | Limited | Ideas only | No | No | No | No |
| Research | Yes | Evidence scope | Evidence records | No | No | No | No |
| Fact Checker | External read | Evidence scope | Verification | No | No | No | No |
| Script Writer | No/limited | Verified content | Script versions | No | No | No | No |
| Creative Director | No/limited | Script/assets | Storyboard | No | No | No | No |
| Video/Image | Provider only | Asset plan | Assets | No | No | No | No |
| Voice | Provider only | Script | Audio | No | No | No | No |
| Editor | No | Assets | Render | No | No | No | No |
| QC | Read | Content/provenance | QC result | No | No | No | No |
| Publisher | Platform | Approved publish package | Publication state | Yes, governed | No | No | No |
| Analytics | Platform read | Analytics | Snapshots | No | No | No | No |
| Showrunner | Sanitized narrative read | Continuity | Story draft | No | No | No | No |

## Capability tokens

A task invocation should receive short-lived scoped permission/capability tokens where practical instead of broad permanent power.

## Secret minimization

An agent usually does not need raw API key text.

Tool backend owns credential and executes provider call.

## Revocation

On:
- suspension;
- termination;
- incident;
- policy change;
revoke relevant grants immediately.

## Audit

Every privileged tool call records:
- agent;
- task;
- permission;
- policy version;
- request;
- receipt/result.


## V4 role examples

### CMO
Allowed:
- create campaign;
- request approved social publishing;
- read public-safe analytics;
- assign Marketing staff.
Denied by default:
- modify hard budgets;
- access raw secrets;
- sign contracts.

### Market Intelligence
Allowed:
- public research/search;
- read our sanitized analytics.
Denied:
- publish;
- copy/download restricted competitor assets;
- modify strategy directly unless delegated.

### HR
Allowed:
- onboarding records;
- persona/culture/event proposals;
- workforce reports.
Denied:
- change provider credentials;
- bypass CEO termination policy.

### Finance
Allowed:
- read cost/revenue records;
- create budget recommendations/anomaly alerts.
Denied:
- raise Owner hard limits.

### Legal/Compliance
Allowed:
- create review/findings/holds.
Denied:
- accept legal agreements as Owner.


# V5 Financial Tool Permissions

Recommended:

| Role | Read revenue | Post ledger | Search prices | Approve budget | Virtual purchase | Financing proposal | External purchase |
|---|---:|---:|---:|---:|---:|---:|---:|
| CEO | Yes | No direct | Yes | Policy-limited | Via command | Yes | Never |
| CFO | Yes | Via controlled service | Yes | Yes | Approve only | Review | Never |
| Revenue Agent | Yes | Evidence only | No | No | No | No | Never |
| Procurement | No need | No | Yes | No | Request only | No | Never |
| VendorShop | Read approved quote | Via order service | No/limited | No | Commit after gates | No | Never |
| Asset Architect | No | No | Read selected spec | No | No | No | Never |
| Legal | Read relevant | No | Read | No | Hold/release | Review | Never |

No agent receives a generic payment-card/bank-transfer/checkout tool.
