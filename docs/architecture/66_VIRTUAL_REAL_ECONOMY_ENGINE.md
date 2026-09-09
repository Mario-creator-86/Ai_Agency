# Virtual ↔ Real Economy Engine

## Purpose

Create a financially constrained virtual company whose unit of account `VR$` is anchored to real USD evidence and real market prices without giving the autonomous studio authority to spend real-world money.

## 1:1 rule

- `$1 settled/confirmed eligible inflow` → `+1 VR$`.
- `$1 actual external operating cost` → `-1 VR$` or corresponding expense/reserve posting.
- `$1 selected market price for virtual procurement` → `1 VR$ purchase cost`.

## What 1:1 does NOT mean

It does not mean:
- the application has a bank account;
- a VR$ purchase moves real money;
- a virtual loan is a real credit facility;
- forecast revenue can be spent;
- the public VR$ balance necessarily equals a real bank balance after virtual-world spending.

## Money classes

### VERIFIED_EXTERNAL
Settled or Owner-confirmed evidence.

### PENDING_EXTERNAL
Earned/expected but not settled.

### FORECAST
Probabilistic future estimate.

### VR_CASH
Spendable in-world treasury.

### VR_RESTRICTED
Reserved for obligations/contingencies.

### VR_RECEIVABLE
Tracked but non-spendable unless a financing policy explicitly advances against it.

### VR_DEBT
Virtual liability.

## Minting eligibility

Minting is a controlled ledger event, not an LLM action.

Eligibility generally requires:
- verified source;
- settled state or Owner-confirmed funding;
- unique external transaction/reference;
- currency normalization;
- not previously minted;
- no compliance hold.

## Reversals

Never delete a prior transaction.
Post a reversing transaction.

If a chargeback creates insufficient VR$:
- treasury may go into deficit/stress;
- spending freeze may activate;
- CEO receives remediation options.

## Multi-currency

Keep:
- original amount;
- original currency;
- FX source;
- FX timestamp;
- converted USD/VR$ value.

Do not fabricate FX rates.

## Accounting method

Use immutable double-entry ledger mechanics.

At minimum create accounts for:
- VR Cash;
- Restricted Cash;
- Receivables;
- Revenue by source;
- Provider/Cloud Expense;
- Marketing Expense;
- Virtual Procurement Expense/Asset;
- Fixed Assets;
- Depreciation;
- Debt Principal;
- Interest Expense;
- Owner Capital;
- Retained Earnings.

## Virtual assets

Market-priced office purchases may be capitalized or expensed according to internal configurable management rules.

The system can support depreciation for realism, but these are virtual management books, not statutory accounting.

## Reconciliation

Daily/periodic reconciliation compares:
- platform estimate vs payout;
- provider estimated usage vs invoice;
- payment intent vs settled donation;
- sponsorship invoice vs receipt;
- refund/chargeback events.

## Public representation

All UI must label whether numbers are:
- VERIFIED;
- PENDING;
- FORECAST;
- VR VIRTUAL.

Never present VR financial statements as legally filed accounts.
