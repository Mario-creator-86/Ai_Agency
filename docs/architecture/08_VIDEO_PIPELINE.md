# Video Production Pipeline v3

## Main channel pipeline

1. Idea
2. Research
3. Claim extraction
4. Fact verification
5. Script
6. Hook
7. Storyboard
8. Asset plan
9. Image/video generation or licensed sourcing
10. Voice
11. Captions
12. Deterministic edit
13. Technical QC
14. Factual QC
15. Rights/policy QC
16. Publish

## Office serial pipeline

1. Prior-day DailyStudioLog
2. Continuity snapshot
3. Showrunner
4. Event-grounding validation
5. Story script
6. Storyboard
7. Character-consistent asset production
8. Voice
9. Edit
10. Technical/continuity QC
11. Publish to separate channel

## Media provider abstractions

### VIDEO_PROVIDER
Must represent actual provider semantics.
Possible:
- create_generation
- poll_status
- fetch_result
- cancel if supported
- estimate_cost
- capabilities
- health

### IMAGE_PROVIDER
- generate
- reference/edit if supported
- capabilities
- fetch result

### TTS_PROVIDER
- synthesize
- voice availability
- capabilities

Unknown/unsupported methods must not be faked.

## Character continuity

Live 2D office should prefer deterministic assets/sprites.

Serial can use generated video, but must use Character Bible references when supported.

If provider cannot preserve a character adequately:
- use deterministic 2D/cutout animation;
- change provider;
- or fail continuity QC.

## Editing

Prefer FFmpeg for:
- trim;
- stitch;
- crop;
- 9:16;
- audio mix;
- captions;
- normalization;
- transitions;
- final encode.

Use safe subprocess invocation.

## Asset rights

Each asset:
- source/provider;
- rights/license status;
- generated/reference provenance;
- content item association.

Unknown rights can block public use.

## QC categories

Technical:
- file valid;
- aspect ratio;
- duration;
- audio;
- captions;
- encoding.

Factual:
- script claims map to evidence.

Visual:
- no severe character drift;
- no wrong employee;
- no wrong historical office state.

Policy/rights:
- assets usable;
- synthetic/real representation not misleading.

## Cost

Before expensive generation:
- estimate;
- reserve budget;
- generate;
- reconcile actual cost.

Retries have a maximum spend.

## Render graph

Represent production as a render graph, not one opaque "make video" call.

Track:
- scene assets;
- audio segments;
- timing;
- captions;
- music;
- overlays;
- transitions;
- final assembly.

A failed scene can be regenerated without restarting the entire video.

## Audio specification

Define configurable targets:
- sample rate;
- loudness target;
- peak limit;
- background-music ducking;
- silence trimming;
- pronunciation dictionary.

Store pronunciation exceptions for recurring names/terms.

## Caption specification

Validate:
- transcript match;
- timing;
- safe margins;
- readable line length;
- font/license;
- no critical visual obstruction.

## Visual factual consistency

Fact-check not only narration.

A storyboard/visual can create a false implication even if script is accurate.

QC should detect where feasible:
- wrong planet/location/person/object;
- wrong scale/category;
- synthetic visual presented as real;
- historical-era mismatch.

## Deterministic fallback format

If premium video generation is unavailable or inconsistent, the studio must have a publishable fallback:
- 2D motion graphics;
- still-image parallax;
- kinetic typography;
- stock/licensed visuals;
- deterministic character animation.

Autonomy must not depend on one generative video vendor.

## Render provenance

Final render records:
- asset hashes;
- editor/version;
- FFmpeg command parameters;
- subtitle version;
- audio version;
- checksum;
- duration;
- dimensions;
- QC version.

## Generation quality budget

Set maximum regeneration attempts per scene and per video.

If repeated generation fails:
- simplify scene;
- switch provider;
- use deterministic fallback;
- or block.
