# The towers by day — prepared, never run in Unreal

Prepared on 2026-09-24 for the next live-HQ rebuild window. Nothing in this folder has run inside
Unreal or Blender yet, and nothing here is wired into `rebuild_live_hq.ps1`.

Why it exists: at noon the live stream's skyline reads as navy "blue cardboard" with lit windows,
because the tower facades' navy and their lit windows are baked into the export's window textures
(`art-source/unreal/bake/<name>_win_color.png` / `_win_emit.png`, dusk albedo 0.005-0.03). No value
the backend sends at run time can give them a day. The Blender day plates already solved the same
towers (`art-source/blender/hq/hq_day.py`); this carries those numbers to the level.

| File | What it is |
|---|---|
| `towers_day.py` | The pure part: glass masks and window ranks from the bake PNGs on disk (numpy, Pillow). |
| `textures/` | Its output: `T_HQ_TowerMask_<name>.png` for the 12 facades and `towers_day.json`. |
| `towers_day_hq_live.py`, `trees_day_hq_live.py`, `sign_hq_live.py` | In-place Unreal passes on the saved level (facades, leaves, the torn sign). Each fails loudly on a UV, chain or compile problem. |
| `day_state.py` | Adds a `day_state` key to `env_report.json` (atomic, with a backup), and a preview driver for the new parameters. |
| `day_pass.ps1` | The window procedure (dot-sourced; runs nothing on load): Preflight, Backup, Masks, HoldReport, StopStream, Pass, Merge, StartStream, DriveDay, Release, Rollback. |
| `backend_day_state.patch` | The backend side for `unreal.py` (reads `day_state`, sends TowerDaylight / WindowsOn / LeafDaylight). |
| `backend_day_state_scene_params.patch` | Written against `00d92ce`; **stale** since `15960b3` rewrote `scene_params.py` — redo by hand. |
| `test_towers_day.py`, `test_day_state.py` | Offline tests for the pure parts (need numpy and Pillow; not in the repository's test path). |

Before a window: at least 16 GB of projected free commit, no game of the Owner's running, and the
Owner's go-ahead. Gates, as for every window: the build frame against the reference (≤ 6.4), p95
frame time, the dusk instant (≤ 6.8), noon / 18:50 / morning / night previews, keep or roll back.
