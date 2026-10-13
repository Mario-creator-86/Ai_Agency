# Open Questions and Deferred Decisions

These questions should not block early architecture unless marked blocking.

## Blocking only when integration begins

- Which video provider has a real API and suitable reference/character consistency?
- Which TTS provider/voice will be used?
- Which search provider(s) will be configured?
- Which YouTube/Google project/account will own OAuth credentials?
- Which models are available through the Owner's Ollama/Ollama Cloud account?

## Architecture decisions to benchmark

- PixiJS vs Phaser for live office.
- Workflow technology: Celery/Dramatiq/RQ/Temporal/other.
- PostgreSQL timing vs initial SQLite.
- Local-only asset storage vs object storage.
- Hosting target for always-on production.

## Product decisions later

- Channel names/branding.
- Exact topic mix at launch.
- Frequency: 1 vs 2 Shorts/day.
- Serial visual style.
- How anthropomorphic/comedic characters should be.
- Whether provider/model names are public character names or fictionalized.
- Fan public-office access level.
- VR$ base currency and peg are now defined as USD 1:1; finalize public disclosure mode and funding-evidence policy.
- Paid pitch price and payment provider.
- Merchandise.

## Director governance decisions

Owner should eventually configure:
- maximum autonomous spend;
- max hires;
- hire/fire approval;
- Director self-model change approval;
- allowed providers;
- prohibited topics;
- autonomous public publishing permission;
- public-facing data policy.

## Principle

Do not guess these values in production.

Use sensible development defaults, expose configuration, and mark unknown external capabilities honestly.

## Decision management

For each open question, when implementation reaches the blocking phase, record:
- owner of decision;
- deadline/milestone;
- options;
- evaluation criteria;
- chosen value;
- ADR if architectural.

## Additional questions

### Governance
- Which Director actions are hard-gated vs approval-gated?
- What maximum rework/message loop limits should default to?
- What triggers automatic SAFE_MODE?

### Public identity
- Will public characters use actual provider/model names or fictional aliases?
- What third-party logos/names, if any, are allowed in the office/serial?

### Reliability
- What reliability burn-in duration is required before autonomous public posting?
- Target RPO/RTO?
- What notification channel will alert Owner when unattended?

### Media
- What deterministic fallback style should exist if generative video fails?
- What character-drift threshold is acceptable?
- Which caption/font/music assets have confirmed commercial rights?

### Story
- Which event classes are always INTERNAL_ONLY?
- How much narrative dramatization is acceptable?
- Should episodes explicitly disclose that dialogue is dramatized from real studio activity?

### World building
- Can the Director only buy catalog items initially?
- When can it commission/generated new 2D objects?
- What layout constraints are immutable?

### Transferability
- Which accounts will be business-owned rather than personal?
- What export package is required for a future sale?

## Decision rule

Open decisions must not be silently resolved by a coding AI when they materially change product behavior, cost, public branding, legal exposure or autonomy.


# V5 Economy decisions to finalize during implementation

1. Default base currency: USD/VR$ is currently assumed.
2. Whether Owner capital contribution requires uploaded/external evidence or Owner attestation is sufficient.
3. Default public financial disclosure mode.
4. Default quote TTL by product category.
5. Internal capitalization threshold/depreciation policy for virtual assets.
6. Debt-capacity policy for pre-revenue and early-revenue stages.
7. Whether paid pitch payments are refundable and exact service promised.
8. Which sources/providers are approved for real-market product/financing/FX references.
9. Gross/net accounting policy is now defined: use gross + separate fees when trustworthy data exists; otherwise use verified net settlement with `NET_SETTLEMENT_ONLY` basis.
