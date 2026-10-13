# Data Model v3

## Organization / world
- Owner
- Studio
- Department
- Room
- Desk
- OfficeLayoutVersion
- OfficeObject
- AgentDeskAssignment

## Workforce
- Agent
- Role
- RoleContract
- Skill
- CapabilityRequirement
- AgentCharacter
- CharacterBible
- AgentPromptVersion
- AgentToolGrant
- AgentPermission
- AgentPerformanceSnapshot
- EmploymentEvent

## Providers
- Provider
- ProviderCredentialReference
- ProviderModel
- ProviderCapability
- ProviderHealthSnapshot
- ProviderRateLimitState
- ProviderBenchmark
- BenchmarkRun

## Workflows
- Workflow
- WorkflowStep
- Task
- TaskAttempt
- TaskLease
- IdempotencyRecord
- CancellationRequest
- ScheduledJob
- RetryRecord
- CostReservation
- CostRecord

## Events / commands
- CommandRecord
- Event
- OutboxRecord
- Message
- Approval
- AuditLog

## Research
- Source
- SourceSnapshot
- Claim
- ClaimEvidence
- ResearchRecord
- VerificationRecord

## Content/media
- ContentItem
- Idea
- ScriptVersion
- HookVersion
- Storyboard
- Scene
- Asset
- AssetRights
- AudioAsset
- VideoAsset
- Render
- QCResult

## Publishing
- Channel
- PublicationIntent
- Publication
- PublicationAttempt
- AnalyticsSnapshot

## Strategy
- Strategy
- StrategyVersion
- Experiment
- ExperimentVariant
- Recommendation
- DirectorDecision

## Story
- DailyStudioLog
- ContinuityState
- StoryEpisode
- StoryScene
- StoryDialogue
- CharacterAppearance
- StoryEventLink

## Operations
- BackupRecord
- Incident
- HealthSnapshot

## Future
- Fan
- Vote
- Pitch
- StudioWallet
- StudioTransaction
- Vendor
- StoreItem
- Inventory
- OfficeUpgrade

## Constraints / invariants

- Agent termination does not delete history.
- Role permissions are evaluated server-side.
- Claim SUPPORTED requires evidence.
- Publication confirmed requires remote ID.
- Idempotency key unique per external side effect.
- Office current-state projection must be derivable from backend.
- Story current-cast appearance must be valid for employment interval.
- Dramatized dialogue cannot be stored as operational Agent Message.
- Cost reservation cannot exceed hard budget.
- STOP AUTONOMY blocks autonomous write-side operations.

## v3 additional entities

### Governance
- OwnerPolicy
- PolicyVersion
- PolicyRule
- GateEvaluation
- ApprovalPolicy
- FeatureFlag

### Agent execution
- AgentRun
- ContextManifest
- PromptTemplate
- PromptExecution
- ToolCall
- ToolReceipt
- AgentEvaluation
- AgentCapacityState
- Escalation

### Repair/reliability
- RepairCase
- ReconciliationRun
- PreflightRun
- ResourceReservation
- QueueSnapshot
- ServiceLevelSnapshot

### Memory
- MemoryRecord
- MemoryLink
- MemoryInvalidation
- MemoryRetentionPolicy

### Public projection
- VisibilityClassification
- PublicStudioEvent
- PublicAgentProfile
- ModerationCase

### Branding/IP
- PublicCharacterIdentity
- ProviderBrandAlias
- AssetLicenseRecord
- DependencyLicenseRecord
- IPAssetRecord

### Office/world
- WorldAsset
- WorldAssetVersion
- RoomTemplate
- PlacementRule
- WorldChangeRequest

### Release engineering
- Deployment
- FeatureFlag
- MigrationRun
- ReleaseArtifact

## v3 key relationships

- Every AgentRun references exact PromptTemplate version and provider/model.
- ToolCall has one or more ToolReceipts/results.
- GateEvaluation references workflow/content and policy version.
- StoryEpisode consumes Narrative/Public-safe projections, not unrestricted raw logs.
- PublicCharacterIdentity may map to AgentCharacter but does not need to expose ProviderModel.
- WorldAsset is versioned and referenced by OfficeObject.
- Publication references the exact Render checksum/version.
- AnalyticsSnapshot references remote video/channel IDs and observation time.

## Data ownership / visibility

Every sensitive entity should be classifiable as:
- PUBLIC;
- INTERNAL;
- CONFIDENTIAL;
- SECRET.

Secrets should generally be references to a secret store, not DB plaintext.

## Soft deletion / history

Use immutable history or soft-deactivation for business-critical entities.

Avoid destructive deletion of:
- agents;
- prompts used in published work;
- evidence;
- published render provenance;
- decisions;
- audit records.

## Multi-studio future-proofing

Where inexpensive, include `studio_id` on core business entities so a future second studio/channel group does not require a full relational rewrite.


# V4 Data Model Additions

## Organization
- Department
- DepartmentCharter
- DepartmentLifecycleEvent
- DepartmentBudget
- ManagerDelegation
- RoleTemplate
- OrgNeedAssessment
- OrgComplexitySnapshot

## Marketing
- MarketingOpportunity
- Campaign
- CampaignVariant
- SocialAccount
- SocialPostGroup
- SocialPostVariant
- CTA
- MarketingMetricSnapshot
- AttributionRecord
- MarketingExperiment

## Community
- CommunityChannel
- CommunityMessage
- CommunityReply
- CommunityPoll
- SentimentSnapshot
- ModerationAction

## Intelligence
- MarketSignal
- CompetitorObservation
- OpportunityHypothesis

## HR / Persona
- NarrativePersona
- PersonaVersion
- RelationshipEdge
- ProbationRecord
- OnboardingRecord
- CultureValue
- EmployeeMilestone

