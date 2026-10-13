"""The characters' own portraits become their bibles' reference pictures (2026-10-11).

The Owner: «Cauta pozele caracterelor/agentilor. Sa le putem include in bible ca la serial sa
stim dupa ce caractere sa ne luam.» Eight character sheets drawn on 2026-09-12 from the prompts
in «Agents ID and Bible/CHARACTER_BIBLES.md» lay in that folder while every slot of every bible
stayed null, and the only route that fills a slot buys pictures (his press,
`generate_character_reference_set`). `app.workflows.passes.character_references` registers the
files named in config/character_references.json for free: each verified file is copied into
the studio's media storage, becomes a MediaAsset row the way the paid route writes one, and
fills the bible's empty portrait slot, once.

Proven here with no provider at all (every socket is refused by conftest): a verified portrait
is registered once and a second pass changes nothing; what was registered is what
`image_reference_for_scene` hands a scene; a file that is missing, that changed since it was
verified, that is not a PNG, or that names nobody is reported and nothing is written; a slot
already holding a picture is never overwritten; the same picture is not registered twice even
after its slot was emptied, and a new picture never overwrites the file of the old one; the
Owner's media folder wins over the default; and the shipped file names every portrait crop at
the hash it was verified at, each cut from one sheet in the folder (2026-10-11: a whole sheet,
with its title, labels, handwritten quote and logos, is a poor picture to draw a face from, so
the registered picture is the sheet's PORTRAIT panel cut clean of all of them).

Review of 2026-10-11 (three more rules, each proven to fail without its fix): a character
whose look the Owner locked is left to him, before the pass and when the lock lands while it
runs; a slot pointing at an asset row that is gone («Start over» keeps the bibles and deletes
the assets) is empty, not filled forever; and what the pass reports is worded for the Owner.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from app.config import ROOT
from app.maintenance import reset_history
from app.media import factory
from app.media.models import CharacterBible, MediaAsset
from app.media.services import (
    DEFAULT_CHARACTERS,
    ReferenceRequired,
    image_reference_for_scene,
    seed_default_character_bibles,
)
from app.models import DomainEvent
from app.workflows.passes import WatchdogContext, registered_passes
from app.workflows.passes import character_references as pass_module
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_character_references import lock_the_look, png_bytes, reference_the_character

SARAH = "Sarah Executive"
ARIS = "Dr. Aris Researcher"
ELENA = "Elena Fact-Checker"
MARCUS = "Marcus Scriptwriter"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def studio(engine, tmp_path, monkeypatch) -> Path:
    """The eight default bibles, a repository of the Owner's own with its pictures folder, and
    the pass pointed at that repository's config file."""
    seed_default_character_bibles(engine)
    source_root = tmp_path / "repo"
    (source_root / "Agents ID and Bible").mkdir(parents=True)
    (source_root / "config").mkdir()
    monkeypatch.setattr(pass_module, "CONFIG_FILE", source_root / "config" / "references.json")
    monkeypatch.setattr(pass_module, "SOURCE_ROOT", source_root)
    return source_root


def a_picture(
    source_root: Path, name: str = "Sarah.png", *, width: int = 96, height: int = 128
) -> tuple[str, bytes]:
    """One PNG in the pictures folder; (the file as the config names it, its bytes)."""
    data = png_bytes(width, height)
    (source_root / "Agents ID and Bible" / name).write_bytes(data)
    return f"Agents ID and Bible/{name}", data


def write_config(source_root: Path, characters: dict[str, dict[str, Any]]) -> None:
    (source_root / "config" / "references.json").write_text(
        json.dumps({"version": 1, "characters": characters}), encoding="utf-8"
    )


def register(engine, settings: Any = None) -> dict[str, Any]:
    return dict(
        pass_module.register_character_portraits(WatchdogContext(engine, settings, "watchdog"))
    )


def bible(session: Session, name: str) -> CharacterBible:
    row = session.scalar(select(CharacterBible).where(CharacterBible.canonical_name == name))
    assert row is not None, name
    return row


def bible_id(engine, name: str) -> str:
    with Session(engine) as session:
        return bible(session, name).id


