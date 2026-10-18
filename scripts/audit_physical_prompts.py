"""Read-only review of physical contradictions in stored storyboard prompts.

Examples:
    python scripts/audit_physical_prompts.py --storyboard UUID --scenes 19 20 21
No changes to SQLite, scene prompts, image files or provider accounts.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "backend"))

from app.config import ROOT, Settings  # noqa: E402
from app.media.prompt_lint import (  # noqa: E402
    lint_motion_prompt,
    lint_still_prompt,
)

PHYSICAL_CODES = frozenset(
    {"PHYSICAL_MEDAL_ORIENTATION", "PHYSICAL_COSMIC_GROUND", "STILL_TEMPORAL_CHANGE"}
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storyboard", required=True, help="UUID-ul storyboardului existent")
    parser.add_argument("--scenes", nargs="*", type=int, help="Numerele scenelor; implicit toate")
    args = parser.parse_args()

    url = make_url(Settings().database_url)
    if url.get_backend_name() != "sqlite" or not url.database:
        parser.error("Auditul local este doar pentru SQLite.")
    db = Path(url.database)
    if not db.is_absolute():
        db = ROOT / db
    if not db.is_file():
        parser.error(f"Baza de date nu exista: {db}")
    con = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
    con.row_factory = sqlite3.Row
    try:
        film = con.execute(
            "SELECT title, visual_bible_json FROM storyboard WHERE id = ?", (args.storyboard,)
        ).fetchone()
        if film is None:
            print("Storyboard negasit.")
            return 2
        bible = json.loads(film["visual_bible_json"] or "{}")
        print(f"FILM: {film['title']} | face_policy: {bible.get('face_policy', 'LEGACY')}")
        scenes = con.execute(
            """SELECT scene_index, visual_prompt, prompt_json
               FROM storyboard_scene WHERE storyboard_id = ?
               ORDER BY scene_index""",
            (args.storyboard,),
        )
        selected = set(args.scenes or [])
        found = False
        for row in scenes:
            index = int(row["scene_index"])
            if selected and index not in selected:
                continue
            package = json.loads(row["prompt_json"] or "{}")
            still = str(package.get("still_prompt") or row["visual_prompt"] or "")
            motion = str(package.get("motion_prompt") or "")
            issues = [
                *lint_still_prompt(still, scene=index, bible=bible),
                *(
                    lint_motion_prompt(motion, scene=index, still_prompt=still)
                    if motion.strip()
                    else []
                ),
            ]
            relevant = [item for item in issues if item.code in PHYSICAL_CODES]
            print(f"\nSCENA {index}: {len(relevant)} constatări fizice")
            for item in relevant:
                found = True
                print(f"  [{item.severity}] {item.code}: {item.message_ro}")
        if not found:
            print("\nNu au fost gasite contradictii din categoriile monitorizate.")
        print("\nAudit read-only: niciun fisier, take sau prompt nu a fost schimbat.")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
