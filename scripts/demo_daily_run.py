"""Run two full days in an isolated studio and print what each stage actually did.

Why a separate database: a daily run writes topics, claims, scripts, renders and a closed log.
Putting demonstration work into the Owner's real studio would leave invented production in an
append-only history that no later reader could tell apart from the real thing.

What is real here and what is not. The runbook, the stage wiring, the agent policy kernel, the
factual gate, the renderer and quality control are the production code paths, unchanged. The
language model is a local stand-in that answers in the schemas the pipeline requires, because
this script must run without a provider account — and it is given nothing: the verification stage
refuses any verdict whose quoted evidence is not in the source verbatim, and the script stage
rejects any scene citing a claim id that was not supplied, so the stand-in has to read the prompt
and answer correctly to get anywhere.

Two runs, because the first one stops where it should. A script is left for the Owner to approve;
the approval happens between the runs, and the second run carries the work forward. That is what
shows the stages are joined rather than merely present.

    uv run python scripts/demo_daily_run.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from tempfile import mkdtemp
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# The Windows console defaults to cp1252, which cannot encode Romanian diacritics.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SOURCE_TEXT = (
    "Domeniul example.com este rezervat pentru documentatie de catre IANA. "
    "Nu poate fi inregistrat de nimeni."
)
QUOTE = "Domeniul example.com este rezervat pentru documentatie de catre IANA."


class ScriptedModel:
    """Answers in the schemas the pipeline demands, reading what it needs out of the prompt."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def health_check(self):
        from app.providers.base import HealthResult

        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        from app.providers.base import GenerateResult

        self.prompts.append(prompt)
        lowered = prompt.lower()
        if "evidence_quote" in prompt or "verdict" in lowered:
            body = (
                '{"status": "SUPPORTED", "confidence": 0.92, "evidence_quote": '
                f'"{QUOTE}", "notes": "Sursa afirma exact acest lucru."}}'
            )
        elif "episodul de azi" in lowered:
            # The roster and the event ids both come out of the prompt: a beat citing an id that
            # is not in the day's events has the whole episode rejected, and a character not in
            # the roster is refused too.
            events = re.findall(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", prompt
            )
            # The roster sits in its own section; parsing the whole prompt would pick up an
            # event description that happens to start with a dash.
            block = prompt.split("DISTRIBU", 1)[-1].split("EVENIMENTELE", 1)[0]
            # A display name can contain brackets of its own ("Sarah (Director)"), so the
            # match is greedy: everything before the LAST bracket on the line.
            roster = re.findall(r"^- (.+) \(", block, flags=re.MULTILINE)
            body = json.dumps(
                {
                    "title": "O zi obisnuita la AMN-AI",
                    "beats": [
                        {
                            "scene": "Biroul de cercetare, dimineata.",
                            "dialogue": "Sursa a fost citita si afirmatia verificata.",
                            "event_ids": events[:1],
                            "characters": roster[:1],
                        }
                    ],
                }
            )
        elif "scenariu de voiceover" in lowered:
            # The prompt lists the verified claims and their identifiers, and a scene citing an
            # id that is not in that list is rejected outright. Reading them back out of the
            # prompt is what a model has to do, so the stand-in does it too.
            ids = re.findall(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", prompt
            )
            body = json.dumps(
                {
                    "title": "Domeniul rezervat pentru documentatie",
                    "scenes": [
                        {
                            "narration": QUOTE,
                            "visual": "Un domeniu web rezervat",
                            "claim_ids": ids[:1],
                        }
                    ],
                }
            )
        else:
            body = json.dumps(
                [
                    {
                        "claim_text": QUOTE,
                        "claim_type": "SCIENTIFIC_FACT",
                        "importance": "CRITICAL",
                        "confidence": 0.9,
                    }
                ]
            )
        return GenerateResult(body, 10, 40, None)


