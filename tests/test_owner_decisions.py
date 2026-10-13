"""The Owner's own window of decisions (2026-10-03): every card waits for his yes or no.

His words: «Dacă sunt decizii pe care eu ca owner trebuie să le iau, trebuie să îmi apară un
card. Trebuie să am propria mea fereastră unde pot să accept sau refuz ce îmi este recomandat
sau trimis.» Before this suite the audit's open questions to him lived in CURRENT_STATUS and in
letters; nothing in the studio held them as decisions he could answer.

What is proven here, with every provider faked: an agent or a stage may PROPOSE a decision
(idempotent by its dedupe key), never decide one; only "owner" decides, once, against the
card's version; an accept applies through his existing Owner command (the ledger records it),
and an apply that fails leaves the card PENDING with a Romanian reason; a guided card waits for
his own action and is closed by the condition clearing or by him; one feed merges the paid-step
approvals, the decisions and the letters that ask him something, with a count; the audit's
pending decisions are seeded once, the budget card from the studio's own numbers.
"""

from __future__ import annotations

import math
from uuid import uuid4

import pytest
from app.agents.messages import post_message
from app.decisions import seed as decision_seed
from app.decisions.models import OwnerDecision
from app.decisions.services import (
    DecideCommand,
    DecisionApplyFailed,
    DecisionConflict,
    DecisionRefused,
    decide_owner_decision,
    propose_owner_decision,
    refresh_owner_decisions,
    withdraw_owner_decision,
)
from app.economy.budget import BudgetCommand, budget_status, set_budget
from app.integrations.models import Integration
from app.models import DomainEvent, OwnerPolicy
from app.schemas import PolicyCommand
from app.services import change_stop, request_approval, utc_now
from sqlalchemy import func, select
from sqlalchemy.orm import Session

PAID_MEDIA_OPTIONS = [
    {
        "key": "mode",
        "label_ro": "Trec la MODE",
        "effect_ro": "Pașii plătiți urmează modul de autonomie.",
        "recommended": True,
        "apply": {
            "type": "paid_media_approval",
            "to": "MODE",
            "expect": "EVERY_PAID_STEP",
        },
    },
    {
        "key": "keep",
        "label_ro": "Rămân la fiecare pas plătit",
        "effect_ro": "Nimic nu se schimbă.",
        "recommended": False,
        "apply": {"type": "none"},
    },
]


def _propose(session: Session, **overrides):
    values = {
        "kind": "paid_media_rule",
        "dedupe_key": "test:paid_media_rule",
        "title_ro": "Când trece studioul de la fiecare pas plătit la MODE",
        "why_ro": "Primul film plătit cu plafon a trecut de ochiul Proprietarului.",
        "effect_ro": "Pașii plătiți nu îl mai întreabă de fiecare dată.",
        "options": PAID_MEDIA_OPTIONS,
        "source": "agent:director",
    }
    values.update(overrides)
    return propose_owner_decision(session, **values)


def _proposed(engine, **overrides) -> tuple[str, int]:
    with Session(engine) as session, session.begin():
        row = _propose(session, **overrides)
        return row.id, row.version


def _decide(engine, decision_id, version, decision="ACCEPT", **extra):
    command = DecideCommand(
        command_id=uuid4(), expected_version=version, decision=decision, **extra
    )
    return decide_owner_decision(engine, decision_id, command, issued_by="owner")


def _row(engine, decision_id) -> OwnerDecision:
    with Session(engine) as session:
        row = session.get(OwnerDecision, decision_id)
        assert row is not None
        session.expunge(row)
        return row


def _events(engine, event_type: str) -> list[DomainEvent]:
    with Session(engine) as session:
        return list(
            session.scalars(select(DomainEvent).where(DomainEvent.event_type == event_type))
        )


def _lift_stop(engine) -> None:
    with Session(engine) as session:
        version = session.get(OwnerPolicy, 1).version
    change_stop(engine, PolicyCommand(command_id=uuid4(), expected_version=version, stopped=False))


