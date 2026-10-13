"""Input guard: existing local-first media checks.

Private production traces omitted; implementation unchanged."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.media.models import SceneTake
from app.models import DomainEvent
from app.providers.runpod.jobs import GenerationJob
from app.services import append_event
from app.wording import count

#: What a purchase buys: a still (an image) or a clip (a video, from a still or from words).
STILL, MOTION = "still", "motion"
#: The take kinds that are clips: a test shot is bought exactly like a motion clip.
MOTION_TAKE_KINDS: tuple[str, ...] = ("motion", "test_shot")
#: The statuses of a purchase that did not come out right (`SceneTake`).
ENDED_WRONG: tuple[str, ...] = ("REJECTED", "REFUSED", "LOST")

#: Why `refused_before` refuses: the identical input was refused for what it showed; a clip
#: from this first frame was refused for a fault of the picture; the identical input failed
#: technically more than `TECHNICAL_RETRIES` rounds.
SAME_INPUT, SAME_STILL, TECHNICAL_TWICE = "SAME_INPUT", "SAME_STILL", "TECHNICAL_TWICE"
#: The failure code a refused purchase is recorded under (the investigation's name).
REFUSAL_CODE = "SAME_INPUT_FAILED"
#: The register's event of a purchase this guard refused (aggregate: the storyboard).
REFUSED_EVENT = "media.same_input_refused"
#: How many more rounds an identical input may be bought after a technical failure: once.
TECHNICAL_RETRIES = 1
#: The longest excerpt of a refusal's words in the Owner's sentence.
WHY_CHARS = 220

#: What an ended take says about its input (`refusal_class`).
CONTENT, TECHNICAL, NOT_BOUGHT, NOT_JUDGED = "content", "technical", "not_bought", "not_judged"

# The codes the other modules write on a take, by value: this module is imported by the
# assembler and the stills stage, so it imports neither (tests/test_input_guard.py keeps the
# two spellings equal).
#: `assembler.CLIP_QC_FAILURE_CODE`, and the event its report is kept in (`CLIP_QC_EVENT`).
CLIP_QC_CODE = "QC.CLIP"
CLIP_QC_EVENT = "media.clip_qc_checked"
#: `stills_stage.GATE_FAILURE_CODE`: the gate's refusal, and a still clip QC sent back to it.
STILL_GATE_CODE = "LOCAL.STILL_GATE"
#: `assembler.REDO_STILL_REPLACED`: a clip retired because its still was replaced.
STILL_REPLACED_CODE = "REDO.STILL_REPLACED"
#: `assembler.DUPLICATE_FILE_CODE`: a purchase that delivered a file the scene already had.
DUPLICATE_FILE_CODE = "VENDOR.DUPLICATE_FILE"
#: `assembler.DEGENERATE_FAILURE_CODE`: the model gave a broken picture (black, flat).
DEGENERATE_CODE = "LOCAL.DEGENERATE_STILL"
#: `assembler.CANCELLED_FAILURE_CODE` / `NOT_QUEUED_FAILURE_CODE`: never made, never paid.
CANCELLED_CODE = "RUNPOD.CANCELLED"
NOT_QUEUED_CODE = "RUNPOD.NOT_QUEUED"
#: Requests that never reached a model: unsent, a local generator that did not answer or could
#: not read the format, a vendor that is not configured.
NOT_SENT_CODES: tuple[str, ...] = (
    "UNSENT",
    "LOCAL_CONNECTION",
    "LOCAL_FORMAT",
    "NOT_CONFIGURED",
)
#: RunPod item states that made nothing, written on a take as ``RUNPOD.<state>``
#: (`_ShotRounds` and `_StillRounds` record ``f"RUNPOD.{error}"``): stopped by RunPod or by the
#: studio (``batch.BatchRun.cancel`` writes CANCELLED_BY_STUDIO, cost 0), never queued, skipped
#: by the worker's time guard before it started (``SKIPPED_TIME``, cost 0), never sent. Uncharged,
#: they say nothing about the input: two stopped rounds must not make the third refused.
NOT_MADE_STATES: tuple[str, ...] = (
    "CANCELLED",
    "CANCELLED_BY_STUDIO",
    "NOT_QUEUED",
    "SKIPPED_TIME",
    "UNSENT",
)
#: The models whose worker graph samples at CFG 1.0, where the negative prompt is never used
#: (backend/runpod_worker/workflows: LTX-2.5's LTXVDualCFGGuider video_cfg 1.0, the KSampler of
#: Wan-2.2-LightX2V and of Qwen-Image-Edit-2511 at cfg 1.0). On them a new negative alone is the
#: same input: the cyclotron's clips went with no negative at all, and adding one would have
#: bought one more identical clip of scene 1. Qwen-Image-2512 samples at CFG 4: its negative is
#: part of what it draws (tests/test_input_guard.py reads the graphs and keeps this list true).
NEGATIVE_UNUSED_MODELS: frozenset[str] = frozenset(
    {"LTX-2.5", "Wan-2.2-LightX2V", "Qwen-Image-Edit-2511"}
)
#: The words `assembler._send_still_back_for_clip` opens a still's refusal with: clip QC found
#: the fault in the picture, whatever the gate's phrases say.
SENT_BACK_WORDS = "Controlul clipului a găsit greșeala în imagine"
#: The words of a take a redo replaces when the caller gives none (`refused_before`).
REPLACED_WORDS = "refacerea scenei a fost hotărâtă tocmai pentru această luare"
#: The Owner's words for a technical failure, by code (never the code itself).
TECHNICAL_WORDS: dict[str, str] = {
    "RUNPOD.EXPIRED_UNDELIVERED": "rezultatul a expirat la RunPod înainte să fie ridicat",
    "VENDOR.NOT_COLLECTED": "rezultatul nu a fost ridicat la timp de la furnizor",
    "VENDOR.UNANSWERED": "cererea a plecat și furnizorul nu a răspuns",
    DEGENERATE_CODE: "modelul a dat o imagine stricată",
}

_WORD = re.compile(r"\w+")
_SCENE_LABEL = re.compile(r"\bScena \d+:\s*")
_HTTP = re.compile(r"^HTTP_(\d{3})$")


# ------------------------------------------------------------------------------ identity


def words_of(text: str | None) -> str:
    """The words of a prompt as compared: Unicode-normalised, case-folded, every run of
    punctuation and spacing one space. «Over the 7.6 seconds» and «over the 7.6 seconds,» are
    the same words; «a faint.» and «a faint shimmer.» are not."""
    folded = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return " ".join(_WORD.findall(folded))


def words_hash(text: str | None) -> str | None:
    """The sha256 of a text's words (`words_of`), or None when it has none (no negative)."""
    words = words_of(text)
    return hashlib.sha256(words.encode("utf-8")).hexdigest() if words else None


