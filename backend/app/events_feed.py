"""The record as a person reads it: a sentence for each event, who did it and which film.

The Owner, 2026-10-11, on the live register («Registru viu / Ce se întâmplă acum») showing
rows like «scene take recorded ×2 — storyboard_id: f06808c9-… · scene_number: 8 · kind:
still» and «Kael (Video Editor) sarcină reușită — still qc · kimi-k3»: «Trebuie să fie mai
pentru oameni, mai puțin cod … să îmi redea pe înțelesul meu … poate punem și imaginea
celui care lucrează … agenții să răspundă cu o bulă când fac ceva și comportamentul lor să
fie ghidat de backend.»

So the page of the record (`services.read_events`) carries, beside each event it already
carried, what the studio can say of it in words: ``words_ro`` (one sentence for the register:
the film by its title, never by its id; the take by its kind; who did what), ``actor`` (the
employee the event belongs to — by the payload's agent id, or by the role the event's kind
implies: a still is the Video Editor's, a decision the Director's — with their name, role and
the role's words), ``film_title`` (the storyboard's title when the event is about one) and
``bubble_ro`` (a short line the office may show over that employee's head, only for events
worth a word). Nothing here is simulated: every sentence is read from the event's payload
and the rows it names.

2026-10-12, the Director's repair loop on RunPod: the register showed «run paused — endpoint_id:
u07hiq… · items: 2 · seconds: 1.33», «spend reserved — purpose: sheet:scene_redo · usd: 0.84»,
«qc paid redo — scene_index: 4 · of_asset: c00866fc-…». Every kind that loop writes has its
sentence now, and a kind nobody has words for yet is still said by its name alone — never an
id, a hash or an endpoint (`_fallback`). The same words travel with the live socket and the
page's first snapshot (`workflows.publisher`, `services.snapshot`), not only with the paged
record: the page keeps the first copy of an event it receives, so the live one must carry them.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.models import Agent, Role
from app.media.models import Storyboard
from app.wording import count, decimal, provider_name

#: Each role as the register names it beside the employee's name.
ROLE_WORDS_RO: dict[str, str] = {
    "Director": "Directoarea",
    "LeadResearcher": "Cercetare",
    "FactChecker": "Verificarea faptelor",
    "ScriptWriter": "Scenarist",
    "VoiceArtist": "Voce",
    "VideoEditor": "Video Editor",
    "Publisher": "Distribuție",
    "Accountant": "Contabilitate",
}

#: Which employee an event belongs to when its payload names nobody: by the event's kind.
#: A RunPod session opened for a step, and a round sent to it, are the Video Editor's work
#: (the stills and the motion are his); the GPU going off is the studio's own housekeeping.
_ROLE_BY_PREFIX: tuple[tuple[str, str], ...] = (
    ("media.director_", "Director"),
    ("media.scene_take", "VideoEditor"),
    ("media.still", "VideoEditor"),
    ("media.motion", "VideoEditor"),
    ("media.shot_prompts", "VideoEditor"),
    ("media.sheet_repair_plan", "VideoEditor"),
    ("media.sheet_repair_finished", "VideoEditor"),
    ("media.prompts_", "VideoEditor"),
    ("media.scene_redone", "VideoEditor"),
    ("media.qc_", "VideoEditor"),
    ("media.clip_qc", "VideoEditor"),
    ("media.video_rendered", "VideoEditor"),
    ("media.render_failed", "VideoEditor"),
    ("media.sound_plan", "VoiceArtist"),
    ("media.narration", "VoiceArtist"),
    ("runbook.qc_paid_redo", "VideoEditor"),
    ("runbook.qc_repair", "Director"),
    ("runpod.gpu_session_opened", "VideoEditor"),
    ("runpod.run_paused", "VideoEditor"),
    ("story.episode_reviewed", "Director"),
    ("story.episode_approved", "Director"),
    ("editorial.judged", "Director"),
    ("story.episode_rejected", "Director"),
    ("story.", "ScriptWriter"),
    ("factual.script", "ScriptWriter"),
    ("factual.claim_verified", "FactChecker"),
    ("factual.", "LeadResearcher"),
    ("research.", "LeadResearcher"),
    ("trends.", "LeadResearcher"),
    ("publishing.", "Publisher"),
    ("economy.", "Accountant"),
    ("director.", "Director"),
)

#: A take's kind in a sentence, and the pronoun that takes it up again.
_KIND_RO: dict[str, tuple[str, str]] = {
    "still": ("imaginea", "o"),
    "test_shot": ("cadrul de probă", "îl"),
    "motion": ("clipul", "îl"),
    "narration": ("narațiunea", "o"),
}
#: The same kinds in the genitive («refacerea imaginii scenei 3»).
_KIND_GEN_RO: dict[str, str] = {
    "still": "imaginii",
    "test_shot": "cadrului de probă",
    "motion": "clipului",
    "narration": "narațiunii",
}
#: A scene's layer the Director's brief names, and its genitive.
_LAYER_RO = {"still": "imaginea", "motion": "mișcarea"}
_LAYER_GEN_RO = {"still": "imaginii", "motion": "mișcării"}
#: A GPU session's purpose, what the editor waits for from it, and a step, in words.
_PURPOSE_RO = {"image": "imagini", "video": "clipuri"}
_PURPOSE_WAIT_RO = {"image": "imaginile", "video": "clipurile"}
_STEP_RO = {
    "stills": "imagini",
    "test_shot": "cadrul de probă",
    "motion": "mișcare",
    "scene_redo": "refacerea unei scene",
    "assemble": "asamblarea",
    "render": "randarea",
}
#: Where a film's walk ended, in words.
_WALK_RO = {
    "COMPLETED": "a mers până la capăt",
    "BLOCKED": "s-a oprit",
    "SKIPPED": "n-a putut porni",
    "WAITING": "așteaptă",
    "INTERRUPTED": "a fost întreruptă",
}
#: Where the day left a film (`runbook.film_state`), in words.
_FILM_STATE_RO = {
    **_WALK_RO,
    "HELD": "e ținut pe loc",
    "USE_THE_SHEET": "se continuă de pe foaia de filmare",
    "BOUGHT": "a cumpărat pasul zilei",
    "REFUSED": "a fost refuzat",
    "WAITING_OWNER": "așteaptă decizia ta",
}
#: A model's vendor, as the Owner knows it.
_VENDOR_RO = {"Qwen-Image-2512": "RunPod", "Qwen-Image-Edit-2511": "RunPod", "LTX-2.5": "RunPod"}
#: Task types as the register names them (the page's own table has the same words).
_TASK_RO: dict[str, str] = {
    "still_qc": "verificarea unei imagini",
    "clip_qc": "verificarea unui clip",
    "picture_qc": "controlul imaginii",
    "shot_prompts": "descrierea cadrelor",
    "director_qc_review": "decizia asupra filmului picat",
    "director_scene_brief": "brief-ul de rescriere a unei scene",
    "scene_prompt_rewrite": "rescrierea promptului unei scene",
    "sheet_repair_assignment": "repartizarea remedierii foii",
    "sound_design": "planul de sunet",
    "write_episode": "episodul serialului",
    "episode_review": "citirea episodului",
    "story_review": "citirea scenariului",
    "editorial_review": "revizuirea editorială",
    "editorial_judgement": "judecata editorială",
    "gather_sources": "căutarea surselor",
    "extract_claims": "extragerea afirmațiilor",
    "verify_claim": "verificarea faptelor",
    "propose_topics": "ideile de subiect",
    "choose_topic": "alegerea subiectului",
    "write_script": "scenariul",
    "review_narration": "revizuirea narațiunii",
    "visual_bible": "ghidul vizual",
    "prepare_publication": "pregătirea publicării",
    "director_review": "revizuirea zilei",
    "reconcile_day": "închiderea zilei",
    "answer_mail": "răspunsul la corespondență",
    "direct_company": "conducerea companiei",
    "research_models": "cercetarea modelelor",
    "owner_chat": "discuția cu Proprietarul",
    "review_failed_render": "diagnoza randării",
}
_RUN_STATUS_RO = {"SUCCEEDED": "reușită", "FAILED": "eșuată", "REFUSED": "refuzată"}
_DECISION_RO = {
    "ACCEPT": "filmul se publică așa cum este",
    "REPAIR": "se refac doar scenele pe care le-a numit",
    "CLOSE": "filmul se închide",
}
_OUTCOME_RO = {
    "ACCEPTED": "acceptat",
    "ACCEPT_REFUSED": "acceptarea refuzată (nu era a ei de trecut cu vederea)",
    "REPAIRED": "refăcut, din nou la control",
    "ASKED": "refacerea așteaptă răspunsul tău",
    "BOUGHT_WAITING": "s-a cumpărat, așteaptă aprobarea preluării",
    "NOTHING_DONE": "nimic din lista ei nu se putea face",
    "CLOSED": "închis",
}
#: Why the GPU went off (`gpu_session.OFF_REASONS` and the guard's own).
_GPU_OFF_RO = {
    "STEP_DONE": "pasul s-a încheiat",
    "SHUTDOWN": "studioul s-a oprit",
    "LAUNCHER_STOP": "oprit de lansator",
    "OWNER_OFF": "la cererea ta",
    "BOOT": "o sesiune rămasă de la pornirea studioului",
    "TICK": "la verificarea periodică",
    "LOW_BALANCE": "soldul e prea mic",
}
#: Why a scene's prompt was rewritten (`assembler` and `scene_rewrite` reasons).
_REWRITE_RO = {
    "redo": "pentru refacere",
    "director": "la decizia Directoarei",
    "director_brief": "la brief-ul Directoarei",
}
#: Why a retired take was retired, beside the Director's decision.
_RETIRED_CODE_RO = {"REDO.STILL_REPLACED": ", pentru că imaginea lui se înlocuiește"}
#: Why a retired take was given back.
_RESTORED_RO = {"redo_delivered_nothing": "refacerea n-a adus nimic"}
#: A scheduled job's name (`workflow.job_fired`), as the page's routine row says it.
_JOB_RO = {"WATCHDOG": "supraveghetorul", "DAILY_RUN": "rularea zilei"}
#: The family of a kind nobody has words for, so its name is at least placed.
_FAMILY_RO = {
    "media": "Producție",
    "runpod": "RunPod",
    "economy": "Bani",
    "runbook": "Rularea zilei",
    "workflow": "Rutina studioului",
    "agent": "Angajați",
    "publishing": "Distribuție",
    "story": "Serialul",
    "factual": "Cercetare",
    "research": "Cercetare",
    "trends": "Tendințe",
    "office": "Birou",
    "governance": "Guvernanță",
    "owner": "Proprietarul",
    "settings": "Setări",
    "provider": "Furnizor",
    "youtube": "YouTube",
    "channel": "Canal",
    "autonomy": "Autonomie",
    "studio": "Studioul",
    "editorial": "Redacția",
    "director": "Directoarea",
}
#: The cause the still gate wrote in its parentheses («… nu trece (cauza). Decide …»).
_CAUSE = re.compile(r"\((.+)\)\.?\s*(?:Decide\b|$)")
#: How long a word the office shows may be, and a sentence of the register.
BUBBLE_MAX = 64
WORDS_MAX = 220


def _payload(event: Mapping[str, Any]) -> dict[str, Any]:
    raw = event.get("payload")
    return dict(raw) if isinstance(raw, Mapping) else {}


class _Actors:
    """The studio's employees, read once per page: by id and by role."""

    def __init__(self, session: Session) -> None:
        rows = session.execute(select(Agent, Role).join(Role, Agent.role_id == Role.id)).all()
        self.by_id: dict[str, dict[str, Any]] = {}
        self.by_role: dict[str, dict[str, Any]] = {}
        for agent, role in rows:
            view = {
                "agent_id": str(agent.id),
                "name": str(agent.display_name or role.name),
                "role": str(role.name),
                "role_ro": ROLE_WORDS_RO.get(str(role.name), str(role.name)),
            }
            self.by_id[str(agent.id)] = view
            # The first employee of a role is the one the register names for it.
            self.by_role.setdefault(str(role.name), view)

    def for_event(self, event: Mapping[str, Any]) -> dict[str, Any] | None:
        payload = _payload(event)
        kind = str(event.get("event_type") or "")
        for key in ("agent_id", "from_agent_id"):
            found = self.by_id.get(str(payload.get(key) or ""))
            if found:
                return found
        if kind.startswith("agent.") and str(event.get("aggregate_id") or "") in self.by_id:
            return self.by_id[str(event["aggregate_id"])]
        decided_by = str(payload.get("decided_by") or "").lower()
        if payload.get("director_repair") or decided_by == "director":
            return self.by_role.get("Director")
        for prefix, role in _ROLE_BY_PREFIX:
            if kind.startswith(prefix):
                return self.by_role.get(role)
        return None


