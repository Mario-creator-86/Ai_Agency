# UI ↔ Backend State Mapping

## Principle

Frontend animation is derived from authoritative state.

## Agent examples

| Backend runtime state | UI behavior |
|---|---|
| IDLE | idle at assigned location |
| THINKING | thinking indicator; real run active |
| WORKING | work animation at relevant desk/zone |
| COMMUNICATING | bubble/message animation from actual Message |
| WAITING_TOOL | waiting indicator + tool name |
| WAITING_EXTERNAL | external-provider wait indicator |
| RETRYING | retry indicator and next retry time |
| BLOCKED | blocked badge + actionable reason |
| ERROR | error state |
| PAUSED lifecycle | paused badge/no new work |
| TERMINATED lifecycle | departure/archive sequence after commit |

## Content

Backend stage controls project-token location.

Presentation may animate movement between zones, but latest status label updates immediately.

## Director decisions

- recommendation only → thought/recommendation panel;
- approval requested → pending approval;
- command executing → attempting;
- committed → result animation.

No visual hire/fire before commit.

## Provider

Backend health and suitability are shown separately.

Example:
API HEALTHY + Script Role UNSUITABLE.

## Replay

Historical playback uses event timestamp and "REPLAY" watermark.

It never masquerades as live office state.

## Animation failure

If an animation asset fails:
- fallback static representation;
- operational state remains visible.

Frontend cosmetic failure must not alter backend task state.

## Debug invariant

Developer overlay can query current backend entity version and compare with UI projection.


## V4 mappings

- `department.created` → new zone/room/label appears only after commit.
- `campaign.*` → Marketing agents animate according to real campaign task.
- `company_event.started` → participants show OFFSITE/COMPANY_EVENT.
- `compliance.hold_created` → affected content visibly blocked.
- `finance.anomaly_detected` → Finance/CFO alert state.
- `market.signal_created` → Intelligence team task/result visual.
- `persona.versioned` → safe visual/persona changes only after persisted update.

No UI-only "team building", "birthday" or "new department" state.


# V5 Financial UI Mapping

Backend event → UI example:
- `revenue.settled` → Treasury receipt animation / Finance notification.
- `vr.minted` → VR$ balance update only after ledger commit.
- `procurement.quote_added` → Procurement desk receives quote card.
- `procurement.finance_approved` → CFO approval state.
- `procurement.virtual_purchase_committed` → VendorShop sale animation.
- `asset_architect.requested` → Architect starts building.
- `office_asset.delivered` → object appears/delivery animation.
- `financing.requested` → CEO/CFO finance meeting state.
- `financing.approved` → debt/VR$ dashboard update.
- `treasury.freeze_enabled` → clear office-wide spending freeze banner.

UI must never animate money receipt, purchase, or loan approval before the corresponding committed backend event.
