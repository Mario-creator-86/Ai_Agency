"""A montage day's money: a paid step holds its next round, not three times every row.

2026-10-16. The montage cut a 160 s short into about 40 rows and an episode into about 37, and
the stills step still held its whole cap at its start: every row's still three times over,
plus every GPU start three times. A 37-row episode's stills held 10,83 USD of the Owner's 20
while their first round cost 3,61, so once the short had spent about 9,5 USD the episode was
refused OVER_DAILY_BUDGET before its first still; the day's goal pass then queued six more runs
that met the same refusal and wrote him «6 rulări» for what was his budget.

Now (`shooting_sheet.StepHold`) a step holds its first round with its GPU starts, grows the
same reservation before every later round within what the budgets have left
(`economy.budget.extend_reservation`), never past the step's cap, and a round the budget cannot
hold ends the step on the budget's words, which the day reads as OVER_DAILY_BUDGET. The day's
goal pass reads a refused round as the budget spent. The preflight prices a montage day.

Every provider is faked: the RunPod cloud of test_runpod_batch, a spy image adapter, a fake
GPU session; prices are the studio's RunPod estimates (Qwen-Image-Edit 9 credits a still,
LTX-2.5 at 24 GPU-seconds a video second, 14 credits a GPU start, 1 credit = 0,01 USD).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from app.economy.budget import BudgetCommand, reserve_spend, set_budget
from app.economy.models import ProviderCostRecord, SpendReservation
from app.media import assembler, cost_plan, shooting_sheet, stills_stage
from app.media.assembler import SpendMeter
from app.media.cost_plan import ESTIMATED, PriceRow, load_price_table
from app.media.models import Storyboard, StoryboardScene
from app.media.shooting_sheet import (
    PurchaseGateRefused,
    build_sheet,
    hold_step_budget,
    run_sheet_step,
)
from app.models import DomainEvent, OwnerPolicy
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_runpod_batch import Cloud, adapter, finishing, price, request
from test_scene_takes import nepal_like
from test_stills_stage import LOOK, SUBJECTS, TAIL, SpyStills

pytestmark = pytest.mark.montage

#: A 160 s short cut into shots of about 4 s.
ROWS = 40
#: Qwen-Image-Edit-2511 at 75 GPU-seconds and 4,00 USD an hour, rounded up to whole credits.
STILL_CREDITS = 9.0
#: LTX-2.5 at 24 GPU-seconds a video second: a 5 s clip is 14 credits.
VIDEO_CREDITS_PER_SECOND = 24 * 4.0 / 3600 / 0.01
#: One GPU start (cold start + idle tail) a round.
START_CREDITS = 14.0


def runpod_prices(stills_model: str = "seedream5_pro") -> Any:
    """The published table with the studio's RunPod estimates laid over it, as
    `providers.runpod.pricing.estimated_prices` lays them for a serverless connection."""
    table = load_price_table()
    rows = [row for row in table.rows if row.model_id not in (stills_model, "LTX-2.5")]
    rows += [
        PriceRow(
            model_id=stills_model,
            kind="image",
            resolution="*",
            source_url="RunPod estimate (test)",
            date="2026-10-16",
            provenance=ESTIMATED,
            credits_per_image=STILL_CREDITS,
        ),
        PriceRow(
            model_id="LTX-2.5",
            kind="video",
            resolution="*",
            source_url="RunPod estimate (test)",
            date="2026-10-16",
            provenance=ESTIMATED,
            credits_per_second=VIDEO_CREDITS_PER_SECOND,
        ),
    ]
    return replace(
        table,
        rows=tuple(rows),
        seconds={**table.seconds, "LTX-2.5": {"min": 1, "max": 10}},
        stills_model=stills_model,
        overhead_credits_per_round={"image": START_CREDITS, "video": START_CREDITS},
        round_models=frozenset({stills_model, "LTX-2.5"}),
    )


@pytest.fixture
def one_still(monkeypatch):
    """Production buys one still a row (2026-10-15); the suite was written on two."""
    for module in (cost_plan, stills_stage, shooting_sheet, assembler):
        monkeypatch.setattr(module, "STILL_CANDIDATES", 1)


def a_spend(engine, usd: float) -> None:
    """What the day's first film already cost, in the books today."""
    with Session(engine) as session, session.begin():
        session.add(
            ProviderCostRecord(
                id=str(uuid4()),
                provider="runpod",
                external_reference=f"test:{uuid4()}",
                status="ESTIMATED",
                amount_micros=int(usd * 1_000_000),
                currency="USD",
                usd_micros=int(usd * 1_000_000),
                attribution_json={"storyboard_id": "the-short"},
                recorded_at=utc_now(),
            )
        )


