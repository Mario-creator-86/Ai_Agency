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

**What is stored is the day's story, not its tail** (`select_story`, 2026-09-24). Measured
before it: the log kept the chronologically last 40 public events, so a long day handed the
showrunner the evening's "a stage of the day ended" lines and none of the morning's choices,
each a Romanian template with no title, reason or claim in it. The selection is computed —
no model decides what the day was about, for the reason the log is never narrated — and
the lines are English, the language the serial is written and published in.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DomainEvent
from app.story.models import DailyStudioLog

PUBLIC_SAFE = "PUBLIC_SAFE"
OWNER_PRIVATE = "OWNER_PRIVATE"

REDACTED = "[redacted]"

#: Event type -> (the fact in plain words, payload keys whose values may be mentioned).
#:
#: Read against `../architecture/07_STORY_ENGINE.md` "Daily close": hires and departures,
#: Director decisions, tasks, failures, retries, the main content produced, publication
#: events. Not here, on purpose: `agent.model_assigned` and everything under `provider.`,
#: `settings.`, `youtube.`, `economy.` and `research.` — models, credentials, money and
#: hosts are the studio's own business. A list value (a verdict's reasons) is offered by its
#: first item only: the reason the verdict was given, not the whole file behind it.
PUBLIC_SAFE_EVENTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "agent.hired": ("a new employee joined the studio", ("display_name", "role")),
    "agent.terminated": ("an employee left the studio", ("display_name", "role")),
    "agent.suspended": ("an employee was suspended", ("display_name",)),
    "agent.paused": ("an employee was put on pause", ("display_name",)),
    "agent.resumed": ("an employee came back to work", ("display_name",)),
    # An agent's report to the team is a fact about the day; its text is the agent's
    # working output and can quote anything, so only the task it reported on is offered.
    "agent.message_sent": ("an employee reported to the team", ("task_type",)),
    "agent.message_posted": ("a letter was sent", ("from_name", "to_name", "subject")),
    # No subject: the answer's event does not say whether the letter was the Owner's, and
    # an answered letter to him carried its subject here whole (read on 2026-09-24).
    "agent.message_answered": ("a letter was answered", ()),
    "factual.topic_proposed": ("a new topic was proposed", ("title",)),
    "factual.topic_selected": ("the topic of the day was chosen", ("title",)),
    "factual.topic_refused": ("a topic was turned down", ("title", "reasons")),
    "factual.claim_verified": ("a claim was checked against its source", ("status",)),
    "factual.claim_extracted": ("a claim was taken from the sources", ()),
    "factual.source_ingested": ("a source was read", ("publisher",)),
    "factual.script_approved": ("the script was approved", ("claims_count",)),
    "factual.script_verified_pass": ("the script passed the fact check", ()),
    "factual.script_blocked_by_gate": ("a script was stopped at the fact gate", ()),
    "factual.story_reviewed": ("the Director read the story", ("verdict", "failed")),
    "factual.hooks_generated": ("hooks were proposed for the script", ()),
    "media.storyboard_created": ("the storyboard was built", ("title", "scene_count")),
    "media.visual_bible_written": ("the Director wrote the film's visual bible", ()),
    "media.shot_prompts_written": ("the film's shots were described", ()),
    "media.video_rendered": ("the film was rendered", ()),
    "media.render_failed": ("a render failed", ()),
    "media.qc_evaluated": ("quality control gave its verdict", ("status",)),
    "media.editorial_reviewed": ("the Director watched the film", ("title", "verdict", "reasons")),
    "publishing.started": ("a publication started", ("title",)),
    "publishing.video_published": ("a film was published", ("title",)),
    "publishing.video_published_simulated": ("a film was published (simulation)", ("title",)),
    "publishing.failed": ("a publication failed", ()),
    "workforce.change_proposed": ("a staffing change was proposed", ()),
    "workforce.change_approved": ("a staffing change was approved", ()),
    "workforce.change_rejected": ("a staffing change was rejected", ()),
    "workforce.employment_started": ("an employee started work", ("display_name", "role")),
    "director.review_completed": ("the Director went through the mail", ("applied",)),
    "director.decision_recorded": ("the Director made a decision", ("decision",)),
    "runbook.stage_finished": ("a stage of the day ended", ("stage", "status")),
    "runbook.stage_retrying": ("a stage of the day was tried again", ("stage",)),
    "office.room_created": ("a new room appeared in the office", ("name",)),
}

