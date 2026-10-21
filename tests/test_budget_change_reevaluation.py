"""Owner budget changes reach film gates and reopen obsolete financial opinions."""

from datetime import UTC, datetime

import pytest
from app.economy import repurchase_gate as gate
from app.economy.budget import BudgetCommand, may_spend, set_budget
from app.media.shooting_sheet import (
    PurchaseGateRefused,
    check_film_ceiling,
    film_budget_view,
    film_ceiling_micros,
    hold_step_budget,
)
from app.media.toolchain import find_ffmpeg
from app.publishing.services import seed_default_channels
from app.runbook.preflight import _daily_budget_films_check
from test_accountant_gates_the_repurchase import (
    ACCEPT_MINOR,
    APPROVE,
    CLOSE_SCENE,
    REFUSE,
    Desk,
    _film,
    _gate_events,
)
from test_budget_gates import book
from test_director_rewrites_failed_scene import agents_say, studio  # noqa: F401
from test_film_costing import a_film
from test_redo_resume_spends_his_yes import _walk


def _check(engine, settings, board, cap):
    return check_film_ceiling(
        engine,
        board,
        cap,
        step="stills",
        plan_hash="current-reviewed-plan",
        settings=settings,
        environment="PRODUCTION",
        allow_over_budget=False,
        correlation_id=board,
    )


def test_unset_film_ceiling_uses_the_active_owner_budget_and_reads_each_update(
    engine, settings, tmp_path
):
    board = a_film(engine, tmp_path)
    book(engine, board, "12.843153")
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="15"))
    with pytest.raises(PurchaseGateRefused):
        _check(engine, settings, board, 4_320_000)

    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="20"))
    view = film_budget_view(engine, board, settings)
    assert view["limit_usd_micros"] == 20_000_000
    assert view["remaining_usd_micros"] == 7_156_847
    assert view["source"] == "buget_zilnic"
    assert _check(engine, settings, board, 4_320_000) is None

    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="10"))
    with pytest.raises(PurchaseGateRefused) as error:
        _check(engine, settings, board, 840_000)
    assert error.value.status == "OVER_FILM_BUDGET"


def test_an_explicit_film_ceiling_is_preserved_after_the_daily_budget_changes(
    engine, settings, tmp_path
):
    board = a_film(engine, tmp_path)
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="20"))
    settings.film_budget_usd = 5.0
    view = film_budget_view(engine, board, settings)
    assert (view["limit_usd_micros"], view["source"]) == (5_000_000, "setare")
    with pytest.raises(PurchaseGateRefused):
        _check(engine, settings, board, 6_000_000)


def test_no_daily_budget_keeps_the_existing_configuration_fallback(engine, settings, tmp_path):
    board = a_film(engine, tmp_path)
    expected, source = film_ceiling_micros(settings)
    view = film_budget_view(engine, board, settings)
    assert view["limit_usd_micros"] == expected and view["source"] == source == "implicit"


def test_shared_daily_budget_still_refuses_combined_holds_after_a_budget_increase(engine):
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="20"))
    hold_step_budget(
        engine,
        "first-film",
        "stills",
        12_000_000,
        plan_hash="approved-first",
        allow_over_budget=False,
        correlation_id="first-film",
    )
    with pytest.raises(PurchaseGateRefused) as error:
        hold_step_budget(
            engine,
            "second-film",
            "stills",
            9_000_000,
            plan_hash="approved-second",
            allow_over_budget=False,
            correlation_id="second-film",
        )
    assert error.value.status == "OVER_DAILY_BUDGET"
    assert not may_spend(engine, 9_000_000)["allowed"]


def test_preflight_explains_the_shared_budget_instead_of_doubling_the_inherited_ceiling(
    engine, settings
):
    seed_default_channels(engine)
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="20"))
    check = _daily_budget_films_check(engine, settings, "PRODUCTION", datetime.now(UTC))
    assert check["ok"] and check["code"] == "daily_budget_films.shared_budget"
    assert check["value"]["per_film_usd"] == "20"
    assert check["value"]["daily_limit_usd"] == "20"
    assert "comun" in check["message"] and "40" not in check["message"]


def test_nadia_receives_the_whole_current_prompt(engine, settings, tmp_path):
    board = a_film(engine, tmp_path)
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="20"))
    prompt = "A complete current scene with all its visible conditions. " * 70
    prompt += "Sarah stays at the right edge in the accepted wardrobe."
    reads = gate._what_nadia_reads(
        engine,
        settings,
        {"storyboard_id": board},
        [],
        1,
        "still",
        {"still_prompt": prompt, "cap_usd": 0.84},
        [],
        {},
        6,
        12,
    )
    assert reads["corrected_prompt"] == prompt
    assert reads["daily_budget"]["limit_usd"] == "20"


def test_large_evidence_does_not_cut_the_current_budget_from_the_agents_message():
    import json

    reads = {
        "corrected_prompt": "The complete reviewed scene. " * 900,
        "daily_budget": {"limit_usd": "20", "remaining_usd": "17.06"},
    }
    data = gate._data(reads, "repurchase-verdict")
    payload = data.split('<untrusted_source_evidence hash="repurchase-verdict">\n', 1)[1]
    parsed = json.loads(payload.split("\n</untrusted_source_evidence>", 1)[0])
    assert parsed == reads


@pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")
@pytest.mark.parametrize("legacy", [False, True])
def test_budget_change_reopens_the_old_refusal_then_keeps_the_new_decision(
    engine,
    settings,
    tmp_path,
    studio,  # noqa: F811
    monkeypatch,
    legacy,
):
    film = _film(engine, tmp_path, monkeypatch)
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="20"))
    desk = Desk(nadia=REFUSE, sarah=CLOSE_SCENE)
    registry = agents_say(studio, desk)
    append = gate.append_event
    if legacy:

        def old_record(session, event_type, aggregate_type, aggregate_id, version, payload, *args):
            payload = {k: v for k, v in payload.items() if k != "budget_context"}
            return append(
                session, event_type, aggregate_type, aggregate_id, version, payload, *args
            )

        monkeypatch.setattr(gate, "append_event", old_record)
    first = _walk(engine, settings, registry, film["board"], film["reading"])
    monkeypatch.setattr(gate, "append_event", append)
    assert first["refused"][0]["status"] == gate.REPURCHASE_REFUSED
    assert len(desk.verdicts) == 1 and film["spy"].asked == []
    unchanged = _walk(engine, settings, registry, film["board"], film["reading"])
    assert unchanged["bought"] == [] and len(desk.verdicts) == 1

    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="30"))
    desk.nadia = APPROVE
    second = _walk(engine, settings, registry, film["board"], film["reading"])
    assert [entry["scene_index"] for entry in second["bought"]] == [1], second
    assert len(desk.verdicts) == 2 and len(film["spy"].asked) == 1
    assert len(_gate_events(engine, film["board"])) == 2
    assert _gate_events(engine, film["board"])[-1]["outcome"] == gate.AGREED


@pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")
def test_changing_the_explicit_film_ceiling_reopens_a_cached_refusal(
    engine,
    settings,
    tmp_path,
    studio,  # noqa: F811
    monkeypatch,
):
    film = _film(engine, tmp_path, monkeypatch)
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="100"))
    settings.film_budget_usd = 15.24
    desk = Desk(nadia=REFUSE, sarah=CLOSE_SCENE)
    registry = agents_say(studio, desk)
    first = _walk(engine, settings, registry, film["board"], film["reading"])
    assert first["refused"][0]["status"] == gate.REPURCHASE_REFUSED

    settings.film_budget_usd = 20.0
    desk.nadia = APPROVE
    second = _walk(engine, settings, registry, film["board"], film["reading"])
    assert second["bought"] and len(desk.verdicts) == 2, second


@pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")
def test_ordinary_spend_does_not_keep_reopening_the_same_refusal(
    engine,
    settings,
    tmp_path,
    studio,  # noqa: F811
    monkeypatch,
):
    from uuid import uuid4

    from app.economy.services import record_provider_cost

    film = _film(engine, tmp_path, monkeypatch)
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="100"))
    desk = Desk(nadia=REFUSE, sarah=CLOSE_SCENE)
    registry = agents_say(studio, desk)
    _walk(engine, settings, registry, film["board"], film["reading"])
    record_provider_cost(
        engine,
        provider="ollama",
        external_reference=str(uuid4()),
        status="ESTIMATED",
        amount="0.01",
        attribution={},
        correlation_id=str(uuid4()),
    )
    again = _walk(engine, settings, registry, film["board"], film["reading"])
    assert not again["bought"] and len(desk.verdicts) == 1


@pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")
def test_more_budget_does_not_undo_an_accepted_minor_quality_decision(
    engine,
    settings,
    tmp_path,
    studio,  # noqa: F811
    monkeypatch,  # noqa: F811
):
    film = _film(engine, tmp_path, monkeypatch)
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="20"))
    desk = Desk(nadia=REFUSE, sarah=ACCEPT_MINOR)
    registry = agents_say(studio, desk)
    first = _walk(engine, settings, registry, film["board"], film["reading"])
    assert first["overturned"] and not first["bought"]
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="30"))
    second = _walk(engine, settings, registry, film["board"], film["reading"])
    assert second["overturned"] and not second["bought"]
    assert len(desk.verdicts) == 1


@pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")
def test_a_cached_minor_acceptance_is_free_even_when_the_budget_is_exhausted(
    engine,
    settings,
    tmp_path,
    studio,  # noqa: F811
    monkeypatch,  # noqa: F811
):
    film = _film(engine, tmp_path, monkeypatch)
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="20"))
    desk = Desk(nadia=REFUSE, sarah=ACCEPT_MINOR)
    registry = agents_say(studio, desk)
    _walk(engine, settings, registry, film["board"], film["reading"])
    record = _gate_events(engine, film["board"])[0]
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="0.01"))
    result = gate.before_paid_redo(
        engine,
        registry,
        settings,
        film["reading"],
        [],
        1,
        "motion",
        {"storyboard_id": film["board"], "plan_hash": record["plan_hash"], "cap_usd": 6.8},
        rounds={},
        per_scene=6,
        per_film=12,
        environment="PRODUCTION",
        measured=False,
        correlation=film["board"],
    )
    assert result is not None and result["verdict"] == "OVERTURNED"
    assert not result["redo"] and len(desk.verdicts) == 1
