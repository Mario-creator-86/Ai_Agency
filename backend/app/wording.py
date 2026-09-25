"""The studio's own words for the Owner: Romanian sentences over the codes the record keeps.

The Owner's standing rule (2026-09-23): what the studio writes for him to read is Romanian.
Until 2026-09-25 the backend wrote Romanian sentences with the record's codes left in them —
«1 bugete active: DAILY 15 USD (OK)», «Modul de autonomie este AUTONOMOUS_CEO», «Gâtuire la
APPROVAL», «publish: COMPLETED — …», «Etapa «post_run» a eșuat: OperationalError: (sqlite3…» —
which read as a page nobody finished. This module is where a code becomes a word, once, so the
preflight, the day's runs, the Director's matters and the letters say the same thing the same
way, and say it in the words the page already uses (`frontend/src/dialog_words.js`,
`ledger.js`'s `RUN_STAGE_LABEL`, the glossary).

What it never does: change a code. The structured fields keep ``DAILY``, ``AUTONOMOUS_CEO``,
``post_run`` and the exception's class; only the sentence beside them is said in words. A code
this module has not heard of passes through lower-cased with spaces rather than being guessed
into a known one.

Pure: no database, no settings, nothing imported from the rest of the studio.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

# ----------------------------------------------------------------------------- counting


def count(n: int, one: str, many: str) -> str:
    """A number and its noun, agreeing as Romanian counts: «1 buget activ», «2 bugete active»,
    «20 de bugete active», «101 bugete active». The same rule `main.js`'s `countLabel` follows,
    so the page and the backend never count the same thing two ways."""
    value = int(n)
    if abs(value) == 1:
        return f"{value} {one}"
    rest = abs(value) % 100
    joiner = " de" if abs(value) >= 20 and (rest == 0 or rest >= 20) else ""
    return f"{value}{joiner} {many}"


def decimal(value: float, places: int = 2) -> str:
    """A number as Romanian writes it: a comma before the decimals («0,53»)."""
    return f"{value:.{places}f}".replace(".", ",")


def _words(table: Mapping[str, str], code: object) -> str:
    """The word for a code; a code nobody named, lower-cased with spaces, never guessed."""
    text = str(code or "").strip()
    if not text:
        return "—"
    return table.get(text.upper(), text.replace("_", " ").lower())


# ----------------------------------------------------------------------------- the day's run

#: The daily run's stages, named as the register names them (`ledger.js` RUN_STAGE_LABEL).
STAGE_NAMES = {
    "preflight": "verificarea preliminară",
    "performance_intake": "preluarea performanței",
    "idea_generation": "generarea de idei",
    "research_and_verification": "documentare și verificare",
    "selection": "alegerea subiectului",
    "script_and_storyboard": "scenariu și storyboard",
    "media": "producție media",
    "edit_and_qc": "montaj și controlul calității",
    "publish": "publicare",
    "post_run": "raportare și închiderea zilei",
    "daily_log": "jurnalul zilei",
    "serial_queue": "episodul din serial",
    "serial_next": "scenariul de mâine",
    "previous_day_log": "jurnalul zilei de ieri",
    "books": "închiderea contabilă",
}


def stage_name(code: object) -> str:
    """A stage of the day in the register's words: ``post_run`` → «raportare și închiderea
    zilei»."""
    text = str(code or "").strip()
    return STAGE_NAMES.get(text, text.replace("_", " "))


def stage_list(codes: Iterable[object]) -> str:
    """Several stages, each in guillemets: «alegerea subiectului», «publicare»."""
    return ", ".join(f"«{stage_name(code)}»" for code in codes)


#: A stage or a run (etapă, rulare: feminine). The glossary's list.
STAGE_STATUS = {
    "COMPLETED": "încheiată",
    "PARTIAL": "parțială",
    "FAILED": "eșuată",
    "BLOCKED": "blocată",
    "SKIPPED": "sărită",
    "SUCCEEDED": "reușită",
    "RUNNING": "în curs",
    "QUEUED": "în așteptare",
    "STATUS": "raportată",
    "ESCALATE": "escaladată",
}


def stage_status(code: object) -> str:
    return _words(STAGE_STATUS, code)


# ----------------------------------------------------------------------------- the Owner's policy

#: The autonomy modes, as the governance panel names them (`governance.js` MODE_LABEL).
AUTONOMY_MODE = {
    "MANUAL": "manual",
    "SUPERVISED": "supravegheat",
    "AUTONOMOUS_CEO": "CEO autonom",
}


def autonomy_mode(code: object) -> str:
    return _words(AUTONOMY_MODE, code)


#: The studio's environment, said as a place the day runs in: «în mediul de test».
ENVIRONMENT = {"TEST": "mediul de test", "PRODUCTION": "producție"}


def environment(code: object) -> str:
    return _words(ENVIRONMENT, code)


# ----------------------------------------------------------------------------- money

#: A budget's period (bugetul zilnic / lunar: masculine adjective).
BUDGET_PERIOD = {"DAILY": "zilnic", "MONTHLY": "lunar"}

#: A budget's state (`dialog_words.js` budgetStateWord).
BUDGET_STATE = {
    "OK": "în limită",
    "WARN": "peste avertizare",
    "WARNING": "peste avertizare",
    "EXCEEDED": "peste limită",
    "BLOCKED": "peste limită",
}


def budget_period(code: object) -> str:
    return _words(BUDGET_PERIOD, code)


def budget_state(code: object) -> str:
    return _words(BUDGET_STATE, code)


# ----------------------------------------------------------------------------- the work

#: A script or a storyboard's own state (scenariul, storyboardul: masculine / neuter).
WORK_STATUS = {
    "DRAFT": "ciornă",
    "APPROVED": "aprobat",
    "REJECTED": "respins",
    "RENDERING": "se randează",
    "RENDERED": "randat",
    "FAILED": "eșuat",
}


def work_status(code: object) -> str:
    return _words(WORK_STATUS, code)


#: A review's verdict (recenzia: feminine) — the story review, the narration review.
REVIEW_VERDICT = {
    "PASS": "trecută",
    "REVISE": "de revizuit",
    "REJECT": "respinsă",
    "BLOCKED": "blocată",
    "FLAG": "semnalată",
    "FAIL": "respinsă",
}


def review_verdict(code: object) -> str:
    return _words(REVIEW_VERDICT, code)


#: The Director's viewing of a finished film (the film: masculine).
VIEWING_VERDICT = {"APPROVE": "aprobat", "REJECT": "respins", "REVISE": "de refăcut"}


def viewing_verdict(code: object) -> str:
    return _words(VIEWING_VERDICT, code)


#: The Publisher's word on a film's metadata.
PUBLICATION_VERDICT = {"READY": "gata de publicare", "HOLD": "ținut în așteptare"}


def publication_verdict(code: object) -> str:
    return _words(PUBLICATION_VERDICT, code)


#: A publication's state (the film on the channel: masculine; `dialog_words.js`).
PUBLICATION_STATUS = {
    "PUBLISHED": "publicat",
    "REMOTE_CONFIRMED": "publicat, confirmat de YouTube",
    "SCHEDULED": "programat",
    "STARTED": "în curs",
    "PUBLISHED_SIMULATED": "simulat, nepublicat",
    "VALIDATED": "validat, neîncărcat",
    "FAILED_RETRYABLE": "eșuat, se reîncearcă",
    "FAILED_FINAL": "eșuat definitiv",
    "REMOTE_UNKNOWN": "necunoscut la YouTube",
}


def publication_status(code: object) -> str:
    return _words(PUBLICATION_STATUS, code)


#: YouTube's privacy of a film (masculine).
PRIVACY = {"PUBLIC": "public", "UNLISTED": "nelistat", "PRIVATE": "privat"}


def privacy(code: object) -> str:
    return _words(PRIVACY, code)


#: A provider's adapter code, as the product it is (glossary: product names never translated).
PROVIDER_PRODUCT = {
    "ELEVENLABS": "ElevenLabs",
    "OPENAI_IMAGES": "OpenAI",
    "RUNWAY": "Runway",
    "RUNWAY_IMAGES": "Runway",
    "YOUTUBE_ANALYTICS": "YouTube Analytics",
}


def provider_name(code: object) -> str:
    text = str(code or "").strip()
    return PROVIDER_PRODUCT.get(text.upper(), text or "—")


# ----------------------------------------------------------------------------- the publishing gate

#: The quality-control verdict, said after a colon as the glossary says it: «controlul
#: calității: a trecut». ``MISSING`` is the gate's own word for a film nobody checked.
QC_STATUS = {
    "PASSED": "a trecut",
    "FAILED": "nu a trecut",
    "PENDING": "în așteptare",
    "MISSING": "lipsește",
}


def qc_status(code: object) -> str:
    return _words(QC_STATUS, code)


#: The Owner's global stop, said once for every door that refuses under it: the publishing
#: gate, the media gate and the policy kernel an employee's run passes through.
AUTONOMY_STOPPED = "Autonomia studioului este oprită; numai Proprietarul o poate reporni."

#: A media connection that is chosen and verified, yet gives no generator: its stored key is
#: empty or cannot be used. The readiness check reads rows and calls it ready; the adapter is
#: what refuses. W31: the preflight printed only its tail («Până atunci …»), a sentence with no
#: subject. The purpose is the readiness label («Imagini», «Voce / TTS»).
MEDIA_KEY_UNUSABLE = (
    "{name} este ales și verificat pentru {purpose}, dar cheia lui lipsește sau nu poate fi "
    "folosită. Salveaz-o din nou în Setări → Video și sunet."
)

# ----------------------------------------------------------------------------- research

#: Why a site's last reading test failed, as the sources list says it (`main.js`
#: HOST_REASON_LABEL; «OTHER» there reads «a răspuns cu nimic utilizabil», said here with its
#: negation).
HOST_TEST_REASON = {
    "HTTP_403": "a refuzat studioul (403)",
    "HTTP_ERROR": "a răspuns cu o eroare",
    "RATE_LIMITED": "limitează cererile",
    "SCRIPT_ONLY": "nu arată nimic fără JavaScript",
    "NETWORK": "nu a răspuns",
    "OTHER": "nu a răspuns cu nimic utilizabil",
}


def host_test_reason(code: object) -> str:
    return _words(HOST_TEST_REASON, code)


_HTTP_STATUS_IN_TEXT = re.compile(r"\bHTTP (\d{3})\b")

#: What the retriever's own English says (`app.research.retrieval`), as a sentence for the
#: Owner. Tried in order; the first fragment found in the retriever's text wins. W31: sixteen
#: sites of the Owner's list read «Source returned HTTP 403» on the Research door.
_HOST_FAILURE_WORDS = (
    ("deadline", "Site-ul nu a răspuns la timp."),
    ("network, TLS", "Conexiunea la site a eșuat (rețea, TLS sau decodare)."),
    (
        "DNS must resolve",
        "Numele site-ului duce și la adrese care nu sunt publice, deci studioul nu îl citește.",
    ),
    # W33: an allowed host is tested at https://<host>/, which passes these rules, so each of
    # the three below is an address the site sent the studio on to — not the Owner's entry.
    (
        "disallowed source URL",
        "Site-ul duce la o adresă scrisă într-o formă pe care studioul nu o citește.",
    ),
    ("URL contains", "Site-ul duce la o adresă cu caractere nepermise sau prea lungă."),
    (
        "HTTPS hosts",
        "Site-ul trimite mai departe la o adresă din afara listei tale sau care nu este HTTPS "
        "public, pe portul 443.",
    ),
    ("redirect", "Site-ul trimite mai departe fără adresă sau de prea multe ori."),
    ("not supported HTML", "Site-ul nu răspunde cu o pagină HTML sau text."),
    ("Compressed", "Site-ul trimite doar răspunsuri comprimate, pe care studioul nu le citește."),
    ("ended before", "Răspunsul site-ului s-a oprit înainte de sfârșit."),
    ("size limit", "Pagina depășește mărimea pe care studioul o citește."),
    ("empty, too short", "Pagina nu are text de citit sau are mai mult decât citește studioul."),
    ("did not produce", "Site-ul nu a dat nicio pagină."),
)


def host_test_detail(reason: object, raw: str = "", retry_after: str | None = None) -> str:
    """Why a site's reading test failed, as a full Romanian sentence for the Research door.

    ``reason`` is the closed code the record keeps (`HOST_TEST_REASON`), ``raw`` the
    retriever's own text — never printed, only read for the status and the kind of fault.
    """
    code = str(reason or "").strip().upper()
    text = raw or ""
    found = _HTTP_STATUS_IN_TEXT.search(text)
    status = found.group(1) if found else None
    if code == "HTTP_403":
        return (
            "Site-ul a refuzat cererea studioului (HTTP 403); cât timp o refuză, nu poate fi sursă."
        )
    if code == "RATE_LIMITED":
        said = "Site-ul limitează cererile (HTTP 429)."
        wait = (retry_after or "").strip()
        if wait:
            said += (
                f" Cere o pauză de {count(int(wait), 'secundă', 'secunde')}."
                if wait.isdigit()
                else f" Cere o pauză până la {wait}."
            )
        return said
    if code == "HTTP_ERROR":
        return (
            f"Site-ul a răspuns cu eroarea HTTP {status}."
            if status
            else "Site-ul a răspuns cu o eroare."
        )
    for fragment, said in _HOST_FAILURE_WORDS:
        if fragment in text:
            return said
    if code == "NETWORK":
        return "Conexiunea la site a eșuat (rețea, TLS sau decodare)."
    if code == "SCRIPT_ONLY":
        return "Pagina se afișează doar cu JavaScript, iar studioul citește HTML-ul servit."
    return "Site-ul nu a dat o pagină pe care studioul o poate citi."


# ----------------------------------------------------------------------------- YouTube

#: What a Google grant lets the studio do, by the scope's last part (`scope_label`). The
#: scope itself stays in the preflight line's ``technical`` record, for a tooltip.
YOUTUBE_SCOPE = {
    "youtube.readonly": "citirea canalului",
    "youtube.upload": "încărcarea filmelor",
    "yt-analytics.readonly": "statisticile",
    "youtube": "administrarea canalului",
    "youtube.force-ssl": "administrarea canalului",
}


def youtube_scope(label: object) -> str:
    """A scope said as what it lets the studio do; a scope nobody named passes through."""
    text = str(label or "").strip()
    return YOUTUBE_SCOPE.get(text, text or "—")


#: Whether a web search engine is verified, as a fact in a list: «…, niciun motor de căutare
#: verificat, …».
SEARCH_ENGINE = {
    "VERIFIED": "un motor de căutare verificat",
    "NONE": "niciun motor de căutare verificat",
}


def search_engine(code: object) -> str:
    return _words(SEARCH_ENGINE, code)


# ----------------------------------------------------------------------------- the company

#: A Director's decision, as an imperative to whoever acts (`dialog_words.js` decisionWord).
DECISION = {
    "SCALE": "Extinde",
    "CONTINUE": "Continuă",
    "ITERATE": "Corectează",
    "EXPERIMENT": "Experimentează",
    "HOLD": "Așteaptă",
    "COOLDOWN": "Pauză",
    "REDUCE": "Reduce",
    "STOP": "Oprește",
    "NEEDS_MORE_DATA": "Mai multe date",
}


def decision(code: object) -> str:
    text = str(code or "").strip()
    return DECISION.get(text.upper(), text.replace("_", " ").capitalize() or "—")


#: Confidence (încrederea: feminine).
CONFIDENCE = {"LOW": "scăzută", "MEDIUM": "medie", "HIGH": "ridicată"}


def confidence(code: object) -> str:
    return _words(CONFIDENCE, code)


#: A stage of the company's pipeline, where the bottleneck is named (`pipelineStageWord`).
PIPELINE_STAGE = {
    "RESEARCH": "cercetare",
    "WRITING": "scriere",
    "APPROVAL": "aprobare",
    "PRODUCTION": "producție",
    "PUBLISHING": "publicare",
}


def pipeline_stage(code: object) -> str:
    return _words(PIPELINE_STAGE, code)


#: What limits a channel's growth.
CONSTRAINT = {
    "NO_DATA": "fără date",
    "NONE_VISIBLE": "nicio limită vizibilă",
    "REACH": "acoperirea",
    "RETENTION": "retenția",
    "CONVERSION": "conversia",
    "TOPIC_SELECTION": "alegerea subiectelor",
}


def constraint(code: object) -> str:
    return _words(CONSTRAINT, code)


#: Why a film underperformed, as a cause.
DIAGNOSIS = {
    "REACH_FAILURE": "acoperire slabă",
    "HOOK_OR_RETENTION_FAILURE": "deschidere sau retenție slabă",
    "CONVERSION_FAILURE": "conversie slabă",
    "TOPIC_FAILURE": "subiect slab",
    "INSUFFICIENT_DATA": "date insuficiente",
}


def diagnosis(code: object) -> str:
    return _words(DIAGNOSIS, code)


#: An anomaly, as the start of a sentence.
ANOMALY = {
    "RETENTION_DROP": "Retenție în scădere",
    "VIEW_SPIKE": "Vizionări neobișnuit de multe",
    "COST_SPIKE": "Cost neobișnuit de mare",
}


def anomaly(code: object) -> str:
    text = str(code or "").strip()
    return ANOMALY.get(text.upper(), text.replace("_", " ").capitalize() or "—")


# ----------------------------------------------------------------------------- what went wrong

#: The marks of a sentence the studio wrote in Romanian: its diacritics or its commonest words.
#: An exception carrying one was raised with a reason written for the Owner (a refused script,
#: a verdict the agent could not give) and is said as written; any other text is a library's.
_ROMANIAN_MARKS = re.compile(r"[ăâîșțşţĂÂÎȘȚŞŢ]")
_ROMANIAN_WORDS = re.compile(
    r"\b(și|este|sunt|nu|pentru|niciun|nicio|fără|după|care|agentul|scenariul|răspunsul)\b",
    re.IGNORECASE,
)
_HTTP_IN_TEXT = re.compile(r"\bHTTP (\d{3})\b")

#: The studio's exception classes whose text is a vendor's or a library's English, in the order
#: they are tried (a subclass before its parent): what each one means for the Owner.
_CLASS_WORDS = (
    ("MediaProviderNotConfigured", "furnizorul nu este configurat (lipsește cheia sau modelul)"),
    ("MediaProviderError", "furnizorul a refuzat sau a oprit lucrarea"),
    ("RenderEngineUnavailable", "motorul de randare nu a putut rula"),
    ("RenderStopped", "randarea a fost oprită"),
    ("PublisherNotConfigured", "publicarea nu este configurată pentru acest canal"),
    ("PublishingGateError", "poarta de publicare a refuzat materialul"),
    ("RemoteStateUnavailable", "starea de pe platformă nu a putut fi citită"),
)


def _status_of(exc: BaseException) -> int | None:
    for attribute in ("http_status", "status", "status_code", "code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
            return value
    found = _HTTP_IN_TEXT.search(str(exc))
    return int(found.group(1)) if found else None


def written_for_the_owner(text: str) -> bool:
    """Whether a message is a Romanian sentence the studio wrote, not a library's text."""
    sample = text or ""
    return bool(_ROMANIAN_MARKS.search(sample)) or len(_ROMANIAN_WORDS.findall(sample)) >= 2


