"""An approved episode becomes a storyboard the existing film path can shoot.

Nothing consumed an APPROVED episode before this: the serial ended as text. This module
turns one into exactly what `generate_storyboard_from_script` produces — a `Storyboard` with
one `StoryboardScene` per beat, APPROVED, 9:16, behind a `ScriptDraft` — so the render, the
narration review, quality control, the Director's viewing and the five-point publishing gate
run on it unchanged. Where the shape forces a row the serial does not naturally have, the
row is written honestly and says what it is:

- The `ScriptDraft` is the episode's spoken words as one voiceover, `claim_ids_json` empty and
  `story_json` marking it a dramatisation. **The factual claim gate does not apply to a
  dramatisation**: an episode makes no claims about the world, it dramatises committed
  events of a closed log, and its truth is the grounding check, not a source. The publishing
  gate already says this plainly for a script with no claims ("none to verify"), and the
  Director's film review must read the same way for a serial storyboard.
- The `StoryReview` the media stage's `story_gate` asks for is written PASS from the
  Director's episode review, with the review's checks and reasons, because that review is
  the reading of this story — asking the factual story checks about a hook and an attributed
  claim would be asking the wrong questions of a comedy. An episode the Owner approved that
  she never read is written PASS as his approval, with no reviewer, no run and no checks,
  and the reason says so (`_story_gate_record`, S10).
- The `TopicIdea` behind the script carries status SERIAL so the factual selection never
  picks it and never counts it as a topic in production.

Voices: each scene lists the bible ids of the characters in its beat, the speakers first in
the order they speak. What a voice reads is the lines' words alone (`app.story.lines`):
measured before the lines existed (2026-09-24), the beat's free dialogue went whole to one
voice, and "Sarah: (sighs)" was read aloud. A v2 episode is read the same way, the labels the
roster knows taken off and the stage directions out. Each scene's lines, with their speakers
and directions, are kept on the script's `scenes_json`, with `speaker_bibles` naming the
bible each speaker has: the render speaks one take per speaker in that character's voice
(`app.media.speaker_voices`, S7), and a scene whose lines are gone is read whole by the
voice the production policy binds for it.

Pictures (S8): measured before it (2026-09-24), the serial's style was the label
"CHARACTER_ANIMATION", which no prompt carried, and the vendor was handed the showrunner's
raw scene line. Now the storyboard's visual bible is the series' one look
(`app.media.series_look`, a proposal in config/serial_series_look.json, never decided per
episode), and every shot prompt opens with its style block, then the beat's room, the camera,
the people in frame as their bibles describe them, and the action. The storyboard composes
these itself through the prompt agent's own path (`write_shot_prompts`, no model), so a
serial shot never reaches a vendor without the look; `describe_serial_shots` then has the
video editor's model write each shot from the beat, once per look version.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.memory import agent_for_role
from app.agents.models import AgentRun
from app.factual.models import ScriptDraft, StoryReview, TopicIdea
from app.media.models import CharacterBible, Storyboard, StoryboardScene
from app.media.montage import beat_tag, serial_shots
from app.media.pause_plan import RowSpec, freeze_rows, serial_lines, serial_row_sides
from app.media.pauses import active_rules as active_pause_rules
from app.media.prompt_agent import PromptError, write_shot_prompts
from app.media.series_look import (
    PART_PURPOSES,
    SHOT_TYPES,
    load_series_look,
    serial_shot_size,
    series_bible,
)
from app.publishing.models import ChannelRecord
from app.services import append_event, utc_now
from app.story.lines import NameBook, beat_lines, speakers_of, spoken_text
from app.story.locations import location_name, studio_locations
from app.story.models import DailyStudioLog, StoryEpisode
from app.story.services import SERIES_KEY, bibles_for_roster

logger = logging.getLogger("studio.media.serial_storyboard")

#: The storyboard's style label. The look itself is the series' style block
#: (`app.media.series_look`), which every shot prompt carries; this label is what the plan
#: and the page show.
VISUAL_STYLE = "CHARACTER_ANIMATION"
ASPECT_RATIO = "9:16"
WORDS_PER_SECOND = 2.5
TOPIC_STATUS = "SERIAL"


class SerialStoryboardError(ValueError):
    """The episode cannot become a storyboard; nothing was written."""


def _character_line(bible: CharacterBible) -> str:
    """The bible's own words for how a character looks, as the prompt agent quotes them."""
    return (
        f"{bible.canonical_name}: {bible.face_hair_desc}. {bible.outfit_desc}. {bible.props_desc}"
    ).strip()


#: The reason on the record of an episode the Owner approved without the Director's reading.
OWNER_ONLY_NOTE = (
    "Aprobat de Owner fără recenzia Directorului: episodul nu a fost citit de ea înainte de "
    "aprobare. Verificările calculate ale Directorului nu au rulat pe el."
)


