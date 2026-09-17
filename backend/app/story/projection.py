"""The narrative projection: what a day looks like from the outside.

`../architecture/07_STORY_ENGINE.md` asks for a `NarrativeProjection` before the showrunner
sees anything, and §54 of the master prompt lists what may never be turned into comedy:
secrets, credentials, stack traces, private Owner messages, security details. Measured on
the live database before this module existed: every `domain_event` carried visibility OWNER
and the day's notable events were described as raw ``key=value`` payload pairs — a model id,
the full text of an agent's message, a dollar figure — offered to the showrunner as they were.

Two mechanisms, both deliberately dumb:

- **A table of event types, private by default.** An event type that is not in
  `PUBLIC_SAFE_EVENTS` is OWNER_PRIVATE, whatever it contains. A public type names the payload
  keys that may be mentioned and a plain phrase for the fact; everything else in the payload
  is never read. "The Director sent the script back" is a fact; the budget figure behind
  the decision is not offered, because no key carries it here.
- **A redaction pass over every description.** Even a safe key can carry an unsafe value (a
  film title with a model name in it), so anything that looks like a key or token, a
  provider or model identifier, a price, a URL or an address is replaced before the text is
  stored. The Owner's words are the strongest case: a letter to or from the Owner is
  projected as the fact that it was written, never as its subject or excerpt.

The projection is derived from committed events and stored on the closed log. It is the
only thing `write_episode` reads, so the check that keeps an episode grounded is also the
check that keeps it public: a beat can only cite what the projection contains.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DomainEvent
from app.story.models import DailyStudioLog

PUBLIC_SAFE = "PUBLIC_SAFE"
OWNER_PRIVATE = "OWNER_PRIVATE"

REDACTED = "[redactat]"

#: Event type -> (the fact in plain words, payload keys whose values may be mentioned).
#:
#: Read against `../architecture/07_STORY_ENGINE.md` "Daily close": hires and departures,
#: Director decisions, tasks, failures, retries, the main content produced, publication
#: events. Not here, on purpose: `agent.model_assigned` and everything under `provider.`,
#: `settings.`, `youtube.`, `economy.` and `research.` — models, credentials, money and
#: hosts are the studio's own business.
PUBLIC_SAFE_EVENTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "agent.hired": ("un angajat nou a intrat în studio", ("display_name", "role")),
    "agent.terminated": ("un angajat a plecat din studio", ("display_name", "role")),
    "agent.suspended": ("un angajat a fost suspendat", ("display_name",)),
    "agent.paused": ("un angajat a fost pus în pauză", ("display_name",)),
    "agent.resumed": ("un angajat s-a întors la lucru", ("display_name",)),
    # An agent's report to the team is a fact about the day; its text is the agent's
    # working output and can quote anything, so only the task it reported on is offered.
    "agent.message_sent": ("un angajat a raportat echipei", ("task_type",)),
    "agent.message_posted": ("o scrisoare a fost trimisă", ("from_name", "to_name", "subject")),
    "agent.message_answered": ("o scrisoare a primit răspuns", ("subject",)),
    "factual.topic_proposed": ("o temă nouă a fost propusă", ("title",)),
    "factual.topic_selected": ("tema zilei a fost aleasă", ("title",)),
    "factual.topic_refused": ("o temă a fost refuzată", ("title",)),
    "factual.claim_verified": ("o afirmație a fost verificată", ("status",)),
    "factual.claim_extracted": ("o afirmație a fost extrasă din surse", ()),
    "factual.source_ingested": ("o sursă a fost citită", ("publisher",)),
    "factual.script_approved": ("scenariul a fost aprobat", ("claims_count",)),
    "factual.script_verified_pass": ("scenariul a trecut verificarea faptelor", ()),
    "factual.script_blocked_by_gate": ("un scenariu a fost oprit la poarta faptelor", ()),
    "factual.story_reviewed": ("Directorul a citit povestea", ("verdict",)),
    "factual.hooks_generated": ("au fost propuse cârlige pentru scenariu", ()),
    "media.storyboard_created": ("storyboard-ul a fost construit", ("title", "scene_count")),
    "media.visual_bible_written": ("Directorul a scris biblia vizuală a filmului", ()),
    "media.shot_prompts_written": ("cadrele filmului au fost descrise", ()),
    "media.video_rendered": ("filmul a fost randat", ()),
    "media.render_failed": ("o randare a eșuat", ()),
    "media.qc_evaluated": ("controlul de calitate a dat verdictul", ("status",)),
    "media.editorial_reviewed": ("Directorul a vizionat filmul", ("title", "verdict")),
    "publishing.started": ("o publicare a început", ("title",)),
    "publishing.video_published": ("un film a fost publicat", ("title",)),
    "publishing.video_published_simulated": ("un film a fost publicat (simulare)", ("title",)),
    "publishing.failed": ("o publicare a eșuat", ()),
    "workforce.change_proposed": ("o schimbare de personal a fost propusă", ()),
    "workforce.change_approved": ("o schimbare de personal a fost aprobată", ()),
    "workforce.change_rejected": ("o schimbare de personal a fost respinsă", ()),
    "workforce.employment_started": ("un angajat a început lucrul", ("display_name", "role")),
    "director.review_completed": ("Directorul și-a citit corespondența", ("applied",)),
    "director.decision_recorded": ("Directorul a luat o decizie", ("decision",)),
    "runbook.stage_finished": ("o etapă a zilei s-a încheiat", ("stage", "status")),
    "runbook.stage_retrying": ("o etapă a zilei este reluată", ("stage",)),
    "office.room_created": ("o cameră nouă a apărut în birou", ("name",)),
}

#: Keys that, when present, mark a letter to or from the Owner. Such a letter is projected as
#: a fact ("Sarah wrote to the Owner") with no subject, excerpt or body.
_OWNER_MARKERS = ("for_owner", "owner_attention")

# --- redaction -------------------------------------------------------------------------

#: A key or token: a labelled secret, or a long opaque run of letters and digits.
_SECRET = re.compile(
    r"(?i)\b(?:sk|xi|rk|key|token|secret|bearer|api[_-]?key|password|parol[aă])"
    r"[\s=:_-]*[A-Za-z0-9_\-./+]{6,}"
)
_OPAQUE = re.compile(r"\b(?=[A-Za-z0-9_\-]*\d)(?=[A-Za-z0-9_\-]*[A-Za-z])[A-Za-z0-9_\-]{24,}\b")
_HEX = re.compile(r"\b[0-9a-fA-F]{24,}\b")
#: An uppercase key id: an access key of the AWS shape is twenty capitals and digits, which
#: `_OPAQUE` (twenty-four characters) let through whole.
_OPAQUE_UPPER = re.compile(r"\b(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{16,}\b")
_URL = re.compile(r"(?i)\b(?:https?://|www\.)\S+")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_MONEY = re.compile(
    r"(?i)(?:[$€£]\s?\d[\d.,]*|\b\d[\d.,]*\s?(?:usd|eur|ron|lei|dollars?|cents?|credits?)\b)"
)
#: A price written currency-first ("USD 12.50"), which `_MONEY` reads only amount-first.
#: Measured in a topic title: it reached the projection whole.
_MONEY_FIRST = re.compile(r"(?i)\b(?:usd|eur|ron|gbp|lei)\s?\d[\d.,]*")
#: A link without its scheme: two or more labels ending in a public suffix, with or without
#: a path. `_URL` asks for "http" or "www.", and "youtu.be/<id>" has neither.
_DOMAIN = re.compile(
    r"(?i)\b(?:[a-z0-9-]+\.)+"
    r"(?:com|net|org|io|ai|be|ro|dev|app|co|tv|me|gg|cloud|xyz|info|eu|uk|us)\b"
    r"(?:/[^\s)\]]*)?"
)
#: Provider names and the model ids they publish. The names are the ones the studio has
#: integrated or evaluated; the shape ("glm-5.3", "gpt-4o", "qwen3.5:7b",
#: "eleven_multilingual_v2") is a lowercase word glued to a version.
_PROVIDER = re.compile(
    r"(?i)\b(?:openai|anthropic|claude|gpt|ollama|elevenlabs|eleven_[a-z0-9_]+|runway|"
    r"gemini|qwen|glm|llama|mistral|deepseek|kling|luma|pika|sora|whisper|deepgram|"
    r"bedrock|vertex|groq|openrouter|together)\b[\w.:-]*"
)
_MODEL_SHAPE = re.compile(r"\b[a-z][a-z_]*[-_:]?\d+(?:[.:-][a-z0-9]+)*\b")
#: A card or account number: four or more digits in a row inside a longer digit run.
_CARD = re.compile(r"\b\d{4,}\b")

_PATTERNS = (
    _SECRET,
    _URL,
    _EMAIL,
    _DOMAIN,
    _MONEY,
    _MONEY_FIRST,
    _PROVIDER,
    _MODEL_SHAPE,
    _OPAQUE,
    _OPAQUE_UPPER,
    _HEX,
    _CARD,
)


def redact(text: str) -> str:
    """Replace anything that looks like a secret, a provider or model id, a price, a URL, an
    address or an account number. Over-redaction is the accepted cost: a title that loses
    a word is a smaller loss than a key that reaches a channel."""
    cleaned = str(text or "")
    for pattern in _PATTERNS:
        cleaned = pattern.sub(REDACTED, cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def leaks(text: str) -> bool:
    """Whether the redaction pass would change this text — the review's privacy check."""
    return redact(text) != re.sub(r"\s+", " ", str(text or "")).strip()


