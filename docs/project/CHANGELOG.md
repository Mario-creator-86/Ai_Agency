# Changelog

## Phase 11 — Financial evidence and the VR$ ledger — 2026-09-10

- Added `backend/app/economy/`: immutable double-entry books in VR$, posted only from real
  external evidence. Seven tables (`0016_phase11_economy`), eleven Owner-only routes, and a
  **Trezorerie** panel in the office.
- The four invariants the economy exists for are enforced by schema and service, not convention:
  one verified dollar mints exactly one VR$ once; forecasts and pending payouts can never be
  spent; a reversal posts a mirror and never deletes; the books always balance. Money is integer
  micros, and a non-USD amount without a recorded FX snapshot is refused rather than converted at
  an invented rate.
- Provider costs are mirrored too, so the treasury shows what running the studio costs and can
  report a deficit honestly. Estimates are shown but never posted.
- No route in the entire API pays, buys, transfers or checks out; a test asserts it over the
  whole OpenAPI surface.
- `treasury` moves from NOT_IMPLEMENTED to PARTIAL in the snapshot module map; `procurement` and
  `financing` stay NOT_IMPLEMENTED. Evidence: `PHASE11_ECONOMY.md`.

## Agency identity: AMN-AI — 2026-09-10

- Named the agency **AMN-AI (Autonomous Machine Nexus — Artificial Intelligence)** everywhere it is
  stated: browser tab, share metadata, top bar, sign-in screen, footer, the 2D building's neon sign,
  FastAPI title, `STUDIO_NAME` default, simulated channel title and Channel B tagline, README,
  AGENTS, launcher scripts, and the distribution names (`amn-ai`, `amn-ai-ui`) with both lockfiles
  regenerated — dependency resolution unchanged (44 packages identical, `uv sync --locked` and
  `npm ci` clean).
- Added the logo as a proper asset set derived from the source artwork: top-bar mark, sign-in
  lockup with a transparent ground, `favicon.ico`, `favicon-32.png`, `apple-touch-icon.png` and a
  512 px master used as `og:image`. Quantised from a single 1.16 MB PNG to ~8 kB per page load.
  Removed the previous brand's unreferenced `favicon.svg`.
- Added `scripts/rename_studio.py`: bootstrap deliberately never rewrites an existing studio name,
  so renaming is an explicit Owner act that appends a `studio.renamed` event beside the row update.
  Applied it to the local studio; the workspace H1 now reads AMN-AI because the database says so.
- Documented the whole identity in `BRAND_AMN_AI.md`. Tests now assert the brand assets the page
  actually references and cover the rename's audit trail, idempotence and refusals.

## Pixel office v2 — 2026-09-10

- Rebuilt the 2D office's visual layer to a modern pixel-art standard, frontend only: new
  `office_palette.js` (hue-shifted five-tone ramps, one material story per department),
  `pixel_sprites.js` (outlined compiled sprites, glow cache), `office_characters.js` (26×34
  seated sprites, role costumes, deterministic looks, honest state poses), `office_rooms.js`
  (room shells, baked light, nine department interiors, workstation occlusion layers),
  `pixel_font.js`; `office_engine.js` rewritten around three cached layers with the same exports.
- Designed the system in Figma before implementing (palette variables, quality-bar floor at 4x,
  character and HUD components, building/layout spec).
- Scene chrome: slim dark bezel and high-contrast dark controls; admin panels unchanged.
- Removed the superseded `office_art.js`. Added 5 frontend tests (43 total), a standalone room
  preview harness and screenshot/FPS review scripts. Backend, API, events and data untouched.

## Foundation 0.1 — 2026-09-09

- Read the full original 83-document specification package; established its implementation baseline.
- Separated architecture (78 documents) and live project tracking (5 original documents) at Owner request.
- Added indexed document hashes, link/inventory validation and failure tests for accidental spec edits.
- Added FastAPI/SQLAlchemy/Alembic backend, configured local credentials, persisted initial world and
  Owner policy, immutable events, idempotent/versioned STOP command and private snapshot/event routes.
- Added responsive HTML/Tailwind/JS foundation shell, truthful unavailable modules and stale-state UI.
- Added locked dependencies, structured logs, security headers, CI baseline and secret scan.
- Verified 26 Python tests, 3 JS tests, lint/types/build, schema upgrade, concurrency, restart and browser.
- Preserved all unimplemented core/V4/V5 requirements; no LLM/media/publishing integration claimed.

