"""The YouTube OAuth 2.0 authorization-code flow, offline access, and what it stores.

The Owner types four things: a name, a Google client id, a client secret and the redirect URI
registered on that client. Everything else about a channel — its id, its title, its handle, its
counts — is read from Google after consent and saved automatically, because a channel id typed by
hand is a claim, while one returned by ``channels.list(mine=true)`` is evidence.

Guarantees this module is responsible for:

  * **A secret never travels back out.** The client secret and the refresh token live only inside
    the vault blob. :func:`connection_view` is the single way a connection is rendered, and it has
    no branch that can include either.
  * **A callback cannot be forged or replayed.** The ``state`` is 43 random characters, stored
    before the browser leaves, single-use, and expired after ten minutes.
  * **Consent is forced only when a refresh token is actually needed.** Google returns one on
    first consent, and thereafter only when asked; so ``prompt=consent`` is sent when nothing is
    stored yet and on an explicit reconnect, and omitted when a working token already exists.
  * **Nothing is hardcoded.** No channel id, no account name, no token, no client. Two channels
    are two rows, and neither is privileged.
"""

from __future__ import annotations

import json
import logging
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app.integrations.vault import CredentialVault
from app.services import append_event, utc_now
from app.youtube.models import OAUTH_STATE_TTL_SECONDS, YouTubeConnection, YouTubeOAuthState

logger = logging.getLogger("studio.youtube")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

#: Read the channel the Owner authorised, upload to it, and read its statistics. Requested
#: together so one consent covers everything the studio does with a channel; Google reports
#: back what it actually granted. The statistics scope was missing until 2026-09-18, so a
#: reconnect could not grant it and the day's statistics read failed on every refresh; a
#: connection made before then must be reconnected once to add it.
SCOPES = (
    "https://www.googleapis.com/auth/youtube.readonly "
    "https://www.googleapis.com/auth/youtube.upload "
    "https://www.googleapis.com/auth/yt-analytics.readonly"
)

#: What each use of a connection needs Google to have granted. Uploading needs the upload
#: scope; the statistics are read through the YouTube Analytics API, whose adapter
#: (`app.providers.youtube_analytics`) asks for yt-analytics.readonly. Measured on the
#: Owner's copy on 2026-09-18: both of his connections hold youtube.readonly and
#: youtube.upload and not the statistics scope, because `SCOPES` above never asked for it.
UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
STATISTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"

#: The ledger lines `app.analytics.services` writes when Google refuses, or never answers, a
#: stored connection: a token refresh (the token every use of the account shares), or a
#: statistics report the token was good for. Aggregate `youtube_connection` / the connection
#: id; payload `connection_id, during, http_status, oauth_error, auth_refused, ...`, never a
#: token. Named here too so the preflight reads them without importing the analytics stage;
#: tests/test_readiness.py holds the two copies equal.
TOKEN_REFRESH_FAILED = "youtube.token_refresh_failed"
ANALYTICS_REFUSED = "youtube.analytics_refused"


def granted_scope_set(row: YouTubeConnection) -> frozenset[str] | None:
    """The scopes Google reported granting, as stored at consent; None when none was stored.

    None is "not recorded", never "nothing granted": a row written before the column was
    filled has no answer to give, and reading that as a refusal would invent a fault.
    """
    stored = (row.granted_scopes or "").split()
    return frozenset(stored) if stored else None


def scope_label(scope: str) -> str:
    """The last part of a scope URL, the name Google's consent screen and docs use."""
    return scope.rstrip("/").rsplit("/", 1)[-1]


#: Exactly the parts the Owner's brief asks for.
CHANNEL_PARTS = "snippet,id,contentDetails,statistics"

STATUS_AUTH_REQUIRED = "AUTH_REQUIRED"
STATUS_CONNECTED = "CONNECTED"
STATUS_ERROR = "ERROR"


class YouTubeConnectionError(Exception):
    """A refusal the Owner can act on. Never carries a secret in its message."""


# ------------------------------------------------------------------------------ transport --