# ------------------------------------------------------------------------------ proposing


def test_a_proposal_is_idempotent_by_its_key_and_open_to_agents(engine):
    first, _ = _proposed(engine)
    again, _ = _proposed(engine, title_ro="Același lucru, spus din nou")
    assert again == first
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(OwnerDecision)) == 1
        row = session.get(OwnerDecision, first)
        assert row.status == "PENDING" and row.version == 1 and row.source == "agent:director"
        # The recommended option leads.
        assert row.options[0]["key"] == "mode" and row.options[0]["recommended"] is True

    # Once he has answered, the same key may be asked again: one OPEN card per key.
    result = _decide(engine, first, 1, decision="REFUSE", note="Nu încă.")
    assert result["decision"]["status"] == "REFUSED"
    second, _ = _proposed(engine)
    assert second != first


def test_a_proposal_puts_the_recommended_option_first_and_refuses_two_recommendations(engine):
    options = list(reversed(PAID_MEDIA_OPTIONS))
    decision_id, _ = _proposed(engine, options=options)
    assert _row(engine, decision_id).options[0]["key"] == "mode"
    both = [dict(option, recommended=True) for option in PAID_MEDIA_OPTIONS]
    with pytest.raises(ValueError), Session(engine) as session, session.begin():
        _propose(session, dedupe_key="test:two", options=both)


# ------------------------------------------------------------------------------- deciding


def test_only_the_owner_decides_an_agents_answer_is_refused_and_changes_nothing(engine):
    decision_id, version = _proposed(engine)
    command = DecideCommand(command_id=uuid4(), expected_version=version, decision="ACCEPT")
    for issuer in ("agent:director", "director", "", "AUTORUN"):
        with pytest.raises(DecisionRefused):
            decide_owner_decision(engine, decision_id, command, issued_by=issuer)
    row = _row(engine, decision_id)
    assert row.status == "PENDING" and row.version == version
    with Session(engine) as session:
        assert session.get(OwnerPolicy, 1).paid_media_approval == "EVERY_PAID_STEP"


def test_a_stale_version_is_a_conflict_and_a_closed_card_is_never_answered_twice(engine):
    decision_id, version = _proposed(engine)
    with pytest.raises(DecisionConflict):
        _decide(engine, decision_id, version + 1)
    _decide(engine, decision_id, version, decision="REFUSE")
    with pytest.raises(DecisionConflict):
        _decide(engine, decision_id, version + 1)


def test_accept_applies_through_the_owner_command_and_the_ledger_records_both(engine):
    decision_id, version = _proposed(engine)
    command = DecideCommand(
        command_id=uuid4(), expected_version=version, decision="ACCEPT", note="Da."
    )
    result = decide_owner_decision(engine, decision_id, command, issued_by="owner")
    # The same command again is the same answer, applied once.
    assert decide_owner_decision(engine, decision_id, command, issued_by="owner") == result

    with Session(engine) as session:
        assert session.get(OwnerPolicy, 1).paid_media_approval == "MODE"
    row = _row(engine, decision_id)
    assert row.status == "ACCEPTED" and row.chosen_option == "mode" and row.note == "Da."
    assert row.decided_by == "owner" and row.version == version + 1
    assert row.applied["type"] == "paid_media_approval"
    assert row.applied["result"]["paid_media_approval"] == "MODE"
    changed = _events(engine, "owner.paid_media_approval_changed")
    decided = _events(engine, "owner.decision_decided")
    assert len(changed) == 1 and len(decided) == 1
    assert decided[0].payload["option"] == "mode"
    assert decided[0].payload["applied_event_id"] == changed[0].event_id


