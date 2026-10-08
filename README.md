# AMN-AI — Autonomous Machine Nexus

AMN-AI is a local, single-owner AI film studio. A team of AI employees (Director, Researcher,
Fact Checker, Script Writer, Voice Artist, Video Editor, Publisher, Accountant) researches a
topic, verifies its claims against stored sources, writes a factual short and an office serial,
plans the shots, buys pictures, motion and narration from the vendors you connect (Runway,
ElevenLabs), cuts the film with FFmpeg, measures it, and uploads it to YouTube — each paid step
and each upload only as far as **your** policy allows. The page shows agents in an original
side-view pixel studio, with the existing production and settings menus.

What it is not: a hosted service, a multi-user product or a promise of good films. It runs on
one machine, for one Owner, on `127.0.0.1`. Where the work stands is in
[CURRENT_STATUS](docs/project/CURRENT_STATUS.md) (in a release archive, see the changelog that
came with it). The Romanian operator guide is [docs/OPERATOR_GUIDE.md](docs/OPERATOR_GUIDE.md).

## Prerequisites

| Needed | Version | Install |
|---|---|---|
| Python | 3.12 – 3.14; local runtime pinned to 3.14.8 | python.org, or `uv python install 3.14.8` |
| uv | current | https://docs.astral.sh/uv/ |
| Node.js + npm | 22.12+ | nodejs.org (only to build the page) |
| **FFmpeg + FFprobe** | 7 or newer, full build | **required for films**: Windows `winget install Gyan.FFmpeg` · Debian/Ubuntu `sudo apt install ffmpeg` · macOS `brew install ffmpeg` |
| Git | any | only to clone |

