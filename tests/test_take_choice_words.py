"""His choice on the contact sheet says what it set going; the sheet says a wait once.

2026-10-04, the Nepal sheet (storyboard 81438d13): he pressed «Alege imaginea aceasta» and saw
nothing change. The books show the choice landed every time, and that the first one queued
FILM_CONTINUE, which bought the test shot under his rule MODE (AUTONOMOUS_CEO) seconds later,
while the notice said «Nimic nu s-a cumpărat». Now:

- POST /media/takes/{id}/decision answers with ``outcome``: what the choice did and what the
  continuation it queued will do, read from the same policy the Policy Kernel reads (and never
  by asking it, which could spend a standing yes).
- The assemble step says «Scenele 1, 2 și 3 nu au încă un cadru acceptat …» once, not one
  sentence per scene.
- A vendor's refusal is said in Romanian, with its text once, behind «Textul furnizorului».

Every provider is faked; nothing is bought and no socket is opened.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from app.economy.budget import BudgetCommand, set_budget
from app.media.assembler import still_fields, take_hash
from app.media.models import SceneTake
from app.media.sheet_words import blocked_words, dedupe_clauses, refusal_view, scene_list
from app.models import OwnerPolicy
from app.services import utc_now
from app.workflows.models import TaskQueueItem
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_film_costing import SEEDANCE
from test_film_costing import a_film as film_with_stills
from test_stills_stage import a_film as film_without_stills
from test_stills_stage import still_prompt

FIXTURES = Path(__file__).parent / "fixtures" / "nepal_1d530880"

#: The vendor's text on the Owner's sheet (takes of 2026-10-03 07:50-07:57 UTC), as kept.
TOO_LARGE = (
    "Validation of body failed; referenceImages.[0]..uri: Data URI is too large: 8.6MB "
    "exceeds the 5MB limit. Upload the file and pass the returned URI instead.; "
    "referenceImages.[0]..uri: Data URI is too large: 8.6MB exceeds the 5MB limit. Upload "
    "the file and pass the returned URI instead."
)
#: The test shot's refusal of 2026-10-03 20:56 UTC.
KEYFRAME = (
    "Keyframe image-to-video requests must use `auto_480p`, `auto_720p`, or `auto_1080p` "
    "because the output aspect ratio follows the first frame."
)
NO_SHOT = (
    "nu au încă un cadru acceptat (nici „imagine fixă animată local” aleasă pe foaia de filmare)."
)


def sheet_url(storyboard_id: str) -> str:
    return f"/api/v1/media/storyboards/{storyboard_id}/shooting-sheet"


def wire(client, tmp_path: Path) -> None:
    state = client.app.app.state
    state.media_storage_root = tmp_path / "media"
    state.scene_model_capabilities = [SEEDANCE]


def policy(engine, *, environment: str, mode: str = "MANUAL", rule: str = "EVERY_PAID_STEP"):
    with Session(engine) as session, session.begin():
        row = session.get(OwnerPolicy, 1)
        row.environment = environment
        row.autonomy_mode = mode
        row.autonomy_stopped = False
        row.paid_media_approval = rule
        row.paid_media_approval_over_usd = None


def two_stills(engine, storyboard_id: str, tmp_path: Path) -> None:
    """Scene 1's two bought stills: take-0 approved by the gate, take-1 his runner-up."""
    identity = take_hash(still_fields(still_prompt(1), None), "seedream5_pro")
    for n, (status, approved_by) in enumerate((("APPROVED", "still_gate"), ("PAID", None))):
        copy = tmp_path / "media" / storyboard_id / f"candidate_{n}.jpg"
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURES / f"scene_0{n + 1}.jpg", copy)
        with Session(engine) as session, session.begin():
            session.add(
                SceneTake(
                    id=f"take-{n}",
                    storyboard_id=storyboard_id,
                    scene_number=1,
                    kind="still",
                    prompt_hash=identity,
                    model_id="seedream5_pro",
                    resolution="1530:2720",
                    status=status,
                    approved_by=approved_by,
                    path=str(copy),
                    sha256=hashlib.sha256(copy.read_bytes()).hexdigest(),
                    credits_quoted=9.0,
                    credits_measured=9.0,
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
            )


def choose(client, headers, take_id: str = "take-1", decision: str = "APPROVED") -> dict:
    answered = client.post(
        f"/api/v1/media/takes/{take_id}/decision", headers=headers, json={"decision": decision}
    )
    assert answered.status_code == 200, answered.text
    body: dict = answered.json()
    return body


def continuations(engine) -> list[TaskQueueItem]:
    with Session(engine) as session:
        rows = list(
            session.scalars(select(TaskQueueItem).where(TaskQueueItem.task_type == "FILM_CONTINUE"))
        )
        session.expunge_all()
        return rows


# --------------------------------------------------------------- 2. the notice tells the truth


def test_in_test_his_choice_buys_nothing_and_says_so(client, engine, headers, tmp_path):
    storyboard_id = film_without_stills(engine, tmp_path)
    wire(client, tmp_path)
    two_stills(engine, storyboard_id, tmp_path)
    policy(engine, environment="TEST", mode="AUTONOMOUS_CEO", rule="MODE")

    body = choose(client, headers)

    outcome = body["outcome"]
    assert outcome["continues"] is False and outcome["buys_unasked"] is False
    assert outcome["message_ro"] == (
        "Imaginea scenei 1 este aleasă. Nimic nu s-a cumpărat: în mediul de test filmul nu "
        "continuă singur; un pas plătit se cumpără doar când îl apeși pe foaie."
    )
    assert body["scene_number"] == 1 and body["superseded"] == ["take-0"]
    assert continuations(engine) == []


def test_under_his_rule_mode_the_choice_says_the_next_step_is_bought_now(
    client, engine, headers, tmp_path
):
    """The Nepal case: PRODUCTION, AUTONOMOUS_CEO, his rule MODE and a daily budget."""
    storyboard_id = film_without_stills(engine, tmp_path)
    wire(client, tmp_path)
    two_stills(engine, storyboard_id, tmp_path)
    policy(engine, environment="PRODUCTION", mode="AUTONOMOUS_CEO", rule="MODE")
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="10"))

    body = choose(client, headers)

    outcome = body["outcome"]
    (queued,) = continuations(engine)
    assert body["continue_task_id"] == queued.id
    assert outcome["continues"] is True and outcome["buys_unasked"] is True
    # the next paid step of the sheet he will see: the other scenes' pictures
    assert outcome["next_step"] == "stills"
    message = outcome["message_ro"]
    assert message.startswith("Imaginea scenei 1 este aleasă. Filmul continuă singur: imaginile ")
    assert "se cumpără acum, fără altă întrebare (plafon " in message
    assert "pașii plătiți urmează modul studioului" in message and "CEO autonom" in message
    assert "Nimic nu s-a cumpărat" not in message, "the continuation buys: never say it does not"
    # nothing was bought by the answer itself: the worker would, and no worker runs here
    with Session(engine) as session:
        assert len(session.scalars(select(SceneTake)).all()) == 2


