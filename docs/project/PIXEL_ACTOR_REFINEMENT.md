# PIXEL_ACTOR_REFINEMENT — completed locally, 2026-10-09

## Current correction: PIXEL_SEAT_ALIGNMENT — complete, 2026-10-09

The Owner asks «te rog sa ii asezi cum trebuie pe scaun!». Three new built-in imagegen
edits preserve faces/outfits/accessories while making the seated legs more upright and
less crouched. Current staff PNGs: staff-a-seated-v3.png, staff-b-seated-v3.png and
staff-idle-seated-v3.png. The two town atlases stay unchanged; the active set remains five
sheets/80 source frames. The older v2 staff sheets remain historical/recovery assets.

Every illustrated desk now has calibrated pelvis/seat and floor contact coordinates in
config/pixel_office.json. Per-frame hip landmarks in pixel_actors.json anchor the pelvis
rather than the head. Upper-body breathing keeps the hip contact fixed. Shins fit the
chair height while shoes retain their aspect and the floor anchor. Traced original
backrest/armrest/stool-front silhouettes replace broad background rectangles, avoiding
wall/table pixels erasing the body. The Director's angled chair, Voice Artist's low chair,
Video Editor's higher chair and two wooden stools are calibrated separately. No furniture
or building raster is repainted. Reserved backend slots/desk IDs/original x/y stay fixed.

The running backend still has its preceding visual config. setLayout keeps those reserved
slots and desk metadata while applying current calibration to matching unchanged desks;
a real browser regression reproduces this situation. No backend restart was required.

All 48 posed combinations (eight staff × rest/work/think/review/sip/stretch) were visually
reviewed in seated-poses.png, plus detailed original/before/after chair boards. Tests reject
frames containing neighbouring figures and invalid hip bounds. 859 frontend units, types,
three bounded browser checks and 53 scoped backend/layout/weather/docs pass. Two temporary
docs failures caused by losing historical audit dates in active_task were corrected; the
regression tests were retained. Registration reproduces byte-identical current metadata.

Final actual UI at 08:30 Europe/Bucharest, cloudy 11°C: all eight actual IDLE employees use
the current seat contacts and masks and visibly animate; road moves, zero page errors,
no duplicate Canvas name or hover box. The final live video is 16.000 s, 1700×1006 H.264
encoded at 12 fps (not a measured UI benchmark). Frames at 1 and 13 seconds were inspected.
Served page/CSS/JS/build record/background and the five active PNGs match disk; source hash
matches launcher build. Foundation readiness remains 200 HEALTHY. An intermediate earlier
recording failed the elapsed-motion criterion; repeated diagnostic and final recordings
passed without relaxing the lifecycle/data guards. Full production workflows remain separate.

Five original generations + three seating edits = eight built-in imagegen calls in this
visual task. No production RunPod/media/model job, upload, policy/database command or
server restart was initiated. Current proof: data/pixel-actors-2026-10-08/verification.json.
The preceding evidence is preserved in refinement-verification-before-seating.json.

Modified by this correction: pixel_actor_atlas.js, pixel_people.js, pixel_desks.js,
pixel_office.js, both pixel config JSONs, pixel_actors.test.js, pixel_life.spec.js,
three seated-v3 PNGs, prompts and register_staff_frames.py. Backup before calibration:
data/pixel-actors-2026-10-08/before-seat-alignment/. Restore only task-owned differences
and rebuild the combined sources; preserve concurrent changes and old weather/navigation.

New original outputs under C:/Users/mario/.codex/generated_images/01a117b7-74db-7ad3-a99b-9e6a0194302e/:

| Current PNG | Built-in imagegen output | SHA-256 |
|---|---|---|
| staff-a-seated-v3.png | exec-64e06ca7-bfd5-4ad1-8800-77c712f1cc4a.png | ad2c41a290db8cf4b16f6c8ac0ca81602194b4ed0121215437c9619bcd868c88 |
| staff-b-seated-v3.png | exec-92d6547c-ec04-4eff-809f-7b3851e2b5f5.png | 6959d06530f71537b154b9af7a38faafa6c6975510a0f47c9dceb0d8a62c8099 |
| staff-idle-seated-v3.png | exec-70600753-698f-472a-b584-ec76052a85a3.png | 2caa787bca862a179ab5add0f5dacf8acbb1a48da070ec8dc736ed784f9b575b |

