# AMN-AI: instructions for Claude Code

## Scope and reading order

This is an existing local, single-owner AI film studio. Improve it incrementally; do not
restart it, introduce a competing backend, or turn it into a hosted/multi-user service.
The Owner's Windows 11 application is the compatibility target. This repository contains
source and sanitized test inputs, not the Owner's production installation or state.

Read AGENTS.md, README.md, docs/architecture/README.md,
docs/architecture/00_MASTER_PROMPT.md, docs/project/CURRENT_STATUS.md,
docs/project/13_ROADMAP_TODO.md, docs/project/16_DECISION_LOG.md and the relevant subsystem
specifications. The current scope is the side-view pixel office. Historical top-down/3D
and Treasury requirements do not supersede the current Owner decisions.

## Architecture and entry points

- `start.cmd` and root `start.py`: Windows startup; delegate to `scripts/start.py` through uv.
- `scripts/start.py`: locked dependencies, bootstrap/migrations, frontend build, preflight
  and the loopback web server. Do not run this against a production database in an audit.
- `backend/app/main.py`: FastAPI `create_app`, HTTP routers and WebSocket event delivery.
- `backend/app/config.py`: validated `STUDIO_*` settings; `.env.example` is the template.
- `backend/app/db.py`, `backend/migrations/`, `alembic.ini`: SQLAlchemy/SQLite and Alembic.
- `backend/app/workflows/`: durable task claims/leases, retries, watchdog and outbox publisher.
- `backend/app/runbook/`: staged daily runs, preflight, continuation and recovery.
- `backend/app/agents/`: Director and employee tasks, structured responses, reviews and memory.
- `backend/app/media/`: scene planning, prompt compilation/rewrites, purchases, takes,
  FFmpeg assembly, quality checks, Director second look and repair decisions.
- `backend/app/integrations/` and `backend/app/providers/`: credentials vault and adapters,
  including Ollama/local media and optional existing cloud vendors.
- `backend/app/publishing/`, `backend/app/youtube/`: provenance/rights/policy-gated publication.
- `backend/runpod_worker/`: existing GPU worker source, pinned manifests and workflows;
  this is not a command to deploy or buy GPU time.
- `frontend/src/main.js`, `frontend/src/pixel_*.js`, `frontend/src/style.css`: Vite/JS,
  Tailwind and the browser pixel studio; public assets are in `frontend/public/`.
- `config/`: workforce/role contracts, presentation, workflow, model and price templates.
- `tests/` and `frontend/tests/`: offline regression suites; production-derived inputs
  have been sanitized for this repository.
- `docs/architecture/`: normative, hash-checked specifications. Do not bypass integrity checks.
- `art-source/` and `Agents ID and Bible/`: retained art sources, licences and character bible.
  Blender/Unreal sources are archival and not required to run the active interface.

## Existing agent orchestration

The eight seeded roles are Sarah (Director), Dr. Aris (Researcher), Elena (Fact Checker),
Marcus (Script Writer), Lyra (Voice Artist), Kael (Video Editor), Vera (Publisher) and
Nadia (Accountant). Consult `config/workforce_seed.json`, `config/role_contracts.json`
and the agent/workflow modules for the actual tools and assignments.

The Director controls the research-to-film workflow and QC/repair decisions within Owner
policy. Work must remain durable across process restarts and independent of an open page.
Backend records and committed domain events are authoritative; UI animation never proves
that a model, GPU job or publication ran. Structured model output must validate before
authorizing any action. An intent, a capability and a verified result are different facts.

Preserve Owner STOP, GPU holds, autonomy modes, credentials encryption, budgets, paid-step
approvals, idempotency, film leases, refusal guards, rights and factual provenance. Developer
AUTORUN is not product permission. Never manufacture progress, FPS, a provider success or QC pass.

## Windows 11 local development

Use a short checkout path, Git, uv, Python 3.12–3.14 (the local pin is 3.14.8), Node.js
22.12+ and npm. Python's SQLite runtime should contain the WAL concurrency fixes described
in README.md. Preserve Python's declared compatibility range and the locked dependencies.
FFmpeg/FFprobe with the required encoders/filters are required for actual film operations.
DPAPI-bound production credentials remain on the Owner's Windows account and cannot be
used by a cloud VM. Models and licensed music are machine-managed, outside Git.

In a separate development checkout:

```text
uv sync --locked
npm ci --prefix frontend
uv run python scripts/check_docs.py
uv run python scripts/check_secrets.py
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -m "not slow"
npm run check --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
```

For an intentional fresh local studio, `start.cmd` creates its own `.env`, random Owner
token and database. It starts STOPPED/MANUAL/TEST with scheduling dormant and no connected
vendor. Never copy production `.env`, databases, credentials keys, accounts or media into a
development checkout. Do not start or restart the Owner's existing studio during an audit.

## Cloud audit limits and checks

Follow `docs/CLAUDE_CLOUD_SETUP.md`. A cloud VM cannot reach the Owner's localhost Ollama,
ComfyUI, Windows DPAPI, local models, drives, GPU, Unreal or production database. Use existing
transport fakes and temporary databases. `tests/conftest.py` refuses external sockets and
isolates media storage; preserve those guards. Do not call real models/vendors to make a test pass.

The small YuNet ONNX model is deliberately excluded from Git. Its source, SHA-256 and MIT
licence remain in the media source/notices. Without it, face measurement returns NOT_RUN
and production quality gates remain closed. Model-dependent tests must report their skip
or failure honestly; do not weaken the gates. Full film/browser tests additionally need
FFmpeg/FFprobe and installed Playwright browsers. Run them only in a disposable environment.
The inherited GitHub workflow is manual-only in this publication to avoid implicit cloud jobs.

## Change safety and delivery

- Work on a feature branch, such as `claude/<task>` or `codex/<task>`, and create a Pull Request.
  Do not push development directly to main, merge automatically or force-push.
- Keep changes compatible with local Windows startup, filesystem paths, locks and DPAPI,
  while retaining supported Linux/cloud test paths. Use pathlib and existing abstractions.
- Never delete, move or overwrite the original installation, databases, models or artwork.
  Never run restore/reset/cleanup/migrations against production during cloud development.
- Keep Ollama and local AI integrations. Do not replace them with paid cloud APIs without
  explicit Owner approval. Existing optional adapters must remain policy-gated.
- Do not deploy, buy services, enable paid resources, generate GPU media or publish a film
  as a side effect of development. No unattended production connections belong in cloud tests.
- Never commit secrets, production data, licensed music, model weights, dependency folders,
  logs, backups or generated outputs. Templates use empty fields or clearly synthetic values.
  Do not print secret values or automatically bless new secret-scan findings.
- Record claims/outcomes in docs/project/ and update the relevant roadmap/changelog/decisions.
  Preserve architecture hashes unless an explicit specification change is reviewed and recorded.
- Run checks appropriate to the change. Report actual commands, outcomes, skips and limits;
  mocks cannot establish live vendor/media/publishing acceptance.
