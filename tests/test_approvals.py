"""The Owner answers an approval, and the studio acts on the answer exactly once.

Until this suite existed a SUPERVISED studio wrote one `owner_approval_request` for the
upload it may not make on its own and then stopped: there was no route to approve or refuse
one, nothing consumed an APPROVED row and no stage re-attempted after one appeared. It
recorded the question and never heard the answer.

Worse, the request was keyed by its `action` alone, so the second, dearer film of the day
reused the first film's row. An answering route on top of that would have let the Owner's
"yes" to a four-dollar film authorise a forty-dollar one — the first test below is that
defect, and every other test here stands on it being closed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.models import ApprovalRequest, DomainEvent, OwnerPolicy
from app.schemas import ApprovalDecisionCommand, PolicyCommand
from app.services import (
    ApprovalClosed,
    ApprovalMissing,
    change_stop,
    decide_approval,
    may_act,
    pending_approvals,
    utc_now,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

PUBLISH = "publishing.public_publish"
DEAR_RENDER = "media.paid_generation_over_threshold"


def a_studio_that_asks(engine, mode: str = "SUPERVISED") -> None:
    """Autonomy on and the mode the Owner set: the state in which a T3 action asks him."""
    change_stop(engine, PolicyCommand(command_id=uuid4(), expected_version=1, stopped=False))
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_mode = mode


def ask(engine, action: str, subject: str, **kwargs) -> dict:
    """One `may_act` in its own transaction, as every caller in the daily run asks it."""
    with Session(engine) as session, session.begin():
        return may_act(session, action, requester="publisher", subject=subject, **kwargs)


def answer(engine, approval_id: str, decision: str, note: str | None = None):
    return decide_approval(
        engine,
        ApprovalDecisionCommand(
            command_id=uuid4(), approval_id=approval_id, decision=decision, note=note
        ),
    )


def rows(engine) -> list[ApprovalRequest]:
    with Session(engine) as session:
        return list(session.scalars(select(ApprovalRequest)))


def age_out(engine, approval_id: str) -> None:
    """Put a request's expiry in the past, the way a day passing would."""
    with Session(engine) as session, session.begin():
        request = session.get(ApprovalRequest, approval_id)
        request.expires_at = (datetime.now(UTC) - timedelta(hours=1)).isoformat()


# ------------------------------------------------- the defect the answering route stands on --


def test_two_films_never_share_one_answer(engine):
    """The Phase D/G verifier's defect: a request keyed by `action` alone meant the second,
    dearer film of the day reused the first film's row, so one "yes" would have covered
    both. A request is about a *thing* — this film, this storyboard — and the key says so."""
    a_studio_that_asks(engine)

    cheap = ask(engine, DEAR_RENDER, "board-cheap", cost_usd=4.0)
    dear = ask(engine, DEAR_RENDER, "board-dear", cost_usd=40.0)

    assert cheap["status"] == dear["status"] == "NEEDS_APPROVAL"
    assert cheap["approval_id"] != dear["approval_id"]
    by_subject = {row.subject: row for row in rows(engine)}
    assert set(by_subject) == {"board-cheap", "board-dear"}
    # Each row carries its own film's figure; the Owner is never shown one film's price
    # under another film's question.
    assert by_subject["board-cheap"].cost_usd == 4.0
    assert by_subject["board-dear"].cost_usd == 40.0

    answer(engine, cheap["approval_id"], "APPROVED")

    assert ask(engine, DEAR_RENDER, "board-cheap")["allowed"] is True
    still_asking = ask(engine, DEAR_RENDER, "board-dear", cost_usd=40.0)
    assert still_asking["allowed"] is False
    assert still_asking["status"] == "NEEDS_APPROVAL"
    assert still_asking["approval_id"] == dear["approval_id"]


def test_the_same_film_asking_twice_is_still_one_question(engine):
    """Keying by the thing must not undo the reason the key existed: the same film asked
    about twice in one day is one row in the Owner's inbox, not two."""
    a_studio_that_asks(engine)

    first = ask(engine, PUBLISH, "asset-1")
    second = ask(engine, PUBLISH, "asset-1")

    assert first["approval_id"] == second["approval_id"]
    assert len(rows(engine)) == 1


# ------------------------------------------------------------ what the Owner is shown --


def test_the_list_shows_only_pending_unexpired_requests_newest_first(engine):
    a_studio_that_asks(engine)
    old = ask(engine, PUBLISH, "asset-old")["approval_id"]
    answered = ask(engine, DEAR_RENDER, "board-answered", cost_usd=9.0)["approval_id"]
    fresh = ask(engine, PUBLISH, "asset-fresh")["approval_id"]
    answer(engine, answered, "REFUSED")
    expired = ask(engine, DEAR_RENDER, "board-expired", cost_usd=1.0)["approval_id"]
    age_out(engine, expired)

    listed = pending_approvals(engine)

    assert [entry.id for entry in listed] == [fresh, old]


def test_the_list_says_what_the_owner_needs_to_decide(engine):
    a_studio_that_asks(engine)
    priced = ask(engine, DEAR_RENDER, "board-1", cost_usd=12.5, evidence="board-1, estimat 12.5")
    unpriced = ask(engine, PUBLISH, "asset-1", evidence="Un film → Canal A (private)")

    listed = {entry.id: entry for entry in pending_approvals(engine)}

    dear = listed[priced["approval_id"]]
    assert dear.risk_tier == "T3"
    assert dear.requester == "publisher"
    assert dear.evidence == "board-1, estimat 12.5"
    assert dear.cost_usd == 12.5
    assert dear.cost_label == "12.5 USD"
    # Romanian, because the Owner reads this list; the action's code name is beside it for
    # whoever has to find the call site.
    assert dear.action == DEAR_RENDER
    assert "randat" in dear.action_label.lower()
    assert dear.expires_at > utc_now()

    # A cost the studio cannot compute is None, and the word for it is not "0 USD".
    upload = listed[unpriced["approval_id"]]
    assert upload.cost_usd is None
    assert upload.cost_label == "necunoscut"
    assert "public" in upload.action_label.lower()


def test_only_the_owner_reads_and_answers_approvals(client, headers, engine):
    a_studio_that_asks(engine)
    request = ask(engine, PUBLISH, "asset-1")
    body = ApprovalDecisionCommand(
        command_id=uuid4(), approval_id=request["approval_id"], decision="APPROVED"
    ).model_dump(mode="json")

    assert client.get("/api/v1/owner/approvals").status_code == 401
    assert client.post("/api/v1/owner/approvals/decision", json=body).status_code == 401

    listed = client.get("/api/v1/owner/approvals", headers=headers)
    assert listed.status_code == 200
    assert [entry["id"] for entry in listed.json()] == [request["approval_id"]]
    decided = client.post("/api/v1/owner/approvals/decision", json=body, headers=headers)
    assert decided.status_code == 200
    assert decided.json()["approval"]["result"] == "APPROVED"
    assert client.get("/api/v1/owner/approvals", headers=headers).json() == []


