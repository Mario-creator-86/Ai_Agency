# Original pixel studio assets — 2026-10-08

## Current original town vehicles v6 — 2026-10-09

town-cars-v6.png: original 1536×1024 RGBA sheet, four independent detailed vehicle profiles.
Two built-in imagegen calls: original art plus transparent extraction; the rejected opaque
draft stays in art-source only. No third-party/game artwork copied. Source originals, exact
prompts and applicable provider-output terms: art-source/pixel/street-vehicles-v6/README.md.
Uniform scaling and registered wheel hubs; original PNG copied byte-for-byte. Body/tyres
remain fixed while hubs rotate. Cars change only beyond the scene edge. Current humans and
chair ensembles use a central 0.9 world scale; town walk/pet PNG bytes remain unchanged.
Proof: PIXEL_STREET_REFINEMENT.md; hashes/registration: config/pixel_actors.json.

## Current integrated person-and-chair v5 — 2026-10-09

Active employee assets: staff-a-chair-v5.png and staff-b-chair-v5.png. Each employee has their
chair or wooden stool included, coherent anatomy, one uniform scale and floor anchor.
Production uses stable first ensemble + small continuous joint motion. Other authored
state poses are source variations, not animation frames. The older seated-v3 description
below is historical and superseded. Town walk/pedal/pet sheets remain unchanged.

studio-chair-cleanplate-v5.png is a generated edit removing the eight empty chairs; runtime
uses only traced chair silhouettes from it. The approved studio-detailed.png remains the
unchanged background. Failed/mismatched art retains the original furniture/code fallback.
Source IDs, provider-output terms and all seven prompts:
[chair-ensembles-v5/README.md](../../art-source/pixel/chair-ensembles-v5/README.md).
Registration, tests and actual proof: PIXEL_CHAIR_ENSEMBLES.md; hashes: config/pixel_actors.json.

## Current seated-v3 correction — 2026-10-09

Active staff art: staff-a-seated-v3.png, staff-b-seated-v3.png, staff-idle-seated-v3.png.
Three original built-in imagegen edits of the earlier own sheets, referencing the existing
chair board for seated anatomy only. Source IDs/hashes/prompts and generation terms are
recorded in PIXEL_ACTOR_REFINEMENT.md. The v2 staff sheets below are historical/recovery.
The town sheets remain active. No game art copied; PNG originals remain unmodified.
Numeric pelvis landmarks and original furniture silhouette clipping fit the eight desks.
48 fixture poses and actual current-seated UI/video were inspected. register_frames.py
now delegates to register_staff_frames.py for the current v3 asset set.

## Detailed original actor atlases — verified 2026-10-09

Supersedes the procedural-only character description below for the current eight staff.
Five unchanged 1254×1254 RGBA built-in imagegen outputs live in frontend/public/assets/pixel:
town-walk-v2.png, town-cycle-pets-v2.png, staff-a-v2.png, staff-b-v2.png, staff-idle-v2.png.
80 drawn frames: four town identities, cyclist, cats/dog, eight state/idle employee poses.
Character Bible appearances are bound by employee_id and all relevant appearance fields;
unknown/changed identities or image failures retain the original code-drawn fallback.
The seated world footprint stays at the existing personal desk anchor with chair occlusion.
The upper-half drawing is also used for the inspector thumbnail.

Original generated source IDs, hashes, visual references, exact prompts, generation terms
and rollback are in PIXEL_ACTOR_REFINEMENT.md and config/pixel_actors.json. Prompt files are
in art-source/pixel/actors-v2/. No game asset was downloaded, copied or redistributed;
exclusivity of generated art is not claimed. Registration reads original alpha for numeric
bounds only. The approved building raster is unchanged. Current-source static page/art and
actual eight-agent motion were verified in the real UI; fixtures separately cover states.
The earlier procedural descriptions and counts below remain historical.

## Living city and desk gestures — 2026-10-08

Original procedural pixel actors in frontend/src/pixel_life.js: pedestrians, cyclist,
car, cat, birds and evening moth/window details. Original hands, paper, pencil, cup and
headset gesture frames extend pixel_people.js. No external sprite/animation pack or asset
download; these authored drawings remain project source. Existing illustration unchanged.
pixel_sky.js moves cached contours from that same illustration; no new background asset.
Workstation/editor research informs gestures only; primary sources are in PIXEL_STUDIO_LIFE.md.
Actual backend modes/lifecycle remain authoritative; atmospheric actors never emit work events.

## Reference research

