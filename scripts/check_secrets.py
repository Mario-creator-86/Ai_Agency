"""Scan distributable text; local secrets, dependency trees and generated data are excluded."""

import re
from pathlib import Path

from detect_secrets import SecretsCollection
from detect_secrets.settings import default_settings

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {
    ".git",
    ".venv",
    "node_modules",
    "dist",
    "data",
    "output",
    ".playwright-cli",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
}
TEXT_SUFFIXES = {".py", ".js", ".json", ".html", ".css", ".toml", ".yml", ".md", ".ini"}


def main() -> None:
    collection = SecretsCollection()
    with default_settings():
        for path in ROOT.rglob("*"):
            relative = path.relative_to(ROOT)
            if any(part in EXCLUDED for part in relative.parts):
                continue
            if path.is_file() and path.suffix in TEXT_SUFFIXES and not path.name.startswith(".env"):
                collection.scan_file(str(path))
    findings = []
    for path, secret in collection:
        relative = Path(path).relative_to(ROOT)
        line = Path(path).read_text(encoding="utf-8").splitlines()[secret.line_number - 1]
        if relative.as_posix() == "docs/project/DOCUMENTATION_INDEX.json" and re.fullmatch(
            r'\s*"(?:original_)?sha256": "[0-9a-f]{64}",?\s*', line
        ):
            continue  # Reviewed document checksums, not credentials; other fields remain scanned.
        findings.append((relative, secret.line_number))
    if findings:
        # Deliberately print locations only, never secret values.
        raise SystemExit("Potential secrets: " + ", ".join(f"{p}:{line}" for p, line in findings))
    print("Secret scan passed for distributable source and documentation.")


if __name__ == "__main__":
    main()