The local environment uses Python 3.14.8 with SQLite 3.53.1, verified on this machine.
Use a runtime containing the [SQLite WAL concurrency fix](https://www.sqlite.org/wal.html#walreset)
(3.51.3 or newer, or the 3.44.6/3.50.7 backports). A temporary test database reported corruption
on the previous SQLite 3.50.4 runtime; that cause was not conclusively reproduced. The production
database passed its integrity check. Package versions remain locked in `uv.lock`.

FFmpeg is not optional: without it the studio refuses to render (HTTP 503) rather than write a
fake file, and quality control cannot measure a film. A film uses `libx264`, `aac`, `subtitles`
(libass), `zscale` (zimg), `loudnorm`, `xfade`, `drawtext`, `zoompan`, `sidechaincompress`,
`silencedetect` and `signalstats`; the launcher lists any your build lacks and what the film
loses without it. Gyan's "full" Windows build and the distribution packages have them all.

The interface needs no Blender, Unreal Engine, ComfyUI or GPU stream. Archived graphics
sources remain recoverable. Start with [the short Romanian guide](docs/project/SIMPLE_STUDIO_GUIDE.md).

## Install and first run

```shell
git clone <your copy> C:\amn-ai        # a SHORT path: some art files have long names
cd C:\amn-ai
start.cmd                               # Windows
uv run --locked python scripts/start.py # any platform
python start.py                         # compatible root entry; delegates through uv
```

If the existing Windows environment refers to a missing base Python, `start.cmd`
restores the version declared in `.python-version` before launching. A healthy environment
does not download or reinstall Python. Recovery needs network access and a recent `uv`
that knows the requested version; it stops with a diagnostic if restoration fails.
On this PC `uv` was updated from 0.11.0 to 0.12.23 for the pinned 3.14.8 download.

On Windows, either clone into a short folder as above or run
`git config --global core.longpaths true` first; a deep folder fails with "Filename too long".
A release archive (`scripts/make_release.py`) has no such files.

`start.py` syncs the locked Python environment, writes `.env` with a fresh Owner key, creates
and migrates the database (`data/studio.db`, backed up before any later migration), seeds the
employees, channels and books, builds the page, prints a preflight read from the studio itself,
and serves http://127.0.0.1:8000. Opened on this machine (127.0.0.1, localhost or [::1] at the
studio's port), the page enters without the sign-in form: the studio hands it the Owner key
(`STUDIO_LOCAL_AUTO_LOGIN`, on by default; the Owner, 2026-10-08). From another machine, through a
proxy, or with `STUDIO_HOST` beyond loopback, paste `STUDIO_OWNER_TOKEN` from `.env` into the form.
Ctrl+C stops it. Every step is idempotent: run the same command to restart or upgrade.
Flags: `--skip-frontend`, `--skip-sync`, `--rebuild`, `--graphics`, `--no-graphics`.

**The studio starts directly with the pixel interface.** Ordinary launches do not start
graphics processes. Legacy `--graphics` tooling is retained for archived art work; it is not
used by the current interface. Treasury and virtual financing are retired from the active
product; actual USD budgets/prices and provider costs remain under **Autonomie**.

**A new studio starts safe:** autonomy STOPPED, mode **MANUAL**, environment **TEST**, the daily
job dormant, no vendor connected. Nothing runs, nothing is bought and nothing is published until
you say so in the page.

Before the first real day, set the scheduling timezone and calendar in `.env`:
`STUDIO_TIMEZONE`, `STUDIO_OFFICE_LATITUDE`, `STUDIO_OFFICE_LONGITUDE`, `STUDIO_OFFICE_CITY`,
`STUDIO_HOLIDAY_COUNTRY`. The defaults are Bucharest. Every setting is listed, grouped and
explained in [.env.example](.env.example); `STUDIO_TIMEZONE` and `STUDIO_NAME` are written into
a new database at bootstrap.

## The demo — no account needed

```shell
uv run python scripts/start.py --demo   # the page on http://127.0.0.1:8010
uv run python scripts/demo_daily_run.py --keep   # one day in a temporary folder, in the console
```

The demo is a separate studio (`data/demo/`, its own database, films and logs) where every
vendor is simulated: a scripted language model that answers in the studio's schemas, local
pictures and a synthetic voice, no motion vendor, no YouTube. A day runs through all thirteen
stages to a real MP4 that FFmpeg encodes and quality control measures. The page carries the
banner **DEMO — furnizori simulați, nimic nu se publică**; publishing, payments, connecting
accounts, switching to PRODUCTION and the paid shooting-sheet steps answer 403; the process
refuses any connection beyond this machine. The demo never marks a provider as working, and it
refuses to start on `data/studio.db`. Its film is a pipeline demonstration, not a sample of
what Runway and ElevenLabs produce.

## Connecting the providers

All connections are made in the page and their keys are stored encrypted beside the database
(`data/studio.credentials.key`), never in `.env`.

- **Language model** — Setări → Furnizori AI (Ollama, OpenAI, Anthropic, …). The seeded
  employees point at the first studio's Ollama Cloud models (`glm-5.2:cloud`, `kimi-k2.6:cloud`,
  `qwen3-coder:480b-cloud`), recorded NOT_CONFIGURED and never contacted. After connecting your
  provider and syncing its models, give each employee a model in Setări → Angajați (or run
  `uv run python scripts/apply_llm_allocation.py`, which applies `config/workforce_seed.json`'s
  allocation to employees nobody configured). Set `STUDIO_AGENT_DAILY_TOKEN_BUDGET` for a paid model.
- **RunPod** (optional cloud stills/video; [connection guide](docs/RUNPOD_INTEGRATION.md)), **Runway** (stills and motion) and **ElevenLabs** (narration) — Setări → Video și sunet. Record
  on each connection whether your plan allows commercial use: until you do, quality control
  passes a film for a private upload only.
- **YouTube** — Setări → Conturi și e-mail, with an OAuth client from **your own** Google Cloud
  project, then bind the account to a channel in Distribuție → Sloturi de canal. Google limits:
  a consent screen left in "Testing" expires refresh tokens after 7 days, and an unaudited
  project's uploads are forced private. Both, and what the studio does about each, are in
  [docs/project/YOUTUBE_CONNECTIONS.md](docs/project/YOUTUBE_CONNECTIONS.md).