# ---------------------------------------------------------------- the Owner's command --


def test_answering_is_idempotent_and_writes_one_event_with_both_states(engine):
    a_studio_that_asks(engine)
    request = ask(engine, PUBLISH, "asset-1")["approval_id"]
    command = ApprovalDecisionCommand(
        command_id=uuid4(), approval_id=request, decision="REFUSED", note="Nu filmul acesta."
    )

    first = decide_approval(engine, command)
    second = decide_approval(engine, command)

    assert first.status == "COMMITTED"
    assert first.approval.result == "REFUSED"
    assert first.approval.note == "Nu filmul acesta."
    assert first.approval.approver == "owner"
    assert first.approval.decided_at is not None
    assert second.model_dump() == first.model_dump()
    with Session(engine) as session:
        events = list(
            session.scalars(
                select(DomainEvent).where(DomainEvent.event_type == "governance.approval_decided")
            )
        )
    assert len(events) == 1
    assert events[0].payload["previous_result"] == "PENDING"
    assert events[0].payload["result"] == "REFUSED"
    assert events[0].payload["action"] == PUBLISH
    assert events[0].payload["subject"] == "asset-1"
    assert events[0].event_id == first.event_id


def test_the_same_command_id_with_another_answer_is_refused(client, headers, engine):
    from app.services import CommandConflict

    a_studio_that_asks(engine)
    first_request = ask(engine, PUBLISH, "asset-1")["approval_id"]
    second_request = ask(engine, PUBLISH, "asset-2")["approval_id"]
    command_id = uuid4()
    decide_approval(
        engine,
        ApprovalDecisionCommand(
            command_id=command_id, approval_id=first_request, decision="APPROVED"
        ),
    )

    with pytest.raises(CommandConflict):
        decide_approval(
            engine,
            ApprovalDecisionCommand(
                command_id=command_id, approval_id=second_request, decision="APPROVED"
            ),
        )
    body = ApprovalDecisionCommand(
        command_id=command_id, approval_id=second_request, decision="APPROVED"
    ).model_dump(mode="json")
    answered = client.post("/api/v1/owner/approvals/decision", json=body, headers=headers)
    assert answered.status_code == 409


def test_a_request_already_answered_cannot_be_answered_again(client, headers, engine):
    a_studio_that_asks(engine)
    request = ask(engine, PUBLISH, "asset-1")["approval_id"]
    answer(engine, request, "REFUSED")

    with pytest.raises(ApprovalClosed) as refused:
        answer(engine, request, "APPROVED")
    assert "REFUSED" in str(refused.value)

    body = ApprovalDecisionCommand(
        command_id=uuid4(), approval_id=request, decision="APPROVED"
    ).model_dump(mode="json")
    response = client.post("/api/v1/owner/approvals/decision", json=body, headers=headers)
    assert response.status_code == 409
    with Session(engine) as session:
        assert session.get(ApprovalRequest, request).result == "REFUSED"


def test_an_expired_request_cannot_be_answered(client, headers, engine):
    """31: an expired approval cannot be reused. It cannot be *given* either — answering a
    question the studio has stopped waiting on would authorise something nobody asked."""
    a_studio_that_asks(engine)
    request = ask(engine, PUBLISH, "asset-1")["approval_id"]
    age_out(engine, request)

    with pytest.raises(ApprovalClosed):
        answer(engine, request, "APPROVED")
    body = ApprovalDecisionCommand(
        command_id=uuid4(), approval_id=request, decision="APPROVED"
    ).model_dump(mode="json")
    answered = client.post("/api/v1/owner/approvals/decision", json=body, headers=headers)
    assert answered.status_code == 409
    with Session(engine) as session:
        assert session.get(ApprovalRequest, request).result != "APPROVED"


def test_a_request_the_studio_never_made_is_not_found(client, headers, engine):
    a_studio_that_asks(engine)
    missing = str(uuid4())

    with pytest.raises(ApprovalMissing):
        answer(engine, missing, "APPROVED")
    body = ApprovalDecisionCommand(
        command_id=uuid4(), approval_id=missing, decision="APPROVED"
    ).model_dump(mode="json")
    answered = client.post("/api/v1/owner/approvals/decision", json=body, headers=headers)
    assert answered.status_code == 404


# ------------------------------------------------------- the studio acts on the answer --


def test_an_approval_is_spent_once_and_never_covers_a_second_day(engine):
    a_studio_that_asks(engine)
    request = ask(engine, PUBLISH, "asset-1")["approval_id"]
    answer(engine, request, "APPROVED")

    used = ask(engine, PUBLISH, "asset-1")
    again = ask(engine, PUBLISH, "asset-1")

    assert used["allowed"] is True
    assert used["approval_id"] == request
    with Session(engine) as session:
        spent = session.get(ApprovalRequest, request)
        assert spent.consumed_at is not None
        assert spent.result == "APPROVED"
        consumed_events = list(
            session.scalars(
                select(DomainEvent).where(DomainEvent.event_type == "governance.approval_consumed")
            )
        )
    assert len(consumed_events) == 1
    # Tomorrow's run finds the yes spent and asks again rather than uploading on it.
    assert again["allowed"] is False
    assert again["status"] == "NEEDS_APPROVAL"
    assert again["approval_id"] != request


def test_a_refusal_is_the_answer_and_the_studio_does_not_ask_again_today(engine):
    a_studio_that_asks(engine)
    request = ask(engine, PUBLISH, "asset-1")["approval_id"]
    answer(engine, request, "REFUSED", note="Nu vreau filmul acesta pe canal.")

    verdict = ask(engine, PUBLISH, "asset-1")

    assert verdict["allowed"] is False
    assert verdict["status"] == "REFUSED_BY_OWNER"
    assert verdict["approval_id"] == request
    assert "refuzat" in verdict["reason"].lower()
    assert "Nu vreau filmul acesta pe canal." in verdict["reason"]
    # No second question: the row the Owner answered is the only one there is.
    assert len(rows(engine)) == 1
    # And the refusal is about this film only.
    assert ask(engine, PUBLISH, "asset-2")["status"] == "NEEDS_APPROVAL"


def test_a_refusal_that_has_expired_lets_the_studio_ask_again(engine):
    a_studio_that_asks(engine)
    request = ask(engine, PUBLISH, "asset-1")["approval_id"]
    answer(engine, request, "REFUSED")
    age_out(engine, request)

    verdict = ask(engine, PUBLISH, "asset-1")

    assert verdict["status"] == "NEEDS_APPROVAL"
    assert verdict["approval_id"] != request