def main() -> int:
    from app.agents.models import Agent, ModelRecord
    from app.agents.services import seed_initial_workforce
    from app.config import Settings
    from app.db import create_db_engine, migrate
    from app.factual.models import ScriptDraft
    from app.factual.services import (
        approve_script_draft,
        ingest_source_snapshot,
        propose_topic_idea,
    )
    from app.integrations.vault import CredentialVault
    from app.media.models import MediaAsset, QualityControlReport
    from app.models import OwnerPolicy
    from app.providers.registry import ProviderRegistry
    from app.runbook.services import execute_daily_run
    from app.runbook.stages import build_stage_runners
    from app.services import bootstrap_studio
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    workspace = Path(mkdtemp(prefix="amn-day-"))
    url = f"sqlite:///{(workspace / 'day.db').as_posix()}"
    settings = Settings(owner_token="d" * 48, database_url=url)  # pragma: allowlist secret

    engine = create_db_engine(url)
    migrate(engine)
    bootstrap_studio(engine, settings)
    seed_initial_workforce(engine)

    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for record in session.scalars(select(ModelRecord)):
            record.is_available = True
    with Session(engine) as session:
        provider_id = session.scalar(select(Agent)).provider_id

    # A topic the Owner proposed and one source about it. Everything after this is the studio's.
    topic = propose_topic_idea(
        engine,
        title="Domenii rezervate pentru documentatie",
        topic="Infrastructura internetului",
        angle="De ce example.com nu apartine nimanui",
        target_audience="curiosi",
        correlation_id=str(uuid4()),
    )
    ingest_source_snapshot(
        engine,
        url="https://www.iana.org/help/example-domains",
        title="IANA Example Domains",
        publisher="www.iana.org",
        author=None,
        raw_content=SOURCE_TEXT,
        credibility_score=0.95,
        correlation_id=str(uuid4()),
        # Attached to the topic: a claim extracted from an unattached source belongs to no topic,
        # and no topic can then be selected from it.
        topic_id=topic["id"],
    )

    registry = ProviderRegistry()
    registry.register(provider_id, ScriptedModel())
    vault = CredentialVault(Path(url.replace("sqlite:///", "")).with_suffix(".credentials.key"))
    runners = build_stage_runners(engine, settings, vault, registry)

    def show(label: str, result: dict) -> None:
        print("")
        print(f"=== {label} ===")
        print(
            f"Stare: {result['status']}   etape complete: "
            f"{result['stages_completed']}/{result['stages_total']}"
        )
        if result.get("stopped_at_stage"):
            print(f"Oprit la: {result['stopped_at_stage']} - {result.get('stop_reason')}")
        for stage in result["stages"]:
            print(f"  {stage['stage']:<26} {stage['status']:<10} {stage['reason'][:220]}")

    print(f"Studio izolat in {workspace}")
    show("Prima rulare", execute_daily_run(engine, settings, vault, stage_runners=runners))

    # The studio stops at the draft on purpose: approving a script is the Owner's decision, and
    # storyboarding requires an APPROVED one.
    with Session(engine) as session:
        pending = session.scalar(select(ScriptDraft).where(ScriptDraft.status == "VERIFIED_PASS"))
        script_id = pending.id if pending else None
    if script_id:
        approve_script_draft(engine, script_id, str(uuid4()))
        print("")
        print(f"[Owner] Scenariul {script_id[:8]} a fost aprobat.")

    show("A doua rulare", execute_daily_run(engine, settings, vault, stage_runners=runners))

    with Session(engine) as session:
        assets = list(session.scalars(select(MediaAsset)))
        reports = list(session.scalars(select(QualityControlReport)))
    print("")
    print("Produse pe disc:")
    for asset in assets:
        path = Path(asset.uri_or_path)
        size = path.stat().st_size if path.is_file() else 0
        print(f"  {asset.asset_type:<16} {size:>9} octeti  furnizor: {asset.provider_name}")
    for report in reports:
        print(f"  QC {report.status:<8} scor {report.score}  motive: {report.failure_reasons_json}")

    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
