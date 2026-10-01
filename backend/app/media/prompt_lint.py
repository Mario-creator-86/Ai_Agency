"""prompt_lint: read every prompt before a credit is priced or spent.

The Nepal film (storyboard 1d530880, 2026-09-26) sent the image model and the video model
the same template text: enum codes ("NEPAL_CLIMATE_CRISIS"), a hex palette, "Camera: medium
shot, locked camera" on every scene, an 8-item "Avoid:" list, a bar chart and a black screen
asked of a photo generator, and never the bible's "No human faces" rule. Each of those is a
finding here, so the shooting sheet can show it to the Owner and the purchase steps refuse
to price a film with an open BLOCK.

The module is pure text: no database, no provider, no network. Every finding carries its
code, severity, scene, the offending substring as evidence and a Romanian message that
quotes that evidence. BLOCK stops the pricing and purchase steps; WARN is shown only.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.wording import count as count_ro

BLOCK = "BLOCK"
WARN = "WARN"

LIVE = "LIVE"
CARD_KINDS = ("DATA_CARD", "TITLE_CARD", "BLACK")
SCENE_KINDS = (LIVE, *CARD_KINDS)

# The motion prompt's last sentence. veo takes its exclusions as negativePrompt nouns, so
# its promptText ends before the "No ..." sentence.
MOTION_CLOSING = "Continuous, seamless shot. No subtitles, no on-screen text."
VEO_MOTION_CLOSING = "Continuous, seamless shot."

# Runway's promptText maxLength, when the contract does not state one.
DEFAULT_PROMPT_MAX_UTF16 = 1000

STILL_WORDS = (60, 120)
MOTION_WORDS = (20, 70)
MAX_INLINE_EXCLUSIONS = 2
EVIDENCE_CHARS = 120

# The camera-move enum of the motion prompt, each with the spellings that mean it.
CAMERA_MOVES: dict[str, str] = {
    "static": (
        r"\bstatic(?:\s+(?:camera|shot|frame))?\b|\blocked[- ]?(?:off\s+)?camera\b"
        r"|\blocked[- ]off\b|\bcamera\s+(?:is\s+|stays\s+|remains\s+)?locked\b"
    ),
    "slow push-in": r"(?:\b(?:slow|gentle|steady|fast|quick)\s+)?\b(?:push[- ]in|dolly[- ]in)\b",
    "slow pull-back": (
        r"(?:\b(?:slow|gentle|steady|fast|quick)\s+)?\b(?:pull[- ]back|pull[- ]out|dolly[- ]out)\b"
    ),
    "slow pan left": r"(?:\b(?:slow|gentle|steady|fast|quick)\s+)?\bpan(?:s|ning)?\s+left\b",
    "slow pan right": r"(?:\b(?:slow|gentle|steady|fast|quick)\s+)?\bpan(?:s|ning)?\s+right\b",
    "tilt up": r"(?:\b(?:slow|gentle|steady)\s+)?\btilt(?:s|ing)?\s+up\b",
    "tilt down": r"(?:\b(?:slow|gentle|steady)\s+)?\btilt(?:s|ing)?\s+down\b",
    "aerial drift forward": (
        r"\baerial\s+drift(?:s|ing)?(?:\s+forward)?\b|\bdrone\s+(?:drift|glide)s?\s+forward\b"
    ),
    "pedestal up": r"\bpedestal\s+up\b|\bcrane\s+up\b",
    "slow orbit": (
        r"(?:\b(?:slow|gentle|steady|fast)\s+)?\borbit(?:s|ing)?\b|\barc(?:s|ing)?\s+around\b"
    ),
}

SHOT_SIZE = re.compile(
    r"\b(extreme\s+wide|wide|medium|close[- ]up|detail|establishing|aerial|macro|full)"
    r"\s+(?:shot|view|angle)\b",
    re.IGNORECASE,
)

SPEED_WORDS = re.compile(
    r"\b(?:slow(?:ly)?|gentle|gently|steady|steadily|calm(?:ly)?|subtle|measured|unhurried"
    r"|fast|quick(?:ly)?|brisk)\b",
    re.IGNORECASE,
)
ENVIRONMENT_MOTION = re.compile(
    r"\b(?:drift\w*|wind|breeze|flow\w*|dust|clouds?|mist|fog|rain\w*|water|smoke|leaves"
    r"|ripple\w*|sway\w*|waves?|snow\w*|steam|haze|grass|current|flicker\w*|stream\w*)\b",
    re.IGNORECASE,
)

ENUM_CODE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
HEX_CODE = re.compile(r"#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b")
TEMPLATE_LABEL = re.compile(
    r"(?:^|(?<=[.;\n]))\s*((?:Environment|Camera|Lighting|Composition|Motion|Style|Palette"
    r"|Subject|Action|Mood|Shot|Lens|Setting|Scene|Colou?rs?|Quality):)",
)
BLOCKING_LABELS = ("Camera:", "Motion:")
AVOID_LIST = re.compile(
    r"\b(?:Avoid|Negative(?:\s+prompt)?|Do\s+not\s+include|Don't\s+include|Exclude)\s*:",
    re.IGNORECASE,
)
INLINE_EXCLUSION = re.compile(r"\b(?:no|without)\s+[\w-]+", re.IGNORECASE)
QUOTED = re.compile(r"\"[^\"\n]{1,80}\"|“[^”\n]{1,80}”|„[^”\n]{1,80}”|(?<!\w)'[^'\n]{1,60}'(?!\w)")
THEN_CHAIN = re.compile(
    r"\bthen\b|\bnext,|\bafter\s+that\b|\bafterwards\b|\bfollowed\s+by\b", re.IGNORECASE
)
NEGATION = re.compile(r"\b(?:no|not|without|never|avoid|don't|do\s+not)\s+[\w-]+", re.IGNORECASE)

# Phrases that ask for something a photo or video generator cannot draw truthfully. They
# force the scene's kind: the Nepal bar chart (100 vs 83) and black screen became women.
KIND_PHRASES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "DATA_CARD",
        re.compile(
            r"\bbar\s+(?:chart|graph)s?\b|\b(?:pie\s+)?charts?\b|\bgraphs?\b|\binfographics?\b"
            r"|\bdiagrams?\b|\b(?:vertical|horizontal)\s+bars?\b|\bbars\b|\bper\s?cent\b"
            r"|\d+(?:[.,]\d+)?\s?%",
            re.IGNORECASE,
        ),
    ),
    (
        "BLACK",
        re.compile(
            r"\bblack\s+(?:screen|frame)\b|\bfades?\s+(?:out\s+)?to\s+black\b|\bfade[- ]out\b"
            r"|\bscreen\s+(?:goes|turns|cuts\s+to)\s+black\b|\bcut\s+to\s+black\b",
            re.IGNORECASE,
        ),
    ),
    (
        "TITLE_CARD",
        re.compile(r"\btitle(?:\s+(?:card|screen))?\b|\bend\s+card\b", re.IGNORECASE),
    ),
)

PERSON = re.compile(
    r"\b(?:person|persons|people|man(?!-)|men|woman|women|farmers?|villagers?|child|children"
    r"|kids?|boys?|girls?|workers?|famil(?:y|ies)|crowds?|mothers?|fathers?|elders?"
    r"|residents?|officials?|protesters?|students?|herders?|porters?|sherpas?|climbers?"
    r"|victims?|survivors?|rescuers?|volunteers?|locals|figures?(?!\s*\d)|pedestrians?"
    r"|shepherds?|monks?|laborers?|labourers?|refugees?|citizens?|soldiers?|nurses?"
    r"|doctors?|fishermen|fisherman|traders?|vendors?)\b",
    re.IGNORECASE,
)
FACE_HIDDEN = re.compile(
    r"\bfrom\s+behind\b|\bfrom\s+(?:high\s+)?above\b|\bsilhouett\w*|\bdistant\b"
    r"|\bin\s+the\s+distance\b|\bfar\s+away\b|\bhands\s+only\b|\bonly\s+(?:their\s+|his\s+"
    r"|her\s+)?hands\b|\bbacks?\s+to\s+the\s+camera\b|\bfaces?\s+(?:not\s+visible|hidden"
    r"|obscured|turned\s+away|out\s+of\s+frame)\b|\bno\s+(?:visible\s+)?faces?\b|\bfaceless\b",
    re.IGNORECASE,
)
FACE_SHOWN = re.compile(
    r"\b(?:faces?|facial\s+expressions?)\s+(?:clearly\s+)?(?:visible|shown|in\s+focus)\b"
    r"|\bclose[- ]?up\s+(?:of|on)\s+(?:a\s+|the\s+|his\s+|her\s+|their\s+)?faces?\b"
    r"|\blooking\s+(?:at|into)\s+the\s+(?:camera|lens)\b|\bportraits?\b|\bsmiling\b"
    r"|\bfacial\s+expressions?\b|\bfaces?\s+close[- ]?up\b",
    re.IGNORECASE,
)
# The prompt says outright that no face is seen.
NO_FACE_STATED = re.compile(
    r"\bno\s+(?:human\s+|visible\s+)?faces?\b|\bfaces?\s+(?:not\s+visible|hidden|obscured"
    r"|turned\s+away|out\s+of\s+frame|never\s+visible)\b|\bfaceless\b"
    r"|\bwithout\s+(?:visible\s+|human\s+)?faces\b|\bno\s+(?:people|person|figures|humans)\b"
    r"|\bempty\s+of\s+people\b|\bunpeopled\b",
    re.IGNORECASE,
)
# A bible rule (continuity rule or avoid item) that forbids faces.
BIBLE_NO_FACES = re.compile(
    r"\bno\s+(?:human\s+|visible\s+|recogni[sz]able\s+)?faces?\b|\bfaceless\b"
    r"|\bfaces?\s+(?:never|must\s+not|should\s+not|do\s+not|don't)\s+(?:appear|be\s+(?:visible"
    r"|shown|seen))\b|\bwithout\s+(?:human\s+)?faces\b",
    re.IGNORECASE,
)
BIBLE_AVOID_FACES = re.compile(
    r"^\s*(?:visible\s+|human\s+|recogni[sz]able\s+|any\s+)*faces?(?:\s+visible)?\s*$",
    re.IGNORECASE,
)

KIND_RO = {
    "DATA_CARD": "grafic (DATA_CARD)",
    "TITLE_CARD": "titlu (TITLE_CARD)",
    "BLACK": "ecran negru (BLACK)",
}
WHERE_RO = {"still": "imaginii", "motion": "de mișcare"}


@dataclass(frozen=True)
class Finding:
    """One thing wrong with a prompt, told to the Owner in Romanian."""

    code: str
    severity: str
    scene: int | None
    evidence: str
    message_ro: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "scene": self.scene,
            "evidence": self.evidence,
            "message_ro": self.message_ro,
        }


@dataclass(frozen=True)
class LintScene:
    """A scene as the linter sees it: its kind and the two prompts that would be sent."""

    scene: int
    kind: str = LIVE
    still_prompt: str = ""
    motion_prompt: str = ""
    model_id: str | None = None
    contract: Mapping[str, Any] | None = None


class PromptLintBlocked(Exception):
    """Raised by require_no_block: a BLOCK finding is open, nothing may be priced or bought."""

    def __init__(self, findings: Sequence[Finding]) -> None:
        self.findings = [f for f in findings if f.severity == BLOCK]
        super().__init__(summary_ro(self.findings))


# --- helpers ---------------------------------------------------------------------------------


def utf16_units(text: str) -> int:
    """Length as the vendors count it (JavaScript string length)."""
    return len(text.encode("utf-16-le")) // 2


def _index_at_units(text: str, limit: int) -> int:
    """The character index where the first UTF-16 unit past `limit` begins."""
    used = 0
    for index, char in enumerate(text):
        used += 2 if ord(char) > 0xFFFF else 1
        if used > limit:
            return index
    return len(text)


def _words(text: str) -> int:
    return len(text.split())


def _excerpt(text: str, limit: int = EVIDENCE_CHARS) -> str:
    """A verbatim prefix of the text: its first sentence, cut at a whole word."""
    stripped = text.strip()
    first = re.split(r"(?<=[.!?])\s", stripped, maxsplit=1)[0]
    if len(first) <= limit:
        return first
    cut = first.rfind(" ", 0, limit)
    return first[: cut if cut > 0 else limit]


def _last_sentence(text: str) -> str:
    parts = [p for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]
    return parts[-1] if parts else text.strip()


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _distinct(matches: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for match in matches:
        if match not in seen:
            seen.append(match)
    return seen


def _others(values: list[str], shown: int = 3) -> str:
    """Romanian tail naming the other offending values, e.g. ' (și încă: „A”, „B”)'."""
    rest = values[1:]
    if not rest:
        return ""
    listed = ", ".join(f"„{value}”" for value in rest[:shown])
    more = (
        f" și {count_ro(len(rest) - shown, 'altă valoare', 'alte valori')}"
        if len(rest) > shown
        else ""
    )
    return f" (și încă: {listed}{more})"


def model_family(model_id: str | None) -> str | None:
    if not model_id:
        return None
    lowered = model_id.lower()
    for family in ("veo", "seedance", "wan", "gen4", "seedream"):
        if lowered.startswith(family):
            return family
    return None


def prompt_cap(contract: Mapping[str, Any] | None, target: str) -> int:
    """The promptText limit in UTF-16 units from a contract, else Runway's 1000."""
    if not contract:
        return DEFAULT_PROMPT_MAX_UTF16
    for key in ("prompt_max_utf16", "prompt_max"):
        value = contract.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, Mapping):
            task = "text_to_image" if target == "still" else "image_to_video"
            chosen = value.get(task)
            if isinstance(chosen, int) and not isinstance(chosen, bool) and chosen > 0:
                return chosen
            numbers = [
                v
                for v in value.values()
                if isinstance(v, int) and not isinstance(v, bool) and v > 0
            ]
            if numbers:
                return min(numbers)
    return DEFAULT_PROMPT_MAX_UTF16