def a_montage_film(engine, tmp_path, rows: int = ROWS) -> str:
    """A film cut into ``rows`` LIVE rows, each with its compiled still prompt."""
    plan = [
        (
            "LIVE",
            "HOOK" if n == 1 else "EVIDENCE",
            f"{LOOK} {SUBJECTS[(n - 1) % 4 + 1]} {TAIL}",
        )
        for n in range(1, rows + 1)
    ]
    storyboard_id = nepal_like(engine, tmp_path, kinds=plan)
    with Session(engine) as session, session.begin():
        session.get(Storyboard, storyboard_id).visual_bible_json = {
            "continuity_rules": ["No human faces appear"]
        }
        for row in session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
        ):
            words = str(row.visual_prompt)
            row.prompt_json = {
                "scene_kind": "LIVE",
                "source": "model",
                "still_prompt": words,
                "look_block": LOOK,
                "camera_move": "slow push-in",
            }
    return storyboard_id


def held(engine) -> list[SpendReservation]:
    with Session(engine) as session:
        rows = list(session.scalars(select(SpendReservation)))
        session.expunge_all()
        return rows


def mode_studio(engine) -> None:
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.autonomy_stopped = False
        policy.autonomy_mode = "AUTONOMOUS_CEO"
        policy.paid_media_approval = "MODE"


class Probe(Exception):
    """The stills stage stood in for: the test reads what the step held when it began."""


# --------------------------------------------------- 1. the second film's stills start


def test_a_40_row_films_stills_hold_fits_beside_the_first_films_spend(
    engine, tmp_path, monkeypatch, one_still
):
    film = a_montage_film(engine, tmp_path)
    mode_studio(engine)
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="20"))
    a_spend(engine, 9.5)  # the factual short, made first
    table = runpod_prices()
    images = SpyStills(balance=100_000)
    sheet = build_sheet(engine, film, table=table, stills_model=images.model, read_live=False)
    stills = sheet["steps"]["stills"]
    assert len(stills["to_buy"]) == ROWS
    # Its first round: every row's still and two GPU starts (scene 1, then the rest).
    first_round = ROWS * STILL_CREDITS + 2 * START_CREDITS
    assert stills["cost_credits"] == first_round == 388
    # The cap, with two re-rolls of everything: 11,64 USD, more than the 10,50 left today.
    assert stills["cap_credits"] == 3 * first_round
    seen: dict[str, Any] = {}

    def stage(_engine, storyboard_id, _correlation, **kwargs):
        hold = kwargs["budget_hold"]
        seen["held"] = hold.held_micros
        seen["reserved"] = sum(r.usd_micros for r in held(engine) if r.status == "RESERVED")
        # A re-roll round of four rows (four stills and a GPU start) grows the same hold.
        seen["room"] = hold.room(first_round, 4 * STILL_CREDITS + START_CREDITS, partial=True)
        raise Probe

    monkeypatch.setattr(shooting_sheet, "run_stills_stage", stage)

    with pytest.raises(Probe):
        run_sheet_step(
            engine,
            film,
            "stills",
            sheet["sheet_hash"],
            correlation_id=str(uuid4()),
            table=table,
            image_adapter=images,
            environment="TEST",
            unasked=False,
            storage_root=tmp_path / "media",
        )

    # The step held its first round (3,88 USD) beside the short's 9,50: 13,38 of 20.
    assert seen["held"] == 3_880_000
    assert seen["reserved"] == 3_880_000
    assert seen["room"] == pytest.approx(4 * STILL_CREDITS + START_CREDITS)
    # It bought nothing: its hold, grown for the re-roll, is let go whole.
    (hold,) = held(engine)
    assert hold.status == "RELEASED" and hold.usd_micros == 3_880_000 + 500_000


