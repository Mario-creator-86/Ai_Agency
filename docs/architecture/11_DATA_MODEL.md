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
