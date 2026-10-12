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
IMAGINI ȘI MIȘCĂRI COSTĂ!»), and what a look teaches the rewrite's lessons (`settle_lessons`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.media.models import SceneTake
from app.models import DomainEvent

#: At most this many items are checked on one picture or clip, each at most this long: the
#: look stays one look, and the refusal's words stay inside a take's failure detail.
MAX_ITEMS = 4
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
#: Where an item comes from, in the order they are ranked under the cap.
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
#: explicitly …», «redo the motion on the new still with the same tilt-down …».
PROPOSAL_SENTENCE = re.compile(
    r"\b(?:must be (?:re)?done|must be redone|must change|re-?do|redone|rewrit\w*"
    r"|paid redo|credits?|buy\w*|bought|purchas\w*|join the|approved still|new still"
    r"|the prompt|motion prompt|still prompt|refac\w*|rescri\w*|cumpăr\w*|credite"
    r"|plătit\w*|alătur\w*)\b",
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
#: only where money or the bible's hard limits are at stake — faces where forbidden, writing,
#: panels; a blank or striped field is no picture at all).
HARD_LIMITS = frozenset({"faces", "readable_text", "panels", "degenerate"})
#: Her second look's verdicts (`app.media.second_look.second_look`, the shared contract).
CONFIRMED, OVERTURNED, UNAVAILABLE = "CONFIRMED", "OVERTURNED", "UNAVAILABLE"


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
) -> dict[str, Any]:
    return {
        "finding": _cut(_said(finding)),
        "expected": _cut(_said(expected)),
        "layer": layer,
        "source": source,
        "source_id": str(source_id) if source_id else None,
        "cause": _cut(_said(cause)),
        "at": str(at or ""),
    }


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
                )
            )
        if entries:
            continue
        # A rewrite recorded before her review kept its findings: the film's own words on her
        # brief, the sentences that say what was seen. Recorded right after the rewrite it
        # asked for (`scene_rewrite._rung`): the brief naming its run, else the first after.
        run_id = payload.get("run_id")
        after = [event for event in briefs if int(event.sequence) > int(rewrite.sequence)]
        brief = next(
            (e for e in after if run_id and (e.payload or {}).get("rewrite_run_id") == run_id),
            after[-1] if after else None,
        )
        said = brief.payload if brief is not None and isinstance(brief.payload, dict) else {}
        layer = MOTION_LAYER if layers == (MOTION_LAYER,) else STILL_LAYER
        for failure in said.get("failures") or []:
            if isinstance(failure, dict) and failure.get("kind") == "film":
                for reason in failure.get("reasons") or []:
                    seen = observed(reason)
                    if seen:
                        # A film reason names no layer: the picture's rewrite checks it on
                        # the still and on the clip after it, the movement's on the clip.
                        on = BOTH_LAYERS if layer == STILL_LAYER else MOTION_LAYER
                        items.append(_item(seen, "", on, FROM_FILM, at=rewrite.timestamp))
    return items


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
    {"finding", "expected", "layer", "source", "source_id", "cause", "at"} (``layer``: still,
    motion or both; ``expected`` the sentence her review said treats it, guidance, empty when
    none; ``source_id`` the review run whose lessons the look confirms or withdraws)."""
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
    corrected: `open_items` of that layer, ranked (`_ranked`), at most `MAX_ITEMS`. Empty when
    nothing was rewritten or refused for it, or when a still approved (a clip passed) after
    it already answered."""
    items = [
        {key: value for key, value in item.items() if key != "at"}
        for item in open_items(session, storyboard_id, scene_index)
        if _on(item, layer)
    ]
    return _ranked(items, layer)[:MAX_ITEMS]


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


def settle_lessons(
    session: Session,
    items: Sequence[Mapping[str, Any]],
    fixes: Sequence[Mapping[str, Any]] | None,
    *,
    approved: bool,
    persisted: bool,
) -> str | None:
    """What a look teaches the rewrite's lessons (stored provisional with the review's run as
    their source, `prompt_agent.record_prompt_lesson`): a take approved with every item GONE
    confirms them (`confirm_prompt_lessons`); a take refused because an item persists, with no
    take of the round approved clean, withdraws them (`withdraw_prompt_lessons`). Returns
    "confirmed", "withdrawn" or None. 2026-10-12, the Owner: «la viitoarele prompturi să se
    asigure că nu mai sunt» — a lesson that did not correct the mistake must not teach it."""
    sources = review_sources(items)
    if not sources:
        return None
    from app.media import prompt_agent  # noqa: PLC0415 - a large module

    every_gone = bool(fixes) and all(fix.get("status") == GONE for fix in fixes or ())
    if approved and every_gone:
        confirm = getattr(prompt_agent, "confirm_prompt_lessons", None)
        if callable(confirm):
            confirm(session, sources)
            return "confirmed"
        return None
    if persisted:
        withdraw = getattr(prompt_agent, "withdraw_prompt_lessons", None)
        if callable(withdraw):
            withdraw(
                session,
                sources,
                "imaginea făcută pe cuvintele corectate repetă greșeala: lecția nu a corectat-o",
            )
            return "withdrawn"
    return None


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
) -> None:
    """Write on the take (`TAKE_NOTE_EVENT`) what was accepted on it: the minor traces the look
    saw, and her look's verdict and reason when hers approved it."""
    from app.services import append_event  # noqa: PLC0415 - services imports media

    if not minor and look is None:
        return
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
    }


def look_accepts(look: Mapping[str, Any] | None) -> bool:
    """Whether her look lets the take stand, so nothing is bought for it: the refusal was wrong
    and what is there is at most minor (OVERTURNED, none or minor), or it was right about a
    defect she calls minor and says need not be redone (CONFIRMED, minor, redo false — the
    Owner: «DIRECTOAREA ACCEPTĂ DEFECTELE MICI!»)."""
    if not look:
        return False
    verdict, severity = look.get("verdict"), look.get("severity")
    if verdict == OVERTURNED:
        return severity in ("none", "minor")
    return verdict == CONFIRMED and severity == "minor" and look.get("redo") is False


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


def clip_settled(
    session: Session,
    *,
    storyboard_id: str,
    scene_number: int,
    take_id: str | None,
    must_fix: Sequence[Mapping[str, Any]],
    report: Any,
    kept: bool,
    look: Mapping[str, Any] | None,
    correlation_id: str,
) -> None:
    """What clip QC's last word on a scene's clip leaves: on the clip kept, its minor traces
    and her look when hers kept it (`record_take_note`); for the movement's rewrite, its
    lessons confirmed by a clip kept with every item gone, withdrawn by one that showed a
    mistake again (`settle_lessons`)."""
    fixes = [dict(fix) for fix in getattr(report, "fixes", ()) or ()]
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
        )
    if must_fix:
        settle_lessons(
            session,
            must_fix,
            fixes,
            approved=kept,
            persisted=not kept and any(fix.get("status") == PERSISTS for fix in fixes),
        )
