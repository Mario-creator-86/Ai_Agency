"""Words per beat is a recommendation the Director decides (the Owner, 2026-10-13: «nu trebuie
să fie ceva fix, este ceva recomandat, dar nici să respingi serialul de la asta; pot lua decizii
singuri, iar Directoarea este aici pentru astfel de situații»).

Read on his page the same day: «The Ninth Rewrite» (13.10.2026) was REJECTED by the computed
checks for a 23-word beat (9 din 10 verificări) before the Director read it, and the cover
signed that FAIL as «Verdictul Directorului». Now the band is `advisory`: measured and shown,
never a reason to ask the writer again, and the Director reads the episode with the measure and
decides; a verdict the computed rules give without her reading is signed by the checks.

Offline: the showrunner and the Director are scripted fakes; no model, no provider."""

from __future__ import annotations

from app.models import DomainEvent
from app.story.models import StoryEpisode
from app.story.review import failed_rules, outside_recommendations, review_episode
from app.story.services import list_episodes
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_serial_pipeline import (  # noqa: F401 - the studio fixture
    KAEL,
    SARAH,
    beats_for,
    checks_of,
    fake_director,
    letters_day,
    registry,
    staffed,
    written,
)

#: Twenty-three spoken words: one over the band, 9.2 seconds at the studio's rate.
LONG = (
    "Right, the cut runs long again, so we trim the middle, keep the hook, and send it back "
    "before lunch today, please, Kael."
)
assert len(LONG.split()) == 23


def _event(session: Session, kind: str, episode_id: str) -> DomainEvent:
    return session.scalars(
        select(DomainEvent).where(
            DomainEvent.event_type == kind, DomainEvent.aggregate_id == episode_id
        )
    ).one()


def _over_the_band(engine, monkeypatch, asked: list[str] | None = None) -> dict:
    _, ids = letters_day(engine)
    beats = beats_for(ids, [SARAH, KAEL])
    beats[2]["lines"] = [{"speaker": SARAH, "text": LONG}]
    return written(engine, monkeypatch, beats, asked)


def test_a_beat_over_the_band_is_measured_as_a_recommendation_not_refused(
    engine,
    staffed,  # noqa: F811 - the fixture imported from test_serial_pipeline
    monkeypatch,
):
    asked: list[str] = []
    episode = _over_the_band(engine, monkeypatch, asked)

    assert len(asked) == 1, "the showrunner was not asked again for a recommendation"
    checks = checks_of(engine, episode["id"])
    words = checks["words_per_beat"]
    assert words["advisory"] is True and words["passed"] is False
    assert words["outside"] == [3] and words["per_beat"][2] == 23
    assert "recomandarea de 8-22" in words["reason"] and "decide Directoarea" in words["reason"]
    assert failed_rules(checks) == []
    assert outside_recommendations(checks) == ["words_per_beat"]
    # The brief says the band is a recommendation, and keeps the figures the writer aims for.
    assert "Aim for 8 to 22 spoken words" in asked[0]
    assert "a recommendation the Director weighs, not a rule" in asked[0]


def test_the_director_reads_a_beat_over_the_band_and_decides(
    engine,
    staffed,  # noqa: F811 - the fixture imported from test_serial_pipeline
    monkeypatch,
):
    episode = _over_the_band(engine, monkeypatch)
    calls: list[str] = []
    fake_director(monkeypatch, "PASS", calls=calls)

    review = review_episode(engine, registry(), episode["id"])

    assert review["verdict"] == "PASS"
    assert len(calls) == 1, "she was asked: a recommendation refuses nothing"
    prompt = calls[0]
    assert '"recommendations"' in prompt
    assert '"outside": [3]' in prompt and '"recommended": [8, 22]' in prompt
    assert "5. Recommendations." in prompt and "flagged, not refused" in prompt
    assert review["checks"]["words_per_beat"]["passed"] is False
    with Session(engine) as session:
        row = session.get(StoryEpisode, episode["id"])
        assert row.status == "DRAFT" and row.review_json["model_used"] is True
        reviewed = _event(session, "story.episode_reviewed", episode["id"])
        assert reviewed.payload["checks_failed"] == []
        assert reviewed.payload["recommendations_outside"] == ["words_per_beat"]


def test_her_fail_on_such_a_beat_is_hers(
    engine,
    staffed,  # noqa: F811 - the fixture imported from test_serial_pipeline
    monkeypatch,
):
    episode = _over_the_band(engine, monkeypatch)
    fake_director(monkeypatch, "FAIL", notes="Beat 3 is too fast to follow: 23 words.")

    review = review_episode(engine, registry(), episode["id"])

    assert review["verdict"] == "FAIL"
    with Session(engine) as session:
        row = session.get(StoryEpisode, episode["id"])
        assert row.status == "REJECTED" and row.reviewed_by == "director"
        assert row.notes == "Beat 3 is too fast to follow: 23 words."
        assert _event(session, "story.episode_rejected", episode["id"]).payload["reviewed_by"] == (
            "director"
        )


def test_a_rule_the_checks_refuse_is_signed_by_the_checks_not_the_director(
    engine,
    staffed,  # noqa: F811 - the fixture imported from test_serial_pipeline
    monkeypatch,
):
    _, ids = letters_day(engine)
    episode = written(engine, monkeypatch, beats_for(ids, [SARAH]))  # one speaker: the cast rule
    calls: list[str] = []
    fake_director(monkeypatch, "PASS", calls=calls)

    review = review_episode(engine, registry(), episode["id"])

    assert review["verdict"] == "FAIL" and calls == []
    assert review["checks"]["cast"]["passed"] is False
    with Session(engine) as session:
        row = session.get(StoryEpisode, episode["id"])
        assert row.status == "REJECTED" and row.reviewed_by == "checks"
        assert row.review_json["model_used"] is False
        assert _event(session, "story.episode_rejected", episode["id"]).payload["reviewed_by"] == (
            "checks"
        )
    (listed,) = [e for e in list_episodes(engine) if e["id"] == episode["id"]]
    assert listed["reviewed_by"] == "checks"
