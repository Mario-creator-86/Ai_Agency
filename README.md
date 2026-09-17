# AMN-AI — Autonomous Machine Nexus

**AMN-AI** (Autonomous Machine Nexus — Artificial Intelligence) is a local-first AI media studio. Phases 0–2 are complete; phases 4–6 are partially implemented and
their acceptance criteria are not met — see [Current status](docs/project/CURRENT_STATUS.md) and the
[external audit](docs/project/AUDIT_2026-09-09_EXTERNAL.md). This is not a production AI company.

The agency name and logo, and which asset belongs where, are documented in
[Brand](docs/project/BRAND_AMN_AI.md).

## Documentation is authoritative

- [Master Prompt](docs/architecture/00_MASTER_PROMPT.md) — primary product/build instructions.
- [Architecture reading order](docs/architecture/README.md) — complete normative specification package.
- [Current status](docs/project/CURRENT_STATUS.md) — verified implementation and limitations.
- [Roadmap](docs/project/13_ROADMAP_TODO.md) and [normalized implementation plan](docs/project/IMPLEMENTATION_PLAN.md).
- [Decisions](docs/project/16_DECISION_LOG.md) and [developer handoff](docs/project/14_AI_HANDOFF_PROTOCOL.md).

## Repository layout

```text
docs/architecture/    78 normative specification/review documents
docs/project/         Live roadmap, status, decisions, change history and document index
backend/app/          FastAPI, settings, persistence, Owner commands and read models
backend/migrations/   Explicit versioned Alembic schema
frontend/             HTML + Tailwind CSS + JavaScript, built with Vite
tests/                Backend local integration/invariant tests
frontend/tests/       Snapshot projection tests
scripts/              start.py launcher, bootstrap, server runner, integrity/security checks
data/                 Local SQLite data (generated, ignored by Git)
output/               Local verification artifacts (generated, ignored by Git)
```

## Local setup

Requires Python 3.12–3.14, uv, Node.js 22.12+ and npm.

One command does everything — dependencies, database, frontend build, server:

```shell
start.cmd
```

On any platform: `uv run python scripts/start.py`. Every step is idempotent, so this is also how
you restart after a code change. Useful flags: `--skip-frontend`, `--skip-sync`, `--rebuild`.

