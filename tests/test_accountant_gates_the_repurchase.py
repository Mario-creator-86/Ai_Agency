"""Money spent again on the same picture passes the Accountant, and her refusal is discussed
with the Director (the Owner, 2026-10-13).

«Ar fi bine să avem încă un prag de verificare la Nadia, după ce trece de Director, asta doar
când vine vorba de a cheltui iar bani pentru aceeași imagine sau video sau sunet. Nadia
primește: ce se cumpără cu promptul nou, ce era greșit, promptul nou. Atunci și Sarah și Nadia
trebuie să fie de acord că e necesar.» «Nadia și Sarah discută. De la contabilitate nu ar trebui
să ajungă la mine. Ar trebui la Sarah înapoi și ei să hotărască. La mine ajunge doar dacă este
peste bugetul filmului aprobat.»

`economy.repurchase_gate`, hooked in `runbook.stages._apply_repairs` after the Director's
correction and before the purchase. Offline: the fakes of `test_redo_resume_spends_his_yes`
(a planned film, its failed render, the vendor spy) and scripted agents; the gate's two
questions are answered by the script, so nothing here proves a live model."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from app.agents.models import AgentMessage, MemoryRecord
from app.economy import repurchase_gate as gate
from app.economy.budget import BudgetCommand, set_budget
from app.economy.services import record_provider_cost
from app.media.models import SceneTake, VideoRenderJob
from app.media.toolchain import find_ffmpeg
from app.models import ApprovalRequest, OwnerPolicy
from app.providers.base import GenerateResult
from app.runbook import stages
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_approvals import answer
from test_clip_qc_wiring import events
from test_director_rewrites_failed_scene import (  # noqa: F401 - the studio fixture
    Agents,
    a_planned_film,
    agents_say,
    studio,
)
from test_film_costing import SEEDANCE, Account, Models, SpyVideo, autonomous_mode
from test_redo_resume_spends_his_yes import _failed_film, _walk

pytestmark = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")

APPROVE = {
    "verdict": "APPROVE",
    "reason": "Refacerea de 6,80 USD încape în cei 8,44 USD rămași din plafon; norii se mișcă.",
    "cheaper_alternative": "",
}
REFUSE = {
    "verdict": "REFUSE",
    "reason": "A doua cumpărare a aceluiași cadru, 6,80 USD, pentru o mișcare abia vizibilă.",
    "cheaper_alternative": "Păstrăm cadrul cumpărat; filmul se publică așa.",
}
INSIST = {"decision": "INSIST", "reason": "Un cadru înghețat strică filmul; cumpăr o dată."}
ACCEPT_MINOR = {"decision": "ACCEPT_MINOR", "reason": "Norii se mișcă puțin; se poate publica."}
CLOSE_SCENE = {"decision": "CLOSE_SCENE", "reason": "Nu mai cumpăr scena 1 pe aceste cuvinte."}


class Desk(Agents):
    """Every agent's model: the rewrite ladder as `Agents` scripts it, and the gate's two
    questions — Nadia's verdict (``nadia``) and Sarah's decision (``sarah``) — answered as
    scripted; a string is answered as it is, for an answer nobody can read."""

    def __init__(self, nadia: Any = None, sarah: Any = None, **kwargs: Any):
        super().__init__(**kwargs)
        self.nadia = dict(APPROVE) if nadia is None else nadia
        self.sarah = dict(INSIST) if sarah is None else sarah
        self.verdicts: list[str] = []
        self.decisions: list[str] = []

    async def generate(self, model, prompt, **kwargs):
        if '"repurchase-verdict"' in prompt:
            self.verdicts.append(prompt)
            return GenerateResult(_said(self.nadia), 10, 40, None)
        if '"repurchase-decision"' in prompt:
            self.decisions.append(prompt)
            return GenerateResult(_said(self.sarah), 10, 40, None)
        return await super().generate(model, prompt, **kwargs)


def _said(script: Any) -> str:
    return json.dumps(script) if isinstance(script, dict) else str(script)


def _paid_clip(engine, tmp_path, storyboard_id: str, asset_id: str, credits: float = 340) -> str:
    """The failed film's scene 1 clip, bought for ``credits`` and refused by clip QC: the
    motion layer of the scene was paid for once, so its paid redo is money spent again."""
    take_id = str(uuid4())
    clip = tmp_path / f"{take_id}.mp4"
    clip.write_bytes(b"clip bytes")
    now = utc_now()
    with Session(engine) as session, session.begin():
        session.add(
            SceneTake(
                id=take_id,
                storyboard_id=storyboard_id,
                scene_number=1,
                kind="motion",
                prompt_hash=uuid4().hex,
                model_id="seedance2_5",
                resolution="1080:1920",
                seconds=5.0,
                credits_quoted=credits,
                credits_measured=credits,
                status="REJECTED",
                path=str(clip),
                sha256="b" * 64,
                created_at=now,
                updated_at=now,
            )
        )
        job = session.scalar(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == asset_id)
        )
        production = dict(job.production_json)
        production["scenes"] = [
            {**scene, "motion": {"take_id": take_id}} for scene in production["scenes"]
        ]
        job.production_json = production
    return take_id


def _film(engine, tmp_path, monkeypatch, *, paid_clip: bool = True) -> dict[str, Any]:
    """A planned film whose render failed on scene 1's clip, the vendor faked, the purchase
    unasked (AUTONOMOUS_CEO under the MODE rule) unless a test asks otherwise."""
    storyboard_id = a_planned_film(engine, tmp_path, still_by="owner")
    autonomous_mode(engine)
    account = Account(10_000)
    spy = SpyVideo("seedance2_5", account)
    monkeypatch.setattr(
        stages,
        "sheet_wiring",
        lambda engine_, vault, settings_: {
            "integration_id": None,
            "capabilities": [SEEDANCE],
            "image_adapter": None,
            "account": account,
            "adapter_for_model": Models(spy),
            "resolution": "1080p",
            "storage_root": tmp_path / "media",
        },
    )
    asset_id = _failed_film(engine, tmp_path, storyboard_id)
    clip = _paid_clip(engine, tmp_path, storyboard_id, asset_id) if paid_clip else None
    with Session(engine) as session:
        job = session.scalar(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == asset_id)
        )
        production = dict(job.production_json)
    reading = {
        "storyboard_id": storyboard_id,
        "media_asset_id": asset_id,
        "report_id": str(uuid4()),
        # The render's record, as her repair reads it (the takes the film was cut from).
        "production": production,
        "proposals": [
            SimpleNamespace(
                scene_index=1, redo="motion", reason="the clip barely moved", free=False
            )
        ],
        "findings": [{"scene_index": 1, "text": "Scena 1: clipul aproape nu se mișcă"}],
        "verdicts": [],
    }
    return {"board": storyboard_id, "asset": asset_id, "clip": clip, "spy": spy, "reading": reading}


def _gate_events(engine, storyboard_id: str) -> list[dict[str, Any]]:
    return [dict(e.payload) for e in events(engine, gate.GATE_EVENT, storyboard_id)]


def _opinions(engine) -> list[MemoryRecord]:
    """The gate's own opinions (the rewrite ladder remembers the Director's review too)."""
    with Session(engine) as session:
        rows = session.scalars(
            select(MemoryRecord)
            .where(
                MemoryRecord.memory_class == "AGENT_OPINION",
                MemoryRecord.content.like("Refacere mișcarea scena 1%"),
            )
            .order_by(MemoryRecord.created_at)
        ).all()
        session.expunge_all()
        return list(rows)


def _letters(engine) -> list[AgentMessage]:
    with Session(engine) as session:
        rows = session.scalars(
            select(AgentMessage)
            .where(AgentMessage.subject.like("%contabilitatea nu e de acord%"))
            .order_by(AgentMessage.created_at)
        ).all()
        session.expunge_all()
        return list(rows)


def _asked_of_owner(engine) -> list[ApprovalRequest]:
    with Session(engine) as session:
        return list(session.scalars(select(ApprovalRequest)))


# ------------------------------------------------------------------ 1. Nadia agrees: bought


def test_nadia_reads_the_corrected_redo_with_its_figures_and_her_approve_buys(
    engine,
    settings,
    tmp_path,
    studio,  # noqa: F811 - the studio fixture
    monkeypatch,
):
    film = _film(engine, tmp_path, monkeypatch)
    desk = Desk(nadia=APPROVE)

    result = _walk(engine, settings, agents_say(studio, desk), film["board"], film["reading"])

    assert [entry["scene_index"] for entry in result["bought"]] == [1], result
    assert result["refused"] == [] and result["asked"] == [] and len(film["spy"].asked) == 1
    assert _asked_of_owner(engine) == [], "the Owner was not asked: inside the ceiling"
    # She was asked once, and nothing was discussed: Sarah was not asked.
    (asked,) = desk.verdicts
    assert desk.decisions == []
    data = json.loads(
        asked.split('<untrusted_source_evidence hash="repurchase-verdict">\n', 1)[1].split(
            "\n</untrusted_source_evidence>", 1
        )[0]
    )
    assert data["scene_index"] == 1 and data["layer"] == "motion"
    assert data["film"]["title"] and data["film"]["storyboard_id"] == film["board"]
    # What was wrong, her brief's diagnosis, and the corrected words the plan buys.
    wrong = data["what_was_wrong"]["quality_control_and_director"]
    assert "the clip barely moved" in wrong and "Scena 1: clipul aproape nu se mișcă" in wrong
    assert "slow drift" in data["what_was_wrong"]["director_brief"]["diagnosis"]
    assert "from left to right" in data["corrected_prompt"]
    assert "from left to right" not in data["what_was_wrong"]["director_brief"]["old_prompt"]
    # The price at today's table, the film's books and ceiling, the redos and his caps.
    assert data["this_redo"]["model_id"] == "seedance2_5"
    assert data["this_redo"]["cap_usd"] == pytest.approx(6.8)
    assert data["film_books"]["ceiling_usd"] > 0 and "remaining_usd" in data["film_books"]
    assert data["film_books"]["after_this_redo_usd"] == pytest.approx(
        data["film_books"]["spent_usd"] + 6.8
    )
    assert data["redos_bought"] == {
        "this_scene": 0,
        "this_film": 0,
        "cap_per_scene": settings.film_max_paid_redos_per_scene,
        "cap_per_film": settings.film_max_paid_redos,
    }
    assert [take["take_id"] for take in data["paid_before_for_this_layer"]] == [film["clip"]]
    assert data["daily_budget"] is None, "no daily budget set: said so, not invented"
    assert "Nadia primește" in data["rule"]["owner_ro"] and data["rule"]["studio"]
    # The verdict is on the film's record, keyed by the plan, and in her memory.
    (recorded,) = _gate_events(engine, film["board"])
    assert recorded["outcome"] == gate.AGREED and recorded["buys"] is True
    assert recorded["scene_index"] == 1 and recorded["layer"] == "motion"
    assert recorded["plan_hash"] and recorded["of_asset"] == film["asset"]
    assert recorded["accountant"]["verdict"] == "APPROVE" and recorded["accountant"]["run_id"]
    assert recorded["director"] is None and recorded["price"]["cap_usd"] == pytest.approx(6.8)
    assert recorded["paid_before"] == [film["clip"]]
    (opinion,) = _opinions(engine)
    assert opinion.agent_id == studio["agents"]["Accountant"]
    assert opinion.source_id == recorded["accountant"]["run_id"]
    assert "APPROVE" in opinion.content and "scena 1" in opinion.content
    assert _letters(engine) == []


# ---------------------------------------------------- 2. Nadia refuses, Sarah insists: bought


def test_her_refusal_is_discussed_and_sarahs_insist_buys_with_both_opinions_recorded(
    engine,
    settings,
    tmp_path,
    studio,  # noqa: F811 - the studio fixture
    monkeypatch,
):
    film = _film(engine, tmp_path, monkeypatch)
    desk = Desk(nadia=REFUSE, sarah=INSIST)

    result = _walk(engine, settings, agents_say(studio, desk), film["board"], film["reading"])

    assert [entry["scene_index"] for entry in result["bought"]] == [1], result
    assert len(film["spy"].asked) == 1 and _asked_of_owner(engine) == []
    assert len(desk.verdicts) == 1 and len(desk.decisions) == 1
    # Sarah read Nadia's words, and was told the Owner is not asked.
    assert REFUSE["reason"] in desk.decisions[0] and "the Owner is not asked" in desk.decisions[0]
    (recorded,) = _gate_events(engine, film["board"])
    assert recorded["outcome"] == gate.INSISTED and recorded["buys"] is True
    assert recorded["accountant"]["verdict"] == "REFUSE"
    assert recorded["accountant"]["cheaper_alternative"] == REFUSE["cheaper_alternative"]
    assert recorded["director"]["decision"] == "INSIST" and recorded["director"]["run_id"]
    assert REFUSE["reason"] in recorded["reason"] and INSIST["reason"] in recorded["reason"]
    # Her letter to Sarah and Sarah's answer, settled; both opinions remembered.
    letter, reply = _letters(engine)
    assert letter.intent == "HANDOFF" and letter.from_agent_id == studio["agents"]["Accountant"]
    assert letter.to_agent_id == studio["agents"]["Director"] and letter.status == "RESOLVED"
    assert REFUSE["reason"] in letter.body_text and "6,80 USD" in letter.body_text
    assert REFUSE["cheaper_alternative"] in letter.body_text
    assert letter.body_json["kind"] == "repurchase_refused"
    assert reply.in_reply_to == letter.id and reply.status == "RESOLVED"
    assert INSIST["reason"] in reply.body_text and "insist" in reply.body_text
    assert recorded["letter_id"] == letter.id
    opinions = _opinions(engine)
    assert [row.agent_id for row in opinions] == [
        studio["agents"]["Accountant"],
        studio["agents"]["Director"],
    ]
    assert "REFUSE" in opinions[0].content and "INSIST" in opinions[1].content


# ------------------------------ 3. Nadia refuses, Sarah accepts or closes: nothing is bought


def test_sarahs_accept_minor_keeps_the_take_through_her_looks_path_and_buys_nothing(
    engine,
    settings,
    tmp_path,
    studio,  # noqa: F811 - the studio fixture
    monkeypatch,
):
    film = _film(engine, tmp_path, monkeypatch)
    desk = Desk(nadia=REFUSE, sarah=ACCEPT_MINOR)

    result = _walk(engine, settings, agents_say(studio, desk), film["board"], film["reading"])

    assert result["bought"] == [] and result["asked"] == [] and film["spy"].asked == []
    assert result["refused"] == [], result
    assert _asked_of_owner(engine) == [], "nothing reached the Owner"
    (kept,) = result["overturned"]
    assert kept["scene_index"] == 1 and kept["redo"] == ["motion"]
    assert kept["verdict"] == "OVERTURNED" and kept["severity"] == "minor"
    assert ACCEPT_MINOR["reason"] in kept["reason"] and REFUSE["reason"] in kept["reason"]
    assert kept["takes"]["clip"] == film["clip"]
    (recorded,) = _gate_events(engine, film["board"])
    assert recorded["outcome"] == gate.ACCEPTED_MINOR and recorded["buys"] is False
    assert kept["run_id"] == recorded["director"]["run_id"]
    assert len(_letters(engine)) == 2 and len(_opinions(engine)) == 2


def test_sarahs_close_scene_buys_nothing_and_holds_the_scene_with_their_words(
    engine,
    settings,
    tmp_path,
    studio,  # noqa: F811 - the studio fixture
    monkeypatch,
):
    film = _film(engine, tmp_path, monkeypatch)
    desk = Desk(nadia=REFUSE, sarah=CLOSE_SCENE)

    result = _walk(engine, settings, agents_say(studio, desk), film["board"], film["reading"])

    assert result["bought"] == [] and result["asked"] == [] and film["spy"].asked == []
    assert result.get("overturned", []) == [] and _asked_of_owner(engine) == []
    (held,) = result["refused"]
    assert held["status"] == gate.REPURCHASE_REFUSED and held["scene_index"] == 1
    assert held["what"] == "scena 1: mișcarea" and held["cap_usd"] == pytest.approx(6.8)
    assert REFUSE["reason"] in held["reason"] and CLOSE_SCENE["reason"] in held["reason"]
    (recorded,) = _gate_events(engine, film["board"])
    assert recorded["outcome"] == gate.CLOSED and recorded["buys"] is False
    # The repair's letter says it in the Owner's words.
    lines = stages._repair_lines(result)
    assert any("Scena 1: mișcarea: Contabila a refuzat" in line for line in lines), lines

    # The same words on the next walk: their decision stands, nobody is asked again.
    again = _walk(engine, settings, agents_say(studio, desk), film["board"], film["reading"])
    assert again["bought"] == [] and film["spy"].asked == []
    assert again["refused"][0]["status"] == gate.REPURCHASE_REFUSED
    assert len(desk.verdicts) == 1 and len(desk.decisions) == 1
    assert len(_gate_events(engine, film["board"])) == 1


# --------------------------------------------- 4. no verdict is no approval: held, said so


def test_an_answer_nobody_can_read_buys_nothing_and_holds_the_scene_for_the_next_try(
    engine,
    settings,
    tmp_path,
    studio,  # noqa: F811 - the studio fixture
    monkeypatch,
):
    film = _film(engine, tmp_path, monkeypatch)
    desk = Desk(nadia="I would rather not say.")

    result = _walk(engine, settings, agents_say(studio, desk), film["board"], film["reading"])

    assert result["bought"] == [] and result["asked"] == [] and film["spy"].asked == []
    assert _asked_of_owner(engine) == [] and desk.decisions == []
    (held,) = result["refused"]
    assert held["status"] == gate.REPURCHASE_UNDECIDED and held["scene_index"] == 1
    assert "Contabila nu a dat un verdict" in held["reason"]
    assert "nu se cumpără a doua oară fără acordul ei" in held["reason"]
    # Asked twice (no object at all: the thinking retry), then nothing more on this walk.
    assert len(desk.verdicts) == 2
    (recorded,) = _gate_events(engine, film["board"])
    assert recorded["outcome"] == gate.HELD and recorded["buys"] is False
    assert recorded["accountant"]["verdict"] is None and recorded["accountant"]["run_id"]
    assert _opinions(engine) == [] and _letters(engine) == []

    # The next try asks her again: no verdict stands for nothing.
    desk.nadia = APPROVE
    again = _walk(engine, settings, agents_say(studio, desk), film["board"], film["reading"])
    assert [entry["scene_index"] for entry in again["bought"]] == [1], again
    assert len(desk.verdicts) == 3 and len(film["spy"].asked) == 1
    assert [e["outcome"] for e in _gate_events(engine, film["board"])] == [gate.HELD, gate.AGREED]


def test_sarahs_accept_minor_of_a_defect_measured_serious_holds_the_scene(
    engine,
    settings,
    tmp_path,
    studio,  # noqa: F811 - the studio fixture
    monkeypatch,
):
    """The contract of her second look (2026-10-12): a defect quality control measured as
    serious is not accepted as minor. Her ACCEPT_MINOR on one buys nothing and accepts
    nothing; the scene waits, and Sarah was told which decisions were hers."""
    film = _film(engine, tmp_path, monkeypatch)
    film["reading"]["verdicts"] = [
        {
            "id": 1,
            "scene_index": 1,
            "verdict": "REAL",
            "text": "Scena 1: clipul este înghețat, cadru static",
            "measured_serious": "frozen",
        }
    ]
    desk = Desk(nadia=REFUSE, sarah=ACCEPT_MINOR)

    result = _walk(engine, settings, agents_say(studio, desk), film["board"], film["reading"])

    assert result["bought"] == [] and film["spy"].asked == [] and result["overturned"] == []
    (held,) = result["refused"]
    assert held["status"] == gate.REPURCHASE_UNDECIDED
    assert "măsurat ca serios" in held["reason"]
    assert "cannot be accepted as minor" in desk.decisions[0]
    (recorded,) = _gate_events(engine, film["board"])
    assert recorded["outcome"] == gate.HELD and recorded["measured_serious"] is True
    assert recorded["director"]["decision"] == "ACCEPT_MINOR"


# ------------------------------------------------------ 5. what is never hers to be asked


def test_the_first_purchase_of_a_layer_is_never_gated(
    engine,
    settings,
    tmp_path,
    studio,  # noqa: F811 - the studio fixture
    monkeypatch,
):
    film = _film(engine, tmp_path, monkeypatch, paid_clip=False)
    desk = Desk(nadia=REFUSE, sarah=CLOSE_SCENE)

    result = _walk(engine, settings, agents_say(studio, desk), film["board"], film["reading"])

    assert [entry["scene_index"] for entry in result["bought"]] == [1], result
    assert desk.verdicts == [] and desk.decisions == []
    assert _gate_events(engine, film["board"]) == [] and _letters(engine) == []


def test_a_take_without_credits_on_it_is_not_a_paid_take(engine, tmp_path, monkeypatch):
    film = _film(engine, tmp_path, monkeypatch, paid_clip=False)
    with Session(engine) as session:
        assert gate.paid_takes(session, film["board"], 1, "still") == []
        assert gate.paid_takes(session, film["board"], 1, "motion") == []
    clip = _paid_clip(engine, tmp_path, film["board"], film["asset"], credits=340)
    with Session(engine) as session, session.begin():
        quoted = session.get(SceneTake, clip)
        quoted.status = "QUOTED"
    with Session(engine) as session:
        assert gate.paid_takes(session, film["board"], 1, "motion") == []
    with Session(engine) as session, session.begin():
        session.get(SceneTake, clip).status = "REJECTED"
    with Session(engine) as session:
        (paid,) = gate.paid_takes(session, film["board"], 1, "motion")
    assert paid["take_id"] == clip and paid["credits"] == 340 and paid["status"] == "REJECTED"


def test_a_redo_over_the_films_ceiling_is_the_owners_refusal_and_nadia_is_not_asked(
    engine,
    settings,
    tmp_path,
    studio,  # noqa: F811 - the studio fixture
    monkeypatch,
):
    from test_budget_gates import policy

    film = _film(engine, tmp_path, monkeypatch)
    policy(engine, environment="PRODUCTION", mode="AUTONOMOUS_CEO", rule="MODE")
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="100"))
    record_provider_cost(
        engine,
        provider="runway",
        external_reference=f"foaie:{film['board']}:stills:{uuid4()}",
        status="ESTIMATED",
        amount="6.000000",
        attribution={"storyboard_id": film["board"], "step": "stills"},
        correlation_id=str(uuid4()),
    )
    # 6 USD in the books plus the redo's 6.80 cap pass a 12 USD ceiling.
    ceiling = settings.model_copy(update={"film_budget_usd": 12.0})
    monkeypatch.setattr("app.media.assembler._studio_settings", lambda: ceiling)
    desk = Desk(nadia=APPROVE)

    result = _walk(engine, ceiling, agents_say(studio, desk), film["board"], film["reading"])

    assert result["bought"] == [] and film["spy"].asked == []
    (refused,) = result["refused"]
    assert refused["status"] == "OVER_FILM_BUDGET", refused
    assert desk.verdicts == [] and desk.decisions == []
    assert _gate_events(engine, film["board"]) == []


# -------------------------------- 6. the resumed walk spends his yes without asking again


def test_the_walk_resumed_on_his_yes_does_not_ask_nadia_again(
    engine,
    settings,
    tmp_path,
    studio,  # noqa: F811 - the studio fixture
    monkeypatch,
):
    film = _film(engine, tmp_path, monkeypatch)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).paid_media_approval = "EVERY_PAID_STEP"
    desk = Desk(nadia=APPROVE)

    # Walk 1: her brief, his rewrite, Nadia's yes; the redo is asked of the Owner.
    first = _walk(engine, settings, agents_say(studio, desk), film["board"], film["reading"])

    assert first["bought"] == [] and len(first["asked"]) == 1, first
    assert len(desk.verdicts) == 1 and film["spy"].asked == []
    (recorded,) = _gate_events(engine, film["board"])
    assert recorded["outcome"] == gate.AGREED

    # His yes; the walk resumes on the corrected words and the recorded agreement.
    answer(engine, first["asked"][0]["approval_id"], "APPROVED", note="Da, reface mișcarea.")
    second = _walk(engine, settings, agents_say(studio, desk), film["board"], film["reading"])

    assert [entry["scene_index"] for entry in second["bought"]] == [1], second
    assert second["asked"] == [] and second["refused"] == []
    assert len(desk.verdicts) == 1, "Nadia was not asked twice for the same corrected words"
    assert len(film["spy"].asked) == 1
    assert len(_gate_events(engine, film["board"])) == 1
    with Session(engine) as session:
        stands = gate.decided_before(session, film["board"], 1, "motion", recorded["plan_hash"])
        assert stands is not None and stands["outcome"] == gate.AGREED
        assert gate.decided_before(session, film["board"], 1, "motion", "other-words") is None