def portrait_of(engine, name: str) -> str | None:
    with Session(engine) as session:
        return (bible(session, name).reference_assets_json or {}).get("portrait")


def assets(engine) -> int:
    with Session(engine) as session:
        return int(session.scalar(select(func.count()).select_from(MediaAsset)) or 0)


def registrations(engine) -> list[DomainEvent]:
    with Session(engine) as session:
        return list(
            session.scalars(
                select(DomainEvent).where(DomainEvent.event_type == pass_module.REGISTERED_EVENT)
            )
        )


# ------------------------------------------------------------------ registered once


def test_a_verified_portrait_is_registered_once(engine, studio, private_media_storage):
    file, data = a_picture(studio)
    write_config(studio, {SARAH: {"file": file, "sha256": sha(data)}})

    first = register(engine)

    assert [entry["character"] for entry in first["registered"]] == [SARAH]
    assert first["problems"] == []
    with Session(engine) as session:
        row = bible(session, SARAH)
        assert row.identity_locks_json == {}, "nothing of his was decided"
        asset = session.get(MediaAsset, row.reference_assets_json["portrait"])
        assert asset is not None
        expected = (
            private_media_storage["REFERENCE_STORAGE_ROOT"] / "references" / row.id / "portrait.png"
        )
        assert Path(asset.uri_or_path) == expected
        assert expected.read_bytes() == data
        assert (asset.asset_type, asset.mime_type) == ("IMAGE", "image/png")
        assert (asset.width, asset.height, asset.file_size_bytes) == (96, 128, len(data))
        assert asset.provenance_hash == sha(data)
        assert asset.license_status == "ORIGINAL_AI_GENERATED"
        event = session.scalar(select(DomainEvent).where(DomainEvent.event_id == asset.event_id))
        assert event is not None and event.event_type == pass_module.REGISTERED_EVENT
        assert event.payload["character_id"] == row.id
        assert event.payload["slot"] == "portrait"
        assert event.payload["sha256"] == sha(data)
        assert event.payload["source_file"] == file
        assert event.correlation_id == "watchdog"
    assert first["registered"][0]["asset_id"] == asset.id

    second = register(engine)

    assert second["registered"] == [] and second["filled"] == [SARAH]
    assert assets(engine) == 1 and len(registrations(engine)) == 1


def test_what_was_registered_is_what_a_scene_is_drawn_from(engine, studio):
    file, data = a_picture(studio)
    write_config(studio, {SARAH: {"file": file, "sha256": sha(data)}})
    register(engine)
    sarah = bible_id(engine, SARAH)

    reference = image_reference_for_scene(engine, [sarah])

    assert reference is not None
    assert (reference["slot"], reference["canonical_name"]) == ("portrait", SARAH)
    assert reference["required"] is False, "no lock was set: the picture helps, it blocks nobody"
    assert reference["mime_type"] == "image/png"
    assert Path(reference["path"]).read_bytes() == data
    payload = factory.reference_payload(engine, [sarah])
    assert payload is not None and payload["bytes"] == data


def test_the_pass_is_registered_at_its_place_in_the_watchdog():
    entry = next(found for found in registered_passes() if found.name == "character_references")
    assert entry.order == 140
    assert entry.function is pass_module.register_character_portraits


# ------------------------------------------------------------------ nothing unverified


def test_a_missing_changed_or_foreign_file_is_reported_and_nothing_is_written(
    engine, studio, private_media_storage
):
    good_file, good = a_picture(studio, "Aris.png")
    (studio / "Agents ID and Bible" / "Elena.png").write_bytes(b"not a png at all")
    write_config(
        studio,
        {
            SARAH: {"file": "Agents ID and Bible/Sarah.png", "sha256": "0" * 64},
            ARIS: {"file": good_file, "sha256": "f" * 64},
            ELENA: {"file": "Agents ID and Bible/Elena.png", "sha256": sha(b"not a png at all")},
            "Nobody Here": {"file": good_file, "sha256": sha(good)},
            MARCUS: {"file": good_file},
        },
    )

    result = register(engine)

    assert result["registered"] == []
    assert {(problem["character"], problem["problem"]) for problem in result["problems"]} == {
        (SARAH, "MISSING_FILE"),
        (ARIS, "MISMATCHED_FILE"),
        (ELENA, "NOT_PNG"),
        ("Nobody Here", "NO_BIBLE"),
        (MARCUS, "ENTRY_INCOMPLETE"),
    }
    for name in (SARAH, ARIS, ELENA, MARCUS):
        assert portrait_of(engine, name) is None
    assert assets(engine) == 0 and registrations(engine) == []
    assert not (private_media_storage["REFERENCE_STORAGE_ROOT"] / "references").exists()


