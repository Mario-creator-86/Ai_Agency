# Pixel-art asset pipeline (Blender → sprites → renderer) — 2026-09-11

> **Superseded on 2026-09-13** by `HQ_LIVING_OFFICE.md`: the office is now the Blender-rendered
> AMN-AI headquarters; the modules and assets described here were removed from the frontend.

Owner-requested quality pass on the 2D cutaway office: a Blender → sprite pipeline was built
and the RESEARCH floor (Level 3) was re-made with it as the quality bar, then compared live
against the hand-drawn floors.

**Outcome (Owner decision, 2026-09-11): the pipeline is switched off.** The Owner judged both
the rendered characters and the rendered rooms/furniture below the existing hand-drawn art
(`PIXEL_OFFICE_V2.md`), so `ATLAS_ZONES` and `ATLAS_CHARACTER_ZONES` in `office_rooms.js` are
empty and every floor draws the procedural art. What stays in force from this pass is the
**Character Bible** rule below. The pipeline, its scripts and the rendered assets remain in the
repository so they can be iterated and compared again by adding a zone type to those sets.

Frontend only: no backend, API, event, migration or layout shape changed, and every existing
control, dialog, click target and state mapping still works.

Design record: `docs/superpowers/specs/2026-09-11-pixel-art-3d-pipeline-design.md`.

## Tools found on E:\

- Blender 5.2.1 LTS — `E:\Program Files\Blender Foundation\Blender 5.2\blender.exe` (used headless).
- Unreal Engine 5.8.2 — `E:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe`
  (reference scene only; nothing it produces ships).

## Layout

```text
art-source/palette.json                  exported from frontend/src/office_palette.js (scripts/export_palette.mjs)
art-source/layout.json                   exported from backend DEFAULT_OFFICE_LAYOUT (scripts/export_layout.py)
art-source/blender/lib/pixelart.py       toolkit: pixel-exact ortho camera (16° pitch), toon ramp materials,
                                         key-colour materials, palette snap, 1-px outline, shadow layers
art-source/blender/props.py              prop library (workstation, shelves, boards, bench, plants, fillers…)
art-source/blender/environment.py        wall tile (wainscot, dado, skirting, picture rail, socket) and 3/4 floor tile
art-source/blender/characters.py         seated character parts in key colours (body/faces, 10 hair styles,
                                         glasses, headset, hands poses, mug)
art-source/blender/build_props.py        renders props + tiles -> frontend/public/assets/{pixel/office,environment}
art-source/blender/build_characters.py   renders parts -> frontend/public/assets/sprites/characters
art-source/blender/export_floor_scene.py composes a floor as glTF for Unreal (art-source/unreal/<zone>_floor.glb)
art-source/unreal/build_reference_scene.py  UE 5.8 editor script: level, ortho camera, lights; render_still.py takes the still
frontend/src/office_atlas.js             loads atlas.json / parts.json, draws props, recolours character parts
```

Generated art (checked in, served by Vite from `frontend/public`):

- `frontend/public/assets/pixel/office/*.png` + `atlas.json` — 21 props with anchors and named points
  (monitor screen rectangle, lamp position); cast-shadow layers where the render produced one.
- `frontend/public/assets/environment/*.png` — `wall_RESEARCH_h111`, `floor_RESEARCH` tiles.
- `frontend/public/assets/sprites/characters/*.png` + `parts.json` — 23 key-coloured parts.

## How the renders stay pixel art

- 1 world px = 1 sprite px. EEVEE renders at the exact sprite size with filter size 0 (no
  anti-aliasing) and no dithering; the orthographic camera is pitched 16° so desk tops and the
  floor read as a shallow 3/4 view (a 10 px floor plane on the premium floor, 7 px elsewhere).
- Materials are toon ramps: Diffuse → Shader to RGB → constant ColorRamp over the five tones of
  the palette ramp, emitted unlit. A steep key sun casts hard shadows; a left fill lifts left
  faces one tone; a right fill keeps right faces one tone above bottom faces — the same
  convention as `slab()` in `office_rooms.js`.
