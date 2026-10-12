"""The Director's second look at a picture quality control refused, before a redo is bought.

2026-10-12: 19.50 USD went to RunPod in one day, 11.05 USD of it on redos, and all three films
still failed quality control. The refusals behind those redos were readings — read on the
database copy: 42 stills refused by the stills gate (YuNet's face count on 1c038a99's faceless
bible, the vision model's «lettering» on the serial's ledger in f06808c9 scene 4), 3 clips by the
clip QC, 17 film scenes by the film's picture checks (f06808c9 scene 7: «a small sketched mark is
visible on the whiteboard») — and a reading can be wrong: on 2026-10-10 a night sky was read as a
band between panels (babcf272). Each refusal bought the next still or clip without anyone looking
whether it was right. The Owner, the same afternoon: «trece imaginile picate de la QC pe la
Directoare și să decidă dacă au picat corect sau nu și dacă trebuie refăcute», and, as a standing
rule, «LLM-ul este pe abonament! NU COSTĂ BANI SĂ TRECEM PE LA EI! GENERAREA DE IMAGINI ȘI
MIȘCĂRI COSTĂ!». A look costs nothing; a redo costs credits. So before a paid still re-roll, a
clip retry or her own film repair is bought for a refusal, the Director looks at the picture
herself (`second_look`), with quality control's own words, the scene's intent and the bible's
rules in front of her, and decides:

- OVERTURNED (no defect, or a minor one: «DIRECTOAREA ACCEPTĂ DEFECTELE MICI!»): nothing is
  bought for it, the picture is used;
- CONFIRMED: the purchase proceeds, her reason added to the redo's reasons;
- UNAVAILABLE (nobody's model sees, she has no seeing model, the answer did not validate twice,
  anything went wrong): the refusal stands, exactly as before this look existed. Never raised.

The agents decide (the Owner: «LLM-urile pot raționa, pot lua decizii și pot hotărî!»): code
gives her the evidence and records what she decided; it does not decide for her. Her answer is
validated only for consistency — a serious defect is never waved through, an overturned refusal
never buys — and an inconsistent answer is asked again with the reason quoted
(`agents.structured.structured_run`).

Every look writes one ``media.director_second_look`` event (UNAVAILABLE included, with why), and
what she concluded becomes her own AGENT_OPINION memory, as her look at the candidates of her
repair does (`agents.reviews.review_bought_pictures`, whose model choice and prompt style this
follows).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.identity import clipped
from app.factual.sanitizer import wrap_in_inert_boundary
from app.media.models import (
    MediaAsset,
    SceneTake,
    Storyboard,
    StoryboardScene,
    VideoRenderJob,
)
from app.models import DomainEvent
from app.services import append_event

logger = logging.getLogger("studio.second_look")

#: The event every look writes, on the storyboard (the register's sentence is the events feed's).
SECOND_LOOK_EVENT = "media.director_second_look"
SECOND_LOOK_TASK = "director_second_look"
SECOND_LOOK_TEMPLATE_VERSION = "director-second-look-v1"
#: What a look can be about: a candidate still, a bought clip, a scene of a finished film.
KINDS = ("still", "shot", "film_scene")
#: Her verdicts, and the one the code gives when she could not look.
CONFIRMED, OVERTURNED, UNAVAILABLE = "CONFIRMED", "OVERTURNED", "UNAVAILABLE"
SEVERITIES = ("none", "minor", "serious")
#: The most pictures one look is shown: a still is one, a shot or a film scene three frames.
MAX_IMAGES = 6
#: The most of quality control's sentences she is shown (each cut at REFUSAL_CHARS).
MAX_REFUSALS = 12
REFUSAL_CHARS = 400
#: Her earlier looks at the same scene shown to her, newest last, so she stays consistent.
EARLIER_LOOKS_SHOWN = 3
VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".webm", ".mkv", ".m4v"})
#: A string longer than any path that is only base64's alphabet is a prepared picture
#: (`picture_qc.still_image`'s output, as `director_qc.look_pictures` gives it).
_BASE64 = re.compile(r"[A-Za-z0-9+/=\s]+")


class SecondLook(BaseModel):
    """Her answer, validated for consistency only: what she sees is hers.

    - OVERTURNED: the refusal is wrong, or the defect is real but minor and the picture can be
      used as it is. Nothing is made again (redo false), and it is never serious.
    - CONFIRMED: the defect is there and the scene must be made again (redo true); it names a
      defect, so its severity is minor or serious, never none.
    """

    model_config = ConfigDict(extra="ignore")
    verdict: Literal["CONFIRMED", "OVERTURNED"]
    severity: Literal["none", "minor", "serious"]
    redo: bool
    reason_ro: str = Field(min_length=1, max_length=600)
    _clip_reason = field_validator("reason_ro", mode="before")(clipped(600))

    @field_validator("verdict", mode="before")
    @classmethod
    def _upper(cls, value: Any) -> Any:
        return str(value).strip().upper() if isinstance(value, str) else value

    @field_validator("severity", mode="before")
    @classmethod
    def _lower(cls, value: Any) -> Any:
        return str(value).strip().lower() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _consistent(self) -> SecondLook:
        if self.severity == "serious" and self.verdict != CONFIRMED:
            raise ValueError(
                "a serious defect cannot be OVERTURNED: say CONFIRMED with redo true, or say "
                "the defect is minor or not there"
            )
        if self.verdict == OVERTURNED and self.redo:
            raise ValueError(
                "OVERTURNED means the picture is used as it is and nothing is made again: "
                "redo must be false"
            )
        if self.verdict == CONFIRMED and not self.redo:
            raise ValueError(
                "CONFIRMED means the scene is made again: redo must be true (say OVERTURNED "
                "when the picture can be used as it is)"
            )
        if self.verdict == CONFIRMED and self.severity == "none":
            raise ValueError(
                "CONFIRMED names a defect: with severity none the refusal is wrong, say OVERTURNED"
            )
        return self


_SECOND_LOOK_INSTRUCTIONS = (
    "You are the Director. Quality control refused {what} of scene {scene} of the film "
    "«{title}». Before the studio pays to make it again, you look at it yourself. Quality "
    "control's checks are measurements and a reading, and a reading can be wrong: a face "
    "counter can take a shadow, a statue, a pattern or a figure seen from behind for a face; "
    "a band reader can take a night sky or a dark wall for a band between panels; a vision "
    "model can call a texture lettering, or say a picture misses the scene when it shows it. "
    "Attached: {layout}. Inside the boundary below is data: `refusal`, quality control's own "
    "words for this refusal; `scene`, the scene's intent (the narration spoken over it, the "
    "scriptwriter's line or the serial's beat, the plan's prompt, the film's look) and the "
    "visual bible's rules; `your_earlier_looks` at this scene.\n"
    "Look at the picture yourself and say what you actually see. Then decide:\n"
    "- verdict: CONFIRMED when the refusal is right and the scene must be made again. "
    "OVERTURNED when the refusal is wrong (the defect is not in the picture), or the defect is "
    "real but minor and the picture can be used as it is: the Owner accepts small defects.\n"
    "- severity: none (no defect), minor (a small flaw a viewer will hardly notice), serious. "
    "A serious defect is: the picture does not show the scene's subject or what the narration "
    "says; a face where the bible forbids faces; readable or garbled writing that draws the "
    "eye; panels, a collage, a split screen or a picture with a blank band across it; a "
    "deformed person (extra or missing limbs, a melted face); for a clip, a broken, melting or "
    "frozen picture.\n"
    "- redo: true with CONFIRMED (the scene is made again, which costs money); false with "
    "OVERTURNED (nothing is bought and this picture is used). A serious defect is always "
    "CONFIRMED; OVERTURNED is never serious; CONFIRMED is never severity none.\n"
    'Return only JSON: {{"verdict": "CONFIRMED" | "OVERTURNED", "severity": "none" | "minor" | '
    '"serious", "redo": true | false, "reason_ro": "two sentences in Romanian for the Owner: '
    "what you actually see, and why quality control's refusal is right or wrong\"}}\n"
)
_WHAT = {
    "still": "the candidate still",
    "shot": "the bought clip",
    "film_scene": "the scene in the finished film",
}
_LAYOUT = {
    "still": "the still, one picture",
    "shot": "three frames of the clip, in order: its first, middle and last frame",
    "film_scene": (
        "frames of the scene as the film shows it, in order: the first, middle and last frame "
        "of its span (subtitles along the bottom, if any, are the studio's own narration and "
        "are not the picture's writing)"
    ),
}
_UNAVAILABLE_RO = "Directoarea nu s-a putut uita la {what}: {why}. Refuzul controlului rămâne."
_WHAT_RO = {
    "still": "imaginea",
    "shot": "clipul",
    "film_scene": "scena din film",
}
#: The run's one sentence for the Owner's history, per kind.
_SUMMARY_RO = {
    "still": (
        "Mă uit eu la imaginea scenei {scene} din «{title}», refuzată de control, înainte să se "
        "cumpere alta."
    ),
    "shot": (
        "Mă uit eu la clipul scenei {scene} din «{title}», refuzat de control, înainte să se "
        "cumpere altul."
    ),
    "film_scene": (
        "Mă uit eu la scena {scene} din filmul «{title}», refuzată de control, înainte să se "
        "refacă pe bani."
    ),
}


# --------------------------------------------------------------------------- the evidence


def _short(text: Any, limit: int = 300) -> str:
    words = " ".join(str(text or "").split())
    return words if len(words) <= limit else words[: limit - 1].rstrip() + "…"


def scene_intent(session: Session, storyboard_id: str, scene_index: int) -> dict[str, Any]:
    """What the scene is meant to show, as she reads it beside quality control's words.

    The narration spoken over it; the scriptwriter's own line (``scene_picture``: the script's
    ``visual_description``, else the package's ``writer_visual`` — never the compiled still
    prompt again, which is what `visual_prompt` holds since the prompt writer overwrote it,
    2026-10-12 on the database copy); for an episode of the serial the beat (the room, who is
    in frame, the action, the part and its lines); the plan (still and motion prompts, the
    camera move, the film's look); and the bible (its rules, its avoid list, whether faces are
    forbidden). Reads only; a film or scene that is not there gives what is known."""
    from app.agents.editorial import is_serial_film  # noqa: PLC0415 - agents import media
    from app.factual.models import ScriptDraft  # noqa: PLC0415
    from app.media.prompt_lint import bible_face_rule  # noqa: PLC0415
    from app.media.stills_stage import _bible_rules  # noqa: PLC0415 - the gate's own rules

    board = session.get(Storyboard, storyboard_id) if storyboard_id else None
    if board is None:
        return {"scene_index": scene_index}
    script = session.get(ScriptDraft, board.script_draft_id) if board.script_draft_id else None
    serial = bool(is_serial_film(board, script))
    row = session.scalars(
        select(StoryboardScene).where(
            StoryboardScene.storyboard_id == storyboard_id,
            StoryboardScene.scene_index == scene_index,
        )
    ).first()
    package: dict[str, Any] = (
        dict(row.prompt_json) if row is not None and isinstance(row.prompt_json, dict) else {}
    )
    scenes = list(script.scenes_json or []) if script is not None else []
    entry: dict[str, Any] = (
        dict(scenes[scene_index - 1])
        if 1 <= scene_index <= len(scenes) and isinstance(scenes[scene_index - 1], dict)
        else {}
    )
    still_prompt = str(package.get("still_prompt") or (row.visual_prompt if row else "") or "")
    writer = str(entry.get("visual_description") or package.get("writer_visual") or "")
    if (
        not writer
        and row is not None
        and " ".join(str(row.visual_prompt or "").split()) != (" ".join(still_prompt.split()))
    ):
        writer = str(row.visual_prompt or "")
    bible = dict(board.visual_bible_json) if isinstance(board.visual_bible_json, dict) else {}
    intent: dict[str, Any] = {
        "film": str(board.title or storyboard_id[:8]).removeprefix("Storyboard: ").strip(),
        "serial": serial,
        "scene_index": scene_index,
        "scene_kind": str(row.scene_kind or "LIVE") if row is not None else None,
        "narration": _short(row.voiceover_segment if row is not None else "", 600),
        "purpose": _short(
            (row.story_purpose if row is not None else "") or entry.get("purpose") or "", 200
        ),
        "scene_picture": _short(writer, 600),
    }
    if serial:
        lines = [
            {
                "speaker": line.get("speaker"),
                "text": _short(line.get("text"), 200),
            }
            for line in entry.get("lines") or []
            if isinstance(line, dict)
        ][:6]
        intent["beat"] = {
            "part": str(entry.get("part") or ""),
            "location": str(
                package.get("location") or entry.get("location_name") or entry.get("location") or ""
            ),
            "in_frame": [
                str(person.get("name"))
                for person in package.get("in_frame") or []
                if isinstance(person, dict) and person.get("name")
            ],
            "action": _short(package.get("action"), 400),
            "lines": lines,
            "background": [str(name) for name in entry.get("background") or []][:6],
        }
    intent["plan"] = {
        "still_prompt": _short(still_prompt, 900),
        "motion_prompt": _short(package.get("motion_prompt"), 500) or None,
        "camera_move": package.get("camera_move") or None,
        "look": _short(package.get("look_block"), 400) or None,
    }
    avoid = bible.get("avoid")
    intent["bible"] = {
        "faces_forbidden": bible_face_rule(bible) is not None,
        "rules": list(_bible_rules(bible))[:12],
        "avoid": [str(item) for item in avoid][:12] if isinstance(avoid, list | tuple) else [],
    }
    return intent


def earlier_looks(session: Session, storyboard_id: str, scene_index: int) -> list[dict[str, Any]]:
    """Her earlier second looks at this scene, newest last (at most `EARLIER_LOOKS_SHOWN`)."""
    out: list[dict[str, Any]] = []
    for event in session.scalars(
        select(DomainEvent)
        .where(
            DomainEvent.event_type == SECOND_LOOK_EVENT,
            DomainEvent.aggregate_id == storyboard_id,
        )
        .order_by(DomainEvent.sequence)
    ):
        payload = event.payload if isinstance(event.payload, dict) else {}
        if payload.get("scene_index") != scene_index or payload.get("verdict") == UNAVAILABLE:
            continue
        out.append(
            {
                "at": event.timestamp,
                "kind": payload.get("kind"),
                "refusal": [_short(text, 200) for text in payload.get("refusal") or []][:3],
                "verdict": payload.get("verdict"),
                "severity": payload.get("severity"),
                "reason_ro": _short(payload.get("reason_ro"), 400),
            }
        )
    return out[-EARLIER_LOOKS_SHOWN:]


# ----------------------------------------------------------------------------- the pictures


def _work_dir(work_dir: Path | None, key: str) -> Path:
    base = work_dir if work_dir is not None else Path(tempfile.gettempdir()) / "amn_second_look"
    folder = base / hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def frames_of(
    path: str | Path,
    kind: str,
    *,
    work_dir: Path | None = None,
    ffmpeg_path: str | None = None,
) -> list[str]:
    """What she is shown of one file, as local paths: a still (or a frame) as it is; a clip's
    first, middle and last frame, cut as quality control cuts them (`qc.clip_frames`, 1080 px
    PNGs). Empty when the file is not there or the frames cannot be cut (no encoder): the
    caller reads that as «not looked at», never as a pass. ``kind`` is the look's kind (still,
    shot, film_scene); what is shown follows the file, not the kind: a picture is shown as it
    is, a video as its three frames, whichever look it is for."""
    from app.media.qc import clip_frames  # noqa: PLC0415 - a large module
    from app.media.toolchain import find_ffmpeg  # noqa: PLC0415

    file = Path(path)
    if not file.is_file():
        return []
    if file.suffix.lower() not in VIDEO_SUFFIXES:
        return [str(file)]
    folder = _work_dir(work_dir, f"{kind}:{file.resolve()}")
    frames = clip_frames(find_ffmpeg(ffmpeg_path), file, folder)
    return [str(frame) for _at, _time, frame in frames]


def _file_sha256(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def film_scene_frames(
    engine: Engine,
    media_asset_id: str,
    scene_index: int,
    *,
    work_dir: Path | None = None,
    ffmpeg_path: str | None = None,
    frame_numbers: Sequence[int] = (),
) -> tuple[list[str], str | None]:
    """The scene's first, middle and last frame as the finished film shows it, and where they
    came from, for a look at a film-QC finding (her REPAIR; `scripts/qc_audit.py`):

    - SHOT: the scene's own shot beside the film, before the captions were burnt in
      (`picture_qc.clean_shots`, verified by its sha256), as quality control judged it;
    - CLIP: the clip take the render cut the scene from, its file still the one bought;
    - FILM: the film's own frames, by the numbers quality control recorded on the scene's span
      (``frame_numbers``), else by the render's timeline (`qc.timeline_spans`);
    - STILL: the still take the scene was filmed from, when nothing else can be cut.

    ([], None) when nothing can be prepared: the caller reads it as «not looked at»."""
    from app.agents.vision import frames_at  # noqa: PLC0415
    from app.media.picture_qc import clean_shots  # noqa: PLC0415 - a large module
    from app.media.qc import (  # noqa: PLC0415 - a large module
        DEFAULT_TIMELINE_FPS,
        span_frame_numbers,
        timeline_spans,
    )

    with Session(engine) as session:
        asset = session.get(MediaAsset, media_asset_id)
        job = session.scalar(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == media_asset_id)
        )
        if asset is None or job is None:
            return [], None
        production: dict[str, Any] = (
            dict(job.production_json) if isinstance(job.production_json, dict) else {}
        )
        planned = {
            int(row.scene_index): float(row.duration_seconds or 0.0)
            for row in session.scalars(
                select(StoryboardScene).where(StoryboardScene.storyboard_id == job.storyboard_id)
            )
        }
        film = Path(str(asset.uri_or_path or ""))
        recorded = next(
            (
                entry
                for entry in production.get("scenes") or []
                if isinstance(entry, Mapping) and entry.get("scene_index") == scene_index
            ),
            {},
        )
        takes: dict[str, tuple[str, str | None]] = {}
        for key in ("motion", "still_take"):
            entry = recorded.get(key)
            take_id = entry.get("take_id") if isinstance(entry, Mapping) else None
            row = session.get(SceneTake, take_id) if take_id else None
            if row is not None and row.path:
                takes[key] = (str(row.path), row.sha256)
    folder = _work_dir(work_dir, f"{media_asset_id}:{scene_index}")
    shot = clean_shots(production, film.parent).get(scene_index) if str(film) != "." else None
    if shot is not None:
        frames = frames_of(shot.path, "film_scene", work_dir=folder, ffmpeg_path=ffmpeg_path)
        if frames:
            return frames, "SHOT"
    clip = takes.get("motion")
    if clip is not None and _file_sha256(Path(clip[0])) == clip[1]:
        frames = frames_of(clip[0], "film_scene", work_dir=folder, ffmpeg_path=ffmpeg_path)
        if frames:
            return frames, "CLIP"
    if film.is_file():
        numbers = [int(n) for n in frame_numbers if int(n) >= 0]
        if not numbers:
            timeline = production.get("timeline")
            fps = float(
                (timeline.get("fps") if isinstance(timeline, dict) else None)
                or production.get("fps")
                or DEFAULT_TIMELINE_FPS
            )
            span = next(
                (s for s in timeline_spans(production, planned) if s["scene_index"] == scene_index),
                None,
            )
            if span is not None:
                numbers = [
                    n
                    for _at, n in span_frame_numbers(
                        span["start"], span["end"], fps, span["dissolve_seconds"]
                    )
                ]
        cut = frames_at(str(film), ffmpeg_path, numbers, folder / "film") if numbers else {}
        if cut and len(cut) == len(set(numbers)):
            return [str(cut[n]) for n in sorted(set(numbers))], "FILM"
    still = takes.get("still_take")
    if still is not None and _file_sha256(Path(still[0])) == still[1]:
        return [still[0]], "STILL"
    return [], None


def _prepared(
    images: Iterable[str], kind: str, *, ffmpeg_path: str | None, work_dir: Path | None
) -> list[str]:
    """The pictures as the seeing model is sent them (base64 JPEG at 1080 px,
    `picture_qc.still_image`): a still or a frame by its path; a clip by its three frames
    (`frames_of`); a picture already prepared as it is. At most `MAX_IMAGES`."""
    from app.media.picture_qc import still_image  # noqa: PLC0415 - a large module
    from app.media.toolchain import find_ffmpeg  # noqa: PLC0415

    ffmpeg = find_ffmpeg(ffmpeg_path)
    out: list[str] = []
    for item in images:
        text = str(item or "")
        if not text:
            continue
        path = Path(text) if len(text) < 1024 else None
        if path is not None and path.is_file():
            for frame in frames_of(path, kind, work_dir=work_dir, ffmpeg_path=ffmpeg_path):
                picture = still_image(ffmpeg, frame)
                if picture:
                    out.append(picture)
        elif len(text) > 256 and _BASE64.fullmatch(text):
            out.append(text)
        if len(out) >= MAX_IMAGES:
            break
    return out[:MAX_IMAGES]


# ------------------------------------------------------------------------------- the look


def _refusal(refusal: Iterable[Any]) -> list[str]:
    return [_short(text, REFUSAL_CHARS) for text in refusal if str(text or "").strip()][
        :MAX_REFUSALS
    ]


def _record(
    engine: Engine,
    *,
    storyboard_id: str,
    scene_index: int,
    kind: str,
    take_ids: list[str],
    refusal: list[str],
    outcome: dict[str, Any],
    correlation_id: str,
    director_id: str | None,
    title: str,
) -> None:
    """One event per look, and her own memory of what she concluded when she looked. A
    failure to record is logged, never raised: the look's answer still reaches its caller."""
    try:
        with Session(engine) as session, session.begin():
            append_event(
                session,
                SECOND_LOOK_EVENT,
                "storyboard",
                storyboard_id,
                1,
                {
                    "storyboard_id": storyboard_id,
                    "scene_index": scene_index,
                    "kind": kind,
                    "take_ids": take_ids,
                    "refusal": refusal,
                    "verdict": outcome["verdict"],
                    "severity": outcome["severity"],
                    "redo": outcome["redo"],
                    "reason_ro": outcome["reason_ro"],
                    "run_id": outcome["run_id"],
                },
                correlation_id,
            )
            if director_id and outcome["verdict"] != UNAVAILABLE:
                from app.agents.memory import remember  # noqa: PLC0415 - agents import media

                remember(
                    session,
                    memory_class="AGENT_OPINION",
                    content=(
                        f"Second look at the {kind.replace('_', ' ')} of scene {scene_index} of "
                        f"“{title}” that quality control refused: {outcome['verdict']} "
                        f"({outcome['severity']}) — {outcome['reason_ro']}"
                    )[:2000],
                    source_type="run",
                    source_id=outcome["run_id"],
                    agent_id=director_id,
                )
    except Exception as exc:  # noqa: BLE001 - the look's answer is returned all the same
        logger.warning("second_look_not_recorded", exc_info=exc)