def _picture_sha(picture: bytes | str | None) -> str | None:
    """A picture as the journal names it: the sha256 of its bytes (a str is already one)."""
    if picture is None:
        return None
    if isinstance(picture, bytes):
        return hashlib.sha256(picture).hexdigest()
    text = str(picture).strip().lower()
    return text or None


def _pictures_sha(pictures: Sequence[bytes | str]) -> str | None:
    """Several pictures in their order (a reference binds to its own input): one sha256."""
    shas = [sha for sha in (_picture_sha(p) for p in pictures) if sha]
    if not shas:
        return None
    return hashlib.sha256("|".join(shas).encode("ascii")).hexdigest()


def _kind(kind: str) -> str:
    named = str(kind or "").strip().lower()
    if named in ("still", "image"):
        return STILL
    if named in ("motion", "test_shot", "video"):
        return MOTION
    raise ValueError(f"not a purchase kind: {kind!r}")


def _seconds(kind: str, seconds: float | None) -> float | None:
    if kind == STILL or seconds is None:
        return None
    return round(float(seconds), 3)


@dataclass(frozen=True)
class PurchaseIdentity:
    """What makes two purchases the same purchase: everything sent, but the seed (see the
    module's docstring). Equal identities are the same input."""

    kind: str
    storyboard_id: str
    scene: int
    model: str
    seconds: float | None
    prompt_words_hash: str
    negative_hash: str | None
    still_sha: str | None
    references_sha: str | None = None

    @property
    def key(self) -> str:
        """One sha256 of the whole identity, for the record."""
        canonical = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def record(self) -> dict[str, Any]:
        return {**asdict(self), "key": self.key}


def purchase_identity(
    *,
    kind: str,
    storyboard_id: str,
    scene: int,
    model: str,
    prompt: str,
    negative: str | None = None,
    seconds: float | None = None,
    picture: bytes | str | None = None,
    references: Sequence[bytes | str] = (),
) -> PurchaseIdentity:
    """The identity of a purchase from what the purchase point has in hand. ``picture`` is the
    first frame a clip model receives (its bytes, or their sha256), None for a still or a clip
    filmed from words; ``references`` the pictures a still is drawn from, in order. The
    negative counts only on a model that uses it (`NEGATIVE_UNUSED_MODELS`)."""
    named = _kind(kind)
    drawn_by = str(model or "")
    return PurchaseIdentity(
        kind=named,
        storyboard_id=str(storyboard_id),
        scene=int(scene),
        model=drawn_by,
        seconds=_seconds(named, seconds),
        prompt_words_hash=words_hash(prompt) or hashlib.sha256(b"").hexdigest(),
        negative_hash=None if drawn_by in NEGATIVE_UNUSED_MODELS else words_hash(negative),
        still_sha=_picture_sha(picture) if named == MOTION else None,
        references_sha=_pictures_sha(references),
    )


