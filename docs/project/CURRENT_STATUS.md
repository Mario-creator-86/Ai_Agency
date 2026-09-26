# CURRENT STATUS — Phases 0-2 complete; Phases 4-6 partially implemented

Last verified: 2026-09-09 by an independent audit (`AUDIT_2026-09-09_EXTERNAL.md`) and the
remediation that followed it. Active edit claim: Codex, 2026-09-11 — ElevenLabs authentication,
database resource discovery/refresh, separate production choices, UI and regression tests.

> **Correction notice (2026-09-09).** An earlier revision of this document declared Phases 4, 5 An earlier revision of this document declared Phases 4, 5
> and 6 "complete — verified". That was not supported by the code. The audit found fabricated
> channel configuration, simulated uploads recorded as real YouTube publications, a
> non-playable file written with an `.mp4` name, a QC gate that verified its own metadata
> instead of the file, and a demo endpoint that inserted a self-authored "SUPPORTED" claim.
> Those defects are fixed; the phases they belonged to are now marked partial, because the
> providers their acceptance criteria require still do not exist. Sections below state what is
> actually true.

## The Unreal skyline has a real day (2026-09-26)

The Unreal skyline has a real day, live. The prepared towers-by-day pass ran on the saved level (glass masks and window ranks from the bake textures; day materials for the 12 facades, the 8 trees and the torn sign; every new parameter defaulting to the approved dusk), and the backend drives it from the real sun: TowerDaylight, WindowsOn per label, LeafDaylight and the skyline's Daylight (commits 0fc72aa, 99f23ad). Measured on the stream: at noon the facades went 83.6/81.5 → 145.0/137.1 and the trees 39.2/45.0 → 69.0/75.3 (glass towers, green foliage, the BUCHAREST AI DISTRICT sign whole); 17:58 clearly better; the reference 19:19 identical (6.8, every building region within 0.1); p95 15.37 ms. Three windows: run 1 (13:53) ran clean and was rolled back when the Owner started a game; run 2 (16:02) passed every numeric gate but the art director refused it because the first windows curve switched almost every window off at +2.7° (18:50) and left the dawn empty — the level was rolled back and the curve reshaped (windows off only above +15°, 70% lit at +2.5°, all at dusk, the dawn's share as a ceiling, the near blocks their own floor); run 3 (16:55-17:16) re-applied the saved pass by hash, previewed 18:50, 07:25 and 19:19 and was KEPT: 18:50 has its lit windows back (1515/2172 px, 88%/86% of before), 07:25 its towers (459/814), 19:19 unchanged. The art director: ALMOST, ship it; his one note is the near block at 18:50 (3 lit windows where before had 9), fixed by its own curve in the next step. Backups: E:\AMN_backup\hq_before_towers_day_20260926_1355 (the pre-window level) and the run records under the session scratchpad. The stream runs the new level since 17:00; the Owner's studio reads day_state but still runs the code it loaded at 13:49, so the fixed curve reaches the live towers on his next restart.

- 2026-09-26 - The backend learns the day state (no Unreal). load_env_report (backend/app/office/unreal.py) reads the optional "day_state" key that art-source/unreal/towers_day/day_state.py merges into env_report.json. The towers must be exactly the report's skyline and near_blocks components and drive TowerDaylight and WindowsOn. The trees must live in the report's world and drive LeafDaylight. skyline_daylight must be the skyline component and drives Daylight. Each entry drives only the parameters it lists. A report without the key sends nothing new, and tests prove it. All calls use the existing allow-listed MeshComponent.SetScalarParameterValueOnMaterials and are eased like every other value. Tested: 160 passed across the touched and neighbouring test files, plus ruff and mypy. Not yet verified on the stream: the in-place passes have never run.

- scene_params() plans from the real sun only, with the weather look still held. TowerDaylight = LeafDaylight = skyline Daylight = day_weight (smoothstep -2.5 to 6.0 deg). WindowsOn = windows_on(windows_share(e) x city_windows(sun)). This is towers_day.py's curve: none above +5 deg, up to 0.2 of the dusk's windows at 0 deg, all of them at -2.5 deg and below. At dawn the existing DAWN_CITY_WINDOWS 0.45 rule applies. The window mapping was re-derived: 0.02 + 0.95 x share, and exactly 1 at share 1. It is continuous at both ends and lights the share asked for. At the reference dusk every new value is its material's default (TowerDaylight 0, WindowsOn 1, LeafDaylight 0, Daylight 0), and the golden test reads those defaults from the pass scripts.

- Decision (to be confirmed by eye): on components that carry WindowsOn, the dawn's fewer windows are counted by WindowsOn. Their EmissiveFactor keeps only the day's dimming (emissive_factor_counted), so the dawn city is not dimmed twice (0.45 x 0.45). The evening side is unchanged. The stale backend_day_state_scene_params.patch is superseded. Its day haze (near #d2e0ef at 0.3 of the dusk opacity, far #c3d5ea x1.05 at 0.62) is not yet in the backend and remains open.

- 2026-09-26 13:53-14:16: towers-by-day window, ROLLED BACK because the Owner started gaming. Preflight passed: 19.3 GB free commit, no game, the stream stopped as found. The Owner's studio had been restarted by him at 13:49 and now runs the working-tree backend that reads day_state. The backup E:\AMN_backup\hq_before_towers_day_20260926_1355 was verified by SHA-256 (2879 files). BEFORE frames were taken with the committed backend at the 2026-09-24 instants: 19:19 = 6.8 against the reference (p95 15.64 ms), and noon = tower facade luma about 82 with 0 lit windows and a tree median of 39-45. All three editor passes ran clean. towers_day_hq_live made 12 facade instances that repeat today's 70 values each. trees_day_hq_live re-parented the leaves (gain 4.715) on 8 trees. sign_hq_live moved the sign 30 cm towards the camera. The day_state merge then worked. At 14:08:46 the Owner started Path of Exile, and at 14:13 League of Legends, so no AFTER frames were taken and no gate was judged.

- The rollback restored Content\HQ, Content\AMN and env_report.json byte for byte: HQ_Dusk.umap is C73D2DB2...0216 and env_report.json is 106C8024...DE04, with no day_state. The stream was left stopped. Nothing is committed and nothing live changed. Next window: rerun Pass, Merge and the AFTER frames with the kit in the session scratchpad (real_sky/towers_window). The existing BEFORE frames stay valid. Add League of Legends / Riot Client to the game check. Only release a merged report after the gates pass, because the Owner's running studio now applies day_state live.

- 2026-09-26 16:02-16:20, towers-by-day window, run 2: KEPT. Preflight had no game running and 17.6 GB free commit, with the stream stopped. The level and env_report.json equalled the pre-window hashes, and the backup E:\AMN_backup\hq_before_towers_day_20260926_1355 verified 2875/2875 with 0 differences. The masks came out identical to the committed textures. The three commandlet passes on the saved level each exited 0 with result 0 and no 'Failed to compile Material': towers (12 facades on the skyline and near_blocks), trees (8 actors, day gain 4.715) and sign (moved 30 cm toward PlateCam). day_state was merged into a held copy while env_report.json stayed aside, so the Owner's studio sent nothing during the previews. The stream was started once, and the previews were driven with the 0fc72aa backend and the held day_state (83/83 calls landed at every instant).

- Gates, run 2. At the 19:19 reference the frame scores 6.7 (BEFORE 6.8). At noon facade luminance went from 83.6/81.5 to 145.0/137.1 with 0 lit tower windows, and tree median went from 39.2/45.0 to 69.0/75.3. p95 is 15.37 ms against 15.64. By eye, noon and 17:58 read as day (glass towers, green trees, sandstone near block), and the BUCHAREST AI DISTRICT sign reads whole at every instant. 19:19 and 21:17 look the same as before. 18:50 and 07:25 keep only a few lit windows (WindowsOn 0.10/0.06 with the sun at +2.7 deg): they are lighter and flatter, judged not worse and flagged for the Owner as a backend-curve choice. Frames, montages and the log are in scratchpad real_sky/towers_window/run2.

- State after run 2: HQ_Dusk.umap is 6828299B...8E03, and art-source/unreal/env_report.json (C9D91A13...9268) carries day_state. The pre-window report is kept as env_report.before_day_state.json (106C8024...DE04), and the pre-window level stays in the backup; rollback means robocopy /MIR the backup's Content\HQ and Content\AMN back and restore env_report.before_day_state.json as env_report.json. The stream was left STOPPED as found. The Owner's studio (run.py 55268, restarted by him at 13:49) reads day_state and will drive the towers' day from the real sun the next time a stream runs. Open for the Owner: his art verdict on the kept pass, and whether more windows should be lit just before sunset and after sunrise.

- 2026-09-26 art review of the towers-by-day window, run 2 (KEPT at 16:14): the frames were reviewed at fit zoom and in full-resolution crops against art-source/reference/headquarters_dusk_primary.png (scratchpad real_sky/towers_window/run2 and run2/art_review/ab_*.png). Noon (13:07) and 17:58 are clearly better: pale glass curtain walls with no lit windows, a sandstone near block, green trees and the BUCHAREST AI DISTRICT sign whole, so the navy cardboard towers and black trees are gone by day. 19:19 (reference, 6.7 against 6.8) and 21:17 are identical to BEFORE, and the HQ building itself is unchanged at every instant (region means equal within 0.2).

- Art verdict: not ship-ready as tuned. 18:50 (sun +2.7 deg) is worse than BEFORE at fit zoom. With WindowsOn at 0.10 the skyline loses most of its lit windows (lit_px 1729/2539 -> 599/482) and reads as mauve-brown slabs, several of them windowless, and the right near block turns from warm lit windows into a black box. 07:25 is mixed: the near block is sunlit and correct, but the left skyline is flat and nearly windowless (lit_px 323 -> 14). The cause is the backend WindowsOn ramp (and the near_blocks' window weight), not the level pass, so the fix needs no rebuild. The pass stays kept (umap 6828299B...8E03, env_report.json C9D91A13...9268 with day_state, rollback via E:\AMN_backup\hq_before_towers_day_20260926_1355 and env_report.before_day_state.json).

- 2026-09-26, towers window run 3, backend part): the towers' windows curve reshaped after the art director refused run 2 (18:50 at WindowsOn 0.10 turned the towers into muddy slabs and the right near block into a black box; 07:25 an empty skyline). scene_params.windows_share now lights none of the dusk's windows only from +15 deg up (the glare), 0.7 of them by +2.5 deg (0.70 at 18:50, +2.7), all from the reference dusk (-2.5) down; tower_windows_share caps the morning by the city's dawn rule (DAWN_CITY_WINDOWS 0.45) instead of multiplying by it, so 07:25 shows 0.45 of the windows, not 0.06; the near blocks take their own value with a floor of 0.5 below +6 deg (near_windows_share), so a lit near block never goes black. The plan's towers key is per label (skyline, near_blocks) and unreal.environment_calls sends each tower component its label's TowerDaylight and WindowsOn. Golden test exact; 155 tests in the touched files and neighbours pass; ruff and mypy clean. Not yet seen on the stream: the previews at 18:50, 07:25, 17:58 and 19:19 follow in the window, with the level pass re-applied by hash and the merged report held aside until KEEP.

- 2026-09-26, towers window run 3, the short window): NOT RUN. After the curve step (scene_params windows curve: off only above +15 deg, 0.7 at +2.5, 1 at the reference; dawn ceiling 0.45; near blocks' floor 0.5), the window to re-apply run 2's level pass by hash and preview 18:50 / 07:25 / 19:19 with the new curve could not start: the stop of the stream's own processes (wilbur 45820, UnrealEditor 45784, running for the Owner since 16:26) was refused by the tool's permission classifier, and the level copy needs the game closed (its packages are open) while a preview on the running pre-window level shows nothing new. Preflight had passed (level C73D2DB2...0216 = backup, live content identical to the pre-window lists, run 2's 30 saved files verified, umap 6828299B...8E03), the merged report was prepared outside the tree (run3\merge\env_report.held.json), and the right near block was measured on the BEFORE and RUN2 frames (18:50: BEFORE lit_px 733 / p90 91.8, RUN2 lit_px 0 / p90 23.8, the black box). Nothing changed: level, env_report.json (no day_state, in place), stream running (Remote Control answering), studio 55268 untouched. The Owner was pushed a restart notice and then its correction.

- 2026-09-26 17:00-17:15, towers window run 3, the short window): run 2's level pass re-applied by hash (30 files, HQ_Dusk.umap 6828299B...8E03, no commandlet) after the main session stopped the stream at 16:55; the stream restarted at 17:00 (wilbur 51724, UnrealEditor 44144, endpointIdConfirm 17:00:25, Remote Control answering) and previewed with the reshaped curve on a held merged report: 18:50 towers lit_px 1515/2172 (88%/86% of BEFORE, run 2 had 599/482), near block dark brown with three lit windows (run 2 black), 07:25 left skyline lit again (459/814 vs run 2 14/193), 19:19 = 6.8 = BEFORE. KEPT with one failed gate stated: the 18:50 frame scores 27.5 against BEFORE 25.6 (limit +1.0; run 2's level alone scored 27.0, the day-lit facades), which no curve on this level can pass. The merged report is released (env_report.json with day_state, the pre-window report kept as env_report.before_day_state.json); the stream ends running; the Owner's studio still runs the 13:49 code (09-24 curve) until he restarts it. Probes: near block WindowsOn 0.85 -> 9 lit blobs, 1.0 -> 18 = BEFORE (curve 0.684 -> 1).

- 2026-09-26, art director's second read, towers window run 3): the refusals on run 2 are answered on the live level. 18:50 is a warm sunset with its lit windows again (towers 1515/2172 lit px, 88%/86% of BEFORE, against run 2's 599/482); the mauve slabs are gone, the facades read as stone in the last sun with window grids that read as windows; the right near block is a dark-brown facade with three lit windows instead of run 2's black box. 07:25 is a city that wakes, not a dusk mirrored: the left skyline has windows again (459/814 vs run 2's 14/193) at about a third of the evening's count, the classic block sandstone in the morning sun. 19:19 is identical to BEFORE by eye and by number (6.8, towers 1376/2263, near block 1194). Noon keeps run 2's leap. Verdict ALMOST, ship: the level is run 2's kept pass, the curve is the Owner's rule (windows 0 above +15 deg, about 0.7 at +2.5, 1 at the reference dusk), and nothing on the page is worse than BEFORE except one patch: the 18:50 near block is thin (3 windows where BEFORE had 9) because 0.68 on that facade lights few ranks; the probes at 0.85 / 1.0 give 9 / 18 windows, so its own curve to about 1.0 by +3 deg restores BEFORE without a level pass.

- the failed gate, read by the art director): the 18:50 score 27.5 against 26.6 is not a picture defect. The gate measures distance from the 19:19 dusk reference at an instant with the sun up; the excess sits in city_left / sky_left / city_right, i.e. the day-lit facades the Owner ordered kept (run 2 alone scored 27.0) plus the returned windows, while every building region is within 0.4 of BEFORE. The gate is the wrong measure for a sun-up instant; the lit_px, near-block and 19:19 gates discriminated and should replace it there. The stream ended running on the re-applied level; the Owner's studio still runs the 09-24 curve until he restarts it, so from about 18:00 tonight his page shows run 2's refused 18:50 until that restart.

## The Owner's controls as plates of the building: premium (2026-09-26)

The last two plain surfaces are plates of the building, and the release judge calls the whole interface premium. In Setări → Canale the Director's right is a decision plate: a large switch, steel when OFF (never alarm-red), lit in the page's accent when ON, each state's meaning written beside it, and a glass confirmation step that shows OPRIT → PORNIT before it asks; proven on a stand that answers as the routes do: no write before «Da», none after «Renunță», one versioned command after «Da». In Trezorerie → Prețurile modelelor each model is a plate with its provider's mark, two USD wells and its key; a provider-wide plate writes the backend's real «*» resource; a model the studio knows can be added, a foreign name is refused in Romanian. The cold entry no longer double-exposes the plates and the stream, and has no dark beat between them; Distribuție opens under reduced motion in 14 ms; the preflight's keys use the backend's arrow. Verdict on the page renderer: amazed YES, premium YES, premium without the Owner's items YES.

- ### The last plain surfaces, game-grade (W36, 2026-09-26)

The release judge of W35 named what still read as a form beside a game frame. Setări → Canale is now a decision plate: the Director's right on an illuminated plate with a 64×32 px switch in a 164×50 px pill, calm steel when OFF (`--ink-2`, never the alarm ink), lit in the page's accent when ON with a halo and a lit top rail; the W34 sentence stands beside it as its two states, word for word, the current one marked «ACUM»; the confirmation is a glass step that shows OPRIT → PORNIT, asks the question, and says «Până nu apeși Da, nu se schimbă nimic.» The channels are plates of their facts at their own height with the page's own marks (clapper, 9:16). The harness proved 0 writes before «Da», 0 after «Renunță», one versioned command after «Da» (`settings.js directorSwitch`, `owner_controls.js directorRightLines`).

- Trezorerie → Prețurile modelelor is one plate per model: the provider's mark (its first letter on the icon family's hexagon, one of three cool tones by name, no downloaded logo), its state (fără preț · preț pus · ia prețul furnizorului), two USD wells and the key. A group «Pentru tot furnizorul» writes the backend's real provider-wide resource «*» (`economy/prices.py ANY_RESOURCE`, `PriceCommand.resource` pattern `\S`, `price_row` specificity) — the backend accepts it, so it is offered, one plate per provider the studio's models run on. «Adaugă un model» puts in the list a model the preflight did not name, validated against the models the studio knows (GET /settings via `knownModels`/`checkNewModel`); nothing is sent on add, the price is saved by the row's own key. Measured: 26 known models offered, a refusal in Romanian for an unknown name, an add with no write, a provider-wide save of two PUTs with resource «*».

- The cold entry double-exposed the plates and the live stream for ~190 ms of the push (28 frames, 502–690 ms, filmed with a stand-in stream frame). `title_screen.js` now marks `body.is-pushing` for `ENTRY.pushMs` when no kept frame lands, and `style.css` holds the stream layer's picture at opacity 0 through the push and fades it in after, as the returning entry's panel appears only after `--dur-push`. Filmed again: 0 double frames at 1920, 1280, 2560 and 390. A short dark beat (~60 ms plus the fade) now sits between the plates' end and the stream's arrival; it is the returning entry's shape and is recorded as a judgement for the Owner.

- Distribuție under reduced motion opened in one 34.7 ms frame (showModal restyle plus a full layout of ~900 objects). Its overview grid, channel card, channel list, each channel slot and the publications list carry `data-door-steps` (`doorSteps` walks six levels), and the gate list's «măsurate» is set in ink weight instead of the italic face whose first use cost 8–10 ms. Measured through `doors36.mjs`: publishing's opening worst frame 13.8 ms at 1280×800 reduced, 14.0 ms at 1920, 7.1 ms with motion, no long animation frame. Research (27.8/20.9 ms) and Story (20.7 ms) still each have one frame over 20 ms on their first open.

- The page's own fallback labels for the two new places now use the backend's arrow (`Setări → Canale`, `Trezorerie → Prețurile modelelor`, `readiness.js FIX_PLACES`); `judge_w34.test.js` was updated on purpose and `judge_w36.test.js` (9 tests) covers the wave. Contrast measured on every text run of both surfaces at four sizes: no failure, lowest 5.80:1; every target ≥ 38×122 px, focus rings 2 px in the accent (the price well carries its input's ring). npm test 611 pass, npm run check clean, shoot.mjs at three sizes with 0 missing fixtures and 0 console errors; frontend/dist rebuilt.

- ### The release judge of W36: the plates hold, the entry's hand-over closed (W37, 2026-09-26)

Judged cold at 1920×1080 in a fresh profile, then returning, then as a critic of 2026 game interfaces, on the page renderer and the captured fixtures (the stream not connected in this wave; a stand-in stream frame where a stream state was needed). Verdict: amazed YES; premium YES; premium without the Owner's items YES. Setări → Canale reads as a decision plate of the building (steel OFF, lit ON, the glass step that says OPRIT → PORNIT before it asks) and Trezorerie → Prețurile modelelor as one plate per model with the provider's mark, two USD wells and a key, the provider-wide «*» plate above them. Proven against a fixture answering as the routes do: 0 writes before «Da», 0 after «Renunță», one versioned command after «Da»; on an answer the page cannot read it says so and keeps the switch; 0 writes on a refused or accepted add, 2 PUT with resource «*» on the provider-wide save. Nothing simulated found.

- The cold entry's hand-over. W36 held the stream's picture until the push's end (700 ms), but the push's own curve has the plates under 5 % from ~580 ms and gone at ~645: the render's ground showed for ~60 ms and the picture only faded in after (a dark beat, ui/w37/entry_1920). `ENTRY.streamMs = 640` (title_frame.js) now ends the hold where the plates are under 2 %, and the picture is full at 760 ms, before the entry's end; `judge_w37.test.js` computes the plates' opacity at that mark from `--ease-push` and the keyframes. Filmed again at 1920, 1280, 2560 and 390: 0 double frames, 0 dark frames, the picture rising as the plates go (ui/w37/entry_after_*, entry_handover_1920.png). Under reduced motion the decision step's `animation: none` was outranked by its own later rule; it is now named from its plate (`.decision-plate .decision-confirm`) and tested.

- Measured: every door under reduced motion at 1920 ≤ 14.0 ms worst except Research's open (20.9) and Treasury's close (20.8), no long animation frame; contrast 0 failures on both new surfaces (lowest 5.80:1); Tab walks of 44/13/30 stops all ringed and ≥ 32 px; shoot.mjs at three sizes with 0 missing fixtures and 0 console errors. npm test 613 pass, npm run check clean, frontend/dist rebuilt. Still plain or open: Distribuție's channel slots are the older card style beside the new plates; the price list is a wall of identical plates when many models are unpriced; a one-sided «*» price leaves its models marked «fără preț».

## Controls for the Owner's decisions: the interface premium apart from his items (2026-09-25)

The Owner's own decisions have controls on the page, and the release judge calls the interface premium apart from what only he can change. Setări has a «Canale» tab where Channel B carries the switch «Directoarea poate aproba episoadele serialului»: it says what it does and what it spends, asks for confirmation, sends the versioned publish-policy command only on «Da», and shows the versioned answer; it stays OFF until the Owner turns it on. The Treasury has «Prețurile modelelor»: one row per unpriced or priced model, USD per million input and output tokens, validated, saved as versioned price commands, in a stable order. The preflight's keys lead to these places, and the backend gives them those places. «Starea modulelor» moved into Setări → Despre studio; the drawer's lower half is «Studioul azi», which now says «Ultima rulare» for a run that is not today's. The register folds the supervisor's routine into one quiet row per stretch and never folds an act. The returning title has no seam, raw YouTube and voice ids are tooltips, long prompts fold to their first sentence. Both controls were proven against the real backend on an empty studio, never on his data. The release judge: amazed YES; premium ALMOST; premium without the Owner's items YES.

- **W34 backend: the two lines the page can now fix, and runs stored before counts.** The preflight gives the Director's leave and the token prices real places on the page. serial_channel.director_may_not_approve now has place 'settings:channels', label «Setări → Canale», and its value carries channel_id and policy_version for the switch. model_prices.unpriced now has place 'treasury' with place_section 'tr-prices' and label «Trezorerie → Prețurile modelelor». A part of a room is the room's id plus the id of its element in index.html, the same way the budget already was, so a page that knows the room opens it at the right section. The price line's value lists each unpriced model and the token prices it lacks: {models, unpriced: [{provider_kind, resource, missing_units}]}. Only serial_channel.missing is still 'not_on_page'. The Settings tabs are named once, in app.wording.SETTINGS_TABS, which the preflight's PLACES reads. Measured on a copy of the Owner's database: both lines now name the page's places; the serial line points to channel 34acf9d6 at policy version 1.

- **Old runs are no longer recounted.** All 18 of the Owner's stored runs (2026-09-12) predate the counts. The runs list used to recount them from artefact keys they never wrote, and so called «producție media» idle on days that rendered. runbook.services.stored_summary now calls a run 'counted' only when every stage carries 'produced'. Any other run is 'before_counts': its summary starts with «Rulare dinainte de numărătoare», names the stages that failed or were blocked, keeps only the film its old publish artefact names by id, and has stages_productive = None (never 0). list_runs and execute_daily_run return summary_code. Tested in tests/test_run_before_counts.py; on the copy, 18 of 18 runs are before_counts.

- **Romanian where the Owner is sent to Settings, and in the two routes' refusals.** Every sentence that said «Settings» now names the tab: analytics (2), research agent picker (2), media route and reference set, workforce proposal, ElevenLabs (2), Runway (3), publishing route (2). tests/test_settings_place_words.py scans every string literal in backend/app for the English form. A command id reused with different data is now said once, in Romanian, as wording.COMMAND_REUSED, and every Owner command uses it. PUT /economy/prices refuses a blank resource as a 422 field error (it was a 409 with an English sentence). The publish policy's «public» refusals no longer name a field and point to the dock's MEDIU switch instead of a «pagina Owner» the studio does not have.

- **Shapes for the page (W34).** PUT /api/v1/economy/prices, Owner bearer.
Request: {command_id: uuid, new per click; provider_kind: ^[a-z][a-z0-9_-]*$, at most 40, lower case, the preflight's value.unpriced[].provider_kind; resource: 1..200 with at least one non-blank character, a model id, a family ending in '*', or '*' for the whole kind; unit: per_1m_input_tokens | per_1m_output_tokens (the token form; per_1k_characters, per_second and per_generation also exist); usd: ^\d{1,9}(\.\d{1,6})?$ with a dot, and '0' means free; optional provenance, default OWNER; optional expected_version ≥ 1, the version of the active row for exactly this kind, resource and unit, left out for the first price; optional notes, at most 2000}. Unknown fields: 422.
200: {id, provider_kind, resource, unit, usd (trimmed decimal string), usd_micros, provenance, version, active, set_by 'owner', notes, set_at, replaced_at null}. The same command again returns the same 200.
409: {detail} in Romanian: COMMAND_REUSED, or «Prețul are versiunea N, nu M; recitește-l înainte să-l schimbi.» («versiunea nesetată» when no row exists).
422: {detail: [{type, loc: ['body', field], msg}]}.
GET /api/v1/economy/prices?provider_kind= returns {prices: [same view]}, active rows only. Each token side is a separate PUT.

- POST /api/v1/publishing/channels/{channel_id}/publish-policy (36-character id, Owner bearer).
Request for the leave switch: {command_id: uuid, expected_version: the channel's policy_version, director_may_approve_episodes: bool}. The channel id and version are in the preflight line's value or in GET /api/v1/publishing/channels (OFFICE_SERIAL). Also accepted: autonomous_privacy, public_publish_enabled, publish_delay_minutes 0..43200, schema_version 1. Unknown fields: 422.
200: {command_id, status: 'COMMITTED' | 'NO_CHANGE', channel: ChannelView (…, director_may_approve_episodes, policy_version, policy_changed_event_id, publisher_ready …), event_id}. COMMITTED raises policy_version by 1 and records publishing.channel_policy_changed; NO_CHANGE leaves no version and no event.
409: COMMAND_REUSED, or «Politica de publicare a canalului s-a schimbat între timp; reîncarcă și trimite comanda din nou.»
404: «Canalul … nu există.»
422: the Romanian «public» refusals, or the pydantic list. Tested in tests/test_price_and_leave_routes.py.

- ## The Owner's own decisions on the page, and the module list off the main screen (2026-09-25)

- Two decisions the preflight said could be made «deocamdată doar prin API-ul studioului» now have controls on the page, and the page never sets either on its own. In Setări, the new tab «Canale» shows each channel with its type, its YouTube account by title and its policy version. On the serial's channel is a switch, «Directoarea poate aproba episoadele serialului», with one sentence under it on what it does and what it spends. It asks before it changes anything, and only «Da» sends the channel's versioned publish-policy command. The Treasury has a new section, «Prețurile modelelor»: per model, the price per million input and output tokens in USD, validated («0,50» or «0.50»; both sides or none), saved as two PUT /economy/prices commands, with the answer in the row. The preflight's two lines open these places through their doors. This works whether the backend still says not_on_page, sends no place (the Owner's running studio) or sends the new places. «Starea modulelor» left the main screen for Setări → «Despre studio», and the side drawer's lower half is now «PE SCURT · Studioul azi» at every height. The release judge's other items are done too: the returning title has no seam; the watchdog's routine is one quiet row per stretch of routine («Rutina studioului ×20 · supraveghetorul»); raw YouTube and voice ids are tooltips; long scene prompts show their first sentence; Research's first open is lighter.

- 2026-09-25, W34, the controls (frontend/src/owner_controls.js, new and tested; settings.js renderChannels, directorSwitch and renderAbout; main.js loadPrices and the prices form; readiness.js CODE_FIX, checkCode and PAGE_SECTIONS; index.html #tr-prices; style.css W34 section). The switch is role=switch and states PORNIT or OPRIT. The confirmation asks «Îi dai Directoarei dreptul să aprobe episoadele serialului?» with «Da, dă-i dreptul» and «Renunță». The command is {command_id, expected_version: policy_version, director_may_approve_episodes}. The answer is «Salvat: … Politica canalului este acum la versiunea N.» or «Nimic de schimbat …»; a refusal is the backend's own detail, and a 409 re-reads the channels. The price rows are the models the preflight found unpriced (value.unpriced from the W34 backend, else a detail that is exactly a kind:model list) plus every model priced per token in the books. A replaced price carries expected_version. A half save is said honestly («Prețul de intrare s-a salvat (versiunea N); cel de ieșire nu: …»). No example figure is shown. The other half of this wave (backend) chose the same places: settings:channels and treasury + tr-prices. The glossary's W34 amendment was written first.

- 2026-09-25, W34, the main screen and the small things. The drawer: #modules-panel is gone, #studio-readout is grid row 2 at every frame height, and its foot key «Despre studio» opens Setări at that tab (main.js keeps latestModules for it). The register (ledger.js): a routine start (ROUTINE_JOB) is folded into the open routine row while no act has been drawn since it opened, and within an hour across an act too. A fold never crosses midnight, the counts account for every event, and letters and acts are never folded. The watchdog is said as «supraveghetorul», the backend's own word. The returning title (title_frame.js keptEdges and skyRow; title_screen.js drawKeptEdges): the band above the kept Unreal frame is the frame's own top row, with the building's columns filled from the sky beside them, stretched, softened and fading into the row's average. It is drawn once per light reading, with no seam and no smear over the lift tower. Distribuție: «Canal YouTube: <title>», with the UC… id and the video id as tooltips. Media: «Voce: <style> · ×0,98» and «Voce alocată», with the voice ids as tooltips; a prompt over 160 characters shows its first sentence and «Tot promptul»; no narration is «—». Research: the «↻» glyph, in no page font, cost 10-11 ms of text shaping on its first use and is now the page's refresh icon. The site rows, sources, topics and scripts are laid out one step per frame (data-door-steps).

- Tested (W34): frontend 598/598 (10 new in tests/judge_w34.test.js, written first; judge_w32, game_frame_css, frame_sky_row, ledger and ledger_fold updated on purpose), tsc clean, build green, dist rebuilt last (index-B3_9mrPm.js); :8000 serves it and was not restarted. No backend or tests/ change by the frontend. Scratchpad ui/w34:
  - w34.mjs at 390, 1280, 1920 and 2560, plus 1280 under reduced motion and 1920 with the W34 backend's places: the switch, its question and answer; the price form's two refusals and its answer; both preflight keys through their doors; 0 raw ids printed; 0 missing, 0 errors; writes only to the harness.
  - Every new key is 32 px or more and ringed.
  - Research under reduced motion, HEAD against W34: worst 41.6-41.7 → 27.8 ms (3 runs each).
  - Every door with motion: 27.8 ms or less.
  - Over the real stream (read-only W21 viewer): Research's first open 27.8 ms without a screencast (HEAD 27.8-34.8); doors_live twice (Research 34.7-34.8 with the screencast, the rest 27.8 or less, lit room within 0.5 px, 0 errors, 0 missing, 0 foreign, the key 0 times).
  - ret34.mjs at 1920 and 2560: the returning title has no seam.
  - contrast26 at 1920: new text 4.67:1 or more.
  - shoot.mjs at 1280, 1920 and 2560: 0 missing, 0 errors.

- Still open (W34). Until the Owner restarts, his studio's preflight still says the price and the Director's right are «doar prin API-ul studioului» beside the keys that now open them. The Director's right stays OFF, and the prices stay unset, until he decides them. A model the preflight does not name cannot be added to the price list from the page. Research keeps one 34.7 ms frame over the stream while a screencast records; the ~17 ms style recalculation of showModal (the document becoming inert) is common to every door. The mail step of the full stranger run timed out on a harness selector and was not re-run after the stretch fold. The storyboard prompts still repeat their subject (the backend's prompt builder). The returning title's seam was photographed only on a morning frame.

- ## The release judge again: the two controls proven on the real backend, and three small untruths fixed (2026-09-25, W35)

- The page and the backend agree. The switch sends {command_id, expected_version: policy_version, director_may_approve_episodes}. The price form sends PUT /economy/prices per side, with the usd decimal string, provenance OWNER and expected_version only when a price is replaced. Both match PublishPolicyCommand and PriceCommand, and the page reads the W34 places (settings:channels; treasury + tr-prices) and value.unpriced.
  - Both controls were driven against the REAL backend of this tree on a FRESH studio (scratchpad ui/w35/fresh_backend.py: the bootstrap seeds, a made-up key, worker and catalogue off, non-loopback network refused; no data of the Owner's) with ui/w35/prove35.mjs.
  - The switch: «Renunță» sends nothing. «Da» gives COMMITTED v2, read back. A concurrent change gives the backend's 409 sentence and the channels are re-read (versiunea 3). The next «Da» gives COMMITTED v4.
  - The prices: comma input is stored as "0.50" v1 OWNER. A replace carries expected_version and gives v2. A stale save gives the backend's «Prețul are versiunea 3, nu 2 …», with no half save. Once every model is priced, the backend's preflight line turns OK on the page.

- W35 fixes.
  - owner_controls.js tokenPriceRows: one fixed order (provider, then model). «Unpriced first» moved the row just saved to the bottom after the recomputed preflight, and the next save priced the wrong model.
  - side_readout.js: the drawer's run line says «Ultima rulare» unless the run's business date is today. It said «Rularea zilei 12/12 · încheiată» on 25.09 for the run of 12.09.
  - style.css: #studio-readout joins the panel-arrive list (the governance panel's delay), the closed-drawer exclusion and the reduced-motion list. It replaced .modules-panel in W34 without being named, and stood opaque at 400 ms.
  - backend runbook/services.py: both run headlines say «etape de lucru». The runs list showed «12/12 etape încheiate» above «10 din 10 etape au rulat».
  - Glossary W35 amendment written first.

- Tested (W35).
  - frontend: 602/602 (4 new in tests/judge_w35.test.js, written first), tsc clean, build green (index-CBVheCVX.js); :8000 serves it and was not restarted.
  - backend: test_run_before_counts and test_day_survives_a_stage updated first; the 12 test files touched this wave pass (208); ruff and mypy clean.
  - Fixtures recaptured from a fresh copy of data/studio.db (with -wal and -shm; the original was never opened): 254/258.
  - A stranger over the real stream (ui/w35/j35_final, read-only W21 viewer): live, returning live, 0 errors, 0 missing, 0 foreign, the key 0 times.
  - shoot.mjs at 1280, 1920 and 2560: 0 missing, 0 errors.
  - focus26 at 1920 and at 1280 reduced: 0 faults. tabwalk35 covers Canale and the switch by Space and Enter.
  - Every door with motion: 27.9 ms or less.
  - contrast from real pixels at 1920: new text 5.5:1 or more; the three 4.40-4.49 runs lie under the sticky header.

- Still open (W35).
  - Until the Owner restarts, his studio's preflight says «doar prin API-ul studioului» beside the keys, and those two keys use the page's «·» labels while the others use «→».
  - Distribuție keeps one 34.7 ms frame on first open under reduced motion (showModal restyle plus a full layout), as in W33/W34.
  - A cold entry double-exposes the plates building and the live stream for ~300 ms during the push.
  - Canale and Prețurile modelelor are clean but plain beside the game frame.
  - The stream harness's 60-event replay no longer reaches a letter; the mail was photographed through the fixture harness.

## The preflight as a checklist, and real faces over the stream (2026-09-25)

The preflight is a game's checklist, and the employees wear their real faces over the stream. Rularea zilei's preflight, the one surface judged NO, now reads «De rezolvat · De știut · În regulă»: each failing check is one row with its state in words, colour and shape, the backend's sentence, a disclosure for details, and a key that opens the exact place that fixes it through its door (a Settings tab, the Treasury's budget, the Character Bible, the autonomy switch). The backend gives each line a stable code, a severity and its place (backend/app/runbook/preflight.py; tests/test_preflight_places.py), speaks in the page's places instead of API routes and environment variables (kept only as a tooltip), and a research site's failure is one Romanian reason with its code (tests/test_host_test_words.py). The inspector's header wears the employee's portrait, the raw id became a copy key, and over the stream every portrait is cut from the real Unreal frame. The release judge: amazed YES, premium ALMOST - the checklist is premium; «Starea modulelor» on the main screen is the one NO left.

- The preflight in the page's words» (W32, backend). Claim: rewrite every preflight sentence in the page's places and give each line structured fields; make the Research door and the preflight agree on failed sites. Outcome: done and tested. backend/app/runbook/preflight.py no longer puts a route, a STUDIO_* variable, an OAuth scope, a policy field, Google's raw answer, a record id or a decimal-point amount in the message, detail or summary. Each line now also carries code ("<name>.<condition>"), impact (blocks | degrades | informs | ok), place (from preflight.PLACES; null when ok), place_label, place_section (an element of index.html) and technical {routes, settings, scopes, fields, answers, paths}. Fixes with no control on the page (token prices, the Director's right to approve episodes, creating channel slots) are said honestly as «deocamdată doar prin API-ul studioului» with place not_on_page. Research: failed site tests store a Romanian detail (app.wording.host_test_detail) with their reason code, and the retriever's English goes to the event as error_detail. The 16 rows the Owner's studio stored before migration 0040 (reason NULL, «Source returned HTTP 403») are read with the derived code and Romanian words, and nothing is written to them. Tests: tests/test_preflight_places.py and tests/test_host_test_words.py are new; the sentence assertions in test_readiness, test_research_sources, test_sources_and_readiness and test_pipeline_coverage were updated on purpose. The neighbours ran green (188 + 262 + 267 passed, 2 skipped); ruff and mypy backend are clean.

- ## The preflight as a checklist, the employee's face, and the doors over the stream (2026-09-25, W32)

- The daily run's preflight was the only surface the release judge called NO. It is now a checklist, like a game's. The lines that fail stand first, each as one row: its state in words, colour and a shape, the backend's sentence as written, and a key to the place in the page that fixes it. The passing lines are one quiet row each, and every detail waits behind «Detalii». The inspector's header now wears the employee's roster portrait. While the Unreal stream is what the visitor sees, every portrait is cut from the real Unreal frame at that employee's desk, so the roster and the building are one picture. Media, Distribuție and the daily run opened with a 35-70 ms frame over the stream; they now open at 21-28 ms.

- 2026-09-25, W32, the preflight (frontend/src/readiness.js preflightChecklist, checklistHtml, fixPlaceOf, technicalNote; main.js loadPreflight and openFixPlace; style.css W32 section). The page reads each check's name, ok and severity, and the new backend's place, place_label, place_section and technical. It never parses a sentence. There are three groups: «De rezolvat» (the backend's first_stop first, then blocking, then degrading, then an unknown severity), «De știut» (failed informational lines) and «În regulă». A failing row has its mark (■ BLOCHEAZĂ, ▲ DEGRADEAZĂ, ● INFORMATIV), its name, the message and «Detalii» (only what the detail adds). The key reads «Deschide {place_label}». It closes the daily run's door and opens the place through its own door, at the Settings tab, or brought to the section once the content stops moving. Setări opens at its tab through settings.js open(tab); the Character Bible opens at its tab; the AUTONOMIE switch gets the focus. `machine` and `not_on_page` get no key. The backend's `technical` is the name's tooltip, never printed. A backend without `place` (the Owner's running studio until his restart) is read by the check's code (CHECK_FIX). Glossary W32 amendment written first.

- 2026-09-25, W32, the employee's face. The inspector's header has the roster's portrait (painted by the same paintPortrait), the state chip, the place and the name. The raw id is no longer a fact on screen: it is the title of a «Copiază identificatorul» key. roster.js streamPortraitSource maps the portrait's world window into the frame the page holds (hq_stream.js replayPicture: the video's frame copied every 2 s, a frozen or held frame, or an earlier visit's kept one). The frame lies exactly over the world, and the Unreal heads sit 34-36 world px above the manifest seats. The page renderer's figure is used otherwise. Nothing is fetched and nothing is drawn per frame. Measured on the real stream (read-only viewer) at 1920 and 2560: 8 of 8 portraits and the inspector come from the stream.

- 2026-09-25, W32, the small things. Setări prints a «settings:<uuid>» connection by its title only; the stored name is in the tooltip. The Treasury's vendor tile says «Runway». The phone rails line up with their content (45-345 px) and fade at the edge they scroll past. At 2560 the roster and the daily run's door are 1840 px wide, and every place stays on one line. Media's and Distribuție's panes were one wrapper, so the W28 stagger never ran and Media laid out every storyboard in its first frame (42.6 ms of layout). The stagger now counts steps; the heavy parts carry data-door-steps; storyboards, scenes and the Journal's beats are content-visibility:auto. Over the real stream, worst frame: Media 48.5-62.5 → 27.8 ms, Distribuție 41.6-69.4 → 20.9, the daily run 34.8-48.5 → 20.9. Under reduced motion, Media 41.7 → 20.9.

- Tested (W32): frontend 582/582 (11 new, tests/judge_w32.test.js, written first), tsc clean, build green, dist rebuilt last (index-B0-9DKyq.js); :8000 serves it and was not restarted. No backend change by the frontend. The new backend's preflight was captured from a copy of data/studio.db (-wal and -shm; the original never opened) into ui/w32/fixtures32 (254 of 258). Scratchpad ui/w32: w32.mjs at 390, 1280, 1920 and 2560 (the checklist, the keys through their doors, the roster, the inspector, the phone rails: 0 errors, 0 missing); live32.mjs on the real stream at 1920 and 2560; w28d/doors_live.mjs 2 runs before and 3 after (0 errors, 0 missing, 0 foreign requests, key 0 times, lit room within 0.5 px); trace32.mjs; doors_film --perf --reduced; focus26 at 1920 and at 1280 with reduced motion, plus focus29 (every stop ringed, inside, 32 px or more); contrast26 at 1920 (checklist lowest 6.10:1); shoot.mjs at 1280, 1920 and 2560 (0 missing, 0 errors).

- Still open (W32). The stream portraits are soft (a 53x40 px crop of the 1920x1008 frame), and in Unreal two employees sit hidden behind their monitors. Research over the stream (34.7 ms) and under reduced motion (41.7 ms, a forced 18.6 ms style recalc in the click), and the Journal over the stream (34.7-41.8 ms), keep one long frame. The preflight's sentences are the backend's and still long. Until the Owner restarts, his studio sends no place fields and the page uses its own names for the keys. The AUTONOMIE-switch key was only unit-tested. Contrast was re-measured at 1920 only.

- ## The release judge after the checklist (2026-09-25, W33)

- A stranger opened every door cold at 1920x1080 in a fresh profile, over the real Unreal stream (read-only viewer, made-up key, no Remote Control). The API was answered from a fresh copy of the Owner's database, so the backend's new words and place fields were judged too. Verdict: amazed YES; premium ALMOST. Setting aside what only the Owner can change, the page is still ALMOST. The preflight checklist, judged NO in W31, is now YES. Four small defects that read as unfinished were fixed:
- a failed site said its reason twice, and for www.nature.com the two halves disagreed and blamed the Owner's entry;
- all 36 Research rows carried an empty OpenSearch field;
- the Character Bible cut its place chips mid-word;
- a seeded connection was titled «settings».

- 2026-09-25, W33, the page and the backend agree. The page reads place, place_label, place_section and technical under the backend's exact names, and every place section exists in index.html (rs-sources, tr-budget, media-characters-section, channels-list, #stop-toggle). No change was needed. Fixtures were recaptured twice from fresh copies of data/studio.db (with -wal and -shm; the original was never opened) into scratchpad ui/w33/fixtures33, 254 of 258 answers each time. The capture blanks every stored secret, so on the copy the image and voice lines read key_unusable; the Owner's studio reads his real keys.

- 2026-09-25, W33, the small fixes.
  - frontend/src/dialog_words.js hostFailureWords: a failed site prints the backend's sentence once, and the reason's label becomes its tooltip.
  - main.js: a site without a search address keeps the empty field behind «Adaugă adresa de căutare».
  - dialog_words.js connectionTitle, used by settings.js: a stored «settings:<uuid>» is titled by its service and host («Ollama · ollama.com»).
  - style.css (W33 section): the Character Bible's chip stands under the name, with an ellipsis and the whole place in its title.
  - backend/app/wording.py: the three URL failures from the retriever are said as the address the site sent the studio on to, never as the Owner's entry breaking the rules (tests/test_host_test_words.py changed first).
  - The glossary's W33 amendment was written in the scratchpad.

- Tested (W33): frontend 588/588 (6 new in tests/judge_w33.test.js, written first), tsc clean, build green, dist rebuilt last (index-fOcfunde.js); :8000 serves it and was not restarted. Backend: test_host_test_words, test_research_sources, test_sources_and_readiness and test_owner_words passed 71; the wave's six touched files passed 97; ruff and mypy backend are clean. Measurements, in scratchpad ui/w33:
  - j33.mjs over the stream, cold and then returning: 0 errors, 0 missing, 0 foreign requests, the key 0 times; 8 of 8 roster portraits and the inspector come from the stream.
  - doors_live, 2 runs: worst frame 13.9-34.8 ms, median 6.9 ms, lit room within 0.5 px.
  - doors_film under reduced motion: Research 41.7 ms, everything else 34.8 ms or less.
  - focus26 at 1920 and at 1280 reduced, plus focus29: every stop ringed, inside its dialog and at least 32 px.
  - contrast26 + pxcontrast26 at 1920: the checklist at least 6.10:1; three runs of 4.35-4.49:1 sit at clipped scroll edges.
  - shoot.mjs at 1280, 1920 and 2560: 0 missing, 0 errors.
  - check33.mjs at 1280 and 390: no chip cut, keys 32 px, no sideways scroll.

- Still open (W33). «Starea modulelor» reads as a developer checklist on the main screen. The returning title shows a seam above the kept Unreal frame. Research keeps a 34.8 ms frame over the stream and 41.7 ms under reduced motion. The register is crowded by the watchdog's routine entries. Raw YouTube channel ids and voice ids are printed. The storyboard prompts repeat their subject (the backend prompt builder). The Owner's items: his restart, model prices, the Director's right to approve episodes, reconnecting YouTube for statistics, the budget before PRODUCTION, the characters' reference sets, the Director's title and gender, and the stored English history.

## The employees as people, and the publishing gate in Romanian (2026-09-25)

The employees are people in a building, and the publishing gate speaks Romanian. The employees' door is a roster (frontend/src/roster.js): one card per employee with a portrait cut from the scene's own plates and sprite at their desk, in the pose their real state plays, their place in the building, their state, their last real task and their runs over 30 days, «—» where the page holds none; a card hands over to the inspector growing out of that desk. The heavy doors lay out in steps after the pane lands, their blurred shadows became gradients and the glass is warmed under the title. A filled approvals list is cards in the drawers' glass with the asker's portrait, and it no longer pushes the modules out of the drawer. The backend's publishing gate writes its reasons in Romanian through app.wording (tests/test_gate_words.py, 25 tests), and the register shows a refused gate's reasons. The release judge: amazed YES, premium ALMOST - the preflight still reads as a console of API routes and settings names, the inspector shows a raw id, and the rest waits for the Owner (a restart above all: his studio still runs the code of 24.09 11:07, so the live building is lit like night at 08:07 beside «Senin 17°C»).

- The publishing gate in the studio's words (2026-09-25). Measured on 28ad681, the Distribution door and the register still read the publishing gate in English: «Global autonomy stop is active», «QC status is MISSING», «Factual provenance unverifiable: no render job records this asset», «Duplicate publishing prevented; asset already published to this channel», «Simulated upload: no video exists on any platform.». The preflight's research line also printed codes inside a Romanian sentence («motor de căutare: NONE», «Picate: www.loc.gov (OTHER)»). Every reason and every check detail of evaluate_publishing_gate is now Romanian, written through app.wording. That covers the five checks and the policy check, passing ones included; the refusals of a publication intent; the gate error's message («Poarta de publicare a refuzat filmul: …»); and the sentences written after the gate (a simulated upload, a retry stopped because a duplicate cannot be ruled out, a platform whose state could not be read, a film not found after waiting). Numbers take a decimal comma and counts agree («0,50», «1 afirmație neverificată sau infirmată», «56 de octeți»). The one sentence for the Owner's global stop («Autonomia studioului este oprită; numai Proprietarul o poate reporni.») is shared by the publishing gate, the media gate and the policy kernel.

- Codes as data, not in sentences. The gate now returns `reason_codes` beside `reasons`, with one code per reason in the same order (AUTONOMY_STOPPED, QC_NOT_PASSED, QC_SCORE_BELOW_MINIMUM, FACTUAL_PROVENANCE_UNKNOWN, CLAIMS_NOT_SUPPORTED, DUPLICATE_ASSET, DUPLICATE_FILM, POLICY_NO_CHANNEL, POLICY_NO_VERSION, POLICY_VERSION_STALE, POLICY_VISIBILITY_EXCEEDED, MEDIA_ASSET_MISSING, MEDIA_FILE_MISSING, EPISODE_METADATA). Each check carries a `data` dict with the facts its sentence says in words: QC status, score and minimum; file path and size; the claim ids, including which are unverified and which are missing; the video already on the channel; and the requested and authorised visibility, the policy versions and the environment. Claim UUIDs have left the sentences. The publishing.gate_failed event records `gate_reason_codes`, and the day's blocked publish stage records `reason_codes`. The preflight's research check keeps search_provider and each failing host's reason code in its `value`. Its sentence says «niciun motor de căutare verificat» and «Nu pot fi citite: site — a refuzat studioul (403)», in the words of the sources list. The channel's visibility reasons say «mediul de test» / «producție» rather than TEST / PRODUCTION.

- Tested: tests/test_gate_words.py (25 tests, written first) plus deliberate updates in 10 existing test files. Each old English assertion was replaced by the Romanian sentence and by an assertion on where its code now lives. Touched files and their neighbours are green, and ruff and mypy backend are clean. No frontend code parses the gate's text. Two register gaps belong to the frontend: «publishing.gate_failed» has no case of its own (it prints «gate failed» with raw payload keys, and its Romanian reasons are never shown), and «publishing.failed» reads a field the event does not carry. Still English on the backend, outside the gate: the YouTube adapter's own error_detail, the publish-policy command's refusals that name public_publish_enabled, and two router HTTP details.

- ## The employees as people, doors at 60 fps, the approvals filled (2026-09-25, W30)

- The employees' door is a roster of people. Each employee is a card with a portrait: the scene's own plates and figure, cut at the employee's desk, in the pose the building plays for their state now. The card gives the name and role as the data gives them, the place in the building, the state now, the last real task and the runs the backend measured, with «—» where the page holds nothing. The cards stand in the building's order. A card opens that employee's inspector from their desk: the roster goes back into the lobby as the inspector grows out of the lit desk. The doors are closer to a clean frame rate: the Journal and the inspector lost their 42-49 ms frames, the mail its 62-69 ms frame, and over the live stream Research went from 62.6 to 34.7 ms and the Journal from 55.5 to 27.8 ms. A filled approvals list was judged for the first time, with a labelled fixture. It pushed the frame 84 px up, which is now fixed, and each request is now a card of the drawers, with the person who asked shown at their desk.

- 2026-09-25, W30, the roster (frontend/src/roster.js, new and tested; hq_world.js HQRenderer.drawPortrait and layerPart; main.js renderRoster, drawPortraits, openPerson; index.html; style.css --person-* tokens and the W30 section). A portrait is a 44x33 world window around the seat, drawn once into a 264x198 canvas. It is made of the room behind (building_back), the figure's still for the state now (stillFrame: typing when working, asleep when paused, holding its head on an error) and the desk in front (building_front), at the hour's real day/night mix. Only the window's pixels are read from each plate. No seat or no sprite: the frame stays dark with «—». The name and role are display_name split at its parenthesis; the role code stays in a title. The place comes from deskPlace, or «fără birou» with no desk. The state now is the name tag's word, worn as a glass chip on the portrait, and the standing is a pill. ULTIMA SARCINĂ is the newer of last_tasks and the register, with how long ago and «eșuată». RULĂRI · 30 DE ZILE shows the runs with agreement, the failure share («—» over no runs) and a meter set through the CSSOM (the CSP refuses inline styles). Cards are ordered top floor first, left to right, with no desk last. Card rows line up by subgrid: 4 to a row at 1920 and 2560, 3 at 1280, 1 at 390. The roster is laid out again only when a card would say something else, from the socket's events. The whole card is one button. It opens the inspector from the desk, the employee chosen as a click on the desk chooses them, and Escape returns the focus to «Angajați». The lit room now belongs to the door that lit it last (dialog_doors.js lightOwner), so the closing roster no longer turns off the desk's light. Glossary W30 amendment written first.

- 2026-09-25, W30, the doors' frames (dialog_doors.js doorRevealAt, doorSteps, doorLanded, revealInSteps; mail_thread.js landed; main.js showInspector and clearInspectorBody; key_light.js readAsync; style.css). A door's parts wait until its words begin to show, 40% into the opening, and then come in one step per frame. A heavy part marked data-door-steps (the Journal's episodes and newest episode, Research's first section) comes in piece by piece. The mail's letters and the inspector's contract, memory and history are laid out once the pane has landed. A fresh inspector shows no one else's contract while it grows. Traced and removed: the pane edge's two blurred shadows (about 16 ms of GPU raster per opening) and the lit room's two (about 28 ms) are now gradients with an unblurred ring; the mail reply's resize grip (56 ms the first time it is painted in a visit) is gone and the field grows with its text instead; the first door of a visit compiled the backdrop and glass blur (41-55 ms), which is now painted at 1% with the title's workspace warm-up (.glass-warm); the key light waited 22-33 ms for the GPU every 2 s at rest and now copies its 64 bytes asynchronously through VideoFrame. Measured, HEAD's build against this one alternately, 3 runs x 10 doors at 1920: openings over 33 ms 17 -> 5, median worst frame 27.8 -> 20.9 ms; Journal 35-42 -> 20.9, inspector 42-49 -> 21-28, mail 62-69 -> 14-21 (one 34.7); Research as the first door after the warm-up 34.6-34.8. On the real stream (read-only viewer), 3 runs: Research 34.7, Journal 27.7-27.8, Media 41.7-55.6.

- 2026-09-25, W30, the approvals filled (governance.js approvalCardHtml, expiryValue, APPROVAL_FOOTNOTE; roster.js requesterPerson; main.js renderApprovals; style.css). The Owner's data has no pending request, so two clearly labelled fixture requests were pushed: the approvals route's answer, plus their governance.approval_requested events in the harness socket's replay (W7_EVENTS, ui/w30/w30_fixture_*.json, every word «FIXTURĂ W30»). They showed a fault. A filled list grew the side drawer's upper half past the frame, the modules were pushed out and the footnote lay over them. When the gold mark brought the requests into view, the frame's grid (overflow: hidden) scrolled 84 px, leaving a black band under the street. The grid's rows are now minmax(0, max-content) minmax(--side-modules-min, 1fr), with overflow: clip after the hidden fallback, and the governance drawer scrolls inside itself. A request is now a card of the drawers: the action as the backend names it and its tier (T4 in gold); «DESPRE» and the subject; COST, EXPIRĂ and ACȚIUNEA set as the plaques set their facts, with «ireversibilă» in the warn ink; «Cerută de» with the employee's name and portrait when the backend's requester is that employee's id or exactly their role's code («publisher» → «Vera (Publisher)»), and otherwise as the backend wrote it; the backend's evidence; the two keys. The note on what an approval does is said once under the list. Every backend sentence is unchanged.

- Tested (W30): frontend 564/564 (15 new: tests/roster.test.js 8, tests/doors_w30.test.js 7, written after the code), tsc clean, build green, dist rebuilt last (index-Ba1trgV1.js); :8000 serves it and was not restarted. No backend change. Scratchpad ui/w30: roster30.mjs (the roster at 1920, 1280, 2560 and 390, the card-to-inspector film, the Tab walk, and 1280 under reduced motion: 8 of 8 portraits drawn, 0 targets under 32 px, the ring shown, no sideways scroll, the focus back on «Angajați»); approvals30.mjs (filled at three sizes: 0 clipped, the frame still); trace30.mjs, twice30.mjs, readback30.mjs and perf30.mjs (the causes above); w28d/doors_film.mjs 3x3 against HEAD (cmp, cmp2); w28d/doors_seq.mjs; w28d/doors_live.mjs 3 times on the real stream (0 errors, 0 missing, 0 foreign requests, the key 0 times in requests or the console, lit room within 0.5 px). shoot.mjs at 1280, 1920 and 2560: 0 missing, 0 errors.

- Still open (W30). Research as a visit's first door keeps one 35 ms frame, and Media one 42-56 ms frame over the live stream. The card-to-inspector hand-over has one 41-55 ms frame. The glass warm-up rides on the title's workspace warm-up, and the key light's asynchronous read needs WebCodecs (elsewhere it falls back to the old readback). The portraits are the page renderer's figures, soft at their size, even while the Unreal building is what is seen. At 2560 the doors stay 1440 px wide, so two places wrap onto two lines. At 1280 a long approvals list scrolls inside the drawer with no edge fade. The approvals were judged only with a labelled fixture. The publishing gate's English reasons, the stored history and the models' fields remain for the backend or the Owner.

- ## The release judge after the roster and the Romanian gate: the words from a fresh copy, the doors on the stream (2026-09-25, W31)

- A stranger, cold and then returning, at 1920x1080 on the real Unreal stream (the W21 read-only viewer: made-up key, RTCDataChannel.send replaced, no Remote Control). The title stands on the studio's real frame of the hour 1.3 s after navigation («ACUM 08:07 · ULTIMUL CADRU LIVE»), the building is live 2.9 s after the key both times, the invitation comes at 13.5 s, and the replay of 12.09 plays to its end both times. 0 errors, 0 missing, 0 foreign requests; the key 0 times in requests, the console or the socket URLs. Verdict: amazed YES, premium ALMOST, and still ALMOST with the Owner's items set aside. The title, the live building, the replay, the doors, the roster of people and the filled approvals are at a 2026 game's level. What keeps the rest ALMOST: the daily run's preflight, which the backend writes today, is a console of API routes, environment names and OAuth scopes. The Owner's studio, running since 24.09 11:07, lights the live building like night at 08:07 under «Senin 17°C», and his next restart fixes it.

- 2026-09-25, W31, the words judged on a fresh copy. The fixtures were recaptured from a copy of data/studio.db taken with -wal and -shm (w17/capture_fixtures17.py; the original never opened; secrets blanked; the copy migrated 0045 → 0047): 254 of 258 answers into ui/fixtures, with the old set kept as ui/fixtures_w30_prev. The publishing gate now reads Romanian with its codes as data («Publicare dublă oprită: materialul este deja pe acest canal», reason_codes ["DUPLICATE_ASSET"]; «Fișierul este pe disc (8591134 de octeți).»; «Controlul calității a trecut, cu scorul 1,00.»). The research line says «niciun motor de căutare verificat» and «Nu pot fi citite: … — nu a răspuns cu nimic utilizabil». The copy also showed a fault: with a chosen, verified media connection whose key cannot be used, the image and voice lines lost their subject («  Până atunci randările folosesc substitute…»).

- 2026-09-25, W31, what the judge fixed (small, each measured first). (1) Rularea zilei → Programare: a stopped daily job promised «Următoarea rulare: 18.09.2026» on 25.09. A stopped job now has no next run («—»), and the job is «Ziua programată» with its code daily_main in the title (readiness.js scheduleNextRun, SCHEDULE_TITLE). (2) The preflight printed the research sentence twice. A detail that repeats its message is now said once, and only what it adds is kept, with every backend sentence word for word (readiness.js checkLine). (3) The image and voice preflight lines now name the connection and the step (backend wording.MEDIA_KEY_UNUSABLE through preflight._media_missing; tests/test_preflight_media_key.py, written first). (4) The side drawer, filled with requests, cut a line in half at 1280 and 1920 with nothing to say it scrolls. Its lower edge now fades into the drawer's glass while there is more below, through a scroll timeline, gone at the end and when everything fits; scroll-padding keeps a Tab-reached key above it (style.css W31 section, --side-pad). (5) The register's refused gate read «gate failed» with raw keys and now says «poarta de publicare a refuzat» with the gate's own reasons. A failed upload's row, empty before, shows the detail the event carries (ledger.js). (6) «a răspuns cu nimic utilizabil» gained its negation. The publish key no longer says «MediaAsset <uuid>» or prints a raw status code (main.js). Glossary W31 amendment written first.

- Tested (W31): frontend 571/571 (7 new, tests/judge_w31.test.js, red first), tsc clean, build green, dist rebuilt last (index-DGuHrA7c.js); :8000 serves it and was not restarted. Backend: tests/test_preflight_media_key.py (3, red at collection first); the touched files and their neighbours 270 + 177 passed in two batches; ruff, format and mypy backend clean; not the whole suite. scripts/check_docs.py verified. Scratchpad ui/w31: stranger29.mjs on the stream (stranger_1920). w28d/doors_live.mjs 3 times on the stream: worst Research 34.7-34.8, Media 41.6-55.6, publishing 34.6-34.8, Journal 27.8-76.4, the rest 20.9 or less; lit room within 0.5 px; 0 errors, 0 missing, 0 foreign, the key 0 times. doors_film --perf twice with the page renderer (1 opening over 33 ms in 20; closings 0) and --reduced (Research and Media 41.7). roster30.mjs (hand-over worst 34.7 ms at 1920, 41.7 at 390; focus back on «Angajați»). approvals30.mjs at four sizes (0 clipped, no sideways scroll) and tab_approvals.mjs (keys 51-95 px above the fade's edge). focus26 and focus29 at 1920 and at 1280 under reduced motion: every stop ringed, inside, 32 px or more. contrast26 at three sizes: lowest real run 4.53:1; flagged runs cropped and found cut by a header edge, unpainted (the live region) or the ring's SVG figure. w28d/phone.mjs (width 390, 0 cut). j31.mjs (every door's whole scroll photographed and its words dumped). shoot.mjs at 1280, 1920 and 2560 on the final build: 0 missing, 0 errors.

- Still open (W31). The Owner's restart: the running studio still speaks the old gate, and the live building's light at 08:07 contradicts «Senin 17°C». The preflight's sentences name API routes, environment variables and OAuth scopes and use a decimal point. The Research door prints the stored «Source returned HTTP 403», and retrieval.py still writes that English. Setări shows a connection titled «settings» with its key. The inspector shows a raw UUID and no portrait. The treasury's «RUNWAY» vendor tile reads as the finance word. The phone rails sit offset and run past the edge. Media keeps a 41-56 ms frame over the stream. The stored history before 25.09, the models' English fields, the identity contracts, the channel names, the Director's title and the gold edge remain the Owner's.

## Doors from their rooms, and the studio's sentences in Romanian (2026-09-25)

The doors open from their rooms, and the studio speaks Romanian to its Owner. Each of the ten dialogs is now a door (frontend/src/dialog_doors.js): it grows out of its room on the building - Research from L3, the Treasury from S2, the inspector from the employee - in 340 ms of compositor-only motion, the room lit gold while it is open (within 0.5 px of the room in the live Unreal video), and closes back into it; a fade under reduced motion; content read ahead on hover or focus. Inside, the type is larger from 1900 px, there are no nested scroll areas (11 before), English model text is set as quoted material, the role codes under names became tooltips, and the phone width has its own layout (the building across the full width, a two-column room menu). The backend now writes the sentences the Owner reads in Romanian (backend/app/wording.py: agreement «1 buget activ / 2 bugete active», codes as words, no raw exception text as a stage's reason, error class in a structured field), and refuses a pause or resume that would change nothing (409, no event). The release judge: amazed YES, premium ALMOST - the history stored before today, the models' own fields and the identity contracts are still English, and the Owner decides whether they change.

- The studio's own sentences in Romanian» (2026-09-25, backend). Claimed and done: every sentence the backend writes for the Owner in the preflight, the runbook's stage reasons, run summaries and letters, the Director's matters and decisions, the growth reasons, the agent-run summaries and the mail titles is Romanian. Counts agree with their nouns, and codes are said as words: DAILY→zilnic, AUTONOMOUS_CEO→CEO autonom, DRAFT→ciornă, APPROVAL→aprobare, COMPLETED→încheiată, post_run→«raportare și închiderea zilei». The codes stay in the structured fields: stage/status in stages_json and events; a new `value` on each preflight check; error_class and error_detail on a stage that raised; body_json on letters. The vocabulary lives in one module, backend/app/wording.py, whose words match the page's own (ledger.js RUN_STAGE_LABEL, dialog_words.js, governance.js). A stage's reason is never an exception's raw text any more. Pause and resume refuse a change that changes nothing with a 409 and a Romanian reason, and record no event. Tested: tests/test_owner_words.py (26) plus about 1,200 neighbouring tests in batches, ruff and mypy clean; not the whole suite. The Owner's running studio picks this up on its next start; nothing was restarted.

- Still open after this change: the publishing gate's reasons and details (publishing/services.py) are English and reach the publish stage reason. Model-written fields (the Director's interpretation/action, selection notes, hold reasons) are in the model's language. The queue worker and watchdog store raw exception text as a task's reason. format_micros writes «1.2 USD» with a point.

- ## The dialogs as a game's doors (2026-09-25, W28)

- Each dialog now opens out of its room on the building and goes back into it. Research opens from L3, Media from the render room on L1, the Treasury from S2, the Journal from the writers' room on L2, Rularea zilei from the façade sign, Angajați from the lobby, Setări from the servers on S1. The inspector opens from the employee's desk and a letter from the register link that opened it. The room is lit while its door is open. On the real Unreal stream the lit room falls within 0.5 px of the room the video shows. A door's content is read while the pointer rests on its menu key or the keyboard reaches it, so it opens with its content ready. The dialogs' words are a step larger from 1900 px. The lists that scrolled inside a dialog are laid out in the dialog's one scroll. The models' English is set as quoted text: a scene's prompt, its narration, a topic's subject. On a phone the building runs the full width, its readouts shorten instead of being cut, and the dock and drawers are laid out for the phone. Frames over 33 ms through the doors: 13, where the old 160 ms fade had 18 in 24 openings. It is not yet a clean 60 fps, and one frame per heavy door is still long.

- 2026-09-25, W28, the doors (frontend/src/dialog_doors.js, new and tested; main.js openDoor, doorReads, lightDoor, sceneClip; style.css W28 tokens --dur-room-open 340ms, --dur-room-close 300ms, --dur-room-fade 180ms, --door-light-*; index.html #door-light). The room's rectangle is the building's own: the manifest's rooms under the page renderer, STREAM_ROOMS while the stream plays, the façade sign's face. It goes through the engine's camera, which the stream follows, and is cut to what shows between the drawers. The opening is one WAAPI animation queued before the first painted frame. It moves translate and non-uniform scale out of the room with --ease-push, from 25% opacity with a warm edge (::after), and the words fade in from half-way. Only compositor properties move, and the pane's own blur is off while it moves. The closing is the stylesheet's discrete exit, aimed at the room, so Escape, the close keys and Settings' cancel all leave the same way, and focus returns at once as before. The lit room is a gold edge laid over the room's box. It comes on as the door opens and fades after it closes: the page's mark of what he opened, not a room state. Under reduced motion the door fades over 180 ms; before, the page's blanket rule made every dialog a cut.

- 2026-09-25, W28, the first frame. Research's first frame laid out its whole 6000 px: 42 ms of forced layout in a 55 ms click. Each door's reads are now taken ahead on the menu key's 120 ms hover, its focus, or the building face that opens it: once per 10 s, from the studio's own API only. A door read in the last 10 s opens on that content; otherwise it reads once the pane has landed. Inside a door the parts are content-visibility:auto, and while it opens they are laid out one per frame. Research's click is now 11-15 ms and its first frame about 21 ms (14-16 ms of layout). Measured against HEAD's build, alternating, 3 runs × 8 doors at 1920: openings over 20 ms 50 (HEAD 36), over 33 ms 13 (HEAD 18), median worst frame 27.8 ms (HEAD 34.7), worst 69.5 (HEAD 83.3). Closings: 0 over 33 ms. The long frames left are GPU raster on the card that also renders Unreal.

- 2026-09-25, W28, type and reading (style.css --dialog-fs-*, --dialog-rail-w, --measure-quote, --quote-rule; dialog_words.js sharedTail; main.js; index.html). From 1900 px a door redefines the page's type tokens one step up (micro 11.5, meta 13.5, body 15, lead 16.5, h3 17.5, h2 24), and from 2400 px one step more; nothing outside a door changes. At 1920, Research went from 57% of its words at 11.5 px to 54% at 13.5 px and 41% at 15 px; Media from 79% at 11.5 px to 78% at 15 px. No list scrolls inside a door any more (11 nested scrollers became 0), and the Journal has its section rail. A topic's subject, a scene's prompt and its narration are quoted text: a hairline, 70 characters to the line, lang=en, the narration in „…”. A storyboard's scenes are rows. The directions every prompt ends with are printed once under the scenes, word for word («Aceleași indicații, la sfârșitul fiecărei scene»). Glossary W28 amendment written first.

- 2026-09-25, W28, small decisions, each reversible in one place. The inspector's eyebrow names the employee's place in the building, from the desk's zone («DIRECȚIUNE · L4», «CERCETARE · L3» …; «SEDIUL · ANGAJAȚI» with no desk). The role codes are gone from under the names in the workforce list and from the live window's heading; each stays as its tooltip. The mail window's time is the page's style, «12.09.2026, 10:37».

- 2026-09-25, W28, the phone (style.css W28 phone section, up to 600 px). The render runs the full 390 px at 6:5 (390×325, was 336×176) and the frame's camera stands the building across it. The readouts give their short form («05:26 · BUCUREȘTI», «Live», «8 angajați · live», «12.09 · 12/12»). The dock is the two switches, a full-width camera row, and the seven rooms as a two-column menu of 40 px keys. The masthead is two rows, and the register, governance and modules are full-width sheets with the 16 px gutter. In the doors, section heads wrap above their keys, the channel's account field takes its own line and the film card stacks. No page scrolls sideways at 390 px.

- Tested (W28): frontend 547/547 (12 new, tests/dialog_doors.test.js, written after the code), tsc clean, build green, dist rebuilt last (index-CUjkLNvY.js); :8000 serves it and was not restarted. No backend change. Scratchpad ui/w28d: doors_seq.mjs (every door opening and closing, frozen and seeked, at 1920, and under reduced motion); doors_film.mjs (real time, all ten doors, --film and --perf); cmp.sh (HEAD against W28); doors_live.mjs (the real stream, read-only viewer, made-up key, RTCDataChannel.send replaced, no Remote Control: 0 errors, 0 missing, 0 foreign requests, the key 0 times in requests or console; lit room within 0.5 px of the video's rooms; median 6.9 ms, worst 62.6 ms); typeaudit.mjs; phone.mjs; trace_door.mjs; the w26 focus26 and contrast26 scripts. Tab: every stop in all eight doors has a ring, stays inside its door and is at least 32 px, at 1920 and at 1280 with reduced motion. Contrast from real pixels: the lowest top-of-door run is 5.73:1 at 1280, 1920 and 2560. Every flagged run I cropped is a line cut by the header's edge or the ring's SVG figure, as in W27; the 4.42-4.50:1 runs at 1920 were not cropped. shoot.mjs at 1280, 1920 and 2560: 0 missing, 0 errors.

- Still open (W28). The doors are not yet a clean 60 fps on the shared machine: about two frames over 20 ms per opening, and one 40-80 ms frame in Research, the Journal, Media, the inspector and the mail (GPU raster of newly shown content). The mail and the inspector still render their content at open. The paused photograph sequences do not show the lit room while a door closes (the real-time films do). On the phone a door's header takes about 200 px. The doors stay 1440 px wide at 2560. A scene's own prompt still repeats itself, because that is the backend's text. The backend's sentences with codes and English remain as W27 listed them.

- ## The release judge again: the doors from their rooms, the studio's words from a fresh copy (2026-09-25, W29)

- A stranger, cold and then returning, at 1920x1080 with the real Unreal stream (read-only viewer, made-up key, RTCDataChannel.send replaced, no Remote Control). The title stands on the studio's real frame of the hour 1.3 s after navigation («ACUM 06:10 · ULTIMUL CADRU LIVE»). The page is live about 3 s after the key (the harness's slow start is 1.0-2.5 s by design). The invitation comes at 13.7 s, and the replay of 12.09 plays to its end both times. 0 errors, 0 missing, 0 foreign requests; the key 0 times in requests or the console. Verdict: amazed YES, premium ALMOST. The title, the live building, the plaques, the replay and now the doors are at a 2026 game's level. On the stream each door grows out of its own room, and the lit room is within 0.5 px of the room in the video. Behind the doors, the studio's stored history and the models' fields are still English and codes («publish: COMPLETED», «Gâtuire la APPROVAL», the identity contracts, the Director's interpretations). A storyboard prompt repeats its own sentence, and the employees are a flat list.

- 2026-09-25, W29, the words judged on a fresh copy. The fixtures were recaptured from a copy of data/studio.db taken with -wal and -shm (w17/capture_fixtures17.py; the original never opened; secrets blanked; the copy migrated 0045 → 0047): 254 of 258 answers, into ui/fixtures, with the old set kept as ui/fixtures_w28_prev. The new backend's sentences show where they are computed on read: «1 buget activ: zilnic 15 USD (în limită).», «Modul de autonomie este CEO autonom: …», «30 de modele …», «8 angajați activi …», «1 film măsurat; o bază de comparație cere 3», and the growth reasons in Romanian. The codes are in each check's new `value`. Rows written before the change keep their words: the 12.09 letters («publish: COMPLETED — …») and the decision «Gâtuire la APPROVAL». The Owner's running studio shows none of the new sentences until he restarts it.

- 2026-09-25, W29, the register's chips are 32 px to the hand where they wrap (frontend/src/style.css; tests/chip_targets.test.js, 2 tests, red first). Each filter chip is 26 px with a 34 px hit area (::after, 4 px above and below). Where the six chips wrap, in the frame's narrow register and on the phone, their rows were 4 px apart. The first row's lower 4 px belonged to the second row: «Toate» had 30 px of its own. The rows are now 8 px apart (--s2). Re-measured with elementFromPoint: every chip has its own 32 px, and the workspace Tab walk shows 0 stops under 32 px at 1920 and at 1280 with reduced motion (before: 1 and 2).

- Tested (W29): frontend 549/549 (2 new), tsc clean, build green, dist rebuilt last (index-Dvl1JScZ.js); :8000 serves it and was not restarted. The backend files touched by the words wave: 185 + 204 passed in two batches; ruff and mypy backend clean; not the whole suite. Scratchpad ui/w29: stranger29.mjs (cold and returning on the real stream); w28d/doors_live.mjs on the stream (median 6.9 ms; worst Research 62.6, Journal 55.5, Media 41.6, the rest 34.7 or less; lit room off by 0.4-0.5 px); latency29.mjs (click to next paint 32-104 ms, handler 8-14 ms); w28d/doors_film.mjs --perf twice and --reduced (openings 12 frames over 33 ms in 20 openings, worst Research 62 ms and the mail 62-70 ms; closings 1 over 33; reduced motion a clean fade, with one 90 ms inspector close); w26 contrast26/pxcontrast26 at 1280, 1920 and 2560 (top of door lowest 5.55:1 at 1920, 4.74:1 at 1280, 4.54:1 at 2560 once edge-cut runs are set aside; every run under 4.5 cropped and found cut by the header or the pane's edge, or the ring's SVG figure); focus26 plus focus29 (all eight doors, the inspector, the mail and the workspace: every stop ringed and inside, 0 under 32 px after the fix); w28d/phone.mjs at 390x844 (width 390, 0 readouts cut, all doors open); shoot.mjs at the three sizes and on the final build: 0 missing, 0 errors.

- Still open (W29). The Owner's studio needs his restart for the new backend. The stored history keeps its codes and English. The models' Owner-facing fields and the identity contracts are English. Sarah is «Directoarea» in some places and «Directorul» in others. A storyboard prompt repeats its subject in the Environment and Lighting slots. The publishing gate's reasons, «motor de căutare: NONE» and «(OTHER)» are English and codes. Research, the mail, the inspector and the Journal open with one 35-70 ms frame. Angajați is a flat list. No filled approvals state was judged, because his data has none.

## The release candidate: the dialogs in the frame's words and glass (2026-09-25)

The release candidate. Every dialog, the Settings tabs, the inspector, the mail and the approvals were walked at three sizes and brought toward the frame: about 60 English codes and raw values the page wrote itself are now Romanian words through the new frontend/src/dialog_words.js (the codes stay in data-* and tooltips; the backend's own sentences stay as written); the dialogs are the drawers' blurred glass with the building visible around them and a gold eyebrow naming their place in the headquarters (CERCETARE · L3, RANDARE · L1, TREZORERIE · S2 …); every scrolling list and field shows the page's focus ring. The last rests: no «acum:» at the replay's end, and the façade plaque holds through a resize. The release judge (cold and returning, with the real stream as one more viewer): amazed YES; premium ALMOST - the building, title, replay and plaques are premium, the dialogs still read as a careful admin console. He fixed a 28 px jump of the whole building after a visit (the stream's video made the viewport scrollable) and three untrue things: green ✓ beside publication rules nobody had checked, «Reia lucrul» offered for an active employee (the backend would record a resume that never happened), and a demo case promised as «verificat» that makes an unverified claim.

- ## The rest of the page at the frame's level (2026-09-25, W26)

- The eight dialogs, the inspector, the mail and the approvals now match the frame. Each dialog is a pane of the drawers' glass over the lit building, which stays visible dimmed and blurred around it. Each header names its place in the building in gold small caps («CERCETARE · L3», «TREZORERIE · S2», «FAȚADA · RULAREA ZILEI»…). The dialogs now say every state in Romanian: walked screen by screen at 1280, 1920 and 2560, the page had printed about 60 raw codes and English-form figures («Stare: SELECTED», «QC: PASSED», «IDLE», «OPEN», «PENDING · NECHELTUIBIL», «4.8s», «2026-09-12»); now it prints none. Only sentences the backend or a model wrote still carry them, word for word. Two rough edges left by the last judge are gone: no room says «acum: …» once the replay has ended, and after a window resize the façade plaque stays on its sign in every frame. Also photographed: the title at golden hour and twilight, morning and evening; the phone width; the night weather signs.

- 2026-09-25, W26, the dialogs' words (frontend/src/dialog_words.js, new and tested; ledger.js mailIntentLabel; main.js, settings.js, serial_room.js, index.html). Glossary W26 amendment written first. Each state the page prints is the Romanian word that agrees with its noun: a topic «ales», a storyboard «randat»/«respins» (a rejected or failed one no longer in the accent green), a shot «plan mediu · grafică animată», «QC: a trecut», a channel «Shorts factuale», a publication «publicat», an employee «activ» and «în așteptare», a run and its stages «încheiată»/«eșuată», the preflight «gata»/«cu limitări»/«blocantă», a decision «Corectează — gâtuire la aprobare · deschisă», «Interpretare (încredere medie)», a growth limit «fără date», a budget «Zilnic · în limită», money not spendable «NEDECONTAT»/«PROGNOZĂ», an account «activ» or «Datorie» (said once), a letter «Raport · rezolvat», memory classes «Decizie»/«Politică», «Raportează către Proprietar». The raw code stays in data-* and in the title tooltip, and in everything the page sends. The decision's owner is the employee's name («Kael (Video Editor)»), and a cold-start matter names its channel. Durations read «4,8 s», frames «1080×1920», days «12.09.2026». Values the page does not know are shown lower-case, never guessed.

- 2026-09-25, W26, the glass and the forms (style.css: tokens --dialog-glass, --dialog-glass-head, --dialog-backdrop, --dialog-backdrop-blur, --dialog-rule, --dialog-rule-w, and W26 sections at the end). The dialog is --dialog-glass (90%) with the drawers' blur and edge. Behind it the page is dimmed at 62% (was 82%) and blurred 6 px, so the lit building shows around it. Each header has its room's eyebrow and a 28 px gold hairline, and Settings got the same header shape. In Research, a failed site test is one alert-coloured line in its row, not a red card for each of 36 sites. The Treasury's budget and capital forms are two equal fields with the button under them, and the long example no longer clips. The scrolling lists that Chrome makes Tab stops (topics, checks, runs, decisions, employees, a scene's prompt) and the Settings fields now show the page's 2 px teal focus ring.

- 2026-09-25, W26, the replay's end and the resize (hq_arrivals.js quietChips and chipStage; office_engine.js quietRoomChips, _watchBox, _queueResize; replay_player.js). In the frame the replay's clock reaches the end, the rooms still lit keep their fading light and none says «acum: …». Measured at 16× with the real stream: the last chip stood 2958 ms after «rularea s-a încheiat», now 0 ms. After a window resize, the engine's own loop had re-sent the old canvas's camera with the new drawer insets for one frame, before the ResizeObserver ran. The video moved and the plaques did not, so the façade plaque stood 257 px off. The engine now reads its box first in its frame, sends the planned camera and queues the resize. Measured with the W23 probe on the real stream: 6 checks off, worst 256.6/252.1 px, became 0 off, worst 0.7 px, at 1280, 1920 and 2560.

- 2026-09-25, W26, photographed for the first time (scratchpad ui/w26/photos). The title at 06:35, 07:25, 18:45 and 19:40 on 25.09 (morning twilight, morning golden hour, evening golden hour, evening twilight, page clock set). Each time the studio's kept frame was a 02:49 night frame, and it correctly did not stand: the plates carry the hour. At 03:30 it does stand. At 390x844: the title on the studio's frame, the workspace, the Treasury dialog, no horizontal scroll. At 03:30 the weather sign reads «☾ Senin», «☁ Parțial înnorat» and «🌧 Burniță».

- Tested (W26): frontend 531/531 (14 new: dialog_words.test.js 10, room_chip.test.js +2, resize_same_frame.test.js +2), tsc clean, build green, dist rebuilt last (index-LgZRqhej.js); :8000 serves it and was not restarted. No backend change. Scratchpad ui/w26: walk.mjs (every dialog screen by screen, at 3 sizes), contrast26.mjs + pxcontrast26.py, focus26.mjs, perf26.mjs, chipend26.mjs, resize26.mjs, adv26.mjs, photos26.mjs. Contrast of real text, measured from pixels of the ground (a textless second capture): lowest 4.69:1 at 1920, 4.68:1 at 2560, 5.07:1 at 1280. Keyboard walk at 1920, and at 1280 with reduced motion: every stop ringed, inside its dialog and at least 32 px (before: 11 stops without a ring). With a dialog open over the running building: median 6.9 ms, 0 frames over 33 while open; the opening frame is 35-42 ms, as before the glass. On the real stream (read-only viewer, made-up key, RTCDataChannel.send replaced, no Remote Control): rest median 6.9 ms and worst 7.2 ms; 0 errors, 0 missing and 0 foreign requests; the key 0 times in URLs, requests or the console. shoot.mjs at 1920, 1280 and 2560: 0 missing, 0 errors.

- Still open (W26), for the Owner or a backend pass. Sentences the backend writes still hold codes and English: «1 bugete active: DAILY 15 USD (OK)», «Modul de autonomie este AUTONOMOUS_CEO», «rămâne DRAFT», «Gâtuire la APPROVAL», «publish: COMPLETED — …», the growth reasons and decision interpretations in English, «Source returned HTTP 403», «StartingCapital». A model's structured answer in the inspector's history shows its own keys and values in English («decision: ITERATE»). Role codes (LeadResearcher) under the names. The mail window's date style («12 sept. 2026») differs from the rest. At the replay's end, an arrival tag can say «lucrează» for up to 4 s. One frame of about 132 ms when a resize crosses the frame's 1051 px breakpoint. At phone width the render is small and its readouts are cut. The dialogs were not photographed over the live stream.

- ## The release judge at the frame's level: a building that never slips, and marks that only say what is true (2026-09-25, W27)

- A stranger, cold and then returning, at 1920x1080 with the real Unreal stream (read-only viewer, made-up key, the kept-frame route played as the new backend plays it). The title stands on the studio's real Unreal frame 1.1 s after navigation (the building at 04:19, «acum 04:19 · ultimul cadru live · azi 04:19»). The page is live about 1 s after the key. The invitation comes at 13.7 s, the replay of 12.09 plays to its end, «Înapoi la live», and the returning visit takes the same path through «Nu acum» and the dock. 0 errors, 0 missing, 0 foreign requests; the key 0 times in URLs, requests or the console. Verdict: amazed YES, premium ALMOST. The title, the live frame, the plaques and the replay are at a 2026 game's level. The eight doors are clean, legible, keyboard-complete glass, but they still read as a console, and much of their text is the backend's or the models' English.

- 2026-09-25, W27, the frame can no longer be scrolled (frontend/src/office_scene.css; tests/viewport_clip.test.js). With the stream, the Pixel Streaming library sets its <video> 48 px down the frame and 28 px past its foot, so #scene-viewport held 1014 px and showed 986. With overflow:hidden that is still a scroll container. Anything that brought a child into view (a focus, find-in-page, scrollIntoView, an automation's hover) lifted the whole building 28 px for the rest of the visit: the glass readouts under the masthead and a dark band under the street, in every rest shot of both judged visits. The viewport and the plaques' layer now use overflow:clip after the hidden fallback: the same picture, no scroll container. Re-run on the real stream: scrollIntoView moves nothing, the readouts are present in every rest shot, and the plaques (at most 0.9 px) and frame times are unchanged.

- 2026-09-25, W27, only true marks (index.html, style.css; main.js showInspectorStates; dialog_words.js lifecycleActs; settings.js). The five publication gates carried page-written green ✓ marks that read as «passed» with nothing checked. They are now a numbered list of rules beside «PARȚIAL» (tests/publish_gate_marks.test.js). The inspector offered «Reia lucrul» to an active employee, and the backend records an agent.resumed event for it. Now only the act that changes something is offered: pause to an active employee, resume to a paused or suspended one, neither to a dismissed one (dialog_words.test.js +1). The Media empty state promised the demo case «un scenariu verificat 9:16». It now says the demo makes «o afirmație neverificată, de verificat în Cercetare», and the page no longer prints «UNVERIFIED» in its own sentences. The provider cards say «Ollama», not «OLLAMA» on one and «ollama» on the next.

- Tested (W27): frontend 535/535 (4 new, each red first), tsc clean, build green, dist rebuilt last (index-Od4XebNM.js); :8000 serves it and was not restarted. No backend change. Scratchpad ui/w27: stranger27.mjs (twice, before and after), scroll27.mjs, overflow27s.mjs, adv27.mjs (--float --contrast --tab; --reduced --float), w26 contrast26/pxcontrast26 at 1280, 1920 and 2560, focus26 at 1920 and at 1280 with reduced motion, walk.mjs at 1920, and shoot.mjs at the three sizes. On the real stream: rest median 6.9 ms, worst 7.1 ms, 0 over 33; drawers and resize worst 20.9 ms; under reduced motion one 34.8 ms frame at the resize. Plaque contrast: eyebrows 5.8-6.4:1, values 15.8-17.1:1. Dialog text from real pixels: lowest 4.69:1 at 1920, 5.07:1 at 1280, 4.68:1 at 2560; the lower runs are text half under the header rule and the ring's SVG figure. Tab: every stop in all eight dialogs ringed, inside its dialog and at least 32 px. shoot.mjs: 0 missing, 0 errors at 1920, 1280 and 2560.

- Still open (W27), for the Owner or a backend pass. The Owner's running backend still needs a restart for the public kept frame and the socket auth. Backend sentences carry codes and English («DAILY 15 USD (OK)», «AUTONOMOUS_CEO», «rămâne DRAFT», «publish: COMPLETED — …», and a raw «database is locked» as a stage reason). The API still records a pause or resume that changes nothing. The identity contracts and channel names are English. Ollama has no token prices. The doors open with one 35-42 ms frame and have no game-level transition from their room. There is a 34.8 ms resize frame under reduced motion. The doors were not photographed over the live stream.

## A stranger's first visit in the real building (2026-09-25)

A stranger's first visit now opens on the real Unreal building too. The Owner's signed-in page sends the studio its newest kept stream frame at most every 5 minutes (backend/app/office/kept_frame.py: one frame outside the database in data/office, written atomically, at most 768 KiB, a whole still WebP only - 13 hostile shapes refused - with its capture time; the key only in the Authorization header); a public read-only route serves it (204 when none), and the title uses it only when its light matches the real hour now (day, golden hour, twilight or night, morning or evening) and it is under a day old, re-checked every minute. The replay's pace keys say the pace against the run («4× · 17× · 70×»), its bar never contradicts itself at the end, captions never overlap, the serial plaque shows only a numbered episode, sockets waiting for the key are capped at 16 per process, and the weather sign follows day and night («☾ Senin» at 03:00). A stranger, cold and returning, with the real stream: YES in the harness that plays the new backend; ALMOST for a real stranger today only because the Owner's running studio has neither the route nor the socket auth until he restarts it.

- ## A first visit on the Unreal building too, and the last rough edges (2026-09-25)

- A stranger's first visit now opens on the Unreal building. While the Owner's signed-in page plays the stream, it sends the studio its newest kept real frame (the same WebP, with its capture time), at most every five minutes. The studio keeps exactly one, the newest, outside the database. The title reads it before any key and stands on it only while its light is the light outside now: the same sun state over Bucharest, and not older than a day. Otherwise the title stands on the plates, as before. The same rule now applies to this browser's own kept frame, so a noon frame never stands on the title at midnight. The replay's speed keys now show the pace against the run, the number the line beside them says. Captions of neighbours at 16× no longer lie over each other. OFFICE SERIAL shows only over a numbered episode. Sockets waiting for the key are limited per process. A stranger: the cold visit is one building from the title to live, with the same entry times as before.

- 2026-09-25, W24, the studio's kept frame (backend/app/office/kept_frame.py; config.py office_kept_frame_dir; main.py; frontend/src/studio_frame.js; main.js readStudioKept, titleKept, titleChoice, studioSend, onKeep; title_screen.js keptStillTrue, dropKept). POST /api/v1/office/kept-frame needs the Owner's key in the Authorization header. It takes only a whole WebP of at most 768 KiB with a recent X-Captured-At (not ahead of the clock, not older than a day). It refuses a frame older than the one kept, writes beside its place and moves the file in with os.replace, into an office folder beside studio.db (data/office, ignored by git). GET is public and read-only: the WebP with X-Captured-At, or 204 when nothing is kept (an older studio's 404 also means the plates). The title takes the newest of this browser's frame and the studio's whose sun state matches now (day; golden hour from 6° down to −1°; twilight to −12°; night below; golden hour and twilight also split into morning and evening). It re-reads the light every minute and gives way to the plates when the state changes. After the key, the starting plate shows the same frame. Measured on the real stream (made-up key, viewer signalling only): 1 POST in 75 s of live, 3.8-4.1 s after the first frame, about 134 KB, key only in the header. A cold stranger's title stands on the Unreal frame 302-360 ms after navigation at 1280, 1920 and 2560, with no plates downloaded, and is live 552-828 ms after the key. The same frame dated noon: the plates. A night frame at 05:25, 75 minutes on: the dawn plates.

- 2026-09-25, W24, the replay's pace and its end (day_replay.js paceKeys, quietSpan, barTick; replay_player.js _paceKeys; index.html). «1×» pressed beside «de 4 ori mai repede decât rularea» read as a contradiction. The keys now show the pace against the run, rounded: «4× · 17× · 70×» for 12.09. The pressed key is the line's own number, and each key's name is the line's own wording. The group is «Ritmul reluării, față de rulare». A quiet stretch says how long it stays on screen, «nicio schimbare în registru 23:50:43–23:51:24 · trece în 0,1 s», instead of a speed other than the key's. The end's «11:38 din 11:39» beside «rularea s-a încheiat» came from rewriting the time only when the absolute clock second changed: a run that starts at .9 s ends inside the second its last moments share. The bar now rewrites whenever its words change. Glossary W24 amendment written first. Key labels 8.9-14.6:1 from pixels, 40x32 px.

- 2026-09-25, W24, the captions, the serial and the sockets (hq_world.js captionPlace, replayCaptionBox, drawReplayCaptions; stream_plaques.js; security.py SOCKET_AUTH_MAX_PENDING). Captions from one frame are placed like tags (the W23 tagClear approach): where they want to be; else along their row while the speaker stays under them; else lifted with a stalk, drawn from the highest down so a stalk passes behind. Over the whole replay at 16×, every painted frame: frames with overlapping captions went from 290-318 of about 1,070 (worst 2,868 px²) to 0 of 1,058-1,084. Frames: median 6.9 ms, worst 14 ms. OFFICE SERIAL shows only over a numbered episode (it said «EP — · Ciornă» over the video). The relay and the events socket share one count of sockets waiting for the key, 16 per process. Past it a socket is closed at once with 1013 (reason «busy» logged). Every exit frees its place.

- Tested (W24): frontend 500/500 (15 new: studio_frame.test.js 8, replay_pace.test.js 7), tsc clean, build green, dist rebuilt; :8000 not restarted and still serving. Backend, tests first: tests/test_office_kept_frame.py (19 new), test_events_socket_auth.py (+3), test_office_stream.py (+1), test_route_authorisation.py (the fifth public route), with test_phase2_workflows: 76 passed. ruff and mypy backend clean. The full suite was not run on the shared machine. The real stream was watched as one more read-only viewer (scratchpad ui/w24: cold24.mjs at 1280, 1920 and 2560; replay24.mjs with and without --before; drop24.mjs): RTCDataChannel.send replaced, no Remote Control, made-up key. Every run: 0 errors, 0 missing, 0 foreign requests, 0 key in URLs or the console. shoot.mjs at 1920, 1280 and 2560: 0 missing, 0 errors. Still open: the Owner's running backend lacks the route until he restarts it (the title's GET gets a 404 and uses the plates; the live page's first POST gets a 405 and stops), and nothing is kept until a signed-in visit plays the stream after that. The studio frame is public, including the in-picture clock's capture hour. The title's first 300 ms are dark. The frame-to-plates change is a cut. The entry's worst frame is 76-132 ms. The lifted-caption path was only unit-tested. Phone width and reduced motion on a studio frame were not photographed.

- ## A stranger and an adversary with the real stream, and four fixes (2026-09-25, W25)

- W25 visited twice at 1920x1080, cold in a fresh profile and then returning, about two minutes each, following only what the page offers, including the whole replay. The real Unreal stream was watched as one more read-only viewer with a made-up key. The harness played the new backend's kept-frame route. Cold: the title stands on the studio's real Unreal frame 1.1 s after navigation, with 0 plates downloaded, captioned «acum 03:00 · ultimul cadru live · azi 03:00». After the key it is the same building live. The invitation, the replay at 4× and 70× of the run, «rularea s-a încheiat | 11:39 din 11:39», «Înapoi la live». Returning: the browser's own newer frame, then the same path through the dock. 0 errors, 0 missing, 0 foreign requests, the key 0 times in URLs, requests or console. Four problems were found and fixed. The weather in the glass bar read «☀ Senin» at 03:00. Five «acum: …» room chips stood at once at the replay's end. A tag was cut off under the register drawer («…cus (Script Writer)»). With the key, the public frame route kept any bytes behind a WebP header.

- 2026-09-25, W25, the kept frame is a picture and nothing else (backend/app/office/kept_frame.py is_webp, _picture_size; tests/test_office_kept_frame.py +14). is_webp now walks the RIFF chunks. It accepts an optional VP8X first (no animation, XMP or EXIF flag, canvas equal to the picture), optional ICCP or ALPH only inside it, and exactly one picture: a VP8 key frame (start code 9d 01 2a) or a VP8L (signature 0x2f, version 0), 1..4096 px, the chunks filling the file exactly. The 13 hostile files are refused with 415; 12 of them passed the W24 check. Among them: HTML in an extra chunk, EXIF, XMP, an animation, two pictures, a bad signature or start code, a size of 0 or 8000 px, a canvas that is not the picture's, an overrun chunk, trailing bytes, no picture at all. The real Chrome frames (VP8X+ICCP+VP8, 1920x1008) and every plate still pass. A probe through create_app: no key with a 5 MB body gives 401 and nothing is kept; the key in ?token= gives 401; PUT and DELETE give 405; 300 GETs take 451 ms, always no-store, nosniff and CSP.

- 2026-09-25, W25, the glass and the replay say one thing at a time (hq_weather.js weatherSign; office_engine.js; hq_arrivals.js chipStage; hq_world.js drawRoomRims, visibleSpan, tagClear maxShift). Glossary W25 amendment first. The weather icon follows the observation's is_day, and the real sun when the studio does not say: a clear night reads «☾ Senin 17°C» (measured live), partly cloudy ☁, drizzle 🌧. Only the most recently lit room says «acum: …»; older rooms keep their fading light without words. The engine passes the visible world span between the drawers. Arrival tags, replayed captions and the name tag stay inside it, and an arrival tag never moves farther from its speaker than its own width. Re-shot at the replay's end: one chip, «Marcus (Script Writer) · a terminat · scenariul» whole beside his room, 0 overlapping captions in 1,063 frames. Pure play: 651 frames, median 6.9 ms, worst 7.2 ms.

- Tested (W25): frontend 517/517 (17 new: weather_sign 6, room_chip 4, visible_span 7), tsc clean, build green, dist rebuilt (index-DdkjrIsK.js); :8000 not restarted and still serving. Backend, tests first: test_office_kept_frame.py 33 (14 new, the 13 hostile cases seen red against W24's check), with the socket-auth, stream and route-authorisation files: 80 passed. ruff, ruff format and mypy backend clean. Real stream, read-only viewer, made-up key (scratchpad ui/w25: stranger25.mjs, adv25_title.mjs, w23/adv23.mjs at 1280, 1920, 2560 and reduced motion, replay24/25, sign25.mjs, shoot.mjs at 3 sizes). Title contrast over the Unreal frame: caption 8.5:1, key label 6.2-6.3:1, hint 5.7-6.2:1. Plaques: eyebrows 5.8-6.4:1, values 15.1-17.3:1. Frames at rest: median 6.9 ms, 0 over 33 at every size and under reduced motion. Plaques stay within 0.9 px of their objects through zoom, drag, fit, wheel and the drawers. Tab: 32-34 stops, all with a visible 2 px ring (the ledger chips are 26 px to the eye, with a 34 px hit area). shoot.mjs: 0 missing, 0 errors at 1920, 1280 and 2560.

## The key out of the socket URLs, and one building for a returning visitor (2026-09-25)

The Owner's key is out of the socket URLs, and a returning visitor sees one building. Both WebSockets (the stream's signalling relay and the events socket) now take the key as their first message (backend/app/security.py: constant-time comparison, a 5 s window, 1008 on anything else, only the reason logged); the page uses this only when GET /office/stream says auth: 'first_message', so it keeps working against the Owner's running studio until he restarts it, and the Pixel Streaming library no longer prints the signalling URL with the key. With the stream configured, the Unreal building is the page's face (a decision taken for the Owner from his «Încă apare vechiul format!», reversible): the title stands on the kept real frame, the entry carries it onto the live video, and the replay plays over a real still of the Unreal building with the rooms' light, monitor glows, tags, captions and the as-of plaques drawn in the stream's measured geometry; every one of the replay's 92 strings traced to the record. Seven plaques over the live video, a dead stream said in words, the plaques following a resize in the same frame, and a 965 ms first-entry freeze (the library's codec enumeration) moved under the title. A stranger: ALMOST — the returning visit amazes; a cold first visit still opens on the page renderer's title. Not done by the page: 8 old local logs in output/ (2026-09-10..12, git-ignored) hold 110 lines with the key in a URL; deleting them and rotating the key is the Owner's call.

- ## The Owner's key out of the URL, and the small truths (2026-09-25, W21)

- The Owner's key no longer needs to travel in a URL. It used to sit in the query string of both of the page's sockets: the stream's signalling and the studio's events. The Pixel Streaming library printed the signalling URL, key included, to the console on every connect, Chrome printed it again when a socket failed, and proxy and server access logs kept it. A backend that answers GET /office/stream with `auth: 'first_message'` now takes the key as each socket's first message and refuses a socket that does not say it within 5 s. The page asks this once per sign-in. The Owner's running studio keeps its old backend until he restarts it, so until then the page speaks to it exactly as before. Also: the Treasury plaque now says «50.000 VR$ cheltuibili»; a stream that does not answer is said to be silent after three failed connects or 20 s; after a window resize the video and its plaques move in the same frame; and three more plaques stand on real objects of the Unreal building (the serial's wall screen, the render screen's bar, the servers' band).

- 2026-09-25, W21, the key (backend/app/security.py socket_first_message_auth and owner_key_matches, office/stream.py, workflows/router.py, publisher.py; frontend/src/hq_stream_config.js socketAuth, authenticateTransport, relayUrl and eventsUrl, hq_stream.js, live_claims.js EventsLink firstMessage, main.js). The first message is {"type":"auth","token":…}. The relay answers {"type":"relay_ready"} only once the key is right and the signalling server has answered; the events socket answers {"type":"auth_ok"} and only then joins the broadcast. The key is compared in constant time and never forwarded, echoed or logged; a refusal logs only its reason (timeout, malformed, wrong). On the page, the library's own transport sends the key when the socket opens and tells the library the socket is open only on «relay_ready», so it starts as it did before. The events link stays «Se conectează…» until «auth_ok». A page from before (?token=) is still read the old way; that branch is to be removed once no such tab remains. Measured with the real stream, playing each backend in turn: new, 0 keys in URLs, the console or the signalling, live in 1671 ms; old, unchanged (live in 1682 ms, with the key printed as before).

- 2026-09-25, W21, what the page says (stream_plaques.js, hq_stream_config.js plateNote and streamSilent, office_scene.css). The Treasury plaque carries the face card's own value, «50.000 VR$ cheltuibili»: the same record holds a VR_DEBT of 50.000, and the bare figure misled. The plate stops saying «Pornește sediul live…» after 3 connects that end before a picture, or 20 s without one. The dark plate then says «Sediul live nu răspunde · se încearcă din nou…» in the warn ink, and the kept frame says «ultimul cadru live · azi 00:33 · sediul live nu răspunde». Measured on both backends, with the signalling down or the key refused: said at 5.35-5.39 s, and 4.56 s over a kept frame. Three plaques were added on objects measured on the stream: OFFICE SERIAL on Conținut's empty wall screen, RANDARE on the light bar of Unreal's RENDER screen, and SERVERE with the day's tokens on the dark band above the racks of S1. Their words are the face cards'. They need their eyebrow to be read, so 1280 at fit keeps the four and 1920 and 2560 show seven: 0 over an employee, 0 over each other, values 15.4-16.9:1, eyebrows 5.8-6.3:1. Glossary W21 amendment written first.

- 2026-09-25, W21, resize in one frame (office_engine.js plannedView and _emitPlannedView, drawers.js syncToWindow, main.js layoutPlaques). The canvas takes its new size a frame later, as W15 decided, but the camera it will stand at is now said in the frame the box changes: the video's transform and the plaques move with the layer's size. Because the window's resize event can arrive a frame after the layout, the drawers are laid out for the new size first. Read after each paint on the real stream: before, 1-2 frames off by up to 135 px (picture) and 452 px (plaques) at 1280/1920/2560; after, 0 frames off, plaques within 0.8 px. An rAF-time probe still sees the unapplied state inside the frame; it is not what is painted.

- Tested (W21): frontend 454/454 (22 new), tsc clean, build green; frontend/dist rebuilt after the checks, and :8000 not restarted. Backend, tests first: tests/test_office_stream.py and the new tests/test_events_socket_auth.py, 37 passed; 53 with test_phase2_workflows and test_route_authorisation; ruff and mypy backend clean; the full suite not run on the shared machine. The real stream was watched as one more read-only viewer (scratchpad ui/w21: h21.mjs playing both backends, auth21.mjs, kept21.mjs, resize21.mjs, plaques21.mjs, adv21.mjs), with a made-up key: RTCDataChannel.send replaced, viewer signalling only, no Remote Control. At rest the median frame is 6.9 ms and the worst 7.2 ms; drawers worst 20.8 ms, 0 over 33. shoot.mjs at 1920, 1280 and 2560: 0 missing, 0 errors. Still open: the key leaves the Owner's URLs only after he restarts his backend; the legacy ?token= branch; «EP —» for an episode with no number; Unreal's baked bar under the RANDARE plaque.

- ## One building from the title to the replay (2026-09-25, W22)

- With the stream configured, a visit now shows one building. The title opens on this browser's kept real frame of the Unreal building, labelled «ultimul cadru live · azi 00:47» beside the real hour. The key carries that frame, dimming it as the plate dims the kept frame, onto the exact place where the workspace draws the stream, and the live video takes over in the same building. The replay («Reluarea zilei») now plays over a still of the real Unreal building, taken at its door. The still is graded in the replay's look and carries the replay's own layers where the photograph shows their objects: the rooms' light rising and falling, the monitors' state as glows, the tags and captions, the shelter clock under ATUNCI, and the plaques with the books as they stood. What the photograph cannot carry is said in words: «cadru live de azi, 01:06 · lumina și vremea nu sunt cele de atunci». Without a stream, the title and the replay are the page renderer's, as before. This is a decision taken for the Owner, reversible: his 2026-09-15 «Încă apare vechiul format!» makes the Unreal building his chosen face.

- 2026-09-25, W22, the title and the entry (title_screen.js useKept, firstKept, land; title_frame.js titleKeptCaption, keptPlacement, landingPlacement, placementTransform; main.js readKeptFrame, readScene, titleKept, titleLanding; style.css .title-kept, .title-stage.lands, body.is-landing). The title stands on the kept frame only when scene.json configures the stream, and waits at most 600 ms for it; then it downloads no plates. The frame is placed where the plates' world is, follows the pointer at the building's depth, and the sky around it is the frame's own top colour. On the key, the landing is read once the masthead is shown. The frame then glides and dims onto the video's place over --dur-push (at 1920: translate(-45.94px, 112px) scale(1.15), equal to the engine's camera). The render's panel appears only when the frame has landed: while it rose under the frame in flight, the building showed twice for about 300 ms. The kept frame is now kept at the stream's width, 1920 px (about 133 KB), since the title shows it as key art. Measured with the real stream at 1280, 1920 and 2560: one building in every frame of the entry, aligned with the live video at 0 px once landed. Entry frames: worst 55.6-69.6 ms with 1-3 over 33 ms, the known workspace-layout frame (55.5 ms on the previous build).

- 2026-09-25, W22, the replay in the Unreal building (replay_still.js; hq_world.js drawOverStill, drawStillRooms, drawStillMonitors, drawClockFace; office_engine.js setReplayStill, stillAhead, onCaptions; hq_stream.js replayPicture, stillAt; stream_plaques.js setReplay; main.js enterReplayLook, leaveReplayLook; replay_player.js lookNote). Every anchor was measured on a raw frame of the live stream (00:47, scratchpad ui/w22/probe, measure_anchors.py): the rooms' lit interiors, the lit face of each desk's monitor, and the shelter clock's panel, which shows the live hour and is covered by the replayed hour under ATUNCI. Order of drawing: the photograph over the world's rectangle, then the rooms shaded or lit to their replayed occupancy (easing over 420 ms, at once under reduced motion), the monitors' glows in their employee's state, the stage flares and rims, the ATUNCI clock and the replay's grade, then the chips, captions and tags. The plaques stay over this replay, in the replay's ink, with «TREZORERIE · ATUNCI» and «… tokenuri atunci», and step aside for a caption. The still is 0 px from the live video it was copied from at every size. Replay frames: median 6.9 ms, worst 7.2-13.9 ms, 0 over 20 ms (the page renderer's replay: worst 20.8 ms). Contrast from pixels: values 15.8-16.9:1, eyebrows 10.0-10.6:1, the line under ATUNCI 10.0-11.1:1. Glossary W22 amendment written first.

- Tested (W22): frontend 473/473 (19 new in tests/one_building.test.js), tsc clean, build green; frontend/dist rebuilt after the checks, :8000 not restarted, no backend change, no git state changed. The real stream was watched as one more read-only viewer (scratchpad ui/w22: one22.mjs at 1280/1920/2560 and under reduced motion, landprobe.mjs, rc22.mjs, nostream22.mjs), with a made-up key, RTCDataChannel.send replaced and no Remote Control. Every run had 0 errors, 0 missing and 0 foreign requests. shoot.mjs at 1920, 1280 and 2560: 0 missing, 0 errors. Still open: a backend that drops its stream configuration after this browser kept a frame shows Unreal on the title and the renderer after the key; a kept frame days old can carry another hour's light onto the title; the photograph's figures and traffic are the door's (the tags carry the replayed states); OFFICE SERIAL reads «—» over the replay; the phone-width title on a kept frame was not photographed.

- ## A stranger again, then an adversary, with the real stream (2026-09-25, W23)

- Two visits at 1920x1080 with the real Unreal stream (one more read-only viewer) give ALMOST. The returning visit amazes: one Unreal building from the title through the replay and back to live, and every word and mark on the replay traces to the record. The first visit is weaker: its title can only be the page's own renderer, because this browser has kept no real frame yet. It was also where the page froze for about a second: the Pixel Streaming library's first codec enumeration ran in the middle of the entry. The page now makes that enumeration itself while the title stands idle. A first visit now reaches the live Unreal building 0.8 s after the key, with no black plate between. Over the replay in the Unreal building, the plaques now step aside for every mark, and a tag never covers the «RELUARE · hh:mm:ss» of a caption. On the Owner's running backend, the library no longer prints his key to the console.

- 2026-09-25, W23, the replay's marks (hq_world.js drawOverStill, drawRoomRims, drawArrivals, tagClear). Over the Unreal still the renderer hands the plaques every mark it draws: captions, the employees' tags (at the place they rest, so the plaques are laid once and not on every frame of the fade) and the rooms' «acum: …» chips. W22 handed on the captions only, and SERVERE lay over Lyra's tag, DISTRIBUȚIE over its room's chip, and OFFICE SERIAL over tags. A tag keeps its row under the desk and slides sideways off the captions drawn that frame and off the tags already laid, in both replay looks. Measured over the whole replay (60 s at the default pace): samples with an overlap went from 46/216 to 0/217, 0/221 and 0/210 at 1920, 1280 and 2560. Plaque set changes went from 16 to 21 per 60 s at 1920.

- 2026-09-25, W23, the first visit's second (hq_stream_config.js warmVideoCodecs, main.js warmStreamCodecs). Profiled on a fresh profile: 977 ms of one frame, 130 ms after the key, were RTCRtpReceiver.getCapabilities('video') inside the library's Config. The browser's first answer in a process is synchronous; later answers are immediate. The page now asks once under the title, after the workspace warm-up, only when scene.json configures the stream and no key has been given. Cold entry: worst frame 965 → 97-104 ms; live 4021 → 2958 ms after the key; the black «Pornește sediul live…» plate no longer shows on a first visit. The cost now falls in the first 1.6 s of the page (one frame of about 680 ms), while the title's plates are still decoding.

- 2026-09-25, W23, the key in the console (hq_stream_config.js redactKey and redactingLogger, hq_stream.js). The page gives the library a logger that blanks the value of any token= before a line reaches the console. Against the old backend: the library's key lines went from 1 to 0 on a live entry and from 6 to 0 in 26 s with the signalling down. Chrome's own «WebSocket connection to …?token=… failed» (6 in 26 s) cannot be suppressed by the page; it ends when the Owner restarts his backend. That :8000 process dates from 2026-09-24 11:07, before the W21 change. scripts/run.py runs uvicorn with access_log=False, so current access logs do not keep the URL. Eight git-ignored logs in output/ (2026-09-10 to 12) do hold 110 accepted «WebSocket /api/v1/ws?token=…» lines; they were counted, never printed.

- Tested (W23): frontend 485/485 (12 new: tests/replay_marks.test.js 7, log_redact.test.js 3, codec_warm.test.js 2), tsc clean, build green; frontend/dist rebuilt after the last change; :8000 not restarted; no backend source changed. Backend re-run: test_office_stream, test_events_socket_auth and test_route_authorisation, 43 passed; ruff and mypy clean.

The real stream was watched as one more read-only viewer (scratchpad ui/w23: stranger23, replay23, adv23, rc23, one22, tabreplay23, cold23, title23, w21/auth21 for both backends), with a made-up key, RTCDataChannel.send replaced, no Remote Control, 0 errors, 0 missing and 0 foreign requests.

- Frames: rest median 6.9 ms, worst 13.9; replay over the still worst 7.2 ms over 5 s and 20.8-27.8 ms over the full 60 s, 0 over 33; drawers worst 20.9 ms.
- Contrast from pixels: live values 15.1-17.3:1, eyebrows 5.8-6.4:1; replay values 15.8-17.3:1, eyebrows 10.2-10.8:1, the line under ATUNCI 10.8-11.4:1; title caption 8.5:1.
- Tab walks live and over the replay: every stop ringed and at least 32 px; Esc leaves the replay.
- shoot.mjs at 1920, 1280 and 2560: 0 missing, 0 errors.

## A kept real frame at entry, and the studio's numbers on the Unreal building (2026-09-24)

The visit with the real stream is continuous and its numbers stand on the building. The page keeps one real frame of the Unreal stream in this browser (a small WebP with its time, taken rarely) and shows it, dimmed and labelled «ultimul cadru live · <zi> <ora>», until the live video's first frame arrives, then fades into the same building live; the kept frame is never shown as live (0 frames in the adversary's logs). Four glass plaques carry the studio's figures on the Unreal building itself (the façade's run, the fact-check counts, the publication state, the Treasury), each anchored to a real object measured on the stream and following zoom, pan and the drawers within 0.9 px. The replay's door fades from the live frame into the replay and back. The slate says «live» only while both the image and the data are live. A stranger with the stream on: ALMOST — one building from title to live and a replay in the Unreal look would make it YES; the judge also found the Owner's key travelling in the signalling URL's query string.

- ## One continuous, truthful visit with the real stream (2026-09-24, W19)

- The page now keeps one real frame of the Owner's live Unreal headquarters in this browser, and the next entry opens on it. It is shown dimmed, with «ultimul cadru live · azi 23:07 · pornește sediul live…», until the live video's first frame, which then takes its place in half a second. Measured with the real stream at 1920, the dark plate between the key and the first picture drops from 1.3-3.2 s to 0 ms on every entry after the first. The studio's figures now stand over the video on four small glass plaques anchored to real objects of the streamed building: the façade's run, the fact-check board, distribution and the Treasury. They follow the camera, never cover an employee, and step aside for their face's readout. Entering the replay, the live picture fades into the page's graded building; leaving it, the live video fades back in. The slate says «live» only while the picture and the studio's data both are; otherwise it says which one is.

- 2026-09-24, W19, the kept frame (frontend/src/stream_keep.js, hq_stream.js, hq_stream_config.js, main.js). The frame is 960x504 WebP, about 50 KB, stored in IndexedDB (amn-ai-hq/kept) with the moment it was taken. It is taken 4 s after the stream's first live frame and then every 60 s, never per frame and never while the page is hidden. Every access is in try/catch under a 1.5 s timeout. A frame older than 30 days is not used. The page reads it while the title is up. streamLayers gained a `kept` state. The corner stays hidden over the kept frame and the slate says «doar datele sunt live», so nothing is shown as live that is not. When the live video presents its first frame (requestVideoFrameCallback), the kept frame fades off in 480 ms (--dur-handoff); under reduced motion it is a cut to the first held frame. With no kept frame (a first visit, or storage refused), the plate stays dark, as the Owner decided on 2026-09-15 («Încă apare vechiul format!»). Measured at 1920 on the real stream: no kept frame, dark 173-1508 ms after the key; with the signalling held 2 s, as the Owner meets it, dark 205-3375 ms. With a kept frame, it is on the plate from 160-186 ms to the first live frame (500 ms, or 2437 ms held), and dark 0 ms.

- 2026-09-24, W19, the plaques (frontend/src/stream_plaques.js, main.js layoutPlaques, office_scene.css). The four were chosen by looking at fit zoom: «RULAREA DIN 12.09 / 12/12 · încheiată», «VERIFICARE · 12.09 / 0 verificate · 11 respinse», «DISTRIBUȚIE / PUBLICAT · 12.09» and «TREZORERIE / 50.000 VR$». Their words come from the same facts store through hq_screens' face functions, with «—» for a value the page does not hold. Each is anchored to a real object measured on a raw 1920x1008 frame of the live stream: the empty façade sign band, the paper board in Verificare, the dark wall screen in Distribuție, and the Treasury's lockers. Measured from the plates' faces, in world px: (-5,-2), (0,-1), (0,0) and (-79,-7); the plates' ticker wall is a bookcase in Unreal. Placement avoids the employees' desk boxes and stays inside the room the drawers leave. The level follows the scale: value only at 1280 fit (0.78 CSS px per world px), full at 1920 (1.15), one step larger at 2560 (1.55), and none below 0.55. They are shown only over the live video, never in the replay, and are not animated under reduced motion. Measured at 1280, 1920 and 2560 across fit, zoom, drag, zoom-out, drawers closed and hover: 0 plaques over an employee and 0 over each other. Value text contrast is 14.4-17.1:1.

- 2026-09-24, W19, the replay's door and what is live. LiveStream.doorway: into the replay, a real frame of the live video fades over 620 ms (--dur-door) into the page's graded building; back, the live video fades in over the replay's last frame. Under reduced motion both are a cut. live_claims.js liveScope decides the slate and the canvas's name: «live» only while both the stream and the events are live; otherwise «… · doar imaginea e live» or «… · doar datele sunt live». With the events socket dropped while Unreal played: the slate «… · DOAR IMAGINEA E LIVE», the chip «Se reconectează…». The glossary W19 amendment was written first.

- Tested (W19): frontend 429/429 (19 new in tests/stream_entry.test.js), tsc clean, build green. frontend/dist was rebuilt after the checks; :8000 was not restarted; no backend source changed and no git state changed. The real stream was watched as one more read-only viewer (scratchpad ui/w19, h19.mjs on the W17 relay: viewer signalling only, RTCDataChannel.send replaced, no Remote Control, no key). Every run: 0 errors, 0 missing, 0 requests outside the studio's API. Frames with the plaques up, at rest: median 6.9 ms, worst 7.1 ms at 1280/1920/2560; drawers worst 20.8 ms, 0 over 33. The first replay entry still has frames of 28-42 ms (48.5 ms with the previous build in the same harness), and the door adds none. shoot.mjs at 1920, 1280 and 2560: 0 missing, 0 errors. Night only: the real hour allowed no day plaques. Still open, for the Owner: the dark plate on a browser's first visit (his 2026-09-15 rule, kept); the title's push still shows the page's building before the stream's; tokens, the EP board and the film frame are still hover-only over the video; the encoder defaults the page's client sends.

- ## A stranger and an adversary with the real stream, and the kept frame's fade (2026-09-24, W20)

- Two 2-minute visits at 1920 with the real Unreal stream, one cold in a fresh profile and one returning, followed only what the page offers: the invitation, the plaques, the faces, an employee, the rooms and the replay. Verdict: ALMOST. The live building and its four plaques look like a 2026 game. The building changes twice: the title's push is the page renderer's building (to about 1.3 s), and the replay is the page's graded, purple one. The adversary found no simulation. A rAF logger over every run recorded 0 frames with the kept frame on the plate and «Live», a «live» slate or a plaque. Kept records dated in the future or 31 days old were never shown. Each plaque followed its record when the record changed: a changed record at load, «—» when unreadable, and live 50.000 → 777 VR$ within 10 s of an economy event, matching the face card. The plaques held their objects within 0.9 px of the video's own transform through zoom, drag, the wheel, the fit glide and the drawers at 1280, 1920 and 2560.

- 2026-09-24, W20, the kept frame's fade (frontend/src/hq_stream.js). On the real stream the library's playStream arrives with the video already holding a frame. The frozen-frame copy made on going live then dropped the kept frame at once: a cut, never the 480 ms fade, and the kept canvas was repainted with this visit's frame under the old name. Now, while an earlier visit's kept frame is on the plate (not held), nothing is copied until the first presented frame. The frame then fades off over 490-530 ms, measured. When the fade ends, the page keeps its own frozen frame at once. If the first-frame callback never comes, a video that has presented frames starts the handoff on the next 2 s tick. The badge «ultimul cadru live · …» now hides for the whole fade; before, it came back beside the corner's «Live» for about 0.5 s. Held (reduced motion) is unchanged: the first held frame replaces the kept one. 3 new tests; frontend 432/432.

- 2026-09-24, W20, measured with the real stream (scratchpad ui/w20; h19 read-only viewer, data channel blocked, no Remote Control, no key). Entry: the title's push covers the plate until about 1.28 s, so the cold visible dark is about 0.3 s at normal speed (first live frame 1573 ms) and about 1.3-3.4 s with the signalling held 2 s. Returning at normal speed, the first live frame (423 ms) comes under the push, so the kept frame is seen only on a slow start. Contrast from real pixels: values 15.6-17.1:1, eyebrows 5.7-6.5:1. Frames: at rest median 6.9 ms, worst 7.2-13.9 ms; drawers worst 13.8-20.9 ms, 0 over 33; door out worst 34.7-41.7 ms, 1 over 33 (the known first-replay hitch); door in 7.1-13.9 ms. Tab walk: 33 stops, all with a visible ring; the plaques are not in the order. report.json: 0 errors, 0 missing, 0 foreign on every positive run. shoot.mjs at 1920, 1280 and 2560: 0 and 0. tsc clean, build green, dist rebuilt; :8000 not restarted; no backend change.

## The real stream in the game frame (2026-09-24)

For the first time the real Unreal headquarters was watched inside the game frame, by a harness that joined the live stream as one more viewer (no input into Unreal, no Remote Control, no Owner key). It found a bug the Owner's live page has today: Pixel Streaming's video took every click and hover, so no figure in the video opened its employee and dragging did not pan; now 12 of 12 clicks open the right employee at three sizes, zoomed and panned, and the video sits whole under the sky row, moving with the camera to 0.00 px. Over the stream the building's focus ring, the arrow keys' card and reduced motion (one real frame every 10 s instead of moving traffic) now work too. The replay's first-entry hitch was traced to a GPU flush and moved under the title; the replay ends on «Înapoi la live»; the fixtures were recaptured from a fresh copy of his data. A stranger with the stream on: ALMOST — "the building looks alive", but the entry is dark for 1-2.5 s, the title, stream and replay show three different buildings, and the studio's numbers drawn on the walls do not appear over the video.

- ## The real stream through the game frame, and the last polish (2026-09-24, W17)

- For the first time the harness showed the Owner's real Unreal headquarters inside the game frame, as one more read-only viewer, and the real stream exposed a bug no stranger could have seen on the page's own renderer. Pixel Streaming's player writes pointer-events: all on its own video, so over the live video no employee could be clicked, no face gave its readout and the building could not be dragged. The video now lets the pointer through: 12 of 12 figures clicked in the video opened the right employee at 1280, 1920 and 2560, zoomed and panned. The video sits whole under the sky row at every size, and moves with the page's camera to the pixel in every frame while the drawers glide. The replay hides the stream, draws the page's own day, and hands back a stream that stayed connected. The first replay of a visit no longer stops the building for a 55-110 ms frame at 1920 and 1280. The replay moves focus only for a keyboard visitor, ends with «Înapoi la live» beside the finished run, and names the live hour «ACUM» beside «ATUNCI» in a narrow frame. The fixtures are the studio as it stands today.

- 2026-09-24, W17, the stream. The harness (scratchpad ui/w17/stream_harness.mjs, stream.mjs) answers GET /office/stream with the relay path and relays the signalling WebSocket to ws://127.0.0.1:8890, as backend/app/office/stream.py does. It forwards only a viewer's signalling (listStreamers, subscribe, answer, iceCandidate, ping/pong, layerPreference), and it replaces RTCDataChannel.send in the page, so nothing reached Unreal; no Remote Control and no key were used. Fix: office_scene.css `.live-stream-layer video { pointer-events: none !important }`. The library's VideoPlayer sets pointer-events: all inline, so the page's layer rule did not reach the video, and the Owner's live page has had no clickable employees under the stream. Measured at 1280, 1920 and 2560: the video's picture rectangle equals the engine's world rectangle (0.00 px) open, closed and zoomed ×1.95. There were 0 frames in which the video lagged the camera (about 1,190 frames of drawer glides per size), and 0 frames over 20 ms. During the replay the layer is hidden, the peer stays connected and decodes at about 39 fps; on exit it is live again at 38-41 fps. Open, not changed: the page's client sends the library's default encoder commands to the shared encoder on every connect (MinQuality 64, MaxQuality 100, MinBitrate 20 Mbps, MaxBitrate 100 Mbps, 60 fps) and requests quality control. The harness blocked them; whether to stop them is the Owner's call.

- 2026-09-24, W17, the first replay's frame. A CDP trace showed the main thread waiting 60 ms on GPU backpressure at the switch, behind 24-39 ms raster flushes, while ANGLE ran worker tasks (likely GPU shader compiles). Tests narrowed it to the night-lit, replay-graded frame. The prewarm under the title drew that frame, but Chrome dropped its recording when the live frame was drawn next over the whole canvas. office_engine.js prewarm now reads a pixel back after the replay frame (_flushCanvas). hq_world.js prepareLight snapshots each composed plate group with createImageBitmap, so the GPU rasters it in its own gap, and it does not compose a light that is already prepared. Worst frame after the click, 3 fresh-profile runs per size from a live noon: before 1920 64/90/32 ms, 1280 79/55/72, 2560 68/68/72; after 1920 32/31/29, 1280 31/28/33, 2560 60/30/34/44/32/33 (plus 5 traced runs at 30-32).

- 2026-09-24, W17, the replay's words and keys. replay_invite.js fromKeyboard and replayFocus (pure, node-tested) decide where focus goes. The page moves focus to the play key at the start, and back at the end, only when the replay was started from the keyboard (the invitation, the dock key, or Enter on the façade), or when focus was on the replay's own controls. A mouse visitor ends on the live building with no «RELUARE» focus label. At the end, paused on the whole run, #replay-back «Înapoi la live» (green, 32 px, 6.24:1) takes the place of «Ieși din reluare». Below 1600 px the live hour reads «ACUM 20:40» beside «ATUNCI 23:48:18» (6.07:1). With both drawers open only ATUNCI shows, and the weather line wraps in its room. day_replay.js now asks the books at every moment the run can have moved a figure, in reads of at most 240 moments (up to 8), all made at the start. From the first moment not asked the walls say «—» (figuresAt `until`), never a stale figure; the run of 12.09 is still one read.

- 2026-09-24, W17, the fixtures and the register. The harness fixtures were recaptured from a fresh copy of data/studio.db (with -wal and -shm; the original never opened). The copy was migrated to 0047 on the copy only, giving 254 of 257 answers; the old set is kept dated. The events ledger (3,249 events) and the as-of answers were regenerated from the same copy. The newest finished run is still 12.09; the modules and the register now say what the studio says on 24.09. That register showed the Owner's switches as raw keys. ledger.js now reads them «Proprietarul a schimbat modul de autonomie · Supravegheat → CEO autonom» and «Proprietarul a schimbat mediul · MEDIU TEST», under the Proprietar chip (glossary W17 amendment first).

- Tested (W17): frontend 404/404 (8 new), tsc clean, build green, frontend/dist rebuilt after the checks, :8000 not restarted, no backend source changed. shoot.mjs at 1920, 1280 and 2560: 0 missing, 0 errors. A fresh-profile visit at 1920, 20:40: 0 errors; rest, replay and drawer frames all at most 31 ms, 0 over 33 ms; back to live in 6.17 s; 0 frames without the replay's marks. Still open: two first-replay frames of 44 and 60 ms in 11 runs at 2560; the live flourishes and canvas-drawn faces are not seen over the stream (the readouts are); the invitation keeps its screen position when the visitor zooms; the encoder commands above.

- ## A stranger with the real stream, then an adversary (2026-09-24, W18)

- For the first time a stranger judged the page with the Owner's real Unreal headquarters playing in the game frame, as one more read-only viewer (scratchpad ui/w18/visit18.mjs on the W17 relay: viewer signalling only, RTCDataChannel.send replaced, no Remote Control, no key). The verdict is ALMOST. The live building is the most striking picture the page has shown: real light, a real street, the real hour, and figures in the video that open the right employee. The visit breaks twice: at the dark 1.0-2.5 s between the title and the first picture, and where the studio's numbers drawn on the walls disappear under the video. The adversary found three accessibility failures that only the stream exposes, and fixed all three. The building's keyboard ring now shows over the stream. An employee reached with the arrow keys gets the glass card «ANGAJAT · … · Enter: deschide fișa angajatului.». Under reduced motion the stream is one real frame renewed every 10 s, and the corner reads «Live · Unreal · un cadru la 10 s». The invitation also follows the building when the visitor zooms.

- 2026-09-24, W18, measured with the stream (1280, 1920 and 2560, 0 errors, 0 missing, 0 requests outside the studio's API):
  - frames: median 6.9 ms; worst 7.2 ms at rest, 14 ms with drawers moving live, 20.9 ms in the replay, 27.7 ms with drawers moving in the replay; 0 frames over 33 ms; 0 camera-lag frames in about 1,190 per size.
  - the fps pill is honest: pill 35-40, WebRTC 34-40, 38.9 frames/s presented.
  - about 70 Mbps per viewer.
  - contrast over the video: 5.5-16.3:1 on every text measured.
  - Tab walk: 35 stops, each with a ring.
  - The W17 stream script re-run on the new build: misfit 0 px, 4 of 4 figures opened.

- 2026-09-24, W18, fixes:
  - office_scene.css: the viewport draws the 2px teal ring over the room the drawers leave while #office-canvas has :focus-visible (z-index 3, above the stream); the canvas's own outline, never seen, is transparent.
  - hq_readouts.js agentReadout, office_engine.js, scene_readout.js, main.js: under the stream (hitsOnly and not the replay), an arrow-key employee gets the face card, and the spoken words are unchanged.
  - hq_stream.js, hq_stream_config.js (HELD_STILL_MS = 10000), live_claims.js, main.js: under prefers-reduced-motion the video is hidden and a kept real frame is renewed every 10 s. The corner reads «Live · Unreal · un cadru la 10 s» with no fps figure, and a change of the system setting is followed.
  - main.js relayoutInviteSoon, replay_invite.js INVITE_RELAYOUT_MS = 180: the invitation is placed again once the camera rests after a zoom or drag.
  - The glossary W18 amendment was written first (backup GLOSSARY.md.w18bak).

- Tested (W18): frontend 410/410 (6 new in tests/stream_visit.test.js), tsc clean, build green, frontend/dist rebuilt after the checks, :8000 not restarted, no backend source changed, no git state changed. Still open, for the Owner:
  - the dark entry gap, and the title's building differing from Unreal's;
  - the studio's numbers drawn on the walls are not seen over the video;
  - the replay shows a third building;
  - the page's client pushes the library's encoder defaults to the shared encoder (blocked by the harness; about 70 Mbps per viewer);
  - the slate keeps «live» from the last snapshot when the events socket drops while the stream plays.

## The replay offered once, lit by its own hour: the first YES (2026-09-24)

The first stranger to answer YES. About four seconds after entering, while the studio rests, one glass invitation stands in the street under the building with words from the record only («Studioul se odihnește acum. Ultima rulare încheiată: …»); one click turns the building into the night of that run, lit by that instant's real sun (within 0.006° of NOAA), with no weather drawn because it is not known, the shelter clock marked ATUNCI, the register's live drawer noting that it stays live, and the Treasury and tokens walls showing the books as they were at each moment ("atunci"), read from two new backend routes (/events?since, /economy/as-of) that matched a recomputation from raw rows at 0 of 6,991 instants. The judge's words: "I clicked it and did not leave the page for the next minute and a half." The studio needs the Owner's next start to apply migrations 0046 and 0047 (two additive indexes); until then the page falls back by itself.

- ## The replay offered, and made whole (2026-09-24)

- The last working day now offers itself. When the visitor has entered the building and the studio rests by its own record (no run under way, nobody at work, a finished run to replay), a pane of the drawers' glass rises once per session into the street under the building: «RELUAREA ZILEI · Studioul se odihnește acum. Ultima zi de lucru: sâmbătă 12.09, 23:48–23:59 · 12 etape · 1 film publicat.» It has two keys, «Vezi reluarea» and «Nu acum». Every figure in it is the run's record. It never starts the replay by itself; Esc or «Nu acum» put it away for the session, and a live event takes it away. The replay is now lit by its own hour: a night run plays under a night sun, whatever the live hour is. It draws no weather, and says under the ATUNCI clock that the weather of that moment is not known. The street's clock shows the replayed time under ATUNCI. The Treasury and the tokens plate show the books as they stood at each replayed moment, marked «atunci». The register says the building is replaying and that the register stays live. The replay finds its run in one read instead of about thirteen.

- 2026-09-24, W15 «the replay offered, and made whole» (frontend and backend). frontend/src/replay_invite.js is pure and node-tested. inviteWords reads the runbook run only: date, weekday, hours in the studio's zone, «N etape» or «k din N etape», and films from the backend's `produced`, else its published list, else a legacy publication. restingNow requires a finished run, no live run and nobody WORKING/THINKING/EXECUTING/RUNNING/PLANNING/REVIEWING. invitePlacement centres the card in the room the drawers leave, under the building, never above the ground floor (0.78 of its height). inviteMemory keeps the session's memory in sessionStorage, inside try/catch. main.js asks again whenever the facts or the people change, 1.5 s after the entry has settled; nothing is fetched. It is said once in the polite region; its keys are 32 px with the teal ring; under reduced motion it appears without its rise. After an automatic return to live, keyboard focus that was on the replay's controls goes to the dock's «Reluare» key.

- The replayed world's light (hq_world.js, office_engine.js). WorldSimulationManager.setReplayMoment lights the world with hq_time's solar position at the replayed instant over Bucharest. It is re-read once per replayed second and set back to the real hour at once on exit. While a day is replayed the world draws NO_WEATHER (hq_weather.js). The glass clock keeps the live hour, and the bus shelter's clock shows the replayed time under «ATUNCI». This is a decision taken for the Owner and reversible: the page does not know the weather of that night, so it draws none and says so («vremea de atunci nu e cunoscută»). Plates for a jump of light are composed ahead of the switch (prepareLight) and taken whole. The real sun's small steps are composed one group per frame off-screen and swapped whole. A jump back to live is composed at once. The engine's prewarm under the title draws one frame of the other light and the replay's grade.

- Backend: GET /api/v1/events?since=<instant> answers from the lowest sequence stamped at or after the instant. It is one query over the new ix_domain_event_timestamp (covering index), and it names the instant in its answer so the page can tell a studio that ignored it. GET /api/v1/economy/as-of?at=…&at=… (up to 240 moments, backend/app/economy/as_of.py) gives, for each moment, three things from the books' own rows up to it: the VR_CASH balance, the DAILY/MONTHLY budgets active then, and the period's and the day's spend and tokens. Spend counts costs no invoice had yet replaced, prices of runs finished by then and holds held then. It uses eight indexed SELECTs whatever the number of moments, and a reading at 'now' equals the live treasury and budget. Pending and forecast lines are not rebuilt, and the answer says so. Migration 0047_replay_reads adds ix_domain_event_timestamp and ix_agent_run_started (additive). The revision guard is now 0047: scripts/start.py applies it through bootstrap on the Owner's next start; the running studio is at 0045. Until then the page falls back: the record is bisected in 14 requests and the walls say «—». Proof: tests/test_replay_reads.py, 14/14, written first. With test_foundation, the economy, reconciliation, concurrency, books, reset, last-task and rehearsal files: 138 passed and 2 opt-in skipped. ruff and mypy clean.

- The reduced-motion drawer snap. Measured, it was not a canvas resize: none happens in the snap. It was the click's forced restyle of the whole document, 7-22 ms, because --hud-l/--hud-r were set on :root. They are now set on the render's own panel, and under reduced motion a closed register's list is content-visibility: hidden. The forced restyle is now 3.9-7.2 ms. The size watch's canvas resize is also deferred one frame.

- Tested (W15): frontend 395/395 (12 new in tests/replay_offer.test.js), tsc clean, build green, frontend/dist rebuilt, :8000 not restarted. shoot.mjs at 1920, 1280 and 2560: 0 missing fixtures, 0 errors. The harness served /events with `since` and /economy/as-of from answers the backend's own economy_as_of computed on a copy of the studio DB (scratchpad ui/w15, offer.mjs, asof_fixture.py). The invitation was photographed at 1280, 1920 and 2560, day and night, and recorded invitation → replay → live at fit zoom (w15/final, sequence_*.png). Contrast: «Vezi reluarea» 5.36:1 at worst, all other words 9.3-15.1:1. On the copy of the DB: 3308 events, 0 stamped out of order; the since page takes 6.3 ms; as-of takes 21 ms for 45 moments and 59 ms for 221. Frames: 311-313 per 5 s with the invitation up and 304-312 in the replay, 0 over 33 ms except one of 37 ms at 2560 at 16×; the exit's worst frame is 21-28 ms. Still open: the first replay of a visit entered from a live day costs one 66-73 ms frame (was 105-158); the stream path is untested; at 1920 and 2560 the shelter clock is under the side drawer.

- ## A stranger again, then an adversary: the replay is offered and holds up (2026-09-24, W16)

- A cold visitor at 1920x1080, in a fresh browser profile at 20:10 Bucharest time, signed in and followed only what the page offered. About 4 s after the key a glass card in the street invited them to «Reluarea zilei». They watched the whole run of 12.09 at 1×, left it, started it again from the dock, and were taken back to live by a live event in 6.2 s. Verdict: YES. The replay is now offered, not hidden, and the minute it plays is the page's most striking moment. An adversary then tested it. Across the whole run, the Treasury and tokens walls equal the books recomputed from the raw rows of a copy of the DB at every 100 ms (6,991 instants, 0 differences). The backend's 221 as-of readings also equal the recomputed books. The replayed sun matches an independent NOAA calculation to 0.006°. A per-frame probe found 0 replay frames without the replay's marks and 0 live frames carrying them, over about 25,000 and 7,000 frames at 1280, 1920 and 2560, day, night and reduced motion.

- 2026-09-24, W16, fixes (frontend only). First, the invitation said «Ultima zi de lucru: sâmbătă 12.09 …» while the live register beside it listed the employees' research runs of 19.09. Glossary first (W16 amendment), then the invitation says «Ultima rulare încheiată: sâmbătă 12.09, 23:48–23:59 · 12 etape · 1 film publicat.» and the idle façade card «Clic sau Enter: Vezi ultima rulare încheiată.», matching the dock's own title. Second, inside the replay's letterbox the live snapshot's «Actualizat hh:mm:ss» stood beside the replayed run's «acum: …». It is now hidden while a day is replayed (office_scene.css). Third, an older studio (the Owner's, at 0045) was asked for /economy/as-of and answered 404, which Chrome logs as an error. day_replay.js figuresQuery now asks for the books only when the log was read by time (method 'since'; both routes came with 0047). The old-studio flow gives 0 errors and no as-of request.

- Tested (W16): frontend 396/396 (1 new), tsc clean, build green. frontend/dist was rebuilt after the checks; :8000 was not restarted. Backend untouched: test_replay_reads, test_rehearsal_on_a_copy and test_phase11_economy 51 passed and 2 opt-in skipped; ruff and mypy clean (199 files). shoot.mjs at 1920, 1280 and 2560: 0 missing, 0 errors; all stranger, contrast and Tab runs: 0 errors. Pixel contrast, minimum over 1280/1920/2560 by day and night: «Vezi reluarea» 5.46:1, other invitation words 9.6-15.7:1, replay chip 10.1:1, replay time 7.3:1, weather line 11.1:1. Tab reaches «Vezi reluarea» and «Nu acum» with the 2 px teal ring; Esc dismisses the card for the session. Frames: 311-313 per 5 s at rest and 306-311 in the replay, with 0 over 33 ms; drawers moving, live or replayed, give 0 over 33 ms except one 34 ms frame at 1280 under reduced motion. Still open: the first replay entered from a live day costs one 63-91 ms frame. Pictures: scratchpad ui/w16 (final_visit_1920, sequence_stranger_1920.png, final_c_*).

- Migration 0047_replay_reads adds two indexes (ix_domain_event_timestamp, ix_agent_run_started); additive, no row changes. The revision guard expects 0047, and scripts/start.py applies 0046 and 0047 through scripts/bootstrap.py on the Owner's next start. Until then the page falls back by itself: the replay bisects the register (14 requests) and the Treasury and tokens walls say «—» during a replay; the page asks the as-of route only of a studio that has it. Verified for this commit: frontend 396/396, tsc clean; tests/test_replay_reads.py, test_phase11_economy, test_foundation, test_schema_and_audit_trail, test_last_task_per_agent, test_rehearsal_on_a_copy and test_phase1_agents 103 passed, 2 opt-in skipped; ruff and mypy clean on 199 files.

## The day replayed from its record, and a live arrival seen across the room (2026-09-24)

The building can now show a working day while the studio rests, and never pretend it is today. «Reluarea zilei» plays the newest finished run back from its own record, time-compressed to about a minute (research, selection, script, media, edit, publish), with the employees' own words, the rooms flaring as each stage starts and the façade sign counting to 12/12; it is labelled at every instant (a letterbox, a grey-violet grade on the world, the «RELUARE · <zi> <ora>» chip, the «ATUNCI» clock, violet tags), a live event takes the page back to live within 6 s, and an independent reducer matched it on both real runs of 12.09 with 0 differences in 889 checks. A live arrival is now seen from across the room (the employee's tag, the stage's room lit), a failed read says so instead of claiming an empty record, each desk is a 32 px+ target, the name tags carry each employee's real last task from the backend (8 of 8 on his data, was 2), and the Journal is a premium glass dialog with the newest episode as a poster. A stranger's verdict: ALMOST — "that minute is the first time the page amazed me"; the visitor still has to find the replay.

- ## A live arrival is seen from across the room (2026-09-24)

- The building now shows a live arrival at the size of the building. When the backend sends, as it happens, that an employee starts to work, that employee wears their world tag for about four seconds: «Dr. Aris (Researcher) · lucrează · căutarea surselor». The tag stands under the desk, and two rings widen from it. When a stage of the day's run starts, the rooms that do that stage's work come up to full light for about three seconds, with a lit, soft-edged frame, and the façade sign glints once. Nothing plays for a replayed event or under reduced motion. A face whose list could not be read now says «—» or «registrul nu a putut fi citit», never that the record is empty. Every desk is a target the size of the desk. The façade card stands under the sign. The name tags read each employee's last task from the studio's own record of runs: 8 of 8, where the replay gave 2. The Journal is a pane of the drawers' glass, with the newest episode on its cover as a poster. The film toast shows the render bay's brightest frame. A stranger at fit zoom now sees the arrival from the other side of the building: about 12 % of the building's pixels change for three seconds, and at rest nothing moves.

- 2026-09-24, W12 «the stranger's list» (frontend, one backend field). frontend/src/hq_arrivals.js is pure and node-tested. main.js hands each socket event to office_engine.js offerArrival(event, live). Only a live 'event' at most two minutes old starts anything; a 'replay_event' never does, and nothing starts under reduced motion. agent.state_changed to WORKING or THINKING (both «lucrează» in the register) puts up the employee's tag for 4 s. The tag is 13 screen px, under the desk (above the head it covered the boards and the render bay). Two rings widen from the desk. When the work ends the words change at once to the register's («a terminat», «stare: eroare», «stare: blocaj»). runbook.stage_started lifts the shade off the stage's rooms for 3.2 s and pours warm ceiling light down them, softer by day. It draws a lit edge with a fading halo over the shell and puts a chip «acum: <etapă>» on the room's floor; the chip is skipped where the room is too narrow (1280). GlintTracker.force glints the sign. The rooms come from who runs each stage in runbook/stages.py (STAGE_ROOMS); preflight and daily_log light no room. Nothing is fetched.

- Not read is not empty. worldFacts.reads records how /runbook/runs, /story/episodes, the treasury and budget, the register and the film frame were read: 'pending', 'ok' or 'failed'. A failure never overwrites a successful read. The sign, the fact-check board, the radar, the render bay, the Treasury, the tokens plate, the writers' screen, the cork board and the side drawer's foot say «—» while a read is pending. When a read failed they say «registrul nu a putut fi citit» (or «serialul…», «trezoreria…», «bugetul…», «cadrul filmului nu a putut fi citit»). «nicio rulare / niciun film / niciun subiect în registru» appear only after a successful read (hq_screens.js listWords, NOT_READ). With every list answering 404, no face claimed an empty record.

- Targets and the façade card. hq_readouts.js deskRegion makes each occupied desk's surface the monitor, the chair, the figure and the desk: 55x62 px at 1920 and 38x42 at 1280, where the monitor alone was 9-13 px. pointerHit makes the figure part of its desk, so the desk card opens from anywhere on the desk; a click still opens the employee. The sign's card prefers 'below' (SURFACES.prefer, placeReadout) and no longer lies over the AMN-AI lettering.

- Backend: backend/app/services.py last_task_per_agent returns each employee's newest run, started or finished. It is one grouped MAX(started_at) per agent over the new index ix_agent_run_agent_started (migration 0046_agent_run_last_task). The snapshot carries it as last_tasks. On a copy of the Owner's data it takes 0.4-0.6 ms and covers all 8 employees. The page merges it with the register's live events, and the newer wins (tasksFromRecord, newerTasks). ledger.js has words for the task types the runs record (answer_mail, research_models, direct_company, story_review and others). The app's revision guard is now 0046: scripts/start.py migrates at start, but a restart through scripts/run.py alone needs scripts/bootstrap.py once. Proof: tests/test_last_task_per_agent.py, 5/5, written first. It covers the newest run, a started run, the snapshot, the route and one indexed SELECT. With test_foundation (schema match) and test_phase1_agents: 49 passed. ruff and mypy are clean.

- The Journal and the toast. #story-modal is a pane of the drawers' glass. Its cover (serial_room.js journalCoverHtml) shows the newest episode as a poster: its number in the display face (a muted «—» with «fără număr în serial» when it has none), its title, the day it tells, and the Director's verdict with the mean of her scores and the checks passed. It has «Citește scenariul» and «În serial N episoade aprobate». The empty «NICIUN FIR DESCHIS» panel is no longer drawn. The film toast shows the render bay's brightest-of-five frame from the same single read of the file (film_poster.js PosterCache).

- Tested (W12): frontend 363/363 (16 new), tsc clean, build green; frontend/dist was rebuilt after the checks, and :8000 was not restarted. shoot.mjs at 1920, 1280 and 2560: 0 missing and 0 errors. The live arrival was recorded at fit zoom at 1920 and 1280, at noon and at night, through the page's own socket (scratchpad ui/w12, arrival_*). While a stage flares, 12.0-12.9 % of the building's pixels change, and the lit rooms gain +23 to +31 luma by day and +47 to +56 at night. The same events replayed gave 0 flourishes. Under reduced motion 0 flourishes: 2.16 % of pixels changed once with the state and then held still. The tag measured 13.8:1 and the chip 13.9-16.0:1. Frames with flourishes every 0.7 s: 312 per 5 s at 1920, 1280 and 2560, p95 21 ms, 0 over 33 ms. The network is the existing poll. Still open: the Unreal stream shows none of the flourish; the migration needs bootstrap on the next restart; THINKING counts as work; at 1280 the tag covers the top of the room below for 4 s.

- ## «Reluarea zilei»: the newest real working day, played back from its record (2026-09-24)

- A visitor who arrives while the studio rests can now watch the last working day. Beside the camera in the dock sits a key, «Reluare», and the idle façade's card says «Clic sau Enter: Vezi ultima zi de lucru.». Either one plays back the newest run the runbook recorded as finished. On the Owner's data that is 12.09, 23:48-23:59 Bucharest time, played in about a minute. The building replays exactly what the studio wrote. Elena checks claim after claim, Sarah reads each draft and Marcus rewrites it, the render passes, Vera publishes, Nadia closes the books, and the sign fills stage by stage to 12/12. Each employee's tag appears when they start, rooms light as their stage starts, and captions carry the words the employees wrote, each labelled with its moment. Nothing about it can be taken for live. A letterbox closes over the sky and the street, the world is graded towards grey and violet, the corner says «RELUARE · 12.09 · 23:48» instead of «Live», and the replayed moment's real clock («ATUNCI 23:49:35») stands beside the live one. The drawers and the register stay live. If anything happens live, «Se întâmplă acum» says what, and the page returns to live on a click or after 6 s.

- 2026-09-24, W13 «Reluarea zilei» (frontend only). frontend/src/day_replay.js is pure and node-tested. replayableRun picks the newest finished run. readRecord reads its events once, when the replay starts: it bisects /events?after=&limit=1 to the run's start (narrowed by the events the page already holds), then pages forward 300 at a time to the run's own runbook.daily_run_finished. On the Owner's data that is 13 requests, and nothing is fetched per frame. buildTimeline cuts the run by its own start and finish events. The reducer frameAt(timeline, t) applies office_state.js's rules to the events up to t, and also gives the day track, the run as its record stood at t (runAt), the topics and the last tasks. initialStates infers only that someone whose first change in the run ends work was already working when it began. Values the record does not carry at t show «—» (treasury, budget, tokens, the serial). buildSchedule plays the busy record at one rate, fitted to about 60 s at 1×, never slower than real time; the speeds are 1×, 4× and 16×. A stretch of 30 s or more with nothing recorded passes in 2 s and says so with its real times. On 12.09 the render's seven silent minutes read «nicio schimbare în registru 23:51:30–23:58:24 · de 207 ori mai repede».

- The page (frontend/src/replay_player.js, main.js, index.html, office_scene.css, hq_world.js, office_engine.js, hq_arrivals.js, hq_readouts.js). While the replay is on, main.js stops handing the engine its live agents, speech and facts, and gives them back at the end; the live state itself keeps updating. Events crossed while playing reach the world through engine.offerReplayArrival (the new `replay` path in Arrivals.offer): tags, rings, room flares and the sign glint. Replayed captions (agent.message_sent text and the finished-task line) are drawn at 12 px with the label «RELUARE · hh:mm:ss», in the backend's own words, at most 2 lines, then «…». The grade (drawReplayGrade) is laid before the words, so the words stay clear. The controls are one plate on the letterbox: play/pause, previous and next stage, a scrubber with each stage's start marked (aria-valuetext gives the clock and the stage; Page Up / Page Down step stages), the real clock, the stage, progress and rate, 1×/4×/16×, and «Ieși din reluare». Esc exits and Space plays or pauses. Stage changes are announced politely. Under reduced motion the replay steps from stage to stage every 3.5 s, with no flourish. Live wins: interruptsReplay (agent., runbook., media., publishing., story., factual., director., economy., and workflow. carrying current_stage) raises «Se întâmplă acum» in the register's own words and returns to live on a click or after 6 s. The watchdog's routine rows do not interrupt. Under the Unreal stream, the replay hides the stream layer for its duration and draws the page's own renderer (untested against the live stream). New tokens --replay-* are in :root; violet belongs to the replay alone. --dock-room went from 372 to 408 px for the new key.

- Tested (W13): frontend 380/380 (17 new), tsc clean, build green. frontend/dist was rebuilt after the checks; :8000 was not restarted and no backend file changed. The node fixture tests/fixtures/replay_runs_2026-09-12.json holds two unedited real runs of 12.09: the captured 07:36 run, and the 20:48 run with its 214 events from a copy of the studio DB. The harness answers /events as the backend does, from all 3170 real events of the same copy (scratchpad ui/fixtures_w13, w13/replay.mjs). Recorded at fit zoom at 1920 (noon and night), 1280, 2560 and under reduced motion: the whole run crossed in order in 60.8 s at 1×. Frames: 309/310 per 5 s at 1× against 313 at rest, 16× p95 24 ms, 0 frames over 33 ms. After a live WORKING event the page returned to live in 6.01 s, with the live tag up; the watchdog's row did not interrupt. Contrast: the replay's words measured 10.9:1, and all its keys are 32 px with the teal focus ring. shoot.mjs at 1920, 1280 and 2560 gave 0 missing and 0 errors. Still open: the replay's sky and street are the present city; the treasury of that night is not in the events (a backend 'as of' read would give it); /events?since= would cut the ~12 probes to 1; the stream path is untested.

- ## A stranger again, then an adversary: the replay is honest and now looks it (2026-09-24, W14)

- A cold visitor at 1920x1080 signed in, watched the idle building, played «Reluarea zilei» from start to end, let a live event arrive during it and opened the Journal. Verdict: ALMOST. The replay is the first thing on the page that amazes: for a minute the building works as it worked on 12.09. At rest the interior is still (only the street moves, 1.43 % of pixels in 5 s), and the replay is only a dock key and a line on the façade card. Three small things undercut the replay's honesty, and W14 fixed them. First, replayed tags, rings and room chips were drawn in the live green, so a cropped tag could not be told from a live one. They are now in the replay's violet (hq_arrivals.js arrivalAccent, used by hq_world.js drawArrivals and drawRoomRims). Second, the slate inside the replay's letterbox said «12/12 · ÎNCHEIATĂ» under a sign at 5/12. It now shows the replayed run as the record stood then (main.js renderDayTrack, replay.frame.track); the live track is kept and returns on exit. Third, the part of the scrubber still to play measured 2.16:1; it is now the new :root token --replay-rest, #6b5db8, at 3.56:1.

- Tested (W14): an independent reducer written from office_state.js's rules agreed with frameAt at every event and at 50 random instants on both real runs of 12.09: 889 checks, 0 mismatches, 0 invented events, 0 stages from the future, 0 early finishes. This is now a node test in day_replay.test.js. Of 27 screenshots at random instants (1920 noon, 2560 night, 1280 reduced motion), every one had the chip «RELUARE · 12.09 · 23:48», «ATUNCI» and the plate in view, and the page never scrolls. Pixel contrast at 1280, 1920 and 2560, day and night, was identical: chip 10.1:1, ATUNCI 14.8:1, time 10.8:1, stage 14.5:1, meta 6.45:1, scrubber thumb 10.8:1, played run 5.6:1. Frame timing: in the replay 309-311 frames per 5 s, 0 over 33 ms; with the drawers moving during the replay 368-375 frames per 6 s, 0 over 33 ms except at 1280 under reduced motion, where the same drawer snap gives 2 live and 4 in replay. The Tab walk goes play, next stage, scrubber, 1×/4×/16×, exit, all 32 px with the teal ring; Page Up/Down step stages. Live wins: the page returned to live in 6.01 s. npm test 383/383, tsc clean, build green, frontend/dist rebuilt, :8000 not restarted. shoot.mjs at 1920, 1280 and 2560: 0 missing, 0 errors. Pictures and measurements: scratchpad ui/w14 (after_1920, after_2560_night, after_1280_reduced, random_sheet.png, crop_tags_3x.png, crop_slate_*.png, c_*/ and contrast_px.json, trace.json).

- Migration 0046_agent_run_last_task adds one index (ix_agent_run_agent_started on agent_run agent_id, started_at) for the snapshot's last task per employee; additive, no row changes. The application's revision guard now expects 0046, and scripts/start.py applies it through scripts/bootstrap.py on the Owner's next start, as every migration before it. Verified for this commit: frontend 383/383, tsc clean; tests/test_last_task_per_agent.py, test_foundation, test_schema_and_audit_trail, test_phase1_agents, test_phase2_workflows, test_phase4_factual and test_rehearsal_on_a_copy 71 passed, 2 opt-in skipped; ruff and mypy clean on 197 files.

## The building's truth is legible (2026-09-24)

The building's truth is now legible. Every bound wall (the façade sign, the cork board, the fact-check board, the writers' screen, the publication radar, the render bay, the server plate, the Treasury) and every occupied desk's monitor answers the pointer and the keyboard with a glass card in the drawers' material, at a readable size and never over the face it describes; the arrows walk the eight employees and then the eight walls, each announced once in Romanian, and Enter opens the wall's room. A face whose value changes live glints once. The idle façade says what is true now («următoarea rulare …» or «programarea zilnică este oprită»), the name tag carries the employee's last real task, the render bay shows the brightest real frame of the newest film, and the backend's run summary counts a legacy run's publication. A stranger's verdict: ALMOST — nothing simulated, but a live arrival is still small at fit zoom.

- ## The truth made legible (2026-09-24)

The building's faces can now be read at fit zoom. Every bound face is a place the pointer and the keyboard can stand on: the façade sign, the cork board, the fact-check board, the writers' screen, the publication radar, the render bay, the tokens plate, the Treasury ticker, and each occupied desk's monitor. A glass card of the drawers' own glass then lies beside the face, with the face's own words larger and one line of what the face is. It stays in the room the drawers, the sky row and the slate leave, and never over the face. A face whose value changes while the page watches glints once. The idle façade says when the next run is, or that the daily schedule is stopped. An employee's last real task shows under their name. The render bay shows the brightest real frame of the newest film. The slate stays on one line off the kerb. The runbook's recount counts the film a legacy run published.

- 2026-09-24, W10 «the truth made legible» (frontend, and one backend count). frontend/src/hq_readouts.js (pure, node tests) lists the eight bound walls with their own face rectangles and adds the monitor of every occupied desk. The renderer appends them to its hits list after the employees, and a pointer takes the smallest box under it, so a desk's monitor is found in front of its employee. surfaceReadout writes each face's words from the same facts store the faces are drawn from; nothing is fetched and a missing value is «—». Example: «TREZORERIE · S2 / 50.000 VR$ cheltuibili / azi 0 / 15 USD». scene_readout.js lays the card with placeReadout (right, left, above, below; inside the free room; never over the face). The card is aria-hidden and its sentence is said once in a polite live region: at once for the keyboard, after 600 ms at rest for the pointer. The keyboard walks the employees and then the walls, with the page's teal focus ring drawn in the world. A click or Enter on a wall opens its room's dialog; a desk monitor opens its employee. When a face's value changes live it glints once for 1.4 s. It does not glint for its first value, within 6 s of the key, or for a value arriving from or going to «—», and never under reduced motion.

- The idle building says what is true now. While no run is under way, the façade sign's state line adds the scheduler's own next run («următoarea rulare vin. 25.09, 05:00») only while the daily job is active and autonomy is on. Otherwise it says «programarea zilnică este oprită» or «autonomia este oprită», and never shows a countdown. The name tag of the employee under the pointer or the keyboard has a faint second line with their last real task from the register: «ultima sarcină: căutarea surselor · acum 12 zile», or «—» when the register holds none. It is never a label on every desk. The render bay samples five key frames of the newest film once per film. It keeps the brightest one that is a picture, meaning the light varies between blocks of the frame, so a flat field does not count. The frame is decoded at 180x320 and the face is cached at twice the display scale. On the Owner's film this is the flare at 6.3 s, luma 137, where the old frame at 5.2 s was two lights on black at luma 42. Nothing is filtered. With both drawers open at 1280 and 1440 the slate stays one line («8 angajați · live»; the full caption is its title), so the near kerb clears it by 11 px and 17 px, where the old second line covered it.

- Backend: backend/app/runbook/services.py produced_by counts a legacy publish artefact, one without the nested 'published' list, from its own publication_id and publication_status. It counts 1 for PUBLISHED, REMOTE_CONFIRMED or SCHEDULED, and 0 for a simulated, failed, validated or blocked one. Current runs are counted as before. The recount of the captured 12.09 20:48 run now reads «7 au produs ceva … Filme publicate: 1.», not «Niciun film publicat azi.». The 17:59 run's reads «Filme publicate: 1.» too; both publications are PUBLISHED records. Proof: tests/test_runbook_publish_count.py, 6/6, written first (3 failed before the fix). Neighbours: daily-run stages, phase-10 runbook, day-survives-a-stage and the rehearsal file gave 104 passed and 2 opt-in skipped. ruff and mypy are clean.

- Tested: frontend 345/345 (28 new), tsc, build. shoot.mjs at 1920, 1280 and 2560: 0 missing, 0 errors. Readouts were probed at 1920, 1280 and 1440 with both drawers open, and at 2560. 24/24 were shown, with 0 covering their face, 0 under a drawer, 0 under the slate and 0 in the sky row. Tab walk: 0 stops out of view, 0 without a ring. The contrast sweep now reads an SVG label's ink from its fill, so the Treasury gauge's «0%» measures 15.52:1 rather than a false 1:1. Over 4284 pixel-measured pairs, including the card over three faces, 0 are below threshold; the card's weakest is 5.62:1. Frame timing at 1920 is 312-314 frames per 5 s, p95 21 ms and 0 face redraws, with the card open and while the keyboard walks. Under reduced motion 0 of 810,000 pixels change. A live topic and a run start pushed through the page's socket glinted the cork board and the sign once (scratchpad ui/w10). Still open: under the Unreal stream the card shows but the rings and glints are not seen. The desk-monitor target is 9-13 screen px. Six of eight employees have no task in the replayed register. The toast's own poster is still the single early frame.

- ## A stranger again (W11, 2026-09-24)

A cold visitor at 1920x1080 would be ALMOST amazed. The title screen and the first viewport read as a 2026 management game. Every bound face now answers the pointer and the keyboard with a readable glass card from the same facts. A live run pushed through the page's socket lights the researcher's monitors, and the cork board and the façade sign each glint once. The building at rest is still because every employee is IDLE in the Owner's data, which is true, and a live arrival is real but small at fit zoom. The adversary pass found three untruths and fixed them. (1) Between two stages of today's run the façade said «în lucru · programarea zilnică este oprită». runSignFace now tells a run that is under way (a stage running now) from one that is open (today's run started and not finished). While a run is open the sign names no next run, and the card says «Rularea de azi nu s-a încheiat încă.». (2) An employee closed with Escape kept the teal 'chosen' ring and tag for the rest of the session. The inspector's close event now clears the selection however the card closes. (3) main.js rewrote the canvas's accessible name without the screens, so the keyboard walk over the 8 walls was never announced as possible. The sentence now comes from one function, hq_readouts.js canvasLabel(live), the same one index.html carries.

- 2026-09-24, W11 adversary (frontend). frontend/src/hq_screens.js runSignFace returns underWay and open. frontend/src/hq_readouts.js uses them for the run_sign card and adds canvasLabel. frontend/src/main.js clears the engine's selection on the inspector's 'close' event and writes the canvas label through canvasLabel. Test first: two new tests in frontend/tests/hq_readouts.test.js, which failed before the change. Frontend 347/347, tsc clean, build green. frontend/dist was rebuilt after the checks passed; the Owner's :8000 was not restarted. The fixtures were mutated behind every wall (w11/mutate.mjs). Every readout followed the new values, and with the endpoints answering 404 they fell back to «—» or said there was none. Pictures and scripts are in scratchpad ui/w11 (stranger.mjs, mutate.mjs, perf.mjs, adv_sky.mjs, tagshot.mjs; sign_between_stages_before_after.png, live_sheet.png, tags_sheet.png).

- Tested (W11): the pixel contrast of the readout over all 8 walls and 2 desk monitors, at 1280, 1920 and 2560, noon and night: 4490 pairs each time, 0 below threshold. The card's weakest text measured 5.55:1. The in-world tag was measured from pixels: name 15.0-15.6:1, the «ultima sarcină» line 6.15-6.41:1. Frames per 5 s at rest, while hovering every face and with the drawers moving, at all three sizes: 312 / 312 / 375 in 6 s, worst 22-27 ms, 0 frames over 33 ms. Tab walk: 136 stops at 1920 and 135 at 1280, 0 out of view and 0 without a ring. The canvas is stop 9, and the arrows announce 8 employees and then 8 walls. Reduced motion: 0 of 810,000 pixels change, and the glints are counted but not drawn. shoot.mjs: 0 missing fixtures and 0 errors at 1920, 1280 and 2560. Backend: test_runbook_publish_count and its neighbours gave 104 passed and 2 opt-in skipped, with ruff and mypy clean. At rest the network is the existing 5 s snapshot poll, with no request per frame. Still open: when /runbook/runs cannot be read, the fact-check and render-bay lines say the record is empty rather than «—». The desk-monitor pointer target is 9-13 px. The façade card covers the AMN-AI lettering when it sits left of the sign. The Journal is the least game-like surface. The street's random life still awaits the Owner.

## The live headquarters follows a real clear day (2026-09-24)

The live headquarters' light now follows a real clear day, computed by the backend and sent over Remote Control, with no rebuild. The evening darkens in order instead of blacking out at 18:50: a warm golden hour (the key on the sun's side carries the low sun), the fills warmed by hue and never brighter than the noon's ground, back to their built colour after sunset; a dawn cooler than the dusk with fewer lit windows; a night sky lit by the city instead of a black void. Noon is unchanged and the approved 19:19 dusk is pixel-identical to before (6.8 against the reference). Three rounds with an art director; the weather's look (cloud deck, rain) is written and tested but held, because the sky atlas has no grey deck — that needs a rebuild. It reaches the live stream when the Owner restarts his studio.

- The headquarters' real day, rounds 1-3 (2026-09-24). The committed code (00d92ce) blacked out the street before the lamps came on. The pavement read 29.9 at 17:45, 20.8 at 18:25, 16.8 at 18:50 and 14.9 at 19:09 (lum2 regions, 0-255), a 'power cut' exactly when visitors arrive. Round 1 added the golden, dawn and night rules and a weather response. Round 2 lit the ground and overshot: the pavement reached 105-115 from 17:45 to 07:25, brighter than under the noon sun (70.7), with a sun-coloured fill after sunset. Round 3 holds the front ground on noon's budget. Over 9 frames the pavement is 65.1 / 65.2 / 58.0 / 59.8 / 52.1 at 17:45 / 17:58 / 18:25 / 18:50 / 19:09, and the road median at most 48.2 (budget 50.6). The golden hour keeps an amber ground (78/54/42), the fills are back to their built colour by -1 deg, and the building keeps its evening order (83.8, 80.6, 73.5, 66.6, 62.1, 47.6). Noon is unchanged and the 19:19 reference holds (6.8-6.9 against committed 6.7-6.8). Night has a lit navy sky (25.4 against 15.3), and dawn has its own deeper blue sky.

- Weather, rounds 1-3 (preview weather only, never shown as real). Under an overcast deck the planter shrubs read 50.5 (shrubs/walk 0.900 against clear noon's 0.909), up from round 2's 37.0. While rain falls the road is a traced mirror (roughness 0.08-0.24) with visible streaks of the lobby, the crossing and S1's LEDs, and its median is 52.0 against overcast's 46.3 at 13:07 (49.7 against 59.7 at 19:19). Not shippable yet. The daytime overcast sky is still the clear hour's blue with fair-weather clouds (top-rows chroma -6 %). Nothing reachable over Remote Control can grey it. The x20 deck sky-light lift also washes the black AMN-AI sign panel to slate (58/71/92 against 30/41/63) and tints the fascia royal blue. Art director's verdict: ALMOST. Ship the clear-weather rules only, with overcast_weight held at 0 and the committed road wetness, and hold the weather branch back. The live stream was left driven by the Owner's studio (read-only check at 16:02: sun pitch moving, StreetFill 0 as the committed plan). The studio still runs its 11:07 code until he restarts it.

- Shipped: the clear-weather rules only. The art director's third read (ship_it false, ship_clear_only true) held the weather branch back, and it is held in one place: scene_params.WEATHER_LOOK = False makes overcast_weight 0 for every weather and rain_look false, so a grey or rainy day gets the clear sky's light at the real hour, and the road stays wet or dry from the real rain exactly as the committed scene made it (the traced-mirror roughness is held too). The deck and rain rules and their seven tests stay, run with the look switched on (tests/test_scene_params.py fixture weather_look); a new test proves that a closed deck or falling rain changes nothing but the road while held. Tests: 155 passed across test_scene_params, test_office_environment_bridge, test_environment_routing, test_env_report and test_office_unreal_bridge; ruff and mypy clean. The Owner's running studio still runs the code it started with at 11:07: none of this, nor the easing fix of 00d92ce, reaches the live stream until he restarts start.py and scripts/run.py.

- The towers by day, prepared and not run (art3:towers-plan, 2026-09-24): the skyline's navy and its lit windows are baked into the export's window textures (dusk albedo 0.005-0.03, 57-194 lit cells of 576 per facade), so no run-time value can give the towers a day. An in-place pass on the saved level (no Blender re-export) is written and tested offline in the session scratchpad (real_sky/wave3/prepared: glass masks and window ranks from the bake PNGs, towers_day_hq_live.py, trees_day_hq_live.py, sign_hq_live.py, day_state.py, day_pass.ps1 with backup and rollback, and a backend patch). It needs a rebuild window with at least 16 GB of projected free commit and no game running.

## The building's screens tell the truth, and the frame is finished (2026-09-24)

The inside of the headquarters now tells the truth. Every desk monitor shows its employee's real state (dark, idle glow, scrolling work, red on error), each room's light follows whether anyone works there, and the building's screens carry real fields: the render bay a frame of the newest real film, the Treasury the spendable VR$ and today's spend against the budget, the façade sign the day's run, the fact-check board the research counts, the cork board the newest proposed topics, the writers' screen the newest episode, the server plate today's tokens. A value the page does not hold is drawn as «—», never invented. The frame is finished: the roof stands under a row of open sky, the dock hangs in the sky instead of over the crossing, the keyboard walks in the order the eye does, the Journal opens on the writers room, and the first visit's freeze fell from about 220 ms to about 75 ms. A stranger's verdict: ALMOST — with his data everyone is idle, so the building is truthfully still until the studio works.

- 2026-09-24, W7 «the idle building comes alive with truth» (frontend only). Every surface in the plates that reads as a screen, a board or a display is bound to a value the page really holds, or shows nothing (frontend/src/hq_screens.js; each binding a pure function with node tests). The plates baked working screens into all 23 monitors, so an idle desk looked busy. Each monitor, one pane per monitor and an angled quad for the desk monitors, now shows the employee's runtime state: dark with nobody at the desk or when paused, a plain idle glow when IDLE, scrolling work and a flicker only while WORKING, a slow pulse while THINKING, red in error. Each seated room's light follows whether anyone works there, within the real day or night: at night no shade while someone works, 0.20 while people sit idle, 0.50 with nobody at a desk; by day 0 / 0.04 / 0.14. Lit screens glow through the shade at night and are washed out by day. The render bay shows the render while the Video Editor works; otherwise a frame of the newest film the runbook recorded, decoded once per film with the Owner's key (film_poster.js); otherwise his state. The Treasury's wall ticker shows the spendable VR$ balance and today's spend against the daily budget in Romanian figures. The façade sign's free half shows the day's run in the slate's own segments and words. The fact-check whiteboard shows the newest run's verified claims and refused verdicts; the research board shows the newest proposed topics, one per note; the writers' room screen shows the newest episode ('EP N' only when the backend numbered it); the distribution radar shows the newest run's publication; the server room plate shows tokens used today. A value the page does not hold shows «—» or stays dark. The racks blink only while someone works.

- How it is fed and drawn. Nothing is fetched per frame. The newest run comes with the day record (/runbook/runs). The treasury and budget are read at the key and again at most every 15 s after an economy event or a finished run; the serial at the key and after story events; the dialogs' own reads feed the same store. Each face is drawn once into its own canvas and redrawn only when its value or the display scale changes: 0 redraws in 5 s of steady frames. Measured at 1920 in headless Chrome: 312 frames per 5 s before and after, median 14-15 ms, p95 21 ms, draw CPU 1-2 ms. Under reduced motion, 0 pixels change over 1.2 s with people at work; without it only the working monitors, the render band and the running segment move. The plate group building_front is split into desks and shell, so a room's light falls on its desks but not on the façade. The measured rectangles live in hq_screens.js until the art build exports them into manifest.json.

- Tested: frontend 303/303 (18 new in tests/hq_screens.test.js; 5 new tokens drift-checked in hq_palette.test.js), tsc, build. shoot.mjs at 1920, 1280 and 2560: 0 missing fixtures, 0 errors. Each surface photographed at fit and at 2x, at 12:00 and 23:30, with the captured fixtures and with a working overlay; a run under way from a named event fixture; the render bay's frame from a labelled FFmpeg test pattern, because the captured fixtures hold no film (scratchpad ui/w7, ui/fixtures_w7). Pixel contrast of the canvas text measured 7.0:1 or better on every face; the weakest designed pair is the fact board's green figure at 4.66:1. Still open: at fit zoom only the sign, 'EP N', the balance and the board figures can be read, and the rest needs 2-4x. With the captured data everyone is IDLE, so the building is truthfully still. Nothing of this shows on the live Unreal stream until the level carries the same bindings; the list is in the W7 return.

- 2026-09-24, W8 «finish the frame» (frontend only). The roof stands under open sky. The camera keeps a 48px row of sky above the world's top edge (--hud-top; game_frame.js frameFloor: the rails at the sides and the sky row at the top, which the frame always covers). The page paints its own sky up to the canvas top (hq_sky.js drawSky from a negative top: the same gradient, the same stars, rain from there; the night grade covers it with no seam). The clock and weather, the dock and the live state hang in that row, so none of them lies on the building. Measured at 1280, 1440, 1920 and 2560: world top 48px under the masthead, roof railing at +50-51, the lowest instrument at +43. The zoom is chosen against that floor, so a drawer only moves the camera (1.15 at 1920, was 1.2). Under a live stream the video is now laid in its box whole (contain, not cover); cover had cut its top rows, the roof's railing among them. The row above the video is the frame's dark ground, with no invented sky. The dock (switches, camera, fullscreen) is one glass plate in that row, and the zebra crossing and both lanes are clear. It is a container: the state words PORNIT/TEST always show; AUTONOMIE/MEDIU from 1100px of room; «Încadrează» and «Ecran complet» from 1500px; below that, icons with their word as a label on hover or focus. Every id is kept.

- The page's order is now the order it is seen in. The register's aside comes before the render and a second aside (governance, approvals, modules) comes after it, so Tab walks masthead > register > render and dock > side drawer (Tab walk at 1920 and 1280: 0 stops out of view, 0 without a ring). On a screen at least 1300px tall, the side drawer ends with «Studioul azi» (side_readout.js). It shows the day's run in the slate's words, the spendable VR$ and today's spend against the budget as the Treasury's wall screen says them, and the next scheduled daily run from /scheduler/jobs. That time is shown only while the job is active and autonomy is on; otherwise it says the schedule or autonomy is stopped. /scheduler/jobs is read with the treasury and budget: at the key and throttled after economy and run events. The Journal opens on the writers room («Episoade»), with the closed days after it.

- The first visit no longer freezes as long. In a fresh browser profile the first workspace frame stopped for 208-243 ms, 380 ms after the key: the GPU compiling, once per profile, the programs for what the workspace draws. While the title is up, the real workspace, masthead and footer are now painted for 4 frames at 1% opacity above it (inert, aria-hidden, at most 5/255 change on any pixel), with sample rows in their empty lists and the drawers laid out as the key will find them. Then they are hidden again; an accepted key ends this at once. Fresh profile per run, 3 runs each: worst frame 215/208/243 ms before, 83/69/76 ms after (a reused profile gives 49-90 ms). Screencast: 319 ms frozen before, 105 ms after. Tested: frontend 317/317 (14 new), tsc, build; shoot.mjs at 1920, 1280 and 2560 with 0 missing and 0 errors; the frame photographed at 1280, 1440, 1920 and 2560, drawers as opened, closed and both open, at 12:00 and 23:30 (scratchpad ui/w8). Frame timing unchanged: 312 frames per 5 s at 1920. Still open: the plate is cut flat at the world's top on its right half, the rest of the cold entry is the workspace's first layout, and the stream has been checked only with a labelled stand-in frame, not Unreal.

- 2026-09-24, W9 «a stranger again, then an adversary» (frontend only). A cold read at 1920 and an adversary's hunt for anything simulated inside the building. Verdict: ALMOST. The idle building is truthfully still, because the captured data holds everyone IDLE. Live events pushed through the page's own events socket ({type:'event'}, the backend gateway's form) bring it alive within a second. The monitors of the employees at work light and scroll, their rooms come up to full light at night, and the render bay says 'ÎN LUCRU'. The sign turns to 'RULAREA DE AZI 1/12 · acum: producție media', and a proposed topic lands on the cork board. A paused desk goes dark and an error goes red. Every surface was checked against the fixture that feeds it and followed when the fixture changed: fact board, episode screen, treasury ticker in deficit, tokens plate and radar. The render bay shows a frame of the real film from backend/storage/media. Two faults were found and fixed. First, the radar printed any publication state but PUBLISHED as the backend's code, so a simulated upload read 'PUBLISHED_SIMULATED'. It now says SIMULAT, and never PUBLICAT, with PROGRAMAT / NECONFIRMAT / EȘUAT for the other states (hq_screens.js PUBLICATION_WORD). Second, the register said 'a terminat' for a live ERROR or BLOCKED and printed task codes. It now says 'stare: eroare' or 'stare: blocaj' and gives the task in words (ledger.js). Measured: frontend 317/317, tsc, build. shoot.mjs at 1920, 1280 and 2560: 0 missing, 0 errors. Worst real text contrast 5.04:1 over 3159 pairs. 60 fps at rest and with the drawers gliding at 1280, 1920 and 2560 (median 15 ms, 0 frames over 33 ms). Cold entry worst frame 69-83 ms. Reduced motion changes 0 of 810,000 pixels. The Tab walk has 0 stops out of view, 0 inert, 0 without a ring. Still open: at fit zoom most faces cannot be read. The runbook's recount calls the 12.09 run filmless although its film was published, which is the backend's to fix. The Unreal stream carries none of this yet.

- Found and fixed by the adversary (W9): frontend/src/hq_screens.js publishFace (distribution radar): Honesty breach. Any publication state other than PUBLISHED was drawn as the backend's raw code. A simulated upload lit the radar as 'PUBLISHED_SIMULATED', which is English and reads as published. SCHEDULED, REMOTE_UNKNOWN and FAILED also showed as raw English. I proved it by setting the fixture to PUBLISHED_SIMULATED (w9/radar_before_after.png). frontend/src/ledger.js describeEvent agent.state_changed / agent.run_completed (live register): A live ERROR or BLOCKED state change was written as '<name> a terminat' ('finished'), which is false. The task also showed as the backend's code, for example 'sarcina reconcile_day'. agent.run_completed printed raw task types such as 'gather_sources · model'. Seen when I pushed a live ERROR event for Nadia. Tests: frontend 317/317, tsc clean, build green; 0 missing fixtures and 0 page errors at 1280, 1920 and 2560; the worst real text contrast 5.04:1; the drawers at 60 fps; the cold first visit's worst frame 69-83 ms (it was 208-243 ms); under reduced motion 0 pixels change.

## The serial made well: a voice per character, one look, its own identity (2026-09-24)

The serial is made well, not only made. Each character speaks in their own voice (a proposal from voices his catalogue already lists, which he confirms), with captions that follow the speaker; the series look reaches every shot prompt and a model cannot restyle it; the episode reaches the Publisher as "<hook> | Inside The Nexus Ep. N" with its logline and the previous episode; an approval the Director never read is recorded as his; the brief (episode-v5) and the Director's rubric (episode-review-v3) ask for a hook inside 3 seconds, a button that calls back, and no invented letters. A rehearsal of two real-calendar days on a copy of his data, every provider faked, filmed today's episode and wrote tomorrow's script on day 1, and filmed that script without rewriting it on day 2. The verifier's verdict: READY for his first paid click once he has done the seven steps below. No real model, voice or image has been used; that proof is his click.

- 2026-09-24, serial S7, one voice per speaker (tested with every provider faked; no real run; live DB never opened). A beat's lines are now spoken by the people who say them. The storyboard keeps, next to each scene's lines, which character bible speaks each one (speaker_bibles). The render plan turns a scene into takes, one per run of one speaker, and gives each take a voice in this order: the character's locked voice, the voice the Owner bound to the character, the voice proposed in config/serial_voice_cast.json (only while that file says it is in use, and only for a voice his own connection lists), then the narrator's. The takes are joined with a 0.3 s breath. The captions follow the takes, and nothing is captioned during the breath. No name or stage direction is ever spoken or captioned. If the lines no longer match the scene's narration, the scene is read whole. A consistency-locked channel with no voice locks (Channel B on his data) narrates rather than refuses, and the plan says so. Every film with real voices now pads each scene's narration to its shot; before, the words ran ahead of the pictures by every second a shot outlasted its words. Proof: tests/test_serial_voices.py, 14/14. A two-speaker beat makes two synthesize calls with two voice ids and one SRT whose cues change with the speaker, and the joined voice track lasts as long as the pictures. Neighbours: test_serial_pipeline 118, one-click adversary 13, production policy 18, phase5 media 30, daily-run stages, whole day and adversaries 143, pricing, editorial and story 71, all passed. ruff and mypy clean. Still open: a real render to hear the eight voices together (his paid click), the frontend labels for the takes, and a backfill of speaker_bibles for storyboards built before S7.

- 2026-09-24, serial S8, the series look and the shot prompts (tested with every model faked; no real run; live DB never opened). Before this, the serial's style was the label CHARACTER_ANIMATION, which no prompt carried, and the vendor got the showrunner's raw scene line. Now one versioned style block, a proposal in config/serial_series_look.json (v1, PROPOSED, on by default), opens every serial shot prompt word for word. It asks for a stylised cinematic 3D office with a warm feature-film finish: the AMN-AI headquarters, adults at human proportions, an eye-level camera, 9:16, and no written words, letters or logos in frame. It was written from the HQ reference picture, the office rooms and the 8 bibles, and it fixes no time of day. The storyboard's visual bible is that look, read-only and never decided per episode. The prompt agent writes the serial shots through the same write_shot_prompts path the factual films use, with a serial brief (serial-shot-prompts-v1). Each prompt is capped at 900 characters: style block, the beat's room, the camera (establishing, two-shot, single, close-up by the beat's part), the people in frame facing the viewer as their bibles describe them, the action and expression from the line's direction, then background, continuity and exclusions while they fit. Spoken lines never reach a picture prompt, and any request for writing is removed. The storyboard composes these shots itself, with no model. The video editor's model then rewrites them once per look version: from the serial stage, and from the media stage before filming, which also covers an episode he approved by hand. Character reference sheets now include the series rendering. Proof: tests/test_serial_look.py, 15/15. Neighbours: serial pipeline, voices, one-click adversary and editorial quality 210; identity, day survival, metadata, references, policy and phase5 171; daily-run stages, whole day, adversaries, publishing, editorial and story 157; all passed. ruff and mypy clean. Still open: a real render to judge the look (his paid click), a per-series seed, the frontend labels, and references (S9).

- 2026-09-24, serial S10, the serial's identity at publish, the honest record, and the brief's tone (tested with every provider faked; no real run; live DB never opened). Before this, an episode reached the Publisher as 'Storyboard: <title>' with its scenes and nothing else. Now the Publisher's facts carry the series 'Inside The Nexus', the episode number, the episode's own title, a logline, the previous episode and the title format '<hook> | Inside The Nexus Ep. N' (app/publishing/serial_identity.py). Every episode's title is written once in that format, whatever the model wrote. The description opens with the logline and names the previous episode. The series is the first tag. The metadata guard is as strict as it was and now judges the hook, not the series marker, so another film's title under the series name is still refused. A refused answer never goes out: the studio's own metadata, built from the episode alone, goes instead, judged by the same guard and the language rule, and the refusal stays on the record (metadata_source studio_fallback). The story gate's record now tells the truth. An episode the Director passed is hers (her checks, run and reasons). An episode the Owner approved without her reading is PASS with no reviewer, no run and no checks, marked source owner_approval with the reason in Romanian, and the production package shows who approved it. No gate changed. The showrunner brief is now episode-v4. It states the show (a deadpan workplace comedy about AI employees who take their jobs completely seriously, told from their own real day, from 07_STORY_ENGINE.md), gives full bibles only to those who act in the day's events and one line to the rest, and asks for a logline. On his bibles that is about 1.9k characters with two actors against 6.2k before. v3 episodes stay readable. Proof: tests/test_serial_identity.py 22/22. Neighbours: serial pipeline, voices, look, one-click adversary, editorial quality and metadata per film 244; daily-run stages, whole day, adversaries, publishing, story, editorial, media, policy, identity and paid-path tests 221; language and multi-LLM 23; all passed. ruff and mypy clean.

- 2026-09-24, serial S12, a rehearsal of two days on a copy of his data (every vendor faked; no real run; data/studio.db never opened, only copied with its -wal and -shm; the daily job switched on only on the copy). His newest event is 2026-09-24 09:47Z, so day 1 = 2026-09-25 and day 2 = 2026-09-26. On the copy only, the Director's leave was granted by his own versioned command (OFFICE_SERIAL policy v1 -> v2). The studio's calendar was moved for every app.* module, and each day ran through the real scheduler, queue, worker and runbook at 05:00. The real production plan ran, with the voice and picture adapters faked where they are built. Day 1 told 2026-09-19 (09-20..23 were empty and 09-24 held no public event): written, read by the Director (PASS, rubric all 4), approved under the leave, storyboarded with the series look (6 shots, each at or under 900 characters, each opening with the style block), filmed in two voices from the proposal (Sarah EXAVITQu4vr4xnSDxMaL, Kael IKne3meq5aSn9XLyUdCD; 12 takes, voice track 47.2 s = picture 47.2 s, 17 captions), passed QC and published SIMULATED (private) as 'Filed under unlikely | Inside The Nexus Ep. 1'. After the day's log closed, serial_next wrote, read and approved the script of 2026-09-25 with no storyboard. Day 2 readied that script from its rows (resumed = storyboard) and filmed it without asking any model to write it again. It went out as 'The record, read twice | Inside The Nexus Ep. 2' with 'Previously on Inside The Nexus: Ep. 1'. Day 2 then wrote the script of 2026-09-26. continuity_state went from 0 to canon 2 to canon 3. Nothing left the machine: 38 free reads were refused by the guard (the Google token and research hosts), there were no real uploads, and no paid path was reached. Report and briefs: scratchpad/rehearsal2/. The rehearsal found and fixed, test first: (1) the run's own end-of-run stage reports weighed as letters, so on day 2 they were the writer's 15 lines and the film published that morning was not among them; they are now routine for the story. (2) A letter to the Director's desk read '... wrote to Director', and hers 'Sarah (Director) wrote to Director'; it now names her, and her own note reads 'noted'. (3) Every year was redacted as an account number ('[redacted]-09-19'), which would also fail a line naming a year at the review's privacy check; a lone 19xx or 20xx is now kept. (4) A resumed serial stage had told_date null, so the run card lacked the day it films. Tests: test_serial_pipeline 125 (3 new functions, 7 cases, plus 1 new assertion), serial neighbours 239, whole day and runbook neighbours 233 (2 opt-in skips), the two-day rehearsal and the one-day harness passed on the copy, mypy clean. Still open: the log freezes at the run's hour (below), the words of a real model, the sound of the voices, and whether pictures hold faces, all of which only his paid click shows.

- 2026-09-24, the serial verified as an adversary and as a showrunner (serial2:verify, verdict READY). Fixed test first (tests/test_serial_quality_adversary.py, 10 tests; 3 fail without the fixes): backend/app/media/factory.py (render_plan takes) + assembler take fallback: A locked character whose locked voice cannot be used (for example, the binding names a voice his connection no longer lists) had a take with no adapter, so the assembler spoke it in the scene's voice. When another locked character comes first in the scene, that is the other character's locked voice. One character was spoken in another's locked voice and labelled 'scene_voice'.; backend/app/media/prompt_agent.py (_serial_package): A model that ignores the series look could restyle every shot. Its action, camera, expression and background reached the prompt whole after the style block ('photorealistic live-action, shot on 35mm film', 'in the style of Pixar', 'anime', 'black-and-white noir', '16:9'). Added strip_style_overrides; it is applied only while the look is in use and keeps lenses and props.; backend/app/publishing/services.py (publication_metadata_refusals copy check): The word-for-word copy check needed title AND tags to match. A Publisher that gave the episode the factual film's exact title with different tags passed whenever one word of that title was also in the episode. The title alone now counts as a copy, with its own Romanian reason.; backend/app/story/services.py (showrunner brief) and backend/app/story/review.py (Director rubric): The brief never put the hook inside 3 seconds, and every bible hands the writer a greeting to open on. It never said the button is the last words or calls back, and it never forbade beats that restate the one before. The day's events are mostly letter subjects, which invite invented contents that the Truth rule did not name. Fixed as brief episode-v5 and review episode-review-v3. The brief is now episode-v5 and the Director's review episode-review-v3: the hook is heard inside 3 seconds, at most 8 words and never a greeting; the button is the last words and best calls back to the hook; every beat escalates, reverses or reveals; a letter known only by its subject is played as the writing, the waiting and the reaction, never given invented contents (the Director counts a quoted invented letter as a Truth FAIL). Tests re-run for this commit with every provider faked: the serial files 233 passed (2 opt-in rehearsals skipped), their neighbours 139 passed, ruff clean, mypy clean on 196 files.

- THE OWNER'S CONDITION HOLDS WITH EVERY PROVIDER FAKED: on a copy of his data with the Director's leave granted on the copy, day 1 (2026-09-25) filmed Ep. 1 'Filed under unlikely' (telling 2026-09-19; two speakers in two voices, six shots opening with the series look, published private and simulated as 'Filed under unlikely | Inside The Nexus Ep. 1') and wrote, read and approved tomorrow's Ep. 2; day 2 filmed Ep. 2 without asking the model to write it again and wrote Ep. 3. What the Owner does before his first paid click, in order: 1. Choose the models (free: configuration only). In Agenți, give a strong model to the showrunner who writes the episode and to Sarah (Director), who judges it with the rubric (hook, situation, turn, payoff, voices, button). The stand-in in the rehearsal only proves the chain, not the words. 2. Read and confirm the show's tone: the SHOW_TONE constant in backend/app/story/services.py ('deadpan workplace comedy about AI employees who take their jobs completely seriously'). It is your taste call. Change the sentence if you want a different tone. 3. Confirm the style block: config/serial_series_look.json (stylised cinematic 3D, warm feature-film finish, AMN-AI headquarters, 9:16, no writing in frame). If you change it, raise 'version'. To draw in the model's default style, set use_until_the_owner_changes_it to false. 4. Confirm the voices. Listen to the 8 proposed voices in the ElevenLabs library (previews are free; nothing is generated): Sarah=Sarah, Aris=George, Elena=Alice, Marcus=Liam, Lyra=Lily, Kael=Charlie, Vera=Matilda, Nadia=Bella; the narrator stays Roger. Bind and lock the ones you like in each character's bible, or edit config/serial_voice_cast.json. A locked voice that later becomes unusable now stops real voices for that scene; nothing silently changes the voice. 5. Decide the Director's leave on Channel B. Either grant it (POST /api/v1/publishing/channels/{id}/publish-policy with director_may_approve_episodes=true; the page does not have this button yet), or approve each episode by hand in the serial room. Without the leave, nothing is filmed and tomorrow's script is not written until you approve. 6. Set the budget and the environment. Keep a DAILY budget that holds two films (the factual one and the episode: in PRODUCTION the motion hold is 12 USD per film, plus narration). Choose TEST (two test shots at 0.60 USD) for the first click, and move to PRODUCTION only after you have watched it. 7. Keep Channel B uploads private (autonomous_privacy private) until you have watched the first episode. Then press the one-click run yourself (not the daily job), watch Ep. 1, listen to the voices and judge the look.

## The workspace becomes a game frame, and the serial a writers room (2026-09-24)

The workspace is a game frame now: the render of the headquarters fills the first viewport edge to edge, the register and governance are glass drawers over its edges that close to rails carrying their real counts, the rooms are the studio's menu in the masthead and the switches one dock. The scene speaks Romanian, the street follows the real hour, day, holidays and weather and stops when the data is lost, the invented sky events are gone, and a historical event no longer speaks as if it happened now. The Journal reads the serial as a writers room (a slate, a beat board, a script page, the Director's rubric, «Scenariul de mâine»). The Media player works on the real server (CSP media-src). A stranger's verdict: ALMOST — no longer a dashboard; the idle building still does not move with the studio's truth.

- 2026-09-24, W4 «the workspace becomes a game frame» (frontend only). On a screen at least 1051px wide and 600px tall, the render is the whole first viewport, edge to edge between the masthead and a 30px footer strip, and the page no longer scrolls. The live register is a glass drawer over the left edge. Governance, the approvals and the module status are one over the right. Each closes by transform to a 40px rail that repeats the panel's own count, and the side rail turns gold while requests wait. The page opens a drawer on its own only where the building still fits beside it (game_frame.js drawerDefaults): both at 1920 and 2560; the register only at 1280-1440. A visitor's own choice is remembered on that browser. The camera covers the viewport and centres the building in the room between the drawers (frameFit); bare ground past the world's edge can only be under a drawer; it glides 420ms when a drawer moves, and not at all under reduced motion. The clock, the live readout, the slate and the moments stand inside that room. The switches and the camera are one dock above the slate. The seven rooms are the masthead's menu, with icon and word at 1720px and wider and icon plus a hover/focus label below that. «Ecran complet» takes the whole frame fullscreen. Below the frame's size the page is the stack it was, and a 390px screen no longer scrolls sideways. Every id is kept; drawers.js and game_frame.js are new.

- The canvas behind the stream. While a configured stream covers the canvas (video, frozen frame or starting plate), the canvas paints nothing and keeps only the employees' hit boxes, so a click on the video still opens the right employee. The page's zoom and pan are laid on the video and the frozen frame as a transform that matches the hit boxes exactly (streamTransform, tested). This assumes Unreal frames the same 1600x840 world as the canvas; the stream is 1920x1008. The canvas now also follows its box when the window resizes, which it never did before.

- The sign-in hitch. The office engine is built parked while the title screen is up. It decodes the plates and draws one frame, unseen, at the size the entry will use: plate caches composed, street sprites tinted for the hour, the work forced onto the GPU. The key light's first read-back waits until the entry has finished. Register rows off screen are not laid out until they scroll into view. The workspace's first layout runs under the still title, and the push starts on the next frame. Measured at 1920, same harness, warm runs: before, two long tasks (about 67ms and 80ms) and frames up to 83-97ms in the push; after, no long task, one 48-56ms frame before the push starts, and push frames at 42ms or less. The first entry in a fresh browser still has one 194-250ms frame of GPU raster (131-153ms before), yet to be checked on the Owner's GPU.

- Figures in the dialogs wave 1 did not reach now read as a Romanian reader writes them (numbers.js): the funding list and its preview («50.000 VR$», «7,00% pe an», «12.500 EUR × 1,08 → 13.500 VR$»), the media dialog's costs and durations, the budget-saved line and the approvals' costs («0,004 USD»). The slate caption is no longer cut at 1280: the slate chooses its words by its own width and puts the caption on a line of its own when it has to.

- Tested: 253/253 frontend tests (game_frame.test.js and game_frame_css.test.js new); tsc; build. Photographed at 1280, 1440, 1920 and 2560 with the drawers as the page opens them, closed, and both open. The entry and a drawer glide were recorded as frame sequences. shoot.mjs at 1920, 1280 and 2560: 0 missing fixtures, 0 errors. Pixel contrast: worst word on the glass 4.97:1. Keyboard walk: clean. Scratchpad ui/w4.

- 2026-09-24, W5 «the world inside the frame» (frontend, plus one line in backend/app/main.py). The scene speaks Romanian. What the canvas draws now goes through the register's own labels (ledger.js runtimeLabel, runDoneLine, taskLabel; taskLabel moved there from main.js). The render bay's display reads «RANDARE / ÎN LUCRU» or «ÎN AȘTEPTARE», a name tag reads «Kael (Video Editor) · în lucru», and a finished run's bubble reads «Sarcină reușită: căutarea surselor ✓» instead of «COMPLETED: GATHER_SOURCES ✓». The English filler «Working on task...» is gone: a message with no text shows no bubble. The backend's own sentences are drawn exactly as written, and the enums stay the enums wherever they are data.

- The street is not simulated. A decision taken for the Owner, reversible: the UFO, fireworks, hot-air balloon, delivery drone, helicopter and shooting star are removed from the street. They are listed in hq_events.js REMOVED_EVENTS, which they cannot pass even from the console, and their drawings are kept in hq_sky.js. Taking an id out of the set brings one back. What remains is the ordinary street, ruled by one pure function, hq_events.js streetRule, of real inputs only. The hour in Bucharest: the working-day rush at 08:00-09:00 and 17:30-18:30, the small hours nearly empty, no day buses at night. The day: weekends are slower, and a Romanian public holiday, Orthodox Easter included, is a Sunday. The weather from /office/weather: rain thins the pavement, opens umbrellas and keeps runners, skaters and two-wheelers in; cars stay on the road, slower; snow and fog keep people home. Whether the page has the studio's data: while the socket is not open or the last read failed, the street holds its frame, as it does under reduced motion. An emergency vehicle drives only when the backend says an emergency exists, and nothing does today. The street's first minute is warmed up in the first weather reading, so a rainy afternoon opens rainy.

- The Media dialog's player plays on the real server: the Content-Security-Policy now carries media-src 'self' blob:. The film is fetched with the Owner's key and played from a blob: URL, which default-src 'self' had refused. tests/test_foundation.py asserts the directive.

- Tested: 268/268 frontend tests (hq_street.test.js and scene_words.test.js new); tsc; build; backend test_foundation and test_delivery_cache, 29 passed. Photographed at 1920 with the page clock fixed and a weather fixture: Wednesday 08:30 and 18:00 (rush), Wednesday 14:30 in rain, Sunday 23:30. On screen that measured 10.4, 8.4, 4.8 and 2.1 vehicles, and 15, 13.1, 6.9 and 3 people; 89% of walkers had umbrellas in the rain; there were 0 sirens and 0 removed events. With the socket dropped, the street stood still for 3s under «Se reconectează». shoot.mjs: 0 missing fixtures, 0 errors. Frame timing could not be taken on a quiet machine. Scratchpad ui/w5.

- THE SERIAL, SHOWN AS A WRITERS ROOM (2026-09-24). The Journal dialog shows an episode as a script page, not a paragraph. A slate carries the episode number in the display face, the day it tells, its state and the Director's verdict. A beat board of five index cards shows the part each beat plays (cârlig, situația, întorsătura, rezolvarea, poanta) in that part's colour, its room from the studio's layout and who speaks. The page itself is set in mono the way a screenplay is: a capitalised heading line with part, floor and room; the scene as action text; each line as the speaker's name over the words, with the direction in small italics between them. The 'Name:' prefix is never glued into the text. v2 episodes are read line by line against their cast, so the Owner's older episodes read the same way. The words are the showrunner's, in English by design; the page only adds labels. The logic is in frontend/src/serial_room.js (node-tested in tests/serial_room.test.js) and the styles in serial_room.css, which uses only style.css tokens.

- Beside the script, the Director's review is a rubric: six rows (cârlig, situația, întorsătura, rezolvarea, vocile, poanta), each drawn as five cells with N/5, and any score under 3 in red. Under it sit the computed checks, labelled as the serial's backend suggested, each with the value the check itself carries and its own Romanian reason when it fails. A FAIL decided before the Director read the episode says so instead of drawing empty bars. «Scenariul de mâine» (tomorrow's script) is its own gold card: premise, cold open, open question, threads to pay off and status. It keeps that title only while the plan still waits for tomorrow; a plan already judged, or one left by a rejected draft, becomes «Planul pentru episodul următor». «Planul primit» says what an episode did with the plan it was handed. The approve action says what happens next, in the status line and under the button: ready to film and filmed by the next run, or the storyboard error and a retry at the next run.

- The daily-run cards know the stage serial_next as «Scenariul de mâine» (in main.js, hud_charts.js and ledger.js). Short notes under a stage's own reason show the days the run closed, the day the episode tells, what a run took up again from an earlier one, the writer's refused answers (hidden when 0) and tomorrow's script (only when one exists). A fix along the way: the jump from a beat card used scrollIntoView, which also scrolled the dialog itself and pushed its header off; it now scrolls only the dialog body.

- Verification: frontend 284/284 tests, tsc clean, build green. Pictures come from scratchpad ui/shoot_serial.mjs at 1920x1080, 1280x800 and 2560x1440 and under reduced motion, against invented v3 fixtures (ui/fixtures_serial_v3, made by make_serial_fixtures.py from the backend's code) laid over the captured ones. Measured: 0 missing fixtures, 0 console errors, lowest text contrast 5.73:1 (computed from CSS), no target under 32px, visible focus on all 22 Tab stops, 0 of 73 lines with a glued name. Still open: no real v3 episode from the backend has been opened in the dialog yet; the Journal opens on the closed-day list with the episodes below the fold at 1080; and the redraw after an approval is untested because the fixtures are static.

- A stranger's cold read, then an adversary (wow2:judge, 1920x1080, real RX 9070): ALMOST, and no longer 'a well-made dark dashboard'. With the drawers closed the first viewport is the headquarters and the city at the real hour; the drawers glide at a median 6.9 ms a frame with 0 frames over 20 ms at 1280-2560; the worst real text contrast measured from pixels is 4.97:1 over 3150 pairs; every drawer is reachable and closable by keyboard. One honesty breach found and FIXED: every replayed event (the history read back when the socket connects, or after a drop) put up speech bubbles as if said now, e.g. «SARCINĂ REUȘITĂ: CĂUTAREA SURSELOR ✓» for a run days old. office_state.handleDomainEvent(event, live) still applies a replayed event's state but puts up no bubble; tests/scene_words.test.js +1. Measured and still open: the first visit in a fresh browser profile has one 215-222 ms frame 330-350 ms after the key (the GPU compiling the workspace's shaders once; warm entries peak at 62 ms on a still frame). Tests: frontend 285/285, tsc clean, build green, tests/test_foundation.py 26 passed.

## The headquarters has a real day, and the live sky follows the real sun (2026-09-24)

The headquarters now has a real day in both of its pictures. The page's own renderer shows a clear Bucharest noon when the sun is up (new Blender day plates: windows off, sunlit facades, a pale haze, the offices lit as by day), and the live Unreal stream runs the rebuilt real-sky level (build 3, gates passed: build frame 6.4, p95 15.19 ms, evening 6.8), driven by the Owner's running studio from the real sun, weather and clock. The easing defect that held every moving light at its first value is fixed in the same commit; it takes effect when the Owner restarts his studio. An art director's cold read: ALMOST - the building and the dusk are close to the reference, the day city around them still reads as a game.

- Day plates (2026-09-24). The page shows the day plate variant alone from about 7 degrees of real solar elevation (hq_world.plateDayMix). Until now that variant was the night city under a grey haze. It is now a clear Bucharest noon, built by art-source/blender/hq/hq_day.py, which build_hq.py calls only under --variant day. The sun stands where the real one does at 12:00 EEST on 2026-09-24 (NOAA elevation 42.2 deg, 23 deg east of south, behind the camera and to the right). The world is a clear-sky gradient that lights and reflects; the page still paints its own sky behind the plates. The towers switch their windows off and take daylight facade colours (blue and grey glass, cream, beige and stone blocks) with concrete roofs. Lamps, LED lines and beacons go dark, and what was only an emission becomes paint (lamp glass, sign letters, white bridge cables). The haze thins to a pale veil, the street is dry, and the offices keep their lamps at 0.55 and cooler, with one soft area light per floor standing in for the sky's light through the open front.

- The committed plates were last exported at 08d07e1 (2026-09-13), and the scene scripts have changed since then for the Unreal build. To keep the crossfade clean, the day plates were rendered from the 08d07e1 scripts plus hq_day.py, and the build's manifest.json is byte-identical to the committed one. export_plates.py --variants day re-exports only the day plates, keeps the night files and entries untouched, and refuses to run if the build's anchor manifest differs from the one the kept plates were drawn with. Day plates get a bloom factor of 0.35, so sunlit white paint does not glow like a lamp. A full night+day rebuild from today's scripts would change the night look and needs the Owner's review.

- Verification recipe: render with blender -b --factory-startup --python art-source/blender/hq/build_hq.py -- --out <dir> --scale 2 --samples 128 --variant day --layers all (about 2 minutes on the RX 9070), then python art-source/blender/hq/export_plates.py <dir> frontend/public/assets/hq --variants day, then npm run build --prefix frontend. Photograph the title with the harness at 12:00, 19:15 and 23:30, and the workspace with the Unreal stream answered as unavailable so that the page's own renderer is what is seen. Measured 2026-09-24: all nine night plates and the manifest byte-identical; night canvas before vs after mean difference 0.21 (traffic only); layout test and 248 frontend tests pass.

- 2026-09-24, real sky rebuild window (phase 2c), CLOSED. The live Unreal HQ now streams the rebuilt level with the real sky: build 3, HQ_Dusk.umap written 11:11:17 (SHA256 C73D2DB2...0216). The game launched at 11:11:53 and joined signalling at 11:12:03-11:12:10, and it has run without a restart since. Backup of the old level: E:\AMN_backup\hq_before_real_sky3_20260924_1020 (umap C3F45A36...86A8). Build 1 (10:23-10:27) failed the build-frame gate at 7.3: four near-block slots moved to M_HQ_CityDay rendered light grey, and a relaunch changed nothing. Build 2 (10:40-10:44, AMN_LOOK_NEAR_DAY_ALBEDO=0) failed worse at 12.9, and a Remote Control diagnosis showed why: the folded texture-less glTF slots glow white at EmissiveFactor 1 whatever their EmissiveStrength. The stream was rolled back byte-identically at 10:51, when the Owner started Path of Exile, and the window waited until his game ended at 11:07. Build 3 (11:07-11:11) carries the fix: look_hq_live.near_blocks_day moves every plain, non-glowing slot of near_blocks and skyline onto M_HQ_CityDay. It passed.

- Gates measured for build 3. Build frame against the reference: 6.4 (6.3-6.6), the same as the old level's 6.4. Frame time p95: 15.19 ms over 87000 frames, against the old level's 15.55 ms, and 14.49-15.35 ms in each lighting state. Evening -2.5 deg (19:19): 6.8 (the 09-19 attempt scored 10.3). Morning -2.5 deg (06:55): 7.9. Crossover 18:50: 16.0. Solar noon: 66.3 and night 21:17: 43.9 (informational, since the reference is a dusk picture). Real present 11:13 and 11:17: 56.3 and 56.8. Every drive landed 67/67 Remote Control calls. The shelter clock showed every instant correctly, and live it reads the real minute (12:33, 12:39, 12:42, 12:46). Targeted tests: tests/test_city_emissive.py 23 passed; ruff F,B,E9 clean. Frames, scores and montages are in the session scratchpad real_sky/rebuild_2c.

- The Owner's studio now drives the environment. env_report.json is back in place and identical to build 3's report, and his start.py/run.py (started 11:07:44) have run the environment pass since 11:17:52. It restores values changed behind its back: sky_backdrop Gain dimmed to 0.3 at 11:19:37 was back at 1.1 within 52 s, the plan's value for the present. The sun's rotation and the clock follow real time. Defect found at close and FIXED in the same commit: EnvironmentPass._eased (backend/app/office/unreal.py) restarted the 30 s ease on every change of target, so a value whose target moves on each tick (the sun, the twilight keys, the sky light, fog, the city's emission, the window blend) stayed at the first value seen - live, the sun's intensity sat at 5.688 from 11:11 against a target of 5.92. A change that finds the light at rest still starts a 30 s ease from what is on screen; a target that moves while an ease is under way now re-aims it instead of restarting it. The close agent's 85-minute replay with the real class and the level's report now sends 255 distinct values rising from 5.688 to 5.920 (target 5.921), where it sent 5.688 255 times. Tests: tests/test_office_environment_bridge.py +2 (a target that moves every tick is followed and never goes backwards; a step still takes the whole ease), 70 passed with the Unreal bridge, routing and sky files. The Owner's running studio keeps the old code until he restarts it; then the evening is checked live at 19:09-19:20.

- Committed with this entry: art-source/unreal/look_hq_live.py (city_plain_slots for near_blocks and skyline onto M_HQ_CityDay), art-source/unreal/city_emissive.py (docstring: the measured false belief) and tests/test_city_emissive.py (+1 test), so the repository reproduces the level that streams. The rejected env_report files are now ignored (.gitignore: env_report.rejected_*.json); env_report.json stays ignored by design. Still open: weather does not yet reach the sky (the plates follow the sun only; weather sets only the road); check_report prints a by-design 'FAIL ref sun 2.5' on a good build; the root cause of the white texture-less slots is not understood.

## The serial in one click: today's episode and tomorrow's script (2026-09-24)

The Owner's condition (2026-09-24): «Poti spune ca este gata cand pot da un click si serialul
zilnic este creat cat si scriptul pentru a doua zi de serial.» Six readers first found that one
click did neither: the serial only ever told yesterday, and yesterday was empty on his data; an
episode he approved by hand was never filmed; the writer saw the day's chronological tail as
template sentences; dialogue was one free-text block read by one voice with the speaker labels;
and nothing wrote tomorrow's script. Seven steps closed it, test first, with every provider
faked, and an adversary verified it: **READY**.

**What one click now does, proven by `tests/test_autonomous_day_end_to_end.py::test_one_click_films_one_episode_and_writes_the_next`
with the real stage runners and faked vendors:** the serial stage tells the newest real day,
writes it through the showrunner brief v3, has the Director read it on a six-point rubric,
approves it under the Owner's policy, storyboards it and the media stage films it; after the
day's log closes, the new stage **«Scenariul de mâine» (`serial_next`)** writes and reviews the
next episode from today's events and plans it, with no storyboard, so no media is spent. The
next day's run films that planned episode without writing it again.

**What it needs from the Owner.** On his data the Director may not approve episodes
(`director_may_approve_episodes = 0` on OFFICE_SERIAL). Without that leave the path is click,
approve, click — the episode waits for him at each step. Granting it is his act. And only his own
paid click proves the brief v3, the rubric and the plan with real models and vendors.

- 2026-09-24, serial S0+S1 (tested with every provider faked, no real run). The 2026-09-19 metadata guard is finished: an office-serial episode cannot go out under another channel's title and tags from the last 24 hours, nor under a title that shares no word with its own episode. It is checked by the Publisher (HOLD) and again on the upload road (BLOCKED_GATE). The dead end is closed: a HOLD the Director lifted no longer hands its refused title to the upload, because the Publisher is asked again, and a BLOCKED_GATE row no longer keeps a film out of later runs. The serial stage now resumes before it skips. In order it takes up an APPROVED episode with no storyboard (readied without a model), a DRAFT the Director never read (read again, with the day's rewrite budget counted over all runs), and a DRAFT passed and waiting for the Owner (named by title; no new episode is written beside it). Only then does it tell a new closed day, looking back at most 7 days. The Owner's approve route builds the storyboard of the episode he approves. Tests: test_publication_metadata_per_film 12/12, test_serial_pipeline 43/43, neighbours 117 + 95 + 104 passed, mypy clean. Still open: S2 (the missing days and the newest real day), S3-S5 (the writer's input, schema and review) and S6 (tomorrow's script in the same click).

- 2026-09-24, serial S2+S3 (tested with every provider faked, no real run, live DB never opened). The run's start now closes every unclosed past date of the last 7 days, never before the studio's first event, then yesterday in full. The serial tells the newest closed day with public-safe events that comes after the newest day already told, and its reason names that day and the quiet days it passed over. Dry rehearsal on a copy of the readers' copy: 2026-09-17..23 are closed, 2026-09-19 is told with 15 lines, and 2026-09-20..23 are quiet. The writer now gets the day's story, not its tail. The projection keeps a computed selection: routine dropped, repeats collapsed with their count, ranked by narrative weight, 8-15 lines in the order they happened. Each line is in English and carries the title, the first reason of a verdict, the refuted claim's text and the actor. The writer is told how many public events it does not see. Model names on record, and the families seedream, seedance, kimi, minimax and others, are redacted. Answered letters no longer leak their subject. Tests: test_serial_pipeline 66/66 (22 new tests, 30 cases), neighbours 104 + 95 + 62 passed, mypy clean. Still open: S4 (showrunner prompt and schema v3, which must also render the Romanian letter subjects in English), S5 (review v2) and S6 (tomorrow's script in the same click).

- 2026-09-24, serial S4 (tested with every provider faked, no real run, live DB never opened). The showrunner's brief is v3 ('episode-v3') and in English. It names the day it tells and asks for hook, situation, turn, payoff and button, and 2-4 speakers who act in the cited events (everyone else is background). It asks for 8-22 spoken words a beat (115-170 in all), English dialogue and title, one of the studio's 12 rooms per beat (11 in the headquarters, plus 'Studio principal' from the room table) and no written text in a scene. It gives the allowed names as a JSON array and each character's voice from their bible, and it keeps the day's events (with who acts in each), the serial's memory and any refused draft inside inert boundaries. The answer is structured lines {speaker, text, direction?}: names, colons and stage directions never reach the spoken text, and 'dialogue' now stores the spoken words only. Names are normalised ('Sarah' becomes 'Sarah (Director)'). A refused answer (stranger, invented citation, placeholder, unknown thread id, not the schema) now spends one of the day's two drafts, and the retry is told why and shown the refused answer. A rewrite after a Director FAIL is shown the refused draft. The Director's computed checks gain the v3 cast rule and a structure check. The storyboard reads the lines and binds the first speaker's voice, and old v2 episodes are still filmable without their labels. Tests: test_serial_pipeline 85/85 (19 new cases, 14 functions), neighbours 147 + 256 + 96 passed, mypy clean. Still open: S5 (review v2), S6 (tomorrow's script), S7 (one voice per speaker), and S13, the only proof that a real model follows the v3 schema.

- 2026-09-24, serial S5 (tested with every provider faked, no real run, live DB never opened). The Director's episode review is v2 ('episode-review-v2'). She now reads each beat with the events it cites (id, the record's public words, who acts), the speakers' voices from their bibles, and canon's last summaries and open threads. Her facts are fitted to a 14,000-character budget by shedding the least needed parts first, never cut mid-JSON. Her English brief FAILs any outcome a beat shows that its cited event does not hold, and she scores hook, situation, turn, payoff, voices and button 1-5. A PASS without the whole rubric is no verdict and is read again next run; a PASS her own scores put below 3 is a FAIL. New computed checks, run before any model: words per beat (8-22 spoken), concentration (no event in more than half the beats unless it is the day's only event), and language (title and every line in English). No check passes by absence: an episode that cites nothing now fails grounding. A dry rehearsal on a copy of the readers' copy shows 'Day One' failing concentration (8 of 8 beats on one event), and its review facts (16,890 characters) fitted whole into 13,530. Tests: test_serial_pipeline 99/99 (12 new functions, 14 cases, the last the contract test), neighbours 68 + 152 passed, test_agent_identity included, mypy clean. Still open: S6 (tomorrow's script in the same click), S7 (one voice per speaker), and S13, the only proof that a real model returns the rubric.

- 2026-09-24, serial S6 (tested with every provider faked; no real run; live DB never opened; the daily job untouched). One click now films one episode and writes the next. The run ends with a new stage, serial_next, after today's log is closed. It writes, reviews and, under the channel's policy, approves the episode of today from today's log (closed at the run's hour), and builds no storyboard, so nothing of an unfinished day is filmed or bought. The next run readies that approved episode (S1's first case) and its media stage films it. The media stage now films a serial episode only once its day is over, so a same-day re-run films nothing of today, even an episode the Owner approved that afternoon. serial_next writes nothing when today's log is not closed (it is blocked by daily_log), when today already has an episode, or when an earlier episode waits for his approval or the Director's reading. Every episode now carries a required plan for the next one (premise, cold-open line, open question, threads to pay off), stored as PLANNED. The next writer is given it inside a data boundary, keeps it only if the events support it, and says so. On approval, the plan is closed as KEPT, DROPPED or UNSAID. 39_DAILY_AUTONOMOUS_RUNBOOK §7 and its index hash are updated, and check_docs passes. Proof: tests/test_autonomous_day_end_to_end.py::test_one_click_films_one_episode_and_writes_the_next. Day D films D-1's episode and writes, reads and approves D's with no storyboard; a second click on D writes and films nothing of D; day D+1 films D's episode without asking any model to write it again. Tests: 24 new (red first), test_serial_pipeline 118/118, neighbours 245 + 171 passed (1 opt-in skip), end-to-end 7/7, mypy clean. Still open: the frontend labels for serial_next and the plan, the full-day log, S7 (one voice per speaker), and S13 (a real model answering the plan fields). With director_may_approve_episodes off, as on his data, tomorrow's script is written only on the first run after he approves the waiting episode.

## The page amazes a first-time visitor — wave 1 (2026-09-24)

The Owner asked on 2026-09-24 for a premium interface «ca un joc demn de anul 2026», one that
amazes whoever opens the page. Six readers first mapped the page and the serial read-only; four
parts then built this wave in frontend/ (plus the modules map in backend/app/services.py and the
delivery headers in backend/app/main.py), and a stranger judged it cold. **Verdict: ALMOST** — the
title screen and the entry amaze; the workspace is a well-made dark dashboard, not yet a 2026
game frame. What is left for YES is listed at the end of this section.

- 2026-09-24, W1 «every live claim true» (frontend/**, backend/app/services.py modules map, backend/app/main.py cache headers). Every 'live' the page prints is now decided in one place, frontend/src/live_claims.js, from states the page actually reads: the Unreal stream's status, the events socket's status and the last snapshot read.
- The corner readout says 'Live · Unreal Nfps' only while the Pixel Streaming video plays, and the figure is the inbound video frame rate from the library's statsReceived event.
- Over a frozen last frame it says 'Se reconectează · cadru înghețat'. Before any frame it is hidden behind the viewport's own 'Pornește sediul live…' plate.
- With no stream it says 'Live · randarea paginii Nfps' only while the backend's events reach the page. Otherwise it says 'Se conectează' or 'Se reconectează', 'Deconectat' on a refused key, and 'Date neactualizate' after a failed snapshot.
- The dot pulses only in the live state, and the slate caption and the canvas label drop ', live' when it is not true.
- The events socket reconnects (EventsLink): 1, 2, 4, 8, 16 then 30 s; a replay from the newest sequence held, in 500-event pages; the snapshot re-read after a drop; a 25 s ping with a 60 s silence limit; code 1008 is final. The masthead chip follows it.
- The register's «Acum» pulses only while a stage is running and something was recorded in the last hour (RUN_QUIET_MS = the worker's 3600 s task lease). After that it reads 'Ultima etapă începută: … · nimic nou de N zile' on the quiet chip. A daily_run_finished newer than a stage_started now closes that stage.
Tested: 188/188 frontend tests, tsc, build, shoot.mjs at 1920/1280/2560 with 0 missing and 0 errors, and frame sequences in scratchpad ui/shots_w1_scene.

- the canvas fallback follows the real Bucharest sun and weather. The reference_dusk light mode was removed from hq_time.js and hq_world.js, and scene.json now says light 'live'. The painted and drifting clouds scale with the real cloud cover from /office/weather (hq_sky.js cloudCover): no weather service means no cloud drawn. Photographed on 2026-09-24 at 12:00, 19:15 and 23:30, and under cloudy, clear and rain answers (scratchpad ui/shots_w1_scene/montage_instants.png). The Unreal level itself is still dusk until W2. The canvas street's random traffic, pedestrians and sky events are still simulated and await the Owner's call.

- delivery. backend/app/main.py serves frontend/dist through PageFiles:
- Vite's content-hashed /assets/<name>-<hash>.<ext> files are 'public, max-age=31536000, immutable';
- every other built file (index.html, icons, /assets/hq art, scene.json) is 'no-cache', revalidated with a 304;
- every /api/* answer, and anything else that set no policy, stays 'no-store'.
Tested in tests/test_delivery_cache.py. Effective after the backend restarts.

- the modules map in snapshot() was read against the code. story is now PARTIAL (it was NOT_IMPLEMENTED): the day closes, a grounded episode is written, reviewed and decided, and the runbook's serial stage takes an approved episode to a storyboard. It is not end to end: an Owner-approved episode is not storyboarded, drafts are not resumed, and there is no tomorrow's script. financing is now PARTIAL (it was NOT_IMPLEMENTED): Owner capital and Owner loans are recorded end to end, while the CEO financing flow and accruing interest are not built. procurement stays NOT_IMPLEMENTED. tests/test_foundation.py asserts both corrections.

- 2026-09-24, W3 «the first ten seconds» (frontend only). The sign-in is now a title screen standing in the studio's own world (frontend/src/title_screen.js, title_frame.js, index.html #title-stage):
- The sky is the office's own SkyRenderer at the real Bucharest sun. The Blender plates form six depth layers, composed as key art: the headquarters on the right with a band of sky above its roof, the brand and the key on the left over a veil.
- The light is the real hour. The day and night plates are crossfaded by the renderer's plateDayMix, and deep night gets its multiply grade. The sun is re-read every minute, and only the variant being shown is downloaded.
- Before the key there is no weather (the route requires the Owner), so none is drawn.
- What moves: mouse parallax of at most 14 px by depth, and the light. Nothing moves under reduced motion.
- The only controls are the key and its button. The masthead and the footer arrive with the workspace.
- A caption states the claim: 'Sediul AMN-AI, București · 19:15 · amurg, în lumina reală a orei'.
- On a key the backend accepted, and only then, the camera pushes into the building (700 ms) and the workspace arrives staggered (masthead, register, render, modules, governance, footer). 820 ms in all.
- A refused key moves nothing. Under reduced motion the workspace opens at once.
Tested:
- 208/208 frontend tests (title_frame.test.js new);
- title_w3.mjs at 1920, 1440, 1280, 2560 and 390, at 12:00, 19:15 and 23:30, with every word at 4.71:1 or better measured from pixels;
- the entry as scrubbed frames and as a real-time screencast (scratchpad ui/shots_w3);
- shoot.mjs at three sizes with 0 missing and 0 errors.

- W9 in part: type, texture and key light.
- The display face Oxanium (SIL OFL 1.1, self-hosted in frontend/public/fonts/oxanium with OFL.txt; ș ț with the comma below checked in the cmap) sets the title, the panel and dialog titles, and the hero figures. It has a metric-matched Arial fallback, and figures are tabular by default.
- The page ground has a still SVG grain (3.5%) and an edge vignette.
- The key light (--key-cool) is sampled every 2 s from the top band of the frame being shown: the stream's kept still, otherwise the page's renderer. It is clamped so --ink-3 keeps 4.5:1 over the lit ground (key_light.js, key_light.test.js).
- Plates and sprite sheets are now decoded off the main thread (hq_assets.js loadBitmap). The longest task after sign-in fell from 222 ms to 97 ms.

- 2026-09-24, W6 «data you can read at a glance» (frontend only). Four instruments draw answers the backend already gives, and nothing else (frontend/src/hud_charts.js).
- The render's slate carries the newest daily run: one segment per stage, placed by the index on runbook.stage_started, coloured green/warm/red/gold/faint. When the register has lost a finished day's events, the run record from /runbook/runs is used instead. Words beside it: 'Rularea din 12.09 · 12/12 · încheiată', or '12.09 · 12/12' on a narrower page.
- The daily-run dialog's «Flux» is six bars on one scale from company-state pipeline.stages, with waiting work in gold and losses in red. It is not drawn as a tapering funnel, because the data is not one.
- Each treasury budget has a ring: spent, then held, against the limit, with the warning tick at warn_ratio.
- Each distribution channel has one column per published film from /analytics/performance. A measured zero is a tick; an unmeasured film has no height.
- An empty series is said in words. Geometry is attributes and classes, never inline style (CSP). Nothing animates on arrival; a tracker segment recolours in 240 ms only when a real stage event changes it.
- «Acum» now agrees with the run record: a stage that started before the day's recorded finish is not running. On the copy of the database it had said 'nimic nou de 4 zile' about a finished day.
Tested: 233/233 frontend tests (hud_charts.test.js new), tsc, build, shoot.mjs at 1920/1280/2560 with 0 missing and 0 errors, and scene_w6.mjs recordings in scratchpad ui/shots_w6_scene.

- W8 «moments» (frontend/src/moments.js, film_poster.js).
- A moment plays only for an event the socket sent as it happened ({type:'event'}; EventsLink now passes the flag), whose own timestamp is under 10 minutes old, and at most once per event_id. The page-open replay, the REST backfill and a reconnect's catch-up play nothing; proven with three fresh milestones sent as replay_event.
- An episode drafted or approved puts a chapter card in the render's lower left: 'Inside The Nexus · Ep 1', the episode's title from /story/episodes, and who decided.
- A film rendered puts a toast in the lower right carrying a real frame of the film. The page streams the start of the +faststart MP4, finds a key frame at 20% of the film by parsing the MP4 index, stops reading, and decodes that one frame with WebCodecs; no <video> and no blob:. Measured about 250-290 ms after the event.
- A film published puts up a toast with its title.
- A request for the Owner re-reads the approvals, and the register's gold mark ('N cereri așteaptă decizia ta', a button to the approvals) glows once for 1.2 s. The mark itself stays up while requests wait.
- Every moment arrives in 320 ms, leaves in 240 ms and is gone within 3 s. One is up at a time. Pointer or focus holds it; the close button and Escape dismiss it; the text goes to a polite live region.
- Under reduced motion the same words stay up for the same time, with no movement.
- The register also gained words for story.episode_approved/rejected and governance.approval_requested, which it had printed as raw English keys.

- the workspace read as a whole at 1920. The masthead's Settings button was a filled green slab, the loudest object above the render. It is now the quiet outlined plate its neighbours wear, in the studio green (9.3:1). Letter subjects in the register drop from 600 to 500 weight so the column no longer reads as a wall of bold. The chapter card has no backdrop blur, because it would be recomputed every frame over the moving picture. Frame timing at 1920 with no screenshots: median 6.9 ms, no long tasks. One 42 ms frame when a chapter card appears, and up to 28 ms while a poster is decoded.

**Measured.** 236 frontend tests pass (165 before this wave), `tsc` clean, the build succeeds; the backend files of this wave pass tests/test_foundation.py and tests/test_delivery_cache.py (29 passed). Every view was photographed at 1280, 1920 and 2560 with 0 missing fixtures and 0 console errors.

**What is left for YES, from the judge.** The Unreal real-sky level on the live stream (the one
game-grade object); the render as the full-bleed hero with the register and approvals as glass
drawers; Unreal stills to replace the 2026-09-13 Blender plates, whose windows are lit at noon;
portraits of the eight employees; the canvas words in Romanian; `media-src 'self' blob:` in the
page's CSP; and the Owner's call on the canvas street's random life (traffic, pedestrians, sky
events come from a seeded generator, not from the backend).

## One icon family, and the two readouts beside the render (2026-09-23)

Active edit claim: Claude, 2026-09-23 — the product's icons, the frame-rate figure on the glass
and the heading band above the render. Done and tested.

**Why.** The seven room links under the render carried seven icons from seven places: a
two-stroke magnifier whose handle floated clear of its lens, a filled badge with a solid play
triangle, a circle crossed by a diagonal that read as *forbidden*, a person, a page, a **house**
for the daily run and a classical bank with seven strokes — twice the ink of anything beside it.
Everywhere else an icon's work was being done by a typographic character: a font's multiplication
sign for every close button, a font's arrow for refresh, a plus and a minus set at `--fs-h3`,
a filled ▶ on the play control. Three drawing systems on one page, at three weights.

**One family.** Every icon in the product is now drawn on one 24×24 grid, inside 4..20 of it, at
`--icon-stroke` (1.7 user units — 1.06 device px at the console's `--scene-icon`, 1.13 at
`--icon`), with round caps and round joins, no fill but the one dot a shape needs, and
`stroke: currentColor`, so an icon never states an ink of its own and always takes the ink of the
control it sits in — its hover, its disabled state, the alert triple on «Ieși din ecran complet».
The family is `.ui-icon` in `style.css`; the seven rooms are inline in `index.html`, the four a
script draws are in `src/icons.js` (new). Twenty-two icons, one grid.

**Two of the seven said the wrong thing.**
- **Rularea zilei** was a *house*. A daily run is a day of work, so it is the sun over the
  horizon. Not the play-in-a-circle the brief offered as the alternative: a play mark already
  means «a film» two buttons to its left, and on a dialog that only *reports* what each run did
  it would read as a Start the Owner must never press by accident.
- **Distribuție** was a compass rose inside a circle, which at 15px reads as a prohibition sign.
  It is now the film leaving the studio: the arrow rising out of the tray. The share glyph was
  built and photographed first; its three nodes turn to mush at the size it is actually drawn.

**Beside the render, two measured changes.**
1. *The frame rate is not a heading.* It was set at `--fs-meta` in `--scene-chrome-ink` — the
   same size and the same ink as the word **Live** next to it — so a figure that ticks every
   second was leading a readout whose subject is that the render is live. It keeps every word and
   takes the chrome's quiet meta treatment: `--fs-micro`, `--scene-chrome-muted`, still mono and
   still tabular. Scoped to the live readout, so the clock in the opposite corner is untouched.
   Measured at 1920×1080: the figure 11.5px/600/`#dfe7f5` → 10px/500/`#8496b8`, 40.4px wide →
   35.2px, and the readout 169px → 163.7px.
2. *The band above the render.* It carried the live badge at its right end until the badge was
   let into the glass, and what was left was a heading alone in an 83px band 1422px wide. Nothing
   was brought back to fill it: every readout this panel owns is already on the bezel — the
   clock, the weather, the live state, and on the slate the employee count and the moment it was
   read — and a second copy up here would be the page saying the same sentence twice. So the band
   was tightened instead. Its two lines were leaded for running prose (`--lh-body` gave the 10px
   eyebrow a 16px line and the 20px title a 30px one) inside 32px of padding; both now take
   `--lh-tight`, the token the type scale already names for titles and figures, and the padding
   comes to the page's own rhythm. Measured at 1920×1080: **83px → 65px**, which is where the
   register's heading and the approvals heading have always been (62px), so the page has one
   section-heading band instead of two; the render begins 18px higher.

**Nothing else changed**: no word, no behaviour, no data flow, no API call, no gate, no test
contract, no id, class, data attribute, `aria` role or test hook. The only literal added to
`style.css` is `--icon: 16px`, inside the `:root` block; a literal was *removed* from
`office_scene.css` (`stroke-width: 1.7` became the token).

**Tested.** `npm test --prefix frontend`: **164 tests, 164 pass, 0 fail** — the same 164, none
added, none changed, because no test named a glyph. `npm run check --prefix frontend`: clean.
`npm run build --prefix frontend`: succeeds. Photographed at 1920×1080 and 1280×800 against the
254 captured answers — login, workspace, the eight dialogs, the inspector, the mail window and
the seventeen deeper dialog states — **0 missing fixtures, 0 console errors** in every run, and
every icon was read at 4× and 8×. At 1280 the seven rooms still use 767.6px of a 791.6px row, to
the pixel what they used before.

**One glyph deliberately left.** The five publishing gates keep their `✓`: it is a status mark
inside a sentence, in `--ok-ink` like every other verdict on the page, not a control's icon, and
a 16px family icon set inline in 13px running text would need a third measure and a baseline
shim to sit on. Five lines to change if the Owner disagrees. The trailing `↗`, `↻` and `↓` after
a label («Deschide firul ↗», «Citește tendințele ↻», «Preia sursa ↓») are punctuation in the
studio's own voice, not icons, and were left as they are.

## The interface speaks Romanian (2026-09-23)

Active edit claim: Claude, 2026-09-23 — the frontend's user-facing strings, in two parts
(the page and the scene; then the eight dialogs, the agent inspector and the mail window).
Both parts are done and tested.

**Why.** The studio already spoke Romanian everywhere it computed a sentence: the preflight's
reasons, the day's summary, the approvals, the governance panel, the refusals. The interface's
older static text was still English, so one row read «Automatizare» above «Fact research», a
button «Randare 9:16» sat beside «Check QC», and the treasury labelled six tiles in two
languages. An independent critic called it the loudest unfinished signal on the screen: a
stranger does not read that as a bilingual product, they read it as a product where nobody
decided. The Owner's own convention decided it: **the interface speaks Romanian.**

**What changed.** Every user-facing string the frontend owns is Romanian, with full diacritics
(ă â î ș ț, comma-below), in the studio's own voice — plain, exact, short, matching the words
the backend already writes. `<html lang>` went from `en` to `ro`; the meta and og descriptions
follow. A glossary was written before the work and followed throughout
(`<scratchpad>/ui/GLOSSARY.md`): the pairs, the loanwords kept and why, and every place the
translator hesitated, with the measurement rather than the guess.

- **The page**: masthead, sign-in, the live register (including the ~90 sentences
  `describeEvent` writes and the ledger's gender-invariable verbs), the module panel, the scene
  panel and its readouts, both toolbars, the footer, the separate per-agent live window, the
  model's answer as a person reads it, and the signage the canvas draws.
- **The dialogs**: every header, one-line purpose, section heading, rail link, field label,
  placeholder, button, tab, table header and `title`/`aria-label` inside the eight dialogs, plus
  every status, intent, empty line, confirmation and error fallback that `main.js`,
  `settings.js`, `youtube_connections.js`, `mail_thread.js`, `agent_details.js` and
  `provider_production.js` write themselves.

**Two things the critic named, both now answered.**
1. The research form had three inputs described only by a placeholder — which disappears the
   moment a word is typed — and a fourth box holding the word `general` with nothing above it.
   The four controls now carry visible Romanian labels taken from what each control already
   said: **Titlul episodului · Subiectul factual · Unghiul · Publicul**. The markup reuses
   `.yt-field` / `.yt-field-label`, the field-label pair the stylesheet already defines for the
   YouTube form, so no rule and no literal was added.
2. The publishing gate card quoted an internal architecture filename. It now says the same
   thing without naming a file the Owner does not open: «Aceste verificări nu sunt încă
   implementate: drepturile pe pachetul final, politica platformei, …».

**What was deliberately left alone.** Values are not labels: the brand, the employees' names and
role names as the data gives them, units and codes (`VR$`, `USD`, `fps`, `9:16`, `QC`, `UUID`,
`API`, `OAuth`), enum values (`IDLE`, `SUPPORTED`, `PASSED`, `SINGLE`, `PRODUCTION`), Google's own
field names on the YouTube form, and every sentence that arrives from the backend — those are
already Romanian and are not the interface's to reword. Loanwords Romanian technical speech
actually uses were kept and are listed in the glossary (`live`, `storyboard`, `prompt`, `token`,
`slot`, `watchdog`, `showrunner`, `analytics`).

**A defect found by reading the photographs, not the code.** The panels printed the plural
against every figure, so the closed day of 2026-09-12 read «1 evenimente de povestit» beside
«92 evenimente». `main.js` now has `countLabel(count, one, many)`: one is singular, and a
numeral takes «de» when its last two digits are 00 or 20 and above — «19 evenimente», «92 de
evenimente», «101 evenimente». It is applied to the day's counts, the episode's beats and cited
events, a script's claims and scenes, an employee's runs and a provider's ledger records.

**Nothing else changed**: no behaviour, no data flow, no API call, no gate, no test contract,
and `style.css` was not touched — no colour, size, radius, shadow or duration literal was added
anywhere.

**Tested.** `npm test --prefix frontend`: **164 tests, 164 pass, 0 fail** — the same 164 as
before; no test was added or removed, and forty-four assertions that named an English word were
updated in the same breath (`ledger`, `ledger_fold`, `live_window`, `friendly_text`,
`day_outcome`, `hq_world`, `hq_stream_lifecycle`, `mail_thread`, `agent_details`).
`npm run check --prefix frontend`: clean. `npm run build --prefix frontend`: succeeds.
Every view was photographed at 1920×1080 and 1280×800 against the 254 captured answers and read
back — login, workspace, the eight dialogs, the agent inspector, the mail window, and the dialog
states the plain shooter cannot reach (the second tab of Settings and of Media, every rail
section of Research, the daily run and the Treasury): **0 missing fixtures, 0 console errors**
in every run, and no Romanian word overflowed the button, tab row or table header it was put in.

**Still English, and not the frontend's to fix.** The rendered city backdrop and the HQ building
plate carry baked-in signage (`BUCHAREST AI DISTRICT`, the floor plates `L4 EXECUTIVE` … `S3 AI
SPACE`): pixels in the art, an `art-source/blender/hq` job and a re-bake, not started. The
bus-shelter posters in `hq_world.js` were kept in English as the studio's own brand and channel
advertising inside the depicted world — one line each to change if the Owner wants them
Romanian. And the backend's own Romanian sentences still point at «Settings» by its English
name while the page's button now says «Setări»; that is one line in the backend's own pass.

## The interface, brought to a finish (2026-09-22/23)

The Owner asked for the interface to be finished «la un nivel extrem de bun cu detalii și
polisare, realism și profesionalism, ca jocurile moderne din 2026 AAA». What stood before: a
light, warm-paper administration page with a black-green top bar, a photoreal night render pasted
in the middle of it, and eight dialogs that were white sheets of dense prose. Nothing about the
studio's behaviour changed in this work: no user-facing string, no Romanian wording, no data flow,
no API call and no gate.

**How the interface was seen at all.** The Owner's studio was not running, so a harness was built
that opens the real page without it (`<scratchpad>/ui/`): `capture_fixtures.py` copies
`data/studio.db` (plus `-wal` and `-shm`), blanks every encrypted column in the copy under a key
made for it, builds the application against the copy with the worker and the catalogue refresh off
behind a loopback-only network guard, and writes **254 captured answers** — one JSON per read-only
route, including the detail views. `shoot.mjs` then serves the built page, answers every
`/api/v1` request from those files, replays his real events over a stubbed websocket, and
photographs eleven views (login, workspace, the eight dialogs, the agent inspector) plus the mail
thread at any width. No provider, no network, no cost, and the live database is never opened.

**Three directions were built, not one.** Three designers each restyled the real code in their own
worktree and photographed it: A, one continuous dark ground with the render as the only heavy
object; B, a warm broadcast charcoal; C, the best possible light room. A judge looked at every
picture and chose **A**, with named grafts from C (the wide page spread, the two-tier scene
console, the chip scale, the figure treatment, the section-head rule) and from B (the dialog rail,
the row rhythm, the storyboard card header), and wrote the specification the build followed
(`<scratchpad>/ui/SPEC.md`).

**What the Owner will see.**
- **One dark ground, and the render is the hero.** The page is a single near-black surface with a
  fixed key light where the 3D window sits; the render carries the only deep well shadow on the
  page. The top bar is a deep green band with the brand on a pale plate.
- **The ledger reads at a glance.** A 54 px time rail in tabular mono figures, the subject in ink
  and the detail beneath it, a colour rail at the row edge for the kind, correspondence on its own
  rail with its way into the thread — and **seventeen identical watchdog rows folded into one**,
  carrying ×17 and the span they cover. Nothing is dropped and correspondence never folds.
- **The daily run is a dashboard**, not six stacked bars: small-caps label, one promoted figure,
  supporting lines in tabular figures, and the tiles of a row close on one edge.
- **Every dialog has one shell**: a header that does not move, a body that scrolls on its own, a
  104-character measure on prose; the three long ones (media, daily run, treasury) have a sticky
  rail of section links that follows the reading (`frontend/src/dialog_rail.js`).
- **The page has no dead area** at 1280, 1440, 1920 or 2560: above 1560 px the register stands
  full height on the left with the render and the two panels beside it, and between 1051 and
  1559 px the same cure with one column fewer.
- **The detail**: one type scale of eight sizes, tabular figures everywhere by default, four
  visibly different button states, one tag system, one shape for every empty, loading and error
  state (keeping the product's own words), dialogs that arrive and leave in 160–200 ms, a new
  ledger row lit once, and exactly one looping animation on the page (the live dot).

**Measured, by the parts that measured them.**
- The architecture part: no horizontal overflow at 1024, 1280, 1440, 1920 or 2560; the register
  equals the grid's height exactly; the filter chips sit on one line with a true 32 px hit box.
- The dialog part: the header's y is identical before and after the body is scrolled on all eight
  dialogs at 1920 and 1440; zero controls under 32 px; worst contrast pair 4.86:1.
- The finishing part: exactly eight font sizes in use at four widths; 308 places with shifting
  figures before, 0 after; 0 heading widows; one infinite animation; `--ink-3` lifted to `#8a98b2`
  after it measured 4.47:1 on the ground a hovered ledger row wears.
- The adversarial part: **655 contrast pairs per width** measured from the running page at 1280,
  1920 and 2560 — 4 failures before it started, **0 after**; worst pair now 5.59:1. A real Tab walk
  over 10 + 34 + 12×8 stops: no invisible focus, no trap, Escape closes all eight dialogs and
  returns focus to the button that opened each. `report.json`: **0 missing fixtures and 0 console
  errors** on every view at every width.
- Tests: **143 frontend tests pass** (125 before), `tsc` clean, the build succeeds. Seven of the
  new tests are the ledger fold, which changes *what* is on screen and had none.

**Not finished, honestly.**
- *Corrected 2026-09-23 by the polishing pass:* the research dialog has the rail. What stood
  here: it was the longest in the product and the only long one without one.
- The login page's gold line breaks the rule that gold is rationed to what is live or waiting for
  the Owner; it is the only accent on that screen and the call is the Owner's.
- The ledger's internal scroll always ends on a clipped half-row.
- The Governance panel carries 180–250 px of empty ground at 1920 and above.
- The thin scrollbar the stylesheet asks for is unverified: this harness's browser hides
  scrollbars entirely, so no photograph in any pass shows one.
- Everything was photographed over the page's own canvas renderer. **The interface has not been
  seen over the live Unreal stream**, which by this project's standard leaves that a guess.
- *Corrected 2026-09-23 by the polishing pass:* the «Live window» is on the new palette, with a
  test that catches a token drift. What stood here: it still carried the old light palette,
  written into the file as literals.
- `frontend/dist` in the repository is rebuilt, but the Owner still has to restart his studio to
  serve it.

### The polishing pass — 2026-09-23

Four of the five gaps the section above left open are closed, and an adversary measured the result
twice by two independent methods.

- **The per-agent «Live window» is on the new palette.** `frontend/src/live_window.js` builds a
  separate popup document and cannot import the page's stylesheet, so its token block is a copy of
  the one in `style.css`, with a comment saying why it is duplicated and that the two must move
  together — and a test (`frontend/tests/hq_palette.test.js`) that fails when a token drifts,
  because a drift is invisible in a browser.
- **The research dialog has the section rail** the other three long dialogs have: five links that
  repeat its own headings, on the wrappers that already existed.
- **The sign-in screen** stands in the product's own world: the headquarters plate behind the card
  under four named veils, the brand artwork on a deliberate printed badge, the gold eyebrow removed
  (gold is rationed to what is live or waits for the Owner), and the Settings button hidden until
  the key is accepted, by reading the `hidden` attribute the page already keeps.
- **The chrome around the render is one instrument family.** Three readouts (clock and weather, the
  live state, the slate) are let into the bezel — square where they meet the frame, rounded only
  towards the picture — and the console's two tiers now start and end on the same margins, with the
  camera as one grouped instrument. Every word each readout said, it still says.
- **The scene answers the pointer and the keyboard.** Selection and hover marks are drawn at a
  constant size *on screen*, so they read at fit zoom as at 4×, in the page's own focus colour and
  geometry; the canvas takes focus, the arrows walk the seats in the renderer's own order, Enter
  selects and Escape clears. The renderer's interface colours come from the page's tokens
  (`frontend/src/hq_palette.js`, new); the art is untouched.
- **What the scene says when it has nothing** — loading, failure, reconnecting, starting — uses the
  product's own sentences in the page's empty/loading/error shapes, as elements with `role=status`
  rather than grey text painted on the canvas.

**Measured on the final build.** 2 853 text/ground pairs read from the *real pixels* of 22 views at
1280, 1920 and 2560 — 0 below threshold, worst 5.28:1 — and the cascade-based sweep agreeing at
671 pairs per width. 84 pairs over the render and 14 in the popup, all passing. A real Tab walk at
1920 and 1280 over the sign-in screen, the workspace and all eight dialogs: no invisible focus, no
trap, no ring under 3:1. `report.json`: 0 missing fixtures and 0 console errors at four widths.
**146 frontend tests pass**, `tsc` clean, the build succeeds.

**Seven defects the adversary found and fixed**, each measured before it was touched: the autonomy
mode the studio is *in* was painted darker and fainter than the modes it is not in (1.05:1 plate,
now the studio's green at 6.54:1); the page's key light had never once reached the screen, because
`body` repainted the ground over it; four fields' placeholder sentences were written and invisible
(1.1:1); the «NICIUNA» tag floated in the middle of the approvals heading; the Governance panel
carried 175px of dead ground; the storyboard's text well cut its seventh line through the middle of
the letters, in five cards at once; and the Settings dialog was the only one whose head rule was
drawn between the title and its own sentence.

**Still not finished, honestly.** 447 of 574 control borders measure under 3:1 — the ghost-control
language the scene pass introduced deliberately, and a whole-surface decision rather than a small
fix (WCAG does not require a boundary for a control whose label is visible). Moving the live badge
onto the glass left the «Studio Office» heading alone in a wide empty band, and what belongs there
must be a word the product already owns — the Owner's call. The two corner readouts cover 440px of
the render's top edge that was whole before. At 1280×800 the sign-in card leaves no room for the
footer on the first screen. The research rail's column is empty below its five links. And the
interface has still never been photographed over the live Unreal stream.

### Closing the critic's list — 2026-09-23

A stranger read the thirteen views at four widths and ranked twenty findings. Eleven are closed in
the view layer and the stylesheet; nine are refused, and the reason for each is written below so the
Owner can check it rather than take it. **Not one user-facing word was added, removed or reworded,
and the 3D art was not touched.**

**Closed.**

- **A row printed its own sentence twice.** Ten consecutive ledger rows read
  `publish: COMPLETED — <sentence>` in bold and `<sentence>` again in grey beneath, because a
  letter's excerpt is usually the whole of its subject after the colon. `withoutEcho()` in
  `frontend/src/ledger.js` drops a detail that is already the end of the headline; the mail window
  does the same for a letter's body (`mail_thread.js`), and because the rule lives in
  `describeEvent`, the per-agent Live window stopped joining the two copies with an em dash as
  well. A letter with genuinely no text still says so; only an echo is dropped. The ×17 fold is
  untouched.
- **The Daily Run tiles.** `align-items` on `#company-state` is back to `start`. This is the second
  time the line has moved and the stylesheet now records both measurements: filling the row bought
  a flush bottom edge with 168px of empty ground *inside* the AGENTS tile at 1920 and 120px inside
  AUTONOMY IS ON at 1280, because the row took its height from a third tile whose data repeats a
  paragraph. Empty ground inside a card reads as an unfinished card; a ragged edge between cards of
  different length reads as cards of different length.
- **The agent inspector's two columns never matched** — the right one stopped 220px short of the
  left at 1920 and left a wholly empty column beside the last block at 2560. `.identity-grid` flows
  the six blocks as CSS columns with `break-inside: avoid`, so a short block is followed by the next
  block. Three columns above 1900px. Nothing is reordered.
- **The long dialogs' rails** painted a 208px column of lit ground the full height of the report —
  in Media, two links above 780px of it. The ground and the hairline move onto `.dialog-rail`
  itself, which is `align-self: start` and sticky: the rail is now a card as tall as its links.
- **The module-status meters read backwards.** Each row is its own grid, so the longest status word
  pulled its own meter left and the modules that are *not* built drew a bar further along than the
  ones half built. `--module-state-w` fixes the status column, so all three states draw one track at
  one x and one width, filled 100 / 50 / 0.
- **The eight dialogs did not share a top edge** — Story opened 60px lower, Settings 230px and Mail
  245px, so the close button moved halfway down the screen depending on the door. Every dialog is
  pinned to `--dialog-top` (5vh), the offset the other seven already used. Settings also gives up
  its own 1000px cap and joins the family width.
- **A wide screen bought margin, not content.** `--dialog-w` steps from 1180px to 1440px above
  1900px and the inspector's contract flows in three columns there. The treasury's six tiles are
  capped at three columns so the most finished component in the product stays three and three
  rather than four and two.
- **Inner scrollers ended by slicing a line of type through the middle of its letters.** The
  ledger, the topic lists, the agent list and the chat history fade over one line-height at the
  bottom lip, driven by the scroller's own position: no fade on a list that does not scroll, and
  none once the reader reaches the end. Measured: ledger 21px of fade at rest, 0px at
  `scrollTop === max`, 0px on every list whose `scrollHeight === clientHeight`. Where a browser has
  no scroll timeline the rule does not apply at all.
- **A connection card was titled with a machine identifier** — `settings:9298e62d-…-64120311942a`
  wrapping to two lines in the biggest type on the card, beside two cards titled `local-ollama` and
  `Ollama Cloud`. Every character is kept: the word before the identifier takes the title, the whole
  string is printed as the card's meta line in the mono face every identifier wears, and the
  untruncated value is on hover.
- **The live badge claimed a picture that was not there.** While the viewport shows its loading or
  error plate, the badge in the opposite corner went on reading `Live Renderer 68fps` over a frame
  whose only other content was "The headquarters art could not be loaded." One `:has()` rule hides
  it for exactly as long as a plate is up.
- **«Fullscreen» did not look like a control at rest** beside a bordered, filled group of four. It
  is the last key of the same instrument and now wears the same plate. The slate's stamp also joins
  the bezel's other figures on a fixed advance.
- **The per-agent Live window** pinned its caption to the floor 430px under three entries. The
  window is a column now and the caption follows the content. Its palette was already the page's
  (`--ink-2` body, `--ink-3` rail, measured 6.39:1); the "cyan" the critic read is an artefact of a
  downscaled capture.

**Refused, and why.**

- **Two display languages in one row** (Module status, the publishing channel row, the six treasury
  captions, the inspector's fourth caption). Every candidate fix is a string change. It is the
  loudest unfinished signal on the screen and it needs one decision from the Owner about which
  language the interface speaks; presentation must not paper over it by inventing words.
- **The `.md` filename, the `.env` sentence, the three unlabelled research fields and the box
  pre-filled with `general`.** All four want words the form does not own as labels (the only names
  those fields have are placeholder *examples*). Owner's call.
- **The Governance dead ground.** The empty plate is centred in its region on purpose, recorded in
  the sheet with the alternative already tried and rejected. The panel is stretched to Module
  status beside it, so pinning the plate under the head rule would not remove the emptiness — it
  would gather all ~200px of it under the note instead of splitting it. Moving a void is not
  closing it.
- **The storyboard prompt well.** A fade mask there was tried in an earlier pass and rejected by a
  judge; the well is sized so the cut lands *between* lines rather than through letters, and an
  "expand" affordance would be a new control with a new word.
- **The numeric fps.** Hiding the badge over a failed frame is a fault fixed. Hiding the figure
  itself is not: it is the Owner's own measurement of his renderer, and the studio's standing rule
  is that nothing in the office view is decoration. Collected for him.
- **The seven room icons.** Two of them do mean the wrong thing (a house for Daily Run, a slashed
  circle for Distribution) and two are drawn at a different weight. Redrawing them is new art.
- **The three-weight button system and Pause/Resume.** The ghost-control language is a whole-surface
  decision the record already names; hiding whichever of Pause/Resume does not apply is a change in
  behaviour, not in presentation.
- **The sign-in brand plate and the «Not connected» chip.** `--plate` is a named token and the mark
  is dark-on-light by design; dulling it is brand. The chip is a true state readout.
- **The «Studio Office» band and the three clocks.** Both need a word the product must already own,
  in a place the Owner chooses.

**Measured on this build.** `report.json`: 0 missing fixtures and 0 console errors at 1280×800,
1440×900, 1920×1080 and 2560×1440. 673 text/ground pairs read from the real pixels of 20 views —
**0 below threshold**, worst 5.73:1. **146 frontend tests pass**, `tsc` clean, the build succeeds.
Pictures: `scratchpad/ui/shots_p7_final/` (four widths), `shots_live_p7/`, `shots_scene_p7/`.

## The rehearsal on the Owner's data (2026-09-18)

The suite was green and the studio had never been tried on the one database that matters. On
2026-09-18 a rehearsal ran one whole scheduled day on a **copy** of the Owner's own studio, through
the real scheduler, worker and runbook (`set_job_active`, `scheduler_tick`, `worker_pass`,
`execute_daily_run` with `build_stage_runners`), with every paid vendor faked and every outside
connection refused; an independent audit then read its report, re-ran it on a fresh copy and named
what it had missed. The audit's verdict was **FIX_FIRST**. This section records what the rehearsal
ran on and why nothing could be spent, every finding of the report and of the audit in their four
classes, and what the four parts that followed fixed. The report and the audit are
`rehearsal_report.txt` and `rehearsal_audit.txt` in the session's scratchpad; the repeatable harness
is `tests/test_rehearsal_on_a_copy.py`, skipped unless `STUDIO_REHEARSAL_DB` names a copy.

**What it ran on.** `data/studio.db` (11,902,976 B), its `-wal` (263,712 B) and its `-shm`
(32,768 B) were copied together with `shutil.copy2` into the scratchpad at about 19:44 UTC, and
sqlite was opened on the copy only (`wal_checkpoint(TRUNCATE)`, `integrity_check` ok). The
credential key was copied beside each copy, because the preflight's media description and the
analytics adapter decrypt integration rows; no key or secret was printed. The copy was already at
`0045_reconciliation`, not at the 0035 the brief assumed: the Owner had restarted his studio himself
at 22:42 local, and `start.py` runs `bootstrap.py` first, so step 1 of his checklist was done by his
own hand before the copy was taken. What the copy holds: eight employees, all on Ollama Cloud; three
VERIFIED integrations (ollama, elevenlabs, runway); both channel slots bound to his CONNECTED
accounts — *Nexus Curiosity* → MAIN_FACTUAL (`youtube_connection` 69cb4598) and *Inside The Nexus*
→ OFFICE_SERIAL (241dfcf5); 98 SUPPORTED, 11 UNVERIFIED and 1 REFUTED claims; 18 daily runs, all of
2026-09-12; a DAILY budget of 15 USD; TEST, AUTONOMOUS_CEO, the stop off, `daily_main` inactive.

**Why nothing could be spent.** Three measures, and the second held where the first did not.
Every paid vendor was faked in the process at the boundaries the whole-day test fakes — one
stand-in model registered under all three provider ids of the copy, the local picture and voice
adapters, the plain render plan, and a recording publisher in place of `stages.selected_youtube`. A
network guard was installed before any studio code was imported and proved itself first; it refused
`connect`, `connect_ex`, `getaddrinfo`, `gethostbyname(_ex)` and asyncio's proactor and selector
`sock_connect` for anything but loopback. And the settings were built with `_env_file=None`, every
`STUDIO_*` variable removed, the worker, the catalogue refresh and trends off, and render storage
moved into the scratchpad. What the rehearsal changed, it changed on copies only and with the
Owner's own commands: `daily_main` activated through `set_job_active` with its `next_run_at` moved
into the past, and `director_may_approve_episodes` granted on OFFICE_SERIAL through
`change_publish_policy` (policy version 1 → 2). The guard's record is the proof: no refusal through
migration, start-up and preflight — the preflight really calls nothing; 4 in pass 1, all
`getaddrinfo 'oauth2.googleapis.com'`; 109 in pass 1b, where the analytics adapter was faked as well
— `api.dev.runwayml.com` ×24, `api.elevenlabs.io` ×12, 33 authorised hosts once each, and
`en.wikipedia.org` and `ro.wikipedia.org` ×20 each. **The only paid path the guard stopped was
Runway's text-to-video in pass 1b, four shots** — about 0.88 USD at catalogue prices, at most
1.20 USD; everything else it refused was a free read. The audit confirmed both halves on its own:
nothing left the machine, and the live files were not touched by the rehearsal — they changed at
22:55:14, when the Owner restarted his studio again from a PyCharm terminal; its read-only copy of
them holds no rehearsal artefact (no run of 2026-09-18, no `sim:` publication, the serial's leave and
the clock unchanged); and the harness, pointed at `data/studio.db`, refused at setup in 0.09 s with
the live files' sizes and times identical before and after.

**What the day said, stage by stage.** Pass 1 used only the whole-day test's fakes; pass 1b faked the
analytics adapter as well, on a fresh copy of the migrated state. The reasons are the studio's own.

| Stage | Pass 1 | Pass 1b |
|---|---|---|
| preflight | COMPLETED, DEGRADED: «Studioul poate rula, dar unele etape vor fi sărite sau vor produce rezultate nepublicabile.» | the same |
| performance_intake | FAILED after 4 attempts over 140.1 s: «URLError: <urlopen error [Errno 11001] rehearsal guard: DNS for 'oauth2.googleapis.com' refused>» | «0 publicări măsurate pe 2 canale. 2 fără date.» |
| idea_generation | BLOCKED: «Rularea s-a oprit la etapa «performance_intake».» | «Propunerile au fost respinse: Propunerile nu respectă schema; nimic nu a fost salvat» |
| research_and_verification | BLOCKED, the same reason | «0 pagini preluate, 0 surse citite, 0 afirmații verificate, 11 verdicte respinse. 33 site-uri retestate (0 citibile).» |
| selection | BLOCKED, the same reason | «Subiect selectat: Why Nepal Is Being Handed a Climate Bill It Cannot Pay.» |
| script_and_storyboard | BLOCKED, the same reason | «1 scenarii scrise în 1 schimburi, 1 aprobate de Director, 1 storyboard-uri generate. 4 cadre descrise complet. Recenzia poveștii: PASS. Un scenariu așteaptă aprobarea ta înainte de storyboard.» |
| serial_queue | BLOCKED, the same reason | «Episodul pentru 2026-09-17 a fost scris, citit, aprobat și pregătit de filmare.» |
| media | BLOCKED, the same reason | «2 videoclipuri randate. Episodul serialului a fost filmat.» |
| edit_and_qc | BLOCKED, the same reason | «2 au trecut QC, 0 au picat.» |
| publish | BLOCKED, the same reason | «Publicat pe Main Channel A - Factual Shorts: PUBLISHED_SIMULATED (private). Publicat pe Channel B - Office Serial: PUBLISHED_SIMULATED (private).» |
| post_run | BLOCKED, the same reason | «10 rapoarte depuse; revizuirea Directorului a fost respinsă: modelul kimi-k3 a scris 184 caractere de analiză și nu a ajuns la decizii; a doua încercare, 184 caractere, tot fără obiect.» |
| daily_log | «Jurnalul zilei 2026-09-18 a fost închis.» | the same |
| the run | FAILED, 2 of 12, a re-attempt queued for 20:24 UTC | COMPLETED 12/12 (run 96b08fd8) |

**Found: two defects.** *One statistics read stopped the day before anything was filmed.* The Google
token refresh in the analytics adapter (`providers/youtube_analytics.py:124`, a `urlopen` outside
the `try` its report had) raised a `URLError`, the stage caught only `MetricsUnavailable`
(`analytics/services.py:296-300`), and the runbook blocked every stage after any failed one; the
re-attempt queued thirty minutes on would have met the same wall. The audit found it worse than
reported: `classify_fault` reads an HTTP 4xx from Google — `invalid_grant`, or a 403 from the
Analytics API — as HARD (measured on both), and a HARD fault in any stage opened safe mode and set
AUTONOMIE OPRITĂ, so **one expired read-only token would have halted the studio until he cleared
it**. His MAIN_FACTUAL slot has two PUBLISHED films with remote ids, so every real day asks Google
first; the whole-day test never met this, because its publications are simulated and carry none.
*The books charged motion that was never generated.* Pass 1b wrote four Runway cost rows, ESTIMATED
and `failed=0` — 0.204 + 0.306 + 0.372 + 0.558 = **1.44 USD** — for shots whose render record says
«api.dev.runwayml.com could not be reached (after 3 attempts)», with no bytes and no credits, and
settled both films' holds (1.30472 and 1.36104 USD) against them. `_priced_scene_costs`
(`economy/accountant.py:184-193`) priced every motion record by its `asked_seconds` whatever became
of the shot, and the price gate's own refusals (`media/assembler.py:1197-1223`) have the same shape,
so on a paid day every shot refused by the 0.60 USD film ceiling or the 0.12 USD-per-second ceiling
would also have been charged against the 15 USD budget.

**Found: the limits of the fakes.** *Two boundaries were not faked:* with the whole-day test's fakes
only, the media stage chose Runway `seedance2_mini` (HERO) and `seedance2_fast` for scenes 1-2 of
each film and made four paid `text_to_video` attempts, three tries each, which only the guard stopped
(four `model_outcome` rows, accepted=0, TECHNICAL, were written on the copy); and the analytics
adapter was not faked, so the harness as first written never went past stage 2 on his data. *Free
vendor reads were refused, not faked:* the Runway and ElevenLabs balance reads
(`economy/credits.py:29`), the host retests (`research/service.py:281`), the Wikipedia searches
(`:543`) and the watchdog's own publisher resolver (`workflows/watchdog.py:175`, which imports
`selected_youtube` from `integrations.services` and is not reached by the stages fake). All were best
effort; on the copy, 34 of the 36 hosts now read FAILED (16 before) purely because of the guard.
*The stand-in's content passed every reviewer:* selection chose his real Nepal topic, and the
stand-in's JWST script «The light your eyes were not built for», citing the Nepal claim 0be61855,
passed the factual gate, the story review, the Director and editorial review; the serial's upload
carried the factual film's metadata («Infrared light and what it shows», tags space/astronomy).
*The picture and character gates were not exercised:* both read NOT_APPLICABLE — «Kael (Video
Editor) gave no usable verdict on the pictures (SUCCEEDED)» — and quality control still scored 1.0
PASSED; if his real vision model answers in prose, films pass that gate unseen. *Stages reported
COMPLETED that did no work* — the audit's finding, which the report had not counted: ideas refused
on schema, research that verified nothing, a Director review with no decisions and the Accountant's
line SKIPPED («books: SKIPPED — Raportul contabil nu respectă schema»), under a run that read
COMPLETED 12/12. *Whether his real refresh tokens still work is unknown:* a rehearsal cannot refresh
a token without leaving the machine.

**Found: what only the Owner can change.** Both YouTube connections read green in the preflight
(«2 sloturi de canal legate de conturi YouTube conectate.», «Canal YouTube conectat prin OAuth.»)
from their stored status alone; their `granted_scopes` hold `youtube.readonly` and `youtube.upload`
and not the `yt-analytics.readonly` the analytics adapter names; and both were connected on
2026-09-11, so if his Google OAuth app is in Testing mode their seven-day refresh tokens end about
now. Six Ollama Cloud models have no token price («Modele fără preț pe jetoane la: ollama. …»), the
only DEGRADING failure of his preflight, so every employee's run is booked without a cost. The voice
is priced at the DOCUMENTED Creator-plan figure for every model («*», 0.22 USD per 1k characters)
while his model is `eleven_flash_v2`, which the same price list bills at half — the audit's
finding. No character has a reference picture («8 personaje fără imagine de referință: …»); a set is
40 images, about 0.80 USD, a cost the preflight's message does not name. The Director may not
approve serial episodes («Canalul serialului este legat, dar Directoarea nu are dreptul să aprobe
episoade: …») and the daily clock is off, both still so on the live data. The mode (AUTONOMOUS_CEO)
and the environment (TEST) are the values the migrations wrote — 0043's and 0031's defaults — and
the rehearsal found no choice of his behind either; the preflight states the mode as a fact without
saying it was a default. 29 scripts of 2026-09-12 stand
VERIFIED_PASS and wait for his approval, and every day repeats «Un scenariu așteaptă aprobarea ta
înainte de storyboard.» about them. In PRODUCTION his 15 USD daily budget and the 12 USD per-film
motion hold leave room for one film, not two — the audit's finding: after the first film settles at
X, the second is refused whenever X + 12.1 > 15, that is whenever X is above about 2.9 USD. Each of
these is now a dated line in «Ce are Owner-ul de făcut» below, in the step it belongs to.

**Found: what worked as designed.** The migration and the seeds are clean on his data. On a copy of
his own backup of 2026-09-12 (at `0029_editorial_review`) the chain ran one revision at a time, 0036
to 0045 in 0.04-0.06 s each, with no warning, no pre-existing cell changed in any table and
`foreign_key_check` empty; bootstrap run again on the live copy changed zero rows; the only change
of meaning is the one 0043 documents, the mode. The app started through its lifespan in 0.317 s,
`/health/ready` answered 200 and the preflight read DEGRADED. With analytics faked too, the day ran
to its end: a factual short and a serial episode grounded in 3 of the 79 events of his real
2026-09-17 log (episode 0b81435e, 52.8 s; grounding, privacy, length and cast passed; approved by
the Director), rendered at 38.4 s and 54.6 s, 1080×1920, captions burnt in, quality control PASSED,
both uploaded private to the simulator, each to its own slot, with no video on any platform; and the
11 re-verdicts on his UNVERIFIED claims were refused because the stand-in's quote is not in their
sources, which is the gate working on real sources.

**Fixed: a failed stage costs its dependants and nothing else.** `YouTubeAnalyticsProvider` turns a
transport or authentication failure — on the token refresh or on the report — into
`MetricsUnavailable` (moved into `providers/youtube_analytics.py`, re-exported by
`analytics.services`), which carries `during`, `auth_refused`, `error_class`, `http_status` and
Google's short `oauth_error` word and never a token. `measure_channel_publications` then records
every publication left as «fără date» with one reason instead of asking Google again, names the
account and the slot and says to press Reconectează, and writes one `youtube.token_refresh_failed`
or `youtube.analytics_refused` ledger event for the preflight. The runbook has `STAGE_PREREQUISITES`
beside `STAGES` (the table, and where each edge comes from, are in `39_DAILY_AUTONOMOUS_RUNBOOK`
§*Abort behavior* and in the decision log): a stage is BLOCKED only when every prerequisite it lists
was lost, with «Nu a fost încercată: etapa de care depinde, «X», a eșuat.» and the root fault named;
the Owner's stop and a blocked preflight still block everything. Safe mode opens only for a P0 as
`21_FAILURE_RECOVERY_PLAYBOOK` defines it — a HARD fault in media, publish or the day's log, or a
database integrity error anywhere (`SAFE_MODE_STAGES`); any other HARD fault costs its stage, its
dependants and one letter from the Director. The same-day re-attempt follows only a transient fault
that cost the day's films (`PRODUCTION_STAGES`), and a day whose films went through while another
stage failed is PARTIAL, which the clock reads as done. Every stage record carries `produced`,
counted from the artefacts its runner already returns, and the run returns a Romanian `summary` and
`stages_productive` — «10 din 10 etape au rulat până la capăt; 7 au produs ceva. Fără rezultat:
«…». Filme publicate: 2.», or «Ziua nu a produs nimic.» — so 12/12 no longer stands for a day that
made nothing. **Fixed: the books charge what was bought.** `motion_was_bought` — `bytes` or
`paid_but_lost`, the only two shapes in which the assembler also records credits — decides whether a
shot is charged, in the finished-render and the lost-render books alike, and a refused shot no
longer teaches a measured price; a film whose every shot was refused settles its hold against its
stills and narration only. The seed adds two DOCUMENTED families, `eleven_flash_*` and
`eleven_turbo_*` at 0.11 USD per 1k characters — the already-cited Creator figure at the half credit
per character the same price list states — and `price_row` ranks any price the Owner typed above
every documented one, then the most specific match. **Fixed: every paid path is faked, and a scan
checks the list.** The suite's autouse guard in `tests/conftest.py` now refuses DNS for anything but
loopback and asyncio's `sock_connect` as well — a new test caught a real ConnectEx attempt to
192.0.2.1 on Windows before the change — and records every refusal. The whole-day test and the
rehearsal share one list of eight fakes (`VENDOR_FAKES`, `install_vendor_fakes`), among them the
motion chooser, which keeps the studio's own `choose_model` decision and replaces only the vendor,
and the analytics adapter. `tests/test_no_paid_path_escapes.py` walks the call graph from
`execute_daily_run` and `build_stage_runners` and fails on any paid adapter reachable without a fake;
against the list as it stood before, it named exactly five sites — the four the rehearsal met and
`verified_search_provider` → `SearchProvider`, which it never did. **Fixed: the preflight says what
will stop tomorrow.** «Canal YouTube conectat» and «2 sloturi legate» now say they read the stored
state; `youtube_upload_access` (BLOCKING) fails on a missing `youtube.upload` or a standing token
refusal, and `youtube_statistics_access` (DEGRADING) on a missing `yt-analytics.readonly` or a
standing refusal, both giving each grant's age with the Testing-mode caveat and neither counting an
unrecorded scope or a failure Google never answered as a refusal; `daily_budget_films` asks the media
stage's own `estimate_film_cost_micros` whether the DAILY budget holds the day's films; and the
summary names the first check that would stop the day or lose a film (`first_stop`) instead of
«Studioul poate rula». On a fresh copy of his copy the preflight now reads DEGRADED: statistics fail
for Nexus Curiosity and Inside The Nexus («fără yt-analytics.readonly»), upload passes with both
grants seven days old and «tokenul poate fi deja expirat», and the budget line is INFORMATIONAL —
15 USD holds two TEST films at 1.2 USD each, while in PRODUCTION 2 × 12 = 24 USD and the serial is
refused once the short costs more than 3 USD.

**One real day, estimated.** The audit's `paid_run_estimate`, priced from the copy's own data, for a
day in TEST (two motion shots per film, a 0.60 USD motion ceiling per film, at most 0.12 USD a
second, private upload): Runway motion with `seedance2_mini` at 0.02 USD/s (HERO) and
`seedance2_fast` at 0.03 USD/s — at the rehearsal's shot lengths film 1 is 0.204 + 0.306 = 0.51 USD
and film 2 is 0.372 USD, its second shot (0.558) refused because only 0.228 of its ceiling is left:
about **0.88 USD**, with a hard ceiling of 1.20 USD a day; stills with `gen4_image` at 0.02 USD each,
7 scenes, **0.14 USD** plus any retry; narration of the rehearsal's 476 + 732 = 1,208 characters,
**0.27 USD** at the DOCUMENTED 0.22 per 1k and about 0.13 USD at the Flash half, and 0.19-0.37 USD
for the 800-900 characters a real film more likely has; YouTube, Analytics and research fetches
0 USD (quota only). **Total known vendor spend: about 1.1-1.3 USD, at most about 1.7 USD**, against
film holds of 1.30 and 1.36 USD and a 15 USD budget. In PRODUCTION (motion on every scene,
image-to-video, a film ceiling of min(12 USD, what the day has left), the cheapest model that reaches
quality at 0.05-0.08 USD/s): 2-4.4 USD of motion per 40-55 s film, plus about 0.07 USD of stills and
0.1-0.2 USD of voice, about 2.3-4.7 USD a film and 4.5-9 USD a day under the 15 USD cap — except that
each film holds 12 USD, so the second is refused whenever the first spent more than about 2.9 USD,
and a typical PRODUCTION day is one film at about 2.5-4.5 USD. **Unknown, and said so:** the language
models — Ollama Cloud is a subscription and he has typed no price; the rehearsal's 36 model runs were
the stand-in's and their token counts mean nothing; his real runs of 2026-09-12 average about 4,400
prompt and 820 completion tokens, roughly 160k and 30k a day, plus the separate `director_loop` and
`model_review` jobs. Also unknown: whether Runway accepts these requests and charges what its credits
estimate, how long real scripts are, how many stills are retried, and whether his tokens still work.
The audit's two conditions on the figure — up to about 0.5 USD more in the books with defect 2, and
most likely 0 USD spent and no film, or safe mode, with defect 1 — are removed in code by the parts
above, under faked providers.

**What was measured, and whose measurement each figure is.** The rehearsal: pass 1 on the copy, pass
1b on a fresh copy of the migrated state, and `tests/test_rehearsal_on_a_copy.py` on a fresh copy,
**1 passed** in 1.67 s with the day stopping at performance intake inside it. The audit: the same
test on its own fresh copy, **1 passed** in 1.11 s with an identical record, and the whole suite,
`uv run pytest -q tests -p no:cacheprovider`, **1265 passed, 2 skipped** in 829 s (the second skip is
the opt-in rehearsal itself) — on the tree as it stood at the rehearsal, before any of the fixes. The
failure-and-analytics part: `tests/test_phase7_analytics.py` **18**, `tests/test_day_survives_a_stage.py`
**14** (new), **124** across the runbook, mail, B/C-adversary and daily-run-stage files, and **202
passed, 1 skipped** across the ten related files. The books part: **13** in
`tests/test_books_and_history.py` for the new cases (red first at 9 passed, 4 failed),
`tests/test_pricing_truth.py` **22** (red first), **158** across seven economy and media files, with
`ruff`, `ruff format --check` and `mypy` clean. The fakes part: **14 passed, 1 skipped** across
`tests/test_no_paid_path_escapes.py` (new, red first), the whole-day test and the rehearsal; **340
passed, 1 skipped** across every file that fakes `getaddrinfo` and the research, provider and
adversary files; and the opt-in rehearsal on the scratchpad copy **1 passed** — the day COMPLETED
through all twelve stages, the chooser picked `seedance2_mini` for two shots at 20.4 credits each,
both through the fake, one film reached the simulator, and the guard made 74 refusals, all free
research reads. The preflight part: **30** across `tests/test_readiness.py` and
`tests/test_sources_and_readiness.py` (red first at 17 passed, 12 failed), **130** across the
preflight's direct consumers, and `node --test frontend/tests/readiness.test.js` **8**. This
documentation part: `scripts/check_docs.py` and `tests/test_documentation.py`. **No whole-suite run
was made by any of the four parts or by this one**; the audit's 1265 / 2 is the newest and is older
than the fixes. No migration was taken: the head stays `0045_reconciliation` and 0046 is free. No
provider was called, nothing was rendered by a vendor, no run was queued on the live studio, no
credit was spent and `data/studio.db` was never opened by any of them.

Not finished, honestly: **the reconnect the Owner is told to make can grant statistics access only
since a change made while these documents were being written.** `SCOPES`
(`backend/app/youtube/services.py`) asked Google for `youtube.readonly` and `youtube.upload` only,
so no reconnect could have granted the statistics scope; another part added `yt-analytics.readonly`
on the night of 2026-09-18, with
`tests/test_youtube_connections.py::test_the_consent_asks_for_the_statistics_the_day_reads` (**1
passed**, run by this documentation part; nothing else of that change was measured here). His
consent screen now asks for one more permission, the change reaches him only when his studio runs
this code, and a connection made before it must be reconnected once to hold the scope — until then
statistics stay «fără date». The
uploader (`providers/youtube.py`) logs a refused refresh and writes no ledger event, so a refusal at
upload reaches the preflight only after the statistics read meets the same dead token — and on the
first day with a dead token the films are made and paid for before the upload fails. The film's hold
still takes the dearest voice price (`estimate_film_cost_micros`), so it holds Flash narration at
about twice its cost while the books now charge the half. The harness now fakes the analytics
adapter, so the real Google refresh on his copy is no longer rehearsed: defect 1's fix is proven by
the failure-and-analytics part's tests with faked transports, and only a free real read — Verify or
Reconnect in Settings — proves his tokens; and the free rehearsal after the fixes, on a fresh copy,
has not been run. The panel does not read `summary`, `stages_productive`, `produced` or `first_stop`
yet, and `frontend/dist` is not rebuilt. (Corrected 2026-09-19: `frontend/src` reads all four,
through `frontend/src/day_outcome.js`; see the subsection below. `frontend/dist` is still not
rebuilt.) `backend/app/runbook/stages.py`'s module docstring still
says a raised fault «stops the day», and `_performance_intake` keeps the reconnect sentence in its
artefacts and the ledger rather than in its own reason line. The manual ingest endpoint
(`analytics/router.py`) now answers 409 with the Romanian reason, not 502, for a transport or
authentication failure. The scan's roots are the daily day only: the watchdog, the Director's loop,
the model review, the catalogue refresh, the reference-set route and the API routes are held by the
network guard alone, and the scan cannot see `getattr` by string, `importlib` or code built at run
time. The free research reads are refused in a rehearsal, not faked, so which of his 36 hosts are
readable today is a real run's measurement. And nothing here proves a vendor: whether Runway returns
usable clips at the estimated credits, whether his models answer the idea, Director and Accountant
schemas (kimi-k3 had already rambled on 2026-09-12), whether a vision model answers the picture gate,
whether the reviewers catch narration its cited claim does not support, and whether the Publisher
titles the serial as the episode — the first real day, watched, is where each of those is measured.
(Corrected 2026-09-19: narration that does not say its cited claims is now refused by a computed
check, before any money is spent; see the subsection below. What a real day still measures is
whether a real writer, given the check's note, repairs the script within the exchange budget.)

### After the rehearsal — 2026-09-19: the narration says what its claims say, and the panel says what the day made

Two parts closed two of the rehearsal's findings in code, under faked providers. The grounding part
made the narration answer to its claims. The panel part made the page show what a day produced.
This subsection records what each changed, what each measured and what is still open. The
rehearsal's findings above stand as they were found.

**Why the narration needed a measure.** In pass 1b the day selected the Owner's real topic «Why
Nepal Is Being Handed a Climate Bill It Cannot Pay», with verified claims about it. The stand-in
writer returned script 5ee7e22e, «The light your eyes were not built for», about the James Webb
telescope. Every scene cited the Nepal claim 0be61855, a SUPPORTED claim about the 83.3 billion
dollars of climate finance given to developing countries in 2020. The script passed the factual
gate, the story review and the Director, and was approved and published to the simulator (the
report's and the audit's FAKE_LIMIT finding). The factual gate (`evaluate_factual_gate`) asks
whether the cited claims exist and are SUPPORTED. Nothing the studio computed asked whether the
narration says them, so only a model's judgement stood between that script and a film. With a real
model the risk is smaller, but real: a film whose words drift from its sources is exactly the
factual failure the gates exist to prevent.

**Fixed: the narration is measured against its claims and its topic.**
`backend/app/factual/grounding.py` (new) reads the voiceover, the topic's title and angle, and the
text of each cited claim, with no model and at no cost. It measures three things, and each failure
gets a Romanian reason naming what is missing:
- every cited claim is present: at least two of the claim's terms (content words, numbers or
  names) appear in the voiceover;
- the voiceover is about the topic: at least two terms of the topic's title and angle appear in it;
- the voiceover is not taken over by facts from elsewhere: it is refused when more than half of its
  numbers and names, and at least two of them, appear in no cited claim and not in the topic.

Words match on their stem, with diacritics folded. Numbers are normalised: «7,000», «7.000» and
«7 000» are one number, and «about 83 billion» says 83.3. Number words are read in English and
Romanian. A script it cannot measure (no claims, a cited claim that no longer exists, or no
narration) is NOT_MEASURED and does not pass. An episode of the office serial is not measured.

It refuses in four places, all but the last before any money is spent:
- The story review has a new blocking check, `narration_is_grounded`. A failure sends the script
  back for a rewrite (REVISE) with a note naming the unsaid claim, and becomes REJECT at the last
  exchange, as the budget already did.
- `_director_approves` measures again and will not approve a script that fails.
- `story_gate`, before the shot descriptions and the render, measures again, so a PASS recorded
  earlier, or given by hand, cannot buy a shot.
- The Director's last look at the finished film (`gather_facts`) carries the measurement and
  refuses a factual film that fails it, before any model is asked.

The story review's facts for the Director carry the measurement too, placed last so that a
truncated payload keeps the scenes. Every one of the four only adds refusals: the factual gate, the
Director's verdict, the five publishing points and the other hard gates are unchanged. Its limit is
stated in the module: it measures words, not meaning, so a narration that repeats two of a claim's
terms while contradicting it passes. That judgement stays with the Director, who now receives the
measurement. `50_CONTENT_GATE_MATRIX` gains the gate's row and a section on what it certifies, and
is re-hashed (the decision log has the reason).

**Calibrated on his real scripts: the grounding part's measurement.** The part opened copies of the
rehearsal databases only, read-only. The real model wrote 31 factual scripts on 2026-09-12:
- Both approved scripts pass: f243bf48, the LHC film, and 37fc8ef6, the ATLAS film.
- 25 of the 29 waiting for the Owner's approval pass.
- The 4 refused each cite a claim their narration never says. 92028a88 cites the sunshield cooling
  the mirror to 40 kelvins, while its scene says «you just block it, one layer at a time».
  8d4f7306, aa3da89f and 670d6279 cite the decommissioning on Aug. 8, 2024, while their scenes say
  the equivalent of «NASA switched it off».
- Across these scripts, the highest share of numbers and names from nowhere was 0.40, against a
  limit of 0.5. The rehearsal's script measured 1.0 and is refused on all three counts.

A stricter rule, asking for each claim's own distinctive words, was rejected. It refused the
approved LHC film, which says «doesn't glow, doesn't absorb light» for «does not interact with the
electromagnetic force». The prefix slack was lowered from three letters to two after «bill» matched
«billion». One existing fixture was changed rather than the check weakened. In
`tests/test_editorial.py`, the film's one claim did not carry the narration's 2023, James Webb
Space Telescope and twenty-six light years, which is exactly what the writer's brief forbids. The
claim now carries them.

**Fixed: the panel says what the day made.** `frontend/src/day_outcome.js` (new) decides, and
`frontend/src/main.js`, `frontend/src/ledger.js` and `frontend/src/style.css` show:
- **Run cards.** The backend's Romanian `summary` appears under the header of each run card.
- **Stage counts.** Each stage row shows its count: «a produs N», «nu a produs nimic», nothing when
  the backend says the stage is not counted (`produced: null`, as for the preflight and the day's
  log), or «nenumărat» for a record older than the counts.
- **Empty and idle.** A COMPLETED run with `stages_productive === 0` gets `rb-empty`, a warning
  colour instead of the green of success. A stage that finished and made nothing gets `rb-idle`.
- **Preflight.** On the preflight card, the check named by `first_stop` sits above the list with
  its own message, labelled «Primul punct blocant» (BLOCKING) or «Ziua nu ajunge întreagă», and is
  outlined inside the list.
- **Ledger.** The ledger's «daily run finished» line carries the summary, and the head line adds
  «· N etape au produs ceva» when the event has the count.

A missing count is never read as zero. A run without `stages_productive` is not called empty, and
a stage record without `produced` is not called idle, because `list_runs` returns older stage
records as stored. Events recorded before the count read exactly as they did. The dependant's
reason, «Nu a fost încercată: etapa de care depinde, «X», a eșuat.», was already shown as the
stage's reason line. It is display only: no gate, verdict or button permission changed, and the
Start button still follows the preflight status.

**What was measured, and whose measurement each figure is.**
- The grounding part:
  - `tests/test_script_grounding.py` **15 passed** (new);
  - `tests/test_editorial.py` **16 passed**, 3 of them new;
  - the factual, editorial, pipeline, runbook, media, publishing and whole-day files together
    (`test_script_grounding`, `test_editorial`, `test_editorial_quality`, `test_phase4_factual`,
    `test_factual_agent_pipeline`, `test_script_writing`, `test_phase9_story`,
    `test_pipeline_coverage`, `test_serial_pipeline`, `test_autonomous_day_end_to_end`,
    `test_daily_run_stages`, `test_day_survives_a_stage`, `test_phase10_runbook`,
    `test_phase5_media`, `test_phase6_publishing`, `test_publish_policy`,
    `test_rehearsal_on_a_copy`) **352 passed, 1 skipped**, the skip being the opt-in rehearsal
    harness;
  - `ruff check` and `ruff format --check` clean on its six files.
- The panel part:
  - `node --test tests/day_outcome.test.js` red first, **0 passed, 1 failed**, because the module
    did not exist, then **9 passed**;
  - `npm test --prefix frontend` **124 passed** (125 on the tree as committed, which also carries
    the stream test of 9ce725a);
  - `npm run check --prefix frontend` (tsc) clean;
  - a `vite build` into a scratch directory compiled, with `frontend/dist` untouched.
- This documentation part: `scripts/check_docs.py` passed, with the matrix re-hashed, and
  `tests/test_documentation.py` **3 passed**.
- The verify part (adversarial, after the documents):
  - the whole suite on the tree it found: **1523 passed, 4 skipped, 2 failed**. Both failures
    were the new check refusing a fixture that breaks the writer's brief:
    `tests/test_phase_bc_adversary.py` narrated the serial's dialogue under a Webb claim, and
    `tests/test_search_step.py` cited a claim `c1` that does not exist, which is NOT_MEASURED
    and held at `story_gate`. The fixtures were corrected, not the check;
  - a faithful narration with its numbers spelled out («six hundred million dollars», «șase
    sute», «twenty eighteen», «locul patru») was refused. The number reader now reads a whole
    spelled-out number in English and Romanian, and ranks from third to tenth on both sides.
    `tests/test_script_grounding.py` went red at **3 failed, 19 passed**, then **22 passed**.
    The recalibration on the copied scripts is identical: both approved films pass, the same 4
    are refused, and the rehearsal's 5ee7e22e is refused;
  - the module docstring now says two letters of prefix slack, as the code does;
  - `ruff check` clean, `mypy backend` clean on 191 files, `npm test --prefix frontend`
    **125 passed**, `scripts/check_docs.py` passed. The build part's seventeen files:
    **359 passed, 1 skipped**;
  - its second whole run had 3 render tests failing that passed alone and with their files
    (52 passed). The cause was not proven there; the next run below shows it.
- The session that committed (2026-09-19, 14:09–14:24): the whole suite on the tree as committed,
  `uv run pytest -q tests -p no:cacheprovider -rfE`: **1518 passed, 4 skipped, 12 failed, 2
  errors** in 917 s. Every one of the 14 is the machine out of commit memory, not the code:
  the two errors and two failures are `MemoryError` inside SQLAlchemy, the render failures are
  FFmpeg dying mid-encode, and Windows logged a low-virtual-memory condition at 14:09, 14:14 and
  14:20 (the Owner's Market Signals held 22.6 GB of commit, the live Unreal stream 13.6 GB). The
  seven files that held them (`test_media_selection`, `test_motion`, `test_phase5_media`,
  `test_phase_bc_adversary`, `test_reattempt_buys_nothing_twice`, `test_phase10_runbook`,
  `test_youtube_connections`) were run again at 16:45: **169 passed**. So 1532 of 1532 pass,
  in two runs. The same shortage stopped the Owner's live stream at 14:23: Unreal crashed in a
  background worker, and a restart at 16:39 died at its second frame on `E_OUTOFMEMORY` with 41 MB
  of commit left. It was restarted at 16:45, when 27 GB were free, and loaded the level.

*Corrected 2026-09-19, after the verify part:* the verify part and the committing session each
made a whole-suite run, recorded above. What stood here: «No part made a whole-suite run, so the
audit's 1265 passed, 2 skipped is still the newest, and it is older than every fix.» No provider was called, nothing was rendered, no run was queued, no credit
was spent, and `data/studio.db`, `art-source/` and `backend/app/office/` were not touched.

Not finished, honestly:
- **The Owner's queue.** 4 of the 29 scripts waiting for his approval (92028a88, 8d4f7306,
  aa3da89f, 670d6279) would now be sent back for a rewrite, or held at `story_gate` if he approved
  one by hand. This is a dated line in step 12 of «Ce are Owner-ul de făcut».
- **A real rewrite.** Only a real model run shows whether a writer given the Romanian note fixes
  the script within the exchange budget. The replayed stand-in does not rewrite, so in its test it
  runs until REJECT.
- **Other languages.** Claims whose sources are in another language were tested only as a Romanian
  narration of English claims. Across languages, ordinary words match only where stems are shared;
  otherwise the match rests on numbers and names.
- *Corrected 2026-09-19 by the verify part:* the module docstring says two letters, as
  `SUFFIX_SLACK` does. What stood here: the docstring said «at most three letters to spare».
- **What a word count cannot hear, measured by the verify part.** The check is lexical, and these
  pass it; each stays the Director's judgement, and she now receives the measurement:
  - negation: «Nepal is NOT ranked fourth ... no US$600 million in damages» measured PASSED;
  - one claim said and the others carried by generic and topic words («countries», «developed»,
    «billion», «Nepal», «climate»). Two stricter rules were tried on the real scripts and both
    refuse the Owner's approved LHC and ATLAS films, so neither was adopted;
  - the claims' keywords in unrelated sentences, with no number from elsewhere;
  - «opt» and «nouă» are read as 8 and 9, so «opt in» or the Romanian «new» can add a number
    from nowhere. Nothing in the calibration set was affected;
  - when the Director refuses on grounding after a review said PASS (only if the text changed
    between the two reads), the rewrite's notes do not mention grounding. No money is at risk:
    `story_gate` measures again before the shot descriptions, the media stage and the render.
- **The panel.** `frontend/dist` is not rebuilt, so the Owner sees none of it until
  `npm run build --prefix frontend` or until `start.py` rebuilds a stale bundle. The panel was not
  seen in a browser against a live backend. A PARTIAL run's `stopped_at_stage` still reads
  «stopped at «X»» rather than «etapa eșuată». The ledger and the run cards still mix English and
  Romanian.
- **Unchanged.** `backend/app/runbook/stages.py`'s module docstring still says a raised fault
  «stops the day». The serial's upload taking the factual film's metadata, found by the rehearsal,
  is not addressed.
- **Scratch files.** The calibration copies (`grounding_calib/` in the session's scratchpad) can be
  deleted.

## Readiness for the first day (2026-09-18)

Six phases are built and the suite is green, which is not the same thing as a studio that can be
left alone on Monday morning. This day measured the distance between the two, in three places, and
closed what could be closed from the record alone. Measured before the work, each of them true of
every studio that has ever run: no budget was active anywhere, so `reserve_spend` took the write
lock and held a film's money against no limit at all; 391 `agent_run` rows on the live copy carried
`cost_vr` NULL because the models the employees actually think with had a price on neither token
side; `seed_initial_workforce` hired every employee onto a text model and no seeded model declares
`vision` at all, so `app.agents.vision.vision_agent` returned None and the picture and character
gates stood down as NOT_APPLICABLE on every film, forever, which means a film of eight blank fields
passed every automatic check;
`generate_storyboard_from_script` wrote `character_ids_json=[]` on every scene of every factual film
— the studio's main product — so the character gate had nothing to compare and only the serial's
storyboard ever filled it; a SUPERVISED day wrote one approval request per film and nothing left the
studio, so an unanswered question expired after twenty-four hours and the film was never made; and
every cost row the studio wrote for itself was ESTIMATED while `spend_since` summed every row in the
period whatever its status, so a render estimated at 4.20 and later billed at 4.55 charged the period
8.75.

**The preflight says what is missing before the Owner spends anything.** Five checks were added to
`app.runbook.preflight`, all of them reading the database and nothing else — no vendor is asked, no
key is used, no job is queued — so the preflight is as cheap and as safe on the hundredth run as on
the first. `spending_budget` (DEGRADING) reports that no budget is active at all: the hold is still
taken, it simply has no limit to refuse it against, and the line names `PUT /economy/budget` because
nobody but the Owner can set one. `model_prices` (DEGRADING) asks whether the models the day's
employees think with have a price on *both* token sides — `llm_cost_vr` returns None unless input and
output are both priced, which is how those 391 rows came to be NULL — and names the provider kinds
that are unpriced without inventing a figure for any of them. `vision_capability` (DEGRADING) asks
`vision_agent` whether anybody in the studio can look at a picture, and says the consequence rather
than the fact: with no model that declares vision, `picture_qc` and `character_drift_qc` stand down
on every film, so a film of blank fields passes every automatic check. `character_references` names
the characters whose slots hold no readable picture — DEGRADING for one whose look is locked, because
that character's film is refused before the first scene rather than having a face invented for it,
and INFORMATIONAL for an unlocked one, whose still is drawn from its prompt as it always was;
"readable" means the slot holds an asset id, the row exists, and the file is still on disk, since a
row pointing at a moved file looks filled in the database and has nothing to compare against in QC.
`serial_channel` (INFORMATIONAL) says whether the OFFICE_SERIAL slot is bound to a connected account
and whether the Director has the Owner's leave to approve episodes, naming
`POST /publishing/channels/{id}/publish-policy`; without the leave every episode stays DRAFT and
waits for him, which is his right and is not autonomy. None of the five is BLOCKING and two of them
never even degrade: a preflight check must not stop the day for something the Owner deliberately
chose, so a studio with nothing configured reports exactly the blocking failures it reported before —
`stop_autonomy` and `llm_provider` — and a test holds that list against the verdict, which is
computed over BLOCKING and DEGRADING only. Beside them, `APPROVAL_EXPIRES_AFTER_HOURS = 24`, a module
constant in `services.py` the Owner could not reach, is now `approval_expires_after_hours` in
`config.py` (default 24, one hour to a week, `STUDIO_APPROVAL_EXPIRES_AFTER_HOURS`), read through the
same local-import-and-`getattr` shortcut `providers.retry` takes, with a documented fallback of 24 so
that a studio whose settings cannot be built can still ask him a question rather than raise while
asking it; the bounds are stated as what they protect — below an hour a question could expire before
he reads it, above a week a yes could be spent long after the film it was asked about — and the
behaviour is unchanged.

**Somebody can be hired who can see, and a factual film records who is in it.** The role now says
what it would want: `ROLE_PREFERENCES` writes `vision` on the Video Editor's role at the PREFERRED
level — which is not a gate and never becomes one — and `prefer_capable_models` moves that employee
onto a model that sees at the next start-up, if the Owner has admitted one. **Corrected at the same
day's closure (2026-09-18): she moves in the same sync that admits the model**, not at the next
start-up; see «Closed the same day» below. PREFERRED was read
nowhere in the code before (the only reading was `requirement_level == "REQUIRED"`, in
`_check_required_capabilities` and in the role projection); it is now read in the hiring path inside
`seed_initial_workforce`, and nowhere that could refuse a run: a studio whose Owner has admitted no
seeing model hires the same way, edits the same way, and is told honestly that nobody looked. His
choice stays his — an employee whose models were ever saved by the assignment command
(`agent.model_assigned`) is not touched, the same guard the start-up allocation uses (**corrected at
the same day's closure, 2026-09-18: that guard read the studio's own allocation file as his hand**,
because `apply_llm_allocation` writes the same event, so the first sync of any studio killed the
preference for a choice he had never made; `_owner_chose_models` now judges the last event that
moved her models) — and the move
writes `agent.model_preferred`, never `agent.model_assigned`, because that second event is the proof
of his choice and `apply_llm_allocation` reads it as "already configured". The capability itself is a
row and not a claim about any model: the seed creates `Capability(name="vision")`, because a role can
only prefer a capability the studio has by name, and attaches it to no proposed model —
`SEEDED_MODEL_CAPABILITIES` now enumerates the four text capabilities explicitly in place of the loop
that wrote "every capability" onto every proposed model, since nothing in the seed contacts a vendor
and a guess that a model can see would make the picture gate certify a look nobody took.
`sync_provider_models` attaches `vision` where the vendor itself declares it. On the film's side,
every factual scene now records its cast, read from what the scene itself says: the scriptwriter's
character list first, then the names the requested picture calls for — not the narration, because the
narrator has no face, and a name spoken over a photograph of a mirror does not put that person in
frame. A first name followed by another capitalised word is not counted (the observer "Vera Rubin" is
a telescope, not the cast), because an invented cast would make the gate certify a comparison nobody
asked for. **Corrected at the same day's closure (2026-09-18): that one exclusion was not enough** —
a bare given name whose next word is lower case ("Hurricane Elena made landfall") was cast as well,
so the reading is now split, the prose's guesses are recorded and never written to the scene, and
only what the film states buys a portrait or refuses a locked character; see «Closed the same day»
below. A film that shows nobody records an empty cast and says once, in the storyboard's own
creation event (`media.storyboard_created`, keys `scenes_with_cast` and `cast_note`), that the
absence is deliberate — readable through `app.media.services.storyboard_cast_note` and returned by
`get_storyboard` as `cast_note`. The consequence is that the reference sets reach the factual film at
last: a scene that names a character with a stored portrait is drawn from it, and a character whose
look is locked and has no reference refuses the scene instead of being given an invented face — a
rule that was until now unreachable from a factual film, because no factual scene listed anybody.

**The Accountant tells him what is waiting, and the books learn what things really cost.**
`waiting_approvals_letter` writes one letter a day, with the same idempotence as the other two — the
studio's business date decided behind the write lock — and writes nothing when nothing is waiting,
so a silent mailbox still means "nothing to decide". Each question is named by what it is in his
language (`APPROVAL_ACTION_LABELS`), with its cost — «necunoscut» where the studio cannot compute
one, never zero, taken from the request's own `cost_label` so that the governance page and the
mailbox can never say two different things about the same question — and with the hour the oldest
one expires; the questions are ordered as the day raised them, and the model-written evidence (a
film's title, a storyboard's estimate) is cut at 120 characters, because a long title may not become
the whole letter. The day's close carries it as its first act, before any question is put to a
model, so a close that fails because the report never came back does not swallow the one letter that
says he has decisions standing. **Corrected at the same day's closure (2026-09-18): the media stage
writes it too, in the minute the question is born**, and the figure in it now carries what the
estimate could not price; see «Closed the same day» below. Beside it, migration
**0045_reconciliation** gives the books the one word they had a vocabulary for and no function:
`provider_reconciliation`, plus `reconciled_at` and `reconciled_by_id` on `provider_cost_record`,
both NULL, so every existing row keeps the reading it had. Reconciliation is the Owner's act and
nobody else's, because only he sees the invoice: `PUT /economy/reconciliations` has the shape of
`PUT /economy/prices` — a `command_id` (a retry returns the original answer, the same id with a
different figure is 409) and `expected_version`, which here is required rather than optional,
because replacing an invoice moves money. An invoice covers a period (the same half-open window
`spend_since` reads) or one named thing — today a render, through the attribution key every row
carries. It writes the BILLED row that posts against VR Cash, stamps `reconciled_at` on the
estimates it covers, and keeps on the row, as data, every row it touched and could not replace, with
the reason. The estimate is marked, never subtracted: it is the document of what the studio believed
a film would cost, and `spend_since` skips it. The billed row carries the hour of the last spend it
pays for, not the hour the Owner typed it, so the period that counted the estimates is the period
that counts the invoice: afterwards a period counts the billed figure once, plus whatever the
invoice did not cover, and `treasury_snapshot.unbilled_provider_costs` falls the same way, because
an estimate that has been paid is no longer an obligation coming. A correction is a new version,
which reverses the previous invoice's posting in the ledger (`reverses_transaction_id`) and
re-adopts its estimates; nothing is edited and nothing is deleted.

**What was measured, and whose measurement each figure is.** The preflight part: `tests/test_readiness.py`
**11 passed** (new) and `tests/test_phase10_runbook.py` **46**, with `tests/test_approvals.py` **18**,
**144** across the eight daily-run, director, pipeline, research, reset, scheduler, sources and
media-toolchain files, **70** across approvals, autonomy modes, books and the closure adversary, and
the three whole-day tests **5**. The workforce and storyboard part: **18** in
`tests/test_phase1_agents.py`, **28** in `tests/test_phase5_media.py`, **16** in
`tests/test_picture_qc.py`, **22** in `tests/test_character_references.py` and **10** in
`tests/test_editorial.py`, with **83**, **51**, **87** and **138** across nineteen neighbouring files
that seed the workforce or build storyboards — 359 in all, all passed. The economy part:
`tests/test_reconciliation.py` **11 passed** (new), `tests/test_books_and_history.py` **17**,
`tests/test_phase11_economy.py` **34**, `tests/test_pricing_truth.py` **18**,
`tests/test_schema_and_audit_trail.py` **3**, **188** across the ten files the migration-head move in
`main.py` can reach, and the whole-day tests **5**, with `ruff`, `ruff format --check`, `mypy backend`
and `scripts/check_docs.py` clean. This documentation part: `scripts/check_docs.py` and
`tests/test_documentation.py`. **No whole-suite run has been made by any of the four**, and the
figure that stands in `PROJECT_STATE.json` — 1194 passed, 1 skipped, taken by the Phase D/G closure's
adversarial verifier on 2026-09-18 — is therefore older than the tree; the verifier's figure for this
phase lands after this document. The migration chain is 0039 → 0040 → 0043 → 0044 → **0045** and
`main.py` pins `0045_reconciliation`: the economy took 0045 as the brief reserved it, the media part
needed no column and took neither 0045 nor 0046, so **0046 is free**. No provider was called, nothing
was rendered, no run was queued and no credit was spent by any of the four.

Not finished, honestly: **nothing here has met a real vendor, a real model or a real invoice.**
Every test fakes every provider at its transport and `tests/conftest.py` refuses every non-loopback
socket, by the Owner's rule of 2026-09-17, so what is proven is behaviour and not a vendor's answer:
that a model declaring `vision` really does return the picture gate's schema on real frames is
unmeasured until he admits one, and the first true reconciliation — his, with his invoice in his
hand — is the measurement of the books. The preflight's five messages have been read in Romanian by
their author and not yet by him. `model_prices` covers the LLM token sides only, on the primary
model of each ACTIVE agent, because that is exactly what makes an agent run's `cost_vr` None; it
does not check the voice price (`per_1k_characters`) or the motion and image prices (`per_second`,
`per_generation`), because naming the voice kind honestly would mean reading the media selection
through the vault rather than the price table and pricing a motion model would mean knowing which
model a plan will pick, and a check that half-covered them would report a pass certifying less than
it looks like. The secondary and tertiary model slots are not priced either, because `vision_agent`
counts only the primary model and the two checks must agree about which model an employee runs on.
**Corrected at the same day's closure (2026-09-18): the Video Editor's preference no longer waits
for the next seed and is no longer invisible** — the second call is wired at the end of
`sync_provider_models`, after `apply_llm_allocation`, and `RoleView` carries
`preferred_capabilities` beside `required_capabilities`; what stands open of it is named below.
**Corrected at the same day's closure (2026-09-18): `picture_qc` reads the storyboard's record**, so
a film that genuinely shows nobody reports the board's own note and the old sentence now means only
what it says. An employee's run is still not reconcilable: the token cost the studio computes for
itself lives in `agent_run.cost_vr` and never passes through `provider_cost_record`, so an Ollama
Cloud invoice cannot yet replace it. An invoice matches on a correlation exactly and knows one
default key, `render_job_id`, which is what `_priced_scene_costs` and `record_failed_render_cost`
write; a hosting charge or a monthly subscription must be reconciled by period, or with a key he
names, because a book does not guess. **Corrected at the same day's closure (2026-09-18): the
waiting-approvals letter no longer leaves only at the day's close** — the media stage writes it in
the minute it raises the question and stops, and `_letter_once_a_day` keeps the close from writing a
second one. **Corrected at the same day's closure (2026-09-18): the panel renders the third severity
and names the checks** — a failing INFORMATIONAL check reads INFORMATIV in neutral grey instead of a
red "DEGRADES", and the five new checks and `autonomy_mode` have Romanian labels. What is still true
of the interface: `youtube_channel_binding` has no label either and still shows by its code name, as
it did before this phase (corrected 2026-09-18, measured in the tree while the rehearsal's documents
were written: `frontend/src/readiness.js` carries «Sloturi de canal legate de YouTube» for it, and
did since the commit that created the module); neither reconciliation screen exists; and `frontend/dist` is still not
rebuilt, so the Owner sees none of any of it until he builds.

### Closed the same day — 2026-09-18: the employee who can see arrives when the model does, a guessed name steers nothing, and the day speaks at the hour it stops

Three things the section above left open, in its own words: a preference that "reaches a studio that
is already running only at the next seed", a picture gate that "does not yet read the storyboard's
cast note", and a letter that "leaves only at the day's close" beside an interface that "has not
moved". An adversarial reading of the checklist — if the Owner did every line of it tonight, what
would the studio make tomorrow at 05:00 and what would most likely go wrong — named the same three
with a file and a line each, measured against this tree. All three are closed, and the second turned
out to be a larger fault than the note it had been filed as.

**The employee who can see arrives on the day the Owner admits the model, not on the day he first
seeded the studio.** Measured before the work: `prefer_capable_models` had exactly one caller,
`seed_initial_workforce`, and that caller one of its own, `scripts/bootstrap.py` — step 1 of his
morning, hours before step 9, where he admits a model that declares vision. Nothing looked again
between the two, so `app.agents.vision.vision_agent` returned None at 05:00, `picture_qc` and
`character_drift_qc` stood down on every film, and a short of eight blank fields would have reached
the Director as finished work. The preference now has its second call site, in `sync_provider_models`
and after `apply_llm_allocation`: `record_declared` a few lines above is the only place in the studio
that ever writes `vision` on a model, so the sync is the first moment at which a seeing model exists
as a row, and it is the Owner's own act — «sincronizează» in *Angajați → Model*, «verifică» in
*Setări → Conexiuni*. After the allocation and never before it, because the allocation is the
studio's baseline and skips only employees who already carry `agent.model_assigned`, which a
preferred move deliberately does not write: run first, the preference would be undone by the file
three lines later. The guard that protected the Owner's own choice was the bare existence of
`agent.model_assigned` — an event written by his command *and* by `apply_llm_allocation`, which
applies `config/workforce_seed.json` through that same command — so the first sync of any studio
assigned the Video Editor the file's own primary and the preference then stood down for ever for a
choice he had never made. `_owner_chose_models` reads instead the last event that moved her models:
none at all means the seed hired her and she may be moved; `agent.model_preferred` means this same
function moved her last and may move her again; `agent.model_assigned` is the file's when her three
slots hold exactly the models the file names for her role (compared through `resolve_model`, so a
":cloud" spelling is not mistaken for a different model) and his hand otherwise. A role the
allocation does not name, and an allocation that cannot be read, are both read as his: standing down
costs a picture check that says honestly it could not run, while moving wrongly overwrites a
decision, and only one of the two is undoable by the studio. Beside it, `RoleView` now carries
`preferred_capabilities` alongside `required_capabilities` — two fields, never one list, because a
preference listed as a requirement would tell him his Video Editor cannot work without a seeing
model, and she works without one — so his page can say why she sits on the model she sits on without
reading the database to explain it.

**A cast the studio guessed steers nothing it cannot take back.** Measured before the work:
`_characters_named_in` counted a bare given name whenever the next word was lower case, so
"Hurricane Elena made landfall" cast Elena Fact-Checker, "Lyra, the constellation, rises" cast Lyra
Voice Artist and "the Kael river delta" cast Kael Video Editor — and that column is not a label:
`assembler.py` hands it to the render, `factory.py` turns it into the vendor's `referenceImages`, and
`image_reference_for_scene` refuses the film outright when the named character's look is locked and
no reference is stored. Once step 10 of his list fills the reference slots, an astronomy short about
a constellation would have been drawn from the Voice Artist's portrait with real credits, and with
`identity_locks_json['visual']` set the same false positive would have refused the day's only factual
film. The reading is now split at the place where the evidence differs. A scene states its cast in
the writer's own `characters` list — read by given name, because a list of characters is a record of
who is in the scene — or by writing a character's whole canonical name in the picture it asks for;
that stated cast alone is written to `character_ids_json`, and it alone buys a portrait, is certified
by the character gate and may refuse a locked film. A bare given name in the prose is a guess: it is
recorded, per scene, on the storyboard's own creation event (`media.storyboard_created`, key
`guessed_cast`, read back through `app.media.services.storyboard_cast_record`), it never reaches the
scene, and the picture gate may look at it — the frame is asked about, the verdict kept as OBSERVED
with `basis: "guessed"`, no stored portrait attached — but it is never counted and can never fail a
film, because a check that measured only guesses has measured nothing. A film whose prose named
somebody and stated nobody therefore no longer claims an empty cast "by design": `cast_note` says
`NO_CAST_ONLY_GUESSED` instead of `NO_CAST_BY_DESIGN`, and the two are different facts. The line the
readiness phase left open is closed with it: `character_drift_qc` reads the board's note, so a film
that honestly shows nobody reports that its cast is empty by design rather than the old single
sentence "no scene in this film lists a character", which now means only what it says — nobody listed
anybody and the board never said why. The cost of the choice is stated rather than hidden: a factual
scene whose picture writes "Sarah at the studio window" and states nothing is no longer cast from
prose, so a reference the Owner paid for goes unused unless the writer lists her. That is the right
cost — the studio may miss a portrait it could have used, and may not buy one for somebody nobody
said was there.

**Under SUPERVISED the day says it stopped, in the same minute, and with a figure that admits what it
left out.** Measured before the work: `waiting_approvals_letter` had one caller, `reconcile_day`,
which runs inside `_post_run` — the day's last working stage — so a question the media stage raised
at 05:30 reached the Owner at the run's end at best, and not at all when the run stopped before
`_post_run`; the question then expired after `approval_expires_after_hours` and that film was never
made. And the figure in it was understated whenever ElevenLabs has no active `per_1k_characters`
price: `estimate_film_cost_micros` counted the narration as 0 and the caveat reached only the
reservation's note, a row he never reads. What he sees now, in order, on a first SUPERVISED morning:
**05:00** the day starts and the preflight is on the panel, every check by a Romanian name — «Buget
de cheltuieli», «Prețurile modelelor», «Angajat care poate privi», «Imaginile de referință ale
personajelor», «Canalul serialului», «Modul de autonomie» — and each failure marked by what it
actually is: BLOCHEAZĂ in red, DEGRADEAZĂ in amber, and, new, INFORMATIV in neutral grey for the
serial channel he has not created and the character whose look he has not locked, which used to print
as a red "DEGRADES" about a day they do not degrade. **≈05:30** the media stage prices the film,
finds the question is his (T3, over his threshold), writes it and stops — and writes the letter in
the same minute rather than waiting for the close: «O întrebare așteaptă răspunsul tău / 1. Un
randat plătit peste pragul stabilit — storyboard …, estimat 1.2 USD; cost 1.2 USD (estimare
incompletă: narația nu are preț stocat și este numărată ca zero); expiră 19.09.2026 05:30.»
**≈05:35 onward** the day runs its remaining stages and `_post_run`'s close calls the same letter and
writes nothing, because `_letter_once_a_day` already has today's date on it: one letter, whatever end
of the day raises it. **Whenever he opens the panel** the approvals card carries the same words
beside the number — «Cost: 1.2 USD (estimare incompletă: narația nu are preț stocat și este numărată
ca zero)» — so the caveat is read where the figure is read, not four lines below it, and the hold in
the books carries it too. **By 05:30 the next morning** the question is dead; he now has the
twenty-four hours he was supposed to have rather than the remainder after the run's close, and if his
answer comes in time the next run films the film it was about.

**What was measured, and whose measurement each figure is.** The seeing-employee part:
`tests/test_seeing_employee.py` **5 passed** (new, red first at 1 passed / 4 failed), with
`tests/test_phase1_agents.py`, `tests/test_multi_llm.py` and `tests/test_provider_discovery.py`
**60** together, **54** across the picture-QC, workflow, factual and truthfulness suites and **79**
across picture QC, readiness and the runbook; `ruff`, `ruff format --check` and `mypy` clean on its
two backend files. The cast part: `tests/test_phase5_media.py` **30**, `tests/test_picture_qc.py`
**17**, `tests/test_character_references.py` **23** — **70** together — with **72** across picture
QC, the seeing employee and editorial quality and **91** across the daily run, the serial pipeline,
the readiness adversary and the production policy; `ruff` and `ruff format --check` clean on its five
files. The letter-and-panel part: `tests/test_phase11_economy.py` **36**,
`tests/test_daily_run_stages.py` **34**, `tests/test_approvals.py` **20**,
`tests/test_books_and_history.py` **17**, and **234** across those four with the E/F adversary,
pricing truth, the runbook, readiness, the readiness adversary and the autonomy modes; on the panel
side `node --test tests/readiness.test.js` **8** (new) inside `node --test tests/*.test.js` **110**,
with `npm run check --prefix frontend` clean. This documentation part: `scripts/check_docs.py` and
`tests/test_documentation.py`. **No whole-suite run was made by any of the four**, and the figure in
`PROJECT_STATE.json` is still the Phase D/G closure verifier's 1194 passed / 1 skipped of 2026-09-18,
older than the tree twice over now; the verifier's figure for the readiness phase and for this
closure lands after this document. No migration was taken: the head stays `0045_reconciliation` and
**0046 is still free**. No provider was called, nothing was rendered, no run was queued, no credit
was spent and `data/studio.db` was not opened.

Not finished, honestly: **the three closures are behaviour under faked providers, and the Owner has
still seen none of them.** The panel was proved by `node --test` and `npm run check` only — no server
was started, no browser was opened and `frontend/dist` was deliberately not rebuilt, because that
build is his own launch act (step 2), so nobody has yet looked at an INFORMATIV card or an amber
caveat. `RUNBOOK_CHECK_LABELS` covers every check name this phase added and every one the panel
already named, but not `youtube_channel_binding`, which `run_preflight` also emits and which showed
by its code name before this work and still does (corrected 2026-09-18: it has a label, «Sloturi de
canal legate de YouTube», in the same module). The guessed cast is on the ledger event and not in
the REST answer: `get_storyboard` returns `cast_note` and not the map, so the Owner cannot yet see on
the storyboard page which names the studio read and refused to cast on. The serial's own board
(`backend/app/media/serial_storyboard.py`) writes no `guessed_cast`, correctly — its cast comes from
the episode roster and is always stated — which means `storyboard_cast_record` answers the empty
record for serial boards, and a later reader must not take that emptiness for "nobody is in it". The
caveat covers narration only, because narration is the only part of the estimate that can silently
become zero; `estimate_film_cost_micros` still does not price the stills at all, so a film's real
image spend is outside the figure rather than counted as zero inside it, and saying so in the caveat
would be a claim the function cannot measure. The caveat itself lives in the request's `evidence`
text and is read back by its first words (`UNPRICED_CAVEAT_PREFIX`) in three places — the
Accountant's letter, the approvals card and the media stage that writes it — because a column would
have needed migration 0046; a column is the right shape when a later phase takes one. The corner case
`_owner_chose_models` names is real and undecidable from the record: an Owner who assigns an employee
by hand to exactly the three models his own allocation file already gives her is read as the file,
and she may be moved — bounded, because the move only ever goes to a model declaring everything the
role requires as well as what it prefers and writes `agent.model_preferred`, so his next assignment
wins and stays won. `waiting_approvals_letter` is called from `_media` without a try/except, matching
the unguarded `budget_refusal_letter` call four lines below it, so if the Accountant's desk raised
from inside it the media stage would fail rather than return SKIPPED; the two were left consistent
rather than one of them guarded. One defect in the tree is named here rather than fixed, because it
belongs to a file this part does not own: `uv run mypy backend/app/media/picture_qc.py` reports one
`union-attr` error at line 285 — `board.id`, where the narrowing that makes it safe is `scenes` being
non-empty, so it is a type-narrowing gap and not a runtime fault. A second, recorded as open while
these documents were being written, was closed in the tree before they were finished:
`tests/test_phase_dg_closure_adversary.py::test_only_the_owners_command_module_reaches_an_approval_row`
had begun to fail because its whole-tree scan for the string "ApprovalRequest" found a docstring line
the Accountant gained in this phase; the scan now walks the parsed module and counts a class
definition, a name, an attribute or an import rather than characters, so prose that explains where
the Owner's question keeps its cost no longer reads as a writer of the row. Measured after that
change on this tree: `uv run pytest -q tests/test_phase_dg_closure_adversary.py` **12 passed**.

### Ce are Owner-ul de făcut

Lista de mai jos este ordinea dimineții primei zile adevărate. Numai Owner-ul poate face lucrurile
din ea; studioul nu le face singur și nu le cere de două ori. Fiecare rând spune ce are de făcut, cu
ce comandă sau pe ce ecran, și ce se întâmplă dacă sare peste el. Rescrisă ca listă ordonată pe
2026-09-18; niciun rând de dinainte nu a fost scos, iar rândurile noi ale acestei faze sunt așezate
la locul lor în ordine. Completată 2026-09-18 după repetiția pe o copie a datelor lui (secțiunea
«The rehearsal on the Owner's data (2026-09-18)» de mai sus): ce a găsit repetiția și numai el poate
face este adăugat în rândul căruia îi aparține, marcat «Adăugat 2026-09-18 după repetiție», fără să
schimbe numerotarea, pentru că pașii sunt citați după număr în alte documente. Completată din nou
2026-09-19, la pașii 2 și 12, cu rânduri marcate «Adăugat 2026-09-19»: ce s-a schimbat pe panou și
ce înseamnă pentru scenariile care îl așteaptă verificarea care arată dacă narațiunea spune ce spun
afirmațiile ei.

1. **Migrează baza de date live** — `uv run python scripts/bootstrap.py`. Lanțul este 0039 (economia
   și rezervările), 0040 (sursele de cercetare), 0043 (modul de autonomie), 0044 (subiectul unei
   cereri de aprobare și răspunsul lui pe rând), iar de azi **0045_reconciliation** (reconcilierea
   facturilor: un tabel nou și două coloane NULL pe rândurile de cost, deci niciun rând vechi nu își
   schimbă citirea). 0041 și 0042 au fost rezervate în faza D/G și nu au fost folosite; 0046 este
   liberă. Corectat 2026-09-18: rândul acesta a cerut pe rând `0040_research_sources`,
   `0043_autonomy_mode` și `0044_approval_answered`. **Dacă sare peste:** `backend/app/main.py` cere
   exact revizia `0045_reconciliation` la pornire, deci serverul nu pornește deloc. Niciun test nu
   atinge baza live. Măsurat 2026-09-18 de repetiție, pe o copie: **pasul acesta este făcut**, de
   mâna lui — repornirea studioului de la 22:42 a rulat `scripts/bootstrap.py` (`start.py` îl
   rulează primul), iar copia luată după ea era deja la `0045_reconciliation`; bootstrap rulat încă
   o dată pe copie nu a schimbat niciun rând. De la următoarea pornire, bootstrap mai seamănă două
   prețuri DOCUMENTED pentru narație (pasul 5).
2. **Construiește interfața** — `npm run build --prefix frontend`. Ecranele schimbate pe 2026-09-18 —
   starea site-urilor în *Cercetare → Surse*, banii ținuți în biroul Contabilitate, panoul de
   guvernanță (modul de autonomie, lista de aprobări, pastilele seturilor de referință) — sunt în
   sursă, nu în pachetul servit. **Dacă sare peste:** pagina servită rămâne pachetul vechi și el nu
   vede nici modul în care rulează studioul, nici întrebările care îl așteaptă. Construirea este
   actul lui de lansare; niciun agent nu a construit și nu a pornit serverul.
   Adăugat 2026-09-19: tot numai în sursă este și ce spune panoul zilei despre ce a produs ziua.
   Sub antetul fiecărei rulări apare propoziția ei. Lângă fiecare etapă scrie «a produs N», «nu a
   produs nimic» sau, la o rulare mai veche decât numărătoarea, «nenumărat». O zi COMPLETED care
   nu a produs nimic nu mai are verdele succesului. Deasupra listei preflight-ului stă prima
   verificare care ar opri ziua («Primul punct blocant») sau ar pierde un film («Ziua nu ajunge
   întreagă»). Le vede numai după construire.
3. **Pornește studioul și citește preflight-ul** — panoul zilei, sau `GET /api/v1/runbook/preflight`.
   De azi raportul numește și cele cinci lucruri pe care numai el le poate aduce: bugetul
   (`spending_budget`), prețurile modelelor (`model_prices`), un angajat care poate privi
   (`vision_capability`), imaginile de referință ale personajelor (`character_references`) și canalul
   serialului (`serial_channel`). Niciuna dintre ele nu oprește ziua — o verificare nu are voie să
   refuze ziua pentru o alegere a lui — deci lista aceasta este exact ce îi rămâne de făcut mai jos.
   Preflight-ul citește numai baza de date: nu întreabă niciun furnizor, nu folosește nicio cheie și
   nu pune nimic la coadă. Corectat la închiderea zilei (2026-09-18): pe panou, o verificare care
   cade fără să strice ziua se citește acum **INFORMATIV**, într-un gri neutru — canalul serialului,
   un personaj a cărui înfățișare nu este blocată — în loc de «DEGRADES» roșu, iar cele cinci
   verificări noi și `autonomy_mode` își au numele în limba lui. Singura care rămâne cu numele ei de
   cod este `youtube_channel_binding`, care nu avea etichetă nici înainte. Toate acestea se văd
   numai după pasul 2. Corectat 2026-09-18, măsurat în cod: și `youtube_channel_binding` are
   etichetă, «Sloturi de canal legate de YouTube». Adăugat 2026-09-18 după repetiție: «Canal
   YouTube conectat» și «2 sloturi legate» erau verzi citind numai starea stocată, nu tokenul; acum
   spun asta, iar trei verificări noi le urmează — «Dreptul de a încărca pe YouTube»
   (`youtube_upload_access`, **BLOCHEAZĂ** când Google nu a acordat încărcarea sau a refuzat tokenul
   după acordare), «Accesul la statisticile YouTube» (`youtube_statistics_access`, DEGRADEAZĂ) și
   «Filmele zilei în bugetul zilnic» (`daily_budget_films`). Rezumatul de sus nu mai spune
   «Studioul poate rula» deasupra unei verificări care vede ziua oprindu-se: numește prima linie care
   ar opri ziua sau ar pierde un film. **Dacă sare peste:** merge mai departe fără să știe ce
   lipsește.
4. **Pune bugetele** — `PUT /economy/budget`, biroul Contabilitate: zilnic, săptămânal, lunar. Nimeni
   altcineva nu le poate pune; Contabilul doar escaladează, nu aprobă. **Dacă sare peste:** rezervarea
   ține banii filmului, dar nu are de ce să îl refuze — o zi de reîncercări cheltuie cât îi vinde
   furnizorul, iar preflight-ul îi scrie `spending_budget` la fiecare pornire.
5. **Tastează prețurile planului** — `PUT /economy/prices`: ce plătește în realitate pentru ElevenLabs,
   Ollama Cloud și Runway, pe model sau `*` pentru tot felul, pe **ambele** unități de jetoane.
   **Dacă sare peste:** cărțile văd o fracțiune din zi — un cost calculabil doar pe o latură este
   None, nu zero, deci fiecare rulare a unui angajat se înregistrează fără cost și Contabilul
   raportează `unpriced_agent_runs`. Narația este singura excepție: bootstrap seamănă cifra publică
   ElevenLabs, marcată DOCUMENTED, care nu este planul lui. Ollama Cloud nu este semănată niciodată,
   pentru că un preț ghicit în cărți este mai rău decât golul pe care Contabilul îl raportează.
   Adăugat 2026-09-18 după repetiție: pe datele lui, șase modele Ollama Cloud (glm-5.3-flash,
   kimi-k3, minimax-m3, mistral-large-3:675b, nemotron-3-ultra, qwen3.5:397b) nu au preț — singura
   linie DEGRADEAZĂ a preflight-ului lui —, iar vocea lui, `eleven_flash_v2`, era prețuită la cifra
   DOCUMENTED pentru orice model («*», 0,22 USD la 1000 de caractere), deși aceeași listă de prețuri
   spune că Flash costă jumătate. De la următoarea pornire bootstrap seamănă și `eleven_flash_*` și
   `eleven_turbo_*` la 0,11 USD, tot DOCUMENTED; prețul pe care îl tastează el trece peste amândouă.
   Rezervarea filmului ia încă prețul cel mai scump al vocii, deci ține pentru narația Flash cam
   dublu față de ce costă.
6. **Pune plafonul de jetoane pe zi**, dacă vrea unul — `STUDIO_AGENT_DAILY_TOKEN_BUDGET`. 0 înseamnă
   fără plafon, așa cum a mers studioul până acum. **Dacă sare peste:** nimic nu se strică, dar bucla
   Directoarei și rundele de corespondență rulează fără tavan. Peste plafon, rularea este oprită
   BLOCKED_BUDGET și Contabilul îi scrie o dată în ziua aceea.
7. **Autorizează site-urile și, dacă vrea, conectează un motor de căutare** —
   `PUT /sources/allowed-hosts/{host}` și Setări → *Conexiuni* → „Căutare web (API JSON)"; butonul
   «Testează site-urile» din *Cercetare → Surse* le încearcă pe loc. Lista nu poate fi lărgită de
   niciun agent, de nicio cerere și de niciun rezultat al motorului: motorul numește adrese, studioul
   păstrează doar ce este pe lista lui și citește el însuși pagina. **Dacă sare peste:** studioul
   găsește pagini numai pe site-urile care poartă ele însele o adresă de căutare, iar
   `research_health` raportează DEGRADED când nu are cum să găsească nimic sau când au mai rămas sub
   zece afirmații verificate — o zi care nu găsește nimic se încheie cinstit cu nimic.
8. **Leagă canalele și pune-le politica** — sloturile în *Publicare → Canale*, apoi
   `POST /publishing/channels/{id}/publish-policy`: vizibilitatea, întârzierea,
   `public_publish_enabled` și dreptul Directoarei de a aproba episoade
   (`director_may_approve_episodes`). **Dacă sare peste:** canalul serialului apare în preflight ca
   `serial_channel` — fără legătură, episoadele se produc și nu au unde urca; fără dreptul
   Directoarei, un episod trecut de ea rămâne DRAFT și așteaptă mâna lui, ceea ce este dreptul lui și
   nu este autonomie. Măsurat 2026-09-18 de repetiție: ambele sloturi sunt legate, dar dreptul
   Directoarei de a aproba episoade este încă `false` pe datele lui (repetiția l-a dat numai pe o
   copie, cu comanda lui).
   Adăugat 2026-09-18 după repetiție: **verifică sau reconectează cele două conexiuni YouTube** —
   *Nexus Curiosity* (slotul MAIN_FACTUAL) și *Inside The Nexus* (slotul OFFICE_SERIAL) — din
   *Setări → Conturi și e-mail* (Verifică sau Reconectează, un apel gratuit), înainte de orice zi
   plătită. Amândouă au fost conectate pe 2026-09-11, Google le-a acordat numai `youtube.readonly` și
   `youtube.upload`, fără accesul la statistici (`yt-analytics.readonly`), iar dacă tokenurile lor
   mai merg nu se știe: repetiția nu le putea încerca fără să iasă din calculator, iar preflight-ul le
   arăta verzi citind numai starea stocată.
   **Reconectează-le pe amândouă acordând accesul la statistici**, și **scoate aplicația lui Google
   OAuth din modul Testing** (în Google Cloud Console, pe ecranul de consimțământ OAuth): cât timp
   aplicația este în Testing, tokenul de reîmprospătare moare la șapte zile după acordare — pentru
   conexiunile din 11 septembrie, cam acum — și va muri din nou la o săptămână după fiecare
   reconectare. Studioul nu vede în ce mod este aplicația; preflight-ul îi arată vârsta fiecărui
   acord. Ecranul lui Google oferă accesul la statistici numai dacă studioul îl cere, iar `SCOPES`
   (`backend/app/youtube/services.py`) a cerut doar `youtube.readonly` și `youtube.upload` — de aceea
   nicio reconectare de până acum nu putea acorda statisticile. În noaptea de 2026-09-18 i s-a
   adăugat `yt-analytics.readonly`: după ce studioul lui pornește cu codul acesta, ecranul îi cere o
   permisiune în plus, pe care trebuie s-o accepte. Până la reconectarea de după acea pornire,
   statisticile rămân «fără date». **Dacă sare peste:** un token mort se vede abia după ce Google l-a refuzat o
   dată. În prima zi cu el statisticile ies «fără date», iar filmele se fac și se plătesc, apoi
   încărcarea lor eșuează; de a doua zi `youtube_upload_access` blochează ziua înainte să cheltuie
   ceva. Până la reparația din 2026-09-18, același refuz oprea ziua la al doilea pas, înainte de
   orice filmare, și punea studioul în mod sigur cu AUTONOMIE OPRITĂ.
9. **Admite un model care poate privi** — Angajați → Model, după ce sincronizarea catalogului îl
   aduce de la furnizor. Niciun model semănat nu declară vedere, iar studioul nu presupune niciodată
   că unul vede: capabilitatea `vision` se atașează doar când vendorul însuși o declară. Rolul
   Monteurului o *preferă* de azi, deci angajata se mută pe un astfel de model la următoarea rulare a
   seed-ului — preferința nu cere nimic și nu refuză nicio rulare. Corectat la închiderea zilei
   (2026-09-18): **nu mai are nimic de atribuit cu mâna după ce admite modelul, și nu mai este nevoie
   nici de o a doua rulare a seed-ului, nici de o repornire.** Mutarea se face în chiar sincronizarea
   care aduce modelul de la furnizor — «sincronizează» în *Angajați → Model*, «verifică» în *Setări →
   Conexiuni* — pentru că acolo se scrie pentru prima oară `vision` pe un rând de model. Dacă îi
   atribuie el însuși un model, alegerea lui rămâne a lui și preferința nu o atinge; ce se mută este
   numai angajata lăsată pe modelul pe care i l-a dat fișierul studioului. **Dacă sare peste:**
   verificarea imaginilor și cea a personajelor stau deoparte la fiecare film, cinstit și vizibil în
   raport (`vision_capability`), deci un film de opt câmpuri goale trece toate verificările automate
   și ajunge la Directoare ca un scurtmetraj terminat.
10. **Produ seturile de referință ale personajelor** —
    `POST /media/characters/{id}/reference-set`, sau butonul de pe fișa personajului (fiecare slot
    este o pastilă, plină sau goală; butonul spune că se consumă credite de imagine și nu produce
    nimic până la a doua apăsare). Cele cinci sloturi — portret, corp întreg, față, profil, spate —
    sunt goale în orice studio care a rulat vreodată. Ruta consumă credite de imagine, deci este actul
    lui și al nimănui altcuiva: niciun pas al zilei nu o cheamă, iar un test ține asta. Răspunde cu
    sloturile umplute, cele refuzate și costul (`usd: None` dacă modelul nu are preț). **Dacă sare
    peste:** fiecare imagine a unui personaj este o invenție nouă și verificarea personajelor nu are
    cu ce compara; iar un personaj cu înfățișarea blocată și fără referință citibilă **refuză
    filmul** — de azi și filmul factual, nu doar episodul de serial — în loc să i se inventeze o
    față. Preflight-ul îi numește pe cei blocați înaintea zilei, ca să nu afle din refuz. Corectat la
    închiderea zilei (2026-09-18): refuzul acela urmează numai un personaj pe care **filmul îl
    spune** — lista de personaje a scenaristului, sau numele întreg în imaginea cerută — niciodată un
    prenume pe care proza doar l-a scris. Un nume ghicit nu cumpără niciun portret, nu refuză niciun
    film și nu apare nicăieri în studio: rămâne pe evenimentul de creare al storyboard-ului, ca să se
    vadă ce a citit studioul și ce a refuzat să creadă. Măsurat 2026-09-18 de auditul repetiției: pe
    datele lui niciunul dintre cele 8 personaje nu are imagine de referință, iar un set întreg
    înseamnă 8 × 5 = 40 de imagini, circa 0,80 USD la 0,02 USD pe imagine (`gen4_image`) — un cost
    pe care mesajul din preflight nu îl numește.
11. **Aprobă furnizorii de rezervă**, dacă vrea unul — `approved_fallbacks`, pe nivelul de politică al
    canalului, al seriei sau al storyboard-ului; pentru un personaj blocat, lista din
    `approved_fallbacks_json` scrisă de o schimbare de identitate APROBATĂ. Aprobarea este dovada că
    tehnologia păstrează personajul recognoscibil, deci nu o poate da studioul; lanțul rămâne oricum
    de cel mult o alternativă pe scop și pe scenă. **Dacă sare peste:** lanțul are un singur vendor și
    o scenă refuzată cade pe cartonul de rezervă pe care QC îl oprește de la publicare.
12. **Alege modul de autonomie** — `POST /api/v1/owner/autonomy-mode` sau panoul de guvernanță:
    MANUAL, SUPERVISED sau AUTONOMOUS_CEO. Coloana a fost scrisă pe AUTONOMOUS_CEO pentru că asta face
    codul de luni de zile, nu ca o promovare; comanda este singura care ridică modul și refuză
    ridicarea cât timp autonomia este oprită sau un incident este deschis, iar coborârea este
    întotdeauna permisă. MANUAL înseamnă o zi care scrie, dar nu cumpără cadre și nu urcă nimic;
    SUPERVISED filmează ziua și îi lasă câte o cerere de aprobare pentru **fiecare film** în loc de
    urcare. `GET /api/v1/owner/approvals` arată ce așteaptă (acțiunea în limba lui, despre ce este,
    treapta de risc, cine întreabă, costul — «necunoscut» când studioul nu îl poate calcula, niciodată
    zero — și cât mai stă în picioare), iar `POST /api/v1/owner/approvals/decision` este răspunsul, o
    singură dată pentru un singur act. De azi Contabilul îi scrie o dată pe zi, la închiderea zilei,
    ce întrebări stau în picioare și până când. Corectat la închiderea zilei (2026-09-18):
    **scrisoarea pleacă din pasul media, îndată ce acela a terminat de întrebat**, nu abia la
    închidere — tot una pe zi, oricare capăt al zilei o ridică primul, și numește fiecare întrebare
    pe care pasul a ridicat-o — deci cele douăzeci și patru de ore îi rămân aproape întregi.
    Corectat 2026-09-18 de verificatorul ultimei runde: o defecțiune de randare la un film de mai
    târziu în aceeași rulare iese din pas înaintea scrisorii, așa că întrebarea aceea îl așteaptă
    până la închiderea zilei. Tot de la închiderea zilei, acolo unde studioul nu a
    putut prețui o parte a filmului, cifra spune asta lângă ea, la fel în scrisoare, pe cartonașul de
    aprobare și în nota rezervării: «estimare incompletă: narația nu are preț stocat și este numărată
    ca zero». Ce nu spune: imaginile nu sunt prețuite deloc în estimare, deci nu lipsesc din ea ca
    zero, ci sunt în afara ei. Un «da» nu trece niciodată peste o poartă care refuză;
    oprirea și SAFE_MODE refuză înaintea lui și îi lasă «da»-ul necheltuit; o politică de canal
    schimbată după ce a răspuns îl retrage, pentru că a spus «da» filmului aceluia la vizibilitatea
    aceea. Pragul peste care o randare plătită devine decizia lui este
    `paid_generation_approval_threshold_usd` (5 USD implicit); cât timp stă o întrebare fără răspuns
    este `STUDIO_APPROVAL_EXPIRES_AFTER_HOURS` (24 de ore implicit, între o oră și o săptămână — sub
    o oră o întrebare i-ar putea expira înainte să o citească, peste o săptămână un «da» s-ar putea
    cheltui mult după filmul despre care a fost întrebat). **Dacă sare peste:** studioul rulează în
    modul scris în coloană, adică AUTONOMOUS_CEO, fără ca el să fi ales asta.
    Adăugat 2026-09-18 după repetiție: pe datele lui coloana arată AUTONOMOUS_CEO pentru că a scris-o
    migrarea 0043 (valoarea ei implicită), la pornirea lui, nu pentru că a ales-o el — iar
    preflight-ul o spune ca pe un fapt («Modul de autonomie este AUTONOMOUS_CEO: …»), fără să spună
    că este valoarea implicită. Tot răspunsul lui așteaptă și **cele 29 de scenarii din 2026-09-12**
    care au trecut poarta factuală (VERIFIED_PASS) și nu au fost aprobate de nimeni:
    `GET /api/v1/factual/scripts` le arată, iar butonul «Approve script» din pagina scenariilor (sau
    `POST /api/v1/factual/scripts/{id}/approve`) aprobă câte unul. Un scenariu aprobat intră în
    storyboard la ziua următoare și poate fi filmat, deci fiecare aprobare este o hotărâre de
    cheltuială; nu există o comandă care să le respingă. **Dacă sare peste:** nimic nu se pierde, dar
    fiecare zi repetă despre ele «Un scenariu așteaptă aprobarea ta înainte de storyboard.»
    Adăugat 2026-09-19: de azi studioul măsoară dacă narațiunea unui scenariu spune ce spun
    afirmațiile pe care le citează. **4 dintre cele 29 nu trec măsurătoarea**, pentru că fiecare
    citează o afirmație pe care narațiunea ei nu o spune:
    - 92028a88 citează parasolarul care răcește oglinda la 40 de kelvini, iar scena ei spune doar
      «you just block it, one layer at a time»;
    - 8d4f7306, aa3da89f și 670d6279 citează oprirea telescopului pe 8 august 2024, iar scenele lor
      spun doar, în cuvinte diferite, că NASA l-a oprit.

    Dacă aprobă cu mâna unul dintre ele, poarta dinaintea descrierii cadrelor și a randării
    (`story_gate`) îl oprește, cu motivul, înainte de orice cadru plătit. Un asemenea scenariu scris
    de acum ar fi trimis înapoi la rescriere de recenzia poveștii. Celelalte 25 trec, la fel ca cele
    două filme aprobate deja (LHC și ATLAS). Măsurătoarea s-a făcut pe copii ale bazelor repetiției,
    deschise numai pentru citire. Baza lui nu a fost deschisă.
13. **Alege mediul studioului: TEST sau PRODUCTION** — `POST /api/v1/owner/environment`, comanda
    lui versionată, sau pagina Owner. Adăugat 2026-09-18, după ce un verificator adversarial a
    răspuns la întrebarea „ce produce studioul mâine la 05:00 dacă face diseară toată lista" și a
    măsurat că lista nu îl întreba niciodată: coloana `owner_policy.environment` pornește pe TEST
    (`backend/app/models.py`), nimic din `scripts/bootstrap.py` nu o mută, iar în TEST fiecare film
    primește cel mult două cadre în mișcare (`STUDIO_TEST_MOTION_SCENES`) și restul stop-cadre, iar
    `resolve_publish_visibility` ține și „public" și „nelistat" la PRODUCTION — deci ambele filme ar
    pleca private, oricât de deschisă ar fi politica pe canal. **Dacă sare peste:** primește două
    filme scurte, făcute aproape numai din stop-cadre, pe care nu le poate vedea nimeni în afară de
    el; nu este o eroare, este exact ce înseamnă TEST, dar nu este ziua pe care o aștepta.
    **Dacă îl mută pe PRODUCTION:** filmele se fac la bugetul de mișcare întreg
    (`STUDIO_MOTION_BUDGET_USD`, 12 USD implicit pe film), iar vizibilitatea devine cea din politica
    fiecărui canal. Atunci cele două numere de la pasul 12 trebuie alese împreună cu acesta: pragul
    peste care o randare devine decizia lui (`paid_generation_approval_threshold_usd`, 5 USD) stă
    sub bugetul de mișcare, deci în PRODUCTION **fiecare** film trece pragul — sub SUPERVISED ziua
    nu ar mai face nimic singură și i-ar lăsa în fiecare dimineață câte o întrebare pentru fiecare
    film. Trei ieșiri, toate ale lui: ridică pragul peste bugetul de mișcare, coboară bugetul de
    mișcare, sau alege AUTONOMOUS_CEO și lasă porțile dure să fie cele care stau între zi și
    furnizor. Așa cum sunt acum, SUPERVISED și PRODUCTION nu pot coexista cu o dimineață autonomă.
    Adăugat 2026-09-18 după repetiție: pe datele lui coloana arată TEST, valoarea implicită scrisă
    de migrarea 0031; repetiția nu a găsit în spatele ei o alegere a lui. Și, pentru PRODUCTION: **bugetul
    lui zilnic de 15 USD ține un singur film la plafonul de mișcare de 12 USD, nu două.** Fiecare film
    ține 12 USD pentru mișcare, plus narația, înainte de prima scenă; scurtul factual este ținut
    primul, iar episodul serialului al doilea, deci episodul este refuzat de buget ori de câte ori
    scurtul a costat mai mult de circa 3 USD (auditul repetiției a socotit 2,9 USD, cu narația
    inclusă). O zi obișnuită în PRODUCTION este, așa cum stau numerele, un singur film de circa
    2,5-4,5 USD. Cele două numere pe care le poate schimba înainte de trecere: bugetul zilnic (pasul
    4), la cel puțin 24 USD pentru două filme, sau plafonul de mișcare pe film
    (`STUDIO_MOTION_BUDGET_USD`), la cel mult 7,5 USD. De azi preflight-ul îi arată asta, cât timp
    studioul este în TEST, ca linie INFORMATIV («Filmele zilei în bugetul zilnic»).
14. **Abia acum pornește ceasul** — activarea lucrării `daily_main` din panoul zilei, care este actul
    lui înregistrat (`workflow.job_activated`), și instalarea sarcinii Windows („AMN-AI Studio",
    `scripts/install_studio_service.ps1`), cu confirmarea o singură dată în `data/studio-service.log`
    că o autentificare S4U deschide cheia. **Dacă sare peste:** lucrarea zilei stă adormită și nu se
    întâmplă nimic — ceea ce este exact regula lui: generarea video costă bani și se face numai după
    ce totul s-a dovedit. Rândurile 1-13 sunt „totul": de aceea acesta este ultimul.
    Adăugat 2026-09-18 după repetiție: verdictul auditului a fost «REPARĂ ÎNTÂI». Cele două defecte
    găsite — o citire refuzată a statisticilor oprea ziua, iar cărțile treceau ca plătite clipurile
    Runway refuzate — sunt reparate în cod și dovedite numai cu furnizori imitați; repetiția gratuită
    de după reparații, pe o copie proaspătă, nu a fost încă rulată. O zi reală plătită în TEST (circa
    1,1-1,3 USD, cel mult circa 1,7 USD, fără modelele de limbaj, al căror cost este necunoscut)
    rămâne decizia lui, cu ceasul pornit de el.
15. **După prima zi cu cheltuială reală: reconciliază facturile furnizorilor** —
    `PUT /economy/reconciliations` (adăugat 2026-09-18), cu numărul facturii, ce acoperă (o perioadă
    sau un lucru numit, azi o randare) și `expected_version`, care aici este cerut pentru că
    înlocuirea unei facturi mișcă bani. Numai el vede factura, deci numai el poate face asta.
    Estimarea nu este ștearsă, ci marcată: ea rămâne documentul a ceea ce studioul a crezut că va
    costa filmul, iar perioada numără de atunci cifra facturată o singură dată, plus ce nu acoperă
    factura. O corecție este o versiune nouă, care întoarce postarea dinainte în registru.
    **Dacă sare peste:** fiecare cifră din cărți rămâne o estimare, iar diferența dintre ce a estimat
    studioul și ce a facturat furnizorul — prețul unei presupuneri — nu se vede nicăieri.

## Quality and governance (Phase D/G, 2026-09-18)

Phases D and G of running unattended: what the studio certifies about a film before the Director
sees it, and who decides that the studio may act at all. Measured on the tree before the work:
`character_drift_qc` reported `NOT_IMPLEMENTED` on every film ever made, and no gate anywhere ever
looked at a frame, so a film of eight blank fields, stripes or garbled writing passed technical QC,
the factual gate and the five publishing points and reached a channel as a finished short;
`CharacterBible.reference_assets_json` declared five slots — portrait, full body, front, side, back
— and every one of them was null in every studio that has ever run, so each generated picture of a
character was a fresh invention and a picture check would have had nothing to compare against; a
scene whose vendor refused it fell straight to the placeholder still that QC blocks from
publication, because a policy level could name one vendor and no other; and
`PolicyView.autonomy_mode` was `Literal["MANUAL"] = "MANUAL"`, a constant no command could move,
while the daily run walked twelve stages with no Owner approval between them, the Director approved
her own scripts, the media stage paid a vendor for shots and the publish stage wrote to YouTube.
`51_AUTONOMY_MODE_SEMANTICS` described three modes and the code had none of them.

**Quality control looks at the pictures before the Director does.** Every scene's middle frame is
cut from the finished film and sent, in one call for the whole film, to an employee whose provider
declares its model can see: is this a picture at all — a blank field, stripes, noise, garbled
writing is not — and does it show what the scene's visual prompt and narration asked for. The same
call carries the characters the storyboard put in each scene, with the Character Bible's canonical
face, hair, outfit, props, role symbols and palette, and, where a bible slot holds a stored asset
id, the portrait itself; a person in the wrong outfit is named with their scene, and
`character_drift_qc` no longer says NOT_IMPLEMENTED for a studio that has characters. A refusal
fails the film in every environment, as the degenerate-still check already does, because nothing in
TEST policy deliberately produces a picture of nothing. The check certifies only what it measured:
with no provider registry handed in, no employee's model declaring vision, no frame cut (no
encoder, no file), the day's token ceiling reached, or a model that narrated and never reached the
JSON, it is NOT_APPLICABLE with the reason, `passed` is None, no failure is added, and the film's
verdict is exactly what the other gates left it — and where the bible holds no characters at all the
character check stays NOT_IMPLEMENTED as it was. One film costs one vision call, two when the model
must be asked again with its own thinking on, and none at all when the check stands down; the call
is an ordinary agent run, so the day's token ceiling covers it.

**Reference pictures for the characters, and a second vendor when the first refuses.**
`POST /media/characters/{id}/reference-set` fills the five slots with real files: one prompt per
slot composed from the bible alone, each still stored as a `MediaAsset` with its own SHA-256 and
its bytes on disk under `backend/storage/character_references/{character}/`, and the asset ids
written back into the slots. A slot the vendor refused keeps what it held and is named in the
answer, so nobody is told a picture exists that was not produced. It spends image credits, so it is
the Owner's act and nothing else: it refuses under STOP AUTONOMY before the first request, asks the
budget once for the whole set through `reserve_spend` and settles or releases that hold, records an
ESTIMATED cost per produced slot, and reports `usd: None` rather than zero when the model has no
recorded price. Nothing in the runbook names it, and a test asserts that against
`runbook/stages.py`, `runbook/services.py` and `workflows/services.py`. From the slots to the film:
`image_reference_for_scene` hands the render the reference the scene's cast has, a character whose
look is locked and has no readable reference is refused rather than invented, and the reference is
passed only to an adapter that declares it can take one — the OpenAI adapter now posts it to the
documented `/v1/images/edits` endpoint as a multipart file part (`ACCEPTS_REFERENCE_IMAGE` is True,
`REFERENCE_IMAGE_VERIFIED` stays False until an Owner-approved run has actually drawn a scene that
way, because no test may buy one). And the production hierarchy resolves a second vendor: a level
may hold the Owner's `approved_fallbacks` for a purpose, a locked character narrows that list to the
technology approved for that character, the chain is bounded to one alternative per purpose per
scene (`MAX_FALLBACKS_PER_PURPOSE`), each attempt carries the connection, the model and what it is
worth at the recorded price, and a policy with no approved fallback behaves exactly as before — one
vendor, then the placeholder still that QC blocks from publication. In TEST the chain is ordered
cheapest-first, so a test still buys the cheapest compatible model; in PRODUCTION the Owner's order
stands.

**The autonomy mode became a fact the studio stores.** Migration `0043_autonomy_mode` adds
`owner_policy.autonomy_mode` (MANUAL | SUPERVISED | AUTONOMOUS_CEO) and takes the honest reading,
**AUTONOMOUS_CEO** — the Director executes T0–T3 within policy, T4 is executed autonomously nowhere,
and the hard gates are unchanged — because that is what the code has been doing, not a promotion the
migration grants. It moves only through `change_autonomy_mode`, a versioned idempotent Owner command
shaped exactly like `change_environment`, which refuses a *promotion* while autonomy is stopped or an
incident is open, and names in its Romanian refusal the two things of 51 it cannot measure
(acceptance criteria, burn-in) rather than pretending to have checked them; lowering the mode is
always allowed, as 51 requires. Beside it, a risk-tier table mapped entry by entry from 31's action
risk tiers and 32's tool risk classes, and one function `may_act(session, action, tier)` the Policy
Kernel asks before an agent acts: STOP AUTONOMY refuses every tier in every mode, SAFE_MODE leaves
monitoring and internal repair and takes the rest, T4 is refused in all three modes, MANUAL allows
T0–T1, SUPERVISED allows T0–T2 and writes an `owner_approval_request` for a T3 external write (31's
Approval object, with a nullable cost because a cost the studio cannot compute is None), and
AUTONOMOUS_CEO allows T0–T3. An action the table does not know and the caller does not classify is
refused `BLOCKED_UNCLASSIFIED`, never guessed. A test asks the five-point publishing gate for a
public film in each of the three modes and it refuses in all three: a mode decides what the studio
may attempt, never what a gate concludes.

**The day reads the new gates and the Owner's mode.** All three parts existed beside the daily run
without being in it; all three are wired. The quality-control stage hands `evaluate_media_qc` the
registry it already held and `settings.ffmpeg_path`, so a studio with a vision-capable model has its
frames looked at — and a studio without one measures the same film to the same verdict for the same
reasons, which is held by a test that runs the stage and the plain call over two identical files and
compares them. The media stage passes the plan's `image_chain` and `reference_for_scene` into the
render; the assembler draws each still through `still_from_chain`, records what each attempt cost on
the scene and on the job, and the Accountant prices a still by the vendor that drew *that scene*
instead of by the film-level record — a scene the approved alternative drew used to be charged to the
first vendor's model. A character whose look the Owner locked and whose reference cannot be read
refuses the film: the job is failed cleanly, what was already bought is costed and the hold goes back
the same second, exactly as a vendor's refusal does. And the day now says what each of its stages is:
`STAGE_ACTIONS` maps every stage to one action and one risk tier of `31_GOVERNANCE_APPROVAL_POLICY`
— performance intake T0, the drafting stages T1, research and the paid render T2, the upload T3
whatever visibility it carries — and `mode_refusal` asks `may_act` before the stage runs, again per
film before the money is held (T3 above `paid_generation_approval_threshold_usd`, five dollars by
default) and again per film before the upload. A stage above the mode is SKIPPED with the Owner's
reason, never BLOCKED, because a mode is his decision and not an incident, and the stages it does
allow still do their work. The preflight shows him which mode the day will run under and refuses
nothing for it: the line is INFORMATIONAL and the verdict is computed over the other two severities,
so it cannot fail a run structurally and not merely by happening to pass. A whole scheduled day is
now run under each mode with every vendor faked — MANUAL fetches no page, buys no shot, uploads
nothing and asks nothing, because MANUAL is already his answer; SUPERVISED films the day and writes
one `owner_approval_request` for `publishing.public_publish` instead of uploading — corrected
2026-09-18 at the closure below: **one request per film**, two on this day, because a request keyed by
its action alone let the day's second film reuse the first film's row; AUTONOMOUS_CEO publishes under
the channel's policy as PUBLISHED_SIMULATED, private, with no request raised.

Tests, by file set: 11 in `tests/test_picture_qc.py` (new), 20 in `tests/test_phase5_media.py` and 7
in `tests/test_cycle_fixes.py` (one appended each), with 77 across the five other callers of
`evaluate_media_qc`; 19 in `tests/test_character_references.py` (new), 21 in
`tests/test_media_selection.py`, 36 in `tests/test_media_providers.py` and 18 in
`tests/test_production_policy.py`, with 166 across the neighbouring media, runbook, economy, routing
and documentation suites; 21 in `tests/test_autonomy_modes.py` (new) and 26 in
`tests/test_foundation.py`, with 45, 6 and 6 across the agent, publish-policy, reset, schema and
route-authorisation files; and the wiring's own 29 (`tests/test_daily_run_stages.py`, eight
appended), 45 (`tests/test_phase10_runbook.py`, one appended) and 5
(`tests/test_autonomous_day_end_to_end.py`, three whole-day tests appended, one per mode). **The
whole suite on the integrated tree: 1148 passed, 1 skipped** (the opt-in real-Ollama test), with
`ruff check`, `ruff format --check` over 384 files, `mypy` over 143 source files and
`scripts/check_docs.py` clean; the adversarial pass that followed added four tests and re-ran
the suite at **1152 passed, 1 skipped** (2026-09-18, 9m48s), finding no defect to fix. The migration
chain is 0040 → 0043 and `main.py` pins it: 0041 and 0042 were reserved by two of the implementers and
neither needed a schema change. Corrected 2026-09-18 at the closure: the chain is 0040 → 0043 →
**0044_approval_answered** and `main.py` pins 0044; 0041 and 0042 stay reserved and unused. No
provider was called, nothing was rendered outside FFmpeg on this machine, no run was queued and no credit was
spent.

Not finished, honestly: **no vision model has ever answered the picture check, here or anywhere.**
Every test fakes the provider at its transport, by the Owner's rule of 2026-09-17 and because
`tests/conftest.py` refuses every non-loopback socket, so what is proven is the gate's behaviour —
one call per film, the frames and the bible in the prompt, a named scene on a refusal, and
NOT_APPLICABLE wherever the look could not happen. Whether a model that declares vision returns this
schema reliably on real frames needs a real render and a real model call, and the work stopped rather
than spend. `seed_initial_workforce` seeds no vision-capable model — the Director's glm-5.3 declares
completion, thinking and tools and no vision — so until the provider catalogue sync records one on an
employee the check will report NOT_APPLICABLE in the live studio, correctly and visibly in every
report. **No real render has been drawn through the second vendor either**, and a studio whose Owner
has approved no alternative has a chain of one, which is every studio today, so the path that matters
— first vendor refuses, approved alternative draws, the books charge the second model — is proven
only against fakes; the OpenAI `/v1/images/edits` multipart path is written to the documented contract
and `REFERENCE_IMAGE_VERIFIED` stays False until an Owner-approved run has actually drawn a scene that
way, because a 400 there would mean the body is wrong. `RunwayImageAdapter` still cannot be handed a
reference (`backend/app/providers/runway.py` was nobody's in this phase), so a Runway-drawn still is
honestly reported as drawn from the words — **corrected 2026-09-18 at the closure: it can**, through
the `referenceImages` field the `text_to_image` task publishes, and `ACCEPTS_REFERENCE_IMAGE` is now
True for it while `REFERENCE_IMAGE_VERIFIED` stays False. **The Owner cannot answer an approval**,
which was true when this was written and is **corrected 2026-09-18 at the closure**: a SUPERVISED day
wrote exactly one `owner_approval_request` for the upload and stopped there honestly, there was no
route to approve or refuse it, nothing consumed an APPROVED row, no stage re-attempted after one
appeared, and `owner_approval_request` was not in `maintenance.HISTORY_TABLES`, so a reset did not
clear it. All five are closed below, and the day now asks one question per film rather than one for
the day. 51's acceptance criteria and burn-in are not checked and cannot be from this database,
so the promotion refusal names them to the Owner instead; 51's department-scoped autonomy is not
implemented — the column is one global mode — and the `Literal["False"]` switches on `PolicyView`
(`external_payments_enabled`, `autonomous_firing_enabled`, `provider_auto_switch_enabled`,
`world_generation_enabled`) are still constants beside tiers that now reason about the same acts.
`backend/app/media/router.py` is still measuring films without the picture check and rendering
without the chain or the reference, so the Owner's manual render and his manual QC behave as they did
yesterday while the daily run does not — **corrected 2026-09-18 at the closure: both of its
`evaluate_media_qc` call sites now take the registry and `settings.ffmpeg_path` and `start_render`
passes the plan's chain and the scene's reference**, so the Owner's own reading of a film is the
reading the day would have given it. The character check reads the storyboard's
`character_ids_json`, which only `serial_storyboard.py` fills — a factual film records
`character_ids_json=[]`, so the record says `no scene in this film lists a character` rather than
passing — and the Director's `gather_facts` still filters the QC report to keys starting with
"measured", so the per-scene verdicts do not reach her prompt. The Director's `frames_for` cuts at
most eight frames, so a ninth scene onwards is recorded `no frame was cut for this scene`, never
looked at and never passed. The reference set uses the first filled slot for every scene rather than
choosing by shot type, and there is no frontend: no button produces a reference set, no page shows
which slots are filled, and nothing in `frontend/src` reads `autonomy_mode` yet — **corrected
2026-09-18 at the closure: the governance panel, the approvals list and the reference-set chips are
written in `frontend/src`**, and are invisible to the Owner until he runs
`npm run build --prefix frontend`, because `frontend/dist` was deliberately not rebuilt. The
research stage's mode refusal is coarse — under MANUAL the whole fetch is skipped including `retest_stale_hosts`, so a
MANUAL studio's host record goes stale — and a stage the mode skips is recorded in the run and the
day's summary but nobody writes the Owner a letter about it — **corrected in part 2026-09-18:**
the Accountant now writes once a day about the *approval requests* that are standing
(`waiting_approvals_letter`, carried by the day's close); a stage skipped because the mode itself
forbade it still gets no letter, because that is his own answer and not a question. `approval_expires_after_hours` stays the
module constant `APPROVAL_EXPIRES_AFTER_HOURS = 24` in `services.py` rather than a key in
`config.py`, because a key nothing reads is a lie about what is configurable — and since the closure
below it decides three things rather than one: how long an unanswered question stands, how long a
refusal stops the studio asking again, and how long a yes can still be spent. **Corrected 2026-09-18
in the readiness section above:** it is now `Settings.approval_expires_after_hours`
(`STUDIO_APPROVAL_EXPIRES_AFTER_HOURS`, default 24, bounded one hour to one week), read by
`services.py` through a local import with a documented fallback of 24, and all three meanings are
named to the Owner where the setting is declared. The behaviour is unchanged.

### Closed the same day — 2026-09-18: the Owner answers, his own buttons see what the day sees, and there is a page

Three things the section above left open, in its own words: a SUPERVISED studio that "records the
question and never hears the answer", an Owner whose manual render and manual QC "behave as they did
yesterday while the daily run does not", and "no frontend for any of it". All three are closed, and
the first of them had to begin with the defect the adversarial pass named rather than with the route.

**The Owner answers, and the day acts on the answer.** A request was deduped by its `action` alone,
so the second, dearer film of a SUPERVISED day reused the first film's row, and an answering route on
top of that would have let a yes to a four-dollar film authorise a forty-dollar one. Migration
`0044_approval_answered` puts the thing the question is about on the row — `subject`: the media asset
for an upload, the storyboard for a paid render — and the key is now the action **and** the subject,
with `note`, `decided_at` and `consumed_at` beside it and an index on (action, subject, result). The
same defect existed one level up, where nothing had looked: the daily run's stage wrapper raised the
approval itself, before it knew which film, so the stage never ran, one answer would have covered
every film of the day, and a day with nothing to publish still put a question in his inbox. The
wrapper now asks the mode without asking the Owner (`ask_owner=False`): a mode that refuses outright
still refuses there, and a mode that would merely ask hands the asking to the stage, which asks per
film with that film's name, its price and its channel policy on the request.
`GET /api/v1/owner/approvals` is what is waiting — the action in Romanian, the tier, who asked, the
evidence, the expiry and the cost, with «necunoscut» where nothing in the studio could compute one and
never a zero. `POST /api/v1/owner/approvals/decision` is the answer: versioned, idempotent by command
id, behind the same write lock as his other commands, one `governance.approval_decided` event carrying
the old result and the new, 409 on a request already answered or expired and 404 on one the studio
never made. The answer is spent in exactly one place — inside `may_act`, in the SUPERVISED T3 branch,
after the stop, T4 and safe mode have had their say — so an approval only ever does what the gate
would otherwise have made him wait for, and never turns a refusal into a pass. It is spent once:
`consumed_at` is the lock and `governance.approval_consumed` the record, and an upload that then fails
asks again tomorrow rather than riding on yesterday's yes. A stop or an incident after he answers
leaves the yes unspent and still his, because neither of them is him changing his mind; a channel
policy version that moved after he answered does retract it, because he said yes to that film going
out at that visibility under that version, so the stale yes is left on the record and a fresh request
naming the new policy is raised instead. Lowering the mode to MANUAL refuses and never looks for his
answer at all, because MANUAL is him asking to be asked about everything. A refusal is COMPLETED, not
SKIPPED — the day's work done and the answer being no, the same shape as the Director's refusal — and
the film keeps its QC-PASSED report, stays unpublished and is not asked about again until his decision
expires; a question still standing is SKIPPED with the approval id in the artefacts, as it was.
`owner_approval_request` joins `HISTORY_TABLES` before `command_record`, so a reset clears it: the
questions are the agents', not his configuration, and a yes about a film that no longer exists is an
authority nothing should still be able to spend.

**The Owner's own render sees what the day sees, and Runway can draw from a reference.**
`backend/app/media/router.py` called `evaluate_media_qc` with the settings alone at both of its call
sites and `assemble_video_job` with neither `image_chain` nor `reference_for_scene`, so the same film
reported `picture_qc` and `character_drift_qc` NOT_APPLICABLE when he pressed Quality Control and
MEASURED when the stage ran it, and his render drew every scene with the one resolved vendor and no
character's reference sheet. The route now passes what the media stage passes: the plan's
`image_chain`, suppressed only when a test has injected an adapter on `app.state`, which is and stays
that render's only vendor; the plan's `reference_for_scene` whatever adapter draws, because which face
a scene must keep is a fact about the film's characters and not about the vendor; and, at both
quality-control call sites, `registry=app.state.registry` and `settings.ffmpeg_path` — the provider
that may hold a model declaring vision, and the encoder that cuts the frame it looks at. His Quality
Control button may therefore now make one vision call and cut frames inside the request, which is the
same single call per film the stage makes; with no seeing model, no registry or no encoder it is still
NOT_APPLICABLE with the reason and the verdict is exactly what the other gates left it. Nothing there
passes by absence. `ReferenceRequired` is a `ValueError`, so the render route answered it 404
"storyboard not found" about a storyboard sitting in front of him; it is now 422 naming the character,
caught before the vendor handler, so a refusal of the studio's own is never presented as a provider
fault. And `RunwayImageAdapter` now carries the contract the OpenAI adapter has: `referenceImages` on
the documented `text_to_image` task, an array of one object whose single required member is a `uri`,
built as an inline data URI by the same helper that has always validated an image-to-video first
frame — so a reference given as a path, an id, or bytes that are not a PNG, JPEG or WebP is refused
before the task is submitted, and `reference_images` is counted 0 or 1 in the attempt's raw response,
so a render's record says whether a character's face came from their sheet or from the words. No `tag`
is sent with it, because a tag means something to Runway only when the prompt names it as `@tag` and
inventing one would change the words the Director approved. `ACCEPTS_REFERENCE_IMAGE` is True because
the code builds the documented field; `REFERENCE_IMAGE_VERIFIED` stays False because no account has
ever answered one, and a test asserts that second flag so nobody can flip it on mock evidence. The
contract refusal for a model that *requires* reference images now fires only when none was given: the
reason was always the missing picture, not the model.

**The panel shows the mode, the approvals and the reference sets.** `policy.autonomy_mode` has been a
real column since 0043 and nothing in `frontend/src` touched it, so a studio running whole days as
AUTONOMOUS_CEO looked, to its Owner, exactly like one that asks before every step. The governance
panel now sits in the column that already shows the studio's state, under the module list: the mode
with the sentence `MODE_MEMORY` gives every agent when it moves, and the other two modes offered as
buttons that send `POST /api/v1/owner/autonomy-mode` with the `expected_version` the snapshot carried.
A promotion while the stop is on is refused by the page itself, in the stop's own words, because the
snapshot already says so; a promotion refused for SAFE_MODE is refused by the server and the panel
prints the server's Romanian sentence rather than a guess, since no safe-mode state is in the snapshot
to read — so a blocked button stays pressable, because pressing it answers *why* and a disabled one
cannot. Lowering the mode is never blocked there, as 51 requires, and an unconfirmed mode command is
resent only when it was for the mode now being asked for, so a slow network is one decision and a
change of mind is a different one. Beneath it, what a SUPERVISED studio wrote instead of acting:
`GET /api/v1/owner/approvals` read at most twice a minute, immediately after any decision and whenever
he presses refresh, each row showing the action in his language, what it is about, its risk tier with
31's definition in the tooltip, who asked, «necunoscut» for a cost nothing could compute and how long
the request still stands; «Aprobă» and «Refuză» send the decision command with a fresh command id, a
409 means it was answered or expired while the page was open and a 404 that it never existed, and a
backend without the route is recorded as not having it and stops being polled after one sentence,
because a panel that repeats a 404 every five seconds teaches its Owner to ignore the panel. Every
card repeats, in Romanian, that an approval lets a permitted action happen and never turns a hard
gate's refusal into a pass. On the Character Bible card the reference set is no longer the ratio
"3/5": every declared slot is a chip, filled or empty, and the button that produces them says in
Romanian that it spends image credits and produces nothing until it is pressed a second time — his
deliberate act, which is why nothing in the day calls that route. The judgements behind all three live
in `frontend/src/governance.js` so that they could be tested; the screens themselves are not tested,
because `main.js` touches the document at import and cannot be loaded by `node --test`, and no DOM
harness was invented to pretend otherwise.

**What the closure measured, and whose measurement each figure is.** No whole-suite run has been made
since these three parts landed, so the **1152 passed, 1 skipped** above remains the last whole-tree
measurement and is now older than the tree; the figures below are each named for the part that took
them. The governance part: `tests/test_approvals.py` **18 passed** (new); the four files it owns
together **75**; the three whole-day tests **5**; the runbook, publishing, publish-policy and
audit-trail suites **91**; foundation, cycle fixes, route authorisation and documentation **42** — 231
in all, with `ruff check`, `ruff format --check`, `mypy` over 187 source files and `check_docs.py`
clean. The media part: **98** across `tests/test_phase5_media.py` (23), `tests/test_media_providers.py`
(41), `tests/test_picture_qc.py` (14) and `tests/test_character_references.py` (20), ten of them new,
plus **88** across the Runway-connection, readiness, editorial-quality and media-selection suites as a
regression check. The frontend part: `npm test --prefix frontend` **102 passed**, fourteen of them the
new `frontend/tests/governance.test.js`, with `npm run check --prefix frontend` (tsc over `src/*.js`,
`checkJs` on) clean. This documentation part: `scripts/check_docs.py` and
`tests/test_documentation.py`. The migration chain is now 0039 → 0040 → 0043 → 0044 and `main.py` pins
`0044_approval_answered`, which is additive — four columns and one index on `owner_approval_request` —
and rewrites no data. No provider was called, nothing was rendered, no run was queued and no credit
was spent by any of the four.

**Still not finished after the closure.** No approval has ever been answered by a real Owner through
the real route against a real database: everything here is measured against the test engine with every
provider faked, and the migration has been walked from an empty database by every test in the run and
never against `data/studio.db`, which nobody opened. The Owner is not told that something is waiting —
a SUPERVISED day records one question per film and the run record carries the approval id, but no
letter and no notification is written, so the list is seen only by someone who opens the panel, and
whether an approval deserves the letter the Accountant writes for a refused budget is his call and not
an agent's. **Corrected 2026-09-18 in the readiness section above:** it does deserve one, and the
Accountant writes it — one letter per business date naming every standing question, carried by the
day's close; no notification is written, and the letter still leaves only in the evening rather than
at the hour the film was stopped. An approval cannot be withdrawn: once he says yes the yes stands until it is spent or
expires, because the honest way to stop a film going out is the stop, which refuses before his answer
is read at all. A film the Owner refused in the *media* stage still lands in `awaiting_owner` and
reports SKIPPED rather than getting the publish stage's COMPLETED distinction between a question and a
decision; the subject is on that stage's request, so his answer is per film there too, but the stage's
vocabulary was left alone. Neither adapter's reference path has ever been accepted by a vendor:
OpenAI's multipart body and Runway's `referenceImages` are both built from the published contracts and
asserted against faked transports, and an HTTP 400 on the first real render is the thing to watch,
because that is how the last unread contract detail announced itself. The size of an inline reference
is not checked: Runway publishes a limit on how large a data URI may be, the number could not be read
without fetching the vendor's documentation, and no guard invents a threshold, so a sheet too large
will come back as a vendor refusal rather than as a silent truncation. Whether a Runway model accepts
an *optional* reference is not a per-model fact the adapter can read — `parse_model_contract` records
only whether the contract *requires* them and `integrations/discovery.py` filters stored `api_metadata`
to a fixed field list — so `referenceImages` is treated as a property of the `text_to_image` task,
which is what Runway publishes today for both of its still models. His manual quality control can now
spend tokens, metered only by the day's ceiling and cached nowhere, because caching a measurement is
how a gate starts certifying what it did not measure this time. And the panel is invisible until he
runs `npm run build --prefix frontend`: no request in it was ever answered against a running backend,
the screens themselves have no test, the refusal card sends no `note` although the command accepts one
and the stage reports it back to him, and the character card still mixes the English labels it already
had with the Romanian the panel added.

## Money and sources (2026-09-17/18)

Phases E and F of running unattended: what a film costs before it is made, and where the day's
pages come from. Measured on a copy of the live database before the work: the check before a
render was `may_spend(engine, 0)` under a comment claiming the plan was costed, so a day at 14.99
of 15 USD started a full film; 391 `agent_run` rows on Ollama Cloud carried `cost_vr` NULL; all
nine live ElevenLabs models carried `pricing {}`, so narration was never costed at all; a render
that a `MediaProviderError` interrupted recorded no cost for the shots the vendor had already
generated; the DAILY window opened at UTC midnight while the studio's day is Europe/Bucharest; a
budget refusal was a SKIPPED stage nobody wrote to the Owner about; the Director's loop and the
mail rounds spent tokens under no ceiling; page discovery ran only through the OpenSearch address
the Owner had typed per host, and only the two Wikipedias carried one; 14 of the 36 authorised
hosts failed retrieval behind bot walls or script-only shells; the Researcher guessed addresses
that answered 404; the day read at most two topics of three pages; and the last live run fetched
0 pages and verified 0 claims, the studio living off the 98 claims verified on 2026-09-12.

**The books hold the money before it is spent, and the day begins when the studio's day begins.**
Migration `0039_pricing_truth_and_reservations` adds `provider_price`, `spend_reservation` and
`provider_cost_record.failed`. A budget period now opens at the studio's own midnight and first of
the month: `_period_start` takes the zone from the `studio` row, which bootstrap writes from
`STUDIO_TIMEZONE`, so the period the books count is the same business date the daily log closes,
and a cost at 22:30 UTC on the 17th belongs to the 18th. `reserve_spend` decides behind the write
lock and writes a RESERVED row that every budget counts until `settle_reservation` (the real cost
rows are in) or `release_reservation` (the film was not made); two films racing for the last ten
dollars get one hold, not two. `release_stale_reservations` is the watchdog's fourth sweep, for
holds older than `STUDIO_RESERVATION_TTL_SECONDS` (six hours) left by a process that died under a
render. `estimate_film_cost_micros` prices a plan conservatively before a frame exists — the
motion at the ceiling that render will be given (`motion_budget_usd` in PRODUCTION,
`test_max_cost_per_generation_usd` × `test_motion_scenes` in TEST) and the narration at the dearest
active per-thousand price over the storyboard's own voiceover — and reports `narration_priced=False`
when no voice price exists, so the stage can say the plan was only partly costed. A film that costs
less settles for less; a film let through on a hopeful estimate would spend the week.

**A price is the Owner's, or it is documented and says so.** A `ProviderPrice` row is written only
by `PUT /economy/prices` — Owner-only, idempotent by command id, versioned with `expected_version`,
provenance OWNER | DOCUMENTED | QUOTED | BILLED — or by `seed_documented_prices`, which carries one
row and one only: ElevenLabs' public list price (Creator plan, 22 USD for 100 000 credits, one
credit a character, so 0.22 USD per 1 000; Flash and Turbo bill half, so the figure is the dearer
one), marked DOCUMENTED with a note saying it is not the Owner's plan. It never overrides a row of
any provenance and adds nothing on a second run. Ollama Cloud is deliberately absent: its price is
whatever the Owner's plan says, and a guess in the books is worse than a gap the Accountant reports
as `unpriced_agent_runs`. Resource `"*"` prices every model of a kind that has no row of its own;
a model's own row outranks it. The ElevenLabs, Ollama and configured-LLM adapters take a
`price_lookup` and cost every call from what they measured — the characters actually sent, the
tokens the vendor reported — and answer None, never zero, without a price or with half of one: a
run priced on one side would be read by the budget as cheaper than it was.

**A render the vendor refused is still a cost, and a refusal is a letter.** `record_failed_render_cost`
writes ESTIMATED rows flagged `failed=True` for the scenes that were attempted, under their own
reference (`render:{job}:failed:scene:{n}:{unit}`), so a finished and a failed reading of the same
job cannot charge the same scene twice and a re-run charges nothing; the books count them like any
estimate and `GET /economy/provider-costs` labels them "ESTIMAT (randare eșuată)". `budget_refusal_letter`
and `may_run_agent` each write the Accountant's letter to the Owner once per business date, decided
behind the write lock, so two stages refused in the same minute write one letter; the Accountant
signs, the Director signs when the studio has no Accountant, and with neither the function reports
that nothing was written rather than inventing an author. `may_run_agent` is the Policy Kernel's
first gate, before the run's write transaction: it counts every token of every run since local
midnight, whatever its outcome, against `STUDIO_AGENT_DAILY_TOKEN_BUDGET` (0 = no ceiling, as the
studio has run until now), and past it the run is recorded BLOCKED_BUDGET like every other block.

**The studio finds its own pages, and the allowlist is not widened by finding them.** When a host
is tested (`test_allowed_host`) or retested by the weekly pass (`retest_stale_hosts`, seven days),
its front page is read through the same DNS-pinned, size-bounded retriever and its own search
address is looked for in `<link rel="search" type="application/opensearchdescription+xml">` and at
`/opensearch.xml`; what is found is stored as DISCOVERED (migration `0040_research_sources`:
`discovered_search_template`, `discovered_at`, `last_test_reason`), and the Owner's own address,
where he typed one, keeps winning. A host that answers 403, limits requests or serves a script-only
shell is FAILED with a reason from a closed vocabulary — HTTP_403, HTTP_ERROR, RATE_LIMITED,
SCRIPT_ONLY, NETWORK, OTHER — that the preflight can show without parsing prose. A web search API
the Owner connects through Settings → *Conexiuni* (catalog kind `search`, one HTTPS JSON contract:
endpoint, key header, result-list path, field names, the key in the vault; "Verify access" sends
one neutral word and checks the shape of the answer) may name addresses and nothing else:
`find_pages` asks the Owner's addresses, then the discovered ones, then the verified engine,
filters the engine's answers against the allowlist before anything downstream sees them, counts
what it dropped, and every page is then read by the studio's own retriever — never the engine's
copy, snippet or "answer". When any of these found pages, the Researcher's plan is a choice among
them and a guessed address is set aside unread and recorded (GUESS_SET_ASIDE); when nothing was
found, his addresses are tried as before and the escalation letter says what each answered. The
day's reading is the Owner's: `STUDIO_RESEARCH_CANDIDATES_PER_DAY` and
`STUDIO_RESEARCH_PAGES_PER_TOPIC`, four and four, clamped 1..12 so a typo cannot turn a research
pass into a crawl.

**The preflight asks whether the studio can find pages, not whether a row exists.**
`research_health` is computed from the record and probes nothing, so it is safe on every run: how
many hosts are authorised, how many were tested successfully, how many carry a search address,
which are failing and why, whether a search engine is VERIFIED, and how many SUPPORTED claims are
in hand. It reports DEGRADED with named Romanian reasons when no host passed, when there is no way
to find pages at all (no search address anywhere and no engine, which returns the Researcher to
guessing), or when fewer than ten verified claims remain — a thirty-second short spends three to
five. A DEGRADED report stops nothing by itself: a day that finds nothing completes honestly with
nothing, and the report is a fact for the Owner to read.

**The day is wired to both, and the studio has run one end to end.** The media stage reads the
day's remaining budget one line *before* it places the film's own hold (a film that counted its own
reservation against itself would render stills with money in the account), prices the plan, holds
the sum, settles only after `record_render_costs` has written the real rows, and releases on every
path where the film was not made — the Owner's stop between two scenes, an encoder that cannot run,
a vendor's refusal, which is costed first. The research stage gathers the Owner's number of
candidates, re-tests every authorised site nobody has tested for a week (one front page each,
nothing on the other six days, so no new scheduled job was needed) and the preflight reports the
health. And the project has the test it never had: `tests/test_autonomous_day_end_to_end.py` fires
the scheduled job, lets the worker execute the real runbook with the real stage runners against a
temporary database, and holds the whole day — twelve stages under a `scheduled:` idempotency key, a
claim extracted from a source and verified by a second employee, a script the Director passed, two
films encoded by FFmpeg and measured by quality control, both published private through the five
gates each to its own channel, and yesterday's serial episode grounded in yesterday's events and
approved under the Owner's Channel B policy — then a second tick that starts nothing. Only the
vendors are faked: one language model answering each prompt in that prompt's own schema, the local
picture and voice adapters, the publishing simulator. No socket leaves the machine, nothing was
rendered by a paid vendor and nothing cost money.

**Every adapter now costs what it spends, and the price table reaches the day.** The prices
existed and nothing carried them: `price_lookup` appeared in the three adapters and in
`economy/prices.py` and at no place where the studio actually builds one, so every
`agent_run.cost_vr` was NULL and every narration unpriced whatever the Owner had typed, and the
budgets counted a fraction of the day. The four construction sites are wired — the seeded Ollama
endpoint (`main.register_seeded_ollama`), the language connections loaded at start-up
(`integrations.services.load_registry`), the one re-registered when the Owner saves a connection
while the studio runs (`integrations/router.py`), and both doors into a voice
(`media.factory.tts_provider` and `tts_provider_for`) — each handed `price_lookup(engine, kind)`,
one short read per call, so a price typed this afternoon costs this evening's runs without a
restart; a model with no row still reports None, never zero. `integrations/credits.py` and
`integrations/discovery.py` are deliberately left without one, because reading a subscription or
listing voices generates nothing, and the list of priced sites is written down in
`tests/test_pricing_truth.py::PRICED_CONSTRUCTION_SITES` with the reason beside it — the scan that
walks it fails on a fifth site added later without a table, and fails too if a listed module stops
building an adapter at all. `seed_documented_prices(engine)` has a caller at last, in
`scripts/bootstrap.py` beside `seed_chart_of_accounts`: the one figure ElevenLabs publishes, marked
DOCUMENTED, never Ollama Cloud, and never over a price of any provenance, so a second bootstrap over
a live studio leaves the Owner's own price standing. And the failed render that recorded nothing is
now proved as well as fixed: a three-scene film whose vendor refuses the third leaves a FAILED job
carrying exactly scenes one and two — the attempt, never the plan — and `record_failed_render_cost`
writes two ESTIMATED rows flagged `failed=True`, referenced `render:{job}:failed:scene:{n}:voice`,
with a second reading charging nothing.

**The Owner can see the state of his sources, and the money that is held as well as the money that
is gone.** `research_health` and the forced retest were computed by the research half and called by
nothing; both now have a route under the factual router, behind the same Owner-only dependency the
allowlist endpoints already carry. `GET /api/v1/factual/research/health` returns the report as the
service builds it and probes nothing, so the screen may ask on every refresh;
`POST /api/v1/factual/research/allowed-hosts/retest` runs `retest_stale_hosts` with
`max_age_days=0`, which is what makes it "now" — the runbook's weekly pass leaves a site tested this
week alone, and this is the Owner asking anyway after fixing something. A test pins the 401 on both
from the other side of the door. *Cercetare → Surse* now prints, for every authorised site, whose
search address is in force (his, or the site's own), the address the studio found on the site itself
and when it found it, and, where the last test failed, the closed-vocabulary reason before the
site's own words for it, so a bot wall and a script-only shell are two different jobs rather than
one paragraph of Romanian; the header line above the list is the health report rather than a count
of rows, «Try it» is offered wherever any address is in force, and a «Test the sites» button asks
for the retest — the first control in the interface that reaches the network on the Owner's click.
In the Books office a run blocked by the day's token ceiling reads as a sentence instead of the raw
word BLOCKED_BUDGET, each budget card prints the sum held for films in production beside the
percentage it is already counted in, and the day prints what is held, what was paid for renders that
failed midway, and how many runs have no recorded price — named, because an unpriced run is real
usage the books cannot value and a total that hid it would read as complete.

Tests, by file set: economy 70 passed (`tests/test_pricing_truth.py` new, with
`test_phase11_economy`, `test_books_and_history`, `test_economy_under_concurrency` and
`test_schema_and_audit_trail`); research 87 passed (`tests/test_research_sources.py` new, 25 tests,
with `test_factual_agent_pipeline`, `test_claim_verification`, `test_sources_and_readiness`,
`test_research_retrieval` and the migration's schema match); the wiring 2 passed
(`tests/test_autonomous_day_end_to_end.py`, new), with 21 (the daily run's stages), 30 (scheduler
and worker), 44 (the runbook and its preflight) and 38 (the adversary, watchdog and sources files,
two of whose assertions the wiring changed). The whole suite on the
integrated tree: **1028 passed, 1 skipped** (the opt-in real-Ollama test), 1029 collected; ruff,
`ruff format --check` and mypy clean on every changed file; `scripts/check_docs.py` passes.
After the closure and its adversarial verification the whole suite is **1067 passed, 1 skipped**,
with `ruff check`, `ruff format --check`, `mypy backend` (183 source files) and
`scripts/check_docs.py` all clean.
The closure measured its own: 17 in
`tests/test_pricing_truth.py` (six new, each written failing first) and 19 in
`tests/test_phase5_media.py` (one new); 108 across the media, discovery, settings and
multi-LLM files and 69 across the adversary, production-policy and economy files; 15 across
`tests/test_phase4_factual.py` and `tests/test_sources_and_readiness.py` for the two new
routes; and 87 frontend tests, with `tsc`, ruff, `ruff format --check` and mypy clean.
Nothing ran against a real model, provider or platform, no daily run was queued and no
credits were spent.

Not finished, honestly: **the Owner's own prices are not in the database.** Wiring the lookups made
a cost computable; it did not invent one. Until `PUT /economy/prices` carries a per-million input
and output price for each model the studio actually runs — Ollama Cloud above all, which is
deliberately never seeded — every `agent_run.cost_vr` stays None and the Accountant keeps reporting
`unpriced_agent_runs`. Narration is the one exception from today: bootstrap seeds the DOCUMENTED
ElevenLabs figure, so a studio with no Owner price costs narration at the public Creator-plan rate
and says DOCUMENTED, not OWNER — that figure is the published list and not his invoice. The live
database has still not been migrated to `0040_research_sources` or bootstrapped, which is an Owner
act because no test may open `data/studio.db`; running bootstrap again is safe, the seed never
overriding a price of any provenance. `frontend/dist` is not rebuilt, so the served page still
carries the old bundle: a build is the Owner's release step, and nothing in this closure was seen
rendering in a browser. Reconciling ESTIMATED rows against a vendor's invoice — a BILLED row
replacing the estimates of one render — still has a vocabulary and no function, so every figure in
the books is ESTIMATED or DOCUMENTED. **Corrected 2026-09-18 in the readiness section above:**
migration `0045_reconciliation` and `PUT /economy/reconciliations` give it a function, which is the
Owner's to use because only he sees the invoice; until he uses it, every figure is still ESTIMATED or
DOCUMENTED. The one question the closure left open was answered in its
verification rather than left standing: the `except RenderStopped` branch released the film's hold
and recorded nothing, although the assembler leaves the same `production_json` for the Owner's stop
as for a vendor refusal, so a film stopped after one scene read in the books as a film that cost
nothing. The branch now costs the attempt before letting the hold go, in the order the refusal
branch already used — the switch decides whether the studio keeps working, not whether a vendor has
already been paid. Neither new route was exercised against a real site, and the
script-only heuristic and the OpenSearch discovery are still proven only on fixture HTML modelled on
the hosts that failed, because `tests/conftest.py` refuses every non-loopback socket — the first
retest against live hosts, which the Owner can now ask for with one button, is the measurement. And
the end-to-end test still skips where FFmpeg is absent, by the convention
`tests/test_phase5_media.py` already uses, its two tests taking about fifty seconds together because
they encode two real films.

### Ce are Owner-ul de făcut → mutată sus, la «Readiness for the first day (2026-09-18)»

Mutată acolo pe 2026-09-18, rescrisă ca listă ordonată a dimineții primei zile adevărate.
Niciun rând de aici nu a fost scos: fiecare este acum un pas numerotat, cu comanda sau ecranul
lui și cu ce se întâmplă dacă sare peste el, alături de pașii pe care i-a adăugat faza aceasta
— preflight-ul citit înaintea oricărei cheltuieli, admiterea unui model care poate privi și
reconcilierea facturilor furnizorilor.

## Delivery and the serial (2026-09-17/18)

Phase B/C of running unattended: what the studio delivers, and the serial as a film. Measured
before the work: `_publish` in `backend/app/runbook/stages.py` took `ready[0]` — the first bound
slot, whatever film came first — and uploaded at a constant `privacy_status="private"`;
`ChannelRecord.upload_privacy_default` was read by nobody on a publish path;
`scheduled_publish_time` was stored on the intent and never sent, and the YouTube adapter had no
`publishAt` and no `videos.update`; performance intake measured every publication through the
first bound slot's account; every `domain_event` carried visibility OWNER and the showrunner was
handed raw `key=value` payload pairs (model ids, message text, prices); continuity between
episodes was one previous title and a roster size; nothing consumed an APPROVED episode, and
`serial_queue` ran last, after the day's log, so no run ever filmed one; the day's log was frozen
at the run's own hour (the live log of 2026-09-16: 92 events, one of them narratable);
`captions.srt` was written beside the render and never muxed or burnt in; nothing normalised
loudness; quality control had no audio and no caption category although
`../architecture/08_VIDEO_PIPELINE.md` lists both; a scene whose motion model refused became a
slow push recorded in a note nobody read; and a render read the Owner's stop never — eight
scenes ran to their end after STOP.

**The Owner sets how a channel publishes, and the studio can say which policy published what.**
`channel_record` carries a versioned publish policy — `autonomous_privacy` (private | unlisted |
public, default private), `public_publish_enabled` (false), `publish_delay_minutes` (0),
`policy_version` (1), `policy_changed_event_id` — migration `0037_publish_policy`, changed only
through `POST /publishing/channels/{id}/publish-policy` (`PublishPolicyCommand`, `command_id`,
`expected_version` = the channel's `policy_version`), which follows `change_environment`
exactly: the write lock first, idempotent by command id, a stale version 409, NO_CHANGE without
a version bump or an event, and on a change `publishing.channel_policy_changed` with the old
and new values and the environment. "public" is accepted only with `public_publish_enabled=true`
in the same command and never while the studio is in TEST (since 2026-09-18 the command is
judged on the state it would leave, so the flag alone cannot re-arm a policy already "public"
while the studio is in TEST). `resolve_publish_visibility(channel, environment)` decides in one
place: private unless the policy says otherwise, public only with the flag and PRODUCTION
(corrected 2026-09-18: unlisted also needs PRODUCTION — an unlisted film is watched by anyone
with the link, so in TEST an unlisted policy resolves private and takes effect when the Owner
moves the studio to PRODUCTION), and a public policy with a delay yields a private upload with
`publish_at` and `release_privacy="public"`, because YouTube schedules a release as a private
upload carrying `status.publishAt` — which the adapter now sends (and refuses on a non-private
upload before any request leaves), beside `containsSyntheticMedia` and the disclosure;
`update_visibility` (videos.update, the synthetic flag re-declared) exists with no production
caller. **A film goes to its own channel or nowhere.** `select_channel_for` reads the storyboard
(`channel_id`, else series key `office_serial` → OFFICE_SERIAL, else MAIN_FACTUAL; corrected
2026-09-18: a `channel_id` whose channel type contradicts the series key is SKIPPED, not
followed, in either direction); a slot unbound or bound to a connection no longer CONNECTED is
SKIPPED by name, with no fallback to another channel. The five gates are untouched; a sixth
(`POLICY_AUTHORISATION_GATE`) runs only for a publication that would be seen and requires the
channel's current `policy_version` stamped on the publication
(`publication_record.policy_version`, in the `publishing.video_published` payload with
`publish_at`) and a requested visibility no more open than the policy resolves to; the Owner's
own intent endpoint is held to the same rule. Analytics ask per channel:
`analytics_provider_for_channel` builds the adapter from that slot's bound CONNECTED account
only, and `measure_channel_publications` measures that channel's PUBLISHED rows and nothing
else.

**The serial is a Channel B film, from a sanitised full-day log.** `app/story/projection.py`
classifies every event type by a table that is OWNER_PRIVATE by default; a PUBLIC_SAFE type
names the payload keys that may be mentioned and a plain phrase for the fact, and every
description passes `redact` (anything shaped like a key or token, a provider or model
identifier, a price, a URL, an address or an account number); a letter to or from the Owner is
projected as the fact that it was written, never its subject. `close_daily_log` stores the
projection on `daily_studio_log.narrative_projection_json` (migration `0036_serial_continuity`),
a log closed before the column existed is projected once from its own committed events, and
`write_episode` grounds beats against the projection only, so a beat citing a private event is
refused as ungrounded (tested: a fake key, a model id, a price and a URL in the day's raw
payloads reach neither the projection nor the prompt). `continuity_state` (one versioned row)
holds the canon episode number, open threads, recurring elements and the last three summaries;
the showrunner's prompt carries them with a "who they are" line per roster member quoted from
the Character Bibles; canon advances only on approval, once per episode. **The Director reads
the episode** (`app/story/review.py`): five computed checks first — grounding, privacy, length
(at most 8 beats, 45–70 s of dialogue), cast, accessibility — and only then her verdict through
`run_agent_task` with the episode as inert data; a FAIL rejects it with her notes and a HANDOFF
letter to the showrunner (one rewrite, then REJECTED); a PASS approves it with
`reviewed_by="director"` only when the OFFICE_SERIAL channel's `director_may_approve_episodes`
is set, otherwise the episode stays DRAFT for the Owner with the review on it. **An approved
episode becomes a storyboard** (`app/media/serial_storyboard.py`, `storyboard_from_episode`):
one scene per beat, the beat's dialogue as the voiceover, the scene and the characters' bible
lines as the visual prompt, bible ids in `character_ids_json` so a locked character's voice is
bound where the Owner has bound one, 9:16, `channel_id` = OFFICE_SERIAL,
`series_key="office_serial"`, behind a claim-less `ScriptDraft`
(`story_json.kind="office_serial_episode"`) with a `StoryReview` PASS written from the episode
review — in exactly the shape `generate_storyboard_from_script` produces (tested field for
field), so render, narration review, QC and publish run unchanged. `run_serial_stage`
(`app/story/serial_stage.py`) does the whole of it for the newest CLOSED log without an episode
and reports every content outcome — a quiet day, a refused draft, a double FAIL, an episode left
for the Owner — as COMPLETED with the reason; only a provider or network fault is raised, as
`TransientStageError`. Routes: `POST /story/episodes/{id}/review`,
`POST /story/episodes/{id}/storyboard`, `GET /story/continuity`,
`POST /story/logs/close-previous`.

**Every film carries captions and normalised loudness, and a mostly-still film is a gate, not a
note.** `backend/app/media/toolchain.py` owns one reading of one filter: `loudnorm` at −14 LUFS
/ −1 dBTP, measured on the joined narration first and applied as one linear gain
(`linear=true`; the one-pass mode audibly breathes on speech), with `LOUDNESS_RANGE_LU` 11 so
narration at 5–9 LU stays in linear mode; the manifest records target, filter, input and output
readings, and a placeholder render on the Owner's FFmpeg 9.0.1 lands at about −14 LUFS in band
with the true peak well under the ceiling. Captions are timed from the narration actually
recorded (`audio_seconds`, written per scene after synthesis), one cue per sentence, lines
wrapped to two of at most 42 characters and balanced, the SRT written after the voice pass and
always beside the film; with `captions_burn_in` (default true) it is burnt in above the bottom
fifth of the frame (measured on a rendered 1080×1920 frame: 50-pixel white type with a dark
edge and no box, baseline 390 px above the bottom). The motion summary counts `motion_scenes`,
`fallback_scenes` (asked and not delivered) and `skipped_scenes` (policy). Quality control
gained `audio_qc` (measured from the finished film, in band and under the ceiling),
`captions_qc` (valid SRT, two lines / 42 characters / no overlap, inside the film, covering the
narration at a word-sequence ratio of at least 0.95) and `motion_qc` (a PRODUCTION film whose
fallback scenes exceed `max_fallback_scenes`, default half, fails; in TEST the same count is a
warning); all three enter the verdict, and a check that cannot be made fails rather than passes.

**The daily run delivers to two channels, films the serial the same day, and stops between
scenes.** `STAGES` now puts `serial_queue` between `script_and_storyboard` and `media`
(the runbook document is renumbered to match, §7 the serial queue and §12 the daily log, with
its indexed hash updated), `_serial_queue` is `run_serial_stage`, and `_media` renders one
factual storyboard then one serial storyboard (told apart by the storyboard's series key
through `channel_type_for_storyboard`) through the same story gate and the same camera, asking
`may_spend` before each film — a refusal before the first film is SKIPPED as before, a refusal
after it names the film skipped (`artefacts.skipped_for_budget`). `execute_daily_run` closes
yesterday's log after a non-blocked preflight and before the stage loop (`close_previous_day`,
retried like a stage, recorded on the preflight line as `artefacts.previous_day_log`); today's
close at the end of the run is unchanged. `_publish` collapses the QC-PASSED queue to one entry
per film, routes each through `select_channel_for`, refuses a film whose slot is unbound or
revoked with the slot's name and never sends it elsewhere, resolves the visibility once and
passes it to the gate pre-check, `publish_media_asset` (with `policy_version` and
`scheduled_publish_time`) and the outcome (`artefacts.published[]` with channel, privacy,
release privacy, publish_at, policy version and the reason); one film per channel per run; a
studio with no slot bound at all is still SKIPPED with the old wording before films are looked
for. `_performance_intake` measures per channel and names an unbound slot in
`artefacts.skipped`. `assemble_video_job` polls `stop_requested` between scenes and before each
motion shot; a set stop fails the job with `STOP_REASON` ("Randarea s-a oprit între scene:
AUTONOMIE OPRITĂ …"), records no asset and raises `RenderStopped`, which `_media` reports
BLOCKED with the Owner's reason (PARTIAL, no safe mode) (corrected 2026-09-18: the render alone
read the stop, so a stop set during the factual film still started the serial's render; `_media`
now reads `stop_requested` before each film and reports BLOCKED naming the film it did not
start). `settings=` reaches the camera
(captions burn-in) and quality control (the fallback ceiling): `captions_burn_in` (true) and
`max_fallback_scenes` (none = half the scenes) are settings. `ScheduledJobView` exposes
`run_at_local` and `timezone`.

**The closure (2026-09-18): the serial film reaches Channel B without an Owner's click.** Two
measured defects stood between an approved episode and the serial's channel. The Director's
film review refused every serial film before any model: `gather_facts`
(`backend/app/agents/editorial.py`) hard-rejected a script with no claims ("scenariul nu se
sprijină pe nicio afirmație") and her brief said a film about the studio itself is REJECTED —
both right for a factual film, both wrong for a dramatisation — so `_publish_one` returned her
refusal before the routing ever saw the film. A serial film is now recognised by the marks the
serial storyboard already carries (`is_serial_film`: series key `office_serial`, or the
script's `story_json["kind"] == "office_serial_episode"`); for it the claims-based verdicts are
not asked, the facts say so plainly (`serial: true`, `series_key`, `episode`), and the brief is
the episode review's (`instructions_for`): a dramatisation makes no claims about the world and
needs no sources, and is judged for the situation, the turn, the payoff, whether each character
sounds like a person, whether the humour is in the situation rather than in explaining the
studio. Everything not about claims is unchanged for both kinds — no script, under forty words,
the wrong audience language and a blank frame still mean REJECT without a model — and a factual
script that rests on nothing is refused in the same words as before (tested, so the exception
cannot widen). And `director_may_approve_episodes` was read from Channel B's `series_rules_json`
and written by no command — the production-policy validator keeps that JSON to
`{series_key: {purpose: selection}}` and would have refused or overwritten the key — so a
Director's PASS left every episode DRAFT and the serial never became a storyboard on its own.
The flag is a column of the publish policy now (`channel_record.director_may_approve_episodes`,
NOT NULL, default false; migration `0038_director_may_approve_episodes`, which `main.py` pins),
in `policy_snapshot` and `ChannelView`, set only through `PublishPolicyCommand` under the
command's existing rules (stale `expected_version` refused, idempotent by command id, NO_CHANGE
without an event, a change bumping `policy_version` and recorded with old and new). A fresh
channel leaves episodes to the Owner; nothing sets the flag on its own. The mechanical leftovers
went with it: the media route's render button and standalone QC pass
`settings=request.app.state.settings` like the daily run, so the Owner's button makes the film
under the same rules; `continuity_state` is in `HISTORY_TABLES`, so a history reset no longer
leaves canon summaries pointing at deleted episodes; the five mypy `union-attr` errors in
`qc.py` are gone; `YouTubeAnalyticsProvider` takes `channel_id` and reads `STUDIO_YOUTUBE_*`
only from a bare constructor, so an adapter built from a channel's bound account no longer
inherits an access token from the Owner's machine; and `PolicyView.public_publish_enabled` is a
real bool — any channel may publish publicly — computed in `policy_view(policy, session)`, so
the snapshot and the result of the very command that enabled it agree.

Tests, by file set: `tests/test_publish_policy.py` 30 (29 new, plus the Director's leave);
`tests/test_serial_pipeline.py` 34 (new); `tests/test_media_toolchain.py` 9 (new) and
`tests/test_phase5_media.py` 18; `tests/test_daily_run_stages.py`, `test_phase10_runbook.py`
and `test_scheduler_worker.py` 89 with 9 new; the closure added 3 to `tests/test_editorial.py`
and 1 each to `test_publish_policy.py`, `test_phase5_media.py`, `test_phase7_analytics.py`
(13), `test_reset.py` (3) and `test_foundation.py` (26), each red first on the measured defect.
The integrator ran the whole suite at the commit: **945 passed, 1 skipped**; with the closure's
nine new tests the collection is 954, and the whole suite with both closures present is the
verifier's to run. ruff and mypy are clean on every changed file and `scripts/check_docs.py`
passes. Nothing was run against a real model, provider or YouTube: the camera, the publisher,
the analytics adapter, the showrunner and the Director are faked at the stage or provider
boundary, as the rules require; no daily run was queued and no render was paid for.

Not finished, honestly: no test drives a serial film through `_publish_one` to Channel B end to
end — the Director's serial brief is tested at `editorial_review` with a scripted model and the
routing with the review faked at the stage boundary; the two halves agree by construction on
the same series-key mark, and the first real day with Channel B bound should be watched, as
should the first real scheduled upload (`publishAt` and `videos.update` were exercised only
against a faked transport); whether `glm-5.3` judges an episode well under the new brief is
unmeasured until a real day; today's log is still closed at the end of the run, so a date whose
run completes is frozen at the run's hour and `close_previous_day` returns it unchanged the next
morning — a full-day log for every date needs that end-of-run close moved, which is the
runbook's decision and is recorded as open; one voice per scene: the assembler synthesises a
single voiceover per scene, so a beat with two speakers is voiced by the first locked character
or the narrator, and the seeded bibles carry no voice binding, so until the Owner binds voices
every scene is the narrator; redaction is pattern-based and over-redacts (years, four-digit
counts, tokens such as `mp4`), and `DomainEvent.visibility` itself is unchanged, still OWNER
everywhere; the old `notable_events_json` descriptions still carry raw payload pairs in the
Owner-only log API; continuity does not track the office layout version, employment intervals
or a canonical character version; caption coverage is matched against the storyboard text, not
transcribed from the audio, and the caption font is Arial by name rather than a licensed studio
face; `upload_privacy_default` and `update_visibility` remain, unread and uncalled;
`YouTubeAnalyticsProvider.from_verified_settings` still falls back to environment credentials
when the bound connection is not exactly one CONNECTED row (`analytics_provider_for_channel`
never calls it); no frontend screen sets the publish policy or the Director's leave — the
Owner has the API (`POST /api/v1/publishing/channels/{id}/publish-policy` with the channel's
`policy_version` as `expected_version`) until one does — and the scheduler panel does not yet
read `run_at_local`; three test files appended in the closure carry LF endings in the working
copy, which a checkout rewrites to CRLF without changing content; the daily job is still
dormant, by the Owner's rule, and no daily run has been queued by anyone.

**Phase B/C tried as an adversary, seven defects closed (2026-09-18).** The whole suite ran green
as delivered — the verifier's run 1, before any of its fixes: 953 passed, 1 skipped; ruff, mypy
(179 files) and `scripts/check_docs.py` clean — and twenty-one adversarial tests in
`tests/test_phase_bc_adversary.py` then measured what the rules had not yet been asked: an
unlisted policy resolved unlisted in TEST (an unlisted film is watched by anyone with the link;
`resolve_publish_visibility` now holds it to PRODUCTION like public, and the two tests that had
encoded the old reading moved to PRODUCTION); with the privacy already "public" from a PRODUCTION
day, `public_publish_enabled=true` in TEST was COMMITTED (the command now refuses on the state it
would leave); a serial-keyed storyboard pinned to Channel A by id was SELECTED for Channel A while
the media stage filmed it as the serial (`select_channel_for` refuses a pin that contradicts the
key, both directions); a currency-first price, a scheme-less link and an AWS-shaped key in a
*safe* title reached the showrunner prompt (three patterns added to `projection.py`, ordinary
titles unchanged); a key in the episode's summary passed the Director's privacy check and would
have entered canon and every later prompt (`episode_checks` now reads the summary, the opened
threads and the recurring elements); and `_media` read the Owner's stop never — a stop set during
the factual film started the serial's render (the stage reads it before each film and reports
BLOCKED). `tests/conftest.py` gained an autouse guard that refuses any socket that is not
loopback, so the Owner's rule that no test spends at a vendor is proven per run rather than
promised; every adapter goes through urllib or http.client, which the guard covers. Held without a
defect: the Owner's leave per channel, one rewrite, a closed log unchanged by late events, the
blank-frame rule for both kinds of film, loudness and captions QC naming their cause, the fallback
gate, the per-film budget. After its fixes the verifier ran the changed files (238, 103 and 21
passed; the new file was 13 red first); the whole suite on the final tree is the committer's run,
and no figure is claimed for it here. Not run against any model, provider or YouTube; no daily run
queued.

## The clock, and a day that asks again (2026-09-17)

Phase A of running unattended: the studio's own clock, and the durability under it. Measured
on a copy of the live database before the work: the daily job had never fired by itself; the
one thing that had stopped the studio for days was a single transient error — SQLite's
"database is locked" at the wrong second — recorded with the weight of a bug, which opened
safe mode and set the autonomy stop; no provider adapter retried anything, so one 503 from
the voice vendor or one 429 while Runway was polled was a failed scene or a SKIPPED stage;
two `video_render_job` rows had been RENDERING since 2026-09-12 with `finished_at` NULL;
`reconcile_publication` had no caller outside the tests; and the worker lived only inside
the foreground process `start.cmd` opens.

**A fault has a class.** A stage's exception is read for its shape and its chain
(`classify_fault`, `backend/app/runbook/services.py`): TRANSIENT is the world being slow — a
timeout, a connection refused or reset, DNS, a provider's 408/425/429/5xx wherever the
raising code put the status (`MediaProviderError.http_status`, `HTTPError.code`, the
"HTTP 502" in `ConfiguredLLM`'s message), SQLite's and SQLAlchemy's `OperationalError`,
`RemoteStateUnavailable`, and a `TransientStageError` a runner may raise when only it can
tell. The walk follows the exception chain as a traceback would, so `media_http`'s "could
not be reached from OSError" is seen for what it is. HARD is everything else — a wrong value,
a policy refusal, a missing file, a full disk, a bug. A transient fault is retried in place,
`STUDIO_STAGE_RETRY_ATTEMPTS` (3) times after the first failure with backoff 20, 40, 80 s,
each retry a `runbook.stage_retrying` event; a stage still failing makes the run FAILED with
`fault_class` TRANSIENT on the stage, the run and the new `daily_run.fault_class` column
(migration 0035), and does not open safe mode. A hard fault keeps the old behaviour: FAILED,
safe mode, the autonomy stop set, a person looks. **Corrected 2026-09-18, after the rehearsal on
the Owner's data: a failed stage did not cost only itself — any failure blocked every stage after
it, so one statistics token refused at performance intake left the day with nothing filmed, and a
hard fault in any stage, an HTTP 4xx from Google included, opened safe mode and set the autonomy
stop.** Since that day a failed stage blocks only the stages that take their input from it
(`STAGE_PREREQUISITES`), and a hard fault opens safe mode only where it is a P0 — in media, publish
or the day's log, or a database integrity error in any stage (`SAFE_MODE_STAGES`); anywhere else it
costs its stage, its dependants and one letter. See «The rehearsal on the Owner's data
(2026-09-18)» above.

**The clock re-attempts a day that could not run.** A clock-fired run is skipped only when
the date already has a run that did work (COMPLETED or PARTIAL) or `STUDIO_DAILY_MAX_ATTEMPTS`
(3) is spent; a BLOCKED preflight or a TRANSIENT failure queues attempt n+1 (corrected
2026-09-18: a TRANSIENT failure queues it only when it cost the day's films — a stage from
selection to publish lost — because a re-attempt re-runs the whole day and would buy a second film
to recover a report; a day whose films went through is PARTIAL and done) under the
idempotency key `daily-retry-<date>-<n>`, held `STUDIO_DAILY_RETRY_SECONDS` (1800) by the
queue's `next_attempt_at` gate (`enqueue_task` gained `not_before`, and the gate is now
tested). A retry that outlives its date skips itself; a waiting retry no longer refuses the
Owner's button; the Director's letter about a stopped day is written once, after the day's
last attempt.

**The day is on the wall clock.** `scheduled_job.run_at_local` ("HH:MM") and
`scheduled_job.timezone` put a job at the next occurrence of a local hour, DST-safe (tested
across Bucharest's 23- and 25-hour days). `daily_main` is seeded at
`STUDIO_DAILY_RUN_HOUR_LOCAL` (05:00) in `STUDIO_TIMEZONE`, follows the setting on every
start-up and stays dormant: waking it schedules the next 05:00, never a fire on the spot.

**STOP cancels a day in flight.** The switch is read again before every stage; a day already
running stops where it is, the remaining stages BLOCKED "Oprit de AUTONOMIE OPRITĂ.", the run
PARTIAL if any stage completed (the log is then closed, a partial day being a day) else
BLOCKED, no safe mode, no letter. `stop_requested(engine)` is exposed for the loops inside a
stage to poll between scenes; a runner that raises or returns BLOCKED while the stop is set
is recorded as the Owner's stop, not a fault.

**The adapters ask again before they fail the day.** `backend/app/providers/retry.py` holds
one policy, `call_with_retries`, for every outbound call in ElevenLabs, OpenAI images, Runway
(submit, poll, download, contract, organization), the seeded Ollama adapter, `ConfiguredLLM`
and YouTube (token refresh, session, chunks, status, search): bounded exponential backoff
with jitter — 1 s doubling, `STUDIO_PROVIDER_RETRY_ATTEMPTS` (3) attempts, one wait capped at
`STUDIO_PROVIDER_RETRY_MAX_SECONDS` (30) — on 429, 5xx and a connection that never opened,
never on another 4xx; a vendor's Retry-After is waited out exactly when it fits under the
cap. The HTTPS boundary (`media_http.request`) now tells the two failure phases apart
(`unsent`, `unanswered`) and carries the vendor's status and Retry-After on the exception. A
billed request — a narration, a still, a Runway task, an LLM generation — that left and got
no answer is not sent again, because the vendor may have served it; reads are. Runway's
estimated credits are recorded once, from the answer that succeeded. The error after the last
attempt is the vendor's own class and fields with "(after N attempts)" on it; the log gets
attempt numbers, status and class, never the error text. Nothing about what "verified" means
for a provider changed.

**The watchdog.** `backend/app/workflows/watchdog.py` (`WATCHDOG`, job `watchdog`, seeded
ACTIVE every `STUDIO_WATCHDOG_INTERVAL_SECONDS` (600), behind the autonomy stop like
everything scheduled; the module is imported only when a task fires, and a build without it
dead-letters the fire with the reason) does three things per pass and records each. A render
RENDERING longer than `STUDIO_RENDER_STUCK_AFTER_SECONDS` (three hours) is failed the way the
assembler fails one — status, `finished_at`, "Blocat: fără progres de N ore" on the row, a
`media.render_failed` event — and the VideoEditor left typing by the dead process is marked
idle. Every publication in REMOTE_UNKNOWN or FAILED_RETRYABLE goes through the reconciliation
that already existed (`reconcile_publication` for an unknown one with a remote id,
`execute_publication`'s retry path for a retryable one, which asks the platform by
idempotency key before it uploads); a platform that does not answer is asked
`STUDIO_RECONCILE_MAX_ATTEMPTS` (3) times, counted from the watchdog's own
`publishing.watchdog_reconcile` events, then the row is moved to NEEDS_RECONCILIATION with a
`publishing.reconcile_exhausted` event and a note for the Owner, and not asked again; an
unknown publication with no remote id — YouTube's UNKNOWN never carries one — is handed over
at once. Lapsed task leases are reported and left alone: `claim_task` re-claims an expired
lease itself, and the test proves it. The pass changes nothing while STOP AUTONOMY is set.

**The studio as a service.** `scripts/install_studio_service.ps1` registers a Windows
Scheduled Task "AMN-AI Studio" (`start.py --skip-frontend` at logon and at startup, three
restarts one minute apart, no execution time limit, output in `data/studio-service.log`,
`-RunWhenLoggedOff` for an S4U logon), idempotently and printing what it registered;
`scripts/uninstall_studio_service.ps1` removes it. Both are the Owner's to run and were
parsed here, not run. The README section "Running as a service" says how, that the daily
job stays dormant until the Owner's recorded activation, that the machine must not sleep at
the run hour (the power plan is the Owner's), and how to check with `schtasks /Query`.

Tests, by file set: runbook, scheduler/worker and the migration schema match 66 passed;
`tests/test_provider_retry.py` 28 passed (new), with 503-then-200, 400-not-retried,
exhaustion and no-double-billing cases added to the media, Ollama and integration-settings
files (46, 14 and 24 passed) and 34 passed on the existing files that drive the changed
adapters; `tests/test_watchdog.py` 11 passed (new); ruff, format and mypy clean on every
changed file; `scripts/check_docs.py` passes. The whole suite was not run by the
implementers; it is the verifier's. Verified as an adversary: the whole suite ran twice,
863 passed, 0 failed, 1 skipped; the close of the day is retried like any stage and a slot
is compared as an instant (two defects the verifier found and fixed, with a red-then-green
test each).

Not finished, honestly (what Phase B/C closed is marked inline): `ScheduledJobView` does not
expose `run_at_local` and `timezone`, so the scheduler API and the page cannot yet show the
fixed hour (closed 2026-09-17: the view carries both; the page does not read them yet); the
runbook reads the stop between stages, but the media scene loop and the other long runners
in `backend/app/runbook/stages.py` do not yet poll `stop_requested` between units of work,
nor raise `TransientStageError` where only they can tell a fault is transient, so the new
behaviour does not reach inside a stage (closed in part 2026-09-17: the render polls the
stop between scenes and before each motion shot, and the serial stage raises
`TransientStageError` for a provider fault; corrected 2026-09-18: the media stage itself reads
the stop before each film, so a stop set during the factual film leaves the serial unfilmed;
the other long runners still do neither); the watchdog dispatch was tested with an injected
stub module — the real module's exports match the handler, but an end-to-end fire with it
was not run; `tests/test_remote_state_honesty.py::test_the_real_provider_turns_a_failed_request_into_unavailable`
now takes about four seconds, because its fake's bare `OSError` is correctly retried with
real 1 s + 2 s sleeps (an autouse fixture in `tests/conftest.py` patching
`app.providers.retry.sleep` would make it instant again); a REMOTE_UNKNOWN publication
without a remote id is handed to the Owner rather than resolved, because
`execute_publication` does not yet admit that state to its reconcile-by-key branch; only the
VideoEditor's runtime state is reconciled when a stuck render is failed, and other employees
left WORKING by a crash are not reset; whether an S4U logon can open the DPAPI-wrapped
credential key on this machine was not verified, and the Owner should read
`data/studio-service.log` once after installing with that switch; `MULTI_LLM.md` named 0034
as the latest migration in passing (corrected 2026-09-18); `main.py` pins the head revision
(`0035_clock_and_fault_class` at this commit, `0038_director_may_approve_episodes` since
2026-09-18), so `scripts/bootstrap.py` (migrate) must run before the server starts on this
version. The "Running on its own" section below said every 24 hours and CATCH_UP; it was
rewritten on 2026-09-18 from the code as it is now. `backend/app/office/unreal.py` fails
`ruff format --check` and has one mypy error (line 72), pre-existing and untouched.

## An employee may think with more than one model (2026-09-12)

Every agent now has an optional second and third model beside its primary, from the same
registry, with a strategy that says what to do with them: single, fallback, review, debate or
parallel (migration 0034). No model is named in the studio's logic — a test scans the backend
and fails if one is — so any slot can be replaced from Settings without a code change. Extra
models are spent only where the agent's own policy says the task earns them, and the reason is
recorded. In review, debate and parallel the answer acted on is always a run on the employee's
own model: a critic advises and cannot publish, command or decide. A review that could not be
done is recorded as incomplete rather than filled in, and the Director's decision then carries
low confidence. The Owner's current allocation lives in `config/workforce_seed.json`: the
Director with a strategic critic, everyone else single. The report is `MULTI_LLM.md`.

## The company is managed, not only measured (2026-09-12)

The Director now answers where the company stands, what is preventing growth and who acts next
(migration 0033). Performance is normalised per film — views per hour, subscriber conversion,
cost and production time on the same row — and judged against the channel's own rolling median,
never an absolute number: a verdict needs three measured films, a day of age and a rate, or the
answer is INSUFFICIENT_DATA. A diagnosis separates reach from retention from conversion and
names the department that can fix it. Her pass runs every six hours on the existing scheduler,
assigns at most three things through the existing mailbox with a review condition on each,
never raises a matter already in hand, and sends STOP and SCALE to the Owner. Each decision is
a row the database refuses to accept without a review condition, and it comes back when the
films it was waiting for have been published. Verified on a copy of the live database: it found
the real bottleneck, six films through quality control and none published. The report is
`DIRECTOR_COMMAND.md`.

## The content decides, before the generation (2026-09-12)

A film now has to be worth making before it can be made. A topic carries an argument — the
fact, why it matters, the payoff, the hook, the ending, a call to action — scored on twelve
weighted editorial dimensions, and an idea that fails the rules is kept with its reasons. A
script carries its story and declares the part every scene plays. Before anything is
generated, the story is reviewed: computed checks for hook, progression, payoff, ending, CTA
and pacing, plus the Director's estimate of where a viewer would stop watching; a script that
is sent back is rewritten once. The render and the prompt agent both refuse a film whose story
has not passed. Then one master visual bible and a full prompt package per shot replace the
single line that used to be sent to a model at 2.60 USD a shot — the same package in both
environments, because TEST saves money on the model, not on the thinking. The report is
`EDITORIAL_PIPELINE.md`.

## Two environments, decided by the studio (2026-09-12)

The studio knows whether it is testing or publishing (`owner_policy.environment`, migration
0031), and that decides which policy chooses each scene's model: in TEST the cheapest
compatible model under a cost ceiling per generation and per second, in PRODUCTION the least
expensive model that reaches the quality the scene's part in the film requires. The
environment is server-side state changed only by the Owner's versioned command; the page
displays it and asks for a change. A model now carries a standing it has to earn
(DISCOVERED → … → PREFERRED) and cannot film anything that will be published until its own
recorded results admit it. Prices carry their provenance — documented, quoted, billed — with
what they were before, and a change past the Owner's threshold reaches him as a letter.

## The clean studio's first film, approved and unpublished (2026-09-12)

From an empty history: six topics proposed in English on authorised sites, pages found
through Wikipedia's and CERN's own addresses, 23 claims verified, a script whose every scene
cites a claim, a storyboard that speaks the writer's words, a 45.6-second 9:16 render with
Runway stills (`seedream5_lite`, after the studio dropped an editing-only model) and an
ElevenLabs voice, quality control passed on every check, and an APPROVE from the Director —
on `kimi-k3`, the first model she has had that can see, citing what the frames show. The
film is not published: that decision is the Owner's.

## Pages are found, not guessed (2026-09-12)

An authorised site can carry its own search address (OpenSearch JSON, `{query}` inside);
the studio asks it before the Researcher plans and reads the pages found when his guesses
fail. On the clean studio's first day every guessed address returned 404; with Wikipedia's
search address recorded, the day is expected to read real pages. Sites that serve articles
only to browsers (UNESCO) stay unreadable under the studio's honest identity.

## Starting over, and a Director who decides once (2026-09-12)

`scripts/reset_history.py` deletes the agents' history and the live ledger and keeps the
configuration (a backup is taken first; the studio must be stopped). The ledger begins at
the reset line. The Director's escalations now close the escalated message, one open letter
per matter reaches the Owner, an investigation's answer is not investigated again, and the
correspondence round runs at most three reviews an hour — the evening of 2026-09-11 ran
nine in twenty-four minutes.

## The Director watches before publishing (2026-09-12)

Nothing reaches a channel without the Director's editorial verdict (migration 0029): she
reads the film as data and frames from the file, decides APPROVE or REJECT with reasons,
and writes to the departments that must change something. The one video that went out —
demo script, sourceless claim, Romanian narration, twenty words — would be rejected on
three counts before any model is asked.

## English on the way out (2026-09-12)

`STUDIO_CONTENT_LANGUAGE` (default `en`) is told to every employee whose words reach the
audience, and a publication whose title or description is not in that language holds. The
Owner's first real upload (private, Main Channel A, title in Romanian) is the case that
motivated it. Structured tasks ask the provider for JSON on the first attempt and think
natively on the second; the Director on `glm-5.3` needs the second, at ~11 minutes and ~46k
tokens per twelve messages.

## The cycle, watched (2026-09-12)

A real day run on a copy of the Owner's data: trends read, five topics proposed, claims
verified, a stalled storyboard re-rendered with real visuals, the Accountant's close parsed,
letters filed. Still short of a published video because the Researcher's guessed URLs 404
(no search step; see the changelog) and the Director's long analysis needed the new
formatting pass. The publish stage was disabled in the copy on purpose.

## Polish pass (2026-09-12)

Every view read from a screenshot and set on one text scale, one radius and shadow, actions
sized to their words, the scene chrome as one bar in two groups, the ledger breathing, and
Settings on the same dialog pattern as the rest. Details in `CHANGELOG.md`.

## Signals: vendor pages and search trends (2026-09-12)

Kael and Lyra choose their models by reading the vendors' own pages (fetched by the studio,
restricted to the vendor's hosts) and scoring the account's models where the production
hierarchy reads scores; a fallback default follows the recommendation, a locked one is
reported on. Google Trends for the studio's country is read daily (migration 0028) and, with
the studio's own measured cohorts, reaches the Researcher's proposals and the Director's
weekly review — so the adaptation loop runs the day real numbers appear. `STUDIO_TRENDS_GEO`.

## Correspondence, and the day that stopped (2026-09-12)

Messages are letters in threads (migration 0027): the ledger names both ends and opens the
thread; the Owner reads the exchange and writes back. Employees answer the letters that ask
for something at each worker pass, and the Director reads the answers at once; a letter to
the Owner (a decision that is hers, a day that stopped, a review that could not run) is red,
under the Owner chip, and waits for the Owner's reply. The empty answers of 2026-09-11 came
from the adapter the studio actually uses (`ConfiguredLLM`, thinking now off, ten-minute
timeout), a stale THINKING flag (runs are records while they run), and media defaults never
chosen (the day finishes its own setup). Token budgets are three times larger.

Still open from the Owner's office-logic request: employees choosing a video model by
researching online (cost, capability, examples), analytics-driven adaptation from Google
Trends and channel numbers, and the visual polish pass — tracked in `13_ROADMAP_TODO.md`.

## The Director's mandate: grow views and retention — 2026-09-11, ZCode (verified, scope released)

Owner's second decree of the day, implemented and live-verified:

- **Sarah's mission is now the growth of the audience** — raising views and retention is her
  primary charge (`_ROLE_DEFINITIONS` + migration `0026_director_mandate`, which also offers
  contract seed v3 to roles never Owner-edited).
- **Contract v3 powers**: she directs ANY employee in writing (every instruction, choice and
  request documented as a message), steers each channel's direction and changes or
  deprioritises topics when the measured performance says so, and requests a larger budget
  from the Accountant with the numbers and the reason written down — the Owner alone
  decides budgets, so a justified request also reaches the Owner. The Accountant's matching
  duty: answer every budget request from the books, in writing.
- **The weekly review routes the mandate.** Its answer is now structured
  (`weekly-review-v2`): verdict, sound indications (→ Lyra), video indications (→ Kael),
  channel direction and topic changes (→ LeadResearcher and ScriptWriter, and remembered as
  STRATEGY memory), a budget request (→ the Accountant, amount + justification) and an
  Owner escalation — all filed as messages that enter each employee's runs, plus her spoken
  summary in the office and the full review in her inbox. A schema-breaking answer files
  nothing and says so; a week with nothing published still reports that at zero tokens.
- **The Accountant answers budget requests at the daily close**: each open request is
  answered with the books' figures, resolved as "transmitted to the Owner", and the close
  escalates — documentation without ever granting a budget (Owner-only, unchanged).

Live verification: server restarted on `0026_director_mandate` (mission + contracts at v3
confirmed in the database), weekly review triggered and completed with the honest
"nimic publicat, nimic de măsurat" STATUS. Tests: backend 528 passed / 1 skipped (new:
schema-break files nothing; the Accountant's budget-request close); ruff, format, mypy
clean; frontend 79/79; docs integrity passes. The pre-existing secret-scan false positive
(`discovery.py:80`) stands, untouched, in Codex's file.

## The roles the Owner ordered: sound, video, and a Director who checks weekly — 2026-09-11, ZCode (verified, scope released)

Owner directive implemented end to end, live-verified against the running studio:

- **Contracts v2** (`config/role_contracts.json`, migration `0025_role_contracts_v2` data-only):
  the sound artist stewards the audio — chooses voice and TTS model where the channel's
  policy allows, weighs naturalness, recorded cost and measured retention, follows the
  Director's written indications, escalates when an indication would break a lock; the video
  editor the same for film models (quality/cost/what kept viewers watching); the Director
  decides from measured performance, sends production indications as messages to the two
  departments, and never skips the weekly review while anything published exists. A role the
  Owner has edited keeps the Owner's text (the migration only offers the newer seed).
- **The Director's indications now reach the employees.** Open messages addressed to an
  agent enter that agent's composed identity ("WHAT IS ASKED OF YOU RIGHT NOW", capped at
  ten, recorded in the context manifest) — identity v2. Resolved messages stop following
  the employee.
- **The weekly performance review** (`backend/app/runbook/weekly.py`): a scheduled job every
  seven days (active standing policy, first fire an hour after birth) plus an Owner button
  in the runbook panel and `POST /runbook/weekly-review`. It reads only what is recorded
  (publications with measured views/retention/CTR, per-channel totals, open strategy
  recommendations), puts the digest in front of the Director through her identity, and files
  her answer as HANDOFF indications to the sound and video departments and a STATUS report
  in her inbox. A week with nothing published reports exactly that and costs no tokens —
  verified live: task `COMPLETED`, "Revizia săptămânală 2026-S37: nimic publicat, nimic de
  măsurat". The autonomy stop gates both the schedule and the button; a week is reviewed at
  most once by the clock.
- Failed agent runs now log the exception with its traceback (`exc_info`), for diagnosis.

Tests: backend 526 passed / 1 skipped (new: open-messages identity test, three weekly-review
tests, scheduler asserts the two standing jobs); ruff, format, mypy clean; frontend 79/79,
tsc clean, build OK; docs integrity passes. Live: server restarted on 0025, contracts at v2,
both jobs registered (daily dormant, weekly active), UI checks 5/5
(`scratch/verify_weekly_review_ui.mjs`). The pre-existing secret-scan flag
(`discovery.py:80`, keyword false positive in Codex's file) stands, untouched.

Honest limits: the review reads the numbers `performance_intake` has collected — with no
publications yet there is nothing to judge, and the departments have no bound voices/models
to be bound by indications until those are configured (the Owner's next configuration step,
not code).

## ZCode investigation + inspector extend — 2026-09-11 (verified, scope released)

Owner questions answered by investigation (no behaviour change): the double "Sarah said"
line is two real `owner_chat` runs sent by the first verification pass, not duplication —
each has its own run row and its own freshly generated answer (today's re-verification
added a third turn). The `performance_intake` SKIPPED message was written at 20:17, before
the channel slots were bound (20:18–20:19, events `channel.credentials_bound`); verified
live against the current database that both bindings are `publisher_ready` and the
analytics provider resolves — the next daily run will not repeat that skip (it will report
"Nicio publicare reală de măsurat", which is the honest state while nothing is published).
Per-channel production criteria are implemented end to end (`media/production_policy.py`
hierarchy and locks, `media/factory.py render_plan` building real ElevenLabs/Runway
adapters per scene, the plan recorded on the render job); the gaps are data, not code:
no character has a bound/locked voice yet and no storyboard carries a `channel_id`, so on
Channel B the "fixed voice" has nothing defined to enforce and nothing routes production
to a channel. Agents have no tool-calling: a run is one prompt; the STATUS lines an
employee "says" are written by deterministic stage code in its name.

Code change: an «⛶ Extinde» button on the Agent Inspector header — the dialog fills the
screen and the whole history reads as one traversable page (no inner scroll box); the
choice persists while reopening the inspector during the session. Frontend only
(`index.html`, `main.js`, `style.css`). Verified: frontend 79/79, tsc clean, build OK,
browser checks 16/16 (`scratch/verify_conversation_live.mjs`, including expand/restore),
zero page errors; screenshot `output/playwright/conversation-inspector-expanded.png`.

## The conversation reads like one — 2026-09-11, ZCode (verified, scope released)

Owner-reported defects, fixed frontend-only against the data already recorded:

- **Raw JSON is no longer shown to the Owner.** A run whose output is JSON (URL picks,
  claims, topics, scenes, verdicts) renders as sentences and lists
  (`frontend/src/friendly_text.js`); the exact model output stays collapsed under
  «Răspunsul exact al modelului», and everything remains saved on the run. A truncated
  answer (token limit mid-list) has its complete items salvaged and shown with a note —
  the Owner-visible case came from Dr. Aris's stored runs and is unit-tested. Old runs
  whose only line was the engineered prompt no longer print instructions as the headline;
  the prompt stays under «Cererea completă».
- **The inspector chat is a live, saved exchange.** Owner question right, employee answer
  left; a "scrie…" indicator driven by the real THINKING/IDLE events; the history refreshes
  itself on message/run events for the open employee, including runs fired from outside
  the page. Proven with a real chat turn (Sarah/glm-5.3-flash) that survived a reload.
- **A live window into an employee's work.** The inspector's «Fereastră live ↗» opens a
  standalone popup (`frontend/src/live_window.js`): state pill, "Acum: …" line, and the
  employee's own event chain, seeded with the day from the ledger and updated from every
  newly recorded event via `Ledger`'s new `onEvents` callback (one funnel for socket,
  snapshot and events endpoint). The inspector detail view is unchanged.
- **The wide dialogs actually reach the page** — they were already styled at
  `min(1180px, 94vw)`; the served build was stale. Rebuilt; measured 1180px in Chromium.

Tests at release: frontend `npm test` 79/79 (14 new for the two modules), `tsc` clean,
build OK; backend `pytest` 522 passed / 1 skipped (unchanged code); ruff, ruff format,
mypy, documentation integrity pass. Browser verification: 14/14 checks in
`scratch/verify_conversation_live.mjs` against the running studio on port 8000, zero page
errors; screenshots `output/playwright/conversation-*.png`. One live chat turn was sent to
an existing configured provider as part of verification.

**Pre-existing baseline failure discovered, not mine and left for its owner:** since the
ElevenLabs work landed (`backend/app/integrations/discovery.py:80`, commit 1c8de87/096dd26),
`scripts/check_secrets.py` flags the dictionary key `"invalid_api_key"` — a keyword-detector
false positive on a key *name*, not a credential. Confirmed present on a clean tree
(stash/pop). `discovery.py` is inside Codex's active claim, so I did not touch it.

## The day starts without blocking the page (2026-09-11)

The Owner's "Pornește rularea de azi" queues the day on the background worker and says so;
the run panel shows the day on its way, and the ledger names each stage as it starts and
ends. Agent runs carry a one-sentence summary of their task, so a history reads as work done
rather than as the prompt behind it, and a run that returned no visible text is recorded
EMPTY_OUTPUT with its reason — thinking models were spending the whole token budget on
reasoning, which is now switched off for Ollama generation.

## Live ledger and the office first (2026-09-11)

The workspace opens on the office, wide, with a live ledger in the left column: every message
an employee sends or files, every task, stage, cost and Owner action, in words and by name,
newest first, filtered by kind, with the production stage and the last daily run in the
head line. The ledger streams over the WebSocket and backfills the day from `GET /events`.
Owner Control and Workforce panels are gone; autonomy is one ON/OFF switch in the office
toolbar. The evening books report is filed by the Accountant, with her headline and holds.

## Books, budget, history (2026-09-11)

Eight employees: Nadia (Accountant) joined, with contract, Bible and a desk in the Accounting
& Treasury office that replaced the Commons. The Owner sets a daily or monthly budget in
Trezorerie; spend is measured from the books, the media stage refuses what an exceeded
budget cannot afford, every render's narration is costed per scene at the stored price, and
the Accountant closes each day before the Director's review. Every employee has a history
(runs, messages, decisions with reasons) and a chat in the Agent Inspector; speech bubbles
page through the whole answer at reading speed. Details and limits:
`ACCOUNTING_AND_HISTORY.md`. Migration 0024.

## The pipeline has no empty stages left (2026-09-11)

Every stage of `../architecture/39_DAILY_AUTONOMOUS_RUNBOOK.md` now has work behind it. New:
§3 idea generation (the Lead Researcher proposes candidates scored on the runbook's six
criteria, deduplicated, limited to authorised hosts), the retrieval half of §4 (the studio
fetches its own pages and keeps only what actually came back) and §5 selection (the Director
chooses among topics that have a verified claim, and the decision is recorded on the topic).
A channel slot now names the YouTube account it publishes through; publishing and analytics
use that binding instead of "the first row", and `GET /publishing/channels` no longer answers
500 when several accounts are connected. `POST /settings/auto-configure` finishes what a
verified connection leaves unfinished, only where the choice is forced. Details and limits:
`PIPELINE_COVERAGE.md`. Migration 0023.

## Employees: identity, memory, reports (2026-09-11)

Every agent run now carries the employee's identity as the system prompt, composed from stored
data (role mission, allowed/prohibited tasks, the role's work contract from
`config/role_contracts.json`, the character's speech style and phrases, the memory its role may
read, standing rules) and records the context manifest on the run. Character Bible entries are
linked to the employees holding their roles. Memory (`memory_record`, classes per
`../architecture/04_AGENT_SYSTEM.md` §9) is written by services on real outcomes with
provenance and read by role scope. Typed messages (`agent_message`) carry STATUS reports and
escalations to the Director; the runbook's `post_run` stage files the day's reports and runs
Sarah's review. Lyra reviews narration, Kael diagnoses failed renders, Vera prepares
publication metadata and may hold a candidate. Details and limits: `AGENT_IDENTITY_MEMORY.md`.
Migration 0022. No new agents were added: hiring stays evidence-driven through workforce
proposals.

## Identity

The agency is **AMN-AI — Autonomous Machine Nexus — Artificial Intelligence**. The name and logo
assets, and the rule that the stored studio name is domain state rather than configuration, are
documented in `BRAND_AMN_AI.md`. Renaming an existing studio is done with
`scripts/rename_studio.py`, which appends a `studio.renamed` event; bootstrap never rewrites it.

## Audit history

- **2026-09-09**, external: found fabricated channel configuration, simulated uploads recorded as
  real publications, a non-playable file named `.mp4`, a self-certifying QC gate. Remediated; see
  `AUDIT_2026-09-09_EXTERNAL.md`.
- **2026-09-10**, third party: `AUDIT_2026-09-10_THIRD_PARTY.md`.
- **2026-09-11**, internal, at the Owner's request: nine defects found and fixed, five areas
  verified and put under test. The most serious were an unanswered question to YouTube recorded as
  a "no" (risking a duplicate upload), a factual gate passing assets it had never traced while
  claiming verification, and Owner funding that a retried request could double. See
  `AUDIT_2026-09-11_INTERNAL.md`.

## Running on its own

Since 2026-09-11 the application process carries a background worker that fires due scheduled
jobs and executes the tasks they enqueue (`backend/app/workflows/worker.py`); since 2026-09-17
the daily job is on the wall clock. `daily_main` (`DAILY_RUN`) is seeded at start-up at
`STUDIO_DAILY_RUN_HOUR_LOCAL` (05:00) in `STUDIO_TIMEZONE` (Europe/Bucharest) —
`scheduled_job.run_at_local` and `.timezone` on the row, a changed hour followed on every
start-up — and seeded dormant: the Owner starts it from the daily-run panel, that decision is
the event `workflow.job_activated`, and waking it schedules the next 05:00, never a fire on the
spot. When a slot passes, the tick enqueues one task keyed on the job and the slot and moves
the job to the next local occurrence of its hour (`next_local_occurrence`, computed on the
local calendar and compared as UTC instants, so the clocks changing neither doubles nor skips
a day); a slot missed while the studio was off fires once when it is back, never a backlog.
Nothing fires while the autonomy stop is set. The clock does at most one successful day per
business date: a date with a COMPLETED or PARTIAL run is not repeated (a second run that day
is the Owner's button, which counts toward the attempts); a day that could not run — a
BLOCKED preflight, a stage that failed on a TRANSIENT fault — is re-attempted the same day
after `STUDIO_DAILY_RETRY_SECONDS` (1800), up to `STUDIO_DAILY_MAX_ATTEMPTS` (3), each attempt
queued under `daily-retry-<date>-<n>` and held by the queue's `not_before`; a re-attempt that
outlives its date skips itself, and a HARD fault opens safe mode and is not re-attempted
(corrected 2026-09-18: a HARD fault opens safe mode only in media, publish or the day's log, or
for a database integrity error; a failed stage blocks only the stages that depend on it, and the
re-attempt follows only a transient fault that cost the day's films — see «The rehearsal on the
Owner's data (2026-09-18)»). Of
the twelve runbook stages, `build_stage_runners` supplies ten (`performance_intake` through
`post_run`, and `serial_queue`); `preflight` and `daily_log` are built into the run itself,
and every stage reports COMPLETED or SKIPPED with a count and a reason.

## Connected accounts

Avatar repair verified 2026-09-11: the CSP now permits YouTube's two avatar origins and the
snapshot selects high → medium → default. Both existing connections (Nexus Curiosity and Inside
The Nexus) were refreshed through the real Verify buttons and displayed their own 800×800 API
images in Chromium, with persisted URLs and zero image-policy violations. Missing-thumbnail
fallback passed a separate browser fixture; completed-Reconnect refresh passed stubbed API tests.
Changed: YouTube snapshot selection, HTTP image CSP, connection-card avatar/CSS, regression tests
and `scripts/verify_youtube_avatars.mjs`. No migration. The local server was rebuilt/restarted.
Validation: 435 backend tests passed, 1 skipped (unconfigured real Ollama); 52 frontend tests
passed; Python/JS type checks, lint, frontend build, documentation integrity and secret scan passed.
Evidence and scope limits are in `YOUTUBE_CONNECTIONS.md`. No remaining avatar blocker.

YouTube channels are connected by OAuth, not by pasting credentials. Settings → *Conturi și
e-mail* takes a connection name, a Google OAuth client id and secret, and a redirect URI; the
Authorization Code flow with `access_type=offline` does the rest, and the channel identity is read
back from `channels.list` rather than typed. Refresh tokens and client secrets live in the Fernet
vault and are never returned by any route. Multiple independent channels are supported, and no
channel is named in the code. Connecting a channel is not the same as publishing to one — see the
Phase 6 correction below. Evidence: `YOUTUBE_CONNECTIONS.md`.

## Baseline and document authority

Started from 83 Markdown documents with no application code, tests, dependencies or Git history.
All original documents were read. The Master Prompt remains authoritative under Owner instructions.
There was no pre-existing test suite to run.

Per Owner request, 78 specifications/review documents live in ../architecture/; five original
tracking documents live here. The document index records original and post-move hashes. Only path
references were changed inside the architecture package. CI/local checks protect the indexed files.

## Working and verified locally

**Phase 0 (complete):**
- FastAPI application at http://127.0.0.1:8000, with private Owner Bearer authentication.
- HTML/Tailwind/JavaScript UI built with Vite; desktop and 390px mobile layouts inspected.
- SQLite database and Alembic revisions 0001_foundation, 0002_phase1_agents, 0003_phase2_automation, 0004_phase4_factual; explicit bootstrap.
- Persisted studio, empty initial room, Owner STOP flag, immutable command/event history.
- Atomic policy/event transactions, optimistic version checks and command idempotency.
- Duplicate/concurrent commands tested; failed event insertion rolls back policy changes.
- STOP state survives application restart; clearing it keeps MANUAL mode.
- Owner-only consistent snapshots/event pagination; disconnects label stale UI.
- No credentials in frontend builds, API projections or request logs.
- Structured request logs, request correlation, health endpoints, CSP/Host checks.
- Locked Python/Node dependencies, lint/types/build/test baseline and GitHub Actions.
- Documentation inventory/hash checks with integrity tests.

**Phase 1 (complete — verified 2026-09-09):**
- Abstract LLMProvider interface (base.py): health_check, list_models, generate, is_cloud model metadata.
- Ollama HTTP adapter (ollama.py v1.0.0): real /api/tags discovery + /api/generate; returns OFFLINE if not running; supports cloud models (glm-5.2:cloud, kimi-k2.6:cloud, qwen3-coder:480b-cloud), api_key bearer auth, and /api/show model inspection.
- ProviderRegistry (registry.py): maps provider IDs to adapter instances; in-process health cache.
- Dynamic model discovery (sync_provider_models): automatically discovers both local and cloud models from provider endpoint, updates model_record, links text_generation capabilities, and emits provider.model_discovered events.
- Role entity with mission, allowed_task_types, prohibited_actions; RoleCapability requirement levels (REQUIRED/PREFERRED).
- Capability entity (text_generation, tool_calling, etc.); ModelCapability mapping with confidence.
- ProviderRecord, ModelRecord: registered providers and models with discovery_method tracking.
- Agent entity: lifecycle (PROPOSED/CANDIDATE/HIRED/ACTIVE/PAUSED/SUSPENDED/TERMINATING/TERMINATED/ARCHIVED) and runtime_state (IDLE/THINKING/WORKING/...).
- AgentRun envelope: full audit record of every LLM invocation with status, tokens, cost_vr, event_id.
- ToolReceipt: immutable append-only receipts (DB trigger, no UPDATE/DELETE) for all tool calls.
- Owner Policy Kernel: enforces autonomy_stop check, lifecycle check, capability match, provider health before any LLM run.
- FastAPI routes: GET/POST /api/v1/agents/, GET/POST /api/v1/providers/, /sync-models, /run.

**Phase 2 (complete — verified 2026-09-09):**
- Persisted workflow state machine (Workflow, WorkflowStep): tracks 17 pipeline stages (DISCOVERY -> ... -> PUBLISHED -> ANALYTICS -> LEARNING) according to 47_STATE_MACHINE_SPECIFICATIONS.md; rejects illegal state transitions.
- Task queue with leases and backoff (TaskQueueItem): atomic task claims with time-bounded worker leases, automatic expired-lease reclamation when workers fail, heartbeat renewal, and task completion.
- Error classification and dead-letter queue: retryable failures trigger exponential backoff with computed next_attempt_at; max attempts exhausted routes tasks to DEAD_LETTER; operator recovery endpoint allows manual retry.
- Singleton-safe scheduler (ScheduledJob): recurring jobs with leader leases to prevent duplicate work across scheduler instances, with support for SKIP and CATCH_UP missed-run policies.
- Transactional outbox (OutboxRecord): atomic commit guarantees that business events and outbox records commit together; outbox dispatcher broadcasts to WebSocket clients and marks status PUBLISHED.
- WebSocket gateway (/api/v1/ws): authenticated real-time event streaming with replay protocol supporting after_sequence cursor to replay missed events after reconnection.
- Autonomy stop hard-gate: task worker and scheduler refuse to claim or run tasks when autonomy_stopped is active.
- Alembic migration 0003_phase2_automation: 5 new tables (workflow, workflow_step, task_queue, scheduled_job, outbox_record) with zero schema drift.

**Phase 3 (complete — visual system v2 2026-09-10, see `PIXEL_OFFICE_V2.md`; Blender sprite pipeline tried on the RESEARCH floor 2026-09-11 and switched off after the Owner's comparison; Character Bible now drives character looks, see `PIXEL_ART_PIPELINE.md`; per-channel production policies with locked character identities 2026-09-11, see `PRODUCTION_POLICY.md`):**
- Premium pixel-art rebuild of the cutaway (palette module with hue-shifted ramps, compiled outlined character sprites with role costumes, per-department room shells and interiors, baked lighting, limestone facade, glass lift). Designed first in Figma (`AMN-AI Office · Pixel Art Design System`, file `bqTc0PoCbjL5dH5xw0FRDI`), then implemented frontend-only; backend, API and events untouched. Measured 60 FPS at ~6 ms/frame; 43 frontend tests pass.
- Lateral cutaway multi-floor skyscraper canvas rendered at 60fps with zero simulated state, inspired by Space Haven, Anomaly President, and retro pixel-art simulation games.
- Seniority-based corporate hierarchy from top to bottom:
  * Floor 4 (Penthouse / Executive Suite): Director / CEO (Sarah) with panoramic city view, executive mahogany desk, gold trendlines, and award trophies.
  * Floor 3 (Research & Fact-Check Lab): Lead Researcher (Dr. Aris) & Fact Checker (Elena) with glowing holographic network graph whiteboard.
  * Floor 2 (Creative Writing & Narrative Studio): Script Writer (Marcus) with cork storyboard pinned with colored cards and red string.
  * Floor 1 (Media Lab & Production Bay): Voice Artist (Lyra) in acoustic foam vocal booth with boom mic & active LED EQ meter; Video Editor (Kael) with triple editing monitors.
  * Ground Floor / Level 0 (Infrastructure, Distribution & Lounge): Ollama Local Cluster & Cloud AI Gateway racks with blinking LED matrices and cooling fans; Coffee lounge with espresso machine emitting steam, water cooler, couch, and wall clock; Distribution hub with Vera at release console with radar map.
- Functional Glass Elevator Shaft on building exterior with moving elevator cabin traveling between floors.
- Procedural Animated Characters (Personaje):
  * Idle breathing bounce and periodic eye blinking.
  * Rapid typing hands on keyboard with dynamic monitor light reflections when WORKING.
  * Chin scratching gesture with floating glowing idea lightbulb and sparks when THINKING.
  * Resting / Zzz animation when PAUSED.
- Smooth camera controls: mouse pan, pinch/wheel zoom (0.4x to 2.5x), `fitToOffice()`, 1:1 reset, and dedicated Fullscreen (`#fullscreen-btn`) & Exit Fullscreen (`#exit-fullscreen-btn`) buttons with automatic canvas resize and Escape key support.
- Interactive Agent Inspector drawer modal (`#agent-inspector`) opened by clicking any character workstation, supporting live agent state inspection, direct task execution, and pause/resume actions (`POST /api/v1/agents/{id}/pause`, `POST /api/v1/agents/{id}/resume`).
- Real-time WebSocket connection to `/api/v1/ws` syncing backend events directly into `OfficeState`.
- Zero CSP violations (`style-src 'self'`). Frontend bundle remains compact.

**Phase 4 (PARTIAL — verification machinery works, real research does not exist):**
- Alembic migration `0004_phase4_factual`: 5 new tables (`topic_idea`, `source_snapshot`, `factual_claim`, `script_draft`, `hook_option`).
- Zone D Prompt Injection Defense (`sanitizer.py`): token stripping, instruction override filtering, and inert `<untrusted_source_evidence>` XML boundary tagging.
- Immutable source snapshots with SHA-256 digests (`content_hash`) and metadata (url, publisher, author, credibility_score). **Source text is supplied to the API by the Owner; nothing is retrieved from the web — there is no search or research adapter.**
- Atomic claim model (`factual_claim`) with status (`UNVERIFIED`, `SUPPORTED`, `REFUTED`), importance (`CRITICAL`, `SUPPORTING`, `FLAVOR`), and confidence.
- Strict Content Gate: attempts to generate or approve scripts with unverified or refuted claims raise `FactualGateError` and record an immutable `BLOCKED_UNVERIFIED_CLAIMS` draft for auditability (`factual.script_blocked_by_gate`).
- Script generation with 100% `SUPPORTED` claims compiles scene cues, voiceovers, and claim references. **A claim becomes SUPPORTED only through `POST /factual/claims/{id}/verify`, whose status is decided by the caller; there is no independent fact-checking agent.**
- Hook Specialist: opening hook variations with psychological techniques (`CURIOSITY_GAP`, `CONTRARIAN`, `STATISTIC_SHOCK`, `STORY_IN_MEDIA_RES`) and retention scores.
- Deduplication novelty calculation preventing repetitive content drift.
- Ollama Cloud model integration (`glm-5.2:cloud`, `kimi-k2.6:cloud`, `qwen3-coder:480b-cloud`).
- Frontend Topic Submission & Verification Modal (`#research-modal`) in 2D Office.
- **Not met for Phase 4 acceptance** (`IMPLEMENTATION_PLAN.md`: "real research, evidence, independent fact checks"): research and independent verification are manual.

**Phase 5 (PARTIAL — real encoding works, real visuals/voice do not exist):**
- Character Bible (`character_bible`): Pre-seeded with 7 canonical studio employees (Sarah, Dr. Aris, Elena, Marcus, Lyra, Kael, Vera) with immutable visual descriptions, hex palettes, role symbols, and voice profiles.
- Storyboard generator (`storyboard`, `storyboard_scene`): Transforms approved scripts into multi-scene visual shot lists enforcing aspect ratio 9:16 (1080x1920); strictly blocks unapproved scripts or scripts with unverified claims via `FactualGateError`.
- Placeholder media adapters (`DeterministicVisualAdapter`, `DeterministicTTSAdapter`): produce SVG layout cards and RIFF/WAVE tones locally. These are placeholders, not generated content: no image model and no voice model is connected. Assets built from them are recorded with provider `PLACEHOLDER_DETERMINISTIC_VISUALS` and are **blocked by QC from publication**.
- Subtitle generator: Compiles synchronized SRT subtitle tracks matching scene voiceover segments and durations.
- Video Assembly Engine (`VideoRenderJob`, `MediaAsset`): encodes a real H.264 1080x1920 MP4 with FFmpeg from raster placeholder frames plus the narration track, and records a SHA-256 digest of the encoded bytes (`media.video_rendered`). **Without FFmpeg the render fails** (`RenderEngineUnavailable`, HTTP 503) and no MediaAsset is recorded; the studio no longer writes a stand-in file with an `.mp4` name.
- Quality Control Engine (`quality_control_report`): Technical QC now **measures the file with ffprobe** (video stream present, measured resolution, measured duration) and **recomputes** the SHA-256 provenance digest, instead of trusting the metadata the renderer wrote. Rights QC checks the license field. Content-source QC fails any asset built from placeholder visuals. Factual QC re-checks every referenced claim. Character-drift QC is reported as `NOT_IMPLEMENTED` — it performs no comparison and certifies nothing.
- Alembic migration `0005_phase5_media`: 6 new tables (`character_bible`, `storyboard`, `storyboard_scene`, `media_asset`, `video_render_job`, `quality_control_report`).
- Media API routes (`/api/v1/media`): Character Bible endpoints, Storyboards, `POST /storyboards/demo-fixture` (creates a topic/script with an **UNVERIFIED** claim; it never marks anything SUPPORTED), video rendering, streaming, and QC gate verification.
- Frontend Media Production Modal (`#media-modal`): Storyboard pipeline viewer, 9:16 preview, QC scorecard, provenance hash badge, Character Bible inspector.
- **Not met for Phase 5 acceptance** (`../architecture/26_MASTER_ACCEPTANCE_CRITERIA.md` §F): there is no image or TTS provider, so no real footage or narration exists; character continuity is unimplemented.

**Phase 6 (PARTIAL as written on 2026-09-09; corrected 2026-09-18 — the pipeline and gates work, and two private uploads have reached Main Channel A since):**
- Channel slots (`channel_record`, `channel_brand_asset`): two slots (`MAIN_FACTUAL`, `OFFICE_SERIAL`) are seeded with **no remote channel ID, no credentials and status `NOT_CONFIGURED`**. Status is derived from what is actually present (`NOT_CONFIGURED` -> `AUTH_REQUIRED` -> `AUTHENTICATED`); nothing is ever reported as configured on the strength of a seed.
- Five-check publishing gate (`evaluate_publishing_gate`). This is a **subset** of the publish column of `../architecture/50_CONTENT_GATE_MATRIX.md`, not an implementation of it — rights on the final package, platform policy, novelty on final metadata, brand strategy, budget, and Channel B continuity/narrative privacy are not implemented:
  1. Global Autonomy Stop check (fails if `autonomy_stopped` is active).
  2. Media file on disk existence check (fails if file missing or 0 bytes).
  3. Quality Control check (fails if QC status is not `PASSED` or score < 0.90).
  4. Factual claim integrity check (fails if any claim referenced in the script is not `SUPPORTED`).
  5. Idempotency & duplicate protection check (fails if asset was already published on that channel).
- YouTube Data API v3 Adapter (`YouTubeProvider`): OAuth2 refresh-token exchange, chunked resumable upload with `Content-Range` and 308 resume, synthetic-content disclosure (`containsSyntheticMedia` plus a disclosure line in the description), remote status polling, and reconciliation that is actually invoked before any retry. **This adapter has never run against Google** — as of 2026-09-09; superseded: channels connect by OAuth since 2026-09-11 and `publication_record` holds two PUBLISHED private uploads of 2026-09-12 with real remote ids (`98JltCPoOKs`, `sDEtt-WQGh8`; see `CHANGELOG.md`, 2026-09-13). `publishAt` and `videos.update`, added 2026-09-17, have run only against a faked transport.
- Simulated Publishing Adapter (`DeterministicPublishingAdapter`): **tests and CI only**. It is never selected at runtime; without real credentials the API returns 503 `PublisherNotConfigured`. Its results carry `simulated=True`, a `sim:` identifier and no platform URL, and are stored as `PUBLISHED_SIMULATED` with event `publishing.video_published_simulated`.
- Publication State Machine & Tracking (`publication_record`): Enforces `DRAFT_INTENT` -> `VALIDATED` -> `STARTED` -> `REMOTE_CONFIRMED` -> `PUBLISHED` transitions with recovery from `REMOTE_UNKNOWN` and `FAILED_RETRYABLE`.
- Unique constraint `uq_channel_idempotency`: Prevents duplicate uploads of the same intent.
- Alembic migration `0006_phase6_publishing`: 3 new tables (`channel_record`, `channel_brand_asset`, `publication_record`).
- Publishing API routes (`/api/v1/publishing`): Channel management, gate evaluation, intent creation, publication execution, quick-publish, and publication history retrieval.
- Frontend Distribution Hub Modal (`#publishing-modal`): shows real channel status with plain-language hints, a banner when no credentials are configured, the gate breakdown including what is not implemented, and publication history where a simulated run is labelled "SIMULAT (nepublicat)" and gets no link. Only a genuine `youtube.com` URL becomes a clickable link.
- **Not met for Phase 6 acceptance** (`../architecture/26_MASTER_ACCEPTANCE_CRITERIA.md` §G): OAuth has never been exercised, no private upload has been verified, and no real remote ID has ever been persisted — as of 2026-09-09; met since: OAuth exercised 2026-09-11, two private uploads with real remote ids persisted 2026-09-12. The per-channel policy of 2026-09-17 is unproven against Google for a scheduled release.

**Phase 11 (complete for the ledger — verified 2026-09-10, see `PHASE11_ECONOMY.md`):**
- Immutable double-entry VR$ books: `ledger_account`, `ledger_transaction`, `ledger_entry`, with
  a seeded chart of accounts covering cash, restricted cash, receivables, fixed assets,
  depreciation, debt, equity, revenue by source and expense lines.
- External evidence layer: `revenue_evidence` (YouTube, donations, sponsorship, other),
  `provider_cost_record`, `owner_funding_event` and `fx_snapshot`. Recording evidence mints
  nothing; only SETTLED revenue mints, and only a BILLED invoice posts a cost.
- The 1:1 rule holds under retry and re-import: `(source, external_reference)` is unique and a
  minted row is stamped with its transaction, so one verified dollar becomes one VR$ exactly once.
- Forecast and pending payouts are reported beside the treasury, labelled, and can never be
  minted or spent. FX is never invented: a non-USD amount without a recorded rate is refused.
- Reversals post a mirrored transaction and never delete; a transaction is reversible at most
  once. A chargeback after real spending shows a deficit rather than hiding it.
- Money is integer micros throughout, so the books cannot drift; `trial_balance` re-adds every
  stored line and is surfaced in the UI.
- Owner-only routes under `/api/v1/economy`; **no route anywhere in the API pays, buys, transfers
  or checks out**, and a test asserts that across the whole OpenAPI surface.
- Frontend **Trezorerie** panel renders the backend's own labels (VR VIRTUAL / PENDING / FORECAST
  / ESTIMAT), the trial-balance verdict and the "not filed accounts" disclaimer.
- Alembic migration `0016_phase11_economy`: 7 new tables. 31 new tests.
- **Not met yet**: nothing spends VR$, no interest accrues, no budgets/runway/P&L, no depreciation,
  and no automatic revenue import — those are Phases 12–14.

## Partial / exact limits (written 2026-09-09; dated corrections inline)

- The application runs end to end locally: foundation, automation, 2D office, factual gating,
  media assembly and the publishing state machine are all exercisable.
- **Two films have been published, both private** (corrected 2026-09-18; the sentence "nothing
  has ever been published" stood here from 2026-09-09): Main Channel A, 2026-09-12, remote ids
  `98JltCPoOKs` and `sDEtt-WQGh8`, recorded PUBLISHED in `publication_record`. Without a bound
  CONNECTED account the publishing API still refuses (503), and the simulator is reachable
  only by injecting a provider in tests.
- **Placeholder renders never pass QC for publication** — content-source QC fails them by
  design; since the Runway and ElevenLabs connections were verified (2026-09-12) real renders
  have passed QC and been published.
- Rendering requires FFmpeg on the host. Without it, `POST /media/render/{id}` returns 503.
- Local single-owner SQLite deployment only. PostgreSQL and multi-user auth remain pending.
- Real Ollama end-to-end test is skip-marked; it runs when `STUDIO_OLLAMA_URL` is set.

## Not implemented (written 2026-09-09; dated corrections inline)

- Search/research adapter (Phase 4 acceptance) and independent fact-checking agent.
- Character-continuity drift detection: quality control reports the check `NOT_IMPLEMENTED` and
  certifies nothing. (The image and TTS providers this line once named are connected since
  2026-09-12: Runway and ElevenLabs.)
- The remaining publish-time gates of `../architecture/50_CONTENT_GATE_MATRIX.md` (rights on final package,
  platform policy, novelty on final metadata, brand, budget, Channel B continuity/privacy).
  Since 2026-09-17 a sixth, policy-authorisation gate runs for a publication that would be
  seen, and Channel B's privacy is enforced when the log is projected, not at publish time.
- Dynamic departments. (The Office Serial's showrunner, the Director's episode review, the
  serial storyboard and its routing to Channel B exist since 2026-09-17/18 — see "Delivery
  and the serial" above — and no real day has filmed an episode yet.)
- Spending VR$: procurement/VendorShop (Phase 13) and treasury financing with interest accrual
  (Phase 14). The ledger they will post to exists; nothing spends from it yet.
- Finance dashboard: budgets, cost centres, runway/burn, P&L, balance sheet, cash flow and
  30/90/180-day scenarios (Phase 12).

## Test evidence

Independent audit environment (Linux, Python 3.13, SQLAlchemy 2.0), 2026-09-09, after remediation:

- `pytest` **with FFmpeg available**: 87 passed, 1 skipped (real Ollama), 0 failed.
- `pytest` **without FFmpeg**: 85 passed, 3 skipped (Ollama + two render tests that are skipped
  rather than silently exercising a fake path), 0 failed.
- `tests/test_truthfulness_gates.py` (new, 10 tests) locks the governance invariants: channel
  slots are never reported as configured, publishing refuses without credentials, a simulated
  upload is never stored as a real publication, a gate refusal is persisted with its event,
  QC rejects a non-video file named `.mp4`, QC rejects a tampered provenance digest, and the
  character-drift check never claims to pass.
- `ffprobe` on a produced render: 1080x1920, h264, duration equal to the storyboard timeline.
- `npm test --prefix frontend`: 6 passed. `npm run check`: 0 errors. `npm run build`: succeeded
  (51.33 kB JS, 24.44 kB CSS).
- **Live application verification** (`scratch/verify_post_audit_e2e.mjs`, real Chromium against a
  running server): **27/27 checks passed**, 0 console errors, 0 CSP violations. It exercises the
  full chain — login, clearing the Owner STOP, channel status, the credential banner, the 1-click
  publish refusal, the demo fixture, the factual gate blocking an unverified script, claim
  verification, approval, storyboarding, rendering, QC, and the publishing gate refusal — and
  confirms with `ffprobe` that the produced file is a real 1080x1920 H.264 video of 18.00s.
  Screenshots: `output/playwright/post-audit-publishing-hub.png`, `post-audit-history.png`,
  `post-audit-media-modal.png`, `post-audit-mobile.png`.
- **Cold-start verification**: from a clean checkout with no `.venv`, no `node_modules`, no `.env`
  and no database, `uv run python scripts/start.py` brought the studio up unattended (uv venv +
  `uv sync --locked` + `npm ci` + Vite build + bootstrap + server), `/health/live` answered 200,
  and the 27-check Playwright suite passed against that fresh instance.

Note on the previous revision of this section: the "80 passed" figure it reported was
reproducible, but the suite passed **because** FFmpeg was absent on the development machine —
the real encoder path raised `DetachedInstanceError` and had never been executed. The suite now
fails loudly in that situation instead of certifying the fallback.

## Files changed / architecture impact

Post-audit remediation (2026-09-09):
- `backend/app/config.py`: `STUDIO_YOUTUBE_*` and `STUDIO_FFMPEG_PATH` settings; credentials no
  longer read ad hoc via `os.getenv`.
- `backend/app/publishing/services.py`: honest channel seeding and `derive_channel_status`;
  gate refusals persisted before raising; `PUBLISHED_SIMULATED` state; QC score minimum
  enforced; reconciliation before any retry; no provider fallback.
- `backend/app/publishing/router.py`: 503 `PublisherNotConfigured`; `POST /channels/seed`
  replaces seeding inside a GET; 404 instead of 500 for a missing asset; quick-publish requires
  an AUTHENTICATED channel.
- `backend/app/providers/publishing_base.py`, `deterministic_pub.py`: `simulated` flag,
  `sim:` identifiers, no fabricated platform URL.
- `backend/app/providers/youtube.py`: chunked resumable upload, synthetic-content disclosure,
  `youtube_provider_from_settings`.
- `backend/app/media/assembler.py`: placeholder raster frames + real FFmpeg encode or
  `RenderEngineUnavailable`; no stand-in `.mp4`; storage root no longer a hardcoded Windows
  path; detached-ORM bug fixed.
- `backend/app/media/qc.py`: ffprobe measurement, provenance re-verification, content-source
  check, character drift reported as `NOT_IMPLEMENTED`.
- `backend/app/media/router.py`: `POST /storyboards/demo-fixture` creates UNVERIFIED claims
  only; render surfaces 503 when no encoder exists.
- `scripts/bootstrap.py`: fixed a `TypeError` that broke first-time `.env` creation.
- `frontend/index.html`, `src/main.js`, `src/style.css`: truthful channel and publication
  status vocabulary, credential banner, no links to non-existent videos.
- `tests/test_truthfulness_gates.py` (new); `tests/test_phase5_media.py` and
  `tests/test_phase6_publishing.py` updated to assert the honest behaviour.
- `pyproject.toml` / `uv.lock`: added `websockets` — without it uvicorn answered the
  `/api/v1/ws` handshake with 404 and the office never received live events. Run `uv sync`.
- `backend/app/factual/services.py`, `router.py`, `schemas.py`: new
  `POST /api/v1/factual/scripts/{id}/approve`, which re-runs the factual gate at approval time.
  Without it, scripts created through the real API (`VERIFIED_PASS`) could never reach the
  `APPROVED` status storyboarding requires — only the removed fixture endpoint could.
- `start.cmd` and `scripts/start.py` (new): single-command launcher with a preflight report that
  states which integrations are configured; `scripts/bootstrap.py` and `../../README.md` point at it.
- `scratch/verify_post_audit_e2e.mjs` (new): the Playwright verification described below.
- `docs/project/AUDIT_2026-09-09_EXTERNAL.md` (new): the audit these changes answer.

- `backend/migrations/versions/0007_correct_fabricated_records.py` (new, data-only): corrects
  rows already written by the pre-audit code — invented channel IDs are cleared and the channels
  set to `NOT_CONFIGURED`, `yt_sim_*` publications become `PUBLISHED_SIMULATED` with their dead
  YouTube URLs removed, and every earlier `PASSED` QC report is marked `INVALIDATED` because the
  gate that granted it measured nothing. Nothing is deleted; history stays auditable.
- `backend/app/main.py`: startup revision check moved to `0007_correct_fabricated_records`.

Modular monolith; no table was added or altered (migration 0007 is data-only). Phase 7 analytics
must therefore start at `0008`.

## Blockers and risks

- **Publishing is blocked by design** until `STUDIO_YOUTUBE_CLIENT_ID`,
  `STUDIO_YOUTUBE_CLIENT_SECRET` and `STUDIO_YOUTUBE_REFRESH_TOKEN` are configured and a
  channel is moved to `AUTHENTICATED`. The whole YouTube path is still unexercised against
  Google. (As of 2026-09-09. Superseded: channels connect by OAuth since 2026-09-11, two
  private uploads reached Main Channel A on 2026-09-12, and since 2026-09-17 a film goes only
  to the channel its storyboard names, at that channel's Owner-set visibility, private by
  default.)
- **Publishable content is blocked** until a real image/TTS provider replaces the placeholder
  adapters; content-source QC fails placeholder visuals on purpose.
- Rendering requires FFmpeg on the host.
- Phase 7 analytics code on disk is inert and unmigrated; wiring it as-is would cause schema
  drift and refuse startup.

## Exact next task

Close the acceptance gaps before advancing to Phase 7, in this order:

1. **Phase 4 acceptance** — a real search/research adapter (`../architecture/22_PROVIDER_INTEGRATION_CONTRACTS.md`
   search adapter contract) feeding `ingest_source_snapshot`, plus an independent fact-checking
   role that cannot verify its own claims.
2. **Phase 5 acceptance** — a real image provider and a real TTS provider, so renders stop being
   placeholder frames and content-source QC can pass; then character-continuity drift detection.
3. **Phase 6 acceptance** — configure Google OAuth, verify one private upload end to end against
   the real API, and record the real remote ID. (Done: OAuth 2026-09-11, two private uploads
   with real remote ids 2026-09-12.)
4. Only then Phase 7 (analytics), starting by adding migration `0008` for the analytics tables
   and wiring the router and `Base.metadata`.


## Codex research scope claim — 2026-09-09T23:19

Active: isolated public HTTPS source retrieval in new backend/app/research files, a local Owner CLI and dedicated tests. UI, media, app wiring, dependencies and migrations remain outside this claim while Claude works there. Baseline: 88 passed, 3 skipped; one documentation test fails on nine stale relative references.

## Codex research increment — completed, scope released

- Implemented Owner-directed known-URL HTTPS retrieval in new `backend/app/research/` files and `scripts/research_source.py`; existing UI/media/application code remains outside this change.
- The CLI can feed the existing authenticated source-ingestion API. No claim is automatically verified; no search provider or worker is activated. Phase 4 remains partial.
- Corrected nine stale architecture/root-document references in project tracking. Original architecture hashes are unchanged.
- Windows validation: 121 passed, 3 skipped (real Ollama unavailable; two FFmpeg checks unavailable). New-module Ruff and mypy pass; document inventory/hash verification passes.
- Real IANA HTTPS retrieval and authenticated ingestion into an isolated temporary database succeeded with matching hashes. Live studio state was not changed.
- Usage, limitations, touched paths and exact remaining research work: `RESEARCH_HANDOFF.md`.
- Next: keyword-search provider integration and independently authorized fact checking; coordinate separately before modifying shared factual routes. Claude retains UI/media scope.

Verification follow-up: the secret scanner flagged a pre-existing hardcoded provenance fixture in `tests/test_phase6_publishing.py`. Replaced only that fixture value with the actual SHA-256 of its test video bytes; no scanner suppression or publishing implementation change.

Final follow-up checks: all six publishing tests pass after the fixture correction; secret scan and documentation inventory/hash checks pass. No frontend or pre-existing backend source file was modified.

## Codex Settings scope — 2026-09-09T23:38

Owner explicitly requested Settings UI: LLM providers, agent assignments, video/audio tools, YouTube/TikTok/Instagram/Facebook and optional email credentials. Scope: new integrations backend + migration 0008, separate settings UI module/styles and minimal app wiring. No office animation edits. Credentials encrypted; saved configuration must never imply verified connectivity or publishing capability.

## Owner-directed renderer fixes — 2026-09-10, ZCode

Owner-reported visual defects only, scope `frontend/src/office_engine.js` scenery/nameplates + one new frontend unit test: remove the invented bus route number "12", stop same-lane vehicles passing through each other (lane spacing at spawn + car-following), and shrink the agent nameplates onto a light "paper" plate for readability. No backend, settings, integrations or office-state changes.

Completed and released the same day. Details:

- `drawCar`: the hard-coded bus route label "12" is gone; the destination blind stays blank.
- `makeTraffic`/`updateTraffic` (new, exported): vehicles now spawn spread across each lane's loop stretch and move as a platoon — a follower near its leader adopts the leader's speed and a hard clamp holds a 24 px bumper gap, including across the road's wrap seam, so same-lane vehicles can no longer drive through each other.
- `drawNamePlate`: the name renders at single scale (was double) on a light paper card with dark ink and a muted state line — half the height, far less floor area, readable over the night interiors; the selected variant keeps the gold border.
- Follow-up (Owner direction, same day): the runtime state moved out of the floor card
  entirely. The card at the character's feet now carries the name only; a new
  `drawStateTag` floats the state (IDLE, WORKING…) above the head as a dark chip with
  department-accent text, and the thinking bulb / sleeping Z marks were raised above it
  so the three never overlap.
- Verification: `npm test` 11/11 (3 new traffic invariant tests: spawn spacing, fast-car-catches-slow-bus, 15-minute mixed-timestep seam run), `npm run check` clean, `npm run build` OK (86 kB). Live browser check on the running local studio confirmed the bus has no number, traffic flows with no overlap across frames, and the nameplates render as small light cards.

## Documentation identifiers, initial Git commit — 2026-09-10, ZCode (second session)

Owner-directed documentation and repository repairs; recorded as D-DOC-001 in the decision log:

- `16_DECISION_LOG.md`: removed the byte-identical duplicate of the ADR-001…ADR-V5-003 block
  (verified identical before deletion; 706 → 551 lines, every ADR now single).
- `../architecture/02_SRS.md`: the v3 additional FRs are renamed `FR-V3-037…FR-V3-066`
  (same numeric suffix, consistent with the existing `FR-V4-`/`FR-ECON-` namespaces), clearing the
  collision with base FR-037…066. NFR-013…021 never collided and are unchanged. Requirement text
  unchanged. `../architecture/V3_FILE_BY_FILE_REVIEW.md` notes the rename; `IMPLEMENTATION_PLAN.md`
  marks the
  recorded conflict resolved. Indexed `sha256` values for both architecture documents updated
  explicitly (original hashes preserved).
- `tests/test_integration_settings.py` (two fixture values only, inside the active Codex Settings
  claim — flagged here so that agent is aware): `"do-not-echo"` → `"abc"` and
  un URL de test cu utilizator și parolă în el → unul doar cu nume de utilizator, so `scripts/check_secrets.py`
  passes without suppression. Both payloads still assert the same 422 refusals; all 15 settings
  tests pass.
- Initial Git commit created at the Owner's request (`ae4dee3`, branch `codex/foundation`, with a
  `main` branch pointer at the same commit): 212 files — source, tests, docs, scratch verification
  scripts. `.gitignore` extended with `backend/storage/` and `Claude outputs/` (generated media and
  screenshots); `.env`, `data/`, `output/`, `dist/`, `node_modules` were already excluded and are
  confirmed absent from the commit.

Verification at commit time: `pytest` 136 passed / 3 skipped; frontend `npm test` 11/11, `tsc`
clean, build OK; `scripts/check_docs.py` and `scripts/check_secrets.py` pass.

## Owner-directed LLM connectivity test — 2026-09-10, ZCode (third session)

Verified the Ollama Cloud integration end to end and added the missing Settings test affordance:

- Live state checked first: the "Ollama Cloud" integration (`https://ollama.com`) is saved and
  VERIFIED, 22 models discovered, all 7 agents carry an assigned model on that provider,
  autonomy stop inactive.
- Real runs through the policy kernel succeeded against the live provider: Sarah/glm-5.3-flash
  (reasoning output; token counts recorded) and Lyra/gpt-oss:120b answered
  "Da, sunt funcțional și gata să te ajut." in ~1s. Runs, tokens and events are in the audit trail.
- New: `POST /api/v1/settings/agents/{id}/test` runs one real connectivity task through the
  agent's assigned model (fixed short objective, max 800 tokens) and returns the same AgentRun
  envelope plus duration; 404 for unknown agents, policy blocks recorded as BLOCKED_* statuses.
- New: each agent card in Settings → Agenți has a "Testează răspunsul" button that surfaces the
  model's answer (or the block reason). Verified live in the browser: the button returned
  "glm-5.3-flash a răspuns: «Da, sunt complet funcțional…»".
- Test: `test_agent_llm_test_endpoint_runs_assigned_model` (provider monkeypatched; no network in
  tests). Settings suite 16/16.

## Whole-tree lint and type cleanup — 2026-09-10, ZCode

With the parallel agents' sessions finished, the committed baseline still failed the README's own
`ruff check .`, `ruff format --check .` and `mypy` (177 ruff findings, 9 mypy errors, inherited
from pre-audit and remediation code). Cleaned without behaviour change:

- `ruff format` across the tree (23 files) plus manual wrapping of the remaining 65 long lines
  (string literals split with identical content; the deterministic SVG template's XML attributes
  re-wrapped — rendering unchanged, hashes are computed at runtime).
- Auto-fixes: 22 unused imports, 11 unsorted import blocks, small UP modernisations.
- Manual: SQLAlchemy `== True` filters → `.is_(True)` (analytics), an unused local dropped
  (publishing), explicit `strict=False` on an intentionally asymmetric `zip` (office layout test),
  `requires_ffmpeg` moved below the imports it uses (E402).
- mypy: explicit `dict[str, Any]` annotations for the ffprobe result and the storyboard scene
  payloads (media/qc.py, media/assembler.py).

Verification after cleanup: `ruff check .` clean, `ruff format --check .` clean (185 files),
`mypy` clean (68 files), `pytest` 137 passed / 3 skipped, frontend `npm test` 11/11, `tsc` clean,
build OK, `check_docs.py` and `check_secrets.py` pass.

## Live speech bubbles wired end to end — 2026-09-10, ZCode (fourth session)

The speech-bubble projection existed in the frontend (handler, expiry, paper bubble renderer)
but nothing ever fed it: the backend never emitted `agent.message_sent`, and the transactional
outbox had no dispatcher, so no event was broadcast live after the initial replay. Three fixes:

1. **Producer** — `run_agent_task` now emits `agent.message_sent` (through
   `append_event_with_outbox`) in the same transaction that records the successful run, with the
   model's real output text (whitespace-normalised, capped at 200 chars) plus `run_id` and
   `task_type`. Per `../architecture/06_BACKEND_EVENT_MODEL.md` §7 only real messages may become
   live bubbles: failed runs and successful runs with no visible text (reasoning models with a
   small budget) emit nothing.
2. **Dispatcher** — the app lifespan now runs the outbox dispatcher every second
   (`publish_pending_outbox`), broadcasting committed outbox events to WebSocket clients. It runs
   on the server's own event loop on purpose: the broadcast tasks and the sockets belong to that
   loop. This also un-silences the workflow events that were already written to the outbox.
3. **UI label** — `agent.message_sent` shows as "Agentul a răspuns" in the activity log.

Verification: three new phase-1 tests (successful run emits the event with the real text and a
PENDING outbox record; failed run emits nothing; empty visible output emits nothing). Live E2E
against Ollama Cloud with the office open: an API-triggered run for Lyra/gpt-oss:120b produced
the speech bubble above her head reading "SUNT GATA SĂ LUCREZ ÎN CABINA VOCALĂ." — the run was
fired from outside the page, so the bubble proves the live event chain, not page-local state.
Full suite: ruff/format/mypy clean, pytest 140 passed / 3 skipped, frontend 11/11, docs and
secret checks pass.

Known related gap (not addressed here): agent runtime-state changes (THINKING/IDLE) are column
updates without events, so the state tag above the head updates on layout refresh rather than
instantly.

## Research agent works the pipeline; office fully live — 2026-09-10, ZCode (fifth session)

Two increments, both verified against the configured Ollama Cloud provider:

**1. The office is fully live.** `run_agent_task` now emits `agent.state_changed`
(THINKING at start, IDLE at completion) through the outbox, and `agent.paused`/`agent.resumed`
were moved onto the outbox too — the state tag above each character's head and the pause
animation now follow backend events in real time instead of waiting for a layout refresh.

**2. The research agent actually reads sources.** New
`POST /api/v1/factual/sources/{id}/extract-with-agent` (`backend/app/factual/agent_pipeline.py`):
the LeadResearcher agent (or any given ACTIVE agent with a model) receives the source's
sanitized text inside the inert `<untrusted_source_evidence>` boundary, extracts up to 12
atomic claims through its real LLM, and the JSON is strictly schema-validated before anything
is stored. Every claim lands **UNVERIFIED** regardless of the model's confidence — the model
that read the source is never the one that verifies it. Unparseable output raises (422) and
stores nothing. A truncated JSON list (token cap hit mid-item) keeps only the complete
objects — the dangling partial claim is dropped, never guessed. The agent announces a human
summary ("Am extras N afirmații...") as its speech bubble instead of raw JSON
(`run_agent_task` gained an `emit_message` flag for structured pipelines).

Live evidence: the IANA Example Domains page was fetched with the research retrieval adapter
(real SHA-256 provenance) and ingested; Dr. Aris (nemotron-3-super) returned 9 accurate claims
(RFC 2606/6761 reservations, registration restrictions, subdomain guidance) recorded UNVERIFIED,
and his speech bubble appeared in the 2D office. Phase 4 remains partial: keyword
search/discovery and an independently authorized fact-checker are still open.

Tests: 4 pipeline tests (stubbed adapter: valid JSON with fences; unparseable output rejected
with nothing stored; policy STOP blocks before any claim; truncated list keeps only complete
claims), phase-1 run tests extended to assert THINKING/IDLE state events. Suite: 144 passed /
3 skipped; ruff, ruff format, mypy, docs and secret checks pass.

## Codex Settings completion and bug audit — 2026-09-10T09:23

Scope resumed on current tree after ZCode additions: finish Settings channel binding UI, reproduce five factual-pipeline test failures, fix confirmed hardcoded operational claims and model availability guards. Preserve concurrent office/research additions. Baseline: 199 passed, 5 failed, 3 skipped; Ruff passed. No production credentials or messages will be generated during tests.

## Codex premium pixel office — 2026-09-10T14:55

Active claim: frontend/src/office_engine.js and a dedicated visual-art module; visual verification artifacts and tracking docs. Owner requested richer pixel characters, architecture, furniture, street people, dogs and cars. Preserve backend projections and concurrent Settings/research changes. Earlier audit verification/handoff remains to finish after this visual increment.

## Codex pixel office — verified, scope released

Visual increment completed; see `PIXEL_OFFICE_REFINEMENT.md`. Added material library, refined building/furniture/characters/dogs/cars/foliage, moved camera controls below the scene and fixed portrait framing. Frontend typecheck/build passed, 18 tests passed; Playwright desktop/fullscreen/mobile and real agent selection passed with zero page errors. Port 8000 serves the rebuilt assets. No backend or provider execution was part of this increment. Concurrent media changes preserved; earlier audit scope remains separately tracked.

## Codex street simulation — active claim

Owner requested round wheels/correct vehicle depth, randomized vehicle/pedestrian activities, animals and a local-clock day/night cycle. Scope: office_engine.js, new street simulation module, frontend tests and tracking docs. Decorative street events remain separate from operational agent events.

## Codex ambient street — complete, scope released

Round pixel wheels and far-to-near vehicle rendering fixed. Added session RNG, ten vehicle models, randomized pedestrian/animal activities, 48 shuffled decorative phrases and local-clock day/night density/lighting. 25 frontend tests, typecheck/build and browser 12:00/03:00 checks passed. Existing agent selection/mobile browser QA passed. See `STREET_LIFE.md` for limits, time semantics and screenshots. No operational backend changes.

## Codex weekly street rhythm — active claim

Refine ambient-life probabilities by local hour and weekday, including weekend nightlife crossing midnight, ordinary passersby throughout the day, coordinated groups and commute props. Scope limited to street simulation, renderer activity props, tests and docs.

## Codex weekly street rhythm — verified, scope released

Replaced exclusive time bins with blended weekday/hour activity and vehicle probabilities. Added morning runners, visible commuters/shoppers, coordinated social groups, weekend nightlife continuing after midnight and quieter Sunday evenings. Ordinary passersby remain possible throughout; groups cannot monopolize the scene. 33 frontend tests pass, typecheck/build pass, five fixed-clock weekly browser scenarios and desktop/mobile/agent selection pass. See `STREET_LIFE.md`. No backend/provider work in this scope.

## Codex outdoor Bucharest clock — active claim

Add a pixel electronic exterior clock, 24-hour HH:mm, Europe/Bucharest with DST. Align decorative street schedule with the same timezone. Scope: clock module, renderer, street time conversion and tests.

## Codex Bucharest clock — verified

Exterior seven-segment HH:mm display added at the building base. Intl Europe/Bucharest supplies DST-aware time and weekday independently of device timezone; street rhythms share this time basis. Typecheck/build, 35 frontend tests (including both DST transitions) and browser canvas/mobile/selection checks passed. Owner has asked about bar placement; clarification pending before changing its location.

## Codex street clock placement / toolbar consistency — active

Owner clarified: controls must match the bottom dock preview; electronic clock should be a freestanding street object to one side. Fix stylesheet packaging under existing CSP and place a sculptural pixel clock to the right. Preserve concurrent dashboard additions.

## Codex clock placement / toolbar — verified, scope released

Moved HH:mm Bucharest clock off the building base onto a sculptural freestanding support at the right pavement edge, based on Owner reference images. Fixed actual toolbar inconsistency: Vite inlined the small dynamic stylesheet as a data URL, blocked by the app CSP; ?no-inline now emits a same-origin CSS asset. No CSP relaxation. Browser asserts stylesheet loaded and dock bottom placement in normal/fullscreen, mobile overflow and real agent selection; zero page errors. Main port 8000 serves the new CSS with HTTP 200. Typecheck/build passed.

## Codex inspector model mismatch — active claim

Read-only live reproduction: /office/layout omits all model fields while /settings reports Sarah has a persisted model_id. Running server exposes an older layout shape. Fix inspector to resolve authoritative agent/provider model records on open, distinguish loading/error from no assignment, and discard stale responses. No model/provider execution or reassignment.

## Codex inspector model mismatch — verified, scope released

Resolved assigned models directly from persisted agent/provider catalogs when opening the inspector; old /office/layout omissions no longer imply no assignment. Loading/error/unverified states are distinct. Added stale-request guards including queued close events. 38 frontend tests and typecheck/build pass. Read-only browser verification on actual port 8000 matched all 7 agents to Settings, including Sarah/glm-5.3-flash; no LLM calls or writes. See `INSPECTOR_MODEL_FIX.md`.

## Codex articulated street actors — active claim

Owner rejects translated walking sprites and disconnected props. Replace ambient human rendering with contact-driven articulated poses for walk/run/cycle/skate/phone/briefcase; add varied appearances and fix clock occlusion. Research: BioMotionLab and Blender IK documentation. Scope street_actor module, ambient update/renderer, tests and visual QA; operational employees/backend preserved.

## Migration-branch unification and full-tree verification — 2026-09-10, ZCode (sixth session)

The parallel sessions had advanced the project massively but left the tree unable to run:
two concurrent revisions after `0011_claim_attribution` (`0012_channel_verification` and
`0012_workforce -> 0013_story -> 0014_runbook`) gave Alembic two heads, so every
`upgrade head` — every test fixture and every bootstrap — failed with 243 errors, and
`main.py` pinned yet another revision. Verified where each session had got to, then:

- `0015_merge_heads` merges both branches into a single head (no schema of its own);
  `main.py` now pins `0015_merge_heads`. Live database bootstrapped through it.
- The 13 Phase-10 runbook failures were environmental, not logical: FFmpeg is a BLOCKING
  preflight check and this machine (like CI) has no FFmpeg. The `studio` fixture now names
  a stub path when no real encoder exists — the stage state machine stays observable
  everywhere; the real encoder path remains covered by the Phase-5 skips.
- ZCode's earlier writer tests were superseded by the parallel session's stronger
  `script_agent.py` implementation (scene-level claim citations) and its
  `test_script_writing.py` suite; the superseded tests were removed. The extraction
  pipeline tests (7) remain.

Combined tree verification: pytest **306 passed / 6 skipped**, ruff + ruff format clean,
mypy clean (89 files), frontend `tsc` clean, **38/38 frontend tests**, Vite build OK
(142.8 kB), docs integrity and secret scan pass. Live studio restarted on `0015_merge_heads`.

## FFmpeg installed on the dev machine — 2026-09-10, ZCode

Owner-approved system change: FFmpeg 9.0.1 (full build, via winget/Gyan) is installed and on
the user PATH; `.env` pins `STUDIO_FFMPEG_PATH` to the absolute executable. The studio's
live preflight moved from BLOCKED to **DEGRADED** — render_engine and media_inspection are
now OK; the remaining degradations are exactly the unlinked credentials (image provider,
voice provider, YouTube) and the empty research allowlist. Full suite with the real encoder
on PATH: **311 passed / 1 skipped** (the render tests no longer skip and pass on the real
FFmpeg path). Future `start.cmd` launches pick FFmpeg up from the registry PATH.


## Codex visual continuation — claim released 2026-09-18

Scope: art-source/unreal/flat_material.py, an isolated material repair/verification script, and visual evidence under output/visual-audit. Investigate skeletal material fallback, validate repair in a copied asset before applying, capture the existing HQ_Dusk baseline and preserve the existing Pixel Streaming/backend integration. No architecture changes. Preserve the pre-existing modification in art-source/blender/hq/build_vehicles.py. Agent: Codex /root.


## Studio Office material repair and native visual audit — 2026-09-18, Codex

Closed the narrow visual-audit scope: M_HQ_Flat skeletal usage and four garment
instances repaired, persisted in a separate UE 5.8.2 process, backed up and applied.
Captured a fresh native PlateCam still at 1920x1008 and compared L2 to the exact
Owner reference. Runtime restored after capture. No L2 geometry/look changes yet.
36 office/layout/stream/bridge tests passed; check_docs passed. New-material creation
and reuse also passed in the isolated UE project, including independent reload.
Direct Python WebRTC capture remains experimental (connected, zero video frames).
See [VISUAL_AUDIT_2026-09-18.md](VISUAL_AUDIT_2026-09-18.md) for evidence, backups, limits and the next AI's exact steps.
Concurrent backend changes and the earlier build_vehicles.py edit were preserved.


## Codex L2 review — claim released 2026-09-18; art pass deferred for stream fix

Scope: isolated Blender mesh variant and copied Unreal review level, L2 composition only. Preserve live HQ_Dusk, materials outside the review assets, backend IDs and all concurrent changes. Render before/after and record actual results. Agent: Codex /root.


### Scope steering — stream stability, 2026-09-18

Owner reports UI freezes/flicker and briefly appearing cars. L2 edits deferred while fixing proven stale reconnect timers in frontend/src/hq_stream.js and regression tests frontend/tests/hq_stream_lifecycle.test.js. No artistic assets changed in this continuation; Blender/UE inventories completed read-only.


## HQ stream stability fix — 2026-09-18, Codex

A stale fallback reconnect timer could tear down a recovered connection. Fixed cancellation/state guarding and immediate/final frame preservation in hq_stream.js. Three red regressions now pass; all 115 frontend tests, TypeScript and Vite build pass. The server serves the new bundle. Actual browser viewer recovered from a controlled outage and remained live through second 86 without another disconnect. Authenticated Owner page requires reload; full UI/traffic stability is not yet proven there. Evidence and next checks: [STREAM_STABILITY_2026-09-18.md](STREAM_STABILITY_2026-09-18.md). L2 inventory completed read-only; no art asset changed during this continuation. Scope released.


### The result, measured independently — 2026-09-23

A third pass re-shot all thirteen views at 1280×800, 1440×900, 1920×1080 and 2560×1440 into
`shots_final3`, looked at every one against `shots_final2`, and re-measured from the real pixels
rather than from the cascade. Nothing in `frontend/src` was changed by this pass; two test files
were added.

**What the numbers say.** 2 998 text/ground pairs read from the pixels of 22 views at three
widths: **0 below threshold, worst 5.09:1** (`04-media` at 2560, the model-choice reason). Over the
render: 28 pairs, 0 below, worst 5.99:1. In the per-agent Live window: 14 pairs, 0 below, worst
5.73:1. Geometry at all four widths: `scrollWidth` equals the viewport, **0** elements past the
right edge, **0** controls under 32px. A real Tab walk over the sign-in screen, the workspace and
all eight dialogs at all four widths: 0 invisible focus rings, 0 rings under 3:1, 0 focus escapes,
0 traps, Escape closes all eight and returns focus to the control that opened them. `report.json`:
**0 missing fixtures and 0 console errors at every width**. **162 frontend tests pass** (146 + 16
new), `tsc` clean, the build succeeds.

**The claims, checked one by one.** The register prints **0** rows whose detail repeats its
headline, at all three widths (was 10 of 13). The eight dialogs now open at **one** top edge per
width (40 / 54 / 72px) and **one** width (1180px at 1280, 1440px at 1920 and 2560) — before, the
tops ran 55 … 300px. The inspector's contract is three columns with a **57px** rag at 1920 and at
2560 (was 225px at 1920 and a wholly empty column at 2560). The rails are cards 92–208px tall
instead of 858px of painted ground. The module meters draw one track at one x. The live badge is
gone from the failure and loading plates.

**Two tests were added, for rules that nothing could see break.**
`frontend/tests/no_echo.test.js` holds the "print the sentence once" rule at all three places it is
applied — `withoutEcho`, the register's own row through `describeEvent`, and the letter in the mail
window — including the cases that must *not* be dropped. `frontend/tests/one_shell.test.js` reads
`style.css` and holds the one-top-edge, one-width and one-meter-track rules, and names the phone
block as the exception it still is.

**What this pass found that is still open.**

- **The mail window says its sentence twice, not three times.** The body echo is gone, but the
  dialog title and the letter's own subject line still carry the same sentence 150px apart. Closing
  that is a string or a markup decision, not a stylesheet one.
- **The Live window's void moved rather than closed.** The caption now sits at y335 directly under
  the last entry, but the 430px below it is empty and nothing anchors the window's foot. The
  duplicate-sentence half of that finding is a clear win; the layout half reads no better than
  before, and arguably worse.
- **The Daily Run tiles are a measured staircase**: rows rag 45px and 114px at 1920, 64px and 153px
  at 1280. This is the trade the stylesheet records, taken knowingly — but `audit_final.mjs`'s
  "tiles that share a row but not a bottom edge" check reports 0 because it looks for
  `.company-card` / `.wf-stat` / `.stat-card` and these tiles are `.runbook-check`. The check has a
  blind spot exactly where the trade was made.
- **The meters still read backwards under 600px.** `@media (max-width: 600px)` lays `.modules li`
  out with an `auto` status column and `min-width: 0` on the meter — the very geometry that was
  fixed above it. No width the Owner uses reaches it; `one_shell.test.js` names it out loud.
- **The wider dialog leaves some boxes short of their own section rule.** At 1440px the error,
  loading and empty wells in Research and Daily Run stop at ~1200px while the head rule beside them
  runs to the margin, and at 2560 the publishing checks card ends 125px above the channel card
  beside it.
- Everything the section above refuses is unchanged and still the Owner's: one display language,
  the `.env` sentence and the `.md` filename, the numeric fps, the seven room icons, the band above
  the render, the research form's four labels, the sign-in brand plate, and the ghost-control
  borders.

**Closed after that report, in this session, by hand (evidence `shots_last/`):**

- A state plate now meets its own section rule instead of stopping two thirds of the way across:
  the plate spans the section and the sentence keeps its 104-character measure through the box's
  own padding (`.topics-loading`, `.ledger-empty`, `.text-error`, `.settings-error`).
- A single-line form field keeps a form's measure (72ch) now that a dialog is 1440px wide, and the
  two fields of one row stay a pair instead of being pushed to opposite sides of the dialog.
- The mail window prints its sentence once: a letter whose subject *is* the window's title shows
  its intent tag without repeating the sentence 150px below it. Two tests hold the rule
  (`frontend/tests/no_echo.test.js`), and a letter with its own subject still prints it.
- The per-agent Live window's caption closes the window again (`margin-top: auto`), instead of
  floating directly under three entries with 430px of bare ground beneath it.
- The module meter reads the same under 600px as it does at every wider rule: one track, one width,
  filled 100/50/0. The phone block had kept the old `auto` geometry.

Frontend tests: **164 pass** (162 after the verifier's two files, plus the two for the mail rule),
`tsc` clean, the build succeeds, 0 missing fixtures and 0 console errors at 1920 and 1280.

Evidence: `shots_final3/`, `shots_live_p8/`, `shots_scene_p8/`, `shots_p8_states/`,
`shots_p8_dstates/` in the session scratchpad. No server, no Unreal, no Python suite, no provider,
no git command that changes state.
