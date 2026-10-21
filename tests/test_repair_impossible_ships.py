"""A REPAIR nothing of which can be carried out under the Owner's caps publishes the film.

2026-10-16, «The Zero Script Club» (f06808c9, report 928af1a7): rendered on 13 October, QC
FAILED on scene 4; from the 14th the Director decided REPAIR on every reading, and every time
«nimic din refacerea hotărâtă nu se putea face» — the Accountant refusing a fifth paid motion of
scene 4 on the cap's own words, a prompt the lint blocked on a scene that had had 18 stills and
3 shots. Her tries ran out (26), her one walk under the cap rule ran at 22:21Z the night before
the continuation's cap fix, and nothing walked the film again; its sheet repair kept asking for
whole-film shot plans. The Owner: «Vreau să publice… Aș vrea să publicăm ce avem».

These tests hold, with a scripted Director and the redo path faked where it would buy (no
vendor, no credit, no model of the studio's own):

- a film like f06808c9 (REPAIR decided, every redo refused by the caps, tries spent) is walked
  again until it is published, from her stored REPAIR and without a model call, accepted
  under the cap with words that say so; nothing bought, no letter to the Owner, an event
  recorded;
- the Accountant's refusal or silence below the renders cap is not the cap's; a redo that
  cannot be made at all ships only after she read the report again knowing it; a verdict
  that is not hers is never published under the cap (the review of 2026-10-17);
- a REPAIR refused only for money keeps today's path (it waits; no ACCEPT, no developer note);
- a REPAIR that can be done is carried out as before;
- a prompt blocker below the cap that repeats on three walks is a tool's defect for the
  developer, and the pass stops asking her for a day; a stop of the moment never is;
- the film rejoined free from the takes kept under the cap is measured and, failing again,
  accepted under the cap on its own report; only narration still left to voice refuses
  that rejoin, never the plan's reservation for the whole voiceover;
- a film that goes to publication with what it has gets no sheet repair any more.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from app.agents.messages import is_for_owner
from app.agents.models import Agent, AgentMessage, ModelRecord, Role
from app.agents.services import seed_initial_workforce
from app.media.assembler import SceneRedoRefused
from app.media.director_qc import DECISION_EVENT, WAITING_EVENT, record_decision
from app.media.models import MediaAsset, QualityControlReport, SceneTake, VideoRenderJob
from app.media.services import seed_default_character_bibles
from app.models import OwnerPolicy
from app.services import append_event, utc_now
from app.workflows.models import TaskQueueItem
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_director_decides_qc import (
    FakeRedoPath,
    _continuations,
    _pass,
    _production,
    answer,
    director_says,
    events,
    failed_film,
    nothing_bought,
    verdicts_for,
)

#: The Accountant's refusal of 22:21Z, as the repair recorded it.
ACCOUNTANT_REFUSED = (
    "Contabila a refuzat a doua cumpărare (Scena 5 a fost deja cumpărată de 4 ori pe acest film "
    "(cap 2 pe scenă, cap 20 pe film), iar acest redo ar fi a cincea reluare plătită pe scenă)"
)
SHIPPED = "limita de randări a fost atinsă; filmul se publică cu ce are"


@pytest.fixture
def studio(engine):
    """The seeded studio, as tests/test_director_decides_qc.py has it: its employees by role."""
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


def _renders(engine, board: str, scene: int, kind: str, count: int) -> None:
    """``count`` paid renders of the scene's layer, each refused (on disk nowhere)."""
    now = utc_now()
    with Session(engine) as session, session.begin():
        for n in range(count):
            take_id = str(uuid4())
            session.add(
                SceneTake(
                    id=take_id,
                    storyboard_id=board,
                    scene_number=scene,
                    kind=kind,
                    prompt_hash=uuid4().hex,
                    model_id="seedance" if kind == "motion" else "seedream5_pro",
                    resolution="1080:1920",
                    status="REJECTED",
                    failure_code="QC.CLIP" if kind == "motion" else "LOCAL.STILL_GATE",
                    path=f"storage/{take_id}.bin",
                    sha256=uuid4().hex,
                    remote_task_id=f"{kind}-{scene}-{n}",
                    created_at=now,
                    updated_at=now,
                )
            )


def _owner_letters(engine) -> list[str]:
    with Session(engine) as session:
        return [str(row.id) for row in session.scalars(select(AgentMessage)) if is_for_owner(row)]


def _stuck_like_f06808c9(engine, film: dict[str, Any]) -> None:
    """Her REPAIR of scene 5's motion refused by the Accountant on the cap's words, 26 rounds
    that left her a note, and her one walk under the cap rule already done."""
    from app.workflows.passes.director_qc_review import CAP_RULE_SINCE, CAUSE_PREFIX

    record_decision(
        engine,
        {
            "report_id": film["report"],
            "media_asset_id": film["asset"],
            "storyboard_id": film["board"],
            "decided_by": "Director",
            "decision": "REPAIR",
            "summary": "Refac doar scena 5.",
            "verdicts": [],
            "repairs": [{"scene_index": 5, "redo": "motion", "reason": "clipul"}],
            "outcome": "NOTHING_DONE",
            "final": False,
            "done": {
                "applied": [],
                "bought": [],
                "asked": [],
                "refused": [
                    {
                        "redo": "motion",
                        "scene_index": 5,
                        "status": "REPURCHASE_REFUSED",
                        "reason": ACCOUNTANT_REFUSED,
                        "what": "scena 5: mișcarea",
                    }
                ],
                "limited": [],
                "skipped": [],
                "waiting": [],
                "card_id": None,
                "new_asset": None,
            },
        },
        "c",
    )
    with Session(engine) as session, session.begin():
        for _ in range(26):
            append_event(
                session,
                WAITING_EVENT,
                "quality_control_report",
                film["report"],
                1,
                {"storyboard_id": film["board"], "reason": "nimic din refacerea hotărâtă"},
                "w",
            )
        append_event(
            session,
            "runbook.film_continued",
            "storyboard",
            film["board"],
            1,
            {"status": "COMPLETED", "cause": f"{CAUSE_PREFIX}{film['report']}"},
            "walk",
        )
    assert utc_now() > CAP_RULE_SINCE


