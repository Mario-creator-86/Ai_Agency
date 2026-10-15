"""The Director reads the episode before it is filmed.

Measured before this module: an episode stopped at DRAFT and waited for the Owner's hand;
nothing read it for the things a reader can measure, and nothing consumed an APPROVED one.
This is the gate between the showrunner and the camera, in the shape `editorial_review`
already has for films:

- **The checks are computed first**, without a model, because they are not matters of taste.
  Grounding (every cited id is in the day's record — reusing the rule `write_episode`
  enforces); privacy (no cited id outside the PUBLIC_SAFE projection, and nothing in the
  text, the summary, the opened threads or the recurring elements the redaction pass would
  change — the summary and the threads are what canon keeps and hands to every later
  episode's prompt); length (at most `MAX_BEATS` beats and 45-70 seconds
  of spoken words at the studio's own 2.5 words a second, names and stage directions not
  counted); cast (a v3 episode: two to four speakers, each acting in the events the episode
  cites — the Owner's rule of 2026-09-24; a v2 episode: every active roster member appears);
  structure (a v3 episode runs hook, situation, turn, payoff, button, in the studio's own
  rooms); words per beat (a v3 beat holds 8-22 spoken words, a scene's nine seconds — since
  2026-10-13 a recommendation: measured and shown, decided by the Director, never a refusal);
  concentration (no event carries more than half the beats unless it is the day's only
  one — the episode on his data cites one event in all eight); language (the title and every
  line in the publishing language, before any paid render); new-viewer accessibility
  (the first beat names who is in the room and does not begin mid-thought); and, when the
  serial's motion model states its longest clip, filmable (each beat's lines said within one
  clip of it, slowed down locally by at most a quarter — 2026-10-10).
  The writer is measured by these same checks before a draft is stored (`draft_checks`).
  A check certifies only what it measured: an episode with nothing to measure (no citation,
  no line, no title) fails it rather than passing by absence.
  Any failure of a rule is the verdict, with its reasons, and the Director is not asked; a
  check that only recommends (``advisory``) hands her its measure, and she decides.
- **Then the Director's verdict** (review v2, 2026-09-24), through `run_agent_task` with the
  episode as data: each beat with the events it cites (id, the record's words, who acts),
  the speakers' voices from their bibles, and the serial's memory. The facts are fitted to a
  size budget by shedding the least needed parts first, never cut mid-JSON. Her brief FAILs
  any outcome a beat shows that the event it cites does not hold, and she scores hook,
  situation, turn, payoff, voices and button 1-5: a PASS without all six scores is no
  verdict, and a PASS her own scores put below 3 anywhere is a FAIL. Her notes go back to
  the showrunner for the one rewrite the stage allows.

A PASS approves the episode only under the channel's policy: the OFFICE_SERIAL channel's
`director_may_approve_episodes` column (migration 0038), False unless the Owner's
publish-policy command set it. Without it the episode stays DRAFT with the review on it, for
the Owner's `decide_episode`. A FAIL is REJECTED at once; the rewrite is a new draft.

- **Then her editorial judgement** (2026-10-11, the Owner's card of 23:30; `judged_review`):
  the reading above let «The Zero Script Club» through — grounded, private in nothing, right
  in length, and a status meeting with no stake and no punchline. So a PASS is held
  (``approve=False``) and the episode is read once more as a stranger would meet it
  (`episode_as_text`), scored on five criteria by `app.agents.editorial_judgement`; below the
  bar the showrunner rewrites on her brief (`write_episode`, ``judged=True``, every check
  above run again on the rewrite), up to `Settings.editorial_rounds` versions, and the
  best-scored version that passed this review ships: approved under the policy
  (`approve_reviewed_episode`), the other versions retired (`retire_episode`) so nothing waits
  for the Owner beside it. Every version read is an `editorial.judged` event; the chosen
  version's scores stay on its review_json for the weekly review.
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.editorial_judgement import (
    SERIAL_EPISODE,
    Version,
    editorial_loop,
    letter_to_owner,
    record_rounds,
)
from app.agents.identity import clipped, parse_structured
from app.agents.language import audience_language_line, looks_like_english
from app.agents.memory import agent_for_role, remember
from app.agents.messages import post_message
from app.agents.services import run_agent_task
from app.factual.sanitizer import wrap_in_inert_boundary
from app.providers.registry import ProviderRegistry
from app.publishing.models import ChannelRecord
from app.services import append_event, utc_now
from app.story.lines import NameBook, beat_lines, participants, speakers_of, spoken_text
from app.story.locations import location_id, studio_locations
from app.story.models import ContinuityState, DailyStudioLog, StoryEpisode
from app.story.projection import leaks
from app.story.services import (
    EPISODE_PARTS,
    MAX_BEATS,
    PREFERRED_SHOWRUNNER_ROLE,
    SERIES_KEY,
    SPEAKING_CAST,
    WORDS_PER_BEAT,
    DraftRefused,
    StoryError,
    advance_continuity,
    bibles_for_roster,
    ensure_projection,
    voice_of,
    write_episode,
)
from app.wording import decimal, work_status

logger = logging.getLogger("studio.story.review")

REVIEW_TASK = "episode_review"
#: v2 (2026-09-24): the cited events, the voices and the memory in the facts; the rubric.
#: v3 (2026-09-24, the adversary's read): the 3-second hook, the button as the last
#: words, beats that change something, and a letter's invented contents as a truth
#: failure, the same rules the showrunner's brief v5 states.
TEMPLATE_VERSION = "episode-review-v3"
REVIEWER_ROLE = "Director"
#: What the Director scores, 1 to 5, in the order an episode plays.
RUBRIC = ("hook", "situation", "turn", "payoff", "voices", "button")
#: A PASS with any score below this is her own FAIL: "the payoff does not work, ship it" is
#: not a verdict the camera should act on.
RUBRIC_FLOOR = 3
#: The facts' size target, in characters. Until v2 the JSON was cut at 14,000 characters
#: wherever that fell, so a long episode reached her as broken JSON with its last beats
#: missing; now the least needed parts are shed first (`fit_to_budget`) and the beats, their
#: lines and their citations are always whole.
FACTS_BUDGET = 14000
#: The studio's speaking rate, the same figure the storyboard uses to time a scene.
WORDS_PER_SECOND = 2.5
MIN_SECONDS = 45.0
MAX_SECONDS = 70.0
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
    #: The rubric, 1-5 for each part of `RUBRIC`; only the rubric's own keys are kept.
    scores: dict[str, int | float] = Field(default_factory=dict)
    _clip_notes = field_validator("notes", mode="before")(clipped(1200))
    _clip_story = field_validator("story", mode="before")(clipped(400))
    _one_reason = field_validator("reasons", mode="before")(
        lambda value: [value] if isinstance(value, str) else value
    )

    @field_validator("scores", mode="before")
    @classmethod
    def _rubric_only(cls, value: Any) -> dict[str, int | float]:
        # A score written "4" or 4.0 is a 4; one that is not a number is left out, which a
        # PASS then answers for as a missing score.
        if not isinstance(value, dict):
            return {}
        found: dict[str, int | float] = {}
        for key, score in value.items():
            name = str(key).strip().lower()
            if name not in RUBRIC or isinstance(score, bool):
                continue
            try:
                number = float(score)
            except (TypeError, ValueError):
                continue
            found[name] = int(number) if number.is_integer() else number
        return found


_INSTRUCTIONS = (
    "You are the Director, and this is the last read of an episode of the studio's own "
    "serial before it is filmed. Below is the episode as data: each beat with its part, "
    "room, scene and lines, and the events it cites (what the studio's record says "
    "happened, and who acted in it); the voices of the people who speak, from their "
    "character bibles; the serial's memory (the last summaries and the open threads); and "
    "what the computed checks measured. Every computed rule passed; what the checks only "
    'recommend and this episode is outside of is listed under "recommendations", for you to '
    "decide.\n"
    "1. Truth. A beat may dramatise its events: jokes, pauses, reactions, compressed talk. "
    "FAIL the episode if any beat shows an outcome that is not in the event it cites: a "
    "decision, a verdict, a success or a failure, a publication, a hire or a departure, "
    "money, an audience, or an ending the event leaves open; or a line that quotes what a "
    "letter said when its event gives only the letter's subject. Name the beat and the "
    "outcome in the reasons.\n"
    "2. The viewer. Does the hook stand alone for someone who has never seen the serial, "
    "with its first line heard inside the first 3 seconds and not a greeting; is there one "
    "situation with a turn and a payoff, each beat changing something; does the button land "
    "as the last words, ideally calling back to the hook; is the humour in the situation "
    "rather than in explaining the studio.\n"
    "3. Voices. Does each speaker sound like their bible (register, cadence, habits, their "
    "own phrases) and like a person, not a status report.\n"
    "4. Continuity. Does it continue or close the open threads it claims to.\n"
    f"5. Recommendations. A beat outside the {WORDS_PER_BEAT[0]}-{WORDS_PER_BEAT[1]} "
    "spoken-word band is flagged, not refused: the filmable rule has already measured that "
    "its lines fit one clip. Keep it when it reads well at 2.5 words a second; FAIL only when "
    "the beat would be cut off or is too fast to follow, naming the beat and its words in the "
    "notes.\n"
    "A dramatisation is not a factual film: it makes no claims about the world and needs no "
    "sources, and you do not reject it for that.\n"
    "Score each part 1-5: 1 missing, 3 works, 5 could not be better. A PASS carries all six "
    "scores and none below 3; a part that scores lower makes the verdict FAIL. Return only "
    'JSON: {"verdict": "PASS" | "FAIL", "scores": {"hook": 1-5, "situation": 1-5, '
    '"turn": 1-5, "payoff": 1-5, "voices": 1-5, "button": 1-5}, "reasons": ["..."], '
    '"notes": "what the showrunner must change, if FAIL", "story": "one sentence: what the '
    'viewer follows"}.\n'
)


def director_may_approve_episodes(session: Session) -> bool:
    """Whether the Owner's policy lets the Director approve an episode on her own.

    False unless the OFFICE_SERIAL channel's publish policy says so. It used to be read from
    the channel's `series_rules_json`, where no command could write it (the production-policy
    validator keeps that JSON to series rules); it is a column of the policy now, set only by
    the Owner's publish-policy command, which versions and records the grant. Nothing here
    writes it.
    """
    channel = session.scalar(
        select(ChannelRecord).where(ChannelRecord.channel_type == "OFFICE_SERIAL")
    )
    return bool(channel is not None and channel.director_may_approve_episodes)


def _words(text: Any) -> int:
    return len(str(text or "").split())


def _speaking_cast(
    lines: list[dict[str, Any]], beats: list[dict], projection: dict[str, dict], cast: list[str]
) -> dict[str, Any]:
    """The Owner's cast rule (2026-09-24): two to four people speak, chosen from those who act
    in the events the episode cites; everyone else is background.

    When the cited events name fewer than two people (a render that finished names nobody),
    those they name must speak, and the rest of the speaking cast may be anyone on the day's
    roster: the rule cannot ask for two people the record does not have.
    """
    speakers = speakers_of(lines)
    acting: list[str] = []
    for beat in beats:
        for event_id in beat.get("event_ids") or []:
            for name in participants(projection.get(event_id) or {}, cast):
                if name not in acting:
                    acting.append(name)
    low, high = SPEAKING_CAST
    outsiders = [name for name in speakers if name not in acting] if len(acting) >= low else []
    silent = [name for name in acting if name not in speakers] if len(acting) < low else []
    problems = []
    if not low <= len(speakers) <= high:
        problems.append(f"vorbesc {len(speakers)} personaje; episodul cere între {low} și {high}")
    if outsiders:
        problems.append("vorbesc fără să acționeze în evenimentele citate: " + ", ".join(outsiders))
    if silent:
        problems.append("nu vorbesc deși acționează în evenimentele citate: " + ", ".join(silent))
    return {
        "passed": not problems,
        "speakers": speakers,
        "acting_in_cited_events": acting,
        "reason": "; ".join(problems),
    }


def _structure(beats: list[dict], locations: list[dict]) -> dict[str, Any]:
    """Hook, situation, turn, payoff, button, in that order, in rooms the studio has."""
    parts = [str(beat.get("part") or "").strip().lower() for beat in beats]
    known = [part for part in parts if part in EPISODE_PARTS]
    problems = []
    unknown = sorted({part or "(nimic)" for part in parts if part not in EPISODE_PARTS})
    if unknown:
        problems.append("părți necunoscute: " + ", ".join(unknown))
    missing = [part for part in EPISODE_PARTS if part not in parts]
    if missing:
        problems.append("lipsesc părțile: " + ", ".join(missing))
    ranks = [EPISODE_PARTS.index(part) for part in known]
    if ranks != sorted(ranks) or parts.count("hook") > 1 or parts.count("button") > 1:
        problems.append(
            "părțile nu merg în ordinea " + ", ".join(EPISODE_PARTS) + " (un singur hook, "
            "primul, și un singur button, ultimul)"
        )
    nowhere = [
        str(beat.get("location") or "(nimic)")
        for beat in beats
        if location_id(beat.get("location"), locations) is None
    ]
    if nowhere:
        problems.append("locuri care nu sunt în studio: " + ", ".join(dict.fromkeys(nowhere)))
    return {"passed": not problems, "parts": parts, "reason": "; ".join(problems)}


def _beat_numbers(beats: list[dict]) -> list[int]:
    return [int(beat.get("beat_number") or index + 1) for index, beat in enumerate(beats)]


def _words_per_beat(
    beats: list[dict], lines_by_beat: list[list[dict[str, Any]]], v3: bool
) -> dict[str, Any]:
    """Spoken words in each beat, against the brief's `WORDS_PER_BEAT` — a recommendation.

    A scene is at most nine seconds on the storyboard, and 22 words are 8.8 seconds at the
    studio's rate; a beat of 40 words is either cut off or read too fast to follow. Only the
    spoken words count: a name, a label or an acting note is never said. A v2 episode was
    never told the rule and is measured but not held to it; a beat with no line fails, since
    nothing in it was measured.

    Since 2026-10-13 the band is ``advisory`` (the Owner: «nu trebuie să fie ceva fix, este
    ceva recomandat, dar nici să respingi serialul de la asta»): a beat outside it is measured
    and shown, the writer is not asked again for it (`services._ask_again`), and the Director
    reads the episode and decides (`review_episode`). Until then a 23-word beat was REJECTED
    before she read it («The Ninth Rewrite», 13.10.2026). The clip's own limit stays the
    `filmable` rule.
    """
    per_beat = [_words(spoken_text(lines)) for lines in lines_by_beat]
    low, high = WORDS_PER_BEAT
    outside = [
        number
        for number, words in zip(_beat_numbers(beats), per_beat, strict=True)
        if not low <= words <= high
    ]
    measured: dict[str, Any] = {
        "per_beat": per_beat,
        "outside": outside,
        "advisory": True,
        "recommended": [low, high],
    }
    if not beats:
        return {**measured, "passed": False, "reason": "episodul nu are niciun beat de măsurat"}
    if not v3:
        return {**measured, "passed": True, "legacy": True, "reason": ""}
    counted = [per_beat[_beat_numbers(beats).index(number)] for number in outside]
    return {
        **measured,
        "passed": not outside,
        "reason": (
            f"beat-urile {', '.join(map(str, outside))} ies din recomandarea de {low}-{high} "
            f"cuvinte rostite (au {', '.join(map(str, counted))}); decide Directoarea"
            if outside
            else ""
        ),
    }


def failed_rules(checks: dict[str, dict[str, Any]]) -> list[str]:
    """The checks that refuse the episode on their own: failed, and not a recommendation."""
    return [
        name for name, check in checks.items() if not check["passed"] and not check.get("advisory")
    ]


def outside_recommendations(checks: dict[str, dict[str, Any]]) -> list[str]:
    """The recommendations the episode is outside of: measured and shown, the Director's to
    decide (2026-10-13)."""
    return [name for name, check in checks.items() if not check["passed"] and check.get("advisory")]


def motion_clip_limit(session: Session) -> dict[str, Any] | None:
    """The motion model the serial is filmed with, and the longest beat one of its clips can
    carry: its longest clip, slowed down locally by at most `SLOWDOWN_ALLOWANCE` (the Owner's
    «Încetinește local»). The model is the one the production policy resolves for the serial's
    channel and series; its longest clip is read from its own contract, else from the price
    table. None when no model is selected or nothing sets its maximum: no filming check is
    then claimed, as no language check is claimed for a language the guard cannot read.
    """
    from app.integrations.models import ProviderResource  # noqa: PLC0415
    from app.media.cost_plan import SLOWDOWN_ALLOWANCE, longest_seconds  # noqa: PLC0415
    from app.media.production_policy import resolve_purpose  # noqa: PLC0415

    channel = session.scalar(
        select(ChannelRecord).where(ChannelRecord.channel_type == "OFFICE_SERIAL")
    )
    chosen = resolve_purpose(session, "video", channel=channel, series_key=SERIES_KEY)
    model_id = str(chosen.get("model_id") or "")
    if not model_id:
        return None
    resource = session.scalar(
        select(ProviderResource).where(
            ProviderResource.integration_id == chosen.get("integration_id"),
            ProviderResource.remote_id == model_id,
        )
    )
    meta = resource.api_metadata if resource is not None else None
    meta = meta if isinstance(meta, dict) else {}
    durations = meta.get("durations")
    contract = durations.get("image_to_video") if isinstance(durations, dict) else None
    rule: dict[str, Any] | None = None
    if isinstance(contract, list) and contract:
        rule = {"values": contract}
    elif isinstance(contract, dict) and contract:
        rule = contract
    longest = longest_seconds(model_id, contract=rule) if rule else longest_seconds(model_id)
    stated = meta.get("max_seconds")
    if longest is None and isinstance(stated, int | float) and not isinstance(stated, bool):
        longest = int(stated)
    if not longest:
        return None
    return {
        "model_id": model_id,
        "longest_seconds": longest,
        "limit_seconds": round(longest * (1 + SLOWDOWN_ALLOWANCE), 3),
    }


def beat_clip_seconds(lines: list[dict[str, Any]]) -> float:
    """The clip one beat's lines need, sized as the motion plan sizes a clip for words not
    yet voiced (`assembler.clip_plan`, an ESTIMATED narration): the words as the voice says
    them (`spoken_words`: a number is said in words) at SECONDS_PER_SPOKEN_WORD, a
    SPEAKER_GAP_SECONDS breath between two speakers' takes (`speaker_segments`), the
    estimate's margin and the scene's closing breath. A serial scene cuts to the next one
    (`storyboard_from_episode`), so no dissolve is added.
    """
    from app.media.assembler import (  # noqa: PLC0415 - the assembler is heavy; read when measured
        NARRATION_ESTIMATE_MARGIN,
        SECONDS_PER_SPOKEN_WORD,
        SPOKEN_TAIL_SECONDS,
        spoken_words,
    )
    from app.media.speaker_voices import SPEAKER_GAP_SECONDS, speaker_segments  # noqa: PLC0415

    takes = speaker_segments(lines)
    said = sum(spoken_words(take["text"]) for take in takes) * SECONDS_PER_SPOKEN_WORD
    said += SPEAKER_GAP_SECONDS * max(0, len(takes) - 1)
    return round(said * (1 + NARRATION_ESTIMATE_MARGIN) + SPOKEN_TAIL_SECONDS, 2)


def _filmable(
    beats: list[dict], lines_by_beat: list[list[dict[str, Any]]], limit: dict[str, Any]
) -> dict[str, Any]:
    """Every beat said within one clip of the serial's motion model (`motion_clip_limit`).

    One beat is one scene and one clip. The words-per-beat rule counts words; this counts
    seconds, numbers said in words and the breaths between speakers included, against what
    the camera can film: a beat longer than its clip slowed by a quarter is refused at
    assembly after its stills, clip and voice were bought (2026-10-10, LTX-2.5 at 10 s).
    """
    needed = [beat_clip_seconds(lines) for lines in lines_by_beat]
    ceiling = float(limit["limit_seconds"])
    numbers = _beat_numbers(beats)
    outside = [n for n, s in zip(numbers, needed, strict=True) if s > ceiling + 1e-6]
    counted = [needed[numbers.index(number)] for number in outside]
    problems = []
    if not beats:
        problems.append("episodul nu are niciun beat de măsurat")
    if outside:
        problems.append(
            f"beat-urile {', '.join(map(str, outside))} nu încap într-un singur cadru: "
            f"{limit['model_id']} filmează cel mult {limit['longest_seconds']} s "
            f"({decimal(ceiling, 1)} s încetinit local), iar replicile lor cer "
            + ", ".join(f"{decimal(seconds, 1)} s" for seconds in counted)
        )
    return {
        **limit,
        "passed": not problems,
        "needed_seconds": needed,
        "outside": outside,
        "reason": "; ".join(problems),
    }


def _concentration(beats: list[dict], day_events: int) -> dict[str, Any]:
    """No event is cited by more than half the beats, unless it is the day's only event.

    Measured on his data (2026-09-24): the one episode written, 'Day One', cites the same
    event in all eight beats, which is filler dressed as grounded: every beat passes the
    grounding and the day is not told. A beat that cites nothing fails here too, because a
    beat with no citation was not measured.
    """
    citations: dict[str, int] = {}
    uncited = []
    for number, beat in zip(_beat_numbers(beats), beats, strict=True):
        cited = list(dict.fromkeys(str(eid) for eid in beat.get("event_ids") or []))
        if not cited:
            uncited.append(number)
        for event_id in cited:
            citations[event_id] = citations.get(event_id, 0) + 1
    most = max(citations.values(), default=0)
    only_event = day_events == 1
    crowded = bool(beats) and most * 2 > len(beats) and not only_event
    problems = []
    if not beats:
        problems.append("episodul nu are niciun beat de măsurat")
    if uncited:
        problems.append(f"beat-urile {', '.join(map(str, uncited))} nu citează niciun eveniment")
    if crowded:
        problems.append(
            f"un singur eveniment este citat în {most} din {len(beats)} beat-uri; cel mult "
            "jumătate, afară de ziua care are un singur eveniment"
        )
    return {
        "passed": not problems,
        "beats": len(beats),
        "citations": citations,
        "most_cited": most,
        "day_events": day_events,
        "only_event": only_event,
        "reason": "; ".join(problems),
    }


def _language(title: str, lines_by_beat: list[list[dict[str, Any]]]) -> dict[str, Any]:
    """The title and every spoken line in English, the language the channels publish in.

    The v2 brief was Romanian and a model answers in the language it is spoken to; a
    Romanian episode reached the camera with nothing to stop it before the paid render, and
    only the Publisher's language hold stopped it after. `looks_like_english` is the guard
    the Publisher uses, read line by line and over the whole text, so neither one Romanian
    line nor Romanian spread thin across many passes. No line or no title is not English.
    """
    spoken = [
        str(line.get("text") or "") for lines in lines_by_beat for line in lines if line.get("text")
    ]
    not_english = [text for text in spoken if not looks_like_english(text)]
    whole = bool(spoken) and looks_like_english("\n".join(spoken))
    title_english = bool(title.strip()) and looks_like_english(title)
    problems = []
    if not title.strip():
        problems.append("episodul nu are titlu")
    elif not title_english:
        problems.append("titlul nu este în engleză")
    if not spoken:
        problems.append("episodul nu are nicio replică de măsurat")
    elif not_english:
        problems.append(f"{len(not_english)} din {len(spoken)} replici nu sunt în engleză")
    elif not whole:
        problems.append("replicile, luate împreună, nu sunt în engleză")
    return {
        "passed": not problems,
        "language": "en",
        "title_english": title_english,
        "lines": len(spoken),
        "lines_not_english": len(not_english),
        "examples": [text[:80] for text in not_english[:3]],
        "reason": "; ".join(problems),
    }


def episode_checks(
    session: Session, episode: StoryEpisode, language: str = "en"
) -> dict[str, dict[str, Any]]:
    """The verdicts that need no model, each with what it measured."""
    log = session.get(DailyStudioLog, episode.log_id)
    if log is None:
        raise ReviewError("Jurnalul episodului nu există")
    projected = {item["event_id"]: item for item in ensure_projection(session, log)}
    projection = set(projected)
    recorded = {item["event_id"] for item in (log.notable_events_json or [])} | projection
    beats = list(episode.beats_json or [])
    cited = list(episode.grounded_event_ids_json or [])
    roster_rows = list(log.roster_json or [])
    names = NameBook(roster_rows, bibles_for_roster(session, roster_rows))
    # A v3 beat has its lines; a v2 beat's free dialogue is read into lines the same way the
    # storyboard reads it, so a name or a stage direction is never counted as speech.
    lines_by_beat = [beat_lines(beat, names) for beat in beats]
    v3 = any(isinstance(beat.get("lines"), list) for beat in beats)

    missing = [eid for eid in cited if eid not in recorded]
    private = [eid for eid in cited if eid in recorded and eid not in projection]
    # Which part of each beat leaks, said to the writer: «beat-urile [1] conțin ceva» left the
    # rewrite guessing which words to change (2026-10-11, a scene description).
    leaking_fields: dict[str, list[str]] = {}
    for beat, lines in zip(beats, lines_by_beat, strict=True):
        fields = [
            label
            for label, found in (
                ("descrierea scenei", leaks(str(beat.get("scene") or ""))),
                ("replicile", leaks(str(beat.get("dialogue") or ""))),
                (
                    "indicațiile de joc",
                    any(leaks(str(line.get("direction") or "")) for line in lines),
                ),
            )
            if found
        ]
        if fields:
            leaking_fields[str(beat.get("beat_number"))] = fields
    leaking = [
        beat.get("beat_number") for beat in beats if str(beat.get("beat_number")) in leaking_fields
    ]
    if leaks(episode.title):
        leaking.insert(0, 0)
        leaking_fields["0"] = ["titlul"]
    # What canon would keep of this episode: measured, a key in the summary passed the
    # beats' check and would have reached every later showrunner prompt through
    # `_previously`.
    continuity = episode.continuity_json or {}
    carried = [str(continuity.get("summary") or "")]
    carried += [str(t) for t in (continuity.get("threads_opened") or [])]
    carried += [str(r) for r in (continuity.get("recurring") or [])]
    # The plan for the next episode (S6) reaches the next writer's brief the same way.
    plan = continuity.get("next_episode")
    if isinstance(plan, dict):
        carried += [
            str(plan.get(key) or "") for key in ("premise", "cold_open_line", "open_question")
        ]
        carried += [str(t) for t in (plan.get("threads_to_pay_off") or [])]
    leaking_canon = [text[:80] for text in carried if leaks(text)]

    words = sum(_words(spoken_text(lines)) for lines in lines_by_beat)
    seconds = round(words / WORDS_PER_SECOND, 1)

    roster = [str(m.get("display_name")) for m in roster_rows if m.get("lifecycle") == "ACTIVE"]
    if v3:
        cast_check = _speaking_cast(
            [line for lines in lines_by_beat for line in lines], beats, projected, names.names
        )
        structure = _structure(beats, studio_locations(session, roster_rows))
    else:
        # A v2 episode was written to the old brief (everyone appears, no parts, no rooms)
        # and is judged by it: the rules it was never told are not held against it.
        cast = {str(name) for beat in beats for name in (beat.get("characters") or [])}
        absent = [name for name in roster if name not in cast]
        cast_check = {
            "passed": not absent,
            "roster": roster,
            "absent": absent,
            "reason": f"nu apar în episod: {', '.join(absent)}" if absent else "",
        }
        structure = {"passed": True, "parts": [], "legacy": True, "reason": ""}

    first = beats[0] if beats else {}
    first_lines = lines_by_beat[0] if lines_by_beat else []
    opening = " ".join(spoken_text(first_lines).lower().split())[:80]
    starts_mid_thought = any(opening.startswith(marker) for marker in CONTINUATION_MARKERS)
    first_names = list(first.get("characters") or [])
    first_scene_words = _words(first.get("scene"))

    checks: dict[str, dict[str, Any]] = {
        "grounding": {
            # An episode that cites nothing is not grounded: nothing was measured.
            "passed": bool(cited) and not missing,
            "cited": len(cited),
            "missing": missing,
            "reason": (
                f"{len(missing)} evenimente citate nu sunt în jurnalul zilei"
                if missing
                else ("episodul nu citează niciun eveniment" if not cited else "")
            ),
        },
        "privacy": {
            "passed": not private and not leaking and not leaking_canon,
            "private_citations": private,
            "leaking_beats": leaking,
            "leaking_fields": leaking_fields,
            "leaking_canon": leaking_canon,
            "reason": "; ".join(
                part
                for part in (
                    f"{len(private)} evenimente citate nu sunt publice" if private else "",
                    (
                        "conțin ceva ce nu poate fi public (o cheie, un link, un preț, un model "
                        "sau un număr de cont): "
                        + ", ".join(
                            "titlul" if number == "0" else f"beat-ul {number} ({', '.join(fields)})"
                            for number, fields in leaking_fields.items()
                        )
                        + "; scrie-le fără"
                    )
                    if leaking
                    else "",
                    (
                        "rezumatul, firele sau elementele recurente conțin ceva ce nu poate "
                        "fi public"
                        if leaking_canon
                        else ""
                    ),
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
        "words_per_beat": _words_per_beat(beats, lines_by_beat, v3),
        "concentration": _concentration(beats, len(projected)),
        "cast": cast_check,
        "structure": structure,
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
    if language.lower() == "en":
        # The guard knows English from the office's own Romanian and nothing else, so it is
        # asked only when the studio publishes in English (STUDIO_CONTENT_LANGUAGE); for any
        # other language no check is claimed rather than one that measured nothing.
        checks["language"] = _language(str(episode.title or ""), lines_by_beat)
    # A v2 episode is filmed whole by one voice and was never told the rule; a studio with
    # no motion model, or one whose longest clip nothing states, has nothing to measure.
    if v3 and (limit := motion_clip_limit(session)) is not None:
        checks["filmable"] = _filmable(beats, lines_by_beat, limit)
    return checks


def draft_checks(
    session: Session, episode: StoryEpisode, offered: list[str], language: str = "en"
) -> dict[str, dict[str, Any]]:
    """What a written answer is measured by before it is stored for the review (brief v7).

    The review's own `episode_checks`, run on the episode as it would be stored, so the
    writer's measure and the Director's can never disagree; and one rule of the brief only:
    nobody speaks but the speakers it offered (``offered``). That rule steers the writer and
    is not the review's: the Owner's rule is the cast check's, two to four who act in the
    cited events, and a draft that keeps it reaches the Director whoever speaks.
    """
    checks = episode_checks(session, episode, language)
    if offered:
        lines = [line for beat in episode.beats_json or [] for line in beat_lines(beat)]
        speaking = speakers_of(lines)
        extra = [name for name in speaking if name not in offered]
        checks["offered_speakers"] = {
            "passed": not extra,
            "offered": list(offered),
            "speakers": speaking,
            "reason": (
                f"vorbesc fără să fie printre vorbitorii aleși ({', '.join(offered)}): "
                + ", ".join(extra)
                if extra
                else ""
            ),
        }
    return checks


def review_facts(
    session: Session, episode: StoryEpisode, checks: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """The episode as the Director reads it: what she needs to judge what checks cannot.

    Until v2 she was given the beats and the cast only, and judged "is this grounded" without
    the events: an outcome no event holds could pass her. Each beat now carries the events it
    cites in the record's own public words, and who acts in them; the speakers carry their
    bibles' voice fields, the same ones the showrunner was briefed with; and the serial's
    memory carries the last summaries and the open threads, by id, as canon holds them.
    """
    log = session.get(DailyStudioLog, episode.log_id)
    projected = {item["event_id"]: item for item in ensure_projection(session, log)} if log else {}
    roster_rows = list(log.roster_json or []) if log else []
    bibles = bibles_for_roster(session, roster_rows)
    names = NameBook(roster_rows, bibles)
    beats = []
    speaking: list[str] = []
    for index, beat in enumerate(episode.beats_json or []):
        lines = beat_lines(beat, names)
        speaking += [name for name in speakers_of(lines) if name not in speaking]
        cites = []
        for event_id in beat.get("event_ids") or []:
            item = projected.get(event_id)
            cites.append(
                {
                    "id": event_id,
                    # A citation outside the public record fails the grounding or the privacy
                    # check before she is asked; None says so if she ever sees one.
                    "what": item.get("description") if item else None,
                    "who": participants(item, names.names) if item else [],
                }
            )
        beats.append(
            {
                "beat": beat.get("beat_number") or index + 1,
                "part": beat.get("part"),
                "location": beat.get("location"),
                "scene": beat.get("scene"),
                "lines": lines,
                "background": beat.get("background"),
                "characters": beat.get("characters"),
                "cites": cites,
            }
        )
    # A v2 episode whose labels the roster does not know has no speakers; its characters are
    # the nearest thing to who talks.
    if not speaking:
        for beat in episode.beats_json or []:
            speaking += [str(n) for n in beat.get("characters") or [] if str(n) not in speaking]
    state = session.get(ContinuityState, 1)
    continuity = episode.continuity_json or {}
    return {
        "title": episode.title,
        "business_date": log.business_date if log else None,
        "beats": beats,
        "cast": names.names,
        "voices": {name: voice_of(bibles.get(name)) for name in speaking if bibles.get(name)},
        "continuity": {
            key: continuity.get(key)
            for key in (
                "episode_number",
                "summary",
                "threads_continued",
                "threads_closed",
                "threads_opened",
                "recurring",
            )
        },
        "previously": {
            "summaries": [
                {
                    key: item.get(key)
                    for key in ("episode_number", "title", "business_date", "summary")
                }
                for item in (state.summaries_json if state else None) or []
            ],
            "open_threads": [
                {"id": thread.get("id"), "text": thread.get("text")}
                for thread in (state.threads_json if state else None) or []
            ],
            "recurring": list((state.recurring_json if state else None) or []),
        },
        "measured": {
            name: {k: v for k, v in check.items() if k != "reason"}
            for name, check in checks.items()
        },
        # What the checks only recommend and this episode is outside of (2026-10-13): hers to
        # decide, with the measure in words. Never shed by `fit_to_budget`: a few short lines.
        "recommendations": [
            {
                "check": name,
                **{
                    key: value
                    for key, value in checks[name].items()
                    if key not in ("reason", "passed", "advisory")
                },
            }
            for name in outside_recommendations(checks)
        ],
    }


def _dumps(facts: dict[str, Any]) -> str:
    return json.dumps(facts, ensure_ascii=False)


def _measured_verdicts_only(facts: dict[str, Any]) -> None:
    facts["measured"] = {name: {"passed": c.get("passed")} for name, c in facts["measured"].items()}


def _newest_summary_only(facts: dict[str, Any]) -> None:
    facts["previously"]["summaries"] = facts["previously"]["summaries"][-1:]


def _voices_without_phrases(facts: dict[str, Any]) -> None:
    for voice in facts["voices"].values():
        voice.pop("expressions", None)
        voice.pop("habits", None)


def _short_scenes(facts: dict[str, Any]) -> None:
    for beat in facts["beats"]:
        beat["scene"] = str(beat.get("scene") or "")[:240]


def _short_event_texts(facts: dict[str, Any]) -> None:
    for beat in facts["beats"]:
        for cited in beat["cites"]:
            if cited.get("what"):
                cited["what"] = str(cited["what"])[:200]


def _no_summaries(facts: dict[str, Any]) -> None:
    facts["previously"]["summaries"] = []
    facts["previously"]["recurring"] = []


def _no_voices(facts: dict[str, Any]) -> None:
    facts["voices"] = {}


#: What is shed, in this order, when the facts are over budget: what she needs least first.
#: The measured details repeat what the checks already decided; the older summaries and the
#: voices' phrases are background; the beats, their lines and their citations are never shed.
_TRIMS = (
    ("measured details", _measured_verdicts_only),
    ("older summaries", _newest_summary_only),
    ("voice phrases and habits", _voices_without_phrases),
    ("long scenes", _short_scenes),
    ("long event texts", _short_event_texts),
    ("all summaries", _no_summaries),
    ("voices", _no_voices),
)


def fit_to_budget(facts: dict[str, Any], budget: int | None = None) -> str:
    """The facts as JSON within ``budget`` characters, shedding `_TRIMS` in order.

    Always whole JSON, and ``trimmed`` names what was shed so she knows it is not there. An
    episode whose beats alone exceed the budget is sent whole and marked ``over_budget``:
    the budget is a target, and a cut through the beats is exactly what v1 did wrong.
    """
    limit = FACTS_BUDGET if budget is None else budget
    text = _dumps(facts)
    if len(text) <= limit:
        return text
    fitted = copy.deepcopy(facts)
    fitted["trimmed"] = []
    for name, trim in _TRIMS:
        trim(fitted)
        fitted["trimmed"].append(name)
        text = _dumps(fitted)
        if len(text) <= limit:
            return text
    fitted["over_budget"] = True
    return _dumps(fitted)


def _held_to_her_rubric(verdict: EpisodeVerdict, director_name: str) -> EpisodeVerdict:
    """A PASS as her rubric allows it: all six scores, each 1-5, none below `RUBRIC_FLOOR`.

    A PASS missing a score, or scoring outside 1-5, is not a usable verdict (ReviewError: the
    draft stays unread and the next run asks again), because a PASS that did not score the
    payoff certified a payoff nobody looked at. A PASS her own scores put below the floor is
    her FAIL, with the low parts as the reasons and the notes for the rewrite. A FAIL needs
    no score: its reasons are the verdict.
    """
    scores = verdict.scores
    if verdict.verdict != "PASS":
        return verdict.model_copy(
            update={"scores": {k: v for k, v in scores.items() if 1 <= v <= 5}}
        )
    missing = [part for part in RUBRIC if part not in scores]
    outside = [part for part, value in scores.items() if not 1 <= value <= 5]
    if missing or outside:
        raise ReviewError(
            f"{director_name} a dat PASS fără rubrica întreagă"
            + (f" (lipsesc: {', '.join(missing)})" if missing else "")
            + (f" (în afara 1-5: {', '.join(outside)})" if outside else "")
        )
    low = [f"{part} {scores[part]}/5" for part in RUBRIC if scores[part] < RUBRIC_FLOOR]
    if not low:
        return verdict
    because = f"notele Directorului sub {RUBRIC_FLOOR}: {', '.join(low)}"
    return verdict.model_copy(
        update={
            "verdict": "FAIL",
            "reasons": [because, *verdict.reasons],
            "notes": (verdict.notes or f"Rescrie părțile notate slab ({', '.join(low)})."),
        }
    )


def _approve(session: Session, episode: StoryEpisode, story: str, correlation: str) -> None:
    """The approval a PASS gets under the channel's policy: APPROVED as the Director's, her
    one-sentence story as the note, the event, and the serial's canon advanced."""
    episode.status = "APPROVED"
    episode.reviewed_by = "director"
    episode.notes = (story or None) and story[:2000]
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