## v2 — 2026-09-09

### Strengthened realism
- Added strict Intent → Policy → Capability → Execution → Verification → Commit model.
- Added tool/action receipts.
- Added UNKNOWN provider/capability states.
- Added realistic local-PC vs always-on deployment constraints.

### Strengthened Director
- Defined broad CEO responsibilities.
- Added self-permission/self-guardrail restrictions.
- Added strategy-change and workforce-evaluation safeguards.
- Added provider discovery vs actual onboarding distinction.

### Strengthened employees
- Added Role Contracts.
- Added capability requirements and least privilege.
- Added safe firing with in-flight task handling.
- Added explicit model-upgrade vs employee-replacement semantics.

### Strengthened automation
- Added durable workflow requirements.
- Added scheduler safety.
- Added leases/locks, idempotency, outbox, retry/backoff, circuit breakers and watchdogs.
- Added external side-effect reconciliation.

### Strengthened UI truthfulness
- UI success only after backend verification.
- Added snapshot/replay, duplicate/out-of-order event handling.
- Added persistent office world state.

### Strengthened research/security
- Added prompt-injection defense.
- Added memory provenance and poisoning controls.
- Added source freshness/staleness.

### Strengthened media/serial
- Added Character Bible and provider-capability constraints.
- Added live operational vs dramatized serial dialogue separation.
- Added media rights/provenance requirements.

### Strengthened operations
- Added provider contract testing.
- Added failure/recovery playbook.
- Added backup/restore, disk retention and deployment guidance.
- Added master acceptance checklist and risk register.

## v3 — 2026-09-09

### Deep file-by-file hardening
- Re-reviewed every v2 document.
- Added Policy Kernel and independent hard gates.
- Added bounded agent communication, deadlock and rework limits.
- Added daily preflight and admission control.
- Added compensation/manual repair model.
- Added prompt/context/memory lifecycle architecture.
- Added model drift and role-suitability revalidation.
- Added multi-objective Director scorecard.
- Added public character alias / provider-brand separation.
- Added WorldBuilder contract for dynamic office growth.
- Added narrative privacy/sanitization.
- Added anti-repetition/novelty gates.
- Added deterministic media fallback.
- Added CI/CD, feature flags and rollback requirements.
- Added reliability SLOs and burn-in.
- Added data privacy classification.
- Added transfer/sale-readiness requirements.
- Added dedicated v3 specifications for governance, prompts/memory, tool permissions, evaluation, reliability, security, public community, IP, daily runbook, world evolution, schema versioning and launch readiness.


## 2026-09-09 — V4 Organizational Expansion
- Added dynamic Department Factory and manager delegation.
- Added Marketing & Communications architecture for YouTube, TikTok, Instagram, Facebook and Telegram.
- Added same-day truthful teaser → next-day Office Serial loop.
- Added marketing attribution and experiments.
- Added Market/Competitive Intelligence.
- Added HR/People Ops, persistent fictional personas, birthdays and relationship graph.
- Added Finance/Accounting/FinOps separation.
- Added Legal/Rights/Compliance department.
- Added future Advertising/Paid Media/Sponsorship architecture.
- Added Company Calendar, milestone triggers and team-building/no-production event mode.
- Added organizational-bloat controls and capacity planning.
- Extended data model, events, commands, tests, UI mappings, governance and acceptance criteria.


## 2026-09-09 — V5 Economy Expansion
- Added 1:1 USD ↔ VR$ market-anchored virtual economy.
- Added financial truth layers and double-entry ledger requirements.
- Added revenue settlement/reversal/idempotency rules.
- Added Owner capital contribution and Owner loan models.
- Added market-referenced virtual financing with debt-capacity gates.
- Added Procurement + VendorShop + NEW/USED current market quote sourcing.
- Added Asset Architect and market-priced office asset lifecycle.
- Added treasury dashboard, runway, burn, forecasts and virtual financial statements.
- Added strict no-real-money-spend boundary.
- Added financial events to UI, Story Engine and marketing provenance.

## Post-audit remediation — 2026-09-09

Answers `docs/project/AUDIT_2026-09-09_EXTERNAL.md`. Decisions recorded as D-AUDIT-001/002.

### Truthfulness (breaking behaviour changes)
- Channel slots seed as `NOT_CONFIGURED` with no remote ID; status is derived from real
  configuration only. Previously seeded as `CONFIGURED` with invented channel IDs.
