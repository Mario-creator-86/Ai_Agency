# Living pixel studio — 2026-10-08

The Owner reports doubled character text and an unwanted hover rectangle, and requests a
living studio/city with believable desk actions. Preserve approved details and personal desks.

## Result and design

Remove the canvas desk label and character border for hover/selection. Keep one native tooltip
with actual name/effective state, including PAUSED/SUSPENDED. Roster, clicks, keyboard selection
and the existing inspector remain available. Real speech bubbles retain their recorded message.

Original rear-seated sprites now have visible breathing, glances/side-face blink, posture shifts,
cup sipping and stretches. Full-cycle identity offsets make their gesture phases independent.
WORKING uses role-specific keyboard/mouse/notebook/paper/headset poses; THINKING alternates
chin/looking poses; REVIEWING reads/marks notes; IDLE never randomly becomes WORKING. Foreground
hands/tools render above the restored chair so movement remains visible. Backend-owned seats
and original Character Bible identities remain intact.

The town has four walking pedestrians, a pedalling cyclist, a passing car with evening lights,
a moving cat, daytime birds, gentle cloud drift and small evening window/moth details. Actual
rain gives pedestrians umbrellas and wet road reflections; moths require suitable available
weather. These are decorative city inhabitants, never new employees or fabricated tasks/events.
Original detailed art is byte-identical; warm interiors and blue/violet night palette preserved.

## Research and asset provenance

- [OSHA workstation work process](https://www.osha.gov/etools/computer-workstations/work-process):
  keyboard/mouse interaction, posture variation, looking away and short stretches/rests inform
  desk motion. These are artistic references, not a medical feature.
- [BLS editors](https://www.bls.gov/ooh/media-and-communication/editors.htm): reading/revising
  content informs paper/notebook gestures. Other role mappings are artistic choices; props
  never assert a performed backend tool call.

Procedural city sprites/gesture frames are original drawings authored locally in project
source. No external artwork, game animation, assets, fonts or libraries were downloaded/copied.
No Blender/Unreal/new GPU infrastructure required; no audio added.

## Motion and guards

Configured ceiling: 12 paints/second, not a measured FPS claim. Sprite cache remains bounded
at 512 compact frames; sky masks/colours remain cached. Cosmetic time freezes for disconnected/
stale data, replay, hidden tab, parked/signed-out state and reduced-motion preference. Real clock
updates independently. Zoom/pan/fit, mobile page scroll, menus, Owner policy and scheduling stay.

## Files

- `frontend/src/pixel_office.js`: single hover label, no border, live cosmetic clock/scheduling,
  city integration, visible foreground hands and truthful paused label.
- `frontend/src/pixel_people.js`: independent role/state gestures and original pixel tools.
- `frontend/src/pixel_life.js` (new): town animation, clipping and motion guard.
- `frontend/src/pixel_sky.js`: cached cloud contours drift without replacing approved assets.
- `config/pixel_office.json`: motion rate/cycles, street geometry and palettes.
- `frontend/tests/pixel_life.test.js` (new): role/gesture/guard/weather/bounded-actor regressions.
- `frontend/tests/e2e/pixel_life.spec.js` (new): actual Canvas changes for all eight fixture staff,
  street, sip/stretch poses, all freeze guards and unchanged IDs/runtime/seats.
- `frontend/tests/e2e/pixel_navigation.spec.js`: hover duplicate/border regression while one
  tooltip and pointer/keyboard/mobile navigation survive.
- `frontend/package.json`: all three bounded checks under `test:scene`.
- `frontend/dist`: rebuilt through canonical builder with current truthful source hash.

## Verification actually performed

Hover bug reproduced first: one duplicate canvas name and one character rectangle. Then
846 frontend cases, TypeScript check, three isolated actual browser cases and 53 scoped
backend/layout/weather/documentation cases pass. Fixtures explicitly exercise working,
thinking/reviewing and weather; those captures do not claim production performed those jobs.

Separately authenticate to the actual running UI, permit GET/HEAD reads only and record the
canvas for eight real seconds after login. All eight actual employees are ACTIVE/IDLE in both
observations; all eight animate and all eight character raster hashes change. Traffic changes
too. IDs/runtime states stay unchanged; duplicate canvas name/hover border/page errors/refused
requests are zero. At 21:06 the real weather readout is Senin 18°C. Video frames at 1/4/7 seconds
were visually inspected. Actual clip (7.886 seconds): `data/pixel-life-2026-10-08/studio-life.mp4`.

Served JS/CSS respond 200 and match built files byte-for-byte; source/build hashes match.
Readiness remains 200 HEALTHY. No production DB/policy/provider change, worker restart or paid
model/media/GPU call was initiated by this refinement. Full Owner workflow suite was not run;
its earlier guard limitation remains separate. Existing >500 kB JS warning remains (521.19 kB,
gzip 173.67 kB). These graphical checks are not a hardware/FPS benchmark.

Concurrent LOCAL_AUTO_LOGIN changes were detected and preserved; the canonical build includes
the current combined source. The running server was not restarted to activate that new route.
Actual verification enters through the existing fallback form when the live route is absent.

Evidence, actual captures/video, structured verification and logs: `data/pixel-life-2026-10-08/`.
Rollback: restore only this task's source/config changes from `before/`, remove the new
pixel_life module and its tests, then rebuild current frontend sources. The dist ZIP is a
point-in-time backup: replacing the whole bundle would also revert concurrent entry changes.
Preserve production DB, other task changes and earlier navigation/night fixes.
Refresh with Ctrl + F5; no server restart is required for the graphical update.