def _reference_parts(reference: Any) -> tuple[str | None, str | None]:
    """The film and the step a money reference names: «foaie:<film>:<step>:<plan>» (a sheet's
    step) or «redo:<film>:<kind>:<scene>:<correlation>» (one scene's paid redo)."""
    parts = str(reference or "").split(":")
    if len(parts) < 3 or not parts[1]:
        return None, None
    if parts[0] == "foaie":
        return parts[1], _STEP_RO.get(parts[2])
    if parts[0] == "redo":
        what = _KIND_GEN_RO.get(parts[2], "înregistrării")
        scene = parts[3] if len(parts) > 3 and parts[3] else ""
        return parts[1], f"refacerea {what}" + (f" scenei {scene}" if scene else "")
    return None, None


def _storyboard_of(event: Mapping[str, Any]) -> str | None:
    payload = _payload(event)
    found = payload.get("storyboard_id")
    if not found and str(event.get("aggregate_type") or "") == "storyboard":
        found = event.get("aggregate_id")
    if not found:
        found, _what = _reference_parts(payload.get("reference"))
    return str(found) if found else None


def _titles(session: Session, events: list[Mapping[str, Any]]) -> dict[str, str]:
    """The titles of the storyboards the page's events name, one query."""
    ids = {board for board in (_storyboard_of(event) for event in events) if board}
    if not ids:
        return {}
    rows = session.scalars(select(Storyboard).where(Storyboard.id.in_(sorted(ids))))
    return {str(row.id): _bare_title(row.title) for row in rows}


