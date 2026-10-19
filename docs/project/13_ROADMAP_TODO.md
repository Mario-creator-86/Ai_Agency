# Roadmap / TODO v3

## 2026-10-16 — Review fixes, context by task, two renders, the voice's own pause (Claude)

- [x] 30 review defects of the montage/v8 day fixed; context by task; renders cap 2 (a setting);
      the voice's own pause (`config/pause_rules.json`); a published topic is finished; the
      dishonest-code audit's 12 findings fixed; the writer eval harness (`scripts/writer_eval.py`).
- [ ] At the next start (the Owner presses GO): set the DAILY budget to 30 USD through the economy
      budget command; close film 87c05891 («Zero Scripts, Blocked Log», v7) and refuse its episode
      through the app, retell 2026-10-16 on v8; write the ~160 s short through the app; he reads
      both before any paid step. Watch the first frozen film: `spans[].pause` planned vs heard.
- [ ] A film refused OVER_THE_WALL (`FilmOverTheWall`, the stills step's `not_bought`) is held but
      not sent back to the writer for a shorter rewrite; the Director loop, routes and sheet must
      know the status.
- [ ] The advisory `pause_marks` review check from the pause design (not built).
- [ ] The scene clip check uses the whole pause a shot holds (0.77 s before a change of part); a
      model with 5 s clips refuses 13-word scenes — decide whether to check the pause at its floor.
- [ ] Legacy CLIP_QC rows with verdict PASSED and accepted_under_cap are read as kept (not migrated);
      LTX manifest rows approved by `director_cap` stay in the file (the trainer skips them).
- [ ] A scene at the still cap with ≥2 stills is held in `stills_plan` until a settle asks the
      Director: watch the ordering on a live board.
- [ ] The serial tells a day closed minutes after midnight (the day log closes at each run's end);
      check what «the day» means for `serial_next` before the v8 retell.
- [ ] `test_writer_brief::test_the_cost_line_is_priced_from_the_table_or_left_out` fails only in
      a shard (order-dependent film ceiling): find the leaked setting.
- [ ] Quality plan steps 3-6 ([STUDIO_QUALITY_PLAN_2026-10-16.md](STUDIO_QUALITY_PLAN_2026-10-16.md)):
      the audit loop's attributed segments and checked quotes, independent judges (nemotron-3-ultra
      stranger; a vision QA model not Kael's), playbooks measured on the harness, the Owner's
      calibration form (`writer_eval.py --calibration-form`). Real-model runs only by his card.
- [ ] 11_DATA_MODEL still says 60/70 s for the Shorts maximum (decision logged; hash update owed).
- [ ] 38 failures that predate 2026-10-16 (listed in CURRENT_STATUS of 2026-10-16).

## 2026-10-16 — Dashboard visual finish

- [x] Metric/channel/icon/typography refinements, navigation states, aligned panel headers and compact empty states.
- [x] Desktop/mobile/enlarged-text checks and UI-only local install; server identity unchanged.
- [ ] Owner visual review after Ctrl+F5.


## 2026-10-16 — Owner reference dashboard

- [x] Reference-based navigation/activity/scene/approvals/queue/compact autonomy layout, no bottom agent strip.
- [x] Real project, monthly-budget and bounded task counters, audience cards for both bound channels with truthful timestamps and polling.
- [x] Desktop/mobile/enlarged-text verification, frontend build and local UI-only installation without server restart.
- [ ] Owner visual review after Ctrl+F5. Exact totals beyond the task API cap and production YouTube freshness are separate from isolated layout acceptance.


## 2026-10-15 — The studio publishes by itself (Claude)

- [x] Cloud asked nothing about thinking; writers get a JSON second attempt; serial film unblocked
      from the approved still's lint; outage ≠ Owner card; publish faults SKIPPED; QC-passed wait
      bounded; night's resume fix committed.
- [ ] Watch after the restart: f06808c9 motion → assembly → QC → publish; Marcus's Supernova
      script in JSON; no model card, no quality letter to the Owner; the day's budget.
- [ ] A Director REJECT of a Publisher HOLD lifts the hold (`reviews.approved_metadata` treats
      RESOLVED as approval): decide REJECT = keep holding.
- [ ] The Owner's yes on `publishing.public_publish` does not continue the film (waits for the
      next 05:00); queue the continuation like a paid-media yes.
- [ ] `FAILED_RETRYABLE` uploads reach the Owner after three watchdog passes (~30 min) — back off
      instead; `NEEDS_RECONCILIATION` is not in `LIVE_PUBLICATION_STATES` (duplicate risk).
- [ ] mypy: 20 pre-existing errors in events_feed, input_guard, redo_cap, goal, elevenlabs_lexicon.
- [ ] A direct test of `_publish_one`'s SKIPPED on `ValueError`/`OSError`.
- [ ] NEXT CYCLE (the Owner, 2026-10-15 07:05Z: «restart acum cu 1–4, apoi 5»): GPU batching across
      films — take every storyboard to its GPU boundary, one session for all stills, then one for all
      motions. `run_stills_stage` must become a `purchase_flow`, and `_media_films`/`_walk_staircase`
      must walk by layer across boards (leases, holds and questions per board kept); `RoundWork` /
      `run_prepared` serve repairs today.
- [ ] Open from the night's structural work (fail on 52bc6e3, passed before): `test_no_paid_path_escapes`
      (3: `reference_image_adapter` reached on the walk with no fake; `gpu_batch.run_rounds` with no
      booking/gate door via `prepared_batch`), `test_runpod_money_adversary` (3), `test_readiness`
      (daily budget below one film), `test_rewrite_learns` (job-1).
- [ ] Pre-existing failures (also on 3dad2ff): `test_bad_film_never_bought` (2), `test_film_close`
      (`native_thinking` kwarg on the stub), `test_mode_lowered_mid_step`, `test_motion_v2` (5),
      `test_next_round_balance` (4, `failure_kind`), `test_owner_takes_never_retired`,
      `test_paid_path_write_lock` (2).
- [ ] The hourly Cowork session presses «Începe ziua» and reassigns models; the Owner decides whether
      it may act or only watch.
- [ ] Letters to the Owner after a hard stop («rularea zilei s-a oprit înainte să se termine», «foaia
      așteaptă să se încheie cumpărarea în curs» on an expired lease) are the studio's matters, not his:
      route them to the Director or drop them.
- [ ] The Director's end-of-day review still quotes the old budget figure (16,20 USD) from the day's
      reports written before the budget fix; the reports should read the period as the kernel does.
- [ ] Inbox hygiene: the Director's read STATUS reports (105 open since 2026-10-03) and Marcus's 60
      open HANDOFFs are never resolved; the loop that reads them must close them, else every call
      carries them (bounded since cycle 3, not resolved).
- [ ] A ladder scene the studio cannot rewrite (no shot plan, closed film, a card) repeats
      «Directoarea nu a putut încă rescrie … studioul reia singur rescrierea» every day with no
      note: write one `developer_defect` note and stop repeating (seen in the three-days test).
- [ ] The rewrite's own lint judges a serial still against the look's cap (20 000) while the
      sheet judges it against the route's: on a route below the look's cap the two disagree and
      the rewrite never converges (not production's case today).

2026-10-15 final Cloud correction: -1 sentinel rejected live, removed; omitted num_predict returns OK in a short paid probe (0.00001 VR). Actual DeepSeek-v4.1-flash max output393216, so480000 invalid. Technical probes not film progress. Backend15596 ready; Owner objects to further parameter changes, no more probes. See corrected SARAH_MARCUS_CLOUD_RESPONSE report.

## 2026-10-15 — Cloud response contract

- [x] Diagnose actual Sarah HTTP 400 / Marcus 600-second timeout separately.
- [x] Use provider-native Cloud output and complete streaming without unsafe resend.
- [x] Safe technical refusal categories; nine regressions and expanded provider/runbook checks.
- [x] Backend restart observed after source saves; both health checks 200.
- [ ] Observe real agent result without launching a test generation.


## 2026-10-15 — Visible wardrobe and reference route

- [x] Preserve partial-character wardrobe in composition/QC and refuse old incomplete input before animation.
- [x] Select discovered compatible RunPod reference route before pricing/approval; share prepared adapters per batch.
- [x] Use actual still model limit in video plan; add explicit framing/unruled-page QA conditions.
- [x] Informational Owner reports and truthful legacy headings; retain real approvals.
- [x] Source/API/UI regression suites and read-only real-data proof.
- [ ] Activate backend at normal restart after current LLM call and observe reviewed Edit/reference generation and final visual QC.

## 2026-10-14 — Sarah QC versus delivery context

- [x] Isolate film visual-QC rewrite from an unrelated undelivered request.
- [x] Make action explicit in brief v4 and required for delivery; preserve verified delivery and financial gates.
- [x] Five regressions, 53 relevant tests and source/document checks passed.
- [ ] Observe actual brief/rewrite/review after normal restart; inspect provider error bodies and Sarah cast/wardrobe completeness before generation.

## 2026-10-14 — Live prompt approval and cancelled redo

- [x] Trace complete real Qwen text, old TREATS approval, legacy incomplete fields and current budget verdict.
- [x] Enforce complete plans, exact current reviewed text and verified current accepted replacement files.
- [x] Route missing clauses to Sarah/rewriter; preserve long factual fields and subject orientation.
- [x] Exclude cancelled undelivered work from bought/waiting progress while preserving actual QC rejections.
- [x] Verify 18 new regressions plus existing Director, native-bundle and financial-boundary checks.
- [ ] Observe activation at next normal restart and actual revised generation/visual QC.

Handoff: LIVE_PROMPT_APPROVAL_AND_ABORTED_REDO_2026-10-14.md.

## 2026-10-14 — Budget changes and complete LLM context

- [x] Replace the unset implicit film ceiling with the current shared daily limit.
- [x] Re-evaluate obsolete financial outcomes after budget/approval changes; retain minor acceptances.
- [x] LLM output x10, complete messages/threads/memory/dossiers and no silent schema fitting.
- [x] Preserve complete shot fields, evidence, lessons and rewrite history; flag provider partial output.
- [x] Verify local gates/route regression suites, 955 frontend tests, types/build and code/doc checks.
- [ ] Observe activation through the next normal server start and actual reviewed generation/QC.

Handoff: BUDGET_AND_COMPLETE_CONTEXT_2026-10-14.md.

## 2026-10-14 — Approved GPU bundles

- [x] Prepare Director repairs across scenes before GPU dispatch; images precede eligible videos.
- [x] Reuse existing purchase gates, per-scene holds and QC; combine compatible ready RunPod work.
- [x] Upload and validate the entire bundle before GPU-on; queue all chunks before polling.
- [x] Account once for shared startup, preserve individual caps/refunds and uncertain-job proofs.
- [x] Extend queued jobs/input URLs for earlier work, cache waits and waiting for GPU availability.
- [x] Verify native still/video redo integration, financial guards, STOP, idempotency and references.
- [ ] Observe the next normal RunPod generation after server activation; confirm actual worker/cache
  reuse and visual QC. No paid cloud verification was performed in this implementation task.

Scope, files and next-AI instructions: APPROVED_GPU_BATCHES_2026-10-14.md.

## 2026-10-14 — Serial prompt route allowance

- [x] Replace the local 980-character cap and 2,000-character clamp with the GPU route's
  20,000-character request allowance; preserve complete first-frame and character conditions.
- [x] Align sheet/repair lint and verify identical text at both Qwen workflow nodes, without
  paid generation; eight recorded serial scenes lose zero required conditions after recomposition.
- [ ] Confirm normal runtime re-description and Sarah-approved image generation/visual QC
  after the Owner next starts the studio. Kelvin acceptance routing and film budget remain separate.

Evidence and rollback: SERIAL_PROMPT_MODEL_LIMIT_2026-10-14.md / .json.

## Agency loop diagnosis — 2026-10-14

- [x] Exclude confirmed uploaded films from repair/writes/purchases; settle stale reports.
- [x] Recover only the dead exclusive workers correlated text sheet calls at startup.
- [x] Test Sarah/Kael with actual providers: classify unusable output by parsed work.
- [x] Scope batches to explicit scene indices; keep complete shared evidence.
- [x] Keep object-list predicates; a negative comma list cannot become positive content.
- [x] Sarah compared actual probes and selected the verified model that delivered.
- [x] Final scene-2 probe: 889 output tokens, changed prompts, no local block, review TREATS.
- [ ] At Owner-requested next start, prove new still acceptance before video and defect QC.

Studio stopped by Owner; monitor PAUSED. Evidence: AGENCY_LOOP_DIAGNOSIS_2026-10-14.md.

## Prompt/QC follow-up — 2026-10-14

- [x] Inspect nine frozen examples; preserve visible endpoint clauses beside scene pointers.
- [x] Preserve the first action after identity/spatial intros and valid object pronouns.
- [x] Native cap before editorial word target; explicit motionless world stays motionless.
- [x] Layer-aware composition checks keep accepted source images without ignoring real QC.
- [x] Remove remaining six-finding/text/JSON cuts; complete reply and before/after to Sarah.
- [x] Nine offline proposals with exact old/new text, roles and required semantic review.
- [ ] Activate/evaluate through real Director/model/GPU/QC after credit restoration. Six
  recorded packages remain blocked with old fields; the nine proposals are unapplied drafts,
  not approvals. Closed/rejected films stay closed.

Evidence: PROMPT_CONTRACT_FOLLOWUP_2026-10-14.md and PROMPT_REPAIR_PROPOSALS_2026-10-14.md.

## Prompt/QC completeness — 2026-10-14

- [x] Read-only audit of every recorded LIVE scene: 85 scenes, 170 prompt texts, 14 boards.
- [x] Supply initial QC conditions; batch complete scenes/claims; preserve canonical wardrobe.
- [x] Include factual final frames; block lost conditions before spending; respect static plans.
- [x] Complete mail/Director/QC context; retain every relevant finding and negative condition.
- [x] Connect existing RunPod input guard; remove editorial daily ceilings; preserve Owner gates.
- [ ] Real models after credit restoration: applicable candidates need editorial review;
  activate normally and prove reviewed words → actual request → result → defect-specific QC.

Evidence: PROMPT_CONTRACT_AUDIT_2026-10-14.md, its JSON inventory and test transcript.

## Director reviews replacement prompts and waiting work — 2026-10-14

- [x] Trace actual Kelvin old/generic-retry requests and Sarah's untreated face finding.
- [x] Route image/video rerolls through the reviewed rewrite, including unavailable looks.
- [x] Prove exact reviewed text reaches the generator in a controlled integration test.
- [x] Give take selection the full character bible/plan and serial writers the composition rules.
- [x] Free Director work during GPU waiting and configurable five-minute general checks.
- [x] Preserve paused schedule, Owner STOP, budgets and the single queue worker.
- [ ] Verify activation and live review → generation → QC; mocks do not prove quality.

Evidence: DIRECTOR_REGENERATION_REVIEW_2026-10-14.md.

## Kelvin: Director handles terminal delivery failures — 2026-10-13

- [x] Reproduce the missing ladder link for RUNPOD.EXPIRED_UNDELIVERED.
- [x] Reuse Sarah's brief for verified terminal delivery recovery; retain QC rewrites,
  budgets, paid-attempt counts, approvals and ambiguous submission safeguards.
- [x] Separate Director waiting from Owner waiting in the media report and register.
- [x] Regression tests and lint; existing type errors compared against HEAD.
- [x] Verify the real Kelvin continuation: Sarah's delivery decision and new request at
  23:39; request queued at 23:50. No extra restart during its generation.
- [ ] Later register/stale-prompt refinements load at the next normal restart; clip delivery
  and visual acceptance remain separate external outcomes.

Evidence: DIRECTOR_DELIVERY_ROUTING_2026-10-13.md.

## Director token allowance x2 — 2026-10-11

- [x] Inspect the cyclotron QC failure: first answer fails existing reason-length
  validation; second consumes its 6,000-token limit and returns `EMPTY_OUTPUT`.
- [x] Configurable Director-only multiplier, default 2 (1..4), applied once to every
  explicit run limit; generation limits recorded; other roles and Owner gates preserved.
- [x] QC v5 communicates existing schema bounds; latest focused 9 regressions pass,
  including Director `None`; related suite 123 pass / 1 live-provider skip. Ruff,
  mypy and independent review pass.
- [x] Runtime activated after a clean restart at 19:24 Bucharest; fresh server/worker
  healthy, effective multiplier 2 verified. Active claim released.

Proof and rollback: [DIRECTOR_TOKEN_BUDGET_2026-10-11.md](DIRECTOR_TOKEN_BUDGET_2026-10-11.md).
A successful new paid-model QC decision is unproven; this task did not request one.

## Front profiles and backend animation acceptance — 2026-10-09

- [x] Owner follow-up: clean portrait images, actual work/lifecycle facts outside the image;
  zero overlays across eight inspectors/cards, units/types and live mobile/delivery check pass.
- [x] Eight frontal identity-bound original portraits, individual role environments and own
  fallback; inspector/roster/requester surfaces, all eight visual headers, actual mobile check.
- [x] Live outbox aggregate_version, state-triggered serialized bounded presentation reads,
  safe legacy layout repair; mismatch/Owner/expiry/stale guards retained.
- [x] 48 real disposable-DB state changes with outbox/WebSocket/Owner HTTP, all painted staff,
  pause/resume, rapid/delayed/legacy/reconnect/stale cases. Heavy game guard unchanged.
- [x] 909 units/types, 72 scoped backend/docs, eight sequential scene and one backend/page
  acceptance. Production read-only eight profiles/roster/phone, correct occupied desks,
  rebuild/source freshness/served bytes, health 200. No production backend restart.

Proof/rollback/provenance: PIXEL_BACKEND_ANIMATION_ACCEPTANCE.md.

## Living studio and desk ergonomics — 2026-10-09

- [x] PIXEL_LIVING_STUDIO — eight individual office chairs, raised seat/pelvis with fixed
  wheels, Nadia rear-left toward her desk and physical upright monitor.
- [x] Backend state/version-authorized varied gestures, bounded 2D floor/furniture contacts,
  damped upper joints, wind paper/plants, rare lamp dips, nine screen planes and original sound.
- [x] 898 frontend/types, eight browser and 81 scoped backend/docs/scan cases; six runtime
  fixtures, seating/codec/audio/owner/expiry guards, nine real dialogs and 32 s actual clip.
- [x] Temporary socket-loss rehearsal with authenticated fresh HTTP policies; expiry and
  stale/changed employee guards retained. Source/build/served bytes and original art checked.
- [ ] Actual channel-film playback: library currently has zero eligible local/public films.
  The isolated codec fixture passes; a real film remains a separate production dependency.

Proof/rollback/provenance: PIXEL_LIVING_STUDIO.md; art-source/pixel/living-studio-v8/.

## Front/back and contact audit — 2026-10-09

- [x] PIXEL_DEPTH_PHYSICS — ground-depth ordering, native near-garden/fence silhouettes,
  transparent road gaps, clock/pets/traffic, indoor ensemble/dialogue/pointer layers.
- [x] Reproduce and fix adjacent menu interception; press every room at seven widths;
  nine actual modal/backdrop/focus/Escape checks, clickable toolbar and roster.
- [x] 883 frontend/types, seven bounded browser and 66 scoped backend/docs/secret cases;
  64 s depth fixtures and actual 32 s live video, no page errors.

Proof and rollback: PIXEL_DEPTH_PHYSICS.md. Existing art/seats/scale/backend truth retained.

## Street refinement — 2026-10-09

- [x] PIXEL_STREET_REFINEMENT — exact 10% human/chair scale reduction, full-width street,
  corrected speeds/cadence, two full cat patrols, four original detailed car profiles.
- [x] 879 frontend/types, six bounded Playwright and 66 scoped backend/docs/secret cases;
  actual 31.958008 s live clip, four vehicle variants, all street actors and eight staff moving.

Proof, source and rollback: PIXEL_STREET_REFINEMENT.md. External workflows remain separate.

## Integrated chairs and natural joint motion — 2026-10-09

- [x] PIXEL_NATURAL_MOTION — generate eight people together with their own chair/stool;
  one scale and floor anchor, selective empty-chair clean plate, continuous small joints.
- [x] 863 frontend/types, five browser checks including 60 simulated seconds at all eight
  seats, and 62 scoped backend/docs/secret cases; actual 19.916016 s live UI clip inspected.

Proof and rollback: PIXEL_CHAIR_ENSEMBLES.md. This supersedes the separate-body seating below.

## Scene motion resume — 2026-10-09

- [x] PIXEL_MOTION_RESUME — reproduce reduced-motion freeze; explicit Owner animation
  default and persistent ANIMAȚII toggle, no Windows/menu setting change.
- [x] 861 frontend/types and four bounded browser checks; actual four pedestrians,
  bicycle/pets and eight staff visibly move; pause/reload/resume/mobile pass.

Proof and rollback: PIXEL_MOTION_RESUME.md; actual clip 15.916016 s.

## Proper seated contact — 2026-10-09

- [x] PIXEL_SEAT_ALIGNMENT — 48 poses reviewed at eight original chairs/stools; pelvis
  anchors, fixed floor, proportional shoes and original furniture silhouette masks.
- [x] Actual current-seat UI verified without backend restart; 859 frontend/types,
  three bounded browser and 53 scoped backend/docs pass. Final live clip: 16 seconds.

PIXEL_ACTOR_REFINEMENT.md records current assets, proof and rollback.

## Detailed living actors — 2026-10-09

- [x] PIXEL_ACTOR_REFINEMENT — five original RGBA atlases/80 source frames, eight real
  employee appearances/state poses, detailed pedestrian/cyclist/pet animation, graceful
  fallback and preserved approved building/personal desks/menus.
- [x] PIXEL_ACTOR_ACCEPTANCE — 859 frontend, types, three bounded browser and 53 scoped
  backend/docs; actual eight-agent visible motion and 15.916 s read-only UI video verified.

Source, provenance, evidence and rollback: PIXEL_ACTOR_REFINEMENT.md.

## RunPod Serverless phase 1 — 2026-10-08 (proven on fakes only)

- [x] RUNPOD_PHASE1_STEPS — paid stills/test shot/motion/redo bought in rounds of one batch job
  each inside one GPU session; round overhead priced; bucket manifests before /status; journal
  without base64; verification without /run; planner ratio normalisation and selected RunPod
  model; media readiness needs the bucket; GPU start shown in the sheet's price.
- [x] RUNPOD_PHASE1_CONTROL / RUNPOD_PHASE1_WORKER — GPU on/off, guard, kernel, cards, page and
  the amn.batch.v1 worker image sources (see their ADRs in 16_DECISION_LOG.md).
- [x] RUNPOD_OWNER_SETUP_CHECK — worker base fixed to the published 5.10.0-base and pinned by
  digest, ComfyUI 0.39.2, public weights pinned, `build resolve` for the gated LTX-2.5
  checksums; a RunPod step refuses before the Owner's yes while his GPU card is not accepted.
- [ ] RUNPOD_IMAGE_BUILD_HOST — Owner decision: where the two images (~39 GB and ~78 GB of
  weights) are built and pushed, and the registry credentials in RunPod.
- [x] RUNPOD_REFERENCE_STILLS — 2026-10-09 (his card: Qwen Edit 2511), studio side on fakes: the
  `Qwen-Image-Edit-2511` route takes the character's picture and Figure 1 (1-3, presigned), a
  locked character is no longer refused NEEDS_REFERENCE there; identity hold UNPROVEN (bake-off).
- [x] RUNPOD_CACHE_STUDIO — 2026-10-09, fakes only: `model_source` cache/volume/baked, mirror
  repo/revision per endpoint, the unbilled cache wait always in the TTL, the weights check
  (`weights_revision`, MODELS_MISSING/WRONG_REVISION → stop, max=0, his card, hold), the
  «aștept descărcarea modelului (neplătită)» words, and the one-time copy pod (`pods.py`, his
  card's accept is the press, capped, always terminated; migration 0057).
- [ ] RUNPOD_MIRROR_COPY_RUN — his accept of «Copiez modelele în contul tău Hugging Face …» (money;
  needs his HF PRO repos, a write token in the RunPod connection and the worker's `build mirror`).
- [ ] RUNPOD_CONSOLE_MODEL — his console step per endpoint («Manage → Edit Endpoint → Model», his
  mirror + HF token), and the copied commit pinned where the worker reads it (mirrors.lock.json +
  a GitHub release, or AMN_MIRROR_REPO/AMN_MIRROR_REVISION in the endpoint env).
- [ ] RUNPOD_CACHE_BAKE_OFF — measure the cache's real load time and blob naming, RTX PRO 6000
  hosts with the cache, CPU pod price, 2511's identity hold at 928x1664 (all UNPROVEN).
- [ ] RUNPOD_STILL_REDO_ROUNDS — the per-scene still redo bought as a round (refused today).
- [ ] RUNPOD_BUCKET — the Owner creates the S3-compatible bucket (e.g. Cloudflare R2) and puts
  its endpoint, name and two keys on the RunPod connection.
- [ ] RUNPOD_BAKE_OFF — the paid test card: billed rate (3.49 vs 4.00), cold start, idleTimeout
  1 s honoured, GPU seconds per still/clip (replace config/runpod_models.json estimates),
  quality against Runway, LTX-2.5 provenance boxes, Restricted key access, R2 If-None-Match.
- [ ] RUNPOD_BALANCE — phase 2: read RunPod's balance/billing once its API field is confirmed.
- [x] RUNPOD_OWNER_SWITCH — «RunPod pornit» on the connection replaces RUNPOD_ENABLED in .env
  (verified-only ON, immediate OFF) and the read-only «Pașii configurării» checklist (fakes only).
- [ ] RUNPOD_OWNER_SWITCH_LIVE — his first press and «Verifică pașii» against his real accounts
  (console links and the HEAD-bucket read on R2 are UNPROVEN until then).

## Living pixel studio — 2026-10-08

- [x] PIXEL_STUDIO_LIFE — one hover tooltip, no character rectangle, independent seated
  state/role gestures and original ambient city actors; approved detailed art preserved.
- [x] PIXEL_LIFE_ACCEPTANCE — 846 frontend, type check, three bounded browser checks and
  53 scoped backend/docs pass; actual eight-agent production animation/video verified.

Report and rollback: PIXEL_STUDIO_LIFE.md; evidence: data/pixel-life-2026-10-08/.

## No sign-in form on the Owner's machine — 2026-10-08

- [x] LOCAL_AUTO_LOGIN — loopback-only key hand-over route, setting, page entry without the form;
  backend (real uvicorn), frontend, type, lint and docs checks pass; browser-verified on an
  isolated fake studio. Live at his next start (page build + new route).

## Pixel navigation and night — 2026-10-08

- [x] PIXEL_NAVIGATION_NIGHT — fix desktop clipping, wheel/drag/fit navigation, native mobile
  scroll; coloured actual-solar sunset/night and stylistic moon/stars. Preserve approved art.
- [x] PIXEL_NAVIGATION_ACCEPTANCE — 826 frontend, type check, two bounded browser cases and
  53 scoped backend/docs pass; real signed-in 8-agent UI and served assets verified.

## Stale backup warning — 2026-10-08

- [x] BACKUP_STALE_ALERT — actual fresh online copy; automatic queued backup completed;
  live readiness HEALTHY. Restore latest real artifact with usable keys/eight agents on
  isolated target; eleven backup regressions pass. Threshold and Owner policy preserved.

## Python runtime recovery — 2026-10-08

- [x] PYTHON_RUNTIME_RECOVERY — restore the pinned missing base before CMD startup; update
  obsolete uv download metadata. Real recovery and complete server/page/API lifecycle
  verified on isolated state; preserve production data/policy and locked packages.

## Launcher compatibility — 2026-10-08

- [x] ROOT_START_COMPATIBILITY — restore python start.py with locked uv delegation; preserve
  options/cwd/exit code and graceful Ctrl+C. Twelve scoped cases and real help probes pass.

## Pixel outdoor clock and Bucharest weather — 2026-10-08

- [x] PIXEL_OUTDOOR_CLOCK_WEATHER — original exterior clock, DST/local time, real configured
  weather and solar tint; protected furnished interiors, capped particles and lifecycle guards.
- [x] PIXEL_WEATHER_GRAPHICS — isolated real Canvas checks for current provider observation,
  day/night/rain/fog/snow/storm, stale/unavailable/replay weather, hidden/logout and phone.
- [ ] PIXEL_WEATHER_OWNER_FLOWS — repeat the full owner_flows suite when its existing game
  guard permits it. The current run skipped all 11 flows; historical 10-flow pass is separate.

## Agent scenario acceptance — 2026-10-08

- [x] AGENT_SCENARIO_ACCEPTANCE — eight assigned agents tested through actual Ollama Cloud;
  independent factual handoffs, contradictions/injection, lost upload response, vocal/editing
  advice, insufficient budget, strategic HOLD, STOP/pause and unavailable-model refusals.
- [x] SCENARIO_MAIL_CONCURRENCY — reproduce SQLite reply race; acquire write lock before
  reading in reply/forward/resolve. Verify actual concurrent-writer regression and mail suite.
- [x] SCENARIO_DEMO_DIRECTOR — correct schema routing and inbox IDs; repeat real local encode
  and QC without outbound vendors. Day PARTIAL because external prerequisites are absent.
- [x] SCENARIO_SERIAL_FEEDBACK — episode-v6 spoken-length reminder; record every rejected
  draft and final real Director PASS. Do not relax duration, per-beat or factual/privacy gates.
- [x] SCENARIO_HERO_PREVIEW — priced motion waiting on stills is no longer presented as free;
  preserve explicit caps and free reuse. Five policy cases and four staircase flows pass.
- [x] SCENARIO_SQLITE_RUNTIME — preserve prior environment; pin Python 3.14.8 with measured
  SQLite 3.53.1 containing the WAL concurrency fix. Production integrity check passes.
- [x] SCENARIO_SECRET_UTF8 — scan Unicode text reliably on Windows, detect a new fake key,
  review fixture hashes individually without weakening the scanner.
- [x] SCENARIO_ANALYTICS_VAULT — missing/unreadable optional statistics credentials are
  reported without invented data; normal daily preflight still blocks the missing key.
- [ ] SERIAL_NORMAL_RETRY_ACCEPTANCE — final sample required five rewrites, exceeding the
  normal autonomous allowance; exact two-draft stage rejects, alternative model times out.
  Prove repeatable acceptance within existing retry/token caps.
- [ ] RUNPOD_LIVE_ACCEPTANCE — real credentials/endpoints, capped generation and existing QC.
- [ ] PUBLISHING_LIVE_ACCEPTANCE — authorised real account, media/rights gates and receipt.

Report: AGENT_SCENARIO_REPORT.md. Current suite counts and limits: CURRENT_STATUS.md.

## Current Ollama Cloud role allocation — 2026-10-08

- [x] OLLAMA_ROLE_ALLOCATION — authenticate existing connection; inspect actual 18-variant/
  17-family catalogue and official sources; verify 16 role samples through real Cloud calls;
  save five primary changes and retain three suitable choices for the existing eight agents.
- [x] OWNER_ASSIGNMENT_ORIGIN — protect explicit choices even when they match seed proposals;
  retain legacy compatibility, verify regressions and record all eight assignments explicitly.
- [x] OLLAMA_ALLOCATION_HANDOFF — full catalogue/reasons/sources, existing prices/policy preserved,
  backups and UI readback. 103 scoped backend tests pass; details in CURRENT_STATUS.md and
  [OLLAMA_ROLE_ALLOCATION.md](OLLAMA_ROLE_ALLOCATION.md).

## Simple pixel studio and essential autonomy — 2026-10-08

- [x] PRESERVE_DETAILED_STUDIO — retain approved library/furniture/plants/lighting, add one
  furnished floor, seat eight existing agents at illustrated desks facing away, preserve
  live states and other menus. Supersedes the earlier cleared-furniture scene; evidence,
  browser captures and verification counts are in CURRENT_STATUS.md.

- [x] PERSONAL_PIXEL_DESKS — stable individual desks, seated layered characters, existing
  Character Bible identity, actual runtime/lifecycle gestures, annex pages and truthful
  stale/replay/reduced-motion behavior. Evidence and test counts: CURRENT_STATUS.md.

- [x] SIMPLE_PIXEL_STUDIO — original browser Canvas/environment/characters; existing menus,
  staff selection/chat, backend reality, accessibility, responsive layout and reduced motion.
- [x] RETIRE_TREASURY — no active Treasury/funding/FX/mint/virtual-ledger screen/public API;
  historical data/internal accounting compatibility preserved, real USD costs/gates retained.
- [x] AUTONOMY_OVERVIEW — current policy/environment/STOP/schedule, links to existing controls,
  budget/prices and collapsed preflight; existing versioned authorization preserved.
- [x] SIMPLE_OPERATOR_HANDOFF — guide, source backup, art provenance, reviewed spec precedence,
  804 UI/nine browser/364 distinct scoped backend tests and static/build/integrity checks.

Start: [SIMPLE_STUDIO_GUIDE.md](SIMPLE_STUDIO_GUIDE.md). Evidence: CURRENT_STATUS.md.
This supersedes the earlier top-down/live-HQ and active virtual-finance product milestones.
RunPod real connection/paid acceptance below remain external work, explicitly deferred.

## RunPod additional provider and local ComfyUI uninstall — 2026-10-07

- [x] RUNPOD_CLOUD_PREPARATION — modular Pod/Serverless adapters, durable idempotency/recovery,
  existing QA/asset/VideoEditor/watchdog integration, GPU estimates and existing financial gates,
  read-only connection check, offline PNG/5s-MP4 verification and disabled infra hooks.
- [x] COMFYUI_UNINSTALL — owned E:/Studio application/models/cache/runtime/workflows/launchers
  removed; stale Agency image/video selections detached, voice/artifacts preserved.
- [ ] RUNPOD_REAL_CONNECTION — supply real credentials and endpoint; authenticate health/models
  and select the available catalogue. No live connection claim based on offline tests.
- [ ] RUNPOD_PAID_ACCEPTANCE — after the separate Owner approval gate, one image and one five-second
  I2V test with real cost/log/asset/QA verification. Never run these in ordinary automated tests.

Implementation/evidence: [RUNPOD_HANDOFF.md](RUNPOD_HANDOFF.md).

## Graphics launch is opt-in — 2026-10-04

- [x] GRAPHICS_OPT_IN — latest Owner request supersedes automatic START_WITH_GRAPHICS:
  ordinary launches create no graphics supervisor; `--graphics` opts into the existing
  lifecycle, `--no-graphics` remains compatible. 85 launcher/graphics/rebuild tests passed.

## A lowered mode stops a paid step — 2026-10-04

- [x] MODE_REDUCTION_STOPS_PURCHASE — his policy read before every vendor request of a step
  bought unasked; the mode before the balance; STUDIO_DEFECT for a 400 naming our request, old
  holds released by the watchdog; QC and the scheduler tick write under the lock. Fakes only.
- [ ] Escalate a STUDIO_DEFECT that is not yet fixed to the team instead of retrying it daily.

## Shooting-sheet clarity — 2026-10-04

- [x] SHOOTING_SHEET_UI — overview with actual media state; production rows before wide scenes;
  folded technical/history/budget details; held hero recovery at its real redo price; readable
  desktop/tablet/phone layouts. 795 frontend tests, TypeScript, build and read-only browser review.
  Provider generation and whole-backend acceptance remain outside this UI milestone.

Implementation 2026-09-09: Phase 0 acceptance verified. See [VERIFICATION.md](VERIFICATION.md).

> **Audit correction, 2026-09-09** — see [AUDIT_2026-09-09_EXTERNAL.md](AUDIT_2026-09-09_EXTERNAL.md)
> and [CURRENT_STATUS.md](CURRENT_STATUS.md). Phases 4, 5 and 6 were previously marked complete;
> their acceptance criteria are **not** met and they are now tracked as partial:
>
> - **Phase 4** — the verification and gating machinery is real, but there is no search/research
>   adapter and no independent fact-checker. Sources are pasted by the Owner; a claim's status is
>   whatever the caller sends. Acceptance ("real research, evidence, independent fact checks") open.
>   Update 2026-09-12: the Researcher proposes topics and names pages; the studio finds pages
>   through each authorised site's own search address (OpenSearch, recorded by the Owner) and
>   reads them; the Fact Checker verifies claims against the fetched text.

### Voice stays its own connection (decided 2026-09-12)

Runway's API does expose ElevenLabs models — `eleven_v3` and `eleven_multilingual_v2` on
`/v1/text_to_speech`, plus dubbing, isolation and sound effects — and the Owner's tier
includes them, so one connection for picture and voice is technically possible. It was
examined and set aside, for reasons that are facts rather than preferences:

- `eleven_v3` there accepts only Runway's own preset voices (49 names), not an ElevenLabs
  `voice_id`; the character identity locks bind ElevenLabs voices, which have no equivalent.
- Each `eleven_*` model on Runway allows 50 generations a day; an eight-scene film spends
  eight, so roughly six films a day. Direct ElevenLabs limits characters, not calls.
- Runway bills in credits (measured: about sixteen credits a second of generated video),
  ElevenLabs in characters; which is cheaper for narration is not known without measuring.

The Owner's decision: keep the ElevenLabs connection separate. Revisit only with a measured
cost comparison, and never at the price of a locked character's voice.
> - **Phase 5** — FFmpeg now produces a real 1080x1920 H.264 file, but there is no image provider
>   and no TTS provider, so the frames are placeholders and QC blocks them from publication.
>   Character continuity is unimplemented. Acceptance ("provenance-backed media") open.
>   Update 2026-09-18: Runway and ElevenLabs are connected since 2026-09-12; captions are burnt
>   in and loudness normalised since 2026-09-17. ~~character-drift QC is still
>   `NOT_IMPLEMENTED`~~ — corrected later the same day: a picture gate and a character gate now
>   measure every scene's middle frame against the scene's prompt and the Character Bible, and the
>   bible's five reference slots can hold real files produced by an Owner-triggered route. Both
>   report NOT_APPLICABLE with a reason until an employee's model declares vision, which no seeded
>   workforce does, so on the live studio the checks stand down visibly rather than certify.
> - **Phase 6** — the gate, state machine and idempotency are real, but OAuth has never been
>   exercised and no upload has ever reached YouTube. Acceptance ("official OAuth, private upload
>   with verified remote ID") open.
>   Update 2026-09-18: OAuth is real since 2026-09-11 and two private uploads with real remote
>   ids (`98JltCPoOKs`, `sDEtt-WQGh8`) reached Main Channel A on 2026-09-12; since 2026-09-17
>   the publish stage sends each film to its storyboard's channel at that channel's Owner-set
>   policy, private by default.
> - **Phase 7** — `backend/app/analytics/` exists on disk but is unmounted, unregistered and has no
>   migration. It is not started work in any deliverable sense; add migration `0008` first
>   (`0007` is the audit data-correction migration).
>
> Order of work: close 4, then 5, then 6, before starting 7.
Canonical phase numbering and original-version mapping: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).
Early STOP/event primitives do not complete Phase 1/2/10 requirements.

## start.py starts the graphics, a stop stops everything — 2026-10-04

The Owner: «cand rulez python start.py, trebuie sa porneasca si grafica. La fel, cand opresc,
totul trebuie sa se opreasca!» Done in `scripts/` and its own tests, every process faked; the
real stream not yet started this way (see CURRENT_STATUS, START_WITH_GRAPHICS).

- [x] START_WITH_GRAPHICS — start.py starts wilbur and Unreal once the server answers (one argument list in `stream_command.json`, shared with `start_live_hq.ps1`); adopts, never doubles; never his editor; waits for his games and 16 GB of commit; bounded restarts; Ctrl+C stops the server cleanly, then Unreal, then wilbur; a kill-on-close Job Object and a close handler leave nothing running

Still open:
- [ ] A verifier starts the real stream through start.py under the gates, then Ctrl+C, a closed window and a killed start.py, and confirms nothing is left (UnrealEditor.exe, node.exe of the stream)
- [ ] Whether Unreal re-joins a restarted wilbur by itself (else restart both together)

## A redo that hung — 2026-10-03

The Owner: «am dat mai devreme să facă o imagine și a rămas blocat acolo». Done in code and its
own tests, every provider faked (0 credits); proven on fakes only (see CURRENT_STATUS).

- [x] REDO_HANG — an overall deadline on every Runway call, on a still purchase and on a paid narration request; the redo's accepted tasks SUBMITTED before any poll, IN_FLIGHT and collected free; the film lease renewed by its holder and reclaimed when it lapses (watchdog, next press, worker start) with its hold released and the Owner's letter

- [x] SHEET_BUSY_ONCE (page) — the sheet's status line has its own grid row (no longer under the body and its sticky bar); the busy sentence is said once, in the bar; a FILM_BUSY press is answered in warning colours; a paid «Refă» (still, motion) cannot be pressed while the film's lease stands, so no yes is asked for a press that would be refused

Still open:
- [ ] Restart of his studio so it runs this code, and `npm run build --prefix frontend` (or start.py, which rebuilds the page) so the page shows the fix (the 17:36 lease was taken over at 20:45 UTC by the old code: no reclaim letter will come for it; its hold 57b2e59e is released by the watchdog's 6 h rule)
- [ ] A reclaimed holder's hold is released, not booked: credits a vanished process committed never reach the ledger as spend
- [ ] Character reference sets (`media.services`, `generate_image`) are bounded in time now but still keep no task id before the poll
- [ ] A host name that never resolves (`getaddrinfo` has no timeout) and an LLM or ffmpeg call inside a leased step are bounded only by the lease's ceiling

## Next-round balance — 2026-10-03

The Owner: «De ce avem nevoie de asa de multe credite daca sa creezi o imagine costa 10-20 de
credite». He chose «Doar pentru runda următoare». Done in code and its own tests, every provider
faked (0 credits); proven on fakes only (see CURRENT_STATUS).

- [x] NEXT_ROUND_BALANCE — `balance_rule`: start on the next round × 1.15, each later purchase × 1.15, a clean LOW_BALANCE stop per scene, the cap the ceiling; the sheet's footer and page; his low-balance card with `balance_covers`; the repair letter's title

Still open:
- [ ] Restart of his studio so it runs the new rule (the LHC sheet then asks 166 credits, his 316 start it)
- [ ] A redo whose balance ran short (scene redo) puts no card yet; only the sheet's paid steps do

## Owner decisions window — 2026-10-03

The Owner: «trebuie să îmi apară un card… propria mea fereastră unde pot să accept sau refuz».
He chose «Fereastră Decizii separată». Done in code and its own tests, every provider faked
(0 credits); proven on fakes only (see CURRENT_STATUS, «State on 2026-10-03»).

- [x] DECISIONS_CORE — owner_decision table (0054), propose/withdraw/decide, appliers through his commands, conditions, one feed, the audit's questions seeded once
- [x] DECISION_SOURCES — cards from the budget wait, refused model connections, YouTube invalid_grant, commercial use, music, the paused sheet repair; allow_repair_retry
- [x] DECISIONS_WINDOW — «Decizii (N)» in the top bar, his window with «Te așteaptă» / «Istoric», Accept / Refuz with a note, guided cards, history
- [x] DOCS_AND_STATUS — spec 31 «Owner decision cards» with its hash, six decisions, status, changelog, roadmap

Still open:
- [ ] Restart of his studio (migrates 0053 → 0054, seeds the cards) and a dist rebuild; until then his page gets 404 on the feed
- [ ] Run the e2e flow «a card accepted in the window» (`npm run test:e2e --prefix frontend`, no game running) and look at the window in a browser
- [ ] A behavioural unit test of the window's controller (focus, deferred repaint, tab keys) needs a DOM library
- [ ] Owner decisions: narration as a paid step (spec 51 change, `record` only today); a «scene to card» command; commercial use applied on accept; an event for a newly proposed card
- [ ] The google_oauth_production card is proposed only by the audit seed, not by the YouTube producers

## Production-readiness audit — 2026-10-01 → 2026-10-02

The Owner's goal: production ready, ready to sell, films made automatically, quality 10/10.
Every item below was implemented test-first with every provider faked (0 credits). "Done" means
done in code and its own tests; nothing here is proven on a real paid vendor
(see CURRENT_STATUS, «State on 2026-10-02»).

Autonomous films and money safety:
- [x] GREEN_SUITE — the committed suite's four failures fixed; FFmpeg runs from a short folder
- [x] PAID_CALLS_AND_TAKE_INTENT — billed POSTs never resent unsafely; task ids kept and collected (0049)
- [x] BOOK_EVERY_PURCHASE — every purchase booked once; charged-but-unanswered counts; narration cached
- [x] NO_REBUY_RECOVERY_REFERENCES — per-scene failure memory; paid takes judged first; serial references
- [x] GATES_BEFORE_BUYING — purchase lease (0050), reservation per step, film ceiling, fail-closed budget, OVER_USD on the cap
- [x] HERO_AUTO_ACCEPT — hero accepted by clip QC under MODE / OVER_USD
- [x] DAY_FLOW_NO_STALL — held films skipped, shot plans re-asked, stale films retired, clear letters
- [x] CONTINUE_REDOS_E2E — FILM_CONTINUE the same day, automatic repair, autonomous-day end-to-end tests
- [x] QUEUE_LEASE_SHUTDOWN — per-claim leases, INTERRUPTED days, graceful shutdown, no dead Workflow rows

Production readiness:
- [x] SECURITY_STARTUP_LOGGING — unreadable vault survivable, safe rotating logs, no key in URLs, file routes confined
- [x] GATES_AND_CI — check_docs and check_secrets green on a fresh clone, check_all.py, CI workflow, patched deps
- [x] BACKUP_DISK_HEALTH — backups, restore guard, backup before migrations, health, disk floor
- [x] PUBLISHING_TRUTH — honest publishing states, reconciliation, visibility read back (0052)
- [x] PUBLISHING_METADATA — YouTube limits, one disclosure, per-channel upload settings (0053), sources

Film quality:
- [x] FILM_AUDIO_AND_RIGHTS — trimmed narration, licensed music bed, stitching, licence ledger (0051)
- [x] FILM_STORY_PICTURE_QC — looping endings, highlighted captions, second framings, grade, cover, editorial QC

Sellable and the page:
- [x] SELLABLE — demo mode, README and operator guide, settings documented, notices, release archive
- [x] PAGE_OWNER_DAY — stale-page banner, sheet keys, paid rule in Guvernanță, confirmations, inbox
- [x] PAGE_SETTINGS_ERRORS — publish policy panel, error words, work queue, plurals, a11y, Playwright on fakes
- [x] DOCS_AND_STATUS — status header, decisions, architecture 51/08/11/39/47/25 amended with hashes

Still open:
- [ ] One whole-suite run after the audit (`scripts/check_all.py`, ≥16 GB free commit, no game) and its dated line here
- [ ] `tests/test_serial_voices.py` two-speaker test red on caption card length since the phrase-aware captions
- [ ] Hosted CI: a git remote or self-hosted runner (Owner's decision); the CI and e2e jobs have never run
- [ ] `uv sync --locked` into the shared `.venv` (cryptography 50, urllib3 2.8, pillow, pytest-cov)
- [ ] Serial episodes walked and retired like factual films; FILM_CONTINUE of a serial tested
- [ ] A SpentStageError at the media stage holds the film with a letter instead of opening safe mode (policy choice)
- [ ] A sweep that books credits on takes left unbooked by a hard kill
- [ ] FILM_CONTINUE checks the vault before buying; integrations/router.py answers an unreadable row in Romanian
- [ ] Romanian details in publishing/router.py and workflows/router.py
- [ ] The page shows held scenes, needs_reference, the hero view, production audio/licences/grade/cover, editorial QC, remote privacy, and labels for the new letter kinds and events
- [ ] Upload the cover (thumbnails.set) and a captions track (quota; Owner's decision)
- [ ] The three catch-up jobs at start-up collide on "database busy" (seen live 2026-10-02)
- [ ] Workforce seed without a model for new installs (SELL-10); a page for the studio's place settings
- [ ] Owner decisions: `narration_purchase`, LOCAL_MOVE, always-on host, the film ceiling figure, his music library
- [ ] The first capped paid film under EVERY_PAID_STEP (the real test)

## PHASE 0 — Foundation
- [x] Inspect repository
- [x] Define repo structure
- [x] Backend skeleton
- [x] Frontend skeleton
- [x] Database
- [x] Migrations
- [x] Config/secrets
- [x] Structured logging
- [x] Health endpoint
- [x] Base tests
- [x] Documentation bootstrap

Acceptance:
backend/frontend/DB start and tests run.

## PHASE 1 — Agent + Capability + Permission Core
- [x] Agent entity
- [x] Role contract
- [x] Skill/capability model
- [x] Tool registry (ToolReceipt + ProviderRegistry)
- [x] Permission engine (Owner Policy Kernel: stop / lifecycle / capability / health / budget gates)
- [ ] Director (Phase 2+ - requires workflow engine)
- [x] Provider registry
- [x] Ollama/Ollama Cloud adapter
- [ ] custom compatible adapter (OpenAI-compat - Phase 2+)
- [ ] fallback routing (Phase 2+)
- [x] agent messages (AgentRun envelope with full audit trail)
- [x] audit log (DomainEvent + ToolReceipt immutable history)

Acceptance:
real LLM task works (requires Ollama running, set STUDIO_OLLAMA_URL); unsupported capability is blocked ✅; Director cannot bypass policy ✅.

## PHASE 2 — Durable Automation / Events
- [x] Persisted workflow state machine (Workflow, WorkflowStep, 17 pipeline stages)
- [x] scheduler (ScheduledJob, singleton-safe leader leases, SKIP/CATCH_UP)
- [x] queue/worker (TaskQueueItem, atomic claim with worker leases)
- [x] leases/locks (time-bounded leases, heartbeat, expired lease recovery)
- [x] retry/backoff (exponential backoff calculation, retryable classification; since 2026-09-17
  every provider call and every runbook stage retries a transient fault within a bound)
- [x] circuit breaker / dead-letter queue (DEAD_LETTER status on max attempts, operator retry)
- [x] idempotency keys (idempotency_key on task_queue)
- [x] cancellation (cancellation transition in workflow state machine)
- [x] transactional outbox/event publishing (OutboxRecord, publish_pending_outbox)
- [x] WebSocket gateway (/api/v1/ws with owner auth)
- [x] snapshot/replay protocol (replay message with after_sequence cursor)

Acceptance:
workflow survives restart ✅; duplicate scheduler does not duplicate work ✅; UI can replay missed state ✅.

## PHASE 3 — 2D Office
- [x] PixiJS vs Phaser decision (Decided in ADR-PHASE3-001: lightweight native Canvas2D, <20kB bundle, 60fps, zero bloat)
- [x] top-down office canvas (Canvas 2D, DPI aware, pan & zoom 0.4x - 2.5x, fitToOffice)
- [x] generic Room/Desk (8 zones: DIRECTOR, RESEARCH, SCRIPT, AUDIO, VIDEO, PUBLISH, SERVER, LOUNGE with desks)
- [x] persistent office world state (`GET /api/v1/office/layout` + `OfficeState` tracking agents, desks, events)
- [x] character identity system (Agent avatars with role colors, badges, initial letters)
- [x] runtime-state animation map (Pulsating state rings: THINKING=amber, WORKING=blue, IDLE=green, PAUSED=gray)
- [x] speech bubbles from real messages (Auto-rendered on `agent.message_sent` or `agent.run_completed`, 5s decay)
- [x] Agent Inspector (Dialog modal `#agent-inspector`, run task, pause/resume)
- [x] Provider Room (SERVER zone with 3 server racks and real-time blinking LEDs)
- [x] content pipeline visualization (Project tokens with stage colors moving across zones)
- [x] reduced motion (`prefers-reduced-motion` CSS & disabled pulsing)

Acceptance:
all live animation comes from backend event/state. ✅

## PHASE 4 — Factual Intelligence
- [x] Idea Agent (propose_topic_idea, topic_idea table, deduplication scoring)
- [x] Research Agent (ingest_source_snapshot, extract_claims)
- [x] source metadata (url, publisher, author, credibility_score)
- [x] research snapshot/hash where practical (SHA-256 content_hash in source_snapshot)
- [x] Claim model (factual_claim with importance, confidence, status: UNVERIFIED, SUPPORTED, REFUTED)
- [x] Fact Checker (verify_claim service and REST endpoint)
- [x] claim freshness/stale state (verified_at timestamp, stale detection)
- [x] prompt-injection defense (Zone D sanitizer, delimiter stripping, inert boundary tag)
- [x] Script Writer (generate_script_draft with scene breakdowns and voiceovers)
- [x] Hook Specialist (generate_hook_options with psychological techniques & retention scores)
- [x] optional History Reviewer (supported via HISTORICAL_EVENT claim typing and validation)
- [x] optional Science Reviewer (supported via SCIENTIFIC_FACT claim typing and validation)
- [x] manual topic UI (modal dialog in frontend, open-research-btn, topic submit form)

Acceptance:
false/unsupported critical claim blocks script/publication path. ✅

## PHASE 5 — Media Production
- [x] Creative Director (automated storyboard director enforcing style, visual flow, 9:16 vertical ratio)
- [x] storyboard (Storyboard & StoryboardScene models with Content Gate verification)
- [x] Character Bible (7 core studio employees seeded with immutable palettes and roles)
- [x] image adapter (DeterministicVisualAdapter generating valid 1080x1920 SVG visual cards)
- [x] video adapter (Deterministic media synthesizer with resolution/aspect ratio validation)
- [x] TTS adapter (DeterministicTTSAdapter producing RIFF/WAVE audio with duration & word alignment)
- [x] asset provenance/rights (MediaAsset with SHA-256 provenance digest, license status, audit events)
- [x] FFmpeg editor (local FFmpeg / deterministic video assembly pipeline producing vertical 9:16 MP4)
- [x] captions — real since 2026-09-17: cues timed from the narration actually recorded, an SRT
  beside every film, burnt in above the bottom fifth by default (`captions_burn_in`) and held
  by `captions_qc`; before that the SRT was written and never used.
- [x] QC (Technical, Factual, and Rights verification checklist; since 2026-09-17 also audio
  loudness, captions and the fallback-scene ceiling)
- [~] character drift QC — since 2026-09-18 `character_drift_qc` measures: the storyboard's cast
  for each scene, the Character Bible's canonical face, hair, outfit, props, role symbols and
  palette and, where a slot holds one, the stored portrait, all carried in the same vision call as
  the picture check; a person in the wrong outfit is named with their scene and the film fails.
  Still partial, and honestly so: it reports NOT_APPLICABLE where no employee's model declares
  vision — which is every live studio today, because `seed_initial_workforce` seeds none — and
  NOT_IMPLEMENTED only where the bible holds no characters at all; the factual storyboard writes
  `character_ids_json=[]`, so on a factual film the record says no scene lists a character rather
  than passing. (It was `NOT_IMPLEMENTED` and certified nothing until 2026-09-18, and ticked in
  error before that.)
- [~] picture QC — new 2026-09-18 (`backend/app/media/picture_qc.py`): every scene's middle frame is
  cut from the finished film and one call asks whether it is a picture at all — a blank field,
  stripes, noise, garbled writing is not — and whether it shows what the scene's visual prompt and
  narration asked for. A refusal fails the film in every environment. Partial for the same reason:
  no vision model has ever answered the prompt (every test fakes the provider at its transport, by
  the Owner's rule), the check stands down NOT_APPLICABLE with its reason wherever it could not
  look, and the Director's `frames_for` cuts at most eight frames, so a ninth scene onwards is
  recorded as never looked at rather than as passed.
- [~] character reference sets — new 2026-09-18: `POST /media/characters/{id}/reference-set` fills
  the five bible slots (portrait, full body, front, side, back) with real `MediaAsset` files, one
  prompt per slot from the bible alone, the money for the whole set held before the first slot. It
  is the Owner's act — it spends image credits, refuses under STOP AUTONOMY and is named by no stage
  of the day. Corrected 2026-09-18 at the closure: the button and the per-slot chips exist in
  `frontend/src` behind a second press that states the cost, and are invisible until
  `npm run build --prefix frontend`. Open: the first filled slot is still used for every scene rather
  than chosen by shot type.
- [x] final MP4 page (Media Production UI modal with 9:16 vertical video player, QC scorecard, Character Bible)

Acceptance:
verified content → valid 9:16 MP4 with provenance. ✅

## PHASE 6 — YouTube Main Channel
- [x] channel setup wizard (ChannelRecord model, default Channel A & Channel B seeding)
- [x] brand assets workflow (ChannelBrandAsset model, tagline, avatar, banner associations)
- [x] Google OAuth — **real, 2026-09-11**: Authorization Code flow with offline access, vault-held
  refresh tokens, single-use state, channel identity read from the API. Owner-managed connections,
  several at once. See `YOUTUBE_CONNECTIONS.md`. The upload half is proven: two private uploads
  with real remote ids reached Main Channel A on 2026-09-12.
- [x] official YouTube integration (YouTube Data API v3 resumable upload protocol)
- [x] private upload — private by default; since 2026-09-17 the visibility is the channel's
  Owner-set publish policy (migration 0037), resolved once and stamped with its version, and a
  sixth gate holds a publication that would be seen to it.
- [x] remote ID verification (stores remote_video_id and full shorts URL upon confirmation)
- [x] idempotency (unique constraint on channel_id + idempotency_key prevents duplicate uploads)
- [x] scheduled release — real since 2026-09-17: a public policy with `publish_delay_minutes`
  uploads private with `status.publishAt`; before that the time was stored on the intent and
  never sent. Exercised against a faked transport only.
- [x] publication history (PublicationRecord tracking with REST endpoint & UI history table)
- [x] policy gate (5-point Content Gate: Autonomy Stop, File On Disk, QC PASSED, Factual 100%, Duplicate Protection)

Acceptance:
private test upload proven without duplicates. ✅

> **2026-09-11 — the runbook now runs the pipeline.** Eight of the twelve daily stages have real
> implementations behind them (`backend/app/runbook/stages.py`), so a day's run performs the work
> of Phases 4 to 7 rather than recording it as unconnected. `idea_generation` and `post_run` have
> no implementation and are still reported SKIPPED with that reason. The acceptance criteria of
> the phases below are unchanged: what is wired is what exists, and the stages report honestly
> where a provider or an approval is missing. Correction 2026-09-18: `build_stage_runners`
> supplies ten of the twelve stages (idea generation and post-run gained their work later on
> 2026-09-11); preflight and the daily log are the run's own. Since 2026-09-17 the serial queue
> runs before media, so the same run films the episode.

## PHASE 7 — Analytics / Growth
- [ ] analytics ingestion
- [ ] snapshots
- [ ] Growth Agent
- [ ] cohort metrics
- [ ] minimum sample thresholds
- [ ] experiments
- [ ] strategy versioning
- [ ] Director recommendations

Acceptance:
real metrics only; recommendations expose sample size/evidence.

## PHASE 8 — Workforce Autonomy
- [ ] performance scorecards
- [ ] recruitment
- [ ] benchmark suites
- [ ] hiring
- [ ] firing
- [ ] safe in-flight task reassignment
- [ ] suspension
- [ ] dynamic roles
- [ ] model/provider switching
- [ ] Director own-config restrictions
- [ ] visual hire/fire

Acceptance:
real end-to-end employee replacement and audit.

## PHASE 9 — Office Serial / Channel B
- [x] Daily Studio Log — closed by every run that did work; since 2026-09-17 yesterday's is
  closed with all of its events at the start of the run, and a closed log never changes.
- [x] ContinuityState — `continuity_state` (migration 0036): episode number, open threads,
  recurring elements, last three summaries; advances only on approval, once per episode.
- [x] live vs dramatized message separation — `narrative_projection_json` on the closed log:
  event types classified PUBLIC_SAFE or OWNER_PRIVATE by a table, private by default,
  descriptions redacted; the showrunner never reads the operational log.
- [x] Showrunner — `write_episode` grounded on the projection, with the canon in the prompt.
- [x] source-event linking — every beat cites committed events of the closed log; a private
  or invented citation fails the episode.
- [~] persistent character visuals/voices — bible lines in every scene prompt; a locked
  character's voice is bound where the Owner has bound one, else the narrator; one voice per
  scene. Since 2026-09-18 a locked *look* can also be carried as a picture: the bible's five
  reference slots hold real files once the Owner has produced them, `image_reference_for_scene`
  hands the render the reference the scene's cast has, and a character whose look is locked and
  whose reference cannot be read refuses the film rather than having a face invented for him. The
  reference reaches only an adapter that declares it can take one — the OpenAI image adapter today,
  not Runway.
- [x] serial storyboard — `storyboard_from_episode`, in the factual storyboard's exact shape.
- [~] serial QC — the Director's five computed checks and her verdict on the episode, then the
  same film QC and her serial brief (2026-09-18). Since 2026-09-18 that film QC includes the picture
  and character checks, and the serial is the one path that fills `character_ids_json`, so the drift
  check has a cast to compare; there is still no serial-specific picture check of its own, and
  nothing runs at all until an employee's model declares vision.
- [x] second channel config — the OFFICE_SERIAL slot carries a publish policy and the
  Director's leave (migrations 0037, 0038); binding an account is the Owner's.
- [~] second channel publishing — routed by the storyboard to OFFICE_SERIAL at its policy,
  tested with faked providers; no real day with Channel B bound has run.

Acceptance:
yesterday's real events → today's coherent episode with correct cast. (Code complete
2026-09-18 with every provider faked; unproven on a real day, by the Owner's rule.)

## PHASE 10 — Full Automation Hardening
- [x] daily main workflow — the background worker fires the scheduled `DAILY_RUN` and executes
  the runbook with real stage work (2026-09-11). Seeded dormant; the Owner starts the clock.
- [x] end-of-day log — closed by every run that did work (Phase 9/10).
- [x] next-day serial workflow — the `serial_queue` stage writes, reviews and storyboards the
  previous closed day's episode, and since 2026-09-17 the same run films it (the stage runs
  before media). Open: today's log is still closed at the run's hour.
- [x] Manual/Supervised/Autonomous — real since 2026-09-18: `owner_policy.autonomy_mode`
  (migration 0043, recorded AUTONOMOUS_CEO because that is what the code does), moved only by
  `change_autonomy_mode` (`POST /api/v1/owner/autonomy-mode`, versioned, idempotent, refusing a
  promotion under STOP or in safe mode and naming 51's acceptance criteria and burn-in as what it
  cannot check), and enforced by `may_act` over a tier table transcribed from 31 and 32 — read top
  down: stop, T4, safe mode, mode. `STAGE_ACTIONS` maps every stage of the day to one action and one
  tier and `mode_refusal` asks before each stage, again per film before the money is held and again
  per film before the upload; a stage above the mode is SKIPPED with the Owner's reason, and the
  preflight shows him the mode as an INFORMATIONAL line that can never fail a run. A whole day is
  tested under each of the three modes. Not implemented: 51's department-scoped autonomy — the
  column is one global mode.
- [~] approval queue — the Director approves the scripts she passes (2026-09-12) and, under the
  Owner's per-channel leave, the episodes (2026-09-18); an episode without that leave waits
  DRAFT for the Owner, and there is no queue view. Since 2026-09-18 the rows exist:
  `owner_approval_request` carries 31's Approval object (action, requester, tier, evidence, proposed
  diff, nullable cost, reversibility, expiry, approver, result), a SUPERVISED day writes one for the
  upload instead of uploading, and a standing request is reused rather than duplicated. Corrected and
  closed 2026-09-18: **he answers one now.** A request is keyed by the action *and* the film
  (`subject`, migration 0044), so a day with two films leaves two questions rather than one covering
  both; `GET /api/v1/owner/approvals` lists what waits,
  `POST /api/v1/owner/approvals/decision` answers it once, the yes is spent inside `may_act` and
  consumed before the act, a refused film comes back COMPLETED and a waiting one SKIPPED, and
  `owner_approval_request` is in `maintenance.HISTORY_TABLES`. Still open, and the reason this stays
  `[~]`: nobody writes him a letter when something waits, the queue view is in `frontend/src` and not
  in the served bundle until he runs `npm run build --prefix frontend`, and a yes cannot be
  withdrawn once given — the stop is the honest way to hold a film back.
- [x] cost reservation — since 2026-09-18 the media stage prices the plan (`estimate_film_cost_micros`) and *holds* the sum behind the write lock (`reserve_spend`, migration 0039), settles it against the real cost rows and releases it on every path where the film was not made; the watchdog frees a hold older than six hours.
- [x] hard budgets — a refusal now stops the film and the Accountant writes to the Owner the same day, and a business date has a token ceiling (`STUDIO_AGENT_DAILY_TOKEN_BUDGET`, 0 = none) enforced as the Policy Kernel's first gate (BLOCKED_BUDGET). Budgets are still set only by the Owner, and none is set on the live studio yet.
- [x] STOP AUTONOMY — the scheduler and the task queue both refuse while the stop is set, and
  since 2026-09-17 a day already running stops between stages (PARTIAL or BLOCKED, no safe mode).
- [x] stuck-job watchdog — the scheduled `watchdog` job (2026-09-17): renders stuck past three
  hours failed, unknown and retryable publications reconciled within a bound and then handed
  to the Owner, lapsed leases reported (`claim_task` reclaims them itself).
- [~] restart recovery — the service restarts the process, the clock re-attempts a day that
  could not run, the watchdog repairs what a crash left (2026-09-17); employees other than the
  VideoEditor left WORKING by a crash are not reset; the render polls the stop between scenes
  since 2026-09-17 and the media stage reads it before each film since 2026-09-18, the other
  long runners still do not.
- [~] cloud/always-on deployment option — local always-on as a Windows Scheduled Task
  (`scripts/install_studio_service.ps1`, 2026-09-17); the cloud option stays open.
- [ ] backup/restore
- [ ] chaos/failure testing

Acceptance:
full simulated unattended cycle survives failures/restart without duplicate side effects.

## PHASE 11 — Public/Fan Hooks
- [ ] public sanitized projection
- [ ] Fan/Vote/Pitch schemas
- [ ] paid-pitch RevenueSource interface
- [ ] fan-vote command pipeline
- [ ] no premature real-world commerce/spending build

The core VR$ Economy / VendorShop implementation is specified separately in PHASES 11–14 of the V5 economy roadmap section below; phase numbers should be normalized by the implementation lead into a single sequential project plan before coding.

## Always
- [x] YouTube profile images: high → medium → default selection, per-connection persistence,
  Verify/completed-Reconnect refresh, narrow CDN CSP and missing-thumbnail avatar (2026-09-11).
  Both existing connections loaded real 800×800 images in Chromium; see `YOUTUBE_CONNECTIONS.md`.
- [ ] Update CURRENT_STATUS.md
- [ ] Update CHANGELOG.md
- [ ] Update 16_DECISION_LOG.md for architecture decisions
- [ ] Run tests
- [ ] Separate mock tests from real-provider tests

## v3 cross-cutting additions

### PHASE 0 additions
- [x] CI baseline
- [x] dependency lockfiles
- [x] secret scanning
- [x] basic threat model
- [x] feature flag framework
- [x] UTC/timezone policy

### PHASE 1 additions
- [x] Owner Policy Kernel
- [x] hard-gate interface (policy kernel enforces stop/lifecycle/capability/health before run)
- [x] PromptTemplate/ContextManifest (prompt_template_version field in AgentRun)
- [x] AgentRun/ToolReceipt (full envelope + immutable receipts)
- [ ] agent concurrency limits (max_concurrent_tasks field exists; enforcement requires Phase 2 queue)
- [ ] loop/rework limits (Phase 2+)

### PHASE 2 additions
- [x] admission control/backpressure (task queue priority + worker capacity)
- [x] Manual Repair Queue (DEAD_LETTER queue + operator retry)
- [ ] compensation/reconciliation contracts
- [ ] daily preflight framework
- [x] event schema/upcasting/version tests (schema_version on all events and models)

### PHASE 3 additions
- [ ] LIVE/REPLAY/DEMO visual modes
- [ ] developer provenance overlay
- [ ] animation compression for high event rate
- [ ] public-safe projection boundary stub

### PHASE 4 additions
- [ ] source quality/freshness scoring
- [ ] content semantic duplicate check
- [ ] prompt/context retrieval tests
- [ ] factual visual-plan validation hook

### PHASE 5 additions
- [ ] deterministic fallback video format
- [ ] caption safe-zone/loudness validation
- [ ] per-scene regeneration budget
- [ ] final render checksum

### PHASE 6 additions
- [ ] channel isolation
- [ ] quota/preflight checks
- [ ] remote-state reconciliation for externally changed videos
- [ ] estimated/pending/settled revenue vs spendable VR$ separation

### PHASE 7 additions
- [ ] multi-objective Director scorecard
- [ ] model drift revalidation
- [ ] novelty/diversity metrics
- [ ] analytics lag handling

### PHASE 8 additions
- [ ] probation/shadow mode for new employees
- [ ] agent capacity planning
- [ ] delegation/manager extensibility
- [ ] public alias vs technical identity

### PHASE 9 additions
- [ ] NarrativeProjection sanitizer
- [ ] public-safe event classification
- [ ] canon correction/versioning
- [ ] provider-brand/public-name policy

### PHASE 10 additions
- [ ] SLO dashboard
- [ ] incident notification
- [ ] reliability burn-in
- [ ] release/rollback runbook
- [ ] RPO/RTO targets

### PHASE 11 additions
- [ ] WorldBuilder schema
- [ ] public moderation schemas
- [ ] External Evidence vs VR Ledger vs Forecast separation
- [ ] fan-vote command pipeline

## Release gates

Do not advance to public autonomous publishing until:
- Phase 0–6 required acceptance passes;
- no unresolved P0;
- reliability burn-in meets configured threshold;
- real provider tests documented;
- current platform policy review completed;
- backup/restore test passed.


# V4 Organizational Expansion Phases

## PHASE 11 — Dynamic Organization Foundation
- [ ] Department entity/lifecycle
- [ ] DepartmentCharter
- [ ] ManagerDelegation
- [ ] Create/Merge/Dissolve department commands
- [ ] OrgNeedAssessment
- [ ] OrgComplexity metrics
- [ ] UI department projection

Acceptance:
CEO can create a trial department with bounded manager permissions; UI reflects committed state.

## PHASE 12 — Marketing & Communications
- [ ] CMO role
- [ ] MarketingOpportunity
- [ ] Campaign model
- [ ] truthful teaser workflow
- [ ] YouTube/TikTok/Instagram/Facebook/Telegram adapter interfaces
- [ ] Telegram first practical community adapter if appropriate
- [ ] social publishing idempotency
- [ ] marketing metrics/attribution
- [ ] campaign experiments

Acceptance:
a real studio event can produce an approved teaser draft linked to tomorrow's episode, with no fabricated facts.

## PHASE 13 — Market Intelligence
- [ ] MarketSignal
- [ ] CompetitorObservation
- [ ] OpportunityHypothesis
- [ ] public-source constraints
- [ ] CEO experiment handoff

## PHASE 14 — People/HR & Persona
- [ ] HR optional department
- [ ] NarrativePersona
- [ ] fictional birthday
- [ ] relationship graph
- [ ] onboarding/probation workflows
- [ ] culture/events coordinator

## PHASE 15 — Finance / Legal
- [ ] FinOps/CFO role
- [ ] financial truth-layer separation
- [ ] unit economics
- [ ] Legal/Compliance department hooks
- [ ] compliance hold workflow
- [ ] sponsor/advertising readiness

## PHASE 16 — Company Event Engine
- [ ] Company Calendar
- [ ] MilestoneTrigger
- [ ] Team-building event
- [ ] production pause policy
- [ ] event canon
- [ ] serial event-day workflow

These phases are after core studio/channel reliability unless an earlier implementation dependency justifies moving a small foundational part forward.


# V5 Roadmap — Economy / Treasury / Procurement

## PHASE 11 — Financial Evidence + VR Ledger
- [ ] RevenueSource adapters/interfaces — no automatic importer yet; evidence is Owner-entered.
- [x] RevenueEvidence model
- [x] OwnerFundingEvent
- [x] FXSnapshot
- [x] immutable double-entry ledger
- [x] Treasury projection
- [x] mint/burn/reversal idempotency
- [x] actual provider-cost ingestion (reconciliation of estimate vs invoice variance: Phase 12)
- [x] financial audit trail

Acceptance:
- [x] verified $1 event can produce exactly 1 VR$ once;
- [x] forecast/pending values remain non-spendable;
- [x] reversal works.

Evidence: `PHASE11_ECONOMY.md`. 31 tests; end-to-end through the HTTP API against an isolated
studio. Nothing spends VR$ yet — that is Phase 13.

## PHASE 12 — Finance Dashboard / Forecast
- [ ] treasury dashboard
- [ ] budget system
- [ ] cost centers
- [ ] runway/burn
- [ ] 30/90/180 day scenarios
- [ ] P&L / Balance Sheet / Cash Flow management views
- [ ] public financial disclosure modes

## PHASE 13 — Procurement + VendorShop
- [ ] PurchaseNeed
- [ ] product specs
- [ ] online quote research adapters
- [ ] NEW/USED support
- [ ] quote TTL/revalidation
- [ ] Finance gate
- [ ] Legal/IP gate where needed
- [ ] VendorShopOrder
- [ ] inventory/fixed asset
- [ ] Asset Architect
- [ ] delivery/world placement

Acceptance:
- CEO asks for a chair → real price evidence → finance approval → VR$ purchase → office asset appears, with zero real checkout.

## PHASE 14 — Treasury Financing
- [ ] financing requests
- [ ] current-market term research
- [ ] debt capacity rules
- [ ] Legal review
- [ ] Owner/governance thresholds
- [ ] Owner capital contribution
- [ ] Owner loan
- [ ] virtual external financing model
- [ ] interest/amortization
- [ ] treasury stress/freeze states

Acceptance:
- financing is realistic, auditable, and cannot create unlimited free VR$.

Implementation sequencing note:
The economy data contracts and command boundaries should be designed early, but full UI/advanced finance can be implemented after the core content pipelines are stable.

## Phase 4 incremental evidence — Codex, 2026-09-09

- [x] Owner-selected public HTTPS URL retrieval with allowlist, DNS pinning, bounded extraction and source hashes; verified against a real IANA source.
- [x] Import retrieved text through the existing authenticated source endpoint; sanitized persistence verified in an isolated database.
- [~] Keyword search/discovery adapter and independent claim-verifier authorization — the discovery half landed 2026-09-18: each authorised site's own search address is discovered as well as typed, and a web search API the Owner connects (catalog kind `search`) may name addresses, which are filtered against the allowlist and read by the studio's own retriever. No engine is connected on the live studio. The Fact Checker has verified claims against the fetched text since 2026-09-12 and cannot verify a claim it made.
- [ ] Worker/UI integration after coordination with the active UI developer.

This increment does not close Phase 4 acceptance. See `RESEARCH_HANDOFF.md`.

## Office visual refinement — 2026-09-10

- [x] Premium pixel material and sprite detailing on the existing office scene.
- [x] Camera dock clear of the building; portrait fit regression fixed.
- [x] Desktop/fullscreen/mobile browser review and agent selection verification.

Evidence: `PIXEL_OFFICE_REFINEMENT.md`. This does not close unrelated Phase 3 functionality or later world-builder procurement requirements.

## Pixel office v2 — 2026-09-10
- [x] Figma design system: Office Palette variables, quality-bar floor (Research, 4x), character and HUD components, building/layout spec.
- [x] Frontend implementation of the same system across all nine departments: palette ramps, outlined compiled sprites with role costumes, room shells with baked light, workstation occlusion, limestone facade, glass lift, dark scene chrome.
- [x] 60 FPS measured (~6 ms/frame); 43 frontend tests; live click-to-inspect verified; no backend/API/event changes.
- [ ] Optional follow-ups: walking sprites for agents leaving their desks, daytime interior palette pass, street crowd rig on the new sprite compiler.

Evidence: `PIXEL_OFFICE_V2.md`.

## Agency identity — AMN-AI — 2026-09-10
- [x] Name introduced across interface, backend, packaging, launcher scripts and documentation.
- [x] Logo asset set derived from the source artwork (mark, lockup, favicon/ico/apple-touch, og master).
- [x] Explicit audited rename of the existing studio row (`scripts/rename_studio.py`, `studio.renamed`).
- [x] Brand rules documented; tests assert the referenced assets and the rename's audit trail.

Evidence: `BRAND_AMN_AI.md`.

## Ambient street increment — 2026-09-10

- [x] Round tires and correct traffic drawing depth.
- [x] RNG vehicle replacement and varied street actors/animals.
- [x] Device-local day/night schedule with lower night density.
- [x] Ambient dialogue separated from real agent speech; simulation and browser tests.

Evidence and deliberate limits: `STREET_LIFE.md`.

- [x] Weekly street rhythms: weighted activities/vehicles, midnight weekend continuity, coordinated groups and ordinary-passersby capacity. Verified by 33 frontend tests and five fixed-clock browser scenarios; see `STREET_LIFE.md`.

- [x] Exterior 24-hour Bucharest clock and timezone-aligned street rhythms; summer/winter transition tests passed.

- [x] Place Bucharest LED clock on its own right-side street support; verify bottom toolbar CSS loads under the actual CSP.

- [x] Inspector model assignment consistent with Settings, including older layout response compatibility, network failures and late responses. Evidence: `INSPECTOR_MODEL_FIX.md`.

## Conversation read by a person — 2026-09-11

- [x] Structured model answers (pages, claims, topics, scenes, verdicts) render as sentences and lists; raw JSON only collapsed; truncated lists salvaged with a note.
- [x] The Agent Inspector chat reads as an exchange (question right, answer left), with a live "scrie…" indicator and self-refreshing history; the exchange is saved on the run.
- [x] «Fereastră live ↗» in the inspector opens a standalone real-time window per employee (state, "Acum" line, event chain), fed from the ledger's own stream; the detail view is unchanged.
- [x] Dialogs confirmed wide in the served build (1180px measured); stale dist rebuilt.

Evidence: `scratch/verify_conversation_live.mjs` 14/14 in Chromium; 79/79 frontend tests. No backend changes.

## Pipeline answers for the Owner; expandable inspector — 2026-09-11

- [x] Investigated the duplicate "Sarah said" lines: two real owner_chat runs from the verification pass, no duplication bug.
- [x] Investigated `performance_intake` skip: the run predated the slot↔account binding by two minutes; live re-resolution confirms the next run proceeds.
- [x] Confirmed agents have no tool access (single-prompt runs); STATUS reports are filed by deterministic stage code.
- [x] Confirmed the per-channel production criteria (FLEXIBLE variants vs CONSISTENCY_LOCKED identity) are implemented end to end; open items are configuration: bind+lock character voices, route storyboards to channels (`channel_id`), pick organization defaults.
- [x] «⛶ Extende» button on the Agent Inspector: fullscreen reading of the whole chat and history, restore included. Verified 16/16 in Chromium.

## The Owner's roles: sound, video, weekly Director review — 2026-09-11

- [x] Contracts v2: sound artist and video editor steward their technology within policy and follow the Director's written indications; the Director decides from analytics and verifies weekly. Migration 0025 re-seeds only never-Owner-edited roles.
- [x] Open messages addressed to an agent enter its composed identity (identity v2) — the channel for the Director's indications.
- [x] Weekly performance review: scheduled every 7 days (active) + Owner button + POST /runbook/weekly-review; digest from recorded metrics; Director's answer filed as HANDOFF to sound and video + STATUS to her inbox; nothing published → honest skip at zero tokens.
- [ ] Owner configuration still open: bind + lock character voices (Channel B), route storyboards to channels (`channel_id`), pick organization default model/voice, connect real publications so the weekly review has numbers.

Evidence: `scratch/verify_weekly_review_ui.mjs` 5/5 live; backend 526/1; frontend 79/79.

## The Director's mandate — grow views and retention — 2026-09-11

- [x] Mission updated (migration 0026): audience growth is her primary charge.
- [x] Contract v3: instruct any employee in writing, steer channels/topics from measured performance, request budget from the Accountant with justification; Accountant answers budget requests from the books and escalates (Owner alone decides budgets).
- [x] Weekly review v2: structured answer routed to all departments + Accountant + Owner escalation; STRATEGY memory for direction; spoken summary in the office; schema violations file nothing.
- [ ] Until real publications and per-channel production exist, the mandate has no numbers to act on — the machinery waits for Phase 5/6 configuration.

## Office logic: correspondence and the day that stopped — 2026-09-12

- [x] `ConfiguredLLM` (the studio's real adapter) asks Ollama for thinking off, reports `done_reason`, and waits ten minutes; a run with no text is `EMPTY_OUTPUT` with the reason.
- [x] Runs are records while they run (`RUNNING` → final; `ABANDONED` after 45 min); a stale THINKING flag is cleared, not obeyed.
- [x] Token budgets ×3; the day runs `auto_configure` before preflight when media readiness says `NO_DEFAULT`.
- [x] Letters: thread, reply, forward, text (migration 0027); open letters enter the employee's prompt with their thread.
- [x] Employees answer their mail each worker pass; the Director reads what came back at once; a question closes, a HANDOFF stays open until done, a long thread waits for the evening or the Owner.
- [x] Letters to the Owner (decision hers / day stopped / review refused): red in the ledger, `GET /agents/messages/owner`, answered from the thread window.
- [x] Thread window on the page; the inspector's inbox opens threads.
- [x] Employees choosing a video/image/voice model by reading the vendors' pages (fetched by the studio, vendor hosts only): scores and prices recorded on the resources, `rank_candidates` reads them, fallback defaults follow, locked ones are reported on; weekly job + Owner button.
- [x] Analytics-driven adaptation wired: Google Trends (daily, `trend_snapshot`) and the studio's measured cohorts reach the Researcher's proposals and the weekly digest; the numbers themselves still wait for real publications.
- [x] Visual polish pass on the whole page, from a screenshot of every view: one text scale, actions sized to their words, the scene chrome as one bar in two groups, the ledger breathing, Settings on the dialog pattern, the inspector's contract as lists.

Evidence: `tests/test_mail.py` 18/18; backend 544/1; frontend 86/86; live on a copy of the Owner's data (`scratch` review scripts).

## The clock and durability (Phase A of running unattended) — 2026-09-17

- [x] Fault classes: a stage's TRANSIENT fault is retried in place (3 retries, 20/40/80 s) and fails the run without safe mode; a HARD fault still opens safe mode. `daily_run.fault_class`, migration 0035. Corrected 2026-09-18 (the rehearsal on the Owner's data): a failed stage, of either class, blocked every stage after it, so it cost the day and not the stage; since then it blocks only its dependants (`STAGE_PREREQUISITES`), and a HARD fault opens safe mode only in media, publish or the day's log, or for a database integrity error (`SAFE_MODE_STAGES`).
- [x] Same-day re-attempts: a BLOCKED preflight or a TRANSIENT day is tried again after 30 minutes, three attempts per business date; a date that did work is never rerun by the clock. Corrected 2026-09-18: a TRANSIENT failure is re-attempted only when it cost the day's films (`PRODUCTION_STAGES`); a day whose films went through is PARTIAL.
- [x] The daily job on the wall clock: `run_at_local` and `timezone` on the row, DST-safe, `STUDIO_DAILY_RUN_HOUR_LOCAL` 05:00; still seeded dormant, the Owner starts it.
- [x] STOP AUTONOMY cancels a running day between stages: PARTIAL or BLOCKED, no safe mode, no letter.
- [x] Provider retries: one bounded, jittered policy (`providers/retry.py`) for every adapter; a billed request that got no answer is not sent again.
- [x] Watchdog job: stuck renders failed, publications reconciled within `reconcile_max_attempts`, then NEEDS_RECONCILIATION for the Owner.
- [x] The studio as a Windows Scheduled Task (`scripts/install_studio_service.ps1` / `uninstall_studio_service.ps1`); README "Running as a service".
- [x] Settings: `STUDIO_DAILY_RUN_HOUR_LOCAL`, `STUDIO_DAILY_MAX_ATTEMPTS`, `STUDIO_DAILY_RETRY_SECONDS`, `STUDIO_STAGE_RETRY_ATTEMPTS`, `STUDIO_STAGE_RETRY_BACKOFF_SECONDS`, `STUDIO_WATCHDOG_INTERVAL_SECONDS`, `STUDIO_PROVIDER_RETRY_ATTEMPTS`, `STUDIO_PROVIDER_RETRY_MAX_SECONDS`, `STUDIO_RENDER_STUCK_AFTER_SECONDS`, `STUDIO_RECONCILE_MAX_ATTEMPTS`.
- [ ] `ScheduledJobView` exposes `run_at_local` and `timezone`, so the scheduler API and the page can show the hour.
- [ ] The long runners in `backend/app/runbook/stages.py` poll `stop_requested(engine)` between scenes and raise `TransientStageError` where only they can tell a fault is transient.
- [ ] `execute_publication` admits REMOTE_UNKNOWN without a remote id to its reconcile-by-key branch, so the watchdog resolves those rows instead of handing them over.
- [ ] Employees other than the VideoEditor left WORKING by a crash are reset (the "stuck agent runtime" item of `../architecture/18_AUTOMATION_ORCHESTRATION.md`).
- [ ] An autouse fixture in `tests/conftest.py` patching `app.providers.retry.sleep`, so the remote-state honesty test is instant again.
- [ ] An end-to-end watchdog fire with the real module through the worker (the dispatch was tested with an injected stub).
- [ ] The Owner's part: run the migration (`scripts/bootstrap.py`), install the task, confirm once in `data/studio-service.log` that an S4U logon opens the credential key, and start the clock — his recorded act. Measured 2026-09-18 by the rehearsal: the migration is done — his own start at 22:42 local ran bootstrap, and a copy taken after it was at `0045_reconciliation`; the task, the S4U check and the clock are still his.

Evidence: 66 (runbook, scheduler/worker, schema match), 28 (provider retry), 46 + 24 (media, Ollama, integration settings), 34 (existing adapter tests), 11 (watchdog) passed on the changed files; ruff, format, mypy and `check_docs.py` clean. The whole suite is the verifier's.


## HQ visual continuation — 2026-09-18

- [x] Diagnose/fix skeletal garment material fallback in isolated assets, reload,
  backup and apply to HQ; preserve live integration.
- [x] Capture a fresh native scene and compare L2 with the exact target image.
- [ ] Capture the actual browser stream at documented quality settings.
- [ ] Finish L2 on a copied level before extending the artistic pass to other floors.
- [ ] Measure game and browser performance after the visual pass.

Detailed acceptance and evidence: [VISUAL_AUDIT_2026-09-18.md](VISUAL_AUDIT_2026-09-18.md).


## Money and sources (Phases E/F of running unattended) — 2026-09-18

- [x] Cost reservation: `reserve_spend` holds a film's estimated cost behind the write lock,
  `settle_reservation` after the real cost rows, `release_reservation` on every path where the film
  was not made; the watchdog frees holds older than `STUDIO_RESERVATION_TTL_SECONDS` (6 h).
  Migration 0039 (`provider_price`, `spend_reservation`, `provider_cost_record.failed`).
- [x] Hard budgets: a budget refusal now stops the film and writes to the Owner the same day
  (`budget_refusal_letter`), and a day's tokens have a ceiling
  (`STUDIO_AGENT_DAILY_TOKEN_BUDGET`, 0 = none) enforced as the Policy Kernel's first gate with
  the verdict BLOCKED_BUDGET. Budgets are still set only by the Owner; the Accountant escalates.
- [x] Budget periods on the studio's own calendar (the `studio` row's zone), so the books count the
  business date the daily log closes.
- [x] Prices are the Owner's: `PUT/GET /economy/prices`, versioned, idempotent, provenance
  OWNER | DOCUMENTED | QUOTED | BILLED; one DOCUMENTED seed (ElevenLabs' public figure) and
  nothing guessed for Ollama Cloud.
- [x] Adapters cost their own calls from what they measured (`price_lookup` on ElevenLabs, Ollama
  and `ConfiguredLLM`), answering None and never zero without a full price.
- [x] A render the vendor refused is costed (`record_failed_render_cost`, ESTIMATED + `failed`,
  idempotent per scene).
- [x] Site search discovered, not only typed: a host test and the weekly retest read the front page
  and the OpenSearch description; the Owner's address keeps winning. Migration 0040
  (`discovered_search_template`, `discovered_at`, `last_test_reason`).
- [x] A web search engine the Owner connects (catalog kind `search`) may name addresses and nothing
  else: `find_pages` filters every result against the allowlist and reads each page with the
  studio's own retriever; the allowlist cannot be widened by an agent, a request or a result.
- [x] Host failures carry a reason code (HTTP_403, HTTP_ERROR, RATE_LIMITED, SCRIPT_ONLY, NETWORK,
  OTHER) and the preflight asks `research_health` — whether the studio can find pages — instead of
  whether a row exists.
- [x] The day's reading is the Owner's: `STUDIO_RESEARCH_CANDIDATES_PER_DAY` and
  `STUDIO_RESEARCH_PAGES_PER_TOPIC` (4 and 4, clamped 1..12).
- [x] One test of a whole day: `tests/test_autonomous_day_end_to_end.py` — the scheduled job, the
  real runbook, two films encoded and published private to their own channels, the serial filmed,
  a second tick that starts nothing; only the vendors are faked.
- [x] Price lookups reach the adapters that are actually built (`main.py`,
  `integrations/services.py`, `integrations/router.py`, `media/factory.py`), so an agent run stops
  recording `cost_vr` NULL and narration is priced in the books. Closed 2026-09-18; a whole-tree
  scan (`tests/test_phase_ef_closure_adversary.py`) holds every construction of a priced adapter,
  and names `economy/credits.py` and `integrations/discovery.py` as the two that generate nothing.
- [x] `seed_documented_prices` is called from `scripts/bootstrap.py` or the start-up seeds. Closed
  2026-09-18: in `scripts/bootstrap.py` beside `seed_chart_of_accounts`; `main.py` has no start-up
  seeds, and a price written on every server start would be a write the Owner did not ask for.
- [x] `assembler._fail_job` writes the scenes it had already built into `production_json`, so the
  failed-render cost has something to charge. Closed 2026-09-18 (committed at 441e431): the scene
  loop is wrapped, and the media stage now charges the attempt on the Owner's stop as well as on a
  vendor's refusal — a shot bought in the minute before STOP was bought all the same.
- [ ] The Accountant reconciles ESTIMATED rows against a vendor's invoice (a BILLED row replacing
  the estimates of one render).
- [x] Routes for `research_health` and a forced retest, and the *Cercetare → Surse* screen showing
  the discovered address, its origin and the failure reason. Closed 2026-09-18:
  `GET /factual/research/health` and `POST /factual/research/allowed-hosts/retest`, both behind the
  factual router's `require_owner`.
- [x] The frontend labels BLOCKED_BUDGET, and the Books office shows `reserved_usd`,
  `failed_render_usd` and `unpriced_agent_runs`. Closed 2026-09-18 in source only:
  `npm run build --prefix frontend` has not been run, so the served bundle is still the old one.
- [ ] The script-only heuristic and the OpenSearch discovery measured against live hosts — the
  first weekly retest on the live database (tests may not open a socket).
- [ ] The Owner's part: run the migration (`scripts/bootstrap.py`) to `0040_research_sources` (done by
  his own start, measured by the rehearsal of 2026-09-18: the live copy is at `0045_reconciliation`), set
  the budgets, type the plan's prices, connect a search engine or add hosts, set the publish policy
  per channel, and start the clock. Nothing above spends money on its own.

Evidence: 70 (economy files), 87 (research files), 2 + 21 + 30 + 44 + 38 (the wiring's files)
passed; the whole suite on the integrated tree 1028 passed / 1 skipped, 1029 collected; ruff,
format, mypy and `check_docs.py` clean. Nothing ran against a real model, provider or platform.
After the closure and its verification (2026-09-18): the whole suite 1067 passed / 1 skipped, ruff,
format, mypy and `check_docs.py` clean, no socket left the machine and nothing was rendered,
uploaded or paid for.


## Quality and governance (Phases D/G of running unattended) — 2026-09-18

- [x] A picture gate: every scene's middle frame cut from the finished film and asked, in one call
  for the whole film, whether it is a picture at all and whether it shows what the scene's visual
  prompt and narration asked for (`backend/app/media/picture_qc.py`). A refusal fails the film in
  every environment, beside the degenerate-still and placeholder-footage checks.
- [x] A character gate that measures: the storyboard's cast per scene against the Character Bible's
  canonical face, hair, outfit, props, role symbols and palette, and against the stored portrait
  where a slot holds one, in the same call. `character_drift_qc` stops saying NOT_IMPLEMENTED for a
  studio that has characters.
- [x] Every stand-down is recorded as one: no registry, no employee's model declaring vision, no
  frame cut, the day's token ceiling reached, a model that never reached the JSON, a scene with no
  verdict, a scene past the eight-frame cap — NOT_APPLICABLE with the reason, `passed` None, no
  failure added, the film's verdict exactly what the other gates left it.
- [x] The employee who looks is found by department (`app.agents.vision.vision_agent`: Video Editor,
  Director, Quality Assurance), primary model only.
- [x] Reference sets for the Character Bible: `POST /media/characters/{id}/reference-set` fills the
  five slots with real `MediaAsset` files under `backend/storage/character_references/{character}/`,
  refuses under STOP AUTONOMY, holds the money for the whole set through `reserve_spend`, reports
  `usd: None` rather than zero when the model has no price, and is named by no stage of the day.
- [x] The reference reaches the render: `image_reference_for_scene` and `reference_payload`, passed
  only to an adapter that declares it can take one; a locked look with no readable reference raises
  `ReferenceRequired` and refuses the film rather than inventing a face.
- [x] A second vendor the Owner approved: `approved_fallbacks` on a level of the production
  hierarchy, narrowed for a visually locked character to the technology an APPROVED identity change
  named, bounded at one alternative per purpose per scene (`MAX_FALLBACKS_PER_PURPOSE`), each attempt
  recording the connection, the model, whether a reference was sent and what it was worth. Ordered
  cheapest-first in TEST.
- [x] The autonomy mode as a fact: `owner_policy.autonomy_mode` (migration 0043, recorded
  AUTONOMOUS_CEO because that is what the code does), `change_autonomy_mode` as the only thing that
  moves it, a promotion refused under STOP or in safe mode with 51's unmeasurable requirements named
  rather than approximated, and lowering always allowed.
- [x] A risk-tier table transcribed from 31 and 32 (`ACTION_RISK_TIERS`) and one gate (`may_act`)
  reading 31's authority hierarchy top down — stop, T4, safe mode, mode — with an unclassified action
  refused `BLOCKED_UNCLASSIFIED` and a caller's own tier taken only upward.
- [x] The day mapped to tiers: `STAGE_ACTIONS` for every stage, `mode_refusal` before each stage,
  again per film before the money is held (T3 above `paid_generation_approval_threshold_usd`, five
  dollars) and again per film before the upload, which is T3 at every visibility. A stage above the
  mode is SKIPPED with the Owner's reason and the day comes out PARTIAL.
- [x] The preflight names the mode without ever failing a run: a third severity, `INFORMATIONAL`,
  with the verdict computed over the other two.
- [x] The day wired to all three: the registry and `ffmpeg_path` into `evaluate_media_qc`, the
  plan's `image_chain` and `reference_for_scene` into the render, and the Accountant pricing a still
  by the vendor that drew *that scene*.
- [x] A whole scheduled day tested under each mode, every vendor faked: MANUAL fetches no page, buys
  no shot, uploads nothing and asks nothing; SUPERVISED films the day and writes one approval request
  for the upload; AUTONOMOUS_CEO publishes private under the channel's policy with none raised.
- [ ] A real vision model answering the picture check. No model has, here or anywhere — every test
  fakes the provider at its transport by the Owner's rule, and `seed_initial_workforce` seeds no
  vision-capable model, so the live studio reports NOT_APPLICABLE until the provider catalogue sync
  records one on an employee.
- [ ] A real render drawn through the second vendor, and through the OpenAI `/v1/images/edits`
  reference path. `REFERENCE_IMAGE_VERIFIED` stays False until an Owner-approved run has drawn a
  scene that way; a 400 there would mean the multipart body is wrong.
- [x] Answering an approval — closed 2026-09-18: migration `0044_approval_answered` puts the film on
  the row (`subject`, plus `note`, `decided_at`, `consumed_at` and an index on action/subject/result),
  so one approval authorises exactly one act on exactly one thing; `GET /api/v1/owner/approvals` lists
  what waits with the cost «necunoscut» where nothing could compute one;
  `POST /api/v1/owner/approvals/decision` is versioned, idempotent by command id, 409 on an answered or
  expired request and 404 on one that never existed; the answer is read inside `may_act`'s SUPERVISED
  T3 branch, after the stop, T4 and safe mode, and consumed (`consumed_at` plus
  `governance.approval_consumed`) *before* the act it authorises. The stage wrapper asks the mode with
  `ask_owner=False` so the caller that can name the film raises the question, and
  `owner_approval_request` is in `maintenance.HISTORY_TABLES` before `command_record`.
- [x] `backend/app/media/router.py` — closed 2026-09-18: both `evaluate_media_qc` call sites pass
  `registry` and `settings.ffmpeg_path`, `start_render` passes the plan's `image_chain` (suppressed only
  for an injected adapter) and `reference_for_scene` (always), and `ReferenceRequired` is answered 422
  naming the character instead of 404 "storyboard not found".
- [x] `RunwayImageAdapter` can be handed a reference — closed 2026-09-18: `referenceImages` on the
  documented `text_to_image` task as an inline data URI, a path, an id or non-PNG/JPEG/WebP bytes
  refused before the task is submitted, `reference_images` counted 0 or 1 in the attempt's raw
  response, `ACCEPTS_REFERENCE_IMAGE` True and `REFERENCE_IMAGE_VERIFIED` False. The contract refusal
  for a model that *requires* references now fires only when none was given.
- [ ] The factual storyboard records no cast (`character_ids_json=[]`), so the character gate has
  nothing to compare on a factual film; only `serial_storyboard.py` fills it.
- [ ] The Director is not told what quality control saw: `gather_facts` filters the QC report to
  keys starting with "measured", so the per-scene verdicts do not reach her prompt.
- [ ] Department-scoped autonomy (51's V4 section): the column is one global mode, and a
  per-department override needs the Owner's department list first.
- [~] Frontend — written 2026-09-18 and not built: `frontend/src/governance.js` (new) holds the
  panel's judgements with 14 tests of its own, and `main.js`/`index.html`/`style.css` render the
  autonomy mode with its two other modes as versioned commands, the approvals list (polled at most
  every thirty seconds, silenced after a 404, «Aprobă»/«Refuză», the cost «necunoscut» where nothing
  could compute one) and the Character Bible's reference slots as chips behind a two-press button.
  Open: `frontend/dist` was not rebuilt, so the Owner sees none of it until
  `npm run build --prefix frontend`; the screens themselves have no test, because `main.js` touches the
  document at import; the refusal card sends no `note`, although the command accepts one and the stage
  reports it back to him; the character card still mixes its older English labels with the new
  Romanian; and nothing yet renders the preflight's third severity, `INFORMATIONAL`.
- [ ] The research stage's mode refusal is coarse: under MANUAL the whole fetch is skipped including
  `retest_stale_hosts`, so a MANUAL studio's host record goes stale.
- [ ] A stage the mode skips is recorded but nobody writes the Owner a letter about it.
- [ ] No approval has ever been answered by a real Owner through the real route against a real
  database: every measurement is against the test engine with the loopback-only socket guard in force,
  and migration 0044 has been walked from an empty database by every test in the run and never against
  `data/studio.db`.
- [x] The Owner is not told that something is waiting — closed in part 2026-09-18 in the readiness
  phase below: `waiting_approvals_letter` writes him one letter per business date naming every standing
  question with its own cost label and the hour the oldest expires, and nothing when nothing waits.
  Still open there: it leaves only at the day's close, and no notification is written.
- [ ] An approval cannot be withdrawn: once he says yes it stands until it is spent or expires, because
  the honest way to stop a film going out is the stop, which refuses before his answer is read at all.
- [x] `APPROVAL_EXPIRES_AFTER_HOURS = 24` — closed 2026-09-18 in the readiness phase below: it is
  `Settings.approval_expires_after_hours` (`STUDIO_APPROVAL_EXPIRES_AFTER_HOURS`, default 24, bounded
  one hour to one week), read by `backend/app/services.py` through a local import with a documented
  fallback of 24, and all three things it decides — how long an unanswered question stands, how long a
  refusal stops the studio asking again, how long a yes can still be spent — are named to the Owner
  where the setting is declared. Behaviour unchanged.
- [ ] A film the Owner refused in the *media* stage still lands in `awaiting_owner` and reports SKIPPED
  rather than the publish stage's COMPLETED distinction between a question and a decision; the subject
  is on that stage's request, so his answer is already per film there.
- [ ] The size of an inline reference is not checked: Runway publishes a limit on how large a data URI
  may be, the number was not read (it needs the vendor's documentation), and no guard invents a
  threshold — a sheet too large comes back as a vendor refusal on the first live run.
- [ ] Whether a Runway model accepts an *optional* reference is not a per-model fact the adapter can
  read: `parse_model_contract` records only `needs_references` and `integrations/discovery.py` filters
  stored `api_metadata` to a fixed field list, so `referenceImages` is treated as a property of the
  `text_to_image` task.
- [ ] The Owner's manual quality control can now spend tokens, metered only by the day's ceiling and
  cached nowhere, because caching a measurement is how a gate starts certifying what it did not measure
  this time.
- [ ] The Owner's part: produce the character reference sets, choose the autonomy mode, answer the
  approvals a SUPERVISED day leaves him, approve the fallback vendors (and set
  `paid_generation_approval_threshold_usd` if five dollars is the wrong line), and run
  `npm run build --prefix frontend` so the panel exists for him. Nothing above spends money on its own.

Evidence: 11 (`tests/test_picture_qc.py`, new), 20 + 7 (one test appended each to
`tests/test_phase5_media.py` and `tests/test_cycle_fixes.py`) and 77 across the other callers of
`evaluate_media_qc`; 19 (`tests/test_character_references.py`, new), 21, 36 and 18 across the media
selection, provider and production-policy files, with 166 across the neighbouring suites; 21
(`tests/test_autonomy_modes.py`, new) and 26 (`tests/test_foundation.py`), with 45, 6 and 6 across
the agent, publish-policy, reset, schema and route-authorisation files; and the wiring's 29, 45 and 5
(`tests/test_daily_run_stages.py`, `tests/test_phase10_runbook.py`,
`tests/test_autonomous_day_end_to_end.py`). The whole suite on the integrated tree: **1148 passed, 1
skipped**; ruff, `ruff format --check` (384 files), mypy (143 source files) and `check_docs.py`
clean. Nothing ran against a real model, provider or platform; no run was queued and no credit was
spent.

Evidence added by the closure of 2026-09-18, each figure named for the part that measured it and no
whole-suite run made since: `tests/test_approvals.py` **18** (new) and 231 Python tests in all across
the governance part's four files and every neighbouring suite its change can reach, with ruff, ruff
format, mypy (187 source files) and `check_docs.py` clean; **98** across `tests/test_phase5_media.py`
(23), `tests/test_media_providers.py` (41), `tests/test_picture_qc.py` (14) and
`tests/test_character_references.py` (20), ten of them new, plus **88** across the Runway-connection,
readiness, editorial-quality and media-selection suites; `npm test --prefix frontend` **102**, fourteen
of them the new `frontend/tests/governance.test.js`, with `npm run check --prefix frontend` clean; and
`scripts/check_docs.py` with `tests/test_documentation.py` for the documents. The migration chain is
0039 → 0040 → 0043 → 0044 and `main.py` pins `0044_approval_answered`. No provider was called, nothing
was rendered, no run was queued and no credit was spent.

## Readiness for the first day — 2026-09-18

- [x] Five preflight checks for what only the Owner can supply, each reading the database and nothing
  else: `spending_budget` (no budget active at all), `model_prices` (the models the day's employees
  think with, priced on both token units), `vision_capability` (`vision_agent` finds nobody),
  `character_references` (a slot holding an asset id whose row exists and whose file is still on disk)
  and `serial_channel` (the serial's slot bound, and the Director's leave to approve episodes).
- [x] None of the five blocks the day: `serial_channel` INFORMATIONAL always,
  `character_references` DEGRADING only for a character whose look is *locked*, and the verdict
  computed over BLOCKING and DEGRADING only, so a studio with nothing configured still reports exactly
  `stop_autonomy` and `llm_provider` as blocking — held by a test, not by the checks happening to pass.
- [x] `APPROVAL_EXPIRES_AFTER_HOURS = 24` lifted out of `backend/app/services.py` — closed 2026-09-18:
  `Settings.approval_expires_after_hours` (`STUDIO_APPROVAL_EXPIRES_AFTER_HOURS`, default 24, bounded
  one hour to one week), read through a local import with a documented fallback of 24, with all three
  meanings named where the setting is declared. Behaviour unchanged.
- [x] A role may prefer a capability: `ROLE_PREFERENCES` + `seed_role_preferences` write the PREFERRED
  row on the Video Editor's role, `prefer_capable_models` acts on it writing `agent.model_preferred`
  and never `agent.model_assigned`, and an employee whose models the Owner saved is not touched.
  PREFERRED is not a gate and never becomes one.
- [x] `Capability(name="vision")` seeded as a row and attached to no proposed model;
  `SEEDED_MODEL_CAPABILITIES` enumerates the four text capabilities in place of the loop that wrote
  every capability onto every model. `sync_provider_models` attaches vision where the vendor declares
  it.
- [x] A factual scene records its cast (the scriptwriter's list, then the requested picture's names,
  never the narration, never a first name followed by another capitalised word), and a film that shows
  nobody says so once in `media.storyboard_created` (`scenes_with_cast`, `cast_note`), read back by
  `storyboard_cast_note` and returned by `get_storyboard`.
- [x] `waiting_approvals_letter`: one letter per business date about the questions still standing, with
  the request's own `cost_label` and the hour the oldest expires, nothing written when nothing waits,
  called by `reconcile_day` as its first act.
- [x] Migration `0045_reconciliation` and `PUT`/`GET /economy/reconciliations`: an invoice over a period
  or one named thing writes the BILLED row at the hour of the last spend it pays for, stamps
  `reconciled_at` on the estimates it covers (which `spend_since` then skips), keeps every unmatched row
  on the row with its reason, and a correction reverses the previous posting and re-adopts its
  estimates. `expected_version` is required, not optional. Head pinned `0045_reconciliation`; 0046 free.
- [ ] `model_prices` covers the LLM token sides only — the primary model of each ACTIVE agent, on
  `per_1m_input_tokens` and `per_1m_output_tokens`. The voice price (`per_1k_characters`) and the motion
  and image prices (`per_second`, `per_generation`) are not checked: naming the voice kind honestly
  means reading the media selection through the vault rather than the price table, and pricing a motion
  model means knowing which model a plan will pick.
- [ ] The secondary and tertiary model slots are not priced by the check, because `vision_agent` counts
  only the primary model and the two checks must agree about which model an employee runs on.
- [x] Closed the same day — 2026-09-18: `prefer_capable_models` has its second call site at the end of
  `sync_provider_models`, immediately *after* `apply_llm_allocation` and inside its own try/except, so
  a seeing model admitted through the Owner's own sync reaches the Video Editor in that same sync — not
  at the next seed and not at a restart. `record_declared` a few lines above is the only code that ever
  writes `vision` on a model, so the sync is the first moment one exists as a row.
- [x] Closed the same day — 2026-09-18: the guard that protected the Owner's choice read the studio's
  own allocation file as his hand, because `apply_llm_allocation` writes `agent.model_assigned` too, so
  the first sync of any studio killed the preference for a choice he never made. `_owner_chose_models`
  judges the *last* event that moved her models, and compares her three slots against
  `config/workforce_seed.json` through `resolve_model`; a role the file does not name, and a file that
  cannot be read, are both read as his.
- [x] Closed the same day — 2026-09-18: `RoleView.preferred_capabilities`, filled in `list_roles` from
  the PREFERRED rows, beside `required_capabilities` and never merged into it — a preference listed as a
  requirement would tell the Owner his Video Editor cannot work without a seeing model. Additive,
  defaulting to `[]`.
- [ ] One corner `_owner_chose_models` cannot decide from the record: an Owner who assigns an employee by
  hand to exactly the three models his own allocation file already names for her role is read as the
  file, and she may be moved. Bounded (the move only ever goes to a model declaring everything the role
  requires as well as prefers, and writes `agent.model_preferred`), and closing it means marking the
  assignment's origin in the `agent.model_assigned` payload — `backend/app/integrations/services.py`,
  its own decision.
- [x] Closed the same day — 2026-09-18: `backend/app/media/picture_qc.py` reads the board's record, and
  `character_drift_qc` reports in order the guessed-names line, the board's own note, "no character in
  this film could be compared with the bible", and only then the old sentence, which now means only what
  it says. The status stays NOT_APPLICABLE with `passed` None either way.
- [x] Closed the same day — 2026-09-18: the cast reading itself was the larger fault.
  `_characters_named_in` counted a bare given name whenever the next word was lower case, so "Hurricane
  Elena made landfall" cast the Fact-Checker into a column the assembler, the factory's
  `referenceImages` and the locked-look refusal all read. It gains a `given_names` flag (one matcher,
  two readings, no drift), `_scene_cast` returns `(stated, guessed)`, and `character_ids_json` carries
  the stated cast only: the writer's `characters` list read by given name, plus whole canonical names in
  the requested picture.
- [x] Closed the same day — 2026-09-18: the guess is kept, never acted on. `media.storyboard_created`
  carries `guessed_cast` beside `scenes_with_cast` and `cast_note`, read back by
  `storyboard_cast_record` (`storyboard_cast_note` is now a thin reader over it); `cast_note`
  distinguishes `NO_CAST_BY_DESIGN` from `NO_CAST_ONLY_GUESSED`. No column, no migration — 0046 stays
  free.
- [x] Closed the same day — 2026-09-18: `evaluate_pictures` asks about a guessed name in the same single
  look and records it `status: "OBSERVED"`, `basis: "guessed"`, counted in `characters_observed` and
  never in `characters_measured`; it can never enter `character_failures` or move
  `character_drift_qc.passed`, and it pulls no stored portrait into the question.
- [ ] The guessed cast is not in the REST answer: `get_storyboard` returns `cast_note` and not the map,
  so the Owner cannot see on the storyboard page which names the studio read and refused to cast on.
  `data["guessed_cast"] = storyboard_cast_record(...)["guessed"]` beside the note, plus a line in
  `frontend/src`, is the whole of it.
- [ ] `backend/app/media/serial_storyboard.py` writes no `guessed_cast` — correct, its cast comes from
  the episode roster and is always stated — so `storyboard_cast_record` answers the empty record for
  serial boards. A later reader must not take that emptiness for "nobody is in it".
- [ ] An employee's run is not reconcilable: `spend_since` sums `agent_run.cost_vr` separately and those
  figures never pass through `provider_cost_record`, so an Ollama Cloud invoice cannot yet replace the
  token cost the studio computed for itself.
- [ ] An invoice matches on a correlation exactly and knows one default key, `render_job_id`; a hosting
  charge or a monthly subscription must be reconciled by period or with a key the Owner names. No
  matching by reference prefix was invented.
- [x] Closed the same day — 2026-09-18: `waiting_approvals_letter` is called from `_media` the moment
  the refusal is recorded, guarded by `refusal.get("approval_id")` so a MANUAL refusal writes nothing,
  and `reconcile_day`'s call is kept. `_letter_once_a_day`'s business-date idempotency makes the two
  callers safe: one letter a day, whichever end of the day notices first. The Owner now has the whole
  twenty-four hours rather than the remainder after the run's close.
- [x] Closed the same day — 2026-09-18: `estimate_film_cost_micros` returns `unpriced`, `caveat` and
  `complete`; `unpriced_caveat`/`UNPRICED_CAVEAT_PREFIX` (`backend/app/economy/budget.py`) are the one
  wording, and the media stage carries it to the hold's note, the Owner's question and the Accountant's
  letter, where `_cost_caveat` and `approvalCaveat` read it back by its first words and yield "" when it
  is absent. The letter strips it out of the 120-character evidence clip first, because that clip cut it
  mid-sentence.
- [x] Closed the same day — 2026-09-18: `frontend/src/readiness.js` (new) holds `RUNBOOK_CHECK_LABELS`
  with a Romanian line for the five new checks and for `autonomy_mode`, `checkVerdictWord`
  (BLOCHEAZĂ / DEGRADEAZĂ / INFORMATIV, an unknown severity printed as it came), `checkClassName`
  (`rb-informational` neutral, no class at all for an unknown severity) and `approvalCaveat`; `main.js`
  imports them and `style.css` gains the two rules. Separate module because `main.js` touches the
  document on import and cannot be loaded by `node --test`.
- [x] `RUNBOOK_CHECK_LABELS` has no entry for `youtube_channel_binding`, which `run_preflight` also
  emits: it showed by its code name before this phase and still does. Anyone adding a check to
  `backend/app/runbook/preflight.py` must add a line there. Corrected 2026-09-18, measured in the
  tree: it has one, «Sloturi de canal legate de YouTube», since the module was created; the three
  checks added after the rehearsal have theirs too.
- [ ] The Accountancy office still needs the reconciliation list and its form, and the cost list must
  show `reconciled_at` and the two new labels, or a row that no longer counts looks like one that does;
  and `frontend/dist` is still not rebuilt, so the Owner sees none of the panel's new words until
  `npm run build --prefix frontend` — his own launch act, step 2 of his checklist. Nobody has yet
  looked at an INFORMATIV card or an amber caveat in a browser.
- [ ] The caveat is stored in the request's `evidence` text and read back by its first words instead of
  living in a column, because a column needs migration 0046 and `backend/app/services.py` /
  `backend/app/schemas.py` were out of scope. A column is the right shape; three readers move onto it
  together when one is taken.
- [ ] `estimate_film_cost_micros` still does not price the stills at all (it prices narration plus the
  motion ceiling), so a film's image spend is outside the figure rather than counted as zero inside it.
  Naming that in the caveat would be a claim the function cannot measure.
- [ ] `waiting_approvals_letter` is called from `_media` without a try/except, matching the unguarded
  `budget_refusal_letter` call four lines below it: if the Accountant's desk raised from inside it the
  media stage would fail instead of returning SKIPPED. Whether both should be guarded belongs to whoever
  owns that stage's failure semantics.
- [ ] Nothing here has met a real vendor, a real model or a real invoice. Every test fakes every
  provider at its transport and `tests/conftest.py` refuses every non-loopback socket, so whether a
  model that declares `vision` answers the picture gate's schema on real frames, and whether a real
  invoice reconciles cleanly, are both the Owner's first measurement.
- [ ] The Owner's part, in order: the fourteen numbered steps of «Ce are Owner-ul de făcut» in
  `CURRENT_STATUS.md` — migrate, build, read the preflight, budgets, prices, token ceiling, sites and
  search engine, channels and their policy, a model that can see, the character reference sets, the
  fallback vendors, the autonomy mode, then the clock, and the invoice reconciliation after the first
  real spend. Nothing above spends money on its own.

Evidence, each figure named for the part that measured it and **no whole-suite run made by any of
them**: `tests/test_readiness.py` **11** (new) and `tests/test_phase10_runbook.py` **46**, with
`tests/test_approvals.py` **18**, **144** across the daily-run, director, pipeline, research, reset,
scheduler, sources and media-toolchain files, **70** across approvals, autonomy modes, books and the
closure adversary, and **5** whole-day tests; **18**, **28**, **16**, **22** and **10** in
`tests/test_phase1_agents.py`, `tests/test_phase5_media.py`, `tests/test_picture_qc.py`,
`tests/test_character_references.py` and `tests/test_editorial.py`, with **83**, **51**, **87** and
**138** across nineteen neighbouring files — 359 in all; `tests/test_reconciliation.py` **11** (new),
`tests/test_books_and_history.py` **17**, `tests/test_phase11_economy.py` **34**,
`tests/test_pricing_truth.py` **18**, `tests/test_schema_and_audit_trail.py` **3**, **188** across the
ten files the migration-head move in `main.py` can reach and **5** whole-day tests; and
`scripts/check_docs.py` with `tests/test_documentation.py` for the documents. `ruff`,
`ruff format --check` and `mypy backend` clean on every changed file. The chain is 0039 → 0040 → 0043
→ 0044 → 0045 with `main.py` pinning `0045_reconciliation`, and 0046 is free. No provider was called,
nothing was rendered, no run was queued and no credit was spent.

Evidence added by the closure of 2026-09-18, each figure named for the part that measured it and **no
whole-suite run made by any of them**: `tests/test_seeing_employee.py` **5** (new; red first at 1
passed / 4 failed) inside **60** with `tests/test_phase1_agents.py`, `tests/test_multi_llm.py` and
`tests/test_provider_discovery.py`, plus **54** across picture QC, workflows, the factual suite and
the truthfulness gates and **79** across picture QC, readiness, the readiness adversary and the
runbook, with `ruff`, `ruff format --check` and `mypy` clean on its two backend files;
`tests/test_phase5_media.py` **30**, `tests/test_picture_qc.py` **17** and
`tests/test_character_references.py` **23** — **70** together — with **72** across picture QC, the
seeing employee and editorial quality and **91** across the daily run, the serial pipeline, the
readiness adversary and the production policy, `ruff` and `ruff format --check` clean on its five
files; `tests/test_phase11_economy.py` **36**, `tests/test_daily_run_stages.py` **34**,
`tests/test_approvals.py` **20** and `tests/test_books_and_history.py` **17**, with **234** across
those four and six neighbouring suites, and `node --test tests/readiness.test.js` **8** (new) inside
`node --test tests/*.test.js` **110** with `npm run check --prefix frontend` clean; and
`scripts/check_docs.py` with `tests/test_documentation.py` for the documents. No migration was taken:
the head stays `0045_reconciliation` and **0046 is still free**. One failure in the tree belongs to no
part of this closure and is reported rather than repaired: `mypy backend/app/media/picture_qc.py`
line 285 (`union-attr` on `board.id`, a narrowing gap and not a runtime fault). A second was closed
in the tree while these documents were written —
`tests/test_phase_dg_closure_adversary.py::test_only_the_owners_command_module_reaches_an_approval_row`
had begun to fail because its whole-tree scan for the string "ApprovalRequest" found a docstring line
the Accountant gained in this phase, and the scan now walks the parsed module rather than its
characters: **12 passed** afterwards. No provider was called, nothing was rendered, no run was queued,
no credit was spent and `data/studio.db` was not opened.


### Stream stability correction — 2026-09-18

- [x] Reproduce and fix stale fallback retries interrupting a recovered live stream.
- [x] Verify real browser video recovery beyond the old retry deadline.
- [ ] Verify the authenticated Owner page after reload; separately investigate traffic-only popping if it persists while video time continues.


## The rehearsal on the Owner's data — 2026-09-18

- [x] A whole scheduled day rehearsed on a copy of the Owner's studio: the real scheduler, worker and
  runbook, every paid vendor faked, every outside connection refused. The copy was made from a plain
  file copy of `studio.db`, its `-wal` and its `-shm`, and the live file was never opened. An
  independent audit re-ran it on a fresh copy, with the verdict FIX_FIRST. The repeatable harness is
  `tests/test_rehearsal_on_a_copy.py`, opt-in through `STUDIO_REHEARSAL_DB`; it refuses
  `data/studio.db`.
- [x] Defect 1, "one statistics read stops the day, and a 4xx from Google halts the studio":
  `MetricsUnavailable` for every transport and authentication failure of the analytics adapter;
  «fără date» per publication, with one ledger event per refused account; `STAGE_PREREQUISITES`, so
  a failed stage blocks only its dependants; `SAFE_MODE_STAGES`, so safe mode opens only for a P0;
  the re-attempt only after a transient fault that cost a film; PARTIAL for a day whose films went
  through.
- [x] Defect 2, "the books charge motion never generated": `motion_was_bought` in both render
  books, and a refused shot teaches no price.
- [x] The run's headline counts what each stage produced (`produced`, `summary`,
  `stages_productive`), so 12/12 no longer stands for a day that made nothing.
- [x] Narration on Flash and Turbo at the documented half (`eleven_flash_*`, `eleven_turbo_*`,
  0.11 USD per 1k characters), with any Owner price outranking every documented one.
- [x] Every paid path faked in the tests. DNS and asyncio's `sock_connect` are refused by the suite's
  guard. One shared list of eight fakes, including the motion chooser and the analytics adapter. A
  call-graph scan (`tests/test_no_paid_path_escapes.py`) fails on any paid adapter reachable from the
  day without a fake.
- [x] The preflight says what will stop tomorrow: `youtube_upload_access` (BLOCKING),
  `youtube_statistics_access` and `daily_budget_films`, the publishing line saying it reads the
  stored state, and a summary that names `first_stop`.
- [x] `39_DAILY_AUTONOMOUS_RUNBOOK` states which stage needs which and that a failed stage blocks
  only its dependants. It is re-hashed, and every sentence that said a failed stage costs only
  itself is corrected with a dated marker.
- [x] `SCOPES` (`backend/app/youtube/services.py`) asks Google for `yt-analytics.readonly`. Before
  that, the reconnect the preflight tells the Owner to make could not grant statistics access.
  Added by another part while these documents were being written, with
  `tests/test_youtube_connections.py::test_the_consent_asks_for_the_statistics_the_day_reads` (1
  passed in this documentation part's run). His consent screen asks for one more permission, and
  each existing connection must be reconnected once, after his studio runs this code.
- [ ] The uploader (`backend/app/providers/youtube.py`) writes `youtube.token_refresh_failed` with
  `during='upload'` when Google refuses its refresh. Until then, an upload-side refusal reaches the
  preflight only after the statistics read meets the same dead token.
- [ ] The film's hold prices narration at the voice model's own price (`price_row` for the model in
  `media_production_config`) rather than the dearest active ElevenLabs price
  (`economy/budget.py`, `estimate_film_cost_micros`). The dearest price stays only as the fallback.
- [ ] The panel shows `run.summary`, `stages_productive`, each stage's `produced`, the reason «Nu a
  fost încercată: etapa de care depinde, «X», a eșuat.» and the preflight's `first_stop`; a PARTIAL
  run's `stopped_at_stage` reads «etapa eșuată» (`frontend/src/main.js`); and `frontend/dist` is
  rebuilt by the Owner. Corrected 2026-09-19:
  - done in `frontend/src`: the summary, `stages_productive`, `produced` and `first_stop`, through
    `frontend/src/day_outcome.js`;
  - the dependant's reason was already shown as the stage's reason line;
  - what stays open is «etapa eșuată» and the rebuild. See «After the rehearsal — 2026-09-19»
    below.
- [ ] `backend/app/runbook/stages.py`'s module docstring still says a raised fault «stops the day».
  `_performance_intake` could carry the first «fără date» reason in its own reason line.
- [ ] The paid-path scan and a fixture's fakes extended to the other scheduled entry points: the
  watchdog (`workflows/watchdog.py:175` resolves the publisher through `integrations.services`),
  `director_loop`, `model_review`, the catalogue refresh and the reference-set route.
- [ ] The free rehearsal re-run on a fresh copy after the fixes, as the audit recommended before any
  paid day.
- [ ] The Owner's part, from the rehearsal. Each item is a dated line in «Ce are Owner-ul de făcut».
  - Verify or reconnect *Nexus Curiosity* and *Inside The Nexus*, granting statistics access.
  - Move his Google OAuth app out of Testing.
  - Type the Ollama Cloud prices and his voice plan's price.
  - Decide on the 29 VERIFIED_PASS scripts of 2026-09-12.
  - Choose the mode and the environment the migrations wrote for him.
  - Before PRODUCTION, raise the DAILY budget to at least 24 USD, or lower the per-film motion
    ceiling to at most 7.5 USD. Otherwise the 15 USD budget holds one film, not two.
  - Grant the Director's leave, produce the reference sets (about 0.80 USD) and start the clock.
- [ ] Measured only by a real day, watched:
  - whether Runway returns usable clips at the estimated credits;
  - whether his models answer the idea, Director and Accountant schemas;
  - whether a vision model answers the picture gate on his frames;
  - whether the reviewers catch narration its cited claim does not support (corrected 2026-09-19:
    a computed check now refuses it before any money is spent; a real day measures whether a real
    writer repairs the script within the exchange budget);
  - whether the Publisher titles the serial as the episode;
  - which of his 36 hosts are readable today.

Evidence, each figure named for the part that measured it:
- The rehearsal: the opt-in test 1 passed on a fresh copy.
- The audit: the opt-in test 1 passed on its own fresh copy, and the whole suite 1265 passed, 2 skipped
  on the tree as it stood at the rehearsal, before the fixes.
- The failure-and-analytics part: `tests/test_phase7_analytics.py` 18,
  `tests/test_day_survives_a_stage.py` 14 (new), 124 across the runbook, mail, B/C-adversary and
  daily-run-stage files, and 202 passed, 1 skipped across ten related files.
- The books part: 13 new cases in `tests/test_books_and_history.py` (red first at 9 passed, 4
  failed), `tests/test_pricing_truth.py` 22, and 158 across seven economy and media files.
- The fakes part: 14 passed, 1 skipped across the scan, the whole-day test and the rehearsal; 340
  passed, 1 skipped across the `getaddrinfo`, research, provider and adversary files; and the opt-in
  rehearsal 1 passed on the scratchpad copy, all twelve stages COMPLETED, with 0 refusals to a paid
  vendor.
- The preflight part: 30 across the two readiness files (red first at 17 passed, 12 failed), 130
  across the preflight's consumers, and `node --test frontend/tests/readiness.test.js` 8.
- The documents: `scripts/check_docs.py` and `tests/test_documentation.py`.

No part made a whole-suite run. No migration was taken, and the head stays `0045_reconciliation`. No
provider was called, no run was queued on the live studio, no credit was spent, and `data/studio.db`
was never opened.

### After the rehearsal — 2026-09-19

- [x] The narration is measured against its claims and its topic (`backend/app/factual/grounding.py`,
  new). The rehearsal's telescope script on the Nepal topic cited a SUPPORTED claim and passed the
  factual gate, the story review and the Director.
  - What it asks: each cited claim appears by two of its terms, the topic by two of its terms, and
    no more than half of the narration's numbers and names come from nowhere.
  - What it returns: NOT_MEASURED does not pass.
  - Where it refuses: the story review's blocking check `narration_is_grounded` (REVISE, then
    REJECT at the last exchange), `_director_approves`, `story_gate` before the shot descriptions
    and the render, and the Director's last look (`gather_facts`).

  It only adds refusals, and serial episodes are not measured.
- [x] Calibrated on the real model's 31 scripts of 2026-09-12. Both approved films pass (LHC
  f243bf48, ATLAS 37fc8ef6). 25 of the 29 waiting pass, and the 4 refused each cite a claim their
  narration never says.
- [x] `50_CONTENT_GATE_MATRIX` names the gate and what it certifies, and is re-hashed (`a436dab0…` →
  `6750c35d…`).
- [x] The panel says what the day made (`frontend/src/day_outcome.js`, new, 9 node tests): the run's
  `summary`, each stage's `produced`, `rb-empty` for a COMPLETED day that made nothing, and
  `first_stop` above the preflight list. A missing count is never read as zero.
- [x] The module docstring of `backend/app/factual/grounding.py` says two letters of prefix slack,
  as `SUFFIX_SLACK` does (the verify part, 2026-09-19).
- [x] Spelled-out numbers are read as numbers in English and Romanian, and ranks from third to
  tenth on both sides. Before, a faithful narration saying «six hundred million dollars» was
  refused (the verify part, red at 3 failed, then 22 passed).
- [x] Two fixtures that broke the writer's brief now narrate what their claims say:
  `tests/test_phase_bc_adversary.py` and `tests/test_search_step.py`.
- [ ] What a word count cannot hear stays the Director's: negation, one claim said with the others
  carried by generic and topic words, keywords in unrelated sentences. Stricter rules refuse the
  Owner's approved LHC and ATLAS films. «opt» and «nouă» still read as 8 and 9.
- [ ] A PARTIAL run's `stopped_at_stage` reads «etapa eșuată», and `frontend/dist` is rebuilt by
  the Owner.
- [ ] The Owner's part: 4 of the 29 waiting scripts (92028a88, 8d4f7306, aa3da89f, 670d6279) fail
  the check. If he approves one by hand, `story_gate` holds it. This is the dated line in step 12 of
  «Ce are Owner-ul de făcut».
- [ ] Measured only by a real day: whether a real writer, given the Romanian note, repairs a refused
  script within the exchange budget. Also untested: claims whose sources are in a language other
  than English, beyond a Romanian narration of English claims.

Evidence, each figure named for the part that measured it:
- The grounding part: `tests/test_script_grounding.py` 15 (new), `tests/test_editorial.py` 16
  (3 new), and 352 passed, 1 skipped across seventeen factual, editorial, pipeline, runbook, media,
  publishing and whole-day files, the skip being the opt-in rehearsal. `ruff check` and
  `ruff format --check` were clean on its six files.
- The panel part: `node --test tests/day_outcome.test.js` red first (0 passed, 1 failed, the module
  missing), then 9; `npm test --prefix frontend` 124; tsc clean; and a scratch `vite build`.
- The verify part: a whole suite of 1523 passed, 4 skipped, 2 failed on the tree it found (both
  fixtures, corrected); `tests/test_script_grounding.py` 22; the seventeen files 359 passed, 1
  skipped; `ruff check` clean; `mypy backend` clean on 191 files; `npm test` 125.
- The committing session: a whole suite of 1518 passed, 4 skipped, 12 failed, 2 errors, all 14
  the machine out of commit memory (`MemoryError`, FFmpeg dying mid-encode, Windows low-memory
  events at 14:09, 14:14 and 14:20); their seven files again: 169 passed.
- The documents: `scripts/check_docs.py` passed, and `tests/test_documentation.py` 3 passed.

No provider was called, no run was queued, no credit was spent, and
`data/studio.db` was never opened.

## The interface, brought to a finish — 2026-09-22/23

- [x] Three visual directions built on the real code and photographed; a judge chose the cinematic
  dark one and wrote the specification (`<scratchpad>/ui/SPEC.md`).
- [x] One token block: six grounds, three hairlines, four inks, rationed gold, rhythm and metric
  tokens, an eight-step type scale. Zero colour and zero font-size literals below it.
- [x] The page composes with no dead area at 1024, 1280, 1440, 1920 and 2560, and never scrolls
  sideways.
- [x] The ledger register: time rail, kind rails, folded repeats (proven by 7 tests), a one-time
  arrival highlight.
- [x] One dialog shell for all eight plus the inspector; a section rail for media, daily run and
  treasury (`frontend/src/dialog_rail.js`, 8 tests).
- [x] The finishing pass: one type scale, tabular figures by default, four button states, one tag
  system, one shape per empty/loading/error state, motion with `prefers-reduced-motion` honoured.
- [x] Adversarial verification: 655 contrast pairs per width (0 failures), a real Tab walk, Escape
  on all eight dialogs, 0 console errors and 0 missing fixtures at four widths. 143 tests pass.
- [x] A harness that opens the interface without the studio: 254 answers captured from a copy of
  the database, secrets blanked, loopback only.
- [ ] The research dialog has no section rail, and it is the longest in the product.
- [ ] The per-agent «Live window» still carries the old light palette as literals.
- [ ] The login page: the gold line breaks the ration, the brand artwork sits on a pale plate, and
  the screen is otherwise empty.
- [ ] The thin scrollbar is unverified (the harness's browser hides scrollbars) and the interface
  has never been photographed over the live Unreal stream.

## The page amazes a first-time visitor — wave 1 (2026-09-24)

- W1 done (live readout, fps source, «Acum» quiet threshold, socket reconnect, modules map, canvas real sky) and W13 done (cache headers). Open from this pass:
- the Owner decides whether the canvas street's random ambient life (traffic, pedestrians, sky events incl. the UFO) stays, goes, or is tied to real data;
- W2 brings the Unreal level onto the real sky, then the frozen-frame and Unreal-fps readout states get photographed live;
- recapture the shooter's snapshot fixture after the backend restart;
- re-read the story maturity when the serial workflow's S1/S6 land;
- consider a per-stage runbook heartbeat, so «Acum» can key on the stage rather than on any event.

- W3 done, and W9 done except number formatting. Open:
- Intl.NumberFormat('ro-RO') on figures ('50000 VR$' becomes '50.000 VR$');
- re-run the page contrast sweep with the grain;
- the renderer's first composite (about 97 ms at sign-in) goes with W4;
- photograph the key light over a live Unreal stream once W2 runs;
- decide whether the title may show real weather before the key (a public read-only weather route, backend office/router.py);
- W5 plates will replace the title's key art automatically (plates.json).

- W6 and W8 are done on the page. Open:
- decide and add media-src 'self' blob: to the CSP in backend/app/main.py: the Media dialog's 'Redă' player uses a blob: URL, which the current policy very probably blocks on the real server (the poster does not need it);
- a backend poster JPEG at render time, which would spare the page the decode;
- the Unreal HQ reacting to milestones through LiveStream.send, with the Blueprint side not yet inspected;
- re-check the moment payloads when the serial workflow's story changes land (episode_number, reviewed_by);
- a per-stage runbook heartbeat, so the gold 'running' segment and «Acum» can key on the stage;
- a figure for the waiting count on the pipeline's scripts row.

## The headquarters has a real day, and the live sky follows the real sun (2026-09-24)

- The art director's verdict on 2026-09-24 is ALMOST (the building and the 19:19 dusk are close to the reference; by day the world around it still reads as a game). Next, in order of visible effect: (1) the Unreal towers by day - sunlit glass and concrete, no warm windows while the sun is up, a lighter haze, the torn BUCHAREST AI DISTRICT sign; (2) a real golden hour from +10 to 0 deg, so 18:50 is never darker than 19:19, checked live under the studio's own pass; (3) sun shadows on the street and lit tree crowns instead of black cards; (4) one world for stream and canvas - the room palette, the frame material and the skyline's day/night window states from one manifest; (5) dressed pedestrians who walk, by time of day, and a real bench; (6) a city sky glow at night and a wet road with reflections; (7) rain, overcast and snow into the sky and the light (today painted clouds show while Open-Meteo says clear); (8) a slow camera drift and event-driven push-ins; (9) a cooler dawn with fewer lit windows than dusk; (10) faces, last.

- check_report should know the twilight model (SunDusk 2.5, movable Sun 0) and stop printing FAIL on a good build; the vehicle sprites keep their headlights on at noon; one static day plate keeps the shadows of 12:00 all day.

## The workspace becomes a game frame, and the serial a writers room (2026-09-24)

- Page wave 3, from the judge, in order: (1) real data inside the world so the idle building is alive with truth - the render bay's screen the last real poster or frame, the Treasury display the real balance, the lobby screen the day track, the fact-check board the real claim counts, monitors and window lights following who is WORKING; (2) 60-100 px of real sky above the roof in the plates, then a top inset for the HUD row (the chips lie on the roof railing today); (3) the dock off the zebra crossing (a corner, or icons until hovered); (4) the Unreal stream seen through the game frame on the Owner's machine (video under the drawers, zoom and pan, a click on a figure opening the right inspector); (5) precompile the workspace's GPU shaders under the title to remove the one-time first-visit freeze; (6) keyboard order register -> frame and dock -> side drawer; (7) fill the empty glass under module status at 2560; (8) the Owner decides «Directorul» or «Directoarea» and it is applied in one pass; (9) recapture the fixtures (the module status still shows Office Serial NEIMPLEMENTAT, the backend says PARTIAL); (10) the Journal opens on the episodes, not on «Zile închise».

## The serial made well: a voice per character, one look, its own identity (2026-09-24)

- S7 (one voice per speaker, captions per take) is done, faked. Next for voices: bind and lock the eight voices once he has heard them (identity locks then keep them across episodes), and backfill speaker_bibles on storyboards built before S7.

- S8 (the series look and serial shot prompts) is done, faked. Next for pictures: S9 (free character references from Unreal, rendered in the series rendering), a per-series seed where a vendor honours one, and his paid render to judge whether the look holds from shot to shot.

- S10 (the serial's identity at publish, the honest review record, the brief's tone and cast) is done, faked. Still open: the page labels for metadata_source, refusals and the approval source; a real Publisher model to see it write hooks in the format; and links to previous episodes once Channel B publishes publicly.

- S12 (two days on a copy of his data) is done, faked. One click filmed yesterday's episode and wrote tomorrow's script on day 1, and filmed that script without rewriting it on day 2, on his real history. Next: his decision on the Director's leave and on the log that freezes at the run's hour; S13 (a real model answering the v4 brief, the rubric and the plan); his paid render to hear the voices and see the look. Rerun the rehearsal with: STUDIO_REHEARSAL_DB=<copy> REHEARSAL_REPORT_PATH=<file> uv run pytest -q -s tests/test_rehearsal_on_a_copy.py -k two_days.

- serial, open - backend/app/agents/reviews.py / publishing guard: Only the Publisher's title and tags are checked against other films. A READY answer with the right title but another film's description, or unrelated tags, still goes out: the logline is prepended, but the rest is hers.

- serial, open - backend/app/media/assembler.py (degenerate-still retry): The retry appends 'A real, detailed scene', which pulls a serial still toward realism against the series look. The line is shared with factual films and the file is S7's, so I left it; 'A detailed, coherent scene' would be neutral.

- serial, open - frontend (Settings) / POST /api/v1/publishing/channels/{id}/publish-policy: No page control grants or withdraws the Director's leave (director_may_approve_episodes). It is only a versioned API command, so the Owner cannot flip it from the page.

- serial, open - backend/app/story/projection.py: The Director's own notes reach the writer cut at about 150 characters with '…' (on 09-19 that was the weekly-review verdict, the funniest fact of the day). 'an employee reported to the team (task: WEEKLY_REVIEW)' is flat machine text. Model names show as '[redacted]' inside subjects.

- serial, open - backend/app/media/factory.py (voice adapter cache): The adapter cache key is (integration, model, voice) and ignores voice_settings. A character binding and the narrator on the same voice id with different settings would share the first adapter's settings. This does not happen on his data, where no bible has a voice.

- serial, open - backend/app/story (computed checks): The 8-word, 3-second hook is asked for and judged by the Director but not computed. The rehearsal stand-in's hook was 10 words and passed. This is left to the rubric on purpose.

- serial, open - backend/app/runbook/services.py + story close_daily_log: (Carried from S12) A day's log freezes at the run's 05:00, so a date's episode tells only what happened before the run. This is the Owner's decision (39_DAILY_AUTONOMOUS_RUNBOOK §7).

- serial, open - real providers: No real-model, real-voice or real-image proof exists. Three things stay unproven until his paid click: whether a model follows v5 and the rubric, how the eight voices sound together with 0.3 s breaths, and whether faces hold across shots.

## The building's screens tell the truth, and the frame is finished (2026-09-24)

- Page wave 4, from the W9 judge (verdict ALMOST: the idle building is truthfully still because every employee is IDLE in his data; pushed live events bring it alive within a second): (1) Make the faces readable at fit zoom. Give the screens canvas hit regions, reusing the renderer's hits list, and show a glass readout on hover or keyboard focus with the face's own words, e.g. 'Trezorerie: -1.234,56 VR$ · azi 12,75 / 15 USD'. Nothing new is fetched; it is the same facts store. (2) An honest reason for the idle building to catch the eye. On the sign: 'următoarea rulare 05:00' when the scheduler job is active, else 'programarea zilnică este oprită', which the side readout already computes. On each desk: a faint 'ultima sarcină: <taskLabel> · acum 3 zile' tag from the register. Both are real data. (3) Backend (serial workflow): runbook produced_by should count publish from 'publication_id' or 'publication_status' on legacy runs. The captured newest run says 'Niciun film publicat azi' while its publication 86fe911d is PUBLISHED on YouTube, which contradicts the radar. (4) Render bay: decode the film frame at a brighter time than POSTER_AT 0.2. The real film's frame there is almost black (two lights), so it reads as 'no signal'. Also consider the poster at 2x the pixels. (5) Fold the slate to one line below 1500 px when both drawers are open; the kerb is covered by 12-18 px at 1280 and 1440. (6) Contrast sweep: blank the Treasury gauge's label ink so the 1:1 false positive goes away. (7) Unreal: the W7 list of bindings is still to do, preferably one endpoint returning face state so the stream and the canvas share one source.

## The live headquarters follows a real clear day (2026-09-24)

- 1) Commit the clear-weather real-day rules (front-ground budget, FacadeLight's own factor, fill colours, golden/dawn/night) with the weather branch held back: overcast_weight pinned to 0, RAIN_ROAD_ROUGHNESS off, weather tests xfail with a reason. (2) Weather branch without a rebuild: limit the deck's sky-light lift so the sign panel stays within +5 of clear noon while the shrubs stay at 50 or above. (3) Next Unreal rebuild window (Owner permission, at least 16 GB free commit, no game running): overcast atlas cells (light-grey day deck sRGB 170-190 with chroma under 15, a dim deck at dusk and dawn with no glow, a city-lit deck at night) or haze planes extended to the top of the frame, then remeasure STREET_CLEAR_ANCHORS, FACADE_CLEAR_ANCHORS and DECK_SKY_LIGHT_LIFT, and consider a neutral captured grey dome for the sky light. (4) Still open: daytime tower and tree materials, facade sun shadows and a raking golden-hour key, the dawn/dusk distinction at street level, and warm night glow at the horizon. (5) After the commit, ask the Owner to restart start.py and scripts/run.py; nobody else restarts them.

## The building's truth is legible (2026-09-24)

- Page wave 4: items (1) faces readable, (2) an honest reason for the idle building, (3) backend publish count, (4) brighter render bay, (5) slate off the kerb and (6) contrast-sweep false positive are done in W10. Item (7), the Unreal bindings through one face-state endpoint, is still open. New follow-ups: a 'last task' per agent from the backend, so the desk tag is not limited to the replayed register; a larger pointer target for desk monitors at fit zoom; the toast's poster using the same brightest-frame choice.

- Page wave 5, from the W11 stranger (verdict ALMOST: the faces are legible and true and a live run arrives visibly, but at rest nothing inside moves and a live arrival is small at fit zoom). (1) Make a real arrival catch the eye: on agent.state_changed to WORKING, show that employee's world tag («<nume> · lucrează · <sarcină>») for about 4 s. On runbook.stage_started, briefly light the room of that stage. Same socket and facts, no new request, off under reduced motion. (2) Unreal bindings through one face-state endpoint, so the stream shows the same faces, rings and glints. (3) Tell 'not read' from 'empty' in worldFacts.run/film, so a failed /runbook/runs gives «—», not «nicio rulare în registru». (4) A desk pointer target of at least 32 px at fit zoom (the desk area opens the desk card). (5) Backend: a 'last task per agent' field, so «ultima sarcină» is not limited to the replayed register. (6) The façade card placed below the sign, off the AMN-AI lettering. (7) A premium pass on the Journal dialog (the frame's glass, an episode cover, the empty-thread panel folded). (8) The film toast's poster uses the brightest-frame choice. (9) The Owner's call on the canvas street's random traffic and pedestrians. Done in W11: the sign between stages, the stale selection after Escape, and the canvas's accessible name.

## The day replayed from its record, and a live arrival seen across the room (2026-09-24)

- next wave after W14: (1) invite the visitor to the replay from the idle façade, once, with words from the record; auto-start after sign-in only with the Owner's consent, never looping. (2) Decide the replay's sky: the replayed hour's sun (astronomically known) with no weather drawn, or the present city as now; grade or hide the street's live clock sign while replaying. (3) A note on the register drawer while the building replays (glossary first). (4) Backend /events?since= and an 'as of' treasury/budget read for the replay. (5) Reduced-motion drawer snap: 2-5 frames over 33 ms at 1280, live and in replay alike. (6) Test the replay under the live Unreal stream. (7) Focus back to the dock's «Reluare» key after an automatic return to live.

## The replay offered once, lit by its own hour: the first YES (2026-09-24)

- W16 next wave: (1) remove the one 63-91 ms frame of the first replay entered from a live day, by prewarming while the invitation is up or by tracing the GPU flush at the switch; (2) move focus programmatically only for a keyboard-started replay, so a mouse visitor is not left with the dock key's «RELUARE» label over the live building; (3) the Owner decides whether a film that is private on YouTube is «publicat» to visitors; (4) read the books in chunks when a run has more than 239 figure-moving events, instead of holding the 239th reading; (5) recapture the harness fixtures with the current backend's run summaries; (6) offer «Înapoi la live» when a replay reaches its end; (7) label the live clock beside ATUNCI below 1600 px; (8) test the replay over the Unreal stream; (9) the Owner's next start applies 0046 and 0047 through bootstrap.

## The real stream in the game frame (2026-09-24)

- next wave after W18:
1. One building from title to live: a kept real Unreal frame for the title and the 'starting' plate, so there is no dark gap and no change of building (the Owner's art choice).
2. The studio's numbers visible over the stream: world-anchored labels for the façade, fact-check, EP board, PUBLICAT, RANDARE, Treasury and tokens, or Unreal screens fed by the backend bridge.
3. A replay that does not jump from Unreal to a different building (a crossfade through the kept frame, or the Owner's choice of the replay's look).
4. The Owner's decision on the encoder commands and quality-control request sent to the shared encoder.
5. Unreal-side alignment of the run-sign board, right tower and lamp with the plates' face positions.
6. «live» on the slate only while both the stream and the studio's events are live.

## A kept real frame at entry, and the studio's numbers on the Unreal building (2026-09-24)

- W20 next wave): [ ] title and push on the kept Unreal frame when one exists (one building from the title to live; Owner's art call); [ ] the replay in the Unreal building's look (the largest step from ALMOST to YES); [ ] plaques and stream transform laid in the same frame as a window resize (1-2 frames up to 363 px off today); [ ] take the Owner's token out of the signalling WebSocket's query string (backend stream.py, security); [ ] a dead-stream wording after N failed connects instead of «pornește sediul live…» (glossary first); [ ] «50.000 VR$ cheltuibili» on the Treasury plaque? (Owner's wording; the record holds VR_DEBT 50.000); [ ] tokens, the EP board and the film frame over the video; [ ] plaque anchors checked on a day frame.

## The key out of the socket URLs, and one building for a returning visitor (2026-09-25)

- W23 leaves open:
(1) a real Unreal frame for the first visit's title, kept by the backend or committed dated, so a stranger never sees two buildings;
(2) the Owner's backend restart, then the removal of the legacy ?token= branch in office/stream.py and workflows/router.py;
(3) a cap on concurrent unauthenticated sockets during the 5 s first-message wait;
(4) the replay speed wording («1×» beside «de 4 ori mai repede decât rularea»), a glossary amendment first;
(5) replayed captions overlapping each other at 16×;
(6) OFFICE SERIAL «EP — · Ciornă» / «—»;
(7) the phone-width title on a kept frame and the screen-reader reading of the replay's start sentence, not yet checked.

## A stranger's first visit in the real building (2026-09-25)

- The Owner restarts the studio on :8000 (the W24/W25 backend: kept-frame route, socket limit, the WebP check), then plays the stream once while signed in, so a stranger's first visit opens on the Unreal building in the real studio, not only in the harness. [ ] Re-measure a real cold visit against :8000 afterwards. [ ] Drop the room chip when the replay reaches its end (up to 3.2 s of «acum: …» beside «rularea s-a încheiat»). [ ] Plaques after a window resize (run_sign 252-363 px off for about 6 checks, carried over from W23). [ ] A per-peer share of SOCKET_AUTH_MAX_PENDING before the studio is ever bound beyond localhost. [ ] Pictures still missing: phone width on a studio frame, golden-hour and twilight titles, the night icons for partly cloudy and drizzle.

## The release candidate: the dialogs in the frame's words and glass (2026-09-25)

- W27 (release judge, 2026-09-25): done: the frame is no longer a scroll container (overflow:clip), the publication gates lost their page-written ticks, the inspector offers only a real lifecycle act, and the demo and provider wording is true. Next: the doors open from their room with a game-level transition and one hero element each, with a larger type scale and a single scroll; a backend pass for Romanian preflight, stage and decision sentences, a refusal of no-op pause/resume, and no raw exceptions as stage reasons; the doors' first-open frame; the reduced-motion resize frame; phone width; the doors photographed over the live stream. Owner: restart the backend, confirm the public kept frame, the language of identities and channel names, and Ollama token prices.

## Doors from their rooms, and the studio's sentences in Romanian (2026-09-25)

- done: the backend's sentences in Romanian (wording.py, preflight `value`, stage error_class/error_detail, 409 on no-op pause/resume). Next: the publishing gate in Romanian, with its ~90 test assertions. The worker/watchdog reasons through app.wording.error_words. A Romanian decimal in format_micros for sentences. An Owner decision on whether the Director's Owner-facing fields (interpretation, note) are asked for in Romanian.

- Done (W29): the release judge on the W28 doors and the Romanian backend, with fixtures recaptured from a fresh copy of the database; the register's wrapped filter chips at 32 px (8 px row gap, tests/chip_targets.test.js). Next, in order: (1) the Owner's decisions below; (2) the publishing gate's reasons in Romanian through app.wording, and the research line's NONE and OTHER as words; (3) the doors at 60 fps: the mail and the inspector rendered after the pane lands, and Research's first screen lighter; (4) Angajați as people in the building, from real state only; (5) the storyboard prompt slots deduped once the Owner agrees; (6) one Director title across the page and backend; (7) a filled approvals state judged through W7_EVENTS; (8) the contrast harness to leave out edge-cut runs and the ring's SVG figure.

## The employees as people, and the publishing gate in Romanian (2026-09-25)

- W31 (release judge, 2026-09-25): [done] fresh-copy fixtures judged; stale next-run promise, daily_main title, doubled preflight line, subjectless media key line (backend, TDD), the drawer's «more below» fade, the register's gate_failed/failed rows, the OTHER negation and the publish status words fixed. [owner] restart start.py (new words, stream light); decide on the stored history, the models' English, the identity contracts and channel names, the «settings» connection, the Director's title, the gold edge, the ollama prices and the analytics scope. [next] a preflight in the page's words (no routes, env names or scopes in sentences; decimal comma; sizes in MB); research retrieval details in Romanian with a reason code; the preflight as a folded checklist; the inspector's portrait and hidden id; no integration key line in Setări; vendor names in their own case; the phone rails; Media's frame over the stream; wider doors at 2560; portraits from the Unreal render.

## The preflight as a checklist, and real faces over the stream (2026-09-25)

- CHANGELOG — Preflight: structured code / impact / place / technical on every line; sentences in the page's places («Trezorerie → Buget și cheltuieli», «Producție media → Character Bible», «Distribuție → Sloturi de canal», «Setări → Conturi și e-mail»); scopes said as what they allow; Romanian dates and decimal comma in sentences; the vision line's agent id moved to value. Research: failed site tests are Romanian with a reason code, and pre-0040 rows are read the same way on the Research door and in the preflight. Open: page controls for token prices, the Director's right to approve episodes and channel slot creation; the remaining «Settings» words in analytics, factual and media messages; the frontend reading the new fields (readiness.js).

- W33 release judge: amazed YES, premium ALMOST, the preflight checklist YES. Done: the page and backend agree on the place fields; Research failures are said once, and never blame the Owner's entry for a redirect; empty search fields sit behind a key; Character Bible chips are no longer cut; the seeded connection has a real title. Next:
  (1) page controls for token prices (Trezorerie), the Director's right to approve episodes and slot creation (Distribuție), switching the backend's not_on_page places when they land;
  (2) fold «Starea modulelor»;
  (3) remove the kept-frame seam on the returning title;
  (4) stagger the Research door's first open;
  (5) the register's routine entries in the studio's words;
  (6) raw channel and voice ids to tooltips; the backend prompt builder's repeated subject;
  (7) the remaining «Settings» words in analytics, factual and media messages; the microsoft.com block page counted as readable.
  Owner: restart, prices, the Director's approval right, YouTube statistics grant, budget before PRODUCTION, reference sets, the Director's title, stored English history.

## Controls for the Owner's decisions: the interface premium apart from his items (2026-09-25)

- W35 (release judge) done. The two Owner controls were proven on the real backend on a fresh studio; price rows keep one order; the drawer says «Ultima rulare» for a run of another day; «Studioul azi» arrives with its drawer; run headlines say «etape de lucru». Next:
  - (1) Distribuție's first open under reduced motion, in steps.
  - (2) Game-grade treatment for Setări → Canale and Prețurile modelelor.
  - (3) No double exposure during the title's push on a cold entry.
  - (4) After the Owner's restart, the FIX_PLACES fallback labels in the «→» form.
  - (5) Prices for a model the preflight does not name, and a provider-wide «*».
  - (6) The stream harness replays enough events to reach a letter.
  - (7) A night frame of the returning title.
  Owner: restart; the Director's right; the six models' token prices; the daily budget against production; YouTube statistics scope; the reference set.

## The Owner's controls as plates of the building: premium (2026-09-26)

- W38 candidates from the W37 judge: (1) Distribuție's channel slots as plates of the Setări → Canale family, the two-bar «filme · măsurat» chart a real meter; (2) Research's open and Treasury's close stepped through data-door-steps (one 20.8–20.9 ms frame each under reduced motion); (3) the price plates folded when priced, with the group header carrying the count of unpriced models; (4) «ia prețul furnizorului» per side; (5) the cold entry's hold tied to the plates' animation rather than a timer; (6) with the stream on, film the real hand-over and the returning entry's landing over the kept frame once, as entry36 did with the stand-in.

## The Unreal skyline has a real day (2026-09-26)

- towers by day, follow-up. (1) Reshape WindowsOn in backend/app/office/scene_params.py: 0 above about 15 deg sun, about 0.6-0.8 at +2..+5 deg in the evening, about 0.3-0.5 in the morning, plus a separate higher floor for near_blocks. Then re-preview 18:50, 07:25 and 19:19 (gates: 18:50 at least as warm as BEFORE, 19:19 at or below 6.8). (2) Art: glass or metal tower crowns instead of flat grey caps, and a daytime face for the CREATE AUTOMATE SCALE TOGETHER board. Optionally add a warm low-sun facade tint before sunset. (3) The morning sky and palette still mirror the evening (real-sky item). (4) The Owner's art verdict on the kept pass is pending.

- after run 3's preview, judge 17:58 by eye (the new curve lights a tenth of the windows there, where run 2 lit none); retire the 09-24 curve copy in art-source/unreal/towers_day/towers_day.py (windows_share, WINDOWS_OFF_ABOVE 5, WINDOWS_FEW 0.2) and the stale backend_day_state*.patch records, so the curve lives only in scene_params; decide whether the near blocks should also outshine the skyline in the evening (today the floor 0.5 is below the evening curve everywhere).

- run the towers window run 3 with the prepared kit (scratchpad real_sky\towers_window\run3\setup3.ps1: MyStop, WaitFree 16, Reapply by hash, Hold, MyStart, WaitJoin, StreamUp, DriveI/Grab at 18:50, 07:25, 19:19, montage3.py, then Release or Unhold+RestoreBackup+restart) once stopping the stream's own processes is permitted for the window; judge 18:50's near block (must not be black: BEFORE p90 91.8 vs run 2's 23.8) and 07:25's left skyline by eye; put towers_day\sign_baseline.json back on KEEP.

- 1) the Owner restarts his studio so the 09-26 curve drives the live towers (until then the page shows the 09-24 curve from about 18:00); (2) art director's look at run3\montage_1850/0725/1919 and near_zoom_1850_2.png - if 18:50's near block should match BEFORE, give near_blocks its own curve reaching about 1.0 by +3 deg (probe: 0.85 -> 9 windows, 1.0 -> 18); (3) preview 17:58 by eye (WindowsOn 0.122 there, run 2 had 0); (4) decide whether the 18:50 score gate (+1.0 over BEFORE against a dusk reference) is the right measure for an instant with the sun up, or replace it with the lit_px / near-block gates that did discriminate; (5) retire the 09-24 curve copy in towers_day.py.

- towers, still open after run 3): (1) near_blocks its own windows curve reaching about 0.95-1.0 by sun +3 deg (probe 0.85 -> 9 windows, 1.0 -> 18 = BEFORE), backend only, previewed live with a held report; (2) the Owner restarts his studio so the 09-26 curve drives the live towers; (3) preview 17:58 by eye with WindowsOn 0.122 and judge the warm low-sun tint - at sun +12 the horizon should be gold and the stone warm, not noon cobalt and white facades; (4) the flat tower crowns - dark caps with no roof, parapet or plant, most visible at noon and at 07:25 now that the facades are lit; (5) the dark board by day - the CREATE/AUTOMATE board and the BUCHAREST AI DISTRICT sign are black slabs at noon; a printed board must read in daylight, or the board is an LED that lights from dusk; (6) the morning palette - the 07:25 cloud band is the evening's rose-mauve; dawn wants a colder grey-blue low band, warm only around the sun, and the far towers one pale grey at noon want depth; (7) replace the 18:50 dusk-reference score gate with the lit_px / near-block / 19:19 gates; (8) retire the 09-24 curve copy in towers_day.py.

## The film staircase — after the Nepal film (2026-09-26 → 2026-10-01)

- Done: the 25 items of the staircase (see CURRENT_STATUS); YuNet installed 2026-10-01.
- Next (workflow amn-film-close-gaps): clip QC (motion floor, faces on three frames, one seed+1
  retry inside the cap) between the motion step and assembly; `require_chosen_fallbacks` before
  assembly; the measured spend on the film; the serial's series_look accepted by the stills and
  motion steps; documented model capabilities and the Owner's allowed set (config/film_models.json)
  so the per-scene cheapest choice works on the real catalogue; ElevenLabs with-timestamps for
  captions; silent card spans and full breaths in QC; three frames per scene in the film-level
  picture check; the assemble step route; the legacy whole-film path never reaching a real paid
  adapter in any environment; step costs booked once; stale paid-step questions withdrawn; the
  drawer's redo and assemble buttons and the Owner's paid-media switch.
- Owner: scripts/bootstrap.py before his next restart, then npm run build --prefix frontend; the
  zero-credit Nepal rehearsal; his decisions (allowed models, hero threshold, budget per film, the
  paid-media rule, a Runway top-up).

## The film staircase closed — ready for the Owner's next paid film (2026-10-01)

- Done: clip QC wired, assemble step, legacy money hole closed, model catalogue, voice timestamps,
  QC spans, compact intermediates released after QC, the drawer completed.
- Owner decisions open: narration as a paid step (`media.narration_purchase`, needs 51); unchecked
  clips (wait for his look, or reject); the allowed set / hero threshold / premium reference in
  config/film_models.json; silent card maximums; fail-closed when YuNet cannot run; the older
  one-frame film-wide look beside the new three-frame look; the ~1,080 old test films (321 GB) in
  backend/storage/media; his real ElevenLabs plan price.
- Follow-ups: retire the legacy assemble_video_job's inline motion buying; a re-QC of a released
  film keeps its first duplicate reading; a second render of a storyboard must not overwrite the
  first film's final_short_9_16.mp4 (provenance); a repo home for the drawer fixture generator;
  base_asset_id on the redo view; Romanian frame names in clip-QC messages.

## The night of 2026-10-11 → 12: the serial rung, «Mișcare v2», the editorial judgement

- Done (see CHANGELOG 2026-10-12): the Director's ladder recomposes a serial scene with today's
  composer (scenes 3–4 of f06808c9); ample cinematic motion with eighteen camera-move families;
  the Director's editorial judgement for both channels, ten rounds, the best version ships; the
  register words the judgement; a stop during a restart is worded as the studio's closing, not
  as the Owner's switch; office presentation files formatted and typed.
- Owner: one restart when the studio is idle (the process of 00:44:43 predates all of it); the
  GPU session shared per model across films (his card: tomorrow, after today's production); the
  LTX LoRA when the training set has ~100 serial clips (his card then).
- Next: `POST /episodes/{id}/review` through the judgement too; a rewrite after a deformed clip
  sets `motion_amplitude = "measured"` on the package; the judgement's rounds written as they
  happen (a crash mid-loop loses them today); `END_BEAT` yields to the 95-word budget on long
  actions.
- Found and closed the same night: the two `tests/test_autonomous_day.py` failures since
  3c30bc6 were the serial's two episodes (today's and tomorrow's) reaching the paid steps
  beside the factual film, not a double purchase; the tests tell the films apart now.
- Morning: a paid motion redo priced with the raw tariff (no RunPod row) held the cyclotron's
  scenes 4–5 NEEDS_OWNER every hour and the walk said «cumpărată» over nothing — fixed
  (`_motion_state` prices as the sheet; a redo that bought nothing is a refusal).
- Done the same morning: a motion rewrite that returned the same prompt («Rescrierea a dat
  același prompt», scene 5 of the cyclotron, every hour) turns the redo to the picture — in the
  QC repair (`_correct_before_redo` tries the still layer) and in the ladder (`open_layers`
  counts the attempt).
- Done the same morning (the Owner, 07:40: «dai singur restart, nu mă aștepta»): a day cut off
  by a shutdown or a crash is resumed by the studio itself after the start
  (`passes/resume_interrupted_day`, `resume_runners`: completed stages replayed, the rest run);
  the restart is the developer session's own, at a safe point, after commit and green suites.
- Next: a RunPod job queued with no worker for longer than the cold start (06:15 → 07:38,
  today's film: RunPod expired it at its ttl, 83 min) should be given up earlier or the Owner
  told at once; a `scripts/restart.py` for the graceful self-restart (today: a scratchpad script).
- 2026-10-15 evening — next: a GPU turned off by the guard during a step (`GUARD_STALE`,
  16:52Z, because the poll was blocked by the Director's company call) ends the walk as
  «STOPPED» with a letter «așteaptă decizia ta pe foaia de filmare» to the Owner
  (`runbook/stages.py` ~2845) and the guard's own letter «GPU-ul RunPod a fost oprit de paznic»
  is `for_owner` — both are the studio's own matter under the letters rule: the next pass
  re-walks (it does, `serial_unfilmed_after_start`) and the Director is told, not him. Also:
  `day_goal` counts a run the developer's restart cut (17:08Z) as one of its six.
- 2026-10-15 evening — next: the verifier is handed a source window that does not carry the
  claim's words («The source excerpt does not mention 1998 observations…» on the Type Ia page
  whose article says it), so the thesis claims of «The Supernova Surprise» stayed UNCERTAIN
  through three research passes; give the verifier the passage found by the claim's own words
  (`evidence_text` quote search over the whole snapshot) before judging.
- 2026-10-15 19:30Z — next (the Owner checked his alerts): of 15 open letters to him, 14 are the
  studio's own matter under the letters rule and were misrouted: `day_interrupted` (×3, the day
  now resumes by itself), `owner_shooting_sheet` for a refusal outside OWNER_DECIDES (×2),
  `runpod_gpu_guard_off`, `film_continue_interrupted`, `film_purchase_abandoned`, and the
  informative `owner_director_qc` / `owner_director_look` / `factual_short` judgement notes.
  Route each producer to the Director (body.to = Director, her inbox) and keep for him only
  accounts, authorisations, security and money cards; the «Decizii» count then shows his real
  cards (today: one, Marcus's failing model).
- 2026-10-15 19:55Z — next: a studio started while another still holds the worker lock serves
  the page and never runs a worker (`main.py` «worker_refused_second_instance», by design for
  the scheduled task beside a manual start). Today the Owner launched `start.cmd` at 19:46Z
  while the restart's graceful stop still waited on the old worker; the old one died at 19:49Z
  and the new one stayed worker-less (`/health/ready` worker ELSEWHERE) until a second restart
  at 19:54Z. The second instance should retry the lock every 30 s and start its worker once the
  holder is gone; the page should say «lucrătorul rulează în alt proces» meanwhile.
- 2026-10-15 21:55Z — next: `scene_rewrite.review_findings` falls back to the scene's newest
  failure whatever take it was (`failures[:1]`), so a quality-control brief on a scene whose
  refused still candidate stands beside an approved one is still reviewed against the refused
  candidate's findings (the audit's brief is now answered by its diagnosis, 28b4a65). Read the
  findings of the take under treatment only. Also: `test_director_rewrites_failed_scene::
  test_the_days_staircase_has_her_rewrite_the_refused_scene_and_walks_on` fails since the
  no-cap audit rounds («Scena 1: auditul nu a spus nimic de ea» — the test's Director fake
  answers the brief, not the audit's rounds): teach the fake the audit's answer. The same fake fails
  `test_director_delivery_routing` (ASKED expected, WAITING «auditul nu a spus nimic de ea»).
- 2026-10-15 23:08Z — next: a graceful stop sent while a DAILY_RUN is claimed takes the page
  down («shutdown_waiting_for_worker») and waits for the whole day run — the serial's writing
  rounds, 12-25 min each, up to ten — so `scripts/restart.py` gave up after 600 s with the
  page dark and the worker still writing; the tree had to be killed (23:17Z) and the day
  resumed by itself after the fresh start. Either the worker abandons an LLM-only task on
  shutdown (the resume pass re-runs the stage; nothing paid is in flight) or `restart.py`
  refuses to stop while a DAILY_RUN is claimed and says so; the boundary scripts must treat a
  claimed day run as blocking, not only a writer's run in flight.
- 2026-10-16 00:46Z — next: the still gate approves pictures the clip QC then refuses for the
  bible: 7c26a7ce scene 1 (a window with daylight in a windowless lab, approved 21:27Z) and
  scene 2 (the scientist's face in profile under a faceless bible, approved 21:27Z) each cost
  a test shot (0,33-0,38 USD) before the fault was placed in the picture. The still gate
  should read the bible's hard limits (faces, windows, lighting state) as the clip QC does —
  the same look, before the shot is bought — or the clip QC's look should run on the still
  first.

- 2026-10-16 06:50Z — montage (the Owner's decision, `media/montage.py`), open after the first
  cut: (a) the breath of 0.12 s (`SPOKEN_TAIL_SECONDS`) is planned after every shot's words; one
  per beat would be truer to a sentence carried across a cut; (b) `film_max_paid_redos` (20 per
  film) and `MAX_STORY_SCENES` are per row, with up to three times the rows — measure the first
  montage films before raising either; (c) the wide still of a beat as a reference image for
  its closer shots (today the prompt and the room reference carry the continuity); (d) the
  sheet could show a beat's shots together (display only); (e) the serial review's `_filmable`
  still measures the whole beat against one clip (right as a length rule for the writers; the
  cut makes it looser than it needs to be).
- 2026-10-16 06:50Z — next: a film ACCEPTED (under the cap or by her looks) whose walk ended
  without publishing has no pass of its own: `passes/director_qc_review` walks it again only
  after a refused viewing. A pass should queue one walk for any film with a PASSED report, no
  publication record and no standing continuation (the dead-process resume covers today's
  case, 7c26a7ce 06:05Z, but not a walk that ended on its own without publishing).
- 2026-10-16 06:50Z — failing on HEAD before the montage, unrelated: `test_motion_v2::
  test_the_ending_survives_a_long_action_whose_later_moments_give_way`, `…_a_single_long_clause_
  keeps_the_ending_with_the_move_said_short`, `…_three_peoples_moments_give_way_word_by_word_
  before_the_ending_does`, `…_an_ending_that_fits_beside_nothing_is_left_out_and_said_so` (they
  assume the old word band: «assert 92 > 900» since the bands went to 900, 2026-10-15 20:07Z —
  rewrite them against a band the test sets itself), and `test_rewrite_learns::
  test_the_films_findings_reach_the_brief_with_the_cause_she_found` (rewritten False, layer
  motion; read its reason).
- 2026-10-16 06:50Z — the restart chain's boundary (`wait_round_end.py`) passed at 06:05:40Z and a
  walk claimed at 06:05:52Z, twelve seconds later, was cut by the stop: the boundary and the
  stop must be one step (`restart.py` taking a lock the worker respects, or the stop refusing
  while a FILM_CONTINUE is claimed), not a check followed by a stop.
- 2026-10-16 08:00Z — the Owner's format, open after the serial's v8 and the 160 s short:
  (a) the architecture's data model (11_DATA_MODEL) still documents 60/70 s for `shorts_max_seconds`
  (migration 0058 raised them to 180; decision logged) — update the text and its index hash;
  (b) the narrator voice of the serial is the Organization default, the same voice a character
  without a voice falls back to — a dedicated narrator voice in the OFFICE_SERIAL channel's
  `series_rules_json["office_serial"]["voice"]` is the Owner's choice (a card); (c) measure the
  first 160 s short and the first v8 episode: cost per film (estimate 7-8 USD with montage),
  QC length, how many shots; (d) the factual writer's schema still caps a scene at 800
  characters and `narration_budget` sizes scenes at 15 words — fine at 160 s (about 28 scenes,
  `MAX_STORY_SCENES` 30), revisit after the first film; (e) `test_readiness::
  test_a_daily_budget_below_one_film_says_the_first_film_is_refused` fails since the film
  ceiling follows the daily budget (not the format work).


## 2026-10-17 — Owner UI requests completed

- [x] Sequential dialog audit: media, research, publishing, workforce, journal, daily run, autonomy, settings, decisions, inspectors, mail/live/player; fixes retained in installed bundle.
- [x] Real daily budget, canonical cost accounting, current Bucharest day completions with pagination/midnight/DST handling.
- [x] Compact named projects and combined YouTube channels; explicit unknown/stale data.
- [x] One persistent UI sound switch, local CC0 collection/provenance and separate browser audio verification.
- [x] 980 frontend tests, TypeScript, 20 budget/reconciliation tests, five browser suites, desktop/mobile actual-backend inspection and static install verification. No start/restart command.

- [x] 2026-10-17: correct Runbook → Compania acum framing; grouped/pair-aligned cards, no row holes, desktop/mobile/200% text inspected, verified static install without restart.

- [x] 2026-10-17: inspect every main tab/section for framing defects; correct forms, checkboxes, structural grids, budget groups and lazy navigation; five widths/200% text and 43 final installed views checked without restart. See UI_ALL_TABS_FRAMING_2026-10-17.md.

- [x] 2026-10-17: synchronize five windows with actual exterior day/night/weather; replace repeated sunset views, trace glazing and preserve original frame pixels after Owner feedback. Native-resolution frame regression and current-app enlarged detail verified, no restart. See UI_WINDOW_VIEWS_2026-10-17.md.

- [x] 2026-10-17: compact Loading... for shooting sheet, normal loaded layout restored; delayed real GET transition and desktop/mobile visual verification; installed without restart.

- [x] 2026-10-17: remove scene ? helper; controls on one row including long GPU status, stop, fullscreen and sound at 1366/1920/2542; narrow-screen scrolling fallback. Verified static install without restart.


## 2026-10-17 — Duplicate serial film recovery

- [x] Finish Claude duplicate-day repair, guard old held drafts/approvals/storyboard reuse/purchases and concurrent requests; correct the existing unpaid duplicate locally, preserve the original and canon, verify repeat recovery. Evidence and remaining separate Claude branches: CURRENT_STATUS, SERIAL_DUPLICATE_RECOVERY. No server start/restart.

- [x] 2026-10-17 Supernova prompt gate repair: still framing/marking context, per-object exclusions, leading label parsing and required audit scenes; 150 relevant tests.
- [ ] Confirm Supernova 1efc3319 autonomous YouTube publication; resumed specific heartbeat, no manual production.

- [x] 2026-10-17: share still-framing contract across audit, rewrite and review; valid replacement no longer contradicted by obsolete lessons.102c5d4;15 dedicated tests, broad258 pass+1 reproduced baseline failure. Supernova remote publication remains pending.

- [x] 2026-10-17: remove pasted compiler-owned configured style/frame and retain visible state when stripping tempo;215 tests,22eff0c.

- [x] 2026-10-17: lossless action dedup retains new state and word order;bd30734,220 relevant tests. Target publication still pending.


## 2026-10-18 — legacy final-prompt rewrite contract
- [x] On-demand LIVE legacy migration with complete Kael finals, current face policy/Owner plan authority, exact review/transport and current purchase approval; original media/history preserved. Local isolated regression verification complete.
- [ ] After controlled integration/restart, accept scene 19 live: Kael finals → Sarah approval → actual provider frames → visual QC. No live row was changed in this task. See LEGACY_EDITOR_FINAL_AUDIT_2026-10-18.md.


## 2026-10-19 — unblock paid prompt repair
- [x] Route paid-scene lint repairs through reviewed final rewrite; bound configured LLM generation lifetime without truncating native output. Isolated regression verification complete.
- [x] Actual scene1 motion rewritten and Sarah TREATS at06:34 Europe-Bucharest; sheet RESOLVED with no remaining blockers and automatic FILM_CONTINUE claimed.
- [ ] Complete subsequent real media/QC/publication through existing production gates.


## 2026-10-19 — Kael final rewrite response contract
- [x] Diagnose scene15/23 stored answers and contradictory legacy example.
- [x] Compact final response schema/instructions, exact-text preservation and131 offline checks.
- [ ] Activate at controlled restart and verify actual scene15/23 saved rewrites with Sarah acceptance.