def identity_of_request(request: Any) -> PurchaseIdentity:
    """The identity of a RunPod item about to be sent (`providers.runpod.batch.BatchRequest`),
    as the worker will really make it (`batch.route_references` may draw a still with the
    route's text model). Computed like `identity_of_journal` reads it back."""
    from app.providers.runpod.batch import BatchRefused, route_references  # noqa: PLC0415

    try:
        routed = route_references(request)
    except BatchRefused:
        # Refused unsent anyway (a model that takes no picture); its identity as asked.
        routed = request
    video = routed.operation == "video"
    return purchase_identity(
        kind=routed.operation,
        storyboard_id=routed.project_id,
        scene=int(routed.scene_id),
        model=routed.model,
        prompt=routed.prompt,
        negative=routed.negative_prompt,
        seconds=routed.duration if video else None,
        picture=routed.source_image if video else None,
        references=tuple(routed.references or ()),
    )


def identity_of_journal(job: GenerationJob) -> PurchaseIdentity | None:
    """The identity of a journalled RunPod item (`batch.journal_payload`: the words as sent,
    every picture by its sha256), or None when the row names no scene of a film."""
    request = job.request if isinstance(job.request, Mapping) else {}
    try:
        scene = int(str(job.scene_id))
        kind = _kind(job.operation)
    except ValueError:
        return None
    source = request.get("source_image")
    references = [
        str(item["sha256"])
        for item in request.get("reference_images") or []
        if isinstance(item, Mapping) and item.get("sha256")
    ]
    return purchase_identity(
        kind=kind,
        storyboard_id=job.project_id,
        scene=scene,
        model=str(request.get("model") or job.model or ""),
        prompt=str(request.get("prompt") or ""),
        negative=request.get("negative_prompt"),
        seconds=request.get("duration"),
        picture=str(source["sha256"])
        if isinstance(source, Mapping) and source.get("sha256")
        else None,
        references=references,
    )


def _job_of(session: Session, take: SceneTake) -> GenerationJob | None:
    if not take.remote_task_id:
        return None
    return session.scalar(
        select(GenerationJob)
        .where(
            GenerationJob.remote_job_id == take.remote_task_id,
            GenerationJob.project_id == take.storyboard_id,
        )
        .limit(1)
    )


def identity_of_take(session: Session, take: SceneTake) -> PurchaseIdentity | None:
    """What a take was bought with, read from its journal row (``remote_task_id``); None for a
    take with no journal row (before the journal, or not bought on RunPod) or not a picture."""
    if take.kind != STILL and take.kind not in MOTION_TAKE_KINDS:
        return None
    job = _job_of(session, take)
    identity = identity_of_journal(job) if job is not None else None
    if identity is None or identity.scene != take.scene_number:
        return None
    return identity


# ---------------------------------------------------------------- what a refusal says


def _http_status(code: str) -> int | None:
    match = _HTTP.match(code)
    return int(match.group(1)) if match else None


def refusal_class(take: SceneTake, *, said: str | None = None) -> str | None:
    """What an ended take says about its input: CONTENT (refused for what it showed: the words
    or the picture must change), TECHNICAL (it failed for a reason the input did not cause: one
    more round of the same input may answer it), NOT_BOUGHT (nothing was made: stopped before
    sending or by the studio's stop, skipped by the worker's time guard, our malformed request;
    `NOT_MADE_STATES`), NOT_JUDGED (a duplicate file), or None for a take that did not end
    wrong. ``said`` is the refusal's whole words when known (the journal's
    ``quality_result``: the take's ``failure_detail`` is cut at 500 characters).

    A refusal with no code is CONTENT: the same input is never bought blind (the rule
    `scene_rewrite.refusal_kind` keeps for a refusal that says nothing)."""
    code = str(take.failure_code or "").strip()
    upper = code.upper()
    if take.status == "LOST":
        return TECHNICAL
    if take.status == "REJECTED":
        if code == DUPLICATE_FILE_CODE:
            return NOT_JUDGED
        if code == DEGENERATE_CODE:
            return TECHNICAL
        if code == STILL_GATE_CODE:
            words = said or take.failure_detail or ""
            if " ".join(str(take.failure_detail or "").split()).startswith(SENT_BACK_WORDS):
                return CONTENT
            from app.media.scene_rewrite import (  # noqa: PLC0415 - it imports the assembler
                CONTENT_REFUSAL,
                refusal_kind,
            )

            return CONTENT if refusal_kind(code, words) == CONTENT_REFUSAL else TECHNICAL
        # Clip QC, the Director's or the Owner's retirement after film QC (REDO.*), his own
        # rejection, a still a video model refused for safety (MOTION.*), no code at all.
        return CONTENT
    if take.status != "REFUSED":
        return None
    charged = take.credits_quoted is not None or take.credits_measured is not None
    if upper.startswith("SAFETY") or ".SAFETY" in upper:
        # The vendor refused what was asked: the same input is refused again.
        return CONTENT
    state = upper.removeprefix("RUNPOD.")
    if (code in (CANCELLED_CODE, NOT_QUEUED_CODE) or state in NOT_MADE_STATES) and not charged:
        # Stopped, never queued, skipped by the worker's time guard: nothing was made.
        return NOT_BOUGHT
    if code in NOT_SENT_CODES:
        return NOT_BOUGHT
    status = _http_status(code)
    if status is not None and 400 <= status < 500 and status not in (408, 429):
        # Our own request was malformed or the account refused it: nothing was made.
        return NOT_BOUGHT
    return TECHNICAL


