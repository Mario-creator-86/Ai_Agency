from sqlalchemy import JSON, Boolean, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Studio(Base):
    __tablename__ = "studio"
    __table_args__ = (CheckConstraint("id = 1"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    timezone: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[str] = mapped_column(String(40))


class OwnerPolicy(Base):
    __tablename__ = "owner_policy"
    __table_args__ = (CheckConstraint("id = 1"), CheckConstraint("version >= 1"))

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    autonomy_stopped: Mapped[bool] = mapped_column(Boolean)
    updated_at: Mapped[str] = mapped_column(String(40))


class DomainEvent(Base):
    __tablename__ = "domain_event"
    __table_args__ = {"sqlite_autoincrement": True}

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True)
    event_type: Mapped[str] = mapped_column(String(100))
    timestamp: Mapped[str] = mapped_column(String(40))
    aggregate_type: Mapped[str] = mapped_column(String(50))
    aggregate_id: Mapped[str] = mapped_column(String(36))
    aggregate_version: Mapped[int] = mapped_column(Integer)
    correlation_id: Mapped[str] = mapped_column(String(36))
    causation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer)
    visibility: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSON)


class CommandRecord(Base):
    __tablename__ = "command_record"

    idempotency_key: Mapped[str] = mapped_column(String(36), primary_key=True)
    command_type: Mapped[str] = mapped_column(String(100))
    payload_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40))


class Room(Base):
    __tablename__ = "room"
    __table_args__ = (CheckConstraint("width > 0 AND height > 0"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    studio_id: Mapped[int] = mapped_column(ForeignKey("studio.id"))
    name: Mapped[str] = mapped_column(String(100))
    purpose: Mapped[str] = mapped_column(Text)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer)
    event_id: Mapped[str] = mapped_column(ForeignKey("domain_event.event_id"))


# Register Phase 1, Phase 2, Phase 4, Phase 5, and Phase 6 models with Base.metadata
import app.agents.models  # noqa: F401, E402
import app.factual.models  # noqa: F401, E402
import app.media.models  # noqa: F401, E402
import app.publishing.models  # noqa: F401, E402
import app.workflows.models  # noqa: F401, E402


import app.integrations.models  # noqa: F401, E402
