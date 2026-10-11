"""The Owner's music library: the only place a film's bed and ambience may come from.

``config/music_library.json`` lists each track the Owner has the right to use::

    {"tracks": [{
        "id": "calm-01",                # stable name, recorded on every film that uses it
        "kind": "music",                # "music" (a bed under the voice) or "ambience"
        "file": "music/calm-01.wav",    # relative to the library file's folder, never outside
        "sha256": "…",                  # the bytes the Owner licensed; others are refused
        "licence": "…",                 # the licence or the plan's terms, in his words
        "commercial_ok": true,          # his explicit yes; anything else is never used
        "redistributable": false,       # whether the file may ship with the studio
        "attribution": null,            # the credit a licence requires, written under the film
        "mood": ["calm", "wonder"],     # what the bed suits (MOOD_WORDS)
        "bpm": 80,
        "tags": ["rain"]                # ambience: the words of a scene's audio_intent it fits
    }]}

It ships empty: which library to use (YouTube's Audio Library downloads, a paid licence, his
own recordings) is the Owner's choice, and a film without a usable track is voice only and
says so. A track is never guessed at: without ``commercial_ok`` true, a licence, the file in
the library's folder and the recorded sha256, it is refused and the refusal is kept.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
#: The library the release ships, empty: a buyer's music is his own choice.
SHIPPED_LIBRARY = ROOT / "config" / "music_library.json"
#: The Owner's own library, beside his files: config/music/ is ignored by git, so nothing of
#: it is committed or shipped (2026-10-11, his first twenty beds and five ambiences from
#: YouTube's Audio Library, registered with scripts/music_add.py).
OWNER_LIBRARY = ROOT / "config" / "music" / "music_library.json"


def library_path(
    env: Mapping[str, str] | None = None,
    *,
    owner: Path = OWNER_LIBRARY,
    shipped: Path = SHIPPED_LIBRARY,
) -> Path:
    """The library the studio reads: the file STUDIO_MUSIC_LIBRARY names (a library kept
    anywhere), else the Owner's library beside his files when it exists, else the shipped
    one. Read once, at start-up."""
    named = (os.environ if env is None else env).get("STUDIO_MUSIC_LIBRARY")
    if named:
        return Path(named)
    return owner if owner.is_file() else shipped


LIBRARY_PATH = library_path()

#: Moods a bed may carry, and the words (English and Romanian, as scripts are written in
#: either) that call for them in a film's core message, title, purposes and words.
MOOD_WORDS: dict[str, tuple[str, ...]] = {
    "tense": ("tense", "danger", "threat", "risk", "crisis", "pericol", "amenin", "criz", "risc"),
    "mystery": (
        "mystery",
        "secret",
        "unknown",
        "vanish",
        "disappear",
        "who",
        "mister",
        "necunoscut",
        "dispăr",
        "cine",
    ),
    "dark": (
        "dark",
        "death",
        "war",
        "disaster",
        "night",
        "întuneric",
        "moart",
        "război",
        "dezastru",
        "noapte",
    ),
    "wonder": (
        "wonder",
        "space",
        "universe",
        "discover",
        "beauty",
        "univers",
        "spațiu",
        "descoper",
        "frumus",
        "uimi",
    ),
    "calm": ("calm", "quiet", "peace", "nature", "slow", "liniște", "natur", "pace", "lin"),
    "uplifting": (
        "hope",
        "success",
        "win",
        "rise",
        "future",
        "speranț",
        "succes",
        "victor",
        "viitor",
    ),
    "epic": (
        "epic",
        "history",
        "empire",
        "ancient",
        "battle",
        "istori",
        "imperi",
        "antic",
        "bătăli",
    ),
}
KINDS = ("music", "ambience")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True)
class Track:
    """One usable entry of the library, its file checked."""

    id: str
    kind: str
    path: Path
    sha256: str
    licence: str
    commercial_ok: bool
    redistributable: bool
    attribution: str | None
    mood: tuple[str, ...] = ()
    bpm: float | None = None
    tags: tuple[str, ...] = ()
    #: What the Owner called the track and how long it runs, as the entry says (scripts/
    #: music_add.py writes both; the loader vouches for neither): read by the Voice Artist's
    #: sound brief (`app.media.sound_design`), never by the mix.
    title: str | None = None
    duration: str | None = None

    def record(self) -> dict[str, Any]:
        """What a film records about the track it used."""
        return {
            "track_id": self.id,
            "kind": self.kind,
            "file": self.path.name,
            "sha256": self.sha256,
            "licence": self.licence,
            "commercial_ok": self.commercial_ok,
            "redistributable": self.redistributable,
            "attribution": self.attribution,
        }


@dataclass
class Library:
    """The usable tracks, and every entry refused with its reason (in Romanian)."""

    path: Path
    tracks: list[Track] = field(default_factory=list)
    refused: list[dict[str, str]] = field(default_factory=list)

    def entry(self, track_id: str) -> Track | None:
        return next((track for track in self.tracks if track.id == track_id), None)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list | tuple):
        return ()
    return tuple(str(item).strip().lower() for item in value if str(item).strip())


def _checked(raw: Any, folder: Path) -> tuple[Track | None, str]:
    """(the track, "") when the entry can be vouched for; (None, the reason) otherwise."""
    if not isinstance(raw, dict):
        return None, "intrarea nu este un obiect"
    track_id = str(raw.get("id") or "").strip()
    if not track_id:
        return None, "intrarea nu are „id”"
    kind = str(raw.get("kind") or "music").strip().lower()
    if kind not in KINDS:
        return None, f"tipul „{kind}” nu este music sau ambience"
    if raw.get("commercial_ok") is not True:
        return None, "nu are „commercial_ok”: true (folosirea comercială nu este confirmată)"
    licence = str(raw.get("licence") or "").strip()
    if not licence:
        return None, "nu are licența scrisă"
    name = str(raw.get("file") or "").strip()
    if not name:
        return None, "nu are fișier"
    path = (folder / name).resolve()
    if not path.is_relative_to(folder.resolve()):
        return None, "fișierul este în afara dosarului bibliotecii"
    if not path.is_file():
        return None, f"fișierul {name} lipsește"
    recorded = str(raw.get("sha256") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", recorded):
        return None, "nu are sha256-ul fișierului licențiat"
    if _sha256(path) != recorded:
        return None, f"fișierul {name} nu este cel licențiat (sha256 diferit)"
    attribution = str(raw.get("attribution") or "").strip() or None
    bpm = raw.get("bpm")
    return (
        Track(
            id=track_id,
            kind=kind,
            path=path,
            sha256=recorded,
            licence=licence,
            commercial_ok=True,
            redistributable=raw.get("redistributable") is True,
            attribution=attribution,
            mood=_strings(raw.get("mood")),
            bpm=float(bpm) if isinstance(bpm, int | float) and not isinstance(bpm, bool) else None,
            tags=_strings(raw.get("tags")),
            title=str(raw.get("title") or "").strip() or None,
            duration=str(raw.get("duration") or "").strip() or None,
        ),
        "",
    )


def load_library(path: Path | str | None = None) -> Library:
    """The library at ``path`` (LIBRARY_PATH by default), every entry checked. A missing or
    unreadable file is an empty library with the reason recorded, never an error that stops
    a film."""
    where = Path(path) if path is not None else LIBRARY_PATH
    library = Library(path=where)
    try:
        data = json.loads(where.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return library
    except (OSError, ValueError) as exc:
        library.refused.append({"id": "*", "reason": f"biblioteca nu poate fi citită ({exc})"})
        return library
    entries = data.get("tracks") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        library.refused.append({"id": "*", "reason": "biblioteca nu are lista „tracks”"})
        return library
    seen: set[str] = set()
    for raw in entries:
        track, reason = _checked(raw, where.parent)
        name = str(raw.get("id") if isinstance(raw, dict) else "?")
        if track is None:
            library.refused.append({"id": name, "reason": reason})
        elif track.id in seen:
            library.refused.append({"id": name, "reason": "id repetat"})
        else:
            seen.add(track.id)
            library.tracks.append(track)
    return library


def moods_of(text: str) -> dict[str, int]:
    """How strongly ``text`` calls for each mood: the count of its words that start one of
    the mood's stems (so "dispărut" calls for mystery)."""
    words = [word.lower() for word in _WORD.findall(text or "")]
    found: dict[str, int] = {}
    for mood, stems in MOOD_WORDS.items():
        hits = sum(1 for word in words for stem in stems if word.startswith(stem))
        if hits:
            found[mood] = hits
    return found


def _order(seed: str, track_id: str) -> str:
    return hashlib.sha256(f"{seed}:{track_id}".encode()).hexdigest()


def choose_bed(library: Library, *, mood_text: str, seed: str) -> Track | None:
    """The bed for a film: the usable music track whose moods the film's words call for
    most; ties (and a film whose words call for nothing) are broken by ``seed`` (the film),
    so successive films do not all carry the same track. None without a usable track."""
    music = [track for track in library.tracks if track.kind == "music"]
    if not music:
        return None
    wanted = moods_of(mood_text)
    return min(
        music,
        key=lambda track: (
            -sum(wanted.get(mood, 0) for mood in track.mood),
            _order(seed, track.id),
        ),
    )


def choose_ambience(library: Library, intent: str) -> Track | None:
    """An ambience whose tags a scene's audio_intent names (rain, wind, city...), or None."""
    words = {word.lower() for word in _WORD.findall(intent or "")}
    if not words:
        return None
    matches = [
        track
        for track in library.tracks
        if track.kind == "ambience"
        and any(word.startswith(tag) for tag in track.tags for word in words)
    ]
    return min(matches, key=lambda track: track.id) if matches else None