@pytest.mark.parametrize("hard_gate", ["STOP", "SAFE_MODE"])
def test_a_stop_or_an_incident_after_an_approval_still_refuses_and_leaves_the_yes_unspent(
    engine, hard_gate
):
    """An approval lets a permitted action happen; it never turns a refusal into a pass.
    STOP and SAFE_MODE are read before the answer is even looked for, so the yes is still
    there, unspent, when the Owner lifts the stop or the incident closes."""
    from app.runbook.models import SafeModeRecord

    a_studio_that_asks(engine)
    request = ask(engine, PUBLISH, "asset-1")["approval_id"]
    answer(engine, request, "APPROVED")
    if hard_gate == "STOP":
        with Session(engine) as session, session.begin():
            session.get(OwnerPolicy, 1).autonomy_stopped = True
    else:
        with Session(engine) as session, session.begin():
            session.add(
                SafeModeRecord(
                    id=str(uuid4()),
                    reason="Un incident ține studioul în SAFE_MODE.",
                    trigger="STAGE_FAILURE",
                    run_id=None,
                    entered_at=utc_now(),
                    cleared_at=None,
                    cleared_notes=None,
                    event_id=None,
                )
            )

    verdict = ask(engine, PUBLISH, "asset-1")

    assert verdict["allowed"] is False
    assert verdict["status"] == ("BLOCKED_STOP" if hard_gate == "STOP" else "BLOCKED_SAFE_MODE")
    with Session(engine) as session:
        assert session.get(ApprovalRequest, request).consumed_at is None


def test_an_expired_approval_is_not_consumed(engine):
    a_studio_that_asks(engine)
    request = ask(engine, PUBLISH, "asset-1")["approval_id"]
    answer(engine, request, "APPROVED")
    age_out(engine, request)

    verdict = ask(engine, PUBLISH, "asset-1")

    assert verdict["allowed"] is False
    assert verdict["status"] == "NEEDS_APPROVAL"
    assert verdict["approval_id"] != request
    with Session(engine) as session:
        # The Owner's answer stays on the record; it is simply too old to act on.
        aged = session.get(ApprovalRequest, request)
        assert aged.result == "APPROVED"
        assert aged.consumed_at is None


def test_an_approval_given_under_another_policy_is_not_consumed(engine):
    """The Owner said yes to an upload under the channel policy he had then. If the policy
    version moved after he answered, the yes was given about something else."""
    a_studio_that_asks(engine)
    given = ask(engine, PUBLISH, "asset-1", context={"channel_id": "A", "policy_version": 1})
    answer(engine, given["approval_id"], "APPROVED")

    verdict = ask(engine, PUBLISH, "asset-1", context={"channel_id": "A", "policy_version": 2})

    assert verdict["allowed"] is False
    assert verdict["status"] == "NEEDS_APPROVAL"
    assert verdict["approval_id"] != given["approval_id"]
    with Session(engine) as session:
        assert session.get(ApprovalRequest, given["approval_id"]).consumed_at is None
        fresh = session.get(ApprovalRequest, verdict["approval_id"])
        assert fresh.proposed_diff == {"channel_id": "A", "policy_version": 2}


def test_an_approval_never_lifts_a_mode_that_was_not_asking(engine):
    """MANUAL refuses a T3 action outright and raises no request; an APPROVED row left from
    a SUPERVISED day must not become a way past a mode the Owner has since lowered."""
    a_studio_that_asks(engine)
    request = ask(engine, PUBLISH, "asset-1")["approval_id"]
    answer(engine, request, "APPROVED")
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_mode = "MANUAL"

    verdict = ask(engine, PUBLISH, "asset-1")

    assert verdict["allowed"] is False
    assert verdict["status"] == "BLOCKED_MODE"
    with Session(engine) as session:
        assert session.get(ApprovalRequest, request).consumed_at is None


# ------------------------------- the letter says the same thing about the same figure --


def _owner_letter(engine, kind: str):
    """The one letter of a kind the Accountant's desk wrote today, or None."""
    from app.agents.models import AgentMessage

    with Session(engine) as session:
        letters = [
            message
            for message in session.scalars(select(AgentMessage))
            if isinstance(message.body_json, dict) and message.body_json.get("kind") == kind
        ]
        assert len(letters) <= 1, "one letter of a kind a day"
        return letters[0] if letters else None


def test_the_letter_repeats_the_caveat_beside_a_cost_that_is_not_the_whole_film(engine):
    """A figure that reads as complete is the worst of the three outcomes.

    Measured before this: the caveat `estimate_film_cost_micros` produced reached the
    reservation's note and nothing else, so the letter about the waiting question said
    «cost 4.2 USD» about a film whose narration had been counted as nothing. The letter now
    carries the stage's own words, beside the figure rather than under it.
    """
    from app.agents.services import seed_initial_workforce
    from app.economy.accountant import waiting_approvals_letter
    from app.economy.budget import UNPRICED_CAVEAT_PREFIX, unpriced_caveat
    from app.services import request_approval

    seed_initial_workforce(engine)
    a_studio_that_asks(engine)
    caveat = unpriced_caveat(["narration"])
    with Session(engine) as session, session.begin():
        request_approval(
            session,
            DEAR_RENDER,
            "T3",
            "video_editor",
            subject="storyboard-1",
            evidence=f"storyboard storyboard-1, estimat 4.200000 USD ({caveat})",
            cost_usd=4.2,
        )

    written = waiting_approvals_letter(engine, str(uuid4()))

    assert written["written"] is True and written["questions"] == 1
    letter = _owner_letter(engine, "owner_waiting")
    assert letter is not None
    assert f"cost 4.2 USD ({UNPRICED_CAVEAT_PREFIX}" in (letter.body_text or ""), letter.body_text
    assert "narația" in (letter.body_text or "")
    # Once, and whole. The evidence line is clipped at 120 characters in the letter, which cut
    # the caveat mid-sentence when it was left inside it.
    assert (letter.body_text or "").count(UNPRICED_CAVEAT_PREFIX) == 1
    assert caveat in (letter.body_text or "")
    # And as data beside the figure, so nothing downstream has to read the sentence back out
    # of a line written for a human.
    assert letter.body_json["questions"][0]["cost_caveat"] == caveat


def test_a_question_whose_figure_is_whole_carries_no_caveat(engine):
    """The caveat is a measurement, not a disclaimer: a question about a complete estimate
    must read as complete, or the Owner learns to skip the words."""
    from app.agents.services import seed_initial_workforce
    from app.economy.accountant import waiting_approvals_letter
    from app.economy.budget import UNPRICED_CAVEAT_PREFIX
    from app.services import request_approval

    seed_initial_workforce(engine)
    a_studio_that_asks(engine)
    with Session(engine) as session, session.begin():
        request_approval(
            session,
            DEAR_RENDER,
            "T3",
            "video_editor",
            subject="storyboard-2",
            evidence="storyboard storyboard-2, estimat 4.200000 USD",
            cost_usd=4.2,
        )

    waiting_approvals_letter(engine, str(uuid4()))

    letter = _owner_letter(engine, "owner_waiting")
    assert letter is not None
    assert UNPRICED_CAVEAT_PREFIX not in (letter.body_text or "")
    assert letter.body_json["questions"][0]["cost_caveat"] == ""


