"""The shooting sheet's sentences that are about more than one row: what the Owner's look at a
take set going, the assembly's wait said once, and a vendor's refusal in his words.

2026-10-04, the Nepal sheet (storyboard 81438d13). He pressed «Alege imaginea aceasta» and saw
nothing change; the notice, at the top of the drawer, said «Nimic nu s-a cumpărat» while the
choice had queued FILM_CONTINUE (`assembler.decide_take`), which bought the test shot under his
rule MODE seconds later. The assemble card repeated one sentence per scene, five times, and a
refused candidate showed the vendor's English twice over.

- `decision_outcome` says what his choice did and what the continuation it queued will do. It
  reads the policy the Policy Kernel reads (`services.may_act`: the stop, safe mode, his
  `paid_media_approval`, the mode, the daily budget, in that order) and describes the verdict;
  it never asks `may_act`, which could spend a yes he already gave.
- `blocked_words` groups the scenes the assembly waits for: one sentence per reason, the
  scenes listed the Romanian way («Scenele 1, 2 și 3 …», «Scena 4 …»).
- `refusal_view` explains a refused take (the known refusals by name, the rest by
  `production_policy.classify_failure`'s kind), with the vendor's text kept once.

Comments in English; every sentence for the Owner in Romanian.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.media.production_policy import classify_failure
from app.models import OwnerPolicy
from app.services import (
    BUDGET_PLACE_WORDS,
    FILM_CONTINUE_TASK,
    MODE_ALLOWS,
    has_active_daily_budget,
    paid_media_policy,
)
from app.wording import autonomy_mode, decimal
from app.wording import environment as environment_words

# ------------------------------------------------------------------------------- scene lists


def scene_list(indexes: Iterable[int]) -> str:
    """Scene numbers the Romanian way: «4», «1 și 2», «1, 2, 3, 4 și 6» (sorted, once each)."""
    numbers = [str(n) for n in sorted({int(n) for n in indexes})]
    if len(numbers) <= 1:
        return "".join(numbers)
    return f"{', '.join(numbers[:-1])} și {numbers[-1]}"


def _scenes(indexes: list[int], one: str, many: str) -> str:
    """«Scena 3 {one}» or «Scenele 2 și 5 {many}»."""
    if len(set(indexes)) == 1:
        return f"Scena {scene_list(indexes)} {one}"
    return f"Scenele {scene_list(indexes)} {many}"


# ---------------------------------------------------------------- 3. the assembly's wait, once

#: A filmed scene with no approved still for its prompt as it is now (`_scene_readiness`).
NO_STILL = "NO_STILL"
#: A filmed scene with a still but no accepted shot and no LOCAL_MOVE of his (PRODUCTION).
NO_SHOT = "NO_SHOT"


def blocked_words(blocked: Iterable[Mapping[str, Any]]) -> str:
    """The scenes the assembly waits for, one sentence per reason instead of one per scene.

    A scene's own cause (its shot refused by the clip QC) stays its own sentence, first; the
    scenes with no still and the scenes with no accepted shot are each said once, grouped. An
    item with no known ``code`` (an older sheet) keeps its own ``reason_ro``."""
    whys: list[str] = []
    own: list[str] = []
    no_still: list[int] = []
    no_shot: list[int] = []
    for item in blocked:
        code = item.get("code")
        index = int(item.get("scene_index") or 0)
        why = str(item.get("why_ro") or "").strip()
        if why and why not in whys:
            whys.append(why)
        if code == NO_STILL:
            no_still.append(index)
        elif code == NO_SHOT:
            no_shot.append(index)
        else:
            reason = str(item.get("reason_ro") or "").strip()
            if reason and reason not in own:
                own.append(reason)
    sentences = [*whys, *own]
    if no_still:
        sentences.append(
            _scenes(
                no_still,
                "nu are o imagine aprobată pentru promptul de acum; cumpărați sau aprobați "
                "imaginea ei pe foaia de filmare.",
                "nu au o imagine aprobată pentru promptul de acum; cumpărați sau aprobați "
                "imaginile lor pe foaia de filmare.",
            )
        )
    if no_shot:
        tail = "(nici „imagine fixă animată local” aleasă pe foaia de filmare)."
        sentences.append(
            _scenes(
                no_shot,
                f"nu are încă un cadru acceptat {tail}",
                f"nu au încă un cadru acceptat {tail}",
            )
        )
    return " ".join(sentences)


# ---------------------------------------------------------- 4. a vendor's refusal, his words

#: Runway's refusal of a picture sent inside the request over its limit (fixed in 626b59d).
_TOO_LARGE = re.compile(
    r"Data URI is too large:\s*([\d.]+)\s*MB exceeds the\s*([\d.]+)\s*MB limit", re.IGNORECASE
)
#: Runway's refusal of a keyframe sent with a fixed ratio (fixed in `runway.pick_ratio`).
_KEYFRAME_RATIO = re.compile(r"must use\s*`?auto_\d+p", re.IGNORECASE)
#: What each kind of `classify_failure` means, said of a request that already ended.
_KIND_WORDS: dict[str, str] = {
    "SAFETY": (
        "Refuz de siguranță al furnizorului: această imagine nu se mai trimite aceluiași model."
    ),
    "CONTRACT": "Furnizorul a refuzat cererea: nu se potrivea contractului acestui model.",
    "TRANSIENT": "Furnizorul nu a fost disponibil când i s-a trimis cererea.",
    "BAD_OUTPUT": "Modelul a livrat un rezultat stricat.",
    "QUALITY": "Rezultatul a picat controlul calității.",
    "ACCOUNT": "Contul furnizorului nu a putut plăti sau nu avea acces.",
    "UNKNOWN": "Furnizorul a refuzat cererea, fără un motiv cunoscut studioului.",
}
_HTTP_CODE = re.compile(r"^HTTP_(\d{3})$")


def dedupe_clauses(text: str | None) -> str:
    """The vendor's text with each «; »-separated clause kept once, in its order."""
    clauses: list[str] = []
    for part in str(text or "").split(";"):
        clause = part.strip()
        if clause and clause not in clauses:
            clauses.append(clause)
    return "; ".join(clauses)