def review_episode(
    engine: Engine,
    registry: ProviderRegistry | None,
    episode_id: str,
    correlation_id: str = "",
    language: str = "en",
    approve: bool = True,
) -> dict[str, Any]:
    """The Director's verdict on one drafted episode; recorded, and acted on under policy.

    ``approve=False`` (2026-10-11) records a PASS and leaves the episode a DRAFT with the
    review on it, for the editorial judgement to run before the approval (`judged_review`;
    `approve_reviewed_episode` then approves under the same policy). A FAIL is REJECTED either
    way: the judgement reads only what the checks and her reading passed.
    """
    correlation = correlation_id or str(uuid4())
    with Session(engine) as session:
        episode = session.get(StoryEpisode, episode_id)
        if episode is None:
            raise ReviewError("Episodul nu există")
        if episode.status != "DRAFT":
            raise ReviewError(f"Episodul este deja {work_status(episode.status)}")
        if episode.review_json:
            raise ReviewError("Episodul a fost deja citit de Director")
        director = agent_for_role(session, REVIEWER_ROLE)
        if director is None:
            raise ReviewError("Niciun Director activ care să citească episodul")
        director_id, director_name = director.id, director.display_name
        checks = episode_checks(session, episode, language)
        facts = review_facts(session, episode, checks)
        title = episode.title

    failed = failed_rules(checks)
    advised = outside_recommendations(checks)
    run_id: str | None = None
    if failed:
        reasons = [checks[name]["reason"] for name in failed if checks[name]["reason"]]
        verdict = EpisodeVerdict(
            verdict="FAIL",
            reasons=reasons,
            notes="; ".join(reasons),
            story="",
        )
    elif registry is not None and registry.registered_ids():
        prompt = (
            audience_language_line(language)
            + _INSTRUCTIONS
            + wrap_in_inert_boundary(
                # A line or a scene could hold the boundary's closing tag and end the data
                # early; it is broken up, as the showrunner's brief does with its events.
                fit_to_budget(facts).replace(
                    "</untrusted_source_evidence", "<\\/untrusted_source_evidence"
                ),
                "the-episode",
            )
        )
        result = run_agent_task(
            engine,
            registry,
            director_id,
            REVIEW_TASK,
            prompt,
            TEMPLATE_VERSION,
            correlation,
            summary=f"Citesc episodul «{title}» înainte de filmare.",
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
        verdict = _held_to_her_rubric(parsed, director_name)  # type: ignore[arg-type]
    else:
        raise ReviewError("Niciun model de limbaj: Directorul nu poate citi episodul")

    with Session(engine) as session, session.begin():
        episode = session.get(StoryEpisode, episode_id)
        assert episode is not None  # read above, in this same process
        may_approve = (
            verdict.verdict == "PASS" and approve and director_may_approve_episodes(session)
        )
        reviewed_at = utc_now()
        episode.review_json = {
            "verdict": verdict.verdict,
            "checks": checks,
            "reasons": list(verdict.reasons),
            "notes": verdict.notes,
            "story": verdict.story,
            "scores": dict(verdict.scores),
            "template_version": TEMPLATE_VERSION,
            "run_id": run_id,
            "model_used": run_id is not None,
            "reviewer_agent_id": director_id,
            "reviewed_at": reviewed_at,
            "approved_by_policy": may_approve,
            # A PASS waiting for the editorial judgement before the policy is asked.
            "held_for_judgement": verdict.verdict == "PASS" and not approve,
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
                "recommendations_outside": advised,
                "model_used": run_id is not None,
            },
            correlation,
        ).event_id
        if verdict.verdict == "FAIL":
            episode.status = "REJECTED"
            episode.notes = (verdict.notes or "; ".join(verdict.reasons)) or None
            # A FAIL the computed rules gave without her reading is signed by the checks
            # (2026-10-13): the cover and the list said «respins de Director» for a verdict
            # she never gave («The Ninth Rewrite», 9 din 10 verificări, fără rubrică).
            by = "director" if run_id is not None else "checks"
            episode.reviewed_by = by
            episode.event_id = append_event(
                session,
                "story.episode_rejected",
                "story_episode",
                episode.id,
                3,
                {"log_id": episode.log_id, "reviewed_by": by},
                correlation,
            ).event_id
            showrunner = agent_for_role(session, PREFERRED_SHOWRUNNER_ROLE)
            if showrunner is not None and episode.notes:
                post_message(
                    session,
                    intent="HANDOFF",
                    subject=f"Rescris: {title}",
                    body={"episode_id": episode.id, "verdict": "FAIL"},
                    body_text=f"{episode.notes} — {director_name}",
                    from_agent_id=director_id,
                    to_agent_id=showrunner.id,
                    # The run is on the episode's review record; the letter is the note.
                    run_id=None,
                    correlation_id=correlation,
                )
        elif may_approve:
            _approve(session, episode, verdict.story, correlation)
        remember(
            session,
            memory_class="AGENT_OPINION",
            content=(
                f"{verdict.verdict} for the episode “{title}”"
                + (f": {'; '.join(verdict.reasons)}" if verdict.reasons else ".")
            ),
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
        "scores": dict(verdict.scores),
        "run_id": run_id,
        "model_used": run_id is not None,
        "approved_by_policy": status == "APPROVED",
    }


