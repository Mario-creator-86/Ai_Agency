# CI/CD and Release Engineering

## Principle

The studio automates media production, not uncontrolled source-code deployment.

## Required checks

Before merge/release:
- unit tests;
- integration tests relevant to changes;
- type checks;
- lint;
- secret scan;
- migration validation;
- frontend build;
- dependency lock consistency.

## Environments

- development;
- test/staging;
- production.

Use production credentials only in production.

## Feature flags

High-risk features:
- autonomous public publish;
- autonomous firing;
- provider auto-switch;
- WorldBuilder generation;
- public fan stream.

Enable independently.

## Release artifact

Record:
- git commit;
- build ID;
- migration version;
- dependency lock hash;
- release timestamp;
- feature flags.

## Database migrations

- forward tested;
- backup before destructive changes;
- rollback or restore plan;
- no external autonomous writes during dangerous migrations.

## Rollback

Have an explicit rollback to last known-good release.

If schema cannot roll back, document forward-fix/restore.

## Production safety

Do not deploy a large backend/event-schema change at the same time as enabling a new autonomous external-write feature without a staged plan.