def classify_kind_phrase(text: str) -> tuple[str, str] | None:
    """(kind, evidence) for the earliest phrase that forces a composed scene, else None."""
    best: tuple[int, str, str] | None = None
    for kind, pattern in KIND_PHRASES:
        match = pattern.search(text)
        if match and (best is None or match.start() < best[0]):
            best = (match.start(), kind, match.group(0))
    if best is None:
        return None
    return best[1], best[2]


def bible_face_rule(bible: Mapping[str, Any] | None) -> str | None:
    """The bible's own words when it forbids faces, else None."""
    if not isinstance(bible, Mapping):
        return None
    rules: list[str] = []
    for key in ("continuity_rules", "rules", "people_rule"):
        value = bible.get(key)
        if isinstance(value, str):
            rules.append(value)
        elif isinstance(value, (list, tuple)):
            rules.extend(str(item) for item in value if item)
    for rule in rules:
        if BIBLE_NO_FACES.search(rule):
            return rule
    avoid = bible.get("avoid")
    if isinstance(avoid, (list, tuple)):
        for item in avoid:
            text = str(item)
            if BIBLE_AVOID_FACES.match(text) or BIBLE_NO_FACES.search(text):
                return text
    return None


def camera_moves(text: str) -> list[tuple[str, str]]:
    """Distinct camera moves named in a motion prompt, as (enum value, text as written)."""
    found: list[tuple[int, str, str]] = []
    for move, pattern in CAMERA_MOVES.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            found.append((match.start(), move, match.group(0).strip()))
    found.sort()
    return [(move, written) for _, move, written in found]


