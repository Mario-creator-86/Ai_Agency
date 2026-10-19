"""Run real Marcus and Sarah LLMs on a disposable studio backup, not on production.

    uv run --locked python -X utf8 scripts/real_serial_audit.py --dry-run
    uv run --locked python -X utf8 scripts/real_serial_audit.py --allow-live-studio

Only LLM adapters are loaded. No media spending or publication can occur.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import traceback
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "backend", ROOT / "scripts"):
    sys.path.insert(0, str(path))

import writer_eval as ev  # noqa: E402
from app.agents.memory import agent_for_role  # noqa: E402
from app.agents.models import AgentRun, ModelRecord  # noqa: E402
from app.story.models import StoryEpisode  # noqa: E402
from app.story.review import episode_as_text, judged_review  # noqa: E402
from app.story.services import write_episode  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402


def director_model(engine, requested):
    with Session(engine) as session:
        agent = agent_for_role(session, "Director")
        if agent is None:
            raise ev.EvalError("Directorul nu exista in backup.")
        current = session.get(ModelRecord, agent.model_id)
        name = requested or (current.model_name if current else None)
    found = ev.resolve_model(engine, name) if name else None
    if found is None:
        raise ev.EvalError("Modelul Sarah nu exista; da --director-model.")
    return found


def pin_director(engine, model):
    with Session(engine) as session, session.begin():
        agent = agent_for_role(session, "Director")
        agent.model_id = model["id"]
        agent.provider_id = model["provider_id"]
        agent.secondary_model_id = None
        agent.tertiary_model_id = None
        agent.multi_llm_strategy = "SINGLE"
        agent.version += 1
        return agent.id


def snapshot(engine):
    with Session(engine) as session:
        return (
            set(session.scalars(select(StoryEpisode.id)).all()),
            set(session.scalars(select(AgentRun.id)).all()),
        )


def collect(engine, old_episodes, old_runs):
    episodes, runs = [], []
    with Session(engine) as session:
        for item in session.scalars(select(StoryEpisode).order_by(StoryEpisode.created_at)):
            if item.id in old_episodes:
                continue
            script, metrics = episode_as_text(item)
            episodes.append({
                "id": item.id, "title": item.title, "status": item.status,
                "rewrite_of": item.rewrite_of_id, "script": script,
                "metrics": metrics, "beats": item.beats_json,
                "writer_quality": (item.continuity_json or {}).get("writer_quality"),
                "write_checks": (item.continuity_json or {}).get("write_checks"),
                "review": item.review_json,
            })
        for item in session.scalars(select(AgentRun).order_by(AgentRun.started_at)):
            if item.id in old_runs:
                continue
            runs.append({
                "task": item.task_type, "model": item.model_name,
                "provider": item.provider_name, "status": item.status,
                "prompt_tokens": item.prompt_tokens,
                "completion_tokens": item.completion_tokens,
                "cost_vr": item.cost_vr,
                "error": (item.error_detail or "")[:250],
            })
    return episodes, runs


def render(data):
    lines = [
        "# Inside The Nexus - test real scenariu si review", "",
        "Case: " + data["case"], "Zi: " + str(data["business_date"]),
        "Marcus: " + str(data["writer_model"]),
        "Sarah: " + str(data.get("director_model")), "",
        "Stare: " + str(data.get("outcome", "INCOMPLETE")),
        "Copia bazei de date este izolata. Media si publicarea sunt dezactivate.", "",
    ]
    for index, episode in enumerate(data["episodes"], 1):
        lines += [
            "", "## Versiunea " + str(index) + ": " + episode["title"], "",
            "Status: " + episode["status"],
            "Rescriere dupa: " + str(episode["rewrite_of"] or "nu"), "",
            "### Scenariul", "", episode["script"], "",
            "### Autoverificarea Marcus (8 criterii)", "",
            json.dumps(episode["writer_quality"], indent=2, ensure_ascii=False), "",
            "### Controlul Sarah (verdict, 8 criterii, motive)", "",
            json.dumps(episode["review"], indent=2, ensure_ascii=False, default=str), "",
        ]
    lines += ["", "## Apeluri AI si consum", "",
              json.dumps(data["runs"], indent=2, ensure_ascii=False), ""]
    if data.get("error"):
        lines += ["", "## Eroare", "", data["error"], ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--case", default="serial-2026-10-15")
    parser.add_argument("--writer-model")
    parser.add_argument("--director-model")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-live-studio", action="store_true")
    args = parser.parse_args(argv)

    cases = {
        case["id"]: case for case in ev.load_cases(ev.CASE_FILE)
        if case["kind"] == "serial"
    }
    if args.case not in cases:
        parser.error("Cazuri: " + ", ".join(cases))
    case = cases[args.case]
    writer_name = args.writer_model or case.get("writer_model")
    if not writer_name or ev.forbidden_writer(writer_name):
        parser.error("Modelul Marcus este interzis sau lipseste. Da --writer-model.")
    active = ev.live_studio(ROOT / "data" / "studio.lock")
    if active and not args.dry_run and not args.allow_live_studio:
        print("Studioul ruleaza. Opreste-l sau da --allow-live-studio.")
        return 3
    if active:
        print("Avertisment: consumul LLM este impartit cu studioul activ.", flush=True)

    folder = ROOT / "data" / "serial_audits" / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + args.case
    )
    data = {
        "case": args.case, "business_date": case["business_date"],
        "backup": case["backup"], "writer_model": writer_name,
        "director_model": None, "outcome": "INCOMPLETE",
        "episodes": [], "runs": [],
    }
    exit_code = 1
    with tempfile.TemporaryDirectory(prefix="amn-real-serial-") as work:
        engine = None
        before = None
        try:
            print("Copiez backup-ul intr-o baza de test separata...", flush=True)
            source = ev.backup_file(ev.DEFAULT_BACKUPS, case["backup"])
            copy = ev.copy_database(source, Path(work) / "case")
            engine = ev.open_copy(copy)
            data["preflight"] = ev.prepare_copy(engine, case)
            writer = ev.resolve_model(engine, writer_name)
            sarah = director_model(engine, args.director_model)
            data["director_model"] = sarah["model_name"]
            if writer is None:
                raise ev.EvalError("Modelul Marcus lipseste din copia de test.")
            if args.dry_run:
                print("Preflight OK: " + writer_name + " / " + sarah["model_name"])
                data["outcome"] = "READY - 0 apeluri AI"
                exit_code = 0
            else:
                registry, info = ev.llm_registry(
                    engine, ROOT / "data" / "studio.credentials.key",
                    {writer["provider_id"], sarah["provider_id"]},
                )
                if info["missing"]:
                    raise ev.EvalError("Conexiuni lipsa: " + ", ".join(info["missing"]))
                director_id = pin_director(engine, sarah)
                for who, employee, model in [
                    ("Marcus", ev.writer_of(engine, "serial"), writer),
                    ("Sarah", director_id, sarah),
                ]:
                    refused = ev.kernel_refusal(engine, registry, employee, model["id"])
                    if refused:
                        raise ev.EvalError(who + " blocat de politica: " + refused)
                before = snapshot(engine)
                with ev.writer_patches(writer["id"]):
                    print("Marcus scrie scenariul cu modelul REAL...", flush=True)
                    first = write_episode(engine, registry, case["log_id"], str(uuid4()))
                    print("Sarah evalueaza scenariul si face judecata editoriala...", flush=True)
                    result = judged_review(
                        engine, registry, first["episode"]["id"], str(uuid4()), rounds=2
                    )
                    if result["verdict"] == "FAIL":
                        print("Sarah a respins; Marcus rescrie o singura data...", flush=True)
                        revised = write_episode(
                            engine, registry, case["log_id"], str(uuid4()),
                            notes=result.get("notes") or "Corecteaza criticile Sarah.",
                            rewrite_of=first["episode"]["id"],
                        )
                        result = judged_review(
                            engine, registry, revised["episode"]["id"],
                            str(uuid4()), rounds=1
                        )
                data["last_review"] = result
                data["outcome"] = str(result["verdict"]) + " / " + str(result["status"])
                exit_code = 0
        except Exception as exc:
            data["error"] = type(exc).__name__ + ": " + str(exc)
            data["traceback"] = traceback.format_exc(limit=8)
            data["outcome"] = "ERROR"
            print("Eroare: " + data["error"], flush=True)
        finally:
            if engine is not None:
                if before is not None:
                    try:
                        data["episodes"], data["runs"] = collect(engine, *before)
                    except Exception as exc:
                        data["collect_error"] = str(exc)
                engine.dispose()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "report.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    (folder / "scenario_and_review.md").write_text(render(data), encoding="utf-8")
    print("\nRezultat:", data["outcome"])
    print("Scenariu si evaluare:", folder / "scenario_and_review.md")
    print("Detalii complete:", folder / "report.json")
    print("Nicio imagine, voce, secventa video sau publicare.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
