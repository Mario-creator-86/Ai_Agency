"""The characters' own portraits become their bibles' reference pictures (2026-10-11).

The Owner: «Cauta pozele caracterelor/agentilor. Sa le putem include in bible ca la serial sa
stim dupa ce caractere sa ne luam.» Eight character sheets drawn by ChatGPT on 2026-09-12 from
the prompts in «Agents ID and Bible/CHARACTER_BIBLES.md» lay in that folder for a month while
every slot of every bible (`CharacterBible.reference_assets_json`) stayed null: the only route
that fills a slot buys pictures (`media.services.generate_character_reference_set`, his press),
and nothing read the folder. So a serial scene that names Sarah is drawn from her words alone,
and the picture check has no face to compare a frame with.

This pass registers them for free. `config/character_references.json` says which file is which
character (a bible's canonical name -> a PNG relative to the repository, with the SHA-256 the
picture was verified at, by eye, against the bible's anchors). For each bible whose ``portrait``
slot is empty and whose file is there, the file is copied under the studio's media storage (the
Owner's ``media_root``, else the folder the paid route writes to) as
``references/<character_id>/portrait.png``, becomes a MediaAsset row written the way the paid
route writes one (type, mime, measured size, SHA-256 provenance, the event it came from), and
the slot is pointed at it. Nothing of his is decided: ``identity_locks_json`` is not touched, so
a missing reference still blocks nobody, and a slot that holds a picture is never replaced.

Idempotent by the picture's SHA-256: ``media.character_reference_registered`` names the
character, the slot and the hash, and a picture registered once is never registered again, even
when its slot was emptied afterwards (someone's decision, not a loss to repair). A file that is
missing, that changed since it was verified (its hash differs from the config's), or that is
not a PNG is reported under ``problems`` and nothing is written for it: an unverified face must
not become the face every shot is drawn from. Nothing here buys, asks the Owner or answers in
his name.

Review of 2026-10-11, three rules added. A character whose look the Owner locked is left to
him: his lock makes a missing reference a deliberate stop (`media.services.ReferenceRequired`:
the Owner produces the set, the scene is made after), and the first version filled that slot
too, so the free sheet lifted his block within ten minutes of a restart; such a character is
now reported under ``locked`` and nothing is written for it, whether the lock was there before
the pass or landed while it ran. A slot pointing at an asset row that is gone is empty: «Start
over» (`app.maintenance.reset_history`) deletes the assets and the ledger and keeps the bibles,
and the first version counted those slots filled forever while the scenes had no reference.
And the detail beside each reported problem is Romanian, like every string that may reach the
Owner; the codes stay as they are, for code to match.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import ROOT
from app.workflows.passes import WatchdogContext, watchdog_pass

#: Which file is which character, written by hand and verified by eye (the Owner's, or the
#: session's that looked at the pictures with the bible beside them).
CONFIG_FILE = ROOT / "config" / "character_references.json"
#: What the files named in it are relative to.
SOURCE_ROOT = ROOT
#: The one slot this pass fills. The Owner's sheets carry the face first; the other slots stay
#: his to buy through the paid route.
SLOT = "portrait"
#: Appended once per registered picture, on the asset it made, as the paid route appends
#: ``media.character_reference_generated``.
REGISTERED_EVENT = "media.character_reference_registered"
#: Where a registered picture lives under the media root: beside, never inside, the folder the
#: paid route writes a character's set to (``<root>/<character_id>/<slot>.png``), so a set bought
#: later overwrites nothing registered here.
FOLDER = "references"
#: What a registered picture is to the books: the Owner supplied it, no vendor drew it for pay.
PROVIDER_NAME = "OWNER_SUPPLIED"

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_dimensions(data: bytes) -> tuple[int, int] | None:
    """(width, height) read from the PNG header, or None when the bytes are not a PNG. Measured
    from the file, as the paid route records what the vendor actually produced."""
    if len(data) < 24 or not data.startswith(_PNG_SIGNATURE) or data[12:16] != b"IHDR":
        return None
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return (width, height) if width and height else None


def _problem(character: str | None, problem: str, file: str | None, detail: str) -> dict[str, Any]:
    return {"character": character, "problem": problem, "file": file, "detail": detail[:300]}


def _entries(
    config_file: Path,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """The config's characters, each with ``file`` and ``sha256``; a file that cannot be read or
    an entry that is not of that shape is a problem named in the result, never a crash."""
    try:
        data = json.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        detail = f"fișierul de configurare nu se poate citi: {type(exc).__name__}: {exc}"
        return {}, [_problem(None, "CONFIG_UNREADABLE", str(config_file), detail)]
    characters = data.get("characters") if isinstance(data, dict) else None
    if not isinstance(characters, dict):
        detail = "fișierul de configurare nu are harta 'characters'"
        return {}, [_problem(None, "CONFIG_UNREADABLE", str(config_file), detail)]
    entries: dict[str, dict[str, Any]] = {}
    problems: list[dict[str, Any]] = []
    for name, entry in characters.items():
        file = entry.get("file") if isinstance(entry, dict) else None
        digest = entry.get("sha256") if isinstance(entry, dict) else None
        if (
            not isinstance(file, str)
            or not file
            or not isinstance(digest, str)
            or len(digest) != 64
        ):
            problems.append(
                _problem(
                    str(name),
                    "ENTRY_INCOMPLETE",
                    file if isinstance(file, str) else None,
                    "intrarea are nevoie de 'file' și de 'sha256' (64 de caractere hex) la care "
                    "a fost verificată imaginea",
                )
            )
            continue
        made_with = entry.get("made_with")
        entries[str(name)] = {
            "file": file,
            "sha256": digest.lower(),
            "made_with": made_with if isinstance(made_with, str) else None,
        }
    return entries, problems


def _slot_filled(session: Any, row: Any) -> bool:
    """Whether the bible's slot holds a picture the studio has: an asset id whose row exists.

    «Start over» (`app.maintenance.reset_history`) deletes the media assets and keeps the
    bibles, so a slot may point at a row that is gone. To everyone who reads the slot
    (`image_reference_for_scene`, the preflight, the picture check) that slot is empty; counting
    it filled here left the scenes without a reference and the only free way back closed.
    """
    from app.media.models import MediaAsset  # noqa: PLC0415 - media imports workflows

    asset_id = dict(row.reference_assets_json or {}).get(SLOT)
    if not isinstance(asset_id, str) or not asset_id.strip():
        return False
    return session.get(MediaAsset, asset_id.strip()) is not None


def _locked(row: Any) -> bool:
    """Whether the Owner locked this character's look (``identity_locks_json.visual``). Then a
    missing reference is his deliberate stop (`media.services.ReferenceRequired`), lifted by
    the set he produces and by nothing that runs on its own."""
    return bool((row.identity_locks_json or {}).get("visual"))


def _store(folder: Path, data: bytes, digest: str) -> Path:
    """The picture on disk as ``portrait.png``, written only when that file is not already these
    bytes (a pass that died between the copy and the row copies nothing again). A different
    picture already there is some asset's file and is left exactly as it is; the new one takes a
    name of its own, by its hash."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{SLOT}.png"
    if path.exists():
        if path.read_bytes() == data:
            return path
        path = folder / f"{SLOT}-{digest[:12]}.png"
        if path.exists() and path.read_bytes() == data:
            return path
    path.write_bytes(data)
    return path


