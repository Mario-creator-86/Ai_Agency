# UI framing audit — 2026-10-17

Scope: UI only. No backend, accounting, provider settings, production actions or media changed. Existing user CSS and running process preserved.

## Inspected
- Research: trends, topic form, recent topics, sources/claims, scripts.
- Media: storyboards, scene details, shooting sheet, Character Bible.
- Publishing: channel slots, readiness gate, history.
- Workforce: all eight people, measurements, proposals.
- Journal: episode cover, expanded script/Director notes, closed days.
- Daily run: company overview, preflight, schedule, runs, work queue.
- Autonomy/Finances: overview, budgets/costs, model prices.
- Settings: all six tabs, top and bottom of longer sections.
- Decisions: waiting and history; eight agent inspectors, expanded inspector, correspondence.

Main pass: 121 baseline and 130 revised views at 1920, 1366 and 390px. Supplement: 26 views including 2542 and 768px, eight inspectors, correspondence and shooting sheet. 13 views with 200% text. Final navigation check: 15 views. Final staged and installed checks: 43 each at 1366px, zero page errors/visible overflow. Screenshots and machine-readable geometry in output/ui-all-tabs-2026-10-17/. Visual contact sheets inspected; the early lazy-layout gap found in scripts was corrected and the final installed screenshot inspected.

## Corrections
- Bound research form actions to their fields; wrap full trend titles.
- Keep section heights stable and use native scrollIntoView for lazy content; queue now has a direct rail link.
- Remove paragraph-width limits from structural Journal and run-stage grids; wrap long plan fields.
- Give Character Bible readable tracks and workforce metrics full aligned columns.
- Group budget/spending separately from provider cost cards, retaining every existing calculation and value.
- Two readable columns for media connection configuration; independent card heights avoid oversized empty interiors.
- Restore compact native checkbox/radio geometry and inline labels; space channel policy fields correctly.
- Keep active Settings tab visible after repaint; align sparse section content at the start.

## Verification and install
980 frontend tests, TypeScript, dialog browser regression suite, Vite build, documentation integrity and whitespace checks passed. Regression checks cover actual production-default checkbox geometry, selected mobile Settings tab visibility, queue navigation and prior dialog fixes. Browser inspection permitted only GET against the existing local server, blocked WebSockets/external origins and every mutation; occasional periodic YouTube verification POST attempts were blocked, never sent. Does not certify production execution or external provider access.

Installed index/JS/CSS hashes match HTTP-served bytes; source build record is current. PID 41588 / creation 1792184568.4750862 remained unchanged. No start/restart command. Existing >500kB bundle advisory remains. Backups and install proof are beside the screenshots.