#: SELL-07, in the Owner's words: Google answers invalid_grant once a grant is revoked, and a
#: Google OAuth app left in "Testing" gives refresh tokens that expire after seven days.
INVALID_GRANT_WORDS = (
    "Google a refuzat accesul la contul YouTube (HTTP {code}, invalid_grant): conexiunea a "
    "expirat sau a fost revocată. Reconectează contul YouTube. Dacă aplicația Google OAuth "
    "este în modul Testing, Google face tokenurile să expire după 7 zile: trece ecranul de "
    "consimțământ în „In production” ca să nu se mai întâmple."
)


def google_refusal_words(code: int, body: str) -> str:
    """Google's refusal of an OAuth request, said to the Owner.

    Google's own code and description are kept (redirect_uri_mismatch, access_denied say
    exactly what to change), but read out of its JSON, never shown as JSON; invalid_grant is
    explained, because its usual cause on a new install is the seven-day Testing token.
    """
    try:
        parsed = json.loads(body) if body else {}
    except ValueError:
        parsed = None
    if not isinstance(parsed, dict):
        return f"Google a răspuns HTTP {code}: {body.strip()[:300]}".rstrip(": ")
    error = parsed.get("error")
    if isinstance(error, dict):  # the APIs' shape, rather than the token endpoint's
        word = str(error.get("status") or error.get("code") or "")
        description = str(error.get("message") or "")
    else:
        word = str(error or "")
        description = str(parsed.get("error_description") or "")
    if word == "invalid_grant":
        return INVALID_GRANT_WORDS.format(code=code)
    said = " — ".join(part for part in (word, description) if part)
    return f"Google a răspuns HTTP {code}" + (f": {said[:300]}" if said else ".")


def _post_form(url: str, form: dict[str, str], *, timeout: int = 20) -> dict:
    """POST an x-www-form-urlencoded body and return the parsed JSON answer.

    Google's error bodies are quoted verbatim because they say the useful thing — redirect_uri
    mismatch, invalid_grant, consent revoked — and replacing that with "something went wrong"
    would throw away the only part that tells the Owner what to change. The request body, which
    contains the secret, is never logged.
    """
    data = urllib.parse.urlencode(form).encode()
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = response.read().decode()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        logger.warning("google_oauth_http_error", extra={"status": exc.code})
        raise YouTubeConnectionError(google_refusal_words(exc.code, detail)) from None
    except OSError as exc:
        raise YouTubeConnectionError(f"Google nu a putut fi contactat: {exc}") from None


def _get_json(url: str, access_token: str, *, timeout: int = 20) -> dict:
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {access_token}"}, method="GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:500]
        raise YouTubeConnectionError(f"YouTube a răspuns {exc.code}: {detail}") from None
    except OSError as exc:
        raise YouTubeConnectionError(f"YouTube nu a putut fi contactat: {exc}") from None


def fetch_channel(access_token: str) -> dict:
    """``channels.list(part=snippet,id,contentDetails,statistics&mine=true)``.

    Returns the first channel of the authorised account. An account with no channel is a real
    situation — a Google account that never created one — and is refused with a message that says
    so, rather than storing an empty identity.
    """
    query = urllib.parse.urlencode({"part": CHANNEL_PARTS, "mine": "true"})
    payload = _get_json(f"{YOUTUBE_API_BASE}/channels?{query}", access_token)
    items = payload.get("items") or []
    if not items:
        raise YouTubeConnectionError(
            "Contul Google autorizat nu are niciun canal YouTube. "
            "Creează canalul, apoi reia conectarea."
        )
    return items[0]


def _channel_snapshot(item: dict) -> dict:
    """Keep the parts of the answer worth showing, and nothing that could grow unbounded."""
    snippet = item.get("snippet") or {}
    statistics = item.get("statistics") or {}
    content = (item.get("contentDetails") or {}).get("relatedPlaylists") or {}
    thumbnails = snippet.get("thumbnails") or {}
    thumbnail = next(
        (
            url
            for size in ("high", "medium", "default")
            if isinstance(url := (thumbnails.get(size) or {}).get("url"), str) and url.strip()
        ),
        None,
    )
    return {
        "custom_url": snippet.get("customUrl"),
        "description": (snippet.get("description") or "")[:500],
        "published_at": snippet.get("publishedAt"),
        "country": snippet.get("country"),
        "thumbnail_url": thumbnail,
        "uploads_playlist_id": content.get("uploads"),
        "subscriber_count": statistics.get("subscriberCount"),
        "video_count": statistics.get("videoCount"),
        "view_count": statistics.get("viewCount"),
        "hidden_subscriber_count": statistics.get("hiddenSubscriberCount"),
    }


# ----------------------------------------------------------------------------------- views --


def connection_view(row: YouTubeConnection) -> dict:
    """The only shape a connection is ever returned in.

    There is deliberately no parameter that would add the client secret or the refresh token.
    Whether a token exists is answered from ``secret_fields``, so answering the question never
    requires decrypting one.
    """
    return {
        "id": row.id,
        "name": row.name,
        "client_id": row.client_id,
        "redirect_uri": row.redirect_uri,
        "status": row.status,
        "connected": row.status == STATUS_CONNECTED,
        # pragma: allowlist nextline secret -- a field-name test; no value is present here
        "has_client_secret": "client_secret" in (row.secret_fields or []),
        "has_refresh_token": "refresh_token" in (row.secret_fields or []),
        "channel": {
            "id": row.remote_channel_id,
            "title": row.remote_channel_title,
            **(row.channel_snapshot or {}),
        }
        if row.remote_channel_id
        else None,
        "granted_scopes": (row.granted_scopes or "").split() or None,
        "connected_at": row.connected_at,
        "last_checked_at": row.last_checked_at,
        "last_error": row.last_error,
        "created_at": row.created_at,
    }


def list_connections(engine: Engine) -> list[dict]:
    with Session(engine) as session:
        rows = session.scalars(
            select(YouTubeConnection).order_by(YouTubeConnection.created_at)
        ).all()
        return [connection_view(row) for row in rows]


def get_connection(engine: Engine, connection_id: str) -> dict | None:
    with Session(engine) as session:
        row = session.get(YouTubeConnection, connection_id)
        return connection_view(row) if row else None


# ------------------------------------------------------------------------------- lifecycle --


