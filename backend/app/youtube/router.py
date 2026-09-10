"""Routes for the YouTube connection flow.

Two kinds of route, with deliberately different protection:

  ``/api/v1/youtube/...``       Owner-only. Everything the Owner initiates.
  ``/auth/youtube/callback``    Public, because Google redirects a browser here and a browser
                                redirect cannot carry the Owner credential. Its protection is the
                                single-use ``state`` issued when the flow started, checked before
                                any code is exchanged.

No route returns a client secret or a refresh token. The only shape a connection is rendered in
is ``connection_view``, which has no branch that could include either.
"""

from __future__ import annotations

import html
from collections.abc import Callable
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from app.security import require_owner
from app.youtube.services import (
    YouTubeConnectionError,
    begin_authorization,
    complete_authorization,
    create_connection,
    delete_connection,
    disconnect_connection,
    get_connection,
    list_connections,
    update_connection,
    verify_connection,
)

UUID36 = Annotated[str, Path(min_length=36, max_length=36)]


class CreateConnection(BaseModel):
    """The four things the Owner types. Nothing about the channel itself is among them."""

    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    name: str = Field(min_length=1, max_length=100)
    client_id: str = Field(min_length=1, max_length=255)
    client_secret: str = Field(min_length=1, max_length=255)
    redirect_uri: str = Field(min_length=1, max_length=500)


class UpdateConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    name: str | None = Field(default=None, max_length=100)
    client_id: str | None = Field(default=None, max_length=255)
    #: Omitted means "leave the stored secret alone"; the interface never receives it back, so it
    #: cannot round-trip one and must be able to submit an edit without it.
    client_secret: str | None = Field(default=None, max_length=255)
    redirect_uri: str | None = Field(default=None, max_length=500)


def _page(title: str, lines: list[str], *, status_code: int = 200) -> HTMLResponse:
    """A plain confirmation page for the browser Google redirected.

    Deliberately unstyled: the Content-Security-Policy allows stylesheets only from this origin
    and no inline styles, and a transient page is not worth an asset. It says what happened and
    tells the Owner where to go back to.
    """
    body = "\n".join(f"<p>{html.escape(line)}</p>" for line in lines)
    return HTMLResponse(
        status_code=status_code,
        content=(
            "<!doctype html><html lang=\"ro\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{html.escape(title)} · AMN-AI</title></head><body>"
            f"<h1>{html.escape(title)}</h1>{body}"
            "<p>Poți închide această filă și te poți întoarce în studio.</p>"
            "</body></html>"
        ),
    )


def create_youtube_router() -> APIRouter:
    """Owner-only management of YouTube connections."""
    router = APIRouter(prefix="/youtube", dependencies=[Depends(require_owner)])

    def _guard(call: Callable[[], dict]) -> dict:
        try:
            return call()
        except YouTubeConnectionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @router.get("/connections")
    def get_connections(request: Request) -> dict:
        """Every connection, with its channel when one has been authorised."""
        return {"connections": list_connections(request.app.state.engine)}

    @router.post("/connections")
    def post_connection(request: Request, cmd: CreateConnection) -> dict:
        """Save the credentials. Authorises nothing and contacts nobody."""
        return _guard(
            lambda: create_connection(
                request.app.state.engine,
                request.app.state.credential_vault,
                name=cmd.name,
                client_id=cmd.client_id,
                client_secret=cmd.client_secret,
                redirect_uri=cmd.redirect_uri,
                correlation_id=str(cmd.command_id),
            )
        )

    @router.get("/connections/{connection_id}")
    def get_one(request: Request, connection_id: UUID36) -> dict:
        found = get_connection(request.app.state.engine, connection_id)
        if found is None:
            raise HTTPException(status_code=404, detail="Conexiunea nu există.")
        return found

    @router.patch("/connections/{connection_id}")
    def patch_connection(request: Request, connection_id: UUID36, cmd: UpdateConnection) -> dict:
        return _guard(
            lambda: update_connection(
                request.app.state.engine,
                request.app.state.credential_vault,
                connection_id,
                name=cmd.name,
                client_id=cmd.client_id,
                client_secret=cmd.client_secret,
                redirect_uri=cmd.redirect_uri,
                correlation_id=str(cmd.command_id),
            )
        )

    @router.delete("/connections/{connection_id}")
    def delete_one(request: Request, connection_id: UUID36) -> dict:
        return _guard(
            lambda: delete_connection(
                request.app.state.engine, connection_id, correlation_id=str(uuid4())
            )
        )

    @router.post("/connections/{connection_id}/authorize")
    def post_authorize(request: Request, connection_id: UUID36) -> dict:
        """Return the Google consent URL for this connection. The Owner's browser opens it."""
        return _guard(
            lambda: begin_authorization(
                request.app.state.engine, connection_id, correlation_id=str(uuid4())
            )
        )

    @router.post("/connections/{connection_id}/reconnect")
    def post_reconnect(request: Request, connection_id: UUID36) -> dict:
        """Same flow, but always asking Google for consent so a refresh token is reissued."""
        return _guard(
            lambda: begin_authorization(
                request.app.state.engine,
                connection_id,
                force_consent=True,
                correlation_id=str(uuid4()),
            )
        )

    @router.post("/connections/{connection_id}/verify")
    def post_verify(request: Request, connection_id: UUID36) -> dict:
        """Re-read the channel with the stored token, so the status reflects today."""
        return _guard(
            lambda: verify_connection(
                request.app.state.engine,
                request.app.state.credential_vault,
                connection_id,
                correlation_id=str(uuid4()),
            )
        )

    @router.post("/connections/{connection_id}/disconnect")
    def post_disconnect(request: Request, connection_id: UUID36) -> dict:
        """Forget the token here and revoke it at Google. The credentials stay for a reconnect."""
        return _guard(
            lambda: disconnect_connection(
                request.app.state.engine,
                request.app.state.credential_vault,
                connection_id,
                correlation_id=str(uuid4()),
            )
        )

    return router


def create_youtube_callback_router() -> APIRouter:
    """The public redirect target. Mounted outside /api/v1 and without the Owner dependency."""
    router = APIRouter()

    @router.get("/auth/youtube/callback", response_class=HTMLResponse)
    def youtube_callback(
        request: Request,
        code: Annotated[str | None, Query(max_length=2048)] = None,
        state: Annotated[str | None, Query(max_length=128)] = None,
        error: Annotated[str | None, Query(max_length=200)] = None,
    ) -> HTMLResponse:
        # Google sends `error=access_denied` when consent is refused. That is an outcome, not a
        # fault, and the page says so rather than showing a stack of jargon.
        if error:
            return _page(
                "Autorizare anulată",
                [f"Google a răspuns: {error}.", "Nu s-a salvat niciun token."],
                status_code=400,
            )
        if not code or not state:
            return _page(
                "Cerere incompletă",
                ["Linkul de întoarcere nu conține codul și starea așteptate."],
                status_code=400,
            )
        try:
            connection = complete_authorization(
                request.app.state.engine,
                request.app.state.credential_vault,
                code=code,
                state=state,
                correlation_id=str(uuid4()),
            )
        except YouTubeConnectionError as exc:
            return _page("Conectare eșuată", [str(exc)], status_code=400)

        channel = connection.get("channel") or {}
        return _page(
            "Canal conectat",
            [
                f"Conexiunea {connection['name']} este acum CONNECTED.",
                f"Canal: {channel.get('title') or 'necunoscut'} ({channel.get('id') or '—'}).",
                "Tokenul a fost salvat criptat pe server. Nu apare niciodată în interfață.",
            ],
        )

    return router
