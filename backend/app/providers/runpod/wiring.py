from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.integrations.models import Integration, ProviderResource
from app.integrations.vault import CredentialVault
from app.models import OwnerPolicy
from app.providers.runpod.adapters import RunPodConnection, RunPodImageAdapter, RunPodVideoAdapter
from app.providers.runpod.config import RunPodConfig
from app.providers.runpod.jobs import GenerationJob


def connection(
    engine: Engine,
    vault: CredentialVault,
    row: Integration,
    model: str | None = None,
    purpose: str | None = None,
) -> Any:
    # The API key and the bucket's keys (S3-compatible) all come from the vault.
    config = RunPodConfig.from_integration(dict(row.config), vault.decrypt(row.encrypted_secrets))
    if not config.configured:
        return None
    if config.mock:
        with Session(engine) as s:
            policy = s.get(OwnerPolicy, 1)
            if policy is not None and policy.environment == "PRODUCTION":
                return None
    cls = (
        RunPodImageAdapter
        if purpose == "image"
        else RunPodVideoAdapter
        if purpose == "video"
        else RunPodConnection
    )
    adapter = cls(config, engine, model=model, integration_id=row.id)
    if model:
        with Session(engine) as session:
            resource = session.scalar(
                select(ProviderResource).where(
                    ProviderResource.integration_id == row.id,
                    ProviderResource.resource_type == "MODEL",
                    ProviderResource.remote_id == model,
                )
            )
            if resource is not None:
                adapter.model_metadata = dict(resource.api_metadata)
    return adapter


def bind_scene(adapter: Any, project_id: str, scene_id: int | str, operation: str) -> None:
    if isinstance(adapter, RunPodConnection):
        adapter.bind_scene(project_id=project_id, scene_id=str(scene_id), operation=operation)


def billing_name(adapter: Any) -> str:
    return "runpod" if isinstance(adapter, RunPodConnection) else "runway"


def sync_take_quality(
    session: Session, take: Any, *, accepted: bool | None = None, reason: str | None = None
) -> None:
    """Use the existing QA verdict inside its transaction, without another QA or writer."""
    if not take.remote_task_id:
        return
    if accepted is None:
        if take.status not in ("APPROVED", "REJECTED"):
            return
        accepted = take.status == "APPROVED"
    row = session.scalar(
        select(GenerationJob).where(
            GenerationJob.remote_job_id == take.remote_task_id,
            GenerationJob.project_id == take.storyboard_id,
            GenerationJob.scene_id == str(take.scene_number),
        )
    )
    if row is not None and row.status == "COMPLETED":
        row.accepted = accepted
        row.quality_result = (
            reason or take.failure_detail or ("PASSED" if accepted else "REJECTED")
        )[:4000]
