"""Phase 9 tables — the two truth layers, kept apart.

`../architecture/07_STORY_ENGINE.md` separates Operational Truth (what the backend recorded)
from the Narrative Layer (the showrunner's dramatised rendering of it), and states that the
narrative layer may never overwrite operational truth. That separation is structural here: a
`DailyStudioLog` is assembled by counting domain events and nothing writes to it afterwards,
while a `StoryEpisode` lives in its own table and references events rather than modifying them.

Between the two sits the narrative projection (migration 0036): the PUBLIC_SAFE view of the
day the showrunner is allowed to read. It is derived from the log's events by a fixed table
and a redaction pass, and it is the only thing that crosses from the first layer to the
second. `ContinuityState` is the serial's own memory — episode number, open threads, recent
summaries — and belongs entirely to the narrative layer.
"""

from __future__ import annotations

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class DailyStudioLog(Base):
    """What actually happened on one studio business date.

    Every field is derived by counting the event stream. No model writes any part of this: it is
    the record an episode is later checked against, so it cannot itself contain a narrative.
    """

    __tablename__ = "daily_studio_log"
    __table_args__ = (
        CheckConstraint("total_events >= 0", name="ck_daily_log_counts_positive"),
        Index("ix_daily_log_date", "business_date", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    #: ISO date in the studio's configured timezone.
    business_date: Mapped[str] = mapped_column(String(10), nullable=False)
    timezone: Mapped[str] = mapped_column(String(60), nullable=False)
    #: Count per event type, exactly as read from the stream.
    event_counts_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    total_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Who was employed that day, so an episode cannot cast someone who was not there.
    roster_json: Mapped[list] = mapped_column(JSON, nullable=False)
    #: The events an episode may be built from: id, type, and a plain description.
    notable_events_json: Mapped[list] = mapped_column(JSON, nullable=False)
    #: The PUBLIC_SAFE projection of the day (migration 0036): [{event_id, event_type, at,
    #: actor, description}], every description redacted. The showrunner reads only this.
    #: NULL on a log closed before the projection existed; filled once, from the same events.
    narrative_projection_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    #: OPEN while the day can still change; CLOSED once counted and frozen.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="CLOSED")
    closed_at: Mapped[str] = mapped_column(String(40), nullable=False)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )


class StoryEpisode(Base):
    """A dramatisation of one day, grounded in that day's events.

    Beats carry the ids of the events that inspired them. That is what makes the difference
    between a serial about this studio and a serial about an imaginary one — and it is checked
    before an episode is stored, not asserted afterwards.
    """

    __tablename__ = "story_episode"
    __table_args__ = (Index("ix_story_episode_log", "log_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    log_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("daily_studio_log.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    #: [{beat_number, scene, dialogue, event_ids, characters}]
    beats_json: Mapped[list] = mapped_column(JSON, nullable=False)
    #: Every distinct event id cited across the beats, for auditing without re-parsing.
    grounded_event_ids_json: Mapped[list] = mapped_column(JSON, nullable=False)
    #: Threads carried from the previous episode, so the serial has continuity.
    continuity_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    # DRAFT | APPROVED | REJECTED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    #: The agent that wrote it. NULL means no agent did.
    written_by_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agent.id"), nullable=True
    )
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Who passed it: "director" (the review, under the channel's policy) or "owner".
    reviewed_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: The Director's review: verdict, the computed checks, reasons, notes, run id.
    review_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    #: The storyboard this episode became, once approved. One per episode.
    storyboard_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("storyboard.id"), nullable=True
    )
    #: The draft this one rewrote after a FAIL, so the two are read together.
    rewrite_of_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("story_episode.id"), nullable=True
    )


class ContinuityState(Base):
    """The serial's memory: one row, advanced only when an episode is approved.

    `../architecture/07_STORY_ENGINE.md` asks for a canon episode number, unresolved
    narrative threads, recurring elements and previous episode summaries. They live here and
    nowhere else — never on the log, which is operational truth, and never inferred from the
    newest episode row, which may be a rejected draft.
    """

    __tablename__ = "continuity_state"
    __table_args__ = (
        CheckConstraint("canon_episode_number >= 0", name="ck_continuity_episode_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    canon_episode_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: [{"id": "T3", "text": "...", "opened_in": 2}] — open questions the serial carries.
    threads_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: Running jokes, props, places the showrunner may call back to.
    recurring_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: The last three: [{"episode_number", "episode_id", "title", "summary", "business_date"}]
    summaries_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )
