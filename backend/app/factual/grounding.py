"""Whether a factual script says what its topic and its claims say.

The rehearsal on the Owner's data (2026-09-18) measured the gap this closes. The day selected
"Why Nepal Is Being Handed a Climate Bill It Cannot Pay", with verified claims about climate
finance, and the stand-in writer returned a script about the James Webb telescope. Every scene
cited the Nepal claim 0be61855 ("Most of the estimated US$83.3 billion provided to developing
countries in 2020 was targeted at mitigation..."); the factual gate saw a SUPPORTED claim and
passed it, the story review passed it, the Director approved it. The factual gate checks that
a cited claim exists and is SUPPORTED. Nothing the studio computed looked at whether the
narration says what the claim says, so only a model's judgement stood between that script and
a film.

This is the computed half of that question. It is lexical, deterministic and explained: it
does not judge meaning, it measures whether the narration rests on its own material.

- **Every cited claim is recognisably present in the voiceover.** A claim's terms are its
  content words, its numbers and its names. A claim is present when at least two of them are
  in the narration (all of them, when it has fewer than two). Two, and not a share of the
  claim: the Owner's approved LHC film says "dark matter ... doesn't glow, doesn't absorb
  light" for "dark matter does not interact with the electromagnetic force", which shares
  exactly "dark" and "matter" with its claim. A stricter bar that asked for the claim's own
  distinctive words refused that film, and a paraphrase that good is what the studio wants.
- **The voiceover is about its topic.** At least two of the terms of the topic's title and
  angle are in it (all of them, when there are fewer).
- **The voiceover is not dominated by material from nowhere.** Numbers and names are the
  content a viewer takes away as fact; when most of the narration's numbers and names appear
  in no claim and not in the topic, the film is telling someone else's story.

Why this measure survives paraphrase and translation. Words are compared by their stem —
lowercased, stripped of diacritics, and equal when they share their first five letters or when
the shorter is a prefix of the longer with at most two letters to spare — so "decaying" meets
"decay", "particles" meets "particle's", and the many cognates the studio's languages share meet
across them ("climate" / "climatice", "mitigation" / "mitigare", "universe" / "univers").
Numbers are normalised ("7,000" and "7.000" and "7 000" are 7000; "83.3" also stands as 83 when
the narration rounds it) and spelled-out numbers are read as numbers in English and Romanian,
whole ("six hundred million" is the claim's "600 million", "twenty eighteen" and "two thousand
eighteen" are 2018, "douăzeci și șase" is 26) and as ranks ("fourth", "a patra" and "4th" are
4), because a voiceover is written to be read aloud. Numbers and names are what a translation keeps
unchanged, and the audience language is English by the Owner's rule (`content_language`) while
sources may be in any language; a translated narration still carries them.

What it cannot do, said plainly: a narration that repeats two of a claim's words while
contradicting it passes this check. That is a question about meaning and it stays the
Director's; this check only makes sure she is never the one thing standing between a Nepal
topic and a telescope film. It was calibrated on every factual script the studio's real model
wrote on 2026-09-12 (31 drafts) and on the rehearsal's own case. The two the studio approved
(the LHC and ATLAS films) pass, and so do 25 of the other 29. The four refused each cite a claim
whose content the narration never says: 92028a88 cites the sunshield cooling the mirror to 40
kelvins on a scene that says "you just block it, one layer at a time"; 8d4f7306, aa3da89f and
670d6279 cite the decommissioning on Aug. 8, 2024 on a scene that says "NASA switched it off".
Those four were never approved. The rehearsal's telescope film is refused on all three counts.

A dramatisation of the office serial makes no claims about the world and is not measured here
(`is_serial_script`). A factual script this cannot measure — no claim, a claim that no longer
exists, no narration — is reported NOT_MEASURED, which is not a pass.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

PASSED = "PASSED"
REFUSED = "REFUSED"
NOT_MEASURED = "NOT_MEASURED"

#: The shortest stem that counts as a word. Three-letter words are almost all function words
#: in both languages; acronyms and numbers are kept whatever their length.
MIN_WORD = 4
#: Two stems are the same word when they share this many leading letters.
SHARED_PREFIX = 5
#: ...or when the shorter is a prefix of the longer with at most this many letters left over
#: ("live" / "lived", "hunt" / "hunted"). Two, not three: at three "bill" met "billion", and
#: the Nepal topic's "climate bill" counted as saying a claim's "US$83.3 billion".
SUFFIX_SLACK = 2
#: How many of a claim's own terms the narration has to carry for the claim to be said.
CLAIM_TERMS_NEEDED = 2
#: How many of the topic's terms the narration has to carry to be about the topic.
TOPIC_TERMS_NEEDED = 2
#: Above this share of the narration's numbers and names coming from nowhere, and with at
#: least `FOREIGN_ANCHORS_NEEDED` of them, the narration is someone else's story. The real
#: scripts of 2026-09-12 measured at most 0.40 (the ATLAS film's "48 years" and "W boson",
#: said as context around claims that carry 46 m, 7,000 tonnes and 125 GeV); the rehearsal's
#: telescope film on the Nepal topic measured 1.0.
FOREIGN_SHARE_LIMIT = 0.5
FOREIGN_ANCHORS_NEEDED = 2

SERIAL_SCRIPT_KIND = "office_serial_episode"

#: Words that carry no subject, in English and in Romanian (diacritics stripped, because the
#: comparison strips them), plus the words the studio's own briefs put into every topic angle
#: ("open with", "close on the number", "viewers"), which say how to tell a film and not what
#: it is about.
STOPWORDS = frozenset(
    """
    about above after again against also although among another anyone anything around because
    been before being below between both could does doing down during each either else even
    ever every from further have having here hers herself himself however into itself just
    least less like made make makes making many more most much must neither never nobody none
    nothing only other others ought ours ourselves over same shall should since some something
    such than that their theirs them themselves then there therefore these they this those
    though through thus till under until upon very what whatever when whenever where whether
    which while whom whose will with within without would your yours yourself yourselves cannot
    can't don't doesn't isn't it's that's there's what's won't wasn't aren't
    this story film video short viewer viewers opens open opening close closes closing ends
    ending number single asks asking follow follows watch look looks show shows tell tells
    why how who first last next today tonight still really actually simply
    us usd eur ron
    acest aceasta aceste acesti acea acel acele aceia aici acolo acum adica asupra atunci
    avea aveau avem aveti ceea cele celor cand care catre cine cineva ceva cum daca dar
    decat deci desi despre din dintre doar dupa este esti fara fata fie fiecare fost foarte
    inca intre intr intru langa mai mult multe multi niciun nicio nimic noastra nostru
    noua nici pana peste pentru poate prin sale sau sunt suntem sunteti toate toti tot
    totul unde unei unor unui vor voastra vostru
    """.split()
)

#: Number words read as numbers, in the two languages the studio works in. "One"/"un" is left
#: out: "the one number", "one idea" are almost never a count.
NUMBER_WORDS = {
    "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
    "thirteen": "13", "fourteen": "14", "fifteen": "15", "twenty": "20", "thirty": "30",
    "forty": "40", "fifty": "50", "hundred": "100", "thousand": "1000", "dozen": "12",
    "decade": "10", "decades": "10", "deceniu": "10", "decenii": "10",
    "doi": "2", "doua": "2", "trei": "3", "patru": "4", "cinci": "5", "sase": "6",
    "sapte": "7", "opt": "8", "noua": "9", "zece": "10", "unsprezece": "11",
    "doisprezece": "12", "douazeci": "20", "treizeci": "30", "suta": "100", "mie": "1000",
    # Ordinals, read as their number on both sides: the claim's "ranked fourth" is the
    # narration's "4th" and "locul patru" ("a patra"). "First" and "second" are left out:
    # "at first" and "a second" are rarely a rank.
    "third": "3", "fourth": "4", "fifth": "5", "sixth": "6", "seventh": "7", "eighth": "8",
    "ninth": "9", "tenth": "10",
    "treia": "3", "treilea": "3", "patra": "4", "patrulea": "4", "cincea": "5",
    "cincilea": "5", "sasea": "6", "saselea": "6", "saptea": "7", "saptelea": "7",
    "optulea": "8", "zecea": "10", "zecelea": "10",
}  # fmt: skip

_NUMBER = re.compile(r"\d{1,3}(?:[,.  ]\d{3})+(?![\d])|\d+(?:[.,]\d+)?")
_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?", re.UNICODE)
_SENTENCE_END = re.compile(r"[.!?:;\n—\"“”]\s*$")


def _fold(text: str) -> str:
    """Lowercase, with the diacritics taken off, so "ș" and "s" are the same letter."""
    decomposed = unicodedata.normalize("NFKD", str(text))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


#: The words a spelled-out number is made of, in English and in Romanian (folded). A voiceover
#: is written to be read aloud and its writer spells numbers out: before these were read as one
#: number, "six hundred million" was a 6 and a 100 that no claim carries, and the adversary's
#: faithful Nepal film (2026-09-19) was refused as "someone else's story" at a share of 0.75.
_SMALL = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
    "unu": 1, "doi": 2, "doua": 2, "trei": 3, "patru": 4, "cinci": 5, "sase": 6, "sapte": 7,
    "opt": 8, "noua": 9, "zece": 10, "unsprezece": 11, "doisprezece": 12,
    "douasprezece": 12, "treisprezece": 13, "paisprezece": 14, "cincisprezece": 15,
    "saisprezece": 16, "saptesprezece": 17, "optsprezece": 18, "nouasprezece": 19,
    "douazeci": 20, "treizeci": 30, "patruzeci": 40, "cincizeci": 50, "saizeci": 60,
    "saptezeci": 70, "optzeci": 80, "nouazeci": 90,
}  # fmt: skip
_HUNDRED = frozenset({"hundred", "suta", "sute"})
_THOUSAND = frozenset({"thousand", "mie", "mii"})
#: Words that join the parts of one number: "two hundred and six", "douăzeci și șase".
_JOINERS = frozenset({"and", "si"})
_NUMBER_WORDS_ALL = frozenset(_SMALL) | _HUNDRED | _THOUSAND
_WORD_TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)
#: What may stand between two words of one number: a space or a hyphen on the same line,
#: nothing else; a full stop or a new scene ends the number.
_NUMBER_GAP = re.compile(r"[ \t]*-?[ \t]*")


def _read_run(words: list[str]) -> list[int]:
    """The numbers a run of number words says, one per number: "twenty eighteen" is 2018.

    A tens word takes a unit after it ("twenty six" is 26); two whole groups of 10-99 side by
    side are a year as it is said aloud ("nineteen ninety eight", "twenty eighteen").
    """
    groups: list[int] = []
    total = current = 0
    started = False
    for word in words:
        if word in _HUNDRED:
            current = (current or 1) * 100
        elif word in _THOUSAND:
            total += (current or 1) * 1000
            current = 0
        else:
            value = _SMALL[word]
            takes = current % 100 == 0 or (current % 100 >= 20 and current % 10 == 0 and value < 10)
            if started and not takes:
                groups.append(total + current)
                total = current = 0
            current += value
        started = True
    groups.append(total + current)
    if len(groups) == 2 and all(10 <= g <= 99 for g in groups):
        return [groups[0] * 100 + groups[1]]
    return groups


def _spell_numbers(text: str) -> str:
    """Write every spelled-out number as digits, so the narration's "six hundred million" is
    the claim's "600 million" and "douăzeci și șase" is 26.

    Only the number words are rewritten; the rest of the text, its line breaks and its
    punctuation, stay where they were, because a name is told from a sentence's first word by
    what comes before it. A lone "one" is left alone ("the one number", "one idea" are almost
    never a count), and a joiner only joins inside a number, never at its edge.
    """
    tokens = list(_WORD_TOKEN.finditer(text))
    runs: list[tuple[int, int, list[str]]] = []
    run: list[re.Match[str]] = []

    def close() -> None:
        words = [_fold(m.group(0)) for m in run]
        if words and words != ["one"]:
            runs.append((run[0].start(), run[-1].end(), words))
        run.clear()

    index = 0
    while index < len(tokens):
        token = tokens[index]
        word = _fold(token.group(0))
        if word in _NUMBER_WORDS_ALL:
            if run and not _NUMBER_GAP.fullmatch(text[run[-1].end() : token.start()]):
                close()
            run.append(token)
        elif (
            word in _JOINERS
            and run
            and index + 1 < len(tokens)
            and _fold(tokens[index + 1].group(0)) in _NUMBER_WORDS_ALL
            and _NUMBER_GAP.fullmatch(text[run[-1].end() : token.start()])
            and _NUMBER_GAP.fullmatch(text[token.end() : tokens[index + 1].start()])
        ):
            # "two hundred and six": the joiner is skipped and the next word joins the run.
            run.append(tokens[index + 1])
            index += 1
        else:
            close()
        index += 1
    close()
    for start, end, words in reversed(runs):
        text = text[:start] + " ".join(str(n) for n in _read_run(words)) + text[end:]
    return text


def _numbers(text: str) -> set[str]:
    """Every number in the text, as a canonical string: "7,000" and "7.000" are both 7000."""
    found: set[str] = set()
    for raw in _NUMBER.findall(str(text)):
        compact = raw.replace(" ", " ")
        if re.fullmatch(r"\d{1,3}(?:[,. ]\d{3})+", compact):
            found.add(str(int(re.sub(r"[,. ]", "", compact))))
            continue
        value = compact.replace(",", ".")
        found.add(f"{float(value):g}" if "." in value else str(int(value)))
    return found


def _same_number(a: str, b: str) -> bool:
    """Equal, or one is a decimal the other rounds: "about 83 billion" says "83.3 billion"."""
    if a == b:
        return True
    decimal, whole = (a, b) if "." in a else (b, a)
    if "." not in decimal or "." in whole:
        return False
    number = float(decimal)
    return whole in (str(int(number)), str(round(number)))


def _terms(text: str) -> tuple[set[str], set[str], set[str]]:
    """The content words, numbers and names of a text, each as the stems they compare by.

    A name is a capitalised word that does not open a sentence, or a word written in capitals
    ("CERN", "ATLAS", "GeV"). It is kept among the content words too, so "Nepal" at the start
    of a sentence still meets "Nepal" in a claim.
    """
    text = _spell_numbers(str(text or ""))
    words: set[str] = set()
    names: set[str] = set()
    numbers = _numbers(text)
    for match in _WORD.finditer(text):
        raw = match.group(0)
        word = _fold(raw).replace("’", "'")
        if word.endswith("'s"):
            word = word[:-2]
        word = word.split("'")[0]
        if word in NUMBER_WORDS:
            numbers.add(NUMBER_WORDS[word])
            continue
        before = text[: match.start()]
        opens_sentence = not before.strip() or bool(_SENTENCE_END.search(before))
        capitals = sum(1 for ch in raw if ch.isupper())
        is_name = (raw[0].isupper() and not opens_sentence) or capitals >= 2
        if word in STOPWORDS:
            continue
        if is_name and (len(word) >= MIN_WORD or capitals >= 2):
            names.add(word)
            words.add(word)
        elif len(word) >= MIN_WORD:
            words.add(word)
    return words, numbers, names


def _same(a: str, b: str) -> bool:
    if a == b:
        return True
    if a[:1].isdigit() or b[:1].isdigit():
        return a[:1].isdigit() and b[:1].isdigit() and _same_number(a, b)
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= SHARED_PREFIX and longer[:SHARED_PREFIX] == shorter[:SHARED_PREFIX]:
        return True
    return (
        len(shorter) >= MIN_WORD
        and longer.startswith(shorter)
        and len(longer) - len(shorter) <= SUFFIX_SLACK
    )


def _found(term: str, pool: set[str]) -> bool:
    return any(_same(term, other) for other in pool)


def is_serial_script(story: Any) -> bool:
    """Whether a script is an episode of the office serial, by the mark its writer leaves.

    The same mark `app.agents.editorial.is_serial_film` reads. A dramatisation makes no claims
    about the world; asking whether it says what its claims say is asking the wrong question.
    """
    return isinstance(story, dict) and story.get("kind") == SERIAL_SCRIPT_KIND


def _quote(text: str, limit: int = 90) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def measure_grounding(
    *,
    topic_title: str,
    topic_angle: str,
    claims: dict[str, str | None],
    voiceover: str,
) -> dict[str, Any]:
    """Measure whether a factual voiceover rests on its topic and on the claims it cites.

    `claims` maps each cited claim id to its text, or to None when the claim no longer exists.
    Returns the status (PASSED, REFUSED or NOT_MEASURED), the Romanian reasons, and every
    measurement behind them, so the Director and the Owner can read what was counted.
    """
    voiceover = str(voiceover or "")
    vo_words, vo_numbers, vo_names = _terms(voiceover)
    vo_pool = vo_words | vo_numbers
    missing_rows = [cid for cid, text in claims.items() if not (text or "").strip()]
    if not claims or missing_rows or not voiceover.strip():
        why = (
            "scenariul nu citează nicio afirmație"
            if not claims
            else (
                "afirmațiile citate nu mai există: " + ", ".join(c[:8] for c in missing_rows)
                if missing_rows
                else "scenariul nu are narațiune"
            )
        )
        return {
            "status": NOT_MEASURED,
            "passed": False,
            "reasons": [f"Ancorarea narațiunii nu a putut fi măsurată: {why}."],
            "claims": [],
            "topic": {},
            "foreign": {},
        }

    title_words, title_numbers, title_names = _terms(topic_title)
    angle_words, angle_numbers, angle_names = _terms(topic_angle)
    title_terms = title_words | title_numbers
    topic_terms = title_terms | angle_words | angle_numbers

    reasons: list[str] = []
    per_claim: list[dict[str, Any]] = []
    material = set(topic_terms)
    for claim_id, text in claims.items():
        words, numbers, names = _terms(str(text))
        material |= words | numbers
        own = words | numbers
        matched = sorted(t for t in own if _found(t, vo_pool))
        needed = min(CLAIM_TERMS_NEEDED, len(own))
        present = len(matched) >= needed and needed > 0
        unsaid = sorted(t for t in own if t not in matched)
        # The claim's own distinctive terms, numbers and names first: they are what the
        # writer has to carry, and what the Owner recognises in a reason.
        unsaid.sort(key=lambda t: (not (t in numbers or t in names), -len(t)))
        per_claim.append(
            {
                "claim_id": claim_id,
                "text": _quote(text or "", 160),
                "terms": len(own),
                "matched": matched,
                "needed": needed,
                "present": present,
                "unsaid": unsaid[:8],
            }
        )
        if not present:
            reasons.append(
                f"Afirmația {claim_id[:8]} («{_quote(text or '')}») este citată, dar narațiunea "
                f"nu o spune: {len(matched)} din {needed} termeni necesari; lipsesc "
                + ", ".join(unsaid[:6])
                + "."
            )

    topic_matched = sorted(t for t in topic_terms if _found(t, vo_pool))
    topic_needed = min(TOPIC_TERMS_NEEDED, len(topic_terms))
    about_topic = len(topic_matched) >= topic_needed
    if not about_topic:
        absent = sorted(
            (t for t in topic_terms if t not in topic_matched),
            key=lambda t: (t not in title_terms, t not in (title_names | angle_names), -len(t)),
        )
        reasons.append(
            f"Narațiunea nu vorbește despre subiectul «{_quote(topic_title)}»: are "
            f"{len(topic_matched)} din {topic_needed} termeni ai subiectului; lipsesc "
            + ", ".join(absent[:6])
            + "."
        )

    anchors = vo_numbers | vo_names
    foreign = sorted(t for t in anchors if not _found(t, material))
    share = round(len(foreign) / len(anchors), 3) if anchors else 0.0
    dominated = len(foreign) >= FOREIGN_ANCHORS_NEEDED and share > FOREIGN_SHARE_LIMIT
    if dominated:
        reasons.append(
            f"Narațiunea spune altă poveste: {len(foreign)} din {len(anchors)} nume și cifre "
            "ale ei nu apar în nicio afirmație citată și nici în subiect ("
            + ", ".join(foreign[:6])
            + ")."
        )

    passed = not reasons
    return {
        "status": PASSED if passed else REFUSED,
        "passed": passed,
        "reasons": reasons,
        "claims": per_claim,
        "claims_present": sum(1 for row in per_claim if row["present"]),
        "claims_cited": len(per_claim),
        "topic": {
            "matched": topic_matched,
            "needed": topic_needed,
            "terms": len(topic_terms),
            "about_topic": about_topic,
        },
        "foreign": {
            "anchors": len(anchors),
            "from_nowhere": foreign[:12],
            "share": share,
            "limit": FOREIGN_SHARE_LIMIT,
            "dominated": dominated,
        },
    }


def script_grounding(session: Any, script: Any) -> dict[str, Any] | None:
    """The grounding of a stored script, or None for a dramatisation of the serial.

    Reads the topic and the cited claims from the rows the studio already has; a cited claim
    that no longer exists is passed as None, which makes the measurement NOT_MEASURED rather
    than quietly measuring the claims that remain.
    """
    from app.factual.models import FactualClaim, TopicIdea  # noqa: PLC0415

    if script is None or is_serial_script(script.story_json):
        return None
    topic = session.get(TopicIdea, script.topic_id) if script.topic_id else None
    if topic is not None and str(topic.status or "").upper() == "SERIAL":
        return None
    claims: dict[str, str | None] = {}
    for claim_id in list(script.claim_ids_json or []):
        row = session.get(FactualClaim, claim_id)
        claims[claim_id] = row.claim_text if row is not None else None
    return measure_grounding(
        topic_title=topic.title if topic else "",
        topic_angle=topic.angle if topic else "",
        claims=claims,
        voiceover=script.voiceover_full_text or "",
    )


def grounding_check(grounding: dict[str, Any]) -> dict[str, Any]:
    """The measurement as one of the story review's checks: passed, and the reason."""
    if grounding.get("passed"):
        return {
            "passed": True,
            "reason": (
                "Narațiunea spune ce spun afirmațiile citate și subiectul: "
                f"{grounding.get('claims_present')} din {grounding.get('claims_cited')} "
                "afirmații recunoscute în text."
            ),
            "measured": grounding,
        }
    return {
        "passed": False,
        "reason": " ".join(grounding.get("reasons") or [])
        or "Ancorarea narațiunii nu a putut fi măsurată.",
        "measured": grounding,
    }
