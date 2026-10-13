# Living pixel studio — verified local implementation, 2026-10-09

The Owner requested grounded feet, furniture contact, varied backend-driven actions and a
living studio with wind, monitors and sound. Later corrections require office chairs for
every employee, a higher seat, and Nadia seated slightly diagonally in front of her desk.
The existing cutaway building, employee identities, personal desks, menus and 0.9 shared
character scale remain. This continues the completed PIXEL_DEPTH_PHYSICS checkpoint.

## Seating, monitor placement and movement

All eight employees have individual caster office chairs. Original v8 sheets provide four
registered upper poses per employee; source, prompts and provenance are retained in
`art-source/pixel/living-studio-v8/`. Earlier v7 drafts stay as development history.
The seat/backrest and pelvis are higher over a longer hydraulic stem. World height rises
5.4 px; wheels remain anchored to the room floor. Nadia and her beige chair face rear-left,
with tucked feet and a small forward inclination toward her own desk/monitor.

Per-seat floor planes, soles/casters, neighbouring solid furniture and monitor gaze targets
are configured in `config/pixel_office.json`. The Owner rejected the preceding monitor:
the old drafting board remained behind the panel and a lower corner crossed the desktop.
The original validation missed that visible error. The final v9 local artwork replaces the
board with an upright LCD, shaded bezel, keyboard and visible pedestal/base on desktop y=484.
Only its configured small repair polygon is composited; an isolated pixel proof reports
2430 changed pixels inside and zero outside. The approved base PNG stays unchanged.
Glass is calibrated to native corners (733,738)-(770,760), and Nadia's gaze follows its center.
A regression check refuses panels intersecting the desktop instead of masking an invalid
support with a minimum height. The v8 raised rear-left chair/body remains unchanged.
Nine screen surfaces cover the eight workstations, including the Video Editor's two monitors.
Live content follows the physical glass through two clipped affine triangles; hardware stays fixed.

This is bounded 2D contact/joint physics: stable lower bodies/chairs, damped upper-body pose
weights, restrained head/wrist movement, fixed floor contacts and bounded reach. Pose
transitions preserve the static chair, with a separate mask for Nadia's angled backrest.
Loose paper responds to gravity, drag, actual available wind and registered furniture/floor
contacts; it bounces, settles and remains limited to eight objects. It is not a full 3D rigid
body engine. Original poses avoid the sideways leg/cabinet intersections seen in the report.

## Backend truth and room life

Owner-only `GET /api/v1/office/presentation` is read-only. It derives individual phased action
cycles from actual employee runtime/lifecycle/version and marks them `presentation_only`.
The UI rejects a mismatched or expired snapshot. Working, thinking, review and frustration
follow the matching real states; error/frustration never comes from random frontend emotion.
Coffee, hair adjustment, small repositioning and screen power are server-authorized cosmetic
actions. They do not write task progress, employee status or a production job.

Plant foliage moves subtly with indoor air and available observed wind. Papers can lift
from desks and settle; a few lamps dip softly for 750 ms once every 227–389 seconds.
The prior day/night/Bucharest weather, full-width street, cats, bicycle, detailed cars and
foreground depth remain. Paused, hidden, stale and replay views stop appropriate live motion,
sound and video. Signing out clears presentation/private media and rejects late fetch results.

A finite authenticated HTTP presentation snapshot bridges a temporary event-socket reconnect
while the main data snapshot remains fresh. Expiry, future timestamps and employee version/state
mismatches still reject movement. A separate real-browser rehearsal closed event sockets for
24 seconds: three actual HTTP policy reads kept all eight real IDLE employees authorized,
with scene/wall time ratio 1.000066 and no page errors or refused requests.

## Real media and original sound

Actual readable local rendered MP4s are authenticated through the existing media route,
inside allowed media roots, with one decoder and a 64 MiB fetch limit. Missing, oversized,
outside-root and simulated files are excluded. Confirmed processed public/unlisted YouTube
publications can open through the Film button in a correctly sized YouTube privacy player.
CSP permits that frame origin; scripts and API credentials remain restricted to this app.
Local video pixels can play on the small monitor planes during idle/review; work screens
display the real work state. Direct YouTube video pixels are not extracted from its player.

Actual library verification: two configured channels, zero confirmed playable publications
and zero eligible local films. The UI therefore shows its honest empty message. Decoding
and moving video pixels were proven separately with a labelled local codec fixture, never
registered as a real production film or channel item. Real channel playback remains dependent
on an eligible film; this work does not generate/upload a paid film to fill that gap.

