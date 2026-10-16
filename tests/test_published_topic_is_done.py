"""A topic whose film is out is finished, whichever of its drafts the film came from (2026-10-16).

Found live at 14:00Z: «Why the Speed of Light Is Exactly 299,792,458 m/s» shipped its second
draft (13f3a3f7), whose film was published at 06:43Z. The Director's editorial judgement had
written two more versions after it (64ef6fdc, 65ee1273), scored them lower and marked them
superseded; neither has a storyboard. `topics_in_production` read each topic by its NEWEST draft
only, so the topic counted as «live», `_selection` said «Un subiect este deja în producție», and
no subject, script or film was made for the day: the factual channel was deadlocked.

A topic is now read by its current script (the newest draft no editorial judgement superseded,
as `script_work` already reads it), and a topic with any film out is neither live nor stalled.
«Out» is an upload the channel confirmed, read as `film_is_closed` reads it: a gate refusal or
a failed upload on an older render, or on another draft's, leaves the topic owing its film.
Nothing here asks a model or a provider.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.factual.models import FactualClaim, ScriptDraft, StoryReview, TopicIdea
from app.media.models import MediaAsset, QualityControlReport, Storyboard, VideoRenderJob
from app.publishing.models import PublicationRecord
from app.publishing.services import list_channels, seed_default_channels
from app.runbook import stages
from sqlalchemy.orm import Session

#: The speed-of-light topic's evening: drafts a few seconds apart, the film the next morning.
EVENING = datetime(2026, 10, 15, 18, 32, 9, tzinfo=UTC)


def _at(seconds: float) -> str:
    return (EVENING + timedelta(seconds=seconds)).isoformat()


def _topic(engine, *, status: str = "SELECTED", title: str = "Why the Speed of Light") -> str:
    topic_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            TopicIdea(
                id=topic_id,
                title=title,
                topic="physics",
                angle="a",
                target_audience="g",
                novelty_score=0.5,
                status=status,
                created_at=_at(-60),
            )
        )
    return topic_id


def _candidate(engine) -> str:
    """A proposed topic with one verified claim: what the day should choose next."""
    topic_id = _topic(engine, status="PROPOSED", title="A new subject, with evidence")
    with Session(engine) as session, session.begin():
        session.add(
            FactualClaim(
                id=str(uuid4()),
                topic_id=topic_id,
                claim_text="A verified claim.",
                claim_type="SCIENTIFIC_FACT",
                importance="CRITICAL",
                status="SUPPORTED",
                confidence=0.9,
                created_at=_at(0),
            )
        )
    return topic_id


def _draft(
    engine,
    topic_id: str,
    *,
    at: float,
    status: str = "VERIFIED_PASS",
    review: str | None = "REVISE",
    superseded_by: str | None = None,
) -> str:
    """One draft of the topic, written ``at`` seconds into the evening, with its story review
    and, for an editorial round that lost, the version that shipped in its place."""
    script_id = str(uuid4())
    story = {}
    if superseded_by:
        story = {"editorial": {"shipped": False, "superseded_by": superseded_by}}
    with Session(engine) as session, session.begin():
        session.add(
            ScriptDraft(
                id=script_id,
                topic_id=topic_id,
                title="Why the Speed of Light",
                voiceover_full_text="text",
                status=status,
                story_json=story,
                created_at=_at(at),
            )
        )
        if review:
            session.flush()
            session.add(
                StoryReview(
                    id=str(uuid4()),
                    script_id=script_id,
                    verdict=review,
                    checks_json={},
                    retention_json={},
                    scores_json={},
                    notes_json={"notes": ["note"]},
                    estimated_seconds=30.0,
                    created_at=_at(at + 5),
                )
            )
    return script_id


def _board(engine, script_id: str, *, at: float, status: str = "APPROVED") -> str:
    board_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            Storyboard(
                id=board_id,
                script_draft_id=script_id,
                title="Storyboard: Why the Speed of Light",
                status=status,
                created_at=_at(at),
            )
        )
    return board_id


def _render(
    engine,
    board_id: str,
    *,
    verdict: str | None,
    published: bool = False,
    status: str = "PUBLISHED",
    remote_video_id: str | None = "yt-speed-of-light",
    remote_upload_status: str | None = None,
) -> str:
    """A finished render of the board, its QC verdict, and, when ``published``, a publication
    row in ``status`` (a confirmed upload unless told otherwise)."""
    asset_id = str(uuid4())
    finished = datetime.now(UTC).isoformat()
    with Session(engine) as session, session.begin():
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="RENDERED_VIDEO",
                uri_or_path=f"storage/{asset_id}.mp4",
                file_size_bytes=10,
                mime_type="video/mp4",
                width=1080,
                height=1920,
                duration_seconds=30.0,
                provider_name="PLACEHOLDER_LOCAL",
                license_status="PROPRIETARY_STUDIO",
                provenance_hash="0" * 64,
                created_at=finished,
            )
        )
        session.flush()
        session.get(Storyboard, board_id).status = "RENDERED"
        session.add(
            VideoRenderJob(
                id=str(uuid4()),
                storyboard_id=board_id,
                status="COMPLETED",
                output_asset_id=asset_id,
                started_at=finished,
                finished_at=finished,
            )
        )
        if verdict:
            session.add(
                QualityControlReport(
                    id=str(uuid4()),
                    media_asset_id=asset_id,
                    status=verdict,
                    score=0.9,
                    checks_json={},
                    failure_reasons_json=[],
                    verified_at=finished,
                )
            )
    if published:
        seed_default_channels(engine)
        channel = {c["channel_type"]: c for c in list_channels(engine)}["MAIN_FACTUAL"]
        with Session(engine) as session, session.begin():
            session.add(
                PublicationRecord(
                    id=str(uuid4()),
                    channel_id=channel["id"],
                    media_asset_id=asset_id,
                    title="Why the Speed of Light Is Exactly 299,792,458 m/s",
                    description="d",
                    tags_json=[],
                    privacy_status="private",
                    status=status,
                    idempotency_key=str(uuid4()),
                    remote_video_id=remote_video_id,
                    remote_upload_status=remote_upload_status,
                    created_at=finished,
                    published_at=finished,
                )
            )
    return asset_id


def _production(engine) -> tuple[list[str], list[str]]:
    with Session(engine) as session:
        return stages.topics_in_production(session)


# ------------------------------------------------------------------ the live deadlock


def test_a_topic_whose_shipped_draft_was_published_is_done_and_a_new_subject_is_chosen(engine):
    """The speed-of-light topic as the studio left it: a first draft sent back, the second
    shipped and published, two later editorial rounds superseded by it and never storyboarded."""
    topic = _topic(engine)
    _draft(engine, topic, at=0, review="REVISE")
    shipped = _draft(engine, topic, at=32, status="APPROVED", review="PASS")
    _draft(engine, topic, at=74, review="PASS", superseded_by=shipped)
    _draft(engine, topic, at=120, review="REVISE", superseded_by=shipped)
    board = _board(engine, shipped, at=156)
    _render(engine, board, verdict="FAILED")  # the first render, refused at 05:27Z
    _render(engine, board, verdict="PASSED", published=True)  # out at 06:43Z
    candidate = _candidate(engine)

    live, stalled = _production(engine)
    assert topic not in live and topic not in stalled
    with Session(engine) as session:
        assert stages.topic_scripts(session)[topic].id == shipped
        assert stages.topics_with_a_published_film(session) == {topic}
        # The room owes it nothing either: the later rounds are superseded, the shipped draft
        # is past the page. Nothing reopens the topic.
        assert stages.script_work(session, [topic]) == []

    chosen = stages._selection(engine)

    assert "deja în producție" not in chosen["reason"], chosen
    assert chosen["artefacts"]["topic_id"] == candidate, chosen
    with Session(engine) as session:
        assert session.get(TopicIdea, candidate).status == "SELECTED"


def test_a_film_out_from_an_older_draft_finishes_the_topic_without_the_editorial_mark(engine):
    """The publication is the fact, not the mark: a newer draft no judgement superseded (one
    sent back with no storyboard, or one whose own film the Director closed) does not reopen
    a topic whose film is already out."""
    sent_back = _topic(engine)
    published = _draft(engine, sent_back, at=0, status="APPROVED", review="PASS")
    _render(engine, _board(engine, published, at=10), verdict="PASSED", published=True)
    _draft(engine, sent_back, at=600, review="REVISE")

    closed = _topic(engine, title="The LHC upgrade")
    published = _draft(engine, closed, at=0, status="APPROVED", review="PASS")
    _render(engine, _board(engine, published, at=10), verdict="PASSED", published=True)
    newer = _draft(engine, closed, at=600, status="APPROVED", review="PASS")
    _board(engine, newer, at=610, status="REJECTED")

    live, stalled = _production(engine)

    assert live == [] and stalled == []  # done: not «în producție», not «picate la QC»


def test_a_published_film_on_an_older_storyboard_of_the_same_script_finishes_the_topic(engine):
    """Not only the newest render of the newest storyboard: a later storyboard of the same
    script, closed, does not make a published film's topic «stalled»."""
    topic = _topic(engine)
    script = _draft(engine, topic, at=0, status="APPROVED", review="PASS")
    _render(engine, _board(engine, script, at=10), verdict="PASSED", published=True)
    _board(engine, script, at=900, status="REJECTED")

    assert _production(engine) == ([], [])


