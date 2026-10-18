# Face detection QC policy — 2026-10-18

## Change and scope

- New factual visual bibles created by `build_visual_bible` use `face_policy: ALLOW` by default and remove model-invented blanket no-faces text from their rules and avoid list.
- The visual-bible writer is explicitly told not to ban all faces. Adult fictional or historical re-enactment faces are not inherently forbidden.
- `bible_face_rule` accepts `ALLOW`, `HIDE`, and `REQUIRE`: ALLOW and REQUIRE do not block visible faces; HIDE does. Bibles without a policy preserve their previous text-based checks.
- `REQUIRE` currently means faces are permitted by the gate, **not** that QC guarantees a face is present. Character continuity and anatomy remain the vision reviewer's responsibility.

## Important boundaries

- This is **not** a change to a media provider's API restrictions, public-platform disclosure rules, likeness rights, age checks, or publication rights. Existing rights/licensing checks remain.
- This deliberately does not loosen old film bibles, which may intentionally require figures viewed from behind. Review the visual bible on each old film before assigning an explicit `face_policy`; otherwise regeneration may use the old facial restrictions.
- YuNet is not removed. Its false positives (including the lamp-column regression fixture) merit a separate calibration / vision-confirmation change before removing a hard gate. This branch addresses over-restrictive **generated policy**, not detector precision.
- Main remains unchanged until review/merge.

## Verification

Run from the project repository root, with the backend Python environment active:

```powershell
python -m pytest tests/test_face_policy.py tests/test_prompt_lint.py tests/test_prompt_compiler.py -q
```

To incorporate newer commits from the existing local `amn-pr1` into this branch, fetch and inspect before merging.


## AI-only panel validation (follow-up)

The row-band and single-axis SSIM heuristics were causing false image/video refusals
(e.g. dark skies, desk surfaces, horizons). They are no longer allowed to reject
paid media, redirect a clip to a fresh still, or trigger a reroll:

- `still_gate.local_checks(..., measure=("panels",))` returns `NOT_APPLICABLE`.
- `qc._panels_check` returns `NOT_APPLICABLE` for the clip and whole-film paths;
  there are no image-row measurements in the automatic purchase path.
- `qc.still_is_degenerate` still rejects essentially *uniform/blank* images
  (SSIM over the threshold on **both** axes). High similarity on just one
  axis is not considered a visual defect without the AI seeing it.
- AI vision must explicitly assess `one_picture`, `matches_plan`, and
  `shows_scene` (for stills). Clip and film checks retain the scene and
  continuity questions. An absent/invalid vision answer is **not** a pass.
- Vision instructions now distinguish actual pasted panel boundaries from
  ordinary straight horizons, ceilings, skies, shadows and desk fronts.
  Visual prompt template versions were advanced for fresh judgements.
- `flat_band` and `FlatBand` remain available for offline diagnosis and
  historical fixtures; they do not block the paid-media paths.

**Important:** This does not override faces/rights checks, missing files,
codec errors, quality metrics unrelated to bands, or other policy gates.

An existing historical QC refusal is not silently deleted from the database.
Re-run QC on the affected media after installing the patch. The new result
must be based on an actual AI vision review, not an automatic approval.

### Suggested offline validation (from project root)

```powershell
python -m pytest tests/test_panels_vision_only.py tests/test_still_gate.py tests/test_clip_qc.py tests/test_picture_qc.py -q
```
