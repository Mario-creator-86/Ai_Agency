"""A still's exclusions go to the image model's negative channel (2026-10-12).

The stills gate refused the serial's two-shots twelve times each as stacked panels (scenes 3
and 6 of «The Zero Script Club») and a single as lettering on a ledger (scene 4), while the
positive prompt said «One continuous picture fills the whole tall frame» and the bible's
«No written words». RunPod's worker has a negative channel (`BatchRequest.negative_prompt`
reaches the graph; tests/test_runpod_worker_studio_contract.py) and the stills step sent
nothing in it. Now every still carries `stills_stage.STILL_NEGATIVE` (panels, collage, split
screen, text, lettering, logo, watermark …), the faces when the bible forbids them, and the
plan's own `avoid` items — where a negation belongs (ADR-POSITIVE-PROMPTS-ONLY), never in the
positive prompt. Not part of the still's identity. Every provider faked, 0 credits.
"""

from __future__ import annotations

from app.media.stills_stage import NEGATIVE_CHARS, STILL_NEGATIVE, _read_scenes, still_negative
from test_runpod_unsent_proof import approved_stills, studio  # noqa: F401 - the fixture

FACELESS = {"continuity_rules": ["No human faces are ever shown."], "avoid": []}


def test_the_negative_names_the_gates_refusals_the_bibles_faces_and_the_plans_avoid():
    plain = still_negative({}, {})
    for term in ("panels", "split screen", "collage", "lettering", "text", "logo", "watermark"):
        assert term in plain.split(", "), term
    assert "faces" not in plain

    faceless = still_negative({"avoid": ["Neon signs", "neon signs.", "a crowd"]}, FACELESS)
    assert "visible faces" in faceless and "portrait" in faceless
    assert faceless.endswith("neon signs, a crowd"), faceless
    assert faceless.count("neon signs") == 1

    # A list, not a second prompt: cut at a term, never mid-word.
    long = still_negative({"avoid": [f"thing number {n} in the frame" for n in range(40)]}, {})
    assert len(long) <= NEGATIVE_CHARS and not long.endswith(",")
    assert long.startswith(", ".join(STILL_NEGATIVE))


def test_every_live_scene_reads_its_negative_and_the_batch_item_carries_it(
    engine,
    tmp_path,
    studio,  # noqa: F811 - the fixture
):
    from test_stills_stage import a_film

    _identifier, live, made = studio
    storyboard_id = a_film(engine, tmp_path)
    _bible, scenes = _read_scenes(engine, storyboard_id)
    for scene in scenes:
        if scene.kind == "LIVE":
            assert "panels" in scene.negative and "lettering" in scene.negative

    approved_stills(engine, made, storyboard_id, tmp_path)

    items = live.runs()[0]["input"]["items"]
    assert items, "no still was sent"
    for item in items:
        assert "panels" in str(item.get("negative_prompt") or ""), item
        assert "lettering" in str(item.get("negative_prompt") or "")
