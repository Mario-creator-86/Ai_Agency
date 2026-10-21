"""One day of the serial: one approved episode, one film (2026-10-17).

Measured on his database at 2026-10-16 23:15:17Z, the run for 2026-10-17, stage serial_queue:
the day «Zero Scripts, Blocked Log» had two REJECTED drafts, 8caad7d9 — a DRAFT whose PASS
was held for the editorial judgement — and b8684fc5, the Director's rewrite of it, APPROVED the
evening before with its film 87c05891 in production. `unfinished_episodes` took the held PASS
up, `approve_reviewed_episode` approved it, canon moved to episode 5 on it and a second film of
the same day, a7db1594, was built — nothing bought for it yet.

These tests hold, on stand-ins only (no vendor, no credit):

- that exact day, before the bug: nothing approved, no second storyboard, the held draft
  closed as superseded with its reason, canon untouched;
- that day after the bug (the duplicate approved, its film built): the studio's own repair
  retires the film through the Director's closing with nothing bought, supersedes the draft,
  tells canon again without it (the number back, the older summary back), and leaves the
  day's film untouched; the purchase lease refuses the duplicate before the repair; a second
  repair finds nothing;
- the guards: the Owner's approval, the storyboard build and the approval under the cap
  refuse a day's second episode or film; a draft the review refused replaces nothing;
- a genuine held PASS — no rewrite, no approved sibling — is still approved and readied.
"""

from __future__ import annotations

from datetime import UTC
from uuid import uuid4

import pytest
from app.agents.models import Agent, ModelRecord
from app.agents.services import seed_initial_workforce
from app.events_feed import enrich
from app.media.models import Storyboard
from app.media.serial_storyboard import SerialStoryboardError, storyboard_from_episode
from app.media.services import seed_default_character_bibles
from app.media.shooting_sheet import FilmClosed, film_is_closed, film_purchase_lease
from app.models import DomainEvent, OwnerPolicy
from app.publishing.services import seed_default_channels
from app.runbook.stages import FILM_RETIRED_EVENT
from app.services import append_event
from app.story import duplicates
from app.story.duplicates import SUPERSEDED_EVENT, repair_duplicate_days
from app.story.models import StoryEpisode
from app.story.review import (
    approve_reviewed_episode,
    approve_under_drafts_cap,
    review_episode,
)
from app.story.serial_stage import run_serial_stage, unfinished_episodes
from app.story.services import (
    CONTINUITY_CORRECTED_EVENT,
    StoryError,
    advance_continuity,
    business_date,
    decide_episode,
    get_continuity,
    write_episode,
)
from app.workflows.passes import WatchdogContext
from app.workflows.passes.serial_duplicates import retire_duplicate_episodes
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_editorial_judgement import GOOD, StandIn, her_answer, registry_with
from test_serial_pipeline import (
    NOON_DAYS_AGO,
    TZ,
    YESTERDAY_NOON,
    a_day,
    allow_director_approval,
    beats_for,
    episode_answer,
    roster_names,
)


@pytest.fixture
def studio(engine):
    """The editorial tests' studio (`test_editorial_judgement.studio`): the workforce, bibles
    and channels, autonomy on, every model available, the Director allowed to approve."""
    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    seed_default_channels(engine)
    allow_director_approval(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        provider_id = session.scalar(select(Agent)).provider_id
    return {"provider_id": provider_id}


def _registry(engine, studio, log: dict, ids: list[str]):
    names = roster_names(engine, log["id"])
    titles: list[str] = []

    def showrunner(prompt: str) -> str:
        return episode_answer(beats_for(ids, names), title=titles[-1])

    model = StandIn(lambda prompt: her_answer(GOOD), on_episode=showrunner)
    return registry_with(studio, model), titles


def _write(engine, registry, titles, log_id: str, title: str, rewrite_of: str | None = None):
    titles.append(title)
    return write_episode(
        engine,
        registry,
        log_id,
        str(uuid4()),
        notes="Rescrie." if rewrite_of else None,
        rewrite_of=rewrite_of,
        judged=rewrite_of is not None,
    )["episode"]["id"]


def _held(engine, registry, titles, log_id: str, title: str, rewrite_of: str | None = None):
    """A DRAFT the Director passed and the judgement held (a stopped run's leftover)."""
    episode_id = _write(engine, registry, titles, log_id, title, rewrite_of)
    review = review_episode(engine, registry, episode_id, str(uuid4()), approve=False)
    assert review["verdict"] == "PASS" and review["status"] == "DRAFT"
    return episode_id


def _rejected(engine, registry, titles, log_id: str, title: str, rewrite_of=None) -> str:
    episode_id = _write(engine, registry, titles, log_id, title, rewrite_of)
    with Session(engine) as session, session.begin():
        row = session.get(StoryEpisode, episode_id)
        row.status, row.reviewed_by, row.notes = "REJECTED", "director", "Rescrie începutul."
    return episode_id


def _old_approval(engine, episode_id: str) -> None:
    """What the approval did before 2026-10-17: APPROVED, the event, canon advanced — and
    nothing closed beside it, nothing asked of its day."""
    with Session(engine) as session, session.begin():
        row = session.get(StoryEpisode, episode_id)
        row.status, row.reviewed_by = "APPROVED", "director"
        row.review_json = {
            **(row.review_json or {}),
            "held_for_judgement": False,
            "approved_by_policy": True,
        }
        append_event(
            session,
            "story.episode_approved",
            "story_episode",
            row.id,
            3,
            {"log_id": row.log_id, "reviewed_by": "director"},
            "old",
        )
        advance_continuity(session, row, "old")


def _row(engine, episode_id: str) -> StoryEpisode:
    with Session(engine) as session:
        row = session.get(StoryEpisode, episode_id)
        session.expunge(row)
    return row


def _boards(engine) -> dict[str, str]:
    with Session(engine) as session:
        return {board.id: board.status for board in session.scalars(select(Storyboard))}


def _events(engine, kind: str) -> list[DomainEvent]:
    with Session(engine) as session:
        rows = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == kind).order_by(DomainEvent.sequence)
        ).all()
        session.expunge_all()
    return rows


