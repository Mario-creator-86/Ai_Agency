# Front employee portraits — original local art, 2026-10-09

The Owner requested front-facing faces and a background matching each profile, illustrated
by the agent inspector header. This separate portrait sheet changes profile/roster portraits;
the seated office ensembles keep looking at their actual monitors.

Source: built-in OpenAI imagegen, one original generation using our existing staff-a-v2 and
staff-b-v2 identity/style references. Original output: exec-31dd2c50-2c72-4867-bc78-c7f48bfcc4b9.png
in this chat's generated_images folder. Exact prompt: prompt.md. The native 1774x887 RGB PNG
is copied unchanged here and to frontend/public/assets/pixel/staff-front-portraits-v10.png.
SHA256: `79a1a3987fc9afc38ab8503a0403cd837a928daf2ede1718c05128fcb2fd87f1`. No game sprite or third-party art was copied.
Provider-output terms govern this generated original, as recorded for the preceding original
studio art; no external asset-pack license or exclusivity is asserted.

Reading order (four columns, two rows): Sarah / Dr. Aris / Elena / Marcus, then Lyra / Kael /
Vera / Nadia. Backgrounds are the director's library/window, scientific research terminal,
evidence boards/library, writing corkboard, voice booth/microphone, editing timelines,
publishing console/map, and accounting books/calculator. Native crop coordinates are in
config/pixel_portraits.json. Uniform containment preserves facial proportions and hair.

Binding requires the exact employee identity, saved appearance and allowed role. Changed
appearance/role, unknown hires or missing art use their own authored frontal fallback, never
another person's generated face. Status/lifecycle facts outside the portraits continue to show backend data; image badges
were removed at the Owner's request.

All eight inspector headers were captured and visually inspected using the actual page in a
disposable backend. Evidence: output/playwright/backend-animation-2026-10-09/portrait-*.png.
Report: docs/project/PIXEL_BACKEND_ANIMATION_ACCEPTANCE.md. Recover renderer/main files from
that evidence folder's before/; remove only the portrait import/render path for art rollback.