# ------------------------------------------ the Owner's gate on every paid media step --
#
# The Nepal film (2026-09-26): the second full render started from a button, showed no
# price and asked nothing, because a T3 media purchase in AUTONOMOUS_CEO is simply ALLOWED
# by the mode. `owner_policy.paid_media_approval` (migration 0048) is read inside `may_act`
# for the four paid media steps, after the stop, the unclassified check, T4 and safe mode,
# and before the mode's ALLOWED return. Each answer is bound to the plan it was given about.

STILLS = "media.stills_purchase"
TEST_SHOT = "media.test_shot"
MOTION = "media.motion_purchase"
REDO = "media.scene_redo"
PLAN_A = "a" * 64
PLAN_B = "b" * 64


def plan(plan_hash: str = PLAN_A, step: str = "motion", cap_credits: int = 2190) -> dict:
    return {"plan_hash": plan_hash, "step": step, "cap_credits": cap_credits}


def paid_policy(engine, value: str = "EVERY_PAID_STEP", over_usd: float | None = None) -> None:
    """Set the field directly, the way a test sets the mode; the command is tested below."""
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.paid_media_approval = value
        policy.paid_media_approval_over_usd = over_usd


def test_every_paid_step_asks_even_the_autonomous_ceo_and_names_the_plan(engine):
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    paid_policy(engine, "EVERY_PAID_STEP")

    verdict = ask(engine, MOTION, "board-nepal", cost_usd=12.24, context=plan())

    assert verdict["allowed"] is False
    assert verdict["status"] == "NEEDS_APPROVAL"
    assert verdict["approval_id"]
    written = rows(engine)
    assert len(written) == 1
    request = written[0]
    assert request.id == verdict["approval_id"]
    assert request.action == MOTION
    assert request.subject == "board-nepal"
    assert request.risk_tier == "T3"
    assert request.cost_usd == 12.24
    assert request.proposed_diff == {"plan_hash": PLAN_A, "step": "motion", "cap_credits": 2190}
    assert request.result == "PENDING"
    # Romanian, and it names the Owner's policy rather than the mode.
    assert "pas plătit" in verdict["reason"]


def test_the_default_policy_is_the_strict_one(engine):
    """A studio bootstrapped today asks before every paid step without anyone setting it."""
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")

    verdict = ask(engine, TEST_SHOT, "board-1", cost_usd=3.4, context=plan(step="test_shot"))

    assert verdict["status"] == "NEEDS_APPROVAL"


@pytest.mark.parametrize("mode", ["MANUAL", "SUPERVISED", "AUTONOMOUS_CEO"])
@pytest.mark.parametrize("action", [STILLS, TEST_SHOT, MOTION, REDO])
def test_every_paid_step_asks_in_every_mode(engine, mode, action):
    a_studio_that_asks(engine, mode)
    paid_policy(engine, "EVERY_PAID_STEP")

    verdict = ask(engine, action, "board-1", cost_usd=1.0, context={"plan_hash": PLAN_A})

    assert verdict["status"] == "NEEDS_APPROVAL"
    assert verdict["approval_id"] is not None


# ------------------------------------- Owner 2026-10-05: free generation never waits ------
#
# «Pe CEO autonom îmi cere acordul DOAR dacă generează imagini sau video cu bani; altfel
# totul se face automat.» A paid-media step whose cap is exactly 0 — the local ComfyUI
# selection — cannot spend anything, so under AUTONOMOUS_CEO the mode alone decides it and
# no question is written, whatever `paid_media_approval` says. A step that can spend even a
# cent still asks, and outside AUTONOMOUS_CEO nothing changes.


def test_a_zero_cap_step_runs_without_asking_the_autonomous_ceo(engine):
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    paid_policy(engine, "EVERY_PAID_STEP")

    verdict = ask(engine, MOTION, "board-1", cost_usd=0, context=plan())

    assert verdict == {
        "action": MOTION,
        "tier": "T3",
        "mode": "AUTONOMOUS_CEO",
        "allowed": True,
        "status": "ALLOWED",
        "reason": "",
        "approval_id": None,
    }
    assert rows(engine) == [], "a free step wrote the Owner a question"


@pytest.mark.parametrize("action", [STILLS, TEST_SHOT, REDO])
def test_every_free_step_is_automatic_for_the_autonomous_ceo(engine, action):
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    paid_policy(engine, "EVERY_PAID_STEP")

    verdict = ask(engine, action, "board-1", cost_usd=0.0, context={"plan_hash": PLAN_A})

    assert verdict["allowed"] is True
    assert rows(engine) == []


@pytest.mark.parametrize("mode", ["MANUAL", "SUPERVISED"])
def test_a_free_step_still_asks_outside_the_autonomous_ceo(engine, mode):
    """His rule names the CEO-autonomous mode; the modes he chose to be asked stay asking."""
    a_studio_that_asks(engine, mode)
    paid_policy(engine, "EVERY_PAID_STEP")

    verdict = ask(engine, MOTION, "board-1", cost_usd=0, context=plan())

    assert verdict["allowed"] is False
    assert verdict["status"] == "NEEDS_APPROVAL"
    assert len(rows(engine)) == 1


def test_a_step_that_can_spend_still_asks_the_autonomous_ceo(engine):
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    paid_policy(engine, "EVERY_PAID_STEP")

    verdict = ask(engine, MOTION, "board-1", cost_usd=0.01, context=plan())

    assert verdict["status"] == "NEEDS_APPROVAL"


def test_a_free_step_without_a_plan_is_still_not_reasoned_about(engine):
    """Free or not, the studio acts only on the plan of his it can name."""
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    paid_policy(engine, "EVERY_PAID_STEP")

    verdict = ask(engine, MOTION, "board-1", cost_usd=0, context=None)

    assert verdict["status"] == "BLOCKED_NO_PLAN"
    assert rows(engine) == []


def test_a_free_step_needs_no_daily_budget_in_production(engine):
    """MONEY-06's fail-closed guards unasked SPENDING; a 0-cap step spends nothing, so the
    missing daily budget does not block it."""
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    paid_policy(engine, "EVERY_PAID_STEP")
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).environment = "PRODUCTION"

    verdict = ask(engine, MOTION, "board-1", cost_usd=0, context=plan())

    assert verdict["allowed"] is True
    assert rows(engine) == []


def test_the_step_is_named_by_the_action_when_the_caller_leaves_it_out(engine):
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")

    verdict = ask(engine, STILLS, "board-1", cost_usd=0.72, context={"plan_hash": PLAN_A})

    with Session(engine) as session:
        request = session.get(ApprovalRequest, verdict["approval_id"])
        assert request.proposed_diff == {"plan_hash": PLAN_A, "step": "stills", "cap_credits": None}


