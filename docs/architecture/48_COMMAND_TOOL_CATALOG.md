# Command and Tool Catalog

## Purpose

LLMs do not mutate state directly. All business effects use typed backend commands/tools.

## Workforce commands

- CreateAgentCandidate
- HireAgent
- SuspendAgent
- ResumeAgent
- TerminateAgent
- ReassignTask
- ChangeAgentModel
- ChangeAgentPrompt
- ChangeAgentPermissions
- SetAgentBudget

## Provider commands

- ConfigureProvider
- TestProvider
- RefreshProviderCapabilities
- BenchmarkProviderModel
- DisableProvider
- SetFallbackRoute

Credential entry/rotation remains Owner/admin governed.

## Content commands

- CreateIdea
- SelectIdea
- StartResearch
- AddSource
- CreateClaim
- VerifyClaim
- CreateScriptVersion
- CreateStoryboard
- RequestMediaGeneration
- CreateRender
- SubmitQC

## Publishing commands

- CreatePublicationIntent
- ValidatePublication
- PublishVideo
- ReconcilePublication
- CancelScheduledPublication if platform supports
- RefreshAnalytics

## Governance commands

- RequestApproval
- ApproveAction
- RejectAction
- SetAutonomyMode
- StopAutonomy
- EnterSafeMode
- ExitSafeMode
- ChangePolicy (Owner-only/highest governance)

## Office commands

- AssignDesk
- CreateRoom
- RequestWorldAsset
- PlaceWorldObject
- RemoveWorldObject
- ActivateLayoutVersion

## Tool receipt rule

Each command that calls an external/internal effect returns:
- command_id;
- policy result;
- execution status;
- receipt IDs;
- resulting entity IDs;
- error/reconciliation status.

## Side-effect classification

Every command declares:
- read-only?;
- reversible?;
- external?;
- financial?;
- approval tier;
- idempotency scope.

## Versioning

Command schemas are versioned and contract-tested.


## V4 organization/marketing commands

- CreateDepartment
- MergeDepartments
- DissolveDepartment
- AssignDepartmentHead
- CreateRole
- CreateMarketingCampaign
- CreateSocialPostVariant
- ScheduleSocialPost
- PublishSocialPost
- CreateMarketSignal
- CreateOpportunityHypothesis
- CreatePersona
- UpdatePersonaVersion
- ScheduleCompanyEvent
- StartCompanyEvent
- CompleteCompanyEvent
- CreateComplianceReview
- PlaceComplianceHold
- ReleaseComplianceHold

Every command uses normal authorization, capability, idempotency and audit rules.


# V5 Economy Commands

## Revenue / treasury
- IngestRevenueEvidence
- VerifyRevenueEvidence
- ConfirmOwnerFunding
- PostRevenueSettlement
- PostRevenueReversal
- RecordExternalCost
- ReconcileExternalCost
- CreateTreasuryReserve
- ReleaseTreasuryReserve
- RefreshFinancialForecast

## Procurement / VendorShop
- CreatePurchaseNeed
- DefineProductSpecification
- SearchMarketQuotes
- AddProcurementQuote
- RefreshProcurementQuote
- SubmitProcurementForFinance
- ApproveProcurementBudget
- PlaceProcurementLegalHold
- ReleaseProcurementLegalHold
- CommitVendorShopVirtualPurchase
- RequestAssetArchitectBuild
- DeliverWorldAsset

## Financing
- CreateFinancingRequest
- ResearchMarketFinancingTerms
- AssessDebtCapacity
- SubmitFinancingLegalReview
- ApproveVirtualFinancing
- ActivateVirtualFinancing
- PostLoanPayment
- RestructureVirtualFinancing

Every command is side-effect classified. `CommitVendorShopVirtualPurchase` is financial inside VR ledger but **not an external payment**.
