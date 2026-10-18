# Studio dashboard — design and implementation plan

Owner request: use the supplied dashboard reference for configuration, retaining the approved pixel scene. This supersedes the earlier small sidebar-only increment.

Layout: narrow permanent navigation, real activity column, central studio, and a right column ordered approvals → upcoming work → compact governance. Across the top: active projects, monthly budget, completed tasks, queued tasks, and one audience card for each configured channel. Remove the bottom employee strip and the long navigation tooltip. Retain employee selection in the scene and workforce menu.

Visual system: keep the existing Oxanium/display and sans/body fonts, midnight #171526 panels, violet #a77bea navigation accents, warm #f4dfb4 scene controls, teal #78bbaf success. Cards have a quiet outline and 8px corners. No fabricated graphs, GPU usage, audience changes or queue estimates.

Data: open unpublished storyboard films are the projects; technical workflows are excluded; tasks use the existing status-filtered queue reads, with capped counts labelled ≥100. Completed tasks are today's rows in the studio timezone, never daily-run stages. Monthly budget uses only the MONTHLY row, with monthly spend separate from the configured limit. Audience cards match publication channels to their authorised YouTube identity. Refresh through the existing channel verification endpoint, visibly labelled with YouTube's measurement time; hidden subscriber counts and failed refreshes remain unknown/stale. This uses existing backend contracts and changes no backend code or permissions.

Implementation, in this session without subagents:

- [x] Add pure dashboard data tests: missing vs zero, monthly vs daily, capped tasks, real queue order, bound channel identity, hidden subscribers, escaped names.
- [x] Add dashboard module and stylesheet; reuse existing menu controls and dialogs. Keep refreshes single-flight and invalidate pending answers on logout; pause polling when hidden and throttle external reads to 60 seconds.
- [x] Change workspace markup and minimal main/drawers hooks. Move detailed governance controls to the existing autonomy dialog. Keep approvals/letters actions intact; no paid generation or startup.
- [x] Browser-check actual renderer + dashboard at 1920/1700/1366/1280/768/390px, long content and enlarged text, keyboard navigation, selection, no overlaps/errors or clipped building. Run affected frontend tests, type check and production build.
- [x] Inspect captures, install only verified built frontend files locally with backup, update status/roadmap/changelog/decisions and the auxiliary handoff. Do not restart the application or claim live backend/provider acceptance from isolated fixtures.

Recovery: output/ui-dashboard-2026-10-16/before/ stores existing source files, including pre-existing sidebar changes. Preserve concurrent backend/doc work. Built-file backups recorded with installation evidence.

Outcome: complete UI implementation and verified local frontend installation; see CURRENT_STATUS for checks, limits and unchanged server proof. No server was started or restarted.

## Owner refinement — visual finish, 2026-10-16

Preserve the reference configuration and data behavior. Use coordinated SVG category icons, distinct metric figures and footers, balanced channel figures, clearer navigation states, aligned side-panel controls and compact confirmed-empty states. Executed and checked in output/ui-dashboard-polish-2026-10-16/. No server restart.
