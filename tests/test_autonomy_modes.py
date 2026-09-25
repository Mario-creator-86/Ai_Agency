"""The autonomy mode is a decision the Owner makes, and the studio obeys it.

Until this suite existed the mode was `Literal["MANUAL"] = "MANUAL"` on the policy view — a
constant nothing could change, while the studio spent its whole day unattended: it chose a
topic, verified it, wrote a script the Director approved, paid a vendor for shots, cut the
film and uploaded it. The specification (51_AUTONOMY_MODE_SEMANTICS) and the behaviour had
to be made to agree, and the honest direction was to admit what the code does.

These tests hold both halves of that agreement: the Owner's command that moves the mode
(versioned, idempotent, refused while the studio is stopped or in safe mode), and the gate
the Policy Kernel asks before an agent acts, which refuses by tier according to the mode and
never opens a hard gate.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.models import ApprovalRequest, DomainEvent, OwnerPolicy
from app.schemas import AutonomyModeCommand, PolicyCommand
from app.services import (
    ACTION_RISK_TIERS,
    AutonomyRefused,
    CommandConflict,
    change_autonomy_mode,
    change_stop,
    may_act,
    snapshot,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def mode_command(version: int = 1, mode: str = "SUPERVISED") -> AutonomyModeCommand:
    return AutonomyModeCommand(command_id=uuid4(), expected_version=version, autonomy_mode=mode)


def clear_the_stop(engine) -> int:
    """Bootstrap stops autonomy; most of these tests are about a studio that may act."""
    result = change_stop(
        engine, PolicyCommand(command_id=uuid4(), expected_version=1, stopped=False)
    )
    return result.policy.version


def set_mode(engine, mode: str) -> int:
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.autonomy_mode = mode
        return policy.version


def enter_safe_mode(engine) -> None:
    """Open a safe-mode record without stopping autonomy.

    `_open_safe_mode` also sets the stop, which would hide whether the safe-mode check does
    any work of its own. The row is what the state is; writing it directly isolates it.
    """
    from app.runbook.models import SafeModeRecord
    from app.services import utc_now

    with Session(engine) as session, session.begin():
        session.add(
            SafeModeRecord(
                id=str(uuid4()),
                reason="Un test ține studioul în SAFE_MODE.",
                trigger="STAGE_FAILURE",
                run_id=None,
                entered_at=utc_now(),
                cleared_at=None,
                cleared_notes=None,
                event_id=None,
            )
        )


# --------------------------------------------------------------- the mode the studio is in --


def test_a_fresh_studio_carries_the_mode_it_actually_runs_in(engine):
    """A new database says AUTONOMOUS_CEO because that is what the code does: the daily run
    walks twelve stages with no Owner approval between them, the Director approves her own
    scripts, the media stage pays a vendor and the publish stage writes to YouTube within
    the channel policy the Owner set. Claiming MANUAL would be the lie this column exists
    to end."""
    with Session(engine) as session:
        assert session.get(OwnerPolicy, 1).autonomy_mode == "AUTONOMOUS_CEO"
    assert snapshot(engine)["policy"]["autonomy_mode"] == "AUTONOMOUS_CEO"


def test_only_the_owner_changes_the_mode(client, headers):
    body = mode_command().model_dump(mode="json")
    assert client.post("/api/v1/owner/autonomy-mode", json=body).status_code == 401
    assert client.post("/api/v1/owner/autonomy-mode", json=body, headers=headers).status_code == 200


def test_the_command_is_versioned_idempotent_and_writes_one_event(engine):
    command = mode_command(1, "SUPERVISED")
    first = change_autonomy_mode(engine, command)
    assert first.status == "COMMITTED"
    assert first.policy.autonomy_mode == "SUPERVISED"
    assert first.policy.version == 2
    assert first.event_id is not None

    retry = change_autonomy_mode(engine, command)
    assert retry.model_dump() == first.model_dump()

    with Session(engine) as session:
        events = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "owner.autonomy_mode_changed")
        ).all()
        assert len(events) == 1
        assert events[0].payload["autonomy_mode"] == "SUPERVISED"
        assert events[0].payload["previous_autonomy_mode"] == "AUTONOMOUS_CEO"


def test_the_same_mode_again_changes_nothing_and_writes_no_event(engine):
    before = snapshot(engine)["cursor"]
    result = change_autonomy_mode(engine, mode_command(1, "AUTONOMOUS_CEO"))
    assert result.status == "NO_CHANGE"
    assert result.event_id is None
    assert snapshot(engine)["cursor"] == before


def test_a_stale_version_is_refused(engine):
    change_autonomy_mode(engine, mode_command(1, "SUPERVISED"))
    with pytest.raises(CommandConflict):
        change_autonomy_mode(engine, mode_command(1, "MANUAL"))


def test_a_promotion_is_refused_while_autonomy_is_stopped(engine):
    """Bootstrap leaves the stop on. 51 says a higher mode needs acceptance criteria, a
    burn-in, no unresolved P0 and the Owner's action; the stop is the part the code can
    read, and the refusal says the rest out loud instead of pretending to have checked it."""
    set_mode(engine, "MANUAL")
    with pytest.raises(AutonomyRefused) as refused:
        change_autonomy_mode(engine, mode_command(1, "AUTONOMOUS_CEO"))
    assert "AUTONOMIA ESTE OPRITĂ" in str(refused.value)
    assert "rodaj" in str(refused.value)
    with Session(engine) as session:
        assert session.get(OwnerPolicy, 1).autonomy_mode == "MANUAL"
        assert (
            session.scalar(
                select(func.count())
                .select_from(DomainEvent)
                .where(DomainEvent.event_type == "owner.autonomy_mode_changed")
            )
            == 0
        )


def test_a_promotion_is_refused_in_safe_mode(engine):
    version = clear_the_stop(engine)
    set_mode(engine, "MANUAL")
    enter_safe_mode(engine)
    with pytest.raises(AutonomyRefused) as refused:
        change_autonomy_mode(engine, mode_command(version, "SUPERVISED"))
    assert "modul sigur" in str(refused.value)


def test_lowering_the_mode_is_always_allowed(engine):
    """51: lowering autonomy is immediate and safe. A studio that is stopped or in an
    incident must still be able to take a step down, or the safest command would be the one
    the safety state forbids."""
    enter_safe_mode(engine)
    result = change_autonomy_mode(engine, mode_command(1, "MANUAL"))
    assert result.status == "COMMITTED"
    assert result.policy.autonomy_mode == "MANUAL"


# ------------------------------------------------------------------------- the tier gate --


TIER_ACTIONS = {
    "T0": "analytics.read",
    "T1": "script.draft",
    "T2": "agent.change_model",
    "T3": "publishing.public_publish",
    "T4": "budget.change_hard_limit",
}


def test_every_action_in_the_table_has_a_tier_from_the_governance_documents():
    assert set(ACTION_RISK_TIERS.values()) == {"T0", "T1", "T2", "T3", "T4"}
    for tier, action in TIER_ACTIONS.items():
        assert ACTION_RISK_TIERS[action] == tier


@pytest.mark.parametrize(
    ("mode", "allowed_tiers"),
    [
        ("MANUAL", {"T0", "T1"}),
        ("SUPERVISED", {"T0", "T1", "T2"}),
        ("AUTONOMOUS_CEO", {"T0", "T1", "T2", "T3"}),
    ],
)
def test_each_mode_allows_exactly_the_tiers_the_specification_gives_it(engine, mode, allowed_tiers):
    clear_the_stop(engine)
    set_mode(engine, mode)
    with Session(engine) as session:
        for tier, action in TIER_ACTIONS.items():
            verdict = may_act(session, action)
            assert verdict["tier"] == tier
            assert verdict["allowed"] is (tier in allowed_tiers), (mode, tier, verdict)
            if not verdict["allowed"]:
                assert verdict["reason"]


def test_no_mode_ever_opens_a_t4_action(engine):
    clear_the_stop(engine)
    for mode in ("MANUAL", "SUPERVISED", "AUTONOMOUS_CEO"):
        set_mode(engine, mode)
        with Session(engine) as session:
            verdict = may_act(session, "credential.rotate")
            assert verdict["allowed"] is False
            assert verdict["status"] == "BLOCKED_OWNER_ONLY"
            assert "Proprietarului" in verdict["reason"]


def test_supervised_records_one_approval_request_for_an_external_write(engine):
    clear_the_stop(engine)
    set_mode(engine, "SUPERVISED")
    with Session(engine) as session, session.begin():
        first = may_act(session, "publishing.public_publish", requester="publisher")
        assert first["allowed"] is False
        assert first["status"] == "NEEDS_APPROVAL"
        assert first["approval_id"]
        # Asking twice is the same request, not a second one: a queue of duplicates would
        # make the Owner's inbox the place autonomy goes to die.
        second = may_act(session, "publishing.public_publish", requester="publisher")
        assert second["approval_id"] == first["approval_id"]
    with Session(engine) as session:
        rows = session.scalars(select(ApprovalRequest)).all()
        assert len(rows) == 1
        assert rows[0].risk_tier == "T3"
        assert rows[0].result == "PENDING"
        assert rows[0].cost_usd is None  # a cost the studio cannot compute is not zero


def test_manual_refuses_an_external_write_without_promising_an_approval(engine):
    clear_the_stop(engine)
    set_mode(engine, "MANUAL")
    with Session(engine) as session, session.begin():
        verdict = may_act(session, "publishing.public_publish")
    assert verdict["allowed"] is False
    assert verdict["status"] == "BLOCKED_MODE"
    # The mode is said in words; its code stays in the verdict's own field.
    assert "manual" in verdict["reason"] and "MANUAL" not in verdict["reason"]
    assert verdict["mode"] == "MANUAL"
    assert verdict["approval_id"] is None


def test_the_stop_outranks_every_mode(engine):
    for mode in ("MANUAL", "SUPERVISED", "AUTONOMOUS_CEO"):
        set_mode(engine, mode)
        with Session(engine) as session:
            for action in TIER_ACTIONS.values():
                verdict = may_act(session, action)
                assert verdict["allowed"] is False
                assert verdict["status"] in ("BLOCKED_STOP", "BLOCKED_OWNER_ONLY")


def test_safe_mode_leaves_monitoring_and_repair_and_takes_the_rest(engine):
    clear_the_stop(engine)
    set_mode(engine, "AUTONOMOUS_CEO")
    enter_safe_mode(engine)
    with Session(engine) as session:
        assert may_act(session, "analytics.read")["allowed"] is True
        assert may_act(session, "script.draft")["allowed"] is True
        spend = may_act(session, "agent.change_model")
        assert spend["allowed"] is False
        assert spend["status"] == "BLOCKED_SAFE_MODE"
        assert may_act(session, "publishing.public_publish")["status"] == "BLOCKED_SAFE_MODE"


def test_an_action_with_no_tier_is_refused_rather_than_guessed(engine):
    clear_the_stop(engine)
    set_mode(engine, "AUTONOMOUS_CEO")
    with Session(engine) as session:
        verdict = may_act(session, "something.nobody.classified")
        assert verdict["allowed"] is False
        assert verdict["status"] == "BLOCKED_UNCLASSIFIED"
        assert verdict["tier"] is None


def test_a_caller_cannot_lower_the_tier_of_its_own_action(engine):
    clear_the_stop(engine)
    set_mode(engine, "MANUAL")
    with Session(engine) as session:
        verdict = may_act(session, "publishing.public_publish", tier="T0")
        assert verdict["tier"] == "T3"
        assert verdict["allowed"] is False


# ------------------------------------------------------------------------- the hard gates --


def test_no_mode_opens_a_hard_gate(engine):
    """A mode decides what the studio may attempt, never what a gate concludes. The
    publishing gate is asked for a public film that has no asset and no channel policy: it
    refuses in all three modes, including the one that allows T3."""
    from app.publishing.services import evaluate_publishing_gate

    clear_the_stop(engine)
    for mode in ("MANUAL", "SUPERVISED", "AUTONOMOUS_CEO"):
        set_mode(engine, mode)
        result = evaluate_publishing_gate(
            engine,
            media_asset_id=str(uuid4()),
            channel_id=str(uuid4()),
            privacy_status="public",
        )
        assert result["eligible"] is False, mode
        assert any("policy" in reason.lower() for reason in result["reasons"]), mode
        refused = {check["check_name"] for check in result["checks"] if not check["passed"]}
        assert "POLICY_AUTHORISATION_GATE" in refused, mode


def test_the_policy_kernel_still_refuses_every_run_under_the_stop(engine):
    """The kernel's mode gate is added beside the stop check, not in front of it."""
    from types import SimpleNamespace

    from app.agents.services import PolicyKernelError, _assert_policy_allows_run

    set_mode(engine, "AUTONOMOUS_CEO")
    agent = SimpleNamespace(id=str(uuid4()), lifecycle="ACTIVE", runtime_state="IDLE")
    with Session(engine) as session:
        with pytest.raises(PolicyKernelError, match="autonomy stop"):
            _assert_policy_allows_run(session, agent, None)


