from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class Integration(Base):
    __tablename__ = "integration"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(100))
    config: Mapped[dict] = mapped_column(JSON)
    encrypted_secrets: Mapped[str] = mapped_column(Text)
    secret_fields: Mapped[list] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30))
    checked_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("domain_event.event_id"))


class ServiceSelection(Base):
    __tablename__ = "service_selection"
    purpose: Mapped[str] = mapped_column(String(40), primary_key=True)
    integration_id: Mapped[str | None] = mapped_column(ForeignKey("integration.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer)
    event_id: Mapped[str] = mapped_column(ForeignKey("domain_event.event_id"))
