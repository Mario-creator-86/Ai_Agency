"""The Owner's «Scrie episodul», carried to the end (2026-10-13).

He pressed the button in the serial room's «Zile închise»; Marcus wrote «The Nine-Scene
Rewrite» (DRAFT) and the Director never read it until the next run's stage took it up («De
ce nu-l citește? Nu trebuie să o facă automat?»). The press now runs the stage's own ladder
for the one day he pressed on (`serial_stage.tell_day_now`, route
``POST /story/logs/{id}/tell``). These tests hold it to the stage's rules, with the stage's
own fakes (tests/test_serial_pipeline.py): the draft written and read; a PASS approved under
the policy and storyboarded, or left for him with the words when the policy says so; a FAIL
rewritten once within `MAX_DRAFTS`; the day's unread DRAFT read instead of a new draft; a
refused day written again with the notes until `MAX_DRAFTS_PER_DAY`; a computed rejection
signed by the checks; one command id, one press; the stop, a quiet day, a day that has its
episode and another day's waiting draft refused in the studio's words; and the route's
answers. Providers are faked; all data is synthetic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.agents.services import seed_initial_workforce
from app.media.services import get_storyboard, seed_default_character_bibles
from app.models import OwnerPolicy
from app.publishing.services import seed_default_channels
from app.services import CommandConflict
from app.story.serial_stage import MAX_DRAFTS_PER_DAY, DayNotTold, tell_day_now
from app.story.services import (
    business_date,
    close_daily_log,
    write_episode,
)
from app.wording import AUTONOMY_STOPPED
from sqlalchemy.orm import Session
from test_serial_pipeline import (
    KAEL,
    SARAH,
    TZ,
    YESTERDAY_NOON,
    a_day,
    allow_director_approval,
    beats_for,
    counting_director,
    episode_answer,
    episode_rows,
    fake_director,
    fake_showrunner,
    letters_day,
    registry,
    roster_names,
    storyboard_count,
    unreadable_director,
)


@pytest.fixture
def staffed(engine):
    """The staffed studio of the serial tests: workforce, bibles, channels, autonomy on."""
    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    seed_default_channels(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    return engine


def press(engine, settings, log_id: str, command_id: str | None = None) -> dict:
    """The Owner's press on one closed day, with the stage's fake registry."""
    return tell_day_now(engine, registry(), settings, log_id, command_id or str(uuid4()))


def a_told_day(engine, monkeypatch, prompts: list[str] | None = None) -> dict:
    """Yesterday, closed with three public events, and a showrunner who writes from them."""
    log, ids = a_day(engine, YESTERDAY_NOON())
    names = roster_names(engine, log["id"])
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names)), prompts)
    return log


def stop_the_studio(engine) -> None:
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = True


# ---------------------------------------------------------------------------
# The ladder: written, read, approved under the policy, readied
# ---------------------------------------------------------------------------


def test_the_press_writes_reads_approves_under_the_policy_and_readies(
    engine, staffed, settings, monkeypatch
):
    allow_director_approval(engine)
    log = a_told_day(engine, monkeypatch)
    reviewed: list[str] = []
    counting_director(monkeypatch, "PASS", reviewed)

    outcome = press(engine, settings, log["id"])

    assert outcome["status"] == "COMPLETED", outcome
    artefacts = outcome["artefacts"]
    assert artefacts["written"] == 1 and artefacts["reviewed"] == 1 and artefacts["approved"] == 1
    assert artefacts["storyboard_id"] and artefacts["told_date"] == log["business_date"]
    assert get_storyboard(engine, artefacts["storyboard_id"])["status"] == "APPROVED"
    assert outcome["verdict"] == "PASS" and outcome["episode_status"] == "APPROVED"
    assert outcome["reviewed_by"] == "director" and outcome["refused"] is False
    assert outcome["words"].startswith(
        f"„{outcome['title']}” a trecut citirea Directorului și e aprobat; pregătit de filmare"
    )
    # TEST buys nothing, so no walk is queued: the next run films it, in the stage's words.
    assert artefacts["film_continue_task_id"] is None and "rularea de mâine" in outcome["words"]
    assert len(reviewed) == 1
    (row,) = episode_rows(engine)
    assert row.status == "APPROVED" and row.storyboard_id == artefacts["storyboard_id"]

    # The day has its episode: a second press is a state, said as one, and writes nothing.
    with pytest.raises(DayNotTold, match="are deja episodul"):
        press(engine, settings, log["id"])
    assert len(episode_rows(engine)) == 1 and storyboard_count(engine) == 1


def test_a_pass_without_the_policy_leaves_the_draft_for_the_owner_with_the_words(
    engine, staffed, settings, monkeypatch
):
    log = a_told_day(engine, monkeypatch)
    fake_director(monkeypatch, "PASS")

    outcome = press(engine, settings, log["id"])

    assert outcome["status"] == "COMPLETED", outcome
    assert outcome["artefacts"]["approved"] == 0
    assert outcome["artefacts"]["storyboard_id"] is None
    assert outcome["episode_status"] == "DRAFT" and outcome["verdict"] == "PASS"
    assert "a trecut citirea Directorului și așteaptă aprobarea ta" in outcome["words"]
    assert storyboard_count(engine) == 0

    # Nothing is written beside it: the canon number is fixed on his approval.
    with pytest.raises(DayNotTold, match="așteaptă aprobarea ta"):
        press(engine, settings, log["id"])
    assert len(episode_rows(engine)) == 1


def test_a_fail_by_the_director_is_rewritten_once_within_the_press(
    engine, staffed, settings, monkeypatch
):
    allow_director_approval(engine)
    prompts: list[str] = []
    log = a_told_day(engine, monkeypatch, prompts)
    fake_director(monkeypatch, "FAIL", notes="Primul beat nu se ține singur.")

    outcome = press(engine, settings, log["id"])

    assert outcome["status"] == "COMPLETED", outcome
    artefacts = outcome["artefacts"]
    assert artefacts["written"] == 2 and artefacts["rewritten"] == 1
    assert artefacts["approved"] == 0 and artefacts["storyboard_id"] is None
    assert len(prompts) == 2 and "Primul beat nu se ține singur." in prompts[1]
    assert outcome["episode_status"] == "REJECTED" and outcome["reviewed_by"] == "director"
    assert "a fost respins de Director: Primul beat nu se ține singur." in outcome["words"]
    assert "o apăsare nouă sau rularea următoare o scrie din nou" in outcome["words"]
    rows = episode_rows(engine)
    assert [row.status for row in rows] == ["REJECTED", "REJECTED"]
    assert rows[1].rewrite_of_id == rows[0].id


def test_a_refused_day_is_written_again_with_the_notes_until_its_drafts_are_spent(
    engine, staffed, settings, monkeypatch
):
    """The day's budget is `MAX_DRAFTS_PER_DAY` over every press and run (2026-10-10): the
    second press rewrites the last refused draft with its notes; the third is refused."""
    prompts: list[str] = []
    log = a_told_day(engine, monkeypatch, prompts)
    fake_director(monkeypatch, "FAIL", notes="Primul beat nu se ține singur.")
    press(engine, settings, log["id"])
    assert len(episode_rows(engine)) == 2

    outcome = press(engine, settings, log["id"])

    artefacts = outcome["artefacts"]
    assert artefacts["resumed"] == "retell"
    assert artefacts["written"] == 1 and artefacts["rewritten"] == 1
    assert len(prompts) == 3 and "Primul beat nu se ține singur." in prompts[2]
    rows = episode_rows(engine)
    assert len(rows) == MAX_DRAFTS_PER_DAY and rows[2].rewrite_of_id == rows[1].id
    assert "se scrie din nou" in outcome["reason"]
    assert f"ziua și-a folosit cele {MAX_DRAFTS_PER_DAY} ciorne" in outcome["words"]

    with pytest.raises(DayNotTold, match=f"cele {MAX_DRAFTS_PER_DAY} ciorne"):
        press(engine, settings, log["id"])
    assert len(episode_rows(engine)) == MAX_DRAFTS_PER_DAY and len(prompts) == 3


def test_an_unread_draft_of_the_day_is_read_instead_of_written_again(
    engine, staffed, settings, monkeypatch
):
    """The 2026-10-13 case: the old button wrote «The Nine-Scene Rewrite» and nobody read it."""
    allow_director_approval(engine)
    prompts: list[str] = []
    log = a_told_day(engine, monkeypatch, prompts)
    draft = write_episode(engine, registry(), log["id"], str(uuid4()))["episode"]
    reviewed: list[str] = []
    counting_director(monkeypatch, "PASS", reviewed)

    outcome = press(engine, settings, log["id"])

    artefacts = outcome["artefacts"]
    assert artefacts["resumed"] == "review" and artefacts["episode_id"] == draft["id"]
    assert artefacts["written"] == 0 and artefacts["reviewed"] == 1
    assert artefacts["approved"] == 1 and artefacts["storyboard_id"]
    assert len(prompts) == 1 and len(reviewed) == 1
    (row,) = episode_rows(engine)
    assert row.id == draft["id"] and row.status == "APPROVED"
    assert outcome["words"].startswith(
        f"„{draft['title']}” a trecut citirea Directorului și e aprobat"
    )


def test_a_draft_the_director_could_not_read_is_left_with_the_words_and_read_next(
    engine, staffed, settings, monkeypatch
):
    allow_director_approval(engine)
    prompts: list[str] = []
    log = a_told_day(engine, monkeypatch, prompts)
    unreadable_director(monkeypatch, [])

    outcome = press(engine, settings, log["id"])

    assert outcome["episode_status"] == "DRAFT" and outcome["verdict"] is None
    assert "Directorul nu a putut-o citi" in outcome["words"]
    assert "rularea următoare o citește din nou" in outcome["words"]

    reviewed: list[str] = []
    counting_director(monkeypatch, "PASS", reviewed)
    again = press(engine, settings, log["id"])

    assert again["artefacts"]["resumed"] == "review" and again["artefacts"]["written"] == 0
    assert again["episode_status"] == "APPROVED" and len(prompts) == 1 and len(reviewed) == 1


def test_a_computed_rejection_is_signed_by_the_checks_in_the_words(
    engine, staffed, settings, monkeypatch
):
    log, ids = letters_day(engine, YESTERDAY_NOON())
    beats = beats_for(ids, [SARAH, KAEL])
    for beat in beats:
        beat["lines"][0]["text"] = "Bună dimineața, unde este numărul pentru această zi, colegi?"
    fake_showrunner(monkeypatch, episode_answer(beats))
    calls: list[str] = []
    fake_director(monkeypatch, "PASS", calls=calls)

    outcome = press(engine, settings, log["id"])

    assert calls == [], "the Director is not asked about an episode the rules refuse"
    assert outcome["episode_status"] == "REJECTED" and outcome["reviewed_by"] == "checks"
    assert "a fost respins de verificările calculate:" in outcome["words"]
    assert "englez" in outcome["words"]


# ---------------------------------------------------------------------------
# One command, one press; what refuses the press
# ---------------------------------------------------------------------------


def test_the_same_command_id_is_one_press(engine, staffed, settings, monkeypatch):
    allow_director_approval(engine)
    prompts: list[str] = []
    log = a_told_day(engine, monkeypatch, prompts)
    fake_director(monkeypatch, "PASS")
    command_id = str(uuid4())

    first = press(engine, settings, log["id"], command_id)
    again = press(engine, settings, log["id"], command_id)

    assert "replayed" not in first and again["replayed"] is True
    assert again["episode_id"] == first["episode_id"] and again["words"] == first["words"]
    assert len(prompts) == 1 and len(episode_rows(engine)) == 1 and storyboard_count(engine) == 1

    # The same id on another day is a mistake the studio refuses rather than guesses about.
    other = close_daily_log(engine, TZ, business_date(TZ, datetime.now(UTC) - timedelta(days=3)))
    with pytest.raises(CommandConflict):
        press(engine, settings, other["id"], command_id)


def test_the_owners_stop_refuses_the_press_in_the_studios_words(
    engine, staffed, settings, monkeypatch
):
    prompts: list[str] = []
    log = a_told_day(engine, monkeypatch, prompts)
    fake_director(monkeypatch, "PASS")
    stop_the_studio(engine)

    with pytest.raises(DayNotTold) as refused:
        press(engine, settings, log["id"])

    assert str(refused.value) == AUTONOMY_STOPPED
    assert prompts == [] and episode_rows(engine) == []


def test_a_quiet_day_is_pressed_like_any_other(engine, staffed, settings, monkeypatch):
    """2026-10-16: the story is the showrunner's and the day its backdrop, so a quiet day is
    told too; the press asks the showrunner, and a non-answer is a refused draft, not «a
    quiet day»."""
    from app.story.services import DraftRefused

    quiet = close_daily_log(engine, TZ, business_date(TZ, datetime.now(UTC) - timedelta(days=3)))
    prompts: list[str] = []
    fake_showrunner(monkeypatch, "", prompts)

    with pytest.raises(DraftRefused) as refused:
        press(engine, settings, quiet["id"])

    assert "liniștită" not in str(refused.value)
    assert prompts and "A quiet day" in prompts[0]
    assert episode_rows(engine) == []


def test_another_days_draft_waiting_for_the_owner_holds_the_press(
    engine, staffed, settings, monkeypatch
):
    """The canon number is fixed on his approval: a script written beside a waiting episode
    would claim its number, so the press on a newer day names the one waiting and writes
    nothing, as the stage does."""
    older, ids = a_day(engine, YESTERDAY_NOON() - timedelta(days=1))
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, roster_names(engine, older["id"]))))
    fake_director(monkeypatch, "PASS")
    waiting = press(engine, settings, older["id"])
    assert waiting["episode_status"] == "DRAFT"
    newer, _ids = a_day(engine, YESTERDAY_NOON())

    with pytest.raises(DayNotTold, match="așteaptă aprobarea ta") as refused:
        press(engine, settings, newer["id"])

    assert waiting["title"] in str(refused.value)
    assert len(episode_rows(engine)) == 1


# ---------------------------------------------------------------------------
# Through the API
# ---------------------------------------------------------------------------


def test_the_route_answers_the_press_once_and_refuses_as_a_state(
    client, headers, engine, staffed, settings, monkeypatch
):
    client.app.app.state.registry = registry()
    allow_director_approval(engine)
    log = a_told_day(engine, monkeypatch)
    fake_director(monkeypatch, "PASS")
    url = f"/api/v1/story/logs/{log['id']}/tell"
    command = {"command_id": str(uuid4())}

    response = client.post(url, json=command, headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["episode_status"] == "APPROVED" and "e aprobat" in body["words"]
    assert body["artefacts"]["storyboard_id"]

    again = client.post(url, json=command, headers=headers)
    assert again.status_code == 200 and again.json()["replayed"] is True
    assert len(episode_rows(engine)) == 1

    third = client.post(url, json={"command_id": str(uuid4())}, headers=headers)
    assert third.status_code == 409 and "are deja episodul" in third.json()["detail"]

    stop_the_studio(engine)
    stopped = client.post(url, json={"command_id": str(uuid4())}, headers=headers)
    assert stopped.status_code == 409 and stopped.json()["detail"] == AUTONOMY_STOPPED


def test_the_route_says_what_could_not_be_stored_as_the_write_route_does(
    client, headers, engine, staffed, settings, monkeypatch
):
    client.app.app.state.registry = registry()
    log, _ids = a_day(engine, YESTERDAY_NOON())
    prompts: list[str] = []
    fake_showrunner(monkeypatch, "nu e JSON", prompts)
    url = f"/api/v1/story/logs/{log['id']}/tell"
    command = {"command_id": str(uuid4())}

    response = client.post(url, json=command, headers=headers)

    assert response.status_code == 422, response.text
    assert "respins" in response.json()["detail"]
    assert episode_rows(engine) == [] and len(prompts) == 2  # a draft and its retry

    # The same press is the same answer, and the showrunner is not asked again.
    again = client.post(url, json=command, headers=headers)
    assert again.status_code == 422 and again.json()["detail"] == response.json()["detail"]
    assert len(prompts) == 2

    # The same id on another log is refused rather than guessed about (the Owner's commands).
    reused = client.post(f"/api/v1/story/logs/{uuid4()}/tell", json=command, headers=headers)
    assert reused.status_code == 409 and "Aceeași comandă" in reused.json()["detail"]

    # A log the studio does not have, and a quiet day: the write route's own answers.
    missing = client.post(
        f"/api/v1/story/logs/{uuid4()}/tell", json={"command_id": str(uuid4())}, headers=headers
    )
    assert missing.status_code == 422 and "nu există" in missing.json()["detail"]
    quiet = close_daily_log(engine, TZ, business_date(TZ, datetime.now(UTC) - timedelta(days=3)))
    quiet_day = client.post(
        f"/api/v1/story/logs/{quiet['id']}/tell", json={"command_id": str(uuid4())}, headers=headers
    )
    # A quiet day is told too (2026-10-16): the stand-in's non-answer is a refused draft.
    assert quiet_day.status_code == 422 and "respins" in quiet_day.json()["detail"]


def test_a_day_whose_drafts_her_reading_spent_ships_its_newest_draft_under_the_cap(
    engine, staffed, settings, monkeypatch
):
    """The Owner, 2026-10-15 («publicăm ce avem»): episode 3 was refused three times by the
    Director's reading and the serial moved to another day. A day whose drafts are spent on
    her reading alone ships its newest draft, approved under the cap with her notes as the
    lesson; a draft the computed checks refused never ships (the test above keeps that)."""
    prompts: list[str] = []
    log = a_told_day(engine, monkeypatch, prompts)
    allow_director_approval(engine)
    fake_director(monkeypatch, "FAIL", notes="Rebuild around one situation that changes.")
    press(engine, settings, log["id"])
    assert len(episode_rows(engine)) == 2

    outcome = press(engine, settings, log["id"])

    artefacts = outcome["artefacts"]
    assert artefacts["written"] == 1 and artefacts["approved"] == 1, outcome
    assert artefacts.get("cap_shipped") is True
    rows = episode_rows(engine)
    assert len(rows) == MAX_DRAFTS_PER_DAY
    assert [row.status for row in rows] == ["REJECTED", "REJECTED", "APPROVED"]
    assert "Aprobat sub plafonul ciornelor zilei" in (rows[2].notes or "")
    assert artefacts["storyboard_id"], outcome
