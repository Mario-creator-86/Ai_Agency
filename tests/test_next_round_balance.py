"""The balance a paid step asks for: its next round only (2026-10-03, NEXT_ROUND_BALANCE).

The Owner's question: «De ce avem nevoie de așa de multe credite dacă să creezi o imagine costă
10-20 de credite». His LHC film waited with 316 credits on the account: its stills step bought
8 scenes x 2 candidates x 9 credits = 144 credits, but before it started it asked for its whole
cap (432: the round plus two re-roll rounds) x 1.15 = 497. On a card he chose «Doar pentru
runda următoare»:

- to START a paid step the balance must hold the cost of its next round only, times the margin
  (settings.paid_step_balance_margin, 1.15): the stills step's first round, the test shot's one
  shot, the motion step's shots, a redo's one purchase;
- BEFORE EACH FURTHER purchase (a stills request, a re-roll round, a clip-QC retry, the next
  shot) the balance is read again and must hold that purchase's price times the margin; when it
  does not, that scene stops cleanly (NEEDS_OWNER, failure_kind LOW_BALANCE, a Romanian reason
  naming the balance and what is needed), what was bought is kept, nothing more is bought in
  the step, and the scene is not held against him (topping up lets it go on);
- the cap he approved stays the absolute ceiling of the step;
- a balance that cannot be read still stops the step (fail closed);
- a LOW_BALANCE at a paid step puts a card in his Decisions window with the amount missing for
  the next round, cleared by a later balance reading that covers it (never a vendor call from
  the feed); the letter of the repair names the film's title.

Every provider is faked: spy adapters count their calls; no socket is opened, nothing is bought.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.decisions.models import OwnerDecision
from app.decisions.services import refresh_owner_decisions
from app.media import balance_rule
from app.media.models import SceneTake
from app.media.shooting_sheet import SheetStepRefused, build_sheet, run_sheet_step
from app.media.stills_stage import StillsStageRefused, stills_plan
from app.media.toolchain import find_ffmpeg
from app.models import DomainEvent
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_stills_stage import (
    FACE,
    NO_FACE,
    SUBJECTS,
    SpyJudge,
    SpyStills,
    a_film,
    approved_run,
    run,
)

requires_ffmpeg = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")


def takes(engine, storyboard_id: str) -> list[SceneTake]:
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(SceneTake)
                .where(SceneTake.storyboard_id == storyboard_id)
                .order_by(SceneTake.scene_number, SceneTake.created_at)
            )
        )
        session.expunge_all()
        return rows


def events(engine, event_type: str) -> list[DomainEvent]:
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(DomainEvent)
                .where(DomainEvent.event_type == event_type)
                .order_by(DomainEvent.sequence)
            )
        )
        session.expunge_all()
        return rows


def cards(engine, kind: str = "low_balance") -> list[OwnerDecision]:
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(OwnerDecision)
                .where(OwnerDecision.kind == kind)
                .order_by(OwnerDecision.created_at)
            )
        )
        session.expunge_all()
        return rows


def by_scene(result: dict) -> dict[int, dict]:
    return {entry["scene_index"]: entry for entry in result["scenes"]}


# ------------------------------------------------------------------------------- the rule


def test_the_need_is_the_rounds_price_times_the_margin_rounded_up():
    # The LHC film: 8 scenes x 2 candidates x 9 credits, its cap with two re-roll rounds.
    assert balance_rule.needed_credits(144, 1.15) == 166
    assert balance_rule.needed_credits(432, 1.15) == 497  # what it asked before his card
    assert balance_rule.needed_credits(18, 1.15) == 21
    assert balance_rule.needed_credits(340, 1.15) == 391
    assert balance_rule.needed_credits(20, 1.15) == 23, "a float product is not rounded up twice"
    assert balance_rule.needed_credits(0, 1.15) == 0
    assert balance_rule.margin_of(None) == pytest.approx(1.15)


def test_the_owners_setting_names_the_margin(settings):
    assert balance_rule.margin_of(settings) == pytest.approx(settings.paid_step_balance_margin)
    stricter = settings.model_copy(update={"paid_step_balance_margin": 2.0})
    assert balance_rule.margin_of(stricter) == 2.0


# ------------------------------------------------------------------- the stills step


def test_the_stills_step_starts_on_its_first_round_not_on_its_cap(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path)
    plan = stills_plan(engine, storyboard_id)
    assert (plan["cost_credits"], plan["cap_credits"]) == (72, 216)

    short = SpyStills(balance=82)
    with pytest.raises(StillsStageRefused) as refused:
        run(engine, storyboard_id, tmp_path, short, SpyJudge())
    assert refused.value.status == "LOW_BALANCE"
    reason = refused.value.reason_ro
    # His words: the balance, the round, the need with the margin, the cap that still binds,
    # and what is missing.
    for words in ("82 de credite", "72 de credite", "83 de credite", "216 credite", "15%"):
        assert words in reason, (words, reason)
    assert "cel puțin 1 credit" in reason
    assert short.asked == []

    # 83 credits: the first round and its margin, far under the cap x 1.15 (249).
    enough = SpyStills(balance=83)
    result = approved_run(engine, storyboard_id, tmp_path, enough, SpyJudge())
    assert len(enough.asked) == 4
    assert all(by_scene(result)[n]["status"] == "APPROVED" for n in (1, 2, 3, 4))
    assert result["low_balance"] is None


def test_a_reroll_the_balance_cannot_cover_stops_that_scene_cleanly(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path)

    def pictures(prompt, call):
        # Scene 4's words always come back with a face: it would be re-rolled.
        return [FACE, FACE] if SUBJECTS[4] in prompt else list(NO_FACE)

    # 83 credits pay the first round (4 x 18 = 72); 11 are left for a re-roll of 18 x 1.15.
    adapter = SpyStills(pictures=pictures, balance=83)

    result = approved_run(engine, storyboard_id, tmp_path, adapter, SpyJudge())

    assert len(adapter.asked) == 4, "a re-roll was bought on 11 credits"
    scenes = by_scene(result)
    assert all(scenes[n]["status"] == "APPROVED" for n in (1, 2, 3))
    four = scenes[4]
    assert four["status"] == "NEEDS_OWNER" and four["failure_kind"] == "LOW_BALANCE"
    # The re-roll was decided by the gate and not bought: four requests, no fifth.
    assert four["rerolls"] == 1
    for words in ("Scena 4", "11 credite", "18 credite", "21 de credite", "cel puțin 10 credite"):
        assert words in four["reason"], (words, four["reason"])
    # What was bought is kept: scene 4's candidates (the same face twice is one picture),
    # judged and rejected, on the books.
    kept = [t for t in takes(engine, storyboard_id) if t.scene_number == 4]
    assert kept and all(t.status == "REJECTED" for t in kept)
    assert result["spent_credits_quoted"] == 72
    assert result["low_balance"] == {
        "scene_index": 4,
        "credits": 11.0,
        "price_credits": 18,
        "needed_credits": 21,
        "missing_credits": 10,
        "reason_ro": four["reason"],
    }
    # A scene the account could not pay for is not held against the Owner: a top-up lets it go.
    (hold,) = [
        e for e in events(engine, "media.still_needs_owner") if e.payload["scene_number"] == 4
    ]
    assert hold.payload["holds"] is False and hold.payload["failure_kind"] == "LOW_BALANCE"


def test_a_first_round_purchase_the_balance_cannot_cover_stops_the_rest(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path)

    def pictures(prompt, call):
        return [FACE, FACE] if SUBJECTS[2] in prompt else list(NO_FACE)

    # Scene 2 fails and is re-rolled twice: 83 - 18 x 4 = 11 are left for scene 3.
    adapter = SpyStills(pictures=pictures, balance=83)

    result = approved_run(engine, storyboard_id, tmp_path, adapter, SpyJudge())

    assert len(adapter.asked) == 4
    scenes = by_scene(result)
    assert scenes[1]["status"] == "APPROVED"
    assert scenes[2]["status"] == "NEEDS_OWNER" and scenes[2].get("failure_kind") is None
    assert scenes[3]["status"] == "NEEDS_OWNER" and scenes[3]["failure_kind"] == "LOW_BALANCE"
    assert scenes[4]["status"] == "NOT_BOUGHT"
    assert "11 credite" in scenes[4]["reason"]
    assert result["low_balance"]["scene_index"] == 3
    assert not [t for t in takes(engine, storyboard_id) if t.scene_number in (3, 4)]


def test_a_balance_that_cannot_be_read_still_stops_the_step(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path)

    class Unreadable(SpyStills):
        async def credit_balance(self):
            raise RuntimeError("HTTP 503")

    adapter = Unreadable()
    with pytest.raises(StillsStageRefused) as refused:
        run(engine, storyboard_id, tmp_path, adapter, SpyJudge())
    assert refused.value.status == "LOW_BALANCE" and "HTTP 503" in refused.value.reason_ro
    assert adapter.asked == []


# -------------------------------------------------------------------- the motion steps


@requires_ffmpeg
def test_the_test_shot_starts_on_one_shot_with_its_margin(engine, tmp_path):
    from app.media.assembler import MotionStepRefused
    from test_film_costing import Account, Models, SpyVideo
    from test_film_costing import a_film as film_with_stills
    from test_film_costing import run as run_motion

    storyboard_id = film_with_stills(engine, tmp_path, scenes=2)
    account = Account(390)  # one shot of 340 x 1.15 = 391; its cap is 680
    models = Models(SpyVideo("seedance2_5", account))
    with pytest.raises(MotionStepRefused) as refused:
        run_motion(engine, storyboard_id, tmp_path, "test_shot", models, account)
    assert refused.value.status == "LOW_BALANCE"
    for words in ("390 de credite", "340 de credite", "391 de credite", "680 de credite"):
        assert words in refused.value.reason_ro, (words, refused.value.reason_ro)
    assert models.posts() == 0

    account.balance = 391
    with pytest.raises(MotionStepRefused) as asked:
        run_motion(engine, storyboard_id, tmp_path, "test_shot", models, account)
    assert asked.value.status == "NEEDS_APPROVAL"


@requires_ffmpeg
def test_a_shot_the_balance_cannot_cover_stops_that_scene_and_keeps_what_was_bought(
    engine, tmp_path
):
    from test_film_costing import Account, Models, SpyVideo, approved, hero_approved
    from test_film_costing import a_film as film_with_stills

    storyboard_id = film_with_stills(engine, tmp_path, scenes=4)
    # After the second shot of the account's life (the hero, then scene 2) something else
    # spent the money: 380 credits are left, under the next shot's 340 x 1.15 = 391.
    account = Account(10_000, after_shot={2: 380.0})
    models = Models(SpyVideo("seedance2_5", account))
    hero_approved(engine, storyboard_id, tmp_path, models, account)

    result = approved(engine, storyboard_id, tmp_path, "motion", models, account)

    assert models.posts() == 2, "a shot was POSTed on 380 credits for a 340 x 1.15 need"
    scenes = by_scene(result)
    assert scenes[2]["status"] == "PAID"
    assert scenes[3]["status"] == "NEEDS_OWNER" and scenes[3]["failure_kind"] == "LOW_BALANCE"
    assert "380 de credite" in scenes[3]["reason"] and "391 de credite" in scenes[3]["reason"]
    assert scenes[4]["status"] == "NOT_BOUGHT"
    assert result["low_balance"]["scene_index"] == 3
    assert result["low_balance"]["needed_credits"] == 391


@requires_ffmpeg
def test_a_clip_qc_retry_the_balance_cannot_cover_stops_the_scene(engine, tmp_path):
    from test_clip_qc_wiring import ScriptedCheck
    from test_film_costing import Account, Models, SpyVideo, approved
    from test_film_costing import a_film as film_with_stills

    storyboard_id = film_with_stills(engine, tmp_path, scenes=1)
    account = Account(391)  # the test shot and its margin; 51 are left for a retry of 340
    models = Models(SpyVideo("seedance2_5", account))

    summary = approved(
        engine,
        storyboard_id,
        tmp_path,
        "test_shot",
        models,
        account,
        clip_check=ScriptedCheck("FAILED", "PASSED"),
    )

    assert models.posts() == 1, "a clip-QC retry was bought on 51 credits"
    (entry,) = summary["scenes"]
    assert entry["status"] == "NEEDS_OWNER" and entry["failure_kind"] == "LOW_BALANCE"
    assert "51 de credite" in entry["reason"] and "391 de credite" in entry["reason"]
    assert summary["low_balance"]["credits"] == 51.0
    (shot,) = [t for t in takes(engine, storyboard_id) if t.kind == "test_shot"]
    assert shot.status == "REJECTED", "the shot bought is kept with its clip report"


# --------------------------------------------- the sheet: its footer and its step's card


def test_the_sheet_footer_asks_the_next_round_and_says_the_cost_and_the_cap(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path)

    sheet = build_sheet(engine, storyboard_id, read_live=False)

    footer = sheet["footer"]
    assert footer["balance_needed_credits"]["stills"] == 83
    rule = footer["balance_rule"]["stills"]
    assert rule["round_credits"] == 72 and rule["cap_credits"] == 216
    assert rule["needed_credits"] == 83 and rule["margin"] == pytest.approx(1.15)
    for words in ("83 de credite", "72 de credite", "216 credite", "15%"):
        assert words in rule["line_ro"], (words, rule["line_ro"])


def sheet_stills(engine, storyboard_id, images, tmp_path):
    plan_hash = build_sheet(engine, storyboard_id, read_live=False)["sheet_hash"]
    return run_sheet_step(
        engine,
        storyboard_id,
        "stills",
        plan_hash,
        correlation_id=str(uuid4()),
        image_adapter=images,
        storage_root=tmp_path / "media",
    )


def test_a_low_balance_at_a_paid_step_puts_a_card_that_a_later_reading_clears(
    engine, tmp_path, settings
):
    storyboard_id = a_film(engine, tmp_path)

    with pytest.raises(SheetStepRefused) as refused:
        sheet_stills(engine, storyboard_id, SpyStills(balance=50), tmp_path)

    assert refused.value.status == "LOW_BALANCE"
    for words in ("50 de credite", "72 de credite", "83 de credite", "216 credite"):
        assert words in refused.value.reason_ro, (words, refused.value.reason_ro)
    (card,) = cards(engine)
    assert card.status == "PENDING" and card.subject_id == storyboard_id
    assert card.clears_when == {"type": "balance_covers", "credits": 83}
    top_up = card.options[0]
    assert top_up["recommended"] and top_up["apply"]["type"] == "guided"
    assert "33 de credite" in top_up["label_ro"], top_up["label_ro"]
    assert "Runway" in top_up["label_ro"]
    assert refused.value.reason_ro in card.why_ro
    # The reading was recorded: the card clears on the books, never on a vendor call.
    (reading,) = events(engine, balance_rule.BALANCE_READ_EVENT)
    assert reading.payload["credits"] == 50.0 and reading.payload["needed_credits"] == 83

    # The same refusal again: one card, not two.
    with pytest.raises(SheetStepRefused):
        sheet_stills(engine, storyboard_id, SpyStills(balance=50), tmp_path)
    assert len(cards(engine)) == 1

    # A reading under the need keeps it; a later one that covers it clears it.
    balance_rule.record_balance_reading(
        engine, 82.0, storyboard_id=storyboard_id, step="stills", needed=83, correlation_id="t"
    )
    refresh_owner_decisions(engine, settings)
    assert cards(engine)[0].status == "PENDING"
    balance_rule.record_balance_reading(
        engine, 90.0, storyboard_id=storyboard_id, step="stills", needed=83, correlation_id="t"
    )
    refresh_owner_decisions(engine, settings)
    assert cards(engine)[0].status == "WITHDRAWN"


def test_a_step_that_starts_withdraws_the_films_low_balance_card(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path)
    with pytest.raises(SheetStepRefused):
        sheet_stills(engine, storyboard_id, SpyStills(balance=50), tmp_path)
    assert cards(engine)[0].status == "PENDING"

    with pytest.raises(SheetStepRefused) as asked:
        sheet_stills(engine, storyboard_id, SpyStills(balance=83), tmp_path)

    assert asked.value.status == "NEEDS_APPROVAL"
    assert cards(engine)[0].status == "WITHDRAWN"


def test_a_scene_stopped_on_the_balance_mid_step_puts_the_card_too(engine, tmp_path, monkeypatch):
    from functools import partial

    from app.media import shooting_sheet, stills_stage
    from test_approvals import answer
    from test_stills_stage import faces_in

    # The sheet's stills step with the faked vision model and face counter of this suite.
    monkeypatch.setattr(
        shooting_sheet,
        "run_stills_stage",
        partial(
            stills_stage.run_stills_stage,
            judge=SpyJudge(),
            face_counter=faces_in(),
            measure=("faces",),
        ),
    )
    storyboard_id = a_film(engine, tmp_path)

    def pictures(prompt, call):
        return [FACE, FACE] if SUBJECTS[4] in prompt else list(NO_FACE)

    images = SpyStills(pictures=pictures, balance=83)
    with pytest.raises(SheetStepRefused) as asked:
        sheet_stills(engine, storyboard_id, images, tmp_path)
    answer(engine, asked.value.approval_id, "APPROVED", note="Da, imaginile.")

    result = sheet_stills(engine, storyboard_id, images, tmp_path)

    assert result["low_balance"]["scene_index"] == 4
    (card,) = cards(engine)
    assert card.clears_when == {"type": "balance_covers", "credits": 21}
    assert "10 credite" in card.options[0]["label_ro"]
    assert "Scena 4" in card.why_ro


# ----------------------------------------------------------------- the sheet repair


def test_the_repair_reads_the_footers_need_and_falls_back_on_the_round():
    from app.media.blocker_repair import sheet_issues

    def low(footer: dict, step: dict) -> list[dict]:
        sheet = {"footer": footer, "steps": {"stills": step}, "story_review": {"passed": True}}
        return [i for i in sheet_issues(sheet) if i["code"] == "LOW_BALANCE"]

    balance = {"read": True, "credits": 100.0, "problem": None}
    step = {"to_buy": [1], "cost_credits": 72, "cap_credits": 216}
    # The footer's need is the next round's: 100 credits are enough for 83.
    assert low({"balance": balance, "balance_needed_credits": {"stills": 83}}, step) == []
    # An older footer without the need: the same rule from the step's round, not its cap.
    assert low({"balance": balance}, step) == []
    (issue,) = low({"balance": {**balance, "credits": 80.0}}, step)
    assert "83" in issue["detail"]


# ------------------------------------------------- adversarial checks (verification pass)


def test_a_larger_need_on_the_same_film_replaces_the_cards_amount(engine, tmp_path, settings):
    """A card that asked for a re-roll's 21 credits must not clear on a reading of 50 when the
    film's next start needs 83: the card follows the film's newest need."""
    from app.decisions.sources import film_low_balance

    storyboard_id = a_film(engine, tmp_path)
    film_low_balance(
        engine,
        storyboard_id,
        title="Film",
        step_words="imaginile",
        short={"needed_credits": 21, "missing_credits": 10, "reason_ro": "Scena 4: ..."},
    )
    with pytest.raises(SheetStepRefused):
        sheet_stills(engine, storyboard_id, SpyStills(balance=50), tmp_path)

    refresh_owner_decisions(engine, settings)
    open_cards = [c for c in cards(engine) if c.status in ("PENDING", "WAITING_FOR_OWNER_ACTION")]
    assert len(open_cards) == 1, [(c.status, c.clears_when) for c in cards(engine)]
    (card,) = open_cards
    assert card.clears_when == {"type": "balance_covers", "credits": 83}
    assert "33 de credite" in card.options[0]["label_ro"]


def test_a_step_that_starts_keeps_a_card_its_balance_does_not_cover(engine, tmp_path):
    """A step that starts on its own (smaller) need does not withdraw a card that names a
    larger one: the balance is still short for what the card asks."""
    from app.decisions.sources import film_low_balance

    storyboard_id = a_film(engine, tmp_path)
    film_low_balance(
        engine,
        storyboard_id,
        title="Film",
        step_words="cadrul de probă",
        short={"needed_credits": 391, "missing_credits": 308, "reason_ro": "..."},
    )
    with pytest.raises(SheetStepRefused) as asked:
        sheet_stills(engine, storyboard_id, SpyStills(balance=83), tmp_path)
    assert asked.value.status == "NEEDS_APPROVAL"
    (card,) = cards(engine)
    assert card.status == "PENDING", "a balance of 83 withdrew a card that needs 391"


def test_an_agent_cannot_answer_the_low_balance_card(engine, tmp_path):
    from app.decisions.services import DecideCommand, DecisionRefused, decide_owner_decision

    storyboard_id = a_film(engine, tmp_path)
    with pytest.raises(SheetStepRefused):
        sheet_stills(engine, storyboard_id, SpyStills(balance=50), tmp_path)
    (card,) = cards(engine)
    command = DecideCommand(
        command_id=uuid4(), decision="ACCEPT", option_key="top_up", expected_version=card.version
    )
    with pytest.raises(DecisionRefused):
        decide_owner_decision(engine, card.id, command, issued_by="video_editor")
    assert cards(engine)[0].status == "PENDING"


@requires_ffmpeg
def test_a_cap_smaller_than_one_shot_buys_nothing(engine, tmp_path):
    from test_film_costing import Account, Models, SpyVideo, approved
    from test_film_costing import a_film as film_with_stills

    storyboard_id = film_with_stills(engine, tmp_path, scenes=1)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))
    summary = approved(
        engine, storyboard_id, tmp_path, "test_shot", models, account, cap_credits=300
    )
    assert models.posts() == 0, "a 340-credit shot was bought under a 300-credit cap"
    assert "STOPPED_AT_CAP" in str(summary["stopped"])


def test_a_card_he_is_carrying_out_follows_the_larger_need(engine, tmp_path, settings):
    from app.decisions.services import DecideCommand, decide_owner_decision
    from app.decisions.sources import film_low_balance

    storyboard_id = a_film(engine, tmp_path)
    film_low_balance(
        engine,
        storyboard_id,
        title="Film",
        step_words="imaginile",
        short={"needed_credits": 21, "missing_credits": 10, "reason_ro": "Scena 4: ..."},
    )
    (card,) = cards(engine)
    command = DecideCommand(
        command_id=uuid4(), decision="ACCEPT", option_key="top_up", expected_version=card.version
    )
    decide_owner_decision(engine, card.id, command, issued_by="owner", settings=settings)
    assert cards(engine)[0].status == "WAITING_FOR_OWNER_ACTION"

    with pytest.raises(SheetStepRefused):
        sheet_stills(engine, storyboard_id, SpyStills(balance=50), tmp_path)
    balance_rule.record_balance_reading(
        engine, 60.0, storyboard_id=storyboard_id, step="stills", needed=83, correlation_id="t"
    )
    refresh_owner_decisions(engine, settings)
    (card,) = cards(engine)
    assert card.status == "WAITING_FOR_OWNER_ACTION", "60 credits closed a card the film needs 83"
    assert card.clears_when == {"type": "balance_covers", "credits": 83}

    balance_rule.record_balance_reading(
        engine, 90.0, storyboard_id=storyboard_id, step="stills", needed=83, correlation_id="t"
    )
    refresh_owner_decisions(engine, settings)
    assert cards(engine)[0].status == "ACCEPTED"
