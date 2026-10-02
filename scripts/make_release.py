"""Build the archive a buyer receives: what runs the studio, and nothing of this machine's.

    uv run python scripts/make_release.py [--out FOLDER] [--with-tests] [--with-dist]

The repository holds more than a buyer should get: the first studio's process history
(docs/project, about 1.4 MB of status, decisions and changelog), scratch scripts that drive the
Owner's own studio, the Unreal and Blender art sources with paths of his machine, and employee
portraits. The archive is built from an ALLOWLIST (SELL-17): only the files a studio needs to
install, run, demo and operate. On top of that, nothing secret can enter it (no .env, no vault
key, no database, no media), and a file that names this machine's folders stops the build.

Files come from `git ls-files` (what the repository tracks, plus new files it does not ignore)
when run in a checkout, else from a walk of the folder. The archive is
`<out>/amn-ai-<version>.zip`, with one top folder `amn-ai-<version>/` and a `.sha256` beside it.
`--with-dist` adds an already built `frontend/dist` (this script never builds it);
`--with-tests` adds the test suite.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import tomllib
import zipfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]

#: Folders and files a studio needs. A path is shipped when it is one of these or inside one.
INCLUDE: tuple[str, ...] = (
    "backend/app/",
    "backend/migrations/",
    "config/",
    "frontend/src/",
    "frontend/public/",
    "frontend/index.html",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/tsconfig.json",
    "frontend/vite.config.js",
    "alembic.ini",
    "pyproject.toml",
    "uv.lock",
    "start.cmd",
    "README.md",
    "THIRD_PARTY_NOTICES.md",
    ".env.example",
    ".gitignore",
    ".gitattributes",
    "docs/OPERATOR_GUIDE.md",
    "docs/project/YOUTUBE_CONNECTIONS.md",
    # The scripts an operator runs; the developer's probes and checks stay behind.
    "scripts/start.py",
    "scripts/run.py",
    "scripts/bootstrap.py",
    "scripts/backup.py",
    "scripts/restore.py",
    "scripts/media_inventory.py",
    "scripts/demo_daily_run.py",
    "scripts/apply_llm_allocation.py",
    "scripts/rename_studio.py",
    "scripts/install_studio_service.ps1",
    "scripts/uninstall_studio_service.ps1",
    "scripts/amn-ai.service",
)
TESTS: tuple[str, ...] = ("tests/",)

#: Never shipped, whatever the allowlist says: secrets, the studio's data, caches, history.
NEVER = re.compile(
    r"(^|/)(\.env(\..*)?|.*\.credentials\.key|.*\.db(-wal|-shm)?|.*\.sqlite3?)$"
    r"|(^|/)(data|storage|backend/storage|node_modules|__pycache__|\.venv|\.claude|\.git"
    r"|\.pytest_cache|\.mypy_cache|\.ruff_cache|output|scratch|Claude outputs)/"
    r"|\.py[cod]$"
)
#: .env.example is the one .env file a buyer needs.
ALLOWED_DESPITE_NEVER = {".env.example"}

#: A text file naming one of these is this machine's, not the product's: the build stops.
MACHINE_PATHS = re.compile(r"Users[\\/]+mario|AI Acency|AMN_PixelStreaming|AMN_backup", re.I)
TEXT_SUFFIXES = {
    ".py",
    ".js",
    ".mjs",
    ".ts",
    ".json",
    ".md",
    ".txt",
    ".html",
    ".css",
    ".toml",
    ".ini",
    ".ps1",
    ".cmd",
    ".service",
    ".yml",
    ".yaml",
    ".cfg",
    ".example",
}


class ReleaseRefused(RuntimeError):
    """The archive would carry something it must not."""


def version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data.get("project", {}).get("version") or "0.0.0")


def candidate_files(root: Path = ROOT) -> list[str]:
    """Every file of the checkout as a POSIX path: git's list in a checkout, else a walk."""
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if Path(top).resolve() != root.resolve():
            raise subprocess.CalledProcessError(1, "git")
        listed = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            check=True,
        ).stdout.decode("utf-8")
        names = [name for name in listed.split("\0") if name]
    except (OSError, subprocess.CalledProcessError):
        names = [
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and not NEVER.search(path.relative_to(root).as_posix())
        ]
    return sorted(name for name in names if (root / name).is_file())


def _allowed(name: str, include: Iterable[str]) -> bool:
    return any(
        name == entry or (entry.endswith("/") and name.startswith(entry)) for entry in include
    )


def select_files(names: Iterable[str], *, with_tests: bool = False) -> list[str]:
    """The allowlisted files, with every forbidden one removed."""
    include = INCLUDE + (TESTS if with_tests else ())
    chosen = []
    for name in names:
        if not _allowed(name, include):
            continue
        if name not in ALLOWED_DESPITE_NEVER and NEVER.search(name):
            continue
        chosen.append(name)
    return chosen


def machine_paths(root: Path, names: Iterable[str]) -> list[str]:
    """Shipped text files that name this machine's folders, as 'file:line'."""
    found = []
    for name in names:
        path = root / name
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        found.extend(f"{name}:{n}" for n, line in enumerate(lines, 1) if MACHINE_PATHS.search(line))
    return found


def build(
    out: Path,
    *,
    root: Path = ROOT,
    with_tests: bool = False,
    with_dist: bool = False,
    names: list[str] | None = None,
) -> Path:
    """Write the archive and its checksum; return the archive's path."""
    files = select_files(
        names if names is not None else candidate_files(root), with_tests=with_tests
    )
    if with_dist:
        dist = root / "frontend" / "dist"
        if not (dist / "index.html").is_file():
            raise ReleaseRefused("--with-dist: frontend/dist is not built (npm run build).")
        files += sorted(p.relative_to(root).as_posix() for p in dist.rglob("*") if p.is_file())
    for required in ("README.md", "THIRD_PARTY_NOTICES.md", "backend/app/main.py", ".env.example"):
        if required not in files:
            raise ReleaseRefused(f"Arhiva nu poate fi făcută fără {required}.")
    leaks = [name for name in files if name not in ALLOWED_DESPITE_NEVER and NEVER.search(name)]
    if leaks:
        raise ReleaseRefused(f"Fișiere interzise în arhivă: {leaks[:5]}")
    named = machine_paths(root, files)
    if named:
        raise ReleaseRefused(
            "Fișiere care numesc folderele acestui calculator: " + ", ".join(named[:10])
        )
    tag = f"amn-ai-{version()}"
    out.mkdir(parents=True, exist_ok=True)
    archive = out / f"{tag}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for name in files:
            info = zipfile.ZipInfo(str(PurePosixPath(tag) / name), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zipped.writestr(info, (root / name).read_bytes())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    return archive


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description="Arhiva de livrare a studioului.")
    parser.add_argument("--out", type=Path, default=ROOT / "output" / "release")
    parser.add_argument("--with-tests", action="store_true")
    parser.add_argument("--with-dist", action="store_true")
    args = parser.parse_args()
    try:
        archive = build(args.out, with_tests=args.with_tests, with_dist=args.with_dist)
    except ReleaseRefused as exc:
        print(f"Arhiva NU a fost făcută: {exc}", file=sys.stderr)
        return 1
    with zipfile.ZipFile(archive) as zipped:
        count = len(zipped.namelist())
    print(f"Arhiva: {archive} ({count} fișiere, {archive.stat().st_size / 1_048_576:.1f} MB)")
    print(f"Suma de control: {archive.with_suffix('.zip.sha256')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