def _first(frames: Any, at: str = "first") -> list[Mapping[str, Any]]:
    return [
        frame for frame in (frames or []) if isinstance(frame, Mapping) and frame.get("at") == at
    ]


def still_at_fault(take: SceneTake, record: Mapping[str, Any] | None) -> bool:
    """Whether a refused clip's fault is in the still it was made from, so that no clip from
    that still, whatever its words, can come out right. ``record`` is the take's clip-QC report
    (`CLIP_QC_EVENT`).

    The first frame of a clip IS its still: a face YuNet measured there is the still's face
    (2026-10-12, 4be4364e: 0.348 on the still at 1080 px, 0.56-0.69 on LTX's frame 0, so the
    gate passed it and clip QC refused six clips with «first (1)»). Also: a flat band splitting
    the first frame, the look's «more than one picture», a vendor refusing the input picture,
    and a clip retired because its still was replaced. The report's own ``back_to_still`` is
    read when it is there: `assembler.clip_report_record` does not keep it today (round 4).
    """
    code = str(take.failure_code or "").upper()
    if code == STILL_REPLACED_CODE or "INPUT.IMAGE" in code:
        return True
    if not record:
        return False
    if record.get("back_to_still") is True or str(record.get("status") or "") == "BACK_TO_STILL":
        return True
    measured = record.get("measured") if isinstance(record.get("measured"), Mapping) else {}
    faces_failed = any(
        isinstance(check, Mapping)
        and check.get("code") == "faces"
        and check.get("status") == "FAILED"
        for check in record.get("checks") or []
    )
    faces = measured.get("faces") if isinstance(measured.get("faces"), Mapping) else {}
    if faces_failed and any(
        int(frame.get("faces") or 0) > 0 for frame in _first(faces.get("frames"))
    ):
        return True
    panels = measured.get("panels") if isinstance(measured.get("panels"), Mapping) else {}
    if any(frame.get("splits_the_picture") for frame in _first(panels.get("frames"))):
        return True
    picture = measured.get("picture") if isinstance(measured.get("picture"), Mapping) else {}
    verdict = picture.get("verdict")
    return isinstance(verdict, Mapping) and verdict.get("one_picture") is False


# --------------------------------------------------------------------------- the rule


@dataclass(frozen=True)
class _Past:
    """One earlier purchase of the scene that ended wrong, with what it was bought with."""

    take: SceneTake
    identity: PurchaseIdentity
    job: GenerationJob
    record: Mapping[str, Any] | None
    refusal: str
    still_fault: bool
    said: str
    #: Refused by the redo that replaces it (`refused_before`'s ``replacing``), not by a check.
    replaced: bool = False

    @property
    def round(self) -> str:
        """The purchase round it belonged to (both candidates of a still pair are one)."""
        return str(self.job.batch_remote_id or self.job.remote_job_id or self.take.id)


@dataclass(frozen=True)
class RefusedAttempt:
    """Why a purchase is not made: the earlier take it repeats, quality control's (or the
    vendor's) words on it, and the Owner's sentence for the register."""

    match: str
    layer: str | None
    take_id: str
    take_ids: tuple[str, ...]
    times: int
    kind: str
    status: str
    failure_code: str | None
    at: str
    seed: int | None
    words: str
    reason_ro: str
    code: str = REFUSAL_CODE

    def record(self) -> dict[str, Any]:
        return {
            "match": self.match,
            "code": self.code,
            "layer": self.layer,
            "take_id": self.take_id,
            "take_ids": list(self.take_ids),
            "times": self.times,
            "kind": self.kind,
            "status": self.status,
            "failure_code": self.failure_code,
            "at": self.at,
            "seed": self.seed,
            "words": self.words,
            "reason_ro": self.reason_ro,
        }


