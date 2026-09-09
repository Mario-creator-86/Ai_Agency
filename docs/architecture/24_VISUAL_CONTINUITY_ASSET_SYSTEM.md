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

## Degraded modes

If provider cannot preserve identity:
- use still/2D compositing;
- use a different provider;
- use standardized 2D character assets instead of fully generative characters;
- flag continuity risk.

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
