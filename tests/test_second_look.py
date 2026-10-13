"""The Director's second look at a picture quality control refused (2026-10-12).

The Owner, after 11.05 USD of redos in one day and three films that still failed: «trece
imaginile picate de la QC pe la Directoare și să decidă dacă au picat corect sau nu și dacă
trebuie refăcute» — a look costs nothing (the model is a subscription), a redo costs credits.
With a scripted Director whose model sees (no vendor, no credit):

- she confirms a serious defect: CONFIRMED, redo, her reason and its cause; one
  ``media.director_second_look`` event and her own memory of it; she was shown the picture,
  quality control's words and the scene's intent;
- she overturns a minor defect: OVERTURNED, nothing to redo; a «CONFIRMED minor» is refused (the
  Owner accepts small defects) and asked again; her lesson goes to the prompt writers' lessons,
  provisional, for the film's own kind;
- on a hard limit of the bible (a face on a faceless bible) «minor» is refused with the rule
  quoted, and a second «minor» is CONFIRMED: fail closed; «not there» (none) overturns it;
- an inconsistent answer (an overturned serious defect) is refused and asked again with why, and
  two inconsistent answers are UNAVAILABLE, the refusal standing;
- with no seeing model, no registry, an unknown kind or a failing model she cannot look: the
  answer is UNAVAILABLE, never an exception, and nothing reaches a model it should not;
- the scene's intent is the scriptwriter's line (not the compiled prompt again) and, for the
  serial, the beat; an old take is judged against the plan it was bought on; her earlier looks
  name the takes they were about, and an audit's own looks are left out;
- a clip is shown as its first, middle and last frame; a film scene as quality control judged
  it — the film's frames at QC's own frame numbers (a caption's rows cut out where one is on
  screen, its words named), else the bought clip cut at the span's own times, never at its own
  last frame (where ffmpeg is).
"""

from __future__ import annotations

import base64
import hashlib
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
from app.media.models import (
    MediaAsset,
    SceneTake,
    Storyboard,
    StoryboardScene,
    VideoRenderJob,
)
from app.media.second_look import (
    HARD_LIMIT_MARK,
    SECOND_LOOK_EVENT,
    SECOND_LOOK_TASK,
    SecondLook,
    film_scene_frames,
    film_scene_view,
    frames_of,
    hard_limits,
    look_schema,
    scene_intent,
    second_look,
)
from app.media.services import seed_default_character_bibles
from app.media.toolchain import find_ffmpeg
from app.models import DomainEvent, OwnerPolicy
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from app.services import append_event
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_director_decides_qc import PANELS, failed_film

FIXTURES = Path(__file__).parent / "fixtures" / "factual_sample"
#: A still, already prepared as the seeing model is sent it (base64), so no encoder is needed.
PICTURE = base64.b64encode((FIXTURES / "scene_01.jpg").read_bytes()).decode("ascii")
FACE = "YuNet a găsit 1 față în imagine; biblia vizuală interzice fețele"
SERIOUS = {
    "verdict": "CONFIRMED",
    "severity": "serious",
    "redo": True,
    "reason_ro": "Văd trei panouri suprapuse, nu o singură imagine. Refuzul este corect.",
    "cause": "Promptul cere trei momente într-un singur cadru, iar modelul le-a stivuit.",
    "layer": "still",
}
MINOR = {
    "verdict": "OVERTURNED",
    "severity": "minor",
    "redo": False,
    "reason_ro": "Văd un singur peisaj întunecat; fața numărată este o umbră pe stâncă. "
    "Defectul e mic și imaginea se folosește.",
    "cause": "Lumina laterală desenează pe stâncă o umbră cu formă de chip.",
    "layer": "still",
}
NOT_THERE = {
    "verdict": "OVERTURNED",
    "severity": "none",
    "redo": False,
    "reason_ro": "Nu văd nicio față: e o stâncă în umbră. Refuzul este greșit.",
}
CONTRADICTORY = {
    "verdict": "OVERTURNED",
    "severity": "serious",
    "redo": False,
    "reason_ro": "Panouri, dar merge.",
    "cause": "Promptul.",
}
LESSON = "Light a rock face from the front so no shadow on it reads as a face."

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