def _story_gate_record(
    episode: StoryEpisode,
    review: dict[str, Any],
    review_run: str | None,
    director_id: str | None,
) -> dict[str, Any]:
    """The story gate's record for an approved episode, saying who actually read it.

    Measured on the code of 2026-09-24: every serial storyboard wrote PASS with the
    Director as reviewer, so an episode the Owner approved straight from DRAFT read as if she
    had passed it. The verdict stays PASS: it is the only value the gate and the table's
    constraint accept, and the Owner's approval is what lets the episode be filmed (a new
    verdict would need a migration and the application's head check). Everything else on
    the row is the truth:

    - her review passed it (whoever approved it after): her checks, her reasons, her run,
      and she is the reviewer;
    - she never read it, or her reading is not a PASS: no reviewer, no run, no checks, and
      the reason says the Owner approved it without her review.
    """
    approved_by = episode.reviewed_by or "owner"
    base = {"episode_id": episode.id, "reviewed_by": approved_by, "approved_by": approved_by}
    if review.get("verdict") == "PASS":
        return {
            "verdict": "PASS",
            "checks_json": dict(review.get("checks") or {}),
            "notes_json": {
                **base,
                "notes": list(review.get("reasons") or []),
                "source": "story.episode_review",
                "director_review": "PASS",
            },
            "reviewer_agent_id": director_id,
            "run_id": review_run,
        }
    notes = [OWNER_ONLY_NOTE]
    if review.get("verdict"):
        notes.append(f"Recenzia Directorului a fost {review['verdict']}.")
    return {
        "verdict": "PASS",
        "checks_json": {},
        "notes_json": {
            **base,
            "notes": notes,
            "source": "owner_approval",
            "director_review": review.get("verdict"),
            "director_review_run_id": review_run,
        },
        "reviewer_agent_id": None,
        "run_id": None,
    }


