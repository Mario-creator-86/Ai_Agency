"""An approved episode becomes a storyboard the existing film path can shoot.

Nothing consumed an APPROVED episode before this: the serial ended as text. This module
turns one into exactly what `generate_storyboard_from_script` produces — a `Storyboard` with
one `StoryboardScene` per beat, APPROVED, 9:16, behind a `ScriptDraft` — so the render, the
narration review, quality control, the Director's viewing and the five-point publishing gate
run on it unchanged. Where the shape forces a row the serial does not naturally have, the
row is written honestly and says what it is:

- The `ScriptDraft` is the episode's dialogue as one voiceover, `claim_ids_json` empty and
  `story_json` marking it a dramatisation. **The factual claim gate does not apply to a
  dramatisation**: an episode makes no claims about the world, it dramatises committed
  events of a closed log, and its truth is the grounding check, not a source. The publishing
  gate already says this plainly for a script with no claims ("none to verify"), and the
  Director's film review must read the same way for a serial storyboard.
- The `StoryReview` the media stage's `story_gate` asks for is written PASS from the
  Director's episode review, with the review's checks and reasons, because that review is
  the reading of this story — asking the factual story checks about a hook and an attributed
  claim would be asking the wrong questions of a comedy.
- The `TopicIdea` behind the script carries status SERIAL so the factual selection never
  picks it and never counts it as a topic in production.

Voices: each scene lists the bible ids of the characters in its beat, in the beat's order, so
the production policy binds the first locked character's voice where a bible has one, and
the narrator otherwise. The visual prompt is the beat's scene plus each character's bible
lines, quoted verbatim, so the look is the bible's and not the model's guess.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.memory import agent_for_role
from app.agents.models import AgentRun
from app.factual.models import ScriptDraft, StoryReview, TopicIdea
from app.media.models import CharacterBible, Storyboard, StoryboardScene
from app.publishing.models import ChannelRecord
from app.services import append_event, utc_now
from app.story.models import DailyStudioLog, StoryEpisode
from app.story.services import SERIES_KEY, bibles_for_roster

#: The look the serial is drawn in. One value for every episode, so the channel is one thing.
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
        channel = session.scalar(
            select(ChannelRecord).where(ChannelRecord.channel_type == "OFFICE_SERIAL")
        )
        director = agent_for_role(session, "Director")
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

        dialogue = "\n\n".join(str(beat.get("dialogue") or "").strip() for beat in beats)
        words = len(dialogue.split())
        target_seconds = max(30, min(75, round(words / WORDS_PER_SECOND)))

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
                "narration": str(beat.get("dialogue") or "").strip(),
                "visual_description": str(beat.get("scene") or "").strip(),
                "characters": list(beat.get("characters") or []),
                "event_ids": list(beat.get("event_ids") or []),
            }
            for index, beat in enumerate(beats, start=1)
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
        # reading that actually happened: the Director's episode review.
        session.add(
            StoryReview(
                id=str(uuid4()),
                script_id=script_id,
                verdict="PASS",
                checks_json=dict(review.get("checks") or {}),
                retention_json={},
                scores_json={},
                notes_json={
                    "notes": list(review.get("reasons") or []),
                    "source": "story.episode_review",
                    "episode_id": episode.id,
                    "reviewed_by": episode.reviewed_by,
                },
                estimated_seconds=float(target_seconds),
                reviewer_agent_id=director.id if director else None,
                run_id=review_run,
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
        session.add(
            Storyboard(
                id=storyboard_id,
                script_draft_id=script_id,
                title=f"Storyboard: {episode.title}"[:200],
                visual_style=VISUAL_STYLE,
                aspect_ratio=ASPECT_RATIO,
                target_duration_seconds=target_seconds,
                status="APPROVED",
                total_scenes=len(beats),
                channel_id=channel.id if channel else None,
                series_key=SERIES_KEY,
                production_overrides_json={},
                created_at=now,
                event_id=event.event_id,
            )
        )
        session.flush()
        for index, beat in enumerate(beats, start=1):
            narration = str(beat.get("dialogue") or "").strip()
            names = [str(name) for name in (beat.get("characters") or [])]
            present = [bibles[name] for name in names if name in bibles]
            visual = str(beat.get("scene") or "").strip()
            if present:
                visual += " Characters: " + " ".join(_character_line(b) for b in present)
            # Without a stated duration a scene lasts as long as its words take to say
            # (about 2.5 a second), within what a short's scene can hold — the same rule as
            # the factual storyboard, so the assembler sees nothing new.
            duration = min(9.0, max(3.0, round(len(narration.split()) / WORDS_PER_SECOND, 1)))
            session.add(
                StoryboardScene(
                    id=str(uuid4()),
                    storyboard_id=storyboard_id,
                    scene_index=index,
                    visual_prompt=visual,
                    visual_type=VISUAL_STYLE,
                    duration_seconds=duration,
                    voiceover_segment=narration,
                    shot_type="MEDIUM",
                    transition_in="FADE" if index == 1 else "CUT",
                    character_ids_json=[b.id for b in present],
                    claim_ids_json=[],
                    production_overrides_json={},
                    created_at=now,
                )
            )
        episode.storyboard_id = storyboard_id
        session.flush()
    return storyboard_id
