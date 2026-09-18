"""Quality control looks at the pictures before the Director does.

Until now the only eye on a finished film was the Director's, at editorial review — after
the film was assembled and after the money for every shot was spent. Everything before her
was file-level: duration, resolution, loudness, captions, how many scenes fell back to a
slow push, and an SSIM heuristic that catches a still which is flat along one axis. That
heuristic catches stripes and blank fields; it cannot tell a beautiful picture of the wrong
thing from the picture the scene asked for, and it never looked at the people in the shot —
`character_drift_qc` said NOT_IMPLEMENTED in as many words.

So the gate that measures the film now also looks at it. One frame from the middle of every
scene goes to a model the provider says can see, in one call for the whole film, with two
questions per scene: is this a picture at all (a blank field, stripes, noise, garbled
writing is not), and does it show what the scene's visual prompt and narration asked for.
The same call carries the characters the storyboard put in each scene, with the Character
Bible's canonical description and, where the bible holds a stored portrait, the portrait
itself; a person in the wrong outfit is named, with their scene.

Two rules shape everything below.

The first is that this check certifies only what it measured. With no registry, no employee
whose model declares vision, no frames (no encoder, or no film to cut), no usable answer, or
the day's token ceiling reached, the check is NOT_APPLICABLE with the reason and `passed`
is None, and the film's verdict is exactly what it would have been. A check that could not
run never reports a pass. Where the bible holds no characters at all, the character check
stays NOT_IMPLEMENTED, as it was.

The second is that a failure here fails the film in every environment. The fallback-scene
gate is conditional — in TEST two motion scenes are the studio's own policy and the rest
push by design, so the same count is a warning there and a failure in PRODUCTION. Nothing
in TEST policy deliberately produces a blank scene or a stranger in a character's clothes.
The gate this one belongs beside is `content_integrity_qc`, the degenerate-still check,
which fails in both environments for exactly this defect measured on the still instead of
on the film. This follows it.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.identity import clipped
from app.agents.vision import frames_for, vision_agent
from app.factual.sanitizer import wrap_in_inert_boundary
from app.media.models import (
    CharacterBible,
    MediaAsset,
    Storyboard,
    StoryboardScene,
    VideoRenderJob,
)

logger = logging.getLogger("studio.picture_qc")

PICTURE_TASK = "picture_qc"
TEMPLATE_VERSION = "picture-qc-v1"

#: The departments asked to look, in order. The Video Editor owns the pictures, so the
#: department that made them is the department that answers for them; the Director is asked
#: only if the Video Editor's model cannot see, and she has her own look later either way.
LOOKERS = ("VideoEditor", "Director", "QualityAssurance")

#: At most this many stored portraits travel with one call. A reference image costs as much
#: as a frame, and beyond a handful the answer is about the attachments, not the film.
MAX_REFERENCE_IMAGES = 4

#: A portrait bigger than this is not sent: the bible is meant to hold a reference, not a
#: master. Measured against the frames, which are 480px JPEGs of a few tens of kilobytes.
MAX_REFERENCE_BYTES = 4_000_000


class ScenePictureVerdict(BaseModel):
    """What the model saw in one scene's frame. Nothing here has a default that reads as a
    pass: a scene the model says nothing about is a scene nobody looked at."""

    model_config = ConfigDict(extra="ignore")
    scene: int
    is_a_picture: bool
    shows_the_scene: bool
    reason: str = Field(default="", max_length=300)
    _clip_reason = field_validator("reason", mode="before")(clipped(300))


class CharacterVerdict(BaseModel):
    model_config = ConfigDict(extra="ignore")
    scene: int
    character: str = Field(default="", max_length=120)
    matches: bool
    reason: str = Field(default="", max_length=300)
    _clip_reason = field_validator("reason", mode="before")(clipped(300))


class PictureReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    scenes: list[ScenePictureVerdict] = Field(default_factory=list, max_length=16)
    characters: list[CharacterVerdict] = Field(default_factory=list, max_length=48)


_INSTRUCTIONS = (
    "You are the studio's quality control, and you are the first eye on this finished film. "
    "Attached are {frames} images: the first {frames} are one frame from the middle of each "
    "scene, in the order the scenes are listed below.{references_note} Judge only what you "
    "can see.\n"
    "For every scene answer two questions from its frame alone. First: is it a picture at "
    "all? A blank or uniform field, plain stripes or bands, pure noise, a smear, or a wall "
    "of garbled writing is not a picture, however clean the file is. Second: does it show "
    "what the scene asked for — its written picture and what the narration says over it? "
    "Something well made that shows none of what the scene asked for does not show it.\n"
    "{character_note}"
    'Return only JSON: {{"scenes": [{{"scene": 1, "is_a_picture": true, '
    '"shows_the_scene": true, "reason": "one short sentence"}}], "characters": '
    '[{{"scene": 1, "character": "...", "matches": true, "reason": "one short sentence"}}]}}'
    " — one entry for every scene listed, and one for every scene-and-character pair listed. "
    "The reason matters most when your answer is false: say what you actually see.\n"
)

_CHARACTER_NOTE = (
    "Some scenes have people in them who must be the same people every time. Under "
    "`characters` below, each pair gives a scene and a character with the studio's canonical "
    "description of them — face and hair, outfit, props, role symbols, palette. For every "
    "pair, say whether the person in that scene's frame is that character as described. A "
    "different outfit, different hair, missing role props: that is not a match, and say "
    "which. If that character is not in the frame at all, that is not a match either.\n"
)

_REFERENCES_NOTE = (
    " After them come {references} reference portraits from the studio's character bible, in "
    "the order they are listed under `references` below; those are what the character must "
    "look like, not frames of this film."
)


def _description(character: CharacterBible) -> dict[str, Any]:
    """The bible's canonical look, with the empty parts left out rather than sent as blanks."""
    fields = {
        "face_and_hair": str(character.face_hair_desc or "").strip(),
        "outfit": str(character.outfit_desc or "").strip(),
        "props": str(character.props_desc or "").strip(),
        "role_symbols": str(character.role_symbols or "").strip(),
    }
    described: dict[str, Any] = {key: value for key, value in fields.items() if value}
    palette = character.palette_json if isinstance(character.palette_json, dict) else {}
    if palette:
        described["palette"] = palette
    return described