def _unavailable(kind: str, why: str, run_id: str | None = None) -> dict[str, Any]:
    """The refusal stands, as before this look existed: ``redo`` True (what quality control's
    refusal already asks for), ``severity`` none (she judged nothing). Callers read ``verdict``."""
    return {
        "verdict": UNAVAILABLE,
        "severity": "none",
        "redo": True,
        "reason_ro": _UNAVAILABLE_RO.format(what=_WHAT_RO.get(kind, "imaginea"), why=why)[:600],
        "run_id": run_id,
    }


def second_look(
    engine: Engine,
    registry: Any | None,
    *,
    storyboard_id: str,
    scene_index: int,
    kind: Literal["still", "shot", "film_scene"],
    images: list[str],
    refusal: list[str],
    correlation_id: str,
    take_ids: Sequence[str] = (),
    ffmpeg_path: str | None = None,
    work_dir: Path | None = None,
) -> dict[str, Any]:
    """The Director looks at a picture quality control refused, before a redo is bought for it,
    and says whether the refusal is right, how serious the defect is and whether the scene must
    be made again.

    ``images`` are local files: a still, or frames (`frames_of`, `film_scene_frames`); a clip's
    file is cut into its first, middle and last frame; a picture already prepared as base64 is
    sent as it is. ``refusal`` is quality control's own words. She is asked on her seeing model
    (`agents.vision.seeing_model`: hers, a slot of hers, else the studio's seeing employee's;
    the run is hers whichever answers) through `structured_run`: an inconsistent answer is asked
    once more with why, and a second failure is UNAVAILABLE.

    Returns {verdict: CONFIRMED | OVERTURNED | UNAVAILABLE, severity: none | minor | serious,
    redo, reason_ro, run_id}. OVERTURNED is never serious and never redoes; CONFIRMED always
    redoes. UNAVAILABLE (no Director, no seeing model, no registry, no picture that can be
    prepared, a refused run, an answer that did not validate twice, any error) never raises and
    leaves the refusal standing (``redo`` True). Writes one ``media.director_second_look`` event
    in every case. Buys nothing."""
    take_list = [str(take) for take in take_ids or ()]
    words = _refusal(refusal or [])
    title = str(storyboard_id)[:8]
    director_id: str | None = None
    index = scene_index if isinstance(scene_index, int) else -1
    try:
        index = int(scene_index)
        if kind not in KINDS:
            raise ValueError(f"unknown look kind {kind!r}")
        outcome, director_id, title = _look(
            engine,
            registry,
            storyboard_id=storyboard_id,
            scene_index=index,
            kind=kind,
            images=list(images or []),
            refusal=words,
            correlation_id=correlation_id,
            ffmpeg_path=ffmpeg_path,
            work_dir=work_dir,
        )
    except Exception as exc:  # noqa: BLE001 - a look never stops the caller's work
        logger.warning("second_look_failed", exc_info=exc)
        outcome = _unavailable(kind, f"o eroare la privire ({type(exc).__name__})")
    _record(
        engine,
        storyboard_id=storyboard_id,
        scene_index=index,
        kind=kind,
        take_ids=take_list,
        refusal=words,
        outcome=outcome,
        correlation_id=correlation_id,
        director_id=director_id,
        title=title,
    )
    return outcome


