# Ambient street and local clock — 2026-09-10

> **Superseded on 2026-09-13** by `HQ_LIVING_OFFICE.md`: the office is now the Blender-rendered
> AMN-AI headquarters; the modules and assets described here were removed from the frontend.

Owner-requested extension of the pixel office exterior. This is decorative fiction, explicitly separate from real agent messages and workflow events.

## Implementation

- `frontend/src/street_life.js`: session-seeded RNG (crypto seed in the browser, injectable fixed seeds for tests), ten vehicle silhouettes, randomized colors/speeds, collision-safe vehicle replacement outside the viewport, depth sorting, pixel-circle rasterizer, bounded street actor lifecycle and shuffled ambient dialogue.
- Models: sedan, hatchback, wagon, SUV, coupe, pickup, taxi, van, minibus, bus. Tires use circular scanlines, not square rectangles. Entire far-lane vehicles render before the near lane, fixing the wheel-over-bus artifact.
- Activities: walking, dog walking, running, cycling, skating, phone conversations, a smoking stop, visibly annoyed walkers, cats. Spawn timing, appearance, direction, speed and pause timing vary. Actors leave at street edges; they are replaced rather than always looping the same cast. Birds vary their next trajectory and are hidden at night.
- 48 ambient phrases are shuffled without repeats until the deck is exhausted, then reshuffled without a repeated boundary phrase. These are a finite authored vocabulary, not LLM output or claims about actual people. Small bubbles say DECOR; the street clock label also identifies the decorative scene.
- `frontend/src/office_engine.js`: consumes the simulator, draws activity props and state-specific ambient poses, respects existing office event mappings. Pixel art for workers remains deterministic and independent of ambient RNG.
- `frontend/src/office_scene.css`: isolated scene/dock styling, imported by the page. Its scoped selectors prevent shared fullscreen rules from stretching the camera dock. Compactness is checked in browser QA.

## Time semantics

Uses Europe/Bucharest time from the device clock, including daylight-saving changes, rechecked at least every minute including after a hidden tab resumes. The exterior seven-segment display shows HH:mm in 24-hour format. Daylight blends across a stylized dawn (05:30–07:30) and dusk (18:30–20:30). This is not a geolocation/seasonal astronomical sunrise calculation and does not fetch weather or a timezone service. The clock label identifies Bucharest.

The weekly schedule now lives in `frontend/src/street_schedule.js`. Activity weights, vehicle weights, traffic admission and population targets blend between hourly anchors. Typical visible-scene targets range from 3 in a quiet worknight to 17 during a busy commute or Friday/Saturday evening; these are art-direction limits, not real population measurements.

- 06:00–08:00: early walkers, runners, dogs and cyclists alongside commuters; weekends start more quietly.
- Around 10:00: workdays favor commuters with briefcases and transit; weekends favor leisure, shopping and groups, while still allowing workers.
- Lunch/afternoon: ordinary errands, shoppers, small groups, walkers and cyclists.
- 17:00–20:00: weekday journeys home, runners, dogs and shopping, with busier traffic.
- Friday/Saturday evening: more coordinated groups and partygoers, more taxis. After midnight, Saturday belongs to Friday's outing and Sunday to Saturday's. Sunday evening and Monday night settle down again.
- Quiet nights still allow ordinary pedestrians, small groups, phone calls, dogs, cats and an occasional runner. The former cats/runners-only rule is removed.

Groups have 2–4 members with a shared direction and speed, individual appearances and preserved spacing. A scene-level group budget reserves room for ordinary passersby; even quiet nights can admit a pair. Existing characters leave naturally when density falls; new admissions slow down. Commuters, shoppers and partygoers have distinct clothing/props. Late-night dialogue omits closed-shop errands and daytime bus claims. Vehicle selection is weighted once per new vehicle: commuter periods favor buses and work traffic, nightlife favors taxis, and buses/minibuses are absent from new deep-night selection. Replacement remains offscreen and collision-safe.

The current minute is checked cheaply every frame; schedule weights and cached sky are recalculated only on a minute change. This preserves responsiveness to the actual local clock without recalculating the weekly schedule at animation frame rate.

## Evidence

- Frontend typecheck and production build passed.
- 33 frontend tests passed. New tests cover the local-hour schedule, seeded RNG/model coverage, painter depth, circular wheel silhouette, phrase shuffle, bounded population/night transition and 20,000 simulated traffic steps with randomized replacement and positive gaps.
- Browser QA with fixed clocks at 12:00 and 03:00: the initial fixed-hour baseline (superseded by the weekly schedule below); zero page errors; compact fullscreen dock. Visual fixture explicitly tested the activity set and overlapping buses in an isolated database, without backend writes or provider calls.
- Existing browser desktop/mobile/agent selection checks also passed after this change.
- Artifacts: `output/playwright/street-12h.png`, `street-3h.png`, `street-activities-fixture.png`. The fixture is for visual QA only, not operational evidence.

No schema changes, external generation charges, social messages or provider calls. Architecture documentation remains unchanged. This is a bounded initial set of everyday situations, not an exhaustive simulation of real life. Future extensions should use this ambient lifecycle rather than create fake domain events.


## Weekly rhythm verification (supersedes the original fixed-hour population rule)

33 tests pass, including all 10,080 minutes of a week, weekday/weekend comparisons, Friday-to-Saturday midnight continuity, probabilistic vehicle-mix sampling, group movement/capacity and quiet-night variety. Browser scenarios cover Monday 07:00 and 10:00, Tuesday 01:00, Saturday 01:00 and Sunday 21:00, with zero page errors. Desktop/mobile and operational agent selection checks passed separately. Screenshots are `output/playwright/weekly-*.png`. These are isolated visual QA scenes with fixed clocks, not evidence of operational jobs. Scope released; backend and concurrent personnel/dashboard changes preserved.


The Bucharest clock is now a freestanding LED street display on the right pavement, with a sculptural support inspired by the Owner references. Scene CSS is emitted as a separate same-origin asset (?no-inline) to comply with CSP. Browser QA asserts the stylesheet is loaded and controls sit at the bottom, including fullscreen.
