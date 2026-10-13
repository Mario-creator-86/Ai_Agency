# Original town vehicles v6

Generated locally for AMN-AI on 2026-10-09 using the built-in OpenAI image generation tool. Exact generation and extraction prompts are in `prompts.json`. No game screenshot or third-party vehicle sprite was copied. Use is governed by the applicable OpenAI output terms and the project's terms; no third-party asset license is asserted.

Original generation ID: `exec-73f023be-83c0-4226-b059-4e440160ff02.png`. Transparent extraction ID: `exec-15d5e5f3-2883-4e1f-93ee-c4761cb24dd9.png`. Both originals remain in `C:/Users/mario/.codex/generated_images/00000000-0000-4000-8000-000000000002/`.

`cars-v6-opaque-draft.png` is the first rejected backdrop-bearing draft. `cars-v6-transparent-original.png` is the accepted generator output, copied byte-for-byte into `frontend/public/assets/pixel/town-cars-v6.png`. The second call removed the backdrop through the image-generation tool; registration scripts only inspect alpha bounds and copy originals.

Four independent side-view silhouettes face right: teal compact hatchback, burgundy station wagon, cream vintage sedan and blue family car. Each contains tinted windows, occupants, headlights, rear lights, door seams, trim and full tyres. The manifest keeps the original frame proportions. Canvas rotates only the clipped wheel hubs; the tyres and body remain fixed. Whole vehicles are mirrored for left-bound traffic. Models change only outside the viewport between passes.

The opaque draft is source-only and must never be loaded in production. No raster was manually retouched or resampled.