def faceless(engine, film) -> None:
    with Session(engine) as session, session.begin():
        session.get(Storyboard, film["board"]).visual_bible_json = {"avoid": ["No visible faces."]}


# --------------------------------------------------------------------------- her verdicts


def test_she_confirms_a_serious_defect_and_the_redo_goes_ahead(engine, studio):
    film = failed_film(engine)
    give_vision(engine, studio["agents"]["Director"].model_id)
    model = LookingDirector(SERIOUS)

    result = look(engine, her_registry(studio, model), film)

    assert set(result) == {
        "verdict",
        "severity",
        "redo",
        "reason_ro",
        "run_id",
        "cause",
        "lesson",
        "layer",
        "source",
    }
    assert (result["verdict"], result["severity"], result["redo"]) == ("CONFIRMED", "serious", True)
    assert result["reason_ro"] == SERIOUS["reason_ro"] and result["run_id"]
    assert (result["cause"], result["layer"], result["source"]) == (
        SERIOUS["cause"],
        "still",
        "STILL",
    )
    # What she was shown: the picture, quality control's own words, the scene's intent.
    ((prompt, images, _model),) = model.looked
    assert images == [PICTURE] and model.other == []
    data = shown(prompt)
    assert data["refusal"] == [PANELS, FACE] and data["kind"] == "still"
    assert data["scene"]["narration"] == "Narration of scene 5."
    assert data["scene"]["bible"]["rules"] == [] and data["scene"]["plan"]["still_prompt"]
    assert "the Owner accepts small defects" in prompt
    assert "is the picture's own writing" in prompt
    # The panels are a hard limit of the bible (the default bible allows faces).
    assert data["hard_limits"] == ["panels"] and HARD_LIMIT_MARK in prompt
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
        "cause": SERIOUS["cause"],
        "lesson": "",
        "lesson_stored": False,
        "layer": "still",
        "source": "STILL",
        "hard_limits": ["panels"],
        "fail_closed": False,
        "plan_as_bought": [],
        "plan_may_be_newer": False,
    }
    with Session(engine) as session:
        run = session.get(AgentRun, result["run_id"])
        assert run.task_type == SECOND_LOOK_TASK
        assert run.agent_id == studio["agents"]["Director"].id
        memory = session.scalars(
            select(MemoryRecord).where(MemoryRecord.source_id == result["run_id"])
        ).one()
        assert memory.memory_class == "AGENT_OPINION" and "CONFIRMED" in memory.content
        assert SERIOUS["cause"] in memory.content


def test_she_overturns_a_minor_defect_and_her_lesson_is_kept_for_the_next_prompts(engine, studio):
    from app.media.prompt_agent import _live_lessons

    film = failed_film(engine)
    give_vision(engine, studio["agents"]["Director"].model_id)
    model = LookingDirector({**MINOR, "lesson": LESSON})

    result = look(engine, her_registry(studio, model), film, refusal=[FACE])

    assert (result["verdict"], result["severity"], result["redo"]) == ("OVERTURNED", "minor", False)
    assert "umbră" in result["reason_ro"] and result["cause"] == MINOR["cause"]
    assert result["lesson"] == LESSON
    (event,) = events(engine)
    assert event["verdict"] == "OVERTURNED" and event["redo"] is False
    assert event["refusal"] == [FACE] and event["hard_limits"] == []
    assert event["lesson_stored"] is True
    with Session(engine) as session:
        (kept,) = [lesson for lesson in _live_lessons(session) if lesson.text == LESSON]
    # Provisional (no picture has proven it), for factual films (babcf272 is not the serial).
    assert (kept.scope, kept.provisional, kept.source_id) == ("factual", True, result["run_id"])


def test_a_confirmed_minor_defect_is_refused_the_owner_accepts_small_defects(engine, studio):
    film = failed_film(engine)
    give_vision(engine, studio["agents"]["Director"].model_id)
    model = LookingDirector({**MINOR, "verdict": "CONFIRMED", "redo": True}, MINOR)

    result = look(engine, her_registry(studio, model), film, refusal=[FACE])

    assert (result["verdict"], result["severity"], result["redo"]) == ("OVERTURNED", "minor", False)
    first, second = (prompt for prompt, _images, _model in model.looked)
    assert "un defect mic se acceptă și nu se reface" in second
    assert "spune OVERTURNED cu severity minor" in second


