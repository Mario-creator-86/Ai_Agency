# Revenue, Monetization & Cash Reconciliation

## Revenue source abstraction

Every monetization mechanism implements or maps to a `RevenueSource`.

Possible sources:
- YouTube;
- TikTok;
- Facebook/Instagram/Meta;
- Telegram;
- donations/tips;
- paid idea submissions;
- paid insights to CEO;
- memberships/subscriptions;
- sponsorships;
- affiliate income;
- merch later;
- licensing later.

## Platform limitations

Do not assume monetization availability or API access.
Each adapter reports:
- configured?;
- revenue data supported?;
- estimate supported?;
- payout/settlement supported?;
- manual import required?;
- region/account limitation.

## Paid idea / insight model

Potential audience flow:
1. fan submits idea/insight;
2. payment processor settles payment if enabled;
3. moderation/Legal rules apply;
4. RevenueEvidence is created;
5. settled amount mints VR$;
6. idea enters CEO/marketing/research queue.

Payment buys the defined service (e.g. review), not automatic acceptance.

## Revenue statuses

- ESTIMATE
- RECEIVABLE
- PENDING_PAYOUT
- SETTLED
- REFUNDED
- CHARGEDBACK
- DISPUTED

Only policy-eligible settlement states create spendable VR$.

## Settlement reconciliation

Use external transaction IDs where possible.

Reconcile:
- estimates to final settlement;
- platform fees;
- payment processor fees;
- refund/chargeback;
- withholding if reported;
- original currency;
- settlement date.

## Actual costs

Paid AI/provider usage is attributed to:
- agent;
- department;
- content item;
- channel;
- campaign;
- failed/reworked task.

Estimated cost is reconciled to provider invoice data when available.

## Revenue concentration

Finance should expose dependence on a single platform.
Example:
YouTube = 85% of trailing settled revenue → concentration risk warning.

## Story/marketing

Marketing can celebrate verified milestones, but must distinguish:
- views;
- estimated earnings;
- settled earnings.


## Gross vs net rule

Where trustworthy data exposes gross payment and fees separately:
- post gross revenue at 1:1 VR$;
- post processor/platform fee as a separate 1:1 VR$ expense;
- net treasury effect equals actual economics.

Example:
Fan pays $5.00; processor fee = $0.45.
- +5.00 VR$ revenue
- -0.45 VR$ payment-processing expense
- +4.55 VR$ net treasury effect.

If only a verified net settlement is available, post the net amount with basis `NET_SETTLEMENT_ONLY` and do not invent the missing gross/fee split.