def shot_size(text: str) -> tuple[str, str] | None:
    """(size, text as written) of the first shot size the still prompt names."""
    match = SHOT_SIZE.search(text)
    if not match:
        return None
    size = " ".join(match.group(1).lower().replace("close up", "close-up").split())
    return size, match.group(0)


def _person_mentions(text: str) -> list[tuple[str, bool]]:
    """Each person the prompt shows, and whether its face is kept out of sight nearby."""
    mentions: list[tuple[str, bool]] = []
    for sentence in re.split(r"(?<=[.!?;])\s+", text):
        words = list(re.finditer(r"\S+", sentence))
        for match in PERSON.finditer(sentence):
            before = sentence[max(0, match.start() - 16) : match.start()].lower()
            if re.search(r"\b(?:no|without|not\s+a|zero)\s+(?:\w+\s+)?$", before):
                continue
            index = next(
                (i for i, word in enumerate(words) if word.start() <= match.start() < word.end()),
                0,
            )
            start = words[max(0, index - 3)].start()
            end = words[min(len(words) - 1, index + 6)].end()
            window = sentence[start:end]
            mentions.append((match.group(0), bool(FACE_HIDDEN.search(window))))
    return mentions


def _finding(code: str, severity: str, scene: int | None, evidence: str, message: str) -> Finding:
    return Finding(
        code=code, severity=severity, scene=scene, evidence=evidence.strip(), message_ro=message
    )


