"""The day's goal reads the budget film by film (the audit of 2026-10-16, SAFE-003).

The day's goal pass read the newest refused round of any film as «the daily budget is spent»
for the whole studio and queued nothing more, with no letter. A serial episode whose stills
did not fit in the 3 USD left stopped the day even when the short still owed a round that
fits — the short then had no run, no card and no reason. The budget now stops the day only when
every film the day still owes waits on it: the owed film's own newest refusal needs more than
is left. A film with no refusal, or whose round fits, keeps the day going.

No provider is called and nothing is bought: refusals are recorded the way the shooting sheet
records them.
"""

from __future__ import annotations

from uuid import uuid4

from app.economy.budget import BudgetCommand, set_budget
from app.factual.models import ScriptDraft, TopicIdea
from app.media.models import Storyboard
from app.media.shooting_sheet import _hold_refused
from app.services import utc_now
from app.story.services import business_date
from sqlalchemy.orm import Session
from test_day_goal import TZ, _finished_run, _pass, _production, _published
from test_montage_money_holds import a_spend


def _board(engine, *, serial: bool) -> str:
    now = utc_now()
    ids = {key: str(uuid4()) for key in ("topic", "script", "board")}
    with Session(engine) as session, session.begin():
        session.add(
            TopicIdea(
                id=ids["topic"],
                title="a topic",
                topic="a topic",
                angle="an angle",
                status="SERIAL" if serial else "SELECTED",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            ScriptDraft(
                id=ids["script"],
                topic_id=ids["topic"],
                title="a film",
                voiceover_full_text="text",
                status="APPROVED",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            Storyboard(
                id=ids["board"],
                script_draft_id=ids["script"],
                title="the episode" if serial else "the short",
                status="APPROVED",
                total_scenes=1,
                visual_bible_json={},
                series_key="office_serial" if serial else None,
                created_at=now,
            )
        )
    return ids["board"]


def _a_day_with_three_dollars_left(engine) -> None:
    _production(engine)
    _finished_run(engine, business_date(TZ))
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="20"))
    a_spend(engine, 17.0)


def _refused(engine, board: str, usd: float) -> None:
    _hold_refused(engine, board, "stills", "DAILY", int(usd * 1_000_000), "over the daily budget")


def test_the_episodes_refused_round_does_not_stop_a_short_that_has_not_been_refused(
    engine, settings
):
    _a_day_with_three_dollars_left(engine)
    _board(engine, serial=False)
    _refused(engine, _board(engine, serial=True), 3.61)

    result = _pass(engine, settings)

    assert result["queued"], result


def test_a_smaller_round_of_the_short_that_fits_keeps_the_day_going(engine, settings):
    _a_day_with_three_dollars_left(engine)
    short, episode = _board(engine, serial=False), _board(engine, serial=True)
    _refused(engine, short, 2.0)  # refused earlier; 3 USD are left now, and it fits
    _refused(engine, episode, 3.61)  # the newest refusal: the episode does not fit

    result = _pass(engine, settings)

    assert result["queued"], result


def test_the_budget_stops_the_day_when_the_film_still_owed_is_the_one_refused(engine, settings):
    _a_day_with_three_dollars_left(engine)
    _published(engine, serial=False)  # the short is out today: only the episode is owed
    short = _board(engine, serial=False)
    _refused(engine, _board(engine, serial=True), 3.61)
    _refused(engine, short, 0.5)  # a later short's round fits, but no short is owed

    result = _pass(engine, settings)

    assert result["queued"] is None and result["budget"] is True, result
    assert result["letter"] is False
    assert "bugetul zilnic" in result["why"] and "episodul" in result["why"]
    assert result["waiting_on_budget"] == ["serial"]


def test_the_budget_stops_the_day_when_both_owed_films_are_refused(engine, settings):
    _a_day_with_three_dollars_left(engine)
    _refused(engine, _board(engine, serial=False), 3.2)
    _refused(engine, _board(engine, serial=True), 3.61)

    result = _pass(engine, settings)

    assert result["queued"] is None and result["budget"] is True, result
    assert result["waiting_on_budget"] == ["short", "serial"]