- Publishing without `STUDIO_YOUTUBE_*` credentials now returns 503 `PublisherNotConfigured`.
  The silent fallback to the simulated adapter is removed.
- Simulated uploads are recorded as `PUBLISHED_SIMULATED` with `sim:` identifiers and no platform
  URL, and are labelled as such in the UI.
- The renderer no longer writes a placeholder file named `.mp4`. It encodes a real H.264
  1080x1920 video with FFmpeg or fails with `RenderEngineUnavailable` (HTTP 503).
- QC measures the file with `ffprobe` and recomputes the provenance digest instead of trusting the
  renderer's own metadata; placeholder visuals are blocked from publication; the character-drift
  check reports `NOT_IMPLEMENTED` instead of passing.
- `POST /media/storyboards/sample` replaced by `POST /media/storyboards/demo-fixture`, which
  creates `UNVERIFIED` claims only.

### Correctness
- Fixed `DetachedInstanceError` in the FFmpeg render path (ORM objects used after session close);
  that path had never executed successfully.
- Gate refusals now persist the `BLOCKED_GATE` record and `publishing.gate_failed` event.
- Missing media asset or channel returns 404 instead of a 500 database integrity error.
- `GET /publishing/channels` no longer writes; seeding moved to `POST /publishing/channels/seed`.
- YouTube upload is chunked and resumable (`Content-Range`, 308 handling); synthetic-content
  disclosure is sent; `reconcile_upload` is invoked before any retry.
- QC minimum score (0.90) is actually enforced by the publishing gate.
- Removed a hardcoded Windows storage path from `assembler.py`.
- Fixed a `TypeError` in `scripts/bootstrap.py` that broke first-time `.env` creation.

### Found and fixed while running the application under Playwright
- **WebSocket gateway repaired.** `websockets` was missing from the dependencies, so uvicorn
  answered the `/api/v1/ws` handshake with 404 and the 2D office never received live events.
  Added `websockets>=13,<16` to `pyproject.toml` and regenerated `uv.lock`. Run `uv sync`.
- **Script approval path added.** `generate_script_draft` produced `VERIFIED_PASS` scripts while
  storyboarding required `APPROVED`, and no approval endpoint existed — the real pipeline could
  not reach the media stage at all; only the fabricated `sample` endpoint could.
  New `POST /api/v1/factual/scripts/{id}/approve` re-runs the factual gate at approval time.

### Data correction
- Migration `0007_correct_fabricated_records` (data-only) repairs existing databases: fabricated
  channel identities cleared, simulated publications relabelled `PUBLISHED_SIMULATED` with their
  dead YouTube URLs removed, and all prior `PASSED` QC reports invalidated so they are re-run by
  the measuring gate. Startup now expects revision `0007`; Phase 7 analytics starts at `0008`.

### Developer experience
- `start.cmd` / `scripts/start.py`: one idempotent command that syncs dependencies, prepares the
  database, builds the frontend and starts the server, then prints a preflight report naming the
  integrations that are actually configured. It stops on a failed step instead of starting a
  half-built studio. README updated accordingly.

### Configuration
- `STUDIO_YOUTUBE_CLIENT_ID`, `STUDIO_YOUTUBE_CLIENT_SECRET`, `STUDIO_YOUTUBE_REFRESH_TOKEN`,
  `STUDIO_YOUTUBE_CHANNEL_ID` and `STUDIO_FFMPEG_PATH` added to `Settings` and `.env.example`.

### Tests
- New `tests/test_truthfulness_gates.py` (10 tests) locking the governance invariants.
- Render tests skip when FFmpeg is absent instead of exercising a fake path.
- 87 passed with FFmpeg; 85 passed / 3 skipped without it.

### Documentation
- `CURRENT_STATUS.md` corrected: Phases 4, 5 and 6 are marked PARTIAL with their exact unmet
  acceptance criteria. `PROJECT_STATE.json` brought up to date (was five phases stale).

## Interface consistency pass — 2026-09-09

Decision D-DESIGN-001.

- **Single colour system.** `frontend/src/style.css` rebuilt around `:root` design tokens derived
  from the original template. The 97 ad-hoc colour literals are gone; components reference tokens.
- **Dialogs re-skinned** from the Tailwind dark theme to the studio's paper surface, with tokenised
  borders, inputs, buttons, tabs, cards and badges.
