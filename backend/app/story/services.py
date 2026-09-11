"""Phase 9 — closing the day, and dramatising it without inventing it.

`../architecture/07_STORY_ENGINE.md` sets out two layers and forbids the second from overwriting
the first. Concretely, that produces two rules this module enforces:

**The log is counted, never narrated.** `close_daily_log` reads the domain event stream and
records what is in it. Nothing here asks a model what kind of day it was, because the log is the
record every episode is later checked against — a narrative inside it would make the check
circular.

**An episode has to be grounded.** Every beat cites the events that inspired it, and every cited
id must exist in that day's log. The forbidden-fabrication list in the spec — a fake hire, a fake
outage, a decision attributed to the wrong person, staff who were not there — is all one failure
underneath: a beat about something the stream never recorded. A beat citing an event that does
not exist is not trimmed away; it fails the whole episode, because the prose around an invented
citation was written under the same misapprehension.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.memory import agent_for_role, remember
from app.agents.models import Agent, Role
from app.agents.services import run_agent_task
from app.models import DomainEvent
from app.providers.registry import ProviderRegistry
from app.services import append_event, utc_now
from app.story.models import DailyStudioLog, StoryEpisode

MAX_BEATS = 8
MAX_NOTABLE_EVENTS = 40
PREFERRED_SHOWRUNNER_ROLE = "ScriptWriter"

#: Event types worth dramatising. Anything not here still counts towards the day's totals but is
#: not offered to the showrunner: a heartbeat is not a story beat, and a shorter list of real
#: material is better than a long one that invites padding.
NARRATIVE_EVENT_TYPES = (
    "agent.hired",
    "agent.terminated",
    "agent.suspended",
    "agent.paused",
    "agent.resumed",
    "agent.model_assigned",
    "agent.message_sent",
    "factual.claim_verified",
    "factual.script_blocked_by_gate",
    "factual.script_approved",
    "media.video_rendered",
    "publishing.video_published",
    "publishing.video_published_simulated",
    "workforce.change_proposed",
    "workforce.change_approved",
    "workforce.change_rejected",
    "settings.integration_checked",
)


class StoryError(ValueError):
    """The episode could not be produced."""


class EpisodeNotGrounded(StoryError):
    """A beat cites something the day's record does not contain.

    Raised instead of dropping the beat: an invented citation means that beat was written from
    somewhere other than the log, and the surrounding prose came from the same pass.
    """


class NothingHappened(StoryError):
    """The day has no narratable events, so there is no episode to write.

    A quiet day is a fact about the studio. Manufacturing a story from an empty log would be
    exactly the fabrication the spec forbids, dressed as productivity.
    """


class _Beat(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scene: str = Field(min_length=5, max_length=300)
    dialogue: str = Field(min_length=5, max_length=1200)
    #: The events this beat dramatises. At least one, and each must be in the day's log.
    event_ids: list[str] = Field(min_length=1, max_length=10)
    #: Who appears. Checked against the roster: the serial cannot cast someone who was not there.
    characters: list[str] = Field(default_factory=list, max_length=10)


class _Episode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=3, max_length=200)
    beats: list[_Beat] = Field(min_length=1, max_length=MAX_BEATS)


_EPISODE = TypeAdapter(_Episode)


def business_date(timezone: str, when: datetime | None = None) -> str:
    """Today's date in the studio's own timezone, not the server's."""
    moment = when or datetime.now(UTC)
    return moment.astimezone(ZoneInfo(timezone)).date().isoformat()


def _day_bounds(date_iso: str, timezone: str) -> tuple[str, str]:
    zone = ZoneInfo(timezone)
    start_local = datetime.fromisoformat(f"{date_iso}T00:00:00").replace(tzinfo=zone)
    return (
        start_local.astimezone(UTC).isoformat(),
        (start_local + timedelta(days=1)).astimezone(UTC).isoformat(),
    )


def _describe(event: DomainEvent) -> str:
    """A plain sentence for one event, built from its own fields.

    Deliberately mechanical. This text is offered to the showrunner as source material, so it
    must not already contain interpretation — that is the episode's job, under supervision.
    """
    payload = event.payload if isinstance(event.payload, dict) else {}
    detail = ", ".join(
        f"{key}={value}"
        for key, value in payload.items()
        if isinstance(value, (str, int, float, bool)) and len(str(value)) <= 80
    )
    return f"{event.event_type} pe {event.aggregate_type} {event.aggregate_id[:8]}" + (
        f" ({detail})" if detail else ""
    )


