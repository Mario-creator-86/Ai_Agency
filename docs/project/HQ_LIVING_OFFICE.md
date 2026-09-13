# The AMN-AI headquarters — the living office (2026-09-13)

The Owner asked for the studio office to be redone so it looks like the headquarters picture he
made (`art-source/reference/headquarters_dusk_primary.png`), built with the studio's own tools
(Blender, Unreal) and without spending image-generation credits. This replaces the procedural
pixel-art office (`PIXEL_OFFICE_V2.md`, `PIXEL_ART_PIPELINE.md`, `STREET_LIFE.md`).

Nothing that shows studio state is invented: an employee types only while the backend says
WORKING, the render bay screen shows the video editor's real state, the lift moves only when a
workflow token changes floor, and the weather is the live observation or none at all.

## What is on screen

- **The building**: roof and AMN-AI sign, L4 Executive, L3 Research (blue) and Fact Check
  (terracotta), L2 Content (wood) and Distribution (teal), L1 Production (audio booth and render
  bay), and the ground floor — S1 Infra, the lobby, S2 Treasury (burgundy) and S3 AI Space (the
  ad-space storefront). Every department has its own office, its own colour and a lit sign, and
  every employee their own desk facing the viewer. The lift tower on the right carries the courier
  between floors.
- **The employees**: eight adult-proportion people (`build_people.py`) from their Character Bibles (palette from
  the backend record; hair, garments and accessories from the Owner's sheets), each seated
  where the backend layout puts their desk, facing the way the reference shows them.
- **The city**: skyline with a cable-stayed bridge and the "Bucharest AI District" billboard,
  trees and street lamps, the terrace, pavement with bollards, a two-lane road with a zebra
  crossing and a bus shelter with a live clock and rotating advertising.
- **Chrome** (English): "WORKSPACE · Studio Office", a pill with Bucharest time and the live
  weather, a "Live Renderer N fps" pill that shows the frames actually drawn, and the control
  bar — Autonomy, Environment, zoom, Fit, 1:1, Fullscreen, Research, Media Production,
  Distribution, Staff, Journal, Daily Run, Treasury.

## Architecture (frontend)

| Module | Role |
| --- | --- |
| `office_engine.js` | `OfficeEngine` (same public API main.js used before), `Viewport`, input, FPS, lift and courier state machine |
| `hq_assets.js` | loads the manifest, plate layers (night, and day only when needed), sprite sheets, vehicle catalogue, event config |
| `hq_world.js` | `WorldSimulationManager` (owns and steps every manager), `HQRenderer` (draw order), `AmbientAnimationManager`, seeded `mulberry32` |
| `hq_time.js` | `TimeOfDayManager`: solar elevation for Bucharest's real date and time → daylight, dusk warmth, phase (day, dawn, dusk, night), sky colours |
| `hq_weather.js` | `WeatherManager`: polls `/api/v1/office/weather`; unknown weather draws nothing |
| `hq_events.js` | `RandomEventManager`: rarity, weight, cooldown, concurrency, allowed weather and time, duration, priority, reaction radius |
| `hq_traffic.js` | `TrafficManager`: right-hand traffic, daily rhythm mix, bus stops, zebra stops, yielding to sirens, no overlaps |
| `hq_pedestrians.js` | `PedestrianManager`: rhythm and weather driven population, commuters, crossings, umbrellas in rain |
| `hq_agents.js` | `AgentVisualStateManager`: backend state → animation, Bible sprite matching, screen modes, reactions of idle agents |
| `hq_sky.js` | sky gradient, clouds, stars, sun and moon, rain, snow, fog, lightning, sky events |

Draw order: sky and far sky events → city → street back → street ground → road light →
building back → live screens → lift → employees → consoles → building shell → near sky events
→ tokens and courier → street props → shelter clock and ad → pedestrians → bollards → vehicles →
near planters → weather → night grade → speech bubbles → selection label.

There is one random source per world (seeded); no manager calls `Math.random`. A seed replays
the same street and the same sequence of events (tested).

## Backend

- `DEFAULT_OFFICE_LAYOUT` now describes the rendered building (world 1600 × 840, rooms and seats
  from the manifest). `tests/test_office_layout_matches_scene.py` fails if the two drift.
- `GET /api/v1/office/weather` (Owner only) reads the current observation from the configured
  Open-Meteo compatible host and maps WMO codes to the scene's conditions. Configuration:
  `STUDIO_OFFICE_WEATHER_HOST` (unset = no weather), `STUDIO_OFFICE_LATITUDE`,
  `STUDIO_OFFICE_LONGITUDE`. Cached ten minutes; a failure is reported, never replaced.

## Random events

`frontend/public/assets/hq/world_events.json` is the whole configuration. Rarity tiers are
common, uncommon, rare and very_rare (the UFO: night, clear sky, a six-hour cooldown, and a
very-rare rate of about one start per thousand minutes of eligible sky). Events include
airliners, bird flocks, the bus serving the shelter, joggers, pedestrians crossing, helicopter,
ambulance, police patrol, delivery drone, a studio ad on the billboard, a hot-air balloon, a
fire engine, fireworks, shooting stars and the UFO. An event with a reaction radius of 1000 or
more turns the heads of idle employees and passers-by for a few seconds; working employees keep
working. For QA: `window.__studio.engine.world.events.trigger('ufo_flyover')`.

## The art pipeline (local, no generated imagery)

```text
uv run python scripts/export_character_bible.py            # Bible palettes -> art-source/character_bible.json
python art-source/blender/hq/make_textures.py              # screens, window views, art, ad banners
blender -b --factory-startup --python art-source/blender/hq/build_hq.py -- --out <dir> --scale 2 --samples 128 --variant night
blender -b --factory-startup --python art-source/blender/hq/build_hq.py -- --out <dir> --scale 2 --samples 128 --variant day
python art-source/blender/hq/export_plates.py <dir> frontend/public/assets/hq
blender -b --factory-startup --python art-source/blender/hq/build_people.py -- --out <frames>
blender -b --factory-startup --python art-source/blender/hq/build_people.py -- --out <frames> --pedestrians
python art-source/sky/paint_clouds.py                      # the sky's painted cloud layers
python art-source/blender/hq/pack_sprites.py <frames> frontend/public/assets/hq/characters --downscale 2
python art-source/blender/hq/pack_sprites.py <frames> frontend/public/assets/hq/characters --manifest pedestrians.json --downscale 2
blender -b --factory-startup --python art-source/blender/hq/build_vehicles.py -- --out <renders>
python art-source/blender/hq/pack_vehicles.py <renders> frontend/public/assets/hq/vehicles
```

- Cycles on the local GPU (HIP), orthographic camera pitched 10°, 28 world pixels per metre;
  every room, seat, screen, lamp and lift stop is exported to `manifest.json` by projecting the
  modelled geometry, never typed in.
- Plates are rendered layer by layer with the other layers present but invisible to the camera,
  so light, shadow and reflection are the whole scene's; bloom is added in post, then each layer
  is cropped to what it covers and saved as WebP (the eighteen plates weigh 2.6 MB).
- Because a layer is rendered without the others in view, a surface that only an earlier-drawn
  layer hides is painted over it on the page. Put geometry in the layer of whatever covers it:
  the slab's body is modelled with the rooms (the floor covers its top), only its face is shell.
  The flattened `--preview` cannot show this kind of fault; check it on a live screenshot.
- The camera looks down 10°, so the top of a box rises about 4.9 world pixels above its front
  edge for every metre of depth. A deep box in front of something paints its roof over it: an
  8 m deep building once hid the fourth line of the skyline slogan. Model facades that stand in
  front of text, windows or rooms as shallow as they can be.
- Cars are lofted from side profiles (`PROFILES` in `build_vehicles.py`: beltline and roof
  height along the length, a glasshouse leaning in, the plan rounded at the bumpers), with wheel
  arches, door seams, mirrors and lamps that wrap round the corners like the reference's
  side-on cars. Only the broad rim light shows in reflections, so windows stay dusk-dark. After
  the lamp pass, each head and tail lamp the render actually shows is recorded per direction in
  `vehicles.json` (`directions.<dir>.lamps`, frame px), and the canvas blooms exactly those.
- `art-source/reference/compare.py <render> <out>` compares a render or a live screenshot with
  the reference per region (colour distance, brightness, contrast, SSIM).

## Unreal Engine 5.8 (in progress)

The Owner judged the Blender-built people, cars and buses far from his picture and asked for
Unreal Engine. The headquarters is being moved there; the web canvas and its managers stay.

```text
blender -b --factory-startup --python art-source/unreal/export_hq_scene.py      # hq_scene.glb + hq_scene.json
UnrealEditor-Cmd.exe art-source/unreal/AMNReference/AMNReference.uproject -run=pythonscript -script=art-source/unreal/build_hq_scene.py
UnrealEditor.exe     art-source/unreal/AMNReference/AMNReference.uproject -ExecCmds="py art-source/unreal/render_hq_still.py" -unattended -nosplash
UnrealEditor-Cmd.exe art-source/unreal/AMNReference/AMNReference.uproject -run=pythonscript -script=art-source/unreal/inventory_content.py
```

- `export_hq_scene.py` builds the Blender scene without rendering, bakes every mesh's world
  transform, turns labels into meshes and writes the lights, the plates' camera and axis markers
  to `hq_scene.json`.
- `build_hq_scene.py` imports it into `/Game/HQ/Scene`, builds `/Game/HQ/HQ_Dusk`: meshes, the 63
  scene lights (lumens from Blender watts, `AMN_LM_PER_W`), sky atmosphere, volumetric clouds,
  height fog, a sun 2.5° under the horizon on the picture's sunset side, a real-time sky light,
  Lumen, the orthographic plate camera and a fixed exposure (`AMN_EV`). The importer's axes and
  units are measured from the marker cubes (Blender +y maps to Unreal −y, 100 units per metre).
- glTF carries only flat colours, so the first import had white walls, white towers and a white
  road. The exporter now bakes each mesh's procedural materials into its own colour and
  emission textures (UV map `bake`, size from surface area up to `AMN_BAKE`, emission stored
  normalised with its strength kept), gives skyline facades tiling textures of 24×24 windows on
  world-aligned UVs (a single bake blurred every window into a golden blob), leaves transparent
  materials as they are and drops the haze planes (Unreal's height fog replaces them).
- An orthographic camera cannot see the sky atmosphere (the first still had a black sky), so
  `compose_sky_backdrop.py` composes the web page's dusk sky (gradient, afterglow, painted cloud
  layers) into `sky_dusk.png`, shown on an unlit backdrop 90 m behind the building.
- The editor started with `-unattended` took its high-resolution screenshot **unlit**: base
  colours and emission at full strength, no lights, no exposure. That is why the first stills
  looked flat and overlit, and why exposure on the volume, on the camera and `r.ExposureOffset`,
  and even lights at a third of their intensity, all rendered the identical image (mean 80.24).
  `render_hq_still.py` now runs `viewmode lit` and the lighting show flags before the shot; the
  same level then rendered lit (mean 115.34, spotlight pools, lit lobby and street lamps).
  `probe_look.py` reads back the stored look, `probe_materials.py` lists the parameters of the
  imported glTF materials (`EmissiveStrength`, `EmissiveFactor`, textures). `AMN_GLB` picks
  another export for the level.
- Balance, measured lit against the picture (environment variables of `build_hq_scene.py`):
  `AMN_LM_INTERIOR` and `AMN_LM_EXTERIOR` (lumens per Blender watt, separately: the rooms blew
  out long before the street was bright enough), `AMN_LEVEL_GAIN` (`level:gain,…`, the floor
  found from the light's height against the ceilings; L3 needed far less than L4), `AMN_SKY_GAIN`
  (the sky backdrop's brightness; lit, 1.35 matches the picture) and `AMN_EV` (exposure offset,
  applied by `render_hq_still.py`). `AMN_SKYLIGHT` changes nothing in the still (2 and 4
  rendered the identical image). Diagnostics: with no interior lights the rooms fell to about
  30 (picture 51–80) and did not change without exterior lights either, so the rooms are lit by
  their own lights only; the street depends on the exterior lights (13 without, 50 at 70 lm/W,
  picture 60). The balance measured closest to the picture is now the script's default: interior
  1.0 lm/W, exterior 70, sky 1.35, EV 0, floors `0:0.55,1:0.7,2:0.7,3:0.3,4:0.8` (mean colour
  distance 26.9; the web page measures 8.3). `AMN_CITY_EMISSIVE` scales `EmissiveStrength` on
  the skyline's imported materials (lit, the city read brighter than the picture) and
  `AMN_STREET_FILL` adds a wide, cool, shadowless area light over the road, in lumens, for what
  the street lamps do not reach. City emission 0.7 is the default (the city dropped by 7). The
  street fill is off by default: at 120000 lm it lifted the street by only 4 points and mirrored
  as a hard white oval on the wet road, a defect the region numbers (25.3) did not show. This is
  where tuning lights stopped paying. What still separates the still from the picture is not
  light balance: a dark road with no wet reflections, harsh light pools, the unlit top sign, and
  no people or vehicles.
- `render_hq_still.py` waits for Lumen and the clouds to settle, then saves
  `AMNReference/Saved/Screenshots/WindowsEditor/hq_dusk.png` at 3200×1680.
- `inventory_content.py` lists what the project holds (`content_inventory.json`): after the Owner
  adds Fab packs (City Sample Vehicles, Vehicle Variety Pack, MetaHuman outfits, office and
  street props) it tells the scene script which meshes exist and how big they are.
- Everything the editor and the exporter generate is ignored by Git; only scripts, the
  `.uproject` and config are checked in.

## Verification

```text
cd frontend && npm test && npm run check && npm run build
uv run pytest tests/test_office_weather.py tests/test_office_layout_matches_scene.py tests/test_phase3_office.py
node scripts/shot_hq.mjs --out dusk.png --time 2026-09-13T16:40:00Z          # the reference's light
node scripts/shot_hq.mjs --out rain.png --time 2026-09-13T20:30:00Z --weather rain
node scripts/shot_hq.mjs --out ufo.png --time 2026-09-13T20:30:00Z --event ufo_flyover --wait 6000
python art-source/reference/compare.py dusk.png compare.png
python art-source/reference/plates_compare.py frontend/public/assets/hq/plates plates.png --daylight 0.07
```

A live screenshot also measures traffic, people and the crossfade, so two shots of the same plates
differ. `plates_compare.py` composes the exported plates alone (the day plates blended in at the
canvas's `plateDayMix` for the shot's daylight; 0.07 at the reference's dusk) and scores only the
building and street regions. When it and a live shot disagree, look for what the canvas adds.

`--weather` and `--event` act only inside the headless browser used for the screenshot.

## Known limits

- Messages written by the backend (reasons, errors, agent prose, run notes) are still in
  Romanian; the interface's own words are English.
- The weather endpoint and the new layout need the backend restarted.
- The lift carries a courier for a workflow token; the seated employees do not leave their
  desks, because the backend does not say they walk anywhere.
