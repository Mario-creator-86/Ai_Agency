# Prelaunch Readiness Checklist

## Before first real autonomous public post

### Infrastructure
- [ ] production deployment stable;
- [ ] worker/scheduler supervised;
- [ ] DB backup tested;
- [ ] restore tested;
- [ ] disk/storage alerts;
- [ ] HTTPS/auth where remotely accessible.

### Governance
- [ ] Owner Policy configured;
- [ ] STOP AUTONOMY tested;
- [ ] SAFE_MODE tested;
- [ ] approval tiers configured;
- [ ] public publishing feature flag explicit.

### Providers
- [ ] primary/fallback LLM verified;
- [ ] research verified;
- [ ] media verified;
- [ ] TTS verified;
- [ ] YouTube OAuth verified;
- [ ] quotas/cost metadata reviewed.

### Content
- [ ] factual gate tested;
- [ ] visual factual QC tested;
- [ ] rights gate tested;
- [ ] novelty gate tested;
- [ ] deterministic media fallback works.

### Automation
- [ ] daily preflight;
- [ ] restart recovery;
- [ ] backpressure;
- [ ] retry caps;
- [ ] repair queue;
- [ ] publication reconciliation;
- [ ] no duplicate upload in fault test.

### UI
- [ ] backend/UI invariant tests green;
- [ ] live vs replay clear;
- [ ] public/internal projections separated.

### Reliability
- [ ] burn-in completed;
- [ ] manual interventions recorded;
- [ ] unresolved P0 = 0;
- [ ] configured SLOs met or Owner explicitly accepts gap.

### Business/rights
- [ ] channel ownership/account inventory;
- [ ] asset/provider terms reviewed;
- [ ] third-party public character naming decision;
- [ ] business export/backup exists.

Only after this checklist is approved should AUTONOMOUS PUBLIC PUBLISHING be enabled.