def test_accept_of_a_budget_card_sets_the_budget_through_the_budget_command(engine):
    with Session(engine) as session:
        from app.economy.budget import budget_version

        expected = budget_version(session, "DAILY")
    options = [
        {
            "key": "raise",
            "label_ro": "Ridic bugetul zilnic la 40 USD",
            "effect_ro": "Un film întreg încape într-o zi.",
            "recommended": True,
            "apply": {
                "type": "budget",
                "period": "DAILY",
                "limit_usd": "40",
                "expected_version": expected,
            },
        },
        {
            "key": "keep",
            "label_ro": "Păstrez bugetul",
            "effect_ro": "Filmul nu încape într-o zi.",
            "recommended": False,
            "apply": {"type": "none"},
        },
    ]
    decision_id, version = _proposed(
        engine, kind="daily_budget", dedupe_key="test:budget", options=options
    )
    _decide(engine, decision_id, version)
    budgets = budget_status(engine)["budgets"]
    daily = [b for b in budgets if b["period"] == "DAILY"]
    assert daily and daily[0]["limit_usd"] in ("40", "40.00", "40.000000")
    assert len(_events(engine, "economy.budget_set")) == 1
    assert _row(engine, decision_id).status == "ACCEPTED"


def test_a_failed_apply_leaves_the_card_pending_with_a_romanian_reason(engine):
    # The budget moved after the card was written: the card's figure was about another state.
    options = [
        {
            "key": "raise",
            "label_ro": "Ridic bugetul zilnic la 40 USD",
            "effect_ro": "Un film întreg încape într-o zi.",
            "recommended": True,
            "apply": {
                "type": "budget",
                "period": "DAILY",
                "limit_usd": "40",
                "expected_version": 0,
            },
        }
    ]
    decision_id, version = _proposed(
        engine, kind="daily_budget", dedupe_key="test:budget-stale", options=options
    )
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="15"))
    with pytest.raises(DecisionApplyFailed) as failure:
        _decide(engine, decision_id, version)
    assert "Bugetul zilnic" in str(failure.value)
    row = _row(engine, decision_id)
    assert row.status == "PENDING" and row.version == version
    assert row.apply_error_ro and "Bugetul zilnic" in row.apply_error_ro
    assert not _events(engine, "owner.decision_decided")
    daily = [b for b in budget_status(engine)["budgets"] if b["period"] == "DAILY"]
    assert daily[0]["limit_usd_micros"] == 15_000_000

    # A promotion the stop forbids is refused by his own command, in its own words.
    promote = [
        {
            "key": "supervised",
            "label_ro": "Trec la supravegheat",
            "effect_ro": "",
            "recommended": True,
            "apply": {"type": "autonomy_mode", "to": "AUTONOMOUS_CEO", "expect": "MANUAL"},
        }
    ]
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_mode = "MANUAL"
    other, other_version = _proposed(engine, dedupe_key="test:promote", options=promote)
    with pytest.raises(DecisionApplyFailed) as refused:
        _decide(engine, other, other_version)
    assert "OPRITĂ" in str(refused.value)
    assert _row(engine, other).status == "PENDING"


def test_an_apply_whose_state_moved_meanwhile_is_refused_not_applied(engine):
    decision_id, version = _proposed(engine)
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.paid_media_approval = "OVER_USD"
        policy.paid_media_approval_over_usd = 5.0
    with pytest.raises(DecisionApplyFailed) as failure:
        _decide(engine, decision_id, version)
    assert "s-a schimbat" in str(failure.value)
    with Session(engine) as session:
        assert session.get(OwnerPolicy, 1).paid_media_approval == "OVER_USD"


# ------------------------------------------------------------------------------- guided


def _runway(engine, commercial: str | None = None) -> str:
    from app.services import append_event

    with Session(engine) as session, session.begin():
        event = append_event(session, "settings.test", "integration", "x", 1, {}, str(uuid4()))
        row = Integration(
            id=str(uuid4()),
            kind="runway",
            name="Runway",
            config={"commercial_use": commercial} if commercial else {},
            encrypted_secrets="",
            secret_fields=[],
            version=1,
            status="ACCESS_VERIFIED",
            checked_at=utc_now(),
            event_id=event.event_id,
        )
        session.add(row)
        return row.id