# ----------------------------------------------------------------- the editorial judgement
#
# 2026-10-11, the Owner's card of 23:30. Everything above measures the episode and asks her
# whether it tells the truth; nothing asked whether a stranger would watch it. The judgement
# below does, after her PASS and before the approval, through `app.agents.editorial_judgement`.


def _retire(
    session: Session,
    episode: StoryEpisode,
    note: str,
    correlation: str,
    *,
    superseded_by: str | None = None,
) -> None:
    """A DRAFT retired as the Director's REJECTED, with the reason as its note."""
    episode.status = "REJECTED"
    episode.notes = note[:2000] or None
    episode.reviewed_by = "director"
    episode.event_id = append_event(
        session,
        "story.episode_rejected",
        "story_episode",
        episode.id,
        3,
        {"log_id": episode.log_id, "reviewed_by": "director", "superseded_by": superseded_by},
        correlation,
    ).event_id


def retire_episode(
    engine: Engine,
    episode_id: str,
    note: str,
    correlation_id: str = "",
    *,
    superseded_by: str | None = None,
) -> None:
    """Retire a DRAFT the judgement will not ship: a version that passed her reading and scored
    lower than the one that ships, or a rewrite she could not read. Left a DRAFT, the first
    would wait for the Owner beside the shipped one (`unfinished_episodes`, «owner»), the
    second would be read and approved by a later run beside it («review»): two episodes for
    one day, and the canon number claimed twice."""
    with Session(engine) as session, session.begin():
        episode = session.get(StoryEpisode, episode_id)
        if episode is None or episode.status != "DRAFT":
            return
        _retire(session, episode, note, correlation_id or str(uuid4()), superseded_by=superseded_by)