- **Research sources** — Cercetare → Surse și afirmații: the hosts the Researcher may read.
- **Music** — `config/music_library.json` (or `STUDIO_MUSIC_LIBRARY`): only tracks you are
  licensed to use commercially, each with its file's SHA-256. It ships empty.

## Your controls

| Control | Where | What it does |
|---|---|---|
| STOP | the AUTONOMIE switch | Nothing scheduled fires and no paid loop starts its next scene. |
| Mode | Guvernanță | MANUAL (you move each stage), SUPERVISED (routine runs, external writes ask), AUTONOMOUS_CEO (the Director acts within policy). T4 actions are always yours. |
| Environment | the MEDIU switch | TEST buys nothing from real vendors in the daily run; PRODUCTION climbs the shooting sheet. |
| Paid-step rule | the shooting sheet, «Când te întreabă un pas plătit al unui film» | EVERY_PAID_STEP (default: every stills, hero, motion and redo step asks you), OVER_USD (asks above your amount), MODE (follows the mode). |
| Budgets | Autonomie → Buget și cheltuieli | A daily budget is **required** for MODE or OVER_USD in PRODUCTION; without one the step is refused (BLOCKED_NO_BUDGET). |
| Film ceiling | `STUDIO_FILM_BUDGET_USD` | What one film may spend in all. The default (motion budget + a six-scene stills cap, 15.24 USD) is below a four-scene 10-second film at 1080p: set your own. |
| Publishing | Distribuție, per channel | Visibility (private/unlisted/public), category, language, Shorts length. |

Every change is a versioned command in the ledger; the studio never changes your policy itself.

## The daily job

The day runs at `STUDIO_DAILY_RUN_HOUR_LOCAL` (05:00) in `STUDIO_TIMEZONE` once you start the
schedule (Rularea zilei → Pornește programarea zilnică). One worker runs per database: a second
studio process on the same database serves the page only. Stopping the studio ends the day after
the scene in flight, recorded INTERRUPTED; an interrupted day is never re-run by the clock, you
start a new one. Your "yes" to a paid step continues that film at once, not at the next 05:00.

## Running as a service