# --------------------------------------------------- 2. a re-roll round the day cannot hold


def a_step_hold(engine, *, cap_credits: float, first_credits: float) -> Any:
    """The stills step's hold as `_run_sheet_step` takes it: its first round, held."""
    from app.media.shooting_sheet import StepHold

    micros = int(first_credits * 10_000)
    reservation = hold_step_budget(
        engine,
        "film-1",
        "stills",
        micros,
        plan_hash="h",
        allow_over_budget=False,
        correlation_id=str(uuid4()),
        step_cap_usd_micros=int(cap_credits * 10_000),
    )
    return StepHold(
        engine=engine,
        storyboard_id="film-1",
        step="stills",
        cap_credits=cap_credits,
        credit_usd=0.01,
        correlation_id=str(uuid4()),
        reservation_id=reservation,
        held_micros=micros,
    )


def rounds_with_a_hold(engine, made, hold: Any, next_round, **kw) -> tuple[dict, Any]:
    """`gpu_batch.run_rounds` as the stills stage drives it: its ledger reads the hold."""
    from app.media.assembler import budget_cut
    from app.media.gpu_batch import run_rounds
    from app.providers.runpod.gpu_session import StepPermit

    ledger = stills_stage._Ledger(cap=int(hold.cap_credits), meter=SpendMeter(), hold=hold)
    summary = run_rounds(
        engine,
        made,
        permit=StepPermit(
            action="media.stills_purchase",
            step="stills",
            storyboard_id="film-1",
            plan_hash="h",
            requester="video_editor",
            approval_id=None,
            owner_press=True,
            correlation_id=str(uuid4()),
            integration_id=None,
        ),
        purpose="image",
        first_round=[request("1", 0), request("1", 1)],
        next_round=next_round,
        price_credits=price,
        cap_left=ledger.room,
        make_room=ledger.round_room,
        guard=None,
        stopped=lambda: None,
        on_submitted=lambda item: None,
        on_outcome=lambda outcome: None,
        meter=ledger.meter,
        sleep=lambda s: None,
        **kw,
    )
    budget_cut(summary, ledger.budget_words)
    return summary, ledger


@pytest.fixture
def gpu(monkeypatch):
    from contextlib import contextmanager

    from app.media import gpu_batch
    from test_runpod_batch import Session_

    @contextmanager
    def session(engine, adapter, *, purpose, permit):
        yield Session_()

    monkeypatch.setattr(gpu_batch, "gpu_session", session)
    monkeypatch.setattr(gpu_batch, "gpu_precheck", lambda *args, **kwargs: None)


