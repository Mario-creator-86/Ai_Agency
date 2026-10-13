# Pixel office v2 — premium visual system for the 2D cutaway — 2026-09-10

> **Superseded on 2026-09-13** by `HQ_LIVING_OFFICE.md`: the office is now the Blender-rendered
> AMN-AI headquarters; the modules and assets described here were removed from the frontend.

## Scope

Owner-requested visual rebuild of the 2D agency to a commercial "modern pixel art" standard
(reference quality: Eastward, Potion Permit, Kingdom Two Crowns; no borrowed assets). The concept
is unchanged: a cutaway building with floors, departments, agents and animations, driven only by
the backend layout and event stream. No backend code, API, event, migration or data shape changed.
No functionality was added or removed; every existing control, dialog, click target and state
mapping still works and is verified below.

Design work happened in Figma first, then the same system was implemented in code:
**AMN-AI Office · Pixel Art Design System** — <https://www.figma.com/design/bqTc0PoCbjL5dH5xw0FRDI>

- Page 01 · Direction, Palette & Components: the `Office Palette` variable collection (60 colour
  tokens: ambient, sky, city, facade, materials, department accents/walls, HUD), swatches bound to
  the variables, seven character components built pixel-for-pixel from the renderer's sprite data,
  and HUD components (state chip variant set, name card, department sign, speech bubble).
- Page 02 · Quality Bar — Research Floor: the finished floor at 4x plus a 6x workstation detail,
  and the eight rules every other room follows. This page is the quality bar for the project.
- Page 03 · Building & Layout Spec: the full building render and the zone table taken from the
  backend layout (`GET /api/v1/office/layout`), with world metrics.

Note: the Figma Starter plan caps the file at three pages and rate-limited the MCP tool calls at
the end of the session; a few annotation texts on pages 02/03 are clipped to one line and the
HUD chip labels in Figma overflow their pixel-spec widths (the code uses a 5×7 bitmap font, Figma
uses "Press Start 2P"). The renders and tokens are authoritative; the annotations are cosmetic.

## What changed (frontend only)

New modules, each with one responsibility:

- `frontend/src/office_palette.js` — the single colour source. Five-tone hue-shifted ramps
  (`ramp()` bends shadows towards `AMBIENT.shadow` violet-navy and highlights towards
  `AMBIENT.light` tungsten), sky/city/street/facade/material ramps, skin/hair/cloth ramps, and
  one material story per department (`DEPARTMENTS`: wall finish, floor finish, accent, trim, lamp).
- `frontend/src/pixel_sprites.js` — `PixelGrid` (letter-row blitting, automatic 1px hue-shifted
  outline, flip), a bounded compiled-sprite cache, cached radial glow sprites, contact shadows.
- `frontend/src/office_characters.js` — seated character sprites (26×34 world px, head 14 px)
  compiled once per look/face/pose; role costumes (`COSTUMES`: blazer, lab coat, cardigan,
  sweater, headset, hoodie, vest), ten hair styles, glasses/headset, deterministic looks per agent
  id; hands/typing frames, thinking hand-to-chin and idea bubble, sleep pose and Z marks;
  `modeForAgent` (unchanged mapping: PAUSED/SUSPENDED/TERMINATED → sleep, WORKING/EXECUTING/
  RUNNING → work, THINKING/PLANNING → think, else idle).
- `frontend/src/office_rooms.js` — room shells (ceiling band with recessed fixtures, lit-to-shadow
  wall with a finish per department: panelled, plaster, foam, brick, steel; floor surface with a
  pattern per department and a concrete slab edge; ambient occlusion at ceiling and floor), baked
  light cones and floor pools, windows showing the night city (repainted when the street clock's
  daylight changes), the workstation (chair → character → desk front/monitor/hands), nine
  department interiors (evidence board, lab bench, executive sofa, storyboard wall, vocal booth,
  edit bay, racks, café bar, dispatch board, shopfront) and collision-free wall fillers.
- `frontend/src/pixel_font.js` — the 5×7 bitmap font, moved out of the engine.
- `frontend/src/office_engine.js` — rewritten orchestrator: sky/skyline/street in the new palette,
  limestone facade with slab ends, roof plant, glass lift shaft and cab, neon signage, HUD chips,
  name cards, speech bubbles, tokens and courier. Three cached layers (bg, static A, front B) so
  a seated person is occluded by their desk; only screens, LEDs, fans, meters, characters, chips
  and the lift are painted per frame. Public API and exports are unchanged (`Viewport`,
  `OfficeEngine`, `streetGeometry`, `PEDESTRIAN_HEIGHT`, `makeTraffic`, `updateTraffic`).
- `frontend/src/office_art.js` — removed (superseded; nothing imported it).
- `frontend/src/style.css`, `frontend/src/office_scene.css` — the scene sits in a slim dark bezel
  instead of the beige frame; camera/module controls are a dark, high-contrast pill; the light
  admin panels around the scene are untouched.
- `frontend/dev/room_preview.html` + `scripts/room_preview.mjs` — standalone room renderer used to
  iterate on one floor without the backend (`node scripts/room_preview.mjs out.png "zone=RESEARCH&scale=4"`).
- `scripts/shot_office.mjs`, `scripts/shot_page.mjs`, `scripts/fps_probe.mjs` — review helpers
  against the running studio (screenshots, page overflow check, frame-rate probe).

Preserved as-is: agent selection and the inspector (hit test now uses the real seat geometry),
`OfficeState` and all event handling, workflow tokens and the lift courier trip, street life and
Bucharest clock, fullscreen/zoom/fit controls, all module dialogs.

## Verification

- `npm test --prefix frontend`: 43 passed (38 existing + 5 new: ramps, department material
  completeness, pixel-grid outline/bounds, sprite template geometry, look/costume/mode mapping).
- `npm run check --prefix frontend` (tsc): clean. `npm run build --prefix frontend`: clean.
- `uv run python scripts/check_docs.py`: inventory and architecture hashes verified.
- Live studio at <http://127.0.0.1:8000> with the seven seeded agents: no page errors on desktop
  (1600×1100) or mobile (390×844), no horizontal overflow; clicking a character selects the real
  backend agent and opens the inspector (`output/playwright/selected.png`).
- Frame rate (`scripts/fps_probe.mjs`, headless Chromium 1920×1080, fullscreen, fit and 2.2x zoom):
  60 FPS, median frame draw 6.3 ms, p95 6.6 ms.
- Screenshots: `output/playwright/baseline-fit.png` (before), `after1-fit.png` / `after1-2x.png`
  (after), `rooms-all.png` (all nine departments), `page-desktop.png`, `page-mobile.png`.

Not done / honest limits: no daytime palette pass beyond the existing daylight mixing; the street
crowd sprites (`street_actor.js`) keep their previous rig with retuned colours only; character
sprites are seated-only (the courier is the only walking figure).
