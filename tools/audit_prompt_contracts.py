"""Read-only audit of recorded shot prompts; never calls a provider or changes the studio."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.media.prompt_agent import (  # noqa: E402
    compile_prompts,
    compose_serial_motion,
    compose_serial_prompt,
    composition_issues,
    motion_prompt_for,
)
from app.media.prompt_lint import BLOCK, LintScene, lint_scene  # noqa: E402
from app.media.series_look import load_series_look  # noqa: E402


def audit(database: Path) -> dict:
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    results = []
    look = load_series_look()
    try:
        rows = connection.execute("""
            SELECT b.id AS board_id, b.title, b.status, b.series_key, b.visual_bible_json,
                   s.scene_index, s.scene_kind, s.prompt_json, s.visual_prompt
            FROM storyboard b JOIN storyboard_scene s ON s.storyboard_id = b.id
            ORDER BY b.created_at, s.scene_index
        """).fetchall()
        for row in rows:
            package = json.loads(row["prompt_json"] or "{}")
            bible = json.loads(row["visual_bible_json"] or "{}")
            if str(row["scene_kind"] or "LIVE").upper() != "LIVE":
                continue
            model_row = connection.execute(
                """
                SELECT model_id FROM scene_take WHERE storyboard_id = ? AND scene_number = ?
                  AND kind IN ('motion', 'test_shot') ORDER BY created_at DESC LIMIT 1
            """,
                (row["board_id"], row["scene_index"]),
            ).fetchone()
            model = model_row[0] if model_row else "seedance2_5"
            still = str(package.get("still_prompt") or row["visual_prompt"] or "")
            motion = str(package.get("motion_prompt") or "")
            old_issues = composition_issues(package, still, motion)
            serial = row["series_key"] == "office_serial"
            if serial:
                candidate = {
                    **package,
                    "still_prompt": compose_serial_prompt(package, look),
                    "motion_prompt": compose_serial_motion(package, look),
                }
            else:
                candidate = {**package, **compile_prompts(package, bible, {"model_id": model})}
            actual_motion, negative = motion_prompt_for(candidate, model)
            candidate_still = candidate["still_prompt"]
            issues = composition_issues(candidate, candidate_still, actual_motion)
            checks = lint_scene(
                LintScene(
                    scene=row["scene_index"],
                    still_prompt=candidate_still,
                    motion_prompt=actual_motion,
                    model_id=model,
                    composition_issues=tuple(issues),
                ),
                bible=bible,
            )
            results.append(
                {
                    "storyboard_id": row["board_id"],
                    "title": row["title"],
                    "board_status": row["status"],
                    "scene": row["scene_index"],
                    "kind": "serial" if serial else "factual",
                    "model": model,
                    "subject": package.get("subject"),
                    "writer_visual": package.get("writer_visual"),
                    "ending_frame": package.get("ending_frame"),
                    "stored_still": still,
                    "stored_motion": motion,
                    "stored_issues": old_issues,
                    "candidate_still": candidate_still,
                    "candidate_motion": actual_motion,
                    "candidate_negative": negative,
                    "candidate_issues": issues,
                    "blocks": [f.as_dict() for f in checks if f.severity == BLOCK],
                    "changed": still != candidate_still or motion != actual_motion,
                }
            )
    finally:
        connection.close()
    return {
        "method": "read-only records and deterministic compilers; no LLM, GPU or visual verdict",
        "candidate_status": "proposals only; not applied or approved by Sarah",
        "boards": len({item["storyboard_id"] for item in results}),
        "scenes": len(results),
        "stored_with_losses": sum(bool(item["stored_issues"]) for item in results),
        "candidates_requiring_editorial_review": sum(bool(item["blocks"]) for item in results),
        "board_statuses": dict(Counter(item["board_status"] for item in results)),
        "scenes_audited": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data/studio.db")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.database)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "scenes_audited"},
            ensure_ascii=False,
        )
    )
