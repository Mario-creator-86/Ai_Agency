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

Two more since the serial became a channel (migration 0036):

**The showrunner reads the projection, never the log.** The day's notable events stay the
operational record, raw payloads and all. What crosses to the narrative layer is
`narrative_projection_json` — the PUBLIC_SAFE view `app.story.projection` derives from the
same committed events, redacted. Grounding is checked against the projection, so a beat can
only cite what may be public: the privacy check and the truth check are the same check.

**The serial has a memory of its own.** `ContinuityState` holds the canon episode number,
the open threads, the recurring elements and the last three summaries. The showrunner is
handed them, must say which threads the episode continued or closed, and the state advances
only when an episode is APPROVED — a rejected draft leaves no trace in canon.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.identity import clipped, joined
from app.agents.language import audience_language_line
from app.agents.memory import agent_for_role, remember
from app.agents.models import Agent, Role
from app.agents.services import run_agent_task
from app.media.models import CharacterBible
from app.models import DomainEvent
from app.providers.registry import ProviderRegistry
from app.services import append_event, utc_now
from app.story.models import ContinuityState, DailyStudioLog, StoryEpisode
from app.story.projection import project_events

MAX_BEATS = 8
MAX_NOTABLE_EVENTS = 40
PREFERRED_SHOWRUNNER_ROLE = "ScriptWriter"
#: How many previous summaries the showrunner is handed, and the state keeps.
CONTINUITY_SUMMARIES = 3
#: The serial's series key on its storyboards and in the channel's series rules.
SERIES_KEY = "office_serial"

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


def _names(value: Any) -> Any:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if item is not None][:12]
    return value


class _Beat(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scene: str = Field(min_length=5, max_length=800)
    dialogue: str = Field(min_length=5, max_length=2400)
    # A scene of 330 characters where 300 were allowed threw the whole episode away; so did
    # a dialogue written as a list of lines.
    _clip_scene = field_validator("scene", mode="before")(joined(800))
    _clip_dialogue = field_validator("dialogue", mode="before")(joined(2400))
    _one_character = field_validator("characters", mode="before")(_names)
    #: The events this beat dramatises. At least one, and each must be in the day's log.
    event_ids: list[str] = Field(min_length=1, max_length=10)
    #: Who appears. Checked against the roster: the serial cannot cast someone who was not there.
    characters: list[str] = Field(default_factory=list, max_length=12)


class _Episode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=3, max_length=200)
    beats: list[_Beat] = Field(min_length=1, max_length=MAX_BEATS)
    #: One paragraph the next episode is told, so the serial remembers itself.
    summary: str = Field(default="", max_length=600)
    _clip_summary = field_validator("summary", mode="before")(clipped(600))
    #: What the episode did with the threads it was handed, by their ids, and what it opened.
    threads_continued: list[str] = Field(default_factory=list, max_length=12)
    threads_closed: list[str] = Field(default_factory=list, max_length=12)
    threads_opened: list[str] = Field(default_factory=list, max_length=6)
    recurring: list[str] = Field(default_factory=list, max_length=8)
    _lists = field_validator(
        "threads_continued", "threads_closed", "threads_opened", "recurring", mode="before"
    )(_names)


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

    Deliberately mechanical. This is the operational record of the day; it is not what the
    showrunner reads (that is the projection), so it keeps the payload as it was.
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
        # The projection is derived here, at close, from the same events and the same roster,
        # so the public face of the day is frozen with the day.
        projection = project_events(events, roster)[-MAX_NOTABLE_EVENTS:]

        identifier = str(uuid4())
        closed_at = utc_now()
        record_event = append_event(
            session,
            "story.daily_log_closed",
            "daily_studio_log",
            identifier,
            1,
            {
                "business_date": date_iso,
                "total_events": len(events),
                "public_safe_events": len(projection),
            },
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
            narrative_projection_json=projection,
            status="CLOSED",
            closed_at=closed_at,
            event_id=record_event.event_id,
        )
        session.add(log)
        session.flush()
        return _public_log(log)


def close_previous_day(engine: Engine, settings: Any, correlation_id: str = "") -> dict:
    """Close yesterday's log with every event of that day, if it is not closed already.

    Measured live: the day's log was frozen at the moment the run reached its last stage —
    the morning of its own date — so it covered the morning (92 events, one of them
    narratable) and nothing after. Called at the start of the daily run, this closes the
    previous business date after the date is over, which is the only moment a full day can
    be counted. A date already closed is returned as it is: a closed log never changes.
    """
    yesterday = business_date(settings.timezone, datetime.now(UTC) - timedelta(days=1))
    return close_daily_log(engine, settings.timezone, yesterday, correlation_id)


