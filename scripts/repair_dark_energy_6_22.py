"""Restore two composer-blocked Dark Energy scene prompts without buying anything.

Dry run (default):
 python scripts/repair_dark_energy_6_22.py
Explicit, backed-up application (only after validating the preview and tests):
 python scripts/repair_dark_energy_6_22.py --apply

Only storyboard 1efc... scenes 6 and 22. Never edits existing SceneTake rows.
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
from app.media.prompt_lint import BLOCK, lint_motion_prompt, lint_still_prompt  # noqa: E402
from app.services import append_event  # noqa: E402

FILM_ID = "1efc3319-44ac-416f-a75a-3217ca9c2070"
TITLE = "Supernova Surprise: Distant Explosions Revealed Dark Energy"
SCENES = (6, 22)
EVENT = "media.owner_composer_prompt_repair"
COMPILED_FIELDS = (
    "still_prompt", "motion_prompt", "negative_prompt", "look_block",
    "camera_move", "shot_size", "motion_family", "motion_intent",
)


def _fingerprint(package: dict, visual: str) -> str:
    raw = json.dumps(
        {"package": package, "visual": visual}, sort_keys=True,
        ensure_ascii=False, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _database() -> Path:
    url = make_url(Settings().database_url)
    if url.get_backend_name() != "sqlite" or not url.database:
        raise RuntimeError("Doar SQLite local este acceptat.")
    path = Path(url.database)
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_file():
        raise FileNotFoundError(f"Baza de date nu exista: {path}")
    return path.resolve()


def _validate_take_states(states: list[tuple[int, str, str]]) -> None:
    for number, kind, status in states:
        if number not in SCENES:
            continue
        if kind != "still" or status != "REJECTED":
            raise RuntimeError(
                f"Scena {number} are {kind}={status}; nu atingem promptul "
                "cand exista un take activ, platit sau aprobat."
            )


def _plan(rows: list[dict], bible: dict) -> list[dict]:
    if sorted(row["scene_index"] for row in rows) != list(SCENES):
        raise RuntimeError("Cele doua scene nu au fost gasite.")
    result = []
    for row in rows:
        number = int(row["scene_index"])
        if row["scene_kind"] != "LIVE":
            raise RuntimeError(f"Scena {number} nu mai este LIVE.")
        old = dict(row["prompt_json"])
        old_visual = str(row["visual_prompt"] or "")
        compiled = compile_prompts(
            {**old, "scene_kind": "LIVE", "shot_type": row["shot_type"]}, bible,
        )
        still = str(compiled["still_prompt"])
        motion = str(compiled["motion_prompt"])
        if number == 6:
            if "16 frame:" in still.casefold():
                raise RuntimeError("Scena 6 inca are fragmentul 16 frame.")
            if "flame is the only light source" not in still.casefold():
                raise RuntimeError(
                    "Scena 6 nu pastreaza sursa unica de lumina; nu se aplica."
                )
        if number == 22 and "the person is seen only from behind" in still.casefold():
            raise RuntimeError("Scena 22 inca introduce o persoana inexistenta.")
        findings = [
            *lint_still_prompt(still, scene=number, bible=bible),
            *lint_motion_prompt(motion, scene=number, still_prompt=still),
        ]
        blocks = [item.code for item in findings if item.severity == BLOCK]
        if blocks:
            raise RuntimeError(f"Scena {number} nu trece lint: {blocks}")
        new = {**old, **{key: compiled[key] for key in COMPILED_FIELDS}}
        result.append({
            "scene": number, "old": old, "new": new,
            "old_visual": old_visual, "new_visual": still,
            "old_fingerprint": _fingerprint(old, old_visual),
            "new_fingerprint": _fingerprint(new, still),
        })
    return result


def _backup(db: Path) -> Path:
    destdir = db.parent / "backups" / "manual_dark_energy"
    destdir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    dest = destdir / f"studio_before_dark_energy_6_22_{timestamp}.sqlite3"
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=5) as src:
        with sqlite3.connect(dest) as out:
            src.backup(out)
            if out.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup-ul este invalid; nimic aplicat.")
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    db = _database()
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=5) as con:
        con.row_factory = sqlite3.Row
        board = con.execute(
            "SELECT id, title, visual_bible_json FROM storyboard WHERE id=?", (FILM_ID,)
        ).fetchone()
        if board is None or TITLE not in board["title"]:
            raise RuntimeError("Storyboard-ul nu este Dark Energy.")
        bible = json.loads(board["visual_bible_json"] or "{}")
        if bible.get("face_policy") != "ALLOW":
            raise RuntimeError("Politica pentru fete nu este ALLOW.")
        rows = []
        for entry in con.execute(
            "SELECT scene_index, scene_kind, shot_type, visual_prompt, prompt_json "
            "FROM storyboard_scene WHERE storyboard_id=? AND scene_index IN (6, 22)",
            (FILM_ID,),
        ):
            item = dict(entry)
            item["prompt_json"] = json.loads(item["prompt_json"] or "{}")
            rows.append(item)
        statuses = [
            (r["scene_number"], r["kind"], r["status"])
            for r in con.execute(
                "SELECT scene_number, kind, status FROM scene_take "
                "WHERE storyboard_id=? AND scene_number IN (6,22)", (FILM_ID,)
            )
        ]
        _validate_take_states(statuses)
    plan = _plan(rows, bible)
    print(f"FILM: {board['title']}")
    for item in plan:
        n = item["scene"]
        print(f"\nSCENA {n}: " + (
            "SCHIMBAT" if item["old_fingerprint"] != item["new_fingerprint"]
            else "NEMODIFICAT"
        ))
        print("  STILL nou:", item["new_visual"][:700])
        print("  TAKE-URI PASTRATE:", [(k, v) for scene, k, v in statuses if scene == n])
        print("  Identitate prompt schimbata:", item["old_fingerprint"] != item["new_fingerprint"])
    if not args.apply:
        print("\nPREVIZUALIZARE: baza de date si take-urile sunt neschimbate.")
        return 0
    if all(i["old_fingerprint"] == i["new_fingerprint"] for i in plan):
        print("Nu exista modificari.")
        return 0
    backup = _backup(db)
    print("\nBACKUP CONFIRMAT:", backup)
    engine = create_db_engine(Settings().database_url)
    try:
        with Session(engine) as session, session.begin():
            lock_for_write(session)
            current = session.get(Storyboard, FILM_ID)
            if current is None or TITLE not in current.title:
                raise RuntimeError("Film diferit intre previzualizare si aplicare.")
            if dict(current.visual_bible_json or {}) != bible:
                raise RuntimeError("Biblia s-a schimbat; tranzactie anulata.")
            current_takes = [
                (t.scene_number, t.kind, t.status)
                for t in session.scalars(
                    select(SceneTake).where(
                        SceneTake.storyboard_id == FILM_ID,
                        SceneTake.scene_number.in_(SCENES),
                    )
                )
            ]
            _validate_take_states(current_takes)
            for item in plan:
                row = session.scalar(
                    select(StoryboardScene).where(
                        StoryboardScene.storyboard_id == FILM_ID,
                        StoryboardScene.scene_index == item["scene"],
                    )
                )
                if (
                    row is None
                    or row.scene_kind != "LIVE"
                    or _fingerprint(dict(row.prompt_json or {}), str(row.visual_prompt or ""))
                    != item["old_fingerprint"]
                ):
                    raise RuntimeError("Prompturile s-au schimbat; tranzactie anulata.")
                if item["old_fingerprint"] == item["new_fingerprint"]:
                    continue
                row.prompt_json = item["new"]
                row.visual_prompt = item["new_visual"]
                append_event(
                    session, EVENT, "storyboard", FILM_ID, 1,
                    {
                        "scene_index": item["scene"],
                        "source": "composer_regression_20261018",
                        "old_prompt_hash": item["old_fingerprint"],
                        "new_prompt_hash": item["new_fingerprint"],
                        "old_package": item["old"],
                        "old_visual_prompt": item["old_visual"],
                        "take_records_modified": False,
                    },
                    str(uuid4()),
                )
        print("\nAPLICAT: doar scenele 6 si 22. Nicio generatie comandata.")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
