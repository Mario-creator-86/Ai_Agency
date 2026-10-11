# Backend animation and front profile acceptance — 2026-10-09

Owner requests: test actual backend updates of status/animation; turn the faces in agent
profiles toward the viewer and add a role-specific background. Eight front portraits now
appear in inspectors, employee cards and requester profiles. Separate seated office ensembles
keep looking at their monitors. All eight front headers have been visually inspected.

## What changed

Original front art is identity/appearance/role-bound and uniformly cropped without facial
stretching. Director library/window, scientific research room, evidence boards/library,
writing room, voice booth, editing monitors, publishing console and accounting books.
Unknown/changed profiles use their own frontal fallback. Backend state/lifecycle facts remain
live, outside the portrait. Source: art-source/pixel/front-portraits-v10/README.md; config/pixel_portraits.json.

The isolated real backend baseline exposed a synchronization defect: live outbox payloads
omitted aggregate_version. Runtime changed to WORKING while frontend version stayed 1 and
backend intent version became 2, so the correct safety guard refused animation. Future live
payloads now carry the committed version, matching replay serialization. Changed scalar
state/version/lifecycle signatures queue an immediate configured debounced policy read.
Reads serialize, late Owner-context replies are rejected, mismatched/failed reads retry within
a bounded configured interval, and no matching authorization means no gesture.

Existing old/queued events without versions trigger a coalesced authenticated committed-layout
read. The page never guesses versions. This compatibility path works with the currently
running backend, so the local page update does not require a production backend restart.

## Actual backend acceptance

Command: npm run test:agents --prefix frontend. One browser/page, production frontend built
into a temporary directory, fresh disposable DB and existing Python server. Paid providers
are replaced; outbound sockets are denied. Actual DB commits, durable outbox dispatch,
WebSocket events and authenticated Owner layout/presentation/snapshot reads are exercised.
Exact eight scene identities are bound only in fresh version-1 test records with FK checks;
immutable event history stays unchanged and new identity events are appended.

- 48 transitions: every employee through WORKING, THINKING, REVIEWING, BLOCKED, ERROR, IDLE.
  Exact committed version, state badge/text, matching authorized action cycle and own desk
  location checked. Recorded final transition latency: 1.607–2.168 s for each full eight-person
  batch under this local run; this is an acceptance observation, not a performance guarantee.
- All eight cropped painted character regions changed in 18 sampled frames each.
- Pause shows the actual lifecycle, switches monitor off and holds the painted body; resume
  restores authorized movement. Runtime and lifecycle remain separate inspector facts.
- Rapid changes retain latest committed REVIEWING. Late old policy cannot rewind state or
  authorize old gestures; the latest policy is read again. Legacy versionless events repair
  through actual authenticated layout reads (2.368 s for eight people in the final run).
- Missed WebSocket state recovers through ordinary HTTP reads, then reconnects without rewind.
  Failed main snapshot freezes everybody; fresh authenticated recovery resumes them.
- All eight front profile headers use the native atlas, exact role and distinct rendered art.
  23 policy responses and 69 actual WebSocket frames; zero page errors.

Final bounded backend/page run: 1 pass / 0 failed / 0 skipped, 84.219 s. Baseline failure and
missing-event-version.json remain alongside the passing verification.json for diagnosis.
This proves the backend-to-page pipeline with controlled disposable data, not paid-provider
production behavior. No production employee commands or GPU/upload jobs were issued by this
acceptance task. Existing full owner_flows game/resource guard remains untouched.

## Additional verification

909 frontend units pass; TypeScript check passes. Eight sequential bounded scene cases pass
across two lanes: life/living (2 pass, 108.142 s) and environment/navigation/motion/seating/
street/depth (6 pass, 75.960 s). Updated legacy fixtures to supply explicit matching intent
and reread it after park/unpark. Living fixture renders at the supported 250 ms catch-up
boundary while the solver retains 16.67 ms substeps; six modes and 360 physical checkpoints
remain. Its no-video run verifies monitors/art, bounded contacts/props, original audio/mute,
expiry/freeze and context cleanup; actual movie codec acceptance is prior living-studio
history, not repeated or claimed as production film proof here.

The initial legacy life fixture lacked policy and the initial living browser deadline was
exceeded on this machine. Both were corrected as above; no production safety gate was removed.
72 final scoped backend/documentation cases pass in 12.56 s (publisher, e2e server, phase3
office, presentation, event authentication and four documentation files). Documentation
inventory/architecture integrity and repository scan pass; 1104 scanned files, 68 existing
reviewed findings, baseline/detectors unchanged. Targeted Ruff check/format pass. Final live
delivery results are recorded in verification-summary.json beside the evidence.

## Local delivery and limits

Frontend rebuilt with the existing launcher build-record mechanism; static files are served
by the existing local backend without restarting it. Actual read-only profile/roster/390 px
phone checks, byte-identical JS/CSS/portrait delivery and hash freshness are saved in
live-profile-verification.json. The approved studio base image remains byte-identical.
The employee roster now joins its place/order to actual seated pixel positions, removing the
obsolete false «fără birou» label. No menus or desk coordinates changed. New outbox serializer source takes effect at the next
ordinary backend startup; legacy repair already handles the running older event format.
Concurrent RunPod/film changes and their separate acceptance limits are preserved.

Evidence: output/playwright/backend-animation-2026-10-09/ (verification.json, screenshots,
live-profile-verification.json and before/). Art/prompt: art-source/pixel/front-portraits-v10/.
Rollback: restore our backend/services, config/presentation, frontend/main and pixel_office
files from before/ with attention to concurrent later edits; remove new portrait import/path
and rebuild. Prefer keeping the compatible aggregate_version field and its regression test.

## Owner follow-up — clean portraits

The Owner rejected the «în așteptare» badge over the face. Removed the inspector image badge
and its obsolete update target. On employee cards, moved the actual work state into the facts
beside the image; lifecycle stays separate. All eight image wells are now free of state labels.
No art regeneration, backend/state/action changes or chair changes. Existing actual state
fields/header metadata still update through the tested event/HTTP pipeline.

909 units and TypeScript pass after this markup/CSS-only follow-up. Rebuilt local frontend,
then actual read-only Playwright asserts zero overlay nodes in all eight inspector portraits
and roster images, eight separate roster state facts, actual header state, mobile bounds,
source freshness and identical served JS/CSS/PNG. Zero page errors/refused requests; readiness
200. Screenshots live-portrait-*.png/live-roster.png/live-portrait-phone.png now show the clean
current portraits. The 48-state backend and eight scene tests above precede this small display
change and were not needlessly repeated. Rollback: before-portrait-label/ in the evidence folder.