def close_daily_log(
    engine: Engine, timezone: str, date_iso: str | None = None, correlation_id: str = ""
) -> dict:
    """Count one business date from the event stream and freeze the result.

    Re-closing a date that is already closed returns the stored log unchanged. The log is what an
    episode is checked against, so letting it drift after the fact would let an episode become
    grounded retroactively.
    """
    date_iso = date_iso or business_date(timezone)
    start, end = _day_bounds(date_iso, timezone)
    correlation = correlation_id or str(uuid4())

    with Session(engine) as session, session.begin():
        existing = session.scalars(
            select(DailyStudioLog).where(DailyStudioLog.business_date == date_iso)
        ).first()
        if existing is not None:
            return _public_log(existing)

        events = list(
            session.scalars(
                select(DomainEvent)
                .where(DomainEvent.timestamp >= start, DomainEvent.timestamp < end)
                .order_by(DomainEvent.sequence)
            )
        )
        counts: dict[str, int] = {}
        for event in events:
            counts[event.event_type] = counts.get(event.event_type, 0) + 1

        notable = [
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "at": event.timestamp,
                "description": _describe(event),
            }
            for event in events
            if event.event_type in NARRATIVE_EVENT_TYPES
        ][-MAX_NOTABLE_EVENTS:]

        role_names = {role.id: role.name for role in session.scalars(select(Role))}
        roster = [
            {
                "agent_id": agent.id,
                "display_name": agent.display_name,
                "role_name": role_names.get(agent.role_id, "Agent"),
                "lifecycle": agent.lifecycle,
            }
            for agent in session.scalars(select(Agent).where(Agent.lifecycle != "TERMINATED"))
        ]

        identifier = str(uuid4())
        closed_at = utc_now()
        record_event = append_event(
            session,
            "story.daily_log_closed",
            "daily_studio_log",
            identifier,
            1,
            {"business_date": date_iso, "total_events": len(events)},
            correlation,
        )
        log = DailyStudioLog(
            id=identifier,
            business_date=date_iso,
            timezone=timezone,
            event_counts_json=counts,
            total_events=len(events),
            roster_json=roster,
            notable_events_json=notable,
            status="CLOSED",
            closed_at=closed_at,
            event_id=record_event.event_id,
        )
        session.add(log)
        session.flush()
        return _public_log(log)


def _public_log(log: DailyStudioLog) -> dict:
    return {
        "id": log.id,
        "business_date": log.business_date,
        "timezone": log.timezone,
        "event_counts": log.event_counts_json,
        "total_events": log.total_events,
        "roster": log.roster_json,
        "notable_events": log.notable_events_json,
        "status": log.status,
        "closed_at": log.closed_at,
    }


def list_daily_logs(engine: Engine, limit: int = 30) -> list[dict]:
    with Session(engine) as session:
        return [
            _public_log(log)
            for log in session.scalars(
                select(DailyStudioLog).order_by(DailyStudioLog.business_date.desc()).limit(limit)
            )
        ]


def get_daily_log(engine: Engine, log_id: str) -> dict | None:
    with Session(engine) as session:
        log = session.get(DailyStudioLog, log_id)
        return _public_log(log) if log else None


def _public_episode(episode: StoryEpisode) -> dict:
    return {
        "id": episode.id,
        "log_id": episode.log_id,
        "title": episode.title,
        "beats": episode.beats_json,
        "grounded_event_ids": episode.grounded_event_ids_json,
        "continuity": episode.continuity_json,
        "status": episode.status,
        "written_by_agent_id": episode.written_by_agent_id,
        "created_at": episode.created_at,
        "notes": episode.notes,
    }


def list_episodes(engine: Engine, log_id: str | None = None) -> list[dict]:
    with Session(engine) as session:
        stmt = select(StoryEpisode).order_by(StoryEpisode.created_at.desc())
        if log_id:
            stmt = stmt.where(StoryEpisode.log_id == log_id)
        return [_public_episode(row) for row in session.scalars(stmt)]


