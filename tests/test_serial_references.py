"""A serial scene is drawn from its character's reference picture, end to end.

2026-10-02 (NO_REBUY_RECOVERY_REFERENCES, A5): the stills step recorded every still's identity
as its words alone and sent only Figure 1, while the assembly looked for the still by its words
AND the character's reference picture. So the first reference set the Owner produced would
have made every serial film fail at assembly (TakesMissing), every day. Now one identity is
used everywhere (the stills step, the shooting sheet, the motion plan, the assembly): the
words, the frame and the reference the scene is drawn from. The reference goes to the vendor
first (Figure 1), the film's look second (Figure 2). A character whose look is locked and has
no reference refuses the step (NEEDS_REFERENCE) with a letter in Romanian, before anything is
asked or bought.

Every provider is faked; no socket is opened (conftest refuses them).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.media import stills_stage
from app.media.models import CharacterBible, MediaAsset, SceneTake, StoryboardScene
from app.media.stills_stage import StillsStageRefused, stills_plan
from app.media.toolchain import find_ffmpeg
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_stills_stage import (
    NO_FACE,
    SUBJECTS,
    SpyJudge,
    SpyStills,
    a_film,
    approved_run,
    takes,
)

requires_ffmpeg = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")

PORTRAIT = b"\x89PNG\r\n\x1a\n" + b"Mara's reference portrait"


class ReferenceStills(SpyStills):
    """The image vendor, faked, that takes reference pictures (as Runway's text_to_image)."""

    ACCEPTS_REFERENCE_IMAGE = True


def a_character(engine, tmp_path: Path, *, referenced: bool, locked: bool) -> str:
    """One character of the serial's cast; with a stored reference portrait when asked."""
    character_id = str(uuid4())
    slots: dict[str, Any] = {"portrait": None}
    with Session(engine) as session, session.begin():
        if referenced:
            asset_id = str(uuid4())
            path = tmp_path / f"{asset_id}.png"
            path.write_bytes(PORTRAIT)
            session.add(
                MediaAsset(
                    id=asset_id,
                    asset_type="IMAGE",
                    uri_or_path=str(path),
                    file_size_bytes=len(PORTRAIT),
                    mime_type="image/png",
                    width=64,
                    height=96,
                    provider_name="TEST_IMAGE_PROVIDER",
                    license_status="ORIGINAL_AI_GENERATED",
                    provenance_hash="0" * 64,
                    created_at=utc_now(),
                )
            )
            slots["portrait"] = asset_id
        session.add(
            CharacterBible(
                id=character_id,
                canonical_name=f"Mara {character_id[:4]}",
                palette_json={"jacket": "#334155"},
                face_hair_desc="Short dark hair, round glasses",
                outfit_desc="A grey wool jacket",
                props_desc="A notebook",
                role_symbols="a notebook",
                reference_assets_json=slots,
                identity_locks_json={"visual": True} if locked else {},
                forbidden_deviations="Never without her glasses.",
                created_at=utc_now(),
            )
        )
    return character_id


def cast(engine, storyboard_id: str, character_id: str, scenes: tuple[int, ...]) -> None:
    with Session(engine) as session, session.begin():
        for row in session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
        ):
            if row.scene_index in scenes:
                row.character_ids_json = [character_id]


def test_a_referenced_scene_sends_the_character_first_and_the_look_second(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path)
    character_id = a_character(engine, tmp_path, referenced=True, locked=True)
    cast(engine, storyboard_id, character_id, (1, 3))
    adapter = ReferenceStills()

    approved_run(engine, storyboard_id, tmp_path, adapter, SpyJudge())

    by_subject = {
        scene: next(call for call in adapter.asked if SUBJECTS[scene] in call["prompt"])
        for scene in (1, 2, 3, 4)
    }
    first = [t for t in takes(engine, storyboard_id) if t.scene_number == 1]
    figure = Path(next(t for t in first if t.status == "APPROVED").path).read_bytes()
    # Scene 1: the character alone (it is the film's Figure 1 itself).
    assert by_subject[1]["references"] == [PORTRAIT]
    assert "Figure 1" in by_subject[1]["prompt"] and "Mara" in by_subject[1]["prompt"]
    # Scene 3: the character first, the film's look second, each named for what it is for.
    assert by_subject[3]["references"] == [PORTRAIT, figure]
    assert stills_stage.FIGURE_TWO in by_subject[3]["prompt"]
    assert stills_stage.FIGURE_ONE not in by_subject[3]["prompt"]
    # Scenes without the character: the film's look alone, as before.
    assert by_subject[2]["references"] == [figure]
    assert stills_stage.FIGURE_ONE in by_subject[2]["prompt"]


