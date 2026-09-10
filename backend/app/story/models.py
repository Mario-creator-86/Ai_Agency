"""Phase 9 tables — the two truth layers, kept apart.

`../architecture/07_STORY_ENGINE.md` separates Operational Truth (what the backend recorded)
from the Narrative Layer (the showrunner's dramatised rendering of it), and states that the
narrative layer may never overwrite operational truth. That separation is structural here: a
`DailyStudioLog` is assembled by counting domain events and nothing writes to it afterwards,
while a `StoryEpisode` lives in its own table and references events rather than modifying them.
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
