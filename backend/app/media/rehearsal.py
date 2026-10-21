"""The zero-credit rehearsal: a film rebuilt from the files already paid for.

Measured on the Nepal film (2026-09-26): two whole renders were bought, the second repeating
every still and clip with the same prompts, and the film still failed quality control. Its
stills, one clip that starts from today's still, and its narration are on disk, paid for. The
first step of the fix costs nothing, and this module is that step:

1. ``adopt_existing_files`` copies the paid files of a storyboard's media folder into a new
   rehearsal folder (the original folder is only read) and records each one as a SceneTake:
   - a LIVE scene's still is checked locally at 0 credits (`still_gate.local_checks`: structure,
     sharpness, baked motion blur, and YuNet faces when the bible forbids them). A clean still
     is APPROVED by the Owner's adoption; a still that fails is PAID and not approved, and the
     sheet lists its scene as needing a new still with its price. It is never bought here.
   - a clip is kept (PAID) only when its first frame is the scene's still; a clip filmed from a
     picture a later render overwrote is REJECTED, never passed off as starting from today's
     still. The model that made each file is read from the render that delivered it.
   - the stills of scenes that are charts, titles or black screens are REJECTED: those scenes
     are composed locally (`cards.py`) from the verified numbers. The scene's kind is decided by
     `services.classify_scene_kind`, and a chart's numbers must pass `services.card_problems`
     against the SUPPORTED claims, or nothing at all is written.
2. ``rehearse`` adopts, then assembles the film from those takes alone
   (`assembler.assemble_from_takes`): the narration is the recorded voice files played back,
   the chart and the black screen are composed, the sound is mastered and the film encoded with
   the current master, and quality control runs on the result. No adapter is passed anywhere,
   so no vendor can be asked; the Owner's report says so and says what still needs credits.

Only the Owner (or ``test`` in a TEST studio) may adopt files: an agent, AUTORUN or a request
parameter cannot. A rehearsal folder inside the original folder is refused, so the original is
never written. Comments are English; every message the Owner reads is Romanian.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.factual.models import FactualClaim, ScriptDraft
from app.media import film_length
from app.media.assembler import (
    LIVE_KIND,
    TAKES_VISUAL_SOURCE,
    TakesMissing,
    assemble_from_takes,
    motion_fields,
    scene_joins,
    scene_kind_of,
    scene_spans,
    scene_view,
    shot_spans,
    still_fields,
    take_hash,
    whole_frames,
)
from app.media.cards import CARD_KINDS
from app.media.cost_plan import (
    STILL_CANDIDATES,
    STILLS_MODEL,
    STILLS_RESOLUTION,
    UnpricedError,
    credits_to_micros,
    load_price_table,
    price_shot,
    price_still,
    source_label,
)
from app.media.models import SceneTake, Storyboard, StoryboardScene, VideoRenderJob
from app.media.prompt_lint import bible_face_rule
from app.media.qc_report import ro_count, ro_number
from app.media.still_gate import CheckResult, StillPlan, local_checks
from app.media.toolchain import find_ffmpeg, find_ffprobe
from app.providers.media_base import TTSProvider, TTSResult
from app.providers.media_http import MediaProviderError
from app.services import append_event, studio_environment, utc_now

#: What a rehearsal's narration is labelled: the voice files already recorded, played back.
#: Never a vendor's name, so nothing reads the rehearsal as a new purchase of narration.
REUSED_VOICE_PROVIDER = "REUSED_VOICE_TAKES"
#: Who may adopt: the Owner, or ``test`` in a TEST studio. Nothing else.
OWNER = "owner"
TEST_ISSUER = "test"
#: What a still kept only so the Owner can see the rehearsal is approved by.
REHEARSAL_ONLY = " (doar repetiția)"
#: A clip whose first frame resembles the still at least this much starts from it. Measured
#: on the Nepal folder at 270x480 grey: 0.993 for the clip filmed from today's still, at most
#: 0.22 for the clips filmed from pictures the second render overwrote.
FIRST_FRAME_MATCH = 0.90
COMPARE_WIDTH, COMPARE_HEIGHT = 270, 480
#: The failure codes a take carries when the studio's own check, not a vendor, set it aside.
FACES_CODE = "LOCAL.FACES"
COMPOSED_CODE = "LOCAL.COMPOSED_SCENE"
MISMATCH_CODE = "LOCAL.FIRST_FRAME_MISMATCH"
UNMEASURED_CODE = "LOCAL.FIRST_FRAME_UNMEASURED"
DETAIL_MAX = 500

_STILL = re.compile(r"^scene_(\d{2})\.(png|jpe?g|webp)$", re.IGNORECASE)
_MOTION = re.compile(r"^motion_(\d{2})\.mp4$", re.IGNORECASE)
_VOICE = re.compile(r"^voice_(\d{2})\.(mp3|wav|m4a)$", re.IGNORECASE)

_CARD_WORDS = {
    "DATA_CARD": "Grafic compus local · 0 credite",
    "TITLE_CARD": "Titlu compus local · 0 credite",
    "BLACK": "Ecran negru compus local · 0 credite",
}


class RehearsalError(ValueError):
    """The rehearsal cannot be done as asked (a card without its verified numbers, a rehearsal
    folder that is not a copy, no encoder). Nothing has been written. Romanian."""


class RehearsalNotFound(LookupError):
    """The storyboard or its media folder does not exist. Romanian."""


class RehearsalRefused(PermissionError):
    """Someone other than the Owner asked to adopt files. Romanian."""


class AdoptExistingFilesCommand(BaseModel):
    """The Owner's request to rebuild a film from the files already paid for (0 credits).

    ``cards`` gives a chart's (or a title's) spec by scene number, when the storyboard does not
    carry it yet: every bar's value and unit is checked against the SUPPORTED claims.
    ``keep_flagged_for_rehearsal`` is his explicit choice to see the rehearsal with the stills
    that failed a local check (faces) instead of stopping at them; they stay listed as needing
    a new still. ``render`` false adopts only.
    """

    model_config = ConfigDict(extra="forbid")

    cards: dict[int, dict[str, Any]] = Field(default_factory=dict)
    keep_flagged_for_rehearsal: bool = False
    render: bool = True


# ------------------------------------------------------------------------------ the voice


class ReusedVoice(TTSProvider):
    """A scene's narration as it was recorded, played back: 0 characters, no vendor.

    It answers only for the words it recorded; asked for any other text it refuses, because a
    recording of other words is not this scene's narration.
    """

    PROVIDER_NAME = REUSED_VOICE_PROVIDER
    model: str | None = None
    voice_id: str | None = None
    integration_id: str | None = None

    def __init__(self, path: Path, seconds: float, text: str, scene_index: int) -> None:
        self.path = path
        self.seconds = seconds
        self.text = text
        self.scene_index = scene_index
        self.calls = 0

    async def health_check(self) -> dict[str, Any]:
        return {"status": "HEALTHY", "mode": "LOCAL_REPLAY"}

    async def list_voices(self) -> list[dict[str, Any]]:
        return []

    async def synthesize(
        self,
        text: str,
        *,
        voice_id: str | None = None,
        speed: float = 1.0,
        pitch: float = 1.0,
        extra: dict[str, Any] | None = None,
    ) -> TTSResult:
        self.calls += 1
        if " ".join(str(text).split()) != " ".join(self.text.split()):
            raise MediaProviderError(
                f"Scena {self.scene_index}: înregistrarea păstrată spune alt text decât scena "
                "de acum; repetiția nu cumpără o voce nouă."
            )
        suffix = self.path.suffix.lower().lstrip(".")
        return TTSResult(
            audio_bytes=self.path.read_bytes(),
            format="mp3" if suffix == "mp3" else suffix,
            duration_seconds=self.seconds,
            raw_response={"reused": self.path.name},
        )


# ------------------------------------------------------------------------- measuring


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _probe(ffprobe: str, path: Path) -> dict[str, Any]:
    """Width, height and duration of one file, as ffprobe reads them (None when absent)."""
    try:
        done = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        data = json.loads(done.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"width": None, "height": None, "duration": None}
    video: dict[str, Any] = next(
        (s for s in data.get("streams") or [] if s.get("codec_type") == "video"),
        {},
    )
    stated: Any = (data.get("format") or {}).get("duration")
    try:
        duration: float | None = float(stated) if stated is not None else None
    except (TypeError, ValueError):
        duration = None
    return {
        "width": int(video["width"]) if video.get("width") else None,
        "height": int(video["height"]) if video.get("height") else None,
        "duration": duration,
    }


def first_frame_similarity(ffmpeg: str, clip: Path, still: Path) -> float | None:
    """SSIM (grey, 270x480) between a clip's first frame and a still; None if unmeasured."""
    graph = (
        f"[0:v]trim=end_frame=1,scale={COMPARE_WIDTH}:{COMPARE_HEIGHT},format=gray[a];"
        f"[1:v]scale={COMPARE_WIDTH}:{COMPARE_HEIGHT},format=gray[b];"
        "[a][b]ssim=stats_file=-"
    )
    try:
        done = subprocess.run(
            [
                ffmpeg,
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(clip),
                "-i",
                str(still),
                "-filter_complex",
                graph,
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    found = re.search(r"All:([0-9.]+)", f"{done.stdout}\n{done.stderr}")
    return float(found.group(1)) if found else None


# ------------------------------------------------------------------------- the pieces


@dataclass
class _Scene:
    row_id: str
    index: int
    kind: str
    forced_by: str | None
    card: dict[str, Any] | None
    visual_prompt: str
    narration: str
    camera_move: str
    view: dict[str, Any]


def _authorise(engine: Engine, issued_by: str) -> None:
    who = str(issued_by or "").strip()
    if who == OWNER:
        return
    if who == TEST_ISSUER and studio_environment(engine) == "TEST":
        return
    raise RehearsalRefused(
        "Doar Proprietarul poate adopta fișierele deja plătite ale unui film; un agent, "
        f"AUTORUN-ul sau un parametru nu pot ({who or 'nimeni'})."
    )


def _check_folders(source_dir: Path | str, rehearsal_root: Path | str) -> tuple[Path, Path]:
    source = Path(source_dir).resolve()
    root = Path(rehearsal_root).resolve()
    if root == source or root.is_relative_to(source) or source.is_relative_to(root):
        raise RehearsalError(
            "Repetiția lucrează numai pe o copie: dosarul repetiției nu poate fi dosarul "
            f"original al filmului sau unul din interiorul lui ({root})."
        )
    if not source.is_dir():
        raise RehearsalNotFound(f"Dosarul cu fișierele filmului nu există: {source.name}.")
    return source, root


def _film_claims(session: Session, board: Storyboard, rows: list[StoryboardScene]) -> dict:
    """Every claim the film cites, as {id: (text, status)}."""
    ids: list[str] = []
    script = session.get(ScriptDraft, board.script_draft_id)
    for claim_id in [
        *(script.claim_ids_json if script else []),
        *[c for row in rows for c in (row.claim_ids_json or [])],
    ]:
        if isinstance(claim_id, str) and claim_id not in ids:
            ids.append(claim_id)
    found = session.scalars(select(FactualClaim).where(FactualClaim.id.in_(ids))).all()
    return {claim.id: (claim.claim_text, claim.status) for claim in found}


def _decide_kinds(
    rows: list[StoryboardScene],
    claims: Mapping[str, tuple[str, str]],
    cards: Mapping[int, Mapping[str, Any]],
) -> list[_Scene]:
    """Each scene's kind and card, refusing (RehearsalError) anything that cannot be drawn
    truly. Pure: nothing is written."""
    from app.media.services import card_problems, classify_scene_kind  # noqa: PLC0415

    indexes = {row.scene_index for row in rows}
    stray = sorted(int(n) for n in cards if int(n) not in indexes)
    if stray:
        raise RehearsalError(
            "Cardurile numesc scene care nu există în film: "
            + ", ".join(f"Scena {n}" for n in stray)
            + "."
        )
    problems: list[str] = []
    scenes: list[_Scene] = []
    for row in rows:
        own = [claims[c][0] for c in (row.claim_ids_json or []) if c in claims]
        kind, forced = classify_scene_kind(
            row.scene_kind, row.visual_prompt or "", row.voiceover_segment or "", own
        )
        given = cards.get(row.scene_index)
        card = (
            dict(given)
            if given is not None
            else (dict(row.card_json) if isinstance(row.card_json, dict) else None)
        )
        if kind == LIVE_KIND:
            if given is not None:
                problems.append(
                    f"Scena {row.scene_index} este filmată (LIVE); un card se dă doar unei "
                    "scene compuse (grafic, titlu, ecran negru)."
                )
            card = None
        else:
            problems += card_problems(row.scene_index, kind, card, claims)
        package = row.prompt_json if isinstance(row.prompt_json, dict) else {}
        scenes.append(
            _Scene(
                row_id=row.id,
                index=row.scene_index,
                kind=kind,
                forced_by=forced,
                card=card,
                visual_prompt=row.visual_prompt or "",
                narration=row.voiceover_segment or "",
                camera_move=str(package.get("camera_move") or "static"),
                view=scene_view(row),
            )
        )
    if problems:
        raise RehearsalError(
            "Repetiția nu compune un card fără cifrele lui verificate: " + " ".join(problems)
        )
    return scenes


def _legacy_manifests(session: Session, storyboard_id: str) -> list[dict[str, Any]]:
    """The production manifests of the renders that delivered files, newest first.

    A rehearsal's own render (assembled from takes, voices played back) delivered nothing new
    and is left out, so a second rehearsal still names the vendors' models.
    """
    jobs = session.scalars(
        select(VideoRenderJob)
        .where(
            VideoRenderJob.storyboard_id == storyboard_id,
            VideoRenderJob.status == "COMPLETED",
        )
        .order_by(VideoRenderJob.finished_at.desc())
    ).all()
    manifests: list[dict[str, Any]] = []
    for job in jobs:
        production = job.production_json if isinstance(job.production_json, dict) else {}
        image = production.get("image") or {}
        voice = production.get("voice") or {}
        if image.get("provider") == TAKES_VISUAL_SOURCE or (
            voice.get("provider") == REUSED_VOICE_PROVIDER
        ):
            continue
        manifests.append({"job_id": job.id, **production})
    return manifests


def _scene_entry(manifest: Mapping[str, Any], index: int) -> Mapping[str, Any]:
    for entry in manifest.get("scenes") or []:
        if isinstance(entry, Mapping) and entry.get("scene_index") == index:
            return entry
    return {}


def _still_model(manifests: list[dict[str, Any]], index: int) -> str:
    """The still on disk is the newest render's (each render overwrites scene_NN)."""
    if not manifests:
        return "unknown"
    newest = manifests[0]
    image = _scene_entry(newest, index).get("image")
    model = (image or {}).get("model") if isinstance(image, Mapping) else None
    return str(model or (newest.get("image") or {}).get("model") or "unknown")


def _motion_origin(manifests: list[dict[str, Any]], index: int, size: int) -> dict[str, Any]:
    """Which render filmed this clip: the one whose scene recorded exactly its bytes."""
    for manifest in manifests:
        motion = _scene_entry(manifest, index).get("motion")
        if isinstance(motion, Mapping) and motion.get("bytes") == size:
            return {"model": str(motion.get("model") or "unknown"), "job_id": manifest["job_id"]}
    return {"model": "unknown", "job_id": None}


def _recorded_characters(manifests: list[dict[str, Any]], index: int) -> int | None:
    if not manifests:
        return None
    value = _scene_entry(manifests[0], index).get("characters")
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def _check_dicts(checks: list[CheckResult]) -> list[dict[str, Any]]:
    return [
        {
            "code": c.code,
            "status": c.status,
            "blocking": c.blocking,
            "value": c.value,
            "detail_ro": c.detail_ro,
        }
        for c in checks
    ]


def _still_price() -> dict[str, Any]:
    """What a new still costs: the stills tier's candidates, at the published price."""
    try:
        table = load_price_table()
        credits = price_still(STILLS_MODEL, STILLS_RESOLUTION, STILL_CANDIDATES, table=table)
        return {
            "credits": credits,
            "usd_micros": credits_to_micros(credits, table.credit_usd),
            "credit_usd": table.credit_usd,
            "source": source_label(table.row(STILLS_MODEL, STILLS_RESOLUTION)),
        }
    except (OSError, ValueError, KeyError, TypeError, UnpricedError):
        return {"credits": None, "usd_micros": None, "credit_usd": None, "source": None}


def still_redo_words(credits: int | None) -> str:
    """'necesită o imagine nouă (18 credite)', or the price unknown, never 0."""
    price = ro_count(credits, "credite") if credits is not None else "preț necunoscut"
    return f"necesită o imagine nouă ({price})"


# ------------------------------------------------------------------------ the adoption


@dataclass
class _Context:
    ffmpeg: str
    ffprobe: str
    ffmpeg_path: str | None
    face_model: Path | None
    environment: str
    faces_forbidden: bool
    keep_flagged: bool
    manifests: list[dict[str, Any]]


def _voice_row(
    context: _Context, scene: _Scene, voice: Path | None
) -> tuple[dict[str, Any], ReusedVoice | None]:
    """The scene's recorded narration, played back, when it is the scene's words."""
    if voice is None:
        return {"status": "missing"}, None
    seconds = _probe(context.ffprobe, voice)["duration"]
    recorded = _recorded_characters(context.manifests, scene.index)
    if not seconds:
        return {"status": "unreadable", "file": voice.name}, None
    if recorded is not None and recorded != len(scene.narration):
        return {"status": "text_changed", "file": voice.name}, None
    return (
        {"status": "adopted", "file": voice.name, "seconds": seconds},
        ReusedVoice(voice, seconds, scene.narration, scene.index),
    )


def _still_take(
    context: _Context, scene: _Scene, still: Path
) -> tuple[dict[str, Any], dict[str, Any], list[CheckResult]]:
    """The take of one paid still: APPROVED when the local checks pass, PAID (or APPROVED only
    for the rehearsal, by the Owner's choice) when one blocks, REJECTED for a card scene."""
    size = _probe(context.ffprobe, still)
    model = _still_model(context.manifests, scene.index)
    sha = _sha256(still)
    take: dict[str, Any] = {
        "kind": "still",
        "scene": scene.index,
        "path": still,
        "sha256": sha,
        "model_id": model,
        "resolution": f"{size['width']}:{size['height']}",
        "seconds": None,
        "prompt_hash": take_hash(still_fields(scene.visual_prompt, None), model),
    }
    if scene.kind in CARD_KINDS:
        take.update(
            status="REJECTED",
            approved_by=None,
            failure_code=COMPOSED_CODE,
            failure_detail=(
                f"Scena {scene.index} se compune local ({_CARD_WORDS[scene.kind]}); "
                "imaginea plătită pentru ea nu se folosește."
            ),
        )
        return take, {"status": "REJECTED", "file": still.name, "reasons": [], "checks": []}, []
    checks = local_checks(
        still,
        StillPlan(
            scene=scene.index,
            still_prompt=scene.visual_prompt,
            camera_move=scene.camera_move,
            faces_forbidden=context.faces_forbidden,
        ),
        environment=context.environment,
        ffmpeg_path=context.ffmpeg_path,
        face_model=context.face_model,
        measure=("degenerate", "sharpness", "motion_blur", "faces"),
    )
    flagged = [c for c in checks if c.blocking]
    code: str | None = None
    detail: str | None = None
    status: str = "APPROVED"
    approver: str | None = OWNER
    if flagged:
        code = "LOCAL." + flagged[0].code.upper()
        detail = "; ".join(c.detail_ro for c in flagged)[:DETAIL_MAX]
        if context.keep_flagged:
            status, approver = "APPROVED", OWNER + REHEARSAL_ONLY
        else:
            status, approver = "PAID", None
    take.update(status=status, approved_by=approver, failure_code=code, failure_detail=detail)
    row = {
        "status": status,
        "approved_by": approver if status == "APPROVED" else None,
        "model_id": model,
        "file": still.name,
        "sha256": sha,
        "checks": _check_dicts(checks),
        "reasons": [c.detail_ro for c in flagged],
    }
    return take, row, flagged


def _motion_verdict(
    scene: _Scene, similarity: float | None, flagged: list[CheckResult]
) -> dict[str, Any]:
    """PAID only when the clip's first frame is the scene's still; REJECTED otherwise."""
    if scene.kind in CARD_KINDS:
        return {
            "status": "REJECTED",
            "failure_code": COMPOSED_CODE,
            "failure_detail": f"Scena {scene.index} se compune local; clipul nu se folosește.",
        }
    if similarity is None:
        return {
            "status": "REJECTED",
            "failure_code": UNMEASURED_CODE,
            "failure_detail": (
                "Nu s-a putut măsura dacă clipul pornește din imaginea scenei; nu se "
                "folosește fără această dovadă."
            ),
        }
    if similarity < FIRST_FRAME_MATCH:
        return {
            "status": "REJECTED",
            "failure_code": MISMATCH_CODE,
            "failure_detail": (
                "Clipul pornește din altă imagine decât imaginea scenei de acum "
                f"(asemănare {ro_number(similarity, 2)}, pragul "
                f"{ro_number(FIRST_FRAME_MATCH, 2)}): a fost filmat dintr-o imagine pe "
                "care o randare ulterioară a înlocuit-o."
            ),
        }
    # Paid and usable; the clip carries whatever the still it starts from carries.
    return {
        "status": "PAID",
        "failure_code": ("LOCAL." + flagged[0].code.upper()) if flagged else None,
        "failure_detail": (
            f"Pornește dintr-o imagine respinsă la verificare: {flagged[0].detail_ro}"
            if flagged
            else None
        ),
    }


def foreseen_spans(
    views: list[Mapping[str, Any]], spoken: list[float | None]
) -> tuple[list[float], list[float]]:
    """How long each scene will last on the film's timeline, and the shot each clip must
    fill, before a render: the assembler's own formulas, not a second guess at them.

    With every scene's narration recorded, a scene lasts its words plus a breath, never past
    its plan and never cutting a word (assembler.scene_spans); otherwise the render keeps the
    plan on whole frames, and so does this. A shot is its scene plus the dissolve the next
    scene asks for (assembler.shot_spans), which is what the render requires a reused clip to
    cover. It used to be max(plan, words) + 0.4 s, the timeline from before 2026-10-01, so the
    sheet could call a paid clip too short that the render would use.

    A film timed by its frozen pauses («pauza vocii», 2026-10-16): each scene's words hold its
    share of them (`film_length.frozen_rows`), every cut on a frame of the cumulative
    timeline, as the render lays it; a film built before them keeps the legacy breath.
    """
    planned = [float(view.get("duration_seconds") or 0.0) for view in views]
    if views and all(isinstance(seconds, int | float) for seconds in spoken):
        plans = film_length.frozen_rows(views)
        lengths = scene_spans(
            planned,
            spoken,
            kinds=[scene_kind_of(dict(view)) for view in views],
            pauses=[plan.share for plan in plans] if plans is not None else None,
        )
    else:
        lengths = [whole_frames(plan) for plan in planned]
    scenes = [
        {**dict(view), "duration_seconds": length}
        for view, length in zip(views, lengths, strict=True)
    ]
    return lengths, shot_spans(scenes, scene_joins(scenes))


def _motion_take(
    context: _Context,
    scene: _Scene,
    clip: Path,
    still: Path | None,
    flagged: list[CheckResult],
    scene_seconds: float,
    shot_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The take of one paid clip, and its row on the sheet (whether the film can use it)."""
    measured = _probe(context.ffprobe, clip)
    origin = _motion_origin(context.manifests, scene.index, clip.stat().st_size)
    similarity = (
        first_frame_similarity(context.ffmpeg, clip, still)
        if still is not None and scene.kind == LIVE_KIND
        else None
    )
    starts_here = similarity is not None and similarity >= FIRST_FRAME_MATCH
    seconds = round(measured["duration"], 3) if measured["duration"] else None
    first_frame = _sha256(still) if starts_here and still is not None else None
    take: dict[str, Any] = {
        "kind": "motion",
        "scene": scene.index,
        "path": clip,
        "sha256": _sha256(clip),
        "model_id": origin["model"],
        "resolution": f"{measured['width']}:{measured['height']}",
        "seconds": seconds,
        "prompt_hash": take_hash(
            motion_fields(scene.view, first_frame, from_prompt=False), origin["model"]
        ),
        "approved_by": None,
        **_motion_verdict(scene, similarity, flagged),
    }
    # What the render asks of a reused clip: that it covers its shot, the scene's span on the
    # timeline plus any dissolve into the next scene (foreseen_spans). A shorter clip is not
    # used (a frozen tail is not motion). ``span`` is the shot, as the sheet reads it after a
    # render (_lines_from_film).
    span = round(shot_seconds, 3)
    row = {
        "status": take["status"],
        "model_id": origin["model"],
        "from_render": origin["job_id"],
        "file": clip.name,
        "seconds": seconds,
        "scene_seconds": round(scene_seconds, 3),
        "span": span,
        "used": take["status"] == "PAID" and seconds is not None and seconds >= span,
        "first_frame_similarity": similarity,
        "detail_ro": take.get("failure_detail"),
    }
    return take, row


def _adopt(
    engine: Engine,
    storyboard_id: str,
    source_dir: Path | str,
    *,
    rehearsal_root: Path | str,
    issued_by: str,
    correlation_id: str,
    cards: Mapping[int, Mapping[str, Any]] | None,
    keep_flagged_for_rehearsal: bool,
    ffmpeg_path: str | None,
    face_model: Path | None,
) -> tuple[dict[str, Any], dict[int, ReusedVoice]]:
    _authorise(engine, issued_by)
    source, root = _check_folders(source_dir, rehearsal_root)
    environment = studio_environment(engine)
    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        if board is None:
            raise RehearsalNotFound("Storyboardul nu există.")
        rows = list(
            session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == storyboard_id)
                .order_by(StoryboardScene.scene_index)
            ).all()
        )
        if not rows:
            raise RehearsalNotFound("Storyboardul nu are scene.")
        claims = _film_claims(session, board, rows)
        scenes = _decide_kinds(rows, claims, {int(k): v for k, v in (cards or {}).items()})
        bible = board.visual_bible_json if isinstance(board.visual_bible_json, dict) else {}
        manifests = _legacy_manifests(session, storyboard_id)
    faces_forbidden = bible_face_rule(bible) is not None

    ffmpeg = find_ffmpeg(ffmpeg_path)
    ffprobe = find_ffprobe(ffmpeg_path)
    if not ffmpeg or not ffprobe:
        raise RehearsalError(
            "Repetiția are nevoie de ffmpeg și ffprobe pentru a măsura și a copia fișierele; "
            "nu sunt instalate."
        )

    # Only what the film is made of is copied: stills, clips, narration. The original folder
    # is read, never written, and every copy is checked byte for byte against it.
    found: dict[str, dict[int, Path]] = {"still": {}, "motion": {}, "voice": {}}
    for path in sorted(source.iterdir()):
        if not path.is_file():
            continue
        for kind, pattern in (("still", _STILL), ("motion", _MOTION), ("voice", _VOICE)):
            matched = pattern.match(path.name)
            if matched:
                found[kind].setdefault(int(matched.group(1)), path)
    legacy = root / "legacy"
    legacy.mkdir(parents=True, exist_ok=True)
    copies: dict[str, dict[int, Path]] = {"still": {}, "motion": {}, "voice": {}}
    for kind, files in found.items():
        for index, original in files.items():
            target = legacy / original.name
            shutil.copyfile(original, target)
            if _sha256(target) != _sha256(original):
                raise RehearsalError(f"Copia fișierului {original.name} nu este identică.")
            copies[kind][index] = target

    price = _still_price()
    context = _Context(
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        ffmpeg_path=ffmpeg_path,
        face_model=face_model,
        environment=environment,
        faces_forbidden=faces_forbidden,
        keep_flagged=keep_flagged_for_rehearsal,
        manifests=manifests,
    )
    plans: list[dict[str, Any]] = []
    voices: dict[int, ReusedVoice] = {}
    rows_out: list[dict[str, Any]] = []
    voice_rows: dict[int, dict[str, Any]] = {}
    for scene in scenes:
        voice_rows[scene.index], reused = _voice_row(
            context, scene, copies["voice"].get(scene.index)
        )
        if reused is not None:
            voices[scene.index] = reused
    # Every scene's words are measured first: a scene's length on the timeline depends on
    # all of them (the breaths are shared out across the film).
    scene_seconds, shot_seconds = foreseen_spans(
        [scene.view for scene in scenes],
        [voices[scene.index].seconds if scene.index in voices else None for scene in scenes],
    )
    for position, scene in enumerate(scenes):
        row: dict[str, Any] = {
            "scene_index": scene.index,
            "kind": scene.kind,
            "kind_forced_by": scene.forced_by,
            "still": None,
            "motion": None,
            "voice": voice_rows[scene.index],
            "credits_needed": 0,
        }
        still = copies["still"].get(scene.index)
        flagged: list[CheckResult] = []
        if still is not None:
            take, row["still"], flagged = _still_take(context, scene, still)
            plans.append(take)
        clip = copies["motion"].get(scene.index)
        if clip is not None:
            take, row["motion"] = _motion_take(
                context,
                scene,
                clip,
                still,
                flagged,
                scene_seconds[position],
                shot_seconds[position],
            )
            plans.append(take)
        rows_out.append(row)

    # One transaction: the kinds and cards, every take and the adoption itself, or nothing.
    adopted_at = utc_now()
    take_ids: dict[tuple[int, str], str] = {}
    with Session(engine) as session, session.begin():
        kinds_set: dict[str, str] = {}
        for scene in scenes:
            record = session.get(StoryboardScene, scene.row_id)
            if record is None:
                continue
            if record.scene_kind != scene.kind or (record.card_json or None) != scene.card:
                kinds_set[str(scene.index)] = scene.kind
            record.scene_kind = scene.kind
            record.visual_type = scene.kind
            record.card_json = scene.card
        for plan in plans:
            take_ids[(plan["scene"], plan["kind"])] = _upsert_take(
                session, storyboard_id, plan, correlation_id, adopted_at
            )
        flagged_scenes = [
            r["scene_index"]
            for r in rows_out
            if r["kind"] == LIVE_KIND and (r["still"] is None or r["still"]["reasons"])
        ]
        append_event(
            session,
            "media.existing_files_adopted",
            "storyboard",
            storyboard_id,
            1,
            {
                "issued_by": issued_by,
                "source_folder": source.name,
                "rehearsal_root": str(root),
                "takes": len(plans),
                "approved_stills": sum(
                    1 for p in plans if p["kind"] == "still" and p["status"] == "APPROVED"
                ),
                "needs_new_still": flagged_scenes,
                "kept_for_rehearsal": bool(keep_flagged_for_rehearsal and flagged_scenes),
                "kinds_set": kinds_set,
                "credits": 0,
            },
            correlation_id,
        )

    for row in rows_out:
        row["line_ro"], row["credits_needed"] = scene_line(row, price)
        for kind in ("still", "motion"):
            if row[kind] is not None and (row["scene_index"], kind) in take_ids:
                row[kind]["take_id"] = take_ids[(row["scene_index"], kind)]
    needs = [r["scene_index"] for r in rows_out if r["credits_needed"] or _needs_still(r)]
    sheet = {
        "scenes": rows_out,
        "needs_new_still": needs,
        "credits_spent": 0,
        "credits_needed_for_stills": (
            price["credits"] * len(needs) if price["credits"] is not None else None
        ),
        "still_price": price,
        "faces_forbidden": faces_forbidden,
        "vision_check": (
            "nerulată: repetiția nu cheltuie; privirea Proprietarului pe foaia de filmare "
            "rămâne verificarea finală"
        ),
    }
    return (
        {
            "storyboard_id": storyboard_id,
            "rehearsal_root": str(root),
            "legacy_folder": str(legacy),
            "takes": len(plans),
            "kinds": {str(s.index): s.kind for s in scenes},
            "sheet": sheet,
            "credits": 0,
        },
        voices,
    )


def _needs_still(row: Mapping[str, Any]) -> bool:
    if row["kind"] != LIVE_KIND:
        return False
    still = row.get("still")
    return still is None or bool(still.get("reasons"))


def _sentence(text: Any) -> str:
    """A reason quoted inside a line: no closing full stop, first letter lower case."""
    words = str(text or "").strip().rstrip(".")
    first = words.split(" ", 1)[0]
    if any(letter.isupper() for letter in first[1:]):
        return words  # a name ("YuNet") keeps its capitals
    return words[:1].lower() + words[1:]


def scene_line(row: Mapping[str, Any], price: Mapping[str, Any]) -> tuple[str, int]:
    """One scene of the rehearsal sheet as the Owner reads it, and the credits it still needs."""
    n = row["scene_index"]
    if row["kind"] in CARD_KINDS:
        return f"Scena {n}: {_CARD_WORDS[row['kind']]}.", 0
    parts: list[str] = []
    needed = 0
    if _needs_still(row):
        redo = still_redo_words(price.get("credits"))
        still = row.get("still")
        why = (
            "; ".join(_sentence(r) for r in still["reasons"])
            if still
            else "imaginea plătită lipsește din dosar"
        )
        kept = bool(still and still.get("status") == "APPROVED")
        parts.append(
            f"Scena {n}: {redo}: {why}"
            + (" (păstrată doar pentru repetiție, nu pentru filmul real)" if kept else "")
        )
        needed = int(price.get("credits") or 0)
    else:
        parts.append(f"Scena {n}: imaginea deja plătită e adoptată · 0 credite")
    motion = row.get("motion")
    if motion is None:
        parts.append("fără clip plătit: imagine fixă (mișcarea se cumpără doar cu aprobarea ta)")
    elif motion["status"] != "PAID":
        why = _sentence(motion.get("detail_ro")).removeprefix("clipul ")
        parts.append(f"clipul plătit nu se folosește: {why}")
    else:
        seconds = motion.get("seconds")
        what = f"clipul deja plătit ({motion['model_id']}" + (
            f", {ro_number(seconds, 2)} s)" if seconds else ")"
        )
        if motion.get("used"):
            parts.append(f"{what} se folosește")
        else:
            parts.append(
                f"{what} e mai scurt decât scena ({ro_number(motion.get('span') or 0, 2)} s), "
                "deci rămâne imagine fixă în această repetiție"
            )
    voice = row.get("voice") or {}
    if voice.get("status") != "adopted":
        parts.append("narațiunea înregistrată lipsește sau nu mai corespunde textului")
    return "; ".join(parts) + ".", needed


def _upsert_take(
    session: Session,
    storyboard_id: str,
    plan: Mapping[str, Any],
    correlation_id: str,
    now: str,
) -> str:
    """One adopted file as one take. Adopting again updates the same row (its new copy), and a
    decision already made on it (APPROVED, REJECTED) is never lowered by the adoption."""
    existing = session.scalars(
        select(SceneTake).where(
            SceneTake.storyboard_id == storyboard_id,
            SceneTake.scene_number == plan["scene"],
            SceneTake.kind == plan["kind"],
            SceneTake.prompt_hash == plan["prompt_hash"],
            SceneTake.sha256 == plan["sha256"],
        )
    ).first()
    take_id = existing.id if existing is not None else str(uuid4())
    status = plan["status"]
    approved_by = plan.get("approved_by")
    if existing is not None and existing.status in ("APPROVED", "REJECTED"):
        if existing.status != status:
            status, approved_by = existing.status, existing.approved_by
        elif existing.approved_by == OWNER:
            # The Owner's full approval is never narrowed to 'rehearsal only'.
            approved_by = OWNER
    event = append_event(
        session,
        "media.scene_take_recorded",
        "scene_take",
        take_id,
        1,
        {
            "storyboard_id": storyboard_id,
            "scene_number": plan["scene"],
            "kind": plan["kind"],
            "status": status,
            "model_id": plan["model_id"],
            "prompt_hash": plan["prompt_hash"],
            "credits_quoted": None,
            "failure_code": plan.get("failure_code"),
            "adopted": True,
        },
        correlation_id,
    )
    row = existing or SceneTake(
        id=take_id,
        storyboard_id=storyboard_id,
        scene_number=plan["scene"],
        kind=plan["kind"],
        prompt_hash=plan["prompt_hash"],
        created_at=now,
    )
    row.model_id = str(plan["model_id"] or "unknown")[:100]
    row.resolution = str(plan["resolution"])[:20]
    row.seconds = plan.get("seconds")
    row.seed = None
    # What one legacy file cost was never measured on its own: unknown, never 0.
    row.credits_quoted = None
    row.credits_measured = None
    row.status = status
    row.approved_by = approved_by if status == "APPROVED" else None
    row.failure_code = plan.get("failure_code")
    detail = plan.get("failure_detail")
    row.failure_detail = detail[:DETAIL_MAX] if isinstance(detail, str) else None
    row.path = str(plan["path"])
    row.sha256 = plan["sha256"]
    row.updated_at = now
    row.event_id = event.event_id
    if existing is None:
        session.add(row)
    return take_id


def adopt_existing_files(
    engine: Engine,
    storyboard_id: str,
    source_dir: Path | str,
    *,
    rehearsal_root: Path | str,
    issued_by: str,
    correlation_id: str | None = None,
    cards: Mapping[int, Mapping[str, Any]] | None = None,
    keep_flagged_for_rehearsal: bool = False,
    ffmpeg_path: str | None = None,
    face_model: Path | None = None,
) -> dict[str, Any]:
    """Adopt a storyboard's already-paid files as takes, on a copy, for 0 credits.

    ``source_dir`` is the film's media folder, only read; the files are copied under
    ``rehearsal_root/legacy`` and the takes point at the copies. Returns the adoption with its
    sheet: per scene its kind, the still's checks, the clip's verdict, the narration, the line
    the Owner reads, and what it still needs in credits (a new still: 'necesită o imagine nouă
    (18 credite)'). Nothing is bought, and no vendor is asked.
    """
    adopted, _voices = _adopt(
        engine,
        storyboard_id,
        source_dir,
        rehearsal_root=rehearsal_root,
        issued_by=issued_by,
        correlation_id=correlation_id or str(uuid4()),
        cards=cards,
        keep_flagged_for_rehearsal=keep_flagged_for_rehearsal,
        ffmpeg_path=ffmpeg_path,
        face_model=face_model,
    )
    return adopted


# ------------------------------------------------------------------------ the rehearsal


def _redo_prices(adoption: Mapping[str, Any], manifests: list[dict[str, Any]]) -> dict:
    """The sheet the Owner's report prices its paid lines from: a new still at the stills
    tier, and new motion on the model each scene was filmed with, at 1080p, for its length."""
    still = adoption["sheet"]["still_price"]
    rows: list[dict[str, Any]] = []
    table = None
    try:
        table = load_price_table()
    except (OSError, ValueError, KeyError, TypeError):
        table = None
    for row in adoption["sheet"]["scenes"]:
        entry: dict[str, Any] = {"scene_index": row["scene_index"], "kind": row["kind"]}
        if row["kind"] in CARD_KINDS:
            entry.update(credits=0, still_credits=0)
            rows.append(entry)
            continue
        entry.update(still_credits=still["credits"], still_price_source=still["source"])
        model = None
        for manifest in manifests:
            motion = _scene_entry(manifest, row["scene_index"]).get("motion")
            if isinstance(motion, Mapping) and motion.get("model"):
                model = str(motion["model"])
                seconds = float(motion.get("asked_seconds") or 0.0) or None
                break
        else:
            seconds = None
        entry.update(model_id=model, resolution="1080p" if model else None, credits=None)
        if table is not None and model and seconds:
            try:
                entry["credits"] = price_shot(model, "1080p", seconds, table=table)
                entry["price_source"] = source_label(table.row(model, "1080p"))
            except UnpricedError:
                entry["credits"] = None
        rows.append(entry)
    return {"credit_usd": still.get("credit_usd"), "scenes": rows}


def owner_report(
    qc: Mapping[str, Any], adoption: Mapping[str, Any], manifests: list[dict[str, Any]]
) -> str:
    """The quality-control part of the Owner's letter (`qc_report.qc_summary_ro`), priced.

    The rehearsal measured no balance (it bought nothing), so the spend is passed as unknown.
    Should the letter writer fail on a report shape it does not know, the film and its quality
    control still exist: the verdict and the control's own reasons are told, and the failure
    is named, never hidden.
    """
    from app.media.qc_report import qc_summary_ro  # noqa: PLC0415

    try:
        return qc_summary_ro(
            qc,
            None,
            sheet=_redo_prices(adoption, manifests),
            scene_kinds={int(k): v for k, v in adoption["kinds"].items()},
        )
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        score = qc.get("score")
        reasons = qc.get("failure_reasons_json") or qc.get("failure_reasons") or []
        return (
            f"Controlul calității: {qc.get('status')}"
            + (f", scor {ro_number(score, 2)}" if isinstance(score, int | float) else "")
            + ". Raportul detaliat nu a putut fi scris "
            f"({type(exc).__name__}: {str(exc)[:160]}). Motivele, așa cum le-a scris "
            "controlul:" + "".join("\n- " + str(reason)[:300] for reason in list(reasons)[:8])
        )


def _lines_from_film(
    rows: list[dict[str, Any]], production: Mapping[str, Any], price: Mapping[str, Any]
) -> None:
    """Say on the sheet what the film actually did with each paid clip, not what was foreseen."""
    entries = {
        entry.get("scene_index"): entry
        for entry in production.get("scenes") or []
        if isinstance(entry, Mapping)
    }
    for row in rows:
        motion = row.get("motion")
        if motion is None:
            continue
        record = (entries.get(row["scene_index"]) or {}).get("motion")
        motion["used"] = bool(isinstance(record, Mapping) and record.get("reused_take"))
        if isinstance(record, Mapping) and (
            record.get("shot_seconds") or record.get("asked_seconds")
        ):
            # The shot the clip had to fill (2026-10-01: the scene plus any dissolve into the
            # next); a render from before records only what the vendor was asked for.
            motion["span"] = float(record.get("shot_seconds") or record["asked_seconds"])
        row["line_ro"], row["credits_needed"] = scene_line(row, price)


def rehearse(
    engine: Engine,
    storyboard_id: str,
    source_dir: Path | str,
    *,
    rehearsal_root: Path | str,
    issued_by: str,
    correlation_id: str | None = None,
    cards: Mapping[int, Mapping[str, Any]] | None = None,
    keep_flagged_for_rehearsal: bool = False,
    settings: Any | None = None,
    ffmpeg_path: str | None = None,
    face_model: Path | None = None,
    run_qc: bool = True,
) -> dict[str, Any]:
    """Adopt the paid files, assemble the film from them, and run quality control: 0 credits.

    The narration is the recorded voice files played back, the cards are composed, the sound is
    mastered and the film encoded with the current master (all under ``rehearsal_root``). No
    image, video or voice adapter is passed to the render, so no vendor can be asked; quality
    control runs without a vision model (no tokens spent), its picture checks reported as not
    applicable. When a LIVE scene has no approved still (one failed a check and the Owner did
    not choose to see it anyway), the film is not assembled and ``not_rendered`` says why.
    """
    from app.media.qc import evaluate_media_qc  # noqa: PLC0415 - qc imports the assembler

    correlation = correlation_id or str(uuid4())
    adoption, voices = _adopt(
        engine,
        storyboard_id,
        source_dir,
        rehearsal_root=rehearsal_root,
        issued_by=issued_by,
        correlation_id=correlation,
        cards=cards,
        keep_flagged_for_rehearsal=keep_flagged_for_rehearsal,
        ffmpeg_path=ffmpeg_path,
        face_model=face_model,
    )
    root = Path(adoption["rehearsal_root"])
    sheet_rows = adoption["sheet"]["scenes"]
    result: dict[str, Any] = {
        "adoption": adoption,
        "film": None,
        "qc": None,
        "not_rendered": None,
        "credits": 0,
    }
    silent = [row["scene_index"] for row in sheet_rows if row["scene_index"] not in voices]
    if silent:
        result["not_rendered"] = (
            "Filmul nu se asamblează: "
            + ", ".join(f"Scena {n}" for n in silent)
            + " nu are narațiunea înregistrată pentru textul de acum, iar repetiția nu "
            "cumpără voce."
        )
    else:
        try:
            result["film"] = assemble_from_takes(
                engine,
                storyboard_id,
                correlation,
                storage_root=root / "render",
                ffmpeg_path=ffmpeg_path,
                tts_adapter_for_scene=lambda scene: voices.get(int(scene["scene_index"])),
                environment=studio_environment(engine),
                settings=settings,
            )
        except TakesMissing as exc:
            result["not_rendered"] = str(exc)
    film = result["film"]
    if film is not None:
        _lines_from_film(sheet_rows, film["production"], adoption["sheet"]["still_price"])
    header = [
        "Repetiția nu a apelat niciun furnizor: 0 credite. Filmul se reface din fișierele "
        "deja plătite, cu graficele și ecranele negre compuse local.",
        *[row["line_ro"] for row in sheet_rows],
    ]
    if film is not None and run_qc:
        result["qc"] = evaluate_media_qc(
            engine,
            film["output_asset_id"],
            correlation,
            settings=settings,
            registry=None,
            ffmpeg_path=ffmpeg_path,
        )
    with Session(engine) as session:
        manifests = _legacy_manifests(session, storyboard_id)
    if result["qc"] is not None:
        report = owner_report(result["qc"], adoption, manifests)
        header += ["", report]
    elif result["not_rendered"]:
        header += ["", result["not_rendered"]]
    result["summary_ro"] = "\n".join(header)
    with Session(engine) as session, session.begin():
        append_event(
            session,
            "media.rehearsal_rendered" if film is not None else "media.rehearsal_not_rendered",
            "storyboard",
            storyboard_id,
            1,
            {
                "asset_id": film["output_asset_id"] if film is not None else None,
                "job_id": film["job_id"] if film is not None else None,
                "qc_status": (result["qc"] or {}).get("status"),
                "not_rendered": result["not_rendered"],
                "credits": 0,
            },
            correlation,
        )
    return result