def _clip_records(
    session: Session, take_ids: list[str]
) -> dict[str, tuple[Mapping[str, Any], str]]:
    """Each clip's latest clip-QC report and when it was written."""
    if not take_ids:
        return {}
    found: dict[str, tuple[Mapping[str, Any], str]] = {}
    for event in session.scalars(
        select(DomainEvent)
        .where(DomainEvent.event_type == CLIP_QC_EVENT, DomainEvent.aggregate_id.in_(take_ids))
        .order_by(DomainEvent.sequence)
    ):
        if isinstance(event.payload, Mapping):
            found[event.aggregate_id] = (event.payload, str(event.timestamp))
    return found


def _history(
    session: Session,
    identity: PurchaseIdentity,
    before: str | None,
    replacing: Sequence[str] = (),
    replacing_why: str | None = None,
) -> list[_Past]:
    """The scene's earlier purchases of this kind that ended wrong and were judged, oldest
    first. With ``before``, only what was bought AND refused before that moment (a replay).
    ``replacing`` are takes a redo replaces: refused by the redo itself, whatever their status
    still says (a motion redo retires the old clip only once the new one is approved)."""
    kinds = (STILL,) if identity.kind == STILL else MOTION_TAKE_KINDS
    replaced = {str(take_id) for take_id in replacing if take_id}
    ended = SceneTake.status.in_(ENDED_WRONG)
    query = (
        select(SceneTake)
        .where(
            SceneTake.storyboard_id == identity.storyboard_id,
            SceneTake.scene_number == identity.scene,
            SceneTake.kind.in_(kinds),
            or_(ended, SceneTake.id.in_(sorted(replaced))) if replaced else ended,
        )
        .order_by(SceneTake.created_at, SceneTake.id)
    )
    if before is not None:
        query = query.where(SceneTake.created_at < before)
    takes = list(session.scalars(query))
    remote = sorted({take.remote_task_id for take in takes if take.remote_task_id})
    jobs: dict[str, GenerationJob] = {}
    if remote:
        for job in session.scalars(
            select(GenerationJob).where(
                GenerationJob.remote_job_id.in_(remote),
                GenerationJob.project_id == identity.storyboard_id,
            )
        ):
            jobs[str(job.remote_job_id)] = job
    records = _clip_records(session, [take.id for take in takes if take.kind != STILL])
    past: list[_Past] = []
    for take in takes:
        job = jobs.get(str(take.remote_task_id or ""))
        bought = identity_of_journal(job) if job is not None else None
        if job is None or bought is None:
            continue
        record, checked_at = records.get(take.id, (None, ""))
        by_redo = take.id in replaced and take.status not in ENDED_WRONG
        if by_redo:
            # The redo is the refusal: the Director (or the Owner) decided this take must be
            # made again, so the same input bought again is a seed-only redo.
            whole, refusal = replacing_why or REPLACED_WORDS, CONTENT
        else:
            refused_at = checked_at if take.failure_code == CLIP_QC_CODE and checked_at else None
            if before is not None and str(refused_at or take.updated_at or "") >= before:
                continue
            whole = str(job.quality_result or "") or str(take.failure_detail or "")
            refusal = refusal_class(take, said=whole)
        if refusal not in (CONTENT, TECHNICAL):
            continue
        blocks = [str(b) for b in (record or {}).get("blocks_ro") or [] if str(b).strip()]
        past.append(
            _Past(
                take=take,
                identity=bought,
                job=job,
                record=record,
                refusal=refusal,
                still_fault=refusal == CONTENT and still_at_fault(take, record),
                said=whole if by_redo else ("; ".join(blocks) or whole),
                replaced=by_redo,
            )
        )
    return past


