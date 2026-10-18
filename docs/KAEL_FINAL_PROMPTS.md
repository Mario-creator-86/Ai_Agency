# Kael-owned final prompts (editor_final_v1)

## Production direction

For **new factual and serial shots** Kael must return complete `still_prompt`
and `motion_prompt` in addition to his per-shot planning metadata. These are
the **actual words** delivered to the image/video vendors. Python is a minimal
technical validator/transporter; it must **not** construct, shorten, inject,
change style, translate, or otherwise edit Kael's creative prompt sentences.

Sarah audits the same direct prompt text before a vendor purchase, records an
approval hash for the exact bytes, and can ask Kael to correct only the faulty
layer. A still is the single first frame; a clip animates that already approved
still. For a motion rewrite, the still prompt is immutable.

The technical adapter checks required fields, permitted camera move enum,
UTF-16 cap and mechanical lint findings. Kael sees actionable failures and
rewrites the exact final text (maximum two retries per scene, eight per film
during initial preflight); repeated refusals do not become paid retries.
Image/video synthesis still requires Sarah's pre-purchase approval, the
existing budgets and spending controls, valid takes and owner controls.

For `editor_final_v1`:
- `compile_prompts` returns final text without creative composition.
- `prompt_audit.prompt_text` and `motion_prompt_for` use the exact final text.
- `scene_rewrite` accepts direct still and motion edits. A motion-only rewrite
  keeps the stored still unchanged; Sarah sees the difference.
- No `motion_intent` reconstruction or current-day serial recomposition.
- An incomplete Kael answer leaves a new scene unplanned; it cannot silently
  revert to the old Python composer during an active writer run.

## Compatibility for material already purchased

Existing packages lack `prompt_format=editor_final_v1`. Their historical
compiler/intent/serial path remains available for playback, recovery, existing
tests and scene QC. **Do not mass rewrite stored prompts**: scene take hashes
and Sarah approvals bind to the old words, and changing them can orphan paid
media. Migrate old films scene-by-scene only after local audit, backed-up
explicit approval and review of existing takes.

`scripts/repair_dark_energy_6_22.py` and
`scripts/repair_dark_energy_prompts.py` are guarded, owner-invoked migrations
for one historical film; the new architecture does not execute them.

## Pre-deployment validation

Keep production stopped and run the focused pytest modules (including
`tests/test_final_prompt_transport.py`). Audit all modified downstream
purchase and rewrite paths with broader regression tests before enabling a
new film. GitHub Actions failures do not substitute for tests actually run on
the Windows PC. No RunPod/video/image purchase is needed to validate the text
path.

This is the migration **in a draft feature branch**, not a claim that the local
running system or every historical prompt has already changed.
