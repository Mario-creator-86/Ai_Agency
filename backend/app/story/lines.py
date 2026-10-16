"""Who says what in an episode: the cast's names, and the lines as a voice will say them.

Measured before this module (2026-09-24): an episode's dialogue was free text with the
speakers' names in it ("Sarah: (sighs) Fine."), and the storyboard handed that text whole to
one voice, so the name and the stage direction were read aloud and printed in the captions.
The showrunner's schema v3 asks for lines instead, each ``{speaker, text, direction?}``; this
module is what both ends of that read:

- **The names.** A model writes "Sarah" for "Sarah (Director)", or her bible's "Sarah
  Executive", and the grounding refused the whole day for it. `NameBook` maps every
  unambiguous way of writing a roster member to the roster's own display name; anything it
  cannot map is a stranger, as before.
- **The spoken text.** Whatever a model puts in ``text`` besides the words — a leading name
  and colon, ``(sighs)``, ``[quietly]``, ``*laughs*`` — is taken out and kept as the
  direction, because a voice says every character of ``text``.
- **The old episodes.** A v2 beat has only its free ``dialogue``. `beat_lines` reads it line
  by line, a label the day's roster knows becoming the speaker and anything else the
  narrator's, so an episode written before v3 is still filmed without its labels.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

#: Titles written before a name; "Dr." alone names nobody.
_TITLES = frozenset({"dr", "mr", "mrs", "ms", "miss", "prof", "sir"})

#: A stage direction inside spoken text: (sighs), [quietly], *laughs*.
_DIRECTION = re.compile(r"\(([^()]{1,160})\)|\[([^\[\]]{1,160})\]|\*([^*]{1,160})\*")

#: A speaker's label at the start of a line: "Sarah (Director): ...". The colon only: a dash
#: after a name is how a line addresses someone ("Kael — the render is late"), and that name
#: is part of what is said.
_LABEL = re.compile(r"^\s*([^:\n]{1,60}?)\s*:\s*(.+)$", re.DOTALL)

#: Words whose full stop belongs to the word, not to the end of a sentence: the titles before
#: a name and the abbreviations a script writes mid-sentence ("Dr. Aris", "the U.S. Navy").
#: Kept without their last stop, as `stops_inside` compares them.
_ABBREVIATIONS = frozenset(
    {"dr", "mr", "mrs", "ms", "prof", "st", "jr", "sr", "u.s", "u.k", "e.g", "i.e", "vs"}
)
#: What may close a sentence after its mark ('"go."', "(done.)") or open a word before it.
_CLOSERS = "\"'”’»)]}"
_OPENERS = "\"'“‘«([{"


def _key(text: Any) -> str:
    """A name as compared: case folded, spaces collapsed, outer punctuation off."""
    return " ".join(str(text or "").casefold().replace("’", "'").split()).strip(" .,;:!?\"'")


def _base(display_name: str) -> str:
    """The name without the role it carries in brackets: "Dr. Aris (Researcher)" -> "Dr. Aris"."""
    return re.sub(r"\s*\([^()]*\)\s*$", "", display_name).strip()


class NameBook:
    """Every unambiguous way of writing a roster member, mapped to the roster's display name.

    Keys, for "Dr. Aris (Researcher)" whose bible is "Dr. Aris Researcher" and whose role is
    LeadResearcher: the display name, "dr. aris", "aris", the bible's name and its first
    word, the bracketed role "researcher" and the role name. A key two members share (two
    Annas) names nobody: guessing between them would put one in the other's scene.
    """

    def __init__(self, roster: Iterable[dict[str, Any]], bibles: dict[str, Any] | None = None):
        self.names: list[str] = []
        claims: dict[str, set[str]] = {}

        def claim(key: str, name: str) -> None:
            if key:
                claims.setdefault(key, set()).add(name)

        for member in roster:
            name = str(member.get("display_name") or "").strip()
            if not name or name in self.names:
                continue
            self.names.append(name)
            base = _base(name)
            claim(_key(name), name)
            claim(_key(base), name)
            words = [w for w in re.split(r"[\s.]+", _key(base)) if w]
            for word in words:
                if len(word) >= 3 and word not in _TITLES:
                    claim(word, name)
            bracket = re.search(r"\(([^()]*)\)\s*$", name)
            if bracket:
                claim(_key(bracket.group(1)), name)
            claim(_key(member.get("role_name")), name)
            bible = (bibles or {}).get(name)
            canonical = str(getattr(bible, "canonical_name", "") or "")
            if canonical:
                claim(_key(canonical), name)
                claim(_key(canonical.split()[0]), name)
        # The display names themselves always win: "Sarah (Director)" is Sarah even if a
        # colleague's role were "Sarah".
        self._book = {key: next(iter(owners)) for key, owners in claims.items() if len(owners) == 1}
        self._book.update({_key(name): name for name in self.names})

    def canonical(self, written: Any) -> str | None:
        """The roster's display name for how a model wrote it, or None for a stranger."""
        key = _key(written)
        if not key:
            return None
        return self._book.get(key)


def split_direction(text: Any) -> tuple[str, str]:
    """(the words a voice says, the stage directions taken out of them)."""
    raw = str(text or "")
    directions = [
        " ".join(next(group for group in match.groups() if group).split())
        for match in _DIRECTION.finditer(raw)
    ]
    spoken = " ".join(_DIRECTION.sub(" ", raw).split())
    return spoken, "; ".join(directions)


