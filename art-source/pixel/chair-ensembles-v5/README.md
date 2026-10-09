# Original integrated person-and-chair sprites — 2026-10-09

Requested by the Owner: “o mai buna abordare ar fi sa ii generzi cu tot cu scaun”.
Final local production assets (unmodified copies of built-in image_gen.imagegen outputs):

- [staff-a-chair-v5.png](../../../frontend/public/assets/pixel/staff-a-chair-v5.png): Sarah,
  Aris, Elena, Marcus; 1227 × 1282 RGBA; 4 rows × 4 authored poses.
- [staff-b-chair-v5.png](../../../frontend/public/assets/pixel/staff-b-chair-v5.png): Lyra,
  Kael, Vera, Nadia; 1230 × 1278 RGBA; 4 rows × 4 authored poses.
- [studio-chair-cleanplate-v5.png](../../../frontend/public/assets/pixel/studio-chair-cleanplate-v5.png):
  1536 × 1024 RGB edit of the approved studio, removing its eight empty chairs/stools.
  Runtime samples this plate through traced chair silhouettes ONLY; the original scene
  remains the base. This edit is not a wholesale replacement of the building.

Source output IDs, in C:/Users/mario/.codex/generated_images/01a117b7-74db-7ad3-a99b-9e6a0194302e/:

- Final A: exec-8ea5b066-ad7d-43fc-858c-dc53820a0e7b.png
- Final B: exec-9f80bf82-d35a-4be5-b524-98a25ab6c63d.png
- Final clean plate: exec-68bd0486-02a9-486d-a3a9-1afb0f831a84.png
- Rejected earlier edits: exec-123aaba7-f02d-40b7-b05a-0fdc8fa4a951.png,
  exec-008a1a8f-554a-423c-994a-8c1ba200460f.png
- Unshipped separate-body trials: exec-754b4425-301b-49da-b316-78ecc5556449.png,
  exec-9c12ad56-74c2-49c8-a927-4cad65c1892e.png

Seven built-in calls total, four drafts retained here and three selected final assets.
Exact prompts are in [prompts.json](prompts.json). Transparent outputs retain original alpha;
registration reads it for bounds only, without bitmap editing. Final content hashes and
bounds are pinned in [pixel_actors.json](../../../config/pixel_actors.json).

The four authored poses are NOT interchangeable animation frames. Production uses each
person's stable first ensemble and small continuously eased head/forearm joints. Chair,
pelvis, legs and shoes remain rigid. Backend states change the joint activity and original
status indicator. Cup/overhead-stretch illustrations are retired from automatic playback.

Source/licence: original generated outputs, subject to the provider's output terms;
no third-party sprite pack, game artwork, music, logo or font was copied or downloaded.
The clean plate uses the existing approved project illustration as the sole edit target.
No exclusivity or legal guarantee is asserted. No RunPod/GPU production job was initiated.