# --- checks shared by both prompts -----------------------------------------------------------


def _hygiene(text: str, scene: int | None, target: str, cap: int) -> list[Finding]:
    where = WHERE_RO[target]
    findings: list[Finding] = []

    codes = _distinct(match.group(0) for match in ENUM_CODE.finditer(text))
    if codes:
        findings.append(
            _finding(
                "ENUM_CODE",
                BLOCK,
                scene,
                codes[0],
                f"Promptul {where} conține codul intern „{codes[0]}”{_others(codes)}. "
                "Modelul nu înțelege coduri; scrieți în cuvinte ce trebuie să se vadă.",
            )
        )

    hexes = _distinct(match.group(0) for match in HEX_CODE.finditer(text))
    if hexes:
        findings.append(
            _finding(
                "HEX_CODE",
                BLOCK,
                scene,
                hexes[0],
                f"Promptul {where} conține culoarea în cod hex „{hexes[0]}”{_others(hexes)}. "
                "Modelul nu citește coduri de culoare; numiți culorile în cuvinte.",
            )
        )

    labels = _distinct(match.group(1) for match in TEMPLATE_LABEL.finditer(text))
    if labels:
        blocking = any(label in BLOCKING_LABELS for label in labels)
        findings.append(
            _finding(
                "TEMPLATE_LABEL",
                BLOCK if blocking else WARN,
                scene,
                labels[0],
                f"Promptul {where} are rubrica de șablon „{labels[0]}”{_others(labels)}. "
                "Scrieți o descriere firească, în fraze, fără rubrici.",
            )
        )

    avoid = AVOID_LIST.search(text)
    if avoid:
        findings.append(
            _finding(
                "AVOID_LIST",
                BLOCK,
                scene,
                avoid.group(0),
                f"Promptul {where} are o listă de interdicții „{avoid.group(0)}”. "
                "Modelele desenează adesea tocmai ce li se interzice; spuneți ce trebuie "
                "să apară.",
            )
        )

    quoted = QUOTED.search(text)
    if quoted:
        findings.append(
            _finding(
                "QUOTED_TEXT",
                BLOCK,
                scene,
                quoted.group(0),
                f"Promptul {where} conține text între ghilimele „{quoted.group(0)}”. "
                "Modelul îl va scrie pe imagine; descrieți scena fără citate.",
            )
        )

    units = utf16_units(text)
    if units > cap:
        overflow = text[_index_at_units(text, cap) :]
        shown = _excerpt(overflow, 60)
        findings.append(
            _finding(
                "OVER_CAP",
                BLOCK,
                scene,
                overflow,
                f"Promptul {where} are {units} unități, peste limita de {cap} a modelului. "
                f"Partea care nu încape începe cu „{shown}”. Promptul nu se taie: "
                "se rescrie mai scurt.",
            )
        )
    return findings


