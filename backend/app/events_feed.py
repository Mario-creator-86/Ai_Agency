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

2026-10-12, the office over the editor's head: «GATA: RESCRIEREA PROMPTULUI UNEI SCENE ✓», and
the Owner: «LA CE SCENĂ LUCREAZĂ?!». An employee's run of one scene (the Director's brief, the
editor's rewrite, her review of it, a still or clip check) is said with its scene and its film
while it works and when it is done — «Gata: rescrierea scenei 3 din «The Zero Script Club» ✓»,
«Am refuzat rescrierea scenei 4: nu tratează constatarea.» — read from the run's own summary,
the brief that names the run and the events of its correlation (`_run_places`).

2026-10-12, evening: her verdict on a rewrite is read from her answer only when her review's
schema accepts it and nothing asked her again, and it never promises a purchase; her second
look at a refusal of quality control (`media.director_second_look`) says whether the refusal
was right and whether the scene is redone, with its scene and its film.

Review of 68fa0b4 (2026-10-12): her second look is said by severity — a defect not in the
picture is a wrong refusal, a real but minor one is «real, dar mic» — a clip her look kept
reads as kept, and her reading of a new prompt lesson (`media.prompt_lesson_read`) says what
it corrects.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.models import Agent, AgentRun, Role
from app.media.models import Storyboard
from app.models import DomainEvent
from app.wording import count, decimal, provider_name

logger = logging.getLogger("studio.events_feed")

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
#: A walk's reason that names the film itself («Filmul «Storyboard: X»: …»,
#: `media.director_qc.outcome_words`): the row already names it once, by its bare title.
_FILM_LEAD = re.compile(r"^\s*Filmul\s+«[^»]*»\s*:\s*")
#: A finished walk whose reason says nothing was done (`director_qc.outcome_words` NOTHING_DONE
#: and WAITING): the film stood still, it did not «go to the end».
_NOTHING_MOVED = re.compile(r"\bnimic\b[^.]*\b(?:nu se putea|nu s-a)\s+re(?:face|făcut)", re.I)
#: The start of the reason `runbook.stages` gives when she decided but nothing could be done.
_DECIDED_NOT_DONE = "nimic din refacerea hotărâtă nu se putea face:"
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
    "director_rewrite_review": "verificarea unei rescrieri",
    "director_second_look": "a doua privire asupra unui refuz al controlului",
    "prompt_lesson_reading": "citirea unei lecții noi despre prompturi",
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
#: The tasks that work on one scene of a film, said with that scene (and the film, when it is
#: known), and those that work on a whole film, said with the film. 2026-10-12: the Owner's
#: office showed «GATA: RESCRIEREA PROMPTULUI UNEI SCENE ✓» over the editor's head, with no
#: scene and no film, and he asked «LA CE SCENĂ LUCREAZĂ?!». A run's own summary names its
#: scene («Rescriu scena 3 din «…» după brief-ul Directoarei.»), and the events of its
#: correlation name the film (`_run_places`).
_SCENE_TASK_RO: dict[str, str] = {
    "scene_prompt_rewrite": "rescrierea scenei {scene}",
    "director_scene_brief": "brief-ul pentru scena {scene}",
    "director_rewrite_review": "verificarea rescrierii scenei {scene}",
    "director_second_look": "a doua privire asupra scenei {scene}",
    "still_qc": "verificarea imaginii scenei {scene}",
    "clip_qc": "verificarea clipului scenei {scene}",
}
_FILM_TASK_RO: dict[str, str] = {
    "picture_qc": "controlul imaginii filmului",
    "director_qc_review": "decizia asupra filmului",
    "shot_prompts": "planul de cadre al filmului",
}
#: The scene a run's summary names («scena 3», «scenei 5») and the film in its quotes.
_SUMMARY_SCENE = re.compile(r"\bscen(?:a|ei|ă)\s+(\d{1,3})\b", re.IGNORECASE)
_SUMMARY_TITLE = re.compile(r"«([^»]{2,200})»")
#: The template suffixes of `structured_run`'s second attempt: a run followed by one of them
#: had its answer refused (`agents.structured.REFUSED_SUFFIX`, `THINKING_SUFFIX`).
_RETRY_SUFFIXES = ("+again", "+think")
#: The events that record which runs worked on which scene: her brief (her brief's, his
#: rewrite's and her review's run ids, each round's too) and the rewrite stored (his run, her
#: review and the reviews she refused before it); her second look at a refusal names hers.
_BRIEF_EVENT = "media.director_scene_brief"
_REWRITTEN_EVENT = "media.prompts_rewritten"
_SECOND_LOOK_EVENT = "media.director_second_look"
#: What her second look looked at (`second_look.second_look`'s ``kind``), in a sentence.
_LOOK_KIND_RO = {"still": "imaginea", "shot": "clipul", "film_scene": "cadrele"}
#: How far before a run its correlation is read for the film it worked on: the Director's
#: ladder and a paid redo's wait at RunPod (up to ~83 min) share one correlation.
_CORRELATION_HOURS = 12
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


