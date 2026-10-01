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
- subject (added 2026-09-18: the identifier of the thing the action is about — see
  *Answering an approval, and spending it* below);
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

## Answering an approval, and spending it (built 2026-09-18)

Until 2026-09-18 this document specified the Approval object and nothing else: a SUPERVISED studio
wrote the row and there was no route by which the Owner could answer it, nothing consumed an
APPROVED row, and no act was ever re-attempted on one. The paragraphs below are what the code does
now (`app.services.request_approval`, `decide_approval`, `may_act`; migration
`0044_approval_answered`), and they are part of this specification.

**What a request identifies.** The Approval object above gains one field, `subject`: the identifier
of the thing the question is about — the media asset for an upload, the storyboard for a paid render.
A standing request is keyed by the action **and** the subject, never by the action alone, because
**one approval authorises exactly one action on exactly one thing**. Two films published to one
channel on one day are two questions; a re-rendered film is a new asset and therefore a new question,
because the Owner approved the film he was shown. An action about the studio itself rather than about
a thing carries an empty subject and has one answer by nature. The evidence is prose written for him
to read and must never be the key: it changes when the title is rewritten.

**What waiting looks like, and how it is answered.** `GET /api/v1/owner/approvals` lists what stands —
the action, the tier, the requester, the evidence, the proposed diff, the expiry and the cost, with
the cost shown as unknown wherever the studio could not compute one and never as zero.
`POST /api/v1/owner/approvals/decision` is the answer: APPROVED or REFUSED, with a word of his own if
he wants one, versioned and idempotent by command id like every other Owner command, recorded as one
ledger event carrying the previous result and the new one. A request that was already answered or has
expired is refused rather than re-answered, because a request answered twice would be two authorities
for one act. An expired request cannot be answered either, and the two writes are deliberately
separate: the decision command refuses it and leaves the row exactly as it stands, because a command
that fails must not be the thing that changes state, while the row is marked EXPIRED when the studio
next raises the same question — which is the studio's own write, not a failed answer's.

**What an approval does, and what it can never do.** It is read in one place only: inside the
authority gate, in the branch where the mode, or the Owner's own paid_media_approval for a
film's paid steps (51, 2026-09-27), would otherwise have made the studio wait for him, and
only after the stop, the Owner-only tier and SAFE_MODE have already answered. An approval therefore
converts exactly one verdict — "he would have to be asked" becomes "allowed, once". **It never turns a
hard gate's refusal into a pass**, and it cannot reach a refusal that outranks it.

**It is spent once.** The row records when its authority was consumed, and it is consumed *before* the
act it authorises is attempted, not after: an upload that then fails asks again on the next run rather
than riding on the same yes. The consumption is written to the ledger beside the decision, so the
record says the studio acted on his answer and when.

**A pending or answered approval under STOP AUTONOMY, SAFE_MODE and a policy change.**

- **STOP AUTONOMY** refuses before any answer is looked for. A pending request stays pending and an
  unspent yes stays unspent and still his: the stop pauses the studio, it does not retract what he
  decided. The same holds for **SAFE_MODE** — an incident is not him changing his mind.
- **Lowering the autonomy mode** refuses without looking for an answer either. An answer given under a
  more permissive mode must never be the way past the mode he chose to replace it with.
- **A policy-version change retracts it.** The proposed diff on the row is the state he was shown —
  for an upload, the channel and the policy version that decide who will see the film. That diff is
  compared again at the moment of spending; if any of it has moved, the answer was given about
  something else, so it is left on the record unspent and a fresh request naming the new state is
  raised. This is the reading of "gate immutability" for approvals: an approval applies to an exact
  version, never to an idea.
- **Expiry** governs all three states with one clock: how long an unanswered question stands, how long
  a refusal stops the studio asking the same question again, and how long a yes can still be spent.

**A refusal is a decision, not a block.** When the Owner says no, the work was done and the answer was
no; the act is recorded as completed-and-refused, with his reason, and the content keeps whatever
verdict the quality gates gave it — he refused sending it out, not the film. A question still standing
is recorded as the studio having skipped the act, with the request's identifier, so the two can never
be read as the same thing.

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