# --- the still prompt ------------------------------------------------------------------------


def lint_still_prompt(
    text: str,
    *,
    scene: int | None,
    bible: Mapping[str, Any] | None = None,
    contract: Mapping[str, Any] | None = None,
    kind: str = LIVE,
) -> list[Finding]:
    """Findings for the prompt sent to the image model for one LIVE scene."""
    findings = _hygiene(text, scene, "still", prompt_cap(contract, "still"))

    exclusions = [match.group(0) for match in INLINE_EXCLUSION.finditer(text)]
    if len(exclusions) > MAX_INLINE_EXCLUSIONS:
        findings.append(
            _finding(
                "TOO_MANY_EXCLUSIONS",
                WARN,
                scene,
                exclusions[MAX_INLINE_EXCLUSIONS],
                f"Promptul imaginii are {count_ro(len(exclusions), 'excludere', 'excluderi')}; "
                f"sunt permise cel mult "
                f"{MAX_INLINE_EXCLUSIONS}. Prima în plus: „{exclusions[MAX_INLINE_EXCLUSIONS]}”. "
                "Spuneți pozitiv ce se vede.",
            )
        )

    if kind == LIVE:
        forced = classify_kind_phrase(text)
        if forced:
            forced_kind, evidence = forced
            findings.append(
                _finding(
                    "KIND_MISMATCH",
                    BLOCK,
                    scene,
                    evidence,
                    f"Scena filmată cere „{evidence}”, ceea ce un generator de imagini nu "
                    f"desenează corect. Se compune local, gratuit, ca {KIND_RO[forced_kind]}.",
                )
            )

    rule = bible_face_rule(bible)
    if rule:
        persons = _person_mentions(text)
        shown = FACE_SHOWN.search(text)
        if shown:
            findings.append(
                _finding(
                    "FORBIDDEN_FACES",
                    BLOCK,
                    scene,
                    shown.group(0),
                    f"Promptul imaginii cere o față vizibilă („{shown.group(0)}”), deși biblia "
                    "vizuală interzice fețele.",
                )
            )
        for person, hidden in persons:
            if not hidden:
                findings.append(
                    _finding(
                        "FORBIDDEN_FACES",
                        BLOCK,
                        scene,
                        person,
                        f"Promptul imaginii arată un om („{person}”) fără să-i ascundă fața, "
                        "deși biblia vizuală interzice fețele. Adăugați lângă el „from behind”, "
                        "„distant”, „silhouette”, „seen from above” sau „hands only”.",
                    )
                )
        carried = bool(NO_FACE_STATED.search(text)) or (
            bool(persons) and not shown and all(hidden for _, hidden in persons)
        )
        if not carried:
            findings.append(
                _finding(
                    "BIBLE_RULE_MISSING",
                    BLOCK,
                    scene,
                    rule,
                    f"Biblia vizuală cere „{rule}”, dar promptul imaginii nu o spune, iar "
                    "modelul adaugă oameni cu fețe. Scrieți-o pozitiv, de exemplu „figures "
                    "small and distant, seen from behind, faces not visible”.",
                )
            )

    count = _words(text)
    low, high = STILL_WORDS
    if text.strip() and not low <= count <= high:
        findings.append(
            _finding(
                "STILL_LENGTH",
                WARN,
                scene,
                _excerpt(text),
                f"Promptul imaginii are {count_ro(count, 'cuvânt', 'cuvinte')} "
                f"(„{_excerpt(text, 60)}”); "
                f"lungimea potrivită este {low}–{high}.",
            )
        )
    return findings