def _look(
    engine: Engine,
    registry: Any | None,
    *,
    storyboard_id: str,
    scene_index: int,
    kind: str,
    images: list[str],
    refusal: list[str],
    correlation_id: str,
    ffmpeg_path: str | None,
    work_dir: Path | None,
) -> tuple[dict[str, Any], str | None, str]:
    """The look itself: (outcome, the Director's id or None, the film's title)."""
    from app.agents.identity import blocker_of  # noqa: PLC0415
    from app.agents.memory import agent_for_role  # noqa: PLC0415 - agents import media
    from app.agents.services import PolicyKernelError  # noqa: PLC0415
    from app.agents.structured import structured_run  # noqa: PLC0415 - it imports services
    from app.agents.vision import seeing_model  # noqa: PLC0415
    from app.media.picture_qc import LOOKERS  # noqa: PLC0415 - a large module

    with Session(engine) as session:
        try:
            intent = scene_intent(session, storyboard_id, scene_index)
            history = earlier_looks(session, storyboard_id, scene_index)
        except Exception as exc:  # noqa: BLE001 - she still looks, with what QC said
            logger.warning("second_look_intent_unread", exc_info=exc)
            intent, history = {"scene_index": scene_index}, []
        title = str(intent.get("film") or storyboard_id[:8])
        director = agent_for_role(session, "Director")
        if director is None:
            return _unavailable(kind, "nu există o Directoare activă"), None, title
        director_id = str(director.id)
        model_id = seeing_model(session, director_id, *LOOKERS)
    if model_id is None:
        return (
            _unavailable(kind, "niciun model al studioului nu vede imagini"),
            director_id,
            title,
        )
    if registry is None or not registry.registered_ids():
        return (
            _unavailable(kind, "niciun furnizor de modele nu este înregistrat"),
            director_id,
            title,
        )
    pictures = _prepared(images, kind, ffmpeg_path=ffmpeg_path, work_dir=work_dir)
    if not pictures:
        why = "imaginile nu au putut fi pregătite (lipsește fișierul sau codorul)"
        return _unavailable(kind, why), director_id, title
    shown = {
        "kind": kind,
        "refused_by": {
            "still": "the stills gate",
            "shot": "the clip QC",
            "film_scene": "the film's quality control",
        }[kind],
        "refusal": refusal,
        "scene": intent,
        "your_earlier_looks": history,
    }
    prompt = _SECOND_LOOK_INSTRUCTIONS.format(
        what=_WHAT[kind], scene=scene_index, title=title[:80], layout=_LAYOUT[kind]
    ) + wrap_in_inert_boundary(
        json.dumps(shown, ensure_ascii=False, default=str)[:12000], "second-look"
    )
    try:
        parsed, first, second = structured_run(
            engine,
            registry,
            director_id,
            SECOND_LOOK_TASK,
            prompt,
            SECOND_LOOK_TEMPLATE_VERSION,
            correlation_id or str(uuid4()),
            SecondLook,
            "",
            summary=_SUMMARY_RO[kind].format(scene=scene_index, title=title[:60]),
            max_tokens=2000,
            extra={"images": pictures},
            model_id=model_id,
        )
    except PolicyKernelError as exc:
        return (
            _unavailable(kind, f"rularea a fost oprită ({_short(exc.block_reason, 200)})"),
            director_id,
            title,
        )
    last = second or first
    run_id = str(last.get("id")) if last.get("id") else None
    if parsed is None:
        blocker = blocker_of(str(last.get("output_text") or ""))
        if blocker is not None:
            why = f"s-a oprit: {_short(blocker.reason, 200)}"
        elif last.get("status") == "SUCCEEDED":
            why = "răspunsul ei nu a respectat forma cerută nici a doua oară"
        else:
            detail = _short(last.get("error_detail") or last.get("status"), 200)
            why = f"rularea nu a reușit ({detail})"
        return _unavailable(kind, why, run_id), director_id, title
    return (
        {
            "verdict": parsed.verdict,
            "severity": parsed.severity,
            "redo": bool(parsed.redo),
            "reason_ro": parsed.reason_ro.strip(),
            "run_id": run_id,
        },
        director_id,
        title,
    )
