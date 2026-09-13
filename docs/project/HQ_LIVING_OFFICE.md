# The AMN-AI headquarters — the living office (2026-09-13)

The Owner asked for the studio office to be redone so it looks like the headquarters picture he
made (`art-source/reference/headquarters_dusk_primary.png`), built with the studio's own tools
(Blender, Unreal) and without spending image-generation credits. This replaces the procedural
pixel-art office (`PIXEL_OFFICE_V2.md`, `PIXEL_ART_PIPELINE.md`, `STREET_LIFE.md`).

Nothing that shows studio state is invented: an employee types only while the backend says
WORKING, the render bay screen shows the video editor's real state, the lift moves only when a
workflow token changes floor, and the weather is the live observation or none at all.

## What is on screen

- **The building**: roof and AMN-AI sign, L4 Executive, L3 Research, L2 Content, L1 Production
  (audio booth and render bay), and the ground floor — S1 Infra, the lobby, S2 Operations
  (treasury and distribution desks) and S3 AI Space (the ad-space storefront). The lift tower
  on the right carries the courier between floors.
- **The employees**: eight chibi characters rendered from their Character Bibles (palette from
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
blender -b --factory-startup --python art-source/blender/hq/build_characters.py -- --out <frames>
blender -b --factory-startup --python art-source/blender/hq/build_characters.py -- --out <frames> --pedestrians
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
- Cars are lofted from side profiles (`PROFILES` in `build_vehicles.py`: beltline and roof
  height along the length, a glasshouse leaning in, the plan rounded at the bumpers), with wheel
  arches, door seams, mirrors and lamps that wrap round the corners like the reference's
  side-on cars. Only the broad rim light shows in reflections, so windows stay dusk-dark. After
  the lamp pass, each head and tail lamp the render actually shows is recorded per direction in
  `vehicles.json` (`directions.<dir>.lamps`, frame px), and the canvas blooms exactly those.
- `art-source/reference/compare.py <render> <out>` compares a render or a live screenshot with
  the reference per region (colour distance, brightness, contrast, SSIM).

## Verification

```text
cd frontend && npm test && npm run check && npm run build
uv run pytest tests/test_office_weather.py tests/test_office_layout_matches_scene.py tests/test_phase3_office.py
node scripts/shot_hq.mjs --out dusk.png --time 2026-09-13T16:40:00Z          # the reference's light
node scripts/shot_hq.mjs --out rain.png --time 2026-09-13T20:30:00Z --weather rain
node scripts/shot_hq.mjs --out ufo.png --time 2026-09-13T20:30:00Z --event ufo_flyover --wait 6000
python art-source/reference/compare.py dusk.png compare.png
```

`--weather` and `--event` act only inside the headless browser used for the screenshot.

## Known limits

- Messages written by the backend (reasons, errors, agent prose, run notes) are still in
  Romanian; the interface's own words are English.
- The weather endpoint and the new layout need the backend restarted.
- The lift carries a courier for a workflow token; the seated employees do not leave their
  desks, because the backend does not say they walk anywhere.