- **Semantic state colours** unified: published / validated / simulated / blocked and channel
  statuses now use consistent background-border-ink triples and stay mutually distinguishable.
- **2D office** framed like the template's office scene; structural scene colours retinted from
  slate blue to the brand greens. Department accents and character art left untouched.
- **Icons removed.** All pictographic emoji dropped from buttons, headings and badges; labels
  rewritten in sentence case.
- **Media panel corrected**: it showed the storyboard UUID under the label "Provenance SHA-256" and
  scored the unimplemented continuity check as 0%. It now shows the measured resolution, duration
  and codec, the real verified digest, and an em dash for the check that does not exist.
- **Accessibility**: `scratch/verify_design.mjs` measures computed contrast in the running page;
  three tokens were darkened to clear WCAG AA. 14/14 design checks and 27/27 functional checks pass.
- **Toolbar highlight fixed.** `cam-btn-active` was hard-coded on the "Cercetare" button, so it
  looked permanently selected. The highlight is now bound to whether that panel is actually open.
- **Leaving fullscreen restores the office.** `.office-scene-container` had no height of its own,
  so it was sized by the canvas while the canvas was sized by it; on exit nothing shrank the canvas
  back and the scene stayed at fullscreen dimensions. The container now has a definite responsive
  height and the engine resizes across two animation frames.
- `scratch/verify_fullscreen.mjs` (new, 10 checks) measures the canvas before, during and after a
  fullscreen round trip and asserts the toolbar highlight follows the open panel.

## Office renderer rebuild — 2026-09-09

Decision D-DESIGN-002. `frontend/src/office_engine.js` rewritten (~2,200 lines).

- **Scene**: dusk sky with stars, moon and drifting clouds; two parallax skylines with lit
  windows; a street at the foot of the building with traffic, pedestrians, swaying trees, lamp
  light pools, a bus stop and planters. All of it seeded scenery, connected to no data.
- **Building**: cutaway shell with structural columns, parapet, roof plant, extractor fans,
  antenna beacon, satellite dish, neon sign, and a glass elevator whose cab travels the shaft.
- **Interiors**: every department has its own furniture — executive bookshelf and awards, research
  evidence board with pinned cards and string, storyboard wall, vocal booth with foam, boom mic,
  mixing desk and VU meters, edit bay with a scrubbing timeline, server racks with per-unit LEDs
  and fans, lounge with espresso steam and a water cooler, distribution console with a radar
  sweep. Empty wall runs are filled with cabinets, posters, whiteboards, coat racks and plants.
- **Characters**: appearance derived from the agent id (skin, hair style and colour, outfit,
  glasses, headset, build), so no two look alike; blinking, breathing, sipping and stretching on
  per-character phases; typing, thinking and sleeping driven strictly by backend state.
- **Rendering**: 1:1 offscreen world buffer blitted without smoothing for crisp pixel art; cached
  static layers; ceiling light cones, screen spill and lamp pools composited additively.
- Nameplates moved onto the floor slab with the state inline, so they no longer collide with the
  floor header below them.

## Office scene corrections — 2026-09-09

Decision D-DESIGN-003.

- **Backend layout**: ground floor doubled in height (200px) and re-divided; new `SHOP` zone
  `ad_shop` for street-level advertising sales, with no desks assigned. Building height 690 -> 740,
  layout height 800 -> 1000. `tests/test_phase3_office.py` extended: floor zones must not overlap
  and every desk must stand inside its own zone.
- **Street rebuilt below the building**: plinth, pavement, kerb, two-lane carriageway with a
  pedestrian crossing, far pavement with drains and planters. Pedestrians can no longer overlap
  the ground floor; `streetGeometry()` is exported and covered by two new frontend tests.
- **Human scale**: pedestrians drawn at the same size as the staff inside; cars ~90px, vans and a
  168px bus, with wheels and glazing to match. Street lamps moved to the building's flanks.
- **Lift**: parked and dark by default, labelled IDLE. It moves only when a workflow token changes
  floor, waits at the delivery floor, then returns to the ground floor.
- **Readability**: nameplates use double-scale type on an opaque plate; wall sconces added to
  tall floors; `M` and `W` glyphs redrawn.

## 2026-09-10 — Street and nameplate corrections (Owner feedback)