def test_a_paid_step_without_a_plan_hash_is_refused_and_writes_nothing(engine):
    """An answer not bound to a plan could be spent on any plan: the gate will not ask it."""
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")

    for context in (None, {}, {"step": "motion"}, {"plan_hash": ""}, {"plan_hash": 7}):
        verdict = ask(engine, MOTION, "board-1", cost_usd=5.0, context=context)
        assert verdict["allowed"] is False
        assert verdict["status"] == "BLOCKED_NO_PLAN"
        assert "foaia de filmare" in verdict["reason"]
    assert rows(engine) == []


def test_a_step_the_caller_names_wrongly_is_refused(engine):
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")

    verdict = ask(engine, MOTION, "board-1", cost_usd=5.0, context=plan(step="stills"))

    assert verdict["status"] == "BLOCKED_NO_PLAN"
    assert rows(engine) == []


def test_a_yes_for_one_plan_never_buys_another(engine):
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    first = ask(engine, MOTION, "board-1", cost_usd=12.24, context=plan(PLAN_A))
    answer(engine, first["approval_id"], "APPROVED", note="Da, doar acest plan.")

    other = ask(engine, MOTION, "board-1", cost_usd=12.24, context=plan(PLAN_B))

    assert other["allowed"] is False
    assert other["status"] == "NEEDS_APPROVAL"
    assert other["approval_id"] != first["approval_id"]
    with Session(engine) as session:
        assert session.get(ApprovalRequest, first["approval_id"]).consumed_at is None
        fresh = session.get(ApprovalRequest, other["approval_id"])
        assert fresh.proposed_diff["plan_hash"] == PLAN_B


def test_a_yes_under_one_cap_never_buys_a_higher_cap(engine):
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    first = ask(engine, MOTION, "board-1", cost_usd=12.24, context=plan(cap_credits=2190))
    answer(engine, first["approval_id"], "APPROVED")

    dearer = ask(engine, MOTION, "board-1", cost_usd=12.24, context=plan(cap_credits=4000))

    assert dearer["status"] == "NEEDS_APPROVAL"
    assert dearer["approval_id"] != first["approval_id"]


def test_a_yes_buys_exactly_one_step_and_is_spent_before_the_purchase(engine):
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    asked = ask(engine, MOTION, "board-1", cost_usd=12.24, context=plan())
    answer(engine, asked["approval_id"], "APPROVED")

    # The purchase happens after `may_act` returns, in the caller's code: by then the yes
    # must already be marked spent in the same transaction, so a crash mid-purchase cannot
    # leave a second free attempt behind.
    with Session(engine) as session, session.begin():
        bought = may_act(session, MOTION, subject="board-1", cost_usd=12.24, context=plan())
        assert bought["status"] == "ALLOWED"
        assert bought["approval_id"] == asked["approval_id"]
        assert session.get(ApprovalRequest, asked["approval_id"]).consumed_at is not None

    again = ask(engine, MOTION, "board-1", cost_usd=12.24, context=plan())

    assert again["allowed"] is False
    assert again["status"] == "NEEDS_APPROVAL"
    assert again["approval_id"] != asked["approval_id"]
    with Session(engine) as session:
        consumed = list(
            session.scalars(
                select(DomainEvent).where(DomainEvent.event_type == "governance.approval_consumed")
            )
        )
    assert len(consumed) == 1
    assert consumed[0].payload["action"] == MOTION


def test_a_yes_for_the_stills_does_not_buy_the_motion(engine):
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    stills = ask(engine, STILLS, "board-1", cost_usd=0.72, context=plan(step="stills"))
    answer(engine, stills["approval_id"], "APPROVED")

    motion = ask(engine, MOTION, "board-1", cost_usd=12.24, context=plan(step="motion"))

    assert motion["status"] == "NEEDS_APPROVAL"
    with Session(engine) as session:
        assert session.get(ApprovalRequest, stills["approval_id"]).consumed_at is None


def test_a_no_on_the_sheet_is_the_answer_for_that_plan(engine):
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    asked = ask(engine, MOTION, "board-1", cost_usd=12.24, context=plan())
    answer(engine, asked["approval_id"], "REFUSED", note="Prea scump.")

    verdict = ask(engine, MOTION, "board-1", cost_usd=12.24, context=plan())

    assert verdict["status"] == "REFUSED_BY_OWNER"
    assert "Prea scump." in verdict["reason"]
    assert len(rows(engine)) == 1


def test_asking_without_writing_leaves_the_owner_alone(engine):
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    asked = ask(engine, MOTION, "board-1", cost_usd=12.24, context=plan())
    answer(engine, asked["approval_id"], "APPROVED")

    verdict = ask(engine, MOTION, "board-1", cost_usd=12.24, context=plan(), ask_owner=False)

    assert verdict["status"] == "NEEDS_APPROVAL"
    assert verdict["approval_id"] is None
    assert len(rows(engine)) == 1
    with Session(engine) as session:
        assert session.get(ApprovalRequest, asked["approval_id"]).consumed_at is None


@pytest.mark.parametrize("hard_gate", ["STOP", "SAFE_MODE", "T4"])
def test_the_hard_gates_still_refuse_before_the_paid_media_gate_and_leave_the_yes_unspent(
    engine, hard_gate
):
    from app.runbook.models import SafeModeRecord

    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    asked = ask(engine, MOTION, "board-1", cost_usd=12.24, context=plan())
    answer(engine, asked["approval_id"], "APPROVED")
    extra: dict = {}
    if hard_gate == "STOP":
        with Session(engine) as session, session.begin():
            session.get(OwnerPolicy, 1).autonomy_stopped = True
    elif hard_gate == "SAFE_MODE":
        with Session(engine) as session, session.begin():
            session.add(
                SafeModeRecord(
                    id=str(uuid4()),
                    reason="Un incident ține studioul în SAFE_MODE.",
                    trigger="STAGE_FAILURE",
                    run_id=None,
                    entered_at=utc_now(),
                    cleared_at=None,
                    cleared_notes=None,
                    event_id=None,
                )
            )
    else:
        # A caller's tier is only ever taken upward, and T4 is nobody's but the Owner's.
        extra = {"tier": "T4"}

    with Session(engine) as session, session.begin():
        verdict = may_act(
            session, MOTION, subject="board-1", cost_usd=12.24, context=plan(), **extra
        )

    assert verdict["allowed"] is False
    assert (
        verdict["status"]
        == {
            "STOP": "BLOCKED_STOP",
            "SAFE_MODE": "BLOCKED_SAFE_MODE",
            "T4": "BLOCKED_OWNER_ONLY",
        }[hard_gate]
    )
    with Session(engine) as session:
        assert session.get(ApprovalRequest, asked["approval_id"]).consumed_at is None
    assert len(rows(engine)) == 1