**Windows** — a Scheduled Task (PowerShell as administrator, your own act):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_studio_service.ps1
powershell -ExecutionPolicy Bypass -File scripts\uninstall_studio_service.ps1
```

It runs `start.py --skip-frontend` at logon and startup and restarts it on failure. Limit: the
vault key is wrapped with DPAPI for your Windows account; `-RunWhenLoggedOff` (S4U) may not be
able to unwrap it, so the supported unattended mode is an interactive logon with automatic
sign-in. The studio then starts DEGRADED and the day is blocked with a letter rather than run on
unreadable keys. The service does not activate the daily job and does not keep the PC awake.
The default (interactive) task starts the studio without the live headquarters. Graphics
require `--graphics` in the launch command and an interactive desktop; an S4U task runs in
session 0 and skips them even when requested.

**Linux** — a systemd user unit, [scripts/amn-ai.service](scripts/amn-ai.service) (installation
steps inside). On Linux the vault key is stored **unwrapped** with mode 0600 beside the database:
keep the disk encrypted. This path is tested by the suite, not yet on a real Linux machine.

## Backups, restore, disk

- `uv run python scripts/backup.py` — an online copy of the database (safe while the studio
  runs), checked, with the wrapped key beside it; `--list` lists them. The studio also copies
  itself daily at `STUDIO_BACKUP_HOUR_LOCAL` and before every migration.
- `uv run python scripts/restore.py` — stop the studio first. The restored studio comes back
  STOPPED, in TEST, with the daily job off; re-enter keys that cannot be read (`--restore-key`
  only on the same Windows account).
- **Films are not in the backup**, only their list: copy `STUDIO_MEDIA_ROOT` to another disk.
  `scripts/media_inventory.py` lists media folders the database no longer knows (dry run).
- A paid step refuses to start below `STUDIO_MIN_FREE_GB` (20) free on the media disk.

## Health and logs

`GET /health/live`; `GET /health/ready` answers 503 when the worker has stalled, the disk is low,
FFmpeg is missing or the newest backup is older than `STUDIO_BACKUP_MAX_AGE_HOURS` (codes only;
the page says it in words). The full log is JSON lines in `data/logs/studio.log`, rotated; keys
and tokens are never written to it.

## Upgrading

Stop the studio, replace the code (pull, or unpack a new release archive over the folder), run
`start.py` again. The bootstrap copies the database before it migrates; the studio refuses to
start on a schema it was not written for.

## Verify

```shell
uv run python scripts/check_all.py          # the whole chain, Idle priority, refuses under 16 GB free
uv run python scripts/check_all.py --quick  # without the film-making tests
```

Or step by step: `scripts/check_docs.py`, `scripts/check_secrets.py` (fails on any finding not
reviewed in `.secrets.baseline`; mark a fake key in a test with `# pragma: allowlist secret`),
`ruff check .`, `ruff format --check .`, `mypy`, `pytest` (`-m "not slow"` for the quick lane),
`npm run check --prefix frontend`, `npm test --prefix frontend`. Build the page into a scratch
folder (`npx vite build --outDir <tmp>` in `frontend/`) when a studio is serving `frontend/dist`.
`STUDIO_REQUIRE_FFMPEG=1` turns an FFmpeg skip into a failure; `STUDIO_REAL_ENCODE=1` keeps the
production encode in every test. Every test fakes every vendor and refuses non-loopback sockets.
The GitHub Actions workflow (Windows and Linux) exists but has not run: the repository has no
remote yet.

## Release archive

`uv run python scripts/make_release.py [--with-dist] [--with-tests]` writes
`output/release/amn-ai-<version>.zip` and its `.sha256` from an allowlist: the backend, the
migrations, the page sources, configuration, the operator scripts, this README, the operator
guide and the notices. It refuses to include `.env`, keys, databases or media, and stops when a
file names this machine's folders.

## Honest limits

- Local only: no TLS, no multi-user access, no remote deployment. Do not expose the port.
- No test proves a film good. The first capped paid film under EVERY_PAID_STEP is the real test.
- Vendor billing and Google's behaviour are known only from fakes until a real run.
- Licences: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Vendor-generated media are governed
  by your plans with those vendors.

## Documentation

The normative specification is [docs/architecture](docs/architecture/README.md) (start at
[00_MASTER_PROMPT](docs/architecture/00_MASTER_PROMPT.md)); decisions are in
[16_DECISION_LOG](docs/project/16_DECISION_LOG.md). Architecture changes require a recorded
decision and an explicit index hash update (`scripts/check_docs.py`).

## API

Every route except `/health/*`, the YouTube OAuth callback, the title's kept frame and
`GET /api/v1/owner/local-session` requires `Authorization: Bearer <STUDIO_OWNER_TOKEN>` (sockets
take the key as their first message, never in the URL). The last hands the key only to a loopback
peer asking at the studio's own loopback address with the page's own `X-Studio-Local-Session: 1`
header, no proxy header and no foreign Origin, with
`STUDIO_HOST` on loopback and `STUDIO_LOCAL_AUTO_LOGIN` on; everyone else gets the 404 of an
unknown path (`backend/app/local_session.py`). The page is the API's client: `GET /api/v1/snapshot`, `GET /api/v1/events`, the
Owner's commands under `/api/v1/owner/*` (versioned, idempotent by `command_id`; a stale version
answers 409), and one router per area under `/api/v1/` (agents, providers, settings, factual,
media, publishing, analytics, economy, youtube, workforce, story, runbook, scheduler, office).
