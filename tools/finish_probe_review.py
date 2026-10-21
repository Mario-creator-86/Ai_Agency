"""Review the corrected test candidate and let Sarah choose between actually tested models."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Literal
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    from app.agents import services, structured
    from app.agents.memory import agent_for_role
    from app.agents.structured import structured_run
    from app.db import create_db_engine
    from app.integrations.services import assign_agent, load_registry
    from app.integrations.vault import CredentialVault
    from app.main import create_app  # noqa: F401 -- ORM registration only
    from app.media import prompt_agent, scene_rewrite
    from app.providers.registry import ProviderRegistry
    from app.services import may_act
    from app.workflows.worker import acquire_worker_lock, worker_lock_path
    from pydantic import BaseModel
    from sqlalchemy.orm import Session

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--failed-probe", type=Path, required=True)
    parser.add_argument("--select-tested-editor", action="store_true")
    args = parser.parse_args()
    data = json.loads(args.probe.read_text(encoding="utf-8"))
    failed = json.loads(args.failed_probe.read_text(encoding="utf-8"))
    assert data["production_scene_edits"] is False and data["changed"] is True
    actual = create_db_engine("sqlite:///data/studio.db")
    path = worker_lock_path(actual)
    lock = acquire_worker_lock(path) if path else None
    if path and lock is None:
        raise RuntimeError("Stop the studio worker before this isolated review")
    copy = create_db_engine("sqlite:///" + (args.probe.parent / "test.db").resolve().as_posix())
    registry = ProviderRegistry()
    load_registry(actual, CredentialVault(ROOT / "data/studio.credentials.key"), registry)
    correlation = str(uuid4())
    normal_run = services.run_agent_task
    calls = []

    def call(_engine, *positional, **kwargs):
        kwargs["summary"] = "Test izolat Codex: " + str(kwargs.get("summary") or positional[2])
        result = normal_run(actual, *positional, **kwargs)
        calls.append(
            {
                k: result.get(k)
                for k in (
                    "id",
                    "task_type",
                    "status",
                    "model_name",
                    "cost_vr",
                    "prompt_tokens",
                    "completion_tokens",
                    "error_detail",
                )
            }
        )
        print(json.dumps(calls[-1], ensure_ascii=False), flush=True)
        return result

    services.run_agent_task = structured.run_agent_task = call
    result = {"correlation_id": correlation, "production_scene_edits": False, "gpu_requests": 0}
    try:
        context = scene_rewrite.scene_context(copy, data["storyboard_id"], data["scene"])
        context["package"] = data["before"]["package"]
        context["visual_prompt"] = data["before"]["visual_prompt"]
        package = data["after"]["package"]
        compiled = prompt_agent.compile_prompts(package, data["writer"]["bible"])
        package = {**package, **compiled}
        assert "or ghost image appears" not in compiled["motion_prompt"].lower()
        assert "stay locked in identical position and shape throughout" in compiled["motion_prompt"]
        result["compiled"] = compiled
        result["review"] = scene_rewrite.review_rewrite(
            copy,
            registry,
            context,
            data["brief"]["brief"],
            data["brief"]["brief"]["layer"],
            package,
            compiled["still_prompt"],
            correlation,
            earlier=data["review"],
        )
        if args.select_tested_editor:

            class Choice(BaseModel):
                choice: Literal["current", "alternative"]
                reason: str

            with Session(actual) as session:
                director = agent_for_role(session, "Director")
                editor = agent_for_role(session, prompt_agent.PROMPT_ROLE)
                gate = may_act(session, "agent.change_model", "T2", requester=director.id)
                if not gate["allowed"]:
                    raise PermissionError("The Owner policy refuses this model change")
            evidence = {
                "current": {
                    "outcome": failed["status"],
                    "scene_changed": failed.get("changed"),
                    "runs": [
                        {k: r.get(k) for k in ("status", "completion_tokens")}
                        for r in failed["calls"]
                        if r["task_type"] == "shot_prompts"
                    ],
                },
                "alternative": {
                    "outcome": data["status"],
                    "scene_changed": data["changed"],
                    "review_after_compiler_fix": result["review"],
                    "runs": [
                        {k: r.get(k) for k in ("status", "completion_tokens")}
                        for r in data["calls"]
                        if r["task_type"] == "shot_prompts"
                    ],
                },
            }
            choice, first, second = structured_run(
                actual,
                registry,
                director.id,
                "director_editor_model_choice",
                "Choose which tested slot the video editor should use next. Both are already "
                "verified and role-compatible. Judge actual usable scene output, not HTTP success. "
                "Do not change budget, STOP or approvals. Return JSON with choice (current or "
                "alternative) and reason. Evidence:\n" + json.dumps(evidence, ensure_ascii=False),
                "editor-model-choice-v1",
                correlation,
                Choice,
                "",
                max_tokens=800,
                summary="Aleg modelul editorului după proba reală de lucru.",
            )
            result["choice"] = choice.model_dump() if choice else None
            result["choice_run_id"] = (second or first).get("id")
            if choice and choice.choice == "alternative":
                from app.agents.models import Agent, AgentRun

                tested_run = next(
                    r["id"] for r in data["calls"] if r["task_type"] == "shot_prompts"
                )
                with Session(actual) as session:
                    fresh = session.get(Agent, editor.id)
                    run = session.get(AgentRun, tested_run)
                    selected_id = run.context_json.get("actual_model_id")
                    # The recorded slot is authoritative; never choose by a hardcoded model name.
                    if not selected_id:
                        from app.agents.models import ModelRecord, ProviderRecord
                        from sqlalchemy import select

                        selected_id = session.scalar(
                            select(ModelRecord.id)
                            .join(ProviderRecord)
                            .where(
                                ModelRecord.model_name == run.model_name,
                                ProviderRecord.name == run.provider_name,
                            )
                        )
                    if not selected_id:
                        raise ValueError("Cannot resolve the tested model on the editor's provider")
                    params = dict(
                        secondary_model_id=fresh.secondary_model_id,
                        tertiary_model_id=fresh.tertiary_model_id,
                        multi_llm_strategy=fresh.multi_llm_strategy,
                        additional_llm_policy=fresh.additional_llm_policy,
                        min_importance=fresh.min_importance,
                        min_confidence=fresh.min_confidence,
                    )
                    version = fresh.version
                result["assignment"] = assign_agent(
                    actual,
                    editor.id,
                    selected_id,
                    version,
                    assignment_origin="DIRECTOR_REPAIR",
                    **params,
                )
    finally:
        result["calls"] = calls
        target = args.probe.parent / "final-review.json"
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "review": result.get("review", {}).get("verdict"),
                    "choice": result.get("choice"),
                    "assignment_saved": "assignment" in result,
                    "report": str(target),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        actual.dispose()
        copy.dispose()
        if lock:
            lock.release()


if __name__ == "__main__":
    main()