def refused_before(
    session: Session,
    identity: PurchaseIdentity,
    *,
    before: str | None = None,
    replacing: Sequence[str] = (),
    replacing_why: str | None = None,
) -> RefusedAttempt | None:
    """The earlier purchase this one would repeat, or None when it may be bought.

    SAME_INPUT first (the identical input was refused for what it showed), then SAME_STILL (a
    clip from this first frame was refused for the still's own fault), then TECHNICAL_TWICE
    (the identical input failed technically in more than `TECHNICAL_RETRIES` rounds). A new
    seed, attempt or candidate is the same input. ``before`` (an ISO time) replays the rule as
    it stood at that moment: only takes bought and refused before it count.

    ``replacing`` (a redo plan's ``replaces``) are the takes the purchase is meant to replace;
    they count as refused for content, with ``replacing_why`` (her finding) as the words.
    Measured 2026-10-12 on the live record: two of the Director's motion redos (f06808c9 scene
    3 at 12:09, 1c038a99 scene 5 at 13:29 UTC) bought the very input of the clip they retired,
    a clip that had passed clip QC, with only the seed moved."""
    past = _history(session, identity, before, replacing, replacing_why)
    same = [entry for entry in past if entry.identity == identity]
    refused = [entry for entry in same if entry.refusal == CONTENT]
    # Clips from this very first frame refused for the still's own fault: whatever the words,
    # the layer at fault is the still (2026-10-12: 81e9a79a repeated the retry's words, whose
    # first frame happened to measure clean, on the still whose face three clips had shown).
    faulty = (
        [
            entry
            for entry in past
            if entry.still_fault and entry.identity.still_sha == identity.still_sha
        ]
        if identity.kind == MOTION and identity.still_sha is not None
        else []
    )
    # Counted in purchase rounds: a still pair refused together was bought once, not twice.
    if refused:
        layer = STILL if identity.kind == STILL or faulty else MOTION
        return _attempt(SAME_INPUT, identity, refused, layer, _rounds(refused))
    if faulty:
        return _attempt(SAME_STILL, identity, faulty, STILL, _rounds(faulty))
    failed = [entry for entry in same if entry.refusal == TECHNICAL]
    if _rounds(failed) > TECHNICAL_RETRIES:
        return _attempt(TECHNICAL_TWICE, identity, failed, None, _rounds(failed))
    return None


def _rounds(entries: list[_Past]) -> int:
    return len({entry.round for entry in entries})


# ------------------------------------------------------------------------ the words

#: The judge's own words inside a refusal, in English (2026-10-12: 12 of the 35 sentences the
#: guard would have written on the live record quoted them, cut mid-quote): a «…» quote in
#: English or cut at the take's 500 characters (the studio's own «push-in» stays); the
#: «(se vede: …)» aside of a repeated finding (`qc._persists_words`); the bible's rule the clip
#: look quotes after «încalcă biblia vizuală:»; and the empty brackets a removed quote leaves.
_QUOTE = re.compile(r"\s*«([^»]*)(»|$)")
_SEEN_ASIDE = re.compile(r"\s*\(se vede:[^)]*(?:\)|$)")
_BIBLE_QUOTE = re.compile(r"(încalcă biblia vizuală):.*$", re.IGNORECASE)
_EMPTY_BRACKETS = re.compile(r"\s*\(\s*\)")
#: The local checks a look was skipped for, by their codes: «oprit-o deja (sharpness)».
_SKIPPED_FOR = re.compile(r"(oprit-o deja)\s*\([^)]*\)")
#: Pieces that are not a reason of their own: the gate's line with the look's verdict, which
#: repeats the reasons before it in the look's code («Verdictul modelului de vedere:
#: regenerate_still»; read only when it is the whole refusal), and the note that the look did
#: not run because a local check had already refused (the check says why).
_NOT_A_REASON = re.compile(
    r"^(?:Imaginea\s+)?(?:Verdictul modelului de vedere|nu a fost privită: verificările locale)",
    re.IGNORECASE,
)
#: The look's verdict codes in the Owner's words (`picture_qc.StillAction`, `ClipAction`): clip
#: QC writes «modelul cere back_to_still» when the verdict is its only reason.
_VERDICT = re.compile(r"(?:Verdictul modelului de vedere:|modelul cere)\s+([a-z_]+)", re.IGNORECASE)
_VERDICT_WORDS: dict[str, str] = {
    "regenerate_still": "o imagine nouă",
    "back_to_still": "o imagine nouă",
    "regenerate_motion": "un clip nou",
    "compose_locally": "compunerea scenei fără model",
}
_ROMANIAN_MARK = re.compile(r"[ăâîșțşţ]", re.IGNORECASE)
_ENGLISH_WORD = re.compile(
    r"\b(?:the|and|of|is|not|with|but|in|on|to|from|only|that|this|shows?|frame|must|be|it"
    r"|its|than|instead|while)\b",
    re.IGNORECASE,
)


def _prepared(text: str) -> str:
    """A refusal's words on one line, without the labels the Owner's sentence already says:
    «Controlul clipului:» and «Scena N:»."""
    said = " ".join(str(text or "").split())
    said = said.removeprefix("Controlul clipului:").strip()
    return _SCENE_LABEL.sub("", said).strip()