- **Bus**: removed the invented route number "12"; the destination blind stays blank.
- **Traffic**: vehicles spawn spread across their lane and follow their lane leader (speed matching
  plus a hard 24 px bumper clamp, seam-aware), so same-lane vehicles no longer pass through each
  other. `makeTraffic`/`updateTraffic` are exported and covered by three new frontend tests
  (spawn spacing, catch-up scenario, 15-minute mixed-timestep seam run).
- **Nameplates**: name type reduced from double to single scale on a light paper card with dark ink
  and a muted state line — smaller plates that stay readable over the dark floors.

## 2026-09-10 — State tag above the character (Owner feedback)

- The floor nameplate now carries the agent name only. The runtime state (IDLE, WORKING, …)
  floats above the character's head on a dark chip in the department accent, and the thinking
  bulb and sleeping Z marks were raised so none of the three overlap.

## 2026-09-10 — Settings agent LLM test + verified Ollama Cloud connectivity

- New `POST /api/v1/settings/agents/{id}/test`: one real run through the assigned model via the
  policy kernel; the Settings → Agenți cards gained a "Testează răspunsul" button that shows the
  model's answer or the block reason. Verified live against Ollama Cloud (glm-5.3-flash,
  gpt-oss:120b). New settings test; suite 16/16.

## 2026-09-10 — Whole-tree lint and type cleanup

- `ruff format` across the tree, 65 long lines wrapped (string content preserved), unused/unsorted
  imports removed, SQLAlchemy `== True` → `.is_(True)`, `zip(..., strict=False)`, import order fix.
- mypy: typed the ffprobe result and storyboard scene payloads (`dict[str, Any]`).
- Baseline now passes every README check: ruff, ruff format, mypy, pytest 137, frontend 11,
  docs integrity, secret scan.

## 2026-09-10 — Live speech bubbles with the agent's real answer

- `run_agent_task` emits `agent.message_sent` (transactional outbox) carrying the model's real
  output when a run succeeds with visible text; failed and text-less runs stay silent.
- The app lifespan now dispatches the outbox every second, so committed events are broadcast to
  WebSocket clients live (previously the dispatcher was never invoked and the office only saw
  the one-shot replay at connect).
- Activity log labels the event "Agentul a răspuns". Verified live: an API-triggered run made
  the answering bubble appear above the agent in the 2D office.

## 2026-09-10 — Research agent extracts claims from real sources; office fully live

- `agent.state_changed` (THINKING/IDLE) now flows through the outbox during runs, and
  pause/resume events were moved onto the outbox — state tags and pause animations in the
  2D office follow backend events live.
- New `POST /factual/sources/{id}/extract-with-agent`: the research agent reads the sanitized
  source (inert boundary, prompt-injection safe) and extracts schema-validated atomic claims
  via its assigned model. Claims stay UNVERIFIED; unparseable output is rejected; truncated
  JSON keeps only complete objects. The agent announces "Am extras N afirmatii..." as its
  speech bubble instead of raw JSON.
- Verified live end to end: real IANA page fetched via the retrieval adapter -> Dr. Aris
  (nemotron-3-super) -> 9 accurate UNVERIFIED claims -> bubble in the office.

## 2026-09-10 — Re-audit of third-party work; the seed stops claiming a healthy provider

- **Independent verification of the newest external work.** Re-ran the full battery against a
  clean checkout rather than trusting the tracking documents: pytest, ruff, ruff format, mypy,
  `tsc`, the frontend unit tests, the Vite build, the documentation hash integrity check and
  the three Playwright suites. Everything passed and nothing regressed. Read the new
  security-sensitive modules line by line — the credential vault, the Settings save/check path,
  the SSRF-hardened retrieval adapter and the research agent pipeline — and confirmed each of
  their stated properties holds in the code: a saved connection is `SAVED` and never verified,
  only a real probe writes `VERIFIED`, retrieval refuses anything but an allow-listed public
  HTTPS host on a DNS-pinned connection, and every extracted claim is stored `UNVERIFIED`.
  Confirmed the two edited architecture documents match their indexed hashes and that the
  decision log records the edit, as the process requires.
- **Fixed: the workforce seed asserted a health check that never happened.** A freshly
  bootstrapped studio recorded the local Ollama endpoint as `HEALTHY` with a health-check
  timestamp and three models as available and verified, on a machine with no Ollama installed —
  the same falsehood the Owner first reported about the YouTube channel. The seed now records
  the provider `NOT_CONFIGURED` and its models `SEEDED_UNVERIFIED` with no timestamps; only a
  real model sync may record health, availability or a verification time. See D-TRUTH-002.
