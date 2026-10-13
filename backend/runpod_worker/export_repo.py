"""Write the worker as a standalone repository for RunPod's GitHub integration.

Owner's card (2026-10-09): the small images (no weights) are built by RunPod's GitHub
integration from a PRIVATE GitHub repository that holds only the worker, at its root. This
writes that repository's tree into a folder; the Owner creates the repository and pushes it
himself (nothing here touches GitHub, RunPod or Hugging Face):

    python -m runpod_worker.export_repo --dest <folder outside the studio>

The tree: ``Dockerfile.stills`` and ``Dockerfile.motion`` (each endpoint names its own as the
"Dockerfile Path"; every pin is written in, the integration documents no build arguments),
the handler and its modules, the graphs, the locks and a README with his steps. The baked
last resort (``Dockerfile``, which needs a Hugging Face secret) is never exported. Text files
are written with LF line endings. ``EXPORT_MANIFEST.json`` lists every file's sha256 and the
studio commit it came from; a later export into the same folder replaces the files it wrote
before (and removes the ones no longer exported), keeps ``.git`` and anything else the Owner
added, and refuses a non-empty folder it did not write or a folder inside the studio's repo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

HERE = Path(__file__).resolve().parent
#: The studio repository (backend/runpod_worker -> the root): never an export target.
STUDIO_ROOT = HERE.parents[1]
MANIFEST = "EXPORT_MANIFEST.json"
#: Copied as they are (LF line endings), in this order, plus every workflows/*.json.
FILES = (
    "Dockerfile.stills",
    "Dockerfile.motion",
    ".dockerignore",
    "requirements.txt",
    "requirements-mirror.txt",
    "__init__.py",
    "amn_handler.py",
    "build.py",
    "comfy.py",
    "contract.py",
    "postprocess.py",
    "storage.py",
    "weights.py",
    "models.lock.json",
    "mirrors.lock.json",
    "custom_nodes.lock.json",
)

README = """# AMN worker pentru RunPod (imaginile mici, fără modele)

Acest depozit conține doar programul care rulează pe plăcile video RunPod (worker-ul AMN).
Modelele NU sunt în imagine: fiecare endpoint le ia din „Model” (cache-ul RunPod), adică din
copia ta privată de pe Hugging Face. Fișierele de aici sunt scrise de studio
(`python -m runpod_worker.export_repo`); nu le modifica de mână, ci exportă din nou.

## Pașii tăi (o singură dată)

1. Creezi pe GitHub un depozit **privat**, gol, și urci în el conținutul acestui folder
   (`git init`, `git add .`, `git commit`, `git push`), din contul tău.
2. În RunPod legi contul GitHub (un singur cont GitHub pentru contul RunPod), apoi, la fiecare
   endpoint, alegi sursa GitHub: acest depozit, ramura `main` și „Dockerfile Path”:
   - endpoint-ul de **poze**: `Dockerfile.stills`
   - endpoint-ul de **clipuri**: `Dockerfile.motion`
3. La fiecare endpoint, în Manage → Edit Endpoint, câmpul **Model** este copia ta privată de pe
   Hugging Face (poze: copia de poze; clipuri: copia de clipuri), cu tokenul tău Hugging Face.
   Câmpul nu se poate seta prin API; studioul verifică doar ce raportează worker-ul.
4. Tot acolo, la „Environment Variables”, pui `AMN_MIRROR_REPO` (copia, cont/nume) și
   `AMN_MIRROR_REVISION` (commit-ul copiei, 40 de caractere), exact cum ți le scrie studioul
   după copiere. Fără ele worker-ul refuză cu WRONG_REVISION înainte să încarce vreun model.
5. Orice actualizare ajunge în RunPod numai printr-un **release** nou pe GitHub: RunPod
   reconstruiește imaginea doar la un release.

## Ce nu e dovedit încă

Primul build făcut de RunPod, faza lui „Testing” (ce rulează și dacă se plătește), viteza de
încărcare a modelelor din cache și dacă există plăci RTX PRO 6000 pe mașinile cu cache-ul:
toate se măsoară la testul plătit, numai cu aprobarea ta.

## Ce conține

- `Dockerfile.stills`, `Dockerfile.motion`: imaginile mici, cu versiunile fixate în ele.
- `amn_handler.py`, `weights.py`, `comfy.py`, `contract.py`, `postprocess.py`, `storage.py`,
  `build.py`: programul.
- `workflows/`: grafurile ComfyUI (poze, poze cu referințe, clipuri LTX-2.5 și Wan 2.2).
- `models.lock.json`, `mirrors.lock.json`, `custom_nodes.lock.json`: ce modele și ce copie
  sunt fixate.
- `EXPORT_MANIFEST.json`: amprenta fiecărui fișier și versiunea studioului din care vine.
"""


def _sources() -> list[str]:
    workflows = sorted(f"workflows/{p.name}" for p in (HERE / "workflows").glob("*.json"))
    return [*FILES, *workflows]


def _lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def _studio_commit() -> str | None:
    try:
        answer = subprocess.run(
            ["git", "-C", str(STUDIO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    commit = answer.stdout.strip()
    return commit if answer.returncode == 0 and len(commit) == 40 else None


def _previous(dest: Path) -> dict[str, str]:
    """The files an earlier export wrote here; ValueError for a folder it did not write."""
    if not dest.exists():
        return {}
    if not dest.is_dir():
        raise ValueError(f"{dest} is not a folder")
    manifest = dest / MANIFEST
    if manifest.is_file():
        files = json.loads(manifest.read_text(encoding="utf-8")).get("files", {})
        return {str(name): str(digest) for name, digest in dict(files).items()}
    if any(child.name != ".git" for child in dest.iterdir()):
        raise ValueError(f"refused: {dest} is not empty and holds no earlier export")
    return {}


def export(dest: Path) -> list[str]:
    """Write the worker repository into ``dest``; returns the files written (relative)."""
    target = dest.resolve()
    if target == STUDIO_ROOT or target.is_relative_to(STUDIO_ROOT):
        raise ValueError("refused: export outside the studio's repository (a separate repo)")
    before = _previous(target)
    target.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    for name in _sources():
        data = _lf((HERE / name).read_bytes())
        out = target / name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        written[name] = hashlib.sha256(data).hexdigest()
    readme = README.encode("utf-8")
    (target / "README.md").write_bytes(readme)
    written["README.md"] = hashlib.sha256(readme).hexdigest()
    for stale in sorted(set(before) - set(written)):
        path = (target / stale).resolve()
        if path.is_relative_to(target) and path.is_file():
            path.unlink()
    manifest = {
        "source": "AMN-AI backend/runpod_worker",
        "source_commit": _studio_commit(),
        "files": written,
    }
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    (target / MANIFEST).write_bytes(text.encode("utf-8"))
    return list(written)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="runpod_worker.export_repo", description=__doc__)
    parser.add_argument("--dest", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        written = export(args.dest)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"exported {len(written)} files to {args.dest}")
    print("next: push it to a PRIVATE GitHub repository; RunPod builds on a GitHub release")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