def test_an_unreadable_config_is_a_problem_not_a_crash(engine, studio):
    result = register(engine)

    assert result["registered"] == []
    assert [problem["problem"] for problem in result["problems"]] == ["CONFIG_UNREADABLE"]


def test_a_slot_that_holds_a_picture_is_never_overwritten(engine, studio, private_media_storage):
    kept = reference_the_character(engine, bible_id(engine, SARAH))
    file, data = a_picture(studio)
    write_config(studio, {SARAH: {"file": file, "sha256": sha(data)}})

    result = register(engine)

    assert result["registered"] == [] and result["filled"] == [SARAH]
    assert portrait_of(engine, SARAH) == kept
    assert assets(engine) == 1 and registrations(engine) == []
    assert not (private_media_storage["REFERENCE_STORAGE_ROOT"] / "references").exists()


def test_the_same_picture_is_not_registered_again_once_its_slot_was_emptied(engine, studio):
    file, data = a_picture(studio)
    write_config(studio, {SARAH: {"file": file, "sha256": sha(data)}})
    first = register(engine)
    first_asset = first["registered"][0]["asset_id"]
    # Someone empties the slot (his decision, or an edit of the bible): not a loss to repair.
    with Session(engine) as session, session.begin():
        row = bible(session, SARAH)
        row.reference_assets_json = {**row.reference_assets_json, "portrait": None}

    again = register(engine)

    assert again["registered"] == [] and again["withheld"] == [SARAH]
    assert portrait_of(engine, SARAH) is None
    assert assets(engine) == 1 and len(registrations(engine)) == 1

    # A new picture is a new registration, and the old one's file is left exactly as it was.
    file, replaced = a_picture(studio, width=120, height=160)
    write_config(studio, {SARAH: {"file": file, "sha256": sha(replaced)}})

    third = register(engine)

    assert [entry["character"] for entry in third["registered"]] == [SARAH]
    with Session(engine) as session:
        old = session.get(MediaAsset, first_asset)
        new = session.get(MediaAsset, third["registered"][0]["asset_id"])
        assert old is not None and new is not None and new.id != old.id
        assert Path(old.uri_or_path).read_bytes() == data
        assert Path(new.uri_or_path).read_bytes() == replaced
        assert Path(new.uri_or_path).parent == Path(old.uri_or_path).parent
        assert Path(new.uri_or_path).name == f"portrait-{sha(replaced)[:12]}.png"
        assert (new.width, new.height) == (120, 160)
    assert portrait_of(engine, SARAH) == new.id
    assert assets(engine) == 2 and len(registrations(engine)) == 2


# ------------------------------------------------------------------ where it is kept


def test_the_owners_media_folder_wins_over_the_default(engine, settings, studio, tmp_path):
    file, data = a_picture(studio)
    write_config(studio, {SARAH: {"file": file, "sha256": sha(data)}})
    owners = settings.model_copy(update={"media_root": tmp_path / "owner_media"})

    result = register(engine, owners)

    path = Path(result["registered"][0]["path"])
    assert (
        path == tmp_path / "owner_media" / "references" / bible_id(engine, SARAH) / "portrait.png"
    )
    assert path.read_bytes() == data
    with Session(engine) as session:
        asset = session.get(MediaAsset, portrait_of(engine, SARAH))
        assert asset is not None and Path(asset.uri_or_path) == path


# ------------------------------------------------------------------ the shipped file


