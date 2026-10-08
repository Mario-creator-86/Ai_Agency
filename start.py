"""Compatibility entry for `python start.py`; the launcher lives in scripts/start.py."""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main(argv: Sequence[str] | None = None) -> int:
    uv = shutil.which("uv")
    if not uv:
        print("uv nu este disponibil pe PATH. Instaleaza uv si reincearca.", file=sys.stderr)
        return 1
    arguments = sys.argv[1:] if argv is None else argv
    try:
        process = subprocess.Popen(
            [uv, "run", "--locked", "python", str(ROOT / "scripts" / "start.py"), *arguments],
            cwd=ROOT,
        )
    except OSError as exc:
        print(f"Lansatorul nu a putut porni: {exc}", file=sys.stderr)
        return 1
    while True:
        try:
            return process.wait()
        except KeyboardInterrupt:
            # Ctrl+C also reaches the shared console's launcher; let it finish cleanly.
            continue


if __name__ == "__main__":
    raise SystemExit(main())
