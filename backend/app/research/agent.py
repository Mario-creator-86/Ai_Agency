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

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.identity import blocker_of, clipped, parse_structured
from app.agents.memory import agent_for_role, remember
from app.agents.messages import post_message
from app.agents.services import run_agent_task
from app.analytics.models import ContentStrategy
from app.config import Settings
from app.factual.editorial import IDEA_WEIGHTS, composite, idea_rejections
from app.factual.models import SourceSnapshot, TopicIdea
from app.factual.sanitizer import wrap_in_inert_boundary
from app.providers.registry import ProviderRegistry
from app.research.retrieval import RateLimited, RetrievalError
from app.research.service import (
    HostNotAllowed,
    allowed_host_rows,
    find_pages,
    research_budget,
    retrieve_and_ingest,
)
from app.services import append_event, utc_now

logger = logging.getLogger("studio.research.agent")

RESEARCHER_ROLE = "LeadResearcher"
TEMPLATE_VERSION = "research-agent-v1"

#: The studio's editorial dimensions, and the older names they replaced. Six equal criteria
#: had the studio proposing whatever looked good; the weights and the floors now live in
#: `app.factual.editorial`, because whether an idea is worth producing is an editorial
#: question, not a research one. Legacy names are still read so an answer in the old shape is
#: scored on what it did say rather than thrown away.
CRITERIA = tuple(IDEA_WEIGHTS)
LEGACY_SCORE_NAMES = {
    "interest": ("hook_potential", "curiosity"),
    "credibility": ("fact_confidence",),
    "novelty": ("originality",),
    "cost": ("production_feasibility",),
}

#: Two titles this similar are the same idea. Measured on word sets, so re-ordering or a
#: synonym in the middle does not smuggle yesterday's topic back in as new.
DUPLICATE_RATIO = 0.6
MAX_CANDIDATES = 8
#: The most pages a plan may name for one topic, whatever the settings say: the budget is
#: the Owner's (``research_pages_per_topic``), this is the ceiling under it.
MAX_URLS = 8


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
    """What the proposer thinks of a candidate, on the dimensions that decide a film.

    A score is an opinion about a candidate and never evidence about the world. The weights
    are the studio's (`IDEA_WEIGHTS`): hook, payoff, story and fact confidence carry most,
    because a beautiful topic with nothing to say is what the old even average kept choosing.
    """

    model_config = ConfigDict(extra="ignore")
    hook_potential: float = Field(ge=0, le=1)
    curiosity: float = Field(ge=0, le=1)
    story_potential: float = Field(ge=0, le=1)
    payoff_strength: float = Field(ge=0, le=1)
    visual_potential: float = Field(ge=0, le=1)
    fact_confidence: float = Field(ge=0, le=1)
    channel_fit: float = Field(ge=0, le=1)
    originality: float = Field(ge=0, le=1)
    shareability: float = Field(ge=0, le=1)
    retention_potential: float = Field(ge=0, le=1)
    cta_opportunity: float = Field(ge=0, le=1)
    production_feasibility: float = Field(ge=0, le=1)
    #: Whether the authorised sites can actually evidence this. Not an editorial dimension —
    #: it decides whether the topic can be researched at all, which retrieval reads.
    source_availability: float = Field(default=0.5, ge=0, le=1)

    @model_validator(mode="before")
    @classmethod
    def _read_legacy_names(cls, data: Any) -> Any:
        """Accept an answer in the older six-criteria shape by mapping what it did say."""
        if not isinstance(data, dict):
            return data
        filled = dict(data)
        for legacy, replacements in LEGACY_SCORE_NAMES.items():
            value = filled.get(legacy)
            if not isinstance(value, int | float):
                continue
            for key in replacements:
                filled.setdefault(key, value)
        return filled

    def composite(self) -> float:
        return composite(self.model_dump())


