# API, Schema and Contract Versioning

## Internal APIs

Use explicit versioned routes or schema versions where changes can break clients.

## Durable events

Every event has `schema_version`.

Readers support:
- current;
- known prior versions through upcasters.

## Database

Migrations are versioned.

Do not encode critical semantics only in application constants without migration strategy.

## Provider adapters

External contract test fixtures should capture representative real responses without secrets.

## Backward compatibility

Prefer:
- add optional field;
- add new event type;
over:
- rename/remove field without migration.

## Frontend/backend compatibility

A deployment should not create a window where frontend expects new event fields the backend cannot provide.

Use:
- coordinated release;
- tolerant readers;
- feature flags.

## Deprecation

Document:
- deprecated field/API;
- replacement;
- removal target;
- migration.

## Contract tests

Test:
- JSON schema;
- unknown fields;
- missing optional fields;
- version conversion;
- malformed payload.