- Post-process (numpy inside Blender): snap every pixel to the ramps the asset is allowed to
  use, then add the renderer's 1-px hue-shifted outline (`AMBIENT.shadow`). The palette is the
  one exported from `office_palette.js`; nothing is coloured by hand.
- Characters are rendered in key colours (red = skin, green = hair, blue = garment, yellow =
  second colour, magenta = trim; five tones each). `office_atlas.js` decodes them and
  `office_characters.js` recolours per `agentLook()`, so identity rules, costumes per role and
  posture-from-backend-state are unchanged. The head is a holdout in hair/glasses/headset
  renders so parts occlude correctly when composited.

## Character Bible is authoritative

The backend's `character_bible` records (`GET /api/v1/media/character-bible`; seven canonical
employees with palette, face/hair, outfit and forbidden deviations) now decide how each
recurring employee is drawn. `main.js` reads the bible once the layout is in and hands it to the
engine; `office_characters.js` matches an agent to an entry by the explicit `employee_id` link
or, failing that, by first name (honorifics ignored), then derives the look:

- hair colour from `palette_json.hair` (or `.bun`), hair style from the description
  (bun, bob, ponytail, spiky → undercut, curly/wavy/tousled, long/sleek, short → crop);
- glasses when the description says spectacles/glasses (round when "circular"/"round");
- headset when it says headset/headphones;
- garment, second colour and trim from the first outfit colour keys present
  (suit/coat/blazer/jacket/vest/hoodie/sweater/shirt/blouse; tie/shirt/blouse/tee/scarf/badge;
  tie/headphones/headset/badge/glasses/scarf).

Skin tone and idle timing still come from the deterministic per-agent hash, because the bible
does not specify them. An agent without a bible entry keeps the role costume it had. The same
rule feeds both the procedural sprites and the atlas parts, so every floor follows the bible.
Verified live: Sarah (brunette bob, navy blazer, sky tie), Dr. Aris (white coat, teal shirt,
round glasses), Elena (auburn bun, olive vest, glasses), Marcus (purple hoodie, curly dark
hair), Lyra (headphones), Kael (spiky sandy hair, headset), Vera (short black hair, headset).

## Characters: hand-drawn on every floor (Owner decision, 2026-09-11)

After the live comparison the Owner judged the Blender-rendered characters a regression against
the hand-drawn sprites (boxier heads, hair reading as a cap; Elena visibly worse). The
renderer therefore draws the hand-drawn characters on every floor, with the Character Bible
applied, and uses the atlas only for rooms and furniture. `ATLAS_CHARACTER_ZONES` in
`office_rooms.js` is empty; the character parts stay rendered and loadable so a later
iteration can be compared again by adding a zone type to that set.

## Integration rules

- `office_rooms.js` exports `ATLAS_ZONES` (currently `RESEARCH`) and `usesAtlas(zone)`. A zone
  in the set draws atlas props, wall/floor tiles and atlas characters **only when the atlas has
  loaded**; otherwise the procedural drawing runs, so the page never shows a hole.
- `workstation()` keeps the layout contract: desk plane at `floorLine - 24`, seat at
  `deskX + 8`; the sprite's screen rectangle and lamp point come from `atlas.json`.
- The engine bakes its static layers again once `loadAtlas()` resolves.
- `frontend/dev/room_preview.html?zone=RESEARCH&atlas=0` renders the procedural "before";
  without `atlas=0` it renders the "after". `scripts/room_preview.mjs` drives it headlessly.

## Rebuild commands

```shell
node scripts/export_palette.mjs
uv run python scripts/export_layout.py
"E:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --python art-source/blender/build_props.py
"E:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --python art-source/blender/build_characters.py
"E:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --python art-source/blender/export_floor_scene.py
npm run build --prefix frontend
```