def _reasons(text: str) -> list[str]:
    """A refusal's reasons, cut at its «;» separators, never inside a «…» quote."""
    parts: list[str] = []
    depth, start = 0, 0
    for index, char in enumerate(text):
        if char == "«":
            depth += 1
        elif char == "»":
            depth = max(0, depth - 1)
        elif char == ";" and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return [part.strip() for part in parts if part.strip()]


def _english(piece: str) -> bool:
    """A piece in English: no Romanian letter and at least two English small words."""
    return not _ROMANIAN_MARK.search(piece) and len(_ENGLISH_WORD.findall(piece)) >= 2


def _unquoted(match: re.Match[str]) -> str:
    """A «…» quote left out when it is the judge's English or was cut; kept otherwise."""
    inner, closed = match.group(1), match.group(2)
    return "" if not closed or _english(inner) else match.group(0)


def _verdict_said(match: re.Match[str]) -> str:
    """The look's verdict code as the Owner reads it."""
    words = _VERDICT_WORDS.get(match.group(1).lower())
    return f"modelul de vedere cere {words}" if words else "modelul de vedere nu o acceptă"


def _readable(text: str) -> str:
    """What the Owner can read of one block or reason: the studio's own Romanian words, without
    the judge's English, the codes, or a reason said twice."""
    kept: list[str] = []
    for reason in _reasons(_prepared(text)):
        piece = _QUOTE.sub(_unquoted, reason)
        piece = _SEEN_ASIDE.sub("", piece)
        piece = _BIBLE_QUOTE.sub(r"\1", piece)
        piece = _SKIPPED_FOR.sub(r"\1", piece)
        piece = _EMPTY_BRACKETS.sub("", piece).strip().rstrip(" ,;:.")
        if not piece or _NOT_A_REASON.match(piece) or _english(piece):
            continue
        piece = _VERDICT.sub(_verdict_said, piece)
        if piece.casefold() not in {item.casefold() for item in kept}:
            kept.append(piece)
    return "; ".join(kept)


def _excerpt(text: str, limit: int = WHY_CHARS) -> str:
    """One readable text cut at a word, never mid-word, with no closing stop (a «;» follows)."""
    said = _prepared(text)
    if len(said) > limit:
        cut = said[: limit - 1]
        said = (cut[: cut.rfind(" ")] if " " in cut else cut).rstrip(" ,;:.") + "…"
    return said.rstrip(" ;,.")


def _why(units: Sequence[tuple[str, str]], limit: int = WHY_CHARS) -> str:
    """The refusal's words for one sentence: each unit (a clip-QC block, or one reason of the
    gate) as (what quality control wrote, what the Owner can read of it), in order. The first
    readable one always (cut if it alone is too long); another only when what quality control
    wrote of it fits whole beside the ones kept. Clip QC's first block is the measured one
    (YuNet's faces); the look's block after it quotes the judge at length and is left out."""
    kept: list[str] = []
    for raw, readable in units:
        if not readable or readable.casefold() in {item.casefold() for item in kept}:
            continue
        if kept and len("; ".join([*kept, _prepared(raw)])) > limit:
            break
        kept.append(_excerpt(readable, limit))
    return "; ".join(kept)


def _words_of_refusal(entry: _Past) -> str:
    code = str(entry.take.failure_code or "")
    if entry.refusal == TECHNICAL and code in TECHNICAL_WORDS:
        return TECHNICAL_WORDS[code]
    blocks = (
        []
        if entry.replaced
        else [str(b) for b in (entry.record or {}).get("blocks_ro") or [] if str(b).strip()]
    )
    units = blocks or _reasons(_prepared(entry.said))
    said = _why([(unit, _readable(unit)) for unit in units])
    if said:
        return said
    if entry.replaced:
        return REPLACED_WORDS
    verdict = _VERDICT.search(" ".join(units))
    if verdict is not None:
        # The look's verdict was the whole refusal: said in words, never in its code.
        return _verdict_said(verdict)
    return "un eșec tehnic" if entry.refusal == TECHNICAL else "refuzul nu spune de ce"


def _times_ro(times: int) -> str:
    return "" if times <= 1 else f" de {count(times, 'dată', 'ori')}"


