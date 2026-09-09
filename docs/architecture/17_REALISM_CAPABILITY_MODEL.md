# Realism and Capability Model

## Why this document exists

LLMs can fluently describe actions they did not actually perform. This product must structurally prevent that behavior from becoming system state.

## Action lifecycle

Every action uses:

PROPOSED
→ AUTHORIZED
→ CAPABILITY_VALIDATED
→ CONFIG_VALIDATED
→ BUDGET_RESERVED
→ EXECUTING
→ EXTERNAL_RESULT_RECEIVED
→ VERIFIED
→ COMMITTED
→ EVENT_EMITTED

Failure can occur at every stage.

## Capability Registry

Track capability facts per provider/model/tool.

Examples:
- supports_text;
- supports_json_schema;
- supports_tool_calling;
- supports_vision;
- supports_reference_images;
- supports_video;
- supports_tts;
- supports_embeddings;
- supports_async_jobs;
- supports_model_listing.

Capability source:
- provider API;
- configured metadata;
- verified integration test.

Unknown capability remains UNKNOWN.

## Tool authority

Only tools can cause privileged effects.

LLM text is advisory until a tool/backend command succeeds.

Examples:
- `hire_agent` command;
- `terminate_agent`;
- `change_agent_model`;
- `publish_video`;
- `create_room`;
- `reserve_budget`.

## External blockers

Director must surface blockers such as:
- no API key;
- no account;
- OAuth required;
- payment required;
- terms acceptance required;
- provider unavailable;
- model removed;
- quota exhausted;
- API unsupported.

It may propose a next step but cannot fabricate resolution.

## Realistic model selection

Do not treat model names as personalities or fixed capability labels.

Provider/model properties can change over time.

Store:
- last verified timestamp;
- capability test version;
- latency/cost samples.

## Realistic autonomy

Autonomy is bounded by:
- available compute;
- provider reliability;
- network;
- quotas;
- local PC uptime;
- platform APIs;
- configured permissions.

"Autonomous" means no routine human decision is required inside these bounds; it does not mean external systems have no restrictions.

## Success receipts

A successful side effect requires evidence:
- remote object ID;
- API status;
- persisted DB record;
- file checksum;
- task output reference.

No receipt = not verified.

## Capability confidence and expiration

Capability is not timeless.

Record:
- status;
- evidence source;
- verified_at;
- expires/recheck_after;
- test version.

A capability last verified months ago may become `STALE_CAPABILITY`.

## Quality capability

Binary support is insufficient.

Example:
a provider may technically support reference images but fail the required continuity quality.

Track role suitability separately from raw feature support:
- CAPABLE;
- CAPABLE_DEGRADED;
- UNSUITABLE;
- UNKNOWN.

## Fallback realism

Fallback must satisfy:
- required technical capabilities;
- policy;
- minimum quality;
- budget;
- credential state.

"Any available model" is not a valid fallback policy.

## World-action realism

A Director request like "build a fountain" requires:
- supported WorldBuilder command;
- asset source/generation;
- validated footprint;
- backend transaction.

An LLM-created description alone is not an office change.

## Reasoning realism

A model saying "I am 98% confident" is not calibrated evidence.

Confidence values are metadata to evaluate, not truth.

Use external validation/benchmark results where material.

## Non-determinism

Repeated model calls may differ.

Persist exact outputs and run metadata.

Do not expect byte-for-byte reproducibility from external stochastic providers unless they explicitly support it.