def test_under_every_paid_step_the_choice_says_the_step_waits_for_his_yes(
    client, engine, headers, tmp_path
):
    storyboard_id = film_without_stills(engine, tmp_path)
    wire(client, tmp_path)
    two_stills(engine, storyboard_id, tmp_path)
    policy(engine, environment="PRODUCTION", mode="AUTONOMOUS_CEO", rule="EVERY_PAID_STEP")

    outcome = choose(client, headers)["outcome"]

    assert outcome["continues"] is True and outcome["buys_unasked"] is False
    assert outcome["message_ro"].startswith(
        "Imaginea scenei 1 este aleasă. Nimic nu s-a cumpărat: imaginile așteaptă aprobarea ta"
    )
    assert "foaia nouă" in outcome["message_ro"]


def test_with_no_daily_budget_the_choice_says_nothing_is_bought_unasked(
    client, engine, headers, tmp_path
):
    storyboard_id = film_without_stills(engine, tmp_path)
    wire(client, tmp_path)
    two_stills(engine, storyboard_id, tmp_path)
    policy(engine, environment="PRODUCTION", mode="AUTONOMOUS_CEO", rule="MODE")

    outcome = choose(client, headers)["outcome"]

    assert outcome["buys_unasked"] is False
    assert "niciun buget zilnic activ" in outcome["message_ro"]
    assert "Autonomie → Buget și cheltuieli" in outcome["message_ro"]


def test_a_rejection_queues_nothing_and_says_so(client, engine, headers, tmp_path):
    storyboard_id = film_without_stills(engine, tmp_path)
    wire(client, tmp_path)
    two_stills(engine, storyboard_id, tmp_path)
    policy(engine, environment="PRODUCTION", mode="AUTONOMOUS_CEO", rule="MODE")

    outcome = choose(client, headers, decision="REJECTED")["outcome"]

    assert outcome["continues"] is False
    assert outcome["message_ro"] == (
        "Imaginea respinsă a scenei 1 nu se mai folosește în film. Nimic nu s-a cumpărat și "
        "nimic nu pornește din această respingere."
    )
    assert continuations(engine) == []


