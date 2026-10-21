"""Safe, two-scene Dark Energy prompt repair. Default is read-only preview.

    python scripts/repair_dark_energy_prompts.py
    python scripts/repair_dark_energy_prompts.py --apply

Only the exact storyboard's scenes 19 and 20 are eligible.
Scene 19 changes its still + motion (old still identity intentionally no longer matches).
Scene 20 keeps its existing still identity and changes only motion-related fields.
No media generation, approval, take status or vendor calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "backend"))

from app.config import ROOT, Settings  # noqa: E402
from app.db import create_db_engine, lock_for_write  # noqa: E402
from app.media.models import SceneTake, Storyboard, StoryboardScene  # noqa: E402
from app.media.prompt_agent import compile_prompts  # noqa: E402
from app.media.prompt_lint import (  # noqa: E402
    BLOCK,
    lint_motion_prompt,
    lint_still_prompt,
)
from app.services import append_event  # noqa: E402

STORYBOARD_ID = "1efc3319-44ac-416f-a75a-3217ca9c2070"
TITLE_EXPECT = "Supernova Surprise: Distant Explosions Revealed Dark Energy"
REPAIR_EVENT = "media.owner_physical_prompt_repair"
FACE_WORDS = ("no faces", "no human faces", "faces not visible", "seen only from behind",
              "never looking at the lens", "no eye contact")


def _database() -> Path:
    url = make_url(Settings().database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise ValueError("Acest instrument accepta numai SQLite local.")
    path = Path(url.database)
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_file():
        raise FileNotFoundError(f"Baza de date nu exista: {path}")
    return path.resolve()


def _fingerprint(package: dict, visual: str) -> str:
    value = json.dumps({"package": package, "visual": visual},
                       sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _clean_face_avoid(package: dict) -> None:
    old = package.get("avoid")
    if isinstance(old, list):
        package["avoid"] = [
            item for item in old
            if not any(word in str(item).lower() for word in FACE_WORDS)
        ]


def _repair19(old: dict, bible: dict, shot_type: str) -> tuple[dict, str]:
    package = dict(old)
    package.update(
        subject=(
            "Three scientists on a formal award-ceremony stage, facing the camera "
            "in a medium frontal three-quarter view, each displaying a pale gold "
            "medal correctly in front of the chest."
        ),
        action=(
            "The three scientists stand together holding their medals in front "
            "of their jackets, receiving the award in a quiet ceremonial moment."
        ),
        writer_visual=(
            "Three scientists face the camera at a medal ceremony, "
            "with their awards held visibly in front."
        ),
        environment=(
            "An elegant ceremony hall with stage curtains, architectural details "
            "and an audience in subdued darkness."
        ),
        # Keep the first frame static: the camera move belongs in motion_prompt.
        camera=(
            "Medium shot, 85mm lens, eye-level angle: all three recipients "
            "and their medals visible in a frontal three-quarter view."
        ),
        camera_move="crane up",
        lighting="Warm overhead spotlights catch the medals, with gentle shadows in the hall.",
        composition=(
            "Vertical 9:16 framing, all three recipients and their medals visible "
            "in the upper two thirds, hall architecture continuing behind them."
        ),
        motion=(
            "The scientists hold their medals as faint gold reflections glint "
            "across the polished surfaces while the spotlights remain steady."
        ),
        continuity=(
            "Three recipients, frontal three-quarter view, medals held in front "
            "of their jackets; the lighting remains fixed throughout."
        ),
        ending_frame=(
            "The medal recipients seen from the front, with their medals in front "
            "of them and the hall visible above."
        ),
    )
    _clean_face_avoid(package)
    compiled = compile_prompts({**package, "scene_kind": "LIVE", "shot_type": shot_type},
                               bible)
    package.update(compiled)
    still = str(compiled["still_prompt"])
    _validate(19, package, still, bible)
    if "from behind" in (still + " " + str(package["motion_prompt"])).lower():
        raise ValueError("Scena 19 mai contine o restrictie pentru vedere din spate.")
    if "slow rise" in still.lower() or "crane up" in still.lower():
        raise ValueError("Scena 19 are inca instructiuni de miscare in STILL.")
    if "shadows drift" in str(package["motion_prompt"]).lower():
        raise ValueError("Scena 19 introduce miscare a umbrelor in ceremonia statica.")
    return package, still


def _repair20(old: dict, visual: str, bible: dict, shot_type: str) -> tuple[dict, str]:
    package = dict(old)
    # Do not change the still, visual_prompt, subject or first-frame composition.
    # Every paid/approved still from this scene must retain its prompt identity.
    package.update(
        # The original action describes changing light, so the compiler repeats
        # the same pulse alongside the newly supplied motion. Freeze it here;
        # visual_prompt and still_prompt retain their exact paid identity.
        action="Galaxy clusters rest in a continuous filamentary cosmic web.",
        camera=(
            "Wide establishing shot, 24mm lens; dolly in: a slow steady forward "
            "glide toward the cosmic web, through the depth of its galaxy filaments."
        ),
        camera_move="dolly in",
        motion=(
            "Faint cool light brightens and dims once in a gentle wave travelling "
            "along the galaxy filaments, while the clusters remain in place."
        ),
        ending_frame=(
            "The connected cosmic web appears slightly closer and fills the centre "
            "of the frame, with the continuous deep-space void around it."
        ),
    )
    compiled = compile_prompts({**package, "scene_kind": "LIVE", "shot_type": shot_type},
                               bible)
    for key in ("motion_prompt", "motion_intent", "camera_move",
                "motion_family", "negative_prompt"):
        package[key] = compiled[key]
    still = str(package.get("still_prompt") or visual)
    _validate(20, package, still, bible)
    if package.get("still_prompt") != old.get("still_prompt"):
        raise ValueError("Scena 20 ar schimba imaginea existenta, operatie interzisa.")
    motion = str(package["motion_prompt"]).lower()
    if motion.count("brightens and dims") > 1:
        raise ValueError("Scena 20 repeta aceeasi schimbare de lumina.")
    return package, visual


def _validate(number: int, package: dict, still: str, bible: dict) -> None:
    findings = [
        *lint_still_prompt(still, scene=number, bible=bible),
        *lint_motion_prompt(
            str(package.get("motion_prompt") or ""), scene=number, still_prompt=still
        ),
    ]
    blockers = [f"{f.code}: {f.message_ro}" for f in findings if f.severity == BLOCK]
    if blockers:
        raise ValueError(f"Scena {number} nu trece verificarea: " + "; ".join(blockers))


def _plan(rows: list[dict], bible: dict) -> list[dict]:
    planned = []
    for row in rows:
        number = row["scene_index"]
        old = dict(row["prompt_json"] or {})
        visual = str(row["visual_prompt"])
        if number == 19:
            new, output_visual = _repair19(old, bible, row["shot_type"])
        else:
            new, output_visual = _repair20(old, visual, bible, row["shot_type"])
        planned.append({
            "scene": number,
            "old": old,
            "new": new,
            "old_visual": visual,
            "new_visual": output_visual,
            "old_fingerprint": _fingerprint(old, visual),
            "new_fingerprint": _fingerprint(new, output_visual),
        })
    return planned


def _backup(db: Path) -> Path:
    folder = db.parent / "backups" / "manual_dark_energy"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    dest = folder / f"studio_before_dark_energy_19_20_{stamp}.sqlite3"
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=5) as origin:
        with sqlite3.connect(dest) as target:
            origin.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup-ul bazei de date nu a trecut integrity_check.")
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Aplică numai după previzualizare")
    args = parser.parse_args()
    db = _database()
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=5) as con:
        con.row_factory = sqlite3.Row
        film = con.execute(
            "SELECT id, title, visual_bible_json FROM storyboard WHERE id = ?",
            (STORYBOARD_ID,),
        ).fetchone()
        if film is None or TITLE_EXPECT not in film["title"]:
            raise RuntimeError("Storyboard-ul nu corespunde filmului Dark Energy.")
        bible = json.loads(film["visual_bible_json"] or "{}")
        if bible.get("face_policy") != "ALLOW":
            raise RuntimeError("Face policy nu este ALLOW; nu aplicăm nimic.")
        rows = [
            dict(r)
            for r in con.execute(
                "SELECT scene_index, scene_kind, shot_type, visual_prompt, prompt_json "
                "FROM storyboard_scene WHERE storyboard_id = ? "
                "AND scene_index IN (19, 20) ORDER BY scene_index",
                (STORYBOARD_ID,),
            )
        ]
        if [r["scene_index"] for r in rows] != [19, 20]:
            raise RuntimeError("Scenele 19 si 20 nu sunt ambele prezente.")
        for row in rows:
            if row["scene_kind"] != "LIVE":
                raise RuntimeError("Cadrul nu mai este LIVE; refuz aplicarea.")
            row["prompt_json"] = json.loads(row["prompt_json"] or "{}")
        inflight = con.execute(
            "SELECT COUNT(*) FROM scene_take WHERE storyboard_id = ? "
            "AND scene_number IN (19, 20) AND status = 'SUBMITTED'",
            (STORYBOARD_ID,),
        ).fetchone()[0]
        if inflight:
            raise RuntimeError("Exista takes SUBMITTED pentru 19/20; asteapta colectarea lor.")
    changes = _plan(rows, bible)
    print("FILM:", film["title"])
    for p in changes:
        action = "SCHIMBAT" if p["old_fingerprint"] != p["new_fingerprint"] else "NEMODIFICAT"
        print(f"\nSCENA {p['scene']}: {action}")
        print("STILL:", "SCHIMBAT" if p["old_visual"] != p["new_visual"] else "PASTRAT")
        print("MOTION:", str(p["new"].get("motion_prompt") or "")[:500])
        print("STILL (inceput):", p["new_visual"][:400])
    if not args.apply:
        print("\nPREVIZUALIZARE: nimic scris. Pentru aplicare: --apply")
        return 0
    if all(p["old_fingerprint"] == p["new_fingerprint"] for p in changes):
        print("Nu exista modificari de aplicat.")
        return 0
    backup = _backup(db)
    print("\nBACKUP:", backup)
    engine = create_db_engine(Settings().database_url)
    try:
        with Session(engine) as session, session.begin():
            lock_for_write(session)
            board = session.get(Storyboard, STORYBOARD_ID)
            if board is None or TITLE_EXPECT not in board.title:
                raise RuntimeError("Storyboard schimbat intre previzualizare si aplicare.")
            if dict(board.visual_bible_json or {}) != bible:
                raise RuntimeError("Biblia vizuala s-a modificat: tranzactie anulata.")
            pending = session.scalar(
                select(SceneTake.id).where(
                    SceneTake.storyboard_id == STORYBOARD_ID,
                    SceneTake.scene_number.in_([19, 20]),
                    SceneTake.status == "SUBMITTED",
                ).limit(1)
            )
            if pending:
                raise RuntimeError("A aparut o generatie in curs: tranzactie anulata.")
            for p in changes:
                row = session.scalar(
                    select(StoryboardScene).where(
                        StoryboardScene.storyboard_id == STORYBOARD_ID,
                        StoryboardScene.scene_index == p["scene"],
                    )
                )
                if row is None or _fingerprint(dict(row.prompt_json or {}), row.visual_prompt) != p["old_fingerprint"]:
                    raise RuntimeError("Scena s-a modificat: tranzactie anulata.")
                if p["old_fingerprint"] == p["new_fingerprint"]:
                    continue
                row.prompt_json = p["new"]
                row.visual_prompt = p["new_visual"]
                append_event(
                    session, REPAIR_EVENT, "storyboard", STORYBOARD_ID, 1,
                    {
                        "scene_index": p["scene"],
                        "reason": "Owner-approved physical composition repair, 2026-10-18",
                        "old_package": p["old"],
                        "old_visual_prompt": p["old_visual"],
                        "package": p["new"],
                        "visual_prompt": p["new_visual"],
                        "still_identity_changed": p["scene"] == 19,
                        "take_records_modified": False,
                    },
                    str(uuid4()),
                )
        print("\nAPLICAT: doar prompturile scenelor 19 si 20; takes-urile sunt intacte.")
        print("Scena 21 ramane neschimbata. Nu s-a cumparat nicio generare.")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