def _public_log(log: DailyStudioLog) -> dict:
    return {
        "id": log.id,
        "business_date": log.business_date,
        "timezone": log.timezone,
        "event_counts": log.event_counts_json,
        "total_events": log.total_events,
        "roster": log.roster_json,
        "notable_events": log.notable_events_json,
        "narrative_projection": log.narrative_projection_json,
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


def ensure_projection(session: Session, log: DailyStudioLog) -> list[dict]:
    """The log's projection; derived once for a log closed before projections existed.

    Filling a NULL column from the same committed events is not a change to the record —
    the counts, the roster and the notable events stay as they were frozen. It is the one
    write a closed log ever receives, and only while the column is NULL.
    """
    if log.narrative_projection_json is None:
        from app.story.projection import project_log_for_story  # noqa: PLC0415

        log.narrative_projection_json = project_log_for_story(session, log)[-MAX_NOTABLE_EVENTS:]
        session.flush()
    return list(log.narrative_projection_json or [])


# --- continuity --------------------------------------------------------------------------


def _continuity_row(session: Session) -> ContinuityState:
    row = session.get(ContinuityState, 1)
    if row is None:
        row = ContinuityState(
            id=1,
            version=1,
            canon_episode_number=0,
            threads_json=[],
            recurring_json=[],
            summaries_json=[],
            updated_at=utc_now(),
        )
        session.add(row)
        session.flush()
    return row


def _public_continuity(row: ContinuityState) -> dict:
    return {
        "version": row.version,
        "canon_episode_number": row.canon_episode_number,
        "threads": list(row.threads_json or []),
        "recurring": list(row.recurring_json or []),
        "summaries": list(row.summaries_json or []),
        "updated_at": row.updated_at,
    }


def get_continuity(engine: Engine) -> dict:
    """The serial's memory as it stands. A studio with no approved episode has number 0."""
    with Session(engine) as session:
        row = session.get(ContinuityState, 1)
        if row is None:
            return {
                "version": 0,
                "canon_episode_number": 0,
                "threads": [],
                "recurring": [],
                "summaries": [],
                "updated_at": None,
            }
        return _public_continuity(row)


def _next_thread_id(threads: list[dict]) -> str:
    used = [int(m.group(1)) for t in threads if (m := re.match(r"T(\d+)$", str(t.get("id"))))]
    return f"T{max(used, default=0) + 1}"


def advance_continuity(session: Session, episode: StoryEpisode, correlation_id: str) -> dict:
    """Move canon forward for an APPROVED episode: number, threads, summaries. Once per episode.

    Idempotent by episode id, so an Owner's approval and a Director's cannot both count the
    same episode; versioned, so a reader can tell that the state moved.
    """
    row = _continuity_row(session)
    summaries = list(row.summaries_json or [])
    if any(item.get("episode_id") == episode.id for item in summaries):
        return _public_continuity(row)
    continuity = dict(episode.continuity_json or {})
    number = row.canon_episode_number + 1
    closed = {str(t) for t in continuity.get("threads_closed") or []}
    threads = [dict(t) for t in (row.threads_json or []) if str(t.get("id")) not in closed]
    for text in continuity.get("threads_opened") or []:
        text = str(text).strip()
        if text and all(t.get("text") != text for t in threads):
            threads.append(
                {"id": _next_thread_id(threads), "text": text[:300], "opened_in": number}
            )
    recurring = list(row.recurring_json or [])
    for item in continuity.get("recurring") or []:
        item = str(item).strip()[:120]
        if item and item not in recurring:
            recurring.append(item)
    summaries.append(
        {
            "episode_number": number,
            "episode_id": episode.id,
            "title": episode.title,
            "summary": str(continuity.get("summary") or "")[:600],
            "business_date": continuity.get("business_date"),
        }
    )
    event = append_event(
        session,
        "story.continuity_advanced",
        "continuity_state",
        "1",
        row.version + 1,
        {
            "episode_id": episode.id,
            "canon_episode_number": number,
            "open_threads": len(threads),
        },
        correlation_id,
    )
    row.canon_episode_number = number
    row.threads_json = threads[:12]
    row.recurring_json = recurring[-12:]
    row.summaries_json = summaries[-CONTINUITY_SUMMARIES:]
    row.version += 1
    row.updated_at = utc_now()
    row.event_id = event.event_id
    session.flush()
    return _public_continuity(row)


# --- the cast, from the bibles -------------------------------------------------------------


def bibles_for_roster(session: Session, roster: list[dict]) -> dict[str, CharacterBible]:
    """display_name -> the character bible for that roster member, where one exists.

    Matched by the bible's employee id first; by the first word of the two names when a
    bible was written before the employee was hired. A member with no bible has no line —
    the prompt says who they are from the roster alone, and never invents a look.
    """
    bibles = list(session.scalars(select(CharacterBible)))
    by_employee = {b.employee_id: b for b in bibles if b.employee_id}
    by_first = {b.canonical_name.split()[0].lower(): b for b in bibles if b.canonical_name}
    found: dict[str, CharacterBible] = {}
    for member in roster:
        name = str(member.get("display_name") or "")
        bible = by_employee.get(str(member.get("agent_id")))
        if bible is None and name:
            bible = by_first.get(name.split()[0].strip("(),.").lower())
        if bible is not None:
            found[name] = bible
    return found


def _who_they_are(name: str, bible: CharacterBible | None) -> str:
    """One line per cast member, quoting the bible verbatim, as the prompt agent does."""
    if bible is None:
        return ""
    traits = ", ".join(str(t) for t in (bible.personality_json or {}).get("traits") or [])
    speech = bible.speech_style_json or {}
    register = str(speech.get("register") or "")
    habits = ", ".join(str(h) for h in speech.get("habits") or [])
    parts = [f"{bible.canonical_name}: {bible.face_hair_desc}. {bible.outfit_desc}."]
    if traits:
        parts.append(f"Fire: {traits}.")
    if register or habits:
        parts.append(f"Vorbește: {register}" + (f"; {habits}" if habits else "") + ".")
    return " ".join(parts)


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
        "reviewed_by": episode.reviewed_by,
        "review": episode.review_json,
        "storyboard_id": episode.storyboard_id,
        "rewrite_of_id": episode.rewrite_of_id,
    }