def test_her_earlier_looks_name_their_takes_and_an_audits_own_are_left_out(engine, studio):
    film = failed_film(engine)
    give_vision(engine, studio["agents"]["Director"].model_id)
    model = LookingDirector(MINOR)
    registry = her_registry(studio, model)
    other = str(uuid4())
    look(engine, registry, film, refusal=[FACE])
    look(engine, registry, film, refusal=[FACE], take_ids=[other], correlation_id="audit-1")

    look(engine, registry, film, refusal=[FACE])
    look(
        engine,
        registry,
        film,
        refusal=[FACE],
        correlation_id="audit-1",
        earlier_looks_skip="audit-1",
    )

    first, second, third, fourth = (shown(prompt) for prompt, _images, _model in model.looked)
    assert first["your_earlier_looks"] == []
    (earlier,) = second["your_earlier_looks"]
    assert earlier["verdict"] == "OVERTURNED" and earlier["severity"] == "minor"
    assert earlier["take_ids"] == [film["takes"][5]["still"]] and earlier["same_picture"] is False
    assert [look["same_picture"] for look in third["your_earlier_looks"]] == [True, False]
    assert third["your_earlier_looks"][1]["take_ids"] == [other]
    # The audit's own looks (correlation «audit-1») are not shown to it as earlier looks.
    assert [look["take_ids"] for look in fourth["your_earlier_looks"]] == [
        [film["takes"][5]["still"]],
        [film["takes"][5]["still"]],
    ]
    assert "not this picture's verdict" in model.looked[0][0]


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
        {**SERIOUS, "severity": "minor"},  # a minor defect is accepted, never confirmed
        {**MINOR, "cause": ""},  # a defect with no cause
        {**CONTRADICTORY},  # a serious defect overturned
    ],
)
def test_every_inconsistent_shape_is_refused(answer):
    with pytest.raises(ValidationError):
        SecondLook.model_validate(answer)


def test_a_clip_or_film_scene_defect_names_its_layer():
    shot = look_schema("shot")
    with pytest.raises(ValidationError, match="layer"):
        shot.model_validate({**MINOR, "layer": None})
    assert shot.model_validate({**MINOR, "layer": "movement"}).layer == "motion"
    assert shot.model_validate(NOT_THERE).layer is None
    assert SecondLook.model_validate({**MINOR, "layer": None}).layer is None


def test_what_she_is_shown_stays_whole_json_when_it_is_long():
    from app.media.second_look import SHOWN_CHARS, _fit_shown

    long_look = {
        "take_ids": ["t"],
        "same_picture": False,
        "verdict": "OVERTURNED",
        "severity": "minor",
        "reason_ro": "x" * 6000,
        "refusal": ["y" * 3000],
    }
    said = _fit_shown(
        {
            "kind": "still",
            "refusal": ["r"],
            "scene": {"plan": {"look": "l" * 400}, "bible": {"avoid": ["a"] * 12}},
            "your_earlier_looks": [long_look] * 3,
        }
    )

    data = json.loads(said)
    assert len(said) <= SHOWN_CHARS and data["refusal"] == ["r"]
    assert data["your_earlier_looks"][0] == {
        "take_ids": ["t"],
        "same_picture": False,
        "verdict": "OVERTURNED",
        "severity": "minor",
    }


def test_the_verdict_and_severity_are_read_whatever_their_case():
    parsed = SecondLook.model_validate({**MINOR, "verdict": "overturned", "severity": "MINOR"})
    assert (parsed.verdict, parsed.severity) == ("OVERTURNED", "minor")


# --------------------------------------------------------------------- the bible's hard limits


