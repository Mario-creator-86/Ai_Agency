# Risk Register

| Risk | Severity | Mitigation |
|---|---|---|
| UI displays invented work | Critical | Backend authoritative events only; E2E invariant tests |
| Director claims action succeeded without tool result | Critical | Capability/action lifecycle + receipts |
| Duplicate YouTube upload | Critical | Idempotency + reconciliation |
| Runaway provider/video costs | High | Reservations, hard caps, circuit breakers |
| Prompt injection from web research | High | Untrusted-content isolation, tool/secret boundaries |
| Unsupported factual claim published | High | Claim provenance + QC block |
| AI video character drift | High | Character Bible, reference-capability checks, QC |
| Provider API changes | High | Adapter contract tests, health/capability status |
| PC asleep breaks automation | High | Background service + always-on deployment option |
| Scheduler launches duplicate daily cycle | High | leader/lock/idempotency |
| Fired employee remains in serial | Medium/High | continuity employment validity rules |
| Serial invents consequential backend event | High | DailyLog grounding + event references |
| Analytics causes overfitting to one viral result | Medium | minimum samples, experiments, cooldown |
| Copyright/rights issue | High | provenance/license gate |
| OAuth/token expiry | Medium | refresh handling, alert, blocked state |
| DB corruption/data loss | High | backups + restore test |
| Asset disk growth | Medium | retention/pruning policy |
| Director self-modifies guardrails | Critical | Owner-owned immutable policy layer |
| Provider credential leak | Critical | secret isolation/redaction |
| Fan/public view leaks internal data | High | sanitized projection boundary |
| Paid idea abuse/spam later | Medium | moderation/payment policy when implemented |
| Multiple AI coding agents conflict | Medium | handoff + task claiming + decision log |

## v3 additional risks

| Risk | Severity | Mitigation |
|---|---|---|
| Multi-agent infinite review/chat loop | High | hop/rework limits, deadlock detection, escalation |
| Director optimizes views at expense of truth/brand | High | hard gates + multi-objective scorecard |
| Provider healthy but quality silently regresses | High | drift monitoring, QC trend, re-benchmark |
| Fallback model technically works but degrades quality | Medium/High | role suitability threshold for fallback |
| Raw private reasoning exposed in UI/logs | High | structured summaries only, no chain-of-thought requirement |
| Public serial leaks private Owner/security details | Critical | NarrativeProjection sanitization + visibility labels |
| Third-party model name used as merch/character without rights review | Medium/High | public alias layer + brand/IP review |
| Director requests office object renderer cannot support | Medium | WorldBuilder schema/capability gate |
| Queue overload creates runaway latency/cost | High | backpressure/admission control |
| Agent loops consume tokens/cost | High | total wall-time/cost/hop limits |
| Restored backup republishes old scheduled jobs | Critical | restore in write-disabled mode + reconciliation |
| Event schema change breaks historical replay | High | versioning/upcasters/contract tests |
| External prices/quotas become stale | Medium | timestamped metadata + revalidation |
| New code deployment breaks autonomous production | High | CI/staging/feature flags/rollback |
| Fan vote manipulation/bots later | Medium | auth/rate limit/moderation, vote integrity |
| Internal credits confused with real revenue | Medium | separate ledgers/UI labels |
| Content becomes repetitive/spam-like | High | novelty/similarity gate + cadence controls |
| Visual storyboard implies false fact despite accurate narration | High | visual factual QC |
| Public channel/account depends on personal Owner credentials | High | account inventory/separation/transfer runbook |
| Dependency compromise/supply-chain issue | High | pinning/scanning/SBOM/review |


## V4 Risks

### R-ORG-01 — Organizational bloat
**Risk:** CEO creates too many agents/departments.
**Controls:** OrgNeedAssessment, trial roles, cost/coordination metrics, periodic consolidation.

### R-MKT-01 — Deceptive clickbait
**Risk:** marketing invents stakes for views.
**Controls:** Event Grounding Gate, payoff check, teaser truth tests.

### R-MKT-02 — Platform API limitations
**Risk:** assumed TikTok/Instagram/Facebook automation is unavailable.
**Controls:** adapter capability discovery, NOT_SUPPORTED/AUTH_REQUIRED states, no fake posting.

### R-MKT-03 — Community prompt injection
**Risk:** fan messages influence privileged agents.
**Controls:** untrusted-input isolation, scoped Community Agent, moderation/sanitization.

### R-COMP-01 — Competitor copying
**Risk:** system learns by plagiarizing.
**Controls:** abstraction-only observations, similarity checks, rights gate.

### R-PER-01 — Persona overrides operational truth
**Risk:** human-like personality alters factual/safety behavior.
**Controls:** separate OperationalIdentity/NarrativePersona models.

### R-EVT-01 — Fictional event presented as real
**Risk:** team building story confuses viewers.
**Controls:** OPERATIONAL_EVENT vs COMPANY_WORLD_EVENT taxonomy and public framing.

### R-FIN-01 — Fictional money confused with real money
**Risk:** internal studio budget treated as actual revenue.
**Controls:** separate ledgers and explicit labels.

### R-LEGAL-01 — Automated legal overconfidence
**Risk:** Legal Agent claims legal certainty.
**Controls:** risk-classification role, external counsel escalation, no binding legal acts.


# V5 Economy Risks

### RISK — Forecast treated as cash
Mitigation: separate ledgers/projections; spend gate uses only eligible treasury balance.

### RISK — Duplicate minting
Mitigation: external transaction idempotency keys + unique constraints + reconciliation.

### RISK — Real/virtual money confusion
Mitigation: explicit labels, disclosure modes, separate real-evidence and VR ledgers.

### RISK — Infinite virtual debt cheat
Mitigation: debt-capacity limits, market references, Legal/Finance gates, Owner thresholds.

### RISK — Stale market prices
Mitigation: quote TTL, revalidation, timestamp/source display.

### RISK — Missing shipping/tax creates unrealistic price
Mitigation: include when known; explicit UNKNOWN + configurable contingency.

### RISK — External checkout accidentally invoked
Mitigation: procurement adapters are read-only; no payment tool; contract tests.

### RISK — Chargeback causes negative treasury
Mitigation: reversals, reserves, stress state, no silent suppression.

### RISK — Public VR$ reveals private revenue
Mitigation: public disclosure policy and sanitized story/marketing projections.

### RISK — Exact branded asset creates IP/trademark issue
Mitigation: Legal/IP gate, public alias/stylization where appropriate.

### RISK — Price search manipulation / bad source
Mitigation: source quality, multiple quotes, outlier detection, provenance, approved domains/providers.