def _second_look_words(
    payload: Mapping[str, Any], name: str, title: str | None
) -> tuple[str, str | None]:
    """The Director's second look at a refusal of quality control (`media.director_second_look`,
    2026-10-12): the Owner, «trece imaginile picate de la QC pe la Directoare și să decidă dacă
    au picat corect sau nu și dacă trebuie refăcute». Said with the scene and the film: whether
    the refusal was right, and whether the scene is redone (bought) or accepted as it is."""
    scene = _scene_number(payload.get("scene_index"))
    what = _LOOK_KIND_RO.get(str(payload.get("kind") or ""), "imaginea")
    of_scene = f" scenei {scene}" if scene else ""
    verdict = str(payload.get("verdict") or "").upper()
    redo = bool(payload.get("redo"))
    severity = str(payload.get("severity") or "").lower()
    if verdict not in ("CONFIRMED", "OVERTURNED"):
        # Only the short why: her look's reason already says «nu s-a putut uita … Refuzul
        # controlului rămâne», which the sentence says once (review of 68fa0b4, 2026-10-12).
        why = _short(_unavailable_why(payload.get("reason_ro")), 110)
        head = _with_film(f"{name} nu s-a putut uita la {what}{of_scene}", " din ", title)
        return _end(f"{head}: refuzul controlului rămâne" + (f" ({why})" if why else "")), None
    why = _short(str(payload.get("reason_ro") or "").rstrip("."), 110)
    because = f" ({why})" if why else ""
    # By severity (review of 68fa0b4, 2026-10-12): a defect she saw and judged small is real,
    # and «refuzul controlului e greșit» said of it was untrue; only a refusal of a defect that
    # is not in the picture (severity none) is a wrong refusal.
    if not redo and (severity == "minor" or verdict == "CONFIRMED"):
        said = "defectul e real, dar mic — se acceptă, nu se reface"
        tail = "defect mic, se acceptă"
    elif not redo:
        said, tail = "refuzul controlului e greșit — se acceptă, nu se reface", "se acceptă"
    elif verdict == "CONFIRMED":
        said, tail = "refuzul e corect — se reface", "se reface"
    else:
        said, tail = "refuzul controlului e greșit, dar scena tot se reface", "se reface"
    head = _with_film(f"{name} s-a uitat la {what}{of_scene}", " din ", title)
    bubble_head = f"M-am uitat la scena {scene}" if scene else "M-am uitat la refuz"
    return (
        _end(f"{head}: {said}{because}"),
        _with_film(bubble_head, " din ", title, f": {tail}.", BUBBLE_MAX),
    )


#: Her look's reason when she could not look (`second_look._UNAVAILABLE_RO`): the head and the
#: tail the register's own sentence already says.
_UNAVAILABLE_REASON = re.compile(
    r"^Directoarea nu s-a putut uita la [^:]+:\s*(?P<why>.*?)\.?\s*"
    r"(?:Refuzul controlului rămâne\.?)?$"
)


