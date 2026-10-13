"""Export the Character Bible's visual fields for the Blender character build.

  uv run python scripts/export_character_bible.py

Writes art-source/character_bible.json from the backend's canonical character records, so the
sprites are coloured by the Bible and never by a value typed into the art script. Reads code,
not the live database: nothing here touches data/studio.db.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.media.services import DEFAULT_CHARACTERS  # noqa: E402


def main() -> None:
    out = [
        {
            "canonical_name": c["canonical_name"],
            "role": c["role"],
            "palette": c.get("palette_json", {}),
            "face_hair_desc": c.get("face_hair_desc", ""),
            "outfit_desc": c.get("outfit_desc", ""),
            "forbidden_deviations": c.get("forbidden_deviations", ""),
        }
        for c in DEFAULT_CHARACTERS
    ]
    path = ROOT / "art-source" / "character_bible.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(out)} characters to {path}")


if __name__ == "__main__":
    main()
