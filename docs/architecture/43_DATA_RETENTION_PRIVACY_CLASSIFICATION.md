# Data Retention and Privacy Classification

## Classes

### PUBLIC
Published/safe public data.

### INTERNAL
Ordinary operational data.

### CONFIDENTIAL
Owner/private business information.

### SECRET
Credentials/tokens/cryptographic secrets.

## Examples

PUBLIC:
- published video metadata;
- sanitized public agent profile.

INTERNAL:
- task logs;
- operational agent messages.

CONFIDENTIAL:
- private Owner commands;
- non-public analytics/business decisions.

SECRET:
- API keys;
- OAuth refresh tokens.

## Retention

Define per entity:
- retention period;
- legal/business reason;
- archive behavior;
- deletion/invalidation.

Audit/provenance may need long retention.

Temporary raw media can be pruned after policy window.

## Public projection

Only PUBLIC fields are public by default.

Explicit sanitization can derive PUBLIC_SAFE projection from INTERNAL source.

## Secrets

Prefer secret references; do not include in backups/exports/logs.

## Future fan data

When public accounts exist, define:
- data collected;
- purpose;
- retention;
- deletion/export;
- moderation retention.

## Backups

Deletion/retention policy should consider backup lifecycle and restoration behavior.