def _commercial_card(engine, integration_id: str) -> tuple[str, int]:
    options = [
        {
            "key": "state",
            "label_ro": "Declar folosirea comercială",
            "effect_ro": "Filmele pot ieși publice după QC.",
            "recommended": True,
            "apply": {
                "type": "guided",
                "place": "media",
                "steps_ro": "Scrie «da» la folosire comercială pe conexiunea Runway.",
            },
        }
    ]
    return _proposed(
        engine,
        kind="commercial_use",
        dedupe_key=f"test:commercial:{integration_id}",
        options=options,
        clears_when={"type": "commercial_use", "integration_id": integration_id},
        subject_type="connection",
        subject_id=integration_id,
    )


def _set_commercial(engine, integration_id: str) -> None:
    with Session(engine) as session, session.begin():
        row = session.get(Integration, integration_id)
        row.config = {**dict(row.config or {}), "commercial_use": "da"}


def test_a_guided_card_waits_for_his_action_and_closes_when_the_condition_clears(engine, settings):
    integration_id = _runway(engine)
    decision_id, version = _commercial_card(engine, integration_id)
    result = _decide(engine, decision_id, version)
    row = _row(engine, decision_id)
    assert row.status == "WAITING_FOR_OWNER_ACTION"
    assert result["decision"]["applied"]["place_ro"] == "Setări → Video și sunet"
    # Nothing has cleared yet: the card keeps waiting.
    refresh_owner_decisions(engine, settings)
    assert _row(engine, decision_id).status == "WAITING_FOR_OWNER_ACTION"

    _set_commercial(engine, integration_id)
    refresh_owner_decisions(engine, settings)
    done = _row(engine, decision_id)
    assert done.status == "ACCEPTED" and done.applied["completed_by"] == "condition"
    assert _events(engine, "owner.decision_completed")


def test_a_pending_card_whose_condition_clears_is_withdrawn(engine, settings):
    integration_id = _runway(engine)
    decision_id, _ = _commercial_card(engine, integration_id)
    _set_commercial(engine, integration_id)
    refresh_owner_decisions(engine, settings)
    row = _row(engine, decision_id)
    assert row.status == "WITHDRAWN" and row.applied["withdrawn_reason_ro"]


def test_he_marks_a_waiting_card_done_and_an_agent_withdraws_a_pending_one(engine):
    integration_id = _runway(engine)
    decision_id, version = _commercial_card(engine, integration_id)
    _decide(engine, decision_id, version)
    # His DONE closes it once the studio sees it done (2026-10-04): the connection says «da».
    _set_commercial(engine, integration_id)
    _decide(engine, decision_id, version + 1, decision="DONE")
    row = _row(engine, decision_id)
    assert row.status == "ACCEPTED" and row.applied["completed_by"] == "owner"

    other, _ = _proposed(engine, dedupe_key="test:withdraw")
    with Session(engine) as session, session.begin():
        gone = withdraw_owner_decision(
            session, dedupe_key="test:withdraw", reason_ro="Nu mai e nevoie.", source="agent:x"
        )
        assert gone is not None
    assert _row(engine, other).status == "WITHDRAWN"
    # Withdrawing what is not open is nothing, never an error.
    with Session(engine) as session, session.begin():
        assert withdraw_owner_decision(session, dedupe_key="test:withdraw", reason_ro="x") is None


# --------------------------------------------------------------------------------- the feed


