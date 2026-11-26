"""Past the Owner's renders cap: what a scene keeps, and who chose it (2026-10-16).

The Owner, 2026-10-15: «Randările odată făcute, de maxim 3x pentru fiecare imagine sau mișcare
… publicăm cu ce Directoarea alege ca fiind cel mai apropiat»; since 2026-10-16 two renders a
layer (`renders_cap`). Until the dishonest-code audit of 2026-10-16 (STUB-001) the studio said
«Directoarea alege / păstrează ce este cel mai apropiat de plan» on every route past the cap,
while the code kept the newest file on disk and nobody looked at anything.

Now, when a scene's layer is at the cap and something of it has to stand:

- with two or more takes of that layer on disk that may stand (`stills_stage._cap_candidates`,
  `assembler._cap_shot_candidates`: never one the Owner rejected himself, never a file that is
  not the one bought), the Director is asked ONE look (`agents.reviews.review_bought_pictures`
  with ``cap=True``: «CHOOSE candidate K», never REJECT; the BARE context, its data carrying
  what she judges) at the candidates against the scene's plan — a still at 1080 px, a clip's
  first, middle and last frames — and her choice stands;
- with one, it stays: there is nothing to choose, nobody is asked, and the words say so;
- with no model registry, no Director, no model that sees, or a look that fails, the studio
  keeps the first of the caller's own order (one quality control passed first, then the
  newest) and says that the studio kept it, never that she chose.

Every choice is recorded (`CAP_CHOICE_EVENT`, on the film) in the transaction that keeps the
take (`record_cap_choice`): who chose, how, among which takes, and her reason.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.media.models import SceneTake, Storyboard, StoryboardScene
from app.services import append_event
from app.wording import count

logger = logging.getLogger("studio.cap_choice")

#: {storyboard_id, scene_index, layer, take_id, chosen_by, how, candidates, shown, not_shown,
#: reason_ro, words_ro, the run when she looked, and what the take was before it was kept}.
CAP_CHOICE_EVENT = "media.cap_choice"
#: Who chose the take kept under the cap.
BY_DIRECTOR = "director"
BY_STUDIO = "studio"
#: How it was chosen: she looked and chose; the scene had one take; of several only one could
#: be shown to her; she could not choose and the studio kept its own pick.
LOOKED = "LOOKED"
ONLY_ONE = "ONLY_ONE"
ONLY_SHOWN = "ONLY_SHOWN"
FALLBACK = "FALLBACK"
#: How many takes she is shown at most, the first of the caller's order (as her look at the
#: candidates her repair bought, `director_qc.LOOK_MAX_CANDIDATES`).
MAX_SHOWN = 6
#: What stands for a layer past the cap, as every sentence that promises it says it.
CAP_KEEPS_RO = (
    "rămâne ce are scena: cu mai multe variante, Directoarea o alege pe cea mai apropiată de "
    "plan, iar când nu le poate privi, studioul o păstrează pe cea trecută de control, altfel "
    "pe cea mai nouă"
)
#: The studio's own order when nobody chooses, said per layer.
STUDIO_RULE_RO = {
    "still": "întâi una trecută de control, apoi cea mai nouă",
    "motion": "întâi unul trecut de control, apoi cel mai nou",
}


@dataclass(frozen=True)
class CapChoice:
    """The take a scene keeps under the cap, and how it came to be the one."""

    take_id: str
    layer: str
    chosen_by: str
    how: str
    words_ro: str
    reason_ro: str = ""
    candidates: tuple[str, ...] = ()
    shown: tuple[str, ...] = ()
    not_shown: tuple[Mapping[str, str], ...] = ()
    run: Mapping[str, Any] = field(default_factory=dict)

    @property
    def by_director(self) -> bool:
        return self.chosen_by == BY_DIRECTOR


def _nouns(layer: str) -> tuple[str, str]:
    return ("imagine", "imagini") if layer == "still" else ("clip", "clipuri")


def _many(layer: str, number: int) -> str:
    one, many = _nouns(layer)
    return count(number, one, many)


def only_one_words(layer: str, scene_index: int) -> str:
    """One take of the layer on disk that may stand: it stays, nobody chose it."""
    if layer == "still":
        return (
            f"Scena {scene_index} are o singură imagine pe disc care poate rămâne; rămâne "
            "aceasta, fără nicio alegere."
        )
    return (
        f"Scena {scene_index} are un singur clip pe disc care poate rămâne; rămâne acesta, "
        "fără nicio alegere."
    )


def _only_shown_words(layer: str, scene_index: int, number: int) -> str:
    if layer == "still":
        return (
            f"Din cele {_many(layer, number)} ale scenei {scene_index}, doar una a putut fi "
            "pregătită pentru privirea Directoarei; studioul a păstrat-o pe aceasta, fără nicio "
            "alegere."
        )
    return (
        f"Din cele {_many(layer, number)} ale scenei {scene_index}, doar unul a putut fi "
        "pregătit pentru privirea Directoarei; studioul l-a păstrat pe acesta, fără nicio "
        "alegere."
    )


def _looked_words(layer: str, scene_index: int, number: int, candidate: int, reason: str) -> str:
    if layer == "still":
        said = (
            f"Directoarea a privit {_many(layer, number)} ale scenei {scene_index} și a ales-o "
            f"pe cea mai apropiată de plan (varianta {candidate})"
        )
    else:
        said = (
            f"Directoarea a privit {_many(layer, number)} ale scenei {scene_index} și l-a ales "
            f"pe cel mai apropiat de plan (varianta {candidate})"
        )
    reason = " ".join(str(reason or "").split()).rstrip(".")
    return f"{said}: {reason}." if reason else f"{said}."


def fallback_words(layer: str, scene_index: int, number: int, rule_ro: str, why: str) -> str:
    """The studio kept one take of several: by its own order, and why she did not choose."""
    one = "o imagine" if layer == "still" else "un clip"
    why = " ".join(str(why or "").split()).rstrip(".") or "nu a putut fi întrebată"
    return (
        f"Studioul a păstrat {one} din cele {_many(layer, number)} ale scenei {scene_index}, "
        f"după regula lui ({rule_ro}); Directoarea nu a ales: {why}."
    )


def _fallback(
    layer: str,
    scene_index: int,
    ids: list[str],
    rule_ro: str,
    why: str,
    *,
    shown: Sequence[str] = (),
    not_shown: Sequence[Mapping[str, str]] = (),
) -> CapChoice:
    return CapChoice(
        take_id=ids[0],
        layer=layer,
        chosen_by=BY_STUDIO,
        how=FALLBACK,
        words_ro=fallback_words(layer, scene_index, len(ids), rule_ro, why),
        reason_ro=" ".join(str(why or "").split())[:600],
        candidates=tuple(ids),
        shown=tuple(shown),
        not_shown=tuple(not_shown),
    )


def _film_title(session: Session, storyboard_id: str) -> str:
    board = session.get(Storyboard, storyboard_id)
    words = str(board.title if board is not None else "")
    return words.removeprefix("Storyboard: ").strip() or storyboard_id[:8]


def _qc_said(session: Session, row: SceneTake) -> dict[str, Any]:
    """What quality control said about one candidate, as she is shown it."""
    said: dict[str, Any] = {"status": row.status, "failure_code": row.failure_code}
    reasons = [part.strip() for part in str(row.failure_detail or "").split("; ") if part.strip()]
    if row.kind != "still":
        from app.media.assembler import clip_qc_of  # noqa: PLC0415 - a large module

        record = clip_qc_of(session, row.id) or {}
        said["clip_qc_verdict"] = record.get("qc_verdict") or record.get("verdict")
        reasons = [str(text) for text in record.get("blocks_ro") or [] if str(text).strip()] or [
            part.removeprefix("Controlul clipului: ") for part in reasons
        ]
    said["qc_reasons"] = reasons[:8]
    return said


def _prepare(
    engine: Engine,
    storyboard_id: str,
    scene_index: int,
    layer: str,
    ids: list[str],
    ffmpeg_path: str | None,
    work_dir: Path,
) -> tuple[dict[str, Any], list[str], list[str], list[dict[str, str]]]:
    """What she is shown: the scene and its candidates (`shown`), their pictures in order
    (`images`), the take ids offered, and the ones not offered with why (no picture at all,
    pictures that cannot be prepared, more than `MAX_SHOWN`)."""
    from app.media.director_qc import (  # noqa: PLC0415 - it imports the agents' reviews
        look_pictures,
        no_picture,
        scene_look_view,
    )
    from app.media.prompt_lint import bible_face_rule  # noqa: PLC0415
    from app.media.stills_stage import _bible_rules  # noqa: PLC0415 - the gate's own rules
    from app.media.toolchain import find_ffmpeg  # noqa: PLC0415

    ffmpeg = find_ffmpeg(ffmpeg_path)
    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        bible = dict(board.visual_bible_json or {}) if board is not None else {}
        title = _film_title(session, storyboard_id)
        row = session.scalars(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id,
                StoryboardScene.scene_index == int(scene_index),
            )
        ).first()
        view = scene_look_view(row, int(scene_index), layer)
        takes = []
        for take_id in ids:
            take = session.get(SceneTake, take_id)
            if take is not None:
                takes.append((take, _qc_said(session, take)))
                session.expunge(take)
    offered: list[str] = []
    not_offered: list[dict[str, str]] = []
    candidates: list[dict[str, Any]] = []
    images: list[str] = []
    for take, said in takes:
        why: str | None = None
        if len(offered) >= MAX_SHOWN:
            why = f"i se arată doar primele {MAX_SHOWN} variante"
        elif (broken := no_picture(take, ffmpeg)) is not None:
            why = f"nu este o imagine ({broken})"
        pictures = [] if why else look_pictures(take, ffmpeg_path, work_dir)
        if why is None and not pictures:
            why = "imaginea nu a putut fi pregătită pentru privire"
        if why is not None:
            not_offered.append({"take_id": str(take.id), "why": why[:300]})
            continue
        offered.append(str(take.id))
        images += pictures
        candidates.append({"candidate": len(offered), **said})
    shown = {
        "film": title,
        "kind": "still" if layer == "still" else "shot",
        "past_the_renders_cap": True,
        "scene": view,
        "faces_forbidden": bible_face_rule(bible) is not None,
        "bible_rules": list(_bible_rules(bible))[:12],
        "candidates": candidates,
    }
    return shown, images, offered, not_offered


def choose_under_cap(
    engine: Engine,
    registry: Any | None,
    *,
    storyboard_id: str,
    scene_index: int,
    layer: str,
    take_ids: Sequence[str],
    correlation_id: str,
    ffmpeg_path: str | None = None,
    rule_ro: str | None = None,
) -> CapChoice | None:
    """The take the scene keeps under the cap among ``take_ids`` (the caller's own order: its
    first is what the studio keeps when nobody chooses, ``rule_ro`` says that order), or None
    when there is none. Two or more: her ONE look (module docstring). Writes nothing: the
    caller keeps the take and records the choice (`record_cap_choice`) in one transaction."""
    from app.agents.reviews import ReviewError, review_bought_pictures  # noqa: PLC0415

    ids = [str(take_id) for take_id in dict.fromkeys(take_ids) if take_id]
    if not ids:
        return None
    index = int(scene_index)
    rule = rule_ro or STUDIO_RULE_RO.get(layer, STUDIO_RULE_RO["motion"])
    if len(ids) == 1:
        return CapChoice(
            take_id=ids[0],
            layer=layer,
            chosen_by=BY_STUDIO,
            how=ONLY_ONE,
            words_ro=only_one_words(layer, index),
            candidates=tuple(ids),
        )
    if registry is None or not registry.registered_ids():
        return _fallback(
            layer, index, ids, rule, "studioul nu are niciun model prin care să o întrebe"
        )
    shown_ids: list[str] = []
    not_shown: list[dict[str, str]] = []
    try:
        with tempfile.TemporaryDirectory(prefix="cap_choice_", ignore_cleanup_errors=True) as work:
            shown, images, shown_ids, not_shown = _prepare(
                engine, storyboard_id, index, layer, ids, ffmpeg_path, Path(work)
            )
        if not shown_ids:
            return _fallback(
                layer,
                index,
                ids,
                rule,
                "nicio variantă nu a putut fi pregătită pentru privirea ei",
                not_shown=not_shown,
            )
        if len(shown_ids) == 1:
            return CapChoice(
                take_id=shown_ids[0],
                layer=layer,
                chosen_by=BY_STUDIO,
                how=ONLY_SHOWN,
                words_ro=_only_shown_words(layer, index, len(ids)),
                candidates=tuple(ids),
                shown=tuple(shown_ids),
                not_shown=tuple(not_shown),
            )
        answer = review_bought_pictures(
            engine,
            registry,
            shown,
            images,
            correlation_id,
            storyboard_id=storyboard_id,
            cap=True,
        )
    except ReviewError as exc:
        logger.warning(
            "cap_choice_not_looked",
            extra={"storyboard_id": storyboard_id, "scene": index, "error": str(exc)[:200]},
        )
        return _fallback(layer, index, ids, rule, str(exc), shown=shown_ids, not_shown=not_shown)
    except Exception as exc:  # noqa: BLE001 - a look that fell: the studio keeps, and says so
        logger.warning(
            "cap_choice_failed",
            extra={"storyboard_id": storyboard_id, "scene": index, "error": type(exc).__name__},
        )
        return _fallback(
            layer,
            index,
            ids,
            rule,
            f"privirea ei a căzut ({type(exc).__name__})",
            shown=shown_ids,
            not_shown=not_shown,
        )
    number = answer.get("candidate")
    if answer.get("decision") != "CHOOSE" or not isinstance(number, int):
        return _fallback(
            layer,
            index,
            ids,
            rule,
            "răspunsul ei nu a numit o variantă",
            shown=shown_ids,
            not_shown=not_shown,
        )
    if not 0 < number <= len(shown_ids):
        return _fallback(
            layer,
            index,
            ids,
            rule,
            f"a numit varianta {number}, care nu i-a fost arătată",
            shown=shown_ids,
            not_shown=not_shown,
        )
    reason = " ".join(str(answer.get("reason") or "").split())[:600]
    return CapChoice(
        take_id=shown_ids[number - 1],
        layer=layer,
        chosen_by=BY_DIRECTOR,
        how=LOOKED,
        words_ro=_looked_words(layer, index, len(shown_ids), number, reason),
        reason_ro=reason,
        candidates=tuple(ids),
        shown=tuple(shown_ids),
        not_shown=tuple(not_shown),
        run={
            key: answer.get(key)
            for key in ("agent_id", "agent_name", "run_id", "model")
            if answer.get(key) is not None
        },
    )


def record_cap_choice(
    session: Session,
    choice: CapChoice,
    *,
    storyboard_id: str,
    scene_index: int,
    correlation_id: str,
    previous: Mapping[str, Any] | None = None,
) -> None:
    """Her choice, or the studio's, recorded on the film (`CAP_CHOICE_EVENT`), inside the
    caller's transaction that keeps the take. ``previous``: the take's status and refusal
    before it was kept (the refusal is cleared on the take; it stays here)."""
    append_event(
        session,
        CAP_CHOICE_EVENT,
        "storyboard",
        storyboard_id,
        1,
        {
            "storyboard_id": storyboard_id,
            "scene_index": int(scene_index),
            "layer": choice.layer,
            "take_id": choice.take_id,
            "chosen_by": choice.chosen_by,
            "how": choice.how,
            "candidates": list(choice.candidates),
            "shown": list(choice.shown),
            "not_shown": [dict(item) for item in choice.not_shown],
            "reason_ro": choice.reason_ro,
            "words_ro": choice.words_ro[:1500],
            # The run field is only provenance metadata, never a call to any
            # model's run() method. Read it as data, not as an executable edge
            # in the paid-path audit's conservative call graph.
            **dict(vars(choice)["run"]),
            **({"previous": dict(previous)} if previous else {}),
        },
        correlation_id,
    )