Original local WebAudio synthesis supplies keyboard, cup, chair, paper, footsteps, birds,
wind and rain ambience. A Sunet click unlocks browser audio; enabled/volume preferences
persist. Sources are bounded, panned to their scene position, synchronized to authorized
actions/contact events, and suspended with the view. Gain was calibrated after a real
recording showed the first level too quiet. No game music or downloaded sound samples used.

## Verification and limits

- 898 frontend unit checks and TypeScript pass.
- Eight bounded Playwright scene checks pass; the final living case was rerun after audio
  calibration and covers late-response cleanup, actual codec pixels and audio unlock/mute.
- Six isolated runtime scenarios, 360 one-second checkpoints: IDLE, WORKING, THINKING,
  REVIEWING, ERROR and BLOCKED. All eight employees exercise distinct authorized actions.
- Seating: 481 samples over 60 simulated seconds, all chairs/soles stationary, upper joints
  moving; pause freezes the pose. Close-ups of all eight seats were visually inspected.
- Physics unit rehearsal covers 190 simulated seconds of paper flight/landing/bounds.
- 81 scoped backend/documentation/repository-scan tests pass. Final direct architecture
  inventory and repository scan results are recorded in PROJECT_STATE; baseline unchanged.
- New backend presentation tests: 15, including Owner access, no mutation/network, individual
  phases, unavailable media/root/size/simulation guards and the narrow frame CSP.
- Actual read-only UI: eight ACTIVE/IDLE employees, seven real idle presentation actions,
  visible motion for all eight, four moving pedestrians, bicycle/dog/two patrolling cats,
  four vehicle variants, real-time travel, sound activity, nine monitor surfaces, pause/reload/
  resume, no duplicate hover name/rectangle, zero page errors/refused requests.
- Nine existing dialogs, toolbar/roster, focus and Escape were checked on the served UI.
- A 32-second live H.264/AAC clip records the actual scene and original sound. Frame rate is
  the recorder's capture rate, not an asserted renderer benchmark.

The source is rebuilt by the canonical launcher helper. The actual instance was gracefully
reloaded after fresh queues showed no running/queued tasks; health and the new route answer.
No Owner policy/database commands or GPU/media/upload jobs were issued by this task.
External RunPod/paid-film acceptance remains separate from this local visual proof.
Final counts, build/served byte comparisons and scan results are in PROJECT_STATE and the
evidence below. There are no skipped cases in this scoped verification.

## Reference observations and provenance

The official [publisher page](https://www.togeproductions.com/project/a-space-for-the-unbound/)
and [Steam presentation](https://store.steampowered.com/app/1201270/A_Space_for_the_Unbound/)
were consulted. Visible footage/official loops show walking and direction changes, a resting
NPC reading a newspaper, interaction with progressive dialogue, and foreground vegetation
occluding people at a stable ground baseline. These informed cadence, idle variation and depth.
Office coffee/hair/monitor/chair actions are original responses to the Owner's requirements.
This is not an exhaustive animation catalog of the game or a copied game asset pack.

## Files, proof and rollback

Backend: `backend/app/office/presentation.py`, office router, narrow frame CSP in app main.
Shared calibration: `config/pixel_presentation.json`, `pixel_office.json`, `pixel_actors.json`.
Frontend: presentation, actor atlas, room life, screens, sound, office engine/main and studio CSS.
Tests: presentation/screen units, backend presentation, living scene and environment/seating
fixture adjustments. Implementation tracking and asset provenance live under `docs/project/`.

`output/playwright/living-studio-2026-10-09/` contains tests/logs, original backups, all-eight
chair close-ups, living/codec/audio proof, game-skill client shots/text, actual UI/dialog
proof, `nadia-chair-monitor-v9.png`, `monitor-verification.json`, `live-studio-clean.png`, `studio-street-motion.mp4`,
metadata and final integrity. `before/` preserves pre-task source/build; `before-ergonomics/`
preserves the preceding v7 calibration. `before-monitor-correction/` preserves the rejected
monitor/config/code and previous clip; v9 source/prompt/terms are in
`art-source/pixel/accounting-monitor-v9/README.md`. Seven built-in art generations were used
in the whole living-studio phase (four v7, two v8, one local v9 monitor edit). A pre-task app main copy removes only this task's
frame-src addition. Restore only these scene changes, preserve unrelated shared changes,
and rebuild with the canonical helper. The original building PNG remains byte-identical.
