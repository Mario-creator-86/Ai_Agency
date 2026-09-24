"""FastAPI REST routes and WebSocket gateway for Phase 2 automation."""

from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Path,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from app.security import (
    SOCKET_AUTH_TIMEOUT_S,
    owner_key_matches,
    require_owner,
    socket_first_message_auth,
)
from app.workflows.publisher import ConnectionManager, replay_events
from app.workflows.schemas import (
    CreateScheduledJobCommand,
    CreateWorkflowCommand,
    ScheduledJobView,
    SetJobActiveCommand,
    TaskQueueItemView,
    WorkflowDetailView,
    WorkflowView,
)
from app.workflows.services import (
    InvalidStateTransitionError,
    create_scheduled_job,
    create_workflow,
    get_workflow_detail,
    list_queue_tasks,
    list_scheduled_jobs,
    list_workflows,
    retry_dead_letter_task,
    scheduler_tick,
    set_job_active,
    transition_workflow,
)


def create_workflows_router() -> APIRouter:
    router = APIRouter(prefix="/workflows", dependencies=[Depends(require_owner)])

    @router.post("/", response_model=WorkflowDetailView)
    def post_workflow(request: Request, command: CreateWorkflowCommand) -> dict:
        return create_workflow(request.app.state.engine, command)

    @router.get("/", response_model=list[WorkflowView])
    def get_workflows(request: Request) -> list[dict]:
        return list_workflows(request.app.state.engine)

    @router.get("/{workflow_id}", response_model=WorkflowDetailView)
    def get_workflow(
        request: Request,
        workflow_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        wf = get_workflow_detail(request.app.state.engine, workflow_id)
        if wf is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return wf

    @router.post("/{workflow_id}/pause", response_model=WorkflowView)
    def pause_workflow(
        request: Request,
        workflow_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        try:
            return transition_workflow(request.app.state.engine, workflow_id, "PAUSED")
        except InvalidStateTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/{workflow_id}/resume", response_model=WorkflowView)
    def resume_workflow(
        request: Request,
        workflow_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        try:
            return transition_workflow(request.app.state.engine, workflow_id, "RUNNING")
        except InvalidStateTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/{workflow_id}/cancel", response_model=WorkflowView)
    def cancel_workflow(
        request: Request,
        workflow_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        try:
            return transition_workflow(request.app.state.engine, workflow_id, "CANCELLED")
        except InvalidStateTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router


def create_tasks_router() -> APIRouter:
    router = APIRouter(prefix="/tasks", dependencies=[Depends(require_owner)])

    @router.get("/queue", response_model=list[TaskQueueItemView])
    def get_queue(
        request: Request,
        status: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> list[dict]:
        return list_queue_tasks(request.app.state.engine, status_filter=status, limit=limit)

    @router.post("/{task_id}/retry", response_model=TaskQueueItemView)
    def retry_task(
        request: Request,
        task_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        try:
            return retry_dead_letter_task(request.app.state.engine, task_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router


def create_scheduler_router() -> APIRouter:
    router = APIRouter(prefix="/scheduler", dependencies=[Depends(require_owner)])

    @router.get("/jobs", response_model=list[ScheduledJobView])
    def get_jobs(request: Request) -> list[dict]:
        return list_scheduled_jobs(request.app.state.engine)

    @router.post("/jobs", response_model=ScheduledJobView)
    def post_job(request: Request, command: CreateScheduledJobCommand) -> dict:
        return create_scheduled_job(request.app.state.engine, command)

    @router.post("/jobs/{job_id}/active")
    def post_job_active(request: Request, job_id: UUID, command: SetJobActiveCommand) -> dict:
        """Start or stop a schedule's clock. Recorded as an autonomy decision."""
        try:
            return set_job_active(
                request.app.state.engine, str(job_id), command.active, str(command.command_id)
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    @router.post("/tick")
    def post_tick(request: Request) -> dict:
        triggered = scheduler_tick(request.app.state.engine)
        return {"triggered_count": len(triggered), "triggered": triggered}

    return router


def register_websocket_gateway(
    app: FastAPI,
    manager: ConnectionManager,
    *,
    auth_timeout_s: float = SOCKET_AUTH_TIMEOUT_S,
) -> None:
    """Register WebSocket endpoint at /api/v1/ws with authentication and replay support.

    The Owner's key is the socket's first message (``{"type": "auth", "token": ...}``, answered
    ``{"type": "auth_ok"}``); until it is right the socket hears nothing and is not in the
    broadcast. A page from before 2026-09-25 still says it in the query string.
    """

    @app.websocket("/api/v1/ws")
    async def websocket_endpoint(
        websocket: WebSocket,
        token: str | None = Query(default=None),
    ) -> None:
        settings = app.state.settings
        expected_token = settings.owner_token.get_secret_value()
        if token is not None:
            if not owner_key_matches(token, expected_token):
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
            await manager.connect(websocket)
        else:
            await websocket.accept()
            if not await socket_first_message_auth(
                websocket, expected_token, timeout_s=auth_timeout_s
            ):
                return
            await websocket.send_text(json.dumps({"type": "auth_ok"}))
            manager.add(websocket)
        engine = app.state.engine

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    data = json.loads(raw)
                except Exception:
                    await websocket.send_text(json.dumps({"error": "invalid_json"}))
                    continue

                msg_type = data.get("type")
                if msg_type == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
                elif msg_type == "replay":
                    after_seq = int(data.get("after_sequence", 0))
                    limit = min(int(data.get("limit", 100)), 500)
                    events = replay_events(engine, after_seq, limit)
                    for e in events:
                        await websocket.send_text(json.dumps({"type": "replay_event", "data": e}))
                    last_seq = events[-1]["sequence"] if events else after_seq
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "replay_complete",
                                "count": len(events),
                                "up_to_sequence": last_seq,
                            }
                        )
                    )
                else:
                    await websocket.send_text(
                        json.dumps({"error": f"unknown_message_type: {msg_type}"})
                    )
        except WebSocketDisconnect:
            manager.disconnect(websocket)
