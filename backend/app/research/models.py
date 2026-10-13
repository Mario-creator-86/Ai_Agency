"""Hosts the Owner authorised for source retrieval, with the result of their last test."""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class ResearchAllowedHost(Base):
    """One Owner-authorised host (bare lowercase DNS name), next to the ones in .env.

    Only the Owner writes here, through an authenticated endpoint; no agent has a tool that
    reaches it, so the allowlist stays the Owner's. A host is a source only if the studio can
    actually read it, which is what the test columns record.
    """

    __tablename__ = "research_allowed_host"

    host: Mapped[str] = mapped_column(String(253), primary_key=True)
    added_by: Mapped[str] = mapped_column(String(50), nullable=False, default="owner")
    added_at: Mapped[str] = mapped_column(String(40), nullable=False)
    last_test_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: PASSED | FAILED — what happened when the studio last fetched the host's front page.
    last_test_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_test_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The site's own search address (OpenSearch Suggestions JSON) with ``{query}`` where the
    #: words go — the studio finds pages here instead of guessing them (migration 0030).
    search_template: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: The same kind of address, read from the host's own front page (``<link rel="search">``
    #: or ``/opensearch.xml``) when the host was tested (migration 0040). The Owner's
    #: ``search_template`` wins whenever both exist: what he typed is a decision, this is a
    #: finding, and a finding never overrides a decision.
    discovered_search_template: Mapped[str | None] = mapped_column(String(500), nullable=True)
    discovered_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: Why the last test FAILED, in a closed vocabulary the preflight can show without parsing
    #: the detail: HTTP_403 | HTTP_ERROR | RATE_LIMITED | SCRIPT_ONLY | NETWORK | OTHER.
    last_test_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("domain_event.event_id"), nullable=True)
