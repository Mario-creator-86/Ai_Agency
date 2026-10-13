"""Make the Owner's ElevenLabs pronunciation dictionary hold ``config/pronunciation.json``.

The Owner, 2026-10-12: «ai acordul meu să faci asta, poți face modificările» — the studio keeps
one dictionary of its own in his ElevenLabs account («AMN-AI narration»): names and acronyms its
narrators say, never numbers (the vendor's text normalisation says those right). This command
creates it once, replaces its rules when the file changes, and writes its locator to
``data/elevenlabs_pronunciation.json``, which the studio reads for every narration whose words
contain one of the terms (`app.providers.elevenlabs_lexicon`). It costs no characters.

It reads the ElevenLabs key from the studio's own vault, never prints it, and writes nothing to
the database. A running studio picks the new version up for the next narration it voices
(the adapter reads the state file each time it is made).

Usage::

    uv run python scripts/pronunciation_sync.py           # sync (no call when nothing changed)
    uv run python scripts/pronunciation_sync.py --check   # show the rules and the synced state
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.providers import elevenlabs_lexicon as lexicon  # noqa: E402

DATABASE = ROOT / "data" / "studio.db"
VERIFIED = ("VERIFIED", "ACCESS_VERIFIED")


def elevenlabs_key() -> str:
    """The key of the studio's verified ElevenLabs connection, read through its vault."""
    from app.integrations.vault import CredentialVault  # noqa: PLC0415

    with sqlite3.connect(f"file:{DATABASE.as_posix()}?mode=ro", uri=True, timeout=10) as db:
        rows = db.execute(
            "select encrypted_secrets, status from integration where kind = 'elevenlabs'"
        ).fetchall()
    for encrypted, status in rows:
        if status in VERIFIED:
            secrets = CredentialVault(DATABASE.with_suffix(".credentials.key")).decrypt(encrypted)
            key = str(secrets.get("api_key") or "")
            if key:
                return key
    raise SystemExit("No verified ElevenLabs connection with a key in the studio.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="show the rules and state only")
    args = parser.parse_args()
    data = lexicon.load_rules()
    print(f"{len(data['rules'])} rules: {', '.join(lexicon.terms_of(data))}")
    if args.check:
        print(json.dumps(lexicon.read_state(), ensure_ascii=False, indent=1))
        return
    state = lexicon.sync_dictionary(elevenlabs_key())
    shown = {k: v for k, v in state.items() if k != "rules_sha"}
    print(json.dumps(shown, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