@requires_ffmpeg
def test_a_serial_board_with_a_referenced_character_goes_from_stills_to_assembly(
    engine, tmp_path, monkeypatch
):
    from app.media import assembler
    from app.media.factory import reference_payload
    from app.media.shooting_sheet import build_sheet
    from test_film_costing import SEEDANCE

    storyboard_id = a_film(engine, tmp_path)
    character_id = a_character(engine, tmp_path, referenced=True, locked=True)
    cast(engine, storyboard_id, character_id, (1, 3))
    approved_run(engine, storyboard_id, tmp_path, ReferenceStills(), SpyJudge())

    # The sheet finds every approved still, the referenced ones included.
    sheet = build_sheet(
        engine, storyboard_id, capabilities=[SEEDANCE], resolution="1080p", read_live=False
    )
    live = [s for s in sheet["scenes"] if s["kind"] == "LIVE"]
    assert all(s["still"] is not None for s in live), [s["scene_index"] for s in live]
    assert sheet["steps"]["stills"]["to_buy"] == []
    # The motion plan starts every shot from its approved still: nothing waits for a still.
    plan = assembler.motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])
    assert {s["status"] for s in plan["scenes"] if s["kind"] == "LIVE"} == {"PLANNED"}

    # The assembly finds them too: no TakesMissing, nothing bought.
    made: list[str] = []

    def assembled(engine_, board, correlation, **render):
        made.append(board)
        return {"job_id": str(uuid4()), "production": {}, "output_asset_id": "asset-1"}

    monkeypatch.setattr(assembler, "assemble_video_job", assembled)
    film = assembler.assemble_from_takes(
        engine,
        storyboard_id,
        str(uuid4()),
        environment="TEST",
        reference_for_scene=lambda scene: reference_payload(engine, scene.get("character_ids")),
    )
    assert made == [storyboard_id]
    assert film["output_asset_id"] == "asset-1"


def test_a_locked_character_with_no_reference_refuses_the_step_before_anything_is_bought(
    engine, tmp_path
):
    storyboard_id = a_film(engine, tmp_path)
    character_id = a_character(engine, tmp_path, referenced=False, locked=True)
    cast(engine, storyboard_id, character_id, (2,))

    plan = stills_plan(engine, storyboard_id)
    assert plan["to_buy"] == []
    (waiting,) = plan["needs_reference"]
    assert waiting["scene_index"] == 2 and "înfățișarea blocată" in waiting["reason_ro"]

    adapter = ReferenceStills()
    with pytest.raises(StillsStageRefused) as refused:
        stills_stage.run_stills_stage(
            engine,
            storyboard_id,
            str(uuid4()),
            plan_hash=plan["plan_hash"],
            image_adapter=adapter,
            registry=None,
            judge=SpyJudge(),
            storage_root=tmp_path / "media",
        )
    assert refused.value.status == "NEEDS_REFERENCE"
    assert "referință" in refused.value.reason_ro
    assert adapter.asked == []
    with Session(engine) as session:
        assert session.scalars(select(SceneTake)).all() == []


@requires_ffmpeg
def test_the_day_waits_for_the_reference_set_with_a_letter_in_romanian(
    engine, settings, tmp_path, monkeypatch
):
    from app.runbook import stages
    from test_daily_run_stages import (
        _bottom_of_the_staircase,
        _owner_letters,
        _production,
        _staircase_world,
    )

    _production(engine)
    storyboard_id = _bottom_of_the_staircase(engine, tmp_path, scenes=2)
    character_id = a_character(engine, tmp_path, referenced=False, locked=True)
    cast(engine, storyboard_id, character_id, (1,))
    world = _staircase_world(engine, tmp_path, monkeypatch, stills=NO_FACE)

    outcome = stages._media(engine, settings, None, None)

    assert world["images"].asked == [] and world["models"].posts() == 0
    (film,) = outcome["artefacts"]["films"]
    assert film["status"] == "WAITING" and film["refusal"] == "NEEDS_REFERENCE"
    (letter,) = _owner_letters(engine, "owner_shooting_sheet")
    assert letter.body_json["status"] == "NEEDS_REFERENCE"
    assert "înfățișarea blocată" in letter.body_text
    assert "referință" in letter.body_text