def _unavailable_why(reason: Any) -> str:
    """The short why of a look she could not take, without the words around it."""
    said = " ".join(str(reason or "").split())
    found = _UNAVAILABLE_REASON.match(said)
    if found:
        said = found.group("why")
    return said.removesuffix("Refuzul controlului rămâne.").strip().rstrip(".")


def _kept_clip_words(payload: Mapping[str, Any], where: str, film: str) -> tuple[str, str | None]:
    """A clip quality control refused and the Director's look kept (``accepted_by``
    director_look, `fix_check.DIRECTOR_LOOK_APPROVER`): it is the film's clip, said as kept —
    never «nu a trecut controlul» (review of 68fa0b4, 2026-10-12)."""
    look = payload.get("director_look") if isinstance(payload.get("director_look"), Mapping) else {}
    why = _short(str(look.get("reason_ro") or "").rstrip("."), 110)
    if str(look.get("severity") or "").lower() == "none":
        judged = "refuzul controlului era greșit"
    else:
        judged = "controlul l-a refuzat, dar defectul e mic"
    said = f"Clipul{where}{film} a fost păstrat de Directoare: {judged} — se acceptă"
    return _end(said + (f" ({why})" if why else "")), f"Clipul{where} păstrat ✓"


def _lesson_read_words(payload: Mapping[str, Any], name: str) -> tuple[str, str | None]:
    """A new prompt lesson read beside the live ones (`prompt_agent.LESSON_READ_EVENT`): by the
    Director, who decided which lessons it corrects (retired) or repeats (kept once), or by the
    words when she could not read it (review of 68fa0b4, 2026-10-12)."""
    lesson = _short(str(payload.get("lesson") or "").rstrip("."), 90)
    corrects = [
        f"«{_short(str(item).rstrip('.'), 60)}»" for item in payload.get("corrects") or [] if item
    ]
    repeats = [
        f"«{_short(str(item).rstrip('.'), 60)}»" for item in payload.get("repeats") or [] if item
    ]
    absorbed = _short(str(payload.get("absorbed_into") or "").rstrip("."), 60)
    parts: list[str] = []
    if corrects:
        retired = "retrasă" if len(corrects) == 1 else "retrase"
        parts.append(f"corectează {_listed(corrects, 2)} ({retired})")
    if repeats:
        parts.append(f"o repetă pe {_listed(repeats, 2)} (păstrate ca una)")
    if absorbed:
        parts.append(f"o spune deja «{absorbed}», cu care e una acum")
    what = "; ".join(parts) or "nu corectează și nu repetă nicio lecție știută"
    if str(payload.get("read_by") or "") == "director":
        return _end(f"{name} a citit lecția nouă «{lesson}»: {what}"), (
            "Am citit o lecție nouă." if parts else None
        )
    why = _short(str(payload.get("unavailable") or "").rstrip("."), 80)
    head = f"Lecția nouă «{lesson}» a fost comparată după cuvinte"
    head += f" (Directoarea n-a putut-o citi: {why})" if why else ""
    return _end(f"{head}: {what}"), None


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


# ------------------------------------------------------------------ where a run worked


def _task_of(payload: Mapping[str, Any]) -> str:
    return str(payload.get("task_type") or "").split(":")[0]


def _run_id(event: Mapping[str, Any]) -> str | None:
    """The run an employee's event is about, when its task works on one scene or one film:
    the run that finished (`agent.run_completed`, its aggregate) or the one that starts
    (`agent.state_changed` THINKING carries its ``run_id``)."""
    kind = str(event.get("event_type") or "")
    if kind not in ("agent.run_completed", "agent.state_changed"):
        return None
    payload = _payload(event)
    task = _task_of(payload)
    if task not in _SCENE_TASK_RO and task not in _FILM_TASK_RO:
        return None
    found = payload.get("run_id")
    if not found and kind == "agent.run_completed":
        if str(event.get("aggregate_type") or "") == "agent_run":
            found = event.get("aggregate_id")
    return str(found) if found else None


