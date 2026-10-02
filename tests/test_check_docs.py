"""The architecture integrity check is line-ending independent.

Every architecture document is stored with LF in git. A Windows checkout with core.autocrlf
writes CRLF, Linux and macOS write LF, so a hash over the raw bytes passed on exactly one of
them (measured 2026-10-01 on a fresh clone of 15d2f96: 77 of 78 recorded hashes matched only a
CRLF checkout, 02_SRS only an LF one). The recorded hash is now taken over the text with CRLF
folded to LF, so the same reviewed content passes on every machine, while a change to the words
still fails.
"""

import hashlib
import importlib.util
import json
import shutil

from app.config import ROOT

spec = importlib.util.spec_from_file_location("check_docs", ROOT / "scripts/check_docs.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

DOCUMENT = "docs/architecture/02_SRS.md"


def _as_lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def _as_crlf(data: bytes) -> bytes:
    return _as_lf(data).replace(b"\n", b"\r\n")


def test_a_crlf_copy_and_an_lf_copy_of_one_document_hash_the_same(tmp_path):
    original = (ROOT / DOCUMENT).read_bytes()
    lf, crlf = tmp_path / "lf.md", tmp_path / "crlf.md"
    lf.write_bytes(_as_lf(original))
    crlf.write_bytes(_as_crlf(original))
    assert lf.read_bytes() != crlf.read_bytes()

    assert checker.document_sha256(lf) == checker.document_sha256(crlf)
    # The normalised hash is the hash of the LF text: what git stores for the document.
    assert checker.document_sha256(crlf) == hashlib.sha256(_as_lf(original)).hexdigest()


def test_every_recorded_architecture_hash_is_the_normalised_one():
    index = json.loads((ROOT / "docs/project/DOCUMENTATION_INDEX.json").read_text("utf-8"))
    architecture = [r for r in index["documents"] if r["path"].startswith("docs/architecture/")]
    assert len(architecture) == 78
    for record in architecture:
        assert record["sha256"] == checker.document_sha256(ROOT / record["path"]), record["path"]
        # The pre-move hash stays as it was captured.
        assert len(record["original_sha256"]) == 64


def test_the_check_passes_on_an_lf_checkout_and_on_a_crlf_checkout(tmp_path):
    for name, convert in (("lf", _as_lf), ("crlf", _as_crlf)):
        root = tmp_path / name
        shutil.copytree(ROOT / "docs", root / "docs")
        shutil.copy(ROOT / "README.md", root / "README.md")  # documents link to it
        for document in (root / "docs/architecture").glob("*.md"):
            document.write_bytes(convert(document.read_bytes()))
        assert checker.check_docs(root) == [], name


def test_a_changed_word_still_fails_whatever_the_line_endings(tmp_path):
    shutil.copytree(ROOT / "docs", tmp_path / "docs")
    target = tmp_path / DOCUMENT
    text = _as_crlf(target.read_bytes())
    target.write_bytes(text.replace(b"\r\n", b"\r\nChanged requirement\r\n", 1))
    errors = checker.check_docs(tmp_path)
    assert f"Architecture changed without indexed review: {DOCUMENT}" in errors


def test_the_repository_keeps_architecture_documents_lf_on_checkout():
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    rules = [line.split() for line in attributes if line.strip() and not line.startswith("#")]
    assert ["*", "text=auto"] in rules
    assert ["docs/architecture/*.md", "text", "eol=lf"] in rules