def _validate_redirect_uri(redirect_uri: str) -> str:
    parsed = urllib.parse.urlparse(redirect_uri.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise YouTubeConnectionError(
            "Redirect URI trebuie să fie o adresă http sau https completă, "
            "ex. http://127.0.0.1:8000/auth/youtube/callback"
        )
    if parsed.query or parsed.fragment:
        raise YouTubeConnectionError("Redirect URI nu poate conține parametri sau fragment.")
    return redirect_uri.strip()


def create_connection(
    engine: Engine,
    vault: CredentialVault,
    *,
    name: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    correlation_id: str,
) -> dict:
    """Save the four things the Owner types. Contacts nothing and authorises nothing."""
    name = name.strip()
    client_id = client_id.strip()
    if not name:
        raise YouTubeConnectionError("Dă conexiunii un nume, ca s-o poți distinge de celelalte.")
    if not client_id or not client_secret.strip():
        raise YouTubeConnectionError("Client ID și Client Secret sunt obligatorii.")
    redirect_uri = _validate_redirect_uri(redirect_uri)

    with Session(engine) as session, session.begin():
        clash = session.scalar(select(YouTubeConnection).where(YouTubeConnection.name == name))
        if clash is not None:
            raise YouTubeConnectionError(f"Există deja o conexiune numită {name!r}.")
        row = YouTubeConnection(
            id=str(uuid4()),
            name=name,
            client_id=client_id,
            redirect_uri=redirect_uri,
            encrypted_secrets=vault.encrypt({"client_secret": client_secret.strip()}),
            secret_fields=["client_secret"],
            status=STATUS_AUTH_REQUIRED,
            channel_snapshot={},
            created_at=utc_now(),
        )
        session.add(row)
        event = append_event(
            session,
            "youtube.connection_created",
            "youtube_connection",
            row.id,
            1,
            {"name": name, "redirect_uri": redirect_uri, "authorised": False},
            correlation_id,
        )
        row.event_id = event.event_id
        session.flush()
        return connection_view(row)


def update_connection(
    engine: Engine,
    vault: CredentialVault,
    connection_id: str,
    *,
    name: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
    redirect_uri: str | None = None,
    correlation_id: str,
) -> dict:
    """Edit the typed fields.

    Changing the Google client invalidates any refresh token issued by the old one, so the token
    is dropped and the connection returns to AUTH_REQUIRED rather than keeping a credential that
    would fail at the worst moment.
    """
    with Session(engine) as session, session.begin():
        row = session.get(YouTubeConnection, connection_id)
        if row is None:
            raise YouTubeConnectionError("Conexiunea nu există.")
        secrets_blob = vault.decrypt(row.encrypted_secrets)
        client_changed = False

        if name is not None and name.strip() and name.strip() != row.name:
            clash = session.scalar(
                select(YouTubeConnection).where(YouTubeConnection.name == name.strip())
            )
            if clash is not None:
                raise YouTubeConnectionError(f"Există deja o conexiune numită {name.strip()!r}.")
            row.name = name.strip()
        if client_id is not None and client_id.strip() and client_id.strip() != row.client_id:
            row.client_id = client_id.strip()
            client_changed = True
        if client_secret is not None and client_secret.strip():
            secrets_blob["client_secret"] = client_secret.strip()
            client_changed = True
        if redirect_uri is not None and redirect_uri.strip():
            row.redirect_uri = _validate_redirect_uri(redirect_uri)

        if client_changed and "refresh_token" in secrets_blob:
            secrets_blob.pop("refresh_token", None)
            row.status = STATUS_AUTH_REQUIRED
            row.connected_at = None
            row.last_error = (
                "Datele clientului Google s-au schimbat, deci vechiul token nu mai e valabil. "
                "Apasă Conectează YouTube."
            )
        row.encrypted_secrets = vault.encrypt(secrets_blob)
        row.secret_fields = sorted(secrets_blob)
        append_event(
            session,
            "youtube.connection_updated",
            "youtube_connection",
            row.id,
            2,
            {"name": row.name, "client_changed": client_changed, "status": row.status},
            correlation_id,
        )
        session.flush()
        return connection_view(row)


def delete_connection(engine: Engine, connection_id: str, *, correlation_id: str) -> dict:
    with Session(engine) as session, session.begin():
        row = session.get(YouTubeConnection, connection_id)
        if row is None:
            raise YouTubeConnectionError("Conexiunea nu există.")
        name = row.name
        session.execute(
            delete(YouTubeOAuthState).where(YouTubeOAuthState.connection_id == connection_id)
        )
        session.delete(row)
        append_event(
            session,
            "youtube.connection_deleted",
            "youtube_connection",
            connection_id,
            3,
            {"name": name},
            correlation_id,
        )
        return {"deleted": connection_id, "name": name}


# ------------------------------------------------------------------------ authorisation --


def begin_authorization(
    engine: Engine,
    connection_id: str,
    *,
    force_consent: bool = False,
    correlation_id: str,
) -> dict:
    """Build the Google consent URL and remember the state that must come back with it."""
    with Session(engine) as session, session.begin():
        row = session.get(YouTubeConnection, connection_id)
        if row is None:
            raise YouTubeConnectionError("Conexiunea nu există.")
        if "client_secret" not in (row.secret_fields or []):
            raise YouTubeConnectionError(
                "Salvează întâi Client ID și Client Secret pentru această conexiune."
            )

        state = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        session.add(
            YouTubeOAuthState(
                state=state,
                connection_id=row.id,
                redirect_uri=row.redirect_uri,
                created_at=now.isoformat(),
                expires_at=(now + timedelta(seconds=OAUTH_STATE_TTL_SECONDS)).isoformat(),
            )
        )
        # Google issues a refresh token on first consent, and afterwards only when asked. Force
        # the prompt when there is nothing stored, or when the Owner explicitly reconnects.
        needs_consent = force_consent or "refresh_token" not in (row.secret_fields or [])
        params = {
            "client_id": row.client_id,
            "redirect_uri": row.redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "access_type": "offline",
            "include_granted_scopes": "true",
            "state": state,
        }
        if needs_consent:
            params["prompt"] = "consent"
        append_event(
            session,
            "youtube.authorization_started",
            "youtube_connection",
            row.id,
            4,
            {"forced_consent": needs_consent, "redirect_uri": row.redirect_uri},
            correlation_id,
        )
        return {
            "authorization_url": f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}",
            "expires_in_seconds": OAUTH_STATE_TTL_SECONDS,
            "forced_consent": needs_consent,
        }