All PNGs remain unchanged RGBA originals, 1254×1254. The correction uses the project's own
staff sheets and chair reference board, not game artwork. Generation service terms apply;
exclusivity is not claimed. Exact prompts: art-source/pixel/actors-v2/*v3-prompt.txt.
The registration entry point delegates to register_staff_frames.py for the current v3 set.
Earlier descriptions and evidence below are historical and superseded by this section.

The Owner rejected the first actor study as crude and asked for substantially more effort.
The current served page uses five new original transparent sprite sheets, with detailed
faces, clothing folds, hands, feet, accessories, bicycle geometry and pet anatomy. The
approved building/furniture illustration is byte-identical; eight personal seats and menus
remain in place. This completes the local visual refinement, not external media acceptance.

## Artwork and movement

80 drawn source frames: 16 pedestrian frames (four identities/four poses), four cyclist
frames, eight cat frames, four dog frames, 32 seated employee/state poses and 16 employee
cup/stretch poses. Walking and pedalling use four drawn keyframes held across eight timing
ticks, not eight separate drawings. Two cats walk, sit, groom and stretch on continuous
routes; grooming/stretch poses have a small body movement. A leashed dog trots with its
walker. Rain adds original drawn umbrellas; the street clip accommodates the canopy/feet.

Staff use their actual employee_id and the Character Bible appearance. Sarah, Aris, Elena,
Marcus, Lyra, Kael, Vera and Nadia keep their distinctive outfits, hair and accessories.
IDLE can breathe, sip and stretch; WORKING, THINKING and REVIEWING choose their own drawn
postures with small upper-body/arm movement. Faster forearm taps do not move the head. Furniture pixels occlude the middle of the
body; raised hands and side arms appear in front of the chair. Feet stay at the seat anchor.
PAUSED/BLOCKED/ERROR/UNKNOWN are still. Hidden/parked/replay/reduced-motion/stale-data guards
freeze cosmetic time. No decorative actor writes agent status, progress or workflow events.

New/hired staff or changes to the Bible's skin/clothing/hair/accessories use the original
code-drawn fallback instead of silently showing a stale generated identity. Failed or
wrong-sized sheet loads also preserve that fallback. Five decoded local sheets are cached
once; source transparency is retained, and runtime uses nearest-neighbour Canvas drawing.
The detailed building raster and generated sheets are not permanently edited by Python.
The registration helper only reads alpha and writes numeric frame bounds/anchors.

## Files

- frontend/src/pixel_actor_atlas.js: local image loading, identity checks, frame registration,
  state/idle selection, fixed-foot compositing and foreground clipping.
- frontend/src/pixel_art.js, pixel_town_people.js, pixel_seated_art.js: original bounded
  code-drawn fallback art and reusable integer drawing helpers.
- frontend/src/pixel_people.js, pixel_life.js, pixel_office.js: existing scene integration.
- config/pixel_actors.json: source hashes, bounds, sizes and eight appearance bindings.
- config/pixel_office.json: sidewalk/second-cat settings; desk/building geometry preserved.
- frontend/public/assets/pixel/*-v2.png: five generated originals, provenance below.
- art-source/pixel/actors-v2/*.txt: exact generation prompts; register_frames.py reads
  the original PNGs and reproduces identical registration/identity metadata (verified).
- frontend/tests/pixel_actors.test.js, tests/fixtures/pixel_actors_bible.json and
  tests/e2e/pixel_life.spec.js: real raster/state/lifecycle and asset/identity checks.

## Verification

859 frontend unit cases, TypeScript, three bounded Canvas/browser checks and 53 scoped
backend/layout/weather/docs cases pass. The atlas integration test uses all five real PNGs
and eight Bible identities in IDLE/WORKING/THINKING/REVIEWING fixture states. It checks visible
pixel changes for every employee, moving traffic and all existing lifecycle guards.
The initial regression (one agent's breath disappearing at display scale) was caught and
fixed; the assertion was retained. Assets' dimensions, RGBA type, hashes and frame bounds
are verified. Unknown/recoloured staff use the fallback.

Actual read-only UI verification on 2026-10-09 at 07:54 Europe/Bucharest: cloudy 10°C,
eight actual employees IDLE, visible raster changes for all eight, moving street, no page
errors, one native name/state tooltip and no duplicate Canvas label/character rectangle.
All five served PNGs match the originals byte-for-byte; served page/CSS/JS/build record and
background match disk. The launcher build record matches the current source hash.
/health/ready returned 200 HEALTHY with no problems (foundation health scope).

Evidence: data/pixel-actors-2026-10-08/verification.json, live-ui-verification.json,
live-studio-actors.png, actors-study.png, preview/life-test-gestures.png and studio-actors.mp4.
The folder keeps the task's start date; verification took place on October 9. The MP4 is
15.916 seconds, 1700×1006, H.264 at an encoding rate of 12 fps; this is not a measured UI FPS
benchmark. Its source records the actual live Canvas after login. Representative frames at
1/7/13 seconds were visually inspected. The separate board and simulated states are fixtures.

No server restart, production policy/database command, RunPod/model/media generation job or
publication was initiated by this task. The built-in image generator was used five times
for the local art. Concurrent RunPod/local-entry changes remain in the combined build.
The existing Vite >500 kB chunk notice remains; no missing art or page error was observed.
Full Owner workflows were not rerun here; earlier guard/external acceptance limits remain.

## Research, source and rights

Official game screenshots were inspected for human proportions, selective contours,
clothing and small-town atmosphere:
https://store.steampowered.com/app/1201270/A_Space_for_the_Unbound/
A bicycle/street gameplay image was also inspected in the browser:
https://gaming-cdn.com/images/products/8637/screenshot/a-space-for-the-unbound-pc-juego-steam-wallpaper-1.jpg?v=1743512062
Neither screenshot nor any game art was downloaded or redistributed in the product.
Generated assets follow the generation service terms; copyright exclusivity is not claimed.
Exact prompts are in art-source/pixel/actors-v2; hashes/registration are in pixel_actors.json.

| Project PNG | Original built-in imagegen output ID | SHA-256 |
|---|---|---|
| town-walk-v2.png | exec-5f99d674-5ef8-4b68-a9a9-49f11355b4ef.png | e96edca9fd853de35aac21ff157e73ee52b7368e8481aa602d8f4d0daca6313b |
| town-cycle-pets-v2.png | exec-d1d94fb4-79a4-411f-97ec-3b5a366ab6fb.png | 95488858189a92107181bf2a24f89075e511d90340d5749a98afce28b366f60a |
| staff-a-v2.png | exec-dac8d351-304c-4625-ba70-4ccda116d2c8.png | bf53fb6bcfc6cfd00aac19e5781e677f2e73de2478ae7dbb8bcead182b225fca |
| staff-b-v2.png | exec-ea2975c9-e068-4d6e-8e76-8a45a4433c3e.png | ed7456047cb224ea3dc67fdffa47e9ce5647c64d6bdbda736e9f94279520d65a |
| staff-idle-v2.png | exec-0b1f9cef-8aaa-470e-881f-48c985a310dd.png | c94ec9bb5e5f87e8c449660c3524c9a3e62a0f96d7e58f442fcc4d5c739370c2 |

Original outputs are under
C:/Users/mario/.codex/generated_images/01a117b7-74db-7ad3-a99b-9e6a0194302e/.
Each PNG is an unchanged 1254×1254 RGBA output. Tiny near-transparent fringe pixels retain
the original alpha and are effectively transparent in Canvas; no raster cleanup was applied.

## Rollback and next work

Baseline source copies are in data/pixel-actors-2026-10-08/before. Restore only the task-owned
changes, remove this task's new modules/config/assets as appropriate, then build through
scripts/start.py's build_frontend helper. Preserve unrelated edits and the preceding
weather/navigation/one-tooltip work. before/served-dist.zip is historical evidence; restoring
it blindly could undo concurrent changes. The server need not restart for static art.
The current user action is Ctrl+F5 at http://127.0.0.1:8000/. External RunPod setup and normal
serial/media/upload acceptance remain tracked separately.