- **Fixed: the seeded provider could not be verified at all.** It had no adapter registered, so
  every check failed with "no adapter registered" and the unverified state was permanent. The
  adapter is now registered at startup, Settings lists the endpoint with a working
  "Verifică și încarcă modelele" button, and an unreachable endpoint answers 503 with what went
  wrong instead of a generic internal error.
- Migration `0009_unverified_seeded_provider` withdraws the claim from existing databases.
- Baseline: ruff, ruff format, mypy, pytest 152 passed / 1 skipped, frontend 11, `tsc`, build,
  docs integrity; Playwright 27/27 + 14/14 + 10/10 + 8/8 (new provider-honesty suite).

## 2026-09-10 — Phase 7 analytics live; lift courier; the ground floor built out

- **Analytics wired, simulator deleted.** The Phase 7 module now runs: router mounted, models in
  `Base.metadata`, migration `0010_phase7_analytics`. Before wiring it, the deterministic
  analytics adapter — which invented view counts, retention and CTR from a hash — was removed
  outright, and the fallback that would have measured a never-uploaded publication under its
  internal row id with it. With no verified YouTube connection, ingestion answers HTTP 503 and
  says plainly that the studio does not estimate or simulate audience figures. This mattered
  more than a display bug: the learning loop reads these numbers back and turns them into the
  Director's recommendations, which change the topic and hook weights the studio writes to.
- **The YouTube Analytics adapter stopped ignoring the reporting window.** Every query used to
  send the same fixed date range, so an all-time report could be stored labelled "24h".
  Impressions and CTR are now read from YouTube's own metrics or reported as zero — never
  back-computed from views.
- **The lift carries someone.** A workflow token changing floor now runs a full delivery: the
  cab comes to the floor, doors open, a runner boards with the work, doors shut for the ride,
  and the runner walks the token to its new department. Doors part only at a floor, as a real
  lift's do. With no workflow running the cab still stands still.
- **The double-height ground floor was built out** — ducting, a service mezzanine with railing,
  pendant lights, and one wall fixture per department (rack status wall, canteen board, dispatch
  board, and an empty "YOUR AD HERE" hoarding over the shopfront).
- **Fixed: workflow tokens were drawn in the wrong departments.** The stage-to-position table
  was hardcoded pixels that predated the taller building — research appeared in the executive
  suite and publishing floated outside the wall — and because the lift is dispatched by the
  zone a token lands in, it also sent the cab to the wrong floor. Stages now name a department
  and the position comes from the layout the backend serves.
- Baseline: ruff, ruff format, mypy, pytest 163 passed / 1 skipped, frontend 17, `tsc`, build,
  docs integrity, secret scan; Playwright 27/27 + 14/14 + 10/10 + 8/8 + 9/9.

## 2026-09-10 — The research loop is usable; verification is independent; inspector fixed

- **Fixed (reported by the Owner): the agent panel showed a model nobody had assigned.** The
  "model" field was a fixed string in the HTML — every agent read `glm-5.2:cloud` whatever was
  chosen in Settings — and the office layout carried no model at all. Assignments now carry the
  agent's real model, its provider, and whether that provider has confirmed it; the panel
  distinguishes "not assigned", "assigned · unverified" and confirmed, and only a confirmed
  model enables a run. Settings now refreshes the office after every change, so a reassignment
  lands without reloading the page. See D-UI-005.
- **The Phase 4 research loop can be driven from the interface.** Fetch a source from a site you
  authorised, have the research agent read it, then verify each claim — all of it previously
  existed only behind `curl` and a shell script.
- **Independent fact-checking.** A second agent, never the one that extracted the claim, checks
  it against the stored source; the studio refuses when no independent agent exists rather than
  letting an agent confirm its own reading. A SUPPORTED or REFUTED verdict must quote the source
  verbatim, and **a verdict whose quote is not in the source is rejected whole — the claim stays
  UNVERIFIED**. UNCERTAIN was added so a checker that finds nothing can say so instead of
  guessing. Migration `0011` records who extracted and who verified each claim.
- **The retrieval allowlist is configuration, not application state.**
  `STUDIO_RESEARCH_ALLOWED_HOSTS` in `.env`, empty by default (retrieval off). The request
  carries no host field, and an entry naming this machine or a private range is refused at
  start-up.
