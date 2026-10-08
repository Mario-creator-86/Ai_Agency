"""«Am făcut-o» closes a card only when the studio sees it done (2026-10-04).

On 2026-10-03 at 21:02 three guided cards in the Owner's window were closed by his DONE
while their conditions were unmet: commercial use on the Runway and on the ElevenLabs
connection (neither connection says «da»), and the sale terms (no LICENSE or EULA file at the
project's root). The page said «Ai marcat-o făcută», the gates still refused, and the seed
never raised the questions again because a key that ever had a card is never seeded twice.

What is proven here, with every provider faked: DONE on a card whose ``clears_when`` reads
false keeps it WAITING_FOR_OWNER_ACTION and says, in Romanian, what is still missing; a
condition that cannot be read keeps the card open (fail closed); a card only he can close
(``never``, or no condition) still closes on his DONE; and the seed re-opens, once and with a
ledger event, a card that an earlier DONE closed while its condition was unmet, without a
second card for the same question.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.decisions import seed as decision_seed
from app.decisions import services as decisions
from app.decisions.models import OwnerDecision
from app.decisions.services import (
    DecideCommand,
    decide_owner_decision,
    propose_owner_decision,
    refresh_owner_decisions,
)
from app.integrations.models import Integration
from app.models import DomainEvent
from app.services import append_event, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session

REOPENED_EVENT = "owner.decision_reopened"


@pytest.fixture
def bare_root(tmp_path, monkeypatch):
    """A project root with no LICENSE or EULA file, for the condition and the seed alike."""
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(decisions, "ROOT", root)
    monkeypatch.setattr(decision_seed, "ROOT", root)
    return root


def _connection(engine, kind: str = "runway", name: str = "AMN-AI") -> str:
    with Session(engine) as session, session.begin():
        event = append_event(session, "settings.test", "integration", "x", 1, {}, str(uuid4()))
        row = Integration(
            id=str(uuid4()),
            kind=kind,
            name=name,
            config={"credit_usd": "0.01"} if kind == "runway" else {},
            encrypted_secrets="",
            secret_fields=[],
            version=1,
            status="ACCESS_VERIFIED",
            checked_at=utc_now(),
            event_id=event.event_id,
        )
        session.add(row)
        return row.id


def _say_yes(engine, integration_id: str) -> None:
    with Session(engine) as session, session.begin():
        row = session.get(Integration, integration_id)
        row.config = {**dict(row.config or {}), "commercial_use": "da"}


def _guided(engine, *, kind: str, dedupe_key: str, clears_when, **extra) -> tuple[str, int]:
    with Session(engine) as session, session.begin():
        row = propose_owner_decision(
            session,
            kind=kind,
            dedupe_key=dedupe_key,
            title_ro="Un pas al tău",
            why_ro="Doar tu îl poți face.",
            effect_ro="Studioul vede rezultatul.",
            options=[
                {
                    "key": "do",
                    "label_ro": "Îl fac eu",
                    "effect_ro": "Îl faci tu, la locul numit.",
                    "recommended": True,
                    "apply": {"type": "guided", "place_ro": "Setări", "steps_ro": "Fă pasul."},
                }
            ],
            clears_when=clears_when,
            source="audit",
            **extra,
        )
        return row.id, row.version


def _answer(engine, decision_id: str, version: int, decision: str, settings=None):
    command = DecideCommand(command_id=uuid4(), expected_version=version, decision=decision)
    return decide_owner_decision(engine, decision_id, command, issued_by="owner", settings=settings)


def _row(engine, decision_id: str) -> OwnerDecision:
    with Session(engine) as session:
        row = session.get(OwnerDecision, decision_id)
        assert row is not None
        session.expunge(row)
        return row


def _waiting(engine, decision_id: str, version: int, settings=None) -> int:
    """He accepts the guided option: the card waits for his act. Returns its version."""
    _answer(engine, decision_id, version, "ACCEPT", settings)
    row = _row(engine, decision_id)
    assert row.status == "WAITING_FOR_OWNER_ACTION"
    return row.version


def _events(engine, event_type: str) -> list[DomainEvent]:
    with Session(engine) as session:
        return list(
            session.scalars(select(DomainEvent).where(DomainEvent.event_type == event_type))
        )


# ----------------------------------------------------------------- DONE reads the condition


def test_done_on_commercial_use_without_da_keeps_waiting_and_names_what_is_missing(
    engine, settings
):
    integration_id = _connection(engine)
    decision_id, version = _guided(
        engine,
        kind="commercial_use",
        dedupe_key=f"commercial_use:{integration_id}",
        clears_when={"type": "commercial_use", "integration_id": integration_id},
        subject_type="connection",
        subject_id=integration_id,
    )
    version = _waiting(engine, decision_id, version, settings)

    result = _answer(engine, decision_id, version, "DONE", settings)
    row = _row(engine, decision_id)
    assert row.status == "WAITING_FOR_OWNER_ACTION", "an unmet condition is not done"
    assert "completed_by" not in (row.applied or {})
    missing = row.apply_error_ro or ""
    assert "«da»" in missing and "termenii planului" in missing and "Runway" in missing
    assert result["decision"]["status"] == "WAITING_FOR_OWNER_ACTION"
    assert result["decision"]["apply_error_ro"] == missing
    # His press is recorded, as what it was: a DONE the studio could not confirm.
    (event,) = [
        e for e in _events(engine, "owner.decision_decided") if e.payload["decision"] == "DONE"
    ]
    assert event.payload["status"] == "WAITING_FOR_OWNER_ACTION"
    assert event.payload["still_missing_ro"] == missing

    # He writes «da» on the connection: now his DONE closes it, and the note goes away.
    _say_yes(engine, integration_id)
    _answer(engine, decision_id, row.version, "DONE", settings)
    done = _row(engine, decision_id)
    assert done.status == "ACCEPTED" and done.applied["completed_by"] == "owner"
    assert done.apply_error_ro is None


def test_done_on_the_sale_terms_without_a_licence_file_keeps_waiting(engine, settings, bare_root):
    decision_id, version = _guided(
        engine,
        kind="sale_terms",
        dedupe_key="audit:sale_terms",
        clears_when={"type": "file_exists", "any_of": list(decision_seed.LICENCE_FILES)},
    )
    version = _waiting(engine, decision_id, version, settings)
    _answer(engine, decision_id, version, "DONE", settings)
    row = _row(engine, decision_id)
    assert row.status == "WAITING_FOR_OWNER_ACTION"
    assert "LICENSE" in row.apply_error_ro and "EULA" in row.apply_error_ro

    (bare_root / "LICENSE").write_text("Termenii Proprietarului.", encoding="utf-8")
    _answer(engine, decision_id, row.version, "DONE", settings)
    assert _row(engine, decision_id).status == "ACCEPTED"


def test_a_condition_that_cannot_be_read_keeps_the_card_open(engine, settings, monkeypatch):
    integration_id = _connection(engine)
    decision_id, version = _guided(
        engine,
        kind="commercial_use",
        dedupe_key=f"commercial_use:{integration_id}",
        clears_when={"type": "commercial_use", "integration_id": integration_id},
    )
    version = _waiting(engine, decision_id, version, settings)

    def unreadable(*_args):
        raise RuntimeError("the books are locked")

    monkeypatch.setitem(decisions.CONDITIONS, "commercial_use", unreadable)
    _answer(engine, decision_id, version, "DONE", settings)
    row = _row(engine, decision_id)
    assert row.status == "WAITING_FOR_OWNER_ACTION", "fail closed: unread is not done"
    assert "nu poate citi" in row.apply_error_ro


@pytest.mark.parametrize("clears_when", [{"type": "never"}, None])
def test_a_card_only_he_can_close_still_closes_on_his_done(engine, settings, clears_when):
    decision_id, version = _guided(
        engine,
        kind="google_oauth_production",
        dedupe_key="audit:google_oauth_production",
        clears_when=clears_when,
    )
    version = _waiting(engine, decision_id, version, settings)
    _answer(engine, decision_id, version, "DONE", settings)
    row = _row(engine, decision_id)
    assert row.status == "ACCEPTED" and row.applied["completed_by"] == "owner"


def test_a_card_closed_by_its_condition_forgets_the_old_missing_note(engine, settings):
    integration_id = _connection(engine)
    decision_id, version = _guided(
        engine,
        kind="commercial_use",
        dedupe_key=f"commercial_use:{integration_id}",
        clears_when={"type": "commercial_use", "integration_id": integration_id},
    )
    version = _waiting(engine, decision_id, version, settings)
    _answer(engine, decision_id, version, "DONE", settings)
    assert _row(engine, decision_id).apply_error_ro
    _say_yes(engine, integration_id)
    refresh_owner_decisions(engine, settings)
    row = _row(engine, decision_id)
    assert row.status == "ACCEPTED" and row.applied["completed_by"] == "condition"
    assert row.apply_error_ro is None


# ------------------------------------------------------ the seed re-opens what DONE closed


def _closed_by_an_earlier_done(engine, decision_id: str) -> None:
    """What the studio before 2026-10-04 did on DONE: ACCEPTED, completed by him, unread."""
    with Session(engine) as session, session.begin():
        row = session.get(OwnerDecision, decision_id)
        row.applied = {
            **dict(row.applied or {}),
            "completed_by": "owner",
            "completed_at": "2026-10-03T21:02:27.917848+00:00",
        }
        row.status = "ACCEPTED"
        row.version += 1


def _legacy_cards(engine, settings) -> dict[str, str]:
    """The window of 2026-10-03 21:02: three guided cards closed by DONE while unmet, one
    closed by DONE that only he can close, and one «keep it as it is» accept."""
    runway = _connection(engine, "runway")
    eleven = _connection(engine, "elevenlabs")
    ids: dict[str, str] = {}
    for name, kind, key, clears in (
        (
            "runway",
            "commercial_use",
            f"commercial_use:{runway}",
            {"type": "commercial_use", "integration_id": runway},
        ),
        (
            "eleven",
            "commercial_use",
            f"commercial_use:{eleven}",
            {"type": "commercial_use", "integration_id": eleven},
        ),
        (
            "sale",
            "sale_terms",
            "audit:sale_terms",
            {"type": "file_exists", "any_of": list(decision_seed.LICENCE_FILES)},
        ),
        ("google", "google_oauth_production", "audit:google_oauth_production", {"type": "never"}),
    ):
        decision_id, version = _guided(engine, kind=kind, dedupe_key=key, clears_when=clears)
        _waiting(engine, decision_id, version, settings)
        _closed_by_an_earlier_done(engine, decision_id)
        ids[name] = decision_id
    return ids


def test_the_seed_reopens_cards_an_earlier_done_closed_while_unmet_once(
    engine, settings, bare_root
):
    ids = _legacy_cards(engine, settings)
    before = {name: _row(engine, decision_id).version for name, decision_id in ids.items()}

    decision_seed.seed_owner_decisions(engine, settings)

    for name in ("runway", "eleven", "sale"):
        row = _row(engine, ids[name])
        assert row.status == "WAITING_FOR_OWNER_ACTION", name
        assert row.version == before[name] + 1
        assert "completed_by" not in row.applied
        assert row.applied["reopened_at"]
        assert row.applied["earlier_done_at"] == "2026-10-03T21:02:27.917848+00:00"
        assert row.apply_error_ro, "the card says what is still missing"
    assert "termenii planului" in _row(engine, ids["runway"]).apply_error_ro
    assert "LICENSE" in _row(engine, ids["sale"]).apply_error_ro
    # Only he can close Google's consent screen: his DONE stands.
    assert _row(engine, ids["google"]).status == "ACCEPTED"
    reopened = _events(engine, REOPENED_EVENT)
    assert sorted(e.aggregate_id for e in reopened) == sorted(
        ids[name] for name in ("runway", "eleven", "sale")
    )
    assert all(e.payload["reason_ro"] for e in reopened)

    # Once: a second seed changes nothing and adds no second card for the same question.
    decision_seed.seed_owner_decisions(engine, settings)
    assert len(_events(engine, REOPENED_EVENT)) == 3
    with Session(engine) as session:
        keys = list(session.scalars(select(OwnerDecision.dedupe_key)))
    assert len(keys) == len(set(keys)), "no duplicate card"

    # Even if a row were closed the old way again, the seed does not re-open it twice.
    _closed_by_an_earlier_done(engine, ids["sale"])
    decision_seed.seed_owner_decisions(engine, settings)
    assert _row(engine, ids["sale"]).status == "ACCEPTED"
    assert len(_events(engine, REOPENED_EVENT)) == 3


def test_the_seed_leaves_a_met_condition_and_an_open_twin_alone(engine, settings, bare_root):
    ids = _legacy_cards(engine, settings)
    # The Runway connection now says «da»: his DONE was true.
    with Session(engine) as session:
        runway_id = session.get(OwnerDecision, ids["runway"]).clears_when["integration_id"]
    _say_yes(engine, runway_id)
    # A producer already asked the ElevenLabs question again: no second open card.
    with Session(engine) as session:
        eleven = session.get(OwnerDecision, ids["eleven"])
        key, clears = eleven.dedupe_key, dict(eleven.clears_when)
    twin, _ = _guided(engine, kind="commercial_use", dedupe_key=key, clears_when=clears)

    decision_seed.seed_owner_decisions(engine, settings)
    assert _row(engine, ids["runway"]).status == "ACCEPTED"
    assert _row(engine, ids["eleven"]).status == "ACCEPTED"
    assert _row(engine, twin).status == "PENDING"
    assert _row(engine, ids["sale"]).status == "WAITING_FOR_OWNER_ACTION"


def test_the_seed_reopens_a_card_whose_condition_cannot_be_read(
    engine, settings, bare_root, monkeypatch
):
    ids = _legacy_cards(engine, settings)

    def unreadable(*_args):
        raise RuntimeError("the books are locked")

    monkeypatch.setitem(decisions.CONDITIONS, "commercial_use", unreadable)
    decision_seed.seed_owner_decisions(engine, settings)
    row = _row(engine, ids["runway"])
    assert row.status == "WAITING_FOR_OWNER_ACTION"
    assert "nu poate citi" in row.apply_error_ro


# ------------------------------------------------- adversarial review (2026-10-04, second pass)


def _unsay_yes(engine, integration_id: str) -> None:
    with Session(engine) as session, session.begin():
        row = session.get(Integration, integration_id)
        config = dict(row.config or {})
        config.pop("commercial_use", None)
        row.config = config


def test_a_done_the_studio_confirmed_is_never_reopened_when_the_condition_later_changes(
    engine, settings
):
    """The re-open repairs only the DONEs taken before DONE read the condition. A card his DONE
    closed after the studio saw the step done is not «re-opened» because the world moved on
    (a balance spent, a budget lowered, a «da» taken back): that would tell him a falsehood."""
    integration_id = _connection(engine)
    decision_id, version = _guided(
        engine,
        kind="commercial_use",
        dedupe_key=f"commercial_use:{integration_id}",
        clears_when={"type": "commercial_use", "integration_id": integration_id},
    )
    version = _waiting(engine, decision_id, version, settings)
    _say_yes(engine, integration_id)
    _answer(engine, decision_id, version, "DONE", settings)
    assert _row(engine, decision_id).status == "ACCEPTED"

    _unsay_yes(engine, integration_id)
    decision_seed.seed_owner_decisions(engine, settings)
    assert _row(engine, decision_id).status == "ACCEPTED", "a confirmed DONE stands"
    assert _events(engine, REOPENED_EVENT) == []


def test_the_seed_never_reopens_an_old_done_over_a_newer_card_he_refused(
    engine, settings, bare_root
):
    """The question was asked again on a newer card and he refused it: the older card his
    DONE closed is not brought back over his refusal, now or at any later start."""
    ids = _legacy_cards(engine, settings)
    with Session(engine) as session:
        sale = session.get(OwnerDecision, ids["sale"])
        key, clears = sale.dedupe_key, dict(sale.clears_when)
    newer, version = _guided(engine, kind="sale_terms", dedupe_key=key, clears_when=clears)
    _answer(engine, newer, version, "REFUSE", settings)
    assert _row(engine, newer).status == "REFUSED"

    decision_seed.seed_owner_decisions(engine, settings)
    decision_seed.seed_owner_decisions(engine, settings)
    assert _row(engine, ids["sale"]).status == "ACCEPTED"
    assert _row(engine, newer).status == "REFUSED"
    assert ids["sale"] not in {e.aggregate_id for e in _events(engine, REOPENED_EVENT)}


def test_a_reopened_card_he_refuses_stays_refused_at_every_later_start(engine, settings, bare_root):
    ids = _legacy_cards(engine, settings)
    decision_seed.seed_owner_decisions(engine, settings)
    row = _row(engine, ids["sale"])
    assert row.status == "WAITING_FOR_OWNER_ACTION"
    _answer(engine, ids["sale"], row.version, "REFUSE", settings)
    for _ in range(2):
        decision_seed.seed_owner_decisions(engine, settings)
        refresh_owner_decisions(engine, settings)
    assert _row(engine, ids["sale"]).status == "REFUSED"
    with Session(engine) as session:
        open_sale = session.scalars(
            select(OwnerDecision).where(
                OwnerDecision.dedupe_key == "audit:sale_terms",
                OwnerDecision.status.in_(decisions.OPEN_STATUSES),
            )
        ).all()
    assert open_sale == []


def test_an_agent_pressing_done_changes_nothing(engine, settings):
    integration_id = _connection(engine)
    decision_id, version = _guided(
        engine,
        kind="commercial_use",
        dedupe_key=f"commercial_use:{integration_id}",
        clears_when={"type": "commercial_use", "integration_id": integration_id},
    )
    version = _waiting(engine, decision_id, version, settings)
    _say_yes(engine, integration_id)  # even with the condition met, only he answers
    command = DecideCommand(command_id=uuid4(), expected_version=version, decision="DONE")
    with pytest.raises(decisions.DecisionRefused):
        decide_owner_decision(
            engine, decision_id, command, issued_by="agent:ceo", settings=settings
        )
    row = _row(engine, decision_id)
    assert row.status == "WAITING_FOR_OWNER_ACTION" and row.version == version


def test_every_readable_condition_says_what_is_missing():
    readable = set(decisions.CONDITIONS) - {"never"}
    assert readable <= set(decisions.MISSING_RO), readable - set(decisions.MISSING_RO)