# ------------------------------------------------------- 3. the assembly's wait, said once


def test_scene_lists_read_the_romanian_way():
    assert scene_list([4]) == "4"
    assert scene_list([2, 1]) == "1 și 2"
    assert scene_list([1, 2, 3, 4, 6]) == "1, 2, 3, 4 și 6"


def test_blocked_scenes_are_grouped_one_sentence_per_kind_with_plurals():
    def shot(n: int, why: str = "") -> dict:
        return {"scene_index": n, "code": "NO_SHOT", "why_ro": why, "reason_ro": f"S{n}"}

    assert blocked_words([shot(n) for n in (1, 2, 3, 4, 6)]) == f"Scenele 1, 2, 3, 4 și 6 {NO_SHOT}"
    assert blocked_words([shot(3)]) == (
        "Scena 3 nu are încă un cadru acceptat (nici „imagine fixă animată local” aleasă pe "
        "foaia de filmare)."
    )
    no_still = [{"scene_index": n, "code": "NO_STILL", "reason_ro": f"S{n}"} for n in (2, 5)]
    why = "Scena 4: cadrul plătit a picat controlul clipului (stă pe loc)."
    said = blocked_words([*no_still, shot(4, why), shot(1)])
    assert said == (
        f"{why} Scenele 2 și 5 nu au o imagine aprobată pentru promptul de acum; cumpărați sau "
        "aprobați imaginile lor pe foaia de filmare. "
        f"Scenele 1 și 4 {NO_SHOT}"
    )
    # an item from an older sheet (no code) keeps its own words
    assert blocked_words([{"scene_index": 2, "reason_ro": "Scena 2: altceva."}]) == (
        "Scena 2: altceva."
    )
    assert blocked_words([]) == ""


def test_the_sheet_says_the_assembly_wait_once_for_every_scene(client, engine, headers, tmp_path):
    storyboard_id = film_with_stills(engine, tmp_path, scenes=3)
    policy(engine, environment="PRODUCTION")
    wire(client, tmp_path)

    step = client.get(sheet_url(storyboard_id), headers=headers).json()["steps"]["assemble"]

    assert step["blocked_ro"] == f"Scenele 1, 2 și 3 {NO_SHOT}"
    assert step["waiting_ro"] == step["blocked_ro"]
    assert [item["code"] for item in step["blocked"]] == ["NO_SHOT"] * 3
    # each scene keeps its own sentence for whoever reads one scene
    assert "Scena 2" in step["blocked"][1]["reason_ro"]


# -------------------------------------------------------- 4. a vendor's refusal, in his words


def test_a_repeated_vendor_text_is_kept_once():
    assert dedupe_clauses(TOO_LARGE) == (
        "Validation of body failed; referenceImages.[0]..uri: Data URI is too large: 8.6MB "
        "exceeds the 5MB limit. Upload the file and pass the returned URI instead."
    )
    assert dedupe_clauses(None) == ""


def test_a_picture_over_runways_limit_is_explained_and_cost_nothing():
    view = refusal_view("HTTP_400", TOO_LARGE, None)

    assert view["kind"] == "PICTURE_TOO_LARGE"
    assert view["credits"] == 0
    assert view["vendor_text"] == dedupe_clauses(TOO_LARGE)
    assert view["explain_ro"] == (
        "Imaginea de referință trimisă avea 8,6 MB, peste limita Runway de 5 MB, iar Runway a "
        "refuzat cererea înainte să genereze ceva. Reparat de atunci (626b59d): studioul "
        "micșorează imaginea sub limită înainte s-o trimită."
    )


def test_a_keyframe_sent_with_a_fixed_ratio_is_explained():
    view = refusal_view("HTTP_400", KEYFRAME, 0.0)

    assert view["kind"] == "RATIO_NOT_AUTO"
    assert view["credits"] == 0
    assert "raport „auto”" in view["explain_ro"]
    # said as what the studio does since, never "fixed": a model whose contract lists no
    # auto ratio still gets a fixed one (runway.pick_ratio)
    assert "Reparat" not in view["explain_ro"] and "De atunci" in view["explain_ro"]


def test_an_unknown_refusal_is_named_by_its_kind_and_keeps_the_vendor_text():
    safety = refusal_view("SAFETY.INPUT.IMAGE", "Flagged.", None)
    assert safety["kind"] == "SAFETY"
    assert safety["explain_ro"].startswith("Refuz de siguranță")
    other = refusal_view(None, "Something odd.", 3.0)
    assert other["kind"] == "UNKNOWN" and other["credits"] == 3.0
    assert other["vendor_text"] == "Something odd."
    assert "fără un motiv cunoscut" in other["explain_ro"]