def test_an_unclassified_paid_action_is_refused_before_the_gate(engine):
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")

    verdict = ask(engine, "media.stills_purchase_v2", "board-1", cost_usd=1.0, context=plan())

    assert verdict["status"] == "BLOCKED_UNCLASSIFIED"
    assert rows(engine) == []


def test_the_paid_media_steps_have_their_tiers_and_romanian_names():
    from app.services import (
        ACTION_RISK_TIERS,
        APPROVAL_ACTION_LABELS,
        PAID_MEDIA_STEPS,
    )

    assert ACTION_RISK_TIERS[STILLS] == "T2"
    assert ACTION_RISK_TIERS[TEST_SHOT] == "T3"
    assert ACTION_RISK_TIERS[MOTION] == "T3"
    assert ACTION_RISK_TIERS[REDO] == "T3"
    assert PAID_MEDIA_STEPS == {
        STILLS: "stills",
        TEST_SHOT: "test_shot",
        MOTION: "motion",
        REDO: "scene_redo",
    }
    for action in PAID_MEDIA_STEPS:
        assert ACTION_RISK_TIERS[action] != "T4"
        label = APPROVAL_ACTION_LABELS[action]
        assert label and label != action
        # Romanian: no English step names leak into what the Owner reads.
        assert not any(word in label.lower() for word in ("purchase", "shot", "redo", "stills"))


def test_a_request_parameter_cannot_loosen_the_gate(engine):
    """Nothing the caller passes changes the Owner's setting: not the context, not a tier."""
    import inspect

    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    loose = {**plan(), "paid_media_approval": "MODE"}

    verdict = ask(engine, MOTION, "board-1", cost_usd=1.0, context=loose)
    lowered = ask(engine, MOTION, "board-2", tier="T1", cost_usd=1.0, context=plan())

    assert verdict["status"] == lowered["status"] == "NEEDS_APPROVAL"
    assert "paid_media_approval" not in inspect.signature(may_act).parameters


# -------------------------------------------------------------- OVER_USD and MODE --


def test_over_usd_asks_only_above_the_threshold(engine):
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    paid_policy(engine, "OVER_USD", 5.0)

    cheap = ask(engine, STILLS, "board-1", cost_usd=0.72, context=plan(step="stills"))
    at_the_line = ask(engine, TEST_SHOT, "board-1", cost_usd=5.0, context=plan(step="test_shot"))
    dear = ask(engine, MOTION, "board-1", cost_usd=12.24, context=plan())
    unknown = ask(engine, REDO, "board-1", cost_usd=None, context=plan(step="scene_redo"))

    assert cheap["status"] == "ALLOWED" and cheap["approval_id"] is None
    assert at_the_line["status"] == "ALLOWED"
    assert dear["status"] == "NEEDS_APPROVAL"
    assert "5" in dear["reason"] and "12,24" in dear["reason"]
    # A cost nobody could compute is not below any threshold.
    assert unknown["status"] == "NEEDS_APPROVAL"
    assert "necunoscut" in unknown["reason"]
    assert {row.action for row in rows(engine)} == {MOTION, REDO}


def test_over_usd_below_the_threshold_still_obeys_the_mode(engine):
    """Below his threshold the Owner hands the step back to the mode, not past it."""
    a_studio_that_asks(engine, "MANUAL")
    paid_policy(engine, "OVER_USD", 5.0)

    verdict = ask(engine, STILLS, "board-1", cost_usd=0.72, context=plan(step="stills"))

    assert verdict["status"] == "BLOCKED_MODE"
    assert rows(engine) == []


@pytest.mark.parametrize(
    ("mode", "action", "expected"),
    [
        ("AUTONOMOUS_CEO", MOTION, "ALLOWED"),
        ("AUTONOMOUS_CEO", STILLS, "ALLOWED"),
        ("SUPERVISED", STILLS, "ALLOWED"),
        ("SUPERVISED", MOTION, "NEEDS_APPROVAL"),
        ("MANUAL", STILLS, "BLOCKED_MODE"),
        ("MANUAL", MOTION, "BLOCKED_MODE"),
    ],
)
def test_mode_restores_what_the_autonomy_mode_decides_today(engine, mode, action, expected):
    a_studio_that_asks(engine, mode)
    paid_policy(engine, "MODE")
    step = "stills" if action == STILLS else "motion"

    verdict = ask(engine, action, "board-1", cost_usd=12.24, context=plan(step=step))

    assert verdict["status"] == expected


def test_mode_under_supervision_still_binds_the_yes_to_the_plan(engine):
    a_studio_that_asks(engine, "SUPERVISED")
    paid_policy(engine, "MODE")
    asked = ask(engine, MOTION, "board-1", cost_usd=12.24, context=plan(PLAN_A))
    answer(engine, asked["approval_id"], "APPROVED")

    assert ask(engine, MOTION, "board-1", context=plan(PLAN_B))["status"] == "NEEDS_APPROVAL"
    assert ask(engine, MOTION, "board-1", context=plan(PLAN_A))["status"] == "ALLOWED"


def test_an_unknown_stored_value_is_read_as_the_strictest(engine):
    """The database refuses other values; a row that somehow holds one still asks."""
    from app.services import paid_media_policy

    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    with Session(engine) as session:
        policy = session.get(OwnerPolicy, 1)
        policy.paid_media_approval = "NEVER_ASK"  # in memory only, never flushed
        assert paid_media_policy(policy) == ("EVERY_PAID_STEP", None)
        policy.paid_media_approval = None
        assert paid_media_policy(policy) == ("EVERY_PAID_STEP", None)
        policy.paid_media_approval = "OVER_USD"
        policy.paid_media_approval_over_usd = None
        assert paid_media_policy(policy) == ("EVERY_PAID_STEP", None)
        session.rollback()
    assert paid_media_policy(None) == ("EVERY_PAID_STEP", None)


# ------------------------------------------------- SetPaidMediaApproval, the Owner's only --


def paid_command(expected_version: int, value: str, over_usd: float | None = None):
    from app.services import PaidMediaApprovalCommand

    return PaidMediaApprovalCommand(
        command_id=uuid4(),
        expected_version=expected_version,
        paid_media_approval=value,
        over_usd=over_usd,
    )


def policy_row(engine) -> tuple[str, float | None, int]:
    with Session(engine) as session:
        policy = session.get(OwnerPolicy, 1)
        return policy.paid_media_approval, policy.paid_media_approval_over_usd, policy.version