def test_the_feed_merges_approvals_decisions_and_letters_with_one_count(client, headers, engine):
    with Session(engine) as session, session.begin():
        session.query(OwnerDecision).delete()  # the startup seed is tested on its own
        request_approval(
            session,
            "media.stills_purchase",
            "T3",
            "Director",
            subject="board-1",
            evidence="Imaginile filmului.",
            proposed_diff={"step": "stills", "plan_hash": "a" * 64},
            cost_usd=0.72,
        )
        post_message(
            session,
            intent="ESCALATE",
            subject="Reparația foii s-a oprit",
            body={"kind": "sheet_repair_paused"},
            body_text="Am nevoie de tine.",
            to_owner=True,
        )
        post_message(
            session,
            intent="STATUS",
            subject="Ziua s-a încheiat",
            body={"kind": "owner_letter"},
            body_text="Doar ca să știi.",
            to_owner=True,
        )
    decision_id, _ = _proposed(engine)

    response = client.get("/api/v1/owner/decision-cards", headers=headers)
    assert response.status_code == 200
    feed = response.json()
    kinds = [card["source_type"] for card in feed["cards"]]
    assert sorted(kinds) == ["approval", "decision", "letter"]
    assert feed["count"] == 3
    assert feed["counts"] == {"approvals": 1, "decisions": 1, "waiting_action": 0, "letters": 1}
    stamps = [card["created_at"] for card in feed["cards"]]
    assert stamps == sorted(stamps, reverse=True)
    decision = next(card for card in feed["cards"] if card["source_type"] == "decision")
    assert decision["id"] == decision_id and decision["recommended_option"] == "mode"
    assert decision["answer"]["path"] == f"/api/v1/owner/decisions/{decision_id}/decide"
    approval = next(card for card in feed["cards"] if card["source_type"] == "approval")
    assert approval["answer"]["path"] == "/api/v1/owner/approvals/decision"
    assert approval["effect_ro"] == "plafon 0.72 USD"
    letter = next(card for card in feed["cards"] if card["source_type"] == "letter")
    assert letter["answer"]["reply_path"].endswith("/reply")

    # His answer through the route; the history keeps it.
    answered = client.post(
        f"/api/v1/owner/decisions/{decision_id}/decide",
        headers=headers,
        json={
            "command_id": str(uuid4()),
            "expected_version": 1,
            "decision": "REFUSE",
            "note": "Mai târziu.",
        },
    )
    assert answered.status_code == 200, answered.text
    feed = client.get("/api/v1/owner/decision-cards", headers=headers).json()
    assert feed["count"] == 2
    assert [card["id"] for card in feed["history"] if card["source_type"] == "decision"] == [
        decision_id
    ]


def test_the_routes_are_the_owners_and_answer_his_errors(client, headers, engine):
    with Session(engine) as session, session.begin():
        session.query(OwnerDecision).delete()
    decision_id, _ = _proposed(engine)
    body = {"command_id": str(uuid4()), "expected_version": 1, "decision": "ACCEPT"}
    assert client.get("/api/v1/owner/decision-cards").status_code == 401
    assert (
        client.post(f"/api/v1/owner/decisions/{decision_id}/decide", json=body).status_code == 401
    )
    stale = dict(body, expected_version=7)
    assert (
        client.post(
            f"/api/v1/owner/decisions/{decision_id}/decide", headers=headers, json=stale
        ).status_code
        == 409
    )
    missing = client.post(f"/api/v1/owner/decisions/{uuid4()}/decide", headers=headers, json=body)
    assert missing.status_code == 404
    # A body cannot name its issuer.
    forged = dict(body, issued_by="owner")
    assert (
        client.post(
            f"/api/v1/owner/decisions/{decision_id}/decide", headers=headers, json=forged
        ).status_code
        == 422
    )


# --------------------------------------------------------------------------------- the seed


def _seeded(engine) -> dict[str, OwnerDecision]:
    with Session(engine) as session:
        rows = list(session.scalars(select(OwnerDecision).where(OwnerDecision.source == "audit")))
        for row in rows:
            session.expunge(row)
        return {row.kind: row for row in rows}


def _budget_below_the_film(engine) -> int:
    """A daily budget, in whole USD, that cannot hold the cheapest capable film's cap."""
    film = decision_seed.cheapest_capable_film(engine)
    assert film is not None
    low = max(1, film["cap_usd_micros"] // 2_000_000)
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd=str(low)))
    return low