def _chain(exc: BaseException) -> list[BaseException]:
    seen: set[int] = set()
    links: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        links.append(current)
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    return links


def error_words(exc: BaseException) -> str:
    """What went wrong, said for the Owner, without a full stop.

    The studio's own Romanian reason when the exception carries one; otherwise the kind of
    fault in Romanian — a busy database, a provider's HTTP answer, a network that did not
    answer — and never a library's raw text. The class and the raw text belong in structured
    fields (`error_fields`), where a person diagnosing it reads them.
    """
    text = str(exc).strip()
    first_line = text.splitlines()[0].strip() if text else ""
    if first_line and written_for_the_owner(first_line):
        return first_line.rstrip(".")[:300]
    names = {type(link).__name__ for link in _chain(exc)}
    lowered = text.lower()
    if "OperationalError" in names and ("locked" in lowered or "busy" in lowered):
        return "baza de date era ocupată de o altă scriere"
    if names & {"IntegrityError", "DatabaseError", "DataError"}:
        return "baza de date a refuzat scrierea"
    if "OperationalError" in names:
        return "baza de date nu a putut fi folosită"
    status = next((s for s in (_status_of(link) for link in _chain(exc)) if s is not None), None)
    if status is not None:
        if status == 429:
            return f"furnizorul a cerut o pauză (HTTP {status})"
        if status >= 500:
            return f"furnizorul a avut o eroare de partea lui (HTTP {status})"
        if status in (401, 403):
            return f"furnizorul a refuzat accesul (HTTP {status})"
        return f"furnizorul a refuzat cererea (HTTP {status})"
    if names & {"TimeoutError", "ReadTimeout", "ConnectTimeout", "timeout"} or getattr(
        exc, "unanswered", False
    ):
        return "furnizorul nu a răspuns la timp"
    if names & {
        "ConnectionError",
        "URLError",
        "gaierror",
        "herror",
        "ConnectionRefusedError",
    } or getattr(exc, "unsent", False):
        return "furnizorul nu a putut fi contactat"
    # The studio's own exception classes whose messages are still English: said by what they
    # are. The class and the English text stay in `error_fields`.
    for name, said in _CLASS_WORDS:
        if name in names:
            return said
    if any("Provider" in name for name in names):
        return "furnizorul a refuzat sau a oprit lucrarea"
    if names & {"JSONDecodeError", "ValidationError"}:
        return "răspunsul primit nu a avut forma cerută"
    return "o eroare neașteptată în codul studioului"


def sentence(clause: str) -> str:
    """A clause as a sentence: its first letter up, one full stop at its end."""
    text = (clause or "").strip().rstrip(".")
    return f"{text[:1].upper()}{text[1:]}." if text else ""


def clause(text: str) -> str:
    """A sentence as a clause to follow a colon: its first letter down, no full stop. A
    name or an acronym at its start (two capitals) keeps its case."""
    body = (text or "").strip().rstrip(".")
    if len(body) > 1 and body[1].isupper():
        return body
    return f"{body[:1].lower()}{body[1:]}"


def error_fields(exc: BaseException) -> dict[str, str]:
    """The fault as data: its class and its own text, for whoever diagnoses it."""
    return {"error_class": type(exc).__name__, "error_detail": str(exc)[:500]}