# ------------------------------------------------------------------ only a confirmed upload is out

#: Every status a publication row is written in. Only the first three, with a remote video id,
#: put a film on the channel (`film_is_closed`); the rest left nothing certain there.
PUBLICATION_STATUSES = (
    "PUBLISHED",
    "SCHEDULED",
    "REMOTE_CONFIRMED",
    "PUBLISHED_SIMULATED",
    "REMOTE_UNKNOWN",
    "STARTED",
    "DRAFT_INTENT",
    "VALIDATED",
    "FAILED_RETRYABLE",
    "NEEDS_RECONCILIATION",
    "BLOCKED_GATE",
    "FAILED_FINAL",
)


def test_an_older_render_the_gate_refused_does_not_finish_a_topic_whose_new_render_waits(engine):
    """Review of 502f407, case (a): one storyboard, an older render that passed QC and that the
    publishing gate refused (BLOCKED_GATE, nothing on the channel), and a newer render waiting
    for its QC verdict. The topic still owes that film: live, and no new subject is chosen
    beside it. Any publication row used to count as «out» on every render of the topic."""
    topic = _topic(engine)
    script = _draft(engine, topic, at=0, status="APPROVED", review="PASS")
    board = _board(engine, script, at=60)
    _render(
        engine, board, verdict="PASSED", published=True, status="BLOCKED_GATE", remote_video_id=None
    )
    _render(engine, board, verdict=None)
    candidate = _candidate(engine)

    with Session(engine) as session:
        assert stages.topics_with_a_published_film(session) == set()
    assert _production(engine) == ([topic], [])

    chosen = stages._selection(engine)

    assert "deja în producție" in chosen["reason"], chosen
    assert chosen["artefacts"]["topic_id"] == topic, chosen
    with Session(engine) as session:
        assert session.get(TopicIdea, candidate).status == "PROPOSED"


