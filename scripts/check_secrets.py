"""Scan what the repository would ship for secrets; fail only on findings nobody has reviewed.

What is scanned: in a git checkout, the files git would ship - tracked plus untracked files
that are not ignored (`git ls-files --cached --others --exclude-standard`, read-only). Outside
one (a release archive), a walk of the tree that skips local data, dependency trees and
generated folders. Either way `.env` files, the credentials key and the studio's data folder
are never opened.

What fails: a finding not in the reviewed baseline (`.secrets.baseline`, detect-secrets
format). A finding matches the baseline on its file, its detector and its hashed value, not on
its line number, so a reviewed line that moves stays reviewed while the same value appearing
in another file does not. A line may also carry an inline `pragma: allowlist secret`, which
detect-secrets honours. Only locations are printed, never a value.

    python scripts/check_secrets.py                  # the gate
    python scripts/check_secrets.py --write-baseline # record today's findings for review
"""

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from detect_secrets import SecretsCollection
from detect_secrets.core import baseline as baseline_format
from detect_secrets.settings import default_settings

ROOT = Path(__file__).resolve().parents[1]
BASELINE_NAME = ".secrets.baseline"
#: Folders never scanned, by any path part: local data and secrets, dependency trees, caches,
#: build output, and other agents' scratch worktrees.
EXCLUDED = {
    ".git",
    ".claude",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "data",
    "storage",
    "output",
    "Claude outputs",
    ".playwright-cli",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
}
TEXT_SUFFIXES = {
    ".py",
    ".js",
    ".mjs",
    ".ts",
    ".json",
    ".html",
    ".css",
    ".toml",
    ".yml",
    ".yaml",
    ".md",
    ".ini",
    ".cfg",
    ".txt",
    ".ps1",
    ".cmd",
    ".bat",
    ".sh",
    ".patch",
}
#: Text files without one of the suffixes above that still ship and are read.
TEXT_NAMES = {".env.example", ".gitattributes", ".gitignore"}
#: The reviewed document checksums in the documentation index are not credentials.
_INDEX = "docs/project/DOCUMENTATION_INDEX.json"
_INDEX_HASH = re.compile(r'\s*"(?:original_)?sha256": "[0-9a-f]{64}",?\s*')
#: The GPU worker's weight pins (a commit and a content checksum per file) are not credentials
#: either: only a whole line holding one of them passes, so a key elsewhere is still caught.
_LOCK_PIN = re.compile(r'\s*"(?:sha256": "[0-9a-f]{64}|revision": "[0-9a-f]{40})",?\s*')
#: mirrors.lock.json pins his private mirror's commit the same way (after the copy, 2026-10-09).
#: Public UI sound sources record SHA-256 digests of the shipped .ogg/.wav assets, never
#: credentials. Match only the entire sha256 line in that exact attribution manifest;
#: a token or another field in the same JSON file remains subject to the secret scan.
_UI_SOUND_SHA256 = re.compile(r'\s*"sha256": "[0-9a-f]{64}",?\s*')
_PINNED = {
    _INDEX: _INDEX_HASH,
    "backend/runpod_worker/models.lock.json": _LOCK_PIN,
    "backend/runpod_worker/mirrors.lock.json": _LOCK_PIN,
    "frontend/public/sounds/ui/sources.json": _UI_SOUND_SHA256,
}
#: The studio's configuration (config/*.json) and its state file record content checksums of
#: reviewed files: pixel art, ComfyUI workflows, the office background. Each new one failed the
#: gate until someone rewrote the whole baseline with --write-baseline (12301a7, 27e016c), and
#: a rewrite also blesses whatever else stood in the tree that day (WP29, 2026-10-09). So a
#: whole line holding a single 64-hex value under a key named for its checksum (`sha256`,
#: `workflow_sha256`, `background_sha256`, ...) passes there; a key, or any other field, in the
#: same files is still scanned.
_CHECKSUM_LINE = re.compile(r'\s*"(?:[a-z0-9]+_)*sha256": "[0-9a-f]{64}",?\s*')
_STATE = "docs/project/PROJECT_STATE.json"


def _pin_for(relative: str) -> re.Pattern[str] | None:
    """The whole-line pattern a finding in `relative` may match to be a pin, not a secret."""
    if relative in _PINNED:
        return _PINNED[relative]
    folder, _, name = relative.rpartition("/")
    if relative == _STATE or (folder == "config" and name.endswith(".json")):
        return _CHECKSUM_LINE
    return None


@dataclass(frozen=True)
class Finding:
    path: str  # relative to the scanned root, with forward slashes
    line: int
    type: str
    hashed_secret: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.path, self.type, self.hashed_secret)


