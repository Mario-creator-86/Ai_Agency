"""Employees choose their technology by reading about it — the studio fetches, they judge.

The Owner asked that the video editor and the voice artist decide which model to use, the
way a person would: read what the vendor says a model does and costs, look at what the
studio's own catalogue exposes, and pick — then say why. Nothing in the studio had a way
for an employee to read a page. Now the steward of a purpose (Kael for video and image,
Lyra for voice) does it in two runs:

1. Given the vendor's documentation index, name up to three pages worth reading — pricing,
   the model overview. The studio fetches them itself, over the same pinned-HTTPS retriever
   that fetches sources, restricted to the vendor's own hosts (the ones the Owner already
   connected an account to). No employee has a tool that reaches anywhere else.
2. Given those pages and the account's own model list, score every candidate 0..1 on
   quality, reliability and speed, record its price with the unit, and recommend one, with
   the page it read as evidence.

The scores and prices go where the production hierarchy already reads them —
`provider_resource.capabilities` / `.pricing`, with the source URL — so `strategy: auto`
and the defaults are ranked by evidence from then on. The default itself is changed only
where the Owner left it as a fallback (`allow_production_override`); a locked default is
reported on, never touched. Everything is said in a letter to the Director.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.identity import parse_structured
from app.agents.memory import agent_for_role
from app.agents.messages import post_message
from app.agents.services import run_agent_task
from app.config import Settings
from app.economy.accountant import price_change_alert
from app.factual.sanitizer import wrap_in_inert_boundary
from app.integrations.autoconfig import DEFAULTS
from app.integrations.catalog import CATALOG
from app.integrations.discovery import (
    DISCOVERED_KINDS,
    ProductionCommand,
    ResourceMetadataCommand,
    production_resource,
    save_production,
    update_resource_metadata,
)
from app.integrations.models import (
    Integration,
    MediaProductionConfig,
    ProviderResource,
    ServiceSelection,
)
from app.media.production_policy import rank_candidates
from app.providers.registry import ProviderRegistry
from app.research.retrieval import RetrievalError, RetrievalPolicy, SourceRetriever
from app.services import append_event

logger = logging.getLogger("studio.model_research")

RESEARCH_TASK = "research_models"
TEMPLATE_VERSION = "model-research-v1"
#: Who judges the technology of each purpose (the roles the Owner made stewards of it).
STEWARDS = {"video": "VideoEditor", "image": "VideoEditor", "voice": "VoiceArtist"}
PURPOSES = ("voice", "image", "video")
MAX_PAGES = 5
PAGE_CHARS = 12_000
INDEX_CHARS = 20_000


class ModelResearchError(ValueError):
    """The research could not run for this purpose; nothing was recorded."""


class UrlPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")
    urls: list[str] = Field(default_factory=list, max_length=6)


class ModelNote(BaseModel):
    model_config = ConfigDict(extra="ignore")
    remote_id: str = Field(min_length=1, max_length=200)
    quality_score: float = Field(default=0.5, ge=0, le=1)
    reliability_score: float = Field(default=0.5, ge=0, le=1)
    latency_score: float = Field(default=0.5, ge=0, le=1)
    price_usd: float | None = Field(default=None, ge=0)
    price_unit: str = Field(default="", max_length=60)
    notes: str = Field(default="", max_length=600)
    evidence_url: str = Field(default="", max_length=1000)


class Recommendation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    remote_id: str = Field(min_length=1, max_length=200)
    reason: str = Field(default="", max_length=1500)


class ModelResearch(BaseModel):
    model_config = ConfigDict(extra="ignore")
    models: list[ModelNote] = Field(default_factory=list, max_length=80)
    recommendation: Recommendation | None = None


_PLAN_INSTRUCTIONS = (
    "You are choosing the {purpose} technology for the studio. Below is the index of the "
    "vendor's documentation. Name up to {max_pages} pages on the vendor's own site "
    "({hosts}) that would tell you what each model does, its limits, and what it costs — "
    "the pricing page first, then per-model pages. Without a page that states prices no "
    "comparison is possible, and a studio that cannot compare overpays. The studio will "
    "fetch them; you cannot browse. "
    'Return only JSON: {{"urls": ["https://..."]}}.\n'
)


_JUDGE_INSTRUCTIONS = (
    "You are choosing the {purpose} technology for the studio, from the models the studio's "
    "own account exposes (listed below with what the API says about each). Read the vendor "
    "pages that follow and judge every listed model you can say something about: quality "
    "(0..1), reliability (0..1), speed (1 = fastest), the price as a number with its unit "
    "(per second of video, per image, per 1k characters), and a one-line note. Cite the "
    "page you read as evidence_url.\n"
    "Price every candidate you can. A model left unpriced cannot be compared, and a studio "
    "that cannot compare pays three times over for the same picture — which is what "
    "happened here: the model in use was recorded at 0.025 USD a second and actually costs "
    "0.43, while models of the same quality cost a third of that. Where a page prices a "
    "resolution or a tier, say which in the note.\n"
    "Then recommend one model for the studio's short vertical videos. {priority_line}\n"
    "In the reason, compare it with the cheapest candidate you scored within 0.1 of it, "
    "name both prices per second, and say plainly whether the dearer one is worth the "
    "multiple. A recommendation without that comparison is not usable.\n"
    "Judge only from the pages and the API data; a model the pages do not describe keeps "
    '0.5 and an empty price. Return only JSON: {{"models": [{{"remote_id": "...", '
    '"quality_score": 0.0, "reliability_score": 0.0, "latency_score": 0.0, '
    '"price_usd": null, "price_unit": "", "notes": "...", '
    '"evidence_url": "https://..."}}], "recommendation": {{"remote_id": "...", '
    '"reason": "..."}}}}.\n'
)


#: What the studio is, in the steward's own terms, so the recommendation serves it. A premium
#: studio wants the best picture its account can make; the price is a fact to record and to
#: compare with, not a reason to settle for less. `STUDIO_PRODUCTION_PRIORITY` sets this.
_PRIORITY_LINES = {
    "premium": (
        "This studio is premium: recommend the best picture the account can make, in the "
        "studio's own frame of 1080x1920. Among models whose quality you score within 0.1 "
        "of each other, recommend the cheaper one — paying a multiple for the same picture "
        "is not premium."
    ),
    "balanced": (
        "Weigh quality, reliability, speed and price about equally, in the studio's frame of "
        "1080x1920."
    ),
    "thrifty": (
        "Prefer the cheapest model that still delivers the studio's frame of 1080x1920 at "
        "acceptable quality."
    ),
}


def _priority_line(settings: Settings) -> str:
    return _PRIORITY_LINES.get(
        getattr(settings, "production_priority", "premium"), _PRIORITY_LINES["premium"]
    )


def vendor_hosts(kind: str) -> tuple[str, ...]:
    """The vendor's own hosts: the documentation host and its parent domains."""
    docs = str(CATALOG.get(kind, {}).get("docs") or "")
    host = (urlsplit(docs).hostname or "").lower()
    if not host:
        return ()
    labels = host.split(".")
    hosts = [host]
    for cut in range(1, len(labels) - 1):
        hosts.append(".".join(labels[cut:]))
    return tuple(dict.fromkeys(hosts))


