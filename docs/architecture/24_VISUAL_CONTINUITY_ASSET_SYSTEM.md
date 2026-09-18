# Visual Continuity and Asset System

## Goals

1. Keep the 2D office coherent.
2. Keep recurring serial characters recognizable.
3. Allow dynamic hiring/firing.
4. Avoid claiming visual consistency that a provider cannot deliver.

## Character Bible

Per employee:
- canonical ID;
- portrait;
- full-body reference;
- front/side/back references if useful;
- palette;
- face/hair descriptors;
- outfit;
- props;
- role symbols;
- voice profile;
- personality notes;
- forbidden deviations;
- employment dates.

A reference slot holds a stored asset id or nothing (stated 2026-09-18, and enforced since).
`CharacterBible.reference_assets_json` carries the five slots above — portrait, full body, front,
side, back — and a slot never holds a description, a prompt or a status string standing in for an
image that was not produced: a value that is not a stored asset id is read as an empty slot. The
descriptive fields (face and hair descriptors, outfit, props, role symbols, palette, forbidden
deviations) are separate from the slots and are what a character with no reference picture is
compared against; a character with neither a description nor a reference is recorded as
not-applicable for that scene, with the reason, and is never sent to a model, because there is
nothing to compare the frame with.

Until 2026-09-18 every one of these five slots was null in every studio that had ever run, so each
generated picture of a character was a fresh invention.

## Producing a reference set (built 2026-09-18)

Reference sets are produced by an Owner-triggered route, not by any stage of the day:
`POST /media/characters/{id}/reference-set`, on the Owner-only media router. It composes one prompt
per slot from the bible alone, stores each produced still as a `MediaAsset` — bytes on disk, size
and dimensions measured from what the adapter returned, SHA-256 provenance, license status
ORIGINAL_AI_GENERATED, the adapter's provider name — and only then writes that asset id into the
slot. A slot the vendor refused keeps whatever it held and is named in the answer with its reason,
so nobody is told a picture exists that was not produced.

It is the Owner's act because it spends image credits, and the studio may not decide to spend a
budget on pictures nobody asked for:
- it refuses under STOP AUTONOMY before the first request;
- it refuses when no verified image provider is selected, rather than drawing placeholder cards and
  calling them references;
- it asks the budget once, for the whole set, before the first slot, and settles that hold when at
  least one picture was produced or releases it when none was;
- it records an estimated cost per produced slot and reports no figure at all — never zero — when
  the model has no recorded price;
- no stage of the daily run names it, and a test asserts that against the runbook's stages, the
  runbook service and the workflow service.

From the slots to a film: the render is handed the reference the scene's cast has, and it is passed
only to an adapter that declares it can take one. A character whose look is locked
(`identity_locks_json['visual']`) and who has no reference asset, or one whose file cannot be read,
**refuses the film** rather than being drawn from the words — inventing a face for a character whose
face is fixed is the thing the lock exists to prevent. The first character the writer named decides
the reference, so a still is never drawn from two faces at once.

## Provider capability

Character consistency techniques depend on provider.

Possible supported features:
- reference image;
- seed;
- image-to-video;
- character reference;
- LoRA/fine-tune;
- style reference.

The system must query/configure actual capability.

In code since 2026-09-18 for the reference image: an adapter declares whether it can take one and
silence is read as no, so a reference is dropped for an adapter that cannot use it and the render
records that no reference was sent — a render never reports a continuity it did not have. A
declaration is about the code, not about the account: an adapter that implements a vendor's
documented reference endpoint says so, and a separate flag stays false until an Owner-approved run
has actually drawn a scene that way, because no test may buy a generation.

## Degraded modes

If provider cannot preserve identity:
- use still/2D compositing;
- use a different provider;
- use standardized 2D character assets instead of fully generative characters;
- flag continuity risk.

"Use a different provider" is bounded and is the Owner's, since 2026-09-18. A level of the
production hierarchy may hold his approved alternatives for a purpose; where a scene has a visually
locked character the list is narrowed to the technology an approved identity change named for that
character, because approval is the evidence that the technology keeps the character recognisable and
the studio cannot produce that evidence about itself. At most one alternative is tried per purpose
per scene: a render that kept trying vendors would spend a film's budget on one shot, and the second
refusal is usually the same refusal. When every approved vendor refuses, the scene falls to the
placeholder still that quality control blocks from publication — which is the "flag continuity risk"
line above, made into a gate.

## 2D office assets

Prefer deterministic sprite/animation assets for the live office.

The live office should not regenerate a character from scratch every frame/session.

Use persistent sprites/model sheets.

## Serial video assets

Can use higher-quality generated scenes, but must reference Character Bible.

## QC checks

- face/hair/outfit mismatch;
- wrong employee present;
- duplicate character;
- missing new hire;
- fired employee present incorrectly;
- office room mismatch;
- wrong props/role.

Built since 2026-09-18, and partial in a way the report states rather than hides. The first two and
the last are measured on the finished film: every scene's middle frame is cut and asked, in one call
for the whole film, whether each character the storyboard put in that scene matches the bible's
canonical face, hair, outfit, props, role symbols and palette — and the stored portrait itself,
where a slot holds one. A person in the wrong outfit is named with their scene and the film fails.
The gate certifies only what it measured: with no vision-capable model on any employee, no frame
cut, or a model that never returned its answer, it reports not-applicable with the reason and
nothing passes by silence. Duplicate character, missing new hire, a fired employee present and
office-room mismatch are **not** measured: they need the day's workforce and layout state in the
question, which the gate does not carry. See `50_CONTENT_GATE_MATRIX.md` for what each status
certifies.

## Office world continuity

Persist layout version.

Serial Story Engine gets the layout valid for the historical date.

If a fountain was bought after Episode 10, it cannot appear in Episode 9 unless intentionally shown as a future fantasy.

## Asset versioning

Character/room/object references need versions.

A new outfit or redesign creates a new CharacterBible/AssetVersion with effective date.

Historical episodes retain the correct version.

## Identity validation

Before serial render:
- expected cast IDs;
- expected character reference versions;
- expected outfit/props;
- expected office layout.

QC records mismatch severity.

## Generated world assets

Future Director-created objects follow:
request
→ asset generation/catalog choice
→ technical validation
→ rights/provenance
→ placement preview
→ commit.

Never let a raw AI image become a live office object without metadata and validation.

## Style Bible

Maintain studio-wide:
- perspective;
- scale;
- line/shading style;
- palette;
- lighting conventions;
- UI sprite dimensions;
- animation frame conventions.

This prevents the office becoming visually incoherent as new agents/rooms arrive.

## Fallback character representation

Every employee should have a deterministic 2D fallback asset even if high-end serial generation fails.

The live office must remain coherent independent of video provider.

## Voice continuity

Recurring public characters should also have:
- canonical voice profile;
- TTS provider/voice ID;
- pronunciation dictionary;
- fallback voice policy.

If a voice disappears:
- do not silently assign a dramatically different voice;
- mark continuity degradation;
- use approved fallback or create a deliberate story/character-version change.