def approve_reviewed_episode(engine: Engine, episode_id: str, correlation_id: str = "") -> dict:
    """The approval a held PASS gets (`review_episode`, ``approve=False``) once the judgement
    chose it: under the channel's policy it is APPROVED as the Director's and canon advances;
    without the policy it stays a DRAFT with its review, for the Owner's `decide_episode`.
    Returns ``{"episode_id", "status", "approved_by_policy"}``; an episode that is not a held
    PASS is left as it is."""
    correlation = correlation_id or str(uuid4())
    with Session(engine) as session, session.begin():
        episode = session.get(StoryEpisode, episode_id)
        if episode is None:
            raise ReviewError("Episodul nu există")
        review = dict(episode.review_json or {})
        if episode.status != "DRAFT" or review.get("verdict") != "PASS":
            return {
                "episode_id": episode_id,
                "status": episode.status,
                "approved_by_policy": bool(review.get("approved_by_policy")),
            }
        may_approve = director_may_approve_episodes(session)
        episode.review_json = {
            **review,
            "approved_by_policy": may_approve,
            "held_for_judgement": False,
        }
        if may_approve:
            _approve(session, episode, str(review.get("story") or ""), correlation)
        return {
            "episode_id": episode_id,
            "status": episode.status,
            "approved_by_policy": may_approve,
        }