def _claim_state(session: Session, state: str) -> YouTubeOAuthState:
    """Accept a state exactly once, and only inside its window."""
    row = session.get(YouTubeOAuthState, state)
    if row is None:
        raise YouTubeConnectionError("Cerere de autorizare necunoscută sau deja folosită.")
    if row.used_at is not None:
        raise YouTubeConnectionError("Această autorizare a fost deja folosită.")
    if datetime.fromisoformat(row.expires_at) < datetime.now(UTC):
        raise YouTubeConnectionError("Autorizarea a expirat. Reia conectarea.")
    row.used_at = utc_now()
    return row


def _record_failure(
    engine: Engine, connection_id: str, reason: str, event_type: str, version: int, correlation: str
) -> None:
    """Persist why an attempt failed, in a transaction of its own.

    It has to be its own transaction: recording the failure inside the one that then raises would
    be rolled back with it, leaving the connection looking untouched precisely when the Owner
    needs to know what went wrong.
    """
    with Session(engine) as session, session.begin():
        row = session.get(YouTubeConnection, connection_id)
        if row is None:
            return
        row.status = STATUS_ERROR
        row.last_error = reason
        row.last_checked_at = utc_now()
        append_event(
            session,
            event_type,
            "youtube_connection",
            connection_id,
            version,
            {"reason": reason[:300]},
            correlation,
        )
        if "invalid_grant" in reason:
            # Only he can authorise the account again: a card in his window of decisions.
            from app.decisions.sources import youtube_refused  # noqa: PLC0415

            youtube_refused(session, row, reason, source="youtube")


def mark_reconnect_needed(
    engine: Engine, connection_id: str, reason: str, *, correlation_id: str
) -> None:
    """Google refused the account during an upload (PUB-01, SELL-07): the connection is ERROR
    with the Romanian reason, and the refusal is written the way the analytics stage writes
    its own (`TOKEN_REFRESH_FAILED`, ``auth_refused``), so every reader of the record — the
    preflight, the page — says «Reconectează» instead of the studio trying again tomorrow.
    A reconnect (`complete_authorization`) or a verification sets it CONNECTED again."""
    words = (reason or "").strip() or "Google a refuzat contul YouTube."
    if "Reconectează" not in words:
        words = f"{words.rstrip('.')}. Reconectează contul YouTube."
    with Session(engine) as session, session.begin():
        row = session.get(YouTubeConnection, connection_id)
        if row is None:
            return
        row.status = STATUS_ERROR
        row.last_error = words[:500]
        row.last_checked_at = utc_now()
        append_event(
            session,
            TOKEN_REFRESH_FAILED,
            "youtube_connection",
            connection_id,
            1,
            {
                "connection_id": connection_id,
                "auth_refused": True,
                "during": "upload",
                "reason": words[:300],
            },
            correlation_id,
        )
        from app.decisions.sources import youtube_refused  # noqa: PLC0415

        youtube_refused(session, row, words, source="publishing")