def test_the_shipped_file_names_every_portrait_crop_at_its_verified_hash():
    """Each character's picture is the PORTRAIT panel of its sheet, cut clean of the sheet's
    title, labels, handwritten quote and logos (2026-10-11): the config names the crop, the
    sheet it was cut from and the box. A crop dropped in the folder without being looked at, a
    renamed file, a sheet nobody cropped, or a bible renamed under the config fails here, not
    in the studio at night."""
    document = json.loads(pass_module.CONFIG_FILE.read_text(encoding="utf-8"))
    names = {entry["canonical_name"] for entry in DEFAULT_CHARACTERS}
    folder = ROOT / "Agents ID and Bible"
    named: set[Path] = set()
    cropped: set[Path] = set()
    for name, entry in document["characters"].items():
        assert name in names, name
        path = ROOT / entry["file"]
        assert path.parent == folder / "portraits", entry["file"]
        assert path.is_file(), entry["file"]
        content = path.read_bytes()
        assert sha(content) == entry["sha256"], f"{entry['file']} changed since it was verified"
        assert pass_module.png_dimensions(content) == tuple(entry["pixels"])
        sheet = ROOT / entry["cropped_from"]
        assert sheet.parent == folder and sheet.is_file(), entry["cropped_from"]
        sheet_size = pass_module.png_dimensions(sheet.read_bytes())
        assert sheet_size is not None, entry["cropped_from"]
        left, top, right, bottom = entry["crop_box"]
        assert 0 <= left < right <= sheet_size[0] and 0 <= top < bottom <= sheet_size[1], name
        assert tuple(entry["pixels"]) == (right - left, bottom - top), f"{name}: not its box"
        named.add(path.resolve())
        cropped.add(sheet.resolve())
    assert len(named) == len(document["characters"]), "two characters name one picture"
    assert len(cropped) == len(document["characters"]), "two characters are cut from one sheet"
    assert {path.resolve() for path in (folder / "portraits").glob("*.png")} == named
    assert {path.resolve() for path in folder.glob("*.png")} == cropped


def test_each_shipped_portrait_is_its_sheets_pixels_at_the_recorded_box():
    """The crop was cut from the sheet with no resampling, so it is exactly the sheet's pixels
    inside crop_box: a crop retouched, rescaled or taken from another picture fails here."""
    Image = pytest.importorskip("PIL.Image")
    document = json.loads(pass_module.CONFIG_FILE.read_text(encoding="utf-8"))
    for name, entry in document["characters"].items():
        with Image.open(ROOT / entry["cropped_from"]) as sheet:
            expected = sheet.convert("RGB").crop(tuple(entry["crop_box"]))
        with Image.open(ROOT / entry["file"]) as crop:
            assert crop.mode == "RGB", name
            assert crop.size == expected.size, name
            assert crop.tobytes() == expected.tobytes(), f"{name}: not the sheet's pixels"


def test_the_shipped_file_registers_every_default_character_once(engine, private_media_storage):
    """The real file against the eight default bibles, into a private media folder: every
    character gets its portrait, nothing is reported, and a second pass changes nothing."""
    seed_default_character_bibles(engine)

    first = register(engine)

    assert first["problems"] == []
    assert sorted(entry["character"] for entry in first["registered"]) == sorted(
        entry["canonical_name"] for entry in DEFAULT_CHARACTERS
    )
    root = private_media_storage["REFERENCE_STORAGE_ROOT"] / "references"
    for entry in first["registered"]:
        reference = image_reference_for_scene(engine, [entry["character_id"]])
        assert reference is not None and reference["asset_id"] == entry["asset_id"]
        assert Path(reference["path"]) == root / entry["character_id"] / "portrait.png"
        assert sha(Path(reference["path"]).read_bytes()) == entry["sha256"]

    second = register(engine)

    assert second["registered"] == [] and len(second["filled"]) == len(DEFAULT_CHARACTERS)


# ------------------------------------------------------------------ his locks (review 2026-10-11)