# --- the motion prompt -----------------------------------------------------------------------


def lint_motion_prompt(
    text: str,
    *,
    scene: int | None,
    still_prompt: str = "",
    model_id: str | None = None,
    contract: Mapping[str, Any] | None = None,
) -> list[Finding]:
    """Findings for the promptText sent with the approved still to the video model."""
    findings = _hygiene(text, scene, "motion", prompt_cap(contract, "motion"))
    family = model_family(model_id)
    model_name = model_id or "modelul video"

    equals = (
        bool(still_prompt.strip()) and bool(text.strip()) and _norm(text) in _norm(still_prompt)
    )
    if equals:
        findings.append(
            _finding(
                "MOTION_EQUALS_STILL",
                BLOCK,
                scene,
                _excerpt(text),
                f"Promptul de mișcare repetă textul imaginii („{_excerpt(text, 80)}”). "
                "Modelul video vede deja imaginea; descrieți doar mișcarea camerei și a "
                "mediului.",
            )
        )
    elif still_prompt.strip() and text.strip():
        motion_words = _content_words(_strip_closing(text))
        still_words = _content_words(still_prompt)
        shared = [word for word in motion_words if word in still_words]
        if motion_words and len(shared) / len(motion_words) > 0.6:
            listed = ", ".join(shared[:6])
            findings.append(
                _finding(
                    "MOTION_REDESCRIBES",
                    WARN,
                    scene,
                    listed,
                    f"Promptul de mișcare redescrie imaginea (cuvinte comune: „{listed}”). "
                    "Spuneți doar ce se mișcă.",
                )
            )

    moves = camera_moves(text)
    if len(moves) != 1:
        if moves:
            evidence = ", ".join(written for _, written in moves)
            message = (
                "Promptul de mișcare are "
                f"{count_ro(len(moves), 'mișcare de cameră', 'mișcări de cameră')} "
                f"(„{evidence}”); "
                "este permisă exact una."
            )
        else:
            evidence = _excerpt(text) or "prompt gol"
            message = (
                f"Promptul de mișcare nu are nicio mișcare de cameră („{_excerpt(text, 60)}”). "
                "Alegeți exact una: " + ", ".join(CAMERA_MOVES) + "."
            )
        findings.append(_finding("CAMERA_COUNT", BLOCK, scene, evidence, message))

    if family != "veo":
        chain = THEN_CHAIN.search(text)
        if chain:
            severity = BLOCK if family == "seedance" else WARN
            findings.append(
                _finding(
                    "THEN_CHAIN",
                    severity,
                    scene,
                    chain.group(0),
                    f"Promptul de mișcare înșiră acțiuni cu „{chain.group(0)}”. Pe "
                    f"{model_name} un clip trebuie să fie o singură mișcare continuă.",
                )
            )

    if family == "veo":
        negation = NEGATION.search(text)
        if negation:
            findings.append(
                _finding(
                    "NEGATION_IN_PROMPT",
                    BLOCK,
                    scene,
                    negation.group(0),
                    f"Pe {model_name} promptul nu poate conține negații („{negation.group(0)}”); "
                    "interdicțiile merg în negativePrompt, ca substantive simple.",
                )
            )

    if text.strip():
        closing = VEO_MOTION_CLOSING if family == "veo" else MOTION_CLOSING
        if not _norm(text).endswith(_norm(closing)):
            ending = _last_sentence(text)
            findings.append(
                _finding(
                    "MOTION_CLOSING",
                    WARN,
                    scene,
                    ending,
                    f"Promptul de mișcare se încheie cu „{_excerpt(ending, 60)}” în loc de "
                    f"„{closing}”.",
                )
            )
        if not SPEED_WORDS.search(text):
            findings.append(
                _finding(
                    "MOTION_SPEED",
                    WARN,
                    scene,
                    _excerpt(text),
                    f"Promptul de mișcare nu spune viteza („{_excerpt(text, 60)}”); adăugați "
                    "un singur cuvânt, de exemplu slow sau gentle.",
                )
            )
        if not ENVIRONMENT_MOTION.search(_strip_closing(text)):
            findings.append(
                _finding(
                    "MOTION_ENVIRONMENT",
                    WARN,
                    scene,
                    _excerpt(text),
                    "Promptul de mișcare nu are nicio mișcare a mediului "
                    f"(„{_excerpt(text, 60)}”): nori care trec, vânt în iarbă, "
                    "apă care curge, praf.",
                )
            )
        count = _words(text)
        low, high = MOTION_WORDS
        if not low <= count <= high:
            findings.append(
                _finding(
                    "MOTION_LENGTH",
                    WARN,
                    scene,
                    _excerpt(text),
                    f"Promptul de mișcare are {count_ro(count, 'cuvânt', 'cuvinte')} "
                    f"(„{_excerpt(text, 60)}”); "
                    f"lungimea potrivită este {low}–{high}.",
                )
            )
    return findings