def complete_authorization(
    engine: Engine, vault: CredentialVault, *, code: str, state: str, correlation_id: str
) -> dict:
    """Exchange the code, read the channel it belongs to, and store both.

    Three steps, each with its own transaction, in this order for a reason:

      1. spend the state — a failed exchange must not leave a state a replay could reuse, and
         Google has already burned the authorisation code by then anyway;
      2. talk to Google with no transaction open, so a slow call cannot hold the database;
      3. store the token and the channel identity together, so a connection can never hold a
         refresh token without the identity that proves whose token it is.
    """
    with Session(engine) as session, session.begin():
        pending = _claim_state(session, state)
        row = session.get(YouTubeConnection, pending.connection_id)
        if row is None:
            raise YouTubeConnectionError("Conexiunea nu mai există.")
        connection_id = row.id
        client_id = row.client_id
        redirect_uri = pending.redirect_uri
        blob = vault.decrypt(row.encrypted_secrets)

    client_secret = blob.get("client_secret")
    if not client_secret:
        raise YouTubeConnectionError("Conexiunea nu are Client Secret salvat.")

    try:
        tokens = _post_form(
            GOOGLE_TOKEN_URL,
            {
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        access_token = tokens.get("access_token")
        if not access_token:
            raise YouTubeConnectionError("Google nu a returnat un access token.")
        refresh_token = tokens.get("refresh_token") or blob.get("refresh_token")
        if not refresh_token:
            raise YouTubeConnectionError(
                "Google nu a returnat un refresh token. Folosește Reconectează, "
                "care cere din nou consimțământul explicit."
            )
        channel = fetch_channel(access_token)
    except YouTubeConnectionError as exc:
        _record_failure(
            engine, connection_id, str(exc), "youtube.authorization_failed", 5, correlation_id
        )
        raise

    with Session(engine) as session, session.begin():
        row = session.get(YouTubeConnection, connection_id)
        if row is None:
            raise YouTubeConnectionError("Conexiunea nu mai există.")
        blob["refresh_token"] = refresh_token
        row.encrypted_secrets = vault.encrypt(blob)
        row.secret_fields = sorted(blob)
        row.remote_channel_id = channel.get("id")
        row.remote_channel_title = (channel.get("snippet") or {}).get("title")
        row.channel_snapshot = _channel_snapshot(channel)
        row.granted_scopes = tokens.get("scope")
        row.status = STATUS_CONNECTED
        row.connected_at = utc_now()
        row.last_checked_at = row.connected_at
        row.last_error = None
        from app.decisions.sources import youtube_reconnected  # noqa: PLC0415

        youtube_reconnected(session, row.id)
        append_event(
            session,
            "youtube.connected",
            "youtube_connection",
            row.id,
            6,
            {
                "name": row.name,
                "channel_id": row.remote_channel_id,
                "channel_title": row.remote_channel_title,
                "granted_scopes": row.granted_scopes,
            },
            correlation_id,
        )
        session.flush()
        return connection_view(row)


def access_token_for(engine: Engine, vault: CredentialVault, connection_id: str) -> str:
    """Trade the stored refresh token for a fresh access token."""
    with Session(engine) as session:
        row = session.get(YouTubeConnection, connection_id)
        if row is None:
            raise YouTubeConnectionError("Conexiunea nu există.")
        blob = vault.decrypt(row.encrypted_secrets)
    refresh_token = blob.get("refresh_token")
    if not refresh_token:
        raise YouTubeConnectionError("Conexiunea nu este autorizată. Apasă Conectează YouTube.")
    tokens = _post_form(
        GOOGLE_TOKEN_URL,
        {
            "client_id": row.client_id,
            "client_secret": blob.get("client_secret", ""),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    access_token = tokens.get("access_token")
    if not access_token:
        raise YouTubeConnectionError("Google nu a reînnoit accesul pentru această conexiune.")
    return access_token


def verify_connection(
    engine: Engine, vault: CredentialVault, connection_id: str, *, correlation_id: str
) -> dict:
    """Re-read the channel with the stored token, and record what came back.

    This is the only honest way to answer "is it still connected": a token that was valid last
    week may have been revoked in the Google account since.
    """
    try:
        access_token = access_token_for(engine, vault, connection_id)
        channel = fetch_channel(access_token)
    except YouTubeConnectionError as exc:
        _record_failure(
            engine, connection_id, str(exc), "youtube.verification_failed", 7, correlation_id
        )
        raise

    with Session(engine) as session, session.begin():
        row = session.get(YouTubeConnection, connection_id)
        if row is None:
            raise YouTubeConnectionError("Conexiunea nu există.")
        row.remote_channel_id = channel.get("id")
        row.remote_channel_title = (channel.get("snippet") or {}).get("title")
        row.channel_snapshot = _channel_snapshot(channel)
        row.status = STATUS_CONNECTED
        row.last_checked_at = utc_now()
        row.last_error = None
        from app.decisions.sources import youtube_reconnected  # noqa: PLC0415

        youtube_reconnected(session, connection_id)
        append_event(
            session,
            "youtube.verified",
            "youtube_connection",
            connection_id,
            8,
            {"channel_id": row.remote_channel_id, "channel_title": row.remote_channel_title},
            correlation_id,
        )
        session.flush()
        return connection_view(row)


def disconnect_connection(
    engine: Engine, vault: CredentialVault, connection_id: str, *, correlation_id: str
) -> dict:
    """Drop the refresh token and the channel identity, and tell Google to forget it too.

    The revocation is best effort: if Google cannot be reached the local token is still removed,
    because leaving a credential behind after the Owner asked to disconnect would be worse than
    leaving a stale grant in their Google account, which they can revoke there.
    """
    with Session(engine) as session, session.begin():
        row = session.get(YouTubeConnection, connection_id)
        if row is None:
            raise YouTubeConnectionError("Conexiunea nu există.")
        blob = vault.decrypt(row.encrypted_secrets)
        refresh_token = blob.pop("refresh_token", None)
        row.encrypted_secrets = vault.encrypt(blob)
        row.secret_fields = sorted(blob)
        row.status = STATUS_AUTH_REQUIRED
        row.remote_channel_id = None
        row.remote_channel_title = None
        row.channel_snapshot = {}
        row.granted_scopes = None
        row.connected_at = None
        row.last_checked_at = utc_now()
        row.last_error = None
        session.execute(
            delete(YouTubeOAuthState).where(YouTubeOAuthState.connection_id == connection_id)
        )

    revoked = False
    if refresh_token:
        try:
            _post_form(GOOGLE_REVOKE_URL, {"token": refresh_token}, timeout=10)
            revoked = True
        except YouTubeConnectionError:
            logger.info("youtube_revoke_unreachable", extra={"connection": connection_id})

    with Session(engine) as session, session.begin():
        row = session.get(YouTubeConnection, connection_id)
        if row is None:
            raise YouTubeConnectionError("Conexiunea nu există.")
        if refresh_token and not revoked:
            row.last_error = "Tokenul a fost șters local; Google nu a confirmat revocarea."
        append_event(
            session,
            "youtube.disconnected",
            "youtube_connection",
            connection_id,
            9,
            {"name": row.name, "revoked_at_google": revoked},
            correlation_id,
        )
        session.flush()
        return connection_view(row)


def provider_for_connection(engine: Engine, vault: CredentialVault, connection_id: str) -> Any:
    """Build a publishing provider bound to one authorised connection.

    The bridge to Phase 6: publishing already knows how to upload given a client id, secret and
    refresh token, and this is where a connection hands them over without any of the three ever
    passing through the interface.
    """
    from app.providers.youtube import YouTubeProvider

    with Session(engine) as session:
        row = session.get(YouTubeConnection, connection_id)
        if row is None:
            raise YouTubeConnectionError("Conexiunea nu există.")
        if row.status != STATUS_CONNECTED:
            raise YouTubeConnectionError(
                f"Conexiunea {row.name!r} nu este conectată. Apasă Conectează YouTube."
            )
        blob = vault.decrypt(row.encrypted_secrets)
        snapshot = row.channel_snapshot if isinstance(row.channel_snapshot, dict) else {}
        return YouTubeProvider(
            client_id=row.client_id,
            client_secret=blob.get("client_secret"),
            refresh_token=blob.get("refresh_token"),
            channel_id=row.remote_channel_id,
            # The uploads playlist reconciliation reads (PUB-03); asked for when absent.
            uploads_playlist_id=snapshot.get("uploads_playlist_id") or None,
        )