def _mb(value: str) -> str:
    number = float(value)
    return decimal(number, 0) if number == int(number) else decimal(number, 1)


def refusal_view(
    code: str | None,
    detail: str | None,
    credits_measured: float | None,
    credits_quoted: float | None = None,
) -> dict[str, Any]:
    """A refused take for the sheet: ``kind``, ``explain_ro``, ``vendor_text`` (once), the
    ``credits`` it cost and whether that number was measured (``credits_known``).

    A request refused at the door (an HTTP 4xx at submit) created no task and cost nothing.
    Any other refusal with no measured spend keeps what it may have cost: the assembler
    records a task the vendor accepted, or a request left unanswered, in ``credits_quoted``
    («may be charged like a success»); such a take is never said to cost 0 (2026-10-04
    adversary review: it was grouped under «Refuzate de furnizor (0 credite)»)."""
    vendor = dedupe_clauses(detail)
    status = _HTTP_CODE.match(str(code or ""))
    at_the_door = status is not None and 400 <= int(status.group(1)) < 500
    if credits_measured is not None:
        credits, known = float(credits_measured), True
    elif at_the_door or not credits_quoted or float(credits_quoted) <= 0:
        credits, known = 0.0, True
    else:
        credits, known = float(credits_quoted), False
    view = _refusal_kind(code, status, vendor)
    if not known:
        view["explain_ro"] += (
            f" Cererea ajunsese la furnizor: poate fi taxată, până la {_mb(str(credits))} "
            "credite (costul nu a fost măsurat)."
        )
    return {**view, "vendor_text": vendor, "credits": credits, "credits_known": known}


def _refusal_kind(code: str | None, status: re.Match[str] | None, vendor: str) -> dict[str, Any]:
    """The refusal's ``kind`` and its explanation in the Owner's words."""
    large = _TOO_LARGE.search(vendor)
    if large:
        # The field Runway names: a reference picture or the clip's first frame.
        what = (
            "Prima imagine a clipului"
            if "promptImage" in vendor and "referenceImages" not in vendor
            else "Imaginea de referință"
        )
        return {
            "kind": "PICTURE_TOO_LARGE",
            "explain_ro": (
                f"{what} trimisă avea {_mb(large.group(1))} MB, peste limita "
                f"Runway de {_mb(large.group(2))} MB, iar Runway a refuzat cererea înainte să "
                "genereze ceva. Reparat de atunci (626b59d): studioul micșorează imaginea sub "
                "limită înainte s-o trimită."
            ),
        }
    if _KEYFRAME_RATIO.search(vendor):
        # Said as what the studio does since, not as "fixed": a model whose contract lists no
        # auto ratio still gets a fixed one (`runway.pick_ratio`).
        return {
            "kind": "RATIO_NOT_AUTO",
            "explain_ro": (
                "Runway cere ca un clip pornit dintr-o imagine să folosească un raport „auto” "
                "(forma clipului urmează imaginea), iar studioul trimisese un raport fix. "
                "De atunci, cu o primă imagine, studioul trimite raportul „auto” cel mai mare "
                "dintre cele din contractul modelului."
            ),
        }
    verdict = classify_failure(
        None if status else code,
        http_status=int(status.group(1)) if status else None,
        detail=vendor,
    )
    return {
        "kind": verdict.kind,
        "explain_ro": _KIND_WORDS.get(verdict.kind, _KIND_WORDS["UNKNOWN"]),
    }