def _reference_asset_id(character: CharacterBible) -> str | None:
    """The first stored portrait the bible declares for this character, if any.

    A slot holds a stored asset id or null, never a description standing in for an image;
    a slot holding something that is not a string is not an asset id and is ignored.
    """
    slots = (
        character.reference_assets_json if isinstance(character.reference_assets_json, dict) else {}
    )
    for value in slots.values():
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _reference_image(session: Session, asset_id: str) -> str | None:
    """A stored portrait as base64, or None when the row or the file is not there."""
    asset = session.get(MediaAsset, asset_id)
    if asset is None:
        return None
    path = Path(asset.uri_or_path)
    try:
        if not path.is_file() or path.stat().st_size > MAX_REFERENCE_BYTES:
            return None
        return base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return None


def _not_applicable(reason: str, *, characters_configured: int = 0) -> dict[str, Any]:
    """Both checks stood down for the same reason, and neither certifies anything."""
    return {
        "picture_qc": {
            "status": "NOT_APPLICABLE",
            "passed": None,
            "detail": reason,
            "frames": 0,
            "scenes": [],
            "model_used": False,
            "run_id": None,
        },
        "character_drift_qc": {
            "status": "NOT_IMPLEMENTED" if characters_configured == 0 else "NOT_APPLICABLE",
            "passed": None,
            "detail": (
                "No character is configured in the bible; this check certifies nothing."
                if characters_configured == 0
                else reason
            ),
            "characters_configured": characters_configured,
            "characters": [],
            "reference_images": 0,
        },
        "failures": [],
    }


