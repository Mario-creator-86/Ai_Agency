# End-to-End Economy Scenarios

These scenarios are normative examples for implementation and tests.

## Scenario A — YouTube revenue becomes VR$

1. Channel A has revenue estimate of $1,200.
2. Dashboard shows `ESTIMATED $1,200`; spendable VR$ does not change.
3. Later platform evidence confirms $1,050 settlement.
4. Evidence is deduplicated and verified.
5. Ledger posts the eligible settlement.
6. Treasury receives +1,050 VR$ (or gross/fees split if trustworthy breakdown exists).
7. CEO can now allocate it.
8. Story/marketing can mention the milestone only according to financial disclosure policy.

## Scenario B — Fan pays $5 to send an idea

1. Fan uses an Owner-enabled payment flow.
2. Idea enters `PAID_PITCH_PENDING_PAYMENT`.
3. Payment settles.
4. If gross/fee data exists:
   - +5.00 VR$ revenue;
   - -processor fee VR$ expense.
5. Idea enters moderation and then CEO review.
6. Payment does not guarantee production.
7. If chargeback occurs later, reversing entries post and treasury reacts.

## Scenario C — CEO wants a chair

1. CEO: `CreatePurchaseNeed("ergonomic chair", NEW_OR_USED)`.
2. Procurement defines dimensions/features/style.
3. Procurement searches current market listings.
4. Quotes found:
   - New Model A: $620;
   - New Model B: $490;
   - Used Model A: $330.
5. Quote source/date/condition/shipping/tax are stored.
6. CFO sees available treasury, runway and budgets.
7. CFO approves up to 350 VR$ and recommends Used Model A.
8. CEO accepts.
9. Quote is revalidated.
10. VendorShop commits a 330 VR$ virtual purchase.
11. Ledger balance decreases by 330 VR$.
12. Inventory asset is created.
13. Asset Architect creates the top-down office representation matching Used Model A specs/style constraints.
14. World Builder delivers/places the chair.
15. Daily Studio Log records the purchase and disagreement.
16. Tomorrow's serial may show: "The CEO wanted the expensive chair. Finance won."
17. No external product checkout or real payment occurred.

## Scenario D — CEO cannot afford a room upgrade

1. Room project costs 2,000 VR$ based on market-backed component estimates.
2. Treasury available = 800 VR$.
3. Finance rejects direct purchase and calculates runway.
4. CEO can:
   - postpone;
   - choose cheaper/used items;
   - increase revenue efforts;
   - request Owner capital;
   - request Owner loan;
   - propose virtual financing.
5. The rejection can become story canon.

## Scenario E — Owner injects $1,000 as capital

1. Owner records/confirms a $1,000 funding event.
2. Type = CAPITAL_CONTRIBUTION.
3. Ledger:
   - +1,000 VR$ cash;
   - +1,000 VR$ Owner equity.
4. No interest obligation.
5. The application itself does not execute the real transfer.

## Scenario F — Owner injects $1,000 as loan

1. Owner selects OWNER_LOAN.
2. Treasury researches comparable current market references if requested.
3. Proposed interest/tenor is reviewed.
4. Owner approves terms and confirms funding.
5. Ledger:
   - +1,000 VR$ cash;
   - +1,000 VR$ loan liability.
6. Interest accrues according to schedule.

## Scenario G — CEO requests virtual financing

1. Treasury stress trigger fires.
2. CEO requests 5,000 VR$ virtual financing.
3. Finance analyzes trailing settled revenue, burn, debt and forecast.
4. Market references indicate a realistic indicative range.
5. Legal reviews wording.
6. Governance approves only if debt-capacity rules pass.
7. If approved:
   - +5,000 VR$ cash;
   - +5,000 VR$ debt liability.
8. This is not revenue and not real bank borrowing.
9. Interest/debt service become future constraints.

## Scenario H — Refund after office upgrade

1. Donation revenue previously created spendable VR$.
2. Studio has already spent some of it.
3. A $100 chargeback arrives.
4. System posts -100 VR$ reversal.
5. If treasury falls below reserve threshold:
   - TREASURY_WARNING or freeze activates;
   - CEO/Finance receive remediation task.
6. History is never rewritten.

## Scenario I — Team building after 1M views

1. 1M views is a milestone but not automatically money.
2. HR proposes team building.
3. Finance checks actual VR$ treasury and market-anchored event budget.
4. CEO approves only if affordable.
5. Event spending posts in VR$.
6. Production pause becomes real workflow state.
7. Office serial covers the event.

This prevents a view milestone from magically creating cash unless a separate settled revenue event exists.
