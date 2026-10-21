"""The Director watches the film before it goes out.

The Owner asked how a video with no story, in the wrong language, resting on one sourceless
claim, could be produced and published. The honest answer: every gate did its narrow job.
Quality control measured the file (decodable, 1080×1920, real images); the voice artist
checked pronunciation; the Publisher checked that the title described the content; the
factual gate saw a claim marked SUPPORTED and asked no further. Nobody asked whether it was
worth watching, and the Director only read her inbox after the upload.

This is the missing gate. Before anything reaches a channel, the Director reads the whole
film as data — the script and its claims with their sources, every scene's picture and
narration, what quality control measured, the audience language — and, when her model can
see and an encoder is at hand, looks at frames from the file itself. A few things are decided
without a model, because they are not matters of taste: a claim with no source is not a
fact; narration not in the audience's language does not go out; a film under forty words has
no story. Her verdict is a record (`editorial_review`), an event the ledger shows, and a
letter to each department that must change something. A REJECT closes the storyboard.

An episode of the office serial is read under a different brief (`is_serial_film`,
`instructions_for`). Measured on the first serial film: it was refused before any model for
resting on no claim, and the brief told her a film about the studio is REJECTED — both true
of a factual film, neither of a dramatisation, which makes no claims about the world and
needs no sources. The other verdicts that need no model (no script, too few words, the wrong
language) and the frames rule hold for both kinds.
"""

from __future__ import annotations

import base64
import json
import logging
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.identity import clipped
from app.agents.language import audience_language_line, language_name, looks_like_english
from app.agents.memory import agent_for_role, remember
from app.agents.messages import post_message
from app.agents.models import Agent, Capability, ModelCapability, Role
from app.factual.grounding import script_grounding
from app.factual.models import FactualClaim, ScriptDraft, SourceSnapshot, TopicIdea
from app.factual.sanitizer import wrap_in_inert_boundary
from app.media.models import (
    EditorialReview,
    MediaAsset,
    QualityControlReport,
    Storyboard,
    StoryboardScene,
    VideoRenderJob,
)
from app.media.montage import beat_of
from app.media.prompt_agent import (
    SCOPE_FACTUAL,
    SCOPE_SERIAL,
    reconcile_prompt_lessons,
    record_prompt_lesson,
)
from app.media.toolchain import find_ffmpeg
from app.providers.registry import ProviderRegistry
from app.services import append_event, utc_now
from app.wording import viewing_verdict

logger = logging.getLogger("studio.editorial")

EDITORIAL_TASK = "editorial_review"
#: v2 (2026-10-16, the montage): the frames are spread over the whole film (`frame_picks`) and
#: the note says which scenes they come from.
TEMPLATE_VERSION = "editorial-v2"
#: Under this many spoken words there is no story to tell, whatever the pictures.
MIN_WORDS = 40
FRAMES = 3
#: One frame per writer's scene, up to this many, spread over the whole film (`frame_picks`).
MAX_FRAMES = 8
FRAME_WIDTH = 480

DEPARTMENTS = {
    "ScriptWriter": "ScriptWriter",
    "VideoEditor": "VideoEditor",
    "VoiceArtist": "VoiceArtist",
    "Publisher": "Publisher",
    "LeadResearcher": "LeadResearcher",
}


class EditorialVerdict(BaseModel):
    model_config = ConfigDict(extra="ignore")
    verdict: str = Field(pattern="^(APPROVE|REJECT)$")
    story: str = Field(default="", max_length=400)
    reasons: list[str] = Field(default_factory=list, max_length=8)
    notes_for: dict[str, str] = Field(default_factory=dict)
    #: One general rule about how the picture models misread prompts, or empty: the only part
    #: of her verdict kept as a prompt lesson (review of 68fa0b4, 2026-10-12: the first sentence
    #: of her fix-it note to the Video Editor, about this one film, was kept as a rule). Never
    #: cut: one over 400 characters is a report, and the store refuses it whole.
    lesson: str = ""
    _clip_story = field_validator("story", mode="before")(clipped(400))

    @field_validator("lesson", mode="before")
    @classmethod
    def _no_lesson(cls, value: Any) -> Any:
        """«null» or no lesson is an empty one: the verdict is never refused for its lesson."""
        return "" if value is None else value


