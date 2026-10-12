"""The Director's second look at a picture quality control refused (2026-10-12).

The Owner, after 11.05 USD of redos in one day and three films that still failed: «trece
imaginile picate de la QC pe la Directoare și să decidă dacă au picat corect sau nu și dacă
trebuie refăcute» — a look costs nothing (the model is a subscription), a redo costs credits.
With a scripted Director whose model sees (no vendor, no credit):

- she confirms a serious defect: CONFIRMED, redo, her reason; one ``media.director_second_look``
  event and her own memory of it; she was shown the picture, quality control's words and the
  scene's intent;
- she overturns a minor defect: OVERTURNED, nothing to redo;
- an inconsistent answer (an overturned serious defect) is refused and asked again with why, and
  two inconsistent answers are UNAVAILABLE, the refusal standing;
- with no seeing model, no registry, an unknown kind or a failing model she cannot look: the
  answer is UNAVAILABLE, never an exception, and nothing reaches a model it should not;
- the scene's intent is the scriptwriter's line (not the compiled prompt again) and, for the
  serial, the beat; a clip is shown as its first, middle and last frame (where ffmpeg is).
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.agents.models import (
    Agent,
    AgentRun,
    Capability,
    MemoryRecord,
    ModelCapability,
    ModelRecord,
    Role,
)
from app.agents.services import seed_initial_workforce
from app.media.models import SceneTake, Storyboard, StoryboardScene
from app.media.second_look import (
    SECOND_LOOK_EVENT,
    SECOND_LOOK_TASK,
    SecondLook,
    film_scene_frames,
    frames_of,
    scene_intent,
    second_look,
)
from app.media.services import seed_default_character_bibles
from app.media.toolchain import find_ffmpeg
from app.models import DomainEvent, OwnerPolicy
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_director_decides_qc import PANELS, failed_film

FIXTURES = Path(__file__).parent / "fixtures" / "nepal_1d530880"
#: A still, already prepared as the seeing model is sent it (base64), so no encoder is needed.
PICTURE = base64.b64encode((FIXTURES / "scene_01.jpg").read_bytes()).decode("ascii")
FACE = "YuNet a găsit 1 față în imagine; biblia vizuală interzice fețele"
SERIOUS = {
    "verdict": "CONFIRMED",
    "severity": "serious",
    "redo": True,
    "reason_ro": "Văd trei panouri suprapuse, nu o singură imagine. Refuzul este corect.",
}
MINOR = {
    "verdict": "OVERTURNED",
    "severity": "minor",
    "redo": False,
    "reason_ro": "Văd un singur peisaj întunecat; fața numărată este o umbră pe stâncă. "
    "Defectul e mic și imaginea se folosește.",
}
CONTRADICTORY = {
    "verdict": "OVERTURNED",
    "severity": "serious",
    "redo": False,
    "reason_ro": "Panouri, dar merge.",
}

requires_ffmpeg = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")


@pytest.fixture
def studio(engine):
    return seeded_studio(engine)


def seeded_studio(engine) -> dict[str, Any]:
    """The seeded studio with its employees by role (as tests/test_director_decides_qc.py)."""
    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        agents = {
            role.name: agent
            for agent, role in session.execute(
                select(Agent, Role).join(Role, Agent.role_id == Role.id)
            ).all()
        }
        provider_id = next(iter(agents.values())).provider_id
        session.expunge_all()
    return {"agents": agents, "provider_id": provider_id}


def give_vision(engine, *model_ids: str) -> None:
    """What a provider declares about a model, as the model sync records it."""
    with Session(engine) as session, session.begin():
        capability = session.scalar(select(Capability).where(Capability.name == "vision"))
        if capability is None:
            capability = Capability(id=str(uuid4()), name="vision", description="sees pictures")
            session.add(capability)
            session.flush()
        for model_id in model_ids:
            session.add(
                ModelCapability(
                    model_id=model_id,
                    capability_id=capability.id,
                    confidence="DECLARED_BY_PROVIDER",
                )
            )


class LookingDirector:
    """Every agent's model: her second look answers ``answers`` in turn (the last one again
    when they run out; a callable is asked with the prompt), with what she was shown recorded;
    anything else is not expected."""

    def __init__(self, *answers: Any, fail: bool = False):
        self.answers = list(answers)
        self.fail = fail
        self.looked: list[tuple[str, list[str], str]] = []
        self.other: list[str] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        if "second-look" not in prompt:
            self.other.append(prompt)
            return GenerateResult("{}", 10, 10, None)
        images = list((kwargs.get("extra") or {}).get("images") or [])
        self.looked.append((prompt, images, model))
        if self.fail:
            raise RuntimeError("the model is down")
        said = self.answers[min(len(self.looked), len(self.answers)) - 1]
        said = said(prompt) if callable(said) else said
        return GenerateResult(said if isinstance(said, str) else json.dumps(said), 10, 40, None)


def her_registry(studio, model) -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(studio["provider_id"], model)
    return registry


def shown(prompt: str) -> dict[str, Any]:
    head = '<untrusted_source_evidence hash="second-look">\n'
    start = prompt.index(head) + len(head)
    return json.loads(prompt[start : prompt.index("\n</untrusted_source_evidence>", start)])


def events(engine) -> list[dict[str, Any]]:
    with Session(engine) as session:
        return [
            dict(event.payload)
            for event in session.scalars(
                select(DomainEvent)
                .where(DomainEvent.event_type == SECOND_LOOK_EVENT)
                .order_by(DomainEvent.sequence)
            )
        ]


def look(engine, registry, film, **overrides) -> dict[str, Any]:
    asked = {
        "storyboard_id": film["board"],
        "scene_index": 5,
        "kind": "still",
        "images": [PICTURE],
        "refusal": [PANELS, FACE],
        "correlation_id": "c-second-look",
        "take_ids": [film["takes"][5]["still"]],
        **overrides,
    }
    return second_look(engine, registry, **asked)


# --------------------------------------------------------------------------- her verdicts


def test_she_confirms_a_serious_defect_and_the_redo_goes_ahead(engine, studio):
    film = failed_film(engine)
    give_vision(engine, studio["agents"]["Director"].model_id)
    model = LookingDirector(SERIOUS)

    result = look(engine, her_registry(studio, model), film)

    assert set(result) == {"verdict", "severity", "redo", "reason_ro", "run_id"}
    assert (result["verdict"], result["severity"], result["redo"]) == ("CONFIRMED", "serious", True)
    assert result["reason_ro"] == SERIOUS["reason_ro"] and result["run_id"]
    # What she was shown: the picture, quality control's own words, the scene's intent.
    ((prompt, images, _model),) = model.looked
    assert images == [PICTURE] and model.other == []
    data = shown(prompt)
    assert data["refusal"] == [PANELS, FACE] and data["kind"] == "still"
    assert data["scene"]["narration"] == "Narration of scene 5."
    assert data["scene"]["bible"]["rules"] == [] and data["scene"]["plan"]["still_prompt"]
    assert "the Owner accepts small defects" in prompt
    # One event, her run, her memory.
    (event,) = events(engine)
    assert event == {
        "storyboard_id": film["board"],
        "scene_index": 5,
        "kind": "still",
        "take_ids": [film["takes"][5]["still"]],
        "refusal": [PANELS, FACE],
        "verdict": "CONFIRMED",
        "severity": "serious",
        "redo": True,
        "reason_ro": SERIOUS["reason_ro"],
        "run_id": result["run_id"],
    }
    with Session(engine) as session:
        run = session.get(AgentRun, result["run_id"])
        assert run.task_type == SECOND_LOOK_TASK
        assert run.agent_id == studio["agents"]["Director"].id
        memory = session.scalars(
            select(MemoryRecord).where(MemoryRecord.source_id == result["run_id"])
        ).one()
        assert memory.memory_class == "AGENT_OPINION" and "CONFIRMED" in memory.content


def test_she_overturns_a_minor_defect_and_nothing_is_redone(engine, studio):
    film = failed_film(engine)
    give_vision(engine, studio["agents"]["Director"].model_id)
    model = LookingDirector(MINOR)

    result = look(engine, her_registry(studio, model), film, refusal=[FACE])

    assert (result["verdict"], result["severity"], result["redo"]) == ("OVERTURNED", "minor", False)
    assert "umbră" in result["reason_ro"]
    (event,) = events(engine)
    assert event["verdict"] == "OVERTURNED" and event["redo"] is False
    assert event["refusal"] == [FACE]


def test_her_earlier_looks_at_the_scene_are_in_front_of_her(engine, studio):
    film = failed_film(engine)
    give_vision(engine, studio["agents"]["Director"].model_id)
    model = LookingDirector(MINOR)
    registry = her_registry(studio, model)
    look(engine, registry, film, refusal=[FACE])

    look(engine, registry, film, refusal=[FACE])

    first, second = (shown(prompt) for prompt, _images, _model in model.looked)
    assert first["your_earlier_looks"] == []
    (earlier,) = second["your_earlier_looks"]
    assert earlier["verdict"] == "OVERTURNED" and earlier["severity"] == "minor"


def test_a_contradictory_answer_is_refused_and_asked_again_with_why(engine, studio):
    film = failed_film(engine)
    give_vision(engine, studio["agents"]["Director"].model_id)
    model = LookingDirector(CONTRADICTORY, SERIOUS)

    result = look(engine, her_registry(studio, model), film)

    assert result["verdict"] == "CONFIRMED" and result["redo"] is True
    first, second = (prompt for prompt, _images, _model in model.looked)
    assert "previous answer was refused" not in first
    assert "previous answer was refused" in second and "cannot be OVERTURNED" in second
    (event,) = events(engine)
    assert event["verdict"] == "CONFIRMED"


def test_two_contradictory_answers_leave_the_refusal_standing(engine, studio):
    film = failed_film(engine)
    give_vision(engine, studio["agents"]["Director"].model_id)
    model = LookingDirector(CONTRADICTORY)

    result = look(engine, her_registry(studio, model), film)

    assert len(model.looked) == 2
    assert (result["verdict"], result["redo"]) == ("UNAVAILABLE", True)
    assert "forma cerută" in result["reason_ro"] and result["run_id"]
    (event,) = events(engine)
    assert event["verdict"] == "UNAVAILABLE" and event["run_id"] == result["run_id"]
    with Session(engine) as session:
        # Nothing she concluded: no memory of a look she did not give.
        assert not session.scalars(
            select(MemoryRecord).where(MemoryRecord.source_id == result["run_id"])
        ).all()


@pytest.mark.parametrize(
    "answer",
    [
        {**MINOR, "redo": True},  # overturned, yet redone
        {**SERIOUS, "redo": False},  # confirmed, yet not redone
        {**SERIOUS, "severity": "none"},  # confirmed with no defect
    ],
)
def test_every_inconsistent_shape_is_refused(answer):
    with pytest.raises(ValidationError):
        SecondLook.model_validate(answer)


def test_the_verdict_and_severity_are_read_whatever_their_case():
    parsed = SecondLook.model_validate({**MINOR, "verdict": "overturned", "severity": "MINOR"})
    assert (parsed.verdict, parsed.severity) == ("OVERTURNED", "minor")


# ------------------------------------------------------------------- when she cannot look


def test_with_no_seeing_model_she_cannot_look_and_no_model_is_asked(engine, studio):
    film = failed_film(engine)
    model = LookingDirector(SERIOUS)

    result = look(engine, her_registry(studio, model), film)

    assert (result["verdict"], result["redo"], result["run_id"]) == ("UNAVAILABLE", True, None)
    assert "nu vede" in result["reason_ro"]
    assert model.looked == [] and model.other == []
    (event,) = events(engine)
    assert event["verdict"] == "UNAVAILABLE" and event["severity"] == "none"


def test_no_registry_an_unknown_kind_or_a_failing_model_never_raise(engine, studio):
    film = failed_film(engine)
    give_vision(engine, studio["agents"]["Director"].model_id)
    down = LookingDirector(SERIOUS, fail=True)

    without = look(engine, None, film)
    unknown = look(engine, her_registry(studio, down), film, kind="poster")
    failing = look(engine, her_registry(studio, down), film)
    no_picture = look(engine, her_registry(studio, down), film, images=["missing.png"])

    for result in (without, unknown, failing, no_picture):
        assert result["verdict"] == "UNAVAILABLE" and result["redo"] is True
    assert "furnizor" in without["reason_ro"]
    assert "eroare" in unknown["reason_ro"]
    assert "nu a reușit" in failing["reason_ro"] and failing["run_id"]
    assert "pregătite" in no_picture["reason_ro"]
    assert len(down.looked) == 1  # only the failing call reached the model
    assert [event["verdict"] for event in events(engine)] == ["UNAVAILABLE"] * 4


# ----------------------------------------------------------------------- what she is shown


def test_the_scene_intent_is_the_writers_line_and_for_the_serial_the_beat(engine):
    from app.factual.models import ScriptDraft

    film = failed_film(engine)
    with Session(engine) as session, session.begin():
        board = session.get(Storyboard, film["board"])
        board.series_key = "office_serial"
        board.visual_bible_json = {"rules": ["No written words anywhere"], "avoid": ["logos"]}
        script = session.get(ScriptDraft, board.script_draft_id)
        script.scenes_json = [
            {"visual_description": f"Writer's line {index}"} for index in range(1, 5)
        ] + [
            {
                "visual_description": "Nadia looks up from the ledger.",
                "part": "turn",
                "location_name": "the ledger room",
                "lines": [{"speaker": "Nadia", "text": "Zero."}],
                "background": ["Marcus"],
            }
        ]
        scene = session.scalars(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == film["board"], StoryboardScene.scene_index == 5
            )
        ).one()
        scene.prompt_json = {
            "still_prompt": "COMPILED still prompt",
            "in_frame": [{"name": "Nadia Voss"}, {"name": "Sarah"}],
            "action": "Nadia lifts her pen, then smiles",
            "location": "office_ledger",
            "camera_move": "slow push-in",
        }

    with Session(engine) as session:
        intent = scene_intent(session, film["board"], 5)

    assert intent["serial"] is True
    assert intent["scene_picture"] == "Nadia looks up from the ledger."
    assert intent["plan"]["still_prompt"] == "COMPILED still prompt"
    assert intent["beat"]["in_frame"] == ["Nadia Voss", "Sarah"]
    assert intent["beat"]["action"] == "Nadia lifts her pen, then smiles"
    assert intent["beat"]["location"] == "office_ledger"
    assert intent["beat"]["lines"] == [{"speaker": "Nadia", "text": "Zero."}]
    assert intent["bible"] == {
        "faces_forbidden": False,
        "rules": ["No written words anywhere"],
        "avoid": ["logos"],
    }


def _clip(path: Path, seconds: float = 2.0) -> Path:
    subprocess.run(
        [
            str(find_ffmpeg()),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=s=270x480:r=24:d={seconds}",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


@requires_ffmpeg
def test_a_clip_is_shown_as_its_first_middle_and_last_frame(engine, studio, tmp_path):
    import hashlib

    film = failed_film(engine)
    give_vision(engine, studio["agents"]["Director"].model_id)
    model = LookingDirector(SERIOUS)
    clip = _clip(tmp_path / "motion_05.mp4")
    still = tmp_path / "scene_05.jpg"
    shutil.copyfile(FIXTURES / "scene_05.jpg", still)

    assert len(frames_of(clip, "shot", work_dir=tmp_path / "frames")) == 3
    assert frames_of(still, "still") == [str(still)]
    result = look(
        engine,
        her_registry(studio, model),
        film,
        kind="shot",
        images=[str(clip)],
        work_dir=tmp_path / "frames",
    )

    assert result["verdict"] == "CONFIRMED"
    ((prompt, images, _model),) = model.looked
    assert len(images) == 3 and all(len(image) > 1000 for image in images)
    assert "three frames of the clip" in prompt
    # A film scene's frames: the clip take the render cut it from, its file the one bought.
    with Session(engine) as session, session.begin():
        row = session.get(SceneTake, film["takes"][1]["motion"])
        row.path = str(clip)
        row.sha256 = hashlib.sha256(clip.read_bytes()).hexdigest()
    frames, source = film_scene_frames(engine, film["asset"], 1, work_dir=tmp_path / "film")
    assert source == "CLIP" and len(frames) == 3
    assert film_scene_frames(engine, film["asset"], 4, work_dir=tmp_path / "film") == ([], None)