def _never_read(relative: Path) -> bool:
    name = relative.name
    if name == ".env" or (name.startswith(".env.") and name not in TEXT_NAMES):
        return True
    if name.endswith(".credentials.key"):
        return True
    if name.startswith("AGENCY_WATCH_STATE_") and name.endswith(".json"):
        # The hourly watch session's state: content hashes of what it read, rewritten every
        # hour (2026-10-15: four baseline refreshes in one morning for the same kind of hex).
        return True
    return any(part in EXCLUDED for part in relative.parts[:-1])


def _is_text(relative: Path) -> bool:
    return relative.suffix.lower() in TEXT_SUFFIXES or relative.name in TEXT_NAMES


def _git_files(root: Path) -> list[Path] | None:
    """What git would ship from `root`, or None when `root` is not the top of a checkout."""
    try:
        top = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            check=False,
        )
        if top.returncode != 0 or Path(top.stdout.strip()).resolve() != root.resolve():
            return None
        listed = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return None
    if listed.returncode != 0:
        return None
    names = [name for name in listed.stdout.decode("utf-8").split("\0") if name]
    return [Path(name) for name in names]


def candidate_files(root: Path = ROOT) -> list[Path]:
    """The files the gate reads, relative to `root`, sorted."""
    listed = _git_files(root)
    if listed is None:
        listed = [path.relative_to(root) for path in root.rglob("*")]
    chosen = [
        relative
        for relative in listed
        if _is_text(relative) and not _never_read(relative) and (root / relative).is_file()
    ]
    return sorted(set(chosen), key=lambda path: path.as_posix())


def scan(root: Path = ROOT, files: list[Path] | None = None) -> list[Finding]:
    collection = SecretsCollection()
    with default_settings():
        for chosen in candidate_files(root) if files is None else files:
            collection.scan_file(str(root / chosen))
    findings = []
    for filename, secret in collection:
        relative = Path(filename).relative_to(root).as_posix()
        pin = _pin_for(relative)
        if pin is not None:
            lines = (root / relative).read_text(encoding="utf-8").splitlines()
            if pin.fullmatch(lines[secret.line_number - 1]):
                continue
        findings.append(Finding(relative, secret.line_number, secret.type, secret.secret_hash))
    return sorted(findings, key=lambda f: (f.path, f.line, f.type))


def load_baseline(path: Path) -> set[tuple[str, str, str]]:
    if not path.is_file():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        (filename, entry["type"], entry["hashed_secret"])
        for filename, entries in data.get("results", {}).items()
        for entry in entries
    }


def write_baseline(path: Path, findings: list[Finding]) -> None:
    """Record the findings in detect-secrets' baseline format, hashes only."""
    with default_settings():
        document = baseline_format.format_for_output(SecretsCollection())
    results: dict[str, list[dict[str, object]]] = {}
    for finding in findings:
        results.setdefault(finding.path, []).append(
            {
                "type": finding.type,
                "filename": finding.path,
                "hashed_secret": finding.hashed_secret,
                "is_verified": False,
                "line_number": finding.line,
            }
        )
    document["results"] = results
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline", type=Path, default=None)
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="record the current findings as the baseline; review every entry before keeping it",
    )
    args = parser.parse_args(argv)
    baseline_path = args.baseline or root / BASELINE_NAME
    files = candidate_files(root)
    findings = scan(root, files)
    if args.write_baseline:
        write_baseline(baseline_path, findings)
        print(f"Baseline written with {len(findings)} findings: {baseline_path}")
        return 0
    reviewed = load_baseline(baseline_path)
    new = [finding for finding in findings if finding.key not in reviewed]
    if new:
        # Deliberately locations only, never secret values.
        locations = ", ".join(f"{f.path}:{f.line} ({f.type})" for f in new)
        print(f"Potential secrets not in {BASELINE_NAME}: {locations}")
        return 1
    print(
        f"Secret scan passed: {len(files)} files, "
        f"{len(findings)} findings, all reviewed in {BASELINE_NAME}."
    )
    return 0


if __name__ == "__main__":
    # detect-secrets opens text with Python's default encoding. On Windows cp1252 it
    # silently skips some UTF-8 files as binary, so the release gate must use UTF-8.
    if not sys.flags.utf8_mode:
        sys.exit(
            subprocess.run(
                [sys.executable, "-X", "utf8", __file__, *sys.argv[1:]],
                stdin=subprocess.DEVNULL,
                check=False,
            ).returncode
        )
    sys.exit(main())
