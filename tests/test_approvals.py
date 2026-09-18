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