The Owner requests an environment and agents inspired by *A Space for the Unbound*.
The publisher page and its screenshots were inspected:
https://www.togeproductions.com/project/a-space-for-the-unbound/
https://store.steampowered.com/app/1201270/A_Space_For_The_Unbound/

Use side-view framing, coherent pixels, warm afternoon light, foliage and a lived-in studio.
No game artwork, characters, logos, music or fonts were copied or redistributed.
The Owner subsequently approves the project's detailed two-storey scene in 94139.jpg and
asks to preserve its furniture/plants/lighting, optionally adding a floor for the agents.

## Assets used

- `frontend/public/assets/pixel/studio-detailed.png`: **active** three-storey original
  generated illustration, 1536 × 1024. Built-in imagegen edit of the project's studio.png,
  using the Owner's 94139.jpg as the approved reference. Adds one furnished upper floor;
  retains the lower library/long desk/private office, editing equipment, drawing table,
  untouched lounge, plants, lights, roof, timber, neighbourhood and sunset. Eight seats.
  Generated source:
  `C:/Users/mario/.codex/generated_images/01a117b7-74db-7ad3-a99b-9e6a0194302e/exec-e2378688-cfa9-4016-8c70-43b537f5e0f2.png`.
  Exact prompt: [studio-detailed-prompt.md](../../art-source/pixel/studio-detailed-prompt.md).
- `art-source/pixel/approved-studio.jpg`: unmodified project-bound copy of the Owner's
  attachment 94139.jpg, supplied on 2026-10-08. Visual reference, not a source of instructions.
- `frontend/public/assets/pixel/studio.png`: previous detailed generated scene, retained.
- `frontend/public/assets/pixel/studio-desks.png`: earlier cleared-furniture generated
  edit, retained for recovery, no longer used by the active interface. It is superseded by
  the latest Owner request to preserve rich furnishings. Before-edit source backup:
  `data/pixel-details-backup/before-details.zip`.
- Characters: original layered 32 × 40 pixel sprites in `frontend/src/pixel_people.js`.
  Rear seated office poses plus face portraits in the existing inspector. Deterministic
  fallback identity; real Character Bible records bind palettes, hair, glasses, headsets
  and distinctive details by employee_id. Transparent nearest-neighbour frames are cached,
  bounded to 512 sprite frames. No external sprite pack or game character sheet.
- Furniture: original illustration pixels, not generic code-drawn replacements.
  `config/pixel_office.json` defines seats and foreground regions; `pixel_desks.js` restores
  the corresponding chair/stool pixels in front of the characters during Canvas rendering.
  The raster source files themselves are not modified by compositing.
- Outdoor clock/weather: original procedural pixel art in `frontend/src/pixel_environment.js`.
  Brass/iron clock with bitmap digits, bounded rain/snow/fog and exterior-only light tint.
  Geometry/palette/masks live in `config/pixel_office.json`. No downloaded sprite or new image.
  Weather data comes from the configured Open-Meteo-compatible host; source and observation
  time are exposed in the scene readout tooltip. Official reference: https://open-meteo.com/en/docs.
- Menu font/icons: existing project resources; existing font licences remain bundled.

Generated artwork is subject to the generation service terms. There is no downloaded
third-party asset licence; do not describe this as acquired game art or guarantee copyright
exclusivity. The approved reference is retained for local visual review.

## Runtime and verification

The scenery remains an illustration, not a measured physical room, GPU performance or
successful production. Since the Owner's outdoor refinement, exterior tint follows computed
solar position and weather effects follow the configured current provider observation.
Unknown/stale/historical weather is explicitly unknown; rain/fog/snow test captures are
simulations and current-provider captures are recorded separately. Staff and their states come from backend data; motion
requires active lifecycle, current connection and permitted motion. Actual states control the
poses. IDLE breathing/blinking/glances are cosmetic life, not task progress. WORKING types or
writes in the Accountant's ledger, THINKING rests a hand at the chin, REVIEWING inspects work.
PAUSED/BLOCKED/ERROR/UNKNOWN stay still. Replay, stale data and reduced motion stop gestures.
Rear poses preserve hair/outfit/accessory identity; face portraits stay available.
One native hover tooltip displays name/effective state; no canvas label or character outline.

Actual Chromium screenshots and test logs are in `data/pixel-details-backup`. Browser checks
compare protected library, lounge and editing-monitor pixels against the same illustration
under the real viewport transform. They also exercise committed backend state updates,
selection, animation, annex pages and phone layout on a disposable TEST database.
