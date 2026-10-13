# V5 Economy Architecture Audit

## Scope reviewed

The V4 organizational architecture was expanded to make economy, finance, procurement and funding first-class systems.

## Resolved design problems

### 1. Real money vs virtual money ambiguity
Resolved with three layers: External Evidence, VR Ledger, Forecast.

### 2. 1:1 currency rule
Defined `1 verified USD = 1 VR$` for eligible inflows and mirrored costs/market prices.

### 3. Forecast overspending
Forecast/pending money is explicitly non-spendable.

### 4. Duplicate platform revenue
Unique evidence/idempotency prevents double minting.

### 5. Refunds/chargebacks
Reversing entries and treasury-stress behavior added.

### 6. Purchase realism
VendorShop requires real market quote evidence, freshness, new/used condition and Finance approval.

### 7. No accidental real purchasing
No autonomous external checkout/payment tool exists in the VendorShop path.

### 8. Visual product creation
Asset Architect is downstream of an approved committed virtual purchase.

### 9. CEO infinite-money problem
Financing requires debt-capacity checks, market references, Legal/governance and creates liabilities/interest.

### 10. Owner funding
Capital contribution and Owner loan are distinct.

### 11. Finance UI
Treasury, P&L, balance sheet, cash flow, runway and 30/90/180 forecasts specified.

### 12. Story realism
Financial events can create drama, but the Showrunner cannot fabricate cash, purchases or loans.

### 13. Milestones
Views do not mint VR$ by themselves. Revenue settlement and a milestone are separate events.

### 14. Privacy
Exact VR$ may reveal real earnings; public disclosure modes added.

## Remaining implementation-time choices

- exact approved market-data/search sources;
- FX source hierarchy;
- quote TTL defaults;
- capitalization/depreciation policy;
- debt-capacity thresholds;
- payment provider for paid pitches/donations;
- public finance disclosure default.

These are configuration/policy decisions rather than missing architecture.