def episode_as_text(episode: StoryEpisode) -> tuple[str, dict[str, Any]]:
    """The episode as a viewer meets it, for the editorial judgement: the title, then each
    beat's part, room and scene in a bracket and its lines as «Name: words»; beside it the small
    context she may use (the logline, who speaks, the parts, the seconds). The event ids, the
    checks and the serial's memory are not here: a stranger has none of them, and the stranger
    is who she judges for."""
    beats = list(episode.beats_json or [])
    lines_by_beat = [beat_lines(beat) for beat in beats]
    rows = [str(episode.title or "").strip()]
    speaking: list[str] = []
    for index, (beat, lines) in enumerate(zip(beats, lines_by_beat, strict=True), start=1):
        part = str(beat.get("part") or "").upper()
        where = str(beat.get("location") or "").strip()
        scene = " ".join(str(beat.get("scene") or "").split())
        head = f"[{beat.get('beat_number') or index}. {part}" + (f" — {where}]" if where else "]")
        rows.append(f"\n{head} {scene}".rstrip())
        for line in lines:
            speaker = str(line.get("speaker") or "Narrator")
            direction = str(line.get("direction") or "").strip()
            said = f" ({direction})" if direction else ""
            rows.append(f"{speaker}{said}: {str(line.get('text') or '').strip()}")
        speaking += [name for name in speakers_of(lines) if name not in speaking]
    words = sum(_words(spoken_text(lines)) for lines in lines_by_beat)
    continuity = episode.continuity_json or {}
    context = {
        "title": episode.title,
        "logline": continuity.get("logline"),
        "summary": continuity.get("summary"),
        "episode_number": continuity.get("episode_number"),
        "beats": len(beats),
        "parts": [beat.get("part") for beat in beats],
        "speakers": speaking,
        "spoken_words": words,
        "seconds": round(words / WORDS_PER_SECOND, 1),
    }
    return "\n".join(rows), context