# ------------------------------------------------------------- f06808c9: ships under the cap


def test_a_film_like_f06808c9_is_walked_once_more_and_published_under_the_cap(
    engine, settings, studio, monkeypatch
):
    from app.media.director_qc import decision_state
    from app.runbook import stages

    film = failed_film(engine, local_move=False)
    _renders(engine, film["board"], 5, "motion", 3)
    _stuck_like_f06808c9(engine, film)
    _production(engine)
    assert decision_state(engine, film["report"])["tries"] == 26

    # The pass walks it once more, under its own key, and not twice while the walk stands.
    assert _pass(engine, settings) == {"queued": [film["board"]]}
    (task,) = _continuations(engine)
    assert task.idempotency_key.endswith(f"cap-settle-{film['report']}-0")
    assert _pass(engine, settings) == {"queued": []}

    repairs = [{"scene_index": 5, "redo": "motion", "reason": "clipul se deformează"}]
    registry, model = director_says(studio, answer(verdicts_for(film), "REPAIR", repairs))
    redo = FakeRedoPath(engine, monkeypatch, still_status="PAID")

    def no_settle(*_a, **_k):
        pytest.fail("the film's other scenes do not stand on its takes: nothing is settled")

    monkeypatch.setattr(stages, "_settle_capped", no_settle)
    published: list[list[str]] = []

    def publish(engine_, settings_, vault, registry_, passed):
        published.append(list(passed))
        return {"status": "COMPLETED", "reason": "publicat", "artefacts": {"published": passed}}

    monkeypatch.setattr(stages, "_publish_passed", publish)
    letters_before = _owner_letters(engine)

    outcome = stages.continue_film(
        engine,
        settings,
        None,
        registry,
        film["board"],
        cause=str(task.payload["cause"]),
        correlation_id=task.id,
    )

    assert outcome["status"] == "COMPLETED", outcome
    assert published == [[film["asset"]]]
    assert redo.calls == [] and redo.measured == []
    # Published from her stored REPAIR: she is not asked again (no answer can strand it).
    assert model.asked == []
    nothing_bought(engine)
    assert _owner_letters(engine) == letters_before
    decided = events(engine, DECISION_EVENT)[-1].payload
    assert decided["decision"] == "ACCEPT" and decided["outcome"] == "ACCEPTED"
    assert decided["decided_by"] == "Director"
    assert SHIPPED in decided["summary"].lower()
    assert decided["shipped_under_cap"]["capped"] == [5]
    assert decided["shipped_under_cap"]["how"] == "AS_IT_STANDS"
    assert decided["shipped_under_cap"]["from_stored_decision"] is True
    (shipped,) = events(engine, stages.SHIPPED_UNDER_CAP_EVENT)
    assert shipped.payload["outcome"] == "ACCEPTED" and shipped.payload["bought"] == []
    assert shipped.payload["passed_asset"] == film["asset"]
    assert shipped.payload["from_stored_decision"] is True
    with Session(engine) as session:
        passed = session.scalar(
            select(QualityControlReport).where(
                QualityControlReport.media_asset_id == film["asset"],
                QualityControlReport.status == "PASSED",
            )
        )
        assert passed is not None
        assert passed.checks_json["director_qc"]["decided_by"] == "Director"
    # Decided: nothing more is queued for it.
    with Session(engine) as session, session.begin():
        session.get(TaskQueueItem, task.id).status = "COMPLETED"
    assert _pass(engine, settings) == {"queued": []}


def _later(monkeypatch, hours: float) -> None:
    """The review pass's clock ``hours`` ahead (the walks' records are immutable history)."""
    from app.workflows.passes import director_qc_review

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return datetime.now(tz) + timedelta(hours=hours)

    monkeypatch.setattr(director_qc_review, "datetime", Later)


def _clock(monkeypatch, hours: float) -> None:
    """The studio's clock ``hours`` ahead: the events a walk writes, and the loop guard's now."""
    import app.services as services
    from app.runbook import stages

    def later() -> str:
        return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()

    monkeypatch.setattr(services, "utc_now", later)
    monkeypatch.setattr(stages, "utc_now", later)


def test_a_cap_settle_walk_that_published_nothing_is_walked_again_later_never_once_only(
    engine, settings, studio, monkeypatch
):
    """The review of 2026-10-17: the cap-settle walk was keyed once per report, so a walk that
    published nothing (refused by his stop, safe mode or his mode; her reading not validated)
    left the film standing for good. Each next walk now waits twice as long as the one before,
    and the walk publishes from her stored REPAIR without asking her: no answer of hers can
    strand it."""
    from app.runbook import stages
    from app.workflows.passes.director_qc_review import CAUSE_PREFIX

    film = failed_film(engine, local_move=False)
    _renders(engine, film["board"], 5, "motion", 3)
    _stuck_like_f06808c9(engine, film)
    _production(engine)
    assert _pass(engine, settings) == {"queued": [film["board"]]}
    (first,) = _continuations(engine)

    def walked_without_publishing(task_id: str) -> None:
        # The walk her failed reading or his mode ended: tries 27, her REPAIR still the newest.
        with Session(engine) as session, session.begin():
            session.get(TaskQueueItem, task_id).status = "COMPLETED"
            append_event(
                session,
                WAITING_EVENT,
                "quality_control_report",
                film["report"],
                1,
                {
                    "storyboard_id": film["board"],
                    "reason": "Decizia Directoarei nu respectă forma cerută nici a doua oară",
                },
                "w",
            )
            append_event(
                session,
                "runbook.film_continued",
                "storyboard",
                film["board"],
                1,
                {"status": "SKIPPED", "cause": f"{CAUSE_PREFIX}{film['report']}"},
                task_id,
            )

    walked_without_publishing(first.id)
    assert _pass(engine, settings) == {"queued": []}  # not again at once
    _later(monkeypatch, 2)
    assert _pass(engine, settings) == {"queued": [film["board"]]}
    second = next(task for task in _continuations(engine) if task.id != first.id)
    assert second.idempotency_key.endswith(f"cap-settle-{film['report']}-1")
    walked_without_publishing(second.id)
    _later(monkeypatch, 1.5)
    assert _pass(engine, settings) == {"queued": []}  # the wait doubled: two hours now
    _later(monkeypatch, 3)
    assert _pass(engine, settings) == {"queued": [film["board"]]}
    assert len(_continuations(engine)) == 3

    # The walk publishes it from her stored REPAIR; her model, which would not validate, is
    # never asked.
    registry, model = director_says(studio, "this is not her answer")
    FakeRedoPath(engine, monkeypatch, still_status="PAID")
    done = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )
    assert done["outcome"] == "ACCEPTED" and done["passed_asset"] == film["asset"]
    assert model.asked == []
    nothing_bought(engine)