def test_a_reroll_round_the_budget_cannot_hold_is_refused_cleanly_and_never_overspends(
    engine, tmp_path, gpu
):
    # 50 cents a day; another film holds 15. The step's first round (two stills and a GPU
    # start: 25 credits) is held; its re-roll round (25 more) finds 10 left.
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="0.50"))
    reserve_spend(engine, 150_000, "sheet:motion", "the-short")
    hold = a_step_hold(engine, cap_credits=75, first_credits=25)
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    made.core.transport = made.core.client.transport = finishing(cloud)
    asked: list[int] = []

    def next_round(outcomes):
        asked.append(len(outcomes))
        if len(asked) == 1:
            return [request("1", 0, attempt=2), request("1", 1, attempt=2)]
        return []

    summary, ledger = rounds_with_a_hold(engine, made, hold, next_round)

    # Round 1 bought; the re-roll round was asked for, and nothing of it was sent.
    assert len(cloud.posts()) == 1 and asked == [2]
    assert ledger.committed == 25.0
    # The hold grew by what the day had left (10 cents) and no further: 50 of 50, never more.
    mine = next(r for r in held(engine) if r.purpose == "sheet:stills")
    assert mine.usd_micros == 350_000
    reserved = sum(r.usd_micros for r in held(engine) if r.status == "RESERVED")
    assert reserved == 500_000
    # The step ends on the budget's words, not on the cap he approved.
    assert "Bugetul zilnic" in summary["stopped"]
    assert "runda următoare a pasului" in summary["stopped"]
    assert summary["cap_stop"] == summary["stopped"]
    assert hold.budget_stop() == {
        "status": "OVER_DAILY_BUDGET",
        "period": "DAILY",
        "reason": summary["stopped"],
    }
    with Session(engine) as session:
        refused = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "media.step_hold_refused")
        ).all()
    assert [event.payload["need_usd_micros"] for event in refused] == [250_000]


def test_the_hold_never_grows_past_the_steps_cap(engine, tmp_path, gpu):
    # The budget has room; the cap he approved (40 credits) leaves one re-roll still.
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="20"))
    hold = a_step_hold(engine, cap_credits=40, first_credits=25)
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    made.core.transport = made.core.client.transport = finishing(cloud)
    calls: list[int] = []

    def next_round(outcomes):
        calls.append(1)
        if len(calls) == 1:
            return [request("1", 0, attempt=2), request("1", 1, attempt=2)]
        return []

    summary, ledger = rounds_with_a_hold(engine, made, hold, next_round)

    assert [len(cloud.jobs[j]["input"]["items"]) for j in sorted(cloud.jobs)] == [2, 1]
    assert ledger.committed == 40.0
    (mine,) = held(engine)
    assert mine.usd_micros == 400_000  # the cap, and not a cent past it
    assert summary["cap_stop"].startswith("STOPPED_AT_CAP")
    assert hold.budget_stop() is None


def refused_events(engine) -> list[DomainEvent]:
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(DomainEvent).where(DomainEvent.event_type == "media.step_hold_refused")
            )
        )
        session.expunge_all()
        return rows


def test_a_round_runpod_measured_above_its_estimate_is_held_at_once(engine, tmp_path, gpu):
    """Review of 8f5c6ec: the hold stayed at the round's estimate after RunPod measured more,
    so a second film was told the money the step already owed was free."""
    from app.economy.budget import budget_status
    from test_runpod_money_adversary import timed

    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="1"))
    hold = a_step_hold(engine, cap_credits=75, first_credits=25)
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    # 400 s executing + the worker's start (the 200 s delay, at most the 120 s cold start
    # budgeted) + 1 s idle = 521 GPU-seconds = 52,1 credits, above the 25 estimated.
    made.core.transport = made.core.client.transport = timed(
        cloud, delay_ms=200_000, execution_ms=400_000
    )

    summary, ledger = rounds_with_a_hold(
        engine,
        made,
        hold,
        lambda outcomes: [],
        credits_for_seconds=lambda seconds: seconds * 0.1,
    )

    assert ledger.committed == pytest.approx(52.1)
    assert summary["stopped"] is None and summary["cap_stop"] is None
    # The hold grew to what RunPod used, beyond the round it was asked for.
    (mine,) = held(engine)
    assert mine.status == "RESERVED" and mine.usd_micros == 521_000
    (daily,) = budget_status(engine)["budgets"]
    assert daily["remaining_usd_micros"] == 479_000
    # A second film cannot take what the step owes: 0,75 USD is refused, what is left fits.
    other = reserve_spend(engine, 750_000, "sheet:stills", "the-episode")
    assert other["allowed"] is False
    assert reserve_spend(engine, 479_000, "sheet:stills", "the-episode")["allowed"] is True
    # Holding money already spent stops nothing and is not a refusal of the budget.
    assert hold.refusal is None and hold.budget_stop() is None
    assert refused_events(engine) == []


