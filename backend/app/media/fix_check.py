"""What a scene's words were rewritten to fix, so the next still and clip are checked for it.

The Owner, 2026-10-12, 16:50, after stopping the studio (19.50 USD of RunPod that day, 11.05
of it on redos, and all three films still failing QC): «Sistemul trebuie să refacă promptul!
... DAR SĂ REFACĂ CE A FOST GREȘIT. Și să se asigure că ce a fost greșit este acum corectat.
Nu să facă aceeași greșeală la nesfârșit!»

Until then the loop checked the WORDS and never the PICTURE against the mistake: the
Director's brief, the Video Editor's rewrite and her review (`scene_rewrite.review_rewrite`:
each finding, whether it is treated, by which new sentence) proved that the prompt answers
the finding; the new still was then judged only against its prompt and the scene, and the
film's picture QC — after the clip, the assembly and the money — was the first to say the
mistake was still there. On f06808c9 scene 4 the finding was «two women face to face instead
of a single on Nadia»; nothing between the rewrite and the finished film looked for them.

`open_findings` names, for one scene and one layer, what is open:

- the review's findings on the newest rewrite by her brief, in quality control's OWN words
  (``qc_text``, the contract of 2026-10-12 evening; ``finding``, her paraphrase, only on a
  record that has no ``qc_text``) with the sentence that treats each as ``expected``, the
  guidance the correction followed. Her REPAIR proposals («After the new still is bought and
  approved, the motion must be redone…», «Paid redo within…») never become an item: they are
  what the studio buys, not what anybody saw (the review of 9ac0195, finding 1). The brief's
  film reasons are read only for a rewrite recorded before the review kept its findings, and
  only their sentences that say what was seen;
- the newest Director QC decision's REAL verdicts on the scene (quality control's text and her
  cause), while no still (or, on the motion layer, no passing clip) was made after it: a paid
  redo that was not rewritten (a still he approved without «final») carried nothing to check;
- each on its layer: a finding treated in the still's words is checked on the next still, one
  treated in the motion's words on the next clip (`picture_qc.judge_clip`), and one whose
  layer is not known on both — a still cannot show a movement, and the still's look saying so
  never closed what only the clip can show (the review of 9ac0195, finding 5).

The stills step gives the still layer to the gate (`still_gate.StillPlan.must_fix`), the motion
step the motion layer to clip QC; the vision look answers each item gone, minor or persists
(the Owner: «DIRECTOAREA ACCEPTĂ DEFECTELE MICI!»): only persists refuses, a minor one is a
warning on the take (`record_take_note`). A still approved after the rewrite, or a clip that
passed after it, was checked: its layer is closed.

Two more things live here because every buyer needs them the same way: the Director's second
look at a refusal before a re-roll or a retry is bought (`director_second_look`; the Owner's
rule of 2026-10-12: «LLM-ul este pe abonament! NU COSTĂ BANI SĂ TRECEM PE LA EI! GENERAREA DE
IMAGINI ȘI MIȘCĂRI COSTĂ!»), and what a look teaches the rewrite's lessons (`confirm_lessons`,
`withdraw_lessons`).

The review of 5fc7468 (2026-10-12, night) kept these rules here:

- a finding her review left UNTREATED and called MINOR is one she accepted («DIRECTOAREA ACCEPTĂ
  DEFECTELE MICI!»): it is never an item, so no still or clip is refused, and nothing bought,
  for it; an item she called minor that the look says persists is a minor trace, a warning;
- lessons are settled per review run (``source_id``): a run's lessons are withdrawn only when
  ITS item persists on a candidate and no candidate of the round shows it corrected, and
  confirmed only when every one of its items, on both layers, is closed and was answered gone;
  a clip retry merely deferred to the next RunPod round settles nothing;
- the brief's film words of a rewrite recorded before her review kept findings are read by
  her (`read_film_reasons`, free) — what quality control SAW, never what to buy — and only
  without her reading by the patterns of `PROPOSAL_SENTENCE`;
- her look keeps a picture only OVERTURNED, never redone, at most minor; a refusal quality
  control measured (a floor, beside the hard limits never offered to her) only as «not in the
  picture» (`look_accepts`, the shared contract);
- what was accepted on a take is read back for the film's QC by `accepted_on_takes`.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.media.models import SceneTake
from app.models import DomainEvent

logger = logging.getLogger("studio.fix_check")

#: Length of the legacy finding summaries; the original domain events remain evidence.
MAX_CHARS = 300
#: The layers an item is checked on (`scene_rewrite.STILL`, `scene_rewrite.MOTION`), and the
#: mark of an item whose layer is not known: it is checked on both.
STILL_LAYER = "still"
MOTION_LAYER = "motion"
BOTH_LAYERS = "both"
#: Kept for callers of the first version: the layer of a rewrite that changed the picture.
PICTURE_LAYER = STILL_LAYER
#: What the look answers per item (`picture_qc.FixAnswer`): the mistake is gone, a small trace
#: of it is left (accepted, a warning), or it is there again (refused).
GONE, MINOR, PERSISTS = "gone", "minor", "persists"
FIX_STATUSES = (GONE, MINOR, PERSISTS)
#: Where an item comes from, in the order they are ranked.
FROM_REVIEW, FROM_DIRECTOR_QC, FROM_FILM = "review", "director_qc", "film"
#: Two items whose content words overlap this much are one finding said twice: her review's
#: ``qc_text`` and her QC verdict's text, or two paraphrases of one picture (`token_overlap`).
DUPLICATE_OVERLAP = 0.6
#: The studio's own notes that travel with the film's findings in a brief's ``failures``,
#: matched on the whole reason. Read on the 2026-10-12 database copy: «Scena 5: mișcarea
#: filmată din imaginea nouă.» rode on every brief of 1c038a99 scene 5 as a «film» finding.
PROCESS_NOTES: tuple[re.Pattern[str], ...] = (
    re.compile(r"^scena \d+: mișcarea filmată din imaginea nouă\.?$", re.IGNORECASE),
    re.compile(r"^scena \d+: filmul se reasamblează", re.IGNORECASE),
    re.compile(r"^the movement of this scene was rewritten before", re.IGNORECASE),
)
#: A sentence of a film reason that prescribes what to buy or rewrite instead of saying what
#: was seen: her REPAIR proposals ride in the same list as the report's words
#: (`runbook.stages._correct_before_redo`). Read on the 2026-10-12 database copy, f06808c9:
#: «After the new still is bought and approved, the motion must be redone on the new still
#: with a prompt that specifies …», «Rewrite the motion prompt to state the final framing
#: explicitly …», «redo the motion on the new still with the same tilt-down …». Only the
#: fallback since the review of 5fc7468: her own reading comes first (`read_film_reasons`).
#: Its patterns of that review, read on the database copy (aa170155 scene 1, 1c038a99 scene
#: 3): «The motion take is a test_shot, not approved;», «drop 'sensors and electronics' which
#: invited instrument markings;», «no negations, no 'text'.», «… was rejected
#: (REDO.STILL_REPLACED) because …» — the studio's process and her prescriptions, not a sight.
PROPOSAL_SENTENCE = re.compile(
    r"\b(?:must be (?:re)?done|must be redone|must change|re-?do|redone|rewrit\w*"
    r"|paid redo|credits?|buy\w*|bought|purchas\w*|join the|approved still|new still"
    r"|the prompt|motion prompt|still prompt|refac\w*|rescri\w*|cumpăr\w*|credite"
    r"|plătit\w*|alătur\w*|test_shot|test shot|not approved|drop\s+(?:the\s+)?['\"‘«]"
    r"|no negations?|rejected \(|re-?animat\w*|is required|is needed|needs? to be)\b",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"(?<=[.;!?])\s+")
#: Words that say nothing about the picture, left out of `token_overlap`.
_FILLER = frozenset(
    {
        "the", "and", "for", "with", "that", "this", "from", "into", "onto", "its", "his",
        "her", "their", "are", "was", "were", "has", "have", "not", "instead", "only", "but",
        "scene", "scena", "frame", "shot", "picture", "still", "clip", "shows", "show",
        "requested", "asked", "plan", "who", "while", "one", "two", "each", "other", "than",
        "same", "also", "very", "just", "out", "over", "under", "there", "what",
    }
)  # fmt: skip
#: Words that say an item is about the movement: on the still layer such an item ranks last.
#: Not «motion» alone: «the motion take … carries the same faults: two women …» is a picture
#: finding about the clip made from the picture (read on the 2026-10-12 database copy).
_MOTION_WORDS = re.compile(
    r"\b(?:movement|moves?|moving|camera|push-?in|pull-?back|pan|tilt|drift\w*|zoom\w*"
    r"|ending|ends|final frame|cut|cuts|morph\w*|warp\w*|flicker\w*)\b",
    re.IGNORECASE,
)
#: The Director QC's decision (`director_qc.DECISION_EVENT`), read for her REAL verdicts.
DIRECTOR_QC_EVENT = "media.director_qc_decision"
#: A note on one take of what was accepted on it: the minor traces the look saw and accepted,
#: and the Director's look that approved it (aggregate: the take). The film QC's context reads
#: it (`take_note`) so the same small trace is not refused again after the money.
TAKE_NOTE_EVENT = "media.take_quality_note"
#: Who approved a take by looking: her second look (`director_second_look`).
DIRECTOR_LOOK_APPROVER = "director_look"
#: The violations a look of hers never overturns (the Owner, 2026-10-12: hard-coded rules stay
#: only where money or the bible's hard limits are at stake — faces where forbidden, panels; a
#: blank or striped field is no picture at all). Writing is hers since 2026-10-15 («scrisul,
#: ea trebuie să hotărască»): the scene's own writing stays, only text laid over the picture
#: or a logo is serious, and she says which.
HARD_LIMITS = frozenset({"faces", "panels", "degenerate"})
#: Her second look's verdicts (`app.media.second_look.second_look`, the shared contract).
CONFIRMED, OVERTURNED, UNAVAILABLE = "CONFIRMED", "OVERTURNED", "UNAVAILABLE"
#: How serious her review (or her QC verdict) called a finding; an item without a word is
#: serious (it is checked).
MINOR_SEVERITY, SERIOUS_SEVERITY = "minor", "serious"
#: Her reading of a pre-contract brief's film words (`read_film_reasons`): what quality control
#: SAW, per brief (aggregate: the storyboard; ``brief_event_id`` names the brief).
FILM_READ_EVENT = "media.film_reasons_read"
FILM_READ_TASK = "director_film_reasons_read"
FILM_READ_TEMPLATE_VERSION = "director-film-reasons-v1"
#: At most this many briefs are read in one call: a slow model never holds a step for long.
FILM_READ_PER_CALL = 6


def _said(value: Any) -> str:
    return " ".join(str(value or "").split())


def _cut(text: str, limit: int = MAX_CHARS) -> str:
    """At most ``limit`` characters, cut at a word with an ellipsis."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _is_process_note(text: str) -> bool:
    return any(pattern.search(text) for pattern in PROCESS_NOTES)


