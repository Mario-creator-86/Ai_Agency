# Raised office chairs and Nadia desk orientation — 2026-10-09

Original transparent artwork edited with the built-in imagegen tool, from the v7 employee
references in this project. Generated-output provider terms apply. No game sprites or sound
samples were imported. The earlier v7 source/drafts are retained alongside this folder.

Production files, copied byte-for-byte:

- `staff-a-chair-v8.png`: Sarah, Aris, Elena, Marcus. Source generation
  `exec-644b6574-4cc7-4480-b6da-5e68f32d49bc.png`.
- `staff-b-chair-v8.png`: Lyra, Kael, Vera, Nadia. Source generation
  `exec-ae7e793e-8a30-448d-b71a-fcd622a3c6b4.png`.

Four columns: desk attention, thinking, coffee and hair correction. Four equal rows, native
RGBA dimensions and hashes registered in `config/pixel_actors.json`. Exact prompts are in
`prompts.json`. No Python raster editing or resampling was used. Registration examines alpha
components, native bounds and caster baselines; Canvas renders the original pixels at runtime.

The Owner requested a higher seat for every person and a slight diagonal posture for Nadia.
The new art raises the chair seat and seated body over a longer stem, with shoes/casters on
the same ground plane. World height adds 5.4 px while the shared 0.9 character scale remains.
Nadia and her beige caster chair use a rear-left view. Her monitor plane is desk-oriented,
with a physical bezel and stand. Current per-seat geometry is in `config/pixel_office.json`.

Runtime keeps one fixed chair/lower-body ensemble and blends only the registered upper
human regions. A per-frame mask protects Nadia's angled chair. Head/wrist joints and damped
pose weights stay bounded; action permission comes from the real server state/version.

Proof, limitations and rollback: `docs/project/PIXEL_LIVING_STUDIO.md` and
`output/playwright/living-studio-2026-10-09/`. `before-ergonomics/` preserves the preceding
calibration. Reproduction helper: `register_ergonomics.py` in that evidence folder; original
generator paths are recorded above and the source PNGs here are sufficient to re-register.
