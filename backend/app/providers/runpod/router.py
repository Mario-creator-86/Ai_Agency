"""The Owner's GPU switch: what the RunPod GPU is doing, and «Oprește GPU acum».

GET /api/v1/runpod/gpu?fresh=0|1 reads the state (the guard's last reading, or one live read
per endpoint at most every 10 s). POST /api/v1/runpod/gpu/off switches every RunPod GPU off
now, idempotent by ``command_id``; it is never refused by STOP AUTONOMIE or the mode: off spends
nothing (ADR-GPU-OFF-ALWAYS). Both behind the Owner's key.

His switch and checklist (2026-10-09, `setup`): PUT /api/v1/runpod/integrations/{id}/switch
moves «RunPod pornit» (ON needs a VERIFIED connection, OFF always works and switches the GPU off);
GET .../setup shows «Pașii configurării» from the last check without calling anything; POST
.../setup/check reads RunPod and the bucket now (GET / HEAD only, never a write).
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.providers.runpod import setup_steps
from app.providers.runpod.gpu_session import force_off, gpu_status
from app.security import require_owner

COMMAND_TYPE = "RunPodGpuOff"
OFF_VERIFIED_WORDS = "GPU-ul RunPod este oprit și verificat."
OFF_UNVERIFIED_WORDS = (
    "Am trimis oprirea GPU-ului RunPod, dar nu a confirmat încă; paznicul verifică din nou la "
    "fiecare minut."
)
NO_RUNPOD_WORDS = "Studioul nu are nicio conexiune RunPod de oprit."


class SwitchCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    on: bool


class GpuOffCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    command_id: UUID


def _off_words(readings: list[dict[str, Any]]) -> str:
    if not readings:
        return NO_RUNPOD_WORDS
    return OFF_VERIFIED_WORDS if all(r.get("off") for r in readings) else OFF_UNVERIFIED_WORDS


def create_runpod_router() -> APIRouter:
    router = APIRouter(prefix="/runpod", dependencies=[Depends(require_owner)])

    @router.get("/gpu")
    def get_gpu(request: Request, fresh: int = 0) -> dict[str, Any]:
        """The GPU switch's state (spec: configured, mock, rate, endpoints, sessions, last off)."""
        return gpu_status(
            request.app.state.engine, request.app.state.credential_vault, fresh=bool(fresh)
        )

    @router.post("/gpu/off")
    def post_gpu_off(request: Request, command: GpuOffCommand) -> Any:
        """«Oprește GPU acum»: purge, cancel, workers.max=0 and verify, on every endpoint."""
        from app.services import (  # noqa: PLC0415 - services imports providers
            CommandConflict,
            command_hash,
            recall_command,
            remember_command,
        )

        engine = request.app.state.engine
        payload = command.model_dump(mode="json")
        digest = command_hash(payload)
        identifier = str(command.command_id)
        try:
            with Session(engine) as session:
                previous = recall_command(session, identifier, digest)
        except CommandConflict as exc:
            return JSONResponse({"detail": str(exc)}, status_code=409)
        if previous is not None:
            return previous
        readings = [
            r.as_dict()
            for r in force_off(engine, request.app.state.credential_vault, reason="OWNER_OFF")
        ]
        answer = {
            "command_id": identifier,
            "readings": readings,
            "verified": bool(readings) and all(r["off"] for r in readings),
            "words_ro": _off_words(readings),
        }
        try:
            with Session(engine) as session, session.begin():
                remember_command(session, identifier, COMMAND_TYPE, digest, answer)
        except IntegrityError:
            # A double press raced this one: its answer is the answer.
            with Session(engine) as session:
                previous = recall_command(session, identifier, digest)
            if previous is not None:
                return previous
        return answer

    @router.get("/integrations/{identifier}/setup")
    def get_setup(identifier: UUID, request: Request) -> dict[str, Any]:
        """«Pașii configurării» from the last check: nothing is called."""
        try:
            return setup_steps.checklist(
                request.app.state.engine,
                request.app.state.credential_vault,
                str(identifier),
                fresh=False,
            )
        except setup_steps.SwitchRefused as exc:
            raise HTTPException(exc.status, exc.reason_ro) from None

    @router.post("/integrations/{identifier}/setup/check")
    def check_setup(identifier: UUID, request: Request) -> dict[str, Any]:
        """«Verifică pașii»: RunPod and the bucket read now (GET / HEAD only)."""
        try:
            return setup_steps.checklist(
                request.app.state.engine,
                request.app.state.credential_vault,
                str(identifier),
                fresh=True,
            )
        except setup_steps.SwitchRefused as exc:
            raise HTTPException(exc.status, exc.reason_ro) from None

    @router.put("/integrations/{identifier}/switch")
    def put_switch(identifier: UUID, command: SwitchCommand, request: Request) -> dict[str, Any]:
        """«RunPod pornit»: his act. ON needs a verified connection; OFF always works."""
        try:
            return setup_steps.set_switch(
                request.app.state.engine,
                request.app.state.credential_vault,
                str(identifier),
                on=command.on,
            )
        except setup_steps.SwitchRefused as exc:
            raise HTTPException(exc.status, exc.reason_ro) from None

    return router