def observed(text: Any) -> str:
    """The sentences of a film reason that say what was seen; a sentence that prescribes what
    to buy, redo or rewrite (`PROPOSAL_SENTENCE`) is left out, and a whole process note
    (`PROCESS_NOTES`) leaves nothing."""
    said = _said(text)
    if not said or _is_process_note(said):
        return ""
    kept = [
        sentence
        for sentence in _SENTENCE_END.split(said)
        if sentence.strip() and not PROPOSAL_SENTENCE.search(sentence)
    ]
    return " ".join(kept).strip(" ;")


def _words(text: Any) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-zăâîșțşţ0-9']+", _said(text).casefold())
        if len(word) >= 3 and word not in _FILLER
    }


def token_overlap(new: Any, known: Any) -> float:
    """The share of ``new``'s content words found in ``known`` (0 when ``new`` has none)."""
    words = _words(new)
    if not words:
        return 0.0
    return len(words & _words(known)) / len(words)


def _duplicate(text: str, kept: Iterable[str]) -> bool:
    return any(
        max(token_overlap(text, other), token_overlap(other, text)) >= DUPLICATE_OVERLAP
        for other in kept
    )


def _scene_of(payload: Mapping[str, Any]) -> int | None:
    try:
        return int(payload.get("scene_index"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _moment(text: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None


def _later(first: Any, second: Any) -> bool:
    """Whether ``first`` is later than ``second`` (ISO timestamps, as `utc_now` writes them)."""
    a, b = _moment(first), _moment(second)
    if a is not None and b is not None and (a.tzinfo is None) == (b.tzinfo is None):
        return a > b
    return str(first or "") > str(second or "")


def _rewrote_picture(payload: Mapping[str, Any]) -> bool:
    """Whether a rewrite by her brief changed the picture's words (its ``layer``; for a record
    without one, whether its still prompt changed)."""
    layer = payload.get("layer")
    if layer:
        return str(layer) == STILL_LAYER
    return _said(payload.get("still_prompt")) != _said(payload.get("old_still_prompt"))


def _said_in(sentence: Any, prompt: Any) -> bool:
    """Whether the treating sentence is in the prompt, word for word (case and spacing aside);
    a fragment under four words proves nothing (the serial's «facing the viewer» is in every
    still)."""
    said = _said(sentence).casefold().rstrip(" .")
    if len(said.split()) < 4:
        return False
    return said in _said(prompt).casefold()


def _review_layer(entry: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    """The layer one of her review's findings is checked on: its own ``layer`` (the contract
    of 2026-10-12 evening); on an older record, the motion for a motion rewrite (the still's
    words were kept), else where its treating sentence stands — the still prompt, the motion
    prompt, both, or neither known (both layers)."""
    layer = str(entry.get("layer") or "")
    if layer in (STILL_LAYER, MOTION_LAYER):
        return layer
    if str(payload.get("layer") or "") == MOTION_LAYER:
        return MOTION_LAYER
    by = entry.get("by")
    in_still = _said_in(by, payload.get("still_prompt"))
    in_motion = _said_in(by, payload.get("motion_prompt"))
    if in_still and not in_motion:
        return STILL_LAYER
    if in_motion and not in_still:
        return MOTION_LAYER
    return BOTH_LAYERS


def _on(item: Mapping[str, Any], layer: str) -> bool:
    return item.get("layer") in (layer, BOTH_LAYERS)


def _approved_still_after(session: Session, storyboard_id: str, scene: int, moment: Any) -> bool:
    made = session.scalars(
        select(SceneTake.created_at).where(
            SceneTake.storyboard_id == storyboard_id,
            SceneTake.scene_number == int(scene),
            SceneTake.kind == "still",
            SceneTake.status == "APPROVED",
        )
    ).all()
    return any(_later(at, moment) for at in made)


def _passing_clip_after(session: Session, storyboard_id: str, scene: int, moment: Any) -> bool:
    """Whether a clip made after ``moment`` was accepted: his approval, or clip QC's pass."""
    from app.media.assembler import SHOT_TAKE_KINDS, clip_qc_of  # noqa: PLC0415 - a large module

    for row in session.scalars(
        select(SceneTake).where(
            SceneTake.storyboard_id == storyboard_id,
            SceneTake.scene_number == int(scene),
            SceneTake.kind.in_(SHOT_TAKE_KINDS),
            SceneTake.status.in_(("PAID", "APPROVED")),
        )
    ):
        if not _later(row.created_at, moment):
            continue
        if row.status == "APPROVED" or (clip_qc_of(session, row.id) or {}).get("verdict") == (
            "PASSED"
        ):
            return True
    return False


def _closed(session: Session, storyboard_id: str, scene: int, layer: str, moment: Any) -> bool:
    if layer == STILL_LAYER:
        return _approved_still_after(session, storyboard_id, scene, moment)
    return _passing_clip_after(session, storyboard_id, scene, moment)


def _item(
    finding: Any,
    expected: Any,
    layer: str,
    source: str,
    *,
    source_id: Any = None,
    cause: Any = "",
    at: Any = None,
    severity: Any = SERIOUS_SEVERITY,
    treated: bool = True,
) -> dict[str, Any]:
    return {
        "finding": _said(finding),
        "expected": _said(expected),
        "layer": layer,
        "source": source,
        "source_id": str(source_id) if source_id else None,
        "cause": _said(cause),
        "severity": _severity(severity),
        "treated": bool(treated),
        "at": str(at or ""),
    }


def _severity(value: Any) -> str:
    """minor or serious; anything else (no word, an unknown one) is serious: it is checked."""
    said = str(value or "").strip().lower()
    return MINOR_SEVERITY if said == MINOR_SEVERITY else SERIOUS_SEVERITY


def accepted_by_her(entry: Mapping[str, Any]) -> bool:
    """Whether her review accepted a finding instead of treating it: marked ``accepted`` (the
    contract of the review of 5fc7468), or left untreated and called minor. 2026-10-12, the
    Owner: «DIRECTOAREA ACCEPTĂ DEFECTELE MICI!» — until then such a finding became a must_fix
    item, every still that showed the small trace again was refused ``finding_persists`` and
    bought again: a paid loop on a defect she had accepted."""
    if entry.get("accepted") is True:
        return True
    treated = entry.get("treated") is not False  # an old (finding, by) pair was treated
    return not treated and _severity(entry.get("severity")) == MINOR_SEVERITY


def _rewrite_items(session: Session, storyboard_id: str, scene: int) -> list[dict[str, Any]]:
    """Her review's findings on the newest rewrites by her brief: the newest that changed the
    picture for the still layer, the newest of any layer for the motion layer; the brief's
    film words only where the review kept no findings."""
    from app.media.assembler import SCENE_PROMPTS_REWRITTEN_EVENT  # noqa: PLC0415 - a large module
    from app.media.scene_rewrite import BRIEF_EVENT, REWRITE_REASON  # noqa: PLC0415

    picture: DomainEvent | None = None
    newest: DomainEvent | None = None
    briefs: list[DomainEvent] = []  # newest first
    for event in session.scalars(
        select(DomainEvent)
        .where(
            DomainEvent.aggregate_id == storyboard_id,
            DomainEvent.event_type.in_((SCENE_PROMPTS_REWRITTEN_EVENT, BRIEF_EVENT)),
        )
        .order_by(DomainEvent.sequence.desc())
    ):
        payload = event.payload if isinstance(event.payload, dict) else {}
        if _scene_of(payload) != int(scene):
            continue
        if event.event_type == BRIEF_EVENT:
            briefs.append(event)
            continue
        if payload.get("reason") != REWRITE_REASON:
            continue
        newest = newest or event
        if _rewrote_picture(payload):
            picture = event
            break
    items: list[dict[str, Any]] = []
    for rewrite, layers in (
        (picture, (STILL_LAYER,)),
        (newest, (MOTION_LAYER,)),
    ):
        if rewrite is None:
            continue
        payload = rewrite.payload if isinstance(rewrite.payload, dict) else {}
        review = payload.get("review") if isinstance(payload.get("review"), dict) else {}
        entries = [
            entry for entry in (review or {}).get("findings") or [] if isinstance(entry, dict)
        ]
        for entry in entries:
            if accepted_by_her(entry):
                # She accepted it (untreated and minor): nothing is checked, refused or bought
                # for it (the review of 5fc7468, finding 1).
                continue
            layer = _review_layer(entry, payload)
            if layer not in (*layers, BOTH_LAYERS):
                continue
            items.append(
                _item(
                    entry.get("qc_text") or entry.get("finding"),
                    entry.get("by"),
                    layer,
                    FROM_REVIEW,
                    source_id=(review or {}).get("run_id"),
                    at=rewrite.timestamp,
                    severity=entry.get("severity"),
                    treated=entry.get("treated") is not False,
                )
            )
        if entries:
            continue
        # A rewrite recorded before her review kept its findings: the film's own words on her
        # brief, what quality control saw. Recorded right after the rewrite it asked for
        # (`scene_rewrite._rung`): the brief naming its run, else the first after.
        run_id = payload.get("run_id")
        brief = _brief_of(rewrite, briefs, run_id)
        layer = MOTION_LAYER if layers == (MOTION_LAYER,) else STILL_LAYER
        # A film reason names no layer: the picture's rewrite checks it on the still and on
        # the clip after it, the movement's on the clip.
        on = BOTH_LAYERS if layer == STILL_LAYER else MOTION_LAYER
        for seen in _film_seen(session, storyboard_id, brief):
            items.append(_item(seen, "", on, FROM_FILM, at=rewrite.timestamp))
    return items


def _brief_of(
    rewrite: DomainEvent, briefs: Sequence[DomainEvent], run_id: Any
) -> DomainEvent | None:
    """The brief recorded right after ``rewrite`` (``briefs`` newest first): the one naming its
    run, else the first after it."""
    after = [event for event in briefs if int(event.sequence) > int(rewrite.sequence)]
    return next(
        (e for e in after if run_id and (e.payload or {}).get("rewrite_run_id") == run_id),
        after[-1] if after else None,
    )


def _film_reasons(brief: DomainEvent | None) -> list[str]:
    """The film's own words on a brief (its failures of kind film), as written."""
    said = brief.payload if brief is not None and isinstance(brief.payload, dict) else {}
    return [
        _said(reason)
        for failure in said.get("failures") or []
        if isinstance(failure, dict) and failure.get("kind") == "film"
        for reason in failure.get("reasons") or []
        if _said(reason)
    ]


def _film_read(session: Session, storyboard_id: str, brief_event_id: str) -> list[str] | None:
    """Her reading of one brief's film words (`read_film_reasons`), or None when she has not
    read it."""
    for event in session.scalars(
        select(DomainEvent)
        .where(DomainEvent.event_type == FILM_READ_EVENT, DomainEvent.aggregate_id == storyboard_id)
        .order_by(DomainEvent.sequence.desc())
    ):
        payload = event.payload if isinstance(event.payload, dict) else {}
        if payload.get("brief_event_id") == brief_event_id:
            return [_said(text) for text in payload.get("seen") or [] if _said(text)]
    return None


def _film_seen(session: Session, storyboard_id: str, brief: DomainEvent | None) -> list[str]:
    """What quality control saw, from a pre-contract brief: her reading when she made one (the
    review of 5fc7468, finding 11 — a semantic question, hers to answer, free), else the
    sentences `observed` keeps."""
    reasons = _film_reasons(brief)
    if not reasons or brief is None:
        return []
    read = _film_read(session, storyboard_id, str(brief.event_id))
    if read is not None:
        return read
    return [seen for seen in (observed(reason) for reason in reasons) if seen]


def _director_qc_items(session: Session, storyboard_id: str, scene: int) -> list[dict[str, Any]]:
    """The newest Director QC decision that judged this scene: its REAL verdicts on it (quality
    control's text, her cause), on their own layer when the verdict names one, else on both."""
    # Her decisions are recorded on the QC report (their aggregate), the film named in the
    # payload: read newest first, as `director_qc.decisions_of_film` reads them.
    for event in session.scalars(
        select(DomainEvent)
        .where(DomainEvent.event_type == DIRECTOR_QC_EVENT)
        .order_by(DomainEvent.sequence.desc())
    ):
        payload = event.payload if isinstance(event.payload, dict) else {}
        if str(payload.get("storyboard_id") or "") != storyboard_id:
            continue
        verdicts = [
            item
            for item in payload.get("verdicts") or []
            if isinstance(item, dict) and _scene_of(item) == int(scene)
        ]
        if not verdicts:
            continue
        items: list[dict[str, Any]] = []
        for verdict in verdicts:
            if str(verdict.get("verdict") or "").upper() != "REAL":
                continue
            layer = str(verdict.get("layer") or "")
            items.append(
                _item(
                    verdict.get("text"),
                    "",
                    layer if layer in (STILL_LAYER, MOTION_LAYER) else BOTH_LAYERS,
                    FROM_DIRECTOR_QC,
                    source_id=payload.get("run_id"),
                    cause=verdict.get("cause"),
                    at=event.timestamp,
                    severity=verdict.get("severity"),
                )
            )
        return items
    return []


def _ranked(items: list[dict[str, Any]], layer: str) -> list[dict[str, Any]]:
    """The items of one layer in the order the cap keeps them: her review's (each with its
    correction) first, then her QC verdicts, then the film's older words; within each, the
    items about this layer's own matter first (a picture before a movement on the still)."""
    order = (FROM_REVIEW, FROM_DIRECTOR_QC, FROM_FILM)

    def key(position_item: tuple[int, dict[str, Any]]) -> tuple[int, int, int, int]:
        position, item = position_item
        moving = bool(_MOTION_WORDS.search(item["finding"]))
        off_layer = moving if layer == STILL_LAYER else not moving
        own = 0 if item.get("layer") == layer else 1
        return (order.index(item["source"]), own, int(off_layer), position)

    return [item for _position, item in sorted(enumerate(items), key=key)]


def open_items(session: Session, storyboard_id: str, scene_index: int) -> list[dict[str, Any]]:
    """Every open item of the scene, both layers, without paraphrases said twice: each
    {"finding", "expected", "layer", "source", "source_id", "cause", "severity", "treated",
    "at"} (``layer``: still, motion or both; ``expected`` the sentence her review said treats
    it, guidance, empty when none; ``source_id`` the review run whose lessons the look confirms
    or withdraws; ``severity`` minor or serious — a minor one that persists is a warning,
    `still_gate.fix_answers`). A finding her review left untreated as minor is no item
    (`accepted_by_her`)."""
    found = _rewrite_items(session, storyboard_id, scene_index) + _director_qc_items(
        session, storyboard_id, scene_index
    )
    items: list[dict[str, Any]] = []
    for item in found:
        if not item["finding"]:
            continue
        layers = (STILL_LAYER, MOTION_LAYER) if item["layer"] == BOTH_LAYERS else (item["layer"],)
        still_open = [
            layer
            for layer in layers
            if not _closed(session, storyboard_id, scene_index, layer, item["at"])
        ]
        if not still_open:
            continue
        if len(still_open) < len(layers):
            item = {**item, "layer": still_open[0]}
        # Said twice (her review's qc_text and her QC verdict's text, or a paraphrase): kept
        # once, the first said — the ranked sources come first in ``found``.
        shared = [
            kept["finding"]
            for kept in items
            if BOTH_LAYERS in (kept["layer"], item["layer"]) or kept["layer"] == item["layer"]
        ]
        if _duplicate(item["finding"], shared):
            continue
        items.append(item)
    return items


def open_findings(
    session: Session, storyboard_id: str, scene_index: int, layer: str = STILL_LAYER
) -> list[dict[str, Any]]:
    """What the scene's next picture (``layer`` still) or clip (``layer`` motion) must show
    corrected: every `open_items` entry of that layer, ranked (`_ranked`). Empty when
    nothing was rewritten or refused for it, or when a still approved (a clip passed) after
    it already answered."""
    items = [
        {key: value for key, value in item.items() if key != "at"}
        for item in open_items(session, storyboard_id, scene_index)
        if _on(item, layer)
    ]
    return _ranked(items, layer)


# ----------------------------------------------------------- what a look says about the items


def fix_status(answer: Any) -> str | None:
    """One answer's status (gone, minor, persists), or None when the item was not answered."""
    if answer is None:
        return None
    status = getattr(answer, "status", None)
    if status is None and isinstance(answer, Mapping):
        status = answer.get("status")
    return str(status) if status in FIX_STATUSES else None


def persisting(fixes: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [fix for fix in fixes if fix.get("status") == PERSISTS]


def minor_traces(fixes: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    return [
        {"finding": str(fix.get("finding") or ""), "seen": str(fix.get("seen") or "")}
        for fix in fixes
        if fix.get("status") == MINOR
    ]


def review_sources(items: Iterable[Mapping[str, Any]]) -> list[str]:
    """The review runs whose provisional lessons the items came with, each once."""
    return list(
        dict.fromkeys(
            str(item.get("source_id"))
            for item in items
            if item.get("source") == FROM_REVIEW and item.get("source_id")
        )
    )


#: Why a review run's lessons are withdrawn (`withdraw_prompt_lessons`).
WITHDRAWN_REASON = "imaginea făcută pe cuvintele corectate repetă greșeala: lecția nu a corectat-o"


def _by_source(answers: Iterable[Mapping[str, Any]]) -> dict[str, list[str | None]]:
    """Per review run (an answer's ``source_id``, carried from its item by
    `still_gate.fix_answers`), the statuses one look gave its items."""
    by: dict[str, list[str | None]] = {}
    for answer in answers or ():
        if answer.get("source") == FROM_REVIEW and answer.get("source_id"):
            by.setdefault(str(answer["source_id"]), []).append(fix_status(answer))
    return by


def _traced_sources(session: Session, storyboard_id: str, scene_index: int) -> set[str]:
    """The review runs one of whose items a take of the scene carries as an accepted minor
    trace (`record_take_note`): answered, but not gone."""
    traced: set[str] = set()
    notes = select(DomainEvent).where(DomainEvent.event_type == TAKE_NOTE_EVENT)
    for event in session.scalars(notes):
        payload = event.payload if isinstance(event.payload, dict) else {}
        if payload.get("storyboard_id") != storyboard_id:
            continue
        if _scene_of({"scene_index": payload.get("scene_number")}) != int(scene_index):
            continue
        traced |= {str(source) for source in payload.get("minor_sources") or [] if source}
    return traced


def confirm_lessons(
    session: Session,
    answers: Sequence[Mapping[str, Any]],
    *,
    storyboard_id: str,
    scene_index: int,
) -> list[str]:
    """The review runs whose provisional lessons (`prompt_agent.record_prompt_lesson`, source the
    review's run) an approved still or a kept clip proves: every item of the run this look
    answered is GONE, none of its items is open on either layer any more (`open_items`, read
    after the take was approved), and no take of the scene carries a minor trace of one. Those
    are confirmed (`confirm_prompt_lessons`) and returned.

    2026-10-12 (the review of 5fc7468, finding 7): the first version confirmed every run the
    plan named on any clean approval — a run whose item lives on the motion layer was confirmed
    by a still that could not show it."""
    by = _by_source(answers)
    if not by:
        return []
    still_open = {
        str(item.get("source_id"))
        for item in open_items(session, storyboard_id, scene_index)
        if item.get("source_id")
    }
    traced = _traced_sources(session, storyboard_id, scene_index)
    proven = [
        source
        for source, statuses in by.items()
        if statuses
        and all(status == GONE for status in statuses)
        and source not in still_open
        and source not in traced
    ]
    if proven:
        from app.media import prompt_agent  # noqa: PLC0415 - a large module

        confirm = getattr(prompt_agent, "confirm_prompt_lessons", None)
        if callable(confirm):
            confirm(session, proven)
    return proven


def withdraw_lessons(session: Session, looks: Sequence[Sequence[Mapping[str, Any]]]) -> list[str]:
    """The review runs whose provisional lessons a round's looks (``looks``: each candidate's
    answers) disprove: an item of the run PERSISTS on a candidate (an item she called minor
    never does: `still_gate.fix_answers` reads its «persists» as minor) and no candidate of the
    round shows every item of the run corrected (gone or a minor trace). Those are withdrawn
    (`withdraw_prompt_lessons`) and returned. 2026-10-12, the Owner: «la viitoarele prompturi
    să se asigure că nu mai sunt» — a lesson that did not correct the mistake must not teach
    it; one that did, on a sibling, did (the review of 5fc7468, findings 7 and 13)."""
    persisted: set[str] = set()
    corrected: set[str] = set()
    for answers in looks:
        for source, statuses in _by_source(answers).items():
            if PERSISTS in statuses:
                persisted.add(source)
            elif statuses and all(status in (GONE, MINOR) for status in statuses):
                corrected.add(source)
    disproven = sorted(persisted - corrected)
    if disproven:
        from app.media import prompt_agent  # noqa: PLC0415 - a large module

        withdraw = getattr(prompt_agent, "withdraw_prompt_lessons", None)
        if callable(withdraw):
            withdraw(session, disproven, WITHDRAWN_REASON)
    return disproven


def record_take_note(
    session: Session,
    *,
    storyboard_id: str,
    scene_number: int,
    take_id: str,
    kind: str,
    approved_by: str,
    minor: Sequence[Mapping[str, Any]] = (),
    look: Mapping[str, Any] | None = None,
    correlation_id: str,
    answers: Sequence[Mapping[str, Any]] = (),
) -> None:
    """Write on the take (`TAKE_NOTE_EVENT`) what was accepted on it: the minor traces the look
    saw (``minor_sources``: the review runs of their items, so a trace never confirms a lesson,
    `confirm_lessons`), and her look's verdict and reason when hers approved it. Read back by
    `take_note` and, for the film's QC and the Director's reading of it, `accepted_on_takes`."""
    from app.services import append_event  # noqa: PLC0415 - services imports media

    if not minor and look is None:
        return
    traced = [
        str(answer.get("source_id"))
        for answer in answers
        if answer.get("status") == MINOR and answer.get("source_id")
    ]
    append_event(
        session,
        TAKE_NOTE_EVENT,
        "scene_take",
        take_id,
        1,
        {
            "storyboard_id": storyboard_id,
            "scene_number": int(scene_number),
            "take_id": take_id,
            "kind": kind,
            "approved_by": approved_by,
            "minor": [dict(item) for item in minor],
            "minor_sources": list(dict.fromkeys(traced)),
            "director_look": (
                {
                    key: look.get(key)
                    for key in ("verdict", "severity", "redo", "reason_ro", "run_id")
                }
                if look is not None
                else None
            ),
        },
        correlation_id,
    )


def take_note(session: Session, take_id: str) -> dict[str, Any] | None:
    """The newest note written on a take (`record_take_note`), or None."""
    event = session.scalars(
        select(DomainEvent)
        .where(DomainEvent.event_type == TAKE_NOTE_EVENT, DomainEvent.aggregate_id == take_id)
        .order_by(DomainEvent.sequence.desc())
        .limit(1)
    ).first()
    return dict(event.payload) if event is not None and isinstance(event.payload, dict) else None


# ------------------------------------------------------------ the Director's second look


def _unavailable(reason: str) -> dict[str, Any]:
    return {
        "verdict": UNAVAILABLE,
        "severity": "none",
        "redo": True,
        "reason_ro": reason,
        "run_id": None,
    }


def director_second_look(
    engine: Any,
    registry: Any,
    *,
    storyboard_id: str,
    scene_index: int,
    kind: str,
    images: Sequence[str],
    refusal: Sequence[str],
    correlation_id: str,
    take_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """The Director looks at a refusal before anything is bought again for it (the shared
    contract: `app.media.second_look.second_look`). Always a dict with ``verdict`` CONFIRMED,
    OVERTURNED or UNAVAILABLE, ``severity``, ``redo``, ``reason_ro`` and ``run_id``; never
    raises: with no registry, no pictures, no module or any error she is UNAVAILABLE and the
    refusal stands, as before her look existed."""
    if registry is None:
        return _unavailable("niciun furnizor de modele nu este înregistrat")
    if not images:
        return _unavailable("nu există imagini de arătat")
    try:
        from app.media.second_look import second_look  # noqa: PLC0415 - built beside this
    except ImportError:
        return _unavailable("privirea a doua a Directoarei nu este instalată")
    try:
        answer = second_look(
            engine,
            registry,
            storyboard_id=storyboard_id,
            scene_index=int(scene_index),
            kind=kind,
            images=list(images),
            refusal=[str(text) for text in refusal if text],
            correlation_id=correlation_id,
            take_ids=list(take_ids),
        )
    except Exception as exc:  # noqa: BLE001 - her silence never stops the studio
        return _unavailable(f"privirea a doua nu a putut fi cerută ({type(exc).__name__})")
    said = dict(answer) if isinstance(answer, Mapping) else {}
    verdict = str(said.get("verdict") or UNAVAILABLE).upper()
    severity = str(said.get("severity") or "none").lower()
    return {
        "verdict": verdict if verdict in (CONFIRMED, OVERTURNED) else UNAVAILABLE,
        "severity": severity if severity in ("none", "minor", "serious") else "serious",
        "redo": bool(said.get("redo", verdict != OVERTURNED)),
        "reason_ro": _cut(_said(said.get("reason_ro")), 500),
        "run_id": said.get("run_id"),
        # Why the defect appears and on which layer (the shared contract's extra keys).
        **{key: said.get(key) for key in ("cause", "lesson", "layer") if said.get(key)},
    }


def look_accepts(look: Mapping[str, Any] | None, *, measured: bool = False) -> bool:
    """Whether her look lets the take stand, so nothing is bought for it: OVERTURNED, no redo,
    and what is there is at most minor («DIRECTOAREA ACCEPTĂ DEFECTELE MICI!»). The shared
    contract of the review of 5fc7468 ties verdict and severity — CONFIRMED is serious and
    redoes, OVERTURNED is none or minor and never redoes — and is kept here as well (defence in
    depth): a CONFIRMED look never keeps a picture, whatever severity it carries.

    ``measured``: the refusal is one quality control MEASURED (a sharpness or a smear floor, a
    clip's motion floor or a cut, beside the bible's hard limits, which are never offered to
    her look): such a defect is serious whatever is written, so her look keeps the picture
    only by saying the defect is not in it (severity none), never by calling it minor."""
    if not look or look.get("verdict") != OVERTURNED or look.get("redo") is True:
        return False
    severity = look.get("severity")
    return severity == "none" if measured else severity in ("none", "minor")


def look_record(look: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Her look as a step's entry keeps it."""
    if not look:
        return None
    return {key: look.get(key) for key in ("verdict", "severity", "redo", "reason_ro", "run_id")}


def shot_second_look(
    engine: Any,
    registry: Any,
    *,
    storyboard_id: str,
    scene_index: int,
    clip: Any,
    refusal: Sequence[str],
    correlation_id: str,
    take_ids: Sequence[str] = (),
    ffmpeg_path: str | None = None,
) -> dict[str, Any]:
    """Her second look at a refused clip (`director_second_look`, kind ``shot``), shown its
    first, middle and last frames as clip QC was (`qc.clip_frames`), cut into a folder of their
    own for the look and removed after it."""
    import shutil  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    from app.media.qc import clip_frames  # noqa: PLC0415 - a large module
    from app.media.toolchain import find_ffmpeg  # noqa: PLC0415

    if registry is None:
        return _unavailable("niciun furnizor de modele nu este înregistrat")
    folder = Path(tempfile.mkdtemp(prefix="director_look_"))
    try:
        frames = [
            str(path) for _at, _moment, path in clip_frames(find_ffmpeg(ffmpeg_path), clip, folder)
        ]
        return director_second_look(
            engine,
            registry,
            storyboard_id=storyboard_id,
            scene_index=scene_index,
            kind="shot",
            images=frames,
            refusal=refusal,
            correlation_id=correlation_id,
            take_ids=take_ids,
        )
    finally:
        shutil.rmtree(folder, ignore_errors=True)


#: The words `assembler._send_still_back_for_clip` writes on a still it sends back to the gate
#: because clip QC blamed the picture; the mark the restore below reads.
SENT_BACK_FOR_CLIP_MARK = "Controlul clipului a găsit greșeala în imagine"
SCENE_RESTORED_EVENT = "media.scene_restored_by_look"


def restore_sent_back_scenes(
    engine: Any,
    registry: Any,
    *,
    storyboard_id: str,
    correlation_id: str,
    ffmpeg_path: str | None = None,
) -> list[int]:
    """Her look at every scene whose still clip QC sent back to the gate (`SENT_BACK_FOR_CLIP_MARK`)
    and whose refused clip is still on disk, before a new still is bought for it: the clip
    itself, with clip QC's words (`shot_second_look`). Her yes (`look_accepts`) restores the
    still (APPROVED, hers) and the clip (PAID, hers, its note written) and nothing is bought
    for the scene; anything else leaves the scene as it was. Returns the scenes restored.

    2026-10-15, episode 2 scene 1: clip QC blamed the still (ruled papers, a zoom), nobody
    looked at the clip, the still she had already approved went back to the gate and the
    scene was about to buy a new still and a new clip. The Owner saw the clip: «este
    acceptabilă, nu are nimic greșit în ea … ea poate să hotărască că imaginea este ok».
    """
    from pathlib import Path  # noqa: PLC0415

    from app.db import lock_for_write  # noqa: PLC0415
    from app.providers.runpod.wiring import sync_take_quality  # noqa: PLC0415
    from app.services import append_event, utc_now  # noqa: PLC0415

    if registry is None:
        return []
    offered: dict[int, tuple[str, str, str, str]] = {}
    with Session(engine) as session:
        stills = session.scalars(
            select(SceneTake)
            .where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.kind == "still",
                SceneTake.status == "REJECTED",
            )
            .order_by(SceneTake.created_at.desc())
        ).all()
        for still in stills:
            scene = int(still.scene_number)
            if scene in offered:
                continue
            if not str(still.failure_detail or "").startswith(SENT_BACK_FOR_CLIP_MARK):
                continue
            newer = session.scalar(
                select(SceneTake.id).where(
                    SceneTake.storyboard_id == storyboard_id,
                    SceneTake.scene_number == still.scene_number,
                    SceneTake.kind == "still",
                    SceneTake.status.in_(("APPROVED", "PAID")),
                    SceneTake.created_at > still.created_at,
                )
            )
            if newer is not None:
                continue  # the scene moved on: a later still is approved or paid
            # (a sibling of the same round the gate refused is not «newer»: 2026-10-15
            # 07:59Z, scenes 2 and 5 of episode 2 were skipped for one and bought again)
            clip = session.scalar(
                select(SceneTake)
                .where(
                    SceneTake.storyboard_id == storyboard_id,
                    SceneTake.scene_number == still.scene_number,
                    SceneTake.kind.in_(("test_shot", "motion")),
                    SceneTake.status == "REJECTED",
                )
                .order_by(SceneTake.created_at.desc())
                .limit(1)
            )
            if clip is None or not clip.path or not Path(str(clip.path)).exists():
                continue
            offered[scene] = (still.id, clip.id, str(clip.path), str(clip.failure_detail or ""))
    restored: list[int] = []
    for scene, (still_id, clip_id, path, detail) in sorted(offered.items()):
        look = shot_second_look(
            engine,
            registry,
            storyboard_id=storyboard_id,
            scene_index=scene,
            clip=Path(path),
            refusal=[detail],
            correlation_id=correlation_id,
            take_ids=[clip_id],
            ffmpeg_path=ffmpeg_path,
        )
        if not look_accepts(look):
            continue
        with Session(engine) as session, session.begin():
            lock_for_write(session)
            still = session.get(SceneTake, still_id)
            clip = session.get(SceneTake, clip_id)
            if (
                still is None
                or clip is None
                or still.status != "REJECTED"
                or clip.status != "REJECTED"
            ):
                continue
            reason = str(look.get("reason_ro") or "")[:400]
            for take in (still, clip):
                take.status = "APPROVED" if take.kind == "still" else "PAID"
                take.approved_by = DIRECTOR_LOOK_APPROVER
                take.failure_code = None
                take.failure_detail = None
                take.updated_at = utc_now()
                sync_take_quality(session, take, accepted=True, reason=reason)
            record_take_note(
                session,
                storyboard_id=storyboard_id,
                scene_number=scene,
                take_id=clip_id,
                kind="motion",
                approved_by=DIRECTOR_LOOK_APPROVER,
                look=look,
                correlation_id=correlation_id,
            )
            # The clip's record is what the hero gate and the sheet read (`assembler.hero_gate`:
            # a PAID hero with a PASSED record is accepted without the Owner's look): as the
            # motion step writes it when her look keeps a clip, PASSED as hers, the blocks
            # kept beside her reason (2026-10-15 07:13Z: restored takes with a FAILED record
            # sent him a letter asking for his look at the test shot).
            from app.media.assembler import CLIP_QC_EVENT, clip_qc_of  # noqa: PLC0415

            earlier = clip_qc_of(session, clip_id) or {}
            append_event(
                session,
                CLIP_QC_EVENT,
                "scene_take",
                clip_id,
                1,
                {
                    **earlier,
                    "storyboard_id": storyboard_id,
                    "scene_number": scene,
                    "take_id": clip_id,
                    "attempt": int(earlier.get("attempt") or 1) + 1,
                    "verdict": "PASSED",
                    "passed": True,
                    "accepted_by": DIRECTOR_LOOK_APPROVER,
                    "director_look": look_record(look),
                },
                correlation_id,
            )
            append_event(
                session,
                SCENE_RESTORED_EVENT,
                "scene_take",
                clip_id,
                1,
                {
                    "storyboard_id": storyboard_id,
                    "scene_number": scene,
                    "still_take_id": still_id,
                    "clip_take_id": clip_id,
                    "reason": reason,
                    "severity": look.get("severity"),
                },
                correlation_id,
            )
        restored.append(scene)
    settle_clips_she_kept(engine, storyboard_id=storyboard_id, correlation_id=correlation_id)
    return restored


def settle_clips_she_kept(engine: Any, *, storyboard_id: str, correlation_id: str) -> list[str]:
    """Every PAID clip of the film her look kept (approved_by `DIRECTOR_LOOK_APPROVER`) whose
    latest record still says FAILED gets the PASSED record her note carries — what the hero
    gate and the sheet read. Idempotent; returns the take ids settled. 2026-10-15 07:13Z: the
    first restore wrote the takes but not the record, and the hero waited for the Owner's
    look over a clip she had already kept."""
    from app.db import lock_for_write  # noqa: PLC0415
    from app.media.assembler import CLIP_QC_EVENT, clip_qc_of  # noqa: PLC0415
    from app.services import append_event  # noqa: PLC0415

    settled: list[str] = []
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        clips = session.scalars(
            select(SceneTake).where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.kind.in_(("test_shot", "motion")),
                SceneTake.status == "PAID",
                SceneTake.approved_by == DIRECTOR_LOOK_APPROVER,
            )
        ).all()
        for clip in clips:
            earlier = clip_qc_of(session, clip.id)
            if earlier is None or earlier.get("verdict") == "PASSED":
                continue
            note = take_note(session, clip.id) or {}
            append_event(
                session,
                CLIP_QC_EVENT,
                "scene_take",
                clip.id,
                1,
                {
                    **earlier,
                    "storyboard_id": storyboard_id,
                    "scene_number": int(clip.scene_number),
                    "take_id": clip.id,
                    "attempt": int(earlier.get("attempt") or 1) + 1,
                    "verdict": "PASSED",
                    "passed": True,
                    "accepted_by": DIRECTOR_LOOK_APPROVER,
                    "director_look": note.get("director_look"),
                },
                correlation_id,
            )
            settled.append(clip.id)
    return settled


def clip_settled(
    session: Session,
    *,
    storyboard_id: str,
    scene_number: int,
    take_id: str | None,
    must_fix: Sequence[Mapping[str, Any]],
    reports: Sequence[Any],
    kept: bool,
    look: Mapping[str, Any] | None,
    correlation_id: str,
    earlier: Sequence[Sequence[Mapping[str, Any]]] = (),
) -> None:
    """What clip QC's last word on a scene's clip leaves: on the clip kept, its minor traces
    and her look when hers kept it (`record_take_note`); for the movement's rewrite, its
    lessons confirmed by the clip kept with every item of a run gone (`confirm_lessons`), or,
    when no clip was kept, withdrawn for a run whose item persisted on a clip of the scene's
    QC and was corrected on none (``reports``: the first clip and its retry; ``earlier``: the
    answers of a first clip checked in an earlier round, when its retry was bought in a
    batch; `withdraw_lessons`). Called only for clip QC's LAST word: a retry merely deferred
    to the next RunPod round settles nothing (the review of 5fc7468, finding 6)."""
    looks = [[dict(fix) for fix in answers] for answers in earlier] + [
        [dict(fix) for fix in getattr(report, "fixes", ()) or ()] for report in reports
    ]
    fixes = looks[-1] if looks else []
    if kept and take_id:
        record_take_note(
            session,
            storyboard_id=storyboard_id,
            scene_number=scene_number,
            take_id=take_id,
            kind="motion",
            approved_by=DIRECTOR_LOOK_APPROVER if look is not None else "clip_qc",
            minor=minor_traces(fixes),
            look=look,
            correlation_id=correlation_id,
            answers=fixes,
        )
    if not must_fix:
        return
    if kept:
        confirm_lessons(session, fixes, storyboard_id=storyboard_id, scene_index=scene_number)
    else:
        withdraw_lessons(session, looks)


def accepted_on_takes(session: Session, take_ids: Iterable[str | None]) -> dict[str, Any]:
    """What was accepted on each of these takes, by take id (the newest `take_note` of each,
    as {"kind", "approved_by", "minor": [{"finding", "seen"}], "director_look"}); a take with
    no note is left out. The reader the film's QC context needs so that a trace the gate or
    clip QC accepted, or her look kept, is not refused again after the money (the review of
    5fc7468, finding 9: the note had no reader)."""
    accepted: dict[str, Any] = {}
    for take_id in dict.fromkeys(str(take) for take in take_ids if take):
        note = take_note(session, take_id)
        if note is None:
            continue
        accepted[take_id] = {
            key: note.get(key) for key in ("kind", "approved_by", "minor", "director_look")
        }
    return accepted


def recorded_answers(clip_record: Mapping[str, Any] | None) -> list[list[dict[str, Any]]]:
    """The look's answers to the motion items on each report of a scene's clip-QC record
    (`assembler.clip_report_record` keeps them under ``measured.picture.fixes``), oldest
    first: what a first clip said when its retry is checked in a later RunPod round."""
    answers: list[list[dict[str, Any]]] = []
    for report in (clip_record or {}).get("reports") or []:
        picture = ((report or {}).get("measured") or {}).get("picture") or {}
        fixes = picture.get("fixes") if isinstance(picture, Mapping) else None
        answers.append([dict(fix) for fix in fixes or [] if isinstance(fix, Mapping)])
    return answers


# ------------------------------------------------- her reading of a pre-contract brief's words


class FilmReasonsSeen(BaseModel):
    """Her reading of a brief's film words: only what quality control SAW in the picture or
    the clip, in its own words (shortened at most), one sight per entry; nothing when it
    names no sight."""

    model_config = ConfigDict(extra="ignore")
    seen: list[str] = Field(default_factory=list)

    @field_validator("seen", mode="before")
    @classmethod
    def _sights(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        # Complete observed findings; output formatting must not erase later defects.
        return [_said(text) for text in value if _said(text)]


_FILM_READ_INSTRUCTIONS = (
    "You are the Director of a film studio. Quality control refused scene {scene} of a film "
    "and the brief below carries its words, mixed with the studio's process notes and your "
    "own earlier prescriptions. List ONLY what quality control SAW in the picture or the clip "
    "— a defect a viewer can see (two women instead of one, lettering on a ring, a bare-rock "
    "tunnel instead of a detector) — each in quality control's own words, shortened at most, "
    "one sight per entry, at most {limit}. Leave out every process note (a take rejected, "
    "replaced, a test shot, not approved, the motion made from the new still), every "
    "prescription (rewrite, redo, re-animate, drop a word, no negations, describe…, name…) and "
    "every price. When it names no sight, answer an empty list. Answer only the JSON object "
    '{{"seen": ["..."]}}.\n\n'
)


def _unread_briefs(session: Session, storyboard_id: str) -> list[tuple[int, DomainEvent]]:
    """The briefs whose film words a pre-contract rewrite of the storyboard is checked by
    (`_rewrite_items`: the newest rewrite per scene and layer, recorded before her review kept
    findings) and that she has not read: (scene, brief), each once."""
    from app.media.assembler import SCENE_PROMPTS_REWRITTEN_EVENT  # noqa: PLC0415 - a large module
    from app.media.scene_rewrite import BRIEF_EVENT, REWRITE_REASON  # noqa: PLC0415

    events = list(
        session.scalars(
            select(DomainEvent)
            .where(
                DomainEvent.aggregate_id == storyboard_id,
                DomainEvent.event_type.in_((SCENE_PROMPTS_REWRITTEN_EVENT, BRIEF_EVENT)),
            )
            .order_by(DomainEvent.sequence.desc())
        )
    )
    briefs: dict[int, list[DomainEvent]] = {}
    newest: dict[tuple[int, bool], DomainEvent] = {}
    for event in events:
        payload = event.payload if isinstance(event.payload, dict) else {}
        scene = _scene_of(payload)
        if scene is None:
            continue
        if event.event_type == BRIEF_EVENT:
            briefs.setdefault(scene, []).append(event)
        elif payload.get("reason") == REWRITE_REASON:
            newest.setdefault((scene, False), event)
            if _rewrote_picture(payload):
                newest.setdefault((scene, True), event)
    wanted: dict[str, tuple[int, DomainEvent]] = {}
    for (scene, _picture), rewrite in newest.items():
        payload = rewrite.payload if isinstance(rewrite.payload, dict) else {}
        review = payload.get("review") if isinstance(payload.get("review"), dict) else {}
        if (review or {}).get("findings"):
            continue
        brief = _brief_of(rewrite, briefs.get(scene, []), payload.get("run_id"))
        if brief is None or not _film_reasons(brief):
            continue
        if _film_read(session, storyboard_id, str(brief.event_id)) is None:
            wanted[str(brief.event_id)] = (scene, brief)
    return list(wanted.values())


def read_film_reasons(
    engine: Any, registry: Any, *, storyboard_id: str, correlation_id: str
) -> int:
    """The Director reads the film words of the storyboard's pre-contract briefs that the fix
    check reads (`_unread_briefs`) and says what quality control SAW (`FilmReasonsSeen`); each
    reading is recorded (`FILM_READ_EVENT`) and read by `_rewrite_items` instead of the patterns
    of `observed`. Free: a model call, no purchase (the Owner, 2026-10-12: «LLM-ul este pe
    abonament!»). Returns how many briefs she read; never raises — with no registry, no Director
    or an answer that does not validate twice nothing is recorded and the patterns stand.

    2026-10-12 (the review of 5fc7468, finding 11): «The motion take is a test_shot, not
    approved;», «drop 'sensors and electronics' which invited instrument markings;» and «no
    negations, no 'text'.» went through the patterns as things a still must not show again —
    process notes and her own prescriptions, asked of every picture as if quality control had
    seen them."""
    if registry is None or not storyboard_id:
        return 0
    try:
        from app.agents.memory import agent_for_role  # noqa: PLC0415 - agents import media
        from app.agents.structured import structured_run  # noqa: PLC0415 - it imports services
        from app.db import lock_for_write  # noqa: PLC0415
        from app.factual.sanitizer import wrap_in_inert_boundary  # noqa: PLC0415
        from app.services import append_event  # noqa: PLC0415 - services imports media

        with Session(engine) as session:
            unread = _unread_briefs(session, storyboard_id)[:FILM_READ_PER_CALL]
            director = agent_for_role(session, "Director") if unread else None
            director_id = str(director.id) if director is not None else None
        if not unread or director_id is None:
            return 0
        read = 0
        for scene, brief in unread:
            reasons = _film_reasons(brief)
            prompt = _FILM_READ_INSTRUCTIONS.format(
                scene=scene, limit=max(1, len(reasons))
            ) + wrap_in_inert_boundary(
                json.dumps({"film_reasons": reasons}, ensure_ascii=False), "film-reasons"
            )
            parsed, first, second = structured_run(
                engine,
                registry,
                director_id,
                FILM_READ_TASK,
                prompt,
                FILM_READ_TEMPLATE_VERSION,
                correlation_id or str(uuid4()),
                FilmReasonsSeen,
                "",
                summary=f"Directoarea citește ce a văzut controlul în scena {scene}",
                max_tokens=1200,
            )
            if parsed is None:
                continue
            last = second or first
            with Session(engine) as session, session.begin():
                lock_for_write(session)
                if _film_read(session, storyboard_id, str(brief.event_id)) is not None:
                    continue  # read meanwhile by another step: one reading per brief
                append_event(
                    session,
                    FILM_READ_EVENT,
                    "storyboard",
                    storyboard_id,
                    1,
                    {
                        "storyboard_id": storyboard_id,
                        "scene_index": scene,
                        "brief_event_id": str(brief.event_id),
                        "seen": list(parsed.seen),
                        "reasons": reasons,
                        "run_id": str(last.get("id")) if last.get("id") else None,
                    },
                    correlation_id or str(uuid4()),
                )
            read += 1
        return read
    except Exception as exc:  # noqa: BLE001 - her silence leaves the patterns standing
        logger.warning("film_reasons_read_failed", extra={"error": type(exc).__name__})
        return 0
