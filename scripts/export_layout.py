"""Export the backend's default office layout (zones, desks, building box) to
art-source/layout.json so the Blender/Unreal reference-scene builders read the same
geometry the renderer gets from GET /api/v1/office/layout.
Run: uv run python scripts/export_layout.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.office.services import DEFAULT_OFFICE_LAYOUT  # noqa: E402

out = ROOT / "art-source" / "layout.json"
out.write_text(json.dumps(DEFAULT_OFFICE_LAYOUT, indent=2) + "\n", encoding="utf-8")
print(f"wrote {out}")