@pytest.fixture
def the_day(engine, studio, settings):
    """The serial as it stood on 2026-10-16 22:06Z: an earlier day in canon (Ep. 1), and the
    day told twice — two refused drafts, a held PASS (``a``) and its rewrite (``b``), APPROVED
    by the evening's script as Ep. 2 with its film in production; ``a`` left a held PASS."""
    earlier_log, earlier_ids = a_day(engine, NOON_DAYS_AGO(2))
    registry, titles = _registry(engine, studio, earlier_log, earlier_ids)
    first = _held(engine, registry, titles, earlier_log["id"], "Stalled Queue")
    assert approve_reviewed_episode(engine, first, "c")["status"] == "APPROVED"
    storyboard_from_episode(engine, first, "c")

    log, ids = a_day(engine, YESTERDAY_NOON())
    registry, titles = _registry(engine, studio, log, ids)
    r1 = _rejected(engine, registry, titles, log["id"], "Blocked Log one")
    r2 = _rejected(engine, registry, titles, log["id"], "Blocked Log two", rewrite_of=r1)
    a = _held(engine, registry, titles, log["id"], "Blocked Log three", rewrite_of=r2)
    b = _held(engine, registry, titles, log["id"], "Blocked Log four", rewrite_of=a)
    _old_approval(engine, b)
    b_board = storyboard_from_episode(engine, b, "c")
    assert get_continuity(engine)["canon_episode_number"] == 2
    return {
        "registry": registry,
        "log_id": log["id"],
        "first": first,
        "a": a,
        "b": b,
        "b_board": b_board,
        "today": business_date(TZ),
    }


# ------------------------------------------------------------------- the day, before the bug


def test_the_held_pass_a_newer_approved_version_rewrote_is_never_taken_up(engine, the_day):
    with Session(engine) as session:
        left = [(kind, e.id) for kind, e in unfinished_episodes(session, the_day["today"])]
    assert left == []


def test_its_approval_closes_it_as_superseded_instead(engine, the_day):
    approval = approve_reviewed_episode(engine, the_day["a"], "c")

    assert approval["status"] == "REJECTED" and approval["superseded_by"] == the_day["b"]
    a = _row(engine, the_day["a"])
    assert a.status == "REJECTED" and a.storyboard_id is None
    assert the_day["b"][:8] in a.notes and "un singur film" in a.notes
    assert get_continuity(engine)["canon_episode_number"] == 2
    (event,) = _events(engine, SUPERSEDED_EVENT)
    assert event.payload["superseded_by"] == the_day["b"] and event.payload["was"] == "DRAFT"