STOP_WORDS = frozenset(
    "a an the and or of to in on at with from for by as is are its it this that while into "
    "over under through across toward towards very".split()
)


def _content_words(text: str) -> list[str]:
    words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z-]+", text)]
    return _distinct(w for w in words if w not in STOP_WORDS and len(w) > 2)


def _strip_closing(text: str) -> str:
    stripped = text.strip()
    for closing in (MOTION_CLOSING, VEO_MOTION_CLOSING):
        if _norm(stripped).endswith(_norm(closing)):
            return stripped[: len(stripped) - len(closing)].strip()
    return stripped


# --- the whole film --------------------------------------------------------------------------


def lint_scene(
    scene: LintScene,
    *,
    bible: Mapping[str, Any] | None = None,
    contract: Mapping[str, Any] | None = None,
) -> list[Finding]:
    """Findings for one scene: its kind, then its prompts if it is filmed."""
    kind = (scene.kind or "").upper()
    terms = scene.contract if scene.contract is not None else contract
    if kind not in SCENE_KINDS:
        return [
            _finding(
                "KIND_UNKNOWN",
                BLOCK,
                scene.scene,
                scene.kind or "(gol)",
                f"Scena are un tip necunoscut „{scene.kind or '(gol)'}”; se acceptă doar "
                "LIVE, DATA_CARD, TITLE_CARD și BLACK.",
            )
        ]
    if kind != LIVE:
        paid = scene.still_prompt.strip() or scene.motion_prompt.strip()
        if not paid:
            return []
        return [
            _finding(
                "CARD_HAS_PROMPT",
                BLOCK,
                scene.scene,
                _excerpt(paid),
                f"Scena {scene.scene} este {KIND_RO[kind]} și se compune local, gratuit, dar "
                f"are un prompt pentru generator („{_excerpt(paid, 60)}”). Un card nu ajunge "
                "niciodată la un model plătit.",
            )
        ]
    findings: list[Finding] = []
    if not scene.still_prompt.strip():
        findings.append(
            _finding(
                "PROMPT_MISSING",
                BLOCK,
                scene.scene,
                "prompt gol",
                f"Scena filmată {scene.scene} nu are promptul imaginii („prompt gol”).",
            )
        )
    else:
        findings += lint_still_prompt(
            scene.still_prompt, scene=scene.scene, bible=bible, contract=terms, kind=kind
        )
    if scene.motion_prompt.strip():
        findings += lint_motion_prompt(
            scene.motion_prompt,
            scene=scene.scene,
            still_prompt=scene.still_prompt,
            model_id=scene.model_id,
            contract=terms,
        )
    return findings