- **Fixed: refusals were replaced by a generic message.** The interface now shows the server's
  own explanation — which host is not authorised, why a provider did not answer — instead of
  "try again", which was hiding the part that says what to do.
- Baseline: ruff, ruff format, mypy, pytest 199 passed / 1 skipped, frontend 17, `tsc`, build,
  docs integrity, secret scan; Playwright 27+14+10+8+9+9+18 = 95 checks.

## 2026-09-10 — Scripts written from verified claims, cited scene by scene

- **The script writer drafts only from SUPPORTED claims**, and every scene names the claims it
  rests on. A scene citing an identifier that was never supplied rejects the whole draft, not
  just that scene: the narration around an invented citation came from somewhere other than the
  evidence, and there is no way to tell how far that reaches. A topic with no verified claim
  produces no script at all rather than one that would be blocked later.
- **The spoken text is the attributed text.** The stored voiceover is assembled from the scene
  narrations, so there is no separate field a model could fill with something the citations do
  not cover.
- **The Research panel now shows scripts** scene by scene with their citation counts, and offers
  approval only on a draft that passed the factual gate. Approval re-runs that gate — a claim
  refuted since the draft was written blocks it — and the refusal now says how many claims
  stopped being supported instead of showing a raw exception.
- Baseline: ruff, ruff format, mypy, pytest 211 passed / 1 skipped, frontend 17, `tsc`, build,
  docs integrity, secret scan; Playwright 106 checks across 8 suites.

## 2026-09-10 — Media adapters, ready for the credentials the Owner will add

- **Real TTS and image adapters** (ElevenLabs, OpenAI Images) that call documented endpoints and
  return what came back. A vendor failure raises; there is no fallback asset, because a
  substitute would flow into QC and the publishing gate as though a provider had made it.
- **Every figure is measured from the bytes received** — narration duration counted from the MP3
  frames, image size read from the PNG header — never taken from the request. Where a vendor
  offers nothing (no word alignment, no seed), the adapter reports nothing instead of echoing the
  request back as if it had applied.
- **A render uses a provider only when it is both verified and selected** for that purpose. With
  none, the render still happens and is labelled placeholder content, which QC keeps out of
  publication — unchanged. The recorded provider name is always the generator that actually made
  the frames, and it drives the asset, the event and the QC report from one value.
- `GET /media/providers` says which generators a render would use and whether its output could be
  published. Settings stops telling you these vendors are unconnected once an adapter exists.
- Baseline: ruff, ruff format, mypy, pytest 241 passed / 1 skipped, frontend 17, `tsc`, build,
  docs integrity, secret scan; Playwright 106 checks across 8 suites.

## 2026-09-10 — Research hands work to production

- **An approved script now reaches production.** The Media panel opens with the approved scripts
  no storyboard has been built from yet — with their scene count and how many verified claims
  each rests on — and builds the storyboard from there. Previously the only creation control was
  the demo fixture, so the two halves of the studio were joined by test data.
- Only APPROVED drafts are offered: approval is what passing the factual gate means. A script
  leaves the queue the moment its storyboard exists, so nothing is produced twice by accident.
- **The panel says what a render will be before you ask for one** — without a verified image
  provider the output is placeholder content that QC blocks from publication. That was knowable
  in advance; reading it in a failed QC report afterwards was the wrong way to find out.
- Baseline: ruff, ruff format, mypy, pytest 244 passed / 1 skipped, frontend 17, `tsc`, build,
  docs integrity, secret scan; Playwright 117 checks across 9 suites.

## 2026-09-10 — Phase 8: the studio can recommend staffing changes, and only recommend them

- **Evidence is counted from the studio's own record** — agent runs and their outcomes over a
  30-day window, queue backlog, dead-lettered tasks. No model is asked what it thinks of a
  colleague; a fluent judgement with nothing under it is exactly what this must not produce.
- **An agent with no runs is shown as unmeasured, not as flawless.** Its failure rate is unknown,
  not zero.
- **Fewer than five runs never becomes a recommendation**, at any failure rate. The service
  refuses to build such a proposal and the database refuses to store one.
- Each proposal carries the numbers it was built from, and the panel shows them — a staffing
  decision has to be checkable months later.
- **A high failure rate proposes suspension, not termination**: the cause is usually the model or
  the provider, and suspension is reversible.