Open [the local studio](http://127.0.0.1:8000). Paste `STUDIO_OWNER_TOKEN` from the generated `.env`
into the Owner sign-in form. Ctrl+C stops the studio.

Before starting, the launcher prints what is actually configured. Two integrations are optional and
are **disabled rather than simulated** when absent:

- **ffmpeg** (plus `ffprobe`) — without it, video rendering returns HTTP 503 and quality control
  cannot measure a render. The studio never writes a placeholder file with an `.mp4` name.
- **YouTube OAuth** (`STUDIO_YOUTUBE_CLIENT_ID`, `STUDIO_YOUTUBE_CLIENT_SECRET`,
  `STUDIO_YOUTUBE_REFRESH_TOKEN`) — without these, publishing endpoints return HTTP 503. Nothing
  is uploaded and nothing is reported as published.

The individual steps, if you prefer to run them yourself:

```shell
uv sync --locked
npm ci --prefix frontend
uv run python scripts/bootstrap.py
npm run build --prefix frontend
uv run python scripts/run.py
``` The token stays in page memory; refresh or sign-out clears the session.
Never commit/share `.env`. Bootstrap never overwrites an existing credential file or studio.

The launcher binds to `127.0.0.1` by default. Remote deployment, TLS and multi-user access are not
implemented. Do not expose this development service directly to the Internet.

SQLite files live under `data/`. Migrations must be run before application startup; application
startup refuses an unexpected schema. Back up the database before future migrations; there is no
destructive downgrade command. Stop the server before manually copying SQLite files, including WAL
and SHM companions if present. A complete tested backup/restore tool is a later roadmap item.

Studio name/timezone are initial bootstrap values. Editing environment defaults later does not
silently rewrite existing domain state. All event timestamps are UTC; display uses stored timezone.

## What works

Authenticated snapshots/event history, persisted initial empty room, explicit unavailable modules,
Owner STOP flag, optimistic versions, idempotent commands, atomic policy/event writes and immutable
history. Releasing STOP keeps Manual mode and does not start work. There are no workers/providers,
media jobs or external publishing/payment routes to run yet.

The frontend polls committed snapshots every five seconds while visible. It labels disconnected
state and disables commands while stale. This is a foundation shell, **not the Phase 3 office renderer**.
Rooms/characters, animation, full WebSocket replay and agent inspectors will be implemented later.

## Running as a service

`start.cmd` runs the studio in a foreground process, and the background worker that fires the
daily run lives inside it: close the window or reboot the machine and autonomy ends silently.
For a studio that is meant to run on its own, register it as a Windows Scheduled Task. The two
scripts below are the Owner's to run, from a PowerShell opened as administrator (a startup
trigger needs it); the studio and its agents never run them.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_studio_service.ps1
powershell -ExecutionPolicy Bypass -File scripts\install_studio_service.ps1 -RunWhenLoggedOff
powershell -ExecutionPolicy Bypass -File scripts\uninstall_studio_service.ps1
```

The task is named **AMN-AI Studio**. It runs the same command `start.cmd` runs, with
`--skip-frontend` (build the bundle once with `start.cmd` before installing), at logon and at
startup, restarts it up to three times one minute apart when it exits with an error, and has no
execution time limit. Registering again replaces the task in place. Everything the studio prints
goes to `data\studio-service.log`. Without `-RunWhenLoggedOff` the task runs in your signed-in
session and the startup trigger only takes effect once you sign in; with it, the task runs
whether you are signed in or not (no password is stored).

Two things the task does not do. It does not activate the daily job: the schedule is seeded
dormant, and starting the studio's clock is your recorded act from the panel
(`workflow.job_activated`), the same as clearing the autonomy stop. And it does not keep the
machine awake: a PC that sleeps at the run hour runs nothing, so set the Windows power plan
(Settings → System → Power, or `powercfg`) so the machine does not sleep while the studio is
meant to work. That setting is yours to change; the scripts do not touch it.

To check that the task exists and when it last ran:

```powershell
schtasks /Query /TN "AMN-AI Studio" /V /FO LIST
Get-ScheduledTaskInfo -TaskName "AMN-AI Studio"      # LastRunTime, LastTaskResult (0 = ran)
Get-Content data\studio-service.log -Tail 40
```

`Start-ScheduledTask` / `Stop-ScheduledTask -TaskName "AMN-AI Studio"` start and stop it by hand.
While the task is running, the watchdog job inside the worker fails renders that have made no
progress past its threshold, reconciles uncertain publications against the platform a bounded
number of times before handing them to you, and reports lapsed task leases; it changes nothing
while STOP AUTONOMY is set.

## Verify

```shell
uv run python scripts/check_docs.py
uv run ruff check .
uv run ruff format --check .
uv run mypy
npm run check --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
uv run pytest
uv run python scripts/check_secrets.py
```

GitHub Actions contains the same baseline for Windows/Linux. Local passes do not prove hosted CI
has executed. Real-provider tests have not run; no external integration is claimed.

Architecture file changes require a recorded decision and explicit index hash update.
`scripts/check_docs.py` detects missing/moved documents, broken known-document references and
unexpected architecture edits. Project tracking documents are intentionally mutable.

## API

Public: `GET /health/live`, `GET /health/ready` (API/database scope only).

Owner Bearer token required:

- `GET /api/v1/snapshot`
- `GET /api/v1/events?after=0&limit=50`
- `POST /api/v1/owner/autonomy-stop` with `schema_version`, UUID `command_id`,
  `expected_version` and Boolean `stopped`.

Same command ID + same payload returns its original result. Changed payload or stale policy version
returns 409. A retry after an unknown network outcome must reuse the original command ID.