def test_a_refused_candidate_on_the_sheet_carries_its_explanation(
    client, engine, headers, tmp_path
):
    storyboard_id = film_without_stills(engine, tmp_path)
    wire(client, tmp_path)
    with Session(engine) as session, session.begin():
        session.add(
            SceneTake(
                id="refused-1",
                storyboard_id=storyboard_id,
                scene_number=2,
                kind="still",
                prompt_hash="h",
                model_id="gen4_image",
                resolution="1080:1920",
                status="REFUSED",
                failure_code="HTTP_400",
                failure_detail=TOO_LARGE,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )

    sheet = client.get(sheet_url(storyboard_id), headers=headers).json()

    (candidate,) = next(s for s in sheet["scenes"] if s["scene_index"] == 2)["candidates"]
    assert candidate["refusal"]["kind"] == "PICTURE_TOO_LARGE"
    assert candidate["refusal"]["credits"] == 0
    assert candidate["reason_ro"] == TOO_LARGE, "the take's own text is kept as it was"


# ------------------------------------- 2b. the notice under an adversary's look (2026-10-04)


def finish_continuations(engine) -> None:
    """The worker ran every queued continuation (none runs in these tests)."""
    with Session(engine) as session, session.begin():
        for task in session.scalars(
            select(TaskQueueItem).where(TaskQueueItem.task_type == "FILM_CONTINUE")
        ):
            task.status = "COMPLETED"


def test_choosing_again_a_picture_whose_continuation_already_ran_says_nothing_starts(
    client, engine, headers, tmp_path
):
    """The Nepal books, 20:56:33: he chose deaa682c back. Its continuation key
    (film-continue-…-take-deaa682c) had run at 17:36, so nothing new was queued; the notice
    must not say the film continues and buys."""
    storyboard_id = film_without_stills(engine, tmp_path)
    wire(client, tmp_path)
    two_stills(engine, storyboard_id, tmp_path)
    policy(engine, environment="PRODUCTION", mode="AUTONOMOUS_CEO", rule="MODE")
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="10"))

    choose(client, headers, "take-1")
    finish_continuations(engine)
    choose(client, headers, "take-0")
    finish_continuations(engine)
    outcome = choose(client, headers, "take-1")["outcome"]

    assert len(continuations(engine)) == 2, "nothing new was queued by the third press"
    assert outcome["continues"] is False and outcome["buys_unasked"] is False
    assert "Filmul continuă singur" not in outcome["message_ro"]
    assert "Nimic nu s-a cumpărat" in outcome["message_ro"]


def test_choosing_again_while_another_continuation_of_the_film_waits_says_it_buys(
    client, engine, headers, tmp_path
):
    """The same press while the other picture's continuation is still queued: that walk
    reads the sheet as it is when it runs, so the film does continue and buys."""
    storyboard_id = film_without_stills(engine, tmp_path)
    wire(client, tmp_path)
    two_stills(engine, storyboard_id, tmp_path)
    policy(engine, environment="PRODUCTION", mode="AUTONOMOUS_CEO", rule="MODE")
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="10"))

    choose(client, headers, "take-1")
    finish_continuations(engine)
    choose(client, headers, "take-0")  # queued, not run yet
    outcome = choose(client, headers, "take-1")["outcome"]

    assert outcome["continues"] is True and outcome["buys_unasked"] is True
    assert "Filmul continuă singur" in outcome["message_ro"]


def test_a_standing_yes_for_the_plan_he_returns_to_is_said_to_buy(
    client, engine, headers, tmp_path
):
    """EVERY_PAID_STEP: a yes he gave for the plan the sheet has again (he chose a picture
    back) is spent by the continuation; the notice must not say the step waits for him."""
    from app.models import ApprovalRequest
    from app.services import request_approval

    storyboard_id = film_without_stills(engine, tmp_path)
    wire(client, tmp_path)
    two_stills(engine, storyboard_id, tmp_path)
    policy(engine, environment="PRODUCTION", mode="AUTONOMOUS_CEO", rule="EVERY_PAID_STEP")
    choose(client, headers, "take-1")
    sheet = client.get(sheet_url(storyboard_id), headers=headers).json()
    with Session(engine) as session, session.begin():
        asked = request_approval(
            session,
            "media.stills_purchase",
            "T2",
            "director",
            subject=storyboard_id,
            evidence="test",
            proposed_diff={
                "plan_hash": sheet["sheet_hash"],
                "step": "stills",
                "cap_credits": sheet["steps"]["stills"]["cap_credits"],
            },
            cost_usd=1.0,
        )
        row = session.get(ApprovalRequest, asked.id)
        row.result = "APPROVED"
        row.decided_at = utc_now()

    outcome = choose(client, headers, "take-1")["outcome"]

    assert outcome["buys_unasked"] is True
    assert "Nimic nu s-a cumpărat" not in outcome["message_ro"]
    assert "aprobarea pe care ai dat-o deja" in outcome["message_ro"]