def test_the_owner_changes_the_paid_media_policy_with_a_versioned_command(engine):
    from app.services import change_paid_media_approval

    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    _, _, version = policy_row(engine)
    command = paid_command(version, "OVER_USD", 5.0)

    result = change_paid_media_approval(engine, command, issued_by="owner")
    replay = change_paid_media_approval(engine, command, issued_by="owner")

    assert result.status == "COMMITTED"
    assert result.paid_media_approval == "OVER_USD"
    assert result.over_usd == 5.0
    assert result.version == version + 1
    assert replay.model_dump() == result.model_dump()
    assert policy_row(engine) == ("OVER_USD", 5.0, version + 1)
    with Session(engine) as session:
        events = list(
            session.scalars(
                select(DomainEvent).where(
                    DomainEvent.event_type == "owner.paid_media_approval_changed"
                )
            )
        )
    assert len(events) == 1
    assert events[0].event_id == result.event_id
    assert events[0].payload == {
        "paid_media_approval": "OVER_USD",
        "over_usd": 5.0,
        "previous_paid_media_approval": "EVERY_PAID_STEP",
        "previous_over_usd": None,
    }

    # And the gate reads the new value at once.
    cheap = ask(engine, STILLS, "board-1", cost_usd=0.72, context=plan(step="stills"))
    assert cheap["status"] == "ALLOWED"


def test_the_same_value_again_is_no_change_and_keeps_the_version(engine):
    from app.services import change_paid_media_approval

    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    _, _, version = policy_row(engine)

    result = change_paid_media_approval(
        engine, paid_command(version, "EVERY_PAID_STEP"), issued_by="owner"
    )

    assert result.status == "NO_CHANGE"
    assert result.event_id is None
    assert policy_row(engine) == ("EVERY_PAID_STEP", None, version)


def test_a_stale_version_is_refused(engine):
    from app.services import CommandConflict, change_paid_media_approval

    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    _, _, version = policy_row(engine)

    with pytest.raises(CommandConflict):
        change_paid_media_approval(engine, paid_command(version + 5, "MODE"), issued_by="owner")
    assert policy_row(engine) == ("EVERY_PAID_STEP", None, version)


@pytest.mark.parametrize("issuer", ["director", "video_editor", "agent", "autorun", "AUTORUN", ""])
def test_nobody_but_the_owner_can_change_it(engine, issuer):
    from app.services import PaidMediaApprovalRefused, change_paid_media_approval

    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    before = policy_row(engine)

    with pytest.raises(PaidMediaApprovalRefused) as refused:
        change_paid_media_approval(engine, paid_command(before[2], "MODE"), issued_by=issuer)

    assert "Proprietar" in str(refused.value)
    assert policy_row(engine) == before
    with Session(engine) as session:
        assert not list(
            session.scalars(
                select(DomainEvent).where(
                    DomainEvent.event_type == "owner.paid_media_approval_changed"
                )
            )
        )


def test_the_issuer_must_be_named():
    import inspect

    from app.services import change_paid_media_approval

    parameter = inspect.signature(change_paid_media_approval).parameters["issued_by"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty


@pytest.mark.parametrize(
    ("value", "over_usd"),
    [
        ("OVER_USD", None),
        ("MODE", 5.0),
        ("EVERY_PAID_STEP", 1.0),
        ("OVER_USD", -1.0),
        ("NEVER", None),
    ],
)
def test_the_command_refuses_a_shape_the_database_would_refuse(value, over_usd):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        paid_command(1, value, over_usd)


def test_the_command_accepts_exactly_the_values_the_database_accepts():
    from typing import get_args

    from app.models import PAID_MEDIA_APPROVALS
    from app.services import PaidMediaApprovalCommand

    annotation = PaidMediaApprovalCommand.model_fields["paid_media_approval"].annotation
    assert set(get_args(annotation)) == set(PAID_MEDIA_APPROVALS)


def test_the_command_takes_no_extra_fields():
    from app.services import PaidMediaApprovalCommand
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PaidMediaApprovalCommand(
            command_id=uuid4(),
            expected_version=1,
            paid_media_approval="MODE",
            issued_by="owner",
        )


# ------------------------------------------- OVER_USD reads the cap a step may spend (MONEY-08)
#
# The threshold was compared with each step's expected cost while his yes lets the step spend up
# to its cap: the hero's 3.40 USD shot may spend 6.80 (one redo), the stills up to three times
# their cost. Under a threshold between the two, the studio bought unasked what could spend
# more than he allowed. The steps now pass their cap; the question says «plafon».


def test_over_usd_compares_the_threshold_with_the_cap_and_says_so(engine):
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    paid_policy(engine, "OVER_USD", 5.0)

    verdict = ask(engine, TEST_SHOT, "board-1", cost_usd=6.8, context=plan(step="test_shot"))

    assert verdict["status"] == "NEEDS_APPROVAL"
    assert "plafonul" in verdict["reason"] and "6,80" in verdict["reason"]
    (row,) = rows(engine)
    # The question he reads carries the cap as its figure, named as such.
    from app.services import approval_view

    assert approval_view(row).cost_label == "plafon 6.8 USD"


def test_under_over_usd_a_hero_whose_cap_passes_the_threshold_is_asked(engine, tmp_path):
    from app.media.assembler import MotionStepRefused
    from test_film_costing import Account, Models, SpyVideo, a_film, run

    storyboard_id = a_film(engine, tmp_path, scenes=3)
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    # The hero costs 3.40 USD and may spend 6.80: a 5 USD threshold lies between the two.
    paid_policy(engine, "OVER_USD", 5.0)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))

    with pytest.raises(MotionStepRefused) as asked:
        run(engine, storyboard_id, tmp_path, "test_shot", models, account)

    assert asked.value.status == "NEEDS_APPROVAL", asked.value.reason_ro
    assert "plafon" in asked.value.reason_ro
    assert models.posts() == 0
    (row,) = rows(engine)
    assert row.cost_usd == pytest.approx(6.8)
    assert "3,40 USD" in row.evidence and "6,80 USD" in row.evidence


def test_under_over_usd_stills_whose_cap_passes_the_threshold_are_asked(engine, tmp_path):
    from app.media.stills_stage import StillsStageRefused
    from test_stills_stage import SpyStills
    from test_stills_stage import a_film as a_film_without_stills
    from test_stills_stage import run as run_stills

    storyboard_id = a_film_without_stills(engine, tmp_path)
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    # Four scenes cost 0.72 USD and may spend 2.16 with their re-rolls; the line is 1 USD.
    paid_policy(engine, "OVER_USD", 1.0)
    images = SpyStills(balance=10_000)

    with pytest.raises(StillsStageRefused) as asked:
        run_stills(engine, storyboard_id, tmp_path, images, None)

    assert asked.value.status == "NEEDS_APPROVAL", asked.value.reason_ro
    assert images.asked == []
    (row,) = rows(engine)
    assert row.cost_usd == pytest.approx(2.16)


def test_under_over_usd_a_step_whose_cap_stays_under_the_threshold_still_follows_the_mode(
    engine, tmp_path
):
    from test_film_costing import Account, Models, SpyVideo, a_film, run

    storyboard_id = a_film(engine, tmp_path, scenes=3)
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    paid_policy(engine, "OVER_USD", 7.0)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))

    run(engine, storyboard_id, tmp_path, "test_shot", models, account)

    assert models.posts() == 1 and rows(engine) == []


