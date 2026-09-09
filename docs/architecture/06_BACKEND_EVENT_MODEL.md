# Backend Event Model v3

## 1. Invariant

No live operational UI animation without authoritative backend state/event.

## 2. Event envelope

```json
{
  "event_id": "uuid",
  "event_type": "agent.state_changed",
  "timestamp": "ISO-8601",
  "aggregate_type": "agent",
  "aggregate_id": "uuid",
  "correlation_id": "workflow_uuid",
  "causation_id": "prior_event_uuid_or_null",
  "schema_version": 1,
  "sequence": 12345,
  "payload": {}
}
```

## 3. Commit ordering

Never emit "success" before transaction/effect verification.

Preferred:
DB transaction updates state + inserts outbox event.
Publisher later emits event.
UI receives only committed event.

## 4. Event families

### Agent
- agent.created
- agent.hired
- agent.config_changed
- agent.state_changed
- agent.message_sent
- agent.performance_updated
- agent.suspended
- agent.termination_started
- agent.terminated

### Task/workflow
- workflow.created
- workflow.started
- workflow.paused
- workflow.cancel_requested
- workflow.cancelled
- workflow.completed
- task.created
- task.assigned
- task.started
- task.waiting_external
- task.retrying
- task.completed
- task.failed
- task.blocked
- task.timed_out

### Director
- director.recommendation_created
- director.decision_created
- director.decision_approval_requested
- director.decision_approved
- director.decision_rejected
- director.decision_executed
- director.decision_failed

### Provider
- provider.configured
- provider.health_changed
- provider.capability_changed
- provider.model_discovered
- provider.rate_limited
- provider.error

### Content/evidence
- content.created
- content.stage_changed
- research.source_added
- claim.created
- claim.verified
- claim.marked_stale
- script.version_created
- storyboard.created
- media.generation_started
- media.generated
- media.generation_failed
- qc.completed

### Publishing
- publication.intent_created
- publication.started
- publication.remote_confirmed
- publication.failed
- analytics.snapshot_created

### Story
- daily_log.closed
- continuity.roster_changed
- showrunner.episode_created

### Office world
- office.room_created
- office.room_removed
- office.desk_assigned
- office.layout_changed
- office.agent_presence_changed
Future:
- office.item_purchased
- office.item_removed

## 5. UI projection rules

- Ignore duplicate event IDs.
- Reject older aggregate version/sequence when a newer one is already applied.
- Request snapshot if sequence gap is detected.
- Distinguish `attempting` from `confirmed`.

## 6. Reconnection protocol

1. Client authenticates.
2. Fetches current office projection snapshot.
3. Sends last known event sequence/cursor.
4. Server replays missed events.
5. Client resumes live stream.

## 7. Speech bubbles

Live bubble requires `agent.message_sent` or another real message event.

Decorative/fake dialogue is forbidden in live operational mode.

## 8. Traceability

UI diagnostics should allow opening the backend `event_id` that caused the visible state.

## 9. Event visibility classification

Every event should include or derive a visibility class:
- INTERNAL;
- OWNER;
- PUBLIC_SAFE;
- SECURITY_SENSITIVE.

Public projection never streams raw internal events directly.

## 10. Schema evolution

Durable events require:
- event schema version;
- upcaster/migration strategy;
- additive-change preference;
- unknown-field tolerance for readers;
- contract tests.

Never make old event history unreadable after deployment.

## 11. Aggregate versioning

For mutable aggregates store an explicit version.

Commands may include `expected_version`.

Reject stale conflicting writes cleanly.

## 12. Clock semantics

Event timestamp is server-recorded UTC.

For externally sourced timestamps, store both:
- received_at;
- source_timestamp if available.

Ordering uses sequence/version, not wall-clock alone.

## 13. Delivery semantics

Assume at-least-once delivery to projections.

Consumers must be idempotent.

Do not architect UI correctness around exactly-once message delivery.

## 14. Event retention and snapshotting

If event volume grows:
- retain audit-critical events;
- create snapshots/checkpoints;
- archive older streams safely.

Snapshots must not destroy ability to explain important historical decisions.

## 15. Public narrative references

StoryEpisode may reference internal event IDs, but public API should expose safe opaque story references unless the internal event is explicitly public-safe.


## V4 event families

### Organization
- department.proposed
- department.created
- department.manager_assigned
- department.staff_changed
- department.merged
- department.dissolved
- role.created

### Marketing
- marketing.opportunity_created
- campaign.created
- campaign.variant_created
- campaign.approved
- social.post_scheduled
- social.post_published
- social.post_failed
- marketing.metrics_updated

### Community
- community.message_received
- community.reply_created
- community.poll_created
- community.sentiment_alert

### Market Intelligence
- market.signal_created
- competitor.observation_created
- opportunity.hypothesis_created

### HR / Persona
- persona.created
- persona.versioned
- relationship.updated
- employee.probation_started
- employee.onboarding_completed

### Finance
- finance.cost_recorded
- finance.revenue_recorded
- finance.anomaly_detected

### Legal
- compliance.review_started
- compliance.review_completed
- compliance.hold_created
- compliance.hold_released

### Company Events
- company_event.proposed
- company_event.approved
- company_event.started
- company_event.completed
- milestone.reached

All UI-visible organizational/social states must originate from committed events.


# V5 Economy Events

Add event families:

### Revenue / money evidence
- revenue.evidence_received
- revenue.estimated
- revenue.pending_payout
- revenue.settled
- revenue.reversed
- owner_funding.confirmed
- external_cost.observed
- external_cost.reconciled

### VR ledger / treasury
- vr.minted
- vr.burned
- ledger.transaction_posted
- treasury.balance_changed
- treasury.reserve_created
- treasury.reserve_released
- treasury.warning
- treasury.freeze_enabled
- treasury.freeze_released

### Procurement
- procurement.need_created
- procurement.quote_added
- procurement.quote_expired
- procurement.selection_proposed
- procurement.finance_approved
- procurement.legal_approved
- procurement.virtual_purchase_committed
- inventory.asset_created
- asset_architect.requested
- asset_architect.completed
- office_asset.delivered

### Financing
- financing.requested
- financing.market_terms_collected
- financing.capacity_assessed
- financing.legal_reviewed
- financing.approved
- financing.funded_virtual
- financing.interest_accrued
- financing.payment_posted
- financing.default_risk_detected

Every financial event must include the ledger/transaction/evidence identifiers required for audit and idempotency.