def test_in_manual_mode_the_film_does_not_continue_by_itself(client, engine, headers, tmp_path):
    """`continue_film` skips under MANUAL (the media stage is T2): the notice says so, even
    when the sheet has no paid step left."""
    storyboard_id = film_without_stills(engine, tmp_path)
    wire(client, tmp_path)
    two_stills(engine, storyboard_id, tmp_path)
    policy(engine, environment="PRODUCTION", mode="MANUAL", rule="MODE")
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="10"))

    outcome = choose(client, headers)["outcome"]

    assert outcome["buys_unasked"] is False
    assert "în modul manual filmul nu continuă singur" in outcome["message_ro"]


def test_with_no_image_or_shot_left_the_paid_narration_is_not_hidden(engine):
    """«Nu mai e niciun pas plătit» was said while the assembly still voices a paid
    narration (ElevenLabs)."""
    from app.media.sheet_words import decision_outcome
    from app.services import queue_film_continue

    with Session(engine) as session, session.begin():
        row = session.get(OwnerPolicy, 1)
        row.environment = "PRODUCTION"
        row.autonomy_mode = "AUTONOMOUS_CEO"
        row.autonomy_stopped = False
        row.paid_media_approval = "MODE"
        task_id = queue_film_continue(session, "sb-1", key="k-1", payload={})
    sheet = {
        "steps": {
            "stills": {"to_buy": []},
            "test_shot": {"to_buy": []},
            "motion": {"to_buy": []},
            "assemble": {
                "blocked": [],
                "narration": {"characters": 900, "usd": 0.27, "priced": True},
            },
        }
    }

    outcome = decision_outcome(
        engine,
        kind="motion",
        scene_number=3,
        decision="APPROVED",
        continue_task_id=task_id,
        sheet=sheet,
    )

    assert "niciun pas plătit" not in outcome["message_ro"]
    assert "narațiunea" in outcome["message_ro"] and "0,27 USD" in outcome["message_ro"]


def test_a_refusal_the_vendor_may_have_charged_is_never_said_to_cost_nothing():
    """A motion take refused after Runway accepted it (or with no answer) keeps what it may
    have cost in ``credits_quoted`` (`assembler`: «may be charged like a success»), with no
    measured spend. It was shown as 0 credits and hidden in the closed 0-credit group."""
    view = refusal_view("VENDOR.FAILED", "Task failed.", None, 40.0)

    assert view["credits"] == 40.0 and view["credits_known"] is False
    assert "poate fi taxată" in view["explain_ro"] and "40" in view["explain_ro"]
    # refused at the door (HTTP 4xx at submit): nothing was created, so nothing was charged,
    # whatever stale quote the adapter still held
    door = refusal_view("HTTP_400", TOO_LARGE, None, 9.0)
    assert door["credits"] == 0 and door["credits_known"] is True
    measured = refusal_view("VENDOR.FAILED", "Task failed.", 0.0, 40.0)
    assert measured["credits"] == 0 and measured["credits_known"] is True


def test_the_sheet_carries_what_an_accepted_then_failed_request_may_have_cost(
    client, engine, headers, tmp_path
):
    storyboard_id = film_without_stills(engine, tmp_path)
    wire(client, tmp_path)
    with Session(engine) as session, session.begin():
        session.add(
            SceneTake(
                id="failed-1",
                storyboard_id=storyboard_id,
                scene_number=2,
                kind="still",
                prompt_hash="h",
                model_id="gen4_image",
                resolution="1080:1920",
                status="REFUSED",
                failure_code="VENDOR.FAILED",
                failure_detail="Task failed.",
                credits_quoted=9.0,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )

    sheet = client.get(sheet_url(storyboard_id), headers=headers).json()

    (candidate,) = next(s for s in sheet["scenes"] if s["scene_index"] == 2)["candidates"]
    assert candidate["refusal"]["credits"] == 9.0
    assert candidate["refusal"]["credits_known"] is False