def evaluate_pictures(
    engine: Engine,
    registry: Any | None,
    media_asset_id: str,
    correlation_id: str,
    *,
    ffmpeg_path: str | None = None,
) -> dict[str, Any]:
    """Look at one finished film's pictures and its people.

    Returns ``{"picture_qc": {...}, "character_drift_qc": {...}, "failures": [...]}`` for
    quality control to fold into its report. Called before quality control opens its write
    transaction, because the model run writes its own rows and the day's token ceiling is
    read outside one (`app.agents.services.run_agent_task`).
    """
    with Session(engine) as session:
        asset = session.get(MediaAsset, media_asset_id)
        if asset is None:
            return _not_applicable("the material does not exist")
        characters_configured = len(list(session.scalars(select(CharacterBible.id))))
        path, duration = asset.uri_or_path, asset.duration_seconds
        job = session.scalar(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == media_asset_id)
        )
        board = session.get(Storyboard, job.storyboard_id) if job is not None else None
        title = str(board.title or "") if board is not None else ""
        # The storyboard read out as plain values. Everything below this session runs with it
        # closed — the model call must not hold a connection while it waits — and a detached
        # ORM row is a lock or an error waiting for a reader who forgot which it was.
        scenes: list[dict[str, Any]] = (
            [
                {
                    "index": scene.scene_index,
                    "seconds": scene.duration_seconds,
                    "picture": scene.visual_prompt,
                    "narration": scene.voiceover_segment,
                    "characters": [
                        cid for cid in (scene.character_ids_json or []) if isinstance(cid, str)
                    ],
                }
                for scene in session.scalars(
                    select(StoryboardScene)
                    .where(StoryboardScene.storyboard_id == board.id)
                    .order_by(StoryboardScene.scene_index)
                )
            ]
            if board is not None
            else []
        )
        if not scenes:
            return _not_applicable(
                "the film has no storyboard scenes to compare its pictures with",
                characters_configured=characters_configured,
            )
        if registry is None or not registry.registered_ids():
            return _not_applicable(
                "no language-model provider is registered: nobody could look at the pictures",
                characters_configured=characters_configured,
            )
        looker = vision_agent(session, *LOOKERS)
        if looker is None:
            return _not_applicable(
                "no employee's model declares vision: the pictures were not looked at",
                characters_configured=characters_configured,
            )
        looker_id, looker_name = looker
        # Read the bible for the people this storyboard actually puts on screen, while the
        # session is open; the model call below must not hold one.
        wanted = [cid for scene in scenes for cid in scene["characters"]]
        bibles = (
            {
                character.id: character
                for character in session.scalars(
                    select(CharacterBible).where(CharacterBible.id.in_(set(wanted)))
                )
            }
            if wanted
            else {}
        )
        described = {
            cid: (_description(character), _reference_asset_id(character), character.canonical_name)
            for cid, character in bibles.items()
        }
        reference_images: dict[str, str] = {}
        for cid, (_, reference_id, _name) in described.items():
            if reference_id is None or len(reference_images) >= MAX_REFERENCE_IMAGES:
                continue
            encoded = _reference_image(session, reference_id)
            if encoded is not None:
                reference_images[cid] = encoded

    frames = frames_for(
        path,
        ffmpeg_path,
        duration,
        scene_seconds=[scene["seconds"] for scene in scenes],
    )
    if not frames:
        return _not_applicable(
            "no frame could be read from the film: there is no encoder, or no file to cut",
            characters_configured=characters_configured,
        )

    # One frame per scene, in order. When the encoder returned fewer than the storyboard
    # has (the frame cap, or a cut that failed), the frames are the first scenes and only
    # those are asked about; the scenes past them are named as unlooked-at, never as passed.
    looked = scenes[: len(frames)]
    unlooked = [scene["index"] for scene in scenes[len(frames) :]]

    #: (scene_index, character_id) pairs the model is asked about, and the ones it cannot be.
    pairs: list[tuple[int, str]] = []
    not_applicable_characters: list[dict[str, Any]] = []
    for scene in looked:
        for cid in scene["characters"]:
            if cid not in described:
                continue
            description, reference_id, name = described[cid]
            if not description and cid not in reference_images:
                not_applicable_characters.append(
                    {
                        "scene": scene["index"],
                        "character": name,
                        "status": "NOT_APPLICABLE",
                        "matches": None,
                        "reason": (
                            "the bible holds no description of this character and no "
                            "reference image: there is nothing to compare the frame with"
                        ),
                    }
                )
                continue
            pairs.append((scene["index"], cid))

    attached_references = [
        {"character": described[cid][2], "image": image}
        for cid, image in reference_images.items()
        if any(cid == pair_id for _, pair_id in pairs)
    ]
    shown = {
        "title": title,
        "scenes": [
            {
                "scene": scene["index"],
                "picture": scene["picture"],
                "narration": scene["narration"],
            }
            for scene in looked
        ],
        "characters": [
            {
                "scene": index,
                "character": described[cid][2],
                "bible": described[cid][0],
                "reference": described[cid][2] if cid in reference_images else None,
            }
            for index, cid in pairs
        ],
        "references": [entry["character"] for entry in attached_references],
    }
    prompt = _INSTRUCTIONS.format(
        frames=len(frames),
        references_note=(
            _REFERENCES_NOTE.format(references=len(attached_references))
            if attached_references
            else ""
        ),
        character_note=_CHARACTER_NOTE if pairs else "",
    ) + wrap_in_inert_boundary(json.dumps(shown, ensure_ascii=False)[:14000], "the-film")

    from app.agents.structured import structured_run  # noqa: PLC0415

    parsed, first, second = structured_run(
        engine,
        registry,
        looker_id,
        PICTURE_TASK,
        prompt,
        TEMPLATE_VERSION,
        correlation_id,
        PictureReport,
        '{"scenes": [...], "characters": [...]}',
        summary=(
            f"Mă uit la cele {len(frames)} cadre ale filmului «{title[:80]}» înainte de Director."
        ),
        max_tokens=4000,
        temperature=0.1,
        extra={"images": frames + [entry["image"] for entry in attached_references]},
    )
    run = second or first
    run_id = run["id"]
    if parsed is None or not parsed.scenes:
        # A model that answered nothing usable, or was refused under the day's token
        # ceiling, has not looked at anything. Say so; do not pass the film for it.
        detail = (
            f"{looker_name} gave no usable verdict on the pictures ({run['status']})"
            if parsed is None
            else f"{looker_name} returned no verdict for any scene"
        )
        logger.info("picture_qc_no_verdict", extra={"run_status": run["status"]})
        stood_down = _not_applicable(detail, characters_configured=characters_configured)
        stood_down["picture_qc"]["frames"] = len(frames)
        stood_down["picture_qc"]["run_id"] = run_id
        for entry in not_applicable_characters:
            stood_down["character_drift_qc"]["characters"].append(entry)
        return stood_down

    failures: list[str] = []
    scene_records: list[dict[str, Any]] = []
    answered = {verdict.scene: verdict for verdict in parsed.scenes}
    measured_scenes = 0
    for scene in looked:
        verdict = answered.get(scene["index"])
        if verdict is None:
            scene_records.append(
                {
                    "scene": scene["index"],
                    "status": "NOT_APPLICABLE",
                    "is_a_picture": None,
                    "shows_the_scene": None,
                    "reason": "no verdict was returned for this scene",
                }
            )
            continue
        measured_scenes += 1
        scene_records.append(
            {
                "scene": scene["index"],
                "status": "MEASURED",
                "is_a_picture": verdict.is_a_picture,
                "shows_the_scene": verdict.shows_the_scene,
                "reason": verdict.reason,
            }
        )
        if not verdict.is_a_picture:
            failures.append(
                f"Scene {scene['index']}: the frame is not a picture — "
                f"{verdict.reason or 'no scene in it'}"
            )
        elif not verdict.shows_the_scene:
            failures.append(
                f"Scene {scene['index']}: the picture is not what the scene asked for — "
                f"{verdict.reason or 'it shows something else'}"
            )
    for index in unlooked:
        scene_records.append(
            {
                "scene": index,
                "status": "NOT_APPLICABLE",
                "is_a_picture": None,
                "shows_the_scene": None,
                "reason": "no frame was cut for this scene",
            }
        )

    picture: dict[str, Any] = {
        "status": "MEASURED" if measured_scenes else "NOT_APPLICABLE",
        "passed": (not failures) if measured_scenes else None,
        "frames": len(frames),
        "scenes_measured": measured_scenes,
        "scenes": scene_records,
        "model_used": True,
        "looked_by": looker_name,
        "run_id": run_id,
    }
    if not measured_scenes:
        picture["detail"] = f"{looker_name} returned no verdict for any scene that was cut"

    character_records = list(not_applicable_characters)
    character_failures: list[str] = []
    by_pair = {(verdict.scene, verdict.character.strip()): verdict for verdict in parsed.characters}
    measured_characters = 0
    for index, cid in pairs:
        name = described[cid][2]
        person = by_pair.get((index, name))
        if person is None:
            character_records.append(
                {
                    "scene": index,
                    "character": name,
                    "status": "NOT_APPLICABLE",
                    "matches": None,
                    "reason": "no verdict was returned for this character in this scene",
                }
            )
            continue
        measured_characters += 1
        character_records.append(
            {
                "scene": index,
                "character": name,
                "status": "MEASURED",
                "matches": person.matches,
                "reason": person.reason,
            }
        )
        if not person.matches:
            character_failures.append(
                f"Scene {index}: {name} is not the character the bible describes — "
                f"{person.reason or 'the person in the frame is someone else'}"
            )

    if characters_configured == 0:
        drift: dict[str, Any] = {
            "status": "NOT_IMPLEMENTED",
            "passed": None,
            "detail": "No character is configured in the bible; this check certifies nothing.",
        }
    elif measured_characters == 0:
        drift = {
            "status": "NOT_APPLICABLE",
            "passed": None,
            "detail": (
                "no character in this film could be compared with the bible"
                if character_records
                else "no scene in this film lists a character"
            ),
        }
    else:
        drift = {
            "status": "MEASURED",
            "passed": not character_failures,
            "detail": None,
        }
    drift.update(
        {
            "characters_configured": characters_configured,
            "characters_measured": measured_characters,
            "characters": character_records,
            "reference_images": len(attached_references),
            "run_id": run_id,
        }
    )

    return {
        "picture_qc": picture,
        "character_drift_qc": drift,
        "failures": failures + character_failures,
    }
