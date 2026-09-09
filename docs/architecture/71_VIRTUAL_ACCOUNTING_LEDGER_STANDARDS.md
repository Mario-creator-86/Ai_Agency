# Virtual Accounting Ledger Standards

## Objective

Make all VR$ flows reproducible, auditable and resistant to LLM hallucination.

## Double entry

Every posted transaction must balance.

Examples:

### Settled YouTube revenue $100
Debit: VR Cash 100
Credit: YouTube Revenue 100

### Virtual chair purchase 300 VR$ capitalized
Debit: Virtual Furniture Asset 300
Credit: VR Cash 300

### Provider cost 10
Debit: AI Provider Expense 10
Credit: VR Cash / Provider Payable 10

### Owner loan 1,000
Debit: VR Cash 1,000
Credit: Owner Loan Liability 1,000

### Interest accrual 10
Debit: Interest Expense 10
Credit: Accrued Interest Liability 10

## Immutable postings

Never edit posted money entries.
Corrections are new reversing/correcting transactions.

## Period close

Support daily/monthly management close:
- reconcile evidence;
- flag unresolved items;
- accrue interest;
- depreciation if enabled;
- lock/snapshot reporting period while still allowing adjustment entries.

## Asset register

Store:
- acquisition cost;
- acquisition date;
- VendorShop order;
- condition;
- department/location;
- current world object;
- depreciation policy;
- disposal/resale later.

## Tax / statutory disclaimer

This ledger is a management simulation. It must not be marketed as jurisdiction-compliant bookkeeping without separate professional validation/integration.
