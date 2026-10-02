# Video Production Pipeline v3

## Main channel pipeline

1. Idea
2. Research
3. Claim extraction
4. Fact verification
5. Script
6. Hook
7. Storyboard
8. Asset plan
9. Image/video generation or licensed sourcing
10. Voice
11. Captions
12. Deterministic edit
13. Technical QC
14. Factual QC
15. Rights/policy QC
16. Publish

## Office serial pipeline

1. Prior-day DailyStudioLog
2. Continuity snapshot
3. Showrunner
4. Event-grounding validation
5. Story script
6. Storyboard
7. Character-consistent asset production
8. Voice
9. Edit
10. Technical/continuity QC
11. Publish to separate channel

## Media provider abstractions

### VIDEO_PROVIDER
Must represent actual provider semantics.
Possible:
- create_generation
- poll_status
- fetch_result
- cancel if supported
- estimate_cost
- capabilities
- health

### IMAGE_PROVIDER
- generate
- reference/edit if supported
- capabilities
- fetch result

### TTS_PROVIDER
- synthesize
- voice availability
- capabilities

Unknown/unsupported methods must not be faked.

## Character continuity

Live 2D office should prefer deterministic assets/sprites.

Serial can use generated video, but must use Character Bible references when supported.

If provider cannot preserve a character adequately:
- use deterministic 2D/cutout animation;
- change provider;
- or fail continuity QC.

## Editing

Prefer FFmpeg for:
- trim;
- stitch;
- crop;
- 9:16;
- audio mix;
- captions;
- normalization;
- transitions;
- final encode.

Use safe subprocess invocation.

## Asset rights

Each asset:
- source/provider;
- rights/license status;
- generated/reference provenance;
- content item association.

Unknown rights can block public use.

## QC categories

Technical:
- file valid;
- aspect ratio;
- duration;
- audio;
- captions;
- encoding.

Factual:
- script claims map to evidence.

Visual:
- no severe character drift;
- no wrong employee;
- no wrong historical office state.

Policy/rights:
- assets usable;
- synthetic/real representation not misleading.

## Cost

Before expensive generation:
- estimate;
- reserve budget;
- generate;
- reconcile actual cost.

Retries have a maximum spend.

## Render graph

Represent production as a render graph, not one opaque "make video" call.

Track:
- scene assets;
- audio segments;
- timing;
- captions;
- music;
- overlays;
- transitions;
- final assembly.

A failed scene can be regenerated without restarting the entire video.

## Audio specification

Define configurable targets:
- sample rate;
- loudness target;
- peak limit;
- background-music ducking;
- silence trimming;
- pronunciation dictionary.

Store pronunciation exceptions for recurring names/terms.

## Caption specification

Validate:
- transcript match;
- timing;
- safe margins;
- readable line length;
- font/license;
- no critical visual obstruction.

## Visual factual consistency

Fact-check not only narration.

A storyboard/visual can create a false implication even if script is accurate.

QC should detect where feasible:
- wrong planet/location/person/object;
- wrong scale/category;
- synthetic visual presented as real;
- historical-era mismatch.

## Deterministic fallback format

If premium video generation is unavailable or inconsistent, the studio must have a publishable fallback:
- 2D motion graphics;
- still-image parallax;
- kinetic typography;
- stock/licensed visuals;
- deterministic character animation.

Autonomy must not depend on one generative video vendor.

## Render provenance

Final render records:
- asset hashes;
- editor/version;
- FFmpeg command parameters;
- subtitle version;
- audio version;
- checksum;
- duration;
- dimensions;
- QC version.

## Generation quality budget

Set maximum regeneration attempts per scene and per video.

If repeated generation fails:
- simplify scene;
- switch provider;
- use deterministic fallback;
- or block.

## Paid staircase (amended 2026-10-02)

Amended deliberately on 2026-10-02 after the production-readiness audit (finding AR-13). Since
2026-10-01 a real film is bought only through this staircase: the old whole-film render refuses a
real paid adapter, and quality control fails a render started on or after 2026-09-26 that was
filmed from template prompts in PRODUCTION or bought whole inside the render
(`production_path_qc`). Everything below is code with tests in which every vendor is faked
(proven on fakes only). The last real paid film, the Nepal film of 2026-09-26, was bought on the
old path, cost over 1,000 Runway credits and failed QC; the first capped paid film under
`EVERY_PAID_STEP` is the real test of this section.

1. **Shot plan.** The model writes the shot plan (`media.prompt_agent.write_shot_prompts`): strict
   parse, one repair, one re-ask. A film without a usable model plan waits `NEEDS_SHOT_PLAN` and is
   asked again at most once a day on two days; it is never filled with template prompts.
