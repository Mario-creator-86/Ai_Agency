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

## As built (amended 2026-10-02)

Amended deliberately on 2026-10-02 after the production-readiness audit (finding AR-08). What
the local studio does today; the always-on studio above is not built and is the Owner's choice.

- **Backup.** `backend/app/backup.py` copies the live SQLite database through SQLite's online
  backup API, checks `PRAGMA integrity_check`, and writes `studio-<UTC>.db` with a manifest
  (`sha256`, size, the migration revision), the wrapped credentials key copied separately (it
  opens only for the same Windows account on the same machine) and optionally a listing of the
  media files (path, size, time; not their bytes). The daily job `backup_daily` runs at
  `STUDIO_BACKUP_HOUR_LOCAL` (03:30) behind STOP; a failure writes one letter a day and prunes
  nothing. Retention keeps the newest copy of each of 14 days and 4 weeks
  (`STUDIO_BACKUP_KEEP_DAILY`, `STUDIO_BACKUP_KEEP_WEEKLY`). On demand: `scripts/backup.py`.
  The films themselves are not in the backup; the media folder is copied to another disk by the
  operator.
- **Backup before migrations.** `scripts/bootstrap.py` makes a `premigrare` copy before it
  migrates a database whose revision is not the head; if the copy fails, nothing is migrated.
- **Restore and restore guard.** `scripts/restore.py` refuses while the studio answers on its
  port and refuses a copy that fails its hash or integrity check. It keeps the current database
  as a `prerestaurare` copy, and the restored studio is set STOPPED, TEST and with the daily job
  inactive in one versioned write; connections whose keys cannot be read are listed with their
  place in Settings. A restore therefore cannot re-publish old work by itself.
- **Disk.** `STUDIO_MEDIA_ROOT` names the media root; under `STUDIO_MIN_FREE_GB` (default 20 GB)
  free, the preflight line `disk_space` is BLOCKING and paid steps refuse `LOW_DISK` before
  buying. Shot intermediates of a film are deleted after its QC; intermediates of failed renders
  are swept after `STUDIO_FAILED_INTERMEDIATES_DAYS` only when the Owner turns the sweep on.
  `scripts/media_inventory.py` lists media folders the database does not know (dry run by default).
- **Health.** `/health/ready` answers 503 with codes only when the worker is stale, the disk low,
  FFmpeg or ffprobe missing, or the newest backup older than `STUDIO_BACKUP_MAX_AGE_HOURS` (36 h);
  an unreadable credentials vault alone keeps 200 with status DEGRADED so the page stays up for
  reconnecting. Three failing worker passes in a row write one letter.
- **Process.** One worker per database (an OS lock beside the database); stopping the studio ends
  the day after the scene in flight as INTERRUPTED. Logs rotate under `data/logs`
  (`STUDIO_LOG_DIR`). A systemd user unit is provided for Linux; the Windows task runs at logon.
- **CI.** `.github/workflows/checks.yml` exists and `scripts/check_all.py` runs the same chain
  locally under the machine's rules; hosted CI has never run, because the repository has no
  remote (the Owner's decision).
- **Restore test.** Tested on temporary copies only; no restore of the Owner's own database has
  been rehearsed.