def list_episodes(engine: Engine, log_id: str | None = None) -> list[dict]:
    with Session(engine) as session:
        stmt = select(StoryEpisode).order_by(StoryEpisode.created_at.desc())
        if log_id:
            stmt = stmt.where(StoryEpisode.log_id == log_id)
        return [_public_episode(row) for row in session.scalars(stmt)]


def get_episode(engine: Engine, episode_id: str) -> dict | None:
    with Session(engine) as session:
        row = session.get(StoryEpisode, episode_id)
        return _public_episode(row) if row else None


_INSTRUCTIONS = """Ești showrunner-ul unui serial scurt despre un studio de producție. Acesta este
EPISODUL {episode_number}. Episodul este un film vertical de 45-70 de secunde: dialogul tuturor
beat-urilor, citit cu voce tare, trebuie să încapă în acest timp (aproximativ 110-175 de cuvinte).

Scrii episodul de azi DOAR din evenimentele reale de mai jos. Poți dramatiza: glume, pauze,
reacții, dialog comprimat, rivalitate jucăușă, încadrare comică.

NU ai voie să inventezi: angajări sau plecări, succese sau eșecuri, cifre de audiență, căderi de
furnizor, sau să atribui o decizie altcuiva decât cui aparține. Nu poți pune în scenă pe cineva
care nu este în distribuția de mai jos. Nu numi furnizori, modele, prețuri sau adrese.

Primul beat trebuie să se țină singur: un spectator care nu a văzut niciun episod înțelege
unde este și cine vorbește. Fiecare membru al distribuției apare măcar într-un beat.

Fiecare beat citează în "event_ids" identificatorii evenimentelor pe care le dramatizează,
copiați EXACT din listă. Un identificator care nu apare în listă face ca tot episodul să fie
respins — nu doar acel beat.

Răspunde EXCLUSIV cu un obiect JSON valid, fără text în plus:
{{"title": "...", "beats": [{{"scene": "...", "dialogue": "...", "event_ids": ["..."],
  "characters": ["..."]}}], "summary": "un paragraf despre ce s-a întâmplat în episod",
  "threads_continued": ["T1"], "threads_closed": [], "threads_opened": ["o întrebare nouă"],
  "recurring": ["o glumă sau un obiect care revine"]}}

Maximum {max_beats} beat-uri.

DISTRIBUȚIA DE AZI (singurii care pot apărea; folosește numele exact din paranteze):
{roster}

EVENIMENTELE DE AZI (singura sursă de fapte):
{events}

{previously}
{notes}"""


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


def _previously(state: ContinuityState | None, episode_number: int) -> str:
    if state is None or not (state.summaries_json or state.threads_json or state.recurring_json):
        return "Acesta este primul episod."
    lines = ["ÎN EPISOADELE ANTERIOARE:"]
    for item in state.summaries_json or []:
        lines.append(
            f"- Ep. {item.get('episode_number')} «{item.get('title')}»"
            f" ({item.get('business_date')}): {item.get('summary')}"
        )
    if state.threads_json:
        lines.append(
            "FIRE DESCHISE (continuă-le sau închide-le și declară în JSON ce ai făcut cu fiecare):"
        )
        lines.extend(f"- {t.get('id')}: {t.get('text')}" for t in state.threads_json)
    if state.recurring_json:
        lines.append("ELEMENTE RECURENTE: " + "; ".join(str(r) for r in state.recurring_json))
    return "\n".join(lines)