def test_money_already_spent_is_held_past_the_round_and_never_refused(engine):
    """What the step committed above its hold is held by what the budgets have left, never
    refused as a purchase, and the round's own growth still answers for the next purchase."""
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="0.50"))
    reserve_spend(engine, 150_000, "sheet:motion", "the-short")
    hold = a_step_hold(engine, cap_credits=75, first_credits=25)

    # The round measured 45 credits; the day has 10 left beside the 25 held.
    room = hold.room(45.0)

    assert hold.held_micros == 350_000 and room == pytest.approx(-10.0)
    assert hold.refusal is None and refused_events(engine) == []
    # Asked again for the same spend, the budget is not asked twice.
    hold.room(45.0)
    assert sum(r.usd_micros for r in held(engine) if r.purpose == "sheet:stills") == 350_000


def test_a_round_cut_by_the_budget_whose_rest_went_out_later_is_not_a_budget_stop(
    engine, tmp_path, gpu
):
    """Review of 8f5c6ec: a re-roll round cut to what the day had left kept its cut and its
    refusal after the next round sent the rest, so a step that bought everything was parked
    on OVER_DAILY_BUDGET and the day's goal read a refusal nobody met."""
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="0.70"))
    other = reserve_spend(engine, 300_000, "sheet:motion", "the-short")
    hold = a_step_hold(engine, cap_credits=75, first_credits=25)
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    made.core.transport = made.core.client.transport = finishing(cloud)
    asked: list[int] = []

    def next_round(outcomes):
        asked.append(len(outcomes))
        if len(asked) == 1:
            return [request("2", 0), request("3", 0)]  # 25 credits; the day has 15 left
        if len(asked) == 2:
            # While scene 2 was made, the other film let its hold go.
            from app.economy.budget import release_reservation

            release_reservation(engine, other["reservation_id"], "the short let it go")
        return []

    summary, ledger = rounds_with_a_hold(engine, made, hold, next_round)

    # Scene 2 went out alone (the cut), scene 3 in the next round: everything was bought.
    assert [
        [it["scene_id"] for it in cloud.jobs[j]["input"]["items"]] for j in sorted(cloud.jobs)
    ] == [["1", "1"], ["2"], ["3"]]
    assert ledger.committed == 55.0
    assert summary["cap_stop"] is None and summary["stopped"] is None
    assert hold.refusal is None and hold.budget_stop() is None
    assert refused_events(engine) == []


# --------------------------------------------------- 3. the day's goal reads the budget


def test_the_days_goal_gives_the_budget_as_its_reason_and_queues_no_run(engine, settings):
    from app.agents.models import AgentMessage
    from app.story.services import business_date
    from app.workflows.models import TaskQueueItem
    from app.workflows.passes.day_goal import LETTER_SUBJECT
    from test_day_goal import TZ, _finished_run, _pass, _production

    today = business_date(TZ)
    _production(engine)
    _finished_run(engine, today)
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="20"))
    a_spend(engine, 17.0)  # the short: 3 USD of the day are left
    # The episode's stills: a first round of 3,61 USD does not fit in the 3 left.
    with pytest.raises(PurchaseGateRefused) as refused:
        hold_step_budget(
            engine,
            "the-episode",
            "stills",
            3_610_000,
            plan_hash="h",
            allow_over_budget=False,
            correlation_id=str(uuid4()),
        )
    assert refused.value.status == "OVER_DAILY_BUDGET"

    stopped = _pass(engine, settings)

    assert stopped["queued"] is None and stopped["letter"] is False
    assert "bugetul zilnic" in stopped["why"]
    with Session(engine) as session:
        assert session.scalars(select(TaskQueueItem)).all() == []
        letters = session.scalars(
            select(AgentMessage).where(AgentMessage.subject == LETTER_SUBJECT)
        ).all()
        assert letters == []

    # He raises the budget: the round fits again, and the day goes on by itself.
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="25"))
    assert _pass(engine, settings)["queued"]


