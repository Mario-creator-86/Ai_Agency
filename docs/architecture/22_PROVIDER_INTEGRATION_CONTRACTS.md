# Provider Integration Contracts

## Goal

Make providers replaceable and prevent the system from assuming capabilities.

## Common provider state

NOT_CONFIGURED
AUTH_REQUIRED
HEALTHY
DEGRADED
RATE_LIMITED
OFFLINE
UNKNOWN

## LLM adapter

Potential methods:
- health_check
- list_models
- get_model_capabilities
- generate
- generate_structured
- estimate_cost

Do not expose a method if underlying provider semantics cannot support it honestly.

## Video adapter

- health_check
- capabilities
- create_generation
- get_generation_status
- cancel_generation if supported
- fetch_result
- estimate_cost

Store remote job ID.

## Image adapter

- health_check
- capabilities
- generate
- edit/reference if supported
- fetch_result

## TTS adapter

- health_check
- list_voices if supported
- synthesize
- estimate_cost

## Search/research adapter

- search
- fetch metadata
- rate limit handling
- source URL

## Browser adapter

Browser is not a generic bypass.

Must respect:
- auth;
- CAPTCHA;
- site restrictions;
- safe navigation policy.

## YouTube adapter

- OAuth status
- channel identity
- upload
- set metadata
- schedule if supported
- get remote status
- get analytics via appropriate APIs

## Provider capability verification

Capability status:
- DECLARED_BY_PROVIDER;
- VERIFIED_BY_TEST;
- MANUALLY_CONFIGURED;
- UNKNOWN.

Prefer VERIFIED_BY_TEST for critical assignments.

## Schema drift

External APIs change.

Contract tests should detect:
- renamed fields;
- missing fields;
- status-code changes;
- async job semantic changes.

Do not allow parser errors to become hallucinated successful outputs.

## Contract versioning

Each adapter records:
- adapter version;
- provider API version if available;
- tested model identifiers;
- last real contract test;
- known unsupported fields.

## Pricing / quota metadata

Treat prices, quotas and limits as time-sensitive configuration.

Record:
- source;
- verified_at;
- currency/unit;
- uncertainty.

Cost estimator must tolerate unknown price and may require conservative reservation.

## Credential scopes

Provider adapter declares required credential scopes/permissions.

Use least privilege.

## Fallback contract

Fallback route specifies:
- compatible task types;
- minimum role quality;
- acceptable max cost;
- disclosure/behavior differences;
- whether Owner approval required.

## Deprecation

If provider/model is removed:
- mark unavailable;
- stop new assignment;
- preserve historical identity;
- trigger re-benchmark/replacement.

## Health vs suitability

Separate:
- API health;
- auth health;
- quota health;
- model availability;
- role suitability.

A HEALTHY API can still be unsuitable for a task.