def _version_of(episode: StoryEpisode, review: dict[str, Any] | None, note: str = "") -> Version:
    """One stored episode as the loop reads it: eligible when her reading passed it."""
    text, context = episode_as_text(episode)
    passed = review is not None and review.get("verdict") == "PASS"
    reasons = "; ".join(str(r) for r in (review or {}).get("reasons") or [])
    return Version(
        id=episode.id,
        text=text,
        context=context,
        eligible=passed,
        note=note or ("" if passed else reasons),
        title=str(episode.title or ""),
    )


def judged_review(
    engine: Engine,
    registry: ProviderRegistry | None,
    episode_id: str,
    correlation_id: str = "",
    language: str = "en",
    rounds: int | None = None,
) -> dict[str, Any]:
    """`review_episode`, then the Director's editorial judgement, then the approval (2026-10-11).

    The reading is held (``approve=False``). A FAIL is returned as it is: REJECTED, for the
    stage's own rewrite. A PASS is read again as a stranger would meet it and scored; below the
    bar the showrunner rewrites on her brief (`write_episode`, ``judged=True``: a new DRAFT,
    measured by every check above and read by her again, so a rewrite that breaks a check is
    REJECTED and scored only for the record), up to ``rounds`` versions
    (`Settings.editorial_rounds`), and the best-scored version that passed her reading ships:
    approved under the policy, the other versions retired, every version an `editorial.judged`
    event, the chosen version's scores on its review_json, and one letter to the Owner only
    when it ships below the bar. A judgement she could not give ships the reviewed draft as it
    is, unjudged: nothing stops for quality.

    Returns the review of the version that ships, with ``episode_id`` (not always the one read
    first), its ``status`` after the approval, and ``editorial`` (the loop's record; None when
    the reading failed).
    """
    correlation = correlation_id or str(uuid4())
    review = review_episode(engine, registry, episode_id, correlation, language, approve=False)
    if review["verdict"] != "PASS":
        return {**review, "editorial": None}
    with Session(engine) as session:
        episode = session.get(StoryEpisode, episode_id)
        assert episode is not None  # reviewed above, in this same process
        log_id = episode.log_id
        director = agent_for_role(session, REVIEWER_ROLE)
        director_id = director.id if director is not None else None
        first = _version_of(episode, review)
    reviews: dict[str, dict[str, Any]] = {episode_id: review}
    latest = {"id": episode_id}

    def rewrite(brief: str, number: int) -> Version | None:
        assert registry is not None  # a PASS with a model's reading is behind every judgement
        try:
            written = write_episode(
                engine,
                registry,
                log_id,
                str(uuid4()),
                language=language,
                notes=brief,
                rewrite_of=latest["id"],
                judged=True,
            )
        except (DraftRefused, StoryError) as exc:
            # Not an episode, a stranger cast, an event that did not happen, or no answer:
            # nothing was stored, and the loop ships the best it has.
            logger.info(
                "editorial_rewrite_not_stored",
                extra={"log_id": log_id, "version": number, "reason": str(exc)[:200]},
            )
            return None
        new_id = str(written["episode"]["id"])
        latest["id"] = new_id
        try:
            verdict = review_episode(
                engine, registry, new_id, str(uuid4()), language, approve=False
            )
        except ReviewError as exc:
            # Her reading gave no verdict. Left a DRAFT with no review, a later run would read
            # and approve it beside the version that ships here (`unfinished_episodes`): it is
            # retired with the reason, and scored only for the record.
            retire_episode(
                engine,
                new_id,
                f"Rescrierea nu a putut fi citită de Director: {exc}",
                correlation,
            )
            with Session(engine) as session:
                row = session.get(StoryEpisode, new_id)
                assert row is not None
                return _version_of(row, None, note=str(exc))
        reviews[new_id] = verdict
        with Session(engine) as session:
            row = session.get(StoryEpisode, new_id)
            assert row is not None
            return _version_of(row, verdict)

    outcome = editorial_loop(
        engine,
        registry,
        kind=SERIAL_EPISODE,
        first=first,
        rewrite=rewrite,
        correlation_id=correlation,
        rounds=rounds,
    )
    shipped = outcome.shipped
    shipped_id = shipped.version.id
    with Session(engine) as session, session.begin():
        record_rounds(session, outcome, "story_episode", correlation)
        for item in outcome.rounds:
            row = session.get(StoryEpisode, item.version.id)
            if row is None:
                continue
            own = outcome.record() if item.version.id == shipped_id else outcome.record_for(row.id)
            row.review_json = {**(row.review_json or {}), "editorial": own}
            if item.version.id != shipped_id and row.status == "DRAFT":
                scored = f"{item.judgement.total}/50" if item.judgement else "necitită"
                chosen = f"{shipped.judgement.total}/50" if shipped.judgement else "necitită"
                _retire(
                    session,
                    row,
                    f"Judecata editorială a ales versiunea {shipped.number} "
                    f"(«{shipped.version.title}», {chosen}) în locul acesteia ({scored}).",
                    correlation,
                    superseded_by=shipped_id,
                )
        letter_to_owner(
            session,
            outcome,
            title=shipped.version.title,
            director_id=director_id,
            correlation_id=correlation,
        )
    approval = approve_reviewed_episode(engine, shipped_id, correlation)
    return {
        **reviews[shipped_id],
        "episode_id": shipped_id,
        "status": approval["status"],
        "approved_by_policy": approval["approved_by_policy"],
        "editorial": outcome.record(),
    }
