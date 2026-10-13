# Pixel-art asset pipeline (Blender + Unreal) — design, 2026-09-11

## Goal

Raise the visual quality of the 2D cutaway office from procedurally drawn rectangles to
studio-grade modern pixel art, without changing the backend, the layout contract
(`GET /api/v1/office/layout`), any event handling, or any existing control. Blender produces the
art; Unreal is a lighting/composition reference only; the browser canvas stays the runtime.

## Decisions

- **Quality bar floor: `RESEARCH` (Level 3).** It is the Figma quality-bar floor, has two desks
  (two characters, two poses at once), and the widest prop variety. Every other floor is left
  untouched until the before/after comparison is clearly in favour of the new pipeline.
- **World scale is unchanged: 1 world px = 1 sprite px.** Zone boxes, desk x positions, desk
  top (`floorLine - 24`), seat x and `characterMetrics` keep their meaning, so hit-testing,
  tokens, the lift and the HUD chips keep working with no change.
- **Blender renders at exact pixel size, not downsampled.** Orthographic camera pitched ~16° so
  desk tops and the floor plane read as a shallow 3/4 view; EEVEE with filter size 0 (no
  anti-aliasing); toon materials built from *Shader to RGB → constant ColorRamp* so every face
  lands on one of the five tones of the palette ramp it belongs to. The palette is exported
  from `frontend/src/office_palette.js` by `scripts/export_palette.mjs` into
  `art-source/palette.json` — one colour source, never duplicated by hand.
- **Post-process in Blender's Python (numpy):** snap every pixel to the nearest colour of the
  ramps that asset is allowed to use, then add the renderer's 1-px hue-shifted outline
  (`AMBIENT.shadow`) around the silhouette, exactly like `PixelGrid.outline()`.
- **Characters keep per-agent deterministic variation.** Blender renders character sheets in
  *key colours* (index colours per material and tone); the frontend recolours them into the
  agent's skin/hair/garment ramps at load, so `agentLook()` and the costume rules stay the only
  source of appearance. Posture still comes only from backend state.
- **Output format:** PNG with alpha per asset under `frontend/public/assets/pixel/<floor>/`,
  plus `atlas.json` (name, size, anchor, allowed ramps, frames). `frontend/public` is what Vite
  serves, so the files reach the app unchanged. Sources live in `art-source/blender/` (scripts,
  .blend files) and `art-source/unreal/` (reference project).
- **Integration:** a new `frontend/src/office_atlas.js` loads the atlas; `office_rooms.js`
  draws the RESEARCH interior from atlas sprites when they are loaded and falls back to the
  procedural drawing when they are not (so the page never shows a hole). The engine re-bakes
  its static layers once when the atlas arrives.
- **Unreal Engine 5.8** gets a reference scene of the floor (imported from Blender) for light,
  contrast, depth and atmosphere checks. Nothing from UE ships in the app.

## Non-goals

Backend changes, hardcoded agent/desk data, removing any existing drawing function, replacing
the runtime with Unreal, touching floors other than RESEARCH in this increment.

## Verification

- `npm test --prefix frontend`, `npm run check --prefix frontend`, `npm run build --prefix frontend`.
- `node scripts/room_preview.mjs` before/after renders of the RESEARCH floor at 4x.
- `node scripts/shot_office.mjs` against the running studio; `node scripts/fps_probe.mjs` for 60 FPS.
- Visual inspection of every exported sprite and of the composed floor.
