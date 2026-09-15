# Changelog

## A warm line under every office ceiling — 2026-09-15

In the Owner's picture a warm LED line runs under each office floor's ceiling, and the tops of the
rooms glow with it. L3 and L1 had no such line in the scene; L4 and L2 had thin ones, set back at the
rear wall.

- `hq_building.ceiling_cove()` adds a warm line under each office ceiling (L1–L4), hung just behind
  the slab's face so it shows from the front, and six small warm lights beside it on each floor
  (`cove_wash`, 18 W). They reach the live level through the full rebuild with the Blender export
  (4.8 minutes); the look pass scales the lights with `AMN_LOOK_COVE`.
- Compared in the stream (mean colour distance, 14.7 before):

  | Cove lights | Mean | Seen |
  | --- | --- | --- |
  | 1.0 | 15.7 | the lines show like the picture's, but the rooms read too bright (L2 88 against 79) |
  | 0.35 | **14.5** | L4 5.5 → 3.5, L3 17.0 → 14.2; the new default |

- Two regions moved away: L1 (7.5 → 10.3) and the roof sign (10.2 → 14.2). Row by row, all of
  that change sits in the rows where the new lines fall: they burnt at 129 and 103 where the
  picture's lines read 64 and 62. They share their material with the slab lines, which the look
  pass had raised to 3 times. At 1.5 (`AMN_LOOK_STRIP_GAIN`, the new default) the mean is **14.1**,
  the closest pass so far: L4 1.6, L1 9.6, the roof sign 12.5.

## Brighter ceiling strips on the live headquarters — 2026-09-15

In the Owner's picture a warm LED strip under each floor's ceiling washes the top of the walls. In
the live frame the top floor's strip is a thin line, and the floors below have none.

- `look_hq_live.py` raises the strips' emission (`edge_led_slab`, `edge_led_warm`, `edge_led`) to
  3 times the imported strength (`AMN_LOOK_STRIP_GAIN`; the imported value is recorded once, so a
  rerun stays the same). Compared in the stream: L4 came closer to the picture (7.8 → 5.5), the roof
  sign moved slightly away (9.1 → 10.2), and the mean stays at 14.7.
- L3 and L2 have no ceiling strip in the scene at all, so a factor cannot give them one. The strips
  have to be added in the Blender scene.

## Server LEDs and smaller skyline windows: tried, left off — 2026-09-15

Two more differences from the Owner's picture were tried in the stream and left off, because
neither brought the frame closer:

- **Server LEDs.** In the picture the S1 racks show rows of green lights; the live racks stand black.
  Every small light (rack LEDs, rack bars, the PCs' and speakers' LEDs, the infra room's grid) is
  baked into one shared emission texture, where it is averaged away. The look pass can give each its
  own colour again (`AMN_LOOK_LED_GAIN`, off). At the scene's strengths the rack bars and the grid
  glowed, but the LED dots did not. At 8 times their strength they still did not: each is 3 × 3 cm,
  under one pixel in the frame, and most likely lost with the imported mesh's smallest parts, while
  the grid's teal lines grew stronger than the picture's. Showing the LEDs needs larger lights in
  the Blender scene.
- **Skyline windows.** The skyline's windows are about 6 × 9 px in the frame, the picture's 2–3 px.
  Halving them through the facade textures' scale (`AMN_LOOK_CITY_WINDOW_SCALE=2`) looked finer by
  eye, but measured further from the picture (mean 14.7 → 14.9; the right-hand city 11.9 → 14.1).
  The export's size stays.

## A lit frame and city views in the rooms' windows — 2026-09-15

Two things set the live headquarters apart from the Owner's picture at a glance: the building's frame
was black where the picture's is a lit dark navy, and the rooms' windows onto the city were flat
mauve panels.

- **The frame.** `look_hq_live.py` places a facade light (`FacadeLight`): a cool area light 10 m in
  front of the building, facing it, on lighting channel 1. Only the `shell` actor also receives
  channel 1 (frame, stone, plinth, glass, roof). The rooms and their props are separate actors, so
  the light behind the open front stays as it was. Compared in the stream (mean colour distance, 15.0
  without):

  | Facade light | Mean | Seen |
  | --- | --- | --- |
  | 20,000 lm over the whole front | 39.6 | a white frame, the roof sign burnt out |
  | 3,000 lm | 20.5 | a slate-grey frame |
  | 800 lm | 15.4 | upper floors closer; ground floor and lift tower too bright |
  | 800 lm held to the floors above the ground floor | **14.6** | a dark navy frame, the new default |

  The light's bottom edge, centre, width and barn doors (5°, 10 m) hold it to the main block above
  the ground floor (`AMN_LOOK_FACADE_*`).
- **The rooms' windows.** The export bakes the windows' city images into the shared `props`
  texture, where each window gets a few texels: the average of its dusk image, mauve. The look pass
  puts the images themselves (`art-source/blender/hq/textures/window_city.png`, `window_city_b.png`)
  back on those two materials, on the model's own UVs, at emission 1.5 (`AMN_LOOK_WINDOW_VIEW`).
  The windows now show dark towers with lit windows against the dusk.

## Blue haze over the live skyline — 2026-09-15

In the Owner's picture the city fades into a blue haze towards its base; the live skyline stood as
black blocks with sharp lit windows.

- Height fog could not do it alone. Its distances count from the plate camera, 246 m in front of
  the building, and the scene's own fog (0.008 from 30 m) is also a veil that lifts the building's
  black frame, the rooms and the sky. Fog moved out to the skyline only (0.12 from 260 m, cut off
  past 330 m) hazed the towers, but the rest went dark: mean colour distance 15.6 → 29.7.
- `art-source/unreal/haze_hq_live.py` draws the haze instead: two unlit, translucent planes
  across the frame, 12 m and 27 m behind the building's front, in front of the city's layers.
  Each fades from full strength at the skyline's base to nothing towards the tower tops (material
  `M_HQ_SkylineHaze`, `AMN_HAZE_*`). The building, the street and its trees stand in front of the
  planes and are untouched. `rebuild_live_hq.ps1` runs it after the look pass.
- Compared in the stream (all regions; left city / right city): no haze 15.6 (22.2 / 20.2); opacity
  0.35 fading out at row 260, 15.3 (20.9 / 17.4); opacity 0.55 fading out at row 160, **15.0**
  (24.1 / 12.0), now the default. The towers read blue and hazy on both sides, the left a little
  lighter than the picture's.
- The building's frame renders black where the picture's is a lit grey. Its materials are 0.5–0.6
  metallic, but setting them to 0.1 changed nothing visible: the frame lacks light, not colour.
  `look_hq_live.py` keeps that setting (`AMN_LOOK_FRAME_METAL`), off.

## A lit street and darker crowns on the live headquarters — 2026-09-15

Next to the Owner's picture the live street was nearly black: the road and the near pavement came
to 15-45 of 255 where the picture's are a lit, cool grey at 55-100, and the green crowns read too
bright.

- Darker leaves: the green leaf texture is now made at 0.6 of its value and 0.95 of its saturation
  (`green_leaves.py` defaults). Measured 16.6 against the picture (17.1 before).
- Why the street was black: nothing lit it. The three street lamps (35,000 lm each) pool on the far
  pavement, and the sky light only captures a dim dusk atmosphere.
- `look_hq_live.py` now places a street fill: a wide, shadowless, cool area light 6 m up, pointing
  straight down over the road (`StreetFill`; `AMN_LOOK_STREET_FILL` lumens, `_Y`, `_DEPTH`). Each
  setting was compared in the stream (street region, 28.4 without the fill):

  | Fill | Street | Result |
  | --- | --- | --- |
  | 4,000 lm over the near pavement | 20.3 | the pale pavement turned lavender |
  | 6,000 lm over the road | 46.4 | a flat grey street |
  | 3,000 lm at y −16 m | 18.2 | |
  | 3,000 lm at y −19 m, 14 m across | 13.5 | the new default |

  With the new default the mean over all regions is 15.6, the closest pass so far (15.9 before).
- Letting Lumen trace reflections up to roughness 0.6 (`AMN_LOOK_TRACE_ROUGHNESS`; the engine's
  own limit is 0.4) brought no light streaks to the road and raised the whole ground floor by about
  4, so it stays at 0.4. The look pass also sets the wet asphalt's roughness range
  (`AMN_LOOK_ROAD_ROUGH_MIN`/`_MAX`, 0.25–0.5) and can cut the fog off past a distance
  (`AMN_LOOK_FOG_CUTOFF`), so the skyline can take haze that the sky behind it does not.

## Green leafy trees on the live street — 2026-09-15

The street's trees were the Blender export's round crowns, which read as foam next to the Owner's
picture, and Megaplants' real trees cannot show their leaves on this machine.

- Soul: City's trees, probed and compared in the stream: the aspen's leaves are a translucent
  material (poorly lit, without depth, hence bare and pale), two are pines, one is a twisted bare
  tree, two more read as bare white branches. One, `SM_S_BuildingSetA_Tree_02_OP02`, keeps a full
  crown (masked, two-sided leaves), and the capture holds with it (no recreate warning).
- Its leaves were autumn orange. The material's only colour parameter (`LitColor`) did not change
  them: the leaf texture itself is orange (leaves average RGB 102, 75, 43). `art-source/unreal/leaves/`
  makes a green copy of it: `export_leaf_texture.py` (Unreal), `green_leaves.py` (turns the leaves'
  hue from 34 to 105 degrees, alpha untouched; RGB 54, 93, 40) and `import_green_leaves.py`
  (Unreal, `/Game/HQ/Materials/T_HQ_Leaves_Green`). The generated images are not committed (pack
  content). `dress_hq_live.py` places the tree (`AMN_TREES=soul`, now the default) with the leaf
  instance `MI_HQ_TreeLeavesGreen`; the tree uplights now run at 0.3.
- Seen in the stream: green leafy crowns on both sides of the building. Measured 17.1 against the
  picture (15.9 with the foam crowns): the crowns read brighter than the picture's (the area left of
  the building 77 against 63). Darker leaves are next.

## Static copies of Megaplants trees: the stream holds, the leaves do not show yet — 2026-09-15

The live level's trees are the Blender export's round crowns, which read as foam next to the
Owner's picture. Megaplants has real trees, but every one is a skeletal mesh (25 of 25), and
skeletal trees stopped Pixel Streaming's capture on an earlier pass.

- `art-source/unreal/convert_trees_static.py` copies a tree's geometry out of the skeletal mesh
  with Geometry Script (`CopyMeshFromSkeletalMesh`) into a new Nanite static mesh under
  `/Game/HQ/Trees` (`CreateNewStaticMeshAssetFromMesh`), keeping its materials. The project now
  enables the `GeometryScripting` plugin. Four trees converted (black alder, black poplar, goat
  willow, Japanese medlar); `dress_hq_live.py` has `AMN_TREES=megastatic` for the two with round
  crowns.
- Verified in the stream: with the static trees the capture held (no "PixelCaptureMediaCapture
  will be destroyed" warning, frames delivered). But the trees rendered bare, white branches with
  no leaves, which reads worse than the foam crowns; the live level went back to its Blender trees
  (the default) while the cause is traced.
- Traced: the Megaplants trees are Nanite skeletal meshes grown by the Procedural Vegetation Editor
  as Nanite assemblies, and their leaves are assembly parts, not triangles of the mesh. A copy of
  the source model has a bark and a foliage section but no UVs; a copy of the render data
  (`AMN_TREE_LOD=RENDER_DATA`) has the bark alone. No Geometry Script copy can carry the leaves.
  The Procedural Vegetation Editor exports a tree as a static mesh with its foliage
  (`Export Mesh Type: Static Mesh`), but only from its editor, so the project now enables that
  (experimental) plugin for that export. `convert_trees_static.py` also gained `AMN_TREE_LOD`,
  `AMN_TREES_OVERWRITE` and Nanite set through `NaniteSettings` (the first copies had Nanite off).
- The export from that editor, with the leaves baked into the mesh ("Create Nanite Foliage" off,
  2,028 foliage instances), ran the editor out of memory, and the streamed game went down with it.
  The editor also warned that the project lacks Shader Model 6 and Nanite Foliage, which Nanite
  assemblies need. Enabled together in `DefaultEngine.ini`, they made the streamed game crash on
  its first frames: a D3D12 fatal error, "No command list slot was available. Too many residency
  sets are open concurrently", during the startup burst of pipeline-state compilation. Both were
  reverted and the stream came back on Shader Model 5 (live, frames delivered). A separate game
  process with Shader Model 6, `r.Nanite.Foliage=1` and `D3D12.ResidencyManagement=0` then crashed
  the GPU ten seconds in ("GPU Crashed or D3D Device Removed"), and the machine stopped responding
  and had to be restarted. That route is closed on this machine (Radeon RX 9070): Shader Model 6
  and Nanite Foliage stay off, and Megaplants' Nanite-assembly leaves cannot be used here.

## Real paintings and wet asphalt in the live headquarters — 2026-09-15

Light values alone kept the live level about as far from the Owner's picture as before (24.2 to
24.3), so the stand-ins themselves are being replaced with the packs' models and materials.

- The Unreal export (`AMN_UNREAL_PROPS=1`, set by `rebuild_live_hq.ps1`) no longer draws the rooms'
  plants and portrait pictures: `hq_lib.plant()` and `frame_picture()` record where they stand
  (`hq_scene.json` "props_m": 21 plants, 5 paintings). `dress_hq_live.py` places Palms Pack plants and
  the restaurant scene's framed paintings there. The web plates are built exactly as before.
- The road wears the bridge scene's cracked asphalt (world-space triplanar, no UVs needed), made
  wet in `/Game/HQ/Materials/MI_HQ_AsphaltWet` (roughness 0.18-0.5 instead of 0.85-1.0).
- `rebuild_live_hq.ps1` runs `look_hq_live.py` after seating the employees: a build recreates every
  light at its defaults, so the look pass is applied again each time.
- Measured against the picture after one full pass (mean colour distance, lower is closer): 16.5,
  the closest the live level has been (24.2 before). The lift tower 7.9, L1 10.0, L4 10.8. By eye:
  the paintings hang facing the camera; the plants are a step back, thin dark sprigs where the
  Blender plants were full; the lobby is too bright (82.7 against 68.2) and the street too dark
  (50.8 against 60.6).
- Second pass: only the full Palms plants (the slender `SM_Plant_07_*` dropped), the restaurant
  scene's large potted frond for plants of 160 cm and more (`AMN_BIG_PLANT_CM`), the lobby's fills
  at 0.75 of the rooms' (`AMN_LOOK_LOBBY`). Measured: 15.8; the ground floor 23.6 to 16.9, the
  lobby's two fronds leafy like the picture's. Still short: the smaller plants on L3 and L4 read
  as dark silhouettes, and the street is as dark as before (50.1 against 60.6).
- Third pass: fronds from 90 cm read leafy on L3 and L4 too, and are kept (`AMN_BIG_PLANT_CM` 90).
  A more reflective, untinted asphalt and street lamps at 0.8 did not lift the street (25.2) and
  brightened the lift tower (10.2 to 14.0) and the ground floor, so they were dropped; the street
  needs another approach than more light. The best balance so far is now each script's default
  (`look_hq_live.py`, `dress_hq_live.py`, `AMN_SKY_GAIN` 1.1 in `build_hq_scene.py`), so a rebuild
  without overrides reproduces it.

## The live headquarters compared region by region with the picture, and the look pass — 2026-09-15

The Owner asked whether the live Unreal headquarters looks like his picture, and to correct the
office, the lights, the textures and the finishes. It does not. Cut region by region against the
picture at the same scale (a 1920x1008 frame from the stream): the picture's rooms have soft warm
light (cove strips, glowing pendants), panelled walls, pinned boards, framed pictures, windows onto
the city and dense plants, where the level had hard coloured spot cones on flat walls, empty
frames and flat purple windows; the picture's street is wet asphalt with streaks of reflected light,
stone paving, bollards and people, where the level had a black road with white headlight patches;
its skyline has sparse lit windows in blue haze and a bridge, where the level had bright blocks.

- `art-source/unreal/look_hq_live.py` tunes the saved level in place (lights by kind, skyline
  emission, the asphalt's roughness and specular, fog, exposure, bloom and a cool-shadow,
  warm-highlight grade), with absolute values from `AMN_LOOK_*`, so passes can be compared without
  re-importing. Measured with `compare.py` (mean colour distance, lower is closer; 24.2 before):
  pass 1 29.6, every region brighter than the picture and the road a mirror of the shopfronts;
  pass 2 27.3, the street's colour right (1.3) but grey and hazy, the ground floor and the sky
  still too bright, the cones still on L4's wall. Tuning light alone does not close the gap: most
  of it is textures, materials and objects.
- `live/rebuild_live_hq.ps1` no longer stops at the Blender export when run by Windows PowerShell
  5.1: that shell turns a native program's stderr into error records, and under "Stop" Blender's
  first DeprecationWarning aborted the pass. The export is judged by its exit code (verified: the
  export passed, 54 meshes, 45 baked, in 115 s).
