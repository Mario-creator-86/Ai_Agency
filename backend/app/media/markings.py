"""Objects whose own markings are not «text in the picture» (2026-10-13).

The Owner, on the film «Why the Kelvin Scale Has No 'Zero' to Begin From»: a scene asked for
a thermometer, and quality control refused every still for the digits on it. «Nu ai cum să
ai un termometru fără scris, grade, Celsius.» A thermometer's scale, a gauge's dial, a clock's
face and a ruler's graduations ARE the object; the bible's rule against writing is about
captions, signs, logos and the lettering a model invents.

So when the scene's plan names such an object (`planned_markings`, read from the still prompt
and the scene's written picture — what the picture must show — never from the narration
alone):

- the vision checks are told the object's markings are expected and asked to count only
  writing elsewhere (`picture_qc.judge_still`, `picture_qc.judge_clip`: `markings_note`);
- a writing finding is a reading the Director judges like any other — never a hard limit of
  the bible that fails closed (`second_look.hard_limits`, `still_gate.may_be_overturned`,
  `qc.look_may_overturn`), never anchored serious in her review of a rewrite
  (`scene_rewrite.hard_limit`), and her brief is told so (`scene_rewrite._data`);
- the still prompt says so instead of «No text» (`still_exclusions`), and a re-roll's positive
  words no longer ask for «unmarked objects» (`still_gate.positive_instruction`).

Writing anywhere else, faces and panels change nothing. The list is short and literal — an
instrument that cannot exist without its scale, a clock, a keyboard — never a sign, a page, a
board or a screen, which a model fills with gibberish and the bible rightly refuses.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

#: Each object with the spellings that name it: English (the prompts) and the Romanian a
#: script's line may use. One key per object; a plan naming it in either language is one.
MARKED_OBJECTS: dict[str, str] = {
    "thermometer": r"\bthermometers?\b|\btermometr(?:u|e|ul|ele|elor)\b",
    "barometer": r"\bbarometers?\b|\bbarometr(?:u|e|ul|ele)\b",
    "manometer": r"\bmanometers?\b|\bmanometr(?:u|e|ul|ele)\b",
    "hygrometer": r"\bhygrometers?\b|\bhigrometr(?:u|e|ul|ele)\b",
    "altimeter": r"\baltimeters?\b|\baltimetr(?:u|e|ul|ele)\b",
    "speedometer": r"\bspeedometers?\b|\bvitezometr(?:u|e|ul|ele)\b",
    "odometer": r"\bodometers?\b|\bkilometraj(?:ul|e)?\b",
    "tachometer": r"\btachometers?\b|\bturometr(?:u|e|ul|ele)\b",
    "voltmeter": r"\bvoltmeters?\b|\bvoltmetr(?:u|e|ul|ele)\b",
    "ammeter": r"\bammeters?\b|\bampermetr(?:u|e|ul|ele)\b",
    "multimeter": r"\bmultimeters?\b|\bmultimetr(?:u|e|ul|ele)\b",
    "galvanometer": r"\bgalvanometers?\b|\bgalvanometr(?:u|e|ul|ele)\b",
    "chronometer": r"\bchronometers?\b|\bcronometr(?:u|e|ul|ele)\b",
    "seismograph": r"\bseismographs?\b|\bseismograf(?:ul|e|ele)?\b",
    "oscilloscope": r"\boscilloscopes?\b|\bosciloscop(?:ul|e|ele)?\b",
    "gauge": r"\bgauges?\b",
    "dial": r"\bdials?\b|\bcadran(?:ul|e|ele)?\b",
    # Not «six o'clock»: an hour of the day is no clock in the picture.
    "clock": r"(?<!o')(?<!o’)\bclocks?\b|\bceas(?:ul|uri|urile)?\b|\bpendul[ăa]\b",
    "watch": r"\b(?:wrist|pocket|stop)[- ]?watch(?:es)?\b|\bwatch\s+face\b",
    "sundial": r"\bsundials?\b",
    "timer": r"\btimers?\b",
    "ruler": r"\brulers?\b|\byardsticks?\b|\brigl(?:[ăa]|e|ele)\b",
    "tape measure": r"\b(?:tape\s+measures?|measuring\s+tapes?)\b|\brulet[ăa]\b",
    "protractor": r"\bprotractors?\b|\braportor(?:ul|e)?\b",
    "weighing scale": (
        r"\b(?:weighing|kitchen|bathroom|balance|laboratory|lab|spring)\s+scales?\b"
        r"|\bcântar(?:ul|e|ele)?\b"
    ),
    "graduated glass": (
        r"\bgraduated\s+(?:cylinders?|beakers?|flasks?|tubes?)\b|\bmeasuring\s+(?:cups?|jugs?)\b"
        r"|\bburettes?\b|\bpipettes?\b|\bsyringes?\b|\bcilindr(?:u|ul)\s+gradat\b|\bsering[ăa]\b"
    ),
    "temperature scale": (
        r"\b(?:celsius|fahrenheit|kelvin|centigrade|temperature|graduated|numbered)\s+scales?\b"
        r"|\bscal[ăa]\s+(?:celsius|fahrenheit|kelvin|de\s+temperatur[ăa]|gradat[ăa])\b"
    ),
    "thermostat": r"\bthermostats?\b|\btermostat(?:ul|e|ele)?\b",
    "compass": r"\bcompass(?:es)?\b|\bbusol(?:[ăa]|e|ele)\b",
    "instrument panel": (
        r"\b(?:instrument|control)\s+panels?\b|\bdashboards?\b|\bcockpits?\b"
        r"|\bbord(?:ul)?\s+de\s+(?:instrumente|comand[ăa])\b"
    ),
    "keyboard": (
        r"\bkeyboards?\b|\btypewriters?\b|\bkeypads?\b|\bcalculators?\b|\bcash\s+registers?\b"
        r"|\btastatur[ăa]\b|\bma[șs]in[ăa]\s+de\s+scris\b"
    ),
}
_PATTERNS: dict[str, re.Pattern[str]] = {
    name: re.compile(pattern, re.IGNORECASE) for name, pattern in MARKED_OBJECTS.items()
}
#: The Owner reads Romanian: the object's name in his sentences (`markings_ro`).
_RO: dict[str, str] = {
    "thermometer": "termometrul",
    "barometer": "barometrul",
    "manometer": "manometrul",
    "hygrometer": "higrometrul",
    "altimeter": "altimetrul",
    "speedometer": "vitezometrul",
    "odometer": "kilometrajul",
    "tachometer": "turometrul",
    "voltmeter": "voltmetrul",
    "ammeter": "ampermetrul",
    "multimeter": "multimetrul",
    "galvanometer": "galvanometrul",
    "chronometer": "cronometrul",
    "seismograph": "seismograful",
    "oscilloscope": "osciloscopul",
    "gauge": "indicatorul cu cadran",
    "dial": "cadranul",
    "clock": "ceasul",
    "watch": "ceasul de mână",
    "sundial": "cadranul solar",
    "timer": "cronometrul",
    "ruler": "rigla",
    "tape measure": "ruleta",
    "protractor": "raportorul",
    "weighing scale": "cântarul",
    "graduated glass": "vasul gradat",
    "temperature scale": "scala de temperatură",
    "thermostat": "termostatul",
    "compass": "busola",
    "instrument panel": "bordul de instrumente",
    "keyboard": "tastatura",
}


def planned_markings(*texts: object, excluded: Sequence[str] = ()) -> tuple[str, ...]:
    """The objects of `MARKED_OBJECTS` the plan's ``texts`` name, in the order they are first
    named, each once; empty when the plan names none. A text that is not a string is read as
    its words; None and empty texts say nothing. An object-specific exclusion of its markings
    takes precedence; a generic ban on captions does not make real instruments blank."""
    said = " ".join(" ".join(str(text).split()) for text in texts if text)
    if not said:
        return ()
    found: list[tuple[int, str]] = []
    for name, pattern in _PATTERNS.items():
        if any(
            pattern.search(str(item))
            and re.search(
                r"\b(?:markings?|numbers?|digits?|labels?|graduations?|ticks?|scale)\b",
                str(item),
                re.IGNORECASE,
            )
            for item in excluded
        ):
            continue
        match = pattern.search(said)
        if match:
            found.append((match.start(), name))
    names = [name for _at, name in sorted(found)]
    if "thermometer" in names and "temperature scale" in names:
        # A thermometer's Celsius scale is the thermometer's, not a second object.
        names.remove("temperature scale")
    return tuple(names)


def named(names: Sequence[str], article: str = "the") -> str:
    """«the thermometer», «the thermometer and the gauge», «a clock, a dial and a gauge»; with
    a capital article, only the first («The thermometer and the gauge»)."""
    said = [f"{article.lower()} {name}" for name in names]
    if not said:
        return ""
    joined = said[0] if len(said) == 1 else ", ".join(said[:-1]) + " and " + said[-1]
    return joined[:1].upper() + joined[1:] if article[:1].isupper() else joined


def markings_note(markings: Sequence[str]) -> str:
    """What a model that judges the picture is told when the plan names an object that
    carries its own markings (English, for the vision model and the Director); "" when the
    plan names none."""
    if not markings:
        return ""
    return (
        f"The plan asks for {named(markings, 'a')}: the scale, numbers, units and labels "
        "that belong on such an object are part of the object, not writing in the picture, "
        "and the picture is right to show them. Count as readable text only writing "
        "elsewhere — a caption, a sign, a logo, lettering on nothing, a line that looks like "
        "a subtitle — and say in your reason where any writing you see is. Such an object is "
        "a photograph of a thing, never a chart, a title or numbers the studio composes "
        "itself: its markings are no reason for compose_locally."
    )


def still_exclusions(markings: Sequence[str]) -> str:
    """The still prompt's last sentence: «No text, no logo.» for a scene of plain objects;
    for one whose plan names an object that carries its own markings, the object keeps them
    (an image model told «no text» leaves a thermometer blank, or draws the digits anyway and
    the words were a lie) and only a caption or a logo is kept out."""
    if not markings:
        return "No text, no logo."
    keeps = "keeps its" if len(markings) == 1 else "keep their"
    return f"{named(markings, 'The')} {keeps} own scale and markings; no caption, no logo."


def markings_kept(markings: Sequence[str]) -> str:
    """The same, said positively alone, for a model whose exclusions go to its negative
    channel (gen4) and whose prompt says no «no»."""
    if not markings:
        return ""
    keeps = "keeps its" if len(markings) == 1 else "keep their"
    return f"{named(markings, 'The')} {keeps} own scale and markings."


def markings_ro(markings: Sequence[str]) -> str:
    """The objects in the Owner's language: «termometrul», «termometrul și cadranul»."""
    names = [_RO.get(name, name) for name in markings]
    if not names:
        return ""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " și " + names[-1]