def lint_film(
    scenes: Sequence[LintScene],
    *,
    bible: Mapping[str, Any] | None = None,
    contract: Mapping[str, Any] | None = None,
) -> list[Finding]:
    """Every scene's findings, then the film's camera language across its LIVE scenes."""
    findings: list[Finding] = []
    for scene in scenes:
        findings += lint_scene(scene, bible=bible, contract=contract)
    live = [scene for scene in scenes if (scene.kind or "").upper() == LIVE]
    moves: list[tuple[int, str, str] | None] = []
    sizes: list[tuple[int, str, str] | None] = []
    for scene in live:
        found = camera_moves(scene.motion_prompt) if scene.motion_prompt.strip() else []
        moves.append((scene.scene, found[0][0], found[0][1]) if len(found) == 1 else None)
        size = shot_size(scene.still_prompt)
        sizes.append((scene.scene, size[0], size[1]) if size else None)
    findings += _camera_language(moves, "mișcare de cameră")
    findings += _camera_language(sizes, "încadrare")
    return findings


def _camera_language(
    values: list[tuple[int, str, str] | None], what: str, run_length: int = 3
) -> list[Finding]:
    if len(values) >= run_length and all(values):
        kinds = {value[1] for value in values if value}
        if len(kinds) == 1:
            first = values[0]
            assert first is not None
            return [
                _finding(
                    "SAME_CAMERA_EVERY_SCENE",
                    BLOCK,
                    None,
                    first[2],
                    "Toate cele "
                    f"{count_ro(len(values), 'scenă filmată', 'scene filmate')} au aceeași "
                    f"{what} („{first[2]}”). "
                    "Filmul pare o singură imagine; variați încadrarea și mișcarea.",
                )
            ]
    findings: list[Finding] = []
    index = 0
    while index < len(values):
        current = values[index]
        end = index + 1
        while (
            current is not None
            and end < len(values)
            and values[end] is not None
            and values[end][1] == current[1]  # type: ignore[index]
        ):
            end += 1
        if current is not None and end - index >= run_length:
            last = values[end - 1]
            assert last is not None
            findings.append(
                _finding(
                    "SAME_CAMERA_RUN",
                    WARN,
                    current[0],
                    current[2],
                    f"Scenele {current[0]}–{last[0]} au la rând aceeași {what} "
                    f"(„{current[2]}”). Variați-o cel puțin o dată la trei scene.",
                )
            )
        index = end
    return findings


# --- the gate --------------------------------------------------------------------------------


def has_block(findings: Iterable[Finding]) -> bool:
    return any(finding.severity == BLOCK for finding in findings)


def summary_ro(findings: Sequence[Finding]) -> str:
    """One Romanian line for the sheet or a 409: counts, then the first blocking reason."""
    blocks = [f for f in findings if f.severity == BLOCK]
    warns = [f for f in findings if f.severity == WARN]
    if not blocks and not warns:
        return "Prompturile sunt în regulă."
    text = (
        f"Prompturile au {count_ro(len(blocks), 'blocaj', 'blocaje')} și "
        f"{count_ro(len(warns), 'avertisment', 'avertismente')}."
    )
    if blocks:
        first = blocks[0]
        where = f"scena {first.scene}" if first.scene is not None else "tot filmul"
        text += f" Primul blocaj ({where}): {first.message_ro}"
    return text


def require_no_block(findings: Sequence[Finding]) -> None:
    """Called before any pricing or purchase: an open BLOCK stops the step."""
    if has_block(findings):
        raise PromptLintBlocked(findings)