@pytest.mark.parametrize("status", ["REPURCHASE_REFUSED", "REPURCHASE_UNDECIDED"])
def test_the_accountant_below_the_renders_cap_is_not_the_cap(
    engine, settings, studio, monkeypatch, status
):
    """The review of 2026-10-17: at a scene's paid-redo limit `_apply_repairs` stops every redo
    before the Accountant except the motion that continues a still round, which the caps let
    through. Her refusal there, or no verdict at all (a model's silence), is not the cap's: her
    REPAIR waits and is read again, and the film is not accepted with the old scene while a
    paid still waits for its motion. The same refusal on a layer past its renders is."""
    from app.economy import repurchase_gate
    from app.runbook import stages

    film = failed_film(engine, local_move=False)
    _renders(engine, film["board"], 5, "motion", 1)  # one render of the cap's three
    monkeypatch.setattr(stages, "_open_still_rounds", lambda session, board: {5: "round-1"})
    monkeypatch.setattr(stages, "_paid_redo_rounds", lambda session, board: {5: 4})

    def accountant(*_args, **_kwargs):
        raise SceneRedoRefused(status, ACCOUNTANT_REFUSED)

    monkeypatch.setattr(repurchase_gate, "before_paid_redo", accountant)
    repairs = [{"scene_index": 5, "redo": "motion", "reason": "clipul se deformează"}]
    registry, model = director_says(studio, answer(verdicts_for(film), "REPAIR", repairs))
    redo = FakeRedoPath(engine, monkeypatch, still_status="PAID")
    _production(engine)

    done = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert redo.calls == []
    assert done["outcome"] == "NOTHING_DONE" and done["passed_asset"] is None
    assert len(model.asked) == 2  # read again, knowing why
    decided = events(engine, DECISION_EVENT)[-1].payload
    assert decided["done"]["refused"][0]["status"] == status
    assert events(engine, stages.SHIPPED_UNDER_CAP_EVENT) == []
    assert stages.repair_stopped_by_caps(engine, settings, film["board"], decided["done"]) is None
    # The motion's renders spent (three of three): the stop is the cap's, whoever refused.
    _renders(engine, film["board"], 5, "motion", 2)
    assert stages.repair_stopped_by_caps(engine, settings, film["board"], decided["done"]) == {
        "capped": [5],
        "by_renders": [5],
        "impossible": [],
    }


# ---------------------------------------------------------------- what is NOT this case


def test_a_repair_refused_only_for_money_keeps_todays_path(engine, settings, studio, monkeypatch):
    from app.runbook import stages

    film = failed_film(engine, local_move=False)
    repairs = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    registry, _model = director_says(studio, answer(verdicts_for(film), "REPAIR", repairs))
    over = SceneRedoRefused("OVER_DAILY_BUDGET", "Bugetul zilei nu ajunge pentru refacere.")
    redo = FakeRedoPath(engine, monkeypatch, refuse={("still", 5): over})
    _production(engine)

    done = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert redo.calls == []
    assert done["outcome"] == "NOTHING_DONE" and done["passed_asset"] is None
    decisions = [event.payload for event in events(engine, DECISION_EVENT)]
    assert decisions and all(item["outcome"] == "NOTHING_DONE" for item in decisions)
    assert decisions[-1]["done"]["refused"][0]["status"] == "OVER_DAILY_BUDGET"
    assert not decisions[-1]["done"].get("developer_note")
    assert events(engine, stages.SHIPPED_UNDER_CAP_EVENT) == []
    assert events(engine, WAITING_EVENT)  # it waits, as it did
    with Session(engine) as session:
        assert (
            session.scalar(
                select(QualityControlReport).where(QualityControlReport.status == "PASSED")
            )
            is None
        )


def test_a_repair_that_can_be_done_is_carried_out_as_before(engine, settings, studio, monkeypatch):
    from app.runbook import stages

    film = failed_film(engine, local_move=False)
    repairs = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    registry, _model = director_says(studio, answer(verdicts_for(film), "REPAIR", repairs))
    redo = FakeRedoPath(engine, monkeypatch)
    _production(engine)

    done = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert redo.calls == [("still", 5, True), ("motion", 5, True)]
    assert done["outcome"] == "REPAIRED"
    (repair,) = done["repairs"]
    assert done["passed_asset"] == repair["new_asset"]
    assert events(engine, stages.SHIPPED_UNDER_CAP_EVENT) == []


