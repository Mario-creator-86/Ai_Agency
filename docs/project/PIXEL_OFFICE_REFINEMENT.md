# Pixel office visual refinement — 2026-09-10

> **Superseded on 2026-09-13** by `HQ_LIVING_OFFICE.md`: the office is now the Blender-rendered
> AMN-AI headquarters; the modules and assets described here were removed from the frontend.

## Scope and art direction

Owner-requested visual refinement of the existing cutaway office, preserving its pixel rendering and backend layout. Midnight blue exterior, warm walnut, muted department colors, ceramic planters and restrained brass/limestone edges. Geometry remains snapped to world pixels; smoothing stays disabled. No generated images, external asset dependencies or new purchased inventory objects.

- `frontend/src/office_art.js`: reusable static botanical, wall-material and facade drawing functions. Existing decorative prop seeds preserve repeatable silhouettes.
- `frontend/src/office_engine.js`: warmer department walls, oak wainscot, acoustic texture, architectural courses, walnut desks, upholstered chairs, monitor bezels, tailored clothing, facial and hair shading, scarf detail, stepped foliage, vehicle trim and smaller stepped tires. Dogs face their actual walking direction, have distinct head/chest/legs/tail and a leash.
- `frontend/src/style.css`: taller scene, compact bottom camera dock, fullscreen positioning.
- `frontend/tests/office_engine.test.js`: regression for fitting a portrait viewport above the toolbar. Minimum zoom and toolbar clearance no longer crop the building on narrow screens.

Agent roster, names, model assignment, runtime states, speech bubbles, production tokens, lift dispatch and traffic spacing remain controlled by the existing state/projection code. Outdoor scenery is decorative. No backend changes or real provider executions belong to this increment. Existing role-derived character identity was preserved; persistent versioned character bibles remain a separate future capability.

## Verification

- `npm run check --prefix frontend`: passed.
- `npm test --prefix frontend`: 18 passed, including projection ordering, street geometry, traffic non-overlap, idle lift, event-driven courier travel and portrait framing.
- `npm run build --prefix frontend`: passed.
- `node output/playwright/office-review.mjs office-after.png`: passed against the isolated local test database, seven agents, real canvas click selected an agent, desktop/fullscreen/mobile screenshots, no page errors or horizontal mobile overflow. No model jobs launched.
- Main application at http://127.0.0.1:8000 serves the new JS/CSS bundles, both HTTP 200. No server restart needed for the static build.

Screenshots: `output/playwright/office-after.png`, `office-fullscreen.png`, `office-mobile.png`; before: `office-before.png`. These are local review artifacts and show the isolated test roster, not evidence of live agent work. Frame rate was not benchmarked and no FPS performance claim is made.

## Coordination and next work

This is a frontend-only visual increment. Concurrent ZCode media/backend changes were preserved and not certified by this UI check. The earlier broader Settings/audit work has its own tracking and needs reconciliation with the later third-party audit before a consolidated project report. The visual scope is released.

Further art iterations can refine bespoke room compositions without changing backend events. Keep material drawing in the art module and static caching in the renderer. Do not use presentation changes to invent jobs or inventory acquisitions.
