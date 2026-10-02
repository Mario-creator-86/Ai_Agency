"""Third-party licences a buyer receives are named, with their notices (SELL-05).

The YuNet network was redistributed with no licence beside it, the page's bundle dropped the
MIT notices of the libraries inside it, and no file listed the dependencies' licences. These
tests keep THIRD_PARTY_NOTICES.md complete as the locks change.
"""

from __future__ import annotations

import json
import re
import subprocess

from app.config import ROOT

NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"


def test_the_page_serves_the_same_notices():
    served = ROOT / "frontend" / "public" / "THIRD_PARTY_NOTICES.txt"
    assert served.read_text(encoding="utf-8") == NOTICES.read_text(encoding="utf-8")


def test_the_bundled_model_and_fonts_carry_their_licence_texts():
    licence = (ROOT / "backend/app/media/models/LICENSE-YuNet").read_text(encoding="utf-8")
    assert "MIT License" in licence and "Shiqi Yu" in licence
    from app.media.faces import YUNET_SHA256

    assert YUNET_SHA256 in licence
    assert (ROOT / "backend/app/media/fonts/OFL.txt").is_file()
    assert (ROOT / "frontend/public/fonts/oxanium/OFL.txt").is_file()


def test_every_runtime_python_dependency_is_listed():
    exported = subprocess.run(
        ["uv", "export", "--frozen", "--no-dev", "--no-hashes", "--no-emit-project"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    names = {
        re.split(r"[=;\s]", line, maxsplit=1)[0].lower()
        for line in exported.splitlines()
        if line and line[0].isalpha()
    }
    text = NOTICES.read_text(encoding="utf-8").lower()
    missing = sorted(name for name in names if name not in text)
    assert not missing, missing


def test_every_package_built_into_the_page_is_listed():
    # ws, its typings and undici-types are Node-side dependencies of Epic's library that a
    # browser bundle never contains (the page talks over the browser's own WebSocket).
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))
    shipped = {
        path.removeprefix("node_modules/")
        for path, row in lock["packages"].items()
        if path
        and not row.get("dev")
        and not path.removeprefix("node_modules/").startswith("@types/")
        and path.removeprefix("node_modules/") not in ("undici-types", "ws")
    }
    text = NOTICES.read_text(encoding="utf-8")
    missing = sorted(name for name in shipped if name not in text)
    assert not missing, missing