def _carried_out_as(monkeypatch, status: str) -> None:
    """The carry-out meets her list stopped ``status`` where her reading's context let it
    through (his final approval written between her reading and the carry-out; a label the
    context read otherwise): her reading's own schema refuses these up front, so only such a
    disagreement brings them to the walk."""
    from app.runbook import stages

    def carried(engine_, settings_, vault, registry_, reading, listed, **_kwargs):
        return {
            "report_id": reading["report_id"],
            "storyboard_id": reading["storyboard_id"],
            "of_asset": reading["media_asset_id"],
            "new_asset": None,
            "listed": listed,
            "applied": [],
            "bought": [],
            "asked": [],
            "refused": [],
            "limited": [],
            "skipped": [{**item, "status": status, "reason": "r"} for item in listed],
            "waiting": [],
            "replaced_his": [],
            "overturned": [],
            "made": [],
            "requalified": None,
        }

    monkeypatch.setattr(stages, "_director_repairs", carried)


def test_his_final_take_ships_the_film_only_after_she_read_the_report_again_knowing_it(
    engine, settings, studio, monkeypatch
):
    """A redo that cannot be made at all (a take the Owner approved as final) ships the film
    with what it has only when her reading again, knowing why, asks it once more; her first
    reading never ships it (the review of 2026-10-17)."""
    from app.runbook import stages

    film = failed_film(engine, local_move=False)
    repairs = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    registry, model = director_says(studio, answer(verdicts_for(film), "REPAIR", repairs))
    redo = FakeRedoPath(engine, monkeypatch)
    _carried_out_as(monkeypatch, "OWNER_APPROVED")
    _production(engine)
    letters_before = _owner_letters(engine)

    done = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert redo.calls == []
    assert len(model.asked) == 2
    decisions = [event.payload for event in events(engine, DECISION_EVENT)]
    assert [item["outcome"] for item in decisions] == ["NOTHING_DONE", "ACCEPTED"]
    assert decisions[0]["done"]["skipped"][0]["status"] == "OWNER_APPROVED"
    assert done["outcome"] == "ACCEPTED" and done["passed_asset"] == film["asset"]
    assert stages.SHIPPED_IMPOSSIBLE_RO in decisions[-1]["summary"].lower()
    assert decisions[-1]["shipped_under_cap"]["impossible"] == [5]
    assert _owner_letters(engine) == letters_before
    nothing_bought(engine)


@pytest.mark.parametrize(
    "case", ["in_flight", "not_takes", "NOT_A_CARD", "OWNER_CHOICE", "UNKNOWN"]
)
def test_a_redo_stopped_for_the_moment_or_by_her_own_label_is_read_again_never_shipped(
    engine, settings, studio, monkeypatch, case
):
    """The review of 2026-10-17: a plan with nothing to buy because its still is still at the
    vendor, a film not cut from takes, her card redo of a filmed scene, her motion for his
    LOCAL_MOVE scene (a still and a rejoin remain), a kind the redo path does not know: none is
    impossible by construction. She reads the report again knowing why; the film is not
    published with its defect."""
    from app.runbook import stages

    film = failed_film(engine, local_move=False)
    repairs = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    registry, model = director_says(studio, answer(verdicts_for(film), "REPAIR", repairs))
    redo = FakeRedoPath(engine, monkeypatch)
    if case == "in_flight":

        def in_flight(*_args, **_kwargs):
            return {"buyable": False, "reason_ro": "Imaginea cerută este încă la furnizor."}

        monkeypatch.setattr("app.media.assembler.redo_plan", in_flight)
    elif case == "not_takes":
        with Session(engine) as session, session.begin():
            job = session.scalar(
                select(VideoRenderJob).where(VideoRenderJob.output_asset_id == film["asset"])
            )
            job.production_json = {**job.production_json, "image": {"provider": "LEGACY"}}
    else:
        _carried_out_as(monkeypatch, case)
    _production(engine)

    done = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert redo.calls == []
    assert done["outcome"] == "NOTHING_DONE" and done["passed_asset"] is None
    assert len(model.asked) == 2
    decisions = [event.payload for event in events(engine, DECISION_EVENT)]
    assert [item["outcome"] for item in decisions] == ["NOTHING_DONE", "NOTHING_DONE"]
    assert events(engine, stages.SHIPPED_UNDER_CAP_EVENT) == []
    with Session(engine) as session:
        assert (
            session.scalar(
                select(QualityControlReport).where(QualityControlReport.status == "PASSED")
            )
            is None
        )


def test_a_verdict_that_is_not_hers_is_never_published_under_the_cap(
    engine, settings, studio, monkeypatch
):
    """The review of 2026-10-17: her ACCEPT of a finding that is not hers (rights, claims,
    placeholder pictures, the production path, the file) is refused, and so is the cap's. The
    film waits for him or the sources, final: no PASSED report, nothing published, and she is
    not asked again only to meet the cap once more."""
    from app.media import blocker_repair
    from app.runbook import stages

    film = failed_film(
        engine,
        local_move=False,
        extra_failures=["Invalid license status: UNKNOWN"],
        extra_checks={"rights_qc": {"passed": False, "license_status": "UNKNOWN"}},
    )
    _renders(engine, film["board"], 5, "still", 3)
    repairs = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    registry, model = director_says(studio, answer(verdicts_for(film), "REPAIR", repairs))
    redo = FakeRedoPath(engine, monkeypatch)
    _production(engine)

    done = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert redo.calls == []
    assert done["outcome"] == "ACCEPT_REFUSED" and done["passed_asset"] is None
    assert len(model.asked) == 1
    (decided,) = [event.payload for event in events(engine, DECISION_EVENT)]
    assert decided["outcome"] == "ACCEPT_REFUSED" and decided["final"] is True
    assert decided["held_under_cap"]["how"] == "NOT_HERS"
    assert "nu se publică" in decided["summary"]
    assert events(engine, stages.SHIPPED_UNDER_CAP_EVENT) == []
    with Session(engine) as session:
        statuses = session.scalars(
            select(QualityControlReport.status).where(
                QualityControlReport.media_asset_id == film["asset"]
            )
        ).all()
    assert statuses == ["FAILED"]
    nothing_bought(engine)
    # Her stored REPAIR stopped by the cap with such a verdict publishes nothing either, and its
    # sheet is still the sheet of a film that does not go out.
    stored = {
        "report_id": film["report"],
        "storyboard_id": film["board"],
        "decision": "REPAIR",
        "outcome": "NOTHING_DONE",
        "verdicts": decided["verdicts"],
        "done": {"limited": [{"scene_index": 5}]},
    }
    assert stages.stored_repair_ships_under_cap(engine, settings, stored) is None
    assert stages.stored_repair_ships_under_cap(engine, settings, {**stored, "verdicts": []})
    assert not blocker_repair.film_settled_for_publication(engine, film["board"], settings)