def _price_key(purpose: str, unit: str) -> str:
    text = unit.lower()
    if "char" in text:
        return "per_1k_characters_usd"
    if "image" in text or purpose == "image":
        return "per_image_usd"
    if "second" in text or "sec" in text or purpose == "video":
        return "per_second_usd"
    return "price_usd"


def _fetch(retriever: SourceRetriever, url: str, chars: int) -> tuple[str, str] | None:
    try:
        page = retriever.fetch(url)
    except (RetrievalError, OSError) as exc:
        logger.info("model_research_page_unread", extra={"error": type(exc).__name__})
        return None
    return page.url, page.text[:chars]


def research_models(
    engine: Engine,
    registry: ProviderRegistry,
    settings: Settings,
    purpose: str,
    correlation_id: str | None = None,
    retriever: SourceRetriever | None = None,
) -> dict[str, Any]:
    """The steward reads the vendor's pages, scores the account's models, recommends one."""
    if purpose not in STEWARDS:
        raise ModelResearchError(f"Nu există un responsabil pentru scopul {purpose!r}")
    correlation = correlation_id or str(uuid4())
    with Session(engine) as session:
        selection = session.get(ServiceSelection, purpose)
        integration = (
            session.get(Integration, selection.integration_id)
            if selection and selection.integration_id
            else None
        )
        if integration is None or integration.kind not in DISCOVERED_KINDS:
            raise ModelResearchError(
                f"Niciun serviciu cu catalog ales pentru {purpose}; nimic de cercetat."
            )
        steward = agent_for_role(session, STEWARDS[purpose])
        if steward is None:
            raise ModelResearchError(f"Niciun {STEWARDS[purpose]} activ care să aleagă.")
        steward_id, steward_name = steward.id, steward.display_name
        kind, integration_id, vendor_name = integration.kind, integration.id, integration.name
        candidates = rank_candidates(
            session,
            integration_id,
            "MODEL",
            {"priority": getattr(settings, "production_priority", "premium")},
            purpose,
        )
        if not candidates:
            raise ModelResearchError(
                f"Contul {vendor_name} nu expune niciun model utilizabil pentru {purpose}."
            )
        rows = {
            r.remote_id: r
            for r in session.scalars(
                select(ProviderResource).where(
                    ProviderResource.integration_id == integration_id,
                    ProviderResource.resource_type == "MODEL",
                )
            )
        }
        listing = [
            {
                "remote_id": c["remote_id"],
                "name": c["name"],
                "api": {
                    k: v
                    for k, v in (rows[c["remote_id"]].api_metadata or {}).items()
                    if k in ("tasks", "limits", "description", "max_duration", "resolutions")
                }
                if c["remote_id"] in rows
                else {},
            }
            for c in candidates
        ]
        config = session.get(MediaProductionConfig, integration_id)
        allow = bool(config.allow_production_override) if config else True
        config_version = config.version if config else 0
        current = {
            "model_id": config.model_id if config else None,
            "voice_id": config.voice_id if config else None,
            "image_model_id": config.image_model_id if config else None,
        }

    hosts = vendor_hosts(kind)
    docs_url = str(CATALOG[kind]["docs"])
    if not hosts:
        raise ModelResearchError(f"Furnizorul {kind} nu are documentație în catalog.")
    reader = retriever or SourceRetriever(RetrievalPolicy(hosts, max_text_chars=40_000))
    index = _fetch(reader, docs_url, INDEX_CHARS)
    if index is None:
        _report(
            engine,
            steward_id,
            f"Cercetare de modele ({purpose}): documentația {vendor_name} nu a putut fi citită",
            f"Am încercat să citesc {docs_url} și nu a răspuns. Aleg pe mai departe după "
            f"catalogul contului, fără prețuri. — {steward_name}",
            correlation,
        )
        return {"status": "SKIPPED", "purpose": purpose, "reason": "documentația nu a răspuns"}

    # 1. Which pages to read.
    plan_prompt = _PLAN_INSTRUCTIONS.format(
        purpose=purpose, max_pages=MAX_PAGES, hosts=", ".join(hosts)
    ) + wrap_in_inert_boundary(index[1], "vendor-docs-index")
    plan = run_agent_task(
        engine,
        registry,
        steward_id,
        RESEARCH_TASK,
        plan_prompt,
        TEMPLATE_VERSION,
        correlation,
        summary=f"Caut în documentația {vendor_name} paginile despre modelele de {purpose}.",
        max_tokens=1500,
        temperature=0.1,
        emit_message=False,
    )
    wanted: list[str] = []
    parsed_plan = parse_structured(plan.get("output_text") or "", UrlPlan)
    if isinstance(parsed_plan, UrlPlan):
        for url in parsed_plan.urls:
            host = (urlsplit(url).hostname or "").lower()
            if url.startswith("https://") and host in hosts and url not in wanted:
                wanted.append(url)
    pages: list[tuple[str, str]] = [index]
    for url in wanted[:MAX_PAGES]:
        if url == index[0]:
            continue
        page = _fetch(reader, url, PAGE_CHARS)
        if page is not None:
            pages.append(page)

    # 2. The judgement.
    evidence = "\n\n".join(
        wrap_in_inert_boundary(f"PAGE {url}\n{text}", f"vendor-page-{i}")
        for i, (url, text) in enumerate(pages)
    )
    judge_prompt = (
        _JUDGE_INSTRUCTIONS.format(purpose=purpose, priority_line=_priority_line(settings))
        + "MODELS ON THE STUDIO'S ACCOUNT:\n"
        + wrap_in_inert_boundary(json.dumps(listing, ensure_ascii=False)[:12_000], "account-models")
        + "\nVENDOR PAGES:\n"
        + evidence
    )
    verdict = run_agent_task(
        engine,
        registry,
        steward_id,
        RESEARCH_TASK,
        judge_prompt,
        TEMPLATE_VERSION,
        correlation,
        summary=(
            f"Judec {len(candidates)} modele de {purpose} de la {vendor_name} după "
            f"{len(pages)} pagini citite."
        ),
        max_tokens=6000,
        temperature=0.1,
        emit_message=False,
    )
    text = verdict.get("output_text") or ""
    research = parse_structured(text, ModelResearch)
    if not isinstance(research, ModelResearch):
        raise ModelResearchError(
            f"{steward_name} nu a produs o judecată utilizabilă "
            f"({verdict['status']}: {verdict.get('error_detail') or 'schema nerespectată'})"
        )

    # 3. Record what was judged, where the hierarchy already reads it.
    known = {c["remote_id"] for c in candidates}
    annotated = 0
    with Session(engine) as session:
        versions = {
            r.remote_id: (r.id, r.metadata_version)
            for r in session.scalars(
                select(ProviderResource).where(
                    ProviderResource.integration_id == integration_id,
                    ProviderResource.resource_type == "MODEL",
                )
            )
        }
    moved: list[dict[str, Any]] = []
    for note in research.models:
        if note.remote_id not in known or note.remote_id not in versions:
            continue
        resource_id, version = versions[note.remote_id]
        source = note.evidence_url if note.evidence_url.startswith("https://") else docs_url
        pricing: dict[str, Any] = {}
        if note.price_usd is not None:
            pricing = {
                _price_key(purpose, note.price_unit): note.price_usd,
                "unit": note.price_unit or purpose,
            }
        try:
            written = update_resource_metadata(
                engine,
                resource_id,
                ResourceMetadataCommand(
                    expected_version=version,
                    pricing=pricing,
                    capabilities={
                        "quality_score": note.quality_score,
                        "reliability_score": note.reliability_score,
                        "latency_score": note.latency_score,
                        "notes": note.notes,
                        "judged_by": steward_name,
                    },
                    source=source,
                ),
            )
            annotated += 1
            # A price the steward read that moved past the Owner's threshold is a letter,
            # the same letter the Accountant writes when a render measures a new price.
            for move in written.get("price_moves") or []:
                percent = move.get("percent")
                if isinstance(percent, int | float) and abs(float(percent)) >= float(
                    settings.price_change_alert_percent
                ):
                    moved.append({**move, "model_id": note.remote_id})
        except ValueError as exc:
            logger.info("model_research_note_refused", extra={"reason": str(exc)[:120]})
    if moved:
        price_change_alert(engine, moved, correlation)

    # 4. The choice, where the Owner left it to the studio.
    field, _ = DEFAULTS[purpose]
    with Session(engine) as session:
        ranked = rank_candidates(
            session,
            integration_id,
            "MODEL",
            {"priority": getattr(settings, "production_priority", "premium")},
            purpose,
        )
        recommended = (
            research.recommendation.remote_id
            if research.recommendation and research.recommendation.remote_id in known
            else (ranked[0]["remote_id"] if ranked else None)
        )
        usable = (
            recommended is not None
            and production_resource(session, integration_id, "MODEL", recommended, purpose)
            is not None
        )
    changed = False
    if usable and allow and recommended != current[field]:
        wanted_defaults = {**current, field: recommended}
        try:
            save_production(
                engine,
                integration_id,
                ProductionCommand(
                    model_id=wanted_defaults["model_id"],
                    voice_id=wanted_defaults["voice_id"],
                    image_model_id=wanted_defaults["image_model_id"],
                    allow_production_override=True,
                    expected_version=config_version,
                ),
            )
            changed = True
        except ValueError as exc:
            logger.info("model_research_default_kept", extra={"reason": str(exc)[:120]})

    reason = research.recommendation.reason if research.recommendation else ""
    top = [
        f"{r['remote_id']} (scor {r['score']:.2f}"
        + (f", {r['per_1k_characters_usd']} USD" if r.get("per_1k_characters_usd") else "")
        + ")"
        for r in ranked[:3]
    ]
    letter = (
        f"Am citit {len(pages)} pagini din documentația {vendor_name} și am judecat "
        f"{annotated} din {len(candidates)} modele de {purpose}. "
        + (f"Recomand {recommended}: {reason} " if recommended else "Nu recomand un model. ")
        + (
            f"L-am pus ca implicit pentru {purpose}."
            if changed
            else (
                f"Implicitul rămâne {current[field] or 'neales'}"
                + ("" if allow else " (blocat de Owner)")
                + "."
            )
        )
        + (f" Primele trei după clasare: {'; '.join(top)}." if top else "")
        + f" — {steward_name}"
    )
    _report(
        engine,
        steward_id,
        f"Cercetare de modele ({purpose}): {recommended or 'fără recomandare'}"[:200],
        letter,
        correlation,
    )
    with Session(engine) as session, session.begin():
        append_event(
            session,
            "media.model_research_recorded",
            "integration",
            integration_id,
            1,
            {
                "purpose": purpose,
                "steward": steward_name,
                "pages": len(pages),
                "annotated": annotated,
                "recommended": recommended,
                "changed": changed,
            },
            correlation,
        )
    return {
        "status": "COMPLETED",
        "purpose": purpose,
        "steward": steward_name,
        "pages": [url for url, _ in pages],
        "annotated": annotated,
        "recommended": recommended,
        "reason": reason,
        "changed": changed,
        "run_ids": [plan["id"], verdict["id"]],
    }


def _report(engine: Engine, steward_id: str, subject: str, text: str, correlation: str) -> None:
    with Session(engine) as session, session.begin():
        post_message(
            session,
            intent="STATUS",
            subject=subject[:200],
            body={"kind": "model_research"},
            body_text=text,
            from_agent_id=steward_id,
            to_agent_id=None,
            correlation_id=correlation,
        )


def research_all(
    engine: Engine,
    registry: ProviderRegistry,
    settings: Settings,
    correlation_id: str | None = None,
    retriever: SourceRetriever | None = None,
) -> dict[str, Any]:
    """Every purpose with a chosen catalogue service, one after the other."""
    results: dict[str, Any] = {}
    for purpose in PURPOSES:
        try:
            results[purpose] = research_models(
                engine, registry, settings, purpose, correlation_id, retriever
            )
        except ModelResearchError as exc:
            results[purpose] = {"status": "SKIPPED", "purpose": purpose, "reason": str(exc)}
    return results