_INSTRUCTIONS = """Ești showrunner-ul unui serial scurt despre un studio de producție.

Scrii episodul de azi DOAR din evenimentele reale de mai jos. Poți dramatiza: glume, pauze,
reacții, dialog comprimat, rivalitate jucăușă, încadrare comică.

NU ai voie să inventezi: angajări sau plecări, succese sau eșecuri, cifre de audiență, căderi de
furnizor, sau să atribui o decizie altcuiva decât cui aparține. Nu poți pune în scenă pe cineva
care nu este în distribuția de mai jos.

Fiecare beat citează în "event_ids" identificatorii evenimentelor pe care le dramatizează,
copiați EXACT din listă. Un identificator care nu apare în listă face ca tot episodul să fie
respins — nu doar acel beat.

Răspunde EXCLUSIV cu un obiect JSON valid, fără text în plus:
{{"title": "...", "beats": [{{"scene": "...", "dialogue": "...", "event_ids": ["..."],
  "characters": ["..."]}}]}}

Maximum {max_beats} beat-uri.

DISTRIBUȚIA DE AZI (singurii care pot apărea):
{roster}

EVENIMENTELE DE AZI (singura sursă de fapte):
{events}

{previously}"""


def _resolve_showrunner(session: Session, agent_id: str | None) -> Agent:
    from app.factual.agent_pipeline import _resolve_agent  # noqa: PLC0415

    return _resolve_agent(session, agent_id, PREFERRED_SHOWRUNNER_ROLE)


def _parse_episode(raw: str) -> _Episode:
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise StoryError("Showrunner-ul nu a răspuns cu un obiect JSON.") from None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            raise StoryError("Showrunner-ul nu a răspuns cu un obiect JSON.") from None
    try:
        return _EPISODE.validate_python(data)
    except ValidationError as exc:
        raise StoryError(
            "Episodul nu respectă formatul cerut (fiecare beat are nevoie de scenă, dialog și "
            "cel puțin un eveniment citat)."
        ) from exc


def write_episode(
    engine: Engine,
    registry: ProviderRegistry,
    log_id: str,
    correlation_id: str = "",
    agent_id: str | None = None,
) -> dict:
    """Draft the Office Serial episode for one closed day, and check it against that day."""
    correlation = correlation_id or str(uuid4())
    with Session(engine) as session:
        log = session.get(DailyStudioLog, log_id)
        if log is None:
            raise StoryError(f"Jurnalul {log_id} nu există")
        notable = list(log.notable_events_json or [])
        if not notable:
            raise NothingHappened(
                f"În {log.business_date} nu s-a întâmplat nimic de povestit. "
                "O zi liniștită este un fapt despre studio, nu un motiv de a inventa un episod."
            )
        roster = list(log.roster_json or [])
        allowed_events = {item["event_id"]: item for item in notable}
        allowed_names = {member["display_name"] for member in roster}
        previous = session.scalars(
            select(StoryEpisode)
            .join(DailyStudioLog, StoryEpisode.log_id == DailyStudioLog.id)
            .where(DailyStudioLog.business_date < log.business_date)
            .order_by(DailyStudioLog.business_date.desc())
            .limit(1)
        ).first()
        previously = (
            f"ÎN EPISODUL ANTERIOR:\n{previous.title}\n"
            + "\n".join(f"- {beat.get('scene', '')}" for beat in (previous.beats_json or [])[:3])
            if previous
            else "Acesta este primul episod."
        )
        previous_title = previous.title if previous else None
        showrunner = _resolve_showrunner(session, agent_id)
        showrunner_id = showrunner.id
        date_iso = log.business_date

    prompt = _INSTRUCTIONS.format(
        max_beats=MAX_BEATS,
        roster="\n".join(
            f"- {m['display_name']} ({m['role_name']}, {m['lifecycle']})" for m in roster
        ),
        events="\n".join(f"- {item['event_id']}: {item['description']}" for item in notable),
        previously=previously,
    )
    result = run_agent_task(
        engine,
        registry,
        showrunner_id,
        "write_episode",
        prompt,
        "v1",
        correlation,
        summary=f"Scriu episodul serialului pentru ziua {date_iso}.",
        max_tokens=7200,
        temperature=0.7,
        emit_message=False,
    )
    if result["status"] != "SUCCEEDED" or not (result.get("output_text") or "").strip():
        detail = result.get("error_detail") or "fără text vizibil"
        raise StoryError(f"Showrunner-ul nu a produs un episod ({result['status']}: {detail})")

    draft = _parse_episode(result["output_text"])

    grounded: list[str] = []
    for index, beat in enumerate(draft.beats, start=1):
        unknown = [eid for eid in beat.event_ids if eid not in allowed_events]
        if unknown:
            raise EpisodeNotGrounded(
                f"Episodul a fost respins: beat-ul {index} citează evenimente care nu s-au "
                f"petrecut în {date_iso}. Nimic nu a fost salvat."
            )
        # Casting someone who was not there is the same failure as citing an event that did not
        # happen — it puts a person in a room the record says they were not in.
        strangers = [name for name in beat.characters if name not in allowed_names]
        if strangers:
            raise EpisodeNotGrounded(
                f"Episodul a fost respins: beat-ul {index} pune în scenă pe cineva care nu era "
                f"în studio în {date_iso}."
            )
        grounded.extend(eid for eid in beat.event_ids if eid not in grounded)

    beats = [
        {
            "beat_number": index,
            "scene": beat.scene.strip(),
            "dialogue": beat.dialogue.strip(),
            "event_ids": beat.event_ids,
            "characters": beat.characters,
        }
        for index, beat in enumerate(draft.beats, start=1)
    ]

    identifier = str(uuid4())
    with Session(engine) as session, session.begin():
        event = append_event(
            session,
            "story.episode_drafted",
            "story_episode",
            identifier,
            1,
            {"log_id": log_id, "grounded_events": len(grounded)},
            correlation,
        )
        episode = StoryEpisode(
            id=identifier,
            log_id=log_id,
            title=draft.title.strip(),
            beats_json=beats,
            grounded_event_ids_json=grounded,
            continuity_json={
                "previous_episode_title": previous_title,
                "roster_size": len(roster),
                "business_date": date_iso,
            },
            status="DRAFT",
            written_by_agent_id=showrunner_id,
            created_at=utc_now(),
            event_id=event.event_id,
            notes=None,
        )
        session.add(episode)
        session.flush()
        return {
            "agent_id": showrunner_id,
            "run_id": result["id"],
            "episode": _public_episode(episode),
        }