def test_a_film_youtube_refused_does_not_finish_a_topic_whose_replacement_is_owed(engine):
    """Review of 502f407, case (b): the first film's upload failed for good (FAILED_FINAL,
    YouTube's «rejected»: nothing on the channel), and a replacement draft is APPROVED with a
    storyboard not rendered yet (a story repair of a film `film_is_closed` does not close).
    The replacement is owed: the topic is live, and the day does not start a second film."""
    topic = _topic(engine)
    first = _draft(engine, topic, at=0, status="APPROVED", review="PASS")
    first_board = _board(engine, first, at=60)
    _render(
        engine,
        first_board,
        verdict="PASSED",
        published=True,
        status="FAILED_FINAL",
        remote_video_id="yt-refused",
        remote_upload_status="rejected",
    )
    second = _draft(engine, topic, at=600, status="APPROVED", review="PASS")
    _board(engine, second, at=660)
    candidate = _candidate(engine)

    with Session(engine) as session:
        from app.media.shooting_sheet import film_is_closed

        assert film_is_closed(session, first_board) is False
        assert stages.topics_with_a_published_film(session) == set()
    assert _production(engine) == ([topic], [])

    chosen = stages._selection(engine)

    assert chosen["artefacts"]["topic_id"] == topic, chosen
    with Session(engine) as session:
        assert session.get(TopicIdea, candidate).status == "PROPOSED"