def _hours_before(stamp: Any, hours: int) -> str | None:
    """An ISO moment ``hours`` earlier, as the record writes its timestamps; None if unread."""
    try:
        moment = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    return (moment - timedelta(hours=hours)).isoformat(timespec="microseconds")


def _scene_number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip()) or None
    return None


def _runs_named(kind: str, payload: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """The runs a brief, a stored rewrite or her second look names, each with her review's
    verdict when the run is her review: [(run_id, {"verdict", "reason_ro"} or {})]. A review
    the record names without a verdict is one whose answer was never accepted, and it is said
    without one (2026-10-12, review of a9f84ea)."""
    named: list[tuple[str, dict[str, Any]]] = []
    if kind == _BRIEF_EVENT:
        for key in ("brief_run_id", "rewrite_run_id"):
            if payload.get(key):
                named.append((str(payload[key]), {}))
        # Each round of his rewrites with her verdict on it (1839dcf): the first round's
        # MISSES is hers as much as the last round's verdict is.
        for attempt in payload.get("review_attempts") or []:
            if not isinstance(attempt, Mapping):
                continue
            if attempt.get("rewrite_run_id"):
                named.append((str(attempt["rewrite_run_id"]), {}))
            if attempt.get("review_run_id"):
                said = {"verdict": attempt.get("verdict"), "reason_ro": attempt.get("reason_ro")}
                named.append((str(attempt["review_run_id"]), said))
        if payload.get("review_run_id"):
            review = {
                "verdict": payload.get("review_verdict"),
                "reason_ro": payload.get("review_reason_ro"),
            }
            named.append((str(payload["review_run_id"]), review))
    elif kind == _REWRITTEN_EVENT:
        if payload.get("run_id"):
            named.append((str(payload["run_id"]), {}))
        review = payload.get("review")
        if isinstance(review, Mapping):
            for refused in review.get("refused") or []:
                if isinstance(refused, Mapping) and refused.get("review_run_id"):
                    said = {"verdict": "MISSES", "reason_ro": refused.get("reason_ro")}
                    named.append((str(refused["review_run_id"]), said))
            if review.get("run_id"):
                said = {"verdict": review.get("verdict"), "reason_ro": review.get("reason_ro")}
                named.append((str(review["run_id"]), said))
    elif kind == _SECOND_LOOK_EVENT and payload.get("run_id"):
        named.append((str(payload["run_id"]), {}))
    return named


def _from_correlations(
    session: Session, runs: list[Any], places: dict[str, dict[str, Any]]
) -> None:
    """The film (and, where a brief names the run, the scene and her verdict) from the events
    of each run's correlation. One correlation can hold several scenes of one film — the
    Director's ladder rewrites scenes 3, 4 and 7 under one (2026-10-12, f06808c9) — so the
    scene comes from the run itself, and the film from a correlation that names only one."""
    correlations = sorted({str(run.correlation_id) for run in runs if run.correlation_id})
    if not correlations:
        return
    query = select(
        DomainEvent.event_type,
        DomainEvent.aggregate_type,
        DomainEvent.aggregate_id,
        DomainEvent.correlation_id,
        DomainEvent.payload,
    ).where(DomainEvent.correlation_id.in_(correlations))
    since = _hours_before(min(str(run.started_at) for run in runs), _CORRELATION_HOURS)
    if since:
        query = query.where(DomainEvent.timestamp >= since)
    boards: dict[str, set[str]] = {}
    for row in session.execute(query):
        payload = row.payload if isinstance(row.payload, Mapping) else {}
        board = payload.get("storyboard_id") or (
            row.aggregate_id if row.aggregate_type == "storyboard" else None
        )
        if board:
            boards.setdefault(str(row.correlation_id), set()).add(str(board))
        for run_id, review in _runs_named(str(row.event_type), payload):
            place = places.get(run_id)
            if place is None:
                continue
            place["named"] = True
            if board:
                place["board"] = str(board)
            scene = _scene_number(payload.get("scene_index"))
            if scene:
                place["scene"] = scene
            if review.get("verdict"):
                place["verdict"] = str(review["verdict"]).upper()
                place["reason_ro"] = str(review.get("reason_ro") or "")
    for run in runs:
        place = places[str(run.id)]
        named = boards.get(str(run.correlation_id)) or set()
        if not place["board"] and len(named) == 1:
            place["board"] = next(iter(named))


def _review_verdicts(session: Session, places: dict[str, dict[str, Any]]) -> None:
    """Her verdict on a rewrite from her run's own answer, while no brief or stored rewrite
    names the run yet — and only an answer her review's own schema accepts
    (`scene_rewrite.RewriteReview`, read as `structured_run` reads it), from a run that was
    not asked again (`_RETRY_SUFFIXES`). 2026-10-12, review of a9f84ea: a MISSES was read from
    an answer the validator had refused, and the office announced a refusal she never made. A
    run the record names says only what the record says (`_runs_named`)."""
    pending = sorted(
        run_id
        for run_id, place in places.items()
        if place["task"] == "director_rewrite_review"
        and not place["verdict"]
        and not place.get("named")
    )
    if not pending:
        return
    try:
        from app.agents.identity import read_structured  # noqa: PLC0415
        from app.media import scene_rewrite  # noqa: PLC0415 - it imports the whole media stage
    except ImportError:  # pragma: no cover - the review's schema is the only judge of an answer
        return
    schema = getattr(scene_rewrite, "RewriteReview", None)
    if schema is None:
        return
    rows = session.execute(
        select(
            AgentRun.id,
            AgentRun.agent_id,
            AgentRun.correlation_id,
            AgentRun.started_at,
            AgentRun.output_text,
            AgentRun.prompt_template_version,
        ).where(AgentRun.id.in_(pending))
    ).all()
    asked_again = _asked_again(session, rows)
    for row in rows:
        if str(row.id) in asked_again:
            continue
        try:
            parsed, _why = read_structured(str(row.output_text or ""), schema)
        except Exception:  # noqa: BLE001 - an answer the schema cannot read says nothing
            continue
        verdict = str(getattr(parsed, "verdict", "") or "").upper() if parsed else ""
        if verdict not in ("TREATS", "MISSES"):
            continue
        places[str(row.id)]["verdict"] = verdict
        places[str(row.id)]["reason_ro"] = str(getattr(parsed, "reason_ro", "") or "")


def _asked_again(session: Session, rows: list[Any]) -> set[str]:
    """The runs among ``rows`` whose answer `structured_run` refused: the next run of the same
    employee, task and correlation is its second attempt (`_RETRY_SUFFIXES`)."""
    correlations = sorted({str(row.correlation_id) for row in rows if row.correlation_id})
    if not correlations:
        return set()
    runs = session.execute(
        select(
            AgentRun.id,
            AgentRun.agent_id,
            AgentRun.correlation_id,
            AgentRun.started_at,
            AgentRun.prompt_template_version,
        )
        .where(
            AgentRun.correlation_id.in_(correlations),
            AgentRun.task_type == "director_rewrite_review",
        )
        .order_by(AgentRun.started_at, AgentRun.id)
    ).all()
    following: dict[str, str] = {}
    last: dict[tuple[str, str], str] = {}
    for run in runs:
        key = (str(run.agent_id), str(run.correlation_id))
        if key in last:
            following[last[key]] = str(run.prompt_template_version or "")
        last[key] = str(run.id)
    return {str(row.id) for row in rows if following.get(str(row.id), "").endswith(_RETRY_SUFFIXES)}


def _place_titles(
    session: Session, places: dict[str, dict[str, Any]], said_titles: dict[str, str]
) -> None:
    """Each run's film by its title: the storyboard found, else the title its summary says
    (cut at 60 characters there, so completed from the storyboard it begins)."""
    boards = sorted({str(place["board"]) for place in places.values() if place["board"]})
    titles: dict[str, str] = {}
    if boards:
        rows = session.execute(
            select(Storyboard.id, Storyboard.title).where(Storyboard.id.in_(boards))
        ).all()
        titles = {str(board): _bare_title(title) for board, title in rows}
    for run_id, place in places.items():
        title = titles.get(str(place["board"] or ""))
        said = said_titles.get(run_id, "")
        if not title and said:
            whole = {
                _bare_title(found)
                for found in session.scalars(
                    select(Storyboard.title)
                    .where(Storyboard.title.startswith(said, autoescape=True))
                    .limit(5)
                )
            }
            title = next(iter(whole)) if len(whole) == 1 else _bare_title(said)
        place["title"] = title or None


def _run_places(session: Session, events: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Where each run the page's events name worked, when its task is one scene's or one
    film's: {run_id: {"task", "scene", "title", "verdict", "reason_ro", "board"}}.

    The scene is the run's own (its summary, or the brief that names the run); the film is the
    storyboard the brief names, else the only one its correlation names, else the title its
    summary says. Read from the record, never guessed: a run nothing places is said as before.
    """
    wanted = sorted({run_id for run_id in (_run_id(event) for event in events) if run_id})
    if not wanted:
        return {}
    runs = list(
        session.execute(
            select(
                AgentRun.id,
                AgentRun.task_type,
                AgentRun.correlation_id,
                AgentRun.started_at,
                AgentRun.context_json,
            ).where(AgentRun.id.in_(wanted))
        ).all()
    )
    if not runs:
        return {}
    places: dict[str, dict[str, Any]] = {}
    said_titles: dict[str, str] = {}
    for run in runs:
        context = run.context_json if isinstance(run.context_json, Mapping) else {}
        summary = str(context.get("task_summary") or "")
        scene = _SUMMARY_SCENE.search(summary)
        places[str(run.id)] = {
            "task": str(run.task_type or "").split(":")[0],
            "scene": int(scene.group(1)) if scene else None,
            "board": None,
            "title": None,
            "verdict": None,
            "reason_ro": "",
            "named": False,
        }
        title = _SUMMARY_TITLE.search(summary)
        if title:
            said_titles[str(run.id)] = title.group(1).strip()
    _from_correlations(session, runs, places)
    _review_verdicts(session, places)
    _place_titles(session, places, said_titles)
    return places


def _with_film(
    head: str, joiner: str, title: str | None, tail: str = "", limit: int | None = None
) -> str:
    """``head``, the film in its quotes and ``tail``; within ``limit`` the title is shortened
    inside its quotes — never the scene — and left out when not even a word of it fits."""
    if not title:
        return head + tail
    whole = f"{head}{joiner}«{title}»{tail}"
    if limit is None or len(whole) <= limit:
        return whole
    room = limit - len(f"{head}{joiner}«»{tail}")
    short = _short(title, room) if room >= 4 else ""
    if len(short) < 2 or len(short) > room:
        return head + tail
    return f"{head}{joiner}«{short}»{tail}"


def _placed_task(task: str, place: Mapping[str, Any] | None) -> tuple[str, str, str | None] | None:
    """(the task said with its scene, how the film follows it, the film's title) for a run
    whose place is known; None when it is not, and the run is said as before."""
    if not place:
        return None
    title = place.get("title") or None
    scene = place.get("scene")
    if task in _SCENE_TASK_RO and scene:
        return _SCENE_TASK_RO[task].format(scene=scene), " din ", title
    if task in _FILM_TASK_RO and title:
        return _FILM_TASK_RO[task], " ", title
    return None


def _placed_run_words(
    task: str,
    placed: tuple[str, str, str | None],
    place: Mapping[str, Any],
    name: str,
    status: str,
    model: str,
) -> tuple[str, str]:
    """A finished run of one scene or one film, said with them; her review of a rewrite says
    whether it treats the finding («Directoarea a refuzat rescrierea scenei 4: nu tratează
    constatarea»), which is what the office needs to hear before anything is bought. Never
    that anything «can be bought»: whether it is depends on money and the Owner's GPU hold,
    which her review does not know (2026-10-12, review of a9f84ea: the register would have
    said «se poate cumpăra» even while the Owner's «Oprește GPU acum» held)."""
    phrase, joiner, title = placed
    scene = place.get("scene")
    if task == "director_rewrite_review" and status == "reușită" and scene:
        verdict = str(place.get("verdict") or "").upper()
        if verdict == "MISSES":
            why = _short(str(place.get("reason_ro") or "").rstrip("."), 120)
            said = _with_film(f"{name} a refuzat rescrierea scenei {scene}", " din ", title)
            said += ": nu tratează constatarea" + (f" ({why})" if why else "")
            return _end(said), f"Am refuzat rescrierea scenei {scene}: nu tratează constatarea."
        if verdict == "TREATS":
            said = _with_film(f"{name} a verificat rescrierea scenei {scene}", " din ", title)
            return (
                said + ": tratează constatarea.",
                f"Rescrierea scenei {scene} tratează constatarea ✓",
            )
    by = f" (cu {model})" if model else ""
    said = _with_film(f"{name} a terminat {phrase}", joiner, title) + f": {status}{by}."
    if status == "reușită":
        return said, _with_film(f"Gata: {phrase}", joiner, title, " ✓", BUBBLE_MAX)
    head = phrase[:1].upper() + phrase[1:]
    return said, _with_film(head, joiner, title, f": {status}", BUBBLE_MAX)


def _words(
    event: Mapping[str, Any],
    actor: Mapping[str, Any] | None,
    title: str | None,
    staff: Mapping[str, Mapping[str, Any]] | None = None,
    places: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[str | None, str | None]:
    """(words_ro, bubble_ro) for one event; a kind nobody has words for is said by its name
    (`_fallback`), never by its fields. ``staff`` is the register's employee per role, for a
    sentence that names a second employee (the Director's brief names the editor). ``places``
    is where the page's runs worked (`_run_places`): a run of one scene names it and its film."""
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
        reason = _FILM_LEAD.sub("", str(payload.get("reason") or "").replace("Oprit: ", ""), 1)
        walk = _WALK_RO.get(status, status.lower())
        if status == "COMPLETED" and _NOTHING_MOVED.search(reason):
            # 2026-10-12 19:50 UTC: «a mers până la capăt: … nimic … nu se putea reface» — a
            # walk that ended with nothing done stood still, and the row says so.
            walk = "a stat pe loc"
        why = _short(reason, 150).rstrip(".")
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
    if kind == "media.still_sent_back":
        # The picture goes back to the stills gate: clip QC found the fault in it (2026-10-12,
        # the cyclotron's scene 1), or the model refused to animate it for safety.
        if str(payload.get("failure_kind") or "") == "CLIP_QC":
            why = "controlul clipului a găsit greșeala în ea; nu se mai animă"
        else:
            why = "modelul a refuzat să o anime din motive de siguranță"
        return (
            f"Imaginea{where}{film} se întoarce la poarta imaginilor: {why}.",
            f"Scena {scene}: imagine nouă, apoi mișcare." if scene else None,
        )
    if kind == "media.motion_needs_owner":
        # The motion step's hold on a scene (its status word is older than the Director's
        # loop): the scene needs a new still first, or its movement stopped on a reason.
        why = _short(str(payload.get("reason") or "").rstrip("."), 150)
        if str(payload.get("status") or "") == "NEEDS_STILL":
            said = f"Scena {scene}{film} are nevoie de o imagine nouă înainte de mișcare"
            return said + (f": {why}" if why else "") + ".", (
                f"Scena {scene}: imagine nouă, apoi mișcare." if scene else None
            )
        said = f"Mișcarea{where}{film} s-a oprit"
        return said + (f": {why}" if why else "") + ".", None
    if kind == "media.director_qc_decision":
        decision = str(payload.get("decision") or "")
        verdict = _DECISION_RO.get(decision, decision.lower())
        outcome = _OUTCOME_RO.get(str(payload.get("outcome") or ""), "")
        said = f"{name} a decis filmul {named}: {verdict}"
        return said + (f" — {outcome}" if outcome else "") + ".", f"Am decis: {verdict}."
    if kind == "media.director_qc_waiting":
        reason = str(payload.get("reason") or "")
        if reason.startswith(_DECIDED_NOT_DONE):
            # She did decide; what she decided could not be done now (the Owner's GPU stop,
            # 2026-10-12 19:50 UTC). The row says the real reason, never «n-a putut decide».
            why = _short(reason[len(_DECIDED_NOT_DONE) :].strip(), 170).rstrip(".")
            return (
                f"{name} a hotărât ce se reface la filmul {named}, dar acum nu se poate face"
                + (f": {why}" if why else "")
                + ".",
                None,
            )
        return f"{name} n-a putut decide încă filmul {named}: {_reason(payload, 150)}.", None
    if kind == "editorial.judged":
        return _judged_words(payload, name, title)
    if kind == "media.director_scene_brief":
        return _brief_words(payload, name, film, editor)
    if kind == _SECOND_LOOK_EVENT:
        return _second_look_words(payload, name, title)
    if kind == "media.prompt_lesson_read":
        return _lesson_read_words(payload, name)
    if kind == "media.clip_qc_checked":
        attempt = payload.get("attempt")
        again = f" la încercarea {attempt}" if isinstance(attempt, int) and attempt > 1 else ""
        if str(payload.get("accepted_by") or "") == "director_look":
            return _kept_clip_words(payload, where, film)
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
        task = _task_of(payload)
        task_ro = _TASK_RO.get(task, task.replace("_", " "))
        raw_status = str(payload.get("status") or "")
        status = _RUN_STATUS_RO.get(raw_status, raw_status.lower())
        model = str(payload.get("model_name") or "")
        place = (places or {}).get(_run_id(event) or "")
        placed = _placed_task(task, place)
        if placed is not None and place is not None:
            return _placed_run_words(task, placed, place, name, status, model)
        said = f"{name} a terminat {task_ro}: {status}" + (f" (cu {model})" if model else "")
        bubble = f"Gata: {task_ro} ✓" if status == "reușită" else f"{task_ro}: {status}"
        return said + ".", bubble
    if kind == "agent.state_changed":
        state = str(payload.get("runtime_state") or "").upper()
        task = _task_of(payload)
        task_ro = _TASK_RO.get(task, task.replace("_", " ")) if task else ""
        if state in ("WORKING", "EXECUTING", "RUNNING", "THINKING", "PLANNING"):
            # «LA CE SCENĂ LUCREAZĂ?!» (the Owner, 2026-10-12): the scene and the film the run
            # is about, from the run itself, while it works.
            placed = _placed_task(task, (places or {}).get(_run_id(event) or ""))
            if placed is not None:
                phrase, joiner, film_title = placed
                said = _with_film(f"{name} lucrează la {phrase}", joiner, film_title) + "."
                return said, _with_film(f"Lucrez la {phrase}", joiner, film_title, ".", BUBBLE_MAX)
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
        if payload.get("reviewed_by") == "checks":
            return "Episodul serialului nu a trecut verificările calculate; se rescrie.", None
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
    try:
        places = _run_places(session, events)
    except Exception as exc:  # noqa: BLE001 - a run's place is an addition; it never costs the page
        logger.warning("run_places_unavailable", extra={"error": type(exc).__name__})
        places = {}
    for event in events:
        actor = actors.for_event(event)
        storyboard_id = _storyboard_of(event)
        title = titles.get(storyboard_id) if storyboard_id else None
        words, bubble = _words(event, actor, title, actors.by_role, places)
        if actor is not None:
            event["actor"] = dict(actor)
        if title:
            event["film_title"] = title
        if words:
            event["words_ro"] = _short(words, WORDS_MAX)
        if bubble:
            event["bubble_ro"] = _short(bubble, BUBBLE_MAX)
    return events
