"""Read-only inspection of the source fields behind broken composed stills.

Example:
  python scripts/audit_composer_scene_sources.py --storyboard 1efc3319-44ac-416f-a75a-3217ca9c2070 --scenes 6 22

Never saves prompt strings, changes SQLite, generates media or calls an LLM.
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
from app.media.prompt_agent import compile_prompts  # noqa: E402


def _excerpt(value: object, limit: int = 550) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit] + " ..."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storyboard", required=True)
    parser.add_argument("--scenes", nargs="+", type=int, default=[6, 22])
    args = parser.parse_args()
    url = make_url(Settings().database_url)
    if url.get_backend_name() != "sqlite" or not url.database:
        parser.error("Suportat doar pe SQLite local.")
    db = Path(url.database)
    if not db.is_absolute():
        db = ROOT / db
    if not db.is_file():
        parser.error(f"Baza de date lipseste: {db}")

    with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=3) as conn:
        conn.row_factory = sqlite3.Row
        film = conn.execute(
            "SELECT title, visual_bible_json FROM storyboard WHERE id=?", (args.storyboard,)
        ).fetchone()
        if not film:
            parser.error("Storyboard negasit.")
        bible = json.loads(film["visual_bible_json"] or "{}")
        print(f"FILM: {film['title']} | face_policy={bible.get('face_policy', '?')}")
        for number in args.scenes:
            row = conn.execute(
                "SELECT scene_kind, shot_type, visual_prompt, prompt_json "
                "FROM storyboard_scene WHERE storyboard_id=? AND scene_index=?",
                (args.storyboard, number),
            ).fetchone()
            if not row:
                print(f"\nSCENA {number}: inexistenta")
                continue
            package = json.loads(row["prompt_json"] or "{}")
            stored = str(package.get("still_prompt") or row["visual_prompt"] or "")
            take_states = conn.execute(
                "SELECT kind, status, count(*) AS n FROM scene_take "
                "WHERE storyboard_id=? AND scene_number=? GROUP BY kind, status",
                (args.storyboard, number),
            ).fetchall()
            print(f"\nSCENA {number}: kind={row['scene_kind']} | shot_type={row['shot_type']}")
            print("  TAKE-URI:", ", ".join(
                f"{r['kind']}:{r['status']}={r['n']}" for r in take_states
            ) or "(niciunul)")
            for key in ("subject", "action", "environment", "camera",
                        "lighting", "avoid"):
                if package.get(key):
                    print(f"  {key}: {_excerpt(package[key], 450)}")
            print("  STORED STILL:", _excerpt(stored))
            try:
                compiled = compile_prompts(
                    {**package, "scene_kind": row["scene_kind"], "shot_type": row["shot_type"]},
                    bible,
                )
            except Exception as exc:  # preview only; report compiler errors honestly
                print(f"  RECOMPILE ERROR: {type(exc).__name__}: {_excerpt(exc)}")
                continue
            corrected = str(compiled.get("still_prompt") or "")
            print("  RECOMPILED STILL:", _excerpt(corrected))
            print("  STRING IDENTICAL:", corrected == stored)
            print("  OLD FACE SENTENCE IN STORED:", "the person is seen only from behind"
                  in stored.lower())
            print("  OLD FACE SENTENCE AFTER COMPILE:",
                  "the person is seen only from behind" in corrected.lower())
            print("  '16 frame:' IN STORED:", "16 frame:" in stored.lower())
            print("  '16 frame:' AFTER COMPILE:", "16 frame:" in corrected.lower())
    print("\nREAD ONLY: niciun prompt, take sau fisier nu a fost modificat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