#: How a payload key is named in the English line.
_LABELS = {
    "display_name": "name",
    "task_type": "task",
    "reasons": "reason",
    "failed": "reason",
    "claims_count": "claims",
    "scene_count": "scenes",
    "applied": "letters acted on",
}

#: Keys that, when present, mark a letter to or from the Owner. Such a letter is projected as
#: a fact ("Sarah wrote to the Owner") with no subject, excerpt or body.
_OWNER_MARKERS = ("for_owner", "owner_attention")

#: Payload keys that name the employee who acted, by id. Resolved through the day's roster
#: only, so what reaches the line is a cast name and never an id.
_ACTOR_KEYS = ("from_agent_id", "verified_by_agent_id", "agent_id", "proposed_by_agent_id")

#: The longest a quoted value may be; a longer one is cut, not dropped, so a reason keeps
#: its first clause.
_VALUE_CHARS = 160

# --- redaction -------------------------------------------------------------------------

#: A key or token: a vendor-prefixed key («sk-…», «xi_…»), a label given a value («password:
#: …», «token abc123…»), or a bearer header; a long opaque run is `_OPAQUE`'s. The label is a
#: whole word now: until 2026-10-11 «key» glued to any six letters matched, and episode 1 of
#: the serial («One View Morning») was refused for «one hand already on the keyboard.».
_SECRET = re.compile(
    r"(?i)\b(?:sk|xi|rk|pk)[-_][A-Za-z0-9_\-]{6,}"
    r"|\b(?:key|token|secret|api[_-]?key|password|parol[aă])\s*[=:]\s*\S{6,}"
    r"|\b(?:key|token|secret|api[_-]?key|password|parol[aă])\s+(?=[\w\-./+]*\d)[\w\-./+]{6,}"
    r"|\bbearer\s+[A-Za-z0-9_\-./+]{6,}"
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
#: Model families whose ids the two patterns around this one miss, measured on 2026-09-24
#: against the studio's own records: "seedream5_pro" and "seedance2_5" (a version glued with
#: an underscore has no word boundary for `_PROVIDER` or `_MODEL_SHAPE` to stop at), and
#: "kimi-k3" or "minimax-m3" (the shape matched the version and left the family name). A
#: letter's subject "Model research (image): seedream5_pro" reached the projection whole.
#: No trailing boundary, on purpose: the family name is the leak, whatever follows it.
_MODEL_FAMILY = re.compile(
    r"(?i)\b(?:seedream|seedance|kimi|minimax|gemma|nemotron|deepseek|qwen|bytedance|"
    r"byteplus|hailuo|moonshot|zhipu)[\w.:-]*"
)
_MODEL_SHAPE = re.compile(r"\b[a-z][a-z_]*[-_:]?\d+(?:[.:-][a-z0-9]+)*\b")
#: A card or account number: four or more digits in a row inside a longer digit run. A year
#: (19xx, 20xx) standing alone is not one: "Ziua povestită: 2026-09-19" reached the writer
#: as "[redacted]-09-19", and a line naming a year failed the review's privacy check
#: (rehearsal on a copy of his data, 2026-09-24).
_CARD = re.compile(r"\b(?!(?:19|20)\d\d\b)\d{4,}\b")

_PATTERNS = (
    _SECRET,
    _URL,
    _EMAIL,
    _DOMAIN,
    _MONEY,
    _MONEY_FIRST,
    _PROVIDER,
    _MODEL_FAMILY,
    _MODEL_SHAPE,
    _OPAQUE,
    _OPAQUE_UPPER,
    _HEX,
    _CARD,
)


@lru_cache(maxsize=8)
def _names_pattern(names: tuple[str, ...]) -> re.Pattern[str] | None:
    """One pattern for the exact model names the studio has on record, longest first."""
    if not names:
        return None
    alternatives = "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
    return re.compile(rf"(?i)(?<![\w.-])(?:{alternatives})(?![\w])")


def redact(text: str, private_names: Iterable[str] = ()) -> str:
    """Replace anything that looks like a secret, a provider or model id, a price, a URL, an
    address or an account number, and any of ``private_names`` (the models the studio has on
    record, whatever their shape). Over-redaction is the accepted cost: a title that loses
    a word is a smaller loss than a key that reaches a channel."""
    cleaned = str(text or "")
    names = _names_pattern(tuple(sorted({n for n in private_names if len(n) >= 3})))
    if names is not None:
        cleaned = names.sub(REDACTED, cleaned)
    for pattern in _PATTERNS:
        cleaned = pattern.sub(REDACTED, cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def leaks(text: str) -> bool:
    """Whether the redaction pass would change this text — the review's privacy check."""
    return redact(text) != re.sub(r"\s+", " ", str(text or "")).strip()


def private_model_names(session: Session) -> set[str]:
    """Every model name the studio has on record, and its stem before a tag.

    The patterns above know families by name and ids by shape; a model the studio discovered
    tomorrow under a plain word ("novamind") has neither, and it is still the studio's own
    business which model did the work. Read from `model_record` (the language models) and
    `model_outcome` (the media models it generated with: "seedance2_mini" on 2026-09-24).
    """
    from app.agents.models import ModelRecord  # noqa: PLC0415
    from app.integrations.models import ModelOutcome  # noqa: PLC0415

    names: set[str] = set()
    found = list(session.scalars(select(ModelRecord.model_name)))
    found += list(session.scalars(select(ModelOutcome.remote_id).distinct()))
    for name in found:
        name = str(name or "").strip()
        if name:
            names.add(name)
            names.add(name.split(":")[0])
    return {name for name in names if len(name) >= 3}


# --- classification ----------------------------------------------------------------------


def classify_event_type(event_type: str) -> str:
    """PUBLIC_SAFE for a type in the table, OWNER_PRIVATE for everything else."""
    return PUBLIC_SAFE if event_type in PUBLIC_SAFE_EVENTS else OWNER_PRIVATE


#: The subject `app.agents.director.file_stage_reports` gives the letter each stage's owner
#: posts to the Director's desk at the end of a run: "<stage>: <STATUS> — <reason>".
_STAGE_REPORT_SUBJECT = re.compile(r"^[a-z][a-z0-9_]*: [A-Z_]+ — ")
#: The Director's desk: a letter with no addressee is posted to her inbox under this name.
_DESK = "Director"


def is_stage_report(event_type: str, payload: dict[str, Any]) -> bool:
    """Whether an event is one of the run's own end-of-run reports.

    The same facts as the stages ending (`runbook.stage_finished`, routine), written as a
    letter. Rehearsal on a copy of his data (2026-09-24): as letters they weighed 8, so the
    fifteen lines of a day were fifteen reports, and the episode filmed and published that
    morning was not among them. A stage that failed is still story, by its own event.
    """
    if event_type != "agent.message_posted" or payload.get("to_agent_id"):
        return False
    return str(payload.get("intent") or "") == "STATUS" and bool(
        _STAGE_REPORT_SUBJECT.match(str(payload.get("subject") or ""))
    )


def _is_owner_letter(payload: dict[str, Any]) -> bool:
    if any(payload.get(marker) for marker in _OWNER_MARKERS):
        return True
    return any(
        str(payload.get(key) or "").strip().lower() == "owner" for key in ("from_name", "to_name")
    )


def _value(value: Any) -> str:
    """One safe value as text: a list by its first item, cut at `_VALUE_CHARS`."""
    if isinstance(value, list):
        value = next((item for item in value if isinstance(item, (str, int, float))), None)
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return ""
    text = " ".join(str(value).split())
    return text if len(text) <= _VALUE_CHARS else text[: _VALUE_CHARS - 1].rstrip() + "…"


def _story_keys(
    event_type: str, payload: dict[str, Any], claim_text: str | None, private: Iterable[str]
) -> dict[str, str]:
    """The substance of one public event, each value redacted: title, reason, verdict, claim.

    ``claim_text`` is the text of a claim the verification REFUTED — the one claim text a
    public line carries, because a refuted claim is what the day's fact check was for.
    """
    safe_keys = PUBLIC_SAFE_EVENTS[event_type][1]
    keys: dict[str, str] = {}
    if "title" in safe_keys and (title := _value(payload.get("title"))):
        keys["title"] = redact(title, private)
    for key in ("reasons", "failed"):
        if key in safe_keys and (reason := _value(payload.get(key))):
            keys["reason"] = redact(reason, private)
            break
    verdict = _value(payload.get("verdict") or payload.get("status")).upper()
    if verdict and ("verdict" in safe_keys or "status" in safe_keys):
        keys["verdict"] = redact(verdict, private)
    if claim_text and verdict == "REFUTED":
        keys["claim"] = redact(_value(claim_text), private)
    return keys


def describe_public(
    event_type: str,
    payload: dict[str, Any],
    claim_text: str | None = None,
    private_names: Iterable[str] = (),
    director: str | None = None,
) -> str | None:
    """The public sentence for one event, in English, or None when the type is private.

    ``director`` is the name of the day's Director (her roster entry): a letter to her desk
    is to her, and one she posts there herself is a note, not a letter to a second person.
    """
    entry = PUBLIC_SAFE_EVENTS.get(event_type)
    if entry is None:
        return None
    phrase, safe_keys = entry
    if event_type.startswith("agent.message_") and _is_owner_letter(payload):
        # The fact that the Owner and an employee exchanged a letter is the studio's day;
        # what it said is the Owner's.
        if str(payload.get("to_name") or "").strip().lower() == "owner":
            writer = str(payload.get("from_name") or "someone")
            return redact(f"{writer} wrote to the Owner", private_names)
        return redact(f"the Owner wrote to {payload.get('to_name') or 'someone'}", private_names)
    if event_type == "agent.message_posted":
        sender, to = _value(payload.get("from_name")), _value(payload.get("to_name"))
        subject = _value(payload.get("subject"))
        if director and to == _DESK and not payload.get("to_agent_id"):
            to = director
        if sender and to == sender:
            line = f"{sender} noted" + (f': "{subject}"' if subject else "")
            return redact(line, private_names)
        if sender and to:
            line = f"{sender} wrote to {to}" + (f': "{subject}"' if subject else "")
            return redact(line, private_names)
    if event_type == "factual.claim_verified" and claim_text:
        if _value(payload.get("status")).upper() == "REFUTED":
            return redact(
                f'a claim was refuted by its source: "{_value(claim_text)}"', private_names
            )
    details = []
    for key in safe_keys:
        text = _value(payload.get(key))
        if text:
            label = _LABELS.get(key, key)
            details.append(
                f'{label} "{text}"' if key in ("title", "subject") else f"{label}: {text}"
            )
    sentence = phrase + (f" ({'; '.join(details)})" if details else "")
    return redact(sentence, private_names)


def _actor(
    event: DomainEvent, payload: dict[str, Any], names: dict[str, str], cast: set[str]
) -> str | None:
    """Who acted, as a name on the day's roster, or None. Never an id."""
    if event.aggregate_type == "agent" and event.aggregate_id in names:
        return names[event.aggregate_id]
    for key in _ACTOR_KEYS:
        if (name := names.get(str(payload.get(key) or ""))) is not None:
            return name
    sender = str(payload.get("from_name") or "")
    return sender if sender in cast else None


def project_events(
    events: list[DomainEvent],
    roster: list[dict[str, Any]],
    claims: dict[str, str] | None = None,
    private_names: Iterable[str] = (),
) -> list[dict]:
    """The PUBLIC_SAFE projection of a list of events, in stream order, every one of them.

    ``claims`` maps a claim id to its text, for the claims the day REFUTED; ``private_names``
    are the studio's model names (`private_model_names`). `select_story` is what trims this
    to what the showrunner reads.
    """
    names = {
        str(member.get("agent_id")): str(member.get("display_name") or "")
        for member in roster
        if member.get("agent_id")
    }
    cast = set(names.values())
    director = next(
        (
            str(member.get("display_name"))
            for member in roster
            if str(member.get("role_name") or "") == _DESK and member.get("display_name")
        ),
        None,
    )
    private = tuple(private_names)
    projection: list[dict] = []
    for event in events:
        payload = event.payload if isinstance(event.payload, dict) else {}
        claim_text = (claims or {}).get(event.aggregate_id)
        description = describe_public(event.event_type, payload, claim_text, private, director)
        if description is None:
            continue
        actor = _actor(event, payload, names, cast)
        prefix = f"{actor}: " if actor and not description.startswith(actor) else ""
        projection.append(
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "at": event.timestamp,
                "actor": actor,
                "classification": PUBLIC_SAFE,
                "description": prefix + description,
                **_story_keys(event.event_type, payload, claim_text, private),
                **({"routine": True} if is_stage_report(event.event_type, payload) else {}),
            }
        )
    return projection


def refuted_claims(session: Session, events: list[DomainEvent]) -> dict[str, str]:
    """claim id -> claim text, for the claims the events REFUTED."""
    from app.factual.models import FactualClaim  # noqa: PLC0415

    ids = [
        event.aggregate_id
        for event in events
        if event.event_type == "factual.claim_verified"
        and isinstance(event.payload, dict)
        and str(event.payload.get("status") or "").upper() == "REFUTED"
    ]
    if not ids:
        return {}
    rows = session.execute(
        select(FactualClaim.id, FactualClaim.claim_text).where(FactualClaim.id.in_(ids))
    )
    return {claim_id: text for claim_id, text in rows}


def project_day(
    session: Session, events: list[DomainEvent], roster: list[dict[str, Any]]
) -> list[dict]:
    """`project_events` with what only the database knows: refuted claims, model names."""
    return project_events(
        events, roster, refuted_claims(session, events), private_model_names(session)
    )


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
    return project_day(session, events, list(log.roster_json or []))


# --- the day's story -----------------------------------------------------------------------

#: The most lines the showrunner is handed, and the fewest a day with any story is filled to.
MAX_STORY_EVENTS = 15
MIN_STORY_EVENTS = 8

#: Narrative weight by event type: what a viewer would call the day's story ranks first.
#: The choices and refusals, the gates that stopped work, the people who came and went and
#: the letters between them are the drama; the machinery that ran as planned is not.
STORY_WEIGHTS: dict[str, int] = {
    "factual.topic_selected": 10,
    "agent.hired": 10,
    "agent.terminated": 10,
    "factual.topic_refused": 9,
    "factual.script_blocked_by_gate": 9,
    "media.render_failed": 9,
    "workforce.employment_started": 9,
    "agent.message_posted": 8,
    "publishing.failed": 8,
    "publishing.video_published": 8,
    "agent.suspended": 7,
    "publishing.video_published_simulated": 7,
    "agent.paused": 6,
    "agent.resumed": 6,
    "director.decision_recorded": 6,
    "factual.script_approved": 6,
    "media.video_rendered": 6,
    "workforce.change_proposed": 6,
    "workforce.change_approved": 6,
    "workforce.change_rejected": 6,
    "factual.script_verified_pass": 5,
    "factual.story_reviewed": 5,
    "media.editorial_reviewed": 5,
    "office.room_created": 5,
    "factual.topic_proposed": 4,
    "media.qc_evaluated": 4,
    "media.storyboard_created": 4,
    "director.review_completed": 3,
    "factual.claim_verified": 3,
    "media.visual_bible_written": 3,
    "runbook.stage_retrying": 3,
    "agent.message_sent": 2,
    "factual.hooks_generated": 2,
    "media.shot_prompts_written": 2,
    "publishing.started": 2,
}
#: Routine: kept out of the story, and used only to fill a short day up to the minimum.
#: Measured on a 2026-09-12 day of 993 events: 900 of them were stages ending as planned.
ROUTINE_EVENTS = frozenset(
    {
        "runbook.stage_finished",
        "agent.message_answered",
        "factual.claim_extracted",
        "factual.source_ingested",
    }
)
#: A verdict or status that turns any event into story: something was refused or broke.
_TROUBLE = frozenset(
    {"FAIL", "FAILED", "REJECT", "REJECTED", "REFUTED", "REVISE", "BLOCKED", "HOLD", "ITERATE"}
)
_TROUBLE_WEIGHT = 9
_ROUTINE_WEIGHT = 1


def story_weight(event_type: str, verdict: str | None = None) -> int:
    """How much one event weighs in the day's story; 1 is routine."""
    if str(verdict or "").upper() in _TROUBLE:
        return max(STORY_WEIGHTS.get(event_type, 3), _TROUBLE_WEIGHT)
    if event_type in ROUTINE_EVENTS:
        return _ROUTINE_WEIGHT
    return STORY_WEIGHTS.get(event_type, 3)


def select_story(projection: list[dict]) -> list[dict]:
    """The day's story out of its full projection, deterministic, in the order it happened.

    Repeats collapse into their first occurrence, which says how many there were; the rest
    is ranked by `story_weight` (earlier first on a tie) and cut at `MAX_STORY_EVENTS`. A day
    with fewer story lines than `MIN_STORY_EVENTS` is filled with its routine up to the
    minimum, so the writer sees the day's texture; a day with no story line at all is a
    quiet day and projects to nothing — the serial then tells the newest day that had one,
    rather than dramatise stages that ended as planned.
    """
    firsts: dict[tuple[str, str], dict] = {}
    counts: dict[tuple[str, str], int] = {}
    for item in projection:
        key = (str(item["event_type"]), str(item["description"]))
        counts[key] = counts.get(key, 0) + 1
        firsts.setdefault(key, item)
    collapsed: list[tuple[int, int, dict]] = []
    for index, (key, first) in enumerate(firsts.items()):
        item = dict(first)
        if counts[key] > 1:
            item["repeats"] = counts[key]
            item["description"] = f"{item['description']} ({counts[key]} times that day)"
        weight = (
            _ROUTINE_WEIGHT
            if item.get("routine")
            else story_weight(item["event_type"], item.get("verdict"))
        )
        collapsed.append((weight, index, item))
    story = sorted((c for c in collapsed if c[0] > _ROUTINE_WEIGHT), key=lambda c: (-c[0], c[1]))
    if not story:
        return []
    kept = story[:MAX_STORY_EVENTS]
    if len(kept) < MIN_STORY_EVENTS:
        routine = [c for c in collapsed if c[0] <= _ROUTINE_WEIGHT]
        kept += routine[: MIN_STORY_EVENTS - len(kept)]
    return [item for _, _, item in sorted(kept, key=lambda c: c[1])]


def left_out(event_counts: dict[str, int], projection: list[dict]) -> int:
    """How many public events of the day the projection does not show, repeats counted."""
    public = sum(int(n) for t, n in (event_counts or {}).items() if t in PUBLIC_SAFE_EVENTS)
    shown = sum(int(item.get("repeats", 1)) for item in projection)
    return max(0, public - shown)
