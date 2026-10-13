# Pixel navigation and night — 2026-10-08

The Owner reported that the desktop scene could not scroll, its lower floor/street was
cut off, and the exterior was grey at 20:10 instead of showing night and a moon.

## Changes

The desktop page intentionally uses a fixed frame with independently scrollable menus.
The pixel stylesheet's 16:9 aspect ratio overrode the desktop renderer's auto ratio.
At the reproduced 1700 × 1100 viewport, the frame was 1006 px tall but the canvas was
956.25 px. Restore auto aspect ratio on desktop; the whole image now fits the actual
frame. At 1366 × 768 the rooftop, all floors, street and clock also fit.

The previous renderer only recoloured the exterior with a `color` blend and grey overlay.
Use coloured multiply lighting and a cached sky layer instead. Preserve the original
cloud contours, plants, roof and skyline; replace the original painted sunset sun with
solar-controlled sky/sun/moon/stars. Solar elevation uses the existing date/location
calculation and Europe/Bucharest timezone, including DST. The moon and stars are stylistic
night indicators; this is not a lunar-phase or astronomical-position calculation.
Existing live weather controls precipitation and dims celestial lights; stale/missing data
still says unavailable and adds no invented rain/snow. Furnished interiors stay protected.

## Navigation

- `Încadrează` fits the complete scene and resets offsets.
- After enlargement, wheel/trackpad scroll or pointer/touch drag pans the scene.
- Shift + wheel pans horizontally. Ctrl/Command + wheel zooms around the pointer.
- Offsets clamp to the artwork on resize/zoom. Wheel at an edge is not captured.
- Phone/short-screen native page scrolling remains available at fit.
- Agent clicks, keyboard selection, menus, autonomy policy and live data remain intact.

## Files

- `frontend/src/pixel_studio.css`: desktop ratio fix.
- `frontend/src/pixel_navigation.js` (new): viewport math and bounded offsets.
- `frontend/src/pixel_office.js`: navigation and sky integration.
- `frontend/src/pixel_sky.js` (new): cached sky mask, twilight colours and celestial pixels.
- `frontend/src/pixel_environment.js`: coloured exterior lighting.
- `config/pixel_office.json`: sky geometry/palette; original image unchanged.
- `frontend/tests/pixel_navigation.test.js`, `pixel_sky.test.js` (new): edge/solar regressions.
- `frontend/tests/e2e/pixel_navigation.spec.js` (new): actual page markup/CSS, isolated browser.
- `frontend/tests/e2e/pixel_environment.spec.js`: moon/sunset and upper-room pixel protection.
- `frontend/package.json`: both bounded browser checks in `test:scene`.
- `frontend/dist`: rebuilt via the canonical launcher builder, with truthful source hash.

## Actual verification

826 frontend unit tests pass; TypeScript check passes; 53 scoped desk/layout/weather and
documentation tests pass. Both bounded browser cases pass: actual CSS layout, wheel/drag,
Ctrl zoom, fit, mobile native scroll, agent pointer/keyboard selection; real Canvas day,
sunset/night, rain/fog/snow/storm, moon pixels, protected interiors and lifecycle guards.
Component weather/phases use explicit test instants/observations; those pictures do not
claim an actual storm or actual historical weather. A sky-edge visual seam was reproduced,
covered by regression tests and corrected after screenshot inspection.

Separately, authenticated read-only navigation of the running production UI succeeds:
eight real agents at their desks, current Bucharest clock/weather, no page errors or rejected
requests. At 20:36 the readout was Senin 18°C, and the moon is visible. The canvas and frame
are both 1006 px tall. Zoom/scroll/fit controls were operated on that real page. Served JS
and CSS respond 200 and match the built files byte-for-byte. Source and build record match.
Production worker/policy/data were not changed or restarted. No paid model/GPU/media calls
were initiated by this repair. Full owner workflow suite was not rerun; its earlier guard
limitation remains separate. The existing >500 kB JS bundle warning remains (513.06 kB).

Evidence and rollback: `data/pixel-navigation-night-2026-10-08/`. Before-source copies and
served dist ZIP are under `before/`; red/green browser captures, test logs, structured final
verification and actual `live-studio-night.png` are retained there. Restore the before files
and dist ZIP to undo this UI change. Keep current production DB/policy untouched.

Refresh the browser with Ctrl + F5 to load the rebuilt frontend. No server restart needed.
