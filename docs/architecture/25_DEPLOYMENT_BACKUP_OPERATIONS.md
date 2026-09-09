# Deployment, Backup and Operations

## Local Studio

Suitable for development and early testing.

Requirements:
- Windows PC powered on;
- network;
- backend service;
- worker;
- scheduler;
- DB;
- media tools.

Browser/UI may close without stopping backend workers.

## Always-On Studio

Required for reliable unattended daily production.

Potential:
- VPS/cloud VM;
- managed DB or PostgreSQL;
- Redis/queue if selected;
- object storage;
- reverse proxy/TLS;
- monitoring.

## Environment separation

Use:
- development;
- staging/test;
- production.

Never test autonomous public publishing first in production.

## Backup

Back up:
- DB;
- character bibles;
- source/evidence metadata;
- scripts;
- final renders;
- continuity;
- provider configuration excluding secrets;
- critical generated assets.

## Secret backup

Do not include raw secrets in normal export.

Provide separate documented secret reconfiguration.

## Restore test

Periodic test:
- restore DB;
- restore assets;
- start application;
- verify content history/continuity;
- verify no external side effects are triggered on restore.

## Migrations

- versioned;
- reversible where practical;
- backup before destructive migration;
- test migration with copy of data.

## Disk management

Video assets can grow quickly.

Implement retention policies:
- keep final output;
- keep provenance-critical assets;
- optionally prune temporary intermediates after configurable period.

Never delete assets required for audit/reproducibility without explicit policy.

## Monitoring

Alert on:
- worker down;
- scheduler down;
- DB unavailable;
- event backlog;
- stuck workflows;
- provider outage;
- budget anomaly;
- disk low;
- backup failed.

## Process supervision

On Windows/local:
- use a documented service/process manager strategy;
- auto-start backend/worker/scheduler if desired;
- expose "workers not running" clearly.

On server:
- supervised processes/containers;
- restart policy;
- health probes.

## RPO / RTO

Define targets before production.

Example configurable concepts:
- RPO: acceptable data loss window;
- RTO: acceptable recovery time.

Published content provenance/employment history should target very low data loss.

## CI/CD

Production deployments should:
- build versioned artifact;
- run tests;
- run migration checks;
- record release;
- support rollback.

## Staging

Use staging/dry-run for:
- new provider adapters;
- OAuth changes;
- workflow migrations;
- Director policy changes;
- new media pipeline.

## Backup scope

Also include:
- prompt versions;
- policy versions;
- audit log;
- world/room assets;
- public character aliases;
- release/config metadata.

## Restore guard

Restored environment defaults to external writes disabled until:
- Owner confirms environment;
- credentials checked;
- reconciliation completed.

This prevents a restored scheduler from re-publishing old work.