#: The office serial's series key and script kind, as `storyboard_from_episode` writes them
#: and the publish routing reads them (`SERIES_CHANNEL_TYPES`). Recognised here by the same
#: marks, so the film the Director judges as an episode is the film that goes to Channel B.
SERIAL_SERIES_KEY = "office_serial"
SERIAL_SCRIPT_KIND = "office_serial_episode"

#: What the Director judges, by the kind of film. The first serial film measured what the
#: single text could not say: a factual film is judged for what the viewer learns and the
#: source behind it, and "a film about the studio itself is REJECTED" was written for a
#: factual channel that must not turn into a diary; an episode of the serial IS the studio's
#: diary, a dramatisation that makes no claims and needs no sources (the words are the
#: episode review's, `app.story.review._INSTRUCTIONS`), and is judged for its story and its
#: people instead. The frames rule and the language rule are the same for both.
_FACTUAL_JUDGEMENT = (
    "the script and the claims it rests on with their sources",
    "does it tell one clear story with a hook and a point; is every sentence something a "
    "viewer learns, backed by a real source; is it in the audience's language",
    "A film about the studio itself, a film that only describes its own process, or narration "
    "nobody would understand is REJECTED.",
    "what the viewer learns",
)
_SERIAL_JUDGEMENT = (
    "the episode's script (its dialogue, beat by beat)",
    "is there one clear situation with a turn and a payoff; does each character sound like "
    "themselves and like a person, not a status report; is the humour in the situation rather "
    "than in explaining the studio; is it in the audience's language",
    "This film is an episode of the studio's own serial. A dramatisation is not a factual "
    "film: it makes no claims about the world and needs no sources, and you do not reject it "
    "for that or for being about the studio; judge the situation, the turn, the payoff, "
    "whether each character sounds like a person. Narration nobody would understand is still "
    "REJECTED.",
    "what the viewer follows",
)

_INSTRUCTIONS = (
    "You are the Director, and this is the last look before a film leaves the studio. Below "
    "is everything the film is, as data: the topic, {script_note}, each scene's picture and "
    "narration, what quality control measured{frames_note}. Judge it as the audience will: "
    "{judgement}; do the pictures show the story rather than decorate it — the frames are "
    "spread over the whole film, one from each scene named with them, and a blank field, "
    "stripes, noise or garbled writing in any of "
    "them means REJECT, however good the rest is (the studio burns its own captions — the "
    "narration's words, a few at a time — into the bottom of every frame: they are the "
    "film's subtitles, never writing in the picture and never a reason); is it worth their "
    "time. {nature} Return "
    'only JSON: {{"verdict": "APPROVE" | "REJECT", "story": "one sentence: {story_note}", '
    '"reasons": ["..."], "notes_for": {{"ScriptWriter": "...", "VideoEditor": "...", '
    '"VoiceArtist": "...", "Publisher": "..."}}, "lesson": "one general rule about how the '
    'picture models misread prompts, or empty"}} — notes only for departments that must '
    "change something. The lesson is kept for every next film's prompts: one rule, true of any "
    "film (no scene, shot or title of this one), or an empty string.\n"
)


def instructions_for(serial: bool, frames_note: str) -> str:
    """The Director's brief for one film: the factual reading, or the serial's."""
    script_note, judgement, nature, story_note = _SERIAL_JUDGEMENT if serial else _FACTUAL_JUDGEMENT
    return _INSTRUCTIONS.format(
        script_note=script_note,
        judgement=judgement,
        nature=nature,
        story_note=story_note,
        frames_note=frames_note,
    )


