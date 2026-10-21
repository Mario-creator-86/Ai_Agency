# Daily dashboard and UI dialog finish

Scope: frontend only, extending the Owner's 16–17 October UI requests. No server restart, backend changes, policy changes, paid production or publication.

## Delivered behavior

- Daily budget reads the existing `GET /economy/budget` DAILY row. Spent/limit, available funds and spent percentage reuse canonical vendor costs. Reservations reduce availability but are not added to spent or counted twice. Subscribed LLM token costs remain outside the vendor budget. Missing limit/data stays explicit.
- Completed-today counts successful agent task executions from paginated `agent.run_completed` records, deduplicated by run ID, using the completion event timestamp (or explicit finished_at). It is distinct from the scheduler's capped queue. Reads begin at Bucharest midnight and continue by cursor; live completion events update immediately, with 30-second polling as fallback. Midnight clears old data before a fresh read; DST boundaries are civil days, not fixed 24-hour intervals.
- Active projects show real names, truncate with full hover titles, and show at most three lines including +N for overflow. Rendering films are included; rejected and released films are excluded.
- One YouTube card keeps each channel's identity, views, subscribers, measurement timestamp and unavailable/stale indication. Existing connection matching and refresh throttling are retained; no unavailable value becomes zero.
- One persistent Sunet ON/OFF switch controls UI effects and preview mute. The volume slider is removed; film playback is available from Producție media. Eight locally served CC0 samples cover typing and notifications, task/project completion, warning and error; original quiet synthesized office air remains. OFF cancels volume automation, cues and sources; reload respects browser gesture restrictions. No generated media file is edited.

## Dialog audit retained

Producție media (both tabs, detail and shooting sheet), Cercetare (all five sections), Distribuție, Angajați, Jurnal, Rularea zilei, Autonomie (all sections), all six Settings sections, Decizii (waiting/history), all eight agent inspectors, expanded inspector, correspondence, live popup and studio player were read-only reviewed. 78 final captures/checks at 2542/1366/768/390 px plus earlier 102 audit views; no page errors or dialog overflow. Fixed rejected status inheriting full error-panel layout, section offsets relative to the wrong ancestor, narrow section-menu/content overlap, detached primary-model picker, and lost keyboard focus after asynchronous channel loading. Common dialog surfaces/buttons/rails match dashboard styling; accessible titles and media keyboard tabs added.

Evidence: `output/ui-dialog-audit-2026-10-16/final-audit.json` and screenshots; `output/ui-dashboard-daily-2026-10-17/` contains dashboard, sound, budget, unit/browser and install evidence. Sources and licenses: [PIXEL_STUDIO_ASSETS.md](PIXEL_STUDIO_ASSETS.md).

## Verification

- Frontend unit suite, TypeScript and isolated browser suites cover budget, pagination beyond 100 completions, deduplication, midnight/DST, unknown versus zero, narrow layouts, dialogs and independent sound ON/OFF behavior.
- Existing budget/reconciliation Python suites: 20 passed. In-process fixtures only; no listening test server was started.
- Actual running-backend review: only GETs allowed; all mutations, WebSockets and other origins blocked in the review browser. Dashboard inspected at 2542/1920/1366/390 px. Sound samples decoded in a real browser; nonzero signal measured on ON, master gain zero/no voices/suspended context on OFF, persisted states and refused resume handled. A 30-event burst emitted one cue.

The completed count measures successful agent runs, not unique films or scheduled housekeeping jobs. YouTube statistics are periodically refreshed, and cached values keep their timestamp. Browser playback can require an initial user interaction. Existing bundle-size warning remains.

## Installed verification

980 frontend unit tests, TypeScript, 20 budget/reconciliation tests and five isolated browser suites passed. Actual installed page and eight sound files verified over HTTP, with matching hashes and source build record (`stale=false`). No server start/restart command was run. A pre-install check found the running process had changed since the older dialog audit; installation used PID 41588 and verified that same process/creation timestamp afterward. Original/during-install identities are retained in install-verification.json. Existing user changes in style.css and the agency watch state were preserved.