def _bare_title(title: Any) -> str:
    """A storyboard's title as the register says it: without the «Storyboard:» prefix the
    media stage writes on it (2026-10-12: every row read «din «Storyboard: The Zero …»»)."""
    said = " ".join(str(title or "").split())
    if said.lower().startswith("storyboard:"):
        said = said.split(":", 1)[1].strip()
    return said


def _short(text: Any, limit: int) -> str:
    said = " ".join(str(text or "").split())
    if len(said) <= limit:
        return said
    return said[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _end(said: str) -> str:
    """A sentence's full stop, unless it already trails off in a shortened quotation."""
    return said if said.endswith("…") else said + "."


def _reason(payload: Mapping[str, Any], limit: int = 140) -> str:
    text = str(payload.get("reason") or payload.get("detail") or "")
    # The gate's own words after the colon ("Scena 3: după 2 refaceri … (…)") read better
    # without the scene prefix the sentence already says.
    if text.startswith("Scen") and ": " in text:
        text = text.split(": ", 1)[1]
    return _short(text.rstrip("."), limit)


def _cause(payload: Mapping[str, Any], limit: int = 120) -> str:
    """What the still gate found, from the parentheses of its line, else its line."""
    text = str(payload.get("reason") or "")
    found = _CAUSE.search(text)
    return _short(found.group(1) if found else _reason(payload), limit)


def _codes(payload: Mapping[str, Any]) -> str:
    seen: list[str] = []
    for item in payload.get("remaining") or []:
        if isinstance(item, Mapping):
            code = str(item.get("code") or "")
            scene = item.get("scene_index")
            label = f"{code} (scena {scene})" if scene else code
            if label and label not in seen:
                seen.append(label)
    return ", ".join(seen[:4]) + ("…" if len(seen) > 4 else "")


def _film(title: str | None) -> str:
    return f" din «{title}»" if title else ""


def _feminine(take: str) -> str:
    return "ă" if take.endswith("a") else ""


def _number(value: Any, places: int = 0) -> str | None:
    """A payload number as Romanian writes it; None when the payload has none."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return decimal(float(value), places)


def _seconds(value: Any) -> str:
    said = _number(value)
    return f"{said} s" if said is not None else "câteva secunde"


def _purpose_ro(purpose: Any) -> str:
    """A reservation's purpose («sheet:scene_redo», «image») as the step it pays for."""
    text = str(purpose or "").strip()
    if text.startswith("sheet:"):
        return _STEP_RO.get(text.split(":", 1)[1], text.split(":", 1)[1].replace("_", " "))
    return {**_PURPOSE_RO, "film": "film"}.get(text, text or "un pas al filmului")


def _vendor(payload: Mapping[str, Any]) -> tuple[str, str]:
    """The vendor a take went to, as a place («la RunPod») and as a subject («RunPod»)."""
    vendor = _VENDOR_RO.get(str(payload.get("model_id") or ""), "")
    return (vendor or "furnizor", vendor or "Furnizorul")


def _listed(items: list[str], limit: int = 3) -> str:
    return ", ".join(items[:limit]) + ("…" if len(items) > limit else "")


def _fallback(kind: str, scene: Any, title: str | None) -> str:
    """A kind nobody has words for yet: its name as words, placed by its film and scene or by
    its family — never a field, an id, a hash or an endpoint."""
    family, _, name = kind.partition(".")
    said = name.replace("_", " ").strip() or kind
    if title:
        return f"«{title}», scena {scene}: {said}." if scene else f"«{title}»: {said}."
    head = _FAMILY_RO.get(family)
    placed = f" (scena {scene})" if scene else ""
    return f"{head}: {said}{placed}." if head else f"{said.capitalize()}{placed}."


#: The editorial judgement's five criteria, short, for the register (the letter has the long
#: names, `editorial_judgement.CRITERIA_RO`).
_CRITERIA_RO: dict[str, str] = {
    "hook": "cârligul",
    "clarity": "claritatea",
    "moment": "momentul memorabil",
    "punchline": "poanta",
    "follow": "motivul de a reveni",
}
#: What she judged, in the nominative and the genitive.
_JUDGED_KIND_RO: dict[str, tuple[str, str]] = {
    "factual_short": ("scenariul short-ului", "scenariului short-ului"),
    "serial_episode": ("episodul serialului", "episodului serialului"),
}
_JUDGED_STOP_RO: dict[str, str] = {
    "rounds_spent": "după toate rundele",
    "writer_silent": "scenaristul n-a mai răspuns",
    "judge_silent": "nota n-a mai venit",
}


def _judged_words(
    payload: Mapping[str, Any], name: str, title: str | None
) -> tuple[str | None, str | None]:
    """The Director's editorial note on one version of a script or episode (`editorial.judged`,
    2026-10-12): the score out of 50, what was weakest, whether it ships or goes back with a
    brief. The version's own title is on the event; the film's, when known, wins."""
    what, what_of = _JUDGED_KIND_RO.get(
        str(payload.get("kind") or ""), ("scenariul", "scenariului")
    )
    shown = title or str(payload.get("title") or "")
    if shown:
        what += f" «{shown}»"
        what_of += f" «{shown}»"
    if payload.get("judged") is False or payload.get("total") is None:
        return f"{name} n-a putut nota versiunea {payload.get('round')} a {what_of}.", None
    total = f"{payload.get('total')}/50"
    version = payload.get("round")
    weak = " și ".join(
        _CRITERIA_RO.get(str(key), str(key)) for key in list(payload.get("weakest") or [])[:2]
    )
    if payload.get("shipped"):
        if payload.get("passed"):
            said = f"{name} a notat {what}: {total} la versiunea {version}; trece la filmare."
            return said, f"Trece: {total}."
        how = _JUDGED_STOP_RO.get(str(payload.get("stopped") or ""), "")
        said = f"{name} a notat {what}: {total} la versiunea {version}; pleacă cea mai bună"
        said += f" ({how})" if how else ""
        said += f", cu {weak} încă slabe" if weak else ""
        return said + ".", f"Pleacă cea mai bună: {total}."
    said = f"{name} a notat versiunea {version} a {what_of}: {total}"
    said += f"; cele mai slabe: {weak}" if weak else ""
    return said + "; brief la scenarist.", f"Versiunea {version}: {total}, brief la scenarist."


def _take_words(
    payload: Mapping[str, Any], name: str, where: str, film: str
) -> tuple[str | None, str | None]:
    """One take's status as the editor would tell it (`media.scene_take_recorded`)."""
    take, pronoun = _KIND_RO.get(str(payload.get("kind") or ""), ("înregistrarea", "o"))
    status = str(payload.get("status") or "")
    at_vendor, vendor = _vendor(payload)
    if status == "QUOTED":
        quoted = _number(payload.get("credits_quoted"))
        cost = f" ({quoted} credite)" if quoted and quoted != "0" else ""
        return f"{name} a pregătit {take}{where}{film} pentru {vendor}{cost}.", None
    if status == "SUBMITTED":
        return (
            f"{name} a trimis la {at_vendor} {take}{where}{film}.",
            f"Am trimis {take}{where} la {at_vendor}.",
        )
    if status == "PAID":
        return (
            f"A sosit {take}{where}{film}; {name} {pronoun} verifică.",
            f"A sosit {take}{where}, {pronoun} verific.",
        )
    if status == "APPROVED":
        return f"{take.capitalize()}{where}{film} a trecut poarta.", None
    if status == "REJECTED":
        why = _reason(payload)
        said = f"{take.capitalize()}{where}{film} a fost respins{_feminine(take)}"
        return said + (f": {why}" if why else "") + ".", None
    if status == "REFUSED":
        why = _short(str(payload.get("failure_detail") or "").rstrip("."), 100)
        said = f"{vendor} a refuzat {take}{where}{film}"
        return _end(said + (f": {why}" if why else "")), None
    if status == "LOST":
        return (
            f"{take.capitalize()}{where}{film} s-a pierdut: {vendor} a primit lucrarea, dar "
            "rezultatul a expirat înainte să fie preluat.",
            None,
        )
    if status:
        return f"{take.capitalize()}{where}{film}: {status.lower().replace('_', ' ')}.", None
    return None, None


def _brief_words(payload: Mapping[str, Any], name: str, film: str, editor: str) -> tuple[str, str]:
    """The Director's brief for one scene (`media.director_scene_brief`): which layer she
    opened, whether the editor's rewrite landed, or came back with the same words."""
    scene = payload.get("scene_index") or payload.get("scene_number")
    layer = str(payload.get("layer") or "")
    asked = str(payload.get("asked_layer") or "")
    layer_ro = _LAYER_RO.get(layer, "")
    said = f"{name} a dat brief de rescriere pentru "
    said += f"{layer_ro} scenei {scene}{film}" if layer_ro else f"scena {scene}{film}"
    if asked and asked != layer and asked in _LAYER_RO:
        said += f" (cerută: {_LAYER_RO[asked]})"
    if payload.get("same_prompt"):
        said += "; rescrierea a dat același prompt, nimic nou de cumpărat"
    elif payload.get("rewritten"):
        said += f"; {editor} a rescris-o"
    elif payload.get("rewritten") is False:
        why = _short(str(payload.get("reason") or "").rstrip("."), 90)
        said += "; rescrierea n-a aterizat încă" + (f": {why}" if why else "")
    bubble = f"Brief pentru scena {scene}" + (f": {layer_ro}." if layer_ro else ".")
    return _end(said), bubble


def _rewrite_words(
    payload: Mapping[str, Any], scene: Any, film: str, named: str
) -> tuple[str, str | None]:
    """A scene's prompt said again (`media.prompts_rewritten`): by the Director's brief, for a
    redo, or — a serial scene — recomposed with today's words or made again on the same ones."""
    reason = str(payload.get("reason") or "")
    layer = str(payload.get("layer") or "")
    if reason == "serial_recompose":
        return (
            f"Scena {scene} a serialului {named} a fost compusă din nou cu cuvintele de azi; "
            "imaginea se reface.",
            f"Scena {scene} e compusă din nou.",
        )
    if reason == "serial_reroll":
        what = "cadrul" if layer == "motion" else "imaginea"
        return (
            f"Scena {scene} a serialului {named}: {what} se reface pe aceleași cuvinte, cu altă "
            "sămânță.",
            f"Scena {scene}: {what} se reface.",
        )
    what_of = f" {_LAYER_GEN_RO[layer]}" if layer in _LAYER_GEN_RO else ""
    why = _REWRITE_RO.get(reason, "")
    said = f"Promptul{what_of} scenei {scene}{film} a fost rescris" + (f" {why}" if why else "")
    return said + ".", f"Promptul scenei {scene} e rescris."


def _repair_words(payload: Mapping[str, Any], name: str, named: str) -> tuple[str, str | None]:
    """One repair of a failed film as the Director applied it (`runbook.qc_repair`): what was
    bought, what still waits, and how the remade film fared at its new control."""
    bought: list[str] = []
    for item in payload.get("bought") or []:
        if isinstance(item, Mapping):
            layer = _LAYER_RO.get(str(item.get("redo") or ""), "înregistrarea")
            bought.append(f"{layer} scenei {item.get('scene_index')}")
    said = f"{name} a aplicat refacerea filmului {named}: "
    if bought:
        said += count(len(bought), "refacere cumpărată", "refaceri cumpărate")
        said += f" ({_listed(bought)})"
    else:
        said += "nimic de cumpărat"
    asked = len(payload.get("asked") or [])
    if asked:
        said += f"; {count(asked, 'întrebare pentru tine', 'întrebări pentru tine')}"
    waiting = [
        item.get("scene_index")
        for item in payload.get("waiting") or []
        if isinstance(item, Mapping) and item.get("scene_index") is not None
    ]
    if waiting:
        scenes = ", ".join(str(scene) for scene in waiting[:3])
        said += f"; {'scena' if len(waiting) == 1 else 'scenele'} {scenes} încă așteaptă"
    verdict = str(payload.get("requalified") or "")
    if verdict == "FAILED":
        said += "; filmul refăcut a picat din nou la control"
    elif verdict == "PASSED":
        said += "; filmul refăcut a trecut controlul"
    return said + ".", "Am aplicat refacerea filmului."


def _words(
    event: Mapping[str, Any],
    actor: Mapping[str, Any] | None,
    title: str | None,
    staff: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[str | None, str | None]:
    """(words_ro, bubble_ro) for one event; a kind nobody has words for is said by its name
    (`_fallback`), never by its fields. ``staff`` is the register's employee per role, for a
    sentence that names a second employee (the Director's brief names the editor)."""
    kind = str(event.get("event_type") or "")
    payload = _payload(event)
    name = str(actor["name"]) if actor else "Studioul"
    scene = payload.get("scene_number") or payload.get("scene_index")
    where = f" scenei {scene}" if scene else ""
    film = _film(title)
    named = f"«{title or '…'}»"
    editor = str((staff or {}).get("VideoEditor", {}).get("name") or "Video Editorul")

    if kind == "media.scene_take_recorded":
        return _take_words(payload, name, where, film)
    if kind == "media.still_needs_owner":
        tries = int(payload.get("rerolls") or 0)
        cause = _cause(payload)
        rounds = count(tries, "refacere", "refaceri")
        said = f"Scena {scene}{film}: după {rounds} imaginea tot nu trece"
        return (
            said + (f" ({cause})" if cause else "") + "; Directoarea rescrie scena.",
            f"Scena {scene} tot nu trece; o rescriem.",
        )
    if kind == "media.stills_step_finished":
        scenes = [s for s in payload.get("scenes") or [] if isinstance(s, Mapping)]
        good = sum(1 for s in scenes if s.get("status") == "APPROVED")
        held = sum(1 for s in scenes if s.get("status") in ("NEEDS_OWNER", "HELD", "REFUSED"))
        approved = count(good, "scenă cu imagine aprobată", "scene cu imagine aprobată")
        redo = f", {count(held, 'scenă de refăcut', 'scene de refăcut')}" if held else ""
        return (
            f"Pasul de imagini pentru {named} s-a încheiat: {approved}{redo}.",
            f"Imagini: {good} bune" + (f", {held} de refăcut" if held else "") + ".",
        )
    if kind == "media.motion_step_finished":
        step = _STEP_RO.get(str(payload.get("step") or ""), "mișcare")
        scenes = [s for s in payload.get("scenes") or [] if isinstance(s, Mapping)]
        reused = sum(1 for s in scenes if s.get("reused"))
        bought = sum(
            1
            for s in scenes
            if not s.get("reused")
            and (s.get("status") in ("BOUGHT", "APPROVED", "ACCEPTED") or s.get("clip_qc"))
        )
        reasons = {str(s.get("reason") or "") for s in scenes if s.get("status") == "NOT_BOUGHT"}
        why = _short(next(iter(sorted(reasons)), ""), 100)
        bought_ro = count(bought, "cadru cumpărat", "cadre cumpărate")
        said = f"Pasul «{step}» pentru {named} s-a încheiat: {bought_ro}"
        said += f", {reused} refolosite" if reused else ""
        return said + (f"; {why}" if why else "") + ".", None
    if kind == "runbook.film_continued":
        status = str(payload.get("status") or "")
        walk = _WALK_RO.get(status, status.lower())
        why = _short(str(payload.get("reason") or "").replace("Oprit: ", ""), 150).rstrip(".")
        return f"Filmul {named} {walk}" + (f": {why}" if why else "") + ".", None
    if kind == "runbook.film_state":
        status = str(payload.get("status") or "")
        state = _FILM_STATE_RO.get(status, status.lower().replace("_", " "))
        step = _STEP_RO.get(str(payload.get("step") or ""), "")
        why = _short(str(payload.get("reason") or "").rstrip("."), 120)
        said = f"Filmul {named} azi {state}" + (f" la pasul «{step}»" if step else "")
        return said + (f": {why}" if why else "") + ".", None
    if kind == "media.sheet_repair_plan_saved":
        return f"{name} a rescris prompturile foii {named}.", "Am rescris prompturile foii."
    if kind == "media.sheet_repair_finished":
        status = str(payload.get("status") or "")
        if status == "RESOLVED":
            return f"Foaia {named} e curată: filmarea merge mai departe.", "Foaia e curată!"
        codes = _codes(payload)
        tail = f": {codes}" if codes else ""
        if status == "WAITING_OWNER":
            return f"Foaia {named} așteaptă o decizie a ta{tail}.", None
        return f"Foaia {named} mai are blocaje{tail}.", None
    if kind == "media.shot_prompts_written":
        return f"{name} a scris planul de cadre pentru {named}.", "Planul de cadre e scris."
    if kind == "media.prompts_rewritten":
        return _rewrite_words(payload, scene, film, named)
    if kind == "media.scene_redone":
        take, _pronoun = _KIND_RO.get(str(payload.get("kind") or ""), ("înregistrarea", "o"))
        credits = _number(payload.get("credits"))
        spent = f" ({credits} credite)" if credits and credits != "0" else ""
        return (
            f"Scena {scene}{film}: {take} a fost refăcut{_feminine(take)}{spent}.",
            f"Scena {scene} refăcută.",
        )
    if kind == "media.scene_take_retired":
        take, _pronoun = _KIND_RO.get(str(payload.get("kind") or ""), ("înregistrarea", "o"))
        by = ""
        if payload.get("director_repair"):
            by = " la decizia Directoarei"
        elif payload.get("owner_press"):
            by = " la cererea ta"
        because = _RETIRED_CODE_RO.get(str(payload.get("failure_code") or ""), "")
        said = f"{take.capitalize()}{where}{film} a fost retras{_feminine(take)}{by}{because}"
        return said + "; nu se mai folosește.", None
    if kind == "media.scene_take_restored":
        take, _pronoun = _KIND_RO.get(str(payload.get("kind") or ""), ("înregistrarea", "o"))
        why = _RESTORED_RO.get(str(payload.get("cause") or ""), "refacerea n-a livrat nimic")
        return f"{take.capitalize()}{where}{film} a fost pus{_feminine(take)} la loc: {why}.", None
    if kind == "media.director_qc_decision":
        decision = str(payload.get("decision") or "")
        verdict = _DECISION_RO.get(decision, decision.lower())
        outcome = _OUTCOME_RO.get(str(payload.get("outcome") or ""), "")
        said = f"{name} a decis filmul {named}: {verdict}"
        return said + (f" — {outcome}" if outcome else "") + ".", f"Am decis: {verdict}."
    if kind == "media.director_qc_waiting":
        return f"{name} n-a putut decide încă filmul {named}: {_reason(payload, 150)}.", None
    if kind == "editorial.judged":
        return _judged_words(payload, name, title)
    if kind == "media.director_scene_brief":
        return _brief_words(payload, name, film, editor)
    if kind == "media.clip_qc_checked":
        attempt = payload.get("attempt")
        again = f" la încercarea {attempt}" if isinstance(attempt, int) and attempt > 1 else ""
        if payload.get("passed"):
            return (
                f"Clipul{where}{film} a trecut controlul{again}.",
                f"Clipul{where} a trecut ✓",
            )
        blocks = [str(b) for b in payload.get("blocks_ro") or [] if b]
        why = _short(blocks[0].rstrip("."), 120) if blocks else ""
        said = f"Clipul{where}{film} nu a trecut controlul{again}"
        return _end(said + (f": {why}" if why else "")), f"Clipul{where} nu trece."
    if kind == "media.qc_evaluated":
        status = str(payload.get("status") or "")
        score = _number(payload.get("score"), 2)
        scored = f" (scor {score})" if score is not None else ""
        if status == "PASSED":
            said = f"Controlul calității a trecut filmul{film}{scored}."
            return said, "Filmul a trecut controlul ✓"
        failures = [str(f) for f in payload.get("failures") or [] if f]
        why = _short(failures[0].rstrip("."), 120) if failures else ""
        said = f"Controlul calității a picat filmul{film}{scored}"
        return _end(said + (f": {why}" if why else "")), "Filmul a picat la control."
    if kind == "media.video_rendered":
        seconds = _number(payload.get("duration_seconds"))
        length = f" ({seconds} s)" if seconds else ""
        redo = str(payload.get("redo") or "")
        if redo:
            what_of = _LAYER_GEN_RO.get(redo, "înregistrării")
            return (
                f"Filmul {named} a fost asamblat din nou după refacerea {what_of}{where}{length}.",
                "Filmul e asamblat din nou.",
            )
        return f"Filmul {named} a fost randat{length}.", "Filmul e randat!"
    if kind == "media.render_failed":
        why = _reason(payload, 150)
        return _end(f"Randarea filmului {named} a eșuat" + (f": {why}" if why else "")), None
    if kind == "media.intermediates_released":
        size = _number(float(payload.get("bytes") or 0) / 1_000_000, 1)
        kept = [k for k in payload.get("kept") or [] if isinstance(k, Mapping)]
        said = f"Fișierele intermediare ale unei randări vechi au fost șterse: {size} MB eliberați"
        if kept:
            why = _short(str(kept[0].get("reason") or "").rstrip("."), 80)
            said += f"; {count(len(kept), 'fișier păstrat', 'fișiere păstrate')}"
            said += f" ({why})" if why else ""
        return said + ".", None
    if kind == "runbook.qc_paid_redo":
        kinds = [_LAYER_RO[k] for k in payload.get("kinds") or [] if k in _LAYER_RO]
        what = " și ".join(kinds) if kinds else "înregistrarea"
        plural = "e" if len(kinds) > 1 else "ă"
        said = f"Refacerea plătită a scenei {scene}{film}: {what} cumpărat{plural}"
        if payload.get("open_motion"):
            said += "; mișcarea poate urma"
        if payload.get("continues"):
            said += "; continuă runda începută"
        return said + ".", f"Scena {scene}: {what} cumpărat{plural}."
    if kind == "runbook.qc_repair":
        return _repair_words(payload, name, named)
    if kind == "runpod.gpu_session_opened":
        purpose = str(payload.get("purpose") or "")
        what = _PURPOSE_RO.get(purpose, "lucru")
        step = _STEP_RO.get(str(payload.get("step") or ""), "")
        said = f"{name} a pornit GPU-ul RunPod pentru {what}{film}"
        said += f" ({step})" if step else ""
        waits = _PURPOSE_WAIT_RO.get(purpose, "rezultatele")
        return said + "; modelul se încarcă (~10 min).", f"GPU pornit: aștept {waits}."
    if kind == "runpod.run_paused":
        items = payload.get("items")
        batch = count(int(items), "lucrare", "lucrări") if isinstance(items, int) else "o rundă"
        said = f"{name} a trimis la RunPod o rundă de {batch}{film}"
        if payload.get("cleared"):
            return said + f"; RunPod a pornit după {_seconds(payload.get('seconds'))}.", (
                "Runda a plecat la RunPod; aștept."
            )
        return said + f"; RunPod nu a pornit în {_seconds(payload.get('seconds'))}.", None
    if kind == "runpod.gpu_off_verified":
        why = _GPU_OFF_RO.get(str(payload.get("reason") or ""), "")
        said = "GPU-ul RunPod s-a oprit" + (f" ({why})" if why else "")
        return said + "; nu mai costă nimic.", None
    if kind == "runpod.gpu_off_unverified":
        why = _short(str(payload.get("reason_ro") or "").rstrip("."), 120)
        return "GPU-ul RunPod nu a confirmat oprirea" + (f": {why}" if why else "") + ".", None
    if kind == "runpod.gpu_forced_off":
        why = _GPU_OFF_RO.get(str(payload.get("reason") or ""), "")
        said = "GPU-ul RunPod a fost oprit forțat" + (f" ({why})" if why else "")
        if payload.get("off") is False:
            said += "; oprirea nu s-a confirmat încă"
        return said + ".", None
    if kind == "economy.spend_reserved":
        usd = payload.get("usd")
        what = _purpose_ro(payload.get("purpose"))
        said = f"{name} a pus deoparte {usd} USD pentru {what}{film}."
        return said, f"Am pus deoparte {usd} USD."
    if kind == "economy.spend_reservation_closed":
        usd = payload.get("usd")
        _board, what = _reference_parts(payload.get("reference"))
        what = what or "pasul"
        status = str(payload.get("status") or "")
        if status == "SETTLED":
            return f"Cheltuit: {usd} USD pe {what}{film}.", None
        if status == "RELEASED":
            return (
                f"Rezervarea de {usd} USD pentru {what}{film} a fost eliberată: nu s-a cheltuit.",
                None,
            )
        return f"Rezervarea de {usd} USD pentru {what}{film} s-a închis ({status.lower()}).", None
    if kind == "economy.provider_cost_recorded":
        vendor = provider_name(payload.get("provider"))
        if vendor.lower() == "runpod":
            vendor = "RunPod"
        _board, what = _reference_parts(payload.get("reference"))
        status = "facturat" if str(payload.get("status") or "") == "BILLED" else "estimat"
        said = f"Cost {status} la {vendor}: {payload.get('vr')} VR$"
        return said + (f" pentru {what}{film}" if what else film) + ".", None
    if kind == "agent.run_completed":
        task = str(payload.get("task_type") or "").split(":")[0]
        task_ro = _TASK_RO.get(task, task.replace("_", " "))
        raw_status = str(payload.get("status") or "")
        status = _RUN_STATUS_RO.get(raw_status, raw_status.lower())
        model = str(payload.get("model_name") or "")
        said = f"{name} a terminat {task_ro}: {status}" + (f" (cu {model})" if model else "")
        bubble = f"Gata: {task_ro} ✓" if status == "reușită" else f"{task_ro}: {status}"
        return said + ".", bubble
    if kind == "agent.state_changed":
        state = str(payload.get("runtime_state") or "").upper()
        task = str(payload.get("task_type") or "").split(":")[0]
        task_ro = _TASK_RO.get(task, task.replace("_", " ")) if task else ""
        if state in ("WORKING", "EXECUTING", "RUNNING", "THINKING", "PLANNING"):
            bubble = f"Lucrez la {task_ro}." if task_ro else "Lucrez."
            return f"{name} lucrează" + (f" la {task_ro}" if task_ro else "") + ".", bubble
        if state == "IDLE":
            return f"{name} a terminat" + (f" {task_ro}" if task_ro else "") + ".", None
        return None, None
    if kind == "workflow.job_fired":
        job = _JOB_RO.get(
            str(payload.get("workflow_type") or "").upper(),
            str(payload.get("job_name") or "o sarcină programată").replace("_", " "),
        )
        return f"Ceasul studioului a pornit {job}.", None
    if kind == "story.episode_drafted":
        number = payload.get("episode_number")
        said = f"{name} a scris episodul{(' ' + str(number)) if number else ''} al serialului"
        return said + (
            " (rescriere)" if payload.get("rewrite_of") else ""
        ) + ".", "Am scris episodul."
    if kind == "story.episode_reviewed":
        verdict = str(payload.get("verdict") or "")
        return f"{name} a citit episodul: {'trece' if verdict == 'PASS' else 'nu trece'}.", None
    if kind == "story.episode_approved":
        return "Episodul serialului e aprobat; se pregătește filmarea.", "Episodul e aprobat!"
    if kind == "story.episode_rejected":
        return "Episodul serialului nu a trecut; se rescrie.", None
    if kind == "story.daily_log_closed":
        safe = int(payload.get("public_safe_events") or 0)
        told = count(safe, "întâmplare", "întâmplări")
        return f"Jurnalul zilei s-a închis: {told} bune de povestit.", None
    return (_fallback(kind, scene, title) if kind else None), None


def enrich(session: Session, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The page's events with ``words_ro``, ``actor``, ``film_title`` and ``bubble_ro`` where
    the studio has them. The dicts are the ones given, completed in place and returned."""
    if not events:
        return events
    actors = _Actors(session)
    titles = _titles(session, [dict(event) for event in events])
    for event in events:
        actor = actors.for_event(event)
        storyboard_id = _storyboard_of(event)
        title = titles.get(storyboard_id) if storyboard_id else None
        words, bubble = _words(event, actor, title, actors.by_role)
        if actor is not None:
            event["actor"] = dict(actor)
        if title:
            event["film_title"] = title
        if words:
            event["words_ro"] = _short(words, WORDS_MAX)
        if bubble:
            event["bubble_ro"] = _short(bubble, BUBBLE_MAX)
    return events
