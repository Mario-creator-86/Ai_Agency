# The Accountant, the budget, and what every employee remembers saying — 2026-09-11

Owner brief: the speech bubble must show the whole answer, slowly enough to read, without
growing; every agent needs a history (what it was asked, what it answered, what it decided
and why) and a live chat that shows that history; and once the studio spends real money,
someone has to keep the books — an Accountant, complete with bible, contract and memory,
integrated into the pipeline so that spending stays under control. The Commons room becomes
Accounting.

## The bubble reads the whole answer

`frontend/src/speech_bubble.js`. The bubble keeps its size (three lines of twenty-four
characters). The answer is wrapped into pages; each page types out at 26 characters a second,
holds 1.9 s, then the next page follows, with a `2/5` counter in the corner. The bubble stays
up exactly as long as reading takes (`bubbleDurationMs`), at most twelve pages — beyond that
the answer is in the chat. The event payload carries up to 1 200 characters instead of 200.
Pure functions, tested in `frontend/tests/speech_bubble.test.js`.

## History and chat

`GET /agents/{id}/history` merges three records that already existed into one timeline,
newest first: every run (what was asked, what was answered, model, tokens, how many memories
were used), every typed message the employee sent or received, and every memory record it
wrote — an `AGENT_OPINION` is a decision and its reason. Nothing new is logged; the timeline
is the audit trail read back.

`POST /agents/{id}/chat` puts the Owner's question to the employee through the same policy
kernel and identity as any task (`task_type: owner_chat`), so the answer comes in the
employee's voice, from its contract and memory, in the language of the question, and the
exchange lands in the same history. The Agent Inspector's "Rulează o sarcină" became this
chat, with the timeline above the input.

## The Accountant

**Nadia (Accountant)**, role `Accountant`, seeded like the other seven: a work contract in
`config/role_contracts.json` (watch every charge and every budget, investigate a day far
above the average or a reference that repeats, hold spend at the warning line, never let a
day continue past an exceeded budget, never report a number that is not in the books), a
Character Bible entry (plum blouse, tortoiseshell glasses, the green ledger; "That figure is
not in the books."), and memory scope. She sits in **Accounting & Treasury** on the ground
floor, where the Coffee Lounge was; the office renderer's `FINANCE` zone replaces `LOUNGE`.

A studio that was staffed before the role existed gets her through
`seed_missing_workforce()`: the role is created from the seed's own definition and the hire
runs on the seed's model if it exists, otherwise on the Director's, so she can work today.
Idempotent; every hire is an event.

## The budget (migration 0024)

`spending_budget`: one active limit per period (DAILY, MONTHLY) in USD micros, set by the
Owner in Trezorerie → Buget și cheltuieli or `PUT /economy/budget`; a new limit replaces the
previous one and keeps it. Spend is measured from `provider_cost_record`, ESTIMATED and
BILLED alike — an estimate is a commitment already made. Usage the books cannot price (a
model with no stored price) is counted and reported as unpriced, never as free.

- `may_spend(usd)` — before the media stage renders anything (runbook §7 "reserve budget");
  an exceeded budget refuses even what it cannot value.
- `record_render_costs(job)` — after every render, each scene's narration at the stored
  per-character price of the model that voiced it, referenced `render:{job}:scene:{n}` so a
  re-run charges once.
- `reconcile_day()` — the Accountant's close, first thing in `post_run` (§10 "reconcile
  cost"), before the Director reads her inbox. The figures are computed from the books; the
  Accountant's structured report (summary, recommendations, holds, continue or not) is
  validated before it is stored. A budget past its warning line or exceeded is an ESCALATE
  whatever the report says; an exceeded one is marked for the Owner.

`GET /economy/budget` and `GET /economy/books/daily` expose the figures;
`POST /economy/books/close` asks for the close on demand.

## Remaining limitations

- Only narration is priced automatically, and only where research stored a per-character
  price on the model. Image and video generation, and language-model runs, are counted as
  unpriced usage until a price is recorded on the resource.
- Costs are estimates until the Owner records the provider's invoice as BILLED; the Accountant
  reports the gap but cannot fetch invoices.
- Analytics measures through the first bound channel; per-channel measurement is not split.
