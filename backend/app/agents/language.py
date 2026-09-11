"""The language the studio publishes in.

The Owner's rule: everything the studio posts is in English, whatever language the prompts,
the office and the Owner speak. That is one setting (`content_language`, default `en`) told
to every employee whose words reach the audience — the script writer, the showrunner, the
Publisher — and checked once more on the way out: a title or description that is plainly not
in the publishing language holds the publication instead of shipping it.

The check is a guard, not a linguist: it knows the marks of the office's own language
(Romanian diacritics and its commonest words) and nothing else, which is exactly the mistake
it exists to catch — an employee answering in the language it was spoken to.
"""

from __future__ import annotations

import re

LANGUAGE_NAMES = {
    "en": "English",
    "ro": "Romanian",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
}

_ROMANIAN_MARKS = re.compile(r"[ăâîșțĂÂÎȘȚ]")
_ROMANIAN_WORDS = re.compile(
    r"\b(și|este|sunt|pentru|fiecare|această|acest|către|într-un|într-o|despre|"
    r"studioul|conținut|afirmație|înainte|produce)\b",
    re.IGNORECASE,
)


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code.lower(), code)


def audience_language_line(code: str) -> str:
    """One sentence for a prompt: what language the audience reads and hears."""
    name = language_name(code)
    return (
        f"AUDIENCE LANGUAGE: {name}. Everything the audience will read or hear — the narration, "
        f"the title, the description, the tags — must be written in {name}, whatever language "
        "these instructions or the source material use.\n"
    )


def looks_like_english(text: str) -> bool:
    """False when the text carries the marks of Romanian; True when it does not.

    A guard for the publishing language, tuned to the one language the office speaks and an
    employee might slip into. Text with no marks of Romanian is taken as English.
    """
    sample = text or ""
    if _ROMANIAN_MARKS.search(sample):
        return False
    return len(_ROMANIAN_WORDS.findall(sample)) < 2


def publication_language_hold(title: str, description: str, code: str) -> str | None:
    """The reason a publication must hold for its language, or None when it may go."""
    if code.lower() != "en":
        return None
    if looks_like_english(f"{title}\n{description}"):
        return None
    return (
        f"Titlul sau descrierea nu sunt în {language_name(code)}; studioul publică doar în "
        f"{language_name(code)}."
    )