@pytest.mark.parametrize(
    ("words", "forbidden", "limits"),
    [
        (FACE, True, ["faces"]),
        (FACE, False, []),
        (PANELS, False, ["panels"]),
        ("Imaginea nu e o singură fotografie: o bandă plată pe toată lățimea", False, ["panels"]),
        (
            "privit la 1080 px: apare text sau un logo («no faces, but faint lettering»)",
            True,
            ["writing"],
        ),
        ("garbled on-picture text ('Dut youn't est allivie s cogterd?')", False, ["writing"]),
        ("Imaginea nu arată ce cere planul scenei «two women facing each other»", True, []),
        ("Imaginea nu arată ce cere scena (imaginea ei scrisă și narațiunea)", False, []),
    ],
)
def test_the_hard_limits_quality_control_reads(words, forbidden, limits):
    assert hard_limits([words], faces_forbidden=forbidden) == limits


def test_a_face_on_a_faceless_bible_is_never_minor_and_fails_closed(engine, studio):
    film = failed_film(engine)
    faceless(engine, film)
    give_vision(engine, studio["agents"]["Director"].model_id)
    model = LookingDirector(MINOR)

    result = look(engine, her_registry(studio, model), film, refusal=[FACE])

    assert len(model.looked) == 2
    assert (result["verdict"], result["severity"], result["redo"]) == ("CONFIRMED", "serious", True)
    assert "limită fermă" in result["reason_ro"] and result["run_id"]
    first, second = (prompt for prompt, _images, _model in model.looked)
    assert HARD_LIMIT_MARK in first and "No visible faces." in first
    assert "previous answer was refused" in second and HARD_LIMIT_MARK in second
    (event,) = events(engine)
    assert event["fail_closed"] is True and event["hard_limits"] == ["faces"]
    assert event["verdict"] == "CONFIRMED" and event["lesson_stored"] is False


def test_on_a_hard_limit_she_overturns_only_a_defect_that_is_not_there(engine, studio):
    film = failed_film(engine)
    faceless(engine, film)
    give_vision(engine, studio["agents"]["Director"].model_id)
    model = LookingDirector(NOT_THERE)

    result = look(engine, her_registry(studio, model), film, refusal=[FACE])

    assert (result["verdict"], result["severity"], result["redo"]) == ("OVERTURNED", "none", False)
    assert len(model.looked) == 1 and result["cause"] == "" and result["layer"] is None


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


def _rewrite(engine, film, payload: dict[str, Any]) -> str:
    """A rewrite of scene 5's words, now (events are immutable: the take's time is set around
    them); its timestamp."""
    from app.services import utc_now

    with Session(engine) as session:
        newest = session.scalar(
            select(DomainEvent.timestamp).order_by(DomainEvent.sequence.desc()).limit(1)
        )
    while newest is not None and utc_now() <= str(newest):
        pass  # one tick of the clock, so the order of the moments is the order of the events
    with Session(engine) as session, session.begin():
        append_event(
            session,
            "media.prompts_rewritten",
            "storyboard",
            film["board"],
            1,
            {"scene_index": 5, "reason": "serial_recompose", **payload},
            str(uuid4()),
        )
    with Session(engine) as session:
        return str(
            session.scalar(
                select(DomainEvent.timestamp).order_by(DomainEvent.sequence.desc()).limit(1)
            )
        )


def _bought_at(engine, take_id: str, at: str) -> None:
    with Session(engine) as session, session.begin():
        session.get(SceneTake, take_id).created_at = at


def _current_plan(engine, film, words: str) -> None:
    with Session(engine) as session, session.begin():
        scene = session.scalars(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == film["board"], StoryboardScene.scene_index == 5
            )
        ).one()
        scene.prompt_json = {"still_prompt": words}


def test_an_old_take_is_judged_against_the_plan_it_was_bought_on(engine, studio):
    film = failed_film(engine)
    give_vision(engine, studio["agents"]["Director"].model_id)
    take = film["takes"][5]["still"]
    _current_plan(engine, film, "NEW words, recomposed at 13:45")
    _bought_at(engine, take, _rewrite(engine, film, {"still_prompt": "OLDER words"}))
    _rewrite(
        engine,
        film,
        {"old_still_prompt": "OLD words the take was bought on", "still_prompt": "NEW words"},
    )
    model = LookingDirector(MINOR)
    registry = her_registry(studio, model)

    look(engine, registry, film, refusal=[FACE])
    # A look with no take named is judged against the current plan.
    look(engine, registry, film, refusal=[FACE], take_ids=[])

    bought_on, current = (shown(prompt)["scene"]["plan"] for prompt, *_ in model.looked)
    assert bought_on["still_prompt"] == "OLD words the take was bought on"
    assert bought_on["as_bought"] == ["still"] and "rewritten after it" in bought_on["note"]
    assert current["still_prompt"] == "NEW words, recomposed at 13:45"
    assert "as_bought" not in current
    assert events(engine)[0]["plan_as_bought"] == ["still"]