def test_the_audit_is_seeded_once_with_the_recommended_option_first(engine, settings):
    _budget_below_the_film(engine)
    created = decision_seed.seed_owner_decisions(engine, settings)
    assert created
    seeded = _seeded(engine)
    for kind in (
        "daily_budget",
        "music_library",
        "narration_paid_step",
        "paid_media_rule",
        "editorial_qc",
        "sale_terms",
    ):
        assert kind in seeded, kind
    for row in seeded.values():
        assert row.status == "PENDING"
        assert row.options[0]["recommended"] is True
        assert row.title_ro and row.why_ro
    assert decision_seed.seed_owner_decisions(engine, settings) == []
    assert len(_seeded(engine)) == len(seeded)

    # Refused, it is not seeded again: "never twice".
    narration = seeded["narration_paid_step"]
    _decide(engine, narration.id, narration.version, decision="REFUSE")
    assert decision_seed.seed_owner_decisions(engine, settings) == []


def test_the_budget_card_is_computed_from_the_studios_numbers(engine, settings):
    film = decision_seed.cheapest_capable_film(engine)
    assert film["cap_usd_micros"] >= film["total_usd_micros"] > 0
    assert film["scenes"] == decision_seed.REFERENCE_SCENES

    low = _budget_below_the_film(engine)
    decision_seed.seed_owner_decisions(engine, settings)
    card = _seeded(engine)["daily_budget"]
    recommended = card.options[0]
    expected = math.ceil(film["cap_usd_micros"] / 5_000_000) * 5
    assert recommended["apply"]["type"] == "budget"
    assert recommended["apply"]["limit_usd"] == str(expected)
    assert f"{low} USD" in card.why_ro
    assert card.clears_when == {
        "type": "daily_budget_at_least",
        "usd_micros": film["cap_usd_micros"],
    }


def test_no_budget_card_when_the_daily_budget_already_holds_a_film(engine, settings):
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="500"))
    decision_seed.seed_owner_decisions(engine, settings)
    assert "daily_budget" not in _seeded(engine)


def test_a_connection_without_commercial_use_gets_its_own_guided_card(engine, settings):
    integration_id = _runway(engine)
    decision_seed.seed_owner_decisions(engine, settings)
    card = _seeded(engine)["commercial_use"]
    assert card.subject_id == integration_id
    assert card.options[0]["apply"]["type"] == "guided"
    _runway_ok = _runway(engine, commercial="da")
    decision_seed.seed_owner_decisions(engine, settings)
    with Session(engine) as session:
        keys = set(
            session.scalars(
                select(OwnerDecision.subject_id).where(OwnerDecision.kind == "commercial_use")
            )
        )
    assert _runway_ok not in keys


def test_the_studio_seeds_at_startup_without_writing_to_the_ledger(client, headers, engine):
    feed = client.get("/api/v1/owner/decision-cards", headers=headers).json()
    kinds = {card["kind"] for card in feed["cards"] if card["source_type"] == "decision"}
    assert {"narration_paid_step", "paid_media_rule", "sale_terms"} <= kinds
    # A proposal is not an act: nothing in the ledger until he answers.
    with Session(engine) as session:
        assert not session.scalars(
            select(DomainEvent).where(DomainEvent.event_type.like("owner.decision%"))
        ).first()


# ---------------------------------------------------------------------------- migration 0054


def test_migration_0054_adds_the_table_with_one_open_card_per_key_and_takes_it_back(tmp_path):
    import sqlite3

    from app.db import create_db_engine, migrate
    from sqlalchemy import inspect
    from test_migrations_0049 import _downgrade

    path = tmp_path / "studio.db"
    engine = create_db_engine(f"sqlite:///{path.as_posix()}")
    migrate(engine, "0053_channel_upload_settings")
    assert "owner_decision" not in inspect(engine).get_table_names()
    migrate(engine, "0054_owner_decisions")
    assert "owner_decision" in inspect(engine).get_table_names()

    raw = sqlite3.connect(path)
    try:
        insert = (
            "INSERT INTO owner_decision (id, kind, title_ro, why_ro, effect_ro, options, "
            "source, dedupe_key, status, version, created_at, updated_at) "
            "VALUES (?, 'k', 't', 'w', 'e', '[]', 'audit', 'same', ?, 1, 'now', 'now')"
        )
        raw.execute(insert, ("a", "PENDING"))
        raw.execute(insert, ("b", "REFUSED"))
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(insert, ("c", "WAITING_FOR_OWNER_ACTION"))
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(insert, ("d", "MAYBE"))
        raw.commit()
    finally:
        raw.close()

    _downgrade(engine, "0053_channel_upload_settings")
    assert "owner_decision" not in inspect(engine).get_table_names()
    engine.dispose()


