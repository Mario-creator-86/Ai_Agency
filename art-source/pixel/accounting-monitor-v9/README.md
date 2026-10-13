# Nadia's upright desk monitor — original local repair, 2026-10-09

The Owner explicitly rejected the preceding slanted monitor. It projected content over the
original drafting board and its lower corner crossed the desktop; a minimum stand height
hid that invalid placement. This repair replaces the board with a normal upright LCD,
shaded bezel, visible pedestal/base and keyboard on the existing small desk. Nadia's v8
rear-left person/chair and the other seven higher office chairs stay unchanged.

Source: built-in OpenAI imagegen, precise-object edit of our existing approved
`frontend/public/assets/pixel/studio-detailed.png` (1536x1024). Original result:
`exec-6daff15f-f550-4d59-83cc-e4504626b840.png` in this chat's generated_images folder.
Exact prompt: `prompt.md`. Output is copied byte-for-byte into this folder and
`frontend/public/assets/pixel/studio-accounting-monitor-v9.png`, not raster-edited in Python.
Native size 1536x1024; SHA256:
`614fea16f97f174a9459271e3c929f1bc2858264a15ccc3efb5b9d2254ed9223`.
One built-in generation for this repair; seven in the whole living-studio phase, including
the four earlier v7 outputs and two v8 outputs. No game sprites or third-party monitor asset.

Provider-output terms apply to this generated original, as recorded for the preceding v8
originals; no external asset-pack license or exclusivity is asserted. The approved base
illustration remains unchanged. Runtime clips this source to the small configured monitor/
drafting-board repair polygon, not the whole generated picture. An isolated Canvas proof
finds 2430 changed pixels in that area and zero changed pixels outside its bounds.

Screen glass is registered to native pixels (733,738)-(770,760); live content is mapped to
that glass, keeping the original drawn bezel and stand. The support reaches desktop y=484,
with actual clearance below the panel. Invalid panel/desktop intersections are now refused
instead of silently shortening a stand. Nadia's gaze target is the glass center; floor
contacts, rear-left seating and 0.9 scale remain. Missing artwork preserves original furniture.

Actual Playwright proof: `output/playwright/living-studio-2026-10-09/monitor-verification.json`
and `nadia-chair-monitor-v9.png`; all eight scene cases pass. Source/build and backend
presentation guards are retained. Recovery: `before-monitor-correction/`, alongside the
existing task backups. Report: `docs/project/PIXEL_LIVING_STUDIO.md`.
