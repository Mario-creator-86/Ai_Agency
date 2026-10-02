"""Verify the specification inventory, hash integrity and local Markdown references."""

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def document_sha256(path: Path) -> str:
    """SHA-256 of a document's text with CRLF folded to LF.

    git stores every architecture document with LF; a Windows checkout with core.autocrlf
    writes CRLF and Linux writes LF. Hashing the raw bytes passed on one of them only, so the
    recorded hash is the LF one: the bytes git stores, whatever the checkout wrote.
    """
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def check_docs(root: Path = ROOT) -> list[str]:
    index = json.loads((root / "docs/project/DOCUMENTATION_INDEX.json").read_text(encoding="utf-8"))
    errors = []
    if len(index["documents"]) != index["source_document_count"]:
        errors.append("Source inventory count changed")
    paths = [record["path"] for record in index["documents"]]
    if len(paths) != len(set(paths)):
        errors.append("Duplicate document path in inventory")
    tracked_architecture = {path for path in paths if path.startswith("docs/architecture/")}
    actual_architecture = {
        path.relative_to(root).as_posix() for path in (root / "docs/architecture").glob("*.md")
    }
    if actual_architecture != tracked_architecture:
        errors.append("Architecture directory differs from indexed inventory")
    for record in index["documents"]:
        path = root / record["path"]
        if not path.resolve().is_relative_to((root / "docs").resolve()):
            errors.append("Document path escaped docs directory")
            continue
        if not path.is_file():
            errors.append(f"Missing: {record['path']}")
            continue
        if path.parent.name == "architecture":
            if document_sha256(path) != record["sha256"]:
                errors.append(f"Architecture changed without indexed review: {record['path']}")
        text = path.read_text(encoding="utf-8")
        for reference in re.findall(r"`((?:\.\./)?[A-Za-z0-9_./-]+\.md)`", text):
            target = path.parent / reference
            # Some source documents refer to future filenames, e.g. deployment artifacts.
            if reference.split("/")[-1] in {r["original_path"] for r in index["documents"]}:
                if not target.is_file():
                    errors.append(f"Broken reference: {record['path']} -> {reference}")
    return errors


if __name__ == "__main__":
    errors = check_docs()
    if errors:
        raise SystemExit("\n".join(errors))
    print("Documentation inventory and architecture hashes verified.")