def test_the_serial_stage_approves_nothing_and_builds_no_second_film(engine, the_day, settings):
    boards_before = _boards(engine)

    outcome = run_serial_stage(engine, the_day["registry"], settings)

    assert outcome["status"] == "COMPLETED", outcome
    assert outcome["artefacts"]["approved"] == 0
    assert outcome["artefacts"]["storyboard_id"] is None
    assert _boards(engine) == boards_before  # no second storyboard; the day's film untouched
    assert _row(engine, the_day["a"]).status == "REJECTED"
    assert outcome["artefacts"]["duplicates"]["drafts_closed"] == [the_day["a"]]
    b = _row(engine, the_day["b"])
    assert b.status == "APPROVED" and b.storyboard_id == the_day["b_board"]
    continuity = get_continuity(engine)
    assert continuity["canon_episode_number"] == 2
    assert continuity["summaries"][-1]["episode_id"] == the_day["b"]
    # A second run finds nothing more to do.
    again = run_serial_stage(engine, the_day["registry"], settings)
    assert "duplicates" not in again["artefacts"] and _boards(engine) == boards_before


def test_an_approval_closes_the_days_other_drafts_at_once(engine, studio, settings):
    log, ids = a_day(engine, YESTERDAY_NOON())
    registry, titles = _registry(engine, studio, log, ids)
    a = _held(engine, registry, titles, log["id"], "Version one")
    b = _held(engine, registry, titles, log["id"], "Version two", rewrite_of=a)

    # The evening's script approves the newest held PASS (`run_serial_next_stage`).
    assert approve_reviewed_episode(engine, b, "c")["status"] == "APPROVED"

    assert _row(engine, a).status == "REJECTED"
    assert "Directoarea l-a rescris" in _row(engine, a).notes


# ------------------------------------------------------------------ the day, after the bug


@pytest.fixture
def the_duplicate(engine, the_day, monkeypatch):
    """The state at 23:15:17Z: ``a`` approved again (Ep. 3) and its film built, nothing bought."""
    _old_approval(engine, the_day["a"])
    with monkeypatch.context() as patch:
        patch.setattr(duplicates, "live_film_of_day", lambda session, episode: None)
        patch.setattr(duplicates, "second_approval", lambda session, episode: False)
        a_board = storyboard_from_episode(engine, the_day["a"], "c")
    assert get_continuity(engine)["canon_episode_number"] == 3
    return {**the_day, "a_board": a_board}


def test_nothing_is_bought_for_the_duplicate_film_even_before_the_repair(engine, the_duplicate):
    with Session(engine) as session:
        assert film_is_closed(session, the_duplicate["a_board"])
        assert not film_is_closed(session, the_duplicate["b_board"])
    with pytest.raises(FilmClosed):
        with film_purchase_lease(engine, the_duplicate["a_board"], holder="t", step="stills"):
            pass


def test_the_watchdog_retires_the_duplicate_film_and_corrects_canon(
    engine, the_duplicate, settings
):
    done = retire_duplicate_episodes(WatchdogContext(engine, settings, "wd-1"))

    assert done["retired"] == [
        {
            "episode_id": the_duplicate["a"],
            "kept_episode_id": the_duplicate["b"],
            "storyboard_id": the_duplicate["a_board"],
            "canon_episode_number": 2,
        }
    ]
    boards = _boards(engine)
    assert boards[the_duplicate["a_board"]] == "REJECTED"
    assert boards[the_duplicate["b_board"]] == "APPROVED"
    (retired,) = _events(engine, FILM_RETIRED_EVENT)
    assert retired.aggregate_id == the_duplicate["a_board"]
    assert retired.payload["retired_by"] == "Director"
    assert retired.payload["spent_usd_micros"] == 0
    assert not any(retired.payload["bought_takes"].values())
    assert retired.payload["kept_storyboard_id"] == the_duplicate["b_board"]
    assert "Dublura zilei" in retired.payload["reason"]

    a = _row(engine, the_duplicate["a"])
    assert a.status == "REJECTED"
    assert "Aprobare retrasă, era o dublură" in a.notes
    assert "Directoarea o rescrisese deja" in a.notes
    assert "fără să se fi cumpărat ceva pentru el" in a.notes
    (superseded,) = _events(engine, SUPERSEDED_EVENT)
    assert superseded.payload["was"] == "APPROVED"
    assert superseded.payload["superseded_by"] == the_duplicate["b"]

    continuity = get_continuity(engine)
    assert continuity["canon_episode_number"] == 2
    assert [s["episode_id"] for s in continuity["summaries"]] == [
        the_duplicate["first"],
        the_duplicate["b"],
    ]
    (corrected,) = _events(engine, CONTINUITY_CORRECTED_EVENT)
    assert corrected.payload["method"] == "refold"
    assert corrected.payload["canon_episode_number_before"] == 3
    assert corrected.payload["canon_episode_number"] == 2

    with Session(engine) as session:
        assert film_is_closed(session, the_duplicate["a_board"])
        assert not film_is_closed(session, the_duplicate["b_board"])
        said = enrich(
            session,
            [
                {"event_type": event.event_type, "payload": event.payload}
                for event in (superseded, corrected, retired)
            ],
        )
    assert "Aprobarea dublă a episodului «Blocked Log three» a fost retrasă" in said[0]["words_ro"]
    assert "episodul curent este 2" in said[1]["words_ro"]
    assert "a fost închis. Dublura zilei" in said[2]["words_ro"]

    # Idempotent: the next tick finds nothing, and writes nothing.
    again = retire_duplicate_episodes(WatchdogContext(engine, settings, "wd-2"))
    assert again == {"retired": [], "waiting": [], "drafts_closed": []}
    assert len(_events(engine, CONTINUITY_CORRECTED_EVENT)) == 1


