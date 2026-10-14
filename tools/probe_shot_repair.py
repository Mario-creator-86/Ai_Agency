"""Explicit isolated real-agent test; scene edits stay in a copy, model runs/costs are real."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> int:
    from app.agents import services, structured
    from app.agents.memory import agent_for_role
    from app.agents.models import AgentRun, ModelRecord
    from app.agents.recovery import recover_interrupted_sheet_runs
    from app.db import create_db_engine
    from app.integrations.services import load_registry
    from app.integrations.vault import CredentialVault
    from app.main import create_app  # noqa: F401 -- register all ORM tables, no server start
    from app.media import blocker_repair, prompt_agent, scene_rewrite
    from app.media.models import StoryboardScene
    from app.media.shooting_sheet import build_sheet
    from app.providers.registry import ProviderRegistry
    from app.runbook.services import clear_shutdown
    from app.workflows.worker import acquire_worker_lock, worker_lock_path
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", required=True)
    parser.add_argument("--scene", type=int, required=True)
    parser.add_argument("--max-agent-calls", type=int, default=6)
    parser.add_argument(
        "--editor-model", help="Optional verified model override for this test only"
    )
    parser.add_argument("--studio-confirmed-stopped", action="store_true", required=True)
    args = parser.parse_args()
    correlation = str(uuid4())
    output = ROOT / "output" / "agency-watch" / ("probe-" + correlation)
    output.mkdir(parents=True)
    production = create_db_engine("sqlite:///data/studio.db")
    path = worker_lock_path(production)
    worker_lock = acquire_worker_lock(path) if path else None
    if path and worker_lock is None:
        raise RuntimeError("The studio worker is running; stop it before an isolated probe")
    # The operator has verified the previous studio process is gone. No age-only reset.
    recovered = recover_interrupted_sheet_runs(production, started_at=datetime.now(UTC))
    copy_path = output / "test.db"
    with sqlite3.connect((ROOT / "data/studio.db").as_uri() + "?mode=ro", uri=True) as source:
        with sqlite3.connect(copy_path) as target:
            source.backup(target)
    copy = create_db_engine("sqlite:///" + copy_path.as_posix())
    editor_override = None
    editor_id = None
    if args.editor_model:
        with Session(copy) as session, session.begin():
            editor = agent_for_role(session, prompt_agent.PROMPT_ROLE)
            model = session.scalar(
                select(ModelRecord).where(
                    ModelRecord.model_name == args.editor_model,
                    ModelRecord.is_available.is_(True),
                )
            )
            if editor is None or model is None:
                raise ValueError("The test requires an active editor and a verified model")
            editor_override, editor_id = model.id, editor.id
            editor.model_id, editor.provider_id = model.id, model.provider_id
    clear_shutdown(copy)  # only the isolated test copy, never the stopped production studio
    registry = ProviderRegistry()
    load_registry(production, CredentialVault(ROOT / "data/studio.credentials.key"), registry)
    calls = []
    actual_run = services.run_agent_task

    def probe_run(_engine, *positional, **keywords):
        if len(calls) >= args.max_agent_calls:
            raise RuntimeError("Isolated test call allowance exhausted")
        keywords["summary"] = "Test izolat Codex: " + str(keywords.get("summary") or positional[1])
        if editor_override and positional[1] == editor_id:
            keywords["model_id"] = editor_override
        result = actual_run(production, *positional, **keywords)
        calls.append(
            {
                key: result.get(key)
                for key in (
                    "id",
                    "task_type",
                    "status",
                    "model_name",
                    "completion_tokens",
                    "prompt_tokens",
                    "cost_vr",
                    "error_detail",
                )
            }
        )
        print(json.dumps({"phase": "agent_returned", **calls[-1]}, ensure_ascii=False), flush=True)
        return result

    services.run_agent_task = probe_run
    structured.run_agent_task = probe_run
    normal_batches = prompt_agent.shot_payload_batches

    def selected_scene_batches(data, lessons, limit, **kwargs):
        batches = normal_batches(data, lessons, limit, **kwargs)
        selected = []
        key = "episode" if "episode" in data else "film"
        for batch in batches:
            scenes = [
                scene for scene in batch[key]["scenes"] if int(scene["scene_index"]) == args.scene
            ]
            if scenes:
                selected.append({**batch, key: {**batch[key], "scenes": scenes}})
        return selected

    prompt_agent.shot_payload_batches = selected_scene_batches
    report = {
        "correlation_id": correlation,
        "storyboard_id": args.board,
        "scene": args.scene,
        "production_scene_edits": False,
        "gpu_requests": 0,
        "recovered": recovered,
    }

    def scene():
        with Session(copy) as session:
            row = session.scalar(
                select(StoryboardScene).where(
                    StoryboardScene.storyboard_id == args.board,
                    StoryboardScene.scene_index == args.scene,
                )
            )
            if row is None:
                raise ValueError("The selected scene does not exist")
            return {"visual_prompt": row.visual_prompt, "package": row.prompt_json}

    try:
        report["before"] = scene()
        reading = build_sheet(copy, args.board, read_live=False)
        issues = blocker_repair.sheet_issues(reading)
        report["issues_before"] = issues
        report["assignment"] = blocker_repair.director_assignment(
            copy, registry, reading, issues, correlation
        )
        context = scene_rewrite.scene_context(copy, args.board, args.scene)
        report["brief"] = scene_rewrite.director_brief(copy, registry, context, correlation)
        report["writer"] = prompt_agent.write_shot_prompts(
            copy,
            registry,
            args.board,
            correlation,
            repair_context={
                "issues": issues,
                "director_assignment": report["assignment"],
                "director_brief": report["brief"],
            },
        )
        report["after"] = scene()
        report["changed"] = report["before"] != report["after"]
        report["issues_after"] = blocker_repair.sheet_issues(
            build_sheet(copy, args.board, read_live=False)
        )
        if report["changed"] and report["brief"].get("brief"):
            package = report["after"]["package"]
            brief = report["brief"]["brief"]
            report["review"] = scene_rewrite.review_rewrite(
                copy,
                registry,
                context,
                brief,
                str(brief.get("layer") or "motion"),
                package,
                report["after"]["visual_prompt"],
                correlation,
            )
        report["status"] = "CHANGED" if report["changed"] else "NO_USABLE_CHANGE"
    except Exception as error:  # preserve diagnostics, never credentials/hidden traces
        report["status"] = "TEST_FAILED"
        report["error_class"] = type(error).__name__
    finally:
        report["calls"] = calls
        with Session(production) as session:
            report["actual_call_limits"] = [
                {
                    "run_id": row.id,
                    "template": row.prompt_template_version,
                    "limits": row.context_json.get("generation_limits"),
                }
                for row in session.scalars(
                    select(AgentRun).where(AgentRun.correlation_id == correlation)
                )
            ]
        (output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "changed": report.get("changed"),
                    "report": str(output / "report.json"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        copy.dispose()
        production.dispose()
        if worker_lock:
            worker_lock.release()
    return 0 if report["status"] != "TEST_FAILED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
