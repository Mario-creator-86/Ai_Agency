"""Quality control looks at the pictures before the Director does.

Until now the only eye on a finished film was the Director's, at editorial review — after
the film was assembled and after the money for every shot was spent. Everything before her
was file-level: duration, resolution, loudness, captions, how many scenes fell back to a
slow push, and an SSIM heuristic that catches a still which is flat along one axis. That
heuristic catches stripes and blank fields; it cannot tell a beautiful picture of the wrong
thing from the picture the scene asked for, and it never looked at the people in the shot —
`character_drift_qc` said NOT_IMPLEMENTED in as many words.

So the gate that measures the film now also looks at it. One frame from the middle of every
scene goes to a model the provider says can see, in one call for the whole film, with three
questions per scene: is this a picture at all (a blank field, stripes, noise, garbled
writing is not), is it ONE picture (panels pasted together or a picture with a blank band
is not: scene 5 of «The Particle That Shouldn't Exist (But Does)», 2026-10-09, was three
stacked panels and passed every check), and does it show what the scene's visual prompt and
narration asked for. The stills gate and clip QC ask the same one-picture question first.
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

The same rule decides what a cast is worth here. A scene's `character_ids_json` is the film's
own word on who is in the shot, and that is what this check certifies. Beside it the
storyboard records the names its prose merely spelled — read from a bare given name, which
was measured to find the Fact-Checker in "Hurricane Elena made landfall" — and those are
asked about too, recorded as OBSERVED, and never counted: a guess cannot fail a film, and a
check that looked only at guesses has measured nothing. Where a film states nobody at all,
the detail is the board's own note, so "this film has no characters by design" no longer
reads as "nobody listed them".

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
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator
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
from app.media.toolchain import find_ffmpeg

if TYPE_CHECKING:
    from app.media.still_gate import StillPlan

logger = logging.getLogger("studio.picture_qc")

PICTURE_TASK = "picture_qc"
#: v2 (2026-10-09): the one-picture question, after scene 5 came out as three stacked panels.
TEMPLATE_VERSION = "picture-qc-v2"

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
    #: One continuous photograph, not panels pasted together or a picture with a blank band.
    one_picture: bool
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
    "For every scene answer three questions from its frame alone. First: is it a picture at "
    "all? A blank or uniform field, plain stripes or bands, pure noise, a smear, or a wall "
    "of garbled writing is not a picture, however clean the file is. Second: is it ONE "
    "picture, one continuous photograph filling the frame from edge to edge? A collage, a "
    "split screen, a grid, panels stacked one above another, a comic strip, or a picture "
    "with a blank or black band across it is not one picture, however good each part is. "
    "Third: does it show what the scene asked for — its written picture and what the "
    "narration says over it? Something well made that shows none of what the scene asked "
    "for does not show it.\n"
    "{character_note}"
    'Return only JSON: {{"scenes": [{{"scene": 1, "is_a_picture": true, "one_picture": true, '
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
            "characters_measured": 0,
            "characters_observed": 0,
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
        if board is None:
            # A film with no storyboard behind it has no scenes to compare its pictures with,
            # which is the same answer as a storyboard with no scenes and is given in the same
            # words. Returned here rather than folded into the `not scenes` check below so
            # that everything after this line has a storyboard to read the cast from.
            return _not_applicable(
                "the film has no storyboard scenes to compare its pictures with",
                characters_configured=characters_configured,
            )
        title = str(board.title or "")
        # The storyboard read out as plain values. Everything below this session runs with it
        # closed — the model call must not hold a connection while it waits — and a detached
        # ORM row is a lock or an error waiting for a reader who forgot which it was.
        scenes: list[dict[str, Any]] = [
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
        if not scenes:
            return _not_applicable(
                "the film has no storyboard scenes to compare its pictures with",
                characters_configured=characters_configured,
            )
        # What the board's maker decided about its cast. Two things come from it: the names
        # its prose spelled and it refused to cast on — asked about below like any other,
        # and unable to fail the film, because the studio was never told that person is in
        # the shot — and, when the film states nobody at all, the maker's own reason for
        # that, so this check reports "no characters by design" where that is what happened
        # instead of the one sentence it used to print for every reason there could be.
        from app.media.services import storyboard_cast_record  # noqa: PLC0415 - read only

        record = storyboard_cast_record(session, board.id)
        cast_note = record["note"]
        for scene in scenes:
            scene["guessed"] = [
                cid
                for cid in record["guessed"].get(str(scene["index"]), [])
                if cid not in scene["characters"]
            ]
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
        wanted = [cid for scene in scenes for cid in scene["characters"] + scene["guessed"]]
        #: The characters the film itself states are in it. Only these may pull a stored
        #: portrait into the question: a guessed name buys nothing and shows nothing.
        stated_ids = {cid for scene in scenes for cid in scene["characters"]}
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
            if cid not in stated_ids:
                continue
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

    #: (scene_index, character_id, basis) triples the model is asked about, and the ones it
    #: cannot be. `basis` is which reading put that name here: "stated" is the film's own
    #: word and is what this check certifies; "guessed" is a name the prose spelled, looked
    #: at for the record and never counted for or against the film.
    pairs: list[tuple[int, str, str]] = []
    not_applicable_characters: list[dict[str, Any]] = []
    for scene in looked:
        asked = [(cid, "stated") for cid in scene["characters"]]
        asked += [(cid, "guessed") for cid in scene["guessed"]]
        for cid, basis in asked:
            if cid not in described:
                continue
            description, reference_id, name = described[cid]
            if not description and cid not in reference_images:
                not_applicable_characters.append(
                    {
                        "scene": scene["index"],
                        "character": name,
                        "basis": basis,
                        "status": "NOT_APPLICABLE",
                        "matches": None,
                        "reason": (
                            "the bible holds no description of this character and no "
                            "reference image: there is nothing to compare the frame with"
                        ),
                    }
                )
                continue
            pairs.append((scene["index"], cid, basis))

    attached_references = [
        {"character": described[cid][2], "image": image}
        for cid, image in reference_images.items()
        if any(cid == pair_id and basis == "stated" for _, pair_id, basis in pairs)
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
            for index, cid, _basis in pairs
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
                    "one_picture": None,
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
                "one_picture": verdict.one_picture,
                "shows_the_scene": verdict.shows_the_scene,
                "reason": verdict.reason,
            }
        )
        if not verdict.is_a_picture:
            failures.append(
                f"Scene {scene['index']}: the frame is not a picture — "
                f"{verdict.reason or 'no scene in it'}"
            )
        elif not verdict.one_picture:
            # 2026-10-09: scene 5 was three stacked panels, and its clip animated them.
            failures.append(
                f"Scene {scene['index']}: the frame is not one picture (panels, a collage or a "
                f"blank band) — {verdict.reason or 'several pictures in one frame'}"
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
                "one_picture": None,
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
    observed_characters = 0
    for index, cid, basis in pairs:
        name = described[cid][2]
        person = by_pair.get((index, name))
        if person is None:
            character_records.append(
                {
                    "scene": index,
                    "character": name,
                    "basis": basis,
                    "status": "NOT_APPLICABLE",
                    "matches": None,
                    "reason": "no verdict was returned for this character in this scene",
                }
            )
            continue
        if basis == "guessed":
            # The storyboard did not put this person in the scene; its prose spelled the
            # name and the board refused to cast on it. What the model saw is worth
            # recording — it is the only place a reader can see what that guess was worth —
            # but a film is never failed for a person nobody said was in it, and a check
            # that measured only guesses has measured nothing.
            observed_characters += 1
            character_records.append(
                {
                    "scene": index,
                    "character": name,
                    "basis": basis,
                    "status": "OBSERVED",
                    "matches": person.matches,
                    "reason": person.reason,
                }
            )
            continue
        measured_characters += 1
        character_records.append(
            {
                "scene": index,
                "character": name,
                "basis": basis,
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
        # Why nothing was measured, in the order the reasons actually rule each other out.
        # The last of them is the one this check used to print for all of them: it now means
        # only what it says — nobody listed anybody, and the board never said why.
        if observed_characters:
            detail = (
                f"no scene in this film states who is in it; {observed_characters} name(s) "
                "its prose spells were looked at and certify nothing"
            )
        elif cast_note:
            detail = cast_note
        elif character_records:
            detail = "no character in this film could be compared with the bible"
        else:
            detail = "no scene in this film lists a character"
        drift = {"status": "NOT_APPLICABLE", "passed": None, "detail": detail}
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
            # Looked at but not counted: the names the board read in the prose and refused
            # to cast on. Reported separately so a reader never mistakes them for evidence.
            "characters_observed": observed_characters,
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


# ------------------------------------------------------------ one still, before motion
#
# The film-level look above runs after the money is spent. The stills gate
# (`app.media.still_gate`) asks the same department to look at each candidate still
# BEFORE a clip is bought: one call per still, at 1080 px. The frames above are 480 px,
# which is enough to see that a scene is a blank field and not enough to see a face in the
# lower third of a 9:16 picture.

STILL_TASK = "still_qc"
#: v2 (2026-10-09): one_picture, and a still is judged as ONE moment, the shot's first frame.
STILL_TEMPLATE_VERSION = "still-qc-v2"
#: The width the still is shown at. A 2K still (1530x2720) is scaled down to it.
STILL_WIDTH = 1080
#: The largest still read for judging; a vendor still is a few megabytes.
MAX_STILL_BYTES = 40_000_000

StillAction = Literal["buy_motion", "regenerate_still", "compose_locally"]

#: The question added on 2026-10-09, after scene 5 of «The Particle That Shouldn't Exist (But
#: Does)» came out as three stacked panels and every check passed it.
ONE_PICTURE = "one_picture"


def _every_entry_answers(entries: Any, question: str) -> Any:
    """Refuse a model's report in which any entry leaves `question` out."""
    if isinstance(entries, list) and any(
        isinstance(entry, dict) and question not in entry for entry in entries
    ):
        raise ValueError(f"every entry must answer {question}")
    return entries


class StillVerdict(BaseModel):
    """What the model saw in one still. Every field is required and every yes/no is a
    real boolean: an answer that leaves a question out, or answers it in words, does not
    validate, and a still with no valid verdict is a still nobody looked at."""

    model_config = ConfigDict(extra="ignore")
    scene: StrictInt
    faces_visible: StrictBool
    readable_text: StrictBool
    matches_plan: StrictBool
    look_ok: StrictBool
    technical_ok: StrictBool
    #: One continuous photograph filling the frame: not a collage, a split screen, a grid,
    #: stacked panels, a comic strip or a picture with a blank or black band. Required of the
    #: model like every other answer: `StillJudgeReport`, the shape a model's answer is read
    #: into, refuses an entry without it. The default is only for a verdict built in code (the
    #: stills step's test fakes, written before the question): a model's silence never
    #: reads as one picture.
    one_picture: StrictBool = True
    bible_violations: str = Field(min_length=1, max_length=300)
    verdict: StillAction
    reason: str = Field(min_length=1, max_length=300)
    _clip_violations = field_validator("bible_violations", mode="before")(clipped(300))
    _clip_reason = field_validator("reason", mode="before")(clipped(300))


class StillJudgeReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    stills: list[StillVerdict] = Field(default_factory=list, max_length=4)

    @field_validator("stills", mode="before")
    @classmethod
    def _one_picture_answered(cls, value: Any) -> Any:
        return _every_entry_answers(value, ONE_PICTURE)