def test_the_next_episode_is_numbered_after_the_kept_one(engine, the_duplicate, studio):
    repair_duplicate_days(engine, "r")
    log, ids = a_day(engine)  # today
    registry, titles = _registry(engine, studio, log, ids)

    written = _write(engine, registry, titles, log["id"], "The day after")
    with Session(engine) as session:
        drafted = session.scalars(
            select(DomainEvent).where(
                DomainEvent.event_type == "story.episode_drafted",
                DomainEvent.aggregate_id == written,
            )
        ).one()
    assert drafted.payload["episode_number"] == 3
    previously = next(p for p in registry_prompts(registry) if "PREVIOUS EPISODES" in p)
    assert "Ep. 2 " in previously and "Ep. 3 " not in previously


def registry_prompts(registry) -> list[str]:
    model = registry.get(next(iter(registry.registered_ids())))
    return model.episode_prompts()


def test_the_serial_stage_repairs_it_and_says_so(engine, the_duplicate, settings):
    outcome = run_serial_stage(engine, the_duplicate["registry"], settings)

    assert outcome["status"] == "COMPLETED", outcome
    assert outcome["reason"].startswith("Ziua ")
    assert "avea două episoade aprobate" in outcome["reason"]
    assert "fără nimic cumpărat" in outcome["reason"]
    assert "serialul revine la episodul 2" in outcome["reason"]
    assert outcome["artefacts"]["approved"] == 0
    assert _boards(engine)[the_duplicate["a_board"]] == "REJECTED"
    assert _boards(engine)[the_duplicate["b_board"]] == "APPROVED"


# ----------------------------------------------------------------------------- the guards


def test_the_owner_cannot_approve_a_days_second_episode(engine, the_day):
    with pytest.raises(StoryError, match="are deja episodul aprobat"):
        decide_episode(engine, the_day["a"], True, "", "c")
    assert _row(engine, the_day["a"]).status == "DRAFT"


def test_no_second_film_is_built_for_a_day(engine, the_day):
    _old_approval(engine, the_day["a"])

    with pytest.raises(SerialStoryboardError, match="un al doilea film"):
        storyboard_from_episode(engine, the_day["a"], "c")


def test_the_cap_never_ships_a_draft_beside_the_days_approved_episode(engine, the_day):
    with Session(engine) as session:
        r1 = session.scalars(
            select(StoryEpisode.id).where(
                StoryEpisode.log_id == the_day["log_id"], StoryEpisode.status == "REJECTED"
            )
        ).first()
    assert approve_under_drafts_cap(engine, r1, "note", "c") is None
    assert _row(engine, r1).status == "REJECTED"


# ------------------------------------------------------------------------ what still ships


def test_a_genuine_held_pass_is_still_approved_and_readied(engine, studio, settings):
    log, ids = a_day(engine, YESTERDAY_NOON())
    registry, titles = _registry(engine, studio, log, ids)
    held = _held(engine, registry, titles, log["id"], "Alone on its day")

    outcome = run_serial_stage(engine, registry, settings)

    assert outcome["status"] == "COMPLETED", outcome
    assert outcome["artefacts"]["approved"] == 1
    assert outcome["artefacts"]["episode_id"] == held and outcome["artefacts"]["storyboard_id"]
    assert "duplicates" not in outcome["artefacts"]
    assert _row(engine, held).status == "APPROVED"
    assert get_continuity(engine)["canon_episode_number"] == 1


def test_a_held_pass_whose_rewrite_the_review_refused_still_ships(engine, studio, settings):
    log, ids = a_day(engine, YESTERDAY_NOON())
    registry, titles = _registry(engine, studio, log, ids)
    held = _held(engine, registry, titles, log["id"], "The one that passed")
    _rejected(engine, registry, titles, log["id"], "Its refused rewrite", rewrite_of=held)

    outcome = run_serial_stage(engine, registry, settings)

    assert outcome["artefacts"]["approved"] == 1 and outcome["artefacts"]["episode_id"] == held
    assert _row(engine, held).status == "APPROVED"


