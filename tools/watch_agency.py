"""Read-only operational snapshot. Never displays model answers, prompts or credentials."""

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def snapshot(database: Path) -> dict:
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row

        def rows(sql):
            return [dict(row) for row in connection.execute(sql)]

        return {
            "observed_at": datetime.now(UTC).isoformat(),
            "event_cursor": rows("SELECT max(sequence) as last FROM domain_event")[0]["last"],
            "claimed_tasks": rows("""
                SELECT id,task_type,status,attempts,max_attempts,updated_at,lease_expires_at
                FROM task_queue WHERE status='CLAIMED'
            """),
            "recent_runs": rows("""
                SELECT id,task_type,status,started_at,prompt_template_version,completion_tokens,
                       length(output_text) as answer_chars,error_detail,
                       json_extract(context_json,'$.task_summary') as task_summary
                FROM agent_run ORDER BY started_at DESC LIMIT 12
            """),
            "recent_shot_output_shape": rows("""
                SELECT id,started_at,status,completion_tokens,length(output_text) as answer_chars,
                       instr(output_text,'<think>') as think_tag,
                       instr(output_text,char(34)||'shots'||char(34)) as shots_key,
                       instr(output_text,'still_subject') as fields
                FROM agent_run WHERE task_type='shot_prompts' ORDER BY started_at DESC LIMIT 8
            """),
            "recent_repair_results": rows("""
                SELECT sequence,timestamp,aggregate_id,payload FROM domain_event
                WHERE event_type='media.sheet_repair_finished' ORDER BY sequence DESC LIMIT 6
            """),
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/studio.db"))
    parser.add_argument("--save", type=Path)
    args = parser.parse_args()
    result = snapshot(args.database)
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