# ------------------------------------------- his yes continues the film the same day (A6)
#
# 2026-10-02 (CONTINUE_REDOS_E2E; A6, AR-05). His answer to a paid step of a film queued
# nothing: the yes waited for the next 05:00 run, so under EVERY_PAID_STEP a film moved one
# stair a day, and a yes given in the morning had often expired (24 h) by the run after it.
# Now an APPROVED answer on a paid step queues FILM_CONTINUE for that film, once, and a paid
# step's question stands for `paid_media_approval_expires_hours` (48 h by default).


def _production(engine) -> None:
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).environment = "PRODUCTION"


def _mode(engine, mode: str) -> None:
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_mode = mode


def _continue_tasks(engine) -> list:
    from app.workflows.models import TaskQueueItem

    with Session(engine) as session:
        found = list(
            session.scalars(select(TaskQueueItem).where(TaskQueueItem.task_type == "FILM_CONTINUE"))
        )
        session.expunge_all()
        return found


def _hours_standing(request: ApprovalRequest) -> float:
    created = datetime.fromisoformat(request.created_at)
    return (datetime.fromisoformat(request.expires_at) - created).total_seconds() / 3600


def test_a_paid_step_question_stands_for_48_hours_and_others_for_24(engine):
    from app.services import paid_media_approval_expires_hours

    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    assert paid_media_approval_expires_hours() == 48

    ask(engine, STILLS, "board-1", cost_usd=0.72, context=plan(step="stills"))
    _mode(engine, "SUPERVISED")
    ask(engine, PUBLISH, "asset-1", context={"channel_id": "c"})
    # The sheet's narration question (the assemble step, bound to the sheet's hash) is a paid
    # step of the film as well.
    ask(
        engine,
        "media.paid_generation_over_threshold",
        "board-1",
        cost_usd=9.0,
        context={"plan_hash": PLAN_A, "step": "assemble"},
    )

    by_action = {request.action: request for request in rows(engine)}
    assert _hours_standing(by_action[STILLS]) == pytest.approx(48, abs=0.01)
    assert _hours_standing(by_action[PUBLISH]) == pytest.approx(24, abs=0.01)
    assert _hours_standing(by_action["media.paid_generation_over_threshold"]) == pytest.approx(
        48, abs=0.01
    )


def test_the_paid_question_hours_are_the_owners_setting(monkeypatch):
    monkeypatch.setenv("STUDIO_PAID_MEDIA_APPROVAL_EXPIRES_HOURS", "72")
    from app.services import paid_media_approval_expires_hours

    assert paid_media_approval_expires_hours() == 72


@pytest.mark.parametrize("action", [STILLS, TEST_SHOT, MOTION, REDO])
def test_his_yes_on_a_paid_step_queues_the_film_to_continue_once(engine, action):
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    _production(engine)
    asked = ask(engine, action, "board-1", cost_usd=1.0, context={"plan_hash": PLAN_A})
    assert asked["status"] == "NEEDS_APPROVAL", asked

    command = ApprovalDecisionCommand(
        command_id=uuid4(), approval_id=asked["approval_id"], decision="APPROVED", note=None
    )
    decide_approval(engine, command)
    decide_approval(engine, command)  # the same command again: replayed, nothing queued twice

    (task,) = _continue_tasks(engine)
    assert task.payload["storyboard_id"] == "board-1"
    assert task.payload["approval_id"] == asked["approval_id"]
    assert task.payload["action"] == action
    assert task.idempotency_key == f"film-continue-board-1-{asked['approval_id']}"
    assert task.status == "QUEUED"
    with Session(engine) as session:
        decided = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "governance.approval_decided")
        ).one()
    assert decided.payload["continue_task_id"] == task.id


def test_a_refusal_or_a_question_that_is_not_a_paid_step_queues_nothing(engine):
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    _production(engine)
    refused = ask(engine, MOTION, "board-1", cost_usd=12.24, context=plan())
    answer(engine, refused["approval_id"], "REFUSED", note="Nu azi.")
    _mode(engine, "SUPERVISED")
    publish = ask(engine, PUBLISH, "asset-1", context={"channel_id": "c"})
    answer(engine, publish["approval_id"], "APPROVED")

    assert _continue_tasks(engine) == []


def test_in_test_his_yes_queues_nothing_because_the_day_does_not_buy_there(engine):
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    asked = ask(engine, STILLS, "board-1", cost_usd=0.72, context=plan(step="stills"))
    answer(engine, asked["approval_id"], "APPROVED")

    assert _continue_tasks(engine) == []


# ------------------------------------------- PAGE-03: a paid question says which film, which step


def test_a_paid_step_question_carries_its_step_its_plan_and_the_films_title(engine, tmp_path):
    from app.media.models import Storyboard
    from test_scene_takes import nepal_like

    # SUPERVISED, so the publication is asked too: a question that is not a film's paid step
    a_studio_that_asks(engine, "SUPERVISED")
    paid_policy(engine, "EVERY_PAID_STEP")
    film = nepal_like(engine, tmp_path)
    with Session(engine) as session, session.begin():
        session.get(Storyboard, film).title = "Nepal plătește criza altora"

    ask(engine, MOTION, film, cost_usd=27.2, context=plan())
    ask(engine, PUBLISH, "asset-1", cost_usd=None)

    views = {view.action: view for view in pending_approvals(engine)}
    motion = views[MOTION]
    assert motion.context == {"step": "motion", "plan_hash": PLAN_A[:12], "storyboard_id": film}
    assert motion.film_title == "Nepal plătește criza altora"
    # a question that is not a film's paid step has neither
    assert views[PUBLISH].context is None
    assert views[PUBLISH].film_title is None


def test_a_paid_step_named_only_by_its_action_still_says_its_step(engine):
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    paid_policy(engine, "EVERY_PAID_STEP")
    ask(engine, STILLS, "board-gone", cost_usd=0.72, context={"plan_hash": PLAN_A})
    (view,) = pending_approvals(engine)
    assert view.context == {
        "step": "stills",
        "plan_hash": PLAN_A[:12],
        "storyboard_id": "board-gone",
    }
    assert view.film_title is None, "no storyboard by that id: no invented title"


def test_the_approvals_route_carries_the_context_to_the_page(client, headers, engine):
    a_studio_that_asks(engine, "AUTONOMOUS_CEO")
    paid_policy(engine, "EVERY_PAID_STEP")
    ask(engine, TEST_SHOT, "board-9", cost_usd=3.4, context=plan(step="test_shot"))
    (row,) = client.get("/api/v1/owner/approvals", headers=headers).json()
    assert row["context"]["step"] == "test_shot"
    assert row["context"]["plan_hash"] == PLAN_A[:12]
    assert "film_title" in row
