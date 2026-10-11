# Front/back, ground contact and interface layers — 2026-10-09

PIXEL_DEPTH_PHYSICS is complete. The Owner's screenshot showed a car in front of the tall
foreground flowers. The same drawing-order audit covered street animals, clock, bicycles,
indoor ensembles, dialogue and the actual menus/dialogs. The approved building and its
details, personal seats, employee identities, 0.9 character scale and backend state remain.

## Drawing order

Objects share a stable order based on their ground contact, regardless of facing direction
or registration/employee array order. Farther objects are painted first:

| Layer/object | Ground depth / rule |
| --- | --- |
| Original building, town, lighting and solar sky | Base of the scene; existing sky/roof clips |
| Rear pedestrians | 570 |
| Dog and leash | 572, ahead of its farther owner |
| Left cat / front pedestrians / right cat | 574 / 575 / 577 |
| Bicycle | 579 |
| Street clock pedestal | 587 |
| Traffic | 590; nearer cars cover the clock's lower stem |
| Near garden and fence | Original pixel silhouettes restored above the street actors |
| Rain, snow and fog | Above outside layers; office interiors excluded |
| Eight seated ensembles | Floor anchors 229 / 375 / 525; all empty chairs cleared first |
| Dialogue | After all seated people, preventing later bodies from covering the bubble |
| Toolbar, roster and native modal dialogs | Existing DOM controls above Canvas; modal backdrop blocks scene |

The staff's chair/person artwork already contains correct internal backrest, legs and feet.
Its uniform scale and contact points are unchanged. The existing furniture restoration and
code-drawn fallback remain available when an ensemble cannot load. Street travel clips are
still full-width: foliage can hide a passing person without stopping their route.
Pointer hit boxes use the same depth order in reverse, so the nearer painted employee
receives a click if targets overlap. An explicit overlapping fixture checks this selection.

## Foreground and lighting

`config/pixel_office.json` registers three traced garden contours, four fence posts and one
near rail. `frontend/src/pixel_depth.js` extracts an alpha mask from the original native
image once per loaded background, using the original leaf/petal palette inside those
contours. Small shaded leaf interiors are retained; road gaps stay transparent. The
compositor copies exact original RGB pixels and caches the plate. The plate's lighting
matches the outdoor pass and is refreshed only when the quantized light/weather changes
(256 steps). No replacement PNG or new downloaded/generated artwork was created.

Night brightness/saturation for pedestrians, cyclists, pets and vehicle bodies are
configured centrally. Headlights retain their emissive pass; chair/office lighting is
unchanged. Actual Bucharest time, solar phase and fresh weather continue to drive the scene.

The unchanged approved background SHA-256 is
`957e67d70e01438056c5e2f073a8b39d8152f2488ea28217df2368384b75dbe1`.
Existing source/provenance is in PIXEL_STUDIO_ASSETS.md, PIXEL_CHAIR_ENSEMBLES.md and
PIXEL_STREET_REFINEMENT.md. This task added no external assets or imagegen calls.

## Actual menu defect found and fixed

At 1360–1719 px, a pixel override made room names inline while the underlying buttons kept
their 36 px icon width. Overflowing icons could intercept the adjacent button: Playwright's
ordinary click on Research hit Media. `pixel_studio.css` now keeps inert floating labels at
narrow desktop widths and uses intrinsic-width named buttons from 1720 px. Menu actions,
names and locations remain the same. Regression checks press every menu at 1051, 1280,
1366, 1700, 1720, 1920 and 2560 px without forced clicks.

## Verification and limits

- 883 frontend unit cases pass; TypeScript check passes.
- Seven bounded Playwright scene checks pass. Navigation was rechecked after the menu fix;
  the new depth check was rechecked after tightening route measurement.
- Depth fixtures: 64 simulated seconds / 257 frames, all four vehicle variants, both
  pedestrian directions and all three garden zones. Pixel assertions check foreground
  coverage and a clear road gap throughout. Six day/night crossing snapshots have zero
  incorrect restored pixels within the stated color tolerance. Clock/traffic overlap,
  dog order, all eight floors and rain/snow/fog exterior clips pass.
- Existing checks also cover 80 simulated street seconds / 641 frames and 60 seated
  seconds / 481 frames. Pause, hidden/stale/replay guards, reduced motion, hover and native
  mobile page scrolling remain covered.
- Actual read-only UI at 11:11 · Parțial înnorat 23°C: eight actual ACTIVE/IDLE
  staff visibly animate; four pedestrians, bicycle, dog, two cats and all four car variants
  move. H.264 review clip: 31.917 s, 1700 × 1006, captured at 24 fps. Scene/wall-time ratio
  1.000144; measured walking speeds approximately ±36.134 world px/s. The two cats cover
  274.262 / 320.000 px. These are recorded travel/capture values, not an FPS benchmark.
- Actual DOM: nine dialogs (Research, Media, Publishing, Workforce, Story, Runbook,
  Autonomy, Settings and agent inspector) open above the scene with focus inside, blocking
  backdrop and normal Escape close. Toolbar and roster stay clickable. Zero page errors
  or refused requests. Screenshots distinguish live UI from the labelled scenario sheet.
- Actual production bundle and static atlases are byte-equal to local build/art; the
  source hash is current and foundation liveness/readiness return HTTP 200.
- 66 scoped backend/docs/secret/layout/weather checks pass; documentation inventory
  and secret scans pass (1066 files / 68 reviewed findings; baseline unchanged). Initial doc-header regression caused by the
  temporary claim was corrected; the final scoped lane is green.

The fixture dates/weather are explicit scenarios. The live clip uses the served bundle
and actual backend states, with only own-origin GET/HEAD and its authenticated read socket.
No backend restart, production policy/database/model command or GPU/media/upload job was
issued. This is a visual depth/contact audit; historical external workflow acceptance
limits in CURRENT_STATUS.md and PROJECT_STATE.json still apply.

## Files and evidence

Source: `config/pixel_office.json`, `frontend/src/pixel_depth.js`, `pixel_life.js`,
`pixel_office.js`, `pixel_actor_atlas.js`, `pixel_vehicle.js`, `pixel_studio.css`.
Regression entry: `frontend/package.json`, `tests/pixel_depth.test.js`,
`tests/fixtures/pixel_depth_entry.js`, `tests/e2e/pixel_depth.spec.js`,
`tests/e2e/pixel_navigation.spec.js` (frontend-relative test paths).

Evidence: `output/playwright/depth-physics-2026-10-09/`:
`depth-crossings.png`, `depth-cycle-proof.json`, `dom-layer-proof.json`,
`menu-hit-proof.json`, `live-ui-verification.json`, `live-studio-clean.png`,
`studio-street-motion.mp4`, `video-metadata.json`, `final-integrity.json`.
`data/pixel-depth-2026-10-09/verification.json` records final check results.

The evidence folder's `before/` contains the preceding scene sources and
`dist-before-depth.zip`. The fallback vehicle backup reconstructs just this task's two
filter additions; other backups were copied before their edits. Restore only these scene
changes, remove the new depth module/test registration if rolling back, and rebuild using
the canonical launcher build helper. Preserve unrelated RunPod/backend/art changes.
Refresh the existing running page with Ctrl+F5; leave ANIMAȚII on for visible movement.
