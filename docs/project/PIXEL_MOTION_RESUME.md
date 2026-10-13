# Pixel studio motion resume — 2026-10-09

## Diagnosis and verified scope

The Owner asks why the townspeople and agents do not move. Windows read-only
SPI_GETCLIENTAREAANIMATION returns false on this computer. The scene inherited
prefers-reduced-motion from the system and had no scene-specific control. On the real
served page with that preference emulated, authoritative data/socket were live, the page
visible, signed in and outside replay, yet lifeElapsed stayed exactly zero for three
seconds and all eight agents had animate=false. The same page without that preference
advanced 2961 ms: this is a motion guard, not missing sprite frames or missing backend work.
The Owner's existing Edge tab is not exposed to the browser connector, so its exact
matchMedia value was not inspected; the system setting and reproducible browser behavior
are evidence of the cause, not a claim of having instrumented that unavailable tab.

## Change

The Owner explicitly requests animation. config/pixel_office.json life.motion_enabled=true
is the scene default. frontend/src/pixel_motion.js binds one ANIMAȚII toggle in the existing
camera toolbar. Local on/off choice survives reload; denied browser storage still permits
session pause/resume. The scene uses that choice, while menu transitions and other interface
motion retain the system preference. No Windows setting changed.

Backend work/lifecycle states remain authoritative. A paused agent does not become working;
stale/disconnected data, replay, sign-out and hidden-tab guards remain. Existing eight seat
contacts, chair masks, original building and all 80 sprite frames remain unchanged.

## Validation

861 frontend unit tests, TypeScript and four bounded Canvas/browser tests pass. A new
regression exercises system reduced motion, initial animation, all pedestrian/bicycle
positions advancing, scene pause, persistence across reload, resume, stale data, replay
and parked timer cleanup. Owner-flow assertions were updated for explicit scene pause;
the full backend-writing owner suite was not run in production. 53 scoped backend/layout/docs
checks pass; scripts/check_docs.py integrity is verified separately.

Actual served UI, 08:45 București, Înnorat 12°C: all four pedestrians travel, bicycle and
leashed dog travel, both cats change pose/step, all eight real IDLE employees change visible
pixels. Verified with system reduced motion emulated; pause survives actual page reload
and resume works. Zero page errors/refused external writes. 390px mobile control fits.
The 15.916016-second H.264 clip is actual live Canvas capture, not a performance benchmark.
Frames at seconds 1 and 13 were visually inspected. The live tests permit only same-origin
GET/HEAD HTTP and the existing authenticated read-only event socket; no work states injected.
An inline diagnostic script was correctly blocked by existing CSP; read-only street geometry
was then loaded via a test-intercepted same-origin script without weakening CSP or changing
the served application. The failed instrumentation attempt made no backend command.

Launcher build record matches current sources; served bundle index-TazDWJpH.js equals disk.
/health/live and /health/ready return 200 HEALTHY (foundation scope). This verifies the UI,
not paid GPU/voice/upload/normal serial acceptance. Concurrent RunPod changes preserved.

## Evidence, source and rollback

- data/pixel-motion-2026-10-09/baseline-reduce.json and baseline.json: before-fix guard proof.
- live-ui-verification.json, build-health.json, mobile.json, verification.json: current proof.
- studio-motion.mp4, video-frame-1.png, video-frame-13.png, live-studio-actors.png, mobile.png.
- frontend/src/pixel_motion.js, main.js, frontend/index.html, config/pixel_office.json.
- frontend/tests/pixel_motion.test.js, tests/e2e/pixel_motion.spec.js and fixture entry.
- data/pixel-motion-2026-10-09/before/ retains source/docs and the preceding served dist.

No new artwork or downloaded assets, no provider/model/policy changes, no paid calls or
production server restart. Original building SHA256:
957e67d70e01438056c5e2f073a8b39d8152f2488ea28217df2368384b75dbe1.
