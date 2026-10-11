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
worth a word). An event nobody has words for carries none of these keys, and the page's own
fallback stays. Nothing here is simulated: every sentence is read from the event's payload
and the rows it names.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.models import Agent, Role
from app.media.models import Storyboard
from app.wording import count, decimal

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
    ("media.video_rendered", "VideoEditor"),
    ("media.render_failed", "VideoEditor"),
    ("media.sound_plan", "VoiceArtist"),
    ("media.narration", "VoiceArtist"),
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
#: A GPU session's purpose, and a step, in words.
_PURPOSE_RO = {"image": "imagini", "video": "clipuri"}
_STEP_RO = {"stills": "imagini", "test_shot": "cadrul de probă", "motion": "mișcare"}
#: Where a film's walk ended, in words.
_WALK_RO = {
    "COMPLETED": "a mers până la capăt",
    "BLOCKED": "s-a oprit",
    "SKIPPED": "n-a putut porni",
    "WAITING": "așteaptă",
    "INTERRUPTED": "a fost întreruptă",
}
#: A model's vendor, as the Owner knows it.
_VENDOR_RO = {"Qwen-Image-2512": "RunPod", "LTX-2.5": "RunPod"}
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
_GPU_OFF_RO = {
    "STEP_DONE": "pasul s-a încheiat",
    "SHUTDOWN": "studioul s-a oprit",
    "LAUNCHER_STOP": "oprit de lansator",
}
_REWRITE_RO = {"redo": "pentru refacere", "director": "la decizia Directoarei"}
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
        if payload.get("director_repair") or payload.get("decided_by") == "director":
            return self.by_role.get("Director")
        for prefix, role in _ROLE_BY_PREFIX:
            if kind.startswith(prefix):
                return self.by_role.get(role)
        return None


def _storyboard_of(event: Mapping[str, Any]) -> str | None:
    payload = _payload(event)
    found = payload.get("storyboard_id")
    if not found and str(event.get("aggregate_type") or "") == "storyboard":
        found = event.get("aggregate_id")
    if not found:
        reference = str(payload.get("reference") or "")
        if reference.startswith("foaie:"):
            found = reference.split(":")[1]
    return str(found) if found else None


def _titles(session: Session, events: list[Mapping[str, Any]]) -> dict[str, str]:
    """The titles of the storyboards the page's events name, one query."""
    ids = {board for board in (_storyboard_of(event) for event in events) if board}
    if not ids:
        return {}
    rows = session.scalars(select(Storyboard).where(Storyboard.id.in_(sorted(ids))))
    return {str(row.id): str(row.title) for row in rows}


def _short(text: Any, limit: int) -> str:
    said = " ".join(str(text or "").split())
    if len(said) <= limit:
        return said
    return said[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


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


def _words(
    event: Mapping[str, Any], actor: Mapping[str, Any] | None, title: str | None
) -> tuple[str | None, str | None]:
    """(words_ro, bubble_ro) for one event, or (None, None) when the studio has no words."""
    kind = str(event.get("event_type") or "")
    payload = _payload(event)
    name = str(actor["name"]) if actor else "Studioul"
    scene = payload.get("scene_number") or payload.get("scene_index")
    where = f" scenei {scene}" if scene else ""
    film = _film(title)
    named = f"«{title or '…'}»"

    if kind == "media.scene_take_recorded":
        take, pronoun = _KIND_RO.get(str(payload.get("kind") or ""), ("înregistrarea", "o"))
        status = str(payload.get("status") or "")
        if status == "SUBMITTED":
            vendor = _VENDOR_RO.get(str(payload.get("model_id") or ""), "furnizor")
            return f"{name} a trimis la {vendor} {take}{where}{film}.", None
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
        return None, None
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
        bought = sum(1 for s in scenes if s.get("status") in ("BOUGHT", "APPROVED", "ACCEPTED"))
        reasons = {str(s.get("reason") or "") for s in scenes if s.get("status") == "NOT_BOUGHT"}
        why = _short(next(iter(sorted(reasons)), ""), 100)
        bought_ro = count(bought, "cadru cumpărat", "cadre cumpărate")
        said = f"Pasul «{step}» pentru {named} s-a încheiat: {bought_ro}"
        return said + (f"; {why}" if why else "") + ".", None
    if kind == "runbook.film_continued":
        status = str(payload.get("status") or "")
        walk = _WALK_RO.get(status, status.lower())
        why = _short(str(payload.get("reason") or "").replace("Oprit: ", ""), 150).rstrip(".")
        return f"Filmul {named} {walk}" + (f": {why}" if why else "") + ".", None
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
        why = _REWRITE_RO.get(str(payload.get("reason") or ""), "")
        return f"Promptul{where}{film} a fost rescris" + (f" {why}" if why else "") + ".", None
    if kind == "media.scene_redone":
        take, _pronoun = _KIND_RO.get(str(payload.get("kind") or ""), ("înregistrarea", "o"))
        credits = payload.get("credits")
        spent = ""
        if isinstance(credits, int | float) and credits:
            spent = f" ({decimal(float(credits), 0)} credite)"
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
        said = f"{take.capitalize()}{where}{film} a fost retras{_feminine(take)}{by}"
        return said + "; nu se mai folosește.", None
    if kind == "media.scene_take_restored":
        return f"Înregistrarea{where}{film} a fost dată înapoi: refacerea n-a livrat nimic.", None
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
        landed = payload.get("rewritten")
        said = f"{name} a dat brief de rescriere pentru scena {scene}{film}"
        if landed:
            said += "; Kael a rescris-o"
        elif landed is False:
            said += "; rescrierea n-a aterizat încă"
        return said + ".", f"Brief pentru scena {scene}."
    if kind == "runpod.gpu_session_opened":
        purpose = _PURPOSE_RO.get(str(payload.get("purpose") or ""), "lucru")
        said = f"Studioul a pornit GPU-ul pe RunPod pentru {purpose}{film}"
        return said + "; modelul se încarcă (~10 min).", None
    if kind == "runpod.gpu_off_verified":
        why = _GPU_OFF_RO.get(str(payload.get("reason") or ""), "")
        return "GPU-ul RunPod s-a oprit" + (f" ({why})" if why else "") + ".", None
    if kind == "economy.spend_reservation_closed":
        usd = payload.get("usd")
        reference = str(payload.get("reference") or "")
        step = next((part for part in reference.split(":") if part in _STEP_RO), "")
        what = _STEP_RO.get(step, "pasul")
        status = str(payload.get("status") or "").lower()
        return f"Cheltuit: {usd} USD pe {what}{film} ({status}).", None
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
            return f"{name} lucrează" + (f" la {task_ro}" if task_ro else "") + ".", None
        if state == "IDLE":
            return f"{name} a terminat" + (f" {task_ro}" if task_ro else "") + ".", None
        return None, None
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
    if kind.startswith("media.") and title:
        # A media event without words of its own still names its film, not its id.
        return f"{kind.split('.', 1)[1].replace('_', ' ')} — «{title}».", None
    return None, None


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
        words, bubble = _words(event, actor, title)
        if actor is not None:
            event["actor"] = dict(actor)
        if title:
            event["film_title"] = title
        if words:
            event["words_ro"] = _short(words, WORDS_MAX)
        if bubble:
            event["bubble_ro"] = _short(bubble, BUBBLE_MAX)
    return events
