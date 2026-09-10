# Phase 11 — Financial evidence and the VR$ ledger — 2026-09-10

## What was built

The economy's foundation: real-world financial evidence, and immutable double-entry virtual books
posted from it. Implemented against `../architecture/66_VIRTUAL_REAL_ECONOMY_ENGINE.md` and
`../architecture/58_FINANCE_ACCOUNTING_FINOPS.md`; the acceptance criteria it targets are the
first four bullets of `../architecture/26_MASTER_ACCEPTANCE_CRITERIA.md` §"V5 Economy".

- `backend/app/economy/models.py` — `LedgerAccount`, `LedgerTransaction`, `LedgerEntry`,
  `RevenueEvidence`, `ProviderCostRecord`, `OwnerFundingEvent`, `FXSnapshot`.
- `backend/app/economy/services.py` — the chart of accounts, minting, reversal, Owner funding,
  provider costs, the treasury projection and the trial balance.
- `backend/app/economy/router.py` — eleven Owner-only routes under `/api/v1/economy`.
- `backend/migrations/versions/0016_phase11_economy.py` — seven additive tables.
- `frontend` — a **Trezorerie** panel in the office toolbar.
- `scripts/demo_treasury.py` — walks a full economic cycle against an isolated studio
  (`--empty` starts one with nothing recorded, for driving the UI by hand).
- `scripts/verify_funding_form.mjs` — drives the Owner funding form in a real browser.

## The four invariants, and where each is enforced

| Invariant | Enforced by |
|---|---|
| One verified dollar becomes exactly one VR$, once | `uq_evidence_reference` on `(source, external_reference)`, plus `minted_transaction_id` being stamped on the row at mint time |
| Forecasts and pending payouts are never spendable | Only `SETTLED` evidence can mint; unsettled rows never reach the ledger, and the treasury view reports them in a separate, labelled block |
| A reversal posts, never deletes | `reverse_transaction` mirrors every line into a new transaction pointing at the original; `uq_reversal_once` means a transaction is reversed at most once |
| The books always balance | `post_transaction` refuses an unbalanced or one-sided set of lines before writing anything; `ck_entry_one_sided` refuses a malformed line even on a direct write; `trial_balance` re-adds every stored line |

Three further rules fall out of the same design:

- **Money is never a float.** Amounts are integer micros (1 VR$ = 1 000 000), parsed from strings,
  so a cent is exact and the ledger cannot drift.
- **FX is never invented.** A non-USD amount without a recorded `FXSnapshot` is refused, and the
  snapshot that justified a conversion is pinned to the row.
- **Costs are mirrored too.** A billed provider invoice debits Provider & Cloud Expense and
  credits VR Cash, so the treasury shows the cost of running the studio and can go into deficit.

## Decisions taken here

The architecture audit left several choices to implementation time. What was chosen, and why:

- **Micros, not cents.** Provider usage is billed in fractions of a cent; cents would round it away.
- **Only settled revenue and only billed costs post.** Symmetric, and it keeps the ledger a record
  of what happened rather than of what is expected.
- **Estimates are reported, not accrued.** Accrual with later true-up is defensible accounting but
  adds a correction path with no reader yet; the estimate is shown beside the books instead.
- **A deficit is reported, not blocked.** Nothing spends VR$ yet, so a spending freeze would have
  nothing to stop. `in_deficit` states the fact; enforcement belongs with procurement in Phase 13.
- **No `command_id` idempotency table.** The unique evidence and invoice references already make
  the money-creating operations idempotent, which is the property that matters.

## Verification

- `uv run pytest`: **338 passed, 6 skipped** (skips are ffmpeg and real-Ollama, both absent here).
  31 of those are new, in `tests/test_phase11_economy.py`.
- `uv run ruff check backend tests scripts`: clean. `uv run mypy`: clean, 93 files.
- `npm run check`, `npm run build`, `npm test --prefix frontend`: clean, 43 frontend tests.
- `uv run python scripts/check_docs.py`: inventory and architecture hashes verified.
- End-to-end through the real HTTP API against an isolated studio
  (`uv run python scripts/demo_treasury.py`): a pending payout settled and minted, a euro
  sponsorship converted at a recorded rate, an Owner contribution and an Owner loan, a billed
  provider invoice and an unbilled estimate. Result: **4055.82 VR$ spendable**, debits
  4492.62 = credits 4492.62, 900 VR$ forecast and 46.10 VR$ unbilled both reported and
  non-spendable. Screenshot: `output/playwright/treasury-panel.png`.

The demo deliberately uses a throwaway database. Recording invented payouts in the Owner's real
books and reversing them afterwards would still leave fabricated history in an append-only audit
trail, which is the exact failure this phase exists to prevent.

## Owner funding from the interface

The Trezorerie panel carries the one form an Owner needs to put money in, because that is the
only economic action that starts with a person rather than with evidence from outside.

- **Two kinds, never blurred.** A contribution credits Owner Capital and is refused a rate; a
  loan credits Debt Principal and requires both a rate and a maturity. The form shows only the
  fields the chosen kind may carry, mirroring what the service enforces.
- **The rate is entered as a percentage** because that is how people think about it, and
  converted to the basis points the ledger stores. 7.25 becomes 725.
- **A comma is refused, not guessed.** "1,000" is a thousand to one reader and one to another;
  for money the form asks again rather than choosing.
- **A foreign amount records its rate first.** Choosing a currency other than USD reveals a rate
  and a source field; the form records the FX snapshot and then cites it on the funding, so the
  "never invent a rate" rule holds from the interface as well as from the API.

Verified in a browser against an isolated, empty studio
(`node scripts/verify_funding_form.mjs <port> <token>`): the comma refusal, the loan without a
maturity refusal, the euro-without-a-rate and rate-without-a-source refusals, then a 2000 USD
loan at 7.25% and a 500 EUR contribution at 1.08, giving 2540 VR$ spendable with 2000 VR$ of debt
and a balanced ledger. Screenshot: `output/playwright/funding-form.png`.

## What Phase 11 does not do

- **Nothing spends VR$.** There is no procurement, no purchase, no checkout and no payment route
  anywhere in the API; a test asserts that over the whole OpenAPI surface.
- **No interest accrues.** `Accrued Interest` and `Interest Expense` exist in the chart of
  accounts, and a loan's rate and maturity are stored, but nothing computes interest yet, so a
  debt stays at its principal. Accrual is Phase 14.
- **No revenue arrives on its own.** Every figure is Owner-entered evidence. There is no YouTube
  payout importer, and analytics do not mint.
- **No budgets, runway, P&L, balance sheet or forecast scenarios.** That is Phase 12, which the
  treasury projection here is built to feed.
- **No depreciation.** Fixed asset and depreciation accounts exist and are unused until Phase 13
  capitalises a purchase.

`treasury` is therefore reported as `PARTIAL` in the snapshot module map, and `procurement` and
`financing` remain `NOT_IMPLEMENTED`.
