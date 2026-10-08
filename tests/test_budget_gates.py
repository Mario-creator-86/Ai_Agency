"""Every gate before a purchase that the Owner's own figures decide (2026-10-02).

Two findings of the audit, each proved on fakes before it was fixed:

- MONEY-06 / AR-07, fail closed. A fresh install has no spending budget, and with none
  `reserve_spend` allowed a 10,000 USD hold. A studio switched to AUTONOMOUS_CEO with the
  paid-media rule MODE (or OVER_USD below its threshold) bought on nothing but each sheet's own
  cap. In PRODUCTION, a paid step the studio would buy unasked is now refused
  (BLOCKED_NO_BUDGET) unless an active DAILY budget exists, and the preflight says so as a
  BLOCKING line. Under EVERY_PAID_STEP the Owner is asked anyway and nothing changes.
- MONEY-07, the film ceiling. ``motion_budget_usd`` (12 USD, "the most one film may spend on
  generated motion") was applied only on the legacy path, while the PRODUCTION staircase
  reserved nothing per film; a typical six-shot sheet caps at about 26 USD. ``film_budget_usd``
  is now checked before every paid step of a PRODUCTION film: what the books hold for the
  film plus the step's cap; over it the step is refused OVER_FILM_BUDGET before any POST,
  unless the Owner's explicit allow flag is given.

Every provider is faked (the spies of test_film_costing); no socket is opened.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from app.economy.budget import BudgetCommand, set_budget
from app.economy.models import SpendReservation
from app.economy.services import record_provider_cost
from app.integrations.vault import CredentialVault
from app.media.shooting_sheet import SheetStepRefused, build_sheet, run_sheet_step
from app.media.toolchain import find_ffmpeg
from app.models import DomainEvent, OwnerPolicy
from app.runbook.preflight import BLOCKING, DEGRADING, run_preflight
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_film_costing import SEEDANCE, Account, Models, SpyVideo, a_film

requires_ffmpeg = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")


def policy(engine, *, environment: str, mode: str, rule: str, over: float | None = None) -> None:
    with Session(engine) as session, session.begin():
        row = session.get(OwnerPolicy, 1)
        row.autonomy_stopped = False
        row.environment = environment
        row.autonomy_mode = mode
        row.paid_media_approval = rule
        row.paid_media_approval_over_usd = over


def step(engine, storyboard_id, tmp_path: Path, models, account, name="test_shot", **kwargs):
    sheet = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)
    return run_sheet_step(
        engine,
        storyboard_id,
        name,
        sheet["sheet_hash"],
        correlation_id=str(uuid4()),
        capabilities=[SEEDANCE],
        account=account,
        adapter_for_model=models,
        storage_root=tmp_path / "media",
        **kwargs,
    )


def reservations(engine) -> list[SpendReservation]:
    with Session(engine) as session:
        rows = list(session.scalars(select(SpendReservation)))
        session.expunge_all()
        return rows


# ------------------------------------------------------------- MONEY-06 / AR-07: fail closed


@requires_ffmpeg
def test_production_under_mode_with_no_daily_budget_buys_nothing(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=3)
    policy(engine, environment="PRODUCTION", mode="AUTONOMOUS_CEO", rule="MODE")
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))

    with pytest.raises(SheetStepRefused) as refused:
        step(engine, storyboard_id, tmp_path, models, account)

    assert refused.value.status == "BLOCKED_NO_BUDGET", refused.value.reason_ro
    assert refused.value.http_status == 409
    assert "Autonomie → Buget" in refused.value.reason_ro
    assert "buget zilnic" in refused.value.reason_ro
    assert models.posts() == 0
    # Whatever the step held while it was refused was let go.
    assert all(row.status != "RESERVED" for row in reservations(engine))

    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="50"))
    bought = step(engine, storyboard_id, tmp_path, models, account)

    assert models.posts() == 1
    assert {s["scene_index"]: s["status"] for s in bought["scenes"]}[1] == "PAID"


@requires_ffmpeg
def test_a_monthly_budget_alone_does_not_open_unasked_buying(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=3)
    policy(engine, environment="PRODUCTION", mode="AUTONOMOUS_CEO", rule="MODE")
    set_budget(engine, BudgetCommand(period="MONTHLY", limit_usd="300"))
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))

    with pytest.raises(SheetStepRefused) as refused:
        step(engine, storyboard_id, tmp_path, models, account)

    assert refused.value.status == "BLOCKED_NO_BUDGET"
    assert models.posts() == 0


@requires_ffmpeg
def test_under_over_usd_below_the_threshold_the_budget_is_required_too(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=3)
    # The hero's cap is 6.80 USD: under a 50 USD threshold the studio would buy it unasked.
    policy(engine, environment="PRODUCTION", mode="AUTONOMOUS_CEO", rule="OVER_USD", over=50.0)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))

    with pytest.raises(SheetStepRefused) as refused:
        step(engine, storyboard_id, tmp_path, models, account)

    assert refused.value.status == "BLOCKED_NO_BUDGET"
    assert models.posts() == 0


@requires_ffmpeg
def test_every_paid_step_still_asks_the_owner_without_a_budget(engine, tmp_path):
    """His own question is the gate there: no budget is needed for him to be asked."""
    storyboard_id = a_film(engine, tmp_path, scenes=3)
    policy(engine, environment="PRODUCTION", mode="AUTONOMOUS_CEO", rule="EVERY_PAID_STEP")
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))

    with pytest.raises(SheetStepRefused) as asked:
        step(engine, storyboard_id, tmp_path, models, account)

    assert asked.value.status == "NEEDS_APPROVAL"
    assert models.posts() == 0


@requires_ffmpeg
def test_in_test_the_rule_is_unchanged(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=3)
    policy(engine, environment="TEST", mode="AUTONOMOUS_CEO", rule="MODE")
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))

    step(engine, storyboard_id, tmp_path, models, account)

    assert models.posts() == 1


def _check(result: dict, name: str) -> dict:
    return next(check for check in result["checks"] if check["name"] == name)


def test_the_preflight_budget_line_blocks_exactly_when_the_studio_would_buy_unasked(
    engine, settings, tmp_path
):
    vault = CredentialVault(tmp_path / "gates.credentials.key")
    policy(engine, environment="PRODUCTION", mode="AUTONOMOUS_CEO", rule="MODE")

    line = _check(run_preflight(engine, settings, vault), "spending_budget")
    assert line["ok"] is False and line["severity"] == BLOCKING
    assert line["code"] == "spending_budget.none_unasked"
    assert "Autonomie → Buget și cheltuieli" in line["message"]
    assert "fără să te întrebe" in line["message"]

    # A monthly budget alone is still not the daily limit the unasked purchase needs.
    set_budget(engine, BudgetCommand(period="MONTHLY", limit_usd="300"))
    monthly = _check(run_preflight(engine, settings, vault), "spending_budget")
    assert monthly["ok"] is False and monthly["severity"] == BLOCKING

    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="15"))
    fixed = _check(run_preflight(engine, settings, vault), "spending_budget")
    assert fixed["ok"] is True

    # Under his own question on every step a missing budget only degrades the day.
    set_budget(engine, BudgetCommand(period="DAILY", retire=True))
    set_budget(engine, BudgetCommand(period="MONTHLY", retire=True))
    policy(engine, environment="PRODUCTION", mode="AUTONOMOUS_CEO", rule="EVERY_PAID_STEP")
    asked = _check(run_preflight(engine, settings, vault), "spending_budget")
    assert asked["ok"] is False and asked["severity"] == DEGRADING
    assert asked["code"] == "spending_budget.none"


# ---------------------------------------------------------------- MONEY-07: the film ceiling


def book(engine, storyboard_id: str, usd: str) -> None:
    record_provider_cost(
        engine,
        provider="runway",
        external_reference=f"foaie:{storyboard_id}:stills:{uuid4()}",
        status="ESTIMATED",
        amount=usd,
        attribution={"storyboard_id": storyboard_id, "step": "stills"},
        correlation_id=str(uuid4()),
    )


@requires_ffmpeg
def test_a_film_over_its_ceiling_is_refused_before_any_post(engine, settings, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=3)
    policy(engine, environment="PRODUCTION", mode="AUTONOMOUS_CEO", rule="MODE")
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="100"))
    ceiling = settings.model_copy(update={"film_budget_usd": 8.0})
    # The film's stills are in the books (2 USD); the hero's cap is 6.80 USD: 8.80 > 8.
    book(engine, storyboard_id, "2.000000")
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))

    with pytest.raises(SheetStepRefused) as refused:
        step(engine, storyboard_id, tmp_path, models, account, settings=ceiling)

    assert refused.value.status == "OVER_FILM_BUDGET", refused.value.reason_ro
    assert refused.value.http_status == 409
    reason = refused.value.reason_ro
    assert "8,00 USD" in reason and "2,00 USD" in reason and "6,80 USD" in reason
    assert models.posts() == 0
    assert all(row.status != "RESERVED" for row in reservations(engine))

    # His explicit consent on the sheet lets the step go over, and it is recorded.
    bought = step(
        engine, storyboard_id, tmp_path, models, account, settings=ceiling, allow_over_budget=True
    )
    assert models.posts() == 1
    assert bought["scenes"][0]["status"] == "PAID"
    with Session(engine) as session:
        excess = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "media.film_budget_excess_approved")
        ).all()
    assert len(excess) == 1 and excess[0].payload["step"] == "test_shot"


@requires_ffmpeg
def test_a_film_inside_its_ceiling_is_bought(engine, settings, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=3)
    policy(engine, environment="PRODUCTION", mode="AUTONOMOUS_CEO", rule="MODE")
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="100"))
    ceiling = settings.model_copy(update={"film_budget_usd": 8.0})
    book(engine, storyboard_id, "1.000000")
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))

    step(engine, storyboard_id, tmp_path, models, account, settings=ceiling)

    assert models.posts() == 1


def test_another_films_spend_does_not_count_against_this_film(engine, settings, tmp_path):
    from app.media.shooting_sheet import film_spend_micros

    storyboard_id = a_film(engine, tmp_path, scenes=2)
    book(engine, storyboard_id, "1.500000")
    book(engine, str(uuid4()), "9.000000")

    assert film_spend_micros(engine, storyboard_id) == 1_500_000


def test_the_sheet_shows_the_films_ceiling_and_what_it_already_holds(engine, settings, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=2)
    book(engine, storyboard_id, "1.500000")

    sheet = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], settings=settings)

    ceiling = sheet["footer"]["film_budget"]
    assert ceiling["spent_usd_micros"] == 1_500_000
    assert ceiling["limit_usd_micros"] > 0
    assert ceiling["remaining_usd_micros"] == ceiling["limit_usd_micros"] - 1_500_000


# ------------------------------------------------- a paid redo passes the same gates


def _a_filmed_film(engine, tmp_path):
    from test_scene_redo import coloured_clip, filmed

    storyboard_id = a_film(engine, tmp_path, scenes=4)
    filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    return storyboard_id


@requires_ffmpeg
def test_a_redo_while_another_buyer_holds_the_film_buys_nothing(engine, tmp_path):
    from app.media.assembler import SceneRedoRefused, redo_plan
    from app.media.shooting_sheet import film_purchase_lease
    from test_scene_redo import redo_motion

    storyboard_id = _a_filmed_film(engine, tmp_path)
    policy(engine, environment="TEST", mode="AUTONOMOUS_CEO", rule="MODE")
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))
    plan = redo_plan(engine, storyboard_id, "motion", 3, capabilities=[SEEDANCE])

    with film_purchase_lease(engine, storyboard_id, holder="the-day", step="staircase"):
        with pytest.raises(SceneRedoRefused) as busy:
            redo_motion(engine, storyboard_id, tmp_path, models, account, 3, plan["plan_hash"])

    assert busy.value.status == "FILM_BUSY" and busy.value.http_status == 409
    assert "Filmul este deja în lucru" in busy.value.reason_ro
    assert models.posts() == 0


@requires_ffmpeg
def test_the_day_waits_for_a_film_the_owner_is_buying_and_leaves_his_lease_alone(
    engine, settings, tmp_path
):
    from app.media.shooting_sheet import current_lease, film_purchase_lease
    from app.runbook.stages import OWNER_DECIDES, _film_staircase

    storyboard_id = a_film(engine, tmp_path, scenes=3)
    policy(engine, environment="TEST", mode="AUTONOMOUS_CEO", rule="MODE")
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))
    wiring = {
        "integration_id": None,
        "capabilities": [SEEDANCE],
        "image_adapter": None,
        "account": account,
        "adapter_for_model": models,
        "resolution": None,
        "storage_root": tmp_path / "media",
    }

    # His press on the sheet holds the film: the day's staircase buys nothing of it and waits.
    with film_purchase_lease(engine, storyboard_id, holder="owner-press", step="test_shot"):
        walked = _film_staircase(
            engine, settings, None, storyboard_id, wiring, "TEST", str(uuid4())
        )
        assert current_lease(engine, storyboard_id)["holder"] == "owner-press"

    assert walked["status"] == "WAITING" and walked["refusal"] == "FILM_BUSY"
    assert "FILM_BUSY" in OWNER_DECIDES
    assert "Filmul este deja în lucru" in walked["reason"]
    assert "cadrul de probă" in walked["reason"]
    assert walked["bought"] == [] and models.posts() == 0 and account.reads == 0
    assert current_lease(engine, storyboard_id) is None


@requires_ffmpeg
def test_a_redo_over_the_films_ceiling_is_refused_and_a_bought_one_settles_its_hold(
    engine, settings, tmp_path, monkeypatch
):
    from app.media import assembler
    from app.media.assembler import SceneRedoRefused, redo_plan
    from test_scene_redo import redo_motion

    storyboard_id = _a_filmed_film(engine, tmp_path)
    policy(engine, environment="PRODUCTION", mode="AUTONOMOUS_CEO", rule="MODE")
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="100"))
    book(engine, storyboard_id, "6.000000")
    monkeypatch.setattr(
        assembler, "_studio_settings", lambda: settings.model_copy(update={"film_budget_usd": 12.0})
    )
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))
    plan = redo_plan(engine, storyboard_id, "motion", 3, capabilities=[SEEDANCE])
    assert plan["cap_usd"] == pytest.approx(6.8)

    # 6 USD in the books plus the redo's 6.80 cap pass the 12 USD ceiling.
    with pytest.raises(SceneRedoRefused) as refused:
        redo_motion(engine, storyboard_id, tmp_path, models, account, 3, plan["plan_hash"])
    assert refused.value.status == "OVER_FILM_BUDGET", refused.value.reason_ro
    assert models.posts() == 0

    # With room under the ceiling the redo is bought once and its hold is settled.
    monkeypatch.setattr(
        assembler, "_studio_settings", lambda: settings.model_copy(update={"film_budget_usd": 20.0})
    )
    redo_motion(engine, storyboard_id, tmp_path, models, account, 3, plan["plan_hash"])
    assert models.posts() == 1
    holds = reservations(engine)
    assert [h.status for h in holds] == ["SETTLED"] and holds[0].purpose == "sheet:scene_redo"
