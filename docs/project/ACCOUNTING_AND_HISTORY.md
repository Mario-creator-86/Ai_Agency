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

- `may_spend(usd)` — before the media stage renders anything (runbook §8 "reserve budget";
  §7 before the 2026-09-18 renumbering); an exceeded budget refuses even what it cannot
  value.
- `record_render_costs(job)` — after every render, each scene's narration at the stored
  per-character price of the model that voiced it, referenced `render:{job}:scene:{n}` so a
  re-run charges once.
- `reconcile_day()` — the Accountant's close, first thing in `post_run` (§11 "reconcile
  cost"; §10 before the 2026-09-18 renumbering), before the Director reads her inbox. The figures are computed from the books; the
  Accountant's structured report (summary, recommendations, holds, continue or not) is
  validated before it is stored. A budget past its warning line or exceeded is an ESCALATE
  whatever the report says; an exceeded one is marked for the Owner.

`GET /economy/budget` and `GET /economy/books/daily` expose the figures;
`POST /economy/books/close` asks for the close on demand.

## Prices, and money held while it is being spent (migration 0039) — 2026-09-18

Spend was measured only from what had already been recorded, and usage on a model with no stored
price stayed unpriced for ever, because there was nowhere for a price to be stored. Two tables
answer that, and neither invents a figure.

`provider_price` — what one unit of a provider's resource costs, in integer micros: one active row
per `(provider_kind, resource, unit)`, versioned, so a new price keeps the old one and the books
can still say what a token cost on a past day. `resource` is the model id the adapter reports;
`"*"` prices every model of a kind that has no row of its own. A price is the Owner's —
`PUT /economy/prices`, Owner-only, idempotent by command id — and every row records where it came
from: OWNER when he typed it, DOCUMENTED for the one figure `seed_documented_prices` writes
(ElevenLabs' public Creator-plan price, 0.22 USD per 1 000 characters, noted as the public list and
not his invoice; `scripts/bootstrap.py` calls the seed), QUOTED for what a vendor offered and
BILLED for what a vendor charged. The seed never overrides a row of any provenance, and Ollama
Cloud is deliberately absent: its price is the plan he bought, and a guess in the books is worse
than the gap the Accountant reports as unpriced runs. The ElevenLabs, Ollama and configured-LLM
adapters are built with this table, so an employee's run and a narration now carry a cost row;
where the price is missing, or only half of it is known, the adapter answers None and never zero.

`spend_reservation` — a sum held against the period's budget while a film is being made. Before a
frame exists the media stage prices the plan (`estimate_film_cost_micros`: the motion at the
ceiling that render will be given, the narration at the dearest active per-thousand price over the
storyboard's own voiceover) and `reserve_spend` writes a RESERVED row behind the write lock, so two
films started together cannot both fit on the last ten dollars. The row ends SETTLED once the real
cost rows for that render are written, or RELEASED on every path where the film was not made — the
Owner's stop between two scenes, an encoder that cannot run, a vendor's refusal, which is costed
first — and the watchdog releases a hold older than six hours, left by a process that died under
it. `spend_since` reports it as `reserved_usd`, beside what was spent and never inside it, and
every budget check counts spent plus held against the limit: the percentage the Owner reads is of
money committed, not only of money gone. `may_spend(usd)` stays what it always was, a reading;
`reserve_spend` is the decision, and a refusal by it brings the Accountant's letter to the Owner
the same day, once.

## Remaining limitations

- Only narration is priced automatically, and only where research stored a per-character
  price on the model. Image and video generation, and language-model runs, are counted as
  unpriced usage until a price is recorded on the resource. (Corrected 2026-09-18:
  language-model runs and narration are priced from `provider_price`, because the adapters
  are now built with that table; image and video generation still are not. A model the Owner
  has not priced is still counted as unpriced usage and reported as `unpriced_agent_runs` —
  the books say the total is lower than the real spend rather than presenting it as
  complete.)
- Costs are estimates until the Owner records the provider's invoice as BILLED; the Accountant
  reports the gap but cannot fetch invoices.
- Analytics measures through the first bound channel; per-channel measurement is not split.
  (Corrected 2026-09-18: untrue since Phase B/C — `measure_channel_publications` measures one
  channel through the adapter built for that channel, and asks only about that channel's own
  PUBLISHED rows carrying a remote video id. A channel whose slot is unbound is still not
  measured at all, and the preflight names that as the missing step.)
