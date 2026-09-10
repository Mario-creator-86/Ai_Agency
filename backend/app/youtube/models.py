"""Tables for the YouTube OAuth connection flow.

One row per channel the Owner authorises, so AMN-AI can hold several independent connections at
once without any of them being special. Nothing about a channel is hardcoded: the identity is
whatever Google returns for the account that granted consent.

What is deliberately *not* in a column:

  * **the client secret and the refresh token.** Both live inside ``encrypted_secrets``, a Fernet
    blob written by the same vault the rest of the studio uses. ``secret_fields`` names which of
    them exist, so the interface can say "connected" without anything decrypting a secret to
    answer the question, and no view model can leak one by accident.

The state table exists because an OAuth redirect comes back through the user's browser, where the
Owner credential is not present. The random ``state`` is therefore the only thing tying the
callback to the request that started it: it is single-use, short-lived, and checked before a code
is exchanged for anything.
"""

from __future__ import annotations

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base

#: How long an authorisation may sit unfinished before its state is refused.
OAUTH_STATE_TTL_SECONDS = 600


class YouTubeConnection(Base):
    """One authorised YouTube channel, or one waiting to be authorised."""

    __tablename__ = "youtube_connection"
    __table_args__ = (
        UniqueConstraint("name", name="uq_youtube_connection_name"),
        CheckConstraint(
            "status IN ('AUTH_REQUIRED','CONNECTED','ERROR')", name="ck_youtube_connection_status"
        ),
        Index("ix_youtube_connection_status", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    #: The Owner's own label for this connection. Unique, so two connections cannot be confused
    #: for one another in a list or as a publishing target. No name is special to the code.
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    #: Google OAuth client id. Not a secret — it travels in the authorisation URL — so it is a
    #: plain column and may be shown back to the Owner to confirm which Google project is in use.
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Must match a redirect URI registered on that Google client, exactly.
    redirect_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    #: Fernet blob: {"client_secret": ..., "refresh_token": ...}. Never returned by any route.
    encrypted_secrets: Mapped[str] = mapped_column(Text, nullable=False)
    #: Which secrets the blob currently holds. Lets a view answer "is this connected?" without
    #: decrypting anything.
    secret_fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: AUTH_REQUIRED (credentials saved, no token) | CONNECTED | ERROR (last attempt failed).
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="AUTH_REQUIRED")

    #: Everything below is what Google said about the authorised account. Never typed by hand.
    remote_channel_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    remote_channel_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: The rest of the channels.list answer worth keeping: custom URL, thumbnail, counts, and the
    #: uploads playlist. Stored as returned so a later reader can see what was actually granted.
    channel_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: The scopes Google actually granted, which can be narrower than the ones requested.
    granted_scopes: Mapped[str | None] = mapped_column(String(600), nullable=True)

    connected_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_checked_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: Why the last attempt failed, in the Owner's language. Cleared on success.
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )


class YouTubeOAuthState(Base):
    """One pending authorisation. Single-use, and useless after it expires."""

    __tablename__ = "youtube_oauth_state"
    __table_args__ = (Index("ix_youtube_oauth_state_connection", "connection_id"),)

    #: Cryptographically random. This is the whole CSRF defence for a callback that cannot carry
    #: the Owner credential, so it is never derived from anything guessable.
    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    connection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("youtube_connection.id"), nullable=False
    )
    #: The redirect URI this authorisation was started with. The token exchange must present the
    #: same value, so it is pinned here rather than re-read from a row that may have been edited.
    redirect_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    expires_at: Mapped[str] = mapped_column(String(40), nullable=False)
    #: Set the moment the state is accepted, so a replayed callback finds it already spent.
    used_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