# ------------------------------------------------------------------- the loop guard


def test_a_prompt_blocker_below_the_cap_that_repeats_is_a_tool_defect_and_never_loops(
    engine, settings, studio, monkeypatch
):
    """The same lasting stop on three WALKS in a row (not three decisions: one walk writes two)
    is a tool's defect for the developer, and the pass stops asking her — for a day."""
    from app.agents.director import DEVELOPER_DEFECT_KIND
    from app.runbook import stages
    from app.workflows.passes.director_qc_review import _developer_waits

    film = failed_film(engine, local_move=False)
    repairs = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    registry, _model = director_says(studio, answer(verdicts_for(film), "REPAIR", repairs))
    lint = SceneRedoRefused("LINT_BLOCKED", "Prompturile au 3 blocaje și 21 de avertismente.")
    redo = FakeRedoPath(engine, monkeypatch, refuse={("still", 5): lint})
    _production(engine)
    letters_before = _owner_letters(engine)

    def walk(hours: float) -> dict[str, Any]:
        _clock(monkeypatch, hours)
        return stages.director_decides_failed_film(
            engine, settings, None, registry, film["report"], film["asset"]
        )

    # Two walks an hour apart, two readings each: the same stop four times, two walks.
    assert walk(0)["outcome"] == "NOTHING_DONE"
    assert walk(1)["outcome"] == "NOTHING_DONE"
    decisions = [event.payload for event in events(engine, DECISION_EVENT)]
    assert len(decisions) == 4 and not any(d["done"].get("developer_note") for d in decisions)

    third = walk(2)

    assert redo.calls == []
    assert third["outcome"] == "NOTHING_DONE"
    decisions = [event.payload for event in events(engine, DECISION_EVENT)]
    assert len(decisions) == 5  # the defect ends the third walk's second reading
    note_id = decisions[-1]["done"]["developer_note"]
    with Session(engine) as session:
        note = session.get(AgentMessage, note_id)
        assert note.body_json["kind"] == DEVELOPER_DEFECT_KIND
        assert note.body_json["defect"] == stages.IMPOSSIBLE_DEFECT
        assert note.body_json["report_id"] == film["report"]
        assert note.body_json["walks"] == 3
        assert note.status == "RESOLVED" and not is_for_owner(note)
        assert _developer_waits(session, film["report"])
    assert _owner_letters(engine) == letters_before
    assert events(engine, stages.SHIPPED_UNDER_CAP_EVENT) == []
    # The pass does not ask her again about this report while the note holds.
    assert _pass(engine, settings) == {"queued": []}
    # A day later she is asked again; the same stop writes a new note at once.
    with Session(engine) as session, session.begin():
        session.get(AgentMessage, note_id).created_at = (
            datetime.now(UTC) - timedelta(hours=stages.IMPOSSIBLE_NOTE_HOURS + 1)
        ).isoformat()
    with Session(engine) as session:
        assert not _developer_waits(session, film["report"])
    later = walk(stages.IMPOSSIBLE_NOTE_HOURS + 3)
    assert later["outcome"] == "NOTHING_DONE"
    renewed = events(engine, DECISION_EVENT)[-1].payload["done"]["developer_note"]
    assert renewed and renewed != note_id


def test_a_stop_of_the_moment_never_makes_the_defect(engine, settings, studio, monkeypatch):
    """The review of 2026-10-17: 928af1a7's PROMPT_NOT_CORRECTED of 13 October (a token limit,
    «Agent already has an active task», a rewrite that did not treat the finding) and a film's
    lease held are of the moment; walk after walk they write no developer's note."""
    from app.runbook import stages

    film = failed_film(engine, local_move=False)
    repairs = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    registry, _model = director_says(studio, answer(verdicts_for(film), "REPAIR", repairs))
    busy = SceneRedoRefused("FILM_BUSY", "Altcineva cumpără acum pentru film.")
    FakeRedoPath(engine, monkeypatch, refuse={("still", 5): busy})
    _production(engine)
    for hours in (0, 1, 2, 3):
        _clock(monkeypatch, hours)
        stages.director_decides_failed_film(
            engine, settings, None, registry, film["report"], film["asset"]
        )
    decisions = [event.payload for event in events(engine, DECISION_EVENT)]
    assert len(decisions) == 8
    assert not any(item["done"].get("developer_note") for item in decisions)

    def refused(status: str, redo: str = "motion") -> dict[str, Any]:
        return {"refused": [{"scene_index": 4, "redo": redo, "status": status, "reason": "r"}]}

    for status in (
        "PROMPT_NOT_CORRECTED",
        "FILM_BUSY",
        "NOT_BOUGHT",
        "NOT_DELIVERED",
        "REPURCHASE_UNDECIDED",
        "NOTHING_TO_BUY",
        "OVER_DAILY_BUDGET",
        "",
    ):
        assert stages._impossibility_key(refused(status)) is None, status
    assert stages._impossibility_key(refused("LINT_BLOCKED")) == (("4", "motion", "LINT_BLOCKED"),)
    # A lasting stop beside one of the moment: not the same impossibility yet.
    mixed = {"refused": [*refused("LINT_BLOCKED")["refused"], *refused("FILM_BUSY")["refused"]]}
    assert stages._impossibility_key(mixed) is None


