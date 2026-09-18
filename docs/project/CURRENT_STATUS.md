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
one `owner_approval_request` for `publishing.public_publish` instead of uploading; AUTONOMOUS_CEO
publishes under the channel's policy as PUBLISHED_SIMULATED, private, with no request raised.

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
the suite at **1152 passed, 1 skipped** (2026-09-18, 9m48s), finding no defect to fix. The migration chain is 0040 → 0043 and `main.py` pins it: 0041 and
0042 were reserved by two of the implementers and neither needed a schema change. No provider was
called, nothing was rendered outside FFmpeg on this machine, no run was queued and no credit was
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
honestly reported as drawn from the words. **The Owner cannot answer an approval**: a SUPERVISED day
writes exactly one `owner_approval_request` for the upload and stops there honestly, there is no
route to approve or refuse it, nothing consumes an APPROVED row and no stage re-attempts after one
appears; `owner_approval_request` is also not yet in `maintenance.HISTORY_TABLES`, so a reset does
not clear it. 51's acceptance criteria and burn-in are not checked and cannot be from this database,
so the promotion refusal names them to the Owner instead; 51's department-scoped autonomy is not
implemented — the column is one global mode — and the `Literal["False"]` switches on `PolicyView`
(`external_payments_enabled`, `autonomous_firing_enabled`, `provider_auto_switch_enabled`,
`world_generation_enabled`) are still constants beside tiers that now reason about the same acts.
`backend/app/media/router.py` is still measuring films without the picture check and rendering
without the chain or the reference, so the Owner's manual render and his manual QC behave as they did
yesterday while the daily run does not. The character check reads the storyboard's
`character_ids_json`, which only `serial_storyboard.py` fills — a factual film records
`character_ids_json=[]`, so the record says `no scene in this film lists a character` rather than
passing — and the Director's `gather_facts` still filters the QC report to keys starting with
"measured", so the per-scene verdicts do not reach her prompt. The Director's `frames_for` cuts at
most eight frames, so a ninth scene onwards is recorded `no frame was cut for this scene`, never
looked at and never passed. The reference set uses the first filled slot for every scene rather than
choosing by shot type, and there is no frontend: no button produces a reference set, no page shows
which slots are filled, and nothing in `frontend/src` reads `autonomy_mode` yet. The research stage's
mode refusal is coarse — under MANUAL the whole fetch is skipped including `retest_stale_hosts`, so a
MANUAL studio's host record goes stale — and a stage the mode skips is recorded in the run and the
day's summary but nobody writes the Owner a letter about it. `approval_expires_after_hours` stays the
module constant `APPROVAL_EXPIRES_AFTER_HOURS = 24` in `services.py` rather than a key in
`config.py`, because a key nothing reads is a lie about what is configurable.

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
the books is ESTIMATED or DOCUMENTED. The one question the closure left open was answered in its
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

### Ce are Owner-ul de făcut

Numai Owner-ul poate face lucrurile de mai jos; studioul nu le face singur și nu le cere de două ori.

- **Migrarea bazei de date live**: `scripts/bootstrap.py` aduce baza la `0043_autonomy_mode`
  (0039 economia, 0040 cercetarea, apoi 0043 modul de autonomie; 0041 și 0042 au fost rezervate în
  faza D/G și nu au fost folosite, pentru că nimic din ele nu avea nevoie de o coloană nouă).
  Corectat 2026-09-18: până atunci rândul de aici cerea `0040_research_sources`. `main.py` cere
  această revizie la pornire, deci migrarea se face înainte de prima pornire pe versiunea aceasta.
  Niciun test nu atinge baza live.
- **Bugetele** (`PUT /economy/budget`, biroul Contabilitate): zilnic, săptămânal, lunar. Nimeni
  altcineva nu le poate pune — Contabilul doar escaladează, nu aprobă. Fără un buget, rezervarea
  ține banii, dar nu are de ce să refuze.
- **Prețurile planului** (`PUT /economy/prices`): ce plătește în realitate pentru ElevenLabs,
  Ollama Cloud și Runway, pe model sau `*` pentru tot felul. Până atunci cărțile văd o fracțiune
  din zi: rularea unui angajat rămâne fără cost, iar narația se prețuiește doar după lista publică
  ElevenLabs, marcată DOCUMENTED, care nu este planul lui.