- **Approving is the Owner's act.** An autonomous approval is refused outright rather than
  quietly turned into a pending proposal, and a rejection requires a written reason.
- Employment is now a record with its own history, so a rehire opens a new period instead of
  reviving a closed one — TERMINATED cannot become ACTIVE by editing state, as the spec requires.
- New "Personal" panel; migration `0012_workforce`.
- Baseline: ruff, ruff format, mypy, pytest 263 passed / 1 skipped, frontend 17, `tsc`, build,
  docs integrity, secret scan; Playwright 126 checks across 10 suites.

## 2026-09-10 — Phase 9: the daily log, and a serial that cannot invent the day

- **The day is counted from the event stream**, in the studio's own timezone — counts per event
  type, the roster, and the events worth dramatising. No model writes any part of the log,
  because the log is what every episode is checked against.
- **A closed day does not change**, and a date can only be closed once. Otherwise an episode
  could become grounded after the fact.
- **Every beat cites the real events it dramatises**, and a citation that is not in that day's
  log fails the whole episode — not just the beat. The spec's forbidden-fabrication list (a fake
  hire, an invented outage, a decision attributed to the wrong person) is all enforced by this
  one rule: those things have no event to cite.
- **The cast is the day's roster.** The serial cannot put someone in a room the record says they
  were not in.
- **A quiet day produces no episode** and the panel says so, instead of offering a button that
  would fail. A quiet day is a fact about the studio.
- `GET /story/episodes/{id}/grounding` re-checks a stored episode against its log, so the
  grounding claim is audited rather than trusted.
- New "Jurnal" panel; migration `0013_story`.
- Baseline: ruff, ruff format, mypy, pytest 284 passed / 1 skipped, frontend 17, `tsc`, build,
  docs integrity, secret scan; Playwright 137 checks across 11 suites.

## 2026-09-10 — Phase 10: the daily runbook, and a run that reports only what it did

- **A preflight that never rounds up.** Every capability is checked and listed with what it
  found — the passing ones too, so the Owner can see what was looked at. A missing media provider
  degrades the day; a stopped autonomy gate, no verified model or no FFmpeg blocks it. The
  DEGRADED summary says in words that stages will be skipped and the output will be
  unpublishable, because "DEGRADED" on its own invites being read as "fine for now".
- **The preflight probes nothing over the network** and changes nothing: reading it twice cannot
  start a run.
- **The run's status is derived from its stages**, never asserted by a caller or a stage. A stage
  reporting COMPLETED does not make the day completed while another was skipped.
- **All twelve stages appear in every run record**, including the ones with no implementation
  connected (SKIPPED, with the reason) and the ones after a stop (BLOCKED, naming where it
  stopped). A record listing only the stages that ran would mislead by its shape alone.
- **A blocked preflight closes no daily log.** A partial day is still a day; a day the studio
  never started is not, and writing a log for it would put work that did not happen into the
  record tomorrow's episode is checked against.
- **A failed stage enters safe mode and stops autonomy**, so an unattended studio does not carry
  on into the next day with an unexamined fault behind it. A second failure does not open a
  second record and obscure when the incident began.
- **Leaving safe mode requires a written note and does not restart autonomy** — examining an
  incident and deciding the studio should act again are separate decisions.
- New "Rulare zilnică" panel; migration `0014_runbook`.
- Baseline: ruff, ruff format, mypy, pytest 304 passed / 1 skipped, frontend 17, `tsc`, build,
  docs integrity, secret scan; Playwright 149 checks across 12 suites.

## 2026-09-10 — Outdoor electronic clock

Added a pixel seven-segment clock marked BUCURESTI, 24-hour HH:mm, using Europe/Bucharest including DST. Street schedules now use the same timezone. 35 frontend tests and browser checks passed.

## 2026-09-10 — Street clock placement and consistent controls

Clock is now freestanding on the right side of the street. Bottom control dock CSS is emitted as a same-origin file, fixing CSP-blocked inline styling. Browser placement checks pass in desktop/fullscreen/mobile.

## 2026-09-10 — Correct agent inspector model assignment

Fixed false “Niciun model alocat” when an older office projection omits model metadata. Inspector now loads persisted agent/model details, handles errors explicitly and discards late responses. All 7 live agents matched Settings in read-only browser QA; 38 frontend tests passed. See `INSPECTOR_MODEL_FIX.md`.