def test_what_stopped_her_list_decides_whether_it_ships(engine, settings):
    """The classification, on the repair's own record."""
    from app.runbook import stages

    film = failed_film(engine, local_move=False)
    board = film["board"]
    _renders(engine, board, 4, "still", 3)

    def refused(scene: int, status: str) -> dict[str, Any]:
        return {"refused": [{"scene_index": scene, "status": status, "reason": "r"}]}

    # At the renders cap, whatever refused it first (the Accountant, the lint).
    for status in ("REPURCHASE_REFUSED", "LINT_BLOCKED", "PROMPT_NOT_CORRECTED"):
        stopped = stages.repair_stopped_by_caps(engine, settings, board, refused(4, status))
        assert stopped == {"capped": [4], "by_renders": [4], "impossible": []}, status
    # Below the cap: a prompt blocker is the ladder's, the Accountant's or her silence hers,
    # money the budget's.
    for status in ("LINT_BLOCKED", "REPURCHASE_REFUSED", "REPURCHASE_UNDECIDED"):
        assert stages.repair_stopped_by_caps(engine, settings, board, refused(5, status)) is None
    # The cap is the layer's: a motion with renders left is not stopped by its still's cap.
    motion = {"refused": [{"scene_index": 4, "redo": "motion", "status": "LINT_BLOCKED"}]}
    assert stages.repair_stopped_by_caps(engine, settings, board, motion) is None
    for money in ("OVER_DAILY_BUDGET", "OVER_FILM_BUDGET", "LOW_BALANCE"):
        assert stages.repair_stopped_by_caps(engine, settings, board, refused(4, money)) is None
    # Impossible by construction: his final take only.
    skipped = {"skipped": [{"scene_index": 3, "status": "OWNER_APPROVED", "reason": "r"}]}
    assert stages.repair_stopped_by_caps(engine, settings, board, skipped) == {
        "capped": [],
        "by_renders": [],
        "impossible": [3],
    }
    # Hers to read again, or of the moment: not impossible.
    for status in ("NOT_A_CARD", "OWNER_CHOICE", "UNKNOWN", "NOTHING_TO_BUY", "NOT_TAKES"):
        mislabel = {"skipped": [{"scene_index": 3, "status": status, "reason": "r"}]}
        assert stages.repair_stopped_by_caps(engine, settings, board, mislabel) is None, status
    # Something bought, asked or waiting is never this.
    assert (
        stages.repair_stopped_by_caps(
            engine, settings, board, {**refused(4, "LINT_BLOCKED"), "bought": [{"redo": "x"}]}
        )
        is None
    )
    waiting = {"waiting": [{"scene_index": 4, "kind": "still"}], **refused(4, "LINT_BLOCKED")}
    assert stages.repair_stopped_by_caps(engine, settings, board, waiting) is None


# -------------------------------------------------------- rejoined free from the kept takes


def _settles_and_rejoins(monkeypatch, stages) -> list[dict[str, Any]]:
    """The film's other scenes stand on its takes; settling scene 5 changes its takes, so the
    film no longer stands on them and is rejoined (`_reencode_from_takes`, faked by
    FakeRedoPath, asked free only)."""
    calls: list[dict[str, Any]] = []

    def stand(engine, storyboard_id, production, *, only=None, skip=None):
        calls.append({"only": only, "skip": skip})
        return only is None

    monkeypatch.setattr(stages, "_scenes_stand", stand)
    monkeypatch.setattr(stages, "_settle_capped", lambda *a, **k: [5])
    return calls


@pytest.mark.parametrize("verdict", ["FAILED", "PASSED"])
def test_a_capped_scene_settled_into_other_takes_rejoins_the_film_free_and_it_ships(
    engine, settings, studio, monkeypatch, verdict
):
    from app.runbook import stages

    film = failed_film(engine, local_move=False)
    _renders(engine, film["board"], 5, "still", 3)
    repairs = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    registry, _model = director_says(studio, answer(verdicts_for(film), "REPAIR", repairs))
    redo = FakeRedoPath(engine, monkeypatch, verdict=verdict)
    asked_free: list[bool] = []
    rejoin = redo.rejoin

    def free_rejoin(*args, **kwargs):
        asked_free.append(bool(kwargs.get("free_only")))
        return rejoin(*args, **kwargs)

    monkeypatch.setattr(stages, "_reencode_from_takes", free_rejoin)
    stood = _settles_and_rejoins(monkeypatch, stages)
    _production(engine)
    letters_before = _owner_letters(engine)

    done = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert redo.calls == [("rejoin", None, False)] and asked_free == [True]
    assert stood == [{"only": None, "skip": {5}}, {"only": {5}, "skip": None}]
    (new_asset,) = redo.measured
    assert done["passed_asset"] == new_asset
    (shipped,) = events(engine, stages.SHIPPED_UNDER_CAP_EVENT)
    assert shipped.payload["rebuilt"] is True and shipped.payload["settled"] == [5]
    assert shipped.payload["new_asset"] == new_asset
    decisions = {e.payload["report_id"]: e.payload for e in events(engine, DECISION_EVENT)}
    old = decisions[film["report"]]
    assert old["outcome"] == "REPAIRED" and old["final"] is True
    assert old["done"]["new_asset"] == new_asset
    with Session(engine) as session:
        report = session.scalar(
            select(QualityControlReport)
            .where(
                QualityControlReport.media_asset_id == new_asset,
                QualityControlReport.status == "PASSED",
            )
            .limit(1)
        )
        assert report is not None
    if verdict == "FAILED":
        assert done["outcome"] == "ACCEPTED"
        (new,) = [item for key, item in decisions.items() if key != film["report"]]
        assert new["decision"] == "ACCEPT" and new["outcome"] == "ACCEPTED"
        assert new["media_asset_id"] == new_asset and new["of_report"] == film["report"]
        assert SHIPPED in new["summary"].lower()
    else:
        assert done["outcome"] == "REPAIRED"
    assert _owner_letters(engine) == letters_before
    nothing_bought(engine)