def test_the_factual_gate_reaches_the_same_verdict_in_every_mode(engine):
    """The other hard gate named in 50: a claim that is not SUPPORTED blocks the film, and
    the mode has nothing to say about it. Asked about the same claim in all three modes, the
    answer and its reasons are identical — a mode decides what may be attempted, never what
    a measurement concludes."""
    from app.factual.services import evaluate_factual_gate

    claim_id = str(uuid4())
    clear_the_stop(engine)
    answers = []
    for mode in ("MANUAL", "SUPERVISED", "AUTONOMOUS_CEO"):
        set_mode(engine, mode)
        with Session(engine) as session:
            answers.append(evaluate_factual_gate(session, [claim_id]))
    assert answers[0][0] is False
    assert answers[0] == answers[1] == answers[2]


def test_a_mode_the_studio_does_not_recognise_grants_the_least(engine):
    """A row carrying something no release ever wrote — a hand-edited database, a column read
    from an older schema — must not be read as more authority than the Owner ever gave. The
    lookup falls to MANUAL's floor rather than to the mode's name, so an unknown mode allows
    T0 and T1 and refuses everything a decision of his stands behind."""
    clear_the_stop(engine)
    set_mode(engine, "FULL_SEND")
    with Session(engine) as session:
        assert may_act(session, "script.draft")["allowed"] is True
        assert may_act(session, "research.fetch_page")["allowed"] is False
        upload = may_act(session, "publishing.public_publish")
        assert upload["allowed"] is False
        # Not an approval either: SUPERVISED is a mode the Owner chose, and this is not it.
        assert upload["status"] == "BLOCKED_MODE"
        assert upload["approval_id"] is None
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ApprovalRequest)) == 0
