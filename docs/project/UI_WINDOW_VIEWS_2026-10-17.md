# Window views and frame correction — 2026-10-17

Owner scope: fix day/night mismatch and scenery through the five illustrated windows; then correct damaged frames reported in the first installed pass. Frontend only, no server restart or production command.

Implemented:
- `pixel_windows.js`: cached runtime compositor using only the approved existing background artwork. Source crops come from the actual exterior at the same world height, with the same outdoor sky, light and observed weather. No image was regenerated or overwritten, no external asset/license introduced.
- `config/pixel_office.json`: five glazing apertures, native-artwork-aligned frame bars and foreground occluders. Other config data verified equal to the original backup.
- `pixel_office.js`: draw the window view before indoor life, chairs, people and monitors. Same live/replay solar moment; no independent window clock.
- Frame correction after Owner feedback: replaced colour-selected glazing with complete traced apertures, separately protecting the original mullions/transoms. This removes fragments of the old panorama/utility lines and preserves frame pixels. Lamps, plants, globe and foreground desk objects occlude the view.

Verification:
- 982 frontend tests, TypeScript and Vite build pass.
- New isolated browser test renders day/dusk/night at native artwork resolution. Every window changes, night is darker; no pixel outside apertures changes, every traced frame pixel stays unchanged, foreground lamps/globe remain. Test evidence: window-tests.log and windows-*.png.
- Existing environment browser suite passes: protected interior patches, real-time clock/weather lifecycle, day/night/replay/visibility behavior. One former interior comparison patch moved off the deliberately changed glazing onto a shelf.
- Current running app reviewed at 1920, 1366 and 390px; additional day/dusk/night scene checks and enlarged frame detail with all eight real agents. Browser restricted to local GET; WebSockets, mutations and external origins blocked. Zero page errors or mutation attempts. Controlled time cases are isolated review views, not changes to production state.
- Served index/JS/CSS hashes match installed files, source build record current. PID 41588 / creation 1792184568.4750862 unchanged throughout. No start/restart command.

Evidence and backups: output/ui-window-views-2026-10-17/. Latest installed-frame-detail.png was visually inspected. First-pass source/config retained in before/ for comparison. Existing >500kB bundle advisory remains; the view is an illustrated crop projection, not a 3D reconstruction. Existing background and all unrelated user changes retained.
