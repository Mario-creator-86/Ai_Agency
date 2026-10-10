"""The Director looks at the pictures a gate refused, and decides (2026-10-10, film babcf272).

The Owner, 20:06 local: «Directorul ce face? El ar trebui să hotărască dacă poza este bună sau
nu.» Her REPAIR of scene 5 bought a new still, the stills gate refused every candidate on a
local reading (a night sky read as a flat band between panels) before anything looked at them,
and her decision waited for his look on the sheet. Now (a scripted Director whose model sees,
the vendors faked; the real path where the encoder is installed):

- she is shown each refused candidate with the scene's words, the bible's rules and the gate's
  own reasons, and chooses one: it is the scene's still, approved by her ("director", never in
  his name), and the walk carries on as with a still the gate approved (his LOCAL_MOVE: the film
  rejoined for 0 credits, no video vendor called), nothing bought again;
- she rejects them all: her decision lapses at once and she reads the report again, her reasons
  in front of her;
- a candidate the degenerate check refused (no picture at all) is never offered to her, nor a
  clip he could not choose either;
- his look wins: a candidate he looked at is not hers, a choice of hers his look came before is
  not applied, his later look replaces hers, and her choice is never his approval;
- he gets one STATUS letter per look;
- with no seeing model anywhere she cannot look: the report waits, and is hers again after the
  days; with a blind model of her own she looks through the studio's seeing model, the run hers.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

import pytest
from app.agents.models import Agent, AgentRun, Capability, ModelCapability
from app.media.director_qc import (
    BOUGHT_WAIT_DAYS,
    DECISION_EVENT,
    DIRECTOR_APPROVER,
    INBOX_KIND,
    LOOK_EVENT,
    LOOK_LETTER_KIND,
    WAITING_EVENT,
    decision_state,
    look_entries,
    look_letter,
    owner_approved_take_ids,
    record_look,
)
from app.media.models import SceneTake
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_director_decides_qc import (
    REPAIR_5,
    FakeRedoPath,
    _accepting,
    _context_of,
    _in,
    _pass,
    _production,
    _she_redoes_the_still_of_scene_2,
    _take,
    answer,
    events,
    failed_film,
    letters,
    verdicts_for,
)

#: What the stills gate said about babcf272's scene-5 candidates: a night sky read as panels.
NIGHT_SKY = "Imaginea are o bandă plată de 33 % din înălțime (rândurile 0-159): panouri"
#: The degenerate check's words: no picture at all.
NO_PICTURE = "Imaginea nu e o imagine: horizontal bands, no scene (structure 0.97)"
OTHER = "Modelul de vedere a văzut text lizibil în imagine"
REJECTED_WHY = "Toate variantele arată într-adevăr trei panouri; nu intră în film."

requires_ffmpeg = pytest.mark.skipif(
    __import__("app.media.qc", fromlist=["find_ffmpeg"]).find_ffmpeg() is None,
    reason="ffmpeg not installed",
)


@pytest.fixture
def studio(engine):
    """The seeded studio, as tests/test_director_decides_qc.py has it: its employees by role."""
    from app.agents.models import ModelRecord, Role
    from app.agents.services import seed_initial_workforce
    from app.media.services import seed_default_character_bibles
    from app.models import OwnerPolicy

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


class SeeingDirector:
    """Every agent's model: the Director's reading of the report answers ``decide``, her look
    at the refused pictures ``look`` (with the pictures recorded), anyone else ``{}``."""

    def __init__(self, decide, look):
        self.decide = decide
        self.look = look
        self.asked: list[str] = []
        self.looked: list[tuple[str, list[str], str]] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        if "director-look" in prompt:
            images = list((kwargs.get("extra") or {}).get("images") or [])
            self.looked.append((prompt, images, model))
            said = self.look(prompt) if callable(self.look) else self.look
        elif "director-qc" in prompt:
            self.asked.append(prompt)
            said = self.decide(prompt) if callable(self.decide) else self.decide
        else:
            said = "{}"
        return GenerateResult(said, 10, 40, None)


def _shown(prompt: str) -> dict[str, Any]:
    head = '<untrusted_source_evidence hash="director-look">\n'
    start = prompt.index(head) + len(head)
    return json.loads(prompt[start : prompt.index("\n</untrusted_source_evidence>", start)])


def _choose(reason_words: str):
    """Her look: CHOOSE the candidate whose gate reasons say ``reason_words``."""

    def look(prompt: str) -> str:
        shown = _shown(prompt)["candidates"]
        number = next(c["candidate"] for c in shown if reason_words in " ".join(c["gate_reasons"]))
        reason = "Este o singură imagine: cerul nopții de sus nu este o bandă între panouri."
        return json.dumps({"decision": "CHOOSE", "candidate": number, "reason": reason})

    return look


REJECT_ALL = json.dumps({"decision": "REJECT", "candidate": None, "reason": REJECTED_WHY})


def _registry(studio, model) -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(studio["provider_id"], model)
    return registry


def _give_vision(engine, *model_ids: str) -> None:
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


def _her_eyes(engine, studio) -> None:
    _give_vision(engine, studio["agents"]["Director"].model_id)


class RefusingGate(FakeRedoPath):
    """The still redo, faked: it buys one candidate per entry of ``details``, each with its file
    on disk, and the stills gate refuses every one with those words (LOCAL.STILL_GATE)."""

    def __init__(self, engine, monkeypatch, tmp_path, details: list[str]):
        super().__init__(engine, monkeypatch, still_status="REJECTED")
        self.tmp_path = tmp_path
        self.details = details
        # What she is shown, faked: the candidate's id stands for its picture.
        monkeypatch.setattr(
            "app.media.director_qc.look_pictures",
            lambda row, ffmpeg_path, work_dir: [f"picture-of-{row.id}"],
        )
        monkeypatch.setattr("app.media.qc.still_is_degenerate", lambda ffmpeg, path: None)

    def redo(self, engine, storyboard_id, correlation_id, *, kind, scene_index=None, **kwargs):
        if kind != "still":
            return super().redo(
                engine, storyboard_id, correlation_id, kind=kind, scene_index=scene_index, **kwargs
            )
        self.calls.append((kind, scene_index, bool(kwargs.get("unasked"))))
        with Session(self.engine) as session, session.begin():
            for number, detail in enumerate(self.details, start=1):
                take_id = _take(session, storyboard_id, int(scene_index), "still", None)
                data = f"candidate {number} {take_id}".encode()
                path = self.tmp_path / f"scene_{scene_index:02d}_redo_c{number}_{take_id[:8]}.png"
                path.write_bytes(data)
                row = session.get(SceneTake, take_id)
                row.status = "REJECTED"
                row.path = str(path)
                row.sha256 = hashlib.sha256(data).hexdigest()
                row.failure_code = "LOCAL.STILL_GATE"
                row.failure_detail = detail
                self.new_stills.append(take_id)
        return {
            "still": {"status": "NEEDS_OWNER"},
            "credits": 8,
            "next_ro": f"Scena {scene_index}: poarta a refuzat variantele.",
        }


def _walk(engine, settings, registry, film) -> dict[str, Any]:
    from app.runbook import stages

    return stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )


# ------------------------------------------------------------------------- she chooses


def test_she_chooses_a_refused_candidate_and_the_film_is_rejoined_for_free(
    engine, settings, studio, monkeypatch, tmp_path
):
    from app.media.assembler import owner_approved_among
    from app.workflows.passes import director_qc_review

    film = failed_film(engine)  # scene 5: his LOCAL_MOVE
    model = SeeingDirector(answer(verdicts_for(film), "REPAIR", REPAIR_5), _choose("panouri"))
    registry = _registry(studio, model)
    _her_eyes(engine, studio)
    gate = RefusingGate(engine, monkeypatch, tmp_path, [NIGHT_SKY, NO_PICTURE])
    _production(engine)
    monkeypatch.setattr(director_qc_review, "RETRY_MINUTES", 0)

    first = _walk(engine, settings, registry, film)

    assert first["outcome"] == "BOUGHT_WAITING"
    state = decision_state(engine, film["report"])
    assert state["pending"] and state["look"] and not state["ready"]
    # Her look is owed, not his: the watchdog puts the film before her.
    assert _pass(engine, settings) == {"queued": [film["board"]]}

    done = _walk(engine, settings, registry, film)

    # Her choice is the scene's still; the film is rejoined from its takes for 0 credits:
    # no motion is bought for his LOCAL_MOVE scene and the still is not bought again.
    assert done["outcome"] == "REPAIRED" and done["passed_asset"], done
    assert gate.calls == [("still", 5, True), ("rejoin", None, False)]
    assert len(model.asked) == 1  # her REPAIR was carried on, not asked again
    night, empty = gate.new_stills
    ((prompt, images, _model),) = model.looked
    shown = _shown(prompt)
    # Never offered: the candidate with no picture at all.
    assert images == [f"picture-of-{night}"]
    assert [c["gate_reasons"] for c in shown["candidates"]] == [[NIGHT_SKY]]
    assert shown["scene"]["scene_index"] == 5 and shown["refused_by"] == "the stills gate"
    assert shown["scene"]["picture_prompt"] and "bible_rules" in shown
    (look,) = events(engine, LOOK_EVENT)
    assert look.payload["decision"] == "CHOOSE" and look.payload["approved"] is True
    assert look.payload["chosen_take_id"] == night
    assert look.payload["previous_failure_detail"] == NIGHT_SKY
    ((skipped),) = look.payload["not_offered"]
    assert skipped["take_id"] == empty and "nu este o imagine" in skipped["why"]
    with Session(engine) as session:
        row = session.get(SceneTake, night)
        assert (row.status, row.approved_by, row.failure_code) == (
            "APPROVED",
            DIRECTOR_APPROVER,
            None,
        )
        assert session.get(SceneTake, empty).status == "REJECTED"
        # Hers, never his: the rule «nobody retires a take he approved» does not cover it.
        assert night not in owner_approved_take_ids(session, film["board"])
        assert owner_approved_among(session, [night]) == []
    # One STATUS letter to him about her look, in his words; never written twice.
    (letter,) = letters(engine, LOOK_LETTER_KIND)
    assert letter.intent == "STATUS" and letter.body_json["approved"] is True
    assert "a ales varianta 1" in letter.body_text and "cerul nopții" in letter.body_text
    again = {**look.payload, "event_id": look.event_id}
    assert look_letter(engine, {"storyboard_id": film["board"]}, again, "c") is None
    _walk(engine, settings, registry, film)
    assert len(letters(engine, LOOK_LETTER_KIND)) == 1
    assert len(model.looked) == 1


@requires_ffmpeg
def test_on_the_real_path_she_chooses_a_refused_still_and_no_video_vendor_is_called(
    engine, settings, tmp_path, monkeypatch
):
    """The staircase film, really assembled from faked vendors: her new still for scene 2 (his
    LOCAL_MOVE) is bought and the stills gate refuses its candidates (nobody could look at them
    then). She looks at the real pictures, chooses one, and the film is rejoined from its takes:
    the video vendor is never called, the still is not bought again."""
    from app.agents.memory import agent_for_role
    from app.agents.models import ModelRecord
    from app.media.production_policy import LOCAL_MOVE
    from app.media.shooting_sheet import set_scene_model
    from app.runbook import stages
    from test_daily_run_stages import _assembled_staircase_film, _provider_costs, _scripted_qc

    storyboard_id, asset_id, world = _assembled_staircase_film(
        engine, settings, tmp_path, monkeypatch
    )
    with Session(engine) as session, session.begin():
        for record in session.scalars(select(ModelRecord)):
            record.is_available = True
        director = agent_for_role(session, "Director")
        assert director is not None
        director_model = director.model_id
        provider_id = session.scalar(select(Agent.provider_id))

    def choose_first(prompt: str) -> str:
        return json.dumps({"decision": "CHOOSE", "candidate": 1, "reason": "O singură imagine."})

    model = SeeingDirector(_she_redoes_the_still_of_scene_2, choose_first)
    registry = ProviderRegistry()
    registry.register(provider_id, model)
    set_scene_model(engine, storyboard_id, 2, LOCAL_MOVE, issued_by="owner")
    posts_before = world["models"].posts()
    looked = _scripted_qc(monkeypatch, ["FAILED", "PASSED"])

    stages._edit_and_qc(engine, registry, settings, vault=None)

    (decided,) = events(engine, DECISION_EVENT)
    assert decided.payload["outcome"] == "BOUGHT_WAITING", decided.payload["done"]
    report_id = decided.payload["report_id"]
    assert decision_state(engine, report_id)["look"] is True
    _give_vision(engine, director_model)  # her eyes, from now on

    outcome = stages.continue_film(
        engine, settings, None, registry, storyboard_id, cause=f"director_qc:{report_id}"
    )

    (look,) = events(engine, LOOK_EVENT)
    assert look.payload["decision"] == "CHOOSE" and look.payload["approved"], look.payload
    ((_prompt, images, _model),) = model.looked
    assert len(images) == len(look.payload["shown"]) >= 1  # one 1080 px still per candidate
    assert all(len(image) > 1000 for image in images)
    with Session(engine) as session:
        row = session.get(SceneTake, look.payload["chosen_take_id"])
        assert (row.status, row.approved_by) == ("APPROVED", DIRECTOR_APPROVER)
    assert world["models"].posts() == posts_before, outcome  # no video vendor call
    assert len(looked) == 2 and looked[1] != asset_id
    assert looked[1] in outcome["passed_assets"], outcome
    (repair,) = [
        e.payload for e in events(engine, "runbook.qc_repair") if e.payload.get("new_asset")
    ]
    assert [item["redo"] for item in repair["applied"]] == ["rejoin"]
    assert repair["bought"] == []
    still_redos = [
        cost
        for cost in _provider_costs(engine)
        if (cost.attribution_json or {}).get("step") == "still_redo"
    ]
    assert len(still_redos) == 1  # the still was not bought again


# -------------------------------------------------------------------------- she rejects


def test_she_rejects_them_all_and_reads_the_report_again_with_her_reasons(
    engine, settings, studio, monkeypatch, tmp_path
):
    from app.runbook import stages

    film = failed_film(engine)
    decisions = iter([answer(verdicts_for(film), "REPAIR", REPAIR_5), _accepting(film)])
    model = SeeingDirector(lambda prompt: next(decisions), REJECT_ALL)
    registry = _registry(studio, model)
    _her_eyes(engine, studio)
    gate = RefusingGate(engine, monkeypatch, tmp_path, [NIGHT_SKY, OTHER])
    _walk(engine, settings, registry, film)
    standing = decision_state(engine, film["report"])
    assert standing["look"]

    looked = stages._director_looks(
        engine, settings, registry, film["report"], standing["decision"], "c"
    )

    assert looked["outcome"] == "LOOKED"
    ((_prompt, images, _model),) = model.looked
    assert sorted(images) == sorted(f"picture-of-{take}" for take in gate.new_stills)
    # Lapsed at once, not after BOUGHT_WAIT_DAYS: the report is hers again.
    state = decision_state(engine, film["report"])
    assert state["lapsed"] and not state["final"] and not state["look"]
    (look,) = events(engine, LOOK_EVENT)
    assert look.payload["decision"] == "REJECT" and look.payload["chosen_take_id"] is None
    with Session(engine) as session:
        assert {session.get(SceneTake, take).status for take in gate.new_stills} == {"REJECTED"}
    (letter,) = letters(engine, LOOK_LETTER_KIND)
    assert "cele 2 imagini cumpărate" in letter.body_text
    assert "nu alege niciuna" in letter.body_text and REJECTED_WHY in letter.body_text

    done = _walk(engine, settings, registry, film)

    # She read the report again with her own reasons, and decided within his limits.
    assert len(model.asked) == 2
    (mine,) = _context_of(model.asked[1])["your_looks"]
    assert mine["decision"] == "REJECT" and mine["reason"] == REJECTED_WHY
    assert done["outcome"] == "ACCEPTED"
    assert gate.calls == [("still", 5, True)]  # nothing bought again
    assert len(model.looked) == 1 and len(letters(engine, LOOK_LETTER_KIND)) == 1


# ---------------------------------------------------------------------- his look wins


def test_his_look_wins_over_hers_and_her_choice_is_never_his(
    engine, settings, studio, monkeypatch, tmp_path
):
    from app.media.assembler import decide_take, owner_approved_among

    film = failed_film(engine)
    model = SeeingDirector(answer(verdicts_for(film), "REPAIR", REPAIR_5), _choose("panouri"))
    registry = _registry(studio, model)
    _her_eyes(engine, studio)
    gate = RefusingGate(engine, monkeypatch, tmp_path, [NIGHT_SKY, OTHER])
    _walk(engine, settings, registry, film)
    night, text = gate.new_stills

    # A candidate he looked at himself is his, not hers to look at.
    decide_take(engine, text, "REJECTED", decided_by="owner", note="nu")
    (entry,) = look_entries(
        engine,
        decision_state(engine, film["report"])["decision"],
        ffmpeg_path=None,
        work_dir=tmp_path,
    )
    assert entry["offered"] == [night]

    done = _walk(engine, settings, registry, film)

    assert done["outcome"] == "REPAIRED"
    with Session(engine) as session:
        assert session.get(SceneTake, night).approved_by == DIRECTOR_APPROVER
        assert session.get(SceneTake, text).status == "REJECTED"
        assert night not in owner_approved_take_ids(session, film["board"])
    # His later look replaces hers: turned down, the still is no longer approved by anyone;
    # chosen again by him, it is his.
    decide_take(engine, night, "REJECTED", decided_by="owner", note="nu-mi place")
    with Session(engine) as session:
        row = session.get(SceneTake, night)
        assert (row.status, row.approved_by) == ("REJECTED", None)
    decide_take(engine, night, "APPROVED", decided_by="owner")
    with Session(engine) as session:
        assert session.get(SceneTake, night).approved_by == "owner"
        assert night in owner_approved_take_ids(session, film["board"])
        assert owner_approved_among(session, [night]) == [night]


def test_a_choice_his_look_came_before_is_not_applied(
    engine, settings, studio, monkeypatch, tmp_path
):
    from app.media.assembler import decide_take

    film = failed_film(engine)
    model = SeeingDirector(answer(verdicts_for(film), "REPAIR", REPAIR_5), _choose("panouri"))
    registry = _registry(studio, model)
    gate = RefusingGate(engine, monkeypatch, tmp_path, [NIGHT_SKY])
    _walk(engine, settings, registry, film)
    decision = decision_state(engine, film["report"])["decision"]
    (entry,) = look_entries(engine, decision, ffmpeg_path=None, work_dir=tmp_path)
    (night,) = gate.new_stills

    decide_take(engine, night, "REJECTED", decided_by="owner", note="nu")  # while she looked
    look = record_look(
        engine, decision, entry, {"decision": "CHOOSE", "candidate": 1, "reason": "bună"}, "c"
    )

    assert look["approved"] is False and "Proprietarul" in look["not_applied"]
    with Session(engine) as session:
        row = session.get(SceneTake, night)
        assert (row.status, row.approved_by, row.failure_code) == (
            "REJECTED",
            None,
            "OWNER.REJECTED",
        )
    assert decision_state(engine, film["report"])["lapsed"]


# ------------------------------------------------------------ what is never offered to her


def test_a_clip_he_could_not_choose_either_is_not_offered_and_nothing_is_asked(
    engine, settings, studio, monkeypatch, tmp_path
):
    """A clip the clip QC refused that was filmed from a still the scene no longer has (here:
    no approved still on disk at all) could not be chosen by him either (`clip_choice`): it is
    not offered to her, she is asked nothing, and the report is hers again."""
    from app.runbook import stages

    film = failed_film(engine, local_move=False)
    model = SeeingDirector("{}", pytest.fail)
    registry = _registry(studio, model)
    _her_eyes(engine, studio)
    since = utc_now()
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"a refused clip")
    with Session(engine) as session, session.begin():
        row = session.get(SceneTake, _take(session, film["board"], 5, "motion", None))
        row.status, row.path = "REJECTED", str(clip)
        row.sha256 = hashlib.sha256(clip.read_bytes()).hexdigest()
        row.failure_code, row.failure_detail = "QC.CLIP", "Controlul clipului: panouri"
        take_id = row.id
    decision = {
        "report_id": film["report"],
        "storyboard_id": film["board"],
        "media_asset_id": film["asset"],
        "started_at": since,
        "waiting_so_far": [{"scene_index": 5, "kind": "motion", "since": since}],
    }

    looked = stages._director_looks(engine, settings, registry, film["report"], decision, "c")

    ((look),) = looked["looks"]
    assert look["decision"] == "NOTHING_TO_SEE" and look["shown"] == []
    ((skipped),) = look["not_offered"]
    assert skipped["take_id"] == take_id and "imagine aprobată" in skipped["why"]
    assert model.looked == []
    (letter,) = letters(engine, LOOK_LETTER_KIND)
    assert "nu i-au putut fi arătate" in letter.body_text


# ---------------------------------------------------------------- who looks, and with what


def test_with_no_seeing_model_the_pictures_wait_and_the_report_is_hers_after_the_days(
    engine, settings, studio, monkeypatch, tmp_path
):
    film = failed_film(engine)
    model = SeeingDirector(answer(verdicts_for(film), "REPAIR", REPAIR_5), pytest.fail)
    registry = _registry(studio, model)
    gate = RefusingGate(engine, monkeypatch, tmp_path, [NIGHT_SKY])
    _walk(engine, settings, registry, film)

    waited = _walk(engine, settings, registry, film)

    assert waited["outcome"] == "WAITING"
    assert model.looked == [] and events(engine, LOOK_EVENT) == []
    (wait,) = events(engine, WAITING_EVENT)
    assert "nu vede" in wait.payload["reason"]
    (note,) = letters(engine, INBOX_KIND)
    assert "nu a putut privi" in note.body_text
    state = decision_state(engine, film["report"])
    assert state["look"] and state["tries"] == 1
    with Session(engine) as session:
        assert session.get(SceneTake, gate.new_stills[0]).status == "REJECTED"

    monkeypatch.setattr("app.media.director_qc.utc_now", lambda: _in(days=BOUGHT_WAIT_DAYS + 1))
    state = decision_state(engine, film["report"])
    assert state["lapsed"] and not state["final"]


def test_with_a_blind_model_she_looks_through_the_studios_seeing_model(
    engine, settings, studio, monkeypatch, tmp_path
):
    """Her own model declares no vision; the Voice Artist's does. The look is still hers (her
    identity, her record), answered by the model that sees."""
    from app.agents.models import ModelRecord

    film = failed_film(engine)
    model = SeeingDirector(answer(verdicts_for(film), "REPAIR", REPAIR_5), _choose("panouri"))
    registry = _registry(studio, model)
    seeing = studio["agents"]["VoiceArtist"].model_id
    assert seeing != studio["agents"]["Director"].model_id
    _give_vision(engine, seeing)
    RefusingGate(engine, monkeypatch, tmp_path, [NIGHT_SKY])
    _walk(engine, settings, registry, film)

    done = _walk(engine, settings, registry, film)

    assert done["outcome"] == "REPAIRED"
    with Session(engine) as session:
        name = session.get(ModelRecord, seeing).model_name
        (run,) = [
            run
            for run in session.scalars(select(AgentRun))
            if run.task_type == "director_take_look"
        ]
        assert run.agent_id == studio["agents"]["Director"].id and run.model_name == name
    assert model.looked[0][2] == name
    assert events(engine, LOOK_EVENT)[0].payload["model"] == name