def reason_ro(
    match: str,
    identity: PurchaseIdentity,
    times: int,
    why: str,
    *,
    layer: str | None = None,
) -> str:
    """The register's sentence (the Owner reads it): what is not bought, why, what must
    change. Never a code, a hash or a seed. A clip refused again whose fault is in its still
    says the still must change first (the Owner, 22:00: a new still before another clip): new
    words on the same still would be refused as SAME_STILL."""
    scene = identity.scene
    picture = f"imaginea scenei {scene}" if identity.kind == STILL else f"scena {scene}"
    if match == TECHNICAL_TWICE:
        return (
            f"Nu cumpăr din nou: {picture} a fost cerută exact așa{_times_ro(times)} și de "
            f"fiecare dată a eșuat tehnic ({why}); aceeași cerere nu se mai trimite până nu se "
            "află de ce."
        )
    each = "" if times <= 1 else " de fiecare dată"
    if match == SAME_STILL:
        return (
            f"Nu cumpăr din nou: scena {scene} a mai fost filmată din aceeași imagine"
            f"{_times_ro(times)} și a fost respinsă{each} pentru o greșeală a imaginii: {why}; "
            "trebuie mai întâi o imagine nouă, nu încă un clip din aceeași imagine."
        )
    if identity.kind == STILL:
        same = "aceleași cuvinte" + (
            ", aceleași imagini de referință" if identity.references_sha else ""
        )
        change = (
            "trebuie schimbate cuvintele sau imaginile de referință"
            if identity.references_sha
            else "trebuie schimbate cuvintele"
        )
    elif identity.still_sha is None:
        same, change = "aceleași cuvinte", "trebuie schimbate cuvintele"
    elif layer == STILL:
        same = "aceeași imagine, aceleași cuvinte"
        change = "greșeala este în imagine, deci trebuie mai întâi o imagine nouă"
    else:
        same, change = (
            "aceeași imagine, aceleași cuvinte",
            "trebuie schimbată imaginea sau cuvintele",
        )
    return (
        f"Nu cumpăr din nou: {picture} a mai fost cumpărată exact așa{_times_ro(times)} "
        f"({same}) și a fost respinsă{each}: {why}; {change}."
    )


def _attempt(
    match: str,
    identity: PurchaseIdentity,
    entries: list[_Past],
    layer: str | None,
    times: int,
) -> RefusedAttempt:
    newest = entries[-1]
    if match == TECHNICAL_TWICE:
        # Each technical failure said once, in order: the rounds may have failed differently.
        said = list(dict.fromkeys(_words_of_refusal(entry) for entry in entries))
        why = _why([(item, item) for item in said])
    else:
        why = _words_of_refusal(newest)
    return RefusedAttempt(
        match=match,
        layer=layer,
        take_id=newest.take.id,
        take_ids=tuple(entry.take.id for entry in entries),
        times=times,
        kind=newest.take.kind,
        status=newest.take.status,
        failure_code=newest.take.failure_code,
        at=str(newest.take.created_at or ""),
        seed=newest.take.seed,
        words=why,
        reason_ro=reason_ro(match, identity, times, why, layer=layer),
    )


#: How far back `record_refusal` looks for the same refusal already said (the storyboard's
#: newest refusals).
SAID_LOOKBACK = 200


def _said_already(session: Session, identity: PurchaseIdentity, sentence: str) -> str | None:
    """The event that already told the register exactly this refusal of this input, when the
    newest refusal of the input said the same sentence: nothing new was bought or refused since,
    so it is not said again (the Owner, 2026-10-12: «nu trebuie să se repete!»)."""
    for event in session.scalars(
        select(DomainEvent)
        .where(
            DomainEvent.event_type == REFUSED_EVENT,
            DomainEvent.aggregate_id == identity.storyboard_id,
        )
        .order_by(DomainEvent.sequence.desc())
        .limit(SAID_LOOKBACK)
    ):
        payload = event.payload if isinstance(event.payload, Mapping) else {}
        said = payload.get("identity") if isinstance(payload.get("identity"), Mapping) else {}
        if said.get("key") == identity.key:
            return event.event_id if payload.get("reason_ro") == sentence else None
    return None


def record_refusal(
    session: Session,
    identity: PurchaseIdentity,
    attempt: RefusedAttempt,
    *,
    correlation_id: str,
    step: str | None = None,
) -> str:
    """Write the refusal for the register (`REFUSED_EVENT`, on the storyboard) and return its
    event id. Nothing is bought, so nothing else is written; the caller's session commits. The
    same refusal of the same input asked again (a walk that comes back an hour later) is said
    once: its first event's id is returned and nothing is written."""
    said = _said_already(session, identity, attempt.reason_ro)
    if said is not None:
        return said
    event = append_event(
        session,
        REFUSED_EVENT,
        "storyboard",
        identity.storyboard_id,
        1,
        {
            "storyboard_id": identity.storyboard_id,
            "scene_index": identity.scene,
            "kind": identity.kind,
            "step": step,
            "identity": identity.record(),
            **attempt.record(),
        },
        correlation_id,
    )
    return event.event_id
