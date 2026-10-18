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
