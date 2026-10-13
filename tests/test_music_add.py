"""scripts/music_add.py puts a downloaded track into the library the way the loader vouches
for it, and refuses what the loader would refuse — before a film does.

2026-10-11: the Owner chose YouTube's Audio Library for the shorts' beds and ambiences and had
the first tracks downloaded from his Studio. The library ships empty; this command fills his.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from app.media import music_library

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import music_add  # noqa: E402


def a_download(folder: Path, name: str, payload: bytes) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(payload)
    return path


def test_a_standard_track_is_copied_registered_and_usable(tmp_path):
    library = tmp_path / "lib" / "music_library.json"
    source = a_download(
        tmp_path / "downloads", "After All - Geographer.mp3", b"ID3" + b"\x01" * 300
    )

    entry = music_add.add_track(
        source,
        library=library,
        track_id="yal-calm-after-all",
        kind="music",
        title="After All",
        artist="Geographer",
        genre="Muzică ambientală",
        mood="calm, wonder",
        duration="3:07",
        date="2026-10-11",
    )

    copied = library.parent / "yal-calm-after-all.mp3"
    assert copied.read_bytes() == source.read_bytes()
    assert entry["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert entry["file"] == "yal-calm-after-all.mp3"
    assert entry["commercial_ok"] is True and entry["redistributable"] is False
    assert entry["attribution"] is None and entry["mood"] == ["calm", "wonder"]
    # Google's words, the source and the date are in the licence the ledger will carry.
    assert "Nu este necesară nicio atribuire" in entry["licence"]
    assert "2026-10-11" in entry["licence"] and "nu se redistribuie" in entry["licence"]
    loaded = music_library.load_library(library)
    assert loaded.refused == []
    (track,) = loaded.tracks
    assert track.id == "yal-calm-after-all" and track.mood == ("calm", "wonder")
    assert music_library.choose_bed(loaded, mood_text="a quiet night", seed="x") is track
    data = json.loads(library.read_text(encoding="utf-8"))
    assert data["notes_ro"] and data["tracks"][0]["title"] == "After All"


def test_an_ambience_needs_its_tags_and_is_found_by_them(tmp_path):
    library = tmp_path / "lib" / "music_library.json"
    source = a_download(tmp_path / "downloads", "Rain On Rooftop.mp3", b"ID3" + b"\x02" * 300)
    with pytest.raises(music_add.MusicAddError, match="tags"):
        music_add.add_track(
            source, library=library, track_id="yal-amb-rain", kind="ambience", title="Rain"
        )
    music_add.add_track(
        source,
        library=library,
        track_id="yal-amb-rain",
        kind="ambience",
        title="Rain On Rooftop",
        tags="rain, storm",
    )
    loaded = music_library.load_library(library)
    assert music_library.choose_ambience(loaded, "rain on the roof").id == "yal-amb-rain"
    assert music_library.choose_bed(loaded, mood_text="rain", seed="x") is None


def test_a_duplicate_id_or_file_a_bad_mood_and_a_creditless_cc_track_are_refused(tmp_path):
    library = tmp_path / "lib" / "music_library.json"
    source = a_download(tmp_path / "downloads", "A.mp3", b"ID3" + b"\x03" * 300)
    other = a_download(tmp_path / "downloads", "B.mp3", b"ID3" + b"\x04" * 300)
    music_add.add_track(
        source, library=library, track_id="yal-a", kind="music", title="A", mood="dark"
    )
    before = library.read_text(encoding="utf-8")

    with pytest.raises(music_add.MusicAddError, match="deja în bibliotecă"):
        music_add.add_track(
            other, library=library, track_id="yal-a", kind="music", title="B", mood="dark"
        )
    with pytest.raises(music_add.MusicAddError, match="deja înregistrat"):
        music_add.add_track(
            source, library=library, track_id="yal-a2", kind="music", title="A", mood="dark"
        )
    with pytest.raises(music_add.MusicAddError, match="nu sunt cunoscute"):
        music_add.add_track(
            other, library=library, track_id="yal-b", kind="music", title="B", mood="jolly"
        )
    with pytest.raises(music_add.MusicAddError, match="creditul"):
        music_add.add_track(
            other,
            library=library,
            track_id="yal-b",
            kind="music",
            title="B",
            mood="dark",
            licence_type="cc-by",
        )
    with pytest.raises(music_add.MusicAddError, match="nume stabil"):
        music_add.add_track(
            other, library=library, track_id="Bad Id", kind="music", title="B", mood="dark"
        )
    assert library.read_text(encoding="utf-8") == before, "a refusal wrote nothing"
    assert not (library.parent / "yal-b.mp3").exists()

    entry = music_add.add_track(
        other,
        library=library,
        track_id="yal-b",
        kind="music",
        title="B",
        mood="dark",
        licence_type="cc-by",
        attribution="Song by X, licensed under CC BY 4.0",
    )
    assert entry["attribution"] == "Song by X, licensed under CC BY 4.0"
    assert "CC BY 4.0" in entry["licence"]


def test_check_names_an_entry_the_loader_refuses(tmp_path, capsys):
    library = tmp_path / "lib" / "music_library.json"
    source = a_download(tmp_path / "downloads", "A.mp3", b"ID3" + b"\x05" * 300)
    music_add.add_track(
        source, library=library, track_id="yal-a", kind="music", title="A", mood="epic"
    )
    (library.parent / "yal-a.mp3").write_bytes(b"other bytes")

    code = music_add.main(["--check", "--library", str(library)])

    assert code == 1
    out = capsys.readouterr().out
    assert "REFUZATĂ yal-a" in out and "sha256" in out


def test_the_command_line_registers_a_file(tmp_path, capsys):
    library = tmp_path / "lib" / "music_library.json"
    source = a_download(tmp_path / "downloads", "Wind In Pine Trees.mp3", b"ID3" + b"\x06" * 300)

    code = music_add.main(
        [
            str(source),
            "--id",
            "yal-amb-wind-pines",
            "--kind",
            "ambience",
            "--title",
            "Wind In Pine Trees",
            "--tags",
            "wind,trees",
            "--library",
            str(library),
            "--date",
            "2026-10-11",
        ]
    )

    assert code == 0
    assert "Înregistrat: yal-amb-wind-pines" in capsys.readouterr().out
    assert music_add.main(["--check", "--library", str(library)]) == 0


def test_the_studio_reads_the_owners_library_beside_his_files_when_it_exists(tmp_path):
    """The release ships config/music_library.json empty; the Owner's library lives beside his
    files in config/music/ (ignored by git) and is read when it exists; STUDIO_MUSIC_LIBRARY
    names any other, kept anywhere (2026-10-11)."""
    shipped = tmp_path / "config" / "music_library.json"
    owner = tmp_path / "config" / "music" / "music_library.json"
    assert music_library.library_path({}, owner=owner, shipped=shipped) == shipped
    owner.parent.mkdir(parents=True)
    owner.write_text('{"tracks": []}', encoding="utf-8")
    assert music_library.library_path({}, owner=owner, shipped=shipped) == owner
    named = tmp_path / "elsewhere" / "library.json"
    assert (
        music_library.library_path(
            {"STUDIO_MUSIC_LIBRARY": str(named)}, owner=owner, shipped=shipped
        )
        == named
    )
    assert music_library.OWNER_LIBRARY.parent.name == "music"
    assert music_library.SHIPPED_LIBRARY.name == "music_library.json"