def _rejoin_fakes(monkeypatch, assembled: list[tuple[int, bool]]) -> None:
    """`_reencode_from_takes` with the sheet, its plan and the assembly faked: the plan's
    narration is f06808c9's reservation figure (769 characters at 0.22 USD per 1k)."""
    from app.runbook import stages

    monkeypatch.setattr(stages, "sheet_wiring", lambda *a, **k: {})
    monkeypatch.setattr("app.media.factory.reference_image_adapter", lambda *a, **k: None)
    monkeypatch.setattr(
        "app.media.shooting_sheet.build_sheet", lambda *a, **k: {"footer": {}, "sheet_hash": "h"}
    )
    monkeypatch.setattr(
        stages,
        "estimate_film_cost_micros",
        lambda *a, **k: {"narration_usd_micros": 169_180, "caveat": ""},
    )

    def assemble(engine_, settings_, vault, storyboard_id, wiring, env, plan_cost, corr, **kw):
        assembled.append((int(plan_cost["narration_usd_micros"]), bool(kw.get("free"))))
        return {"status": "ASSEMBLED", "asset_id": f"film-{len(assembled)}"}

    monkeypatch.setattr(stages, "_assemble_from_takes", assemble)


def test_the_free_rejoin_refuses_only_narration_still_left_to_voice(engine, settings, monkeypatch):
    """The review of 2026-10-17: the free rejoin read the plan's narration figure, the
    reservation for the whole voiceover at the dearest price (f06808c9: 0.169 USD for 769
    characters already voiced), so every narrated film was refused its rejoin and published as
    it was, her words saying it «would buy new narration». Only what no narration take holds
    refuses it now, said in characters; the day's own rejoin is as it was."""
    from app.runbook import stages

    assembled: list[tuple[int, bool]] = []
    _rejoin_fakes(monkeypatch, assembled)
    left = {"characters": 0}
    monkeypatch.setattr(stages, "_narration_left_to_voice", lambda *a: left["characters"])

    def rejoin(free_only: bool) -> dict[str, Any]:
        result: dict[str, Any] = {"applied": [], "made": [], "new_asset": None, "refused": []}
        stages._reencode_from_takes(
            engine, settings, None, "board", result, "c", redo="rejoin", free_only=free_only
        )
        return result

    voiced = rejoin(True)
    assert voiced["new_asset"] == "film-1" and voiced["refused"] == []
    assert assembled == [(0, True)]  # nothing voiced anew: nothing held

    left["characters"] = 120
    unvoiced = rejoin(True)
    assert unvoiced["new_asset"] is None and assembled == [(0, True)]
    (refused,) = unvoiced["refused"]
    assert "120 caractere" in refused["reason"] and "USD" not in refused["reason"]

    day = rejoin(False)
    assert day["new_asset"] == "film-2" and assembled[-1] == (169_180, False)


def test_the_narration_left_is_read_with_the_assemblys_own_voices(engine, monkeypatch):
    from app.runbook import stages

    def per_scene(scene):
        return "voice-of-scene"

    def segments(scene):
        return None

    monkeypatch.setattr(
        "app.media.factory.render_plan",
        lambda engine_, vault, board: {
            "tts_for_scene": per_scene,
            "voice_segments_for_scene": segments,
        },
    )
    monkeypatch.setattr("app.media.factory.tts_provider", lambda engine_, vault: "the-voice")
    asked: list[dict[str, Any]] = []

    def to_buy(engine_, board, **kwargs):
        asked.append({"board": board, **kwargs})
        return 0

    monkeypatch.setattr("app.media.assembler.narration_to_buy", to_buy)

    assert stages._narration_left_to_voice(engine, None, "board") == 0
    assert asked == [
        {
            "board": "board",
            "tts_adapter": "the-voice",
            "tts_adapter_for_scene": per_scene,
            "voice_segments_for_scene": segments,
        }
    ]


def test_a_rejoin_that_voices_nothing_holds_nothing_and_writes_no_budget_letter(
    engine, settings, monkeypatch
):
    from app.runbook import stages

    def never(*_a, **_k):
        pytest.fail("a rejoin that voices nothing reserves nothing and writes no budget letter")

    monkeypatch.setattr(stages, "reserve_spend", never)
    monkeypatch.setattr("app.economy.accountant.budget_refusal_letter", never)
    monkeypatch.setattr(stages, "mode_refusal", lambda *a, **k: None)
    monkeypatch.setattr("app.media.factory.render_plan", lambda *a, **k: {})
    monkeypatch.setattr("app.media.factory.tts_provider", lambda *a, **k: None)
    monkeypatch.setattr(
        "app.media.assembler.assemble_from_takes",
        lambda *a, **k: {"job_id": "job", "output_asset_id": "film"},
    )
    monkeypatch.setattr(
        "app.economy.accountant.record_render_costs", lambda *a, **k: {"recorded": 0}
    )

    made = stages._assemble_from_takes(
        engine,
        settings,
        None,
        "board",
        {},
        "PRODUCTION",
        {"narration_usd_micros": 0},
        "c",
        free=True,
    )

    assert made["status"] == "ASSEMBLED" and made["asset_id"] == "film"


# --------------------------------------------------- the sheet of a film that goes out as is


@pytest.fixture
def nepal(engine, tmp_path, monkeypatch):
    from app.factual import story_review
    from app.media import blocker_repair as repair
    from test_shooting_sheet import nepal_film

    monkeypatch.setattr(repair, "repair_story", lambda *a, **kw: None)
    monkeypatch.setattr(story_review, "story_gate", lambda *a: (True, ""))
    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.autonomy_stopped = False
        policy.autonomy_mode = "AUTONOMOUS_CEO"
    return nepal_film(engine, tmp_path)