def test_duplicate_purchase_is_blocked_even_when_board_timestamps_tie(engine, the_duplicate):
    with Session(engine) as session, session.begin():
        kept = session.get(Storyboard, the_duplicate["b_board"])
        duplicate = session.get(Storyboard, the_duplicate["a_board"])
        duplicate.created_at = kept.created_at
    with Session(engine) as session:
        assert film_is_closed(session, the_duplicate["a_board"])
        assert not film_is_closed(session, the_duplicate["b_board"])


def test_existing_duplicate_storyboard_is_not_returned_as_reusable(engine, the_duplicate):
    with pytest.raises(SerialStoryboardError, match="un al doilea film"):
        storyboard_from_episode(engine, the_duplicate["a"], "again")
    assert _boards(engine)[the_duplicate["b_board"]] == "APPROVED"


def test_retired_duplicate_cannot_be_approved_again_under_the_cap(engine, the_duplicate):
    repair_duplicate_days(engine, "repair")
    assert approve_under_drafts_cap(engine, the_duplicate["a"], "again", "c") is None
    assert _row(engine, the_duplicate["a"]).status == "REJECTED"


def test_recovery_waits_for_a_live_purchase_lease(engine, the_duplicate):
    from datetime import datetime, timedelta

    from app.media.models import FilmPurchaseLease

    with Session(engine) as session, session.begin():
        session.add(
            FilmPurchaseLease(
                storyboard_id=the_duplicate["a_board"],
                holder="existing-buyer",
                step="stills",
                acquired_at=datetime.now(UTC).isoformat(),
                expires_at=(datetime.now(UTC) + timedelta(minutes=2)).isoformat(),
            )
        )
    done = repair_duplicate_days(engine, "repair")
    assert len(done["waiting"]) == 1 and done["retired"] == []
    assert _row(engine, the_duplicate["a"]).status == "APPROVED"
    assert get_continuity(engine)["canon_episode_number"] == 3


def test_simultaneous_owner_approvals_keep_exactly_one_episode(engine, studio):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    log, ids = a_day(engine, YESTERDAY_NOON())
    registry, titles = _registry(engine, studio, log, ids)
    drafts = [_held(engine, registry, titles, log["id"], title) for title in ("First", "Second")]
    start = Barrier(2)

    def approve(episode_id):
        start.wait(timeout=5)
        try:
            return decide_episode(engine, episode_id, True, "", "parallel")["status"]
        except StoryError:
            return "REFUSED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(approve, drafts))
    assert sorted(outcomes) == ["APPROVED", "REFUSED"]
    assert sum(_row(engine, eid).status == "APPROVED" for eid in drafts) == 1
    assert get_continuity(engine)["canon_episode_number"] == 1


def test_simultaneous_storyboard_builds_reuse_one_film(engine, the_day):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    # Exercise creation rather than the already-built board in the fixture.
    with Session(engine) as session, session.begin():
        row = session.get(StoryEpisode, the_day["b"])
        original = row.storyboard_id
        row.storyboard_id = None
    start = Barrier(2)

    def build(_):
        start.wait(timeout=5)
        return storyboard_from_episode(engine, the_day["b"], "parallel")

    with ThreadPoolExecutor(max_workers=2) as pool:
        films = list(pool.map(build, range(2)))
    assert films[0] == films[1] and films[0] != original
    assert len(_boards(engine)) == 3


def test_a_delayed_review_cannot_resurrect_a_superseded_draft(engine, studio, monkeypatch):
    from app.story import review as reviews
    from app.story.review import ReviewError

    log, ids = a_day(engine, YESTERDAY_NOON())
    registry, titles = _registry(engine, studio, log, ids)
    old = _write(engine, registry, titles, log["id"], "Old draft")
    newer = _held(engine, registry, titles, log["id"], "New draft", rewrite_of=old)
    run = reviews.run_agent_task

    def answer(*args, **kwargs):
        result = run(*args, **kwargs)
        assert approve_reviewed_episode(engine, newer, "newer")["status"] == "APPROVED"
        return result

    monkeypatch.setattr(reviews, "run_agent_task", answer)
    with pytest.raises(ReviewError, match="decis"):
        review_episode(engine, registry, old, "late")
    assert _row(engine, old).status == "REJECTED"
    assert _row(engine, newer).status == "APPROVED"
    assert get_continuity(engine)["canon_episode_number"] == 1