def split_label(text: Any, names: NameBook | None = None) -> tuple[str | None, str]:
    """A leading "Name:" taken off a line: (the name as written, the rest).

    With ``names``, only a label the roster knows is taken, so "Here's the thing: we ship"
    keeps its colon; without it (reading a model's answer, before the roster is at hand)
    any short label before a colon is taken, and the grounding judges the name afterwards.
    """
    raw = str(text or "").strip()
    match = _LABEL.match(raw)
    if match is None:
        return None, raw
    label, rest = match.group(1).strip(), match.group(2).strip()
    if names is not None:
        return (label, rest) if names.canonical(label) else (None, raw)
    if len(label.split()) > 4 or not rest:
        return None, raw
    return label, rest


def clean_line(
    speaker: str | None, text: Any, direction: Any, names: NameBook | None
) -> dict[str, Any] | None:
    """One line as it is stored: the speaker's roster name, the spoken words, the direction.

    A label the roster knows at the start of ``text`` is removed: the speaker field already
    says who talks, and the label would be read aloud. None when nothing is left to say.
    """
    label, rest = split_label(text, names) if names is not None else (None, str(text or ""))
    spoken, taken = split_direction(rest if label else text)
    notes = [part for part in (" ".join(str(direction or "").split()), taken) if part]
    if not spoken:
        return None
    line: dict[str, Any] = {"speaker": speaker, "text": spoken}
    if notes:
        line["direction"] = "; ".join(notes)[:200]
    return line


def beat_lines(beat: dict[str, Any], names: NameBook | None = None) -> list[dict[str, Any]]:
    """The lines of one stored beat, v3 or v2, as ``{speaker, text, direction?}``.

    A v3 beat has them already. A v2 beat is read from its ``dialogue``: each line whose
    label the roster knows becomes that member's, anything else the narrator's (speaker
    None), and every stage direction comes out of the spoken text.
    """
    stored = beat.get("lines")
    if isinstance(stored, list) and stored:
        return [dict(line) for line in stored if isinstance(line, dict) and line.get("text")]
    found: list[dict[str, Any]] = []
    for raw in str(beat.get("dialogue") or "").splitlines():
        label, rest = split_label(raw, names) if names is not None else (None, raw)
        speaker = names.canonical(label) if names is not None and label else None
        line = clean_line(speaker, rest, "", None)
        if line is not None:
            found.append(line)
    return found


def stops_inside(word: Any) -> bool:
    """Whether a word's full stop is part of the word: a title or an abbreviation
    (`_ABBREVIATIONS`), or a single capital initial ("J. Robert"). "I." is not an initial:
    "So did I." ends a line far more often than a name starts with it."""
    bare = str(word or "").strip().rstrip(_CLOSERS).lstrip(_OPENERS)
    if not bare.endswith(".") or bare.endswith(".."):
        return False
    stem = bare[:-1]
    initial = len(stem) == 1 and stem.isalpha() and stem.isupper() and stem != "I"
    return initial or stem.casefold() in _ABBREVIATIONS


def ends_sentence(word: Any) -> bool:
    """Whether a word ends its sentence: its last mark, before any closing quote or bracket,
    is a full stop, a question or an exclamation mark — and the stop is not a title's, an
    abbreviation's or an initial's (`stops_inside`). A decimal ("3.5") ends nothing: its
    point is inside the word.

    Measured 2026-10-16: «Dr. Aris guards his numbers.» was two sentences to the narration
    check and two shots, two voice takes, to the montage, cut between the title and the name.
    """
    bare = str(word or "").strip().rstrip(_CLOSERS)
    if not bare or bare[-1] not in ".!?":
        return False
    return not stops_inside(bare)


def sentence_count(text: Any) -> int:
    """How many sentences ``text`` holds (`ends_sentence`); words after the last full stop
    are one more, and marks with no word before them are none."""
    count, open_sentence = 0, False
    for word in str(text or "").split():
        if any(char.isalnum() for char in word):
            open_sentence = True
        if open_sentence and ends_sentence(word):
            count += 1
            open_sentence = False
    return count + (1 if open_sentence else 0)


def spoken_text(lines: Iterable[dict[str, Any]]) -> str:
    """What the voices say, one line to a row: no name, no direction."""
    return "\n".join(str(line.get("text") or "").strip() for line in lines if line.get("text"))


def speakers_of(lines: Iterable[dict[str, Any]]) -> list[str]:
    """Who speaks, in the order they first do."""
    found: list[str] = []
    for line in lines:
        speaker = line.get("speaker")
        if speaker and speaker not in found:
            found.append(str(speaker))
    return found


def participants(item: dict[str, Any], cast: Iterable[str]) -> list[str]:
    """The roster members who act in one projected event: who did it, and who it names.

    A letter "Sarah (Director) wrote to Kael (Video Editor)" has both; a render that
    finished has nobody. Read from the projection only (its `actor` and its public line), so
    the answer is what the audience may know.
    """
    found: list[str] = []
    actor = item.get("actor")
    if actor:
        found.append(str(actor))
    description = str(item.get("description") or "")
    for name in cast:
        if name and name in description and name not in found:
            found.append(name)
    return found
