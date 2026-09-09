"""Phase 2 tests: workflows, task queue with leases, scheduler, outbox, and cloud model discovery.

Covers:
- Alembic migration 0003 schema match (zero drift)
- Workflow creation and initial step
- Workflow state machine transitions (legal vs illegal)
- Task queue atomic claim, lease expiration recovery, heartbeat, completion
- Retryable failure with exponential backoff & dead-letter queue routing
- Operator dead-letter recovery
- Autonomy stop gate blocking tasks & scheduler
- Singleton-safe scheduler leader leasing
- Transactional outbox atomicity & publisher dispatch
- Dynamic cloud model discovery (glm-5.2:cloud, kimi-k2.6:cloud, qwen3-coder:480b-cloud)
- WebSocket gateway authentication and replay protocol
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.agents.models import ProviderRecord
from app.agents.services import sync_provider_models
from app.db import create_db_engine, migrate
from app.main import create_app
from app.models import Base, DomainEvent, OwnerPolicy
from app.providers.base import GenerateResult, HealthResult, LLMProvider, ModelInfo
from app.providers.registry import ProviderRegistry
from app.services import bootstrap_studio, utc_now
from app.workflows.models import (
    OutboxRecord,
    ScheduledJob,
    TaskQueueItem,
    Workflow,
)
from app.workflows.publisher import ConnectionManager, publish_pending_outbox
from app.workflows.schemas import (
    CreateScheduledJobCommand,
    CreateWorkflowCommand,
)
from app.workflows.services import (
    InvalidStateTransitionError,
    append_event_with_outbox,
    claim_task,
    complete_task,
    create_scheduled_job,
    create_workflow,
    enqueue_task,
    fail_task,
    heartbeat_task,
    retry_dead_letter_task,
    scheduler_tick,
    transition_workflow,
)
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def phase2_engine(settings):
    """Engine with Phase 0 + 1 + 2 migrations applied."""
    engine = create_db_engine(settings.database_url)
    migrate(engine)
    bootstrap_studio(engine, settings)
    yield engine
    engine.dispose()


def clear_autonomy_stop(engine):
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.autonomy_stopped = False
        policy.version += 1


# ---------------------------------------------------------------------------
# 1. Migration & Schema Match
# ---------------------------------------------------------------------------


def test_phase2_migration_creates_all_tables(phase2_engine):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    with phase2_engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == [], f"Schema drift detected: {diff}"


# ---------------------------------------------------------------------------
# 2. Workflow Creation & Step Initialization
# ---------------------------------------------------------------------------


def test_create_workflow_and_initial_step(phase2_engine):
    engine = phase2_engine
    cmd = CreateWorkflowCommand(
        command_id=uuid4(),
        workflow_type="SHORT_VIDEO",
        title="Episode 1: The New Room",
        config={"topic": "Quantum Computing", "target_seconds": 58},
    )
    result = create_workflow(engine, cmd)
    assert result["workflow_type"] == "SHORT_VIDEO"
    assert result["status"] == "CREATED"
    assert result["current_stage"] == "DISCOVERY"
    assert len(result["steps"]) == 1
    assert result["steps"][0]["stage"] == "DISCOVERY"
    assert result["steps"][0]["status"] == "PENDING"

    # Verify event and outbox record were created atomically
    with Session(engine) as session:
        wf = session.get(Workflow, result["id"])
        assert wf is not None
        event = session.scalars(
            select(DomainEvent).where(DomainEvent.event_id == wf.event_id)
        ).first()
        assert event is not None
        assert event.event_type == "workflow.created"
        outbox = session.scalars(
            select(OutboxRecord).where(OutboxRecord.event_id == event.event_id)
        ).first()
        assert outbox is not None
        assert outbox.status == "PENDING"


# ---------------------------------------------------------------------------
# 3. Workflow State Machine Transitions
# ---------------------------------------------------------------------------


def test_workflow_legal_and_illegal_transitions(phase2_engine):
    engine = phase2_engine
    cmd = CreateWorkflowCommand(
        command_id=uuid4(),
        workflow_type="SHORT_VIDEO",
        title="Pipeline Test",
        config={},
    )
    wf = create_workflow(engine, cmd)
    wf_id = wf["id"]

    # Illegal transition: CREATED -> COMPLETED
    with pytest.raises(InvalidStateTransitionError):
        transition_workflow(engine, wf_id, "COMPLETED")

    # Legal: CREATED -> PREFLIGHT -> ADMITTED -> RUNNING -> PAUSED -> RUNNING -> COMPLETED
    s1 = transition_workflow(engine, wf_id, "PREFLIGHT")
    assert s1["status"] == "PREFLIGHT"

    s2 = transition_workflow(engine, wf_id, "ADMITTED")
    assert s2["status"] == "ADMITTED"

    s3 = transition_workflow(engine, wf_id, "RUNNING")
    assert s3["status"] == "RUNNING"

    s4 = transition_workflow(engine, wf_id, "PAUSED")
    assert s4["status"] == "PAUSED"

    s5 = transition_workflow(engine, wf_id, "RUNNING")
    assert s5["status"] == "RUNNING"

    s6 = transition_workflow(engine, wf_id, "COMPLETED")
    assert s6["status"] == "COMPLETED"

    # Terminal: COMPLETED cannot transition
    with pytest.raises(InvalidStateTransitionError):
        transition_workflow(engine, wf_id, "RUNNING")


# ---------------------------------------------------------------------------
# 4. Task Queue: Claim, Leases, Expiration Recovery, Heartbeat, Completion
# ---------------------------------------------------------------------------


def test_task_queue_lease_and_expiration_recovery(phase2_engine):
    engine = phase2_engine
    clear_autonomy_stop(engine)

    # Enqueue task
    task = enqueue_task(
        engine,
        task_type="agent_execution",
        payload={"agent_role": "ScriptWriter", "stage": "SCRIPTING"},
        priority=10,
    )
    assert task["status"] == "QUEUED"
    assert task["attempts"] == 0

    # Worker 1 claims task with short 1-second lease
    claimed = claim_task(engine, worker_id="worker_1", lease_duration_seconds=1)
    assert claimed is not None
    assert claimed["id"] == task["id"]
    assert claimed["status"] == "CLAIMED"
    assert claimed["lease_token"] == "worker_1"
    assert claimed["attempts"] == 1

    # Worker 2 tries to claim while lease is active -> None available
    assert claim_task(engine, worker_id="worker_2") is None

    # Simulate worker 1 dying and lease expiring: set lease_expires_at to past
    with Session(engine) as session, session.begin():
        t = session.get(TaskQueueItem, task["id"])
        t.lease_expires_at = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()

    # Worker 2 now successfully steals / recovers the task!
    recovered = claim_task(engine, worker_id="worker_2", lease_duration_seconds=30)
    assert recovered is not None
    assert recovered["id"] == task["id"]
    assert recovered["lease_token"] == "worker_2"
    assert recovered["attempts"] == 2

    # Worker 2 heartbeats task
    assert heartbeat_task(engine, task["id"], lease_token="worker_2", extension_seconds=60) is True
    assert heartbeat_task(engine, task["id"], lease_token="wrong_token") is False

    # Worker 2 completes task
    completed = complete_task(engine, task["id"], lease_token="worker_2")
    assert completed["status"] == "COMPLETED"
    assert completed["lease_token"] is None


# ---------------------------------------------------------------------------
# 5. Retry, Backoff, and Dead-Letter Queue
# ---------------------------------------------------------------------------


def test_task_fail_backoff_and_dead_letter(phase2_engine):
    engine = phase2_engine
    clear_autonomy_stop(engine)

    task = enqueue_task(
        engine,
        task_type="video_render",
        payload={"scene_id": 1},
        max_attempts=2,
        backoff_seconds=2,
    )

    # Attempt 1: claim & fail (retryable)
    c1 = claim_task(engine, "worker_1")
    assert c1["attempts"] == 1
    f1 = fail_task(engine, task["id"], "worker_1", error_detail="Out of GPU memory", retryable=True)
    assert f1["status"] == "RETRYING"
    assert f1["error_detail"] == "Out of GPU memory"

    # Fast-forward next_attempt_at to make it eligible immediately
    with Session(engine) as session, session.begin():
        t = session.get(TaskQueueItem, task["id"])
        t.next_attempt_at = utc_now()

    # Attempt 2: claim & fail (reaches max_attempts=2 -> DEAD_LETTER)
    c2 = claim_task(engine, "worker_1")
    assert c2["attempts"] == 2
    f2 = fail_task(
        engine, task["id"], "worker_1", error_detail="Out of GPU memory again", retryable=True
    )
    assert f2["status"] == "DEAD_LETTER"

    # Operator recovers dead-letter task
    recovered = retry_dead_letter_task(engine, task["id"])
    assert recovered["status"] == "QUEUED"
    assert recovered["attempts"] == 0
    assert recovered["error_detail"] is None


# ---------------------------------------------------------------------------
# 6. Autonomy Stop Gate on Tasks & Scheduler
# ---------------------------------------------------------------------------


def test_autonomy_stop_blocks_task_claim_and_scheduler(phase2_engine):
    engine = phase2_engine
    # By default, bootstrap leaves autonomy_stopped=True

    enqueue_task(engine, "automated_job", {})
    assert claim_task(engine, "worker_1") is None  # Blocked!

    # Create due scheduled job
    now_past = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    cmd = CreateScheduledJobCommand(
        command_id=uuid4(),
        name="daily_pulse",
        workflow_type="SHORT_VIDEO",
        interval_seconds=60,
    )
    job = create_scheduled_job(engine, cmd)
    with Session(engine) as session, session.begin():
        j = session.get(ScheduledJob, job["id"])
        j.next_run_at = now_past

    # Scheduler tick while autonomy stopped triggers nothing!
    triggered = scheduler_tick(engine)
    assert triggered == []

    # Clear stop -> now scheduler triggers and task can be claimed
    clear_autonomy_stop(engine)
    triggered_after = scheduler_tick(engine)
    assert len(triggered_after) == 1
    assert triggered_after[0]["name"] == "daily_pulse"

    claimed = claim_task(engine, "worker_1")
    assert claimed is not None


# ---------------------------------------------------------------------------
# 7. Singleton-Safe Scheduler Duplicate Prevention
# ---------------------------------------------------------------------------


def test_scheduler_duplicate_prevention_via_leader_lease(phase2_engine):
    engine = phase2_engine
    clear_autonomy_stop(engine)

    cmd = CreateScheduledJobCommand(
        command_id=uuid4(),
        name="hourly_sync",
        workflow_type="SHORT_VIDEO",
        interval_seconds=3600,
    )
    job = create_scheduled_job(engine, cmd)
    with Session(engine) as session, session.begin():
        j = session.get(ScheduledJob, job["id"])
        j.next_run_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        # Simulate active leader lease by scheduler_A
        j.leader_token = "scheduler_A"
        j.leader_expires_at = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()

    # scheduler_B runs tick -> skips because scheduler_A holds the lease
    triggered = scheduler_tick(engine, leader_id="scheduler_B")
    assert triggered == []


# ---------------------------------------------------------------------------
# 8. Transactional Outbox Atomicity & Publisher Dispatch
# ---------------------------------------------------------------------------


def test_transactional_outbox_atomicity_and_dispatch(phase2_engine):
    engine = phase2_engine

    # 1. Rollback test
    with Session(engine) as session:
        try:
            with session.begin():
                append_event_with_outbox(
                    session, "test.rolled_back", "test", "1", 1, {}, str(uuid4())
                )
                raise RuntimeError("Force rollback")
        except RuntimeError:
            pass

    with Session(engine) as session:
        assert session.scalars(select(OutboxRecord)).all() == []

    # 2. Commit test
    with Session(engine) as session, session.begin():
        append_event_with_outbox(
            session, "test.committed", "test", "2", 1, {"k": "v"}, str(uuid4())
        )

    with Session(engine) as session:
        pending = session.scalars(
            select(OutboxRecord).where(OutboxRecord.status == "PENDING")
        ).all()
        assert len(pending) == 1

    # 3. Publisher dispatch test
    manager = ConnectionManager()
    count = publish_pending_outbox(engine, manager)
    assert count == 1

    with Session(engine) as session:
        record = session.scalars(select(OutboxRecord)).first()
        assert record.status == "PUBLISHED"
        assert record.published_at is not None


# ---------------------------------------------------------------------------
# 9. Cloud Model Discovery in Ollama (glm-5.2:cloud, kimi-k2.6:cloud, etc.)
# ---------------------------------------------------------------------------


class MockCloudOllamaProvider(LLMProvider):
    """Mock Ollama provider that returns both local and cloud-backed models."""

    async def health_check(self) -> HealthResult:
        return HealthResult(status="HEALTHY")

    async def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo("llama3.2:latest", None, True, "parameter_size=3B", is_cloud=False),
            ModelInfo("glm-5.2:cloud", None, True, "cloud_model=true", is_cloud=True),
            ModelInfo("kimi-k2.6:cloud", None, True, "cloud_model=true", is_cloud=True),
            ModelInfo("qwen3-coder:480b-cloud", None, True, "cloud_model=true", is_cloud=True),
        ]

    async def generate(self, model: str, prompt: str, **kwargs) -> GenerateResult:
        return GenerateResult(
            text=f"Response from {model}", prompt_tokens=10, completion_tokens=5, cost_vr=None
        )


def test_ollama_cloud_models_discovery(phase2_engine):
    engine = phase2_engine
    provider_id = str(uuid4())
    root_event_id = None

    with Session(engine) as session, session.begin():
        root_event = session.scalars(select(DomainEvent).limit(1)).first()
        root_event_id = root_event.event_id
        provider = ProviderRecord(
            id=provider_id,
            name="ollama-cloud-endpoint",
            provider_type="OLLAMA",
            base_url="http://127.0.0.1:11434",
            status="HEALTHY",
            last_health_check=None,
            adapter_version="1.0.0",
            notes="supports :cloud models",
            created_at=utc_now(),
            event_id=root_event_id,
        )
        session.add(provider)

    registry = ProviderRegistry()
    registry.register(provider_id, MockCloudOllamaProvider())

    # Sync models from provider
    synced = sync_provider_models(engine, registry, provider_id)
    assert len(synced) == 4
    model_names = {m["model_name"] for m in synced}
    assert "glm-5.2:cloud" in model_names
    assert "kimi-k2.6:cloud" in model_names
    assert "qwen3-coder:480b-cloud" in model_names
    assert "llama3.2:latest" in model_names

    # Verify domain event emitted for discovered models
    with Session(engine) as session:
        events = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "provider.model_discovered")
        ).all()
        assert len(events) == 4
        discovered_payloads = [e.payload["model_name"] for e in events]
        assert "glm-5.2:cloud" in discovered_payloads


# ---------------------------------------------------------------------------
# 10. WebSocket Gateway & Replay Protocol
# ---------------------------------------------------------------------------


def test_websocket_auth_and_replay(settings, phase2_engine):
    app = create_app(settings)
    token = settings.owner_token.get_secret_value()

    # Unauthorized connection -> rejected with WS 1008
    from starlette.websockets import WebSocketDisconnect

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/api/v1/ws?token=invalid_token"):
                pass

        # Authorized connection
        with client.websocket_connect(f"/api/v1/ws?token={token}") as ws:
            # Ping -> pong
            ws.send_json({"type": "ping"})
            resp = ws.receive_json()
            assert resp["type"] == "pong"

            # Replay from sequence 0 (replays bootstrap events)
            ws.send_json({"type": "replay", "after_sequence": 0, "limit": 10})
            event_1 = ws.receive_json()
            assert event_1["type"] == "replay_event"
            assert event_1["data"]["sequence"] == 1

            event_2 = ws.receive_json()
            assert event_2["type"] == "replay_event"
            assert event_2["data"]["sequence"] == 2

            complete = ws.receive_json()
            assert complete["type"] == "replay_complete"
            assert complete["count"] >= 2