def test_a_failing_language_model_connection_gets_a_reconnect_card_withdrawn_when_verified(
    engine, settings
):
    from app.services import append_event

    with Session(engine) as session, session.begin():
        event = append_event(session, "settings.test", "integration", "o", 1, {}, str(uuid4()))
        ollama = Integration(
            id=str(uuid4()),
            kind="ollama",
            name="Ollama Cloud",
            config={},
            encrypted_secrets="",
            secret_fields=[],
            version=1,
            status="FAILED",
            checked_at=utc_now(),
            event_id=event.event_id,
        )
        session.add(ollama)
        ollama_id = ollama.id
    decision_seed.seed_owner_decisions(engine, settings)
    card = _seeded(engine)["reconnect_connection"]
    assert card.subject_id == ollama_id
    assert card.options[0]["apply"]["place_ro"] == "Setări → Furnizori AI"

    # He reconnects and the check verifies the key: the card goes away by itself.
    with Session(engine) as session, session.begin():
        row = session.get(Integration, ollama_id)
        row.status, row.checked_at = "VERIFIED", utc_now()
    refresh_owner_decisions(engine, settings)
    assert _row(engine, card.id).status == "WITHDRAWN"
    # And it is not seeded again.
    assert decision_seed.seed_owner_decisions(engine, settings) == []


# ------------------------------------------------- verification (2026-10-03): adversarial


def test_an_accept_whose_card_failed_after_the_apply_committed_applies_once_on_retry(
    engine, monkeypatch
):
    """The apply commits, then the card's own transaction dies (a crash, a lock). His page
    reloads and he presses Accept again with a NEW command id: the change is not applied twice
    and the card ends ACCEPTED with the first apply's event."""
    from app.decisions import services as decisions

    decision_id, version = _proposed(engine)
    real_remember = decisions.remember_command
    calls = {"n": 0}

    def dies_once(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("the card's transaction died")
        return real_remember(*args, **kwargs)

    monkeypatch.setattr(decisions, "remember_command", dies_once)
    with pytest.raises(RuntimeError):
        _decide(engine, decision_id, version)
    assert _row(engine, decision_id).status == "PENDING", "the card did not commit"
    with Session(engine) as session:
        assert session.get(OwnerPolicy, 1).paid_media_approval == "MODE", "the apply did"

    _decide(engine, decision_id, version)

    row = _row(engine, decision_id)
    changed = _events(engine, "owner.paid_media_approval_changed")
    assert row.status == "ACCEPTED"
    assert len(changed) == 1, "applied once, never twice"
    assert row.applied["event_id"] == changed[0].event_id


def test_a_forged_issuer_or_an_agent_key_never_reaches_the_decide_route(client, headers, engine):
    decision_id, version = _proposed(engine)
    body = {"command_id": str(uuid4()), "expected_version": version, "decision": "ACCEPT"}
    path = f"/api/v1/owner/decisions/{decision_id}/decide"
    assert client.post(path, json=body).status_code == 401
    wrong = {**headers, "Authorization": "Bearer not-the-owner"}
    wrong.pop("X-Owner-Key", None)
    assert client.post(path, json=body, headers=wrong).status_code in (401, 403)
    forged = client.post(path, json={**body, "issued_by": "owner"}, headers=headers)
    assert forged.status_code == 422
    assert _row(engine, decision_id).status == "PENDING"
    with Session(engine) as session:
        assert session.get(OwnerPolicy, 1).paid_media_approval == "EVERY_PAID_STEP"