2. **Shooting sheet** (`media.shooting_sheet`). Per scene: the prompt written for its model; a lint
   that blocks enum codes, hex colours, forbidden faces, charts sent to a photo model and
   over-long prompts before a price is shown; the cheapest capable model per scene (premium only
   for the hook; the Owner's override wins); seconds, credits and USD; and each step's credit cap.
   The sheet has a `plan_hash`; a yes is bound to that hash, its step and its cap, and spent once.
3. **Gates before any purchase.** One buyer per film (`film_purchase_lease`, `FILM_BUSY`
   otherwise; a repeated press with the same `command_id` replays the stored answer); the step's
   cap reserved against the budget (purpose `sheet:<step>`), settled when booked and released when
   nothing was spent; the film ceiling (`film_budget_usd`, `OVER_FILM_BUDGET`); a free-disk floor
   on the media root (`STUDIO_MIN_FREE_GB`, `LOW_DISK`); then `may_act` with the `plan_hash`
   (51_AUTONOMY_MODE_SEMANTICS).
4. **Stills** (`media.stills_purchase`). Candidates per scene, each judged automatically by the
   stills gate. A scene that shows a locked serial character sends the character's reference
   picture first and the film's look second; a locked character with no reference is refused
   `NEEDS_REFERENCE` before anything is bought.
5. **Hero test shot** (`media.test_shot`). One motion clip of the hook scene, checked by clip QC.
   The rest of the motion follows only through `hero_gate` (51).
6. **Motion** (`media.motion_purchase`). Image-to-video per scene on its own model, under the cap.
   Clip QC checks every paid clip (a motion floor per camera move, YuNet faces on the first, middle
   and last frames, cut spikes, the vision judge) and buys at most one retry (seed+1, a firmer
   prompt) inside the approved cap. A failed clip is REJECTED and never assembled.
7. **Takes, intent and recovery** (`scene_take`). Every purchase is a take keyed by its identity
   (`prompt_hash` over the words, the model and the reference picture), so one identity is never
   bought twice. The request is written `SUBMITTED` with the vendor's task id before any poll. A
   clip or still that did not arrive stays `SUBMITTED` (in flight, never to buy) and is collected
   later by GET only, by the next step or by the watchdog; past 24 h it becomes `LOST` with one
   letter. A submit that may have been charged without an answer counts against the cap, is
   recorded `VENDOR.UNANSWERED` and is never sent again automatically. Only Runway's documented
   "may retry" statuses (429, 502, 503, 504) are resent on a billed POST. A paid but unjudged take
   is judged (0 media credits) before anything is bought.
8. **Per-scene failure memory.** A scene the gate sent to the Owner, refused for safety, lost,
   left unanswered, or that reached `max_paid_attempts_per_scene` (default 3) paid attempts is
   held `NEEDS_OWNER` and never bought again until his own act lifts it (a model change, a
   decision on its takes, a redo he approved, or new words).
9. **Booking.** Each purchase is booked once under its own reference (the step, the film, the
   `plan_hash` and the run's correlation; `redo:{film}:{kind}:{scene}:…` for a redo). A step that
   fails after paying is booked from the measured balance drop, raises `SpentStageError` (a HARD
   fault, never retried) and writes the Owner a letter.
10. **Assemble.** Narration bought per scene and kept as a `narration` take (reused, never bought
    twice), its silent edges trimmed to a 0.12 s breath, stitched with the neighbouring words for
    a voice that accepts it; captions on the voice's own clock, lit word by word; the film graded
    toward its first filmed scene; free second framings (punch-ins) inside long scenes; a closing
    card instead of a black ending; a music bed and ambience only from the Owner's licensed
    library (`config/music_library.json` or `STUDIO_MUSIC_LIBRARY`; each entry needs
    `commercial_ok`, a licence and a matching SHA-256), the bed ducked 20 LU under the voice;
    the premium master: 24 fps, x264 High CRF 17, -14 LUFS with a true-peak limiter.
11. **QC and repair.** Technical, rights (a per-component licence ledger: a film is LICENSED only
    when every still, clip, voice, font and track carries commercial-use evidence, otherwise
    NEEDS_REVIEW, which publishes privately only), audio mix, editorial (advisory unless the Owner
    makes it blocking) and production-path checks. A failed film is repaired free first
    (re-encode from the takes, card recompose, sound remaster), then by capped paid scene redos
    (`film_max_paid_redos_per_scene` 1, `film_max_paid_redos` 2), each a priced plan behind
    `media.scene_redo`.
12. **Cover.** A 1080x1920 cover from the hero still and the hook, composed locally (0 credits).

The "Generation quality budget" above is met by items 7, 8 and 11.
