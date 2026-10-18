"""Read-only diagnosis of Sarah/Kael's rewrite-review cycles.

Usage:
 python scripts/audit_scene_rewrite_loop.py --storyboard 1efc3319-44ac-416f-a75a-3217ca9c2070
 python scripts/audit_scene_rewrite_loop.py --storyboard UUID --scene 19 --limit 25

Queries immutable history + local log tails, no API/LLM, prompts, take status or DB writes.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "backend"))
from app.config import ROOT, Settings  # noqa: E402

BRIEFS = "media.director_scene_brief"
REWRITES = "media.prompts_rewritten"
CODES = (BRIEFS, REWRITES, "media.shot_prompts_written", "media.shot_prompts_incomplete")


def _short(value: Any, length: int = 280) -> str:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, default=str)
    return " ".join(str(value or "").split())[:length]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storyboard", required=True)
    parser.add_argument("--scene", type=int)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error("--limit trebuie sa fie intre 1 si 100")
    url = make_url(Settings().database_url)
    if url.get_backend_name() != "sqlite" or not url.database:
        parser.error("Auditul suporta doar baza locala SQLite.")
    db = Path(url.database)
    if not db.is_absolute():
        db = ROOT / db
    if not db.is_file():
        parser.error("Nu exista baza de date: " + str(db))

    with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=3) as con:
        con.row_factory = sqlite3.Row
        board = con.execute(
            "SELECT title, status FROM storyboard WHERE id=?", (args.storyboard,)
        ).fetchone()
        if board is None:
            parser.error("Storyboard inexistent.")
        print(f"FILM: {board['title']} | status={board['status']}")
        event_types = ",".join("?" for _ in CODES)
        # Read more than displayed: scene filtering is applied after query, without JSON1
        # dependency. This still does no full-database scan of other projects.
        rows = con.execute(
            f"SELECT sequence, timestamp, event_type, payload FROM domain_event "
            f"WHERE aggregate_id=? AND event_type IN ({event_types}) "
            f"ORDER BY sequence DESC LIMIT 1500", (args.storyboard, *CODES)
        ).fetchall()
        chosen = []
        for row in rows:
            payload = json.loads(row["payload"] or "{}")
            scene = payload.get("scene_index")
            if args.scene is not None and scene != args.scene:
                continue
            chosen.append((row, payload))
            if len(chosen) == args.limit:
                break

        print(f"\n=== ULTIMELE {len(chosen)} EVENIMENTE DE RESCRIERE ===")
        run_ids = set()
        for row, p in reversed(chosen):
            scene = p.get("scene_index")
            print(
                f"\n[{row['timestamp']}] #{row['sequence']} "
                f"{row['event_type']} | scena={scene or '-'} | "
                f"layer={p.get('layer') or p.get('asked_layer') or '-'}"
            )
            if row["event_type"] == BRIEFS:
                print(
                    "  status: rewritten={rewritten}, same_prompt={same_prompt}, "
                    "not_treating={not_treating}, review={review_verdict}, "
                    "exhausted={layer_exhausted}, locked={composer_locked}".format(**{
                        k: p.get(k) for k in (
                            "rewritten", "same_prompt", "not_treating", "review_verdict",
                            "layer_exhausted", "composer_locked",
                        )
                    })
                )
                for key in ("diagnosis", "change", "review_reason_ro", "reason", "cause"):
                    if p.get(key):
                        print(f"  {key}: {_short(p[key])}")
                for attempt in p.get("review_attempts") or []:
                    print(
                        f"  R{attempt.get('round')}: {attempt.get('verdict') or 'UNREVIEWED'} "
                        f"reason={_short(attempt.get('reason_ro') or attempt.get('reason'), 300)}"
                    )
                    for finding in (attempt.get("findings") or [])[:4]:
                        if not finding.get("treated") and not finding.get("accepted"):
                            print(
                                f"    UNTREATED id={finding.get('id')} "
                                f"field={finding.get('field') or '-'} "
                                f"locked={finding.get('locked')} "
                                f"why={_short(finding.get('why_not') or finding.get('qc_text'), 260)}"
                            )
                    run_ids.update(str(attempt.get(k)) for k in ("rewrite_run_id", "review_run_id") if attempt.get(k))
                for key in ("brief_run_id", "rewrite_run_id", "review_run_id"):
                    if p.get(key):
                        run_ids.add(str(p[key]))
            else:
                print(f"  reason={_short(p.get('reason'), 170)}")
                for key in ("old_still_prompt", "still_prompt", "old_motion_prompt", "motion_prompt"):
                    if p.get(key) and row["event_type"] == REWRITES:
                        print(f"  {key}: {_short(p[key], 210)}")
        if chosen:
            counts = Counter(
                (p.get("scene_index"), p.get("review_verdict"))
                for row, p in chosen if row["event_type"] == BRIEFS
            )
            print("\nREZUMAT BRIEF-URI:", dict(counts))
        else:
            print("Nu exista evenimente de acest tip pentru selectia ceruta.")

        if run_ids:
            marks = ",".join("?" for _ in run_ids)
            runs = con.execute(
                f"SELECT r.id, r.task_type, r.status, r.model_name, r.error_detail, "
                f"r.started_at, a.display_name FROM agent_run r "
                f"LEFT JOIN agent a ON a.id=r.agent_id WHERE r.id IN ({marks}) "
                f"ORDER BY r.started_at", tuple(sorted(run_ids))
            ).fetchall()
            print("\n=== RUN-URI CORESPUNZATOARE (FARA CHEI/TOKENURI) ===")
            for r in runs:
                print(
                    f"{r['started_at']} | {r['display_name']} | {r['task_type']} "
                    f"| {r['status']} | {r['model_name']} "
                    f"| eroare={_short(r['error_detail'], 190)}"
                )

        latest = con.execute(
            "SELECT s.scene_index, t.kind, t.status, t.failure_code, t.failure_detail "
            "FROM storyboard_scene s LEFT JOIN scene_take t ON t.storyboard_id=s.storyboard_id "
            "AND t.scene_number=s.scene_index WHERE s.storyboard_id=? "
            + ("AND s.scene_index=? " if args.scene is not None else "") +
            "ORDER BY s.scene_index, t.created_at DESC LIMIT 80",
            (args.storyboard, args.scene) if args.scene is not None else (args.storyboard,)
        ).fetchall()
        print("\n=== TAKE-URI (max. 80 randuri) ===")
        for t in latest:
            print(
                f"scena={t['scene_index']} {t['kind'] or '-'} "
                f"{t['status'] or '-'} {t['failure_code'] or '-'} "
                f"{_short(t['failure_detail'], 170)}"
            )
    print("\nDoar citire. Trimite-mi iesirea acestei comenzi pentru diagnostic.")


if __name__ == "__main__":
    main()