# --------------------------------------------------- 4. the walk waits on the budget


def test_a_step_ended_on_the_budget_waits_on_his_budget_not_on_a_fault(
    engine, settings, monkeypatch
):
    from app.media import factory
    from app.runbook import stages

    monkeypatch.setattr(shooting_sheet, "recover_paid_takes", lambda *a, **k: {})
    monkeypatch.setattr(factory, "reference_image_adapter", lambda e, s, a: a)
    steps = {
        "stills": {"to_buy": [1, 2], "held": []},
        "test_shot": {"to_buy": [], "held": []},
        "motion": {"to_buy": [], "held": []},
    }
    monkeypatch.setattr(
        shooting_sheet,
        "build_sheet",
        lambda *a, **k: {"steps": steps, "sheet_hash": "h", "scenes": []},
    )
    words = "Bugetul zilnic de 20 USD ar fi depășit: runda următoare a pasului cere 0.5 USD."
    monkeypatch.setattr(
        shooting_sheet,
        "run_sheet_step",
        lambda *a, **k: {
            "stopped": words,
            "budget_stopped": {"status": "OVER_DAILY_BUDGET", "period": "DAILY", "reason": words},
            "booked": {"credits": 388.0},
        },
    )

    # The money boundary is under test; Sarah's review is supplied by a
    # deterministic stand-in so the unrelated Director gate cannot hide it.
    monkeypatch.setattr(
        "app.media.prompt_audit.audit_before_purchase",
        lambda *a, **k: {
            "approved": list(k["scenes"]), "rewritten": [], "held": [],
            "skipped": [], "asked": True,
        },
    )
    film = stages._walk_staircase(engine, settings, object(), "film-1", {}, "PRODUCTION", "c")

    assert film["status"] == "WAITING" and film["refusal"] == "OVER_DAILY_BUDGET"
    assert film["step"] == "stills" and film["reason"] == words
    assert film["refusal"] in stages.OWNER_DECIDES and film["refusal"] in stages.ACCOUNT_WIDE


# --------------------------------------------------- 5. the preflight prices a montage day


def test_the_preflight_prices_a_montage_day_against_the_daily_budget(
    engine, settings, monkeypatch, one_still
):
    from app.publishing.services import seed_default_channels
    from app.runbook.preflight import _daily_budget_films_check

    seed_default_channels(engine)  # the serial's channel: two films a day
    settings.target_video_seconds = 160
    monkeypatch.setattr(shooting_sheet, "price_table_for", lambda *a: runpod_prices())
    now = datetime.now(UTC)
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="15"))

    short = _daily_budget_films_check(engine, settings, "PRODUCTION", now)

    # Per film: 40 stills and two starts (3,88), the test shot (0,28), 39 clips and a start
    # (5,60): 9,76 USD; the day 19,52 USD, before any re-roll and without the narration.
    assert short["code"] == "daily_budget_films.montage_day_over_budget"
    assert short["impact"] == "degrades"
    day = short["value"]["montage_day"]
    assert day["rows"] == 40 and day["films"] == 2
    assert day["film_usd_micros"] == "9.76" and day["day_usd_micros"] == "19.52"
    assert "19,52 USD" in short["message"] and "15 USD" in short["message"]
    assert "Autonomie → Buget și cheltuieli" in short["message"]

    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="20"))
    fits = _daily_budget_films_check(engine, settings, "PRODUCTION", now)

    assert fits["ok"] is True
    assert "rămân 0,48 USD pentru reluări" in fits["message"]