def storyboard_from_episode(engine: Engine, episode_id: str, correlation_id: str) -> str:
    """Build the storyboard for one APPROVED episode and return its id. Once per episode."""
    now = utc_now()
    with Session(engine) as session, session.begin():
        episode = session.get(StoryEpisode, episode_id)
        if episode is None:
            raise SerialStoryboardError("Episodul nu există")
        if episode.status != "APPROVED":
            raise SerialStoryboardError(
                f"Episodul este {episode.status.lower()}; doar un episod aprobat se filmează"
            )
        if episode.storyboard_id:
            existing = session.get(Storyboard, episode.storyboard_id)
            if existing is not None and existing.status != "REJECTED":
                return existing.id
        log = session.get(DailyStudioLog, episode.log_id)
        roster = list(log.roster_json or []) if log else []
        bibles = bibles_for_roster(session, roster)
        names = NameBook(roster, bibles)
        locations = studio_locations(session, roster)
        channel = session.scalar(
            select(ChannelRecord).where(ChannelRecord.channel_type == "OFFICE_SERIAL")
        )
        director = agent_for_role(session, "Director")
        look = load_series_look()
        beats = list(episode.beats_json or [])
        if not beats:
            raise SerialStoryboardError("Episodul nu are niciun beat")
        review = episode.review_json if isinstance(episode.review_json, dict) else {}
        # The review's run is linked only while the run row exists: after a history reset the
        # review stays on the episode but the run is gone, and a dangling key would stop the
        # storyboard for a link nobody reads.
        review_run = review.get("run_id")
        if review_run and session.get(AgentRun, review_run) is None:
            review_run = None

        lines = [beat_lines(beat, names) for beat in beats]
        # «Pauza vocii» (the Owner, 2026-10-16): a writer's «(beat)» marked where it stood,
        # at most one a beat and never before the punchline, and each line named for the
        # voice take it is said in (`pause_plan.serial_lines`).
        pause_rules = active_pause_rules()
        if pause_rules is not None:
            lines = serial_lines(lines, [beat.get("part") for beat in beats], pause_rules)
        spoken = [spoken_text(said) for said in lines]
        dialogue = "\n\n".join(spoken)
        words = len(dialogue.split())
        # 90-180 s since 2026-10-16 (the Owner's format; the review holds the words under
        # the Short's wall).
        target_seconds = max(90, min(180, round(words / WORDS_PER_SECOND)))
        # The montage (the Owner, 2026-10-16): a beat cut into shots with its dialogue — one
        # per speaker's run, a reaction shot on the listener when a run is long — each an
        # ordinary scene of the storyboard and of the script's `scenes_json`, tagged with the
        # beat it came from (`montage.serial_shots`, `montage.beat_tag`).
        cuts: list[dict[str, Any]] = []
        for number, beat in enumerate(beats, start=1):
            for shot in serial_shots(
                lines[number - 1], number, part=beat.get("part"), first_beat=number == 1
            ):
                cuts.append({"beat": number, "source": beat, **shot})

        topic_id, script_id, storyboard_id = str(uuid4()), str(uuid4()), str(uuid4())
        session.add(
            TopicIdea(
                id=topic_id,
                title=episode.title[:200],
                topic="Serialul de birou",
                angle=f"Episodul serialului pentru ziua {log.business_date if log else '?'}",
                target_audience="general",
                novelty_score=1.0,
                status=TOPIC_STATUS,
                decided_by=episode.reviewed_by,
                decision_notes="Dramatizare a jurnalului zilei; nu este un subiect factual.",
                created_at=now,
            )
        )
        session.flush()
        scenes_json = [
            {
                "scene_index": index,
                "narration": spoken_text(cut["lines"]),
                "visual_description": str(cut["source"].get("scene") or "").strip(),
                "characters": list(cut["source"].get("characters") or []),
                "event_ids": list(cut["source"].get("event_ids") or []),
                "lines": list(cut["lines"]),
                # Which bible speaks each line: the render's takes are spoken in the voice
                # of the character, not of the scene.
                "speaker_bibles": {
                    name: bibles[name].id for name in speakers_of(cut["lines"]) if name in bibles
                },
                "part": cut["source"].get("part"),
                "location": cut["source"].get("location"),
                # The room as the shot prompts name it, and who stands in the background.
                "location_name": (
                    location_name(cut["source"]["location"], locations)
                    if cut["source"].get("location")
                    else ""
                ),
                "background": [str(name) for name in cut["source"].get("background") or []],
                # The beat this shot was cut from, and which of its shots it is.
                "beat": (
                    beat_tag(cut["beat"], cut["shot"], cut["of"], cut.get("size"), on=cut.get("on"))
                    if int(cut["of"]) > 1 or cut.get("size")
                    else None
                ),
            }
            for index, cut in enumerate(cuts, start=1)
        ]
        session.add(
            ScriptDraft(
                id=script_id,
                topic_id=topic_id,
                version=1,
                title=episode.title[:200],
                target_duration_seconds=target_seconds,
                voiceover_full_text=dialogue,
                scenes_json=scenes_json,
                status="APPROVED",
                claim_ids_json=[],
                unverified_claim_ids_json=[],
                story_json={
                    "kind": "office_serial_episode",
                    "episode_id": episode.id,
                    "log_id": episode.log_id,
                    "episode_number": (episode.continuity_json or {}).get("episode_number"),
                    "grounded_event_ids": list(episode.grounded_event_ids_json or []),
                    "factual_gate": (
                        "not applicable: a dramatisation of committed events makes no claims"
                    ),
                },
                created_at=now,
            )
        )
        session.flush()
        # The story gate the media stage asks before spending anything, satisfied by the
        # reading that actually happened, and recorded as that reading (S10).
        session.add(
            StoryReview(
                id=str(uuid4()),
                script_id=script_id,
                **_story_gate_record(
                    episode, review, review_run, director.id if director else None
                ),
                retention_json={},
                scores_json={},
                estimated_seconds=float(target_seconds),
                created_at=now,
            )
        )
        event = append_event(
            session,
            "media.storyboard_created",
            "storyboard",
            storyboard_id,
            1,
            {
                "script_draft_id": script_id,
                "title": episode.title[:200],
                "visual_style": VISUAL_STYLE,
                "aspect_ratio": ASPECT_RATIO,
                "scene_count": len(beats),
                "episode_id": episode.id,
            },
            correlation_id,
        )
        board = Storyboard(
            id=storyboard_id,
            script_draft_id=script_id,
            title=f"Storyboard: {episode.title}"[:200],
            visual_style=VISUAL_STYLE,
            aspect_ratio=ASPECT_RATIO,
            target_duration_seconds=target_seconds,
            status="APPROVED",
            total_scenes=len(cuts),
            channel_id=channel.id if channel else None,
            series_key=SERIES_KEY,
            production_overrides_json={},
            # The series' one look, read-only: an episode never decides its own.
            visual_bible_json=series_bible(look, ASPECT_RATIO),
            created_at=now,
            event_id=event.event_id,
        )
        session.add(board)
        session.flush()
        pause_rows: list[RowSpec] = []
        for index, cut in enumerate(cuts, start=1):
            beat = cut["source"]
            narration = spoken_text(cut["lines"])
            speakers = speakers_of(cut["lines"])
            # A reaction shot is on the listener: first in the cast, so the still is theirs.
            listener = [str(cut["on"])] if cut.get("size") == "reaction" and cut.get("on") else []
            cast = listener + [name for name in speakers if name not in listener]
            cast += [str(name) for name in (beat.get("characters") or []) if name not in cast]
            present = [bibles[name] for name in cast if name in bibles]
            visual = str(beat.get("scene") or "").strip()
            if beat.get("location"):
                visual = f"{location_name(beat['location'], locations)}. {visual}"
            if present:
                visual += " Characters: " + " ".join(_character_line(b) for b in present)
            if look.get("block"):
                # Replaced by the composed shot below; the look opens even this first draft.
                visual = f"{look['block']} {visual}"
            # Without a stated duration a scene lasts as long as its words take to say
            # (about 2.5 a second), within what a short's scene can hold — the same rule as
            # the factual storyboard, so the assembler sees nothing new.
            duration = min(9.0, max(3.0, round(len(narration.split()) / WORDS_PER_SECOND, 1)))
            # The camera varies across the episode by the beat's part, and across a beat by
            # the montage's cut; the prompt pass below writes the same size into the shot.
            size = str(cut.get("size") or "") or serial_shot_size(
                beat.get("part"), cut["beat"], len(speakers)
            )
            if size not in SHOT_TYPES:
                size = serial_shot_size(beat.get("part"), cut["beat"], len(speakers))
            tag = (
                beat_tag(cut["beat"], cut["shot"], cut["of"], size, on=cut.get("on"))
                if int(cut["of"]) > 1 or cut.get("size")
                else None
            )
            row = StoryboardScene(
                id=str(uuid4()),
                storyboard_id=storyboard_id,
                scene_index=index,
                visual_prompt=visual,
                visual_type=VISUAL_STYLE,
                duration_seconds=duration,
                voiceover_segment=narration,
                shot_type=SHOT_TYPES[size],
                story_purpose=PART_PURPOSES.get(str(beat.get("part") or "").lower()),
                transition_in="FADE" if index == 1 else "CUT",
                character_ids_json=[b.id for b in present],
                claim_ids_json=[],
                production_overrides_json={},
                prompt_json={"beat": tag} if tag else None,
                created_at=now,
            )
            session.add(row)
            if pause_rules is not None:
                sides, runs = serial_row_sides(cut["lines"], beat=int(cut["beat"]))
                pause_rows.append(RowSpec(row=row, sides=sides, lines=runs))
        # Every join of the episode classed and timed from each voice's own pauses, fitted
        # under the channel's wall and frozen on its row before anything is bought
        # (`pause_plan.freeze_rows`).
        if pause_rules is not None:
            freeze_rows(session, board, pause_rows, serial=True, rules=pause_rules)
        episode.storyboard_id = storyboard_id
        session.flush()
    # Every shot composed with the series' look, through the prompt agent's own path and with
    # no model: the raw scene line above never reaches a vendor. A model's description, when
    # there is one, comes after (`describe_serial_shots`).
    try:
        write_shot_prompts(engine, None, storyboard_id, correlation_id)
    except PromptError as exc:
        logger.info("serial_shots_not_composed", extra={"reason": str(exc)[:160]})
    return storyboard_id


