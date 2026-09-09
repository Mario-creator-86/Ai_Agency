# Autonomous AI Studio — Documentation Repository v3

This repository is the **single source of truth** for the Autonomous AI Studio project.

The product is an autonomous AI media company represented as a living top-down 2D office. It produces:

1. **Channel A — Main Factual Shorts**: international English-language factual Shorts.
2. **Channel B — Office Serial**: a serialized workplace sitcom based on what actually happened inside the studio during the previous day.

The system is designed to become highly autonomous, but autonomy must remain **realistic, capability-bound, auditable, recoverable and safe**.

## Five non-negotiable invariants

1. **Backend = Reality**  
   The database, workflow state and committed domain events are authoritative. The UI never invents live activity.

2. **Intent ≠ Capability ≠ Outcome**  
   An agent may want to do something, but it can only do it if it has the required tool, permission, provider capability, credentials, budget and runtime access. The system only reports success after the external/internal effect is verified.

3. **Automation must be durable**  
   The production pipeline may not depend on a browser tab being open. Workflows, retries, leases, state, cancellation and side effects must survive restarts.

4. **No factual publication without provenance**  
   Important factual claims must be tied to evidence. Unresolved critical claims block publication.

5. **Director is powerful but not magical**  
   The Director is the CEO of the AI workforce, but remains subordinate to Owner policy, credentials, platform limitations, budgets and capability boundaries.

## Reading order for every AI coding agent

Before editing code, read:

1. `00_MASTER_PROMPT.md`
2. `01_VISION.md`
3. `02_SRS.md`
4. `03_ARCHITECTURE.md`
5. `04_AGENT_SYSTEM.md`
6. `05_UI_UX_2D_OFFICE.md`
7. `06_BACKEND_EVENT_MODEL.md`
8. `07_STORY_ENGINE.md`
9. `08_VIDEO_PIPELINE.md`
10. `09_CHANNELS_AND_AUTOMATION.md`
11. `10_FUTURE_MODULES.md`
12. `11_DATA_MODEL.md`
13. `12_TESTING_QA.md`
14. `../project/13_ROADMAP_TODO.md`
15. `../project/14_AI_HANDOFF_PROTOCOL.md`
16. `15_SECURITY_COSTS_OBSERVABILITY.md`
17. `../project/16_DECISION_LOG.md`
18. `17_REALISM_CAPABILITY_MODEL.md`
19. `18_AUTOMATION_ORCHESTRATION.md`
20. `19_DIRECTOR_CEO_SPEC.md`
21. `20_EMPLOYEE_AGENT_SPEC.md`
22. `21_FAILURE_RECOVERY_PLAYBOOK.md`
23. `22_PROVIDER_INTEGRATION_CONTRACTS.md`
24. `23_CONTENT_RIGHTS_PLATFORM_POLICY.md`
25. `24_VISUAL_CONTINUITY_ASSET_SYSTEM.md`
26. `25_DEPLOYMENT_BACKUP_OPERATIONS.md`
27. `26_MASTER_ACCEPTANCE_CRITERIA.md`
28. `27_RISK_REGISTER.md`
29. `28_DOCUMENTATION_AUDIT.md`
30. `29_OPEN_QUESTIONS_AND_DECISIONS.md`
31. `../project/CURRENT_STATUS.md`
32. `../project/CHANGELOG.md`
33. `30_PROMPT_CONTEXT_MEMORY_ARCHITECTURE.md`
34. `31_GOVERNANCE_APPROVAL_POLICY.md`
35. `32_AGENT_TOOL_PERMISSION_MATRIX.md`
36. `33_MODEL_EVALUATION_DRIFT.md`
37. `34_CONTENT_QUALITY_ANALYTICS_OBJECTIVES.md`
38. `35_CI_CD_RELEASE_ENGINEERING.md`
39. `36_RELIABILITY_SLO_RUNBOOK.md`
40. `37_PUBLIC_COMMUNITY_MODERATION_PRIVACY.md`
41. `38_IP_BRAND_TRANSFERABILITY.md`
42. `39_DAILY_AUTONOMOUS_RUNBOOK.md`
43. `40_THREAT_MODEL_SECURITY_BOUNDARIES.md`
44. `41_WORLD_BUILDER_OFFICE_EVOLUTION.md`
45. `42_API_SCHEMA_VERSIONING_CONTRACTS.md`
46. `43_DATA_RETENTION_PRIVACY_CLASSIFICATION.md`
47. `44_CONTENT_DEDUPLICATION_NOVELTY.md`
48. `45_PRELAUNCH_READINESS_CHECKLIST.md`

## Required working files

These must always stay current:

- `../project/CURRENT_STATUS.md`
- `../project/13_ROADMAP_TODO.md`
- `../project/CHANGELOG.md`
- `../project/16_DECISION_LOG.md`

A new AI coding agent must be able to continue the project without asking the Owner to re-explain the architecture.

## v3 document precedence and operating model

When documentation appears to conflict, use this precedence:

1. Owner policy and explicitly approved current decisions.
2. `00_MASTER_PROMPT.md`.
3. `31_GOVERNANCE_APPROVAL_POLICY.md`.
4. `17_REALISM_CAPABILITY_MODEL.md`.
5. `02_SRS.md`.
6. subsystem specifications.
7. roadmap/TODO/status documents.

Do not resolve contradictions silently. Record the conflict and resolution in `../project/16_DECISION_LOG.md`.

### Required reading by task type

**Any coding task**
- README
- MASTER PROMPT
- CURRENT_STATUS
- ROADMAP/TODO
- DECISION LOG

**Agent/Director work**
- Agent System
- Director Spec
- Employee Spec
- Prompt/Context/Memory
- Governance
- Tool/Permission Matrix
- Model Evaluation/Drift

**Automation**
- Architecture
- Backend Event Model
- Automation/Orchestration
- Daily Autonomous Runbook
- Failure Recovery
- Reliability/SLO

**2D office**
- UI/UX
- Backend Event Model
- Visual Continuity
- World Builder / Office Evolution

**Content/video**
- Story Engine
- Video Pipeline
- Rights/Policy
- Content Quality/Analytics
- Deduplication/Novelty

### Never expose hidden reasoning

The product may display concise operational messages, evidence, decision summaries and structured rationales. It must not require or persist hidden chain-of-thought. "Thinking" animations represent a real reasoning task in progress, not a transcript of private internal reasoning.

### Product maturity levels

- **Prototype**: local, manual, mocks clearly labeled.
- **MVP**: real agents/research/2D projection and one real MP4 path.
- **Supervised Production**: real publishing with Owner approval.
- **Autonomous Production**: durable unattended operation with guardrails.
- **Public Studio**: sanitized fan view and community features.
- **Transfer-Ready Business**: documented IP, provider/account separation, export and operational runbooks.

## Deep review report

See `V3_FILE_BY_FILE_REVIEW.md` for the file-by-file v3 audit.

## Additional v3 operational specifications

- `46_REQUIREMENTS_TRACEABILITY_MATRIX.md`
- `47_STATE_MACHINE_SPECIFICATIONS.md`
- `48_COMMAND_TOOL_CATALOG.md`
- `49_UI_BACKEND_STATE_MAPPING.md`
- `50_CONTENT_GATE_MATRIX.md`
- `51_AUTONOMY_MODE_SEMANTICS.md`
- `52_OBSERVABILITY_METRICS_CATALOG.md`
- `53_PERFORMANCE_CAPACITY_PLAN.md`


# V4 Organizational Expansion

This version adds architecture for an evolving AI company:

- Marketing & Communications
- cross-platform social distribution
- Telegram community
- dynamic departments and managers
- Market / Competitive Intelligence
- HR / People Operations
- Finance / FinOps
- Legal / Compliance
- Advertising / Sponsorship
- employee personalities and birthdays
- company calendar and team-building/milestone events
- organizational growth controls.

For these additions also read docs `54` through `65`.


## V5 — Market-Anchored Virtual Economy

V5 adds a core VR$ economy:
- 1 verified USD inflow → 1 VR$;
- market-priced virtual purchases;
- real-world revenue/cost evidence;
- Finance/Treasury;
- Owner funding;
- realistic virtual financing;
- Procurement + VendorShop;
- Asset Architect;
- financial dashboard/forecasting;
- double-entry virtual ledger;
- economy-driven story/world events.

The system never autonomously spends real money or completes a real product/loan checkout.

Read additionally:
- `66_VIRTUAL_REAL_ECONOMY_ENGINE.md`
- `67_VENDORSHOP_PROCUREMENT_ARCHITECT.md`
- `68_TREASURY_FINANCING_CAPITAL_STRUCTURE.md`
- `69_REVENUE_MONETIZATION_CASH_RECONCILIATION.md`
- `70_FINANCIAL_DASHBOARD_FORECASTING.md`
- `71_VIRTUAL_ACCOUNTING_LEDGER_STANDARDS.md`
- `72_ECONOMY_STORY_WORLD_INTEGRATION.md`

- `73_END_TO_END_ECONOMY_SCENARIOS.md` — normative money/procurement/loan examples.
- `V5_ECONOMY_ARCHITECTURE_AUDIT.md` — design audit and resolved risks.
