"""A failed model run says which HTTP status the provider gave and what it means.

Measured on the Owner's studio on 2026-10-02: every run of the daily catch-up (Researcher,
Director, Showrunner, the claim checks, the clip looks; five models on one Ollama Cloud
connection) failed, and each run recorded only "ProviderHTTPError". Nobody could tell a revoked
key (401) from an exhausted plan (402/429), a retired model (404) or an outage (5xx), so nobody
knew what to fix. The status is a number and carries no secret; the vendor's body still never
reaches the record.

The model is faked at the provider boundary; no socket is opened.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.agents.models import Agent, AgentRun
from app.agents.services import run_agent_task
from app.integrations.llm import ProviderHTTPError
from sqlalchemy.orm import Session
from test_agent_budget import a_running_studio


class Refusing:
    """An employee's model whose provider answers with one HTTP status."""

    def __init__(self, status: int) -> None:
        self.status = status

    async def health_check(self):  # pragma: no cover - not asked here
        raise AssertionError

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        raise ProviderHTTPError(self.status)


@pytest.mark.parametrize(
    ("status", "meaning"),
    [
        (401, "cheia"),
        (403, "cheia"),
        (402, "abonamentul"),
        (429, "limita"),
        (404, "modelul"),
        (503, "furnizorul"),
    ],
)
def test_a_failed_run_records_the_http_status_and_what_it_means(
    engine, monkeypatch, status, meaning
):
    agent_id, registry, _ = a_running_studio(engine, monkeypatch)
    with Session(engine) as session:
        provider_id = session.get(Agent, agent_id).provider_id
    registry.register(provider_id, Refusing(status))

    run = run_agent_task(engine, registry, agent_id, "t", "spune ceva", "v1", str(uuid4()))

    assert run["status"] == "FAILED"
    with Session(engine) as session:
        stored = session.get(AgentRun, run["id"])
        detail = stored.error_detail
    assert detail.startswith(f"ProviderHTTPError: HTTP {status}"), detail
    assert meaning in detail.lower(), detail


def test_an_error_without_a_status_keeps_only_its_class_name(engine, monkeypatch):
    agent_id, registry, _ = a_running_studio(engine, monkeypatch)

    class Broken(Refusing):
        async def generate(self, model, prompt, **kwargs):
            raise RuntimeError("https://vendor.example/v1?key=SECRET leaked")

    with Session(engine) as session:
        provider_id = session.get(Agent, agent_id).provider_id
    registry.register(provider_id, Broken(0))

    run = run_agent_task(engine, registry, agent_id, "t", "spune ceva", "v1", str(uuid4()))

    with Session(engine) as session:
        detail = session.get(AgentRun, run["id"]).error_detail
    assert detail == "RuntimeError"
