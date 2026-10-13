"""Put a licensed track into the Owner's music library, or check the library.

The library is the only place a film's bed or ambience may come from
(`app.media.music_library`). The release ships ``config/music_library.json`` empty: where
the music comes from is the Owner's choice. His own library is ``config/music/
music_library.json``, beside his files (``config/music/`` is ignored by git, so nothing of it
is committed or shipped), and the studio reads it when it exists (`music_library.library_path`).
On 2026-10-11 he chose YouTube's Audio Library (docs/project/MUSIC_YOUTUBE_AUDIO_LIBRARY_
2026-10-11.md) and had the first twenty beds and five ambiences downloaded from his Studio.
This is the command that puts a downloaded file into the library the way the loader vouches
for it: the file copied beside the library as ``<id>.mp3``, its sha256 recorded, the licence
written with Google's own words and the download date, commercial use confirmed,
redistribution refused, and the entry read back through `load_library`, so a mistake is seen
here and not in a film's quality report. The studio reads the library once, at start-up: a
restart follows the first fill.

It never downloads anything, never opens Studio and never touches ``data/``.

Usage::

    uv run python scripts/music_add.py "C:/Users/me/Downloads/After All - Geographer.mp3" \\
        --id yal-calm-after-all --kind music --title "After All" --artist Geographer \\
        --genre "Muzică ambientală" --mood calm --licence-type standard
    uv run python scripts/music_add.py "C:/Users/me/Downloads/Rain On Rooftop.mp3" \\
        --id yal-amb-rain-rooftop --kind ambience --title "Rain On Rooftop" \\
        --tags rain,storm --licence-type standard
    uv run python scripts/music_add.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.media import music_library  # noqa: E402

#: Where a track came from, recorded on its entry.
SOURCE = "youtube-audio-library"
LICENCE_TYPES = ("standard", "cc-by")
#: A stable id: recorded on every film that uses the track, so never renamed.
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,60}$")
_AUDIO = (".mp3", ".wav", ".m4a", ".ogg", ".flac")
#: The licence dialog of a standard track, as YouTube Studio showed it on 2026-10-11
#: («Licență pentru Biblioteca audio YouTube»). Kept verbatim: the ledger carries Google's
#: words, not ours.
STANDARD_WORDS = (
    "Poți să folosești această înregistrare audio în videoclipuri, inclusiv în cele din care "
    "generezi bani. Nu este necesară nicio atribuire. YouTube poate menționa artistul și poate "
    "adăuga la videoclipul tău un link către Biblioteca audio. Nu ai permisiunea să pui la "
    "dispoziție, să distribui sau să interpretezi fișiere de muzică din această bibliotecă "
    "separat de videoclipuri și alte conținuturi în care le-ai încorporat (de ex., "
    "distribuirea separată a acestor fișiere nu este permisă)."
)
NOTES_RO = (
    "Biblioteca de muzică a Proprietarului, lângă fișierele ei (config/music/, ignorat de git: "
    "nu se livrează). Fiecare piesă: id, kind (music sau ambience), file (relativ la acest "
    "dosar), sha256 (al fișierului licențiat), licence (licența sau termenii planului), "
    "commercial_ok (true doar dacă licența permite folosire comercială), redistributable, "
    "attribution (textul cerut de licență sau null), mood, bpm, tags (pentru ambianță). O piesă "
    "fără commercial_ok true, fără licență sau cu alt sha256 nu este folosită niciodată. "
    "Intrările se adaugă cu scripts/music_add.py."
)


class MusicAddError(ValueError):
    """A track that cannot be vouched for, with the reason in Romanian."""


def licence_text(licence_type: str, date: str) -> str:
    """The licence field: Google's words, the source and the download date, then what the
    studio makes of it (YouTube's videos, monetised included; elsewhere unconfirmed; never
    redistributed)."""
    if licence_type == "standard":
        return (
            "YouTube Audio Library, licență standard — «Licență pentru Biblioteca audio "
            f"YouTube», cum o arată YouTube Studio: „{STANDARD_WORDS}” Descărcată din YouTube "
            "Studio → Bibliotecă audio (filtrul „Atribuirea nu este obligatorie”) la "
            f"{date}, în contul Proprietarului. Folosire în videoclipurile canalului, inclusiv "
            "monetizate; în afara YouTube neconfirmat de Google; nu se redistribuie."
        )
    return (
        "Creative Commons Attribution 4.0 (CC BY 4.0), prin YouTube Audio Library; descărcată "
        f"din YouTube Studio → Bibliotecă audio la {date}, în contul Proprietarului. Creditul "
        "din câmpul attribution este obligatoriu în descrierea videoclipului; folosire pe orice "
        "platformă cu credit; nu se redistribuie prin studio."
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _words(value: str | None) -> list[str]:
    return [part.strip().lower() for part in str(value or "").split(",") if part.strip()]


def _read(library: Path) -> dict[str, Any]:
    if not library.exists():
        return {"notes_ro": NOTES_RO, "tracks": []}
    data = json.loads(library.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("tracks"), list):
        raise MusicAddError(f"biblioteca {library} nu are lista „tracks”")
    return data


def _write(library: Path, data: dict[str, Any]) -> None:
    library.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    library.write_text(text, encoding="utf-8", newline="\n")


def add_track(
    source: Path,
    *,
    library: Path,
    track_id: str,
    kind: str,
    title: str,
    artist: str = "",
    genre: str = "",
    mood: str | list[str] | None = None,
    tags: str | list[str] | None = None,
    licence_type: str = "standard",
    attribution: str | None = None,
    duration: str = "",
    date: str | None = None,
) -> dict[str, Any]:
    """Copy ``source`` beside ``library`` and append its entry; the entry, as written.

    Refused (`MusicAddError`, nothing written): a missing or non-audio file, an id that is
    not a slug or already used, a file already registered (same sha256), a kind the loader
    does not know, a mood the studio does not know (`MOOD_WORDS`), a bed without a mood, an
    ambience without a tag, a Creative Commons track without its credit. After the write the
    entry is read back through `load_library`; a refusal there is this error too.
    """
    source = Path(source).expanduser()
    library = Path(library)
    moods = _words(mood) if isinstance(mood, str) else [m.lower() for m in (mood or [])]
    tag_words = _words(tags) if isinstance(tags, str) else [t.lower() for t in (tags or [])]
    if not source.is_file():
        raise MusicAddError(f"fișierul {source} nu există")
    if source.suffix.lower() not in _AUDIO:
        raise MusicAddError(f"{source.name} nu este un fișier audio ({', '.join(_AUDIO)})")
    if not _ID.match(track_id):
        raise MusicAddError(
            f"id-ul „{track_id}” nu este un nume stabil (litere mici, cifre și cratime, 3-61)"
        )
    if kind not in music_library.KINDS:
        raise MusicAddError(f"tipul „{kind}” nu este music sau ambience")
    if licence_type not in LICENCE_TYPES:
        raise MusicAddError(f"licența „{licence_type}” nu este standard sau cc-by")
    unknown = [m for m in moods if m not in music_library.MOOD_WORDS]
    if unknown:
        raise MusicAddError(
            f"stările {', '.join(unknown)} nu sunt cunoscute studioului "
            f"({', '.join(music_library.MOOD_WORDS)})"
        )
    if kind == "music" and not moods:
        raise MusicAddError("o piesă de fundal are nevoie de cel puțin o stare (--mood)")
    if kind == "ambience" and not tag_words:
        raise MusicAddError("o ambianță are nevoie de cel puțin un cuvânt (--tags)")
    credit = " ".join(str(attribution or "").split()) or None
    if licence_type == "cc-by" and not credit:
        raise MusicAddError(
            "o piesă Creative Commons se înregistrează doar cu creditul ei (--attribution), "
            "copiat din fereastra licenței"
        )
    data = _read(library)
    if any(isinstance(t, dict) and t.get("id") == track_id for t in data["tracks"]):
        raise MusicAddError(f"id-ul „{track_id}” este deja în bibliotecă")
    digest = _sha256(source)
    same = next(
        (t for t in data["tracks"] if isinstance(t, dict) and t.get("sha256") == digest), None
    )
    if same is not None:
        raise MusicAddError(f"fișierul este deja înregistrat ca „{same.get('id')}”")

    when = date or datetime.now(UTC).date().isoformat()
    # Beside the library file: the loader refuses a file outside the library's folder.
    relative = f"{track_id}{source.suffix.lower()}"
    target = library.parent / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and _sha256(target) != digest:
        raise MusicAddError(f"{relative} există deja cu alt conținut; alege alt id")
    shutil.copyfile(source, target)
    entry: dict[str, Any] = {
        "id": track_id,
        "kind": kind,
        "file": relative,
        "sha256": digest,
        "licence": licence_text(licence_type, when),
        "commercial_ok": True,
        "redistributable": False,
        "attribution": credit,
        "mood": moods,
        "bpm": None,
        "tags": tag_words,
        # Read by people and the ledger, ignored by the loader.
        "title": title,
        "artist": artist,
        "genre": genre,
        "duration": duration,
        "source": SOURCE,
        "licence_type": licence_type,
        "added": when,
    }
    data["tracks"].append(entry)
    _write(library, data)
    loaded = music_library.load_library(library)
    refusal = next((r for r in loaded.refused if r.get("id") == track_id), None)
    if refusal is not None:
        raise MusicAddError(f"intrarea scrisă este refuzată de bibliotecă: {refusal['reason']}")
    return entry


def check(library: Path) -> music_library.Library:
    """The library as the studio reads it: its usable tracks and every refused entry."""
    return music_library.load_library(library)


def _quiet_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        # Romanian words on a console or a pipe in another code page: never a crash.
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file", nargs="?", type=Path, help="the downloaded audio file")
    parser.add_argument("--id", dest="track_id", help="stable id (slug), e.g. yal-calm-after-all")
    parser.add_argument("--kind", choices=music_library.KINDS, default="music")
    parser.add_argument("--title", default="")
    parser.add_argument("--artist", default="")
    parser.add_argument("--genre", default="")
    parser.add_argument("--duration", default="", help="as Studio shows it, e.g. 3:07")
    parser.add_argument("--mood", default="", help="comma-separated: calm,wonder (a bed)")
    parser.add_argument("--tags", default="", help="comma-separated: rain,storm (an ambience)")
    parser.add_argument("--licence-type", choices=LICENCE_TYPES, default="standard")
    parser.add_argument("--attribution", default=None, help="the CC credit, copied verbatim")
    parser.add_argument("--date", default=None, help="download date YYYY-MM-DD (default: today)")
    parser.add_argument(
        "--library",
        type=Path,
        default=None,
        help="the library file (default: the Owner's, config/music/music_library.json, or the "
        "one STUDIO_MUSIC_LIBRARY names)",
    )
    parser.add_argument("--check", action="store_true", help="list refused entries and stop")
    args = parser.parse_args(argv)
    _quiet_console()
    library = args.library or (
        music_library.LIBRARY_PATH
        if music_library.LIBRARY_PATH != music_library.SHIPPED_LIBRARY
        else music_library.OWNER_LIBRARY
    )

    if args.check:
        loaded = check(library)
        print(f"Biblioteca {library}: {len(loaded.tracks)} piese folosibile")
        for track in loaded.tracks:
            what = ", ".join(track.mood) if track.kind == "music" else ", ".join(track.tags)
            print(f"    {track.id} ({track.kind}: {what})")
        for refused in loaded.refused:
            print(f"    REFUZATĂ {refused['id']}: {refused['reason']}")
        return 1 if loaded.refused else 0

    if args.file is None or not args.track_id:
        parser.error("dă fișierul și --id (sau --check)")
    try:
        entry = add_track(
            args.file,
            library=library,
            track_id=args.track_id,
            kind=args.kind,
            title=args.title or args.file.stem,
            artist=args.artist,
            genre=args.genre,
            mood=args.mood,
            tags=args.tags,
            licence_type=args.licence_type,
            attribution=args.attribution,
            duration=args.duration,
            date=args.date,
        )
    except MusicAddError as exc:
        print(f"Neînregistrat: {exc}")
        return 1
    what = ", ".join(entry["mood"]) if entry["kind"] == "music" else ", ".join(entry["tags"])
    print(f"Înregistrat: {entry['id']} ({entry['kind']}: {what}) → {entry['file']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