def test_a_rewrite_that_kept_no_old_words_falls_back_to_the_one_before_the_take(engine, studio):
    film = failed_film(engine)
    give_vision(engine, studio["agents"]["Director"].model_id)
    take = film["takes"][5]["still"]
    _current_plan(engine, film, "NEW words")
    _bought_at(engine, take, _rewrite(engine, film, {"still_prompt": "OLDER words"}))
    _rewrite(engine, film, {"still_prompt": "NEW words"})
    model = LookingDirector(MINOR)

    look(engine, her_registry(studio, model), film, refusal=[FACE])

    ((prompt, _images, _model),) = model.looked
    assert shown(prompt)["scene"]["plan"]["still_prompt"] == "OLDER words"


def test_a_plan_rewritten_without_its_old_words_is_said_to_be_maybe_newer(engine, studio):
    film = failed_film(engine)
    give_vision(engine, studio["agents"]["Director"].model_id)
    _bought_at(engine, film["takes"][5]["still"], "2026-01-01T09:00:00+00:00")
    _rewrite(engine, film, {"still_prompt": "NEW words"})
    model = LookingDirector(MINOR)

    look(engine, her_registry(studio, model), film, refusal=[FACE])

    ((prompt, _images, _model),) = model.looked
    plan = shown(prompt)["scene"]["plan"]
    assert plan["plan_may_be_newer"] is True and "may be newer" in plan["note"]
    assert events(engine)[0]["plan_may_be_newer"] is True


def _video(path: Path, seconds: float, red: tuple[float, float] | None = None) -> Path:
    """A blue 108x192 video at 24 fps, red between ``red`` seconds (a marker)."""
    source = f"color=c=blue:s=108x192:r=24:d={seconds}"
    if red is not None:
        source += (
            f",drawbox=x=0:y=0:w=iw:h=ih:color=red:t=fill:enable='between(t,{red[0]},{red[1]})'"
        )
    subprocess.run(
        [str(find_ffmpeg()), "-v", "error", "-y", "-f", "lavfi", "-i", source]
        + ["-pix_fmt", "yuv420p", str(path)],
        check=True,
        capture_output=True,
    )
    return path


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


def _red(path: str) -> bool:
    import cv2

    picture = cv2.imread(path)
    blue, _green, red = (float(channel.mean()) for channel in cv2.split(picture))
    return red > 150 and blue < 100


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@requires_ffmpeg
def test_a_clip_is_shown_as_its_first_middle_and_last_frame(engine, studio, tmp_path):
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

    assert result["verdict"] == "CONFIRMED" and result["source"] == "CLIP"
    ((prompt, images, _model),) = model.looked
    assert len(images) == 3 and all(len(image) > 1000 for image in images)
    assert "three frames of the clip" in prompt and '"layer": "still" | "motion"' in prompt
    assert film_scene_frames(engine, film["asset"], 4, work_dir=tmp_path / "film") == ([], None)


def the_cut_film(engine, film, tmp_path: Path) -> dict[str, Any]:
    """Scene 1 of the film, on disk: a 4 s clip bought for a 2 s span, a red marker only near
    the span's end (1.75-2.0 s); the film made from it (the clip trimmed to the span) with the
    marker at its frames 42-47, a caption of the studio on screen around 1 s only; QC's span
    look recorded frames 0, 24 and 47."""
    clip = _video(tmp_path / "motion_01.mp4", 4.0, red=(1.75, 1.99))
    movie = _video(tmp_path / "final_short_9_16.mp4", 3.0, red=(1.75, 1.99))
    (tmp_path / "captions.srt").write_text(
        "1\n00:00:00,900 --> 00:00:01,100\nThe studio's own words\n", encoding="utf-8"
    )
    with Session(engine) as session, session.begin():
        asset = session.get(MediaAsset, film["asset"])
        asset.uri_or_path, asset.provenance_hash = str(movie), _sha(movie)
        job = session.scalar(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == film["asset"])
        )
        production = dict(job.production_json)
        production["captions"] = {"burned_in": True, "srt": "captions.srt"}
        production["timeline"] = {
            "fps": 24,
            "spans": [
                {
                    "scene_index": 1,
                    "start": 0.0,
                    "end": 2.0,
                    "dissolve_seconds": 0.0,
                    "shot_seconds": 2.0,
                    "slow_factor": None,
                    "second_framing": None,
                    "kind": "LIVE",
                },
                {"scene_index": 2, "start": 2.0, "end": 3.0, "dissolve_seconds": 0.0},
            ],
        }
        job.production_json = production
        take = session.get(SceneTake, film["takes"][1]["motion"])
        take.path, take.sha256 = str(clip), _sha(clip)
    return {"clip": clip, "movie": movie}