def write_episode(
    engine: Engine,
    registry: ProviderRegistry,
    log_id: str,
    correlation_id: str = "",
    agent_id: str | None = None,
    language: str = "en",
    notes: str | None = None,
    rewrite_of: str | None = None,
) -> dict:
    """Draft the Office Serial episode for one closed day, and check it against that day.

    ``notes`` are the Director's notes on a draft that failed review; the rewrite is asked
    for with them and recorded as a rewrite of that draft.
    """
    correlation = correlation_id or str(uuid4())
    with Session(engine) as session, session.begin():
        log = session.get(DailyStudioLog, log_id)
        if log is None:
            raise StoryError(f"Jurnalul {log_id} nu există")
        projection = ensure_projection(session, log)
        if not projection:
            raise NothingHappened(
                f"În {log.business_date} nu s-a întâmplat nimic de povestit. "
                "O zi liniștită este un fapt despre studio, nu un motiv de a inventa un episod."
            )
        roster = list(log.roster_json or [])
        allowed_events = {item["event_id"]: item for item in projection}
        allowed_names = {member["display_name"] for member in roster}
        state = session.get(ContinuityState, 1)
        episode_number = (state.canon_episode_number if state else 0) + 1
        previously = _previously(state, episode_number)
        previous_title = (state.summaries_json or [{}])[-1].get("title") if state else None
        bibles = bibles_for_roster(session, roster)
        cast_lines = []
        for member in roster:
            name = member["display_name"]
            line = f"- {name} ({member['role_name']}, {member['lifecycle']})"
            who = _who_they_are(name, bibles.get(name))
            cast_lines.append(line + (f" — {who}" if who else ""))
        showrunner = _resolve_showrunner(session, agent_id)
        showrunner_id = showrunner.id
        date_iso = log.business_date

    prompt = audience_language_line(language) + _INSTRUCTIONS.format(
        episode_number=episode_number,
        max_beats=MAX_BEATS,
        roster="\n".join(cast_lines),
        events="\n".join(f"- {item['event_id']}: {item['description']}" for item in projection),
        previously=previously,
        notes=(
            f"NOTELE DIRECTORULUI LA VERSIUNEA ANTERIOARĂ (rescrie ținând cont de ele):\n{notes}"
            if notes
            else ""
        ),
    )
    result = run_agent_task(
        engine,
        registry,
        showrunner_id,
        "write_episode",
        prompt,
        "v2",
        correlation,
        summary=f"Scriu episodul {episode_number} al serialului pentru ziua {date_iso}.",
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
                f"petrecut în {date_iso} sau nu pot fi povestite public. Nimic nu a fost salvat."
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
            {
                "log_id": log_id,
                "grounded_events": len(grounded),
                "episode_number": episode_number,
                "rewrite_of": rewrite_of,
            },
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
                "episode_number": episode_number,
                "summary": draft.summary.strip(),
                "threads_continued": draft.threads_continued,
                "threads_closed": draft.threads_closed,
                "threads_opened": draft.threads_opened,
                "recurring": draft.recurring,
            },
            status="DRAFT",
            written_by_agent_id=showrunner_id,
            created_at=utc_now(),
            event_id=event.event_id,
            notes=None,
            rewrite_of_id=rewrite_of,
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
        episode.reviewed_by = "owner"
        episode.event_id = append_event(
            session,
            "story.episode_approved" if approve else "story.episode_rejected",
            "story_episode",
            episode.id,
            2,
            {"log_id": episode.log_id, "reviewed_by": "owner"},
            correlation,
        ).event_id
        if approve:
            advance_continuity(session, episode, correlation)
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
    """Re-check a stored episode against its day, so the claim can be audited, not trusted.

    Checked against the projection: an id that is in the day's operational record but not
    in its public projection is a private event, and an episode citing one is not grounded
    in anything the audience may see.
    """
    with Session(engine) as session:
        episode = session.get(StoryEpisode, episode_id)
        if episode is None:
            raise StoryError("Episodul nu există")
        log = session.get(DailyStudioLog, episode.log_id)
        source = (
            log.narrative_projection_json
            if log is not None and log.narrative_projection_json is not None
            else (log.notable_events_json if log else [])
        )
        known = {item["event_id"] for item in source or []}
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