def _registered(registry: Any) -> bool:
    try:
        return registry is not None and bool(registry.registered_ids())
    except (AttributeError, TypeError):
        return False


def describe_serial_shots(
    engine: Engine, registry: Any, storyboard_id: str, correlation_id: str
) -> dict[str, Any]:
    """Have the video editor's model write each shot of a serial storyboard from its beat.

    Once per look version: shots a model already described under the current look are left
    as they are (``skipped``), and so are shots the studio composed when no model is
    registered. Shots composed under an older look, or never composed (a storyboard built
    before S8), are composed again, by the model when there is one. The model's failure is a
    degradation: `write_shot_prompts` keeps the studio's composition. Never raises for a
    refusal; returns ``{"skipped", "shots", ...}``.
    """
    look = load_series_look()
    version = look.get("version") if look.get("in_use") else None
    has_model = _registered(registry)
    with Session(engine) as session:
        packages = [
            dict(scene.prompt_json or {})
            for scene in session.scalars(
                select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
            )
        ]
    current = bool(packages) and all(
        "series_look_version" in p and p.get("series_look_version") == version for p in packages
    )
    by_model = current and all(p.get("from_model") for p in packages)
    if current and (by_model or not has_model):
        return {"storyboard_id": storyboard_id, "skipped": True, "shots": []}
    try:
        written = write_shot_prompts(
            engine, registry if has_model else None, storyboard_id, correlation_id
        )
    except PromptError as exc:
        logger.info("serial_shots_not_described", extra={"reason": str(exc)[:160]})
        return {"storyboard_id": storyboard_id, "skipped": True, "shots": [], "error": str(exc)}
    return {**written, "skipped": False}
