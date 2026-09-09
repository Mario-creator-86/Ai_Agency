# Foundation verification — 2026-09-09

Classification: **LOCAL INTEGRATION** and **UNIT**. No real-provider, staging or production claim.

| Check | Result |
|---|---|
| `uv run pytest` | 26 passed, 0 failed, 0 skipped |
| `npm test --prefix frontend` | 3 passed, 0 failed |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed |
| `uv run mypy` | Passed, 9 application source files |
| `npm run check --prefix frontend` | Passed |
| `npm run build --prefix frontend` | Passed, Vite 7.3.6 |
| `uv lock --check` | Passed |
| `uv run python scripts/check_docs.py` | 83 original documents accounted for; 78 architecture hashes valid |
| `uv run python scripts/check_secrets.py` | Passed; exact indexed checksums recognized as non-secrets |
| `npm install --prefix frontend` audit | 0 known vulnerabilities reported at install |

Environment: Windows, Python 3.14.3, SQLAlchemy 2.0.52, Alembic 1.19.2, FastAPI 0.141.1.
Dependency resolution is recorded in uv.lock and frontend/package-lock.json.

Backend coverage includes authenticated API reads/writes, validation/privacy, persistent STOP,
same-command replay, competing stale writes, transactional rollback, immutable history, migration
repeat/schema match, pagination, unavailable DB readiness, unmigrated startup refusal and static UI.

Document checks are tested with copies: unexpected Master Prompt edits fail; missing Master Prompt
fails. Original architecture files are never modified by tests.

Browser verification used Playwright CLI on the actual local service:

- Owner password field and login reach the real backend snapshot.
- Clearing STOP creates a committed event and leaves Manual mode.
- Re-enabling STOP persists and increases the event cursor.
- Desktop and 390x844 mobile screenshots inspected; mobile has no horizontal overflow.
- Offline mode shows stale data, disables the control, and displays a Romanian connection message.
- Returning online resumes snapshots and clears the transient connection warning.
- Reload clears the in-memory Owner credential and returns to login.

Artifacts: `../../output/playwright/studio-desktop.png`, `../../output/playwright/studio-mobile.png`.
Generated artifacts are not versioned source. A missing favicon was fixed; deliberate offline requests
produce expected browser network errors. Upstream Starlette/httpx/AnyIO emit two deprecation warnings
in Python tests; no tests fail. Hosted GitHub Actions has not run because no remote was pushed.

Limits: no throughput/burn-in validation, production renderer, worker shutdown/recovery, provider
contracts, media QC, public publishing, financial ledger or external checkout testing is claimed.
