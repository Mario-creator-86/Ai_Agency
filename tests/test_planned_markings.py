"""Writing that belongs to the object the plan asks for (2026-10-13).

The Owner, on the film «Why the Kelvin Scale Has No 'Zero' to Begin From»: a scene asked for a
thermometer and quality control refused every still for the digits on it. «Nu ai cum să ai un
termometru fără scris, grade, Celsius.» Offline, with faked models and vendors:

- the plan's objects that carry their own markings are read from its words (`planned_markings`);
- writing on such an object is no hard limit of the bible: the Director overturns it in one
  look, without the fail-closed loop, while the same words on a plan of plain objects still
  fail closed; her rewrite review does not anchor such a finding serious;
- the stills gate leaves such a writing refusal to her look (never a blind re-roll), its words
  tell the Owner why, and a re-roll keeps the object's scale;
- the look that judges the still is told the instrument keeps its scale; the stills step asks
  her before anything more is bought; a clip's writing refusal is hers to overturn too;
- the still prompt says the object keeps its markings instead of «No text».
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from app.media import fix_check
from app.media.markings import (
    markings_kept,
    markings_note,
    markings_ro,
    planned_markings,
    still_exclusions,
)
from app.media.models import StoryboardScene
from app.media.picture_qc import judge_still
from app.media.prompt_agent import compile_prompts
from app.media.prompt_lint import has_block, lint_still_prompt
from app.media.qc import ClipCheck, ClipReport, look_may_overturn
from app.media.scene_rewrite import hard_limit
from app.media.second_look import HARD_LIMIT_MARK, hard_limits
from app.media.still_gate import StillPlan, decide, may_be_overturned, positive_instruction
from app.media.stills_stage import still_negative
from app.media.toolchain import find_ffmpeg
from app.providers.base import GenerateResult, HealthResult
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_director_decides_qc import failed_film
from test_fix_is_verified import HER, Looks, OffPlanFirst, new_pictures_for, verdict
from test_second_look import (
    FIXTURES,
    LookingDirector,
    events,
    give_vision,
    her_registry,
    look,
    seeded_studio,
    shown,
)
from test_stills_stage import LOOK, SUBJECTS, TAIL, SpyStills, a_film, approved_run

requires_ffmpeg = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")

THERMOMETER = (
    "Detail shot, 85mm lens. A mercury thermometer with its Celsius scale on a lab bench, one "
    "cold lamp. Vertical 9:16 frame, main subject in the upper two thirds."
)
WRITING = "Modelul de vedere a văzut text lizibil în imagine («digits along the thermometer»)"
#: Her look at the digits: the scale is the thermometer's, the picture is used.
ITS_SCALE = {
    "verdict": "OVERTURNED",
    "severity": "minor",
    "redo": False,
    "reason_ro": "Văd doar scala termometrului cu gradele ei; nu e text în imagine.",
    "cause": "Planul cere un termometru, iar modelul de vedere a citit scala lui ca text.",
    "layer": "still",
}


# ------------------------------------------------------------------- the objects a plan names


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("A mercury thermometer with its Celsius scale on a lab bench", ("thermometer",)),
        ("un termometru vechi pe masa laboratorului", ("thermometer",)),
        ("a brass pressure gauge beside a wall clock", ("gauge", "clock")),
        ("the Kelvin scale drawn as a tall vertical line", ("temperature scale",)),
        ("A far village of stone houses on a terraced slope", ()),
        ("a blank sign over a shop, a page of a book", ()),
        ("the valley lit at six o'clock in the evening", ()),
        (None, ()),
    ],
)
def test_the_objects_a_plan_names(text, found):
    assert planned_markings(text) == found


def test_the_words_for_the_models_and_the_owner():
    assert still_exclusions(()) == "No text, no logo."
    assert still_exclusions(("thermometer",)) == (
        "The thermometer keeps its own scale and markings; no caption, no logo."
    )
    assert still_exclusions(("thermometer", "gauge")).startswith(
        "The thermometer and the gauge keep their own"
    )
    assert markings_kept(("clock",)) == "The clock keeps its own scale and markings."
    assert markings_note(("thermometer",)).startswith("The plan asks for a thermometer:")
    assert "only writing elsewhere" in markings_note(("thermometer",))
    assert "no reason for compose_locally" in markings_note(("thermometer",))
    assert markings_note(()) == "" and markings_kept(()) == ""
    assert markings_ro(("thermometer", "gauge")) == "termometrul și indicatorul cu cadran"


def test_the_still_prompt_lets_the_instrument_keep_its_scale():
    package = {
        "scene_index": 3,
        "scene_kind": "LIVE",
        "subject": "a mercury thermometer on a lab bench",
        "environment": "a dim laboratory",
        "camera": "detail shot, 85mm lens",
        "lighting": "one cold lamp",
        "motion": "the mercury climbs",
        "camera_move": "slow push-in",
    }
    still = compile_prompts(package, {})["still_prompt"]
    assert still.endswith("The thermometer keeps its own scale and markings; no caption, no logo.")
    assert "No text" not in still
    assert not has_block(lint_still_prompt(still, scene=3))
    plain = compile_prompts({**package, "subject": "a cold lamp on a lab bench"}, {})
    assert plain["still_prompt"].endswith("No text, no logo.")


# ------------------------------------------------------------ no hard limit, hers to judge


def test_writing_on_the_planned_object_is_no_hard_limit():
    # Since 2026-10-15 no writing is a hard limit (the Owner: a book in the background, a
    # thermometer's scale, a page someone writes on — the scene's own; only text laid over
    # the picture or a logo is serious, and she says which), with or without markings.
    assert hard_limits([WRITING], faces_forbidden=False) == []
    assert hard_limits([WRITING], faces_forbidden=False, markings=("thermometer",)) == []
    # Faces and panels stay what they are.
    face = "YuNet a găsit 1 față în imagine; biblia vizuală interzice fețele"
    assert hard_limits([face, WRITING], faces_forbidden=True, markings=("thermometer",)) == [
        "faces"
    ]
    assert hard_limits(["o bandă plată între panouri"], faces_forbidden=False, markings=("x",)) == [
        "panels"
    ]
    # Her review of a rewrite does not anchor such a finding serious either.
    assert hard_limit("Modelul de vedere a văzut text lizibil în imagine", {}) is True
    assert (
        hard_limit("Modelul de vedere a văzut text lizibil în imagine", {}, ("thermometer",))
        is False
    )
    assert hard_limit("Imaginea nu e o singură fotografie: panouri", {}, ("thermometer",)) is True


def _plan_asks_for_a_thermometer(engine, film) -> None:
    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == film["board"], StoryboardScene.scene_index == 5
            )
        )
        row.prompt_json = {**dict(row.prompt_json or {}), "still_prompt": THERMOMETER}


def test_she_overturns_the_digits_on_a_thermometer_in_one_look(engine):
    studio = seeded_studio(engine)
    film = failed_film(engine)
    _plan_asks_for_a_thermometer(engine, film)
    give_vision(engine, studio["agents"]["Director"].model_id)
    model = LookingDirector(ITS_SCALE)

    result = look(engine, her_registry(studio, model), film, refusal=[WRITING])

    assert (result["verdict"], result["severity"], result["redo"]) == ("OVERTURNED", "minor", False)
    assert result["cause"] == ITS_SCALE["cause"]
    ((prompt, _images, _model),) = model.looked
    assert "The plan asks for a thermometer" in prompt and HARD_LIMIT_MARK not in prompt
    assert "only such an object's own scale is no defect" in prompt
    data = shown(prompt)
    assert data["planned_markings"] == ["thermometer"] and "hard_limits" not in data
    assert data["scene"]["plan"]["planned_markings"] == ["thermometer"]
    (event,) = events(engine)
    assert event["planned_markings"] == ["thermometer"] and event["hard_limits"] == []
    assert event["verdict"] == "OVERTURNED" and event["fail_closed"] is False


def test_the_same_writing_on_a_plan_of_plain_objects_is_hers_too(engine):
    studio = seeded_studio(engine)
    film = failed_film(engine)
    give_vision(engine, studio["agents"]["Director"].model_id)
    model = LookingDirector(ITS_SCALE)

    result = look(engine, her_registry(studio, model), film, refusal=[WRITING])

    # Her look stands as she gave it: writing is no hard limit (2026-10-15), so a «minor»
    # is not refused and asked again, and nothing fails closed for the words alone.
    assert len(model.looked) == 1
    assert result["verdict"] == "OVERTURNED" and result["redo"] is False
    (event,) = events(engine)
    assert event["hard_limits"] == [] and "planned_markings" not in event
    assert event["fail_closed"] is False


# --------------------------------------------------------------------------- the stills gate


def test_the_gate_leaves_such_a_writing_refusal_to_her_look():
    plan = StillPlan(
        scene=4,
        still_prompt=THERMOMETER,
        camera_move="slow push-in",
        faces_forbidden=False,
        expected_markings=("thermometer",),
    )
    plain = StillPlan(scene=4, still_prompt="A cold lamp.", camera_move="", faces_forbidden=False)
    picture = FIXTURES / "scene_01.jpg"

    digits = decide(picture, plan, [], verdict(readable_text=True), environment="TEST")
    lettering = decide(picture, plain, [], verdict(readable_text=True), environment="TEST")

    assert digits.decision == "BLOCKED" and "readable_text" in digits.violations
    assert digits.expected_markings == ("thermometer",)
    # Both are hers since 2026-10-15: lettering on a plain plan is no hard limit either.
    assert may_be_overturned(digits) and may_be_overturned(lettering)
    assert "deși planul cere termometrul" in digits.reasons_ro[0]
    assert "Directoarea decide" in digits.reasons_ro[0]
    assert (
        "text lizibil" in lettering.reasons_ro[0] and "termometrul" not in lettering.reasons_ro[0]
    )
    # Panels on the same still stay the code's.
    panels = decide(
        picture, plan, [], verdict(readable_text=True, one_picture=False), environment="TEST"
    )
    assert not may_be_overturned(panels)
    # A re-roll keeps the instrument's scale and asks every other surface plain.
    words = positive_instruction(["readable_text"], ("thermometer",))
    assert "the thermometer's own scale" in words and "plain" in words
    assert positive_instruction(["readable_text"]).startswith("plain surfaces")


class SeeingModel:
    """The looker's model, faked: answers any look with a still that is right, every prompt
    kept."""

    def __init__(self):
        self.calls: list[str] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        self.calls.append(prompt)
        answer: dict[str, Any] = {
            "stills": [
                {
                    "scene": 4,
                    "faces_visible": False,
                    "readable_text": False,
                    "one_picture": True,
                    "matches_plan": True,
                    "shows_scene": True,
                    "look_ok": True,
                    "technical_ok": True,
                    "bible_violations": "none",
                    "verdict": "buy_motion",
                    "reason": "a thermometer on a bench, its scale readable",
                }
            ]
        }
        return GenerateResult(json.dumps(answer), 10, 40, None)


@requires_ffmpeg
def test_the_look_is_told_the_instrument_keeps_its_scale(engine):
    studio = seeded_studio(engine)
    give_vision(engine, studio["agents"]["VideoEditor"].model_id)
    model = SeeingModel()
    registry = her_registry(studio, model)
    plan = StillPlan(
        scene=4,
        still_prompt=THERMOMETER,
        camera_move="",
        faces_forbidden=False,
        expected_markings=("thermometer",),
    )
    plain = StillPlan(scene=4, still_prompt="A cold lamp.", camera_move="", faces_forbidden=False)

    told = judge_still(engine, registry, FIXTURES / "scene_01.jpg", plan, "c-markings")
    not_told = judge_still(engine, registry, FIXTURES / "scene_01.jpg", plain, "c-plain")

    assert told.status == "MEASURED" and not_told.status == "MEASURED"
    first, second = model.calls
    assert (
        "The plan asks for a thermometer" in first
        and '"planned_markings": ["thermometer"]' in first
    )
    assert "The plan asks for" not in second and "planned_markings" not in second


@requires_ffmpeg
def test_the_stills_step_asks_her_about_the_thermometers_digits(engine, tmp_path, monkeypatch):
    """As `test_her_look_never_overturns_the_bibles_hard_limits`, with scene 2's plan asking
    for a thermometer: the lettering the look reads is hers to judge, and her look keeps the
    picture, so nothing more is bought."""
    looks = Looks(HER["OVERTURNED"])
    monkeypatch.setattr(fix_check, "director_second_look", looks)
    storyboard_id = a_film(engine, tmp_path)
    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 2
            )
        )
        words = (
            f"{LOOK} {SUBJECTS[2]} A mercury thermometer with its Celsius scale on a stone. {TAIL}"
        )
        row.visual_prompt = words
        row.prompt_json = {**dict(row.prompt_json or {}), "still_prompt": words}
    adapter = SpyStills(pictures=new_pictures_for(2))

    result = approved_run(engine, storyboard_id, tmp_path, adapter, OffPlanFirst(lettering=True))

    assert len(looks.asked) == 1, "the digits on the thermometer are hers to judge"
    asked = looks.asked[0]
    assert asked["scene_index"] == 2 and asked["kind"] == "still"
    assert any("termometrul" in reason for reason in asked["refusal"])
    assert len([c for c in adapter.asked if SUBJECTS[2] in c["prompt"]]) == 1, "no re-roll"
    by_scene = {entry["scene_index"]: entry for entry in result["scenes"]}
    assert by_scene[2]["status"] == "APPROVED" and by_scene[2]["approved_by"] == "director_look"


# ------------------------------------------------------------------------------- the clip


def _clip_refused_for_writing(**picture: Any) -> ClipReport:
    return ClipReport(
        scene=1,
        path="clip.mp4",
        checks=(
            ClipCheck("motion", "PASSED", False, 0.5, "mișcare"),
            ClipCheck("picture", "FAILED", True, None, "apare text sau un logo"),
        ),
        passed=False,
        blocks_ro=("apare text sau un logo",),
        warnings_ro=(),
        unmeasured=(),
        measured={"picture": {"verdict": {"readable_text": True, "one_picture": True}, **picture}},
    )


def test_a_clips_writing_is_hers_to_overturn_with_or_without_planned_markings():
    assert look_may_overturn(_clip_refused_for_writing())
    assert look_may_overturn(_clip_refused_for_writing(planned_markings=["thermometer"]))


# ------------------------------------------------------------------- the negative channel


def test_the_negative_channel_keeps_the_instruments_markings():
    """The Codex review of c6dc05c: a negative prompt told «text, lettering» beside «the
    thermometer keeps its scale» draws a blank instrument. Captions, a logo and a watermark
    stay out of every still."""
    plain = still_negative({}, {})
    marked = still_negative({}, {}, ("thermometer",))
    assert "text" in plain.split(", ") and "lettering" in plain.split(", ")
    assert "text" not in marked.split(", ") and "lettering" not in marked.split(", ")
    for kept in ("captions", "subtitles", "logo", "watermark", "panels"):
        assert kept in marked.split(", ")