- `export_hq_scene.py` draws the skyline's window textures with fewer lit windows
  (`AMN_WINDOW_LIT_SHARE`, 0.6 of the Blender material's), each at its own brightness
  (`AMN_WINDOW_DIM_MIN`) and divided by a mullion.

## The live headquarters reaches the Owner's browser, and stops flickering — 2026-09-15

- The Owner's page kept switching between the Unreal stream and the page's own renderer. Every
  connection from his browser (Comet) ended after 13 seconds and was retried 15 seconds later;
  Unreal logged "Failed to set codec preferences: Missing codec from recv codec capabilities" for
  each. `start_live_hq.ps1` forced H.264, which that browser cannot decode. It now passes
  `-PixelStreamingWebRTCNegotiateCodecs`: Unreal offers H.264, VP8, VP9 and AV1 and the browser
  picks one. Verified: a Chromium build without H.264 received 1920x1008 video (346 frames in
  three seconds), and the Owner's next connection stayed up until the stream was stopped.
- When the stream drops after it has shown a frame (a restart of the game, a network hiccup), the
  page keeps that frame, frozen, with "Reconnecting to the live headquarters…", instead of
  uncovering its own renderer, which draws a different picture of the same building
  (`streamLayers` in `hq_stream_config.js`, a frame kept every two seconds in `hq_stream.js`).
- The Owner still saw the older picture while the level was being rebuilt ("Încă apare vechiul
  format!"): with no frame yet the page showed its renderer. With a stream configured the page
  now never shows it: before the first frame the viewport stays dark and says "Starting the live
  headquarters…" (the renderer keeps running underneath, so clicks still find the employees).
  `rebuild_live_hq.ps1` stops the stream only when Unreal is about to touch the level, after the
  Blender export, so a full pass keeps the picture live about two minutes longer.

## The MetaHuman employees seated in the live headquarters, and driven by the studio — 2026-09-15

- `backend/app/office/unreal.py`: with `STUDIO_OFFICE_UNREAL_REMOTE_URL` (the streamed game's
  Remote Control, e.g. `http://127.0.0.1:30010`) the backend reads the office layout every
  `STUDIO_OFFICE_UNREAL_SYNC_SECONDS` (5) and tells Unreal, desk by desk, what it says: an
  employee is shown only while an agent holds the desk, and held still while that agent is paused
  or suspended. Only changes are sent; everything is sent again after Unreal fails to answer and
  every minute. Unset, nothing reaches out. `tests/test_office_unreal_bridge.py`.
- `art-source/unreal/people/seat_employees.py` retargets ActorCore's seated loops onto the
  MetaHuman skeleton, seats every built employee at their desk facing the viewer, and records the
  actor, body and animation object paths in `people/seat_report.json` for the bridge. It is the last
  step of `live/rebuild_live_hq.ps1`, since a rebuilt level has no employees.
- `art-source/unreal/people/rig_in_editor.py` rigs and builds the MetaHumans unattended in the full
  editor and quits. A commandlet could not: the eighth build (Nadia) crashed twice in TextureGraph's
  groom bake at frame 0, with and without `-AllowCommandletRendering`, while the same build worked
  from an editor that had already drawn frames. `-ExecutePythonScript` closes the editor as soon as
  its file returns, so the script is started with `-ExecCmds="py …"` and waits 300 ticks.
- `Config/DefaultRemoteControl.ini` allows only the bridge's two calls. The streamed game refused
  `SkeletalMeshComponent` functions until they were listed ("not allowed by remote control
  settings"). The first entries, `FunctionName="SetPlayRate"`, opened every function of `Actor`
  and `SkeletalMeshComponent` instead: the field is optional, its value needs parentheses, and
  without them it stays unset, which means "any function". Written `FunctionName=("SetPlayRate")`,
  the game refuses the functions not listed and accepts the two that are.
- Seen live: all eight employees seated in their offices in the streamed page (1920x1008, 511
  frames, no errors); an employee hidden by hand was shown again by the bridge within its
  one-minute refresh (44 s). Mean colour distance to the picture 24.2 with a bus crossing the
  street (23.3 before the employees).
- The first seating pass recorded each body as `TRASH_SkeletalMeshComponent_8`: creating the
  retargeted animations reinstanced the blueprints after the actors were spawned, and the game has
  no such component (its body is `<actor>.Body`). The animations are now made before spawning, and
  the paths are read back after the level is saved.
- Backend tests: 776 passed, 1 skipped (a real Ollama is not configured).

## The Unreal headquarters dressed with the Fab packs, and a moving street — 2026-09-15

The Owner asked for the headquarters to be carried to the end in Unreal. The Blender stand-ins that
the packs can replace are replaced, and the street moves.

- `art-source/unreal/live/rebuild_live_hq.ps1` runs one pass: Blender export for Unreal, the level
  rebuilt, the packs placed, the traffic sequence built, the stream restarted. It stops the stream
  before touching the level: rebuilding under the running game failed to replace the sky
  material, and `build_hq_scene.py` now rebuilds that material's graph when it cannot delete it.
- The Blender export for Unreal (`AMN_UNREAL_WORKSTATIONS=1`) keeps each workstation's desk and
  chair in one object and its flat monitor and mug in another (`desk_screens`), so the live scene
  can put real furniture in place of the first and keep the studio's own screens. The web plates
  are built exactly as before.
- `dress_hq_live.py` places desks and chairs (Apartment Tech Props), keyboards, mice and desk lamps
  at the eight seats, lamp posts, the bench, the bus shelter, planters and Megaplants trees at the
  street's anchors, and City Sample Vehicles in both lanes, each scaled and grounded by its measured
  bounds at the positions the web scene uses.
- `traffic_hq_live.py` drives the vehicles with a looping level sequence that plays on start.
- MetaHuman: the Creator's 29 presets are installed but not rigged, and rigging needs the Owner's
  signed-in editor; `people/employees.json` and `people/rig_employees.py` are ready for that session.
- What the passes found, and fixed. The wind-animated Megaplants trees stopped the stream (the
  capture was recreated again and again, no frame reached the page); static trees brought it back.
  Re-importing over the previous import left the skyline's facade materials without their window
  textures (flat white towers) and piled up renamed texture copies; each build now imports into its
  own `Scene_<timestamp>` folder and deletes the old ones. The pack's arm lamps read as black crosses
  at the scene's lamp heights; the posts are now slim lanterns.
- Seen in the page (headless Chrome, 15:03): the stream is live at 1920x1008 with the lit skyline,
  the lanterns, the bench and the shelter. Mean colour distance to the picture 24.6 (the page's own
  renderer measures 11.5): the street is still far too dark, the trees are bare, the shelter's red
  edges are not the picture's, and there are no people yet.
- Second pass (15:09): the scene keeps its own leafy trees (Soul: City's rendered bare and pale),
  the shelter is the model without red neon edges, and every vehicle carries two headlights and two
  red tail lights, attached so the traffic sequence carries them: a car crossing the frame lights
  the road ahead of it. Mean colour distance 23.3. Still missing: people, a lit wet road, the roof's
  brightness.

## The office furniture, the people's animations and the MetaHuman data — 2026-09-15

The Owner asked Claude to take over the Launcher. Every pack below now loads in Unreal 5.8
(`probe_pack_assets.py`).

- **MetaHuman Creator Core Data** is installed into the engine (grooms, clothing, presets, texture
  synthesis), what the Creator needs to build the employees.
- **Apartment Tech Props**: desk, desk chair, monitor, keyboard, mouse, PC tower, printer,
  speakers, headset, phone, desk lamp, cables. The Launcher downloaded it but never copied it into
  the project; it was copied from the Launcher's download without overwriting anything: the 23
  shared Deko files that differ from City Street Props' copies were left as they are.
- **25 Office Desktop Items**: laptop, headphones, lamp, documents, cups, books (with Starter Content).
- **ActorCore Sample Motions**: male and female dummies with IK rigs and retargeters, idle, walk,
  stand-to-sit and seated-talk animations.
- **Fab plugin** is installed in the engine (`Engine/Plugins/Fab`, on by default).
- ArchViz Interior (Unreal 4.27 only) was not added: the Launcher wanted to overwrite files it
  could not show, so the copy was cancelled.

## City Sample Vehicles, the bridge and the shopfronts load — 2026-09-15

The Owner added City Sample Vehicles (13 vehicles, a city bus among them), Modular Building Set and
Automotive Bridge Scene to AMNReference.

- City Sample Vehicles needs Chaos Vehicles and virtual textures: the project enables
  `ChaosVehiclesPlugin` and `r.VirtualTextures=True` (the next launch recompiles shaders once).
- `art-source/unreal/probe_pack_assets.py` loads one asset from each pack, found by name inside the
  pack: the bus (11.3 m), a car and its blueprint, the bridge arches (39 m) and lamp, shopfront
  columns, street props, a Megaplants pine (25.7 m) and Soul: City all load in 5.8.
- Vehicle Variety Pack's meshes load, but its drivable blueprints refer to UE4 classes
  (`TireConfig`, its animation blueprint) that no longer exist; the scene uses its meshes only.

## The Fab packs are in the Unreal project — 2026-09-15

The Owner added his Fab packs to AMNReference (about 40 GB): Vehicle Variety Pack, City Street
Props, Mega Street Props, Street Props Vol.1 and Vol.2, Soul: City, Megaplants, Palms, the
photography kit, turnstiles and several interiors.

- `inventory_content.py` now reads each static mesh's size from the asset registry
  (`ApproxSize`) instead of loading every mesh, which on packs this size would exhaust memory.
  It listed 7742 assets and no load errors.
- Still missing for the picture: City Sample Vehicles, Modular Building Set, Automotive Bridge
  Scene, ArchViz Interior, Streetwear Parametric Outfit 1, the Fab plugin and the MetaHuman
  Creator data. The packs that arrived hold five cars (hatchback, pickup, sports car, SUV, box
  truck), no taxi, no bus and no people.

## The Unreal headquarters, live in the page — 2026-09-13

The Owner chose to see the headquarters rendered by Unreal Engine live in the page (Pixel
Streaming). The pipe is built end to end; the Unreal level does not have the employees and the
street life yet, so the stream is only switched on by configuration.

- **Unreal streams.** The project enables Pixel Streaming 2. `art-source/unreal/live/start_live_hq.ps1`
  starts Epic's signalling server (release UE5.8-0.1.0, built with Node 22.14.0, outside the repo
  because its scripts break on spaces) and runs `/Game/HQ/HQ_Dusk` as a game through the plate
  camera, H.264 on the RX 9070. Unreal loaded the level and joined the signalling server.
- **The backend relays.** The page may only talk to its own origin, so
  `/api/v1/office/stream/signalling` carries the signalling to `STUDIO_OFFICE_STREAM_SIGNALLING_URL`
  (Owner token, constant-time), and `GET /api/v1/office/stream` says whether a stream is
  configured. Unset or not running, the relay closes and nothing takes the stream's place.
- **The page shows it.** The office viewport lays Epic's player over its own renderer, lets clicks
  through to it, hides the video while the stream is down and retries (`scene.json`
  `live_stream`). `#scene-viewport[data-stream]` says which one is on screen.
- **Seen in the page.** Headless Chrome logged in, the viewport went `live`: 1920×1008 H.264,
  794 frames decoded in the first seconds, no console errors.
- **Remote Control on this machine only.** The running level answers Remote Control's HTTP API
  on 127.0.0.1:30010, the route for placing the employees without C++ (both installed MSVC
  versions are banned by UE 5.8). Its settings are in `Config/DefaultRemoteControl.ini`; the
  unused WebSocket server, which had opened on 0.0.0.0, stays off.
- Tests: `tests/test_office_stream.py` (relay both ways, token refused, not configured, not
  running, address check), `frontend/tests/hq_stream.test.js`.

## MetaHuman Creator enabled in the Unreal project — 2026-09-13

The employees are to be real MetaHumans, so the AMNReference project now loads the MetaHuman
Creator plugin (`MetaHumanCharacter`, which brings RigLogic, hair strands, cloth and the MetaHuman
SDK with it).

- `art-source/unreal/probe_metahuman_cloud.py` checks it headless: the scripting subsystem is there
  and a MetaHuman character asset is created.
- Two things still stand between that and a finished face and body. The auto-rig and texture
  services need an Epic login, and the headless run starts a device-code login the Owner would
  have to confirm, so rigging runs in the editor he is signed in to. The Creator's optional core
  data (texture synthesis) is not installed with the engine yet.

## Every department its own office, in its own colour — 2026-09-13

The Owner pointed at S2 on the live page: the accountant and the publisher sat side by side in one
room. His rule: separate offices, one per department, each in a different colour. He chose where
Distribution goes and that Research and Fact Check part as well.

- **L3** is two rooms with a partition: Research (blue, Aris) and Fact Check (terracotta, Elena).
- **L2** is two rooms: Content (wood, Marcus) and Distribution (teal, Vera, with her desk and the
  release radar on the wall).
- **S2** on the ground floor is the Treasury alone (burgundy, Nadia, her desk in the middle, the
  sign reads "S2 TREASURY").
- Each room has a lit sign naming its department. The backend layout has the new zones
  (`factcheck_room`, `publish_desk` on floor 2, a wider `accounting_office`) and the fact-check
  stage walks to the Fact Check room; the scene's manifest and the layout are checked against each
  other by `tests/test_office_layout_matches_scene.py`. The server needs a restart to serve them.

## The headquarters in Unreal Engine 5.8 — 2026-09-13

The Owner asked for Unreal Engine. The headquarters now renders there from the Blender build
(`art-source/unreal/`); the web page still shows the Blender plates, because the Unreal still
does not yet beat them.

- **The pipeline**: `export_hq_scene.py` (Blender → `hq_scene.glb` + lights, camera and axis
  markers in `hq_scene.json`), `compose_sky_backdrop.py` (the web page's dusk sky as an image),
  `build_hq_scene.py` (level `/Game/HQ/HQ_Dusk`: meshes, the 63 scene lights, sky backdrop, sun,
  fog, orthographic plate camera, Lumen), `render_hq_still.py` (3200×1680 still), and
  `inventory_content.py`, `probe_look.py`, `probe_materials.py` for diagnosis.
- **Four faults found and fixed on the way**, each confirmed by measurement before the fix:
  glTF dropped every procedural material (233 materials arrived untextured: white walls,
  towers and road), so materials are baked into textures and skyline facades get tiling window
  textures; an orthographic camera cannot see the sky atmosphere (black sky), so the sky is a
  backdrop; the editor took its screenshot **unlit** (exposure, lights at a third, even
  `r.ExposureOffset` rendered the identical image), so `render_hq_still.py` forces the lit view;
  lit, the interior lights were several times too strong and unequal between floors, so interior
  and exterior lights and each floor are balanced separately.
- **Measured against the picture** (mean colour distance per region): first import 36.6, unlit
  with baked materials 31.5, first lit still 134.9, balanced 28.3 (L2 8, L4 13, L1 17, ground
  floor 27, L3 42). The web page measures 8.3, so it stays in use. By eye the Unreal still has
  what the web page lacks — pools of light, a glowing lobby, lit trees and street lamps — and
  still lacks people, vehicles, a lit wet road and the picture's light on the facade.

## Everyone at their own desk, facing the Owner, always at the picture's dusk — 2026-09-13

The Owner compared the office with his picture again: two employees shared one counter in S2,
some sat with their backs turned behind white blocks, the sky and colours were wrong, and buses
drove through each other. His answers: every employee has their own desk, sits facing the viewer
with the monitor to one side, and the office always has the picture's light.

- **One workstation per employee** (`hq_building.workstation`): a light desk top with a warm LED
  under its front edge, slim legs, a keyboard, a monitor turned in from one side so it never hides
  the person, a mug, and an office chair behind them. The accountant and the publisher in S2 now
  have two desks. Every seat faces the viewer (a test checks it, and that no two share a desk).
- **New people** (`build_people.py`, replacing the chibi `build_characters.py`): adult
  proportions from metaball bodies, cloth and skin materials, faces, hair, glasses, headsets and
  earrings from the Character Bible; seated poses facing the viewer for every backend state,
  standing, reacting and walking; pedestrians from the same builder.
- **Always the picture's dusk** (`scene.json` → `"light": "reference_dusk"`): the office, the sky
  and the street are lit as in the picture at any hour; the clock, the street's daily rhythm and
  the random events keep the real time, and live rain, snow and fog still fall. Live cloud cover no
  longer greys the painted sky. `"live"` restores the real sun.
- **Tall vehicles never overlap**: a bus, truck or fire engine enters only when no tall vehicle is
  in the other lane, so two of them are never drawn one over the other.
- Honest limit: without the old lit counters the rooms measure darker than the picture (plates
  alone 4.8 → 7.3), and the Owner judged the figures, cars and buses still far from the picture.
  The next step moves the rendering to Unreal Engine 5.8 (`art-source/unreal/export_hq_scene.py`,
  `build_hq_scene.py`, `render_hq_still.py`), with content packs the Owner adds from Fab.

## A sky with clouds, like the picture's — 2026-09-13

The Owner compared the office with his picture and found the sky empty: a plain gradient, with
clouds drawn only when live weather reported them.

- **Painted cloud banks**, made by `art-source/sky/paint_clouds.py` without any image generator:
  layered noise shaped into long banks with crisp edges, lit from below at dusk (warm undersides,
  blue-grey cores, as in the picture), white by day, dim at night. Three WebP layers (330 KB in
  all) are crossfaded with the time of day (`cloudLayerWeights`).
- **Live weather still rules the sky**: real cloud cover and fog grey it over, rain, snow and
  storms are drawn on top. With the server restarted the endpoint answers, and on the day this was
  made Bucharest reported "Cloudy 16°C", which is why the live sky reads grey.

## A bridge that fans, a grey tower, notes with writing — 2026-09-13

- **The bridge is cable-stayed like the picture's**: a pylon about twice as tall over the deck,
  cables leaving it along its height with the highest reaching farthest (the first try paired
  them the other way and drew a lattice), small warm deck lights, and a thin warm line up the
  pylon so it reads against the towers behind it.
- **The lift tower's stone column is a cool grey** instead of warm mauve. A sweep of lighter
  greys, closer to how light the picture's column looks, measured worse each step (tower 9.3,
  12.0, 14.7), so the darkest stays.
- **L3's pinboard notes carry lines of writing**; measured, they change no room's score.
- Live page at the picture's light: mean colour distance 8.5 → 8.3, left sky 26.6 → 24.1; plates
  alone 4.8 (the grey stone costs the tower 0.5).

## The skyline recedes, and the slogan says TOGETHER — 2026-09-13

- **The slogan panel reads all four lines.** The classic building in front of it was 8 m deep, so
  from the camera's 10° its roof and cornices rose over the panel and hid "TOGETHER"; it is now a
  shallow lit facade, as in the picture.
- **The skyline recedes into blue**: the far haze is blue instead of pink, tower windows are
  smaller and more of them are lit, and the brightest windows are warm white instead of bluish.
- **The bridge** has warm, dim cables and deck lights instead of a glowing white fan.
- Live page at the picture's light: mean colour distance 9.1 → 8.5; right-hand city 13.3 → 11.2,
  left sky 30.5 → 26.6, street 4.9 → 3.7. Plates alone 4.8 → 4.7.
- A trial of lower desks with a wooden top and clutter on the back desks measured worse in every
  room (L4 3.0 → 4.8, L3 10.1 → 12.5) and read no closer to the picture at the canvas's scale, so
  it was not kept; only lines of writing on L3's pinboard notes stay, for the next plates.

## Rooms as bright as the picture's — 2026-09-13

Once dusk stopped borrowing light from the sunlit day plates, every room read a little darker than
the picture. Interior lights are now 3.15 times their modelled energy (was 2.8).

- Plates alone at the picture's dusk: mean colour distance 5.4 → 4.8 (L4 1.7, ground floor 2.9,
  street 4.1, L1 4.4, tower 4.8, L2 5.1, L3 8.8).
- Live page: mean 10.1 → 9.1; L4 5.7 → 2.7, L2 9.2 → 6.6, ground floor 5.9 → 3.0. The largest
  gaps left are the sky (the picture has sunset clouds, drawn here only when real weather reports
  cloud) and the right-hand skyline.

## Dusk no longer looks half like day — 2026-09-13

The lift tower, the sign and the street measured far brighter live than their own night plates.
Composing the plates the way the canvas does found why: the day plates were crossfaded in
linearly with daylight, and daylight already rises while the sun is below the horizon (the sky
needs that). At the picture's dusk, with the sun 2.5° down, 30% of a sunlit render was added.

- The day plates now follow daylight to the power 2.2 (`plateDayMix`): about 7% at that dusk,
  fully there by day. The sky keeps its own curve.
- Measured on the live page: sign 12.5 → 3.9, tower 18.8 → 9.0, street 10.7 → 5.2, mean colour
  distance 10.4 → 10.1. The rooms, which the sunlit blend had been lifting, now read slightly
  darker than the picture; the near-pavement darkening planned for that same excess is dropped.

## Street life in the evening light, a lit tower, lush trees — 2026-09-13

- **Cars, buses and pedestrians take the light of the hour.** They are rendered under neutral
  light, so at dusk a white bus glowed against the dark street. Their sheets are now multiplied
  by the outdoor light (untouched by day, dim cool blue at dusk and night, greyer under cloud) and
  cached until that light changes; lamps, light bars and the courier inside the building are not
  tinted. Street lamps also leave long warm streaks on the road after dark.
- **The lift tower** has its narrow side bay lit like the picture's, frames in steel blue and
  larger stone blocks; its shaft glows less, so it no longer outshines the picture.
- **Trees** have lighter, more translucent crowns around a dark green core and stronger warm
  uplights; the bridge's cables are fine lines instead of a glowing tent; L3's spot cones are
  narrower again, since with bloom they drew discs brighter than the picture.
- **Measured on the live page at the picture's light**: mean colour distance 11.4 → 10.4; L3
  17.0 → 10.3, street 13.8 → 10.7, L4 3.4, L1 4.9, ground floor 4.8. On the plates alone the tower
  is now 4.8, but live it still measures 18.8: something drawn over the plates brightens it, and
  that is the next thing to find.

## Floors, street and sky measured against the picture — 2026-09-13

Region by region against the Owner's picture, the building still had heavy dark bands between
floors, a pale warm road with a glowing zebra, flat skies and racks that read as green noise.

- **The dark band over every floor was a compositing fault**, not the model: each plate layer is
  rendered with the other layers invisible, and the slab's body sat in the shell layer the canvas
  draws after the rooms, so its whole top face was painted over the floors. The slab body now
  lives with the rooms; the shell keeps its navy face with a warm LED line, as in the picture.
  The lift tower's floor bands are shallow, so the lit shaft shows above them.
- **The street is dark, cool and matte where it should be**: plain grey road paint instead of
  self-lit stripes, asphalt that no longer mirrors the lit facade at the camera's grazing angle,
  matte paving (it had mirrored the S2 and S3 labels), a warm stone terrace, softer street lamps.
- **The sky is not level at dusk**: the camera looks north, so the sun sets on the left; a warm
  afterglow hugs that horizon and a lighter blue sits high across from it, as in the picture.
- **Rooms**: server racks are dark units with slot lines and steady lamps (the canvas still adds
  the blinking that follows the studio's work), the S3 vending machine has shelves of cans,
  spot cones on the back walls are wide and soft, pendant lamps are big enough to read, console
  tops no longer glow white, and L3 and L4 are as bright as the picture's.
- **Measured on the live page at the picture's light**: mean colour distance 13.0 → 11.4; L4
  11.5 → 3.5, L2 15.7 → 7.5, L1 11.3 → 5.0, ground floor 6.2 → 4.4, street 19.4 → 13.8.
  Regressions still open: L3 (13.5 → 17.0) and the lift tower (13.9 → 17.4) now come out
  brighter than the picture once bloom is added.

## Cars that read as cars — 2026-09-13

Next to the picture's rounded SUVs and sedans, the street's cars still looked like stacked boxes.

- **Bodies are lofted from side profiles**: bonnet, raked windscreen, roof and boot for the
  sedan, coupe, hatchback, SUV, EV, taxi and police car, with the glasshouse leaning in and the
  plan rounded at the bumpers; wheel arches, door seams, handles and mirrors on both flanks.
- **Lamps wrap round the corners**, so a car seen side-on shows its headlights and red tail
  lamps as the picture's cars do. The render records where each visible lamp sits and the canvas
  blooms exactly there after dark, with a faint horizontal streak on headlights.
- **Windows stay dusk-dark**: the key and fill lights no longer mirror as white squares on glass
  and bonnets; light bars on police cars and ambulances keep their red and blue.

## The headquarters, rebuilt from the Owner's picture — 2026-09-13

The Owner asked for the office to be redone so it looks like his headquarters picture, with the
studio called AMN-AI (the picture said "AMH-AI"), made with Blender or Unreal and without his
image-generation credits. The pixel-art office is gone; what replaces it is described in
`HQ_LIVING_OFFICE.md`.

- **The building** is a Cycles scene built from the picture's own measurements: sign, four
  upper floors with their labels, the audio booth and render bay, S1 Infra, the lobby with its
  stairs, S2 Operations, S3 AI Space and the glass lift tower. Plates come in layers (night and
  day) so employees sit behind their consoles and pedestrians walk behind the bollards. A
  per-region comparison with the picture went from a colour distance of 70.6 on the first
  render to 14.4 on the live page at the same light.
- **The employees** are eight chibi characters rendered from their Character Bibles, each with
  typing, thinking, idle, talking, paused, error, standing, reacting and walking frames. What
  plays is the backend state; the render bay's screen shows the video editor's real state
  instead of the picture's "RENDER 91%".
- **The city lives**: right-hand traffic from nineteen rendered vehicles (buses carrying
  AMN-AI, Nexus Curiosity and Inside The Nexus ads, taxis, vans, trucks, bicycles, scooters,
  motorcycles, and emergency vehicles with lights and sirens), pedestrians following the daily
  rhythm, a bus that serves the shelter, traffic that stops for people on the zebra.
- **Time and weather are real**: the sun's elevation for Bucharest's date and time decides day,
  dusk and night; the weather comes from a new endpoint, `GET /api/v1/office/weather`, and is not
  drawn at all when it is unknown.
- **Random events** are configuration (`world_events.json`): rarity, weight, cooldown,
  concurrency, weather and time of day, duration, priority and reaction radius — from airliners
  and crossings to fireworks and a very rare UFO. A seed replays a day exactly.
- **The interface speaks English**: the office chrome, every dialog, the ledger, settings,
  YouTube connections and the live window.
- The office layout now matches the rendered building, and a test keeps them in step.

## Watching the film: stripes, a discarded shot plan, and a disclosure it never carried — 2026-09-13

The Owner watched *How ATLAS Caught the Higgs Boson in Real Time* and named what was wrong:
text in the picture that should not be there, a weak voice, pictures that were poor and
sometimes made no sense — and he asked whether it was because the studio buys the cheapest.
Mostly it was not. The film was watched frame by frame and every fault traced to its cause.

**What the film is.** 0–4s old theory pages whose printed words are gibberish; 4–7s a light
net, two spheres colliding, a fully white frame; 7–10s a particle burst; 10–14s ATLAS drawn as
a futuristic tower in a canyon (it is a horizontal cylinder in a cavern); 14–19s abstract neon
spirals; **19–30s eleven seconds of vertical beige stripes** — the film's payoff. Quality
control scored it 1.0, and the Director approved it having seen three frames.

**Why.**
- The video editor wrote a 14,036-character shot plan — lens, light direction and colour,
  composition — and **the studio threw all of it away** because two `audio_intent` lines ran
  past 200 characters. One field failed validation, so the whole pack did, and every shot was
  rebuilt from the writer's one-line description, repeated into subject, action, environment
  and lighting.
- His visual bible went the same way for describing the palette, the light and the camera as
  objects instead of sentences; the film was shot on an empty default look.
- The writer's line for the payoff asked for *"a text overlay appears: 'Top quark or W
  boson?'"*, and the prompt passed it to the image model, which drew stripes.
- Quality control measures the file, never the picture; the Director was shown frames at 20,
  50 and 80 per cent, so two of five scenes were never seen.
- The cheap choices are real but secondary: in TEST the motion model was `seedance2_mini`
  (catalogue quality 0.6, against 0.8 for `seedance2`), and the narration was ElevenLabs'
  lowest-latency `eleven_flash_v2` on the free plan.

**What changed.**
- A model's answer is fitted to the schema instead of refused for its shape: an overlong field
  is shortened, a structured value is said as a sentence, and a shot that cannot be placed
  costs only itself. Kael's real plan now keeps all five shots.
- Pictures are never asked to draw writing: text requests are stripped from every positive
  field, and both the writer's and the editor's briefs say so. Text belongs to the edit.
- A composed prompt says each thing once.
- Every still is measured when it is made — squeezed along each axis and compared with itself
  by SSIM, with the encoder the studio already has. Real stills measured 0.18–0.76 (a plain sky
  0.89/0.91); the ATLAS stripes 0.961. Above 0.94 on one axis is stripes or bands, on both a
  blank field. A broken still is generated once more, told plainly what a picture is; still
  broken, it is recorded and **quality control fails the film** and names the scene.
- The Director is shown one frame from the middle of every scene, and told that a blank field,
  stripes, noise or garbled writing in any of them is a REJECT.

**The description.** The Owner's rule: every film says it was made with generative AI by the
AMN-AI studio pipeline, links the studio's site, and credits INSIDE THE NEXUS. It is added on
every road to YouTube — the day's publish stage, the one-click route and the Owner's own intent
— once, inside YouTube's 5,000 characters, whatever the Publisher wrote. The site
(`STUDIO_AI_DISCLOSURE_URL`, empty until it exists) and the creator channel
(`STUDIO_CREATOR_CHANNEL_TITLE=INSIDE THE NEXUS`) are configuration; the link to the channel is
read from its stored connection (`@insidethenexusai`), not written in code. The two films
already on the channel keep their old descriptions: the upload adapter cannot edit a published
video, and editing one is the Owner's call.

**The cost, from the credits.** The studio had never written a vendor balance down, so the
ATLAS render's "before" cannot be proven after the fact, and Runway's usage report does not yet
include the day. What is exact: Runway holds **1,662 credits** now; ElevenLabs counted the
render's narration **1,411 → 1,608 characters (197)**, the flash model billing half a credit
per character. From now on the media stage reads each vendor's balance immediately before and
after every render and writes the difference on the render and in the event stream, with the
dollar value of Runway credits at the Owner's recorded rate. The 30 credits on 2026-09-11 and
the six `gemini_2.5_flash` generations on the same key are not made by any code in the studio.

`uv run pytest -q` — **735 passed, 1 skipped**, including tests built from the ATLAS film's own failures. `ruff`, `mypy`, `scripts/check_docs.py` clean.

## The studio published a new film end to end, and the office showed nobody working — 2026-09-13

The first complete cycle under the corrected rules ran on the evening of 2026-09-12 and went
all the way: the Director chose *How CERN's ATLAS Measured a Higgs Boson in Real Time*, the
writer and she worked the story for seven exchanges, she passed and approved it herself, the
video editor wrote the visual bible and five shot prompts, and the media stage produced five
Runway stills, five ElevenLabs narration clips and two Runway motion clips (the TEST limit),
cut them into a 30.2-second film, QC scored it 1.0, the Director watched it and approved it,
and the Publisher uploaded it privately to Main Channel A as `sDEtt-WQGh8`. Media stage start
to publication: seven and a half minutes.

While that happened, the Owner watched the office and asked why it was stuck at Lyra. It was
not stuck. Her narration review was the last model call (THINKING, then IDLE at 20:51:30), and
for the next seven minutes her voice was recorded, the stills and shots were generated and the
film was cut — in her name and Kael's — while both showed IDLE and the ledger said nothing.
An employee's state changed only when she thought with a model; the paid part of the day ran
beside it. The office already draws `WORKING` as typing and the live window already counts it
as busy. The backend simply never said it.

- `mark_working` / `mark_idle` / `at_work` in `agents/services.py`: the employee holding a
  role is WORKING for exactly as long as a production step runs, with a detail the ledger can
  read (*vocea scenei 3*, *mișcarea scenei 2*, *montajul filmului*), and IDLE after — also when
  the vendor fails. Best effort by design: a status line that cannot be written is logged, and a
  paid render never dies because of it.
- The assembler wraps each paid step in the employee who owns it: stills, motion and the cut
  are the video editor's, narration is the voice artist's. Placeholders mark nobody.
- The stale-state sweeper no longer flips a WORKING employee to IDLE: production has no model
  run behind it by nature, and a model task may run beside it.
- The ledger read every state that was not THINKING as *a terminat* (finished) — so WORKING
  would have read "finished" at the moment work began. It reads *lucrează*, with the detail.

**Two things the cycle's books showed, recorded and not papered over.** The render's recorded
cost is 0.316 USD and it is incomplete. The ElevenLabs narration has no cost row at all:
`eleven_flash_v2` carries no price in the catalogue, so the Accountant correctly counts the
scene as unpriced rather than free — the gap is the catalogue, not the arithmetic. And both
motion shots were priced at `seedance2_mini`'s documented 0.02 USD a second, because Runway
named no credits on the prompt-only path; the render's own summary therefore says 0 USD for
motion while the books say 0.216. No price was written into code to fill either gap.

`uv run pytest -q` — **727 passed, 1 skipped**. `npm test` — **87 passed**, including the ledger's WORKING
case. `ruff`, `mypy` clean.

## Time to fix it — 2026-09-12

The run finished without crashing for the first time since the room opened, and the story was
refused at the wall anyway: five drafts, everything passing except one check, and then the
budget ran out. The Owner's answer was the right one — *it should have been given the time to
clarify and correct the problem.*

**The check was wrong.** `ending_answers_the_hook` compares the content words of the hook with
those of the payoff onward. The hook: *"This telescope was supposed to work 14 months. It
guarded Earth for over a decade instead."* The ending: *"It spent eleven years watching for
things that burn in our sky — and ended as one of them."* That ending answers that hook
exactly, and shares no word with it. Four refusals for writing it well. Whether an ending
answers its opening is a question about meaning, and nothing that counts words can decide it:
it is now an **advisory** check — still measured, still recorded, passed to the Director as a
flag to look at, and no longer able to refuse a script by itself.

**And the budget was counting the wrong thing.** It counted every rewrite of a topic, ever —
including eleven rounds caused by the studio's own faults in earlier runs. That story began
this run at exchange twelve of sixteen and hit the wall five drafts later while it was still
getting better. A budget is for a conversation going in circles, not for one doing its work:
it counts **rounds that changed nothing**, and a draft better than any before it reopens the
room. Progress is measured the only way the studio can measure it alone — how many refusing
checks are left.

**The room is twenty exchanges**, the Owner's number, and the twentieth is a decision rather
than another request. Which exchange she is in and how many went nowhere are now two separate
numbers; they had been the same one by mistake.

`uv run pytest -q` — **726 passed, 1 skipped**. `ruff`, `mypy`, `scripts/check_docs.py` clean.


## The write that could not wait — 2026-09-12

Two watched runs died on the same statement: `UPDATE agent SET runtime_state`, "database is
locked", once in the script stage and once in `post_run`. Raising `busy_timeout` from ten
seconds to thirty did not help, which was the clue.

Measured on a scratch database: connection A opens a deferred transaction and reads; B writes
and commits and closes; A then writes and is refused **in 0.00 seconds**, with the lock free
and nobody to wait for. SQLite's deferred `BEGIN` takes a read snapshot at the first SELECT,
and no amount of waiting makes an old snapshot writable. `busy_timeout` was never going to
matter.

`BEGIN IMMEDIATE` everywhere was the obvious cure and is wrong here. The studio opens a
writing session inside an open reading session in many places — the economy suite is full of
them — and there the inner write waits on the outer read's own lock: **32.8 seconds, then the
same error**. Under that setting twenty-three tests failed, most of them the books.

So the lock is taken per transaction, by the transactions that know they will write:
`lock_for_write(session)` as the first statement, a no-op UPDATE of the policy row. From then
on the transaction is a writer, its later writes cannot be refused, and any other writer waits
its turn — which `busy_timeout` does cover. It is called in both of `run_agent_task`'s write
blocks, which is where the studio failed twice; both close before the model is called, so the
lock is held for milliseconds.

The measurements are in the code, so the next person to reach for `BEGIN IMMEDIATE` does not
have to spend the afternoon finding out.

`uv run pytest -q` — **723 passed, 1 skipped**, including one that reproduces the refusal and
shows the line that prevents it. `ruff`, `mypy`, `scripts/check_docs.py` clean.


## A reviewer who cannot see the conversation cannot finish it — 2026-09-12

The open writers' room ran for the first time: ten exchanges on one story inside a single run,
and the story tightened as it went — 42.9s, 39.1, 31.4, 29.5, 25.3, 37.6, 36.8, 38.3, 31.0.
From the second exchange on, every computed check passed. The Director said REVISE nine times
anyway, and then the run died on `database is locked` and the studio went into safe mode.

**She was asked in a vacuum.** Each reading got the script and nothing else: no sense of which
exchange this was, no memory of what she had asked for, no moment where she had to decide. Ask
a good critic "what is wrong with this" nine times and you get nine answers, because there is
always something. She now sees the exchange number and the budget, the notes she gave last
time — with the instruction that a note the writer has acted on is settled, and that the
question is whether the film is good enough to publish, not whether it is perfect — and at the
last exchange she is told to answer PASS or REJECT. If she asks for another rewrite when there
will be no rewrite, the studio records that as REJECT and says why: a REVISE with nothing
following it is a refusal that will not say its name. Her authority is untouched; what she
refuses stays refused, and is only named.

**And the lock.** `busy_timeout` was ten seconds. A stage that spends four minutes talking to
models writes dozens of small transactions while the outbox dispatcher writes beside it once a
second and a WAL checkpoint takes the write lock for as long as it needs; ten seconds ran out
while updating one agent's runtime state. It is thirty.

`BEGIN IMMEDIATE` was tried first and reverted: it takes the write lock up front, which turns
contention into waiting rather than failing — but the studio opens a writing session inside an
open reading session in a dozen places, and under IMMEDIATE the inner write waits on the outer
read's own lock. Measured on a scratch database: **32.8 seconds, then the same "database is
locked" it was meant to cure.** The comment in `db.py` now says so, with the measurement, so
the next person to have the idea does not have to spend the afternoon on it.

`uv run pytest -q` — **722 passed, 1 skipped**. `ruff`, `mypy`, `scripts/check_docs.py` clean.


## The writers' room stays open — 2026-09-12

Four watched cycles ended the same way: the studio wrote two drafts, the second was one note
from passing, and the day closed with nothing made. The Owner settled what the rule should be:
*"we have plenty of tokens. The day does not close after two attempts. We can have ten or
twenty exchanges until we have a film. The day closes when the short is published."*

- `MAX_REVISIONS` was **2**, on the reasoning that a third attempt on the same evidence
  produces a third version of the same weakness. That reasoning was about cost, and cost is not
  the constraint: rewriting text is the cheapest thing the studio does, while a render is where
  the money goes. It is **15** — high enough to be a real conversation, finite enough that a
  story the evidence cannot support is eventually let go of.
- The script stage no longer writes exactly two drafts. The writer and the Director work the
  story until she approves it, until the review refuses it, or until `MAX_SCRIPT_EXCHANGES`
  (16) closes the room — and on her approval the storyboard is made in the same run, so the
  film reaches the camera the same day.
- What the Owner reads says how long the conversation took: *"5 scenarii scrise în 5 schimburi,
  1 aprobate de Director, 1 storyboard-uri generate."*

`uv run pytest -q` — **720 passed, 1 skipped**. `ruff`, `mypy`, `scripts/check_docs.py` clean.


## Does the film close, or is there a scene wearing the label — 2026-09-12

The revision loop converged for the first time: *How NASA Tracks Asteroids That Could Hit
Earth*, draft one refused on two counts, draft two — with the draft it was revising in front of
it — fixed the causal progression and kept its length. One check still refused it, twice, and
the check was wrong.

`has_ending` asked whether any scene carried the label `ENDING` or `CTA`. The draft ended on
*"after ten years defending the planet, it became a streak of fire in the sky"*, declared that
ending, and carried a CTA of its own — but the writer had spent all five scenes the brief
allows on HOOK, SETUP, DEVELOPMENT, EVIDENCE and PAYOFF, and delivered the close inside the
last of them. The film closed; only the label was missing.

- The check now asks whether the film ends: a labelled `ENDING`/`CTA` scene, **or** a declared
  ending that the last scene actually speaks. A film that just stops still fails, and so does
  one whose ending is written in the fields but never said out loud.
- The brief says the missing half plainly: the last scene closes the film, carries the ending
  and the CTA, and is labelled `ENDING` or `CTA` — do not finish on `EVIDENCE` or `PAYOFF`.

`uv run pytest -q` — **719 passed, 1 skipped**. `ruff`, `mypy`, `scripts/check_docs.py` clean.


## A revision revises the draft — 2026-09-12

Three watched cycles in a row, on the same topic, showed the writer getting worse instead of
better. Draft two of *How NASA Keeps a Space Telescope Alive With Frozen Fuel* passed every
computed check at 39.5 seconds; the Director sent it back on taste alone, with surgical notes —
cut the second line of scene 2, tighten scene 5 to end on the mirror, fix a generic CTA, and
resolve a real topic drift she had caught (the thesis promises finite fuel, the script delivers
the sunshield). Draft three came back at 46.8 seconds with no ending at all.

The cause was in the prompt: the notes travelled on their own, followed by "write the story
again from the beginning". The writer never saw the draft he was revising. A note about scene 5
cannot be obeyed by someone who has to reinvent scene 5 first, so every revision re-rolled the
story and lost whatever had been working — and after two of those the revision budget refused
the topic, for a fault that was ours.

- `previous_draft` reads the newest draft of the topic back — title, hook, ending, CTA, and
  every scene with its purpose, narration, visual and claims.
- The revision prompt now carries it, inside the same inert boundary any other data gets, then
  the notes, then the instruction that changed: **revise this script, keep what works, change
  only what the notes name, and do not reinvent the story from zero.**
- A first draft is handed no previous one, and says so.

`uv run pytest -q` — **717 passed, 1 skipped**. `ruff`, `mypy`, `scripts/check_docs.py` clean.


## The target is a target, not a knife — 2026-09-12

The corrected brief went out and the writer still lost a story to the duration check: 103
words, five scenes, 41.0 seconds against a 39-second ceiling. Two faults behind one refusal.

**The brief and the check were still not reading the same number.** `expected_seconds` charges
`SCENE_BEAT_SECONDS` for every scene change — the breath between shots — while the budget
priced the narration in words alone. So the brief promised a ceiling about five words looser
than the one applied, and the writer, obeying it, was refused for the difference. The budget
now settles the scene count first and prices the words against the seconds that are left.

**And the check was too strict to be right.** The Owner settled it: *"it is fine if it goes
over by a few words, not all videos are the same."* The tolerance was 0.3; it is 0.5, with the
format's own limit (`MAX_SHORT_SECONDS`, 60s) as the outer wall a tolerance may not reach over.
A 30-second target now accepts 15–45 seconds. The 41-second draft passes. Two hundred words in
a thirty-second film — the failure the check was written for, a film that ends before its
words — still does not. The brief says the same thing in the same voice: aim here, a few words
over is fine, past this it is no longer a short.

`uv run pytest -q` — **715 passed, 1 skipped**. `ruff`, `mypy`, `scripts/check_docs.py` clean.


## The Director approves her own scripts, and the brief can be satisfied — 2026-09-12

A watched cycle produced a new film for the first time: the Director chose *How the James Webb
Space Telescope Sees the First Galaxies* over the asteroid topic on 16 supported claims, the
writer drafted it, and the story review sent it back. Twice. Then the studio stopped — and
what stopped it was four separate faults in one chain.

**The brief asked for a film its own budget could not pay for.** The writer was told "30
seconds, about 78 words" and, in the same breath, offered up to twelve scenes across eight
story purposes under a five-line beat table. Seventy-eight words over seven scenes is eleven
words a scene, which nobody writes; he wrote twenty-one, twice (57.5s, then 41.2s against a
39s ceiling). The arithmetic now lives in `narration_budget` and the brief states it: at 30
seconds, **5 scenes of 12–19 words**, 78 words in total, refused over 101 — and it says the
count is on the spoken text, not on the `duration_seconds` numbers the model fills in. The
beat table is expressed as fractions of the film's own length, so it reproduces the historic
0–3 / 3–8 / 8–18 / 18–26 / 26–30 table at 30 seconds and stays true at any other. The refusal
now names the ceiling and the target too, because "too long" is not a brief.

**The revision budget never fired.** `MAX_REVISIONS` counted the reviews of one draft row while
every rewrite wrote a new row, so each attempt was the first revision of a brand-new draft and
nothing ever escalated. It counts the story now — the topic behind the drafts.

**The studio had written itself into a corner.** The script stage skipped a topic the moment
any draft existed for it, while the topic still counted as in production, so a story sent back
twice could neither be rewritten nor got past: nothing new could be selected, and nothing would
write a third draft. `script_work` replaces that test — a topic owes work while its newest
draft has no storyboard and the review sent it back, and the reading's notes travel with the
rewrite. A REJECTED story is not retried here; its budget is spent, the letters have gone to
the departments, and it stops holding the studio up.

**Approval was in the Owner's inbox.** A script the Director had read and passed still waited
for him to press a button — "I don't have to approve the new scripts, the Director does", as he
put it. She approves what she passed, in the same decision, and the record carries `approved_by`
and the reason. The factual gate is still re-checked at approval, so she cannot approve a script
whose claim stopped being supported while it was written. The Owner keeps the same API route and
can still refuse what she allowed.

`uv run pytest -q` — **711 passed, 1 skipped**. Thirteen new checks across
`tests/test_editorial_quality.py`. `ruff`, `mypy`, `scripts/check_docs.py` clean.

One consequence worth stating: the James Webb topic has already spent its revision budget, so
under the corrected rule its next reading refuses it and the selection moves to the next topic
with verified claims. The corrected brief gets its first run on a story that has not been
refused yet, which is the honest way round.


## A film is not a file — 2026-09-12

The studio published its first video: *The Universe's Missing Pieces: Why the LHC Upgrade
Matters*, private, on Main Channel A. Watching the ledger, the Owner asked the right question
about what was left behind in the queue — and the answer was that the same film would have
gone out three more times.

One storyboard had been rendered four times during the day: a retake, a re-edit, another pass.
Each render is a new `MediaAsset` with a new id, each one passed quality control, and the
duplicate gate compared `media_asset_id` — the **file**. So three QC-passed files, all of the
same film, sat eligible on every gate. One per daily run, the channel would have received the
same video four days running. Proven on a copy of the live database before the fix: all three
returned `eligible: True`.

- **Identity is the film, not the file.** `film_identity` walks asset → render job →
  storyboard → script, and `published_films` keys what a channel already carries by both the
  script and the storyboard. A candidate matches on whichever of the two it can establish;
  when provenance cannot be walked at all the answer is "unknown", never "new".
- **The duplicate gate refuses a second render** of a script the channel already carries, and
  says which video it already has: *this film is already on the channel as “…” (remote_id: …);
  this asset is another render of the same script*.
- **Cross-posting is untouched.** The gate is per channel, so one film may go to two channels;
  what it may not do is go to the same channel twice.
- **A failed upload blocks nothing.** Only live publications count, so a retry after a refused
  upload still works.
- **The publish stage offers each film once.** The queue is collapsed to the newest render per
  film, and a film the channel already carries is not a candidate at all — so the stage walks
  on to the next real film instead of stopping on a refusal.
- Gate 4 (factual integrity) now uses the same provenance walk instead of its own copy.

Five tests in `tests/test_phase6_publishing.py` describe it: a retake refused and naming the
earlier video, a second storyboard from one script still the same film, the same film allowed
on a second channel, a failed publication not blocking, and the provenance walk itself.

`uv run pytest -q` — **698 passed, 1 skipped**. `ruff`, `mypy`, `scripts/check_docs.py` clean.


## An employee may think with more than one model — 2026-09-12

Every agent ran on exactly one model, and that single slot could not express the thing the
Owner wanted: a Director who proposes a strategic decision and then has it challenged before
she commits, a researcher who falls back when a model is unavailable, a hard question answered
independently by two models and reconciled by the employee.

So three slots and a strategy, and one rule above all of it: **no model is named in the
studio's logic**. A model in a slot is a configuration value the Owner can replace from
Settings tomorrow without a line of code changing, and a test scans the whole backend and
fails if a configured model name appears anywhere outside documentation (migration 0034).

- **Three slots per employee**, from the registry the primary already came from — no second
  registry, no second connector, no second configuration screen. Each slot is checked the way
  the primary always was: the model must exist, be available, and satisfy what the role
  requires, because a fallback onto a model that cannot do the job is not a fallback.
- **Five strategies.** SINGLE stays the normal way work is done. FALLBACK takes over only when
  the first answer does not exist, and never invents one. REVIEW has the second model look for
  what is wrong and the first decide. DEBATE asks a third model only when the two materially
  disagree. PARALLEL synthesises independent answers.
- **Extra models are not spent on routine work.** The agent's own policy and the importance
  the caller declares decide, and the reason is recorded in words: "this was strategic, at or
  above the threshold" is auditable, "a second model was called" is not.
- **The advisers advise; the employee decides.** In REVIEW, DEBATE and PARALLEL the answer the
  caller acts on is always a run on the employee's own model, with the other models' words in
  its prompt. A critic cannot publish, command a department or change a strategy, because the
  only thing it produces is text the primary model reads — and it is told so.
- **A review that could not be done is said so.** No fabricated critique: the collaboration
  closes as REVIEW_INCOMPLETE, the answer still stands, and the Director's loop drops that
  decision's confidence to low and writes why.
- **Traceability.** Each participating call stays an ordinary run with its own model and
  tokens; `llm_collaboration` joins them with the part each played, the disagreement and the
  final model. Changing a slot today cannot rewrite what yesterday was answered by.
- **The Owner's allocation is a file he can edit** (`config/workforce_seed.json`): the
  Director on her primary with a strategic critic, everyone else single. It is applied once
  per employee, at the first model sync that learns which models exist, and never over an
  existing assignment — otherwise the next sync would quietly undo a choice made in Settings.
  `scripts/apply_llm_allocation.py --force` applies it when the file is a new instruction.
- Tests: `tests/test_multi_llm.py`, the twenty-two the Owner asked for, with stand-in model
  names so no test can pass because a name looks familiar. 693 pass.
- The report is in `MULTI_LLM.md`.

## The Director runs a company, not a video — 2026-09-12

Every part of this studio was measured and no part was managed. The Director chose the day's
topic, read her inbox and watched the finished film; nobody asked where the company stood,
what was preventing growth, which department was holding up the ones after it, whether an
agent had been idle for a week, or whether last month's strategic bet had worked. A snapshot
said "10 000 views" and nothing said whether that was good.

Nothing here is a second management system. The Director is the same agent with the same role
and the same model, given a new task; assignments go through the existing mailbox, the loop
runs as a standard job on the existing scheduler, idle agents and dead letters come from
`measure_workforce`, weight changes stay `DirectorRecommendation` with its own database
constraints, and the panel is the panel that was already there (migration 0033).

- **The company has a readable state.** Environment, data maturity, each channel with the last
  seven days against the seven before them, the pipeline stage by stage with what is in flight
  and where the bottleneck is, agents with their failure rates, the ordered backlog with a
  reason per place, open decisions, anomalies, and what limits growth per channel. All of it
  from stored rows: a channel with nothing measured reports nothing, not zero.
- **Performance is normalised.** Views per hour beside the totals, subscriber conversion,
  engagement, cost and production minutes on the same row, cost per thousand views. A verdict
  needs a baseline of at least three measured films, twenty-four hours of age and a rate;
  without them the answer is INSUFFICIENT_DATA, which is a real answer.
- **A diagnosis names a department.** Click-through separates "nobody chose it" from "they
  chose it and left", and conversion separates "they watched and did not subscribe" from
  both. Four causes, four assignments. One film never condemns a category, and nothing in the
  studio can permanently ban a topic.
- **The loop's output is action.** At most three assignments per pass, each a letter with the
  observation, the evidence, the interpretation, the confidence, the decision and the review
  condition. A matter already under an open decision is not raised again. A matter assigned
  three times goes to the Owner instead of round a fourth time. STOP and SCALE are the
  Owner's, always.
- **A decision is a row with a review date.** The database refuses a decision nobody will
  check. When the films it was waiting for have been published, it comes back as a matter and
  is closed with what actually happened — so strategy itself can be learned from.
- **Idle agents get real work, and only when nothing is in flight.** With films waiting to be
  finished, finishing them is the work; inventing a task then is the definition of busywork.
- Tests: `tests/test_director_command.py`, the thirty the Owner asked for. Verified against a
  copy of the live database: it found the studio's real bottleneck — six films through quality
  control and none published — and reordered the backlog by evidence in hand. 674 pass.
- The full report is in `DIRECTOR_COMMAND.md`.

## The idea has to argue for itself — 2026-09-12

The Owner's principle, in the order it has to be enforced: a good idea, then a good story,
then a good script, then a good prompt, and only then a video. A powerful video model cannot
rescue a weak idea. The studio could research a fact, verify it, write narration that cited
it, and produce a film nobody would watch, because nothing in the pipeline ever asked *why
this video should exist* — and what reached the video model was the single line the writer had
typed under `visual`, at about 2.60 USD a shot.

Nothing here is a second pipeline. The research agent, the trusted-source registry, the
independent fact checker, the script writer, the Owner's script approval, the Director's
selection and her final viewing, the production stages and the model routing are all the ones
that existed; each gained what it was missing (migration 0032).

- **An idea now carries a thesis**: the core fact, why it matters, why now, the payoff, a
  hook, an ending, a call to action that belongs to this story, the risk and the length. It is
  scored on twelve editorial dimensions that are **weighted, not averaged** — hook, payoff,
  story and fact confidence decide — so a beautiful topic with nothing to say stops winning.
  An idea that fails the editorial rules is kept with its reasons instead of dropped.
- **A script now has a shape**: the writer is briefed on the thirty-second structure, on
  causal progression instead of "and then", on showing rather than narrating twice, and on the
  studio's own speaking rate, so thirty seconds of film no longer carries sixty seconds of
  words. Every scene declares the part it plays, and the story — one message, the takeaway,
  the hook, the ending, the CTA and its kind — is stored with the draft.
- **The story is read before anything is bought** (`story_review`). The computed checks ask
  whether the film has a hook that is not "did you know", a purpose and an attribution behind
  every scene, a payoff in the second half that answers the hook, an ending, a closing
  question about *this* story, and narration that fits the length. The Director says where
  interest would collapse, second by second. A script that is sent back is rewritten once with
  the notes. This is the first gate in this studio that runs **before** the money.
- **The prompt carries the film**: one master visual bible (style, world, palette, light,
  camera language, continuity rules, what to avoid) and a full package per shot — subject,
  action, environment, camera, lighting, composition, motion, emotion, background, continuity
  with the shot before it, audio intent, transition, negatives and story purpose. It may not
  invent a number the story never stated, may not make the film more spectacular than the
  story, and is capped in length because a thousand meaningless words bury the fields that
  matter. `visual_prompt` still holds what is sent, so the render path is untouched.
- **Prompt quality is constant across environments.** The prompt agent is never told which
  environment it is in; TEST saves money by choosing a cheaper model, never by thinking less.
- **The loop closes**: the Director's notes about the pictures become prompt lessons the next
  film's prompt agent reads, and the weekly review compares what the studio predicted about a
  film with what the audience actually did.
- Tests: `tests/test_editorial_quality.py`, the twenty-one the Owner asked for. Two real
  defects surfaced while writing them: the prompt agent was not checking the story gate, and a
  second prompt pass read its own output as the writer's line. Both fixed. 645 pass.
- The full report is in `EDITORIAL_PIPELINE.md`.

## Two environments, and a model that has to earn its place — 2026-09-12

The Owner found in one search what the studio's own steward had not: models at 0.05-0.12 USD
a second where the studio was paying 0.43. *"Seedance face video sa fie de 3 ori mai scump,
merita? Este agent, are un rol! Asta trebuie sa faca!"* And before that, the cost of not
knowing which kind of work was happening: an experiment bought the same eight shots a film
does, 21.08 USD in an afternoon.

Both are the same missing distinction. The studio now knows **which environment it is in**,
and a model now has **a standing it has to earn**.

- **The environment is the studio's own state** (migration 0031, `owner_policy.environment`,
  `POST /owner/environment`): TEST or PRODUCTION, changed by the Owner through the same
  versioned, idempotent command that stops autonomy, never by a query parameter a page could
  set. The top bar says which it is, always, and the button beside the autonomy switch
  changes it.
- **One router, two policies** (`choose_model` in `production_policy.py`). Business logic
  states a requirement — the task, the quality the scene needs, its length, what it may
  cost — and never a model name. In **TEST** the answer is the cheapest compatible model and
  the quality ranking is not consulted; its fallback is the next cheapest, never the best;
  and a shot above `STUDIO_TEST_MAX_COST_PER_GENERATION_USD` or
  `STUDIO_TEST_MAX_COST_PER_SECOND_USD` is refused rather than quietly bought. In
  **PRODUCTION** the answer is the least expensive model that reliably reaches the quality
  the scene requires, and the decision says what it did not buy and at what multiple — the
  Owner's marginal question, answered in writing.
- **The scene's part in the film sets the tier**, not the model's price: HOOK and ENDING are
  asked for more than the middle (`scene_role`, `SCENE_ROLE_TIERS`, `scene_tier`), because
  the first shot decides whether anyone watches and the last whether anyone comments.
- **A model has a life** (`app/integrations/lifecycle.py`): DISCOVERED → QUARANTINE →
  BENCHMARKING → CANDIDATE → PRODUCTION → PREFERRED, and DEPRECATED. A model the vendor
  exposed today is taken into the catalogue and kept **out of production** until its own
  results say otherwise; a model whose contract could not be read waits in quarantine rather
  than being tried on a film; a model the Owner's deny list names
  (`STUDIO_MODEL_DENY_LIST`) is retired on sight and chosen in neither environment.
- **The studio learns from its own results** (`model_outcome`): every generation is recorded
  with its environment and kind, its scene category, what it cost and whether it was
  accepted first time. A cheap functional test is recorded and **never** allowed to teach the
  studio about a model's picture; a test of a model that is not yet admitted **is** that
  model's benchmark, which is how a new model earns its way in. The daily review
  (`MODEL_REVIEW`, a standing job) promotes and demotes on that evidence and generates
  nothing, so it costs nothing.
- **A price keeps its date.** CONFIGURED, ESTIMATED and BILLED are distinguished
  (`pricing_version`, `price_verified_at`, `price_verification`, `previous_pricing_json`): a
  price is never overwritten in silence, what it was is kept, and a move past
  `STUDIO_PRICE_CHANGE_ALERT_PERCENT` is a letter from the Accountant to the Owner.
- **The vendor is asked before it is paid.** Where Runway's own published contract declares a
  task accepts a dry run, the render asks what this exact shot will cost before buying it; a
  quote that disagrees with the stored price by more than
  `STUDIO_PRICE_STALE_TOLERANCE_PERCENT` marks the stored price stale and replaces it, and a
  quote above a ceiling means the shot is not bought at all. A flag the vendor does not
  declare is never sent, because a question about a price must not become a purchase.
- **The page can say why**: under each rendered film, which model filmed each scene, in which
  environment, for how much, and the router's reason.
- Tests: `tests/test_environment_routing.py` (the eighteen the Owner asked for) and the
  render's own outcome records in `tests/test_motion.py`. 625 pass.

## Twenty-one dollars, and the guards that were missing — 2026-09-12

The Owner's credits fell to 1 878 and he asked who spent them. The answer, from Runway's own
usage: the studio generated eight `seedance2_5` shots for one film — 3 986 → 1 878 credits,
**21.08 USD** at the Owner's price of a hundred credits to the dollar. Six shots reached the
film. **Two were generated, charged for and thrown away** because the studio's own download
cap (32 MB) was smaller than a 7.6-second shot: 14.8 paid seconds, about six dollars, lost to
a bug. No agent and no worker did this; the render was started from here. Measured cost, far
from the catalogue's 0.025 USD a second: **43 credits a second — 0.43 USD — about 2.60 USD a
six-second shot.**

What was missing, now built:

- **A credit has a price** (`credit_usd` on the connection, in Settings): vendors that bill
  in credits state the credits a task costs and nothing about money. With the Owner's number
  the books convert it, so a film's cost is a figure and the daily budget can bite.
- **A ceiling per render** (`STUDIO_MOTION_BUDGET_USD`, default 12): the first shot teaches
  what a shot costs, and every shot after it is refused when what remains would not cover
  one. A film finishes with camera pushes rather than quietly spending the week.
- **A paid shot is never discarded**: a failed download is retried, and a shot that is paid
  for and still lost is recorded as `paid_but_lost` with its credits.
- **A test renders the minimum, on the cheapest model that films from words**
  (`?mode=test`, `test_motion_provider`, `cheapest_prompt_to_video`): no still bought first,
  two scenes by default. Production keeps the best model the account has, from the still the
  Director approved. The Owner's rule: test cheap, production best.
- Tests: two more in `tests/test_motion.py`.

## A premium studio, and the frame it films in — 2026-09-12

The steward read the vendor's pages, scored eighteen video models and recommended
`seedance2_fast`: "cost-efficient… acceptable quality for social media formats". The Owner's
answer was the standing instruction this studio had never been told: *"Nu facem rabat de la
cheltuieli. Nu are sens sa avem o companie de creare filme care nu poate livra filme bune."*
And the recommendation was worse than cheap — `seedance2_fast` tops out at 720×1280 for a
studio that renders 1080×1920.

- **The studio has a standing priority** (`STUDIO_PRODUCTION_PRIORITY`, default `premium`):
  it becomes the ranking's weights (quality 0.6, reliability 0.25, speed 0.1, cost 0.05) and
  a line in the steward's instructions — "recommend the best picture the account can make…
  treat price as a fact to record rather than the deciding one". `balanced` and `thrifty`
  are the other two; a channel may still override per purpose.
- **A model that cannot fill the studio's frame never outranks one that can**
  (`delivers_studio_frame`, `STUDIO_FRAME = 1080:1920`): read from each model's published
  ratios, so the 720×1280 models sort last instead of being recommended. It is a preference,
  not an exclusion — an account that offers nothing taller can still film.
- **The download cap was costing shots**: eight seconds of 1080×1920 came back near forty
  megabytes and two scenes of the first motion film were lost to a thirty-two megabyte
  limit. The cap is ninety-six now; it exists so a stray response cannot fill memory, not to
  judge a film's weight.
- Tests: one more in `tests/test_production_policy.py`.

## What a film costs reaches the books — 2026-09-12

The Owner asked what has been spent so far. The honest answer was that nothing had been
recorded: `provider_cost_record` was empty after four renders. Three reasons, each fixed:

- **The Owner's render button never asked the Accountant anything.** The day's media stage
  called `record_render_costs`; the button did not, so every render started from the page
  left the books untouched. It records now, and reports what it recorded with the render.
- **The production record named the voice provider but not its connection**, and a price
  belongs to a model on a connection — so narration could not be priced even where a price
  existed. The adapter that actually spoke is named, with its connection and model.
- **Runway bills credits, and the studio's prices are in dollars.** Runway answers every new
  task with `estimatedCost` in credits: the only number the vendor itself states about the
  money. It is kept per scene and per render (`motion.estimated_credits`), so a film that
  spent credits can be read back even while no dollar price for a credit is recorded.
- Tests: one more in `tests/test_motion.py`.

## The film plays where the film is — 2026-09-12

"Ar trebui sa pot sa il vad in Producție media, NU?" — yes, and it could not be seen: the
card drew a black rectangle labelled "9:16 Video" beside the measurements, and the endpoint
that serves the file (`GET /media/assets/{id}/stream`, there all along) was never called.

- **Redă** plays the rendered short in the card, at 9:16. The Owner's key travels in a
  header, which `<video src>` cannot send, so the bytes are fetched once with the key and
  played from a blob — the same bytes the new **Descarcă fișierul** link saves.
- Where a film lives, for the record: `backend/storage/media/<storyboard_id>/` holds the
  stills (`scene_NN.png`), the first frames sent to the motion model (`first_scene_NN.jpg`),
  the generated clips (`motion_NN.mp4`), the normalised shots (`shot_NN.mp4`), the narration
  (`voice_NN.mp3`, `master_audio.wav`) and the film (`final_short_9_16.mp4`). The MediaAsset
  row keeps the path and the SHA-256 of the bytes.
- Measured, for the question "does it take this long?": eight stills took eight and a half
  minutes, eight generated shots twenty-five — because the account's tier allows
  `maxConcurrentGenerations: 1` for every video model (and 2 for the still model), so the
  shots are made one at a time by the vendor, not by choice.

## A shot is a file, and a film is its picture — 2026-09-12

The first dissolving render looked right and was not: forty-six seconds of narration over
**six and a half seconds of picture**. One filter graph over eight inputs failed quietly
after the first dissolve, and quality control passed the file — because a container is as
long as its longest stream, and the longest stream was the audio.

- **Each shot is built and checked on its own** (`_shot_command`): one ffmpeg call per scene
  writes `shot_NN.mp4`, exactly as long as the scene, from the generated clip or from the
  still pushed in; a shot that does not come out fails the render there, named. The dissolve
  pass then works over finished files, so `_dissolve_command` has nothing left to hide.
- **The render measures the picture before recording anything** (`_video_stream_seconds`):
  a film whose video stream is more than a second shorter than its narration fails, and no
  MediaAsset is written for it.
- **Quality control measures the video stream** (`probe_media_file`): `video_duration_seconds`,
  `video_frames` and `video_fps` come from the stream itself, next to the container's
  duration, so the old "45 seconds" cannot be claimed by audio alone again.
- The Director's frame extraction asks for full range (`setrange=pc`) through `image2pipe`:
  the dissolve chain writes limited-range video, and the JPEG encoder had refused every
  frame — she was approving films she could not look at.
- Tests: three more in `tests/test_motion.py`.

## A short that moves — 2026-09-12

The Owner watched the first finished film and said what it was: "sunt doar niste imagini
lipite… Eu vreau un filmulet, cursiv." He was right. Every scene was a still held on screen
for the length of its narration, joined by hard cuts. The account has sixteen video models,
six of them priced per second, and the production hierarchy already resolved a `video`
choice for every scene — the assembler simply never asked for it.

- **A shot per scene, and the shots dissolve** (`_dissolve_command`): every scene becomes a
  clip of its own length, one ffmpeg call fades each into the next, and each dissolve
  consumes only the overlap the shot was made longer by — so shot N still starts exactly
  where scene N's words start, and the film is as long as the narration it carries.
- **The approved still is the first frame of generated motion** (`_generate_motion`): the
  scene's still goes to the scene's video model as `promptImage` with the scene's length, and
  the clip that comes back is the shot. A model that refuses leaves that scene as a slow push
  into the still — a shot, not a held frame — and the film is still made; what happened is
  recorded per scene in the render job.
- **What a scene costs is priced in its own unit**: narration by the thousand characters, the
  still by the image, motion by the second of film (`estimate_cost_usd`, `record_render_costs`).
  An adapter now carries the connection it was built from, so the Accountant can find the
  price at all; a unit with no recorded price is reported unpriced, never counted as free.
  At the account's prices a forty-five second short costs about $0.45–$1.15 in motion.
- **The first frame is sent at the size the film is made at**: a generated still came back
  as a twelve-megabyte PNG, which base64 turned into a seventeen-megabyte request and Runway
  answered 413 for every scene. The still is re-encoded to a 1080-wide JPEG (about half a
  megabyte) before it travels, and the shot is generated from it.
- Measured on the Owner's account, and worth knowing before the next render: one four-second
  shot on `seedance2_mini` — the cheapest video model there — cost 64 Runway credits, about
  sixteen a second, where the catalogue's recorded price implies far less. A forty-five
  second short of generated motion is therefore around seven hundred credits.
- Tests: `tests/test_motion.py` (4).

## The Director could not see, and nothing said so — 2026-09-12

The clean studio produced a real film: 45.6 s, 1080×1920, eight scenes on seven claims from
CERN's dark-matter page, Runway stills, an ElevenLabs voice, quality control passed on
technical, rights, source and factual checks. Then the editorial gate sent three frames of
it to the Director's model and the whole call failed: `glm-5.3` declares `completion`,
`thinking` and `tools` — not `vision`. A model that cannot see does not answer worse; it
refuses the request, so no film could ever be approved.

- **What a model can do is the provider's statement, and it is stored**: `ModelInfo` carries
  `capabilities`, the configured adapter asks Ollama's `/api/show` per model, and the model
  sync records every declared capability (creating the row for a word the studio has not
  heard before — the vocabulary is the provider's). `kimi-k3`, `qwen3.5:397b`,
  `mistral-large-3:675b`, `glm-5.3-flash`, `kimi-k2.6`, `deepseek-v4.1-flash`, `minimax-m3`
  and `gemma4:31b` declare vision; the rest of the account does not.
- **Frames go only to a model that can see** (`model_can_see`): otherwise the Director
  reviews the written film — script, claims with sources, scenes, what QC measured — and the
  prompt tells her she is judging it blind and to say if the pictures are what she needs.
- Tests: one more in `tests/test_editorial.py`.

## The studio finds pages before the Researcher names them — 2026-09-12

The first day of the clean studio, watched live: six real topics in English on authorised
sites; then nothing read. Dr. Aris named three addresses per topic from memory and every
one returned 404 — UNESCO serves its article pages only to browsers (the front page answers
the studio's honest identity; the deep pages do not), and the DeepMind, Anthropic and
Hugging Face paths did not exist. The Director, seeing a letter with no body, asked for
"raw fetch logs". A site's own search, in the OpenSearch Suggestions JSON format, answers
the studio's identity and returns pages that exist (Wikipedia's does, tested).

- **Search address per authorised site** (migration 0030 `research_allowed_host.search_template`,
  `set_search_template`, `PUT /factual/sources/allowed-hosts/{host}/search`, a field and a
  "Probează" button in the research dialog): https on the same host, `{query}` where the
  words go. Nothing is hardcoded: the Owner records it, the studio uses it.
- **`find_pages` / `search_pages`** (`backend/app/research/service.py`): the retriever asks
  for JSON (`accept_json`) under the same allowlist, SSRF, size and time rules; results are
  kept only on authorised hosts; a failed search is an empty answer.
- **The Researcher plans from pages that exist**: `gather_sources` lists the pages found in
  his prompt; when every guess of his fails, the found pages are read anyway.
- **Searches are the names in the title, not the sentence** (`search_queries`): a site's
  suggestion search matches the start of a page title, so the second clean day — with the
  whole title as the query — found nothing. Now the proper names and acronyms of the title
  and subject line ("James Webb Space Telescope", "Higgs Boson", "UNESCO") are asked, longer
  first, at most six.
- **The letter carries the evidence**: "Nicio sursă preluată" now lists each address and
  what the site answered, and says the studio fetched with its own identity.
- **A later evening pass that fails does not undo the first** (`_post_run`): the third
  review of the clean day returned no text and the stage reported the whole review refused.
- **One mistyped claim is one claim lost, not a day lost**: the third clean day read real
  pages (CERN's dark-matter page, NASA's Webb page, Wikipedia's High-Luminosity LHC page —
  the search step works), then the Researcher's claim list carried `"confidence": 0.95.0`
  in one object; the parser refused the whole list, the stage failed, the day failed and the
  studio entered safe mode. `_salvage_complete_objects` now keeps the objects that parse
  (a doubled decimal is repaired), and `_research_and_verification` counts a source whose
  answer cannot be read ("N surse fără afirmații citibile") and reads the next one.
- The same page named with and without a trailing slash is read once.
- **The fourth clean day produced a script — and refused it**: five scenes on dark matter
  cited their verified claims, five on the LHC upgrade cited nothing (no LHC claim had been
  verified: five claims a day out of thirty extracted). Now the day verifies up to
  `VERIFY_BATCH = 24` claims, CRITICAL first, and a draft with uncited scenes is sent back
  to the writer once with those scenes named ("write the film the claims allow"); the second
  draft is the one stored. The fifth clean day's rewrite still had one scene of seven with
  no fact behind it ("the LHC is getting stronger" — no page read said so): a minority of
  uncited scenes is now cut and the attributed film kept (`cut_scenes` in the result, named
  in the writer's announcement); a rewrite that still rests mostly on nothing is refused.
- **The storyboard speaks the writer's words**: the seventh clean day built eight silent
  scenes called "Scene 1"… "Scene 8" from a real script — `generate_storyboard_from_script`
  read the demo fixture's keys (`voiceover_segment`, `visual_prompt`) and not the writer's
  (`narration`, `visual_description`); the voice artist passed it ("nothing to pronounce").
  Both spellings are read now, and a scene without a stated duration lasts as long as its
  words take to say (3–9 s).
- **A provider's refusal fails the render, not the day**: Runway answered HTTP 400 and the
  media stage raised, the day failed and the studio entered safe mode. The refusal is now
  counted in the stage report ("N randări refuzate de furnizor"), the storyboard stays
  approved for tomorrow's attempt, and the day goes on.
- **One live storyboard per script**: rebuilding a storyboard supersedes an earlier one
  nobody has rendered (it is marked REJECTED), so the render stage never picks the stale
  board over the new one.
- **Why Runway refused: a model that edits pictures, not one that draws them.** The eighth
  clean day's HTTP 400 body said `referenceImages: expected array, received undefined`.
  `gen4_image_turbo` is listed under `text_to_image` and *requires* one to three reference
  images — it edits pictures it is given — and it was the studio's image default because it
  is the cheapest still model in the account. The contract parser now records
  `needs_references` per model and task, and `usable_purposes` — the one place that says
  what the API's own evidence lets a model do — no longer counts an editing task as the
  ability to serve that purpose. So the model is not offered in Settings, is not a candidate
  for automatic selection, and a stored default naming it is unusable rather than tried; the
  adapter also refuses before spending a call (`code="reference_images_required"`). Nothing
  is hardcoded: the fact comes from Runway's own published contract. `auto_configure` also
  replaces a stored default the API's evidence no longer supports (it used to keep any
  default that existed), naming the dropped model in its report. `needs_references` is
  stored with the rest of a model's public catalogue metadata at refresh, so the rule holds
  for the account as it is today, not as the code imagined it.
- Tests: `tests/test_search_step.py` (13), three more in `tests/test_script_writing.py`,
  one in `tests/test_runway_connection.py`.

## A review that fed itself, and a studio that can start over — 2026-09-12

The Owner's live evening, read from the record: after the day closed, the Director reviewed
nine times in twenty-four minutes (≈200k completion tokens). Each review escalated the same
matter to the Owner again — an escalated message stayed OPEN, so the next review found it
and wrote the same letter (nine copies of "Am nevoie de decizia ta: Nicio sursă preluată…");
each answer to an investigation was investigated again ("Investigate: Re: Investigate: …");
and every answer that landed in the inbox triggered another review.

- **Escalated is decided** (`backend/app/agents/director.py`): an ESCALATE_TO_OWNER marks
  the message ANSWERED — it waits for the Owner in its thread, not in the inbox.
- **One open letter per matter** (`backend/app/agents/messages.py`): a letter to the Owner
  whose subject is already waiting OPEN is that letter; nothing is posted twice.
- **An investigation's answer is read, not re-investigated**: a REQUEST_INVESTIGATION on a
  message whose subject already carries `Investigate:` becomes an ACKNOWLEDGE.
- **Reviews are rationed** (`REVIEWS_PER_HOUR = 3` in `backend/app/agents/mail.py`): the
  correspondence round defers the Director's review once the hour's reviews are spent; the
  letters are still answered.
- **Starting over** (`backend/app/maintenance.py`, `scripts/reset_history.py`): deletes what
  the agents did — topics, sources, claims, scripts, storyboards, renders, QC, publications,
  letters, runs, memories, day records, the outbox, the media files — and the live ledger,
  keeping the workforce, providers, credentials, channels and their YouTube bindings, bibles,
  strategy, authorised sites and the treasury. The immutability triggers are dropped for the
  one transaction and put back; foreign keys are checked before they are re-enabled. The
  script backs up `data/studio.db` to `data/backups/` first and refuses while the studio
  answers on its port. The ledger (`read_events`) starts at the `studio.history_reset` line.
- Why the Researcher "produced no ideas": on 2026-09-11 22:55 UTC he proposed five topics,
  all about IANA example domains — the demo fixture's `example.com` page was the only source
  and claim in his memory — and `www.iana.org` is not an authorised site, so all five were
  rejected. The reset removes the demo; the rule stands.
- Tests: `tests/test_reset.py` (3), three more in `tests/test_mail.py`.

## The Director watches the film before it goes out — 2026-09-12

The Owner asked how a video with no story, in Romanian, resting on one claim, could be
produced and published. From the record: the script was a demo of 2026-09-09 whose single
claim ("the system produces 9:16 video with a SHA-256 provenance hash and automatic QC")
has no source at all and was seeded SUPPORTED; the factual gate looked only at the status;
quality control measured the file (decodable, 1080×1920, real images) and nothing else; the
voice artist checked pronunciation; the Publisher checked that the title described the
content (it did); the Director read her inbox after the upload. Every gate did its narrow
job; nobody watched the film.

- **Editorial gate** (`backend/app/agents/editorial.py`, migration 0029 `editorial_review`):
  before the publish stage prepares anything, the Director reads the whole film as data —
  topic, script, every claim with its source, each scene's picture and narration, what QC
  measured, the audience language — and, when an encoder is at hand, three frames from the
  file itself go to her model (`images` on the generate call; the assigned models declare
  vision). Her verdict is a record, an event in the ledger ("vizionat și respins — …"), a
  STATUS or ESCALATE in the inbox, and a HANDOFF letter to each department her notes name.
  A REJECT closes the storyboard, keeps the film out of the queue, and lets selection move
  on. Three things are decided without a model: a claim with no source, narration not in the
  audience language, fewer than forty spoken words. The film that went out fails all three.
- `structured_run` carries `extra` (the frames) through both attempts.
- Tests: `tests/test_editorial.py` (6, one skipped without ffmpeg on PATH).

## The studio publishes in English, and the Director says what her model did — 2026-09-12

- **Audience language** (`backend/app/agents/language.py`, `STUDIO_CONTENT_LANGUAGE`, default
  `en`): the Owner's rule that everything posted is in English, whatever language the office
  works in. The script writer, the showrunner and the Publisher are told the audience
  language at the top of their prompts; on the way out, a title or description that carries
  the marks of Romanian holds the publication with the reason (`publication_language_hold`),
  so the Director sees it rather than the audience. The first real publication went out with
  a Romanian title — that is the case this closes.
- **The first structured attempt asks the provider for JSON** (`format: "json"`): a model
  that answers plainly is held to the object (qwen3.5: 133 tokens); one that narrates
  regardless still gets the native-thinking second attempt — which, live, is what let the
  Director decide twelve messages on `glm-5.3` (five minutes narrating for nothing, six
  thinking, 22k tokens, then letters to two employees). Slow and dear; the model is the
  Owner's choice.
- **When neither attempt yields decisions, the Director's letter to the Owner says what the
  model did** — how many characters of analysis, whether the second attempt thought its whole
  budget away — and that a model answering with the object directly would finish the review.
- Tests: `tests/test_language.py` (4), `tests/test_mail.py`.

## A real cycle, watched live, and what it showed — 2026-09-12

Run on a copy of the Owner's data with the worker on and publishing disabled in the copy;
the previous night's run on the live studio read the same way. Found and fixed:

- **Analysis instead of the object.** Asked not to think aloud, `glm-5.3` wrote twelve thousand
  tokens of inventory and never reached the JSON; the Accountant's close did the same at
  smaller scale. `parse_structured` now finds the first object that validates anywhere in
  the text, and `structured_run` (`backend/app/agents/structured.py`) asks once more, with
  the model's own thinking on (`think: true`) and the same budget, when the answer has no
  object — a model that narrates with thinking off answers cleanly when it may think where
  the text is not. Asked instead to "just format" its analysis, `glm-5.3` narrated again, so
  that path was dropped. The Director's review and the Accountant's close use it. Live: the
  close parsed (Nadia held unpriced runs and said why); the review's second attempt is what
  the next cycle runs.
- **A review the Director can finish.** Sixty inbox messages in one prompt were beyond her
  model in either mode (narration at 12k tokens with thinking off; nothing at all with it
  on). The review reads twelve at a time (`REVIEW_BATCH`), comes round up to three times an
  evening while more is open, has a 24k budget, and STATUS reports nobody read in three days
  are archived (`archive_stale_reports`) so the inbox holds letters, not history.
- **Limits that threw work away.** A 220-character topic sentence rejected five proposals; a
  330-character scene and a dialogue written as a list of lines rejected an episode. Text
  fields clip (`clipped`) or join (`joined`) instead of refusing; proposals are validated one
  candidate at a time. Live: five topics proposed where yesterday none were.
- **A jammed line.** Seven topics sat SELECTED behind demo-era renders whose quality control
  had failed or been invalidated; nothing could be chosen past them. `topics_in_production`
  tells work in flight from work that stalled; a stalled storyboard is rendered again once,
  with real visuals, when an image provider is READY; invalidated verdicts are measured
  again, newest file first. Live: selection moved on, one storyboard was re-rendered with
  Runway stills and ElevenLabs narration (18 s, decodable); the five demo-era files failed
  QC honestly ("moov atom not found" — they never were videos).
- **Sources that never existed.** The Researcher names deep URLs from memory and they 404
  (`nasa.gov/mission_pages/...`); the studio fetches, it cannot search. Today's guesses are
  not retried the same day, duplicates of a title share one attempt, and research reads for
  topics that still need it — but the limit stands: without a search step, only hosts with
  guessable pages (Wikipedia articles) work reliably. `www.wikipedia.org` on the allowlist is
  the portal, not the articles: `en.wikipedia.org` / `ro.wikipedia.org` must be added.
- **Watched to the end, live**: with twelve messages and a 24k budget the Director's review
  parsed (22.8k tokens): three letters of investigation (to the Accountant, the sound
  department, the Researcher), two letters to the Owner (link the YouTube account; rule on
  the unpriced runs and the Accountant's hold), two approvals, five acknowledgements. Within
  a minute the worker had the answers: the Researcher's in words; the Accountant's model
  restated the schema's example and her letter read "..." — a reply must now be words, and
  a narrated answer gets the native-thinking second attempt like every structured task; the
  sound department answered with a blocker JSON pasted into the letter — a blocker is now
  filed as an ESCALATE in words: what stops them, what they need.
- **The ledger reads letters as envelopes**: from → to, subject, first line, and how many
  letters the thread holds.
- Tests: `tests/test_cycle_fixes.py` (7), `tests/test_mail.py` (+1); backend 566/1.

## Polish pass: rhythm, hierarchy, chrome — 2026-09-12

Read from a screenshot of every view (login, workspace, research, media, publishing,
workforce, story, runbook, treasury, settings, inspector), then changed:

- **One text scale**: 13px for reading, 12px for meta, 10.5px letter-spaced labels; panels and
  dialogs share one radius and shadow; the top bar's crumb is a label, not a Tailwind class.
- **Actions sized to their words**: dialog submit buttons and the inspector's action row no
  longer span the column (the login button alone stays full-width).
- **The scene chrome is one bar in two groups**: the scene's own controls (autonomy switch,
  zoom, fit, fullscreen) on the left, the doors to each module on the right; they wrap by
  group on a narrow scene.
- **The ledger breathes**: 13px rows with hover, tabular times, filter chips that fit, and
  the production line as a status pill.
- **Settings**: titled «Setări», tabs on a segmented track, ✕ to close like every dialog,
  cards on the panel radius, inputs with the same focus ring as everywhere else.
- **Inspector**: four stat columns, the mission set apart from the contract, contract
  items with marks.
- Evidence: `scratch` before/after screenshots per view; frontend 86/86, tsc clean.

## The stewards read the vendors' pages; the studio reads what people search for — 2026-09-12

The Owner asked how employees could choose a video model by researching online, and that
the analytics machinery exist before the numbers do.

- **Model research** (`backend/app/media/model_research.py`): the steward of a purpose
  (Kael for video and image, Lyra for voice) names up to three pages worth reading on the
  vendor's own site, the studio fetches them over the source retriever restricted to the
  vendor's hosts (`vendor_hosts` from the catalogue's documentation URL — no employee has
  a tool that reaches anywhere else), and the steward scores every model the account
  exposes (quality, reliability, speed, price with its unit, a note, the page as evidence).
  Scores and prices go into `provider_resource.capabilities/pricing` with the source, where
  `rank_candidates` and `strategy: auto` already read them (`per_second_usd` and
  `per_image_usd` now count as prices too). The recommended model becomes the default only
  where the Owner left it as a fallback (`allow_production_override`); a locked default is
  reported on. Every run ends in a letter to the Director. Weekly job
  `model_research_weekly`, Owner button in Settings → Video și sunet, `POST
  /settings/model-research`.
- **Trends** (`backend/app/analytics/trends.py`, migration 0028 `trend_snapshot`): Google's
  public "trending now" feed for the studio's country (`STUDIO_TRENDS_GEO`, default RO), read
  once a day over pinned HTTPS, kept as rows; a feed that does not answer is recorded as
  `trends.unavailable`. The Researcher's proposals get `trending_now` and
  `measured_performance` (the studio's own cohorts of three or more videos, best and worst);
  the weekly digest lists the week's trends; a trend is a hook, never a source. Daily job
  `trends_daily`, the idea stage refreshes when stale, `GET/POST /analytics/trends`, and a
  «Ce caută lumea acum» block in the research dialog.
- Tests: `tests/test_signals.py` (10), `tests/test_scheduler_worker.py`; live: the RO feed
  read once (10 trends, with traffic and news).

## The office writes letters, and the Director writes to the Owner — 2026-09-12

What stopped the day of 2026-09-11 (12/12 stages "completed", nothing produced), and the
correspondence the Owner asked for.

- **The real adapter.** The studio's connections run through `ConfiguredLLM`
  (`backend/app/integrations/llm.py`), not `app.providers.ollama`; the thinking-off fix of
  2026-09-11 had gone into the wrong class, so every run on the Owner's Ollama Cloud still
  spent its whole token budget on reasoning and returned nothing. `think: false` is now sent
  by the adapter the studio uses, `done_reason` travels back, and the socket timeout is ten
  minutes instead of thirty seconds ("time-out" was the browser and the socket, not the model).
- **A stuck employee.** Dr. Aris sat in THINKING all day — a flag left by a run the process
  never came back to — and every stage that needed him was refused "already has an active
  task". A run is now a record from the moment the model is called (`RUNNING`, closed as
  `ABANDONED` after 45 minutes); a THINKING flag with no run behind it is cleared, not obeyed.
- **Token budgets ×3** on every task (fact-check 2 100, Director review 7 500, scripts 9 000…).
- **Media setup finishes itself.** A verified image or voice connection with no default model
  or voice reported `NO_DEFAULT` until the Owner found a form; the day now runs the existing
  `auto_configure` before its preflight when readiness says something is empty.
- **Letters** (migration 0027): a message has a thread, a reply, and the letter itself
  (`thread_id`, `in_reply_to`, `body_text`). Forwarding keeps the thread, so everyone on it
  reads the same exchange. The Director's decisions are letters in the thread they answer;
  stage reports carry their reason as text. An employee's open letters enter its prompt with
  the last three turns of their thread.
- **Employees answer their mail** (`backend/app/agents/mail.py`): the worker answers, each
  pass, the letters that ask for something — in the employee's voice, in the thread — and
  the Director reads what came back at once. A question closes with its answer; a HANDOFF
  stays open until the employee says the work is done; a report waits for nobody; a thread
  past eight letters is left to the evening review or the Owner.
- **Letters to the Owner.** When a decision is the Owner's, or the day stopped, or the
  evening review could not run, the Director writes to the Owner: what stopped, where, what
  she needs. Such letters are out of her own inbox, in red in the ledger under the Owner
  chip, and wait for the Owner's reply, which closes them and reaches her; her answer to the
  Owner is again addressed to the Owner. `GET /agents/messages/owner`.
- **The page**: a letter in the ledger names both ends and opens its thread
  (`frontend/src/mail_thread.js`): who wrote to whom, when, about what, the text, how it
  ended; the Owner writes back from the bottom. The inspector's inbox opens threads too.
- API: `GET /agents/messages/threads/{id}`, `POST /agents/messages/{id}/reply`,
  `POST /agents/messages/{id}/forward`, `GET /agents/messages/owner`.
- Tests: `tests/test_mail.py` (18), `tests/test_audit_regressions.py`,
  `frontend/tests/mail_thread.test.js`, `frontend/tests/ledger.test.js`.

## The Director's mandate: grow views and retention — 2026-09-11, ZCode

The Owner's decree, made mechanical:

- **Sarah's mission** (role row + migration 0026): growing views and retention is her
  primary charge; she directs every department in writing, steers channels and topics from
  measured analytics, documents every decision.
- **Contract v3**: she may instruct any employee, change channel direction and topics on
  the measured evidence, and request a larger budget from the Accountant with the numbers
  and the reason written down. The Accountant must answer every budget request from the
  books and escalate it — only the Owner can raise a budget, and nothing in this change
  gives an agent that power.
- **The weekly review became the mandate's instrument.** Her answer is structured JSON,
  validated before anything is stored: verdict; sound indications → Lyra; video indications
  → Kael; channel direction and topic changes → LeadResearcher and ScriptWriter (and
  remembered as STRATEGY); budget request → the Accountant; escalation → the Owner. Every
  piece lands as a message that enters that employee's runs, the office hears her spoken
  summary, and her inbox keeps the full review. An answer that breaks the schema files
  nothing and says so.
- **The Accountant answers at the daily close**: every open budget request is answered with
  the day's computed figures, resolved as transmitted, and the close escalates to the Owner.

Backend 528 passed / 1 skipped; ruff, format, mypy clean; frontend 79/79. Live: server on
0026, mission and contracts confirmed, weekly review re-run honestly skipped at zero tokens.

## Sound, video and a Director who checks weekly — the roles the Owner ordered — 2026-09-11, ZCode

- **The contracts say who does what now.** Seed v2 (migration 0025, data-only; a role the
  Owner edited keeps the Owner's text): the sound artist chooses the voice and TTS model
  where the policy allows and follows the Director's written indications; the video editor
  picks film models by quality, recorded cost and what kept viewers watching; the Director
  decides from measured performance, instructs the two departments in writing, and never
  skips the weekly review while anything published exists.
- **Indications travel.** Open messages addressed to an employee enter that employee's every
  run ("WHAT IS ASKED OF YOU RIGHT NOW", identity v2, capped at ten, recorded on the run).
  The Director files a HANDOFF to the sound or video department; from the next run onward
  the employee works under it until it is resolved.
- **The weekly review exists.** Every seven days (standing policy, autonomy stop still
  gates) or on the Owner's new button in the runbook panel, the studio compiles the week's
  measured picture — views, retention, click-through per published video, per-channel
  totals, open strategy recommendations — and puts it in front of the Director through her
  identity and memory. Her answer becomes HANDOFF indications to Lyra and Kael plus a STATUS
  report in her inbox. A week with nothing published reports exactly that and spends no
  tokens; the clock reviews a week once. Live-verified: the first run answered "Revizia
  săptămânală 2026-S37: nimic publicat, nimic de măsurat".
- Failed agent runs log the exception with its traceback.
- Backend 526 passed / 1 skipped; ruff, format, mypy clean; frontend 79/79; UI checks 5/5
  in Chromium. Limits, honestly: with no publications and no bound voices/models, the review
  and the locks have nothing to chew on until the Owner configures them — the machinery
  waits ready.

## What the Owner asked about the pipeline, and an expandable inspector — 2026-09-11, ZCode

Investigation turn; one small frontend addition.

- **Sarah did not write twice by accident.** The two 21:58/21:59 ledger lines are two real
  `owner_chat` runs — the first verification pass sent the same question twice; each run has
  its own row and its own freshly generated answer. No duplication bug.
- **"Niciun cont YouTube verificat" was true when written, and no longer is.** The daily run
  started 20:17:03; the channel slots were bound to their accounts at 20:18:54 and 20:19:02
  (`channel.credentials_bound`). Re-ran the stage's own resolution against the live
  database: both bindings `publisher_ready`, the analytics adapter builds. The next run
  reports "Nicio publicare reală de măsurat" instead of the skip.
- **Agents see only what their prompt carries.** No tool-calling exists anywhere in
  `run_agent_task`: a run is one prompt to one model. Every STATUS/ESCALATE an employee
  "says" is written by deterministic pipeline code in its name — Sarah never read the
  YouTube state herself; the stage told the studio (and her report) what it found.
- **Per-channel production criteria are implemented; the data is not dressed yet.** The full
  hierarchy (organization → channel → series → episode → scene → character lock) is live in
  `media/production_policy.py`, `render_plan` resolves it per scene into real ElevenLabs
  TTS / Runway video adapters and records the plan on the render job. Channel A is FLEXIBLE
  (episode/scene may swap voices and film models, `strategy: auto` ranks candidates by
  stored quality/cost/speed/language), Channel B is CONSISTENCY_LOCKED (technology changes
  at episode/scene are ignored with a note; a locked character keeps its bound voice;
  visual locks refuse unapproved video models; changes go through the identity-change
  approval workflow). What is missing is configuration, not code: no character has a bound
  or locked voice, no storyboard names its channel, and no organization default model/voice
  is chosen — until those are set, the locks have nothing to hold.
- **«⛶ Extinde» on the Agent Inspector.** The dialog fills the screen and the entire
  history — every run, message, memory, every question and answer — becomes one
  traversable page instead of a box with its own scrollbar; the button restores the normal
  size. Verified in Chromium (expand, restore, 16/16 checks).

## The conversation reads like one: answers in words, a chat, and a window into the work — 2026-09-11, ZCode

Owner-reported: a structured answer printed as raw JSON, cramped cards, no way to watch an
employee at work. All three fixed in the frontend, against the already-recorded data.

- **An answer is written for a person.** A run whose output is JSON — chosen pages, extracted
  claims, proposed topics, scenes, a verdict — renders as sentences and lists with links;
  the model's exact output stays one click away under «Răspunsul exact al modelului». An
  answer cut off mid-list by the token limit now has its complete items salvaged and shown
  with a note, instead of printing the broken JSON (the backend already kept those items;
  the display finally agrees). Old runs whose only line was the engineered prompt no longer
  print 240 characters of instructions as the headline — the chip says what the job was and
  the full prompt stays under «Cererea completă». Nothing stopped being saved: everything
  lives on the run, as before.
- **The conversation is a conversation.** Owner questions render right in the studio green,
  employee answers left on paper. While the employee works the panel says "scrie…", driven
  by the real THINKING/IDLE events, and the history refreshes itself when the answer, a
  report or a completed run lands — including runs fired from outside the page. Verified
  with a real chat turn to Sarah (glm-5.3-flash), and again after a reload: the exchange
  was on the run all along.
- **A window into the work.** The inspector's new «Fereastră live ↗» opens a standalone
  window for one employee: the current state as a pill ("THINKING"), a head line ("Acum:
  lucrează la sarcina propose topics"), and the employee's own event chain — starting work,
  what it says, what it finishes — seeded with the day and updated from every new event,
  from the socket or the events endpoint alike. The inspector keeps every detail of each
  action; the window is the live view. The popup is styled through CSSOM because the page
  CSP (rightly) forbids inline styles in it.
- New modules `friendly_text.js` and `live_window.js`, both pure-tested (14 new frontend
  tests; 79 total). `Ledger` gained an `onEvents` callback so the live windows see exactly
  the stream the ledger renders. Verified in Chromium against the running studio:
  14/14 checks (`scratch/verify_conversation_live.mjs`), screenshots under
  `output/playwright/conversation-*.png`.

## Three things the Owner reported: a silent start, a prompt for a task, twin entries — 2026-09-11

- **Starting the day answers at once.** `POST /runbook/runs` executed the whole run inside the
  request — twelve stages, minutes of work — while the page gave up after ten seconds and said
  "Conexiune indisponibilă", though the studio kept working. The button now queues the day
  (the same `DAILY_RUN` task the schedule uses, `manual: true` so it may repeat a day the
  clock would not) and answers "Rularea de azi a fost pornită". A second press, a stopped
  autonomy, safe mode and a disabled worker each refuse with their own sentence.
  `GET /runbook/runs` also returns `pending`, and the panel shows the day on its way.
- **Where production is, while it is there.** `runbook.daily_run_started`,
  `runbook.stage_started` and `runbook.stage_finished` go through the outbox, so the ledger
  reads "etapă pornită · producția media (7/12)" as it happens and its head line says
  "Acum: producția media".
- **A task reads as a sentence.** Runs recorded the engineered prompt as what was asked, so
  five fact-checks in a row opened with the same nine hundred words and looked like one entry
  repeated — the claim was buried in the middle. `run_agent_task(..., summary=...)` carries
  the employee's own sentence ("Verific afirmația: «…»", "Închid ziua: 0 USD azi…"); the
  history shows it, with the full prompt under «Cererea completă». Older runs keep their
  prompt, trimmed to a readable line.
- **An answer nobody can read is not an answer.** Ollama counts a thinking model's private
  reasoning against `num_predict`: `qwen3.5:397b` asked for 700 tokens spent all 700 thinking
  and returned an empty response with `done_reason: length` — recorded as SUCCEEDED with
  nothing under it (17 of 18 fact-checks, both Director reviews, the Accountant's close).
  Generation now asks for thinking off, and a run with no text is recorded `EMPTY_OUTPUT`
  with the reason instead of a green line.
- **Nothing is said twice.** A report an employee files is both a message and a memory in the
  same words; the timeline now shows the message and drops the copy — the memory itself is
  untouched, so the next run still has it.
- Tests: `tests/test_phase10_runbook.py` (queued start, refusals, stage events),
  `tests/test_books_and_history.py`, `tests/test_ollama_adapter.py`,
  `tests/test_phase1_agents.py`, `frontend/tests/ledger.test.js`.

## The Owner watches the pipeline live from a ledger beside the office — 2026-09-11

- **Live ledger** (`frontend/src/ledger.js`, pure and tested): the left column of the
  workspace lists what is happening now and what happened today — every message an employee
  sends or files (by name, with its intent and subject), every task started or finished,
  every workflow stage, provider cost, budget event and Owner action — in words, newest
  first, with filters (Vorbe / Producție / Personal / Bani / Owner). The head line says where
  production stands (current stage, last daily run). Events arrive over the WebSocket as
  before; on load the ledger backfills up to 600 events through `GET /events` (limit now up
  to 300 per page).
- **Layout**: the office is first and wide (`380px | rest`, height up to 76 vh); Owner Control
  and Workforce panels, the page heading and the FOUNDATION notice are gone. Connection
  status, Settings and logout live in the top bar.
- **Autonomy switch**: one ON/OFF toggle in the office toolbar, styled as game chrome,
  replaces the STOP AUTONOMY button; it still posts `POST /owner/autonomy-stop`.
- **The books report carries the Accountant's name.** `post_run` turned Nadia's close into a
  stage report with no status and filed it as the Director's. The report now carries her
  intent, headline and holds, and is filed by her (`config/role_contracts.json`,
  `backend/app/runbook/stages.py`, `backend/app/agents/director.py`).
- Tests: `frontend/tests/ledger.test.js`, `tests/test_books_and_history.py`.

## The Accountant keeps the books; every employee has a history and a chat — 2026-09-11

Write-up: `ACCOUNTING_AND_HISTORY.md`.

- **Speech bubbles read the whole answer.** Same box, three lines; the text pages through
  at reading speed with a page counter, and the bubble stays up as long as reading takes.
  `frontend/src/speech_bubble.js` (pure, tested); the event carries 1 200 characters.
- **History and chat per employee.** `GET /agents/{id}/history` merges runs, typed messages
  and memory into one timeline (what was asked, answered, decided and why);
  `POST /agents/{id}/chat` puts the Owner's question through the employee's identity and
  policy kernel. The Agent Inspector shows the timeline above a chat input.
- **Nadia (Accountant)**: role, work contract, Character Bible, memory scope, a desk in the
  new Accounting & Treasury office (the Coffee Lounge / Commons is gone). A studio staffed
  before the role existed hires her through `seed_missing_workforce()`.
- **Budget** (migration 0024, `spending_budget`): daily and monthly limits set by the Owner
  in Trezorerie; spend measured from the books (estimates and bills), unpriced usage reported
  as such. The media stage refuses a render an exceeded budget cannot afford; every render's
  narration is costed per scene at the stored price; the Accountant closes the day in
  `post_run` before the Director's review and escalates a warning or an exceeded budget.
- API: `GET/PUT /economy/budget`, `GET /economy/books/daily`, `POST /economy/books/close`.
- Tests: `tests/test_books_and_history.py`, `frontend/tests/speech_bubble.test.js`.

## The pipeline has no empty stages left, and a channel knows its account — 2026-09-11

Everything was connected and nothing worked: the publishing screen answered "Internal error",
images and voice were reported missing, analytics found no account, and idea generation was
skipped. Audit and fixes: `PIPELINE_COVERAGE.md`.

- **The 500 is gone.** `GET /publishing/channels` asked `selected_youtube()` for the studio's
  one publisher; with two accounts connected and no channel naming either, that refusal became
  a 500, and the screen printed it into both panels. Publishing is per slot, so the endpoint
  answers per slot: the account each channel is bound to, and the accounts available to bind.
- **Channel ↔ account binding is visible and one click** in Publicare → Sloturi de canale. The
  publish stage uploads through the bound account instead of "the first channel row", the
  analytics stage measures through it, and the preflight names an unbound slot as the missing
  step.
- **`POST /settings/auto-configure`** (a button in Settings → Video și sunet) selects a service
  for a purpose where exactly one verified connection can serve it and fills only empty
  defaults, preferring a model the pipeline can call from a prompt. It reports every choice
  with its reason, refuses to resolve an ambiguous purpose, and never replaces the Owner's own.
- **Idea generation exists** (runbook §3): the Lead Researcher proposes candidates scored on
  the six criteria, deduplicated by title similarity, limited to hosts the Owner authorised;
  duplicates and unauthorised sites are dropped with the reason.
- **Research fetches its own pages** (§4): the Researcher names URLs on authorised hosts and
  the studio downloads each one itself, so an invented URL simply fails and a real one is
  stored with the text that came back.
- **The Director selects the day's topic** (§5) among candidates that have a verified claim,
  and the decision is recorded on the topic (`decided_by`, `decision_notes`); a choice that
  names nothing on the shortlist falls back to the deterministic order.
- **Every dialog is one width** (1180px, 94vw) instead of 520–950px: reports, contracts,
  source lists and production plans were being read through a narrow strip.
- Migration 0023 (`topic_idea`: scores, source plan, proposer, decision);
  `tests/test_pipeline_coverage.py`.

## The preflight names the missing step; Runway makes stills; sites are added and tested — 2026-09-11

The Owner had a verified ElevenLabs key selected for voice and a verified Runway key, and the
preflight still said "no verified image/voice provider". The connections were fine; no default
model and voice had been chosen, and nothing said so.

- `media.factory.media_readiness()`: per purpose, READY / NO_SELECTION / NOT_VERIFIED /
  NO_DEFAULT / NO_ADAPTER with the next action in the Owner's words; the preflight's image and
  voice checks use it ("X este verificat și ales pentru Voce / TTS, dar nu are un model și o
  voce implicită…").
- Runway serves images too: `RunwayImageAdapter` (text_to_image task, polled, measured from
  the bytes), a per-purpose usability from the discovered contract (`usable_purposes`), an
  image default on the connection (`MediaProductionConfig.image_model_id`, "Model imagine
  implicit" in Settings) and purpose-aware validation in the hierarchy. `CATALOG["runway"]`
  now lists `video` and `image`.
- Authorised source sites are an Owner action in the interface, not only a line in `.env`:
  `research_allowed_host` (migration 0022), `PUT/DELETE /factual/sources/allowed-hosts/{host}`
  with the same public-hostname rules as the configuration file, and
  `POST …/{host}/test`, which fetches the site's front page through the real retriever and
  records PASSED or the exact reason it cannot be read. The research modal lists hosts with
  their origin and last test; the preflight counts the tested ones. No agent has a tool that
  reaches these endpoints. Tests: `tests/test_sources_and_readiness.py`.
- `migrate()` runs table rebuilds with foreign keys suspended (the live studio's 0021 failed
  on referenced rows); regression test in `tests/test_foundation.py`.

## Every employee has an identity, a memory and a report to file — 2026-09-11

The model was never told who it was: `run_agent_task` sent the task text alone. Now every run
carries a system prompt composed from stored data (name, role, mission, allowed and prohibited
tasks, work contract, character voice, memory the role may read, standing rules) and records
the manifest of it on the run. Write-up: `AGENT_IDENTITY_MEMORY.md`.

- `config/role_contracts.json` → `role.work_contract_json` / `memory_scope_json` (what each
  role watches, investigates, corrects, lets pass, never lets pass, escalates; who it reports
  to; which stages it owns). Seeded, Owner-editable, never overwritten by a reseed.
- Character Bible entries are linked to the employees holding their roles.
- `memory_record` (04_AGENT_SYSTEM §9 classes) written by services on real outcomes with
  provenance, expiry and invalidation; read by role scope; ids recorded per run.
- `agent_message` with the spec's intents; the Director's inbox; events through the outbox.
- Lyra reviews narration, Kael diagnoses failed renders, Vera prepares publication metadata
  and may HOLD a candidate; the runbook publishes with her metadata or not at all.
- `post_run` is the Director's desk: stage reports filed by their owners, then Sarah's review
  (ACKNOWLEDGE / REQUEST_INVESTIGATION / APPROVE / REJECT / ESCALATE_TO_OWNER) as messages and
  memory, never as a change to a gate.
- API and Agent Inspector expose identity, contract, memory, messages and the prompt itself.
- Migration 0022; `tests/test_agent_identity.py`.

## Runway: name and key only, models read from the account — 2026-09-11

The Runway connection form asked for a "Model ID" and stored it as a preference; nothing
verified the key or read the account. Now it is the same flow ElevenLabs has, through the same
code: save name + key → key verified → models discovered → optional default → production.

- `DISCOVERED_KINDS` (`integrations/discovery.py`) replaces the `kind == "elevenlabs"`
  branches in save/verify/refresh/catalog/default/validation; ElevenLabs and Runway share one
  discovery, one `ProviderResource` inventory and one `MediaProductionConfig` default.
- `providers/runway.py`: a `VideoProvider`. Models come from `GET /v1/organization`
  (`tier.models`, limits, usage); tasks, ratios and durations per model from Runway's
  published OpenAPI contract for the same API version. No model id, ratio or duration in code.
  `create_generation` / `get_generation_status` implement the task + poll flow;
  `factory.video_provider_for()` and `render_plan()["video_for_scene"]` expose it.
- `CATALOG["runway"]`: `[KEY]`, runtime `media`. The Settings card shows "Model video
  implicit" with the override switch; only discovered models that make video are selectable.
  The "Verify" button is no longer hidden for Runway. `elevenlabs_settings.js` became the
  generic `provider_production.js`, driven by the catalog's `kind_info`.
- Per-scene plans resolve `video` with the scene's cast: a character with a locked `visual`
  identity accepts only video models in its approved list, on any channel. The flexible /
  locked channel rules for video models were already in place and are now tested with a real
  video catalogue (`tests/test_production_policy.py`), plus `tests/test_runway_connection.py`.

## Two channels, two production policies — 2026-09-11

Technology (providers, models, voices) is replaceable; a recurring character is a persistent
creative asset. Nexus Curiosity (MAIN_FACTUAL) may pick its technology per video; Inside The
Nexus (OFFICE_SERIAL) keeps its characters' identities whatever the technology underneath.
Audit first, reuse second, extend third: no new agents, registry, discovery or production path.

- The connection's model/voice (`MediaProductionConfig`) is now the Organization default with
  `allow_production_override`; the Settings card calls them "Model implicit" / "Voce implicită".
- A configuration hierarchy in `backend/app/media/production_policy.py`: Organization → Channel
  (`production_policy`, `production_defaults_json`, `series_rules_json`) → Series → Episode
  (`Storyboard.channel_id`, `series_key`, overrides) → Scene → Character. Later levels win,
  except a locked character field, which wins over everything. A selection is valid only if
  it names a verified connection and discovered, available resources.
- FLEXIBLE channels may ask for `strategy: auto`, ranked from stored research annotations
  (quality, reliability, latency, price, language) — never from a preference in code.
  CONSISTENCY_LOCKED channels keep technology decisions at channel/series level and refuse
  automatic voice choice.
- Character identity locks: `voice_binding_json`, `identity_locks_json` (voice, visual,
  personality, speech style), `approved_fallbacks_json`, `consistency_status`. A newer model
  reaches a locked voice only through an approved fallback. Identity changes go through
  `CharacterIdentityChange`: PROPOSED → TESTING → APPROVED | REJECTED; only APPROVED rewrites
  the bible. Rebinding a locked voice directly returns 409.
- Renders (API and daily runbook) resolve a plan per storyboard and per scene, so a scene that
  casts a locked character is voiced by that character's voice; `VideoRenderJob.production_json`
  records provider, model, voice, characters, audio seconds, synthesis time and attempts.
- Migration 0021 adds the columns and the workflow table with neutral defaults; the channel
  seed fills only a NULL policy from `DEFAULT_CHANNELS`. Rehearsed on a copy of the live
  database: connections, secrets, discovered resources, defaults, both YouTube channels and
  all characters unchanged.
- UI: channel cards show the policy (FLEXIBILĂ / CONSISTENȚĂ BLOCATĂ), the ElevenLabs card shows
  defaults with an override switch, character cards show the bound voice, locks and status.
- Tests: `tests/test_production_policy.py` covers the seven acceptance scenarios from the brief
  plus the identity workflow. 467 backend tests, 53 frontend tests, lint, types, format,
  documentation integrity and the secret scan pass. Write-up: `PRODUCTION_POLICY.md`.

## The Character Bible says who each employee is, not only how they look — 2026-09-11

The bible stored appearance and a voice profile. Everything the Owner listed as needed next —
personality, speaking style, expressions, behaviour, reference assets — had nowhere to live, so
a story engine asked to write for Elena had no stored answer for how Elena talks and would have
invented one per episode, which `../architecture/64_NARRATIVE_PERSONA_RELATIONSHIP_ENGINE.md` forbids.

- `character_bible` gains five columns (migration 0020): `personality_json` (traits, values,
  humor, social energy, conflict style, strengths and weaknesses), `speech_style_json`
  (register, cadence, sentence length, vocabulary, habits, language), `expressions_json`
  (greeting, agreement, disagreement, under pressure, sign-off, recurring joke),
  `behavior_json` (work rituals, gestures, desk habits, likes, dislikes) and
  `reference_assets_json`.
- The canonical seven are authored in full, consistent with the voice style and role each
  already had. Narrative only: none of it may change what an agent may do or whether a gate
  passes, which is the persona spec's core rule.
- Reference assets are declared slots — portrait, full body, front, side, back, as
  `../architecture/24_VISUAL_CONTINUITY_ASSET_SYSTEM.md` asks — and every one is null, because none have been
  produced. A description standing in for a missing image would let continuity QC believe a
  reference exists.
- Rows seeded before these fields are completed once on the next read; a field an Owner has
  edited is never overwritten. Rehearsed on a copy of the live database: revision 0019 → 0020,
  seven rows kept, thirty-five fields completed, second run writes nothing.
- The Character Bible panel showed `visual_profile_json.archetype`, `appearance_notes` and
  `voice.pace`, none of which the record has, so every card read "Specialist / Design canonic
  studio / default (normal)". It now shows the stored values and omits a line the bible does
  not carry.

Verified: 458 backend tests (3 new), 53 frontend tests, lint, types, format, documentation
integrity and the secret scan pass.

## ElevenLabs verification says what the key lacks — 2026-09-11

- Diagnosis of the Owner's "Cheia nu a putut fi verificată" after the dynamic-catalogue rework:
  the flow was correct; ElevenLabs answered HTTP 401 `missing_permissions` on `/v1/user`,
  `/v1/models` and `/v2/voices` because the key was created with restricted scopes. The
  message hid that behind a generic sentence.
- `MediaProviderError` now carries the vendor's short error identifier (`code`, e.g.
  `missing_permissions`, `invalid_api_key`) and the HTTP status; `media_http.error_code()`
  reads only closed-vocabulary slugs from error bodies, never free text, so no vendor message
  or key fragment can reach the UI or the log.
- Discovery maps the identifier to an Owner-facing instruction: restricted key → grant User
  (Read), Models (Read), Voices (Read) and Text to Speech in ElevenLabs → Developers → API
  Keys; invalid/revoked key → generate a new one; quota/concurrency → wait or check the plan.
  A key that reads the account but not the catalogue gets its own message.
- Tests: restricted key, catalogue-only restriction and invalid key are each explained
  (`test_integration_settings.py`); error-identifier parsing rejects free text
  (`test_media_providers.py`).

## Detail pass on the hand-drawn office — 2026-09-11

Owner direction after the Blender comparison: keep the hand-drawn art and raise it with
details, shadows and subtle animation, on every floor. Frontend only.

- Windows are now holes onto the scene's own backdrop: each one shows exactly what stands
  behind the building at its world coordinates, so the penthouse looks out on sky and tower
  tops while lower floors see the roofs and lit windows across the street, and the view
  follows the Bucharest clock (day/night). Six distant high-rises were added to the far
  skyline so upper floors are not looking at empty sky. The standalone room preview keeps a
  floor-aware fallback view.
- Window light spills down the wall and pools on the floor (warm by day, cool blue at night).
- Chairs are high-backed with a headrest and show around the seated figure; desks stand on the
  floor plane with feet, a pedestal to the floor, a bevelled lip, a mousepad and a cable.
- Characters: lit forehead, shadow under the chin and along the jaw, shaded right side of the
  torso, a second hair highlight; an idle glance every few seconds; the monitor's light
  catches the near cheek and shoulder while WORKING (state-driven, never decorative).
- Skirting boards on plaster, panelled and brick walls; the research lab's flasks bubble
  in their own colours.
- By day the ceiling fixtures dim to fill light and desk/floor lamps fade, so the windows
  carry the room; at night the fixtures and lamps carry it. Steam curls off the mug during the
  idle sip. Plants are pointed blades on stems, back blades in shade, front blades lit with a
  pale vein, instead of stacked blocks.
- The sun follows the real Bucharest clock across the sky (east at sunrise, high at noon,
  west at dusk). A desk's screen animates only while the agent seated at that desk is
  WORKING; screens without a desk (shopfront, dispatch) still follow their zone.
- Verified: 53 frontend tests, tsc/build clean, 61 FPS at fit and 2.2x (median draw 7.7 ms).

## YouTube channel avatars — 2026-09-11

- Select the API-provided thumbnail URL in high, medium, default order and persist it in each
  connection's existing JSON snapshot on authorization, completed reconnect and Verify.
- Fix the actual browser failure: `img-src` now permits the two YouTube avatar CDN origins.
  Keep all other CSP directives unchanged. No image URL or channel identity is hardcoded.
- Render a neutral CSS avatar only for a missing thumbnail; real images retain their API URL
  and send no referrer. The full frontend build and 52 frontend tests pass.
- Live Chromium verification clicked Verify for Nexus Curiosity and Inside The Nexus: both
  URLs persisted, both images decoded at 800×800, and no image CSP violations occurred.
  `scripts/verify_youtube_avatars.mjs` records live evidence separately from its missing-image fixture.
  Reconnect callback refresh and connection isolation are covered by stubbed Google regression tests.

## Pixel-art pipeline: the Research floor rendered from Blender — 2026-09-11

- The 2D office's art can now come from Blender renders instead of hand-placed rectangles.
  `art-source/blender/` builds every prop, wall/floor tile and character part in 3D from the
  palette exported out of `office_palette.js`, renders it at 1 world px = 1 sprite px with toon
  ramps (no anti-aliasing), snaps every pixel to the palette and adds the renderer's 1 px
  outline. Output lands in `frontend/public/assets/{pixel/office,environment,sprites/characters}`
  with `atlas.json` / `parts.json` manifests (anchors, screen rectangles, lamp points).
- `frontend/src/office_atlas.js` loads the manifests and recolours the key-coloured character
  parts per agent look, so identity, costume-per-role and posture-from-backend-state rules are
  unchanged. `office_rooms.js` draws a zone from the atlas only if it is in `ATLAS_ZONES`
  (RESEARCH, the quality bar) **and** the atlas has loaded; every other case is the procedural
  art, so nothing ever renders as a hole.
- The premium floor shows a 10 px 3/4 floor plane, wainscot with dado, skirting and picture
  rail, volumetric desks and chairs, a lab bench, shelves, evidence board and fillers, all under
  one key light. Desk plane, seat and hit-test geometry are the same numbers as before.
- Unreal Engine 5.8 is used as a reference tool only: `export_floor_scene.py` composes the floor
  as glTF and `art-source/unreal/build_reference_scene.py` builds a lit, ortho-camera level in
  the `AMNReference` project for lighting/composition checks. Nothing from it ships.
- Outcome: after the live comparison the Owner judged both the rendered characters and the
  rendered rooms/furniture below the hand-drawn art, so `ATLAS_ZONES` and
  `ATLAS_CHARACTER_ZONES` are empty and every floor draws the procedural art. The pipeline and
  its assets stay in the repository, switched off.
- The Character Bible (`/media/character-bible`) is now authoritative for how the office draws
  each employee: hair colour and style, glasses, headset and outfit colours come from the
  bible entry matched by employee link or first name; the per-agent hash only fills what the
  bible leaves open. Applies to every floor, procedural or atlas.
- Verified: 53 frontend tests (5 new), tsc/build clean, ruff/mypy/docs/secrets clean, live
  studio with seven agents at 61 FPS (fit and 2.2×). Write-up and honest before/after in
  `PIXEL_ART_PIPELINE.md`.

## The studio runs without the browser — 2026-09-11

- Added the background worker (`backend/app/workflows/worker.py`), the part of the studio that
  was missing for it to be autonomous at all. The scheduler could be ticked and the queue could
  be claimed, and nothing did either on its own: a daily job would sit with `next_run_at` in the
  past forever, and "autonomous" meant the Owner pressing a button every day.
- One pass, every `worker_interval_seconds` (default 30): fire the due jobs, then run the queued
  tasks through a dispatch table. `DAILY_RUN` executes the runbook. Nothing fires while the
  autonomy stop is set. The scheduled daily run happens at most once per business date; a second
  run on the same day stays the Owner's decision from the panel.
- `scheduler_tick` now enqueues a task for each fired job, keyed on the job and the slot it was
  due for, so a restart that puts the slot back finds the queued work instead of adding to it.
  `missed_policy` is honoured: a missed slot fires once under either policy — three days offline
  is one run, never three — and CATCH_UP keeps the original anchor while SKIP re-anchors to now.
- The daily job is seeded at start-up **dormant**. A schedule that fired within thirty seconds of
  the first start-up would begin a real day — agents, tokens, renders — on a decision nobody
  took. Starting it is an Owner action from the panel, recorded as `workflow.job_activated`.
- The daily-run panel shows the schedule: next and last run, the cadence, the missed-run policy,
  a plain note when autonomy is stopped, and the toggle.
- `scripts/demo_worker.py` starts the real server process with the worker on, activates the
  schedule through the API, makes the slot due, and waits without touching anything. A daily run
  appeared on its own in an isolated studio. `scripts/verify_runbook_ui.mjs` drives the panel.

## The daily run does the day's work — 2026-09-11

- Connected real work to the runbook. `execute_daily_run` walked twelve stages and nothing in the
  application ever supplied the work for any of them, so every run recorded preflight and then
  eleven SKIPPED: truthful, and idle. Eight stages now have implementations behind them.
- Performance intake measures the videos the platform is actually serving. Research reads the
  ingested sources and has a second agent check every claim against the source it came from.
  Selection takes a topic that has something verified to say. The script writer drafts from the
  supported claims, storyboards what the Owner has approved, renders it, and quality control
  measures the file. Publishing goes through the same five-point gate as a manual publication.
  The serial writes the episode for the day the studio has just closed.
- Two outcomes, kept apart: COMPLETED means the stage ran to its end, SKIPPED means it could not
  run. "We looked and there was nothing" and "we could not look" now read differently in a run.
- Where a person decides, the studio stops. A draft is left at VERIFIED_PASS for the Owner, and
  storyboarding waits for that approval. `idea_generation` and `post_run` stay unwired, because
  neither has an implementation and inventing one would be worse than the runbook saying so.
- A refusal is not a failure. A rejected script or a rejected episode is the pipeline working;
  letting it raise would have stopped the day at that stage and left the log unclosed.
- Added `select_topic`, the verb that was missing: a topic goes into production only if at least
  one claim about it is SUPPORTED. Idempotent, and it records the decision.
- `scripts/demo_daily_run.py` runs two full days in a throwaway studio, with an Owner approval
  between them. The second day renders a real 51 kB MP4 through FFmpeg and quality control
  measures it with ffprobe and fails it — placeholder visuals, duration outside Shorts limits.
  Every refusal in the run is specific and correct.

## Internal audit — 2026-09-11

- Audited the whole studio at the Owner's request. Nine defects found and fixed, each with a test
  that fails without the fix; five areas checked, found sound, and given tests so the finding
  repeats on every run. Full account: `AUDIT_2026-09-11_INTERNAL.md`.
- The serious ones: a failed question to YouTube was recorded as the answer "no", which could
  produce a duplicate upload of a video already live; the factual gate passed assets whose
  provenance it never established while claiming it had; a claim referenced but absent counted as
  supported; and Owner funding was not idempotent, so a retried request doubled the money.
- The quiet one: the studio could not find its own encoder. Three parts of the code resolved
  FFmpeg three different ways, so media inspection reported unavailable with ffprobe sitting
  beside the configured ffmpeg. One resolver now, and five media tests that had been skipping
  themselves run against the real encoder: 402 passed, 1 skipped, from 391 passed, 6 skipped.
- CI had been failing two of its eleven checks since Phase 11. Both green.
- Migration `0018_audit_gaps` links an exchange rate and a scheduled job to the event that
  created them.

## The YouTube form no longer empties itself — 2026-09-11

- Fixed the connection form losing everything typed into it whenever the window lost focus.
  Filling it means copying a client id and a secret out of the Google console one at a time, and
  the refresh-on-focus listener rebuilt the whole section on every return, so the Owner could
  never reach the end of the form.
- The refresh now runs only after an authorisation has actually been started, and never while a
  form is open. Independently, what is typed is mirrored into a draft held outside the DOM and
  restored on any redraw, dropped on cancel and after a successful save.
- Saving now closes the form before the request, so a success shows the cards instead of leaving
  the filled form on screen; a failure leaves the form and its contents untouched.

## The YouTube catalog form is gone — 2026-09-11

- Deleted the `youtube` entry from the settings catalog. It still asked for a refresh token and an
  ID canal YouTube beside the new OAuth section, which is exactly what the OAuth flow exists to
  remove. Connecting a channel through Google is now the only way to give the studio YouTube
  credentials.
- Repointed every consumer at the connection: publishing credentials, channel binding (now
  `connection_id`, with the remote channel id copied from the grant rather than from a typed
  field), the analytics provider, the runbook preflight check, and the purpose selections.
- With several channels connected and no binding, the studio refuses to choose one rather than
  taking the first row. Publishing to the wrong channel is not recoverable.
- Fixed a bug this uncovered: media providers (ElevenLabs, OpenAI media) were verified by a branch
  that built a YouTube provider, so every check raised and reported FAILED. They now use the vendor
  probe that already covered them.

## YouTube connections by OAuth, not by typing — 2026-09-11

- Replaced the hand-typed refresh token and channel id with the Authorization Code flow. The Owner
  now enters four things — connection name, Google OAuth client id, client secret, redirect URI —
  and presses **Conectează YouTube**. The studio requests `access_type=offline`, asks for consent
  only when it has no refresh token or the Owner pressed Reconnect, stores the token in the Fernet
  vault, reads the channel with `channels.list`, and shows which account was authorised.
- Added `backend/app/youtube/` and migration `0017_youtube_connections`: two tables, eight
  Owner-only routes, and one public callback protected by a single-use, ten-minute random state.
  Neither the client secret nor the refresh token is a column, and no view model has a branch that
  could return one.
- Several channels are supported and none is special: no channel id, client id, token or account
  name appears anywhere in the code, and a test greps for all five shapes.
- Reconnect, Verify, Disconnect and Delete are Owner actions. Disconnect forgets the token locally
  before revoking it at Google, so an unreachable Google still leaves the studio clean. Editing the
  client id drops the stored refresh token, because a token issued to one OAuth client cannot be
  used by another.
- Fixed two defects the browser pass found: `window.open(..., 'noopener')` returns `null`, so the
  consent tab fell through to a fallback that navigated the studio's own tab to Google; and the CSS
  class `.secondary`, used by roughly fifteen affirmative buttons across the admin surface, had
  never been defined in any stylesheet. Evidence: `YOUTUBE_CONNECTIONS.md`.

## Phase 11 — Financial evidence and the VR$ ledger — 2026-09-10

- Added `backend/app/economy/`: immutable double-entry books in VR$, posted only from real
  external evidence. Seven tables (`0016_phase11_economy`), eleven Owner-only routes, and a
  **Trezorerie** panel in the office.
- The four invariants the economy exists for are enforced by schema and service, not convention:
  one verified dollar mints exactly one VR$ once; forecasts and pending payouts can never be
  spent; a reversal posts a mirror and never deletes; the books always balance. Money is integer
  micros, and a non-USD amount without a recorded FX snapshot is refused rather than converted at
  an invented rate.
- Provider costs are mirrored too, so the treasury shows what running the studio costs and can
  report a deficit honestly. Estimates are shown but never posted.
- No route in the entire API pays, buys, transfers or checks out; a test asserts it over the
  whole OpenAPI surface.
- Owner funding has a form in the Trezorerie panel: contribution or loan, the rate entered as a
  percentage and stored as basis points, loan terms required and contribution terms refused, an
  ambiguous comma refused rather than guessed, and a non-USD amount recording its exchange rate
  and source before it is converted.
- `treasury` moves from NOT_IMPLEMENTED to PARTIAL in the snapshot module map; `procurement` and
  `financing` stay NOT_IMPLEMENTED. Evidence: `PHASE11_ECONOMY.md`.

## Agency identity: AMN-AI — 2026-09-10

- Named the agency **AMN-AI (Autonomous Machine Nexus — Artificial Intelligence)** everywhere it is
  stated: browser tab, share metadata, top bar, sign-in screen, footer, the 2D building's neon sign,
  FastAPI title, `STUDIO_NAME` default, simulated channel title and Channel B tagline, README,
  AGENTS, launcher scripts, and the distribution names (`amn-ai`, `amn-ai-ui`) with both lockfiles
  regenerated — dependency resolution unchanged (44 packages identical, `uv sync --locked` and
  `npm ci` clean).
- Added the logo as a proper asset set derived from the source artwork: top-bar mark, sign-in
  lockup with a transparent ground, `favicon.ico`, `favicon-32.png`, `apple-touch-icon.png` and a
  512 px master used as `og:image`. Quantised from a single 1.16 MB PNG to ~8 kB per page load.
  Removed the previous brand's unreferenced `favicon.svg`.
- Added `scripts/rename_studio.py`: bootstrap deliberately never rewrites an existing studio name,
  so renaming is an explicit Owner act that appends a `studio.renamed` event beside the row update.
  Applied it to the local studio; the workspace H1 now reads AMN-AI because the database says so.
- Documented the whole identity in `BRAND_AMN_AI.md`. Tests now assert the brand assets the page
  actually references and cover the rename's audit trail, idempotence and refusals.

## Pixel office v2 — 2026-09-10

- Rebuilt the 2D office's visual layer to a modern pixel-art standard, frontend only: new
  `office_palette.js` (hue-shifted five-tone ramps, one material story per department),
  `pixel_sprites.js` (outlined compiled sprites, glow cache), `office_characters.js` (26×34
  seated sprites, role costumes, deterministic looks, honest state poses), `office_rooms.js`
  (room shells, baked light, nine department interiors, workstation occlusion layers),
  `pixel_font.js`; `office_engine.js` rewritten around three cached layers with the same exports.
- Designed the system in Figma before implementing (palette variables, quality-bar floor at 4x,
  character and HUD components, building/layout spec).
- Scene chrome: slim dark bezel and high-contrast dark controls; admin panels unchanged.
- Removed the superseded `office_art.js`. Added 5 frontend tests (43 total), a standalone room
  preview harness and screenshot/FPS review scripts. Backend, API, events and data untouched.

## Foundation 0.1 — 2026-09-09

- Read the full original 83-document specification package; established its implementation baseline.
- Separated architecture (78 documents) and live project tracking (5 original documents) at Owner request.
- Added indexed document hashes, link/inventory validation and failure tests for accidental spec edits.
- Added FastAPI/SQLAlchemy/Alembic backend, configured local credentials, persisted initial world and
  Owner policy, immutable events, idempotent/versioned STOP command and private snapshot/event routes.
- Added responsive HTML/Tailwind/JS foundation shell, truthful unavailable modules and stale-state UI.
- Added locked dependencies, structured logs, security headers, CI baseline and secret scan.
- Verified 26 Python tests, 3 JS tests, lint/types/build, schema upgrade, concurrency, restart and browser.
- Preserved all unimplemented core/V4/V5 requirements; no LLM/media/publishing integration claimed.

## v2 — 2026-09-09

### Strengthened realism
- Added strict Intent → Policy → Capability → Execution → Verification → Commit model.
- Added tool/action receipts.
- Added UNKNOWN provider/capability states.
- Added realistic local-PC vs always-on deployment constraints.

### Strengthened Director
- Defined broad CEO responsibilities.
- Added self-permission/self-guardrail restrictions.
- Added strategy-change and workforce-evaluation safeguards.
- Added provider discovery vs actual onboarding distinction.

### Strengthened employees
- Added Role Contracts.
- Added capability requirements and least privilege.
- Added safe firing with in-flight task handling.
- Added explicit model-upgrade vs employee-replacement semantics.

### Strengthened automation
- Added durable workflow requirements.
- Added scheduler safety.
- Added leases/locks, idempotency, outbox, retry/backoff, circuit breakers and watchdogs.
- Added external side-effect reconciliation.

### Strengthened UI truthfulness
- UI success only after backend verification.
- Added snapshot/replay, duplicate/out-of-order event handling.
- Added persistent office world state.

### Strengthened research/security
- Added prompt-injection defense.
- Added memory provenance and poisoning controls.
- Added source freshness/staleness.

### Strengthened media/serial
- Added Character Bible and provider-capability constraints.
- Added live operational vs dramatized serial dialogue separation.
- Added media rights/provenance requirements.

### Strengthened operations
- Added provider contract testing.
- Added failure/recovery playbook.
- Added backup/restore, disk retention and deployment guidance.
- Added master acceptance checklist and risk register.

## v3 — 2026-09-09

### Deep file-by-file hardening
- Re-reviewed every v2 document.
- Added Policy Kernel and independent hard gates.
- Added bounded agent communication, deadlock and rework limits.
- Added daily preflight and admission control.
- Added compensation/manual repair model.
- Added prompt/context/memory lifecycle architecture.
- Added model drift and role-suitability revalidation.
- Added multi-objective Director scorecard.
- Added public character alias / provider-brand separation.
- Added WorldBuilder contract for dynamic office growth.
- Added narrative privacy/sanitization.
- Added anti-repetition/novelty gates.
- Added deterministic media fallback.
- Added CI/CD, feature flags and rollback requirements.
- Added reliability SLOs and burn-in.
- Added data privacy classification.
- Added transfer/sale-readiness requirements.
- Added dedicated v3 specifications for governance, prompts/memory, tool permissions, evaluation, reliability, security, public community, IP, daily runbook, world evolution, schema versioning and launch readiness.


## 2026-09-09 — V4 Organizational Expansion
- Added dynamic Department Factory and manager delegation.
- Added Marketing & Communications architecture for YouTube, TikTok, Instagram, Facebook and Telegram.
- Added same-day truthful teaser → next-day Office Serial loop.
- Added marketing attribution and experiments.
- Added Market/Competitive Intelligence.
- Added HR/People Ops, persistent fictional personas, birthdays and relationship graph.
- Added Finance/Accounting/FinOps separation.
- Added Legal/Rights/Compliance department.
- Added future Advertising/Paid Media/Sponsorship architecture.
- Added Company Calendar, milestone triggers and team-building/no-production event mode.
- Added organizational-bloat controls and capacity planning.
- Extended data model, events, commands, tests, UI mappings, governance and acceptance criteria.


## 2026-09-09 — V5 Economy Expansion
- Added 1:1 USD ↔ VR$ market-anchored virtual economy.
- Added financial truth layers and double-entry ledger requirements.
- Added revenue settlement/reversal/idempotency rules.
- Added Owner capital contribution and Owner loan models.
- Added market-referenced virtual financing with debt-capacity gates.
- Added Procurement + VendorShop + NEW/USED current market quote sourcing.
- Added Asset Architect and market-priced office asset lifecycle.
- Added treasury dashboard, runway, burn, forecasts and virtual financial statements.
- Added strict no-real-money-spend boundary.
- Added financial events to UI, Story Engine and marketing provenance.

## Post-audit remediation — 2026-09-09

Answers `docs/project/AUDIT_2026-09-09_EXTERNAL.md`. Decisions recorded as D-AUDIT-001/002.

### Truthfulness (breaking behaviour changes)
- Channel slots seed as `NOT_CONFIGURED` with no remote ID; status is derived from real
  configuration only. Previously seeded as `CONFIGURED` with invented channel IDs.
- Publishing without `STUDIO_YOUTUBE_*` credentials now returns 503 `PublisherNotConfigured`.
  The silent fallback to the simulated adapter is removed.
- Simulated uploads are recorded as `PUBLISHED_SIMULATED` with `sim:` identifiers and no platform
  URL, and are labelled as such in the UI.
- The renderer no longer writes a placeholder file named `.mp4`. It encodes a real H.264
  1080x1920 video with FFmpeg or fails with `RenderEngineUnavailable` (HTTP 503).
- QC measures the file with `ffprobe` and recomputes the provenance digest instead of trusting the
  renderer's own metadata; placeholder visuals are blocked from publication; the character-drift
  check reports `NOT_IMPLEMENTED` instead of passing.
- `POST /media/storyboards/sample` replaced by `POST /media/storyboards/demo-fixture`, which
  creates `UNVERIFIED` claims only.

### Correctness
- Fixed `DetachedInstanceError` in the FFmpeg render path (ORM objects used after session close);
  that path had never executed successfully.
- Gate refusals now persist the `BLOCKED_GATE` record and `publishing.gate_failed` event.
- Missing media asset or channel returns 404 instead of a 500 database integrity error.
- `GET /publishing/channels` no longer writes; seeding moved to `POST /publishing/channels/seed`.
- YouTube upload is chunked and resumable (`Content-Range`, 308 handling); synthetic-content
  disclosure is sent; `reconcile_upload` is invoked before any retry.
- QC minimum score (0.90) is actually enforced by the publishing gate.
- Removed a hardcoded Windows storage path from `assembler.py`.
- Fixed a `TypeError` in `scripts/bootstrap.py` that broke first-time `.env` creation.

### Found and fixed while running the application under Playwright
- **WebSocket gateway repaired.** `websockets` was missing from the dependencies, so uvicorn
  answered the `/api/v1/ws` handshake with 404 and the 2D office never received live events.
  Added `websockets>=13,<16` to `pyproject.toml` and regenerated `uv.lock`. Run `uv sync`.
- **Script approval path added.** `generate_script_draft` produced `VERIFIED_PASS` scripts while
  storyboarding required `APPROVED`, and no approval endpoint existed — the real pipeline could
  not reach the media stage at all; only the fabricated `sample` endpoint could.
  New `POST /api/v1/factual/scripts/{id}/approve` re-runs the factual gate at approval time.

### Data correction
- Migration `0007_correct_fabricated_records` (data-only) repairs existing databases: fabricated
  channel identities cleared, simulated publications relabelled `PUBLISHED_SIMULATED` with their
  dead YouTube URLs removed, and all prior `PASSED` QC reports invalidated so they are re-run by
  the measuring gate. Startup now expects revision `0007`; Phase 7 analytics starts at `0008`.

### Developer experience
- `start.cmd` / `scripts/start.py`: one idempotent command that syncs dependencies, prepares the
  database, builds the frontend and starts the server, then prints a preflight report naming the
  integrations that are actually configured. It stops on a failed step instead of starting a
  half-built studio. README updated accordingly.

### Configuration
- `STUDIO_YOUTUBE_CLIENT_ID`, `STUDIO_YOUTUBE_CLIENT_SECRET`, `STUDIO_YOUTUBE_REFRESH_TOKEN`,
  `STUDIO_YOUTUBE_CHANNEL_ID` and `STUDIO_FFMPEG_PATH` added to `Settings` and `.env.example`.

### Tests
- New `tests/test_truthfulness_gates.py` (10 tests) locking the governance invariants.
- Render tests skip when FFmpeg is absent instead of exercising a fake path.
- 87 passed with FFmpeg; 85 passed / 3 skipped without it.

### Documentation
- `CURRENT_STATUS.md` corrected: Phases 4, 5 and 6 are marked PARTIAL with their exact unmet
  acceptance criteria. `PROJECT_STATE.json` brought up to date (was five phases stale).

## Interface consistency pass — 2026-09-09

Decision D-DESIGN-001.

- **Single colour system.** `frontend/src/style.css` rebuilt around `:root` design tokens derived
  from the original template. The 97 ad-hoc colour literals are gone; components reference tokens.
- **Dialogs re-skinned** from the Tailwind dark theme to the studio's paper surface, with tokenised
  borders, inputs, buttons, tabs, cards and badges.
- **Semantic state colours** unified: published / validated / simulated / blocked and channel
  statuses now use consistent background-border-ink triples and stay mutually distinguishable.
- **2D office** framed like the template's office scene; structural scene colours retinted from
  slate blue to the brand greens. Department accents and character art left untouched.
- **Icons removed.** All pictographic emoji dropped from buttons, headings and badges; labels
  rewritten in sentence case.
- **Media panel corrected**: it showed the storyboard UUID under the label "Provenance SHA-256" and
  scored the unimplemented continuity check as 0%. It now shows the measured resolution, duration
  and codec, the real verified digest, and an em dash for the check that does not exist.
- **Accessibility**: `scratch/verify_design.mjs` measures computed contrast in the running page;
  three tokens were darkened to clear WCAG AA. 14/14 design checks and 27/27 functional checks pass.
- **Toolbar highlight fixed.** `cam-btn-active` was hard-coded on the "Cercetare" button, so it
  looked permanently selected. The highlight is now bound to whether that panel is actually open.
- **Leaving fullscreen restores the office.** `.office-scene-container` had no height of its own,
  so it was sized by the canvas while the canvas was sized by it; on exit nothing shrank the canvas
  back and the scene stayed at fullscreen dimensions. The container now has a definite responsive
  height and the engine resizes across two animation frames.
- `scratch/verify_fullscreen.mjs` (new, 10 checks) measures the canvas before, during and after a
  fullscreen round trip and asserts the toolbar highlight follows the open panel.

## Office renderer rebuild — 2026-09-09

Decision D-DESIGN-002. `frontend/src/office_engine.js` rewritten (~2,200 lines).

- **Scene**: dusk sky with stars, moon and drifting clouds; two parallax skylines with lit
  windows; a street at the foot of the building with traffic, pedestrians, swaying trees, lamp
  light pools, a bus stop and planters. All of it seeded scenery, connected to no data.
- **Building**: cutaway shell with structural columns, parapet, roof plant, extractor fans,
  antenna beacon, satellite dish, neon sign, and a glass elevator whose cab travels the shaft.
- **Interiors**: every department has its own furniture — executive bookshelf and awards, research
  evidence board with pinned cards and string, storyboard wall, vocal booth with foam, boom mic,
  mixing desk and VU meters, edit bay with a scrubbing timeline, server racks with per-unit LEDs
  and fans, lounge with espresso steam and a water cooler, distribution console with a radar
  sweep. Empty wall runs are filled with cabinets, posters, whiteboards, coat racks and plants.
- **Characters**: appearance derived from the agent id (skin, hair style and colour, outfit,
  glasses, headset, build), so no two look alike; blinking, breathing, sipping and stretching on
  per-character phases; typing, thinking and sleeping driven strictly by backend state.
- **Rendering**: 1:1 offscreen world buffer blitted without smoothing for crisp pixel art; cached
  static layers; ceiling light cones, screen spill and lamp pools composited additively.
- Nameplates moved onto the floor slab with the state inline, so they no longer collide with the
  floor header below them.

## Office scene corrections — 2026-09-09

Decision D-DESIGN-003.

- **Backend layout**: ground floor doubled in height (200px) and re-divided; new `SHOP` zone
  `ad_shop` for street-level advertising sales, with no desks assigned. Building height 690 -> 740,
  layout height 800 -> 1000. `tests/test_phase3_office.py` extended: floor zones must not overlap
  and every desk must stand inside its own zone.
- **Street rebuilt below the building**: plinth, pavement, kerb, two-lane carriageway with a
  pedestrian crossing, far pavement with drains and planters. Pedestrians can no longer overlap
  the ground floor; `streetGeometry()` is exported and covered by two new frontend tests.
- **Human scale**: pedestrians drawn at the same size as the staff inside; cars ~90px, vans and a
  168px bus, with wheels and glazing to match. Street lamps moved to the building's flanks.
- **Lift**: parked and dark by default, labelled IDLE. It moves only when a workflow token changes
  floor, waits at the delivery floor, then returns to the ground floor.
- **Readability**: nameplates use double-scale type on an opaque plate; wall sconces added to
  tall floors; `M` and `W` glyphs redrawn.

## 2026-09-10 — Street and nameplate corrections (Owner feedback)

- **Bus**: removed the invented route number "12"; the destination blind stays blank.
- **Traffic**: vehicles spawn spread across their lane and follow their lane leader (speed matching
  plus a hard 24 px bumper clamp, seam-aware), so same-lane vehicles no longer pass through each
  other. `makeTraffic`/`updateTraffic` are exported and covered by three new frontend tests
  (spawn spacing, catch-up scenario, 15-minute mixed-timestep seam run).
- **Nameplates**: name type reduced from double to single scale on a light paper card with dark ink
  and a muted state line — smaller plates that stay readable over the dark floors.

## 2026-09-10 — State tag above the character (Owner feedback)

- The floor nameplate now carries the agent name only. The runtime state (IDLE, WORKING, …)
  floats above the character's head on a dark chip in the department accent, and the thinking
  bulb and sleeping Z marks were raised so none of the three overlap.

## 2026-09-10 — Settings agent LLM test + verified Ollama Cloud connectivity

- New `POST /api/v1/settings/agents/{id}/test`: one real run through the assigned model via the
  policy kernel; the Settings → Agenți cards gained a "Testează răspunsul" button that shows the
  model's answer or the block reason. Verified live against Ollama Cloud (glm-5.3-flash,
  gpt-oss:120b). New settings test; suite 16/16.

## 2026-09-10 — Whole-tree lint and type cleanup

- `ruff format` across the tree, 65 long lines wrapped (string content preserved), unused/unsorted
  imports removed, SQLAlchemy `== True` → `.is_(True)`, `zip(..., strict=False)`, import order fix.
- mypy: typed the ffprobe result and storyboard scene payloads (`dict[str, Any]`).
- Baseline now passes every README check: ruff, ruff format, mypy, pytest 137, frontend 11,
  docs integrity, secret scan.

## 2026-09-10 — Live speech bubbles with the agent's real answer

- `run_agent_task` emits `agent.message_sent` (transactional outbox) carrying the model's real
  output when a run succeeds with visible text; failed and text-less runs stay silent.
- The app lifespan now dispatches the outbox every second, so committed events are broadcast to
  WebSocket clients live (previously the dispatcher was never invoked and the office only saw
  the one-shot replay at connect).
- Activity log labels the event "Agentul a răspuns". Verified live: an API-triggered run made
  the answering bubble appear above the agent in the 2D office.

## 2026-09-10 — Research agent extracts claims from real sources; office fully live

- `agent.state_changed` (THINKING/IDLE) now flows through the outbox during runs, and
  pause/resume events were moved onto the outbox — state tags and pause animations in the
  2D office follow backend events live.
- New `POST /factual/sources/{id}/extract-with-agent`: the research agent reads the sanitized
  source (inert boundary, prompt-injection safe) and extracts schema-validated atomic claims
  via its assigned model. Claims stay UNVERIFIED; unparseable output is rejected; truncated
  JSON keeps only complete objects. The agent announces "Am extras N afirmatii..." as its
  speech bubble instead of raw JSON.
- Verified live end to end: real IANA page fetched via the retrieval adapter -> Dr. Aris
  (nemotron-3-super) -> 9 accurate UNVERIFIED claims -> bubble in the office.

## 2026-09-10 — Re-audit of third-party work; the seed stops claiming a healthy provider

- **Independent verification of the newest external work.** Re-ran the full battery against a
  clean checkout rather than trusting the tracking documents: pytest, ruff, ruff format, mypy,
  `tsc`, the frontend unit tests, the Vite build, the documentation hash integrity check and
  the three Playwright suites. Everything passed and nothing regressed. Read the new
  security-sensitive modules line by line — the credential vault, the Settings save/check path,
  the SSRF-hardened retrieval adapter and the research agent pipeline — and confirmed each of
  their stated properties holds in the code: a saved connection is `SAVED` and never verified,
  only a real probe writes `VERIFIED`, retrieval refuses anything but an allow-listed public
  HTTPS host on a DNS-pinned connection, and every extracted claim is stored `UNVERIFIED`.
  Confirmed the two edited architecture documents match their indexed hashes and that the
  decision log records the edit, as the process requires.
- **Fixed: the workforce seed asserted a health check that never happened.** A freshly
  bootstrapped studio recorded the local Ollama endpoint as `HEALTHY` with a health-check
  timestamp and three models as available and verified, on a machine with no Ollama installed —
  the same falsehood the Owner first reported about the YouTube channel. The seed now records
  the provider `NOT_CONFIGURED` and its models `SEEDED_UNVERIFIED` with no timestamps; only a
  real model sync may record health, availability or a verification time. See D-TRUTH-002.
- **Fixed: the seeded provider could not be verified at all.** It had no adapter registered, so
  every check failed with "no adapter registered" and the unverified state was permanent. The
  adapter is now registered at startup, Settings lists the endpoint with a working
  "Verifică și încarcă modelele" button, and an unreachable endpoint answers 503 with what went
  wrong instead of a generic internal error.
- Migration `0009_unverified_seeded_provider` withdraws the claim from existing databases.
- Baseline: ruff, ruff format, mypy, pytest 152 passed / 1 skipped, frontend 11, `tsc`, build,
  docs integrity; Playwright 27/27 + 14/14 + 10/10 + 8/8 (new provider-honesty suite).

## 2026-09-10 — Phase 7 analytics live; lift courier; the ground floor built out

- **Analytics wired, simulator deleted.** The Phase 7 module now runs: router mounted, models in
  `Base.metadata`, migration `0010_phase7_analytics`. Before wiring it, the deterministic
  analytics adapter — which invented view counts, retention and CTR from a hash — was removed
  outright, and the fallback that would have measured a never-uploaded publication under its
  internal row id with it. With no verified YouTube connection, ingestion answers HTTP 503 and
  says plainly that the studio does not estimate or simulate audience figures. This mattered
  more than a display bug: the learning loop reads these numbers back and turns them into the
  Director's recommendations, which change the topic and hook weights the studio writes to.
- **The YouTube Analytics adapter stopped ignoring the reporting window.** Every query used to
  send the same fixed date range, so an all-time report could be stored labelled "24h".
  Impressions and CTR are now read from YouTube's own metrics or reported as zero — never
  back-computed from views.
- **The lift carries someone.** A workflow token changing floor now runs a full delivery: the
  cab comes to the floor, doors open, a runner boards with the work, doors shut for the ride,
  and the runner walks the token to its new department. Doors part only at a floor, as a real
  lift's do. With no workflow running the cab still stands still.
- **The double-height ground floor was built out** — ducting, a service mezzanine with railing,
  pendant lights, and one wall fixture per department (rack status wall, canteen board, dispatch
  board, and an empty "YOUR AD HERE" hoarding over the shopfront).
- **Fixed: workflow tokens were drawn in the wrong departments.** The stage-to-position table
  was hardcoded pixels that predated the taller building — research appeared in the executive
  suite and publishing floated outside the wall — and because the lift is dispatched by the
  zone a token lands in, it also sent the cab to the wrong floor. Stages now name a department
  and the position comes from the layout the backend serves.
- Baseline: ruff, ruff format, mypy, pytest 163 passed / 1 skipped, frontend 17, `tsc`, build,
  docs integrity, secret scan; Playwright 27/27 + 14/14 + 10/10 + 8/8 + 9/9.

## 2026-09-10 — The research loop is usable; verification is independent; inspector fixed

- **Fixed (reported by the Owner): the agent panel showed a model nobody had assigned.** The
  "model" field was a fixed string in the HTML — every agent read `glm-5.2:cloud` whatever was
  chosen in Settings — and the office layout carried no model at all. Assignments now carry the
  agent's real model, its provider, and whether that provider has confirmed it; the panel
  distinguishes "not assigned", "assigned · unverified" and confirmed, and only a confirmed
  model enables a run. Settings now refreshes the office after every change, so a reassignment
  lands without reloading the page. See D-UI-005.
- **The Phase 4 research loop can be driven from the interface.** Fetch a source from a site you
  authorised, have the research agent read it, then verify each claim — all of it previously
  existed only behind `curl` and a shell script.
- **Independent fact-checking.** A second agent, never the one that extracted the claim, checks
  it against the stored source; the studio refuses when no independent agent exists rather than
  letting an agent confirm its own reading. A SUPPORTED or REFUTED verdict must quote the source
  verbatim, and **a verdict whose quote is not in the source is rejected whole — the claim stays
  UNVERIFIED**. UNCERTAIN was added so a checker that finds nothing can say so instead of
  guessing. Migration `0011` records who extracted and who verified each claim.
- **The retrieval allowlist is configuration, not application state.**
  `STUDIO_RESEARCH_ALLOWED_HOSTS` in `.env`, empty by default (retrieval off). The request
  carries no host field, and an entry naming this machine or a private range is refused at
  start-up.
- **Fixed: refusals were replaced by a generic message.** The interface now shows the server's
  own explanation — which host is not authorised, why a provider did not answer — instead of
  "try again", which was hiding the part that says what to do.
- Baseline: ruff, ruff format, mypy, pytest 199 passed / 1 skipped, frontend 17, `tsc`, build,
  docs integrity, secret scan; Playwright 27+14+10+8+9+9+18 = 95 checks.

## 2026-09-10 — Scripts written from verified claims, cited scene by scene

- **The script writer drafts only from SUPPORTED claims**, and every scene names the claims it
  rests on. A scene citing an identifier that was never supplied rejects the whole draft, not
  just that scene: the narration around an invented citation came from somewhere other than the
  evidence, and there is no way to tell how far that reaches. A topic with no verified claim
  produces no script at all rather than one that would be blocked later.
- **The spoken text is the attributed text.** The stored voiceover is assembled from the scene
  narrations, so there is no separate field a model could fill with something the citations do
  not cover.
- **The Research panel now shows scripts** scene by scene with their citation counts, and offers
  approval only on a draft that passed the factual gate. Approval re-runs that gate — a claim
  refuted since the draft was written blocks it — and the refusal now says how many claims
  stopped being supported instead of showing a raw exception.
- Baseline: ruff, ruff format, mypy, pytest 211 passed / 1 skipped, frontend 17, `tsc`, build,
  docs integrity, secret scan; Playwright 106 checks across 8 suites.

## 2026-09-10 — Media adapters, ready for the credentials the Owner will add

- **Real TTS and image adapters** (ElevenLabs, OpenAI Images) that call documented endpoints and
  return what came back. A vendor failure raises; there is no fallback asset, because a
  substitute would flow into QC and the publishing gate as though a provider had made it.
- **Every figure is measured from the bytes received** — narration duration counted from the MP3
  frames, image size read from the PNG header — never taken from the request. Where a vendor
  offers nothing (no word alignment, no seed), the adapter reports nothing instead of echoing the
  request back as if it had applied.
- **A render uses a provider only when it is both verified and selected** for that purpose. With
  none, the render still happens and is labelled placeholder content, which QC keeps out of
  publication — unchanged. The recorded provider name is always the generator that actually made
  the frames, and it drives the asset, the event and the QC report from one value.
- `GET /media/providers` says which generators a render would use and whether its output could be
  published. Settings stops telling you these vendors are unconnected once an adapter exists.
- Baseline: ruff, ruff format, mypy, pytest 241 passed / 1 skipped, frontend 17, `tsc`, build,
  docs integrity, secret scan; Playwright 106 checks across 8 suites.

## 2026-09-10 — Research hands work to production

- **An approved script now reaches production.** The Media panel opens with the approved scripts
  no storyboard has been built from yet — with their scene count and how many verified claims
  each rests on — and builds the storyboard from there. Previously the only creation control was
  the demo fixture, so the two halves of the studio were joined by test data.
- Only APPROVED drafts are offered: approval is what passing the factual gate means. A script
  leaves the queue the moment its storyboard exists, so nothing is produced twice by accident.
- **The panel says what a render will be before you ask for one** — without a verified image
  provider the output is placeholder content that QC blocks from publication. That was knowable
  in advance; reading it in a failed QC report afterwards was the wrong way to find out.
- Baseline: ruff, ruff format, mypy, pytest 244 passed / 1 skipped, frontend 17, `tsc`, build,
  docs integrity, secret scan; Playwright 117 checks across 9 suites.

## 2026-09-10 — Phase 8: the studio can recommend staffing changes, and only recommend them

- **Evidence is counted from the studio's own record** — agent runs and their outcomes over a
  30-day window, queue backlog, dead-lettered tasks. No model is asked what it thinks of a
  colleague; a fluent judgement with nothing under it is exactly what this must not produce.
- **An agent with no runs is shown as unmeasured, not as flawless.** Its failure rate is unknown,
  not zero.
- **Fewer than five runs never becomes a recommendation**, at any failure rate. The service
  refuses to build such a proposal and the database refuses to store one.
- Each proposal carries the numbers it was built from, and the panel shows them — a staffing
  decision has to be checkable months later.
- **A high failure rate proposes suspension, not termination**: the cause is usually the model or
  the provider, and suspension is reversible.
- **Approving is the Owner's act.** An autonomous approval is refused outright rather than
  quietly turned into a pending proposal, and a rejection requires a written reason.
- Employment is now a record with its own history, so a rehire opens a new period instead of
  reviving a closed one — TERMINATED cannot become ACTIVE by editing state, as the spec requires.
- New "Personal" panel; migration `0012_workforce`.
- Baseline: ruff, ruff format, mypy, pytest 263 passed / 1 skipped, frontend 17, `tsc`, build,
  docs integrity, secret scan; Playwright 126 checks across 10 suites.

## 2026-09-10 — Phase 9: the daily log, and a serial that cannot invent the day

- **The day is counted from the event stream**, in the studio's own timezone — counts per event
  type, the roster, and the events worth dramatising. No model writes any part of the log,
  because the log is what every episode is checked against.
- **A closed day does not change**, and a date can only be closed once. Otherwise an episode
  could become grounded after the fact.
- **Every beat cites the real events it dramatises**, and a citation that is not in that day's
  log fails the whole episode — not just the beat. The spec's forbidden-fabrication list (a fake
  hire, an invented outage, a decision attributed to the wrong person) is all enforced by this
  one rule: those things have no event to cite.
- **The cast is the day's roster.** The serial cannot put someone in a room the record says they
  were not in.
- **A quiet day produces no episode** and the panel says so, instead of offering a button that
  would fail. A quiet day is a fact about the studio.
- `GET /story/episodes/{id}/grounding` re-checks a stored episode against its log, so the
  grounding claim is audited rather than trusted.
- New "Jurnal" panel; migration `0013_story`.
- Baseline: ruff, ruff format, mypy, pytest 284 passed / 1 skipped, frontend 17, `tsc`, build,
  docs integrity, secret scan; Playwright 137 checks across 11 suites.

## 2026-09-10 — Phase 10: the daily runbook, and a run that reports only what it did

- **A preflight that never rounds up.** Every capability is checked and listed with what it
  found — the passing ones too, so the Owner can see what was looked at. A missing media provider
  degrades the day; a stopped autonomy gate, no verified model or no FFmpeg blocks it. The
  DEGRADED summary says in words that stages will be skipped and the output will be
  unpublishable, because "DEGRADED" on its own invites being read as "fine for now".
- **The preflight probes nothing over the network** and changes nothing: reading it twice cannot
  start a run.
- **The run's status is derived from its stages**, never asserted by a caller or a stage. A stage
  reporting COMPLETED does not make the day completed while another was skipped.
- **All twelve stages appear in every run record**, including the ones with no implementation
  connected (SKIPPED, with the reason) and the ones after a stop (BLOCKED, naming where it
  stopped). A record listing only the stages that ran would mislead by its shape alone.
- **A blocked preflight closes no daily log.** A partial day is still a day; a day the studio
  never started is not, and writing a log for it would put work that did not happen into the
  record tomorrow's episode is checked against.
- **A failed stage enters safe mode and stops autonomy**, so an unattended studio does not carry
  on into the next day with an unexamined fault behind it. A second failure does not open a
  second record and obscure when the incident began.
- **Leaving safe mode requires a written note and does not restart autonomy** — examining an
  incident and deciding the studio should act again are separate decisions.
- New "Rulare zilnică" panel; migration `0014_runbook`.
- Baseline: ruff, ruff format, mypy, pytest 304 passed / 1 skipped, frontend 17, `tsc`, build,
  docs integrity, secret scan; Playwright 149 checks across 12 suites.

## 2026-09-10 — Outdoor electronic clock

Added a pixel seven-segment clock marked BUCURESTI, 24-hour HH:mm, using Europe/Bucharest including DST. Street schedules now use the same timezone. 35 frontend tests and browser checks passed.

## 2026-09-10 — Street clock placement and consistent controls

Clock is now freestanding on the right side of the street. Bottom control dock CSS is emitted as a same-origin file, fixing CSP-blocked inline styling. Browser placement checks pass in desktop/fullscreen/mobile.

## 2026-09-10 — Correct agent inspector model assignment

Fixed false “Niciun model alocat” when an older office projection omits model metadata. Inspector now loads persisted agent/model details, handles errors explicitly and discards late responses. All 7 live agents matched Settings in read-only browser QA; 38 frontend tests passed. See `INSPECTOR_MODEL_FIX.md`.