def decide_episode(
    engine: Engine, episode_id: str, approve: bool, notes: str, correlation_id: str = ""
) -> dict:
    """The Owner accepts or rejects a dramatisation of their own studio."""
    correlation = correlation_id or str(uuid4())
    with Session(engine) as session, session.begin():
        episode = session.get(StoryEpisode, episode_id)
        if episode is None:
            raise StoryError("Episodul nu există")
        if episode.status != "DRAFT":
            raise StoryError(f"Episodul este deja {episode.status.lower()}")
        episode.status = "APPROVED" if approve else "REJECTED"
        episode.notes = notes.strip()[:2000] or None
        episode.event_id = append_event(
            session,
            "story.episode_approved" if approve else "story.episode_rejected",
            "story_episode",
            episode.id,
            2,
            {"log_id": episode.log_id},
            correlation,
        ).event_id
        showrunner = agent_for_role(session, PREFERRED_SHOWRUNNER_ROLE)
        remember(
            session,
            memory_class="OWNER_POLICY",
            content=(
                f"The Owner {'approved' if approve else 'rejected'} the episode "
                f"“{episode.title[:120]}”" + (f": {episode.notes}" if episode.notes else ".")
            ),
            source_type="owner",
            source_id=episode.id,
            event_id=episode.event_id,
            agent_id=showrunner.id if showrunner else None,
        )
        session.flush()
        return _public_episode(episode)


def grounding_report(engine: Engine, episode_id: str) -> dict[str, Any]:
    """Re-check a stored episode against its day, so the claim can be audited, not trusted."""
    with Session(engine) as session:
        episode = session.get(StoryEpisode, episode_id)
        if episode is None:
            raise StoryError("Episodul nu există")
        log = session.get(DailyStudioLog, episode.log_id)
        known = {item["event_id"] for item in (log.notable_events_json or [])} if log else set()
        cited = list(episode.grounded_event_ids_json or [])
        missing = [eid for eid in cited if eid not in known]
        return {
            "episode_id": episode.id,
            "business_date": log.business_date if log else None,
            "cited_events": len(cited),
            "events_available_that_day": len(known),
            "citations_not_in_the_log": missing,
            "grounded": not missing,
        }