def meanwhile(monkeypatch, change) -> None:
    """Something else commits ``change`` between the pass's read and its write transaction.

    The write lock is the first statement of that transaction (`app.db.lock_for_write`), so a
    change made just before it is exactly what «his press or another process» would have
    committed meanwhile; the pass's own re-read must see it.
    """
    import app.db as db_module

    real = db_module.lock_for_write
    done: list[bool] = []

    def interposed(session) -> None:
        if not done:
            done.append(True)
            change()
        real(session)

    monkeypatch.setattr(db_module, "lock_for_write", interposed)


def test_a_locked_look_is_left_to_the_owner(engine, studio, private_media_storage):
    """A character whose look is locked and has no reference refuses its scene until the
    Owner produces the set (`ReferenceRequired`: «The Owner produces the set; the scene is
    made after»). Filling that slot with the free sheet lifted his block by code; so a locked
    character is reported under ``locked`` and nothing is written for it, while an unlocked
    one named in the same config is registered as before."""
    lock_the_look(engine, bible_id(engine, SARAH))
    sarah_file, sarah = a_picture(studio)
    aris_file, aris = a_picture(studio, "Aris.png")
    write_config(
        studio,
        {
            SARAH: {"file": sarah_file, "sha256": sha(sarah)},
            ARIS: {"file": aris_file, "sha256": sha(aris)},
        },
    )

    result = register(engine)

    assert result["locked"] == [SARAH]
    assert [entry["character"] for entry in result["registered"]] == [ARIS]
    assert result["problems"] == []
    assert portrait_of(engine, SARAH) is None
    with pytest.raises(ReferenceRequired):
        image_reference_for_scene(engine, [bible_id(engine, SARAH)])
    assert assets(engine) == 1 and len(registrations(engine)) == 1
    references = private_media_storage["REFERENCE_STORAGE_ROOT"] / "references"
    assert not (references / bible_id(engine, SARAH)).exists()
    assert (references / bible_id(engine, ARIS) / "portrait.png").read_bytes() == aris


def test_a_look_locked_meanwhile_is_left_to_him_too(engine, studio, monkeypatch):
    file, data = a_picture(studio)
    write_config(studio, {SARAH: {"file": file, "sha256": sha(data)}})
    sarah = bible_id(engine, SARAH)
    meanwhile(monkeypatch, lambda: lock_the_look(engine, sarah))

    result = register(engine)

    assert result["registered"] == [] and result["locked"] == [SARAH]
    assert portrait_of(engine, SARAH) is None
    assert assets(engine) == 0 and registrations(engine) == []


def test_a_slot_filled_meanwhile_is_not_replaced(engine, studio, monkeypatch):
    file, data = a_picture(studio)
    write_config(studio, {SARAH: {"file": file, "sha256": sha(data)}})
    sarah = bible_id(engine, SARAH)
    kept: list[str] = []
    meanwhile(monkeypatch, lambda: kept.append(reference_the_character(engine, sarah)))

    result = register(engine)

    assert result["registered"] == [] and result["filled"] == [SARAH]
    assert portrait_of(engine, SARAH) == kept[0]
    assert assets(engine) == 1 and registrations(engine) == []


def test_a_bible_deleted_meanwhile_is_a_problem_not_a_crash(engine, studio, monkeypatch):
    file, data = a_picture(studio)
    write_config(studio, {SARAH: {"file": file, "sha256": sha(data)}})
    sarah = bible_id(engine, SARAH)

    def delete_the_bible() -> None:
        with Session(engine) as session, session.begin():
            session.delete(session.get(CharacterBible, sarah))

    meanwhile(monkeypatch, delete_the_bible)

    result = register(engine)

    assert result["registered"] == []
    assert [(p["character"], p["problem"]) for p in result["problems"]] == [(SARAH, "NO_BIBLE")]
    assert assets(engine) == 0 and registrations(engine) == []


# ------------------------------------------------------------------ a slot that dangles