def is_serial_film(board: Storyboard | None, script: ScriptDraft | None) -> bool:
    """Whether a film is an episode of the office serial, by the marks its storyboard carries.

    The storyboard's series key is what the publish routing reads; the script's `story_json`
    kind is what `storyboard_from_episode` wrote. Either is enough: a serial storyboard built
    by hand without a series key is still a dramatisation, and a script on a serial key is
    still one when its story_json was lost.
    """
    if board is not None and str(board.series_key or "").strip().lower() == SERIAL_SERIES_KEY:
        return True
    story = script.story_json if script is not None and isinstance(script.story_json, dict) else {}
    return story.get("kind") == SERIAL_SCRIPT_KIND


class EditorialError(ValueError):
    """The film could not be reviewed; nothing was decided."""


def gather_facts(session: Session, media_asset_id: str, language: str) -> dict[str, Any]:
    """Everything the Director reads, and the verdicts that need no model."""
    asset = session.get(MediaAsset, media_asset_id)
    if asset is None:
        raise EditorialError("Materialul nu există")
    job = session.scalar(
        select(VideoRenderJob).where(VideoRenderJob.output_asset_id == media_asset_id)
    )
    board = session.get(Storyboard, job.storyboard_id) if job else None
    script = session.get(ScriptDraft, board.script_draft_id) if board else None
    topic = session.get(TopicIdea, script.topic_id) if script else None
    scenes = (
        list(
            session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == board.id)
                .order_by(StoryboardScene.scene_index)
            )
        )
        if board
        else []
    )
    claims: list[dict[str, Any]] = []
    hard: list[str] = []
    serial = is_serial_film(board, script)
    story = script.story_json if script and isinstance(script.story_json, dict) else {}
    for claim_id in list(script.claim_ids_json or []) if script else []:
        claim = session.get(FactualClaim, claim_id)
        if claim is None:
            hard.append(f"afirmația {claim_id[:8]} nu mai există")
            continue
        source = session.get(SourceSnapshot, claim.source_id) if claim.source_id else None
        claims.append(
            {
                "text": claim.claim_text,
                "status": claim.status,
                "source": (
                    {"url": source.url, "publisher": source.publisher, "title": source.title}
                    if source
                    else None
                ),
            }
        )
        # A serial episode carries no claims by construction; one that somehow does is
        # still not a factual film, and a source is not what its truth rests on.
        if serial:
            continue
        if source is None:
            hard.append(f"afirmația «{claim.claim_text[:80]}» nu are nicio sursă")
        elif claim.status != "SUPPORTED":
            hard.append(f"afirmația «{claim.claim_text[:80]}» nu este verificată ({claim.status})")
    voiceover = script.voiceover_full_text if script else ""
    words = len(voiceover.split())
    if not script:
        hard.append("materialul nu are un scenariu de care să țină")
    elif words < MIN_WORDS:
        hard.append(f"fără poveste: narațiunea are {words} cuvinte, sub {MIN_WORDS}")
    if language.lower() == "en" and voiceover and not looks_like_english(voiceover):
        hard.append(f"narațiunea nu este în {language_name(language)}")
    # The one verdict that depends on the kind of film. A factual script that rests on
    # nothing is refused in the words the first review used; a dramatisation of the day's
    # committed events makes no claims about the world and is not asked for any.
    if script and not claims and not serial:
        hard.append("scenariul nu se sprijină pe nicio afirmație")
    # Whether the narration says what its claims and its topic say, measured on the text
    # (`app.factual.grounding`). The rehearsal of 2026-09-18 approved a telescope film on the
    # Nepal climate-finance topic because nothing computed asked; the story review and the gate
    # before the render refuse it now, and this is the last look, for a film that reached the
    # file some other way. A factual film it could not measure is not waved through either.
    grounding = script_grounding(session, script) if script and not serial else None
    if grounding is not None and not grounding["passed"] and claims:
        hard.append("narațiunea nu spune ce spun afirmațiile ei: " + " ".join(grounding["reasons"]))
    qc = session.scalar(
        select(QualityControlReport)
        .where(QualityControlReport.media_asset_id == media_asset_id)
        .order_by(QualityControlReport.verified_at.desc())
    )
    return {
        "asset_id": media_asset_id,
        "path": asset.uri_or_path,
        "storyboard_id": board.id if board else None,
        "topic": {"title": topic.title, "angle": topic.angle} if topic else None,
        "title": script.title if script else (board.title if board else ""),
        # Said plainly, so the Director and anyone reading the review know which brief
        # applied: the episode's title and number are the serial's own record of it.
        "serial": serial,
        "series_key": SERIAL_SERIES_KEY if serial else None,
        "episode": (
            {
                "title": script.title if script else (board.title if board else ""),
                "number": story.get("episode_number"),
            }
            if serial
            else None
        ),
        "voiceover": voiceover,
        "words": words,
        "claims": claims,
        # What was measured about the narration against its claims and its topic, so her
        # verdict can cite it. None for an episode of the serial.
        "grounding": grounding,
        "scenes": [
            {
                "index": s.scene_index,
                # The writer's scene this shot was cut from (the montage, `montage.beat_of`);
                # None for a scene the montage did not cut.
                "writer_scene": beat_of(s.prompt_json).get("scene_number"),
                "seconds": s.duration_seconds,
                "narration": s.voiceover_segment,
                "picture": s.visual_prompt,
            }
            for s in scenes
        ],
        "quality_control": {
            "status": qc.status if qc else None,
            "measured": (
                {
                    k: v
                    for k, v in (qc.checks_json.get("technical_qc") or {}).items()
                    if k.startswith("measured")
                }
                if qc and isinstance(qc.checks_json, dict)
                else {}
            ),
        },
        "duration_seconds": asset.duration_seconds,
        "visual_provider": asset.provider_name,
        "audience_language": language_name(language),
        "hard_rejects": hard,
    }