# --------------------------------------------------- 2. what his look at a take set going

#: What a still, a test shot and a clip are called in the first sentence of the answer.
_CHOSEN: dict[tuple[str, str], str] = {
    ("still", "APPROVED"): "Imaginea scenei {n} este aleasă.",
    ("test_shot", "APPROVED"): "Cadrul de probă al scenei {n} este aprobat.",
    ("motion", "APPROVED"): "Clipul scenei {n} este aprobat.",
    ("still", "REJECTED"): "Imaginea respinsă a scenei {n} nu se mai folosește în film.",
    ("test_shot", "REJECTED"): "Cadrul de probă respins al scenei {n} nu se mai folosește în film.",
    ("motion", "REJECTED"): "Clipul respins al scenei {n} nu se mai folosește în film.",
}


def _safe_mode_open(session: Session) -> bool:
    from app.runbook.models import SafeModeRecord  # noqa: PLC0415 - runbook imports media

    found = session.scalars(
        select(SafeModeRecord).where(SafeModeRecord.cleared_at.is_(None)).limit(1)
    ).first()
    return found is not None


def _next_step(sheet: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The first paid step of the sheet that still has something to buy, as the staircase
    walks it (`runbook.stages._film_staircase`)."""
    from app.media.shooting_sheet import SHEET_STEPS, STEP_WORDS_RO  # noqa: PLC0415

    steps = (sheet or {}).get("steps") or {}
    for name in SHEET_STEPS:
        step = steps.get(name) or {}
        if step.get("to_buy"):
            return {
                "step": name,
                "words": STEP_WORDS_RO.get(name, name),
                "tier": step.get("tier"),
                "cap_usd": step.get("cap_usd"),
                "action": step.get("action"),
                "cap_credits": step.get("cap_credits"),
            }
    return None


#: A FILM_CONTINUE task that has not run yet or is running (`workflows.services`).
_LIVE_TASK = ("QUEUED", "RETRYING", "CLAIMED", "RUNNING")


def _continuation_live(session: Session, task_id: str, storyboard_id: str | None) -> bool:
    """Whether a continuation of this film will still walk it: the task his decision named,
    or any other FILM_CONTINUE of the film not yet finished.

    2026-10-04 adversary review: `queue_film_continue` is keyed per take, so choosing a
    picture back (the Nepal books, 20:56:33, deaa682c) returned the task of its first choice,
    which had run hours before; nothing new was queued, yet the answer said the film
    continued and bought."""
    from app.workflows.models import TaskQueueItem  # noqa: PLC0415 - workflows import media

    own = session.get(TaskQueueItem, task_id)
    if own is not None and own.status in _LIVE_TASK:
        return True
    film = storyboard_id or (
        str((own.payload or {}).get("storyboard_id") or "") if own is not None else ""
    )
    if not film:
        return False
    for task in session.scalars(
        select(TaskQueueItem).where(
            TaskQueueItem.task_type == FILM_CONTINUE_TASK, TaskQueueItem.status.in_(_LIVE_TASK)
        )
    ):
        if str((task.payload or {}).get("storyboard_id") or "") == film:
            return True
    return False


def _standing_answer(
    session: Session, step: Mapping[str, Any], sheet: Mapping[str, Any] | None, subject: str
) -> str | None:
    """His standing answer (APPROVED or REFUSED) about this step of the sheet as it is now,
    read the way `may_act` reads it (`_answered_approval`: the action, the film, the plan,
    the step and its cap) and never spent: a yes he gave a plan he chose his way back to is
    spent by the continuation, and the answer must say so."""
    from app.services import _answered_approval  # noqa: PLC0415

    plan_hash = (sheet or {}).get("sheet_hash")
    action = step.get("action")
    if not plan_hash or not action or not subject:
        return None
    context = {
        "plan_hash": plan_hash,
        "step": step["step"],
        "cap_credits": step.get("cap_credits"),
    }
    answered = _answered_approval(session, str(action), subject, context)
    return str(answered.result) if answered is not None else None


def _media_stage_tier() -> str:
    """The tier `continue_film` asks the mode for before it walks a film at all."""
    from app.runbook.stages import STAGE_ACTIONS  # noqa: PLC0415 - runbook imports media

    return STAGE_ACTIONS["media"][1]


def _rule_words(rule: str, over: float | None) -> str:
    from app.runbook.stages import paid_rule_words  # noqa: PLC0415 - runbook imports media

    return paid_rule_words(rule, over)


def _continuation_words(
    session: Session,
    step: dict[str, Any] | None,
    sheet: Mapping[str, Any] | None,
    subject: str = "",
) -> tuple[bool, str]:
    """(buys with no new question, the sentence) for a continuation queued in PRODUCTION,
    read in the order `continue_film` and `may_act` read (stop, safe mode, the mode's say on
    the media stage, T4, his rule and his standing answer, the daily budget, the mode)."""
    policy = session.get(OwnerPolicy, 1)
    if policy is None or policy.autonomy_stopped:
        return (
            False,
            "Nimic nu s-a cumpărat: autonomia este oprită, deci filmul nu continuă singur.",
        )
    if _safe_mode_open(session):
        return False, (
            "Nimic nu s-a cumpărat: studioul este în modul sigur, deci filmul nu continuă "
            "singur până nu închizi modul sigur."
        )
    rule, over = paid_media_policy(policy)
    mode = str(policy.autonomy_mode or "MANUAL")
    rule_words = _rule_words(rule, over)
    if _media_stage_tier() > MODE_ALLOWS.get(mode, "T1"):
        # `continue_film` asks the mode for the media stage first and skips the film.
        return False, (
            f"Nimic nu s-a cumpărat: în modul {autonomy_mode(mode)} filmul nu continuă "
            "singur; fiecare pas plătit îl apeși tu pe foaie."
        )
    if step is None:
        assemble = ((sheet or {}).get("steps") or {}).get("assemble") or {}
        if sheet is not None and assemble.get("blocked"):
            waiting = str(assemble.get("blocked_ro") or blocked_words(assemble["blocked"]))
            return False, (
                "Nimic nu s-a cumpărat: nu mai e niciun pas plătit de cumpărat, iar filmul "
                f"încă nu se poate asambla. {waiting}"
            )
        narration = assemble.get("narration") or {}
        if (
            sheet is not None
            and int(narration.get("characters") or 0) > 0
            and (float(narration.get("usd") or 0) > 0 or not narration.get("priced"))
        ):
            # The assembly voices the narration, a paid generation (ElevenLabs) the mode and
            # his threshold decide (`narration_gate`): never "no paid step left".
            price = (
                f"{decimal(float(narration['usd']))} USD"
                if narration.get("priced")
                else "preț necunoscut"
            )
            return True, (
                "Imaginile și cadrele sunt cumpărate: filmul trece singur la asamblare, unde "
                f"narațiunea ({price}, ElevenLabs) se poate plăti fără altă întrebare, cum "
                f"permit modul studioului ({autonomy_mode(mode)}) și pragul tău."
            )
        if sheet is not None:
            return False, (
                "Nu mai e niciun pas plătit de cumpărat: filmul trece singur la asamblare. "
                f"Regula ta: {rule_words}; modul studioului: {autonomy_mode(mode)}."
            )
        return False, (
            "Nimic nu s-a cumpărat încă: filmul continuă singur cu pasul următor. "
            f"Regula ta: {rule_words}; modul studioului: {autonomy_mode(mode)}."
        )
    words = str(step["words"])
    tier = str(step.get("tier") or "T3")
    cap = step.get("cap_usd")
    cap_usd = float(cap) if isinstance(cap, int | float) and not isinstance(cap, bool) else None
    if tier == "T4":
        return False, f"Nimic nu s-a cumpărat: {words} rămâne doar al tău de apăsat."
    asks_owner = rule == "EVERY_PAID_STEP" or (
        rule == "OVER_USD" and (cap_usd is None or over is None or cap_usd > over)
    )
    allowed = tier <= MODE_ALLOWS.get(mode, "T1")
    if asks_owner or (not allowed and mode == "SUPERVISED" and tier == "T3"):
        # `may_act` reads his standing answer about this plan here: a yes is spent and buys.
        standing = _standing_answer(session, step, sheet, subject)
        price = f" (plafon {decimal(cap_usd)} USD)" if cap_usd is not None else ""
        if standing == "APPROVED":
            return True, (
                f"Filmul continuă singur: {words} se cumpără acum cu aprobarea pe care ai "
                f"dat-o deja pentru foaia aceasta{price}, dacă soldul Runway și bugetul zilei "
                f"ajung. Regula ta: {rule_words}."
            )
        if standing == "REFUSED":
            return False, (
                f"Nimic nu s-a cumpărat: ai refuzat deja {words} pentru foaia aceasta, deci "
                "nu se cumpără."
            )
    if asks_owner:
        return False, (
            f"Nimic nu s-a cumpărat: {words} așteaptă aprobarea ta, pe foaia nouă (o aprobare "
            f"dată foii vechi nu mai cumpără nimic). Regula ta: {rule_words}."
        )
    if allowed and not has_active_daily_budget(session):
        return False, (
            f"Nimic nu s-a cumpărat: regula ta ar lăsa studioul să cumpere {words} singur, dar "
            "nu există niciun buget zilnic activ, iar în producție nu se cumpără nimic "
            f"neîntrebat fără o limită zilnică. Setează bugetul în {BUDGET_PLACE_WORDS}."
        )
    if allowed:
        price = f" (plafon {decimal(cap_usd)} USD)" if cap_usd is not None else ""
        return True, (
            f"Filmul continuă singur: {words} se cumpără acum, fără altă întrebare{price}, "
            f"dacă soldul Runway și bugetul zilei ajung. Regula ta: {rule_words}; modul "
            f"studioului: {autonomy_mode(mode)}."
        )
    if mode == "SUPERVISED" and tier == "T3":
        return False, (
            f"Nimic nu s-a cumpărat: în modul {autonomy_mode(mode)}, {words} așteaptă aprobarea ta."
        )
    return False, (
        f"Nimic nu s-a cumpărat: în modul {autonomy_mode(mode)} studioul nu cumpără singur "
        f"{words}; îl apeși tu pe foaie."
    )


def decision_outcome(
    engine: Engine,
    *,
    kind: str,
    scene_number: int,
    decision: str,
    continue_task_id: str | None,
    sheet: Mapping[str, Any] | None = None,
    storyboard_id: str | None = None,
) -> dict[str, Any]:
    """What his look at a take did, in one answer: ``message_ro`` (the sentence the page shows
    in the scene he pressed), ``continues`` (a FILM_CONTINUE was queued), ``buys_unasked``
    (the continuation will buy its next step without asking him) and ``next_step``.

    ``sheet`` is the sheet as it is after the decision (read with no live call); without it
    the step is not named."""
    first = _CHOSEN.get((kind, decision), "Decizia ta este înregistrată.").format(n=scene_number)
    step = _next_step(sheet)
    if decision != "APPROVED":
        return {
            "message_ro": f"{first} Nimic nu s-a cumpărat și nimic nu pornește din această "
            "respingere.",
            "continues": False,
            "buys_unasked": False,
            "next_step": None,
        }
    with Session(engine) as session:
        policy = session.get(OwnerPolicy, 1)
        environment = str(getattr(policy, "environment", None) or "TEST")
        if continue_task_id is None:
            if environment != "PRODUCTION":
                said = (
                    f"Nimic nu s-a cumpărat: în {environment_words(environment)} filmul nu "
                    "continuă singur; un pas plătit se cumpără doar când îl apeși pe foaie."
                )
            else:
                said = "Nimic nu s-a cumpărat și nimic nu se cumpără până nu apeși un pas plătit."
            return {
                "message_ro": f"{first} {said}",
                "continues": False,
                "buys_unasked": False,
                "next_step": step["step"] if step else None,
            }
        if not _continuation_live(session, continue_task_id, storyboard_id):
            return {
                "message_ro": f"{first} Nimic nu s-a cumpărat și nimic nu pornește acum: "
                "alegerea aceasta a mai fost făcută o dată, iar continuarea filmului de atunci "
                "s-a încheiat. Pasul următor îl poți apăsa tu pe foaie.",
                "continues": False,
                "buys_unasked": False,
                "next_step": step["step"] if step else None,
            }
        buys, said = _continuation_words(session, step, sheet, storyboard_id or "")
    return {
        "message_ro": f"{first} {said}",
        "continues": True,
        "buys_unasked": buys,
        "next_step": step["step"] if step else None,
    }