# --- classification ----------------------------------------------------------------------


def classify_event_type(event_type: str) -> str:
    """PUBLIC_SAFE for a type in the table, OWNER_PRIVATE for everything else."""
    return PUBLIC_SAFE if event_type in PUBLIC_SAFE_EVENTS else OWNER_PRIVATE


def _is_owner_letter(payload: dict[str, Any]) -> bool:
    if any(payload.get(marker) for marker in _OWNER_MARKERS):
        return True
    return any(
        str(payload.get(key) or "").strip().lower() == "owner" for key in ("from_name", "to_name")
    )


def describe_public(event_type: str, payload: dict[str, Any]) -> str | None:
    """The public sentence for one event, or None when the type is private."""
    entry = PUBLIC_SAFE_EVENTS.get(event_type)
    if entry is None:
        return None
    phrase, safe_keys = entry
    if event_type.startswith("agent.message_") and _is_owner_letter(payload):
        # The fact that the Owner and an employee exchanged a letter is the studio's day;
        # what it said is the Owner's.
        who = str(payload.get("from_name") or payload.get("to_name") or "cineva")
        other = "Owner" if str(payload.get("to_name") or "").lower() == "owner" else who
        writer = who if other == "Owner" else "Owner"
        return redact(f"{writer} i-a scris lui {other}")
    details = []
    for key in safe_keys:
        value = payload.get(key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            text = str(value).strip()
            if text and len(text) <= 160:
                details.append(f"{key}: {text}")
    sentence = phrase + (f" ({'; '.join(details)})" if details else "")
    return redact(sentence)


def project_events(events: list[DomainEvent], roster: list[dict[str, Any]]) -> list[dict]:
    """The PUBLIC_SAFE projection of a list of events, in stream order."""
    names = {
        str(member.get("agent_id")): str(member.get("display_name") or "")
        for member in roster
        if member.get("agent_id")
    }
    projection: list[dict] = []
    for event in events:
        payload = event.payload if isinstance(event.payload, dict) else {}
        description = describe_public(event.event_type, payload)
        if description is None:
            continue
        actor = names.get(event.aggregate_id) if event.aggregate_type == "agent" else None
        projection.append(
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "at": event.timestamp,
                "actor": actor,
                "classification": PUBLIC_SAFE,
                "description": (f"{actor}: " if actor else "") + description,
            }
        )
    return projection


def project_log_for_story(session: Session, log: DailyStudioLog) -> list[dict]:
    """The sanitised, narratable events of one closed day, read from the committed stream.

    Reads the events again rather than the log's `notable_events_json`: those descriptions
    are the raw operational record, and the whole point is that the showrunner's material is
    derived from the events by the table above and nothing else.
    """
    from app.story.services import _day_bounds  # noqa: PLC0415 - the log's own window

    start, end = _day_bounds(log.business_date, log.timezone)
    events = list(
        session.scalars(
            select(DomainEvent)
            .where(DomainEvent.timestamp >= start, DomainEvent.timestamp < end)
            .order_by(DomainEvent.sequence)
        )
    )
    return project_events(events, list(log.roster_json or []))