@watchdog_pass("character_references", order=140, on_error={"registered": [], "problems": []})
def register_character_portraits(context: WatchdogContext) -> dict[str, Any]:
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    from app.db import lock_for_write  # noqa: PLC0415
    from app.media import services as media_services  # noqa: PLC0415 - media imports workflows
    from app.media.models import CharacterBible, MediaAsset  # noqa: PLC0415
    from app.models import DomainEvent  # noqa: PLC0415
    from app.services import append_event, utc_now  # noqa: PLC0415

    result: dict[str, Any] = {
        "registered": [],
        "filled": [],
        "locked": [],
        "withheld": [],
        "problems": [],
    }
    entries, problems = _entries(CONFIG_FILE)
    result["problems"].extend(problems)
    if not entries:
        return result

    with Session(context.engine) as session:
        bibles = {
            row.canonical_name: (row.id, _slot_filled(session, row), _locked(row))
            for row in session.scalars(select(CharacterBible))
        }
        # The pass's own mark: (character, slot, hash) of every picture registered before.
        marks = {
            (
                str(payload.get("character_id")),
                str(payload.get("slot")),
                str(payload.get("sha256")),
            )
            for event in session.scalars(
                select(DomainEvent).where(DomainEvent.event_type == REGISTERED_EVENT)
            )
            for payload in [event.payload or {}]
        }

    owed: list[tuple[str, str, dict[str, Any], bytes, str, tuple[int, int]]] = []
    for name, entry in sorted(entries.items()):
        found = bibles.get(name)
        if found is None:
            result["problems"].append(
                _problem(
                    name,
                    "NO_BIBLE",
                    entry["file"],
                    "niciun personaj din Character Bible nu poartă acest nume",
                )
            )
            continue
        character_id, filled, locked = found
        if filled:
            result["filled"].append(name)
            continue
        if locked:
            result["locked"].append(name)
            continue
        source = SOURCE_ROOT / entry["file"]
        try:
            data = source.read_bytes()
        except OSError as exc:
            result["problems"].append(
                _problem(
                    name,
                    "MISSING_FILE",
                    entry["file"],
                    f"fișierul nu se poate citi: {type(exc).__name__}: {exc}",
                )
            )
            continue
        digest = hashlib.sha256(data).hexdigest()
        if digest != entry["sha256"]:
            result["problems"].append(
                _problem(
                    name,
                    "MISMATCHED_FILE",
                    entry["file"],
                    f"SHA-256 al fișierului începe cu {digest[:12]}, cel verificat cu "
                    f"{entry['sha256'][:12]}: imaginea s-a schimbat de când a fost verificată; "
                    "uită-te la ea din nou și scrie noul hash",
                )
            )
            continue
        dimensions = png_dimensions(data)
        if dimensions is None:
            result["problems"].append(
                _problem(
                    name, "NOT_PNG", entry["file"], "slotul cere un PNG, iar fișierul nu este unul"
                )
            )
            continue
        if (character_id, SLOT, digest) in marks:
            result["withheld"].append(name)
            continue
        owed.append((name, character_id, entry, data, digest, dimensions))
    if not owed:
        return result

    media_root = getattr(context.settings, "media_root", None)
    root = Path(media_root) if media_root else Path(media_services.REFERENCE_STORAGE_ROOT)
    for name, character_id, entry, data, digest, (width, height) in owed:
        # The file before the row, as the paid route: a row that cannot be written must not name
        # a file that is not there, and a file without a row is copied over harmlessly next time.
        try:
            path = _store(root / FOLDER / character_id, data, digest)
        except OSError as exc:
            result["problems"].append(
                _problem(
                    name,
                    "NOT_WRITABLE",
                    entry["file"],
                    f"folderul de referințe nu se poate scrie: {type(exc).__name__}: {exc}",
                )
            )
            continue
        asset_id = str(uuid4())
        outcome = "gone"
        with Session(context.engine) as session, session.begin():
            lock_for_write(session)  # this transaction reads the bible, then writes it
            row = session.get(CharacterBible, character_id)
            if row is None:
                pass  # deleted meanwhile: named below, nothing written
            elif _slot_filled(session, row):
                outcome = "filled"  # meanwhile, by his press or another process: never replaced
            elif _locked(row):
                outcome = "locked"  # his lock landed meanwhile: only his set lifts it
            else:
                outcome = "registered"
                event = append_event(
                    session,
                    REGISTERED_EVENT,
                    "media_asset",
                    asset_id,
                    1,
                    {
                        "character_id": character_id,
                        "canonical_name": name,
                        "slot": SLOT,
                        "sha256": digest,
                        "source_file": entry["file"],
                        "path": str(path),
                        "bytes": len(data),
                        "width": width,
                        "height": height,
                        "made_with": entry["made_with"],
                        "registered_by": "watchdog",
                    },
                    context.correlation_id,
                )
                session.add(
                    MediaAsset(
                        id=asset_id,
                        asset_type="IMAGE",
                        uri_or_path=str(path),
                        file_size_bytes=len(data),
                        mime_type="image/png",
                        width=width,
                        height=height,
                        duration_seconds=None,
                        provider_name=PROVIDER_NAME,
                        remote_job_id=None,
                        license_status="ORIGINAL_AI_GENERATED",
                        provenance_hash=digest,
                        created_at=utc_now(),
                        event_id=event.event_id,
                    )
                )
                row.reference_assets_json = {**(row.reference_assets_json or {}), SLOT: asset_id}
        if outcome == "registered":
            result["registered"].append(
                {
                    "character": name,
                    "character_id": character_id,
                    "asset_id": asset_id,
                    "sha256": digest,
                    "path": str(path),
                }
            )
        elif outcome == "filled":
            result["filled"].append(name)
        elif outcome == "locked":
            result["locked"].append(name)
        else:
            result["problems"].append(
                _problem(name, "NO_BIBLE", entry["file"], "personajul a fost șters între timp")
            )
    return result
