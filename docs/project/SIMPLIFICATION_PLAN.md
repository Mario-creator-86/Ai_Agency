# Simple autonomous pixel studio — 2026-10-08

Owner explicitly requests simplifying the existing project, removing Treasury, replacing the
agent/environment UI with stylish pixel art inspired by A Space for the Unbound, and keeping
the remaining menus. Existing AUTORUN authorization covers routine implementation/design choices.

## Design and boundaries

Retain production, agents, research/evidence, QA, assets, integrations including RunPod,
durable workers/scheduling/recovery, publishing permissions, approvals, STOP and actual spend caps.
Remove Treasury, virtual financing/funding/minting and VR$ from the active product/API/UI.
Historical records remain recoverable; existing provider costs/budgets are essential, not Treasury.
No paid jobs, changed autonomy permissions, real publishing or data deletion as a side effect.

Approaches considered: reskin the Blender scene (keeps substantial complexity); force Unreal pixel
postprocessing (adds runtime/GPU dependencies); replace with a lightweight browser 2D pixel scene
(chosen: simple, inspectable, independent of GPU tooling, deterministic staff projection).

Visual direction verified on the publisher's official page and screenshots:
https://www.togeproductions.com/project/a-space-for-the-unbound/
https://store.steampowered.com/app/1201270/A_Space_For_The_Unbound/
Use an original cinematic side-view neighbourhood/studio, foliage, warm windows and layered sky.
Do not reuse game artwork/characters/logos. New scenery is decorative; working state and speech
come exclusively from backend projections/events. Every employee stays selectable by pointer
and keyboard, with the existing inspector/chat. Respect reduced motion and stale/disconnected data.

Palette: ink #222538, plum #4b3556, sky #e9a786, leaf #1e3940, teal #69ada3, paper #f4dfb4.
Typography: preserve existing menu text/fonts for legibility; crisp pixel character/scene rendering.
Layout: existing header/menus → large pixel stage → compact status/agent strip. Existing operational
drawers/dialogues remain accessible. Treasury's menu/dialogue is removed.

```
 [existing menus] [Decisions] [Settings]
 ┌────────────────────────────────────────────┐
 │             original pixel studio          │
 │   research · writing · editing · director   │
 │      selectable real employee characters   │
 └────────────────────────────────────────────┘
 [actual state] [employee list] [zoom/reset]
```

## Execution and verification

- [x] Read current architecture/state and preserve the dirty source in data/simplification-backup.
- [x] Research reference; choose compact architecture/art direction and record Owner override.
- [x] Retire Treasury UI, API and active feature claims; preserve cost/budget functionality/data.
- [x] Add one understandable autonomy-settings overview reusing existing versioned commands.
- [x] Replace active legacy 3D/stream scene with original pixel environment/characters.
- [x] Verify agent selection/chat, menus, responsiveness, truthful states and reduced motion in browser.
- [x] Run scoped backend/UI regressions, lint/types/build/docs/secret checks; fix defects.
- [x] Update current status/decisions/roadmap/changelog, spec precedence and handoff with real evidence.

Backups/archives preserve previous RunPod/local-provider work. Do not stage unrelated modifications.