- **Un motor de căutare** (Setări → *Conexiuni* → „Căutare web (API JSON)"), dacă vrea ca studioul
  să găsească pagini și pe site-urile fără adresă proprie de căutare; și **site-urile autorizate**
  (`PUT /sources/allowed-hosts/{host}`). Lista nu poate fi lărgită de niciun agent, de nicio cerere și
  de niciun rezultat al motorului: motorul numește adrese, studioul păstrează doar ce este pe lista
  lui și citește el însuși pagina.
- **Politica de publicare pe canal** (`POST /publishing/channels/{id}/publish-policy`):
  vizibilitatea, întârzierea, `public_publish_enabled` și dreptul Directoarei de a aproba episoade.
  Fără dreptul acesta, un episod trecut de Directoare rămâne DRAFT și așteaptă mâna lui.
- **Ceasul**: activarea lucrării `daily_main` din panoul zilei — actul lui înregistrat
  (`workflow.job_activated`) — și instalarea sarcinii Windows („AMN-AI Studio",
  `scripts/install_studio_service.ps1`), cu confirmarea o singură dată în `data/studio-service.log`
  că o autentificare S4U deschide cheia. Până atunci lucrarea zilei stă adormită, după regula lui:
  generarea video costă bani și se face numai după ce totul s-a dovedit.
- **Plafonul de jetoane pe zi** (`STUDIO_AGENT_DAILY_TOKEN_BUDGET`), dacă vrea unul: 0 înseamnă
  fără plafon, așa cum a mers studioul până acum. Peste el, rularea este oprită BLOCKED_BUDGET și
  Contabilul îi scrie o dată în ziua aceea.
- **Seturile de referință ale personajelor** (`POST /media/characters/{id}/reference-set`, adăugat
  2026-09-18): cele cinci sloturi — portret, corp întreg, față, profil, spate — sunt goale în orice
  studio care a rulat vreodată, așa că fiecare imagine a unui personaj este până acum o invenție
  nouă, iar verificarea imaginilor nu are cu ce compara. Ruta consumă credite de imagine, deci este
  actul lui și al nimănui altcuiva: niciun pas al zilei nu o cheamă, iar un test ține asta. Un
  personaj cu înfățișarea blocată și fără referință citibilă refuză filmul, în loc să i se inventeze
  o față. Nu există încă buton în interfață; ruta răspunde cu sloturile umplute, cele refuzate și
  costul (`usd: None` dacă modelul nu are preț).
- **Modul de autonomie** (`POST /api/v1/owner/autonomy-mode`, migrarea 0043): MANUAL, SUPERVISED sau
  AUTONOMOUS_CEO. Coloana a fost scrisă pe AUTONOMOUS_CEO pentru că asta face codul de luni de zile,
  nu ca o promovare — comanda este singura care ridică modul și refuză ridicarea cât timp autonomia
  este oprită sau un incident este deschis. MANUAL înseamnă o zi care scrie, dar nu cumpără cadre și
  nu urcă nimic; SUPERVISED filmează ziua și îi lasă o cerere de aprobare în loc de urcare — dar
  deocamdată **nu are cum să răspundă la ea**: ruta de aprobare nu există încă, deci SUPERVISED este
  un mod care pune întrebarea și nu aude răspunsul. Pragul peste care o randare plătită devine
  decizia lui este `paid_generation_approval_threshold_usd` (5 USD implicit).
- **Furnizorii de rezervă aprobați** (`approved_fallbacks`, pe nivelul de politică al canalului, al
  seriei sau al storyboard-ului; pentru un personaj blocat, lista din `approved_fallbacks_json`
  scrisă de o schimbare de identitate APROBATĂ): fără ei, lanțul are un singur vendor și o scenă
  refuzată cade pe cartonul de rezervă pe care QC îl oprește de la publicare. Aprobarea este dovada
  că tehnologia păstrează personajul recognoscibil, deci nu o poate da studioul; lanțul rămâne oricum
  de cel mult o alternativă pe scop și pe scenă.
- **Reconstruirea interfeței** (`npm run build --prefix frontend`): ecranele schimbate pe
  2026-09-18 — starea site-urilor în *Cercetare → Surse*, banii ținuți în biroul
  Contabilitate — sunt în sursă, nu în pachetul servit. Construirea este actul lui de
  lansare; niciun agent nu a construit și nu a pornit serverul.

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
safe mode, the autonomy stop set, a person looks.

**The clock re-attempts a day that could not run.** A clock-fired run is skipped only when
the date already has a run that did work (COMPLETED or PARTIAL) or `STUDIO_DAILY_MAX_ATTEMPTS`
(3) is spent; a BLOCKED preflight or a TRANSIENT failure queues attempt n+1 under the
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
outlives its date skips itself, and a HARD fault opens safe mode and is not re-attempted. Of
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