def test_a_slot_whose_asset_row_is_gone_is_filled_again(engine, studio):
    """«Start over» (`maintenance.reset_history`) deletes the media assets and the ledger and
    keeps the bibles, so every slot pointed at a row that was gone; the pass counted them
    filled forever and the scenes had no reference. A slot whose asset row is missing is
    empty, and with the marks gone too the picture is registered again, onto the same file."""
    file, data = a_picture(studio)
    write_config(studio, {SARAH: {"file": file, "sha256": sha(data)}})
    first = register(engine)
    sarah = bible_id(engine, SARAH)
    old = first["registered"][0]["asset_id"]

    reset_history(engine)

    assert portrait_of(engine, SARAH) == old, "the slot dangles after the reset"
    assert image_reference_for_scene(engine, [sarah]) is None

    again = register(engine)

    assert [entry["character"] for entry in again["registered"]] == [SARAH]
    assert again["filled"] == [] and again["withheld"] == []
    new = again["registered"][0]["asset_id"]
    assert new != old and portrait_of(engine, SARAH) == new
    assert Path(again["registered"][0]["path"]) == Path(first["registered"][0]["path"])
    reference = image_reference_for_scene(engine, [sarah])
    assert reference is not None and reference["asset_id"] == new
    assert Path(reference["path"]).read_bytes() == data
    assert assets(engine) == 1 and len(registrations(engine)) == 1


def test_a_dangling_slot_does_not_bypass_the_marks(engine, studio):
    """Only the asset row gone, the ledger intact: the slot is empty, and the picture it held
    was registered once, so it is withheld as after any emptied slot, not registered twice."""
    file, data = a_picture(studio)
    write_config(studio, {SARAH: {"file": file, "sha256": sha(data)}})
    first = register(engine)
    with Session(engine) as session, session.begin():
        session.delete(session.get(MediaAsset, first["registered"][0]["asset_id"]))

    again = register(engine)

    assert again["registered"] == [] and again["filled"] == []
    assert again["withheld"] == [SARAH]
    assert assets(engine) == 0 and len(registrations(engine)) == 1


# ------------------------------------------------------------------ what it reports


def test_a_folder_that_cannot_be_written_is_a_problem_not_a_crash(
    engine, studio, private_media_storage
):
    file, data = a_picture(studio)
    write_config(studio, {SARAH: {"file": file, "sha256": sha(data)}})
    root = private_media_storage["REFERENCE_STORAGE_ROOT"]
    root.parent.mkdir(parents=True, exist_ok=True)
    root.write_bytes(b"a file where the folder should be")

    result = register(engine)

    assert result["registered"] == []
    assert [(p["character"], p["problem"]) for p in result["problems"]] == [(SARAH, "NOT_WRITABLE")]
    assert portrait_of(engine, SARAH) is None
    assert assets(engine) == 0 and registrations(engine) == []


def test_the_problems_are_worded_for_the_owner(engine, studio, private_media_storage):
    """The codes stay English for code to match; the detail beside each is what a person
    reads, so it is Romanian like every other string that may reach the Owner."""
    good_file, good = a_picture(studio, "Aris.png")
    (studio / "Agents ID and Bible" / "Elena.png").write_bytes(b"not a png at all")
    write_config(
        studio,
        {
            SARAH: {"file": "Agents ID and Bible/Sarah.png", "sha256": "0" * 64},
            ARIS: {"file": good_file, "sha256": "f" * 64},
            ELENA: {"file": "Agents ID and Bible/Elena.png", "sha256": sha(b"not a png at all")},
            "Nobody Here": {"file": good_file, "sha256": sha(good)},
            MARCUS: {"file": good_file},
        },
    )

    worded = {p["problem"]: p["detail"] for p in register(engine)["problems"]}

    assert "fișierul nu se poate citi" in worded["MISSING_FILE"]
    assert "uită-te la ea din nou" in worded["MISMATCHED_FILE"]
    assert "cere un PNG" in worded["NOT_PNG"]
    assert "niciun personaj" in worded["NO_BIBLE"]
    assert "'sha256'" in worded["ENTRY_INCOMPLETE"] and "verificată" in worded["ENTRY_INCOMPLETE"]

    (studio / "config" / "references.json").write_text("{", encoding="utf-8")
    [unreadable] = register(engine)["problems"]
    assert unreadable["problem"] == "CONFIG_UNREADABLE"
    assert "nu se poate citi" in unreadable["detail"]