## Finance
- ExternalLedgerEntry
- EstimatedRevenueRecord
- InternalEconomyTransaction
- CostAllocation
- FinancialAnomaly

## Legal
- ComplianceReview
- ComplianceFinding
- ComplianceHold
- RightsAssetRecord

## Company Events
- CompanyEvent
- MilestoneTrigger
- EventParticipant
- EventOutcome
- CalendarAvailability
- EpisodeCommitment

## Important separation constraints

- NarrativePersona must never determine authorization.
- InternalEconomyTransaction must never be summed as real cash.
- Story embellishments must not be stored as OperationalEvent.
- Social post must retain source event/campaign provenance.


# V5 Financial / Economy Entities

Add at minimum:

## External evidence
- RevenueSource
- RevenueEvidence
- ExternalTransactionReference
- PlatformPayout
- DonationReceipt
- SponsorshipReceipt
- PaidPitchPayment
- OwnerFundingEvent
- ExternalCostEvidence
- RefundOrChargeback
- FXSnapshot

## Ledger / treasury
- VirtualAccount
- LedgerTransaction
- LedgerEntry
- TreasuryBalanceProjection
- TreasuryReserve
- Budget
- BudgetAllocation
- CostCenter
- FinancialPeriod

## Procurement / VendorShop
- PurchaseNeed
- ProductSpecification
- ProcurementQuote
- QuoteSource
- ProcurementDecision
- VendorShopOrder
- InventoryAsset
- AssetValuation
- AssetDepreciationSchedule
- AssetArchitectJob
- DeliveryEvent

## Financing
- FinancingRequest
- MarketRateReference
- DebtCapacityAssessment
- FinancingAgreement
- LoanSchedule
- LoanPayment
- InterestAccrual
- CovenantOrRiskLimit

## Forecasting
- FinancialForecast
- ForecastScenario
- ForecastAssumption
- ForecastConfidence

## Key relationships / constraints

- RevenueEvidence has unique external idempotency identity when available.
- VR mint transaction references exactly one eligible evidence/funding event.
- LedgerTransaction is immutable after posting; corrections use reversing entries.
- ProcurementQuote stores original currency + FX snapshot + quote timestamp + expiry.
- VendorShopOrder references the exact approved quote/price method.
- InventoryAsset references VendorShopOrder.
- FinancingAgreement references approval and market-rate evidence.
- Forecast records never directly mutate TreasuryBalanceProjection.

# As built: the film's paid path and operations (amended 2026-10-02)

Amended deliberately on 2026-10-02 after the production-readiness audit (finding AR-13). The
entities above are the logical model; these are the tables the code has today for the film's paid
path, the day and operations, with the migration that made each.

## Film purchase
- `scene_take` (0048, 0049, 0051): one row per purchase for a scene of a storyboard —
  `storyboard_id`, `scene_number`, `kind` (`still`, `motion`, `test_shot`, `narration`),
  `prompt_hash` (the take's identity), `model_id`, `resolution`, `seconds`, `seed`,
  `credits_quoted`, `credits_measured`, `status` (`QUOTED`, `SUBMITTED`, `PAID`, `APPROVED`,
  `REJECTED`, `REFUSED`, `LOST`), `failure_code`, `path`, `sha256`, `approved_by`,
  `remote_task_id` (the vendor's task id, written before any poll), and the licence evidence
  `licence_vendor`, `licence_terms`, `commercial_use`. Kind and status carry check constraints.
- `film_purchase_lease` (0050): `storyboard_id` (primary key), `holder`, `step`, `acquired_at`,
  `expires_at`: at most one buyer per film.
- `spending_budget`: `period` (DAILY or MONTHLY), `limit_usd_micros`, `warn_ratio`, `active`,
  `replaced_at`; set and retired only by the Owner, versioned and idempotent by command id.
- `spend_reservation`: `purpose` (for a paid step `sheet:<step>`), `correlation_id`, `usd_micros`,
  `status` (`RESERVED`, `SETTLED`, `RELEASED`), `settled_reference`; a hold left by a dead process
  is released by the watchdog after `reservation_ttl_seconds`.
- `provider_cost_record`: the books; each purchase booked once under its own reference.

## The day and the queue
- `daily_run`: `business_date`, `preflight_status`, `preflight_json`, `status` (`RUNNING`,
  `COMPLETED`, `PARTIAL`, `BLOCKED`, `FAILED`, `INTERRUPTED`), `stages_json`, `stages_total`,
  `stages_completed`, `stopped_at_stage`, `stop_reason`, `fault_class`, `started_at`,
  `finished_at`. Written RUNNING after the preflight and updated before each stage (47).
- `task_queue`: `task_type` (including `DAILY_RUN`, `FILM_CONTINUE`, `BACKUP`), `status`,
  `attempts`, `max_attempts`, `lease_token` (one token per claim), `lease_expires_at`
  (renewed by a heartbeat).
- `command_record`: idempotency of the Owner's commands, including sheet purchases
  (`SheetPurchase`) and a publication he resolved (`ResolvePublication`).

## Publishing
- `publication_record` (0052): `remote_privacy_status`, `remote_upload_status` and
  `remote_checked_at` — what YouTube says about the upload, beside what was asked.
- `channel_record` (0053): `youtube_category_id` (default `28`), `made_for_kids` (default false),
  `default_language` (NULL means the studio's content language), `shorts_max_seconds` (60 factual,
  70 serial); part of the channel's versioned publish policy.

## Invariants
- `APPROVED` on a take is the Owner's act alone; clip QC accepting a hero is an event on the
  take, not a status.
- A take of one identity is bought once; a still or clip collected late lands on its own
  `SUBMITTED` row.
- A `daily_run` becomes `INTERRUPTED` at most once and is never re-run by the clock.