@dataclass(frozen=True)
class StillJudgement:
    """The vision half of the stills gate. `verdict` is None whenever status is NOT_RUN."""

    status: str  # MEASURED | NOT_RUN
    verdict: StillVerdict | None
    detail_ro: str
    run_id: str | None
    looked_by: str | None
    image_width: int | None


_STILL_INSTRUCTIONS = (
    "You are the studio's quality control. Attached is ONE still, generated for scene "
    "{scene} of a factual short, before any money is spent on animating it. Judge only what "
    "you can see. The plan, the film's look and the visual bible's rules are below.\n"
    "A still is ONE moment: the first frame of the shot that will be animated from it. If "
    "the plan describes several moments (first one thing, then another), judge the still "
    "against the first moment only. A still that shows several moments at once, side by "
    "side or one above another, does not match the plan.\n"
    "Answer each question about this still:\n"
    "- faces_visible: is any human face visible, even small, partly turned or in the "
    "background? A figure seen only from behind, a silhouette or hands alone is not a face.\n"
    "- readable_text: is there any lettering, number, sign, caption or logo?\n"
    "- one_picture: is this ONE continuous photograph filling the whole frame from edge to "
    "edge? A collage, a split screen, a grid, panels stacked one above another, a comic "
    "strip, a picture inside a picture, or a picture with a blank or black band across it "
    "is not one picture.\n"
    "- matches_plan: does it show what the plan asks for, as one moment?\n"
    "- look_ok: does it match the film's look (light, palette, grain)?\n"
    "- technical_ok: is it sharp where it should be, free of warped anatomy, smears, "
    "stripes or artefacts?\n"
    "- bible_violations: name the violation or write none. Check every rule listed.\n"
    "- verdict: buy_motion only if the still is right as it is (never when one_picture is "
    "false); regenerate_still if a new still could fix it; compose_locally if the plan asks "
    "for a chart, a title, numbers or a black screen, which the studio draws itself.\n"
    'Return only JSON: {{"stills": [{{"scene": {scene}, "faces_visible": false, '
    '"readable_text": false, "one_picture": true, "matches_plan": true, "look_ok": true, '
    '"technical_ok": true, "bible_violations": "none", "verdict": "buy_motion", "reason": '
    '"one short sentence saying what you actually see"}}]}}\n'
)


def still_image(ffmpeg: str | None, path: Path | str, width: int = STILL_WIDTH) -> str | None:
    """The still scaled to `width` px as base64 JPEG, or None when it cannot be made."""
    source = Path(path)
    if not ffmpeg or not source.is_file():
        return None
    try:
        if source.stat().st_size > MAX_STILL_BYTES:
            return None
        result = subprocess.run(  # noqa: S603 - argument list, no shell
            [
                ffmpeg,
                "-v",
                "error",
                "-nostdin",
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-vf",
                f"scale={width}:-2:flags=lanczos",
                "-q:v",
                "3",
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
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    return base64.b64encode(result.stdout).decode("ascii")


def _still_not_run(
    detail: str,
    *,
    run_id: str | None = None,
    looked_by: str | None = None,
    width: int | None = None,
) -> StillJudgement:
    return StillJudgement(
        status="NOT_RUN",
        verdict=None,
        detail_ro=f"nu a fost privită: {detail}",
        run_id=run_id,
        looked_by=looked_by,
        image_width=width,
    )


def judge_still(
    engine: Engine,
    registry: Any | None,
    still_path: Path | str,
    plan: StillPlan,
    correlation_id: str,
    *,
    ffmpeg_path: str | None = None,
) -> StillJudgement:
    """One vision call on one candidate still, at 1080 px, by the LOOKERS.

    Returns MEASURED with the verdict only when the model answered for exactly this scene
    with every field; anything else is NOT_RUN ("nu a fost privită"), which the stills gate
    treats as a block. Nothing here passes a still by silence.
    """
    if registry is None or not registry.registered_ids():
        return _still_not_run("niciun furnizor de modele nu este înregistrat")
    with Session(engine) as session:
        looker = vision_agent(session, *LOOKERS)
    if looker is None:
        return _still_not_run("niciun angajat nu are un model care vede")
    looker_id, looker_name = looker
    image = still_image(find_ffmpeg(ffmpeg_path), still_path)
    if image is None:
        return _still_not_run(
            "imaginea nu a putut fi pregătită la 1080 px (lipsește codorul sau fișierul)",
            looked_by=looker_name,
        )
    shown = {
        "scene": plan.scene,
        "plan": plan.still_prompt,
        "look": plan.look_block,
        "camera_move": plan.camera_move,
        "faces_forbidden": plan.faces_forbidden,
        "bible_rules": list(plan.bible_rules),
    }
    prompt = _STILL_INSTRUCTIONS.format(scene=plan.scene) + wrap_in_inert_boundary(
        json.dumps(shown, ensure_ascii=False)[:8000], "the-still"
    )

    from app.agents.structured import structured_run  # noqa: PLC0415

    parsed, first, second = structured_run(
        engine,
        registry,
        looker_id,
        STILL_TASK,
        prompt,
        STILL_TEMPLATE_VERSION,
        correlation_id,
        StillJudgeReport,
        '{"stills": [...]}',
        summary=f"Mă uit la imaginea scenei {plan.scene} înainte să se cumpere mișcarea.",
        max_tokens=800,
        temperature=0.1,
        extra={"images": [image]},
    )
    run = second or first
    run_id = run["id"]
    if parsed is None:
        return _still_not_run(
            f"{looker_name} nu a dat un verdict utilizabil ({run['status']})",
            run_id=run_id,
            looked_by=looker_name,
            width=STILL_WIDTH,
        )
    entries = [verdict for verdict in parsed.stills if verdict.scene == plan.scene]
    if len(entries) != 1:
        return _still_not_run(
            f"{looker_name} nu a răspuns pentru scena {plan.scene}"
            if not entries
            else f"{looker_name} a dat {len(entries)} verdicte pentru scena {plan.scene}",
            run_id=run_id,
            looked_by=looker_name,
            width=STILL_WIDTH,
        )
    return StillJudgement(
        status="MEASURED",
        verdict=entries[0],
        detail_ro=entries[0].reason,
        run_id=run_id,
        looked_by=looker_name,
        image_width=STILL_WIDTH,
    )


# ------------------------------------------------------------ one clip, before assembly
#
# A bought clip is looked at before it is cut into the film: three frames of it (the first,
# the middle and the last) in one call, at 1080 px, with the same plan, look and bible rules
# its still was judged against. Three frames see what one cannot: a face that turns toward
# the camera half-way, a picture that melts or changes place, writing that appears late.

CLIP_TASK = "clip_qc"
#: v2 (2026-10-09): one_picture; a clip made of panels goes back to its still.
CLIP_TEMPLATE_VERSION = "clip-qc-v2"
#: The frames shown per clip, in order: first, middle, last.
CLIP_FRAMES = 3

ClipAction = Literal["keep", "regenerate_motion", "back_to_still"]


class ClipVerdict(BaseModel):
    """What the model saw in one clip's three frames. As with `StillVerdict`, every field is
    required and every yes/no is a real boolean; a clip with no valid verdict was not seen."""

    model_config = ConfigDict(extra="ignore")
    scene: StrictInt
    faces_visible: StrictBool
    readable_text: StrictBool
    matches_plan: StrictBool
    look_ok: StrictBool
    technical_ok: StrictBool
    same_shot: StrictBool
    #: Each frame is one continuous photograph, not panels. False means the still itself must
    #: change (clip QC routes it back to the still, never to another seed). Required of the
    #: model through `ClipJudgeReport`; the default is only for a verdict built in code, as on
    #: `StillVerdict`.
    one_picture: StrictBool = True
    bible_violations: str = Field(min_length=1, max_length=300)
    verdict: ClipAction
    reason: str = Field(min_length=1, max_length=300)
    _clip_violations = field_validator("bible_violations", mode="before")(clipped(300))
    _clip_reason = field_validator("reason", mode="before")(clipped(300))


class ClipJudgeReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    clips: list[ClipVerdict] = Field(default_factory=list, max_length=4)

    @field_validator("clips", mode="before")
    @classmethod
    def _one_picture_answered(cls, value: Any) -> Any:
        return _every_entry_answers(value, ONE_PICTURE)


@dataclass(frozen=True)
class ClipJudgement:
    """The vision half of clip QC. `verdict` is None whenever status is NOT_RUN."""

    status: str  # MEASURED | NOT_RUN
    verdict: ClipVerdict | None
    detail_ro: str
    run_id: str | None
    looked_by: str | None
    image_width: int | None
    frames: int


_CLIP_INSTRUCTIONS = (
    "You are the studio's quality control. Attached are THREE frames of ONE generated clip "
    "for scene {scene} of a factual short, in order: the first frame, the middle frame and "
    "the last frame. The clip was animated from an approved still and has not been cut into "
    "the film yet. Judge only what you can see. The plan, the camera move asked for, the "
    "film's look and the visual bible's rules are below.\n"
    "Answer each question about the clip, looking at all three frames:\n"
    "- faces_visible: is any human face visible in ANY of the three frames, even small, "
    "partly turned or in the background? A figure seen only from behind, a silhouette or "
    "hands alone is not a face.\n"
    "- readable_text: is there any lettering, number, sign, caption or logo in any frame?\n"
    "- matches_plan: does the clip show what the plan asks for?\n"
    "- look_ok: does it keep the film's look (light, palette, grain) in every frame?\n"
    "- technical_ok: are all three frames free of warped or melting shapes, morphing "
    "bodies, smears, flicker artefacts and stripes?\n"
    "- same_shot: are the three frames one continuous shot of the same place, with no cut "
    "to another picture and nothing turning into something else?\n"
    "- one_picture: is each frame ONE continuous photograph filling the whole frame? A "
    "collage, a split screen, a grid, panels stacked one above another, a comic strip, or a "
    "frame with a blank or black band across it is not one picture.\n"
    "- bible_violations: name the violation or write none. Check every rule listed.\n"
    "- verdict: keep only if the clip is right as it is; regenerate_motion if animating the "
    "same still again could fix it; back_to_still if the still itself must change (always "
    "when one_picture is false: the same still animated again shows the same panels).\n"
    'Return only JSON: {{"clips": [{{"scene": {scene}, "faces_visible": false, '
    '"readable_text": false, "matches_plan": true, "look_ok": true, "technical_ok": true, '
    '"same_shot": true, "one_picture": true, "bible_violations": "none", "verdict": "keep", '
    '"reason": "one short sentence saying what you actually see"}}]}}\n'
)


def _clip_not_run(
    detail: str,
    *,
    run_id: str | None = None,
    looked_by: str | None = None,
    width: int | None = None,
    frames: int = 0,
) -> ClipJudgement:
    return ClipJudgement(
        status="NOT_RUN",
        verdict=None,
        detail_ro=f"clipul nu a fost privit: {detail}",
        run_id=run_id,
        looked_by=looked_by,
        image_width=width,
        frames=frames,
    )


def judge_clip(
    engine: Engine,
    registry: Any | None,
    frame_paths: Sequence[Path | str],
    plan: StillPlan,
    correlation_id: str,
    *,
    motion_prompt: str = "",
    ffmpeg_path: str | None = None,
) -> ClipJudgement:
    """One vision call on one clip's first, middle and last frames, at 1080 px, by the
    LOOKERS. MEASURED only when the model answered for exactly this scene with every field;
    anything else is NOT_RUN ("clipul nu a fost privit"), which clip QC treats as a block."""
    if len(frame_paths) != CLIP_FRAMES:
        return _clip_not_run(f"s-au tăiat {len(frame_paths)} cadre, nu {CLIP_FRAMES}")
    if registry is None or not registry.registered_ids():
        return _clip_not_run("niciun furnizor de modele nu este înregistrat")
    with Session(engine) as session:
        looker = vision_agent(session, *LOOKERS)
    if looker is None:
        return _clip_not_run("niciun angajat nu are un model care vede")
    looker_id, looker_name = looker
    ffmpeg = find_ffmpeg(ffmpeg_path)
    images = [still_image(ffmpeg, path) for path in frame_paths]
    if any(image is None for image in images):
        return _clip_not_run(
            "cadrele nu au putut fi pregătite la 1080 px (lipsește codorul sau fișierul)",
            looked_by=looker_name,
        )
    shown = {
        "scene": plan.scene,
        "plan": plan.still_prompt,
        "camera_move": plan.camera_move,
        "motion": motion_prompt,
        "look": plan.look_block,
        "faces_forbidden": plan.faces_forbidden,
        "bible_rules": list(plan.bible_rules),
    }
    prompt = _CLIP_INSTRUCTIONS.format(scene=plan.scene) + wrap_in_inert_boundary(
        json.dumps(shown, ensure_ascii=False)[:8000], "the-clip"
    )

    from app.agents.structured import structured_run  # noqa: PLC0415

    parsed, first, second = structured_run(
        engine,
        registry,
        looker_id,
        CLIP_TASK,
        prompt,
        CLIP_TEMPLATE_VERSION,
        correlation_id,
        ClipJudgeReport,
        '{"clips": [...]}',
        summary=f"Mă uit la clipul scenei {plan.scene} înainte să intre în film.",
        max_tokens=800,
        temperature=0.1,
        extra={"images": [image for image in images if image is not None]},
    )
    run = second or first
    run_id = run["id"]
    if parsed is None:
        return _clip_not_run(
            f"{looker_name} nu a dat un verdict utilizabil ({run['status']})",
            run_id=run_id,
            looked_by=looker_name,
            width=STILL_WIDTH,
            frames=CLIP_FRAMES,
        )
    entries = [verdict for verdict in parsed.clips if verdict.scene == plan.scene]
    if len(entries) != 1:
        return _clip_not_run(
            f"{looker_name} nu a răspuns pentru scena {plan.scene}"
            if not entries
            else f"{looker_name} a dat {len(entries)} verdicte pentru scena {plan.scene}",
            run_id=run_id,
            looked_by=looker_name,
            width=STILL_WIDTH,
            frames=CLIP_FRAMES,
        )
    return ClipJudgement(
        status="MEASURED",
        verdict=entries[0],
        detail_ro=entries[0].reason,
        run_id=run_id,
        looked_by=looker_name,
        image_width=STILL_WIDTH,
        frames=CLIP_FRAMES,
    )