@requires_ffmpeg
def test_a_film_scene_is_shown_as_qc_judged_it_the_films_frames_before_the_raw_clip(
    engine, studio, tmp_path
):
    film = failed_film(engine)
    the_cut_film(engine, film, tmp_path)

    images, view = film_scene_view(
        engine, film["asset"], 1, work_dir=tmp_path / "look", frame_numbers=[0, 24, 47]
    )

    # FILM wins over the clip: the film's frames at QC's numbers, the marker in the last one.
    assert view["source"] == "FILM_CROPPED" and view["film_frames"] == [0, 24, 47]
    first, middle, last, strip = images
    assert _red(last) and not _red(first)
    # The studio's caption is on screen at frame 24 only: its rows are cut out and its words
    # named; frames 0 and 47 are whole, and any writing on them is the picture's own.
    notes = view["frames"]
    assert [note["film_frame"] for note in notes] == [0, 24, 47, 24]
    assert notes[1]["studio_caption"] == "The studio's own words"
    assert "cut out" in notes[1]["shows"] and "bottom strip" in notes[3]["shows"]
    assert notes[0]["studio_caption"] is None and notes[2]["studio_caption"] is None
    assert "picture's own" in notes[2]["note"]
    assert "fake subtitle" in view["writing"]

    # She is told what she is looking at, given only the paths (the view is beside them).
    give_vision(engine, studio["agents"]["Director"].model_id)
    model = LookingDirector({**SERIOUS, "layer": "motion"})
    result = look(
        engine,
        her_registry(studio, model),
        film,
        scene_index=1,
        kind="film_scene",
        images=images,
        refusal=["Cadrele scenei din film: apare text sau un logo"],
        take_ids=[film["takes"][1]["still"], film["takes"][1]["motion"]],
    )
    assert (result["source"], result["layer"]) == ("FILM_CROPPED", "motion")
    ((prompt, pictures, _model),) = model.looked
    assert len(pictures) == 4 and "film frames 0 (0.00 s), 24 (1.00 s), 47 (1.96 s)" in prompt
    assert "fake subtitle" in prompt
    assert shown(prompt)["frames"][1]["studio_caption"] == "The studio's own words"


@requires_ffmpeg
def test_without_the_film_the_clip_is_cut_at_the_spans_own_times(engine, tmp_path):
    film = failed_film(engine)
    the_cut_film(engine, film, tmp_path)
    with Session(engine) as session, session.begin():
        session.get(MediaAsset, film["asset"]).provenance_hash = "f" * 64  # not this file

    images, view = film_scene_view(
        engine, film["asset"], 1, work_dir=tmp_path / "look", frame_numbers=[0, 24, 47]
    )

    assert view["source"] == "CLIP"
    assert [note["clip_seconds"] for note in view["frames"]] == [0.0, 1.0, 1.958]
    # The span ends at 2.0 s: its last frame shows the marker; the clip's own last frame (4 s)
    # does not, and was never shown.
    assert _red(images[2]) and not _red(images[0])
    assert not _red(frames_of(tmp_path / "motion_01.mp4", "shot", work_dir=tmp_path / "raw")[2])
    assert (
        film_scene_frames(
            engine, film["asset"], 1, work_dir=tmp_path / "look", frame_numbers=[0, 24, 47]
        )[1]
        == "CLIP"
    )