def _rendered(engine, board: str, status: str) -> dict[str, str]:
    ids = {"asset": str(uuid4()), "report": str(uuid4())}
    now = utc_now()
    with Session(engine) as session, session.begin():
        session.add(
            MediaAsset(
                id=ids["asset"],
                asset_type="RENDERED_VIDEO",
                uri_or_path=f"storage/{ids['asset']}.mp4",
                file_size_bytes=10,
                mime_type="video/mp4",
                width=1080,
                height=1920,
                duration_seconds=25.0,
                provider_name="SCENE_TAKES",
                license_status="PROPRIETARY_STUDIO",
                provenance_hash="0" * 64,
                created_at=now,
            )
        )
        session.flush()
        session.add(
            VideoRenderJob(
                id=str(uuid4()),
                storyboard_id=board,
                status="COMPLETED",
                output_asset_id=ids["asset"],
                started_at=now,
                finished_at=now,
                production_json={"image": {"provider": "SCENE_TAKES"}, "scenes": []},
            )
        )
        session.flush()
        session.add(
            QualityControlReport(
                id=ids["report"],
                media_asset_id=ids["asset"],
                status=status,
                score=1.0 if status == "PASSED" else 0.0,
                checks_json={},
                failure_reasons_json=[] if status == "PASSED" else ["Scena 1: x"],
                verified_at=now,
            )
        )
    return ids


def test_a_queued_sheet_repair_of_a_film_going_out_as_it_is_is_withdrawn_without_a_model(
    engine, nepal, monkeypatch
):
    from app.media import blocker_repair as repair
    from test_sheet_blocker_repair import sheet

    queued = repair.submit_sheet_issues(engine, sheet(engine, nepal))
    with Session(engine) as session:
        task = session.get(TaskQueueItem, queued["task_id"])
        payload = dict(task.payload)
    assert not repair.film_settled_for_publication(engine, nepal)
    _rendered(engine, nepal, "PASSED")
    assert repair.film_settled_for_publication(engine, nepal)

    def no_model(*_a, **_k):
        pytest.fail("a film going out as it is gets no sheet repair")

    monkeypatch.setattr(repair, "director_assignment", no_model)
    monkeypatch.setattr(repair, "write_shot_prompts", no_model)

    result = repair.process_sheet_repair(engine, object(), payload, correlation_id="t")

    assert result["status"] == "STALE" and result["reason"] == repair.SETTLED_FILM_NOTE
    with Session(engine) as session:
        report = session.get(AgentMessage, payload["message_id"])
        assert report.status != "OPEN"
    # Nothing new is queued or built for its sheet.
    assert repair.submit_sheet_issues(engine, sheet(engine, nepal))["status"] == "FILM_SETTLED"
    built: list[str] = []
    monkeypatch.setattr(repair, "build_sheet", lambda engine_, identifier, **k: built.append(1))
    assert repair.scan_sheet_issues(engine)["reported"] == []
    assert built == []


def test_a_failed_film_whose_repair_only_the_caps_stopped_gets_no_sheet_repair(
    engine, nepal, settings
):
    from app.media import blocker_repair as repair

    film = _rendered(engine, nepal, "FAILED")
    assert not repair.film_settled_for_publication(engine, nepal, settings)
    _renders(engine, nepal, 1, "motion", 3)
    record_decision(
        engine,
        {
            "report_id": film["report"],
            "media_asset_id": film["asset"],
            "storyboard_id": nepal,
            "decided_by": "Director",
            "decision": "REPAIR",
            "summary": "s",
            "verdicts": [],
            "repairs": [],
            "outcome": "NOTHING_DONE",
            "final": False,
            "done": {
                "refused": [
                    {"scene_index": 1, "status": "REPURCHASE_REFUSED", "reason": ACCOUNTANT_REFUSED}
                ]
            },
        },
        "c",
    )
    assert repair.film_settled_for_publication(engine, nepal, settings)
    withdrawn = repair.withdraw_sheet_repairs(engine, nepal, "se publică")
    assert withdrawn == []  # nothing was open for it


@pytest.mark.parametrize(
    "hard_check",
    ["rights_qc", "factual_qc", "content_source_qc", "production_path_qc", "music_license"],
)
def test_new_rejoined_film_never_waives_hard_qc(engine, settings, studio, monkeypatch, hard_check):
    from app.runbook import stages

    film = failed_film(engine, local_move=False)
    _renders(engine, film["board"], 5, "still", 3)
    repairs = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    registry, _model = director_says(studio, answer(verdicts_for(film), "REPAIR", repairs))
    redo = FakeRedoPath(
        engine, monkeypatch, verdict="FAILED", checks={hard_check: {"passed": False}}
    )
    if hard_check == "music_license":
        qc = redo.qc

        def unlicensed(*args, **kwargs):
            result = qc(*args, **kwargs)
            with Session(engine) as session, session.begin():
                report = session.get(QualityControlReport, result["id"])
                report.failure_reasons_json = [
                    "Piesa „unknown” nu este în biblioteca de muzică a Proprietarului"
                ]
            return result

        monkeypatch.setattr(stages, "evaluate_media_qc", unlicensed)
    _settles_and_rejoins(monkeypatch, stages)
    _production(engine)

    done = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )
    assert done["outcome"] == "ACCEPT_REFUSED"
    assert not done.get("passed_asset")
    assert not events(engine, stages.SHIPPED_UNDER_CAP_EVENT)
    assert redo.measured
    with Session(engine) as session:
        assert not session.scalar(
            select(QualityControlReport.id).where(
                QualityControlReport.media_asset_id == redo.measured[-1],
                QualityControlReport.status == "PASSED",
            )
        )
    nothing_bought(engine)


def test_stored_cap_classification_uses_spent_motion(engine, settings, monkeypatch):
    from app.runbook import stages

    film = failed_film(engine, local_move=False)
    monkeypatch.setattr(stages, "motion_spent", lambda session, board, scene, config: scene == 5)
    done = stages.repair_stopped_by_caps(
        engine,
        settings,
        film["board"],
        {
            "refused": [{"scene_index": 5, "redo": "motion", "status": "LINT_BLOCKED"}],
        },
    )
    assert done == {"capped": [5], "by_renders": [5], "impossible": []}