class TopicThesis(BaseModel):
    """Why this video should exist, which is the question nothing in the studio used to ask.

    "The James Webb telescope discovered something interesting" is not an idea. "A newly
    observed exoplanet is unusual, and the video ends by revealing the one characteristic
    astronomers care about" is. Every field here is part of that difference, and
    `idea_rejections` refuses a candidate that cannot fill them.
    """

    model_config = ConfigDict(extra="ignore")
    core_fact: str = Field(default="", max_length=600)
    why_it_matters: str = Field(default="", max_length=600)
    why_now: str = Field(default="", max_length=400)
    payoff: str = Field(default="", max_length=600)
    hook: str = Field(default="", max_length=400)
    ending: str = Field(default="", max_length=400)
    cta: str = Field(default="", max_length=300)
    cta_kind: str = Field(default="", max_length=20)
    channel_fit: str = Field(default="", max_length=300)
    visual_potential: str = Field(default="", max_length=600)
    risk: str = Field(default="", max_length=600)
    expected_seconds: float = Field(default=30.0, ge=0, le=600)

    _clip_fact = field_validator("core_fact", mode="before")(clipped(600))
    _clip_matters = field_validator("why_it_matters", mode="before")(clipped(600))
    _clip_now = field_validator("why_now", mode="before")(clipped(400))
    _clip_payoff = field_validator("payoff", mode="before")(clipped(600))
    _clip_hook = field_validator("hook", mode="before")(clipped(400))
    _clip_ending = field_validator("ending", mode="before")(clipped(400))
    _clip_cta = field_validator("cta", mode="before")(clipped(300))
    _clip_visual = field_validator("visual_potential", mode="before")(clipped(600))
    _clip_risk = field_validator("risk", mode="before")(clipped(600))


class TopicCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = Field(min_length=5, max_length=200)
    topic: str = Field(min_length=2, max_length=600)
    angle: str = Field(min_length=5, max_length=2000)
    target_audience: str = Field(default="general", max_length=300)
    expected_hosts: list[str] = Field(default_factory=list, max_length=6)
    scores: TopicScores
    thesis: TopicThesis = Field(default_factory=TopicThesis)

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
    "Propose {wanted} candidate topics for the factual shorts channel, each about thirty "
    "seconds long. A topic is not an idea. An idea answers why the video should exist: what "
    "the one fact is, why anyone should care, what makes a viewer stop scrolling in the first "
    "three seconds, what they know or feel at the end, and how the film closes. "
    '"The James Webb telescope discovered something interesting" is not an idea. "A newly '
    "observed exoplanet is unusual, and the film ends by revealing the one characteristic "
    'astronomers care about" is. "Napoleon facts" is not an idea. "Most people picture '
    "Napoleon as unusually short; the film starts from that assumption, shows where the myth "
    'came from, and ends with his actual height for his time" is.\n\n'
    "Each candidate must be something the sites listed below could actually evidence — you "
    "may only name hosts from that list, and the studio fetches the pages itself, so a site "
    "that cannot support the topic is a topic that dies at verification. Do not repeat "
    "anything in the recent topics list, and do not restate one idea in different words. Do "
    "not propose a topic because it is trending, recent, or would look beautiful: a trend is "
    "a hook, not a source, and a film with nothing to say fails however good the pictures "
    "are. You are given what people in the studio's country are searching for and what "
    "measured well or badly on the studio's own channels; prefer the kinds of topic that "
    "measured well.\n\n"
    "Score each candidate 0..1, honestly — a low score on a real weakness is more useful "
    "than a high one everywhere: hook_potential (would a viewer stop scrolling), curiosity "
    "(does it open an information gap), story_potential (is there a thirty-second story, not "
    "a list of facts), payoff_strength (is the ending worth the wait), visual_potential (is "
    "there something to show, not just to say), fact_confidence (can every statement be "
    "sourced on the authorised sites), channel_fit, originality, shareability, "
    "retention_potential (would they watch to the end), cta_opportunity (is there a natural "
    "question to leave them with), production_feasibility (1 means easy), source_availability "
    "(is the evidence on the authorised sites).\n\n"
    "Begin your reply with the JSON object itself — no analysis or preamble before it. "
    'Return only JSON: {{"candidates": [{{"title": "...", "topic": "...", "angle": "...", '
    '"target_audience": "...", "expected_hosts": ["..."], '
    '"scores": {{"hook_potential": 0.0, "curiosity": 0.0, "story_potential": 0.0, '
    '"payoff_strength": 0.0, "visual_potential": 0.0, "fact_confidence": 0.0, '
    '"channel_fit": 0.0, "originality": 0.0, "shareability": 0.0, '
    '"retention_potential": 0.0, "cta_opportunity": 0.0, "production_feasibility": 0.0, '
    '"source_availability": 0.0}}, '
    '"thesis": {{"core_fact": "the one verified fact the film rests on", '
    '"why_it_matters": "why this is worth thirty seconds of a stranger\'s life", '
    '"why_now": "why today rather than any day", '
    '"payoff": "what the viewer knows, feels or understands at the end", '
    '"hook": "the first sentence, which must open a gap the film then closes", '
    '"ending": "how the film closes", '
    '"cta": "a closing line that belongs to this story and invites a comment", '
    '"cta_kind": "CURIOSITY|DECISION|KNOWLEDGE|DEBATE|FOLLOW|SERIES|COMMENT", '
    '"channel_fit": "why it suits this channel", '
    '"visual_potential": "what is actually shown, shot by shot in one line", '
    '"risk": "what could be wrong, unverifiable or misread", '
    '"expected_seconds": 30}}}}]}}.\n'
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
            # The editorial rules, before anyone is asked to choose: an idea with no hook, no
            # payoff, no reason to exist or a hook its ending does not answer is refused here.
            # It is kept with its reasons rather than dropped, because what the studio turned
            # down is also what it learns from (and what the Owner can argue with).
            refusals = idea_rejections(candidate.thesis.model_dump(), scores.model_dump())
            if refusals:
                event = append_event(
                    session,
                    "factual.topic_refused",
                    "topic_idea",
                    identifier,
                    1,
                    {"title": candidate.title, "reasons": refusals[:4]},
                    correlation,
                )
                session.add(
                    TopicIdea(
                        id=identifier,
                        title=candidate.title,
                        topic=candidate.topic,
                        angle=candidate.angle,
                        target_audience=candidate.target_audience or "general",
                        novelty_score=scores.originality,
                        status="REJECTED",
                        created_at=utc_now(),
                        selected_at=None,
                        event_id=event.event_id,
                        scores_json={**scores.model_dump(), "composite": scores.composite()},
                        source_plan_json=list(candidate.expected_hosts),
                        proposed_by_agent_id=researcher_id,
                        thesis_json=candidate.thesis.model_dump(),
                        rejection_reasons_json=refusals,
                        decided_by="editorial rules",
                        decision_notes="; ".join(refusals)[:2000],
                    )
                )
                existing.append(candidate.title)
                rejected.append(
                    {"title": candidate.title, "why": "editorial: " + "; ".join(refusals[:2])}
                )
                continue
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
                    novelty_score=scores.originality,
                    status="PROPOSED",
                    created_at=utc_now(),
                    selected_at=None,
                    event_id=event.event_id,
                    scores_json={**scores.model_dump(), "composite": scores.composite()},
                    source_plan_json=list(candidate.expected_hosts),
                    proposed_by_agent_id=researcher_id,
                    thesis_json=candidate.thesis.model_dump(),
                    rejection_reasons_json=[],
                )
            )
            existing.append(candidate.title)
            stored.append(
                {
                    "id": identifier,
                    "title": candidate.title,
                    "composite": scores.composite(),
                    "expected_hosts": list(candidate.expected_hosts),
                    "payoff": candidate.thesis.payoff,
                    "hook": candidate.thesis.hook,
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


#: Words that open a title without naming anything: not a search on their own.
_OPENERS = frozenset(
    {"how", "why", "what", "the", "a", "an", "is", "are", "can", "does", "do", "when", "where"}
)


def search_queries(title: str, topic: str = "") -> list[str]:
    """Short searches a site's suggestion search can answer, from a title and its subject.

    A suggestion search matches the start of a page title, so the proper names in the
    title and the subject line — "James Webb Space Telescope", "Higgs Boson", "UNESCO" —
    are what finds pages; the whole sentence finds nothing. Longer names first; a name of
    three or more words is also asked as its first two; at most six searches.
    """
    queries: list[str] = []
    for text in (title, topic):
        words = [w.strip("'\"“”‘’(),.:;!?") for w in str(text).split()]
        run: list[str] = []
        runs: list[list[str]] = []
        for index, word in enumerate(words):
            bare = re.sub(r"[’']s$", "", word)
            capital = bool(bare) and (bare[0].isupper() or bare.isupper())
            opener = index == 0 and bare.lower() in _OPENERS
            if capital and not opener and bare.lower() not in _OPENERS:
                run.append(bare)
            else:
                if run:
                    runs.append(run)
                run = []
        if run:
            runs.append(run)
        for group in runs:
            queries.append(" ".join(group[:4]))
            if len(group) >= 3:
                queries.append(" ".join(group[:2]))
            if group[0].isupper() and len(group[0]) >= 3:
                queries.append(group[0])  # an acronym is a name on its own: UNESCO, CERN, LHC
    ordered: list[str] = []
    for query in sorted(queries, key=lambda q: -len(q)):
        if query and query not in ordered and len(query) >= 3:
            ordered.append(query)
    return ordered[:6]


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
#: When the studio found pages, the plan is a choice among them. Measured on the clean
#: studio's first days: every address the Researcher guessed returned 404, and every page
#: a site's own search returned existed. A guess next to a real page is a page not read.
_FOUND_INSTRUCTIONS = (
    "Pages the studio has already found on the authorised sites for this topic — they exist "
    "and can be read, so prefer them: choose up to {limit} among them. An address that is "
    "not in this list is a guess and is not fetched today:\n"
)
#: Why a guessed address is set aside when real pages exist; shown in the run's record.
GUESS_SET_ASIDE = (
    "adresă ghicită, nefolosită: studioul a găsit pagini reale pentru subiect și citește "
    "doar dintre ele"
)


def gather_sources(
    engine: Engine,
    registry: ProviderRegistry,
    settings: Settings,
    topic_id: str,
    correlation_id: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Have the Researcher name pages for a topic, then fetch them. Returns what was stored.

    ``limit`` is the pages read for this topic; left out, it is the Owner's
    ``research_pages_per_topic`` (``research_budget``), capped at ``MAX_URLS``. When the
    sites' own searches or the verified search engine found pages, the plan is a choice
    among them and a guessed address is set aside unread; when nothing was found, the
    Researcher's addresses are tried as before, and the letter says what each answered.
    """
    correlation = correlation_id or str(uuid4())
    limit = max(1, min(limit or research_budget(settings)[1], MAX_URLS))
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
    # search address, then the verified search engine: pages found this way exist, and a
    # plan that starts from them is read. `found_via` says which way found what and how
    # many engine results fell outside the allowlist.
    found_via: dict[str, Any] = {}
    found = [
        p
        for p in find_pages(settings, engine, search_queries(title, topic.topic), report=found_via)
        if p["url"] not in already
    ]
    payload = json.dumps({"title": title, "angle": angle}, ensure_ascii=False)
    prompt = _SOURCE_INSTRUCTIONS.format(limit=limit, hosts=", ".join(shortlist[:12]))
    if found:
        prompt += (
            _FOUND_INSTRUCTIONS.format(limit=limit)
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

    found_urls = {p["url"].rstrip("/") for p in found}
    for candidate in plan.urls[:limit]:
        # ".../webb" and ".../webb/" are one page; the third clean day stored it twice.
        url = candidate.url.strip()
        if url.rstrip("/") in {u.rstrip("/") for u in already}:
            continue
        if found and url.rstrip("/") not in found_urls:
            # Real pages exist for this topic: a guess is not fetched, and its being set
            # aside is recorded so the Director can see the plan and the choice.
            failed.append({"url": url, "why": GUESS_SET_ASIDE})
            continue
        read(url)
    # The plan is the Researcher's choice among the pages that exist; it is not a way to
    # lose the ones he did not choose. What was found is read up to the limit.
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
                    "nu o servește unui program. Căutările site-urilor și motorul de căutare, "
                    "dacă este conectat, nu au găsit pagini pentru acest subiect. — Dr. Aris"
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
        "found_via": found_via,
    }
