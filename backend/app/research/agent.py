"""What the studio decides to look into, and where it looks.

Two stages of `../architecture/39_DAILY_AUTONOMOUS_RUNBOOK.md` had no agent behind them: §3
(idea generation) and the retrieval half of §4 (research). Topics were typed in by the Owner
and sources were ingested by hand, so a studio left alone produced nothing and reported
"nothing to produce" — truthfully, and uselessly.

The Lead Researcher now proposes candidate topics, scored on the runbook's own criteria and
deduplicated against what the studio already has, and then proposes the pages to read for the
topic in production. Two rules keep this honest:

- **A proposal is not a fact.** A topic is stored as PROPOSED with the proposer's scores; the
  Director selects under policy (§5), and nothing is written as evidence.
- **Every URL is actually fetched.** The Researcher may only name hosts the Owner authorised
  and whose test passed; the studio then downloads the page through the same retriever the
  Owner's own "add source" button uses. A URL the model invented does not resolve, and one
  that does is stored with the text that came back — never with the text the model expected.
  The Fact Checker still has to find each claim in that text, verbatim.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.identity import blocker_of, clipped, parse_structured
from app.agents.memory import agent_for_role, remember
from app.agents.messages import post_message
from app.agents.services import run_agent_task
from app.analytics.models import ContentStrategy
from app.config import Settings
from app.factual.models import SourceSnapshot, TopicIdea
from app.factual.sanitizer import wrap_in_inert_boundary
from app.providers.registry import ProviderRegistry
from app.research.retrieval import RateLimited, RetrievalError
from app.research.service import (
    HostNotAllowed,
    allowed_host_rows,
    find_pages,
    retrieve_and_ingest,
)
from app.services import append_event, utc_now

logger = logging.getLogger("studio.research.agent")

RESEARCHER_ROLE = "LeadResearcher"
TEMPLATE_VERSION = "research-agent-v1"

#: The runbook's scoring criteria (§3). The proposer scores each 0..1; the composite is their
#: mean, so a candidate cannot be pushed up by one strong number alone.
CRITERIA = ("interest", "credibility", "source_availability", "visual_potential", "novelty", "cost")

#: Two titles this similar are the same idea. Measured on word sets, so re-ordering or a
#: synonym in the middle does not smuggle yesterday's topic back in as new.
DUPLICATE_RATIO = 0.6
MAX_CANDIDATES = 8
MAX_URLS = 4


class ResearchAgentError(ValueError):
    """The proposal could not be produced or did not match its schema; nothing was stored."""


class NoResearcher(ResearchAgentError):
    """No active employee holds the research role."""


class NoAuthorisedHosts(ResearchAgentError):
    """No site the studio may read has passed its test, so there is nowhere to look."""


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", str(text).lower()) if len(w) > 2}


def _too_similar(title: str, existing: list[str]) -> str | None:
    """The existing title this one duplicates, if any (Jaccard over word sets)."""
    words = _words(title)
    if not words:
        return None
    for other in existing:
        other_words = _words(other)
        if not other_words:
            continue
        overlap = len(words & other_words) / len(words | other_words)
        if overlap >= DUPLICATE_RATIO:
            return other
    return None


def _tested_hosts(settings: Settings, engine: Engine) -> list[str]:
    """Hosts the studio may read and has actually read: authorised and last tested PASSED.

    A host from the configuration file has no test row; it counts, because putting it there is
    the Owner's own statement. A host added in the interface counts once its test passed.
    """
    hosts = []
    for row in allowed_host_rows(settings, engine):
        if row["source"] == "env" or row["last_test_status"] == "PASSED":
            hosts.append(row["host"])
    return hosts


# ----------------------------------------------------------------------------- §3 ideas


class TopicScores(BaseModel):
    model_config = ConfigDict(extra="ignore")
    interest: float = Field(ge=0, le=1)
    credibility: float = Field(ge=0, le=1)
    source_availability: float = Field(ge=0, le=1)
    visual_potential: float = Field(ge=0, le=1)
    novelty: float = Field(ge=0, le=1)
    cost: float = Field(ge=0, le=1)

    def composite(self) -> float:
        return round(sum(getattr(self, key) for key in CRITERIA) / len(CRITERIA), 4)


class TopicCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = Field(min_length=5, max_length=200)
    topic: str = Field(min_length=2, max_length=600)
    angle: str = Field(min_length=5, max_length=2000)
    target_audience: str = Field(default="general", max_length=300)
    expected_hosts: list[str] = Field(default_factory=list, max_length=6)
    scores: TopicScores

    _clip_title = field_validator("title", mode="before")(clipped(200))
    _clip_topic = field_validator("topic", mode="before")(clipped(600))
    _clip_angle = field_validator("angle", mode="before")(clipped(2000))
    _clip_audience = field_validator("target_audience", mode="before")(clipped(300))


class LooseProposal(BaseModel):
    """The answer's shape before each candidate is judged on its own: one candidate that
    breaks the schema is one candidate rejected with its reason, not a day without ideas."""

    model_config = ConfigDict(extra="ignore")
    candidates: list[dict[str, Any]] = Field(default_factory=list, max_length=40)


class TopicProposal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    candidates: list[TopicCandidate] = Field(default_factory=list, max_length=MAX_CANDIDATES)


_IDEA_INSTRUCTIONS = (
    "Propose {wanted} candidate topics for the factual shorts channel. Each must be something "
    "the sites listed below could actually evidence — you may only name hosts from that list, "
    "and the studio will fetch the pages itself, so a site that cannot support the topic is a "
    "topic that dies at verification. Do not repeat anything in the recent topics list, and do "
    "not restate one idea in different words. Score each candidate 0..1 on the studio's "
    "criteria: interest (would a viewer stop scrolling), credibility (can it be sourced), "
    "source_availability (is it on the authorised sites), visual_potential (is there something "
    "to show), novelty (has the studio done it), cost (1 means cheap to produce). You are also "
    "given what people in the studio's country are searching for right now and what measured "
    "well or badly on the studio's own channels: a trend is a hook, not a source — use it only "
    "where the authorised sites can evidence it — and prefer the kinds of topic that measured "
    "well over the kinds that did not. Begin your reply with the JSON object itself — no "
    "analysis or preamble before it. Return only "
    'JSON: {{"candidates": [{{"title": "...", "topic": "...", "angle": "...", '
    '"target_audience": "...", "expected_hosts": ["..."], "scores": {{"interest": 0.0, '
    '"credibility": 0.0, "source_availability": 0.0, "visual_potential": 0.0, "novelty": 0.0, '
    '"cost": 0.0}}}}]}}.\n'
)


def _signals(engine: Engine, settings: Settings) -> dict[str, Any]:
    """What is trending and what measured, for the proposal prompt. Empty when unknown."""
    from app.analytics.services import compute_cohort_metrics  # noqa: PLC0415
    from app.analytics.trends import trending_now  # noqa: PLC0415
    from app.publishing.models import ChannelRecord  # noqa: PLC0415

    trends = trending_now(engine, settings.trends_geo) if settings.trends_enabled else []
    best: list[dict[str, Any]] = []
    worst: list[dict[str, Any]] = []
    with Session(engine) as session:
        channel_ids = [c.id for c in session.scalars(select(ChannelRecord))]
    for channel_id in channel_ids:
        cohorts = [
            c for c in compute_cohort_metrics(engine, channel_id, "topic") if c["sample_size"] >= 3
        ]
        for item in cohorts[:3]:
            best.append(
                {
                    "topic": item["cohort_key"],
                    "mean_views": item["mean_views"],
                    "mean_retention": item["mean_retention"],
                    "videos": item["sample_size"],
                }
            )
        for item in cohorts[-3:]:
            if item not in cohorts[:3]:
                worst.append(
                    {
                        "topic": item["cohort_key"],
                        "mean_views": item["mean_views"],
                        "mean_retention": item["mean_retention"],
                        "videos": item["sample_size"],
                    }
                )
    return {
        "trending_now": [
            {"query": t["title"], "searches": t["approx_traffic"], "news": t["news"]}
            for t in trends
        ],
        "measured_performance": {
            "best": best[:6],
            "worst": worst[:6],
            "note": (
                "no measured performance yet; nothing published and measured"
                if not best and not worst
                else "from the studio's own analytics, cohorts of three or more videos"
            ),
        },
    }


def propose_topics(
    engine: Engine,
    registry: ProviderRegistry,
    settings: Settings,
    correlation_id: str | None = None,
    wanted: int = 5,
) -> dict[str, Any]:
    """Have the Lead Researcher propose candidate topics. Stores what survives validation."""
    correlation = correlation_id or str(uuid4())
    hosts = _tested_hosts(settings, engine)
    if not hosts:
        raise NoAuthorisedHosts(
            "Niciun site autorizat și testat: cercetarea nu are unde să caute dovezi."
        )
    with Session(engine) as session:
        researcher = agent_for_role(session, RESEARCHER_ROLE)
        if researcher is None:
            raise NoResearcher("Niciun cercetător activ")
        researcher_id = researcher.id
        recent = [
            row.title
            for row in session.scalars(
                select(TopicIdea).order_by(TopicIdea.created_at.desc()).limit(40)
            )
        ]
        strategy = session.scalar(
            select(ContentStrategy)
            .where(ContentStrategy.is_active.is_(True))
            .order_by(ContentStrategy.version.desc())
        )
        weights = dict(strategy.topic_weights_json or {}) if strategy else {}

    payload = json.dumps(
        {
            "authorised_hosts": hosts,
            "recent_topics": recent,
            "topic_weights": weights,
            **_signals(engine, settings),
        },
        ensure_ascii=False,
    )
    prompt = _IDEA_INSTRUCTIONS.format(wanted=min(wanted, MAX_CANDIDATES)) + wrap_in_inert_boundary(
        payload, "studio-context"
    )
    result = run_agent_task(
        engine,
        registry,
        researcher_id,
        "propose_topics",
        prompt,
        TEMPLATE_VERSION,
        correlation,
        summary=f"Caut {min(wanted, MAX_CANDIDATES)} idei de subiect pentru studio.",
        max_tokens=7500,
        temperature=0.4,
        emit_message=False,
    )
    text = result.get("output_text") or ""
    if result["status"] != "SUCCEEDED" or not text.strip():
        raise ResearchAgentError(
            f"Cercetătorul nu a produs propuneri ({result['status']}: "
            f"{result.get('error_detail') or 'fără text vizibil'})"
        )
    blocker = blocker_of(text)
    if blocker is not None:
        with Session(engine) as session, session.begin():
            post_message(
                session,
                intent="ESCALATE",
                subject=f"Idea generation blocked: {blocker.reason[:150]}",
                body={"reason": blocker.reason, "needs": blocker.needs},
                from_agent_id=researcher_id,
                run_id=result["id"],
                correlation_id=correlation,
            )
        return {
            "agent_id": researcher_id,
            "run_id": result["id"],
            "proposed": [],
            "blocked": blocker.reason,
        }

    loose = parse_structured(text, LooseProposal)
    if not isinstance(loose, LooseProposal):
        raise ResearchAgentError("Propunerile nu respectă schema; nimic nu a fost salvat")
    candidates: list[TopicCandidate] = []
    rejected: list[dict[str, str]] = []
    for raw in loose.candidates[:MAX_CANDIDATES]:
        try:
            candidates.append(TopicCandidate.model_validate(raw))
        except ValidationError as exc:
            field = ".".join(str(x) for x in exc.errors()[0]["loc"]) if exc.errors() else "?"
            rejected.append(
                {"title": str(raw.get("title", "?"))[:200], "why": f"schemă: câmpul {field}"}
            )
    allowed = set(hosts)
    stored: list[dict[str, Any]] = []
    with Session(engine) as session, session.begin():
        existing = [row.title for row in session.scalars(select(TopicIdea))]
        for candidate in candidates:
            duplicate = _too_similar(candidate.title, existing)
            if duplicate:
                rejected.append({"title": candidate.title, "why": f"duplicat: «{duplicate[:60]}»"})
                continue
            unknown = [h for h in candidate.expected_hosts if h not in allowed]
            if unknown:
                rejected.append(
                    {"title": candidate.title, "why": "site neautorizat: " + ", ".join(unknown[:3])}
                )
                continue
            scores = candidate.scores
            identifier = str(uuid4())
            event = append_event(
                session,
                "factual.topic_proposed",
                "topic_idea",
                identifier,
                1,
                {"title": candidate.title, "score": scores.composite()},
                correlation,
            )
            session.add(
                TopicIdea(
                    id=identifier,
                    title=candidate.title,
                    topic=candidate.topic,
                    angle=candidate.angle,
                    target_audience=candidate.target_audience or "general",
                    novelty_score=scores.novelty,
                    status="PROPOSED",
                    created_at=utc_now(),
                    selected_at=None,
                    event_id=event.event_id,
                    scores_json={**scores.model_dump(), "composite": scores.composite()},
                    source_plan_json=list(candidate.expected_hosts),
                    proposed_by_agent_id=researcher_id,
                )
            )
            existing.append(candidate.title)
            stored.append(
                {
                    "id": identifier,
                    "title": candidate.title,
                    "composite": scores.composite(),
                    "expected_hosts": list(candidate.expected_hosts),
                }
            )
        if stored:
            remember(
                session,
                memory_class="AGENT_OPINION",
                content="Proposed topics: "
                + "; ".join(f"{t['title']} ({t['composite']})" for t in stored[:5]),
                source_type="run",
                source_id=result["id"],
                agent_id=researcher_id,
            )
            post_message(
                session,
                intent="HANDOFF",
                subject=f"{len(stored)} teme propuse pentru selecție",
                body={"topics": stored, "rejected": rejected},
                from_agent_id=researcher_id,
                to_agent_id=None,
                run_id=result["id"],
                correlation_id=correlation,
            )
    return {
        "agent_id": researcher_id,
        "run_id": result["id"],
        "proposed": stored,
        "rejected": rejected,
    }


# ----------------------------------------------------------------------------- §4 sources


class SourceCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    url: str = Field(min_length=10, max_length=1000)
    why: str = Field(default="", max_length=500)


class SourcePlan(BaseModel):
    model_config = ConfigDict(extra="ignore")
    urls: list[SourceCandidate] = Field(default_factory=list, max_length=MAX_URLS)


_SOURCE_INSTRUCTIONS = (
    "Name up to {limit} pages to read for the topic below. Only these hosts are authorised, "
    "and only pages on them will be fetched: {hosts}. Give full https URLs you believe exist "
    "on those hosts; the studio downloads each one itself and keeps whatever text comes back, "
    "so a URL that does not resolve is simply dropped. Prefer a page about the specific "
    "subject over a section front page. Return only JSON: "
    '{{"urls": [{{"url": "https://...", "why": "..."}}]}}.\n'
)


def gather_sources(
    engine: Engine,
    registry: ProviderRegistry,
    settings: Settings,
    topic_id: str,
    correlation_id: str | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    """Have the Researcher name pages for a topic, then fetch them. Returns what was stored."""
    correlation = correlation_id or str(uuid4())
    hosts = _tested_hosts(settings, engine)
    if not hosts:
        raise NoAuthorisedHosts(
            "Niciun site autorizat și testat: cercetarea nu are unde să caute dovezi."
        )
    with Session(engine) as session:
        topic = session.get(TopicIdea, topic_id)
        if topic is None:
            raise ResearchAgentError("Subiect inexistent")
        researcher = agent_for_role(session, RESEARCHER_ROLE)
        if researcher is None:
            raise NoResearcher("Niciun cercetător activ")
        researcher_id = researcher.id
        title, angle = topic.title, topic.angle
        planned = [h for h in (topic.source_plan_json or []) if h in hosts]
        already = {
            row.url
            for row in session.scalars(
                select(SourceSnapshot).where(SourceSnapshot.topic_id == topic_id)
            )
        }

    shortlist = planned or hosts
    # Before the Researcher names anything, the studio asks the authorised sites that have a
    # search address: pages found this way exist, and a plan that starts from them is read.
    found = [p for p in find_pages(settings, engine, title) if p["url"] not in already]
    payload = json.dumps({"title": title, "angle": angle}, ensure_ascii=False)
    prompt = _SOURCE_INSTRUCTIONS.format(
        limit=min(limit, MAX_URLS), hosts=", ".join(shortlist[:12])
    )
    if found:
        prompt += (
            "Pages the studio has already found on the authorised sites for this topic — "
            "they exist and can be read, so prefer them and add others only if clearly better:\n"
            + "\n".join(f"- {p['url']} — {p['title']}" for p in found)
            + "\n"
        )
    prompt += wrap_in_inert_boundary(payload, "topic")
    result = run_agent_task(
        engine,
        registry,
        researcher_id,
        "gather_sources",
        prompt,
        TEMPLATE_VERSION,
        correlation,
        summary=f"Caut surse pentru subiectul «{title}».",
        max_tokens=3600,
        temperature=0.2,
        emit_message=False,
    )
    text = result.get("output_text") or ""
    if result["status"] != "SUCCEEDED" or not text.strip():
        raise ResearchAgentError(
            f"Cercetătorul nu a propus surse ({result['status']}: "
            f"{result.get('error_detail') or 'fără text vizibil'})"
        )
    plan = parse_structured(text, SourcePlan)
    if not isinstance(plan, SourcePlan):
        raise ResearchAgentError("Lista de surse nu respectă schema; nimic nu a fost preluat")

    fetched: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []

    def read(url: str) -> None:
        try:
            stored = retrieve_and_ingest(engine, settings, url, str(uuid4()), topic_id=topic_id)
            fetched.append(
                {
                    "url": stored["source"]["url"],
                    "title": stored["source"]["title"],
                    "characters": len(stored["source"].get("sanitized_content") or ""),
                }
            )
        except (HostNotAllowed, RetrievalError, RateLimited, ValueError) as exc:
            # A page the studio could not read is a fact about the page, not a failure of the
            # day: it is recorded and the next candidate is tried.
            failed.append({"url": url, "why": str(exc)[:200]})
            logger.info("source_not_retrieved", extra={"url_host": url[:80]})
        already.add(url)

    for candidate in plan.urls[:limit]:
        if candidate.url not in already:
            read(candidate.url)
    # The Researcher's guesses all failed: the pages the studio found are read anyway. A
    # plan is his choice among pages; it is not a way to lose the ones that exist.
    if not fetched:
        for page in found:
            if len(fetched) >= limit:
                break
            if page["url"] not in already:
                read(page["url"])

    with Session(engine) as session, session.begin():
        if fetched:
            remember(
                session,
                memory_class="HISTORICAL_EVENT",
                content=f"Read {len(fetched)} pages for «{title[:80]}»: "
                + "; ".join(f["url"] for f in fetched[:3]),
                source_type="run",
                source_id=result["id"],
                agent_id=researcher_id,
            )
        if failed and not fetched:
            # The letter carries the evidence — each address and what the site answered —
            # so the Director decides on it instead of asking for the fetch log.
            post_message(
                session,
                intent="ESCALATE",
                subject=f"Nicio sursă preluată pentru «{title[:80]}»",
                body={"topic_id": topic_id, "failed": failed},
                body_text=(
                    "Am cerut paginile de mai jos, cu identitatea studioului "
                    "(AutonomousAIStudio-SourceRetriever), și niciuna nu a putut fi citită:\n"
                    + "\n".join(f"- {f['url']} — {f['why']}" for f in failed)
                    + "\nUn 404 pe o adresă ghicită înseamnă că pagina nu există sau că site-ul "
                    "nu o servește unui program; nu am unealtă de căutare. — Dr. Aris"
                ),
                from_agent_id=researcher_id,
                to_agent_id=None,
                run_id=result["id"],
                correlation_id=correlation,
            )
    return {
        "agent_id": researcher_id,
        "run_id": result["id"],
        "topic_id": topic_id,
        "fetched": fetched,
        "failed": failed,
        "found": found,
    }