#: The word a provider uses for "this model can look at an image". Ollama answers it in a
#: model's own capability list; nothing here decides it from a model's name.
VISION = "vision"


def model_can_see(session: Session, agent_id: str) -> bool:
    """Whether the provider says this employee's model can look at a picture.

    Sending frames to a model without vision does not degrade the answer — the provider
    refuses the whole call, so the Director could never give a verdict. Her model
    (glm-5.3) declares completion, thinking and tools; qwen3.5 and mistral-large-3 declare
    vision as well. The gate reads the declaration instead of hoping.
    """
    agent = session.get(Agent, agent_id)
    if agent is None or not agent.model_id:
        return False
    return bool(
        session.scalar(
            select(ModelCapability.capability_id)
            .join(Capability, Capability.id == ModelCapability.capability_id)
            .where(ModelCapability.model_id == agent.model_id, Capability.name == VISION)
            .limit(1)
        )
    )


def frame_picks(beats: Sequence[Any], limit: int = MAX_FRAMES) -> list[int]:
    """Which storyboard rows a look of ``limit`` frames is shown, as positions in film order.

    ``beats`` holds each row's writer scene (``prompt_json.beat.scene_number``,
    `montage.beat_of`), None for a row the montage did not cut. Every row when they all fit;
    else one row per writer's scene — the middle shot of its beat, and the film's last row for
    the last beat, so the payoff is always seen — sampled evenly over the film when there are
    more writer's scenes than frames, and the frames left over spread evenly over the rows
    between.

    The montage (2026-10-16) cut each writer's scene into 2-3 rows, and the first eight rows
    were the first 25-35 s of a 160 s film: the Director's viewing and the film's picture look
    never saw its ending, the very failure (the ATLAS payoff approved unseen) one frame per
    scene was written against.
    """
    count = len(beats)
    if limit <= 0 or count == 0:
        return []
    if count <= limit:
        return list(range(count))
    groups: list[list[int]] = []
    for position, beat in enumerate(beats):
        if groups and beat is not None and beats[groups[-1][-1]] == beat:
            groups[-1].append(position)
        else:
            groups.append([position])
    chosen = groups
    if len(groups) > limit:
        # Evenly over the film, its first and its last writer's scene included.
        chosen = (
            [groups[round(i * (len(groups) - 1) / (limit - 1))] for i in range(limit)]
            if limit > 1
            else [groups[-1]]
        )
    picks = [group[(len(group) - 1) // 2] for group in chosen[:-1]] + [chosen[-1][-1]]
    taken = set(picks)
    rest = [position for position in range(count) if position not in taken]
    spare = limit - len(picks)
    if spare > 0 and rest:
        picks += [rest[(2 * i + 1) * len(rest) // (2 * spare)] for i in range(spare)]
    return sorted(picks)


def frames_for(
    path: str,
    ffmpeg_path: str | None,
    duration: float | None,
    scene_seconds: list[float | None] | None = None,
    picks: Sequence[int] | None = None,
) -> list[str | None]:
    """One frame from the middle of each picked scene, as base64 JPEG, for a model that can
    see: ``picks`` are positions in ``scene_seconds`` (`frame_picks`); without them, rows
    spread over the whole film, its last one included.

    It used to be three frames at 20, 50 and 80 per cent of the film. A five-scene film showed
    the Director three of its scenes, and the payoff of the ATLAS film — eleven seconds of
    stripes — was approved on that. The planned scene lengths are scaled to the film's real
    length, because a scene lasts as long as its narration was recorded. Every scene's length
    places the picked ones on the timeline, so a frame is cut where its own scene plays.

    One entry per picked moment, in the order asked: a cut that failed is None in its own
    place. A failed cut used to be skipped, and every frame after it was then read as the
    scene before its own — the Director told «the middle of scenes 1, 2, 3» about the frames
    of 1, 3 and the next one, and the picture look judging a character against another
    scene's frame (the audit of 2026-10-16, SAFE-001). Empty when nothing can be cut at all.
    """
    ffmpeg = find_ffmpeg(ffmpeg_path)
    file = Path(path)
    if not ffmpeg or not file.is_file() or not duration or duration <= 0:
        return []
    lengths = [float(seconds) if seconds else 0.0 for seconds in (scene_seconds or [])]
    moments: list[float | None] = []
    if sum(lengths) > 0:
        scale = duration / sum(lengths)
        starts = [sum(lengths[:position]) for position in range(len(lengths))]
        chosen = frame_picks([None] * len(lengths)) if picks is None else list(picks)
        for position in chosen:
            moments.append(
                (starts[position] + lengths[position] / 2) * scale
                if 0 <= position < len(lengths)
                else None
            )
    else:
        moments = [duration * fraction for fraction in (0.2, 0.5, 0.8)[:FRAMES]]
    frames: list[str | None] = []
    for number, wanted in enumerate(moments):
        if wanted is None:
            frames.append(None)
            continue
        moment = max(0.0, wanted)
        try:
            result = subprocess.run(  # noqa: S603 - argument list, no shell
                [
                    ffmpeg,
                    "-v",
                    "error",
                    "-ss",
                    f"{moment:.2f}",
                    "-i",
                    str(file),
                    "-frames:v",
                    "1",
                    # JPEG is a full-range format, and the dissolve chain writes a film
                    # whose range is limited: without setrange the encoder refuses every
                    # frame, and the Director is handed a film she cannot look at. The
                    # frames come back down a pipe, so the muxer is image2pipe.
                    "-vf",
                    f"scale={FRAME_WIDTH}:-2,setrange=pc",
                    "-f",
                    "image2pipe",
                    "-c:v",
                    "mjpeg",
                    "pipe:1",
                ],
                capture_output=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            # The encoder itself is gone or hung: the moments left are not tried, and each
            # keeps its place as a missing frame.
            logger.warning(
                "frame_cut_failed",
                extra={
                    "path": str(file),
                    "at_seconds": round(moment, 2),
                    "error_class": type(error).__name__,
                },
            )
            return frames + [None] * (len(moments) - number)
        if result.returncode == 0 and result.stdout:
            frames.append(base64.b64encode(result.stdout).decode("ascii"))
        else:
            logger.warning(
                "frame_cut_failed",
                extra={
                    "path": str(file),
                    "at_seconds": round(moment, 2),
                    "returncode": result.returncode,
                },
            )
            frames.append(None)
    return frames


def accepted_under_cap(session: Session, media_asset_id: str) -> dict[str, Any] | None:
    """The Director's newest QC decision on this film when it ACCEPTED the film — under the
    Owner's renders cap (`media.renders_cap`) or on her own judgement of the
    findings — else None: such a film is published as it stands, and her viewing writes
    notes, not a veto. 2026-10-15 12:20Z, the Owner: «orice iese, chiar dacă pică, Directorul
    se uită peste ce avem, și publică!»; 17:36Z, a4ecf40a: she accepted the film after QC
    (nine minor findings, nothing bought), her viewing then refused it for its story — a
    story the drafts cap had shipped — and the day's episode stood unpublished with its
    money spent. The story's lessons belong to the next script, not to this film."""
    from app.media.director_qc import DECISION_EVENT  # noqa: PLC0415 - media imports agents
    from app.models import DomainEvent  # noqa: PLC0415

    for event in session.scalars(
        select(DomainEvent)
        .where(DomainEvent.event_type == DECISION_EVENT)
        .order_by(DomainEvent.sequence.desc())
    ):
        payload = event.payload if isinstance(event.payload, dict) else {}
        if str(payload.get("media_asset_id") or "") != media_asset_id:
            continue
        if payload.get("outcome") == "ACCEPTED":
            return dict(payload)
        return None
    return None


def latest_editorial(session: Session, media_asset_id: str) -> EditorialReview | None:
    return session.scalar(
        select(EditorialReview)
        .where(EditorialReview.media_asset_id == media_asset_id)
        .order_by(EditorialReview.created_at.desc())
    )


def _frames_note(
    can_see: bool, frames: Sequence[str], framed: Sequence[Any], unseen: Sequence[Any]
) -> str:
    """What the Director's brief says about the frames: how many are attached, which scenes
    they are, and which picked scene has none because its cut failed (SAFE-001). A model that
    can see but was handed no frame is told that, not that it has no vision."""
    blind = (
        " — so judge it from what is written here and say so if the pictures are what you "
        "would need to decide"
    )
    if not frames:
        if can_see:
            return ". No frame could be cut from the film's file, so you cannot see it" + blind
        return ". You cannot see the film itself — your model has no vision" + blind
    note = f", and {len(frames)} frames from the file itself are attached"
    if framed and len(framed) == len(frames):
        note += f" (the middle of scenes {', '.join(map(str, framed))}, in that order)"
    if unseen:
        many = len(unseen) > 1
        note += (
            f"; no frame could be cut for scene{'s' if many else ''} "
            f"{', '.join(map(str, unseen))}, so you have not seen "
            f"{'their pictures' if many else 'its picture'}"
        )
    return note


def editorial_review(
    engine: Engine,
    registry: ProviderRegistry | None,
    media_asset_id: str,
    correlation_id: str | None = None,
    language: str = "en",
    ffmpeg_path: str | None = None,
) -> dict[str, Any]:
    """The Director's verdict on one finished film; recorded, announced, and written home."""
    correlation = correlation_id or str(uuid4())
    with Session(engine) as session:
        director = agent_for_role(session, "Director")
        if director is None:
            raise EditorialError("Niciun Director activ care să vizioneze")
        director_id, director_name = director.id, director.display_name
        facts = gather_facts(session, media_asset_id, language)

    verdict: EditorialVerdict | None = None
    run_id: str | None = None
    frames: list[str] = []
    if facts["hard_rejects"]:
        verdict = EditorialVerdict(
            verdict="REJECT",
            story="",
            reasons=facts["hard_rejects"][:8],
            notes_for={"ScriptWriter": "; ".join(facts["hard_rejects"])[:600]},
        )
    elif registry is not None and registry.registered_ids():
        from app.agents.structured import structured_run  # noqa: PLC0415

        with Session(engine) as session:
            can_see = model_can_see(session, director_id)
        listed = list(facts.get("scenes") or [])
        # One frame per writer's scene, spread over the whole film, its last row included.
        picks = frame_picks([scene.get("writer_scene") for scene in listed])
        cut: list[str | None] = []
        if can_see:
            cut = frames_for(
                facts["path"],
                ffmpeg_path,
                facts["duration_seconds"],
                scene_seconds=[scene.get("seconds") for scene in listed],
                picks=picks,
            )
        frames = [frame for frame in cut if frame]
        # Which scenes the frames are, in order: no longer simply the first ones (a film whose
        # scenes have no lengths is cut at fixed fractions, and names none). Each pick keeps
        # its own frame: a cut that failed takes its scene's name with it, and that scene is
        # named as unseen, never given the next scene's frame (SAFE-001).
        named = any(scene.get("seconds") for scene in listed)
        framed = (
            [listed[p].get("index") for p, frame in zip(picks, cut, strict=False) if frame]
            if named
            else []
        )
        unseen = (
            [listed[p].get("index") for p, frame in zip(picks, cut, strict=False) if not frame]
            if named
            else []
        )
        shown = {k: v for k, v in facts.items() if k not in ("path", "hard_rejects")}
        prompt = (
            audience_language_line(language)
            + instructions_for(
                bool(facts.get("serial")),
                frames_note=_frames_note(can_see, frames, framed, unseen),
            )
            + wrap_in_inert_boundary(json.dumps(shown, ensure_ascii=False), "the-film")
        )
        parsed, first, second = structured_run(
            engine,
            registry,
            director_id,
            EDITORIAL_TASK,
            prompt,
            TEMPLATE_VERSION,
            correlation,
            EditorialVerdict,
            '{"verdict": "APPROVE|REJECT", "story": "...", "reasons": [...], "notes_for": {}, '
            '"lesson": ""}',
            summary=(
                f"Vizionez «{facts['title']}» înainte de publicare "
                f"({len(frames)} {'cadru' if len(frames) == 1 else 'cadre'})."
            ),
            max_tokens=6000,
            temperature=0.1,
            extra={"images": frames} if frames else None,
        )
        run_id = (second or first)["id"]
        if parsed is None:
            raise EditorialError(
                f"{director_name} nu a dat un verdict utilizabil "
                f"({(second or first)['status']}: fără obiect)"
            )
        verdict = parsed
    else:
        raise EditorialError("Niciun model de limbaj: Directorul nu poate viziona materialul")

    # The Owner, 2026-10-15: a film accepted under his cap is published as it stands. Her
    # viewing still says what it saw — the reasons stay on the record, the lesson is kept —
    # but it is not a veto: the verdict is APPROVE under the cap, no department is told to
    # remake anything, and a storyboard a viewing refused earlier stands RENDERED again.
    with Session(engine) as session:
        under_cap = accepted_under_cap(session, media_asset_id)
    if verdict.verdict == "REJECT" and under_cap is not None:
        verdict = EditorialVerdict(
            verdict="APPROVE",
            story=verdict.story,
            reasons=verdict.reasons,
            notes_for=verdict.notes_for,
            lesson=verdict.lesson,
        )
    else:
        under_cap = None

    with Session(engine) as session, session.begin():
        review_id = str(uuid4())
        event = append_event(
            session,
            "media.editorial_reviewed",
            "media_asset",
            media_asset_id,
            1,
            {
                "verdict": verdict.verdict,
                "story": verdict.story[:200],
                "reasons": verdict.reasons,
                "frames_seen": len(frames),
                "title": facts["title"],
                "under_cap": under_cap is not None,
            },
            correlation,
        )
        session.add(
            EditorialReview(
                id=review_id,
                media_asset_id=media_asset_id,
                storyboard_id=facts["storyboard_id"],
                verdict=verdict.verdict,
                story=verdict.story,
                reasons_json=list(verdict.reasons),
                notes_json=dict(verdict.notes_for),
                reviewer_agent_id=director_id,
                run_id=run_id,
                frames_seen=len(frames),
                model_used=run_id is not None,
                created_at=utc_now(),
                event_id=event.event_id,
            )
        )
        if verdict.verdict == "REJECT" and facts["storyboard_id"]:
            board = session.get(Storyboard, facts["storyboard_id"])
            if board is not None:
                board.status = "REJECTED"
        elif under_cap is not None and facts["storyboard_id"]:
            board = session.get(Storyboard, facts["storyboard_id"])
            if board is not None and board.status == "REJECTED":
                # Refused by an earlier viewing of the same film, never closed: a film
                # with a finished render that goes out under the cap.
                board.status = "RENDERED"
        roles = {
            role.name: agent
            for agent, role in session.execute(
                select(Agent, Role)
                .join(Role, Agent.role_id == Role.id)
                .where(Agent.lifecycle == "ACTIVE")
            ).all()
        }
        subject = f"Vizionare: {viewing_verdict(verdict.verdict)} — {facts['title']}"
        summary_text = (
            f"{'Aprobat' if verdict.verdict == 'APPROVE' else 'Respins'}: {facts['title']}. "
            + (f"Despre: {verdict.story} " if verdict.story else "")
            + (f"Motive: {'; '.join(verdict.reasons)}." if verdict.reasons else "")
        )
        post_message(
            session,
            intent="STATUS" if verdict.verdict == "APPROVE" else "ESCALATE",
            subject=subject,
            body={"media_asset_id": media_asset_id, "verdict": verdict.verdict},
            body_text=summary_text + f" — {director_name}",
            from_agent_id=director_id,
            to_agent_id=None,
            run_id=run_id,
            correlation_id=correlation,
        )
        # What the Director says about how the pictures were misread is a lesson about
        # prompting: if a wording keeps producing the wrong camera move, or a character who
        # changes coat between shots, the next film's prompt agent should know it before it
        # writes. Only her lesson, for its kind of film, unverified until a picture proves it,
        # never this film's title (review of 68fa0b4, 2026-10-12: the first sentence of her
        # note to the Video Editor was a fix for this one film, kept as a rule for all).
        if verdict.lesson.strip():
            record_prompt_lesson(
                session,
                verdict.lesson,
                source_id=run_id,
                scope=SCOPE_SERIAL if facts.get("serial") else SCOPE_FACTUAL,
                provisional=True,
                storyboard_id=facts.get("storyboard_id"),
            )
        sent = 0
        if verdict.verdict == "REJECT" and under_cap is None:
            for role_name, note in verdict.notes_for.items():
                target = roles.get(DEPARTMENTS.get(role_name, role_name))
                if target is None or not str(note).strip():
                    continue
                post_message(
                    session,
                    intent="HANDOFF",
                    subject=f"Refăcut: {facts['title']}",
                    body={
                        "media_asset_id": media_asset_id,
                        "storyboard_id": facts["storyboard_id"],
                    },
                    body_text=f"{note} — {director_name}"[:4000],
                    from_agent_id=director_id,
                    to_agent_id=target.id,
                    run_id=run_id,
                    correlation_id=correlation,
                )
                sent += 1
        remember(
            session,
            memory_class="AGENT_OPINION",
            content=summary_text,
            source_type="run" if run_id else "system",
            source_id=run_id or review_id,
            agent_id=director_id,
        )
    # Her lesson read beside the live ones by her (free), so a correction retires the rule it
    # corrects before the next writer reads them; it never raises.
    reconcile_prompt_lessons(engine, registry, correlation)
    return {
        "review_id": review_id,
        "verdict": verdict.verdict,
        "story": verdict.story,
        "reasons": list(verdict.reasons),
        "letters": sent,
        "frames_seen": len(frames),
        "model_used": run_id is not None,
        "run_id": run_id,
    }