def test_a_film_is_out_for_its_topic_exactly_when_it_is_closed_for_production(engine):
    """`topics_with_a_published_film` reads an upload as `film_is_closed` does: every
    publication status, with a remote video id, without one, and with an empty one. A film
    closed for production finishes its topic; any other row leaves the topic to its film."""
    from app.media.shooting_sheet import film_is_closed

    boards: dict[str, tuple[str, str, str | None]] = {}
    for status in PUBLICATION_STATUSES:
        for remote in ("yt-1", None, ""):
            topic = _topic(engine, title=f"{status} {remote!r}")
            script = _draft(engine, topic, at=0, status="APPROVED", review="PASS")
            # An older storyboard carries the row; the current one waits for its render, so
            # only `topics_with_a_published_film` can finish the topic.
            board = _board(engine, script, at=10)
            _render(
                engine,
                board,
                verdict="PASSED",
                published=True,
                status=status,
                remote_video_id=remote,
            )
            _board(engine, script, at=20)
            boards[topic] = (board, status, remote)

    with Session(engine) as session:
        closed = {
            topic for topic, (board, _, _) in boards.items() if film_is_closed(session, board)
        }
        out = stages.topics_with_a_published_film(session)

    assert out == closed
    assert sorted((boards[topic][1], boards[topic][2]) for topic in out) == [
        ("PUBLISHED", "yt-1"),
        ("REMOTE_CONFIRMED", "yt-1"),
        ("SCHEDULED", "yt-1"),
    ]
    live, stalled = _production(engine)
    assert sorted(live) == sorted(set(boards) - out) and stalled == []


# ------------------------------------------------------------------ the current script


def test_a_superseded_rewrite_does_not_hide_how_the_shipped_film_stands(engine):
    """Before any publication the topic is read by the film that shipped. A shipped film whose
    render failed QC is stalled, though a superseded rewrite was sent back after it (it used to
    count as live for ever); a shipped film still waiting for its render is live, though a
    superseded rewrite was refused after it (it used to count as stalled, and the next topic
    was chosen beside a film in flight)."""
    failed = _topic(engine, title="Failed QC")
    shipped = _draft(engine, failed, at=0, status="APPROVED", review="PASS")
    _render(engine, _board(engine, shipped, at=60), verdict="FAILED")
    _draft(engine, failed, at=30, review="REVISE", superseded_by=shipped)

    rendering = _topic(engine, title="Still rendering")
    shipped = _draft(engine, rendering, at=0, status="APPROVED", review="PASS")
    _board(engine, shipped, at=60)
    _draft(engine, rendering, at=30, review="REJECT", superseded_by=shipped)

    live, stalled = _production(engine)

    assert live == [rendering]
    assert stalled == [failed]


def test_a_topic_with_no_unsuperseded_draft_still_reads_as_owing_work(engine):
    """A topic none of whose drafts is current (a record the loop never writes, but read
    defensively) is not mistaken for a finished one."""
    topic = _topic(engine)
    _draft(engine, topic, at=0, review="REVISE", superseded_by=str(uuid4()))

    assert _production(engine) == ([topic], [])


# ------------------------------------------------------------------ point 3: old scripts


def test_a_month_old_script_only_topic_the_review_refused_is_stalled_not_live(engine):
    """The shape of 48ba6eb7 (James Webb) and 8a2c07a2 (NASA asteroids), 2026-09-12: drafts
    VERIFIED_PASS, no storyboard, the newest refused by the story review. Stalled, so they do
    not hold the selection; and a sent-back one is still owed a rewrite (`script_work`), so it
    stays live: its age is not a reason, since `film_wait_days` retires films, not scripts."""
    refused = _topic(engine, title="James Webb")
    _draft(engine, refused, at=-34 * 86400, review="REVISE")
    _draft(engine, refused, at=-34 * 86400 + 30, review="REJECT")
    owed = _topic(engine, title="Sent back")
    _draft(engine, owed, at=-34 * 86400, review="REVISE")

    live, stalled = _production(engine)

    assert stalled == [refused] and live == [owed]
    with Session(engine) as session:
        assert stages.script_work(session, [refused, owed]) == [(owed, ["note"])]


# ------------------------------------------------------------------ the Owner's close


def test_closing_the_shipped_film_reads_its_topic_by_the_shipped_draft(engine):
    """«Închide filmul» says what the close does to the topic, read as the selection reads it:
    the shipped film holds its topic, not a superseded rewrite with no storyboard."""
    from app.media.film_close import _topic_after_close

    topic = _topic(engine)
    shipped = _draft(engine, topic, at=0, status="APPROVED", review="PASS")
    board = _board(engine, shipped, at=60)
    _draft(engine, topic, at=30, review="REVISE", superseded_by=shipped)

    with Session(engine) as session:
        after = _topic_after_close(session, session.get(Storyboard, board))

    assert after["freed"] is True and after["held_by"] is None, after