Review artifacts (generated, ignored by Git): `output/art/props_contact.png`,
`output/art/characters_contact.png`, `output/art/research_before_4x.png`,
`output/art/research_after_4x.png`, `output/art/live_after_fit.png`,
`output/art/live_after_research_2x.png`, `output/art/live_bible_research_2x.png`,
`output/art/live_bible_ground_2x.png`, `output/art/ue_research_reference.png` (the Unreal still).

## Verification (2026-09-11)

- `npm test --prefix frontend`: 53 passed (48 existing + 4 new in `office_atlas.test.js`:
  key decoding, ramp resolution, image decoding, no-DOM fallback; 1 new in
  `office_art_v2.test.js`: Character Bible matching and look derivation).
- `npm run check --prefix frontend` (tsc), `npm run build --prefix frontend`: clean.
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`,
  `uv run python scripts/check_docs.py`, `uv run python scripts/check_secrets.py`: clean
  (`art-source/` is excluded from ruff: those scripts run inside Blender/Unreal's own Python).
- Live studio at http://127.0.0.1:8000 with the seven seeded agents: no page errors; the
  atlas is served (`/assets/pixel/office/atlas.json` → 200); clicking a character still selects
  the real backend agent (hit-test geometry unchanged).
- Frame rate (`scripts/fps_probe.mjs`, headless Chromium 1920×1080, fullscreen): 61 FPS at
  fit and at 2.2× zoom, median draw 7.4 ms / 6.5 ms.

## Before / after, honestly

What is clearly better on the RESEARCH floor: coherent light (every object lit by the same key
sun, top faces lit, hard contact shadows), real volume on desks, chairs, shelves and the lab
bench, a 3/4 floor the furniture actually stands on, panelled wainscot with dado and skirting,
and one palette across props, walls and people. What is not yet better: the character heads
are boxier than the hand-drawn ones and the "short" hair reads as a cap; the plant and desk
lamp are simpler than the procedural versions. Those are prop/character iterations inside the
same pipeline (edit `characters.py` / `props.py`, re-run the build), not pipeline problems.

Decision on rolling the pipeline out to the other eight departments is the Owner's; the
mechanism is one line (`ATLAS_ZONES`) plus the per-department tiles and props.

## Unreal Engine reference scene

`art-source/blender/export_floor_scene.py` composes the RESEARCH floor (room shell, wainscot,
props at the renderer's positions, ceiling fixtures) and exports `research_floor.glb`.
`art-source/unreal/build_reference_scene.py` imports it into the `AMNReference` project
(`/Game/Reference/research`), places an orthographic camera pitched like the sprite camera, a
key sun, a cool fill, a violet ambient sky light and one warm point light per ceiling fixture,
a fixed-exposure post-process volume; framing is measured from the placed meshes so the
importer's unit scale and axis convention are never assumed. `render_still.py` takes a still
through that camera inside the editor (`-ExecCmds="py render_still.py"`), saved under
`AMNReference/Saved/Screenshots/`. The Movie Render Queue path was dropped: its queue factory
class is not exposed to Python in 5.8. Everything the editor generates (`Content/`, `Saved/`,
`Intermediate/`, the `.glb`) is ignored by Git; only the scripts, `.uproject` and config are
checked in. The rendered still (`output/art/ue_research_reference.png`) frames the room at the
sprite camera's pitch and confirms the lighting story the sprites use: a steep warm key, cool
fill from the left, ambient violet in the shadows and warm pools under each fixture. Two headless
bugs found on the way are fixed in the scripts: Blender's `matrix_world` is stale in background
mode until `view_layer.update()`, and `unreal.Rotator` takes (roll, pitch, yaw) positionally.

## Not done / honest limits

- Only RESEARCH is re-made; the other floors and the street are untouched.
- No walk/leave animations: the office has no walking agents today (the courier is procedural).
- The window sprite is a frame only; the city view behind it is still drawn by the renderer.
