"""The Director reads the episode before it is filmed.

Measured before this module: an episode stopped at DRAFT and waited for the Owner's hand;
nothing read it for the things a reader can measure, and nothing consumed an APPROVED one.
This is the gate between the showrunner and the camera, in the shape `editorial_review`
already has for films:

- **The checks are computed first**, without a model, because they are not matters of taste.
  Grounding (every cited id is in the day's record — reusing the rule `write_episode`
  enforces); privacy (no cited id outside the PUBLIC_SAFE projection, and nothing in the
  text the redaction pass would change); length (at most `MAX_BEATS` beats and 45-70 seconds
  of dialogue at the studio's own 2.5 words a second); cast (every active roster member
  appears — the serial is about the studio, not about one of its desks); and new-viewer
  accessibility (the first beat names who is in the room and does not begin mid-thought).
  Any failure is the verdict, with its reasons, and the Director is not asked.
- **Then the Director's verdict**, through `run_agent_task` with the episode as data. Her
  notes go back to the showrunner for the one rewrite the stage allows.

A PASS approves the episode only under the channel's policy: `director_may_approve_episodes`
in the OFFICE_SERIAL channel's `series_rules_json`, False unless the Owner's publish-policy
command set it. Without it the episode stays DRAFT with the review on it, for the Owner's
`decide_episode`. A FAIL is REJECTED at once; the rewrite is a new draft.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.identity import clipped, parse_structured
from app.agents.language import audience_language_line
from app.agents.memory import agent_for_role, remember
from app.agents.messages import post_message
from app.agents.services import run_agent_task
from app.factual.sanitizer import wrap_in_inert_boundary
from app.providers.registry import ProviderRegistry
from app.publishing.models import ChannelRecord
from app.services import append_event, utc_now
from app.story.models import DailyStudioLog, StoryEpisode
from app.story.projection import leaks
from app.story.services import (
    MAX_BEATS,
    PREFERRED_SHOWRUNNER_ROLE,
    advance_continuity,
    ensure_projection,
)

logger = logging.getLogger("studio.story.review")

REVIEW_TASK = "episode_review"
TEMPLATE_VERSION = "episode-review-v1"
REVIEWER_ROLE = "Director"
#: The studio's speaking rate, the same figure the storyboard uses to time a scene.
WORDS_PER_SECOND = 2.5
MIN_SECONDS = 45.0
MAX_SECONDS = 70.0
#: The channel policy flag the Owner's publish-policy command sets. Read, never written, here.
POLICY_FLAG = "director_may_approve_episodes"
#: Openings that assume the viewer saw yesterday. A first beat that starts with one of these
#: does not stand alone.
CONTINUATION_MARKERS = (
    "ca ieri",
    "din nou",
    "cum spuneam",
    "cum ziceam",
    "tot despre",
    "as we said",
    "as i said",
    "after yesterday",
    "like yesterday",
    "again,",
    "still,",
    "as before",
    "continuing",
    "back to",
)


class ReviewError(ValueError):
    """The episode could not be reviewed; nothing was decided."""


class EpisodeVerdict(BaseModel):
    model_config = ConfigDict(extra="ignore")
    verdict: str = Field(pattern="^(PASS|FAIL)$")
    reasons: list[str] = Field(default_factory=list, max_length=8)
    #: For the showrunner: what to change in the rewrite.
    notes: str = Field(default="", max_length=1200)
    #: One sentence: what the viewer follows.
    story: str = Field(default="", max_length=400)
    _clip_notes = field_validator("notes", mode="before")(clipped(1200))
    _clip_story = field_validator("story", mode="before")(clipped(400))
    _one_reason = field_validator("reasons", mode="before")(
        lambda value: [value] if isinstance(value, str) else value
    )


_INSTRUCTIONS = (
    "You are the Director, and this is the last read of an episode of the studio's own "
    "serial before it is filmed. Below is the episode as data: its beats (scene, dialogue, "
    "who is in it), the day's cast, what the computed checks measured, and the serial's "
    "memory (previous summaries, open threads). Every check passed; you judge what checks "
    "cannot. Judge it as a viewer: does the first beat stand alone for someone who has "
    "never seen the serial; is there one clear situation with a turn and a payoff; does "
    "each character sound like themselves and like a person, not a status report; is the "
    "humour in the situation rather than in explaining the studio; does it continue or "
    "close the threads it claims to. A dramatisation is not a factual film: it makes no "
    "claims about the world and needs no sources, and you do not reject it for that. Return "
    'only JSON: {"verdict": "PASS" | "FAIL", "reasons": ["..."], "notes": "what the '
    'showrunner must change, if FAIL", "story": "one sentence: what the viewer follows"}.\n'
)


def director_may_approve_episodes(session: Session) -> bool:
    """Whether the Owner's policy lets the Director approve an episode on her own.

    False unless the OFFICE_SERIAL channel's `series_rules_json` says so. The flag is set only
    by the Owner's publish-policy command; nothing here writes it.
    """
    channel = session.scalar(
        select(ChannelRecord).where(ChannelRecord.channel_type == "OFFICE_SERIAL")
    )
    if channel is None:
        return False
    rules = channel.series_rules_json if isinstance(channel.series_rules_json, dict) else {}
    return rules.get(POLICY_FLAG) is True


def _words(text: Any) -> int:
    return len(str(text or "").split())


def episode_checks(session: Session, episode: StoryEpisode) -> dict[str, dict[str, Any]]:
    """The verdicts that need no model, each with what it measured."""
    log = session.get(DailyStudioLog, episode.log_id)
    if log is None:
        raise ReviewError("Jurnalul episodului nu există")
    projection = {item["event_id"] for item in ensure_projection(session, log)}
    recorded = {item["event_id"] for item in (log.notable_events_json or [])} | projection
    beats = list(episode.beats_json or [])
    cited = list(episode.grounded_event_ids_json or [])

    missing = [eid for eid in cited if eid not in recorded]
    private = [eid for eid in cited if eid in recorded and eid not in projection]
    leaking = [
        beat.get("beat_number")
        for beat in beats
        if leaks(str(beat.get("scene") or "")) or leaks(str(beat.get("dialogue") or ""))
    ]
    if leaks(episode.title):
        leaking.insert(0, 0)

    words = sum(_words(beat.get("dialogue")) for beat in beats)
    seconds = round(words / WORDS_PER_SECOND, 1)

    roster = [
        str(m.get("display_name"))
        for m in (log.roster_json or [])
        if m.get("lifecycle") == "ACTIVE"
    ]
    cast = {str(name) for beat in beats for name in (beat.get("characters") or [])}
    absent = [name for name in roster if name not in cast]

    first = beats[0] if beats else {}
    opening = " ".join(str(first.get("dialogue") or "").lower().split())[:80]
    starts_mid_thought = any(opening.startswith(marker) for marker in CONTINUATION_MARKERS)
    first_names = list(first.get("characters") or [])
    first_scene_words = _words(first.get("scene"))

    return {
        "grounding": {
            "passed": not missing,
            "cited": len(cited),
            "missing": missing,
            "reason": (
                f"{len(missing)} evenimente citate nu sunt în jurnalul zilei" if missing else ""
            ),
        },
        "privacy": {
            "passed": not private and not leaking,
            "private_citations": private,
            "leaking_beats": leaking,
            "reason": "; ".join(
                part
                for part in (
                    f"{len(private)} evenimente citate nu sunt publice" if private else "",
                    f"beat-urile {leaking} conțin ceva ce nu poate fi public" if leaking else "",
                )
                if part
            ),
        },
        "length": {
            "passed": 0 < len(beats) <= MAX_BEATS and MIN_SECONDS <= seconds <= MAX_SECONDS,
            "beats": len(beats),
            "words": words,
            "seconds": seconds,
            "reason": (
                ""
                if 0 < len(beats) <= MAX_BEATS and MIN_SECONDS <= seconds <= MAX_SECONDS
                else (
                    f"{len(beats)} beat-uri și {seconds:.0f} secunde de dialog; "
                    f"ținta este cel mult {MAX_BEATS} beat-uri și "
                    f"{MIN_SECONDS:.0f}-{MAX_SECONDS:.0f} secunde"
                )
            ),
        },
        "cast": {
            "passed": not absent,
            "roster": roster,
            "absent": absent,
            "reason": f"nu apar în episod: {', '.join(absent)}" if absent else "",
        },
        "accessibility": {
            "passed": bool(first_names) and first_scene_words >= 3 and not starts_mid_thought,
            "first_beat_names": first_names,
            "starts_mid_thought": starts_mid_thought,
            "reason": (
                ""
                if bool(first_names) and first_scene_words >= 3 and not starts_mid_thought
                else "primul beat nu se ține singur: numește cine e în scenă și unde suntem"
            ),
        },
    }


def review_episode(
    engine: Engine,
    registry: ProviderRegistry | None,
    episode_id: str,
    correlation_id: str = "",
    language: str = "en",
) -> dict[str, Any]:
    """The Director's verdict on one drafted episode; recorded, and acted on under policy."""
    correlation = correlation_id or str(uuid4())
    with Session(engine) as session:
        episode = session.get(StoryEpisode, episode_id)
        if episode is None:
            raise ReviewError("Episodul nu există")
        if episode.status != "DRAFT":
            raise ReviewError(f"Episodul este deja {episode.status.lower()}")
        if episode.review_json:
            raise ReviewError("Episodul a fost deja citit de Director")
        director = agent_for_role(session, REVIEWER_ROLE)
        if director is None:
            raise ReviewError("Niciun Director activ care să citească episodul")
        director_id, director_name = director.id, director.display_name
        checks = episode_checks(session, episode)
        log = session.get(DailyStudioLog, episode.log_id)
        facts = {
            "title": episode.title,
            "business_date": log.business_date if log else None,
            "beats": [
                {
                    "beat": beat.get("beat_number"),
                    "scene": beat.get("scene"),
                    "dialogue": beat.get("dialogue"),
                    "characters": beat.get("characters"),
                }
                for beat in (episode.beats_json or [])
            ],
            "cast": [m.get("display_name") for m in (log.roster_json or [])] if log else [],
            "continuity": {
                key: (episode.continuity_json or {}).get(key)
                for key in (
                    "episode_number",
                    "summary",
                    "threads_continued",
                    "threads_closed",
                    "threads_opened",
                )
            },
            "measured": {
                name: {k: v for k, v in c.items() if k != "reason"} for name, c in checks.items()
            },
        }
        title = episode.title

    failed = [name for name, check in checks.items() if not check["passed"]]
    run_id: str | None = None
    if failed:
        reasons = [checks[name]["reason"] for name in failed if checks[name]["reason"]]
        verdict = EpisodeVerdict(
            verdict="FAIL",
            reasons=reasons[:8],
            notes="; ".join(reasons)[:1200],
            story="",
        )
    elif registry is not None and registry.registered_ids():
        prompt = (
            audience_language_line(language)
            + _INSTRUCTIONS
            + wrap_in_inert_boundary(json.dumps(facts, ensure_ascii=False)[:14000], "the-episode")
        )
        result = run_agent_task(
            engine,
            registry,
            director_id,
            REVIEW_TASK,
            prompt,
            TEMPLATE_VERSION,
            correlation,
            summary=f"Citesc episodul «{title[:80]}» înainte de filmare.",
            max_tokens=3000,
            temperature=0.1,
            emit_message=False,
        )
        run_id = result["id"]
        parsed = (
            parse_structured(result.get("output_text") or "", EpisodeVerdict)
            if result["status"] == "SUCCEEDED"
            else None
        )
        if parsed is None:
            raise ReviewError(
                f"{director_name} nu a dat un verdict utilizabil ({result['status']}: fără obiect)"
            )
        verdict = parsed  # type: ignore[assignment]
    else:
        raise ReviewError("Niciun model de limbaj: Directorul nu poate citi episodul")

    with Session(engine) as session, session.begin():
        episode = session.get(StoryEpisode, episode_id)
        assert episode is not None  # read above, in this same process
        may_approve = verdict.verdict == "PASS" and director_may_approve_episodes(session)
        reviewed_at = utc_now()
        episode.review_json = {
            "verdict": verdict.verdict,
            "checks": checks,
            "reasons": list(verdict.reasons),
            "notes": verdict.notes,
            "story": verdict.story,
            "run_id": run_id,
            "model_used": run_id is not None,
            "reviewer_agent_id": director_id,
            "reviewed_at": reviewed_at,
            "approved_by_policy": may_approve,
        }
        episode.event_id = append_event(
            session,
            "story.episode_reviewed",
            "story_episode",
            episode.id,
            2,
            {
                "log_id": episode.log_id,
                "verdict": verdict.verdict,
                "checks_failed": failed,
                "model_used": run_id is not None,
            },
            correlation,
        ).event_id
        if verdict.verdict == "FAIL":
            episode.status = "REJECTED"
            episode.notes = (verdict.notes or "; ".join(verdict.reasons))[:2000] or None
            episode.reviewed_by = "director"
            episode.event_id = append_event(
                session,
                "story.episode_rejected",
                "story_episode",
                episode.id,
                3,
                {"log_id": episode.log_id, "reviewed_by": "director"},
                correlation,
            ).event_id
            showrunner = agent_for_role(session, PREFERRED_SHOWRUNNER_ROLE)
            if showrunner is not None and episode.notes:
                post_message(
                    session,
                    intent="HANDOFF",
                    subject=f"Rescris: {title[:110]}"[:200],
                    body={"episode_id": episode.id, "verdict": "FAIL"},
                    body_text=f"{episode.notes} — {director_name}"[:4000],
                    from_agent_id=director_id,
                    to_agent_id=showrunner.id,
                    # The run is on the episode's review record; the letter is the note.
                    run_id=None,
                    correlation_id=correlation,
                )
        elif may_approve:
            episode.status = "APPROVED"
            episode.reviewed_by = "director"
            episode.notes = (verdict.story or None) and verdict.story[:2000]
            episode.event_id = append_event(
                session,
                "story.episode_approved",
                "story_episode",
                episode.id,
                3,
                {"log_id": episode.log_id, "reviewed_by": "director"},
                correlation,
            ).event_id
            advance_continuity(session, episode, correlation)
        remember(
            session,
            memory_class="AGENT_OPINION",
            content=(
                f"{verdict.verdict} for the episode “{title[:120]}”"
                + (f": {'; '.join(verdict.reasons)}" if verdict.reasons else ".")
            )[:600],
            source_type="run" if run_id else "system",
            source_id=run_id or episode.id,
            agent_id=director_id,
        )
        status = episode.status
    return {
        "episode_id": episode_id,
        "verdict": verdict.verdict,
        "status": status,
        "checks": checks,
        "reasons": list(verdict.reasons),
        "notes": verdict.notes,
        "story": verdict.story,
        "run_id": run_id,
        "model_used": run_id is not None,
        "approved_by_policy": status == "APPROVED",
    }
