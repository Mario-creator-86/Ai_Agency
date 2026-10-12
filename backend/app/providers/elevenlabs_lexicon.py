"""The studio's own ElevenLabs pronunciation dictionary (2026-10-12).

The Owner, after reading that ElevenLabs keeps pronunciation rules: «Dacă ne ajută ar trebui să
facem asta!» and, once shown what it would cover, «ai acordul meu să faci asta, poți face
modificările». Until then the adapter could send dictionaries but «creating one is the Owner's
act»; none existed, and Rolf Widerøe was said «Wideroe» in the cyclotron film.

The rules live in ``config/pronunciation.json`` (committed: names and acronyms only — numbers and
units are already said right by the vendor's text normalisation). `sync_dictionary` makes the
account's dictionary hold exactly those rules — created once with ``add-from-rules``, replaced
with ``set-rules`` when the file changes (each change is a new ``version_id``) — and writes the
locator, the terms and the rules' hash to ``data/elevenlabs_pronunciation.json`` (git-ignored:
it names an account resource). `studio_dictionaries` reads that file for the adapter
(`factory.tts_provider_for`), which attaches the dictionary to a narration only when its words
contain one of the terms (`elevenlabs.ElevenLabsTTSAdapter.request_settings`).

Documented endpoints (read 2026-10-12): POST /v1/pronunciation-dictionaries/add-from-rules
{name, description, rules} -> {id, version_id}; POST /v1/pronunciation-dictionaries/{id}/set-rules
{rules} -> {id, version_id}. A rule is {type: "alias", string_to_replace, alias} or {type:
"phoneme", string_to_replace, phoneme, alphabet: "ipa"}, with case_sensitive and word_boundaries.
Creating or changing a dictionary costs no characters.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from app.config import ROOT

#: The curated rules, committed with the code.
RULES_PATH = ROOT / "config" / "pronunciation.json"
#: The account's dictionary as last synced: its locator, terms and the rules' hash.
STATE_PATH = ROOT / "data" / "elevenlabs_pronunciation.json"
HOST = "api.elevenlabs.io"
RULE_TYPES = ("alias", "phoneme")


class LexiconError(ValueError):
    """The rules file is not usable as it stands."""


def load_rules(path: Path = RULES_PATH) -> dict[str, Any]:
    """The rules file, checked: every rule has the documented fields and a term once."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, list) or not rules:
        raise LexiconError("config/pronunciation.json has no rules")
    seen: set[str] = set()
    for rule in rules:
        term = str(rule.get("string_to_replace") or "").strip() if isinstance(rule, dict) else ""
        kind = rule.get("type") if isinstance(rule, dict) else None
        if not term or kind not in RULE_TYPES:
            raise LexiconError(f"A rule without a term or type: {rule!r}")
        if kind == "alias" and not str(rule.get("alias") or "").strip():
            raise LexiconError(f"The alias rule for «{term}» has no alias")
        if kind == "phoneme" and not (
            str(rule.get("phoneme") or "").strip() and rule.get("alphabet")
        ):
            raise LexiconError(f"The phoneme rule for «{term}» has no phoneme or alphabet")
        if term in seen:
            raise LexiconError(f"«{term}» has two rules")
        seen.add(term)
    return data


def vendor_rules(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The rules as the vendor takes them: only its fields, matching case and whole words."""
    out: list[dict[str, Any]] = []
    for rule in data["rules"]:
        item: dict[str, Any] = {
            "type": rule["type"],
            "string_to_replace": rule["string_to_replace"],
            "case_sensitive": True,
            "word_boundaries": True,
        }
        if rule["type"] == "alias":
            item["alias"] = rule["alias"]
        else:
            item["phoneme"] = rule["phoneme"]
            item["alphabet"] = rule["alphabet"]
        out.append(item)
    return out


def rules_sha(rules: Iterable[Mapping[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(list(rules), ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def terms_of(data: Mapping[str, Any]) -> list[str]:
    return [str(rule["string_to_replace"]) for rule in data["rules"]]


def mentions(text: str, terms: Iterable[str]) -> bool:
    """Whether the words contain a term the way the vendor matches it: case-sensitive, whole
    word. A narration without one keeps exactly the identity and request it always had."""
    for term in terms:
        if term and re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text):
            return True
    return False


def read_state(path: Path = STATE_PATH) -> dict[str, Any] | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def studio_dictionaries(path: Path = STATE_PATH) -> list[dict[str, Any]]:
    """The synced dictionary for the adapter: [{pronunciation_dictionary_id, version_id, terms}],
    or [] when none was synced (the adapter then sends what it always sent)."""
    state = read_state(path)
    if not state:
        return []
    dictionary, version = state.get("pronunciation_dictionary_id"), state.get("version_id")
    terms = state.get("terms")
    if not (isinstance(dictionary, str) and dictionary and isinstance(version, str) and version):
        return []
    return [
        {
            "pronunciation_dictionary_id": dictionary,
            "version_id": version,
            "terms": [str(t) for t in terms] if isinstance(terms, list) else [],
        }
    ]


def sync_dictionary(
    api_key: str,
    *,
    rules_path: Path = RULES_PATH,
    state_path: Path = STATE_PATH,
    transport: Any = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Make the account's dictionary hold the rules file's rules; return the state written.

    Nothing is sent when the rules are unchanged since the last sync. ``transport`` is
    ``app.providers.media_http.request``'s signature (tests pass a fake; nothing else calls
    the vendor)."""
    from app.providers.media_http import request  # noqa: PLC0415

    # One request, never retried: an unanswered create may have made the dictionary, and a
    # second one would be a second dictionary. The next sync finds no state and asks again.
    send = transport or request
    data = load_rules(rules_path)
    rules = vendor_rules(data)
    digest = rules_sha(rules)
    state = read_state(state_path) or {}
    if state.get("rules_sha") == digest and state.get("version_id"):
        return {**state, "changed": False}
    headers = {
        "xi-api-key": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if state.get("pronunciation_dictionary_id"):
        path = f"/v1/pronunciation-dictionaries/{state['pronunciation_dictionary_id']}/set-rules"
        body = {"rules": rules}
    else:
        path = "/v1/pronunciation-dictionaries/add-from-rules"
        body = {"name": data.get("name") or "AMN-AI narration", "rules": rules}
        if data.get("description"):
            body["description"] = str(data["description"])[:1000]
    answer, _, _ = send(
        HOST,
        "POST",
        path,
        headers,
        json.dumps(body, ensure_ascii=False).encode("utf-8"),
        timeout=30,
    )
    dictionary = (answer or {}).get("id") or state.get("pronunciation_dictionary_id")
    version = (answer or {}).get("version_id")
    if not dictionary or not version:
        raise LexiconError("ElevenLabs did not return the dictionary's id and version")
    from app.services import utc_now  # noqa: PLC0415

    written = {
        "pronunciation_dictionary_id": str(dictionary),
        "version_id": str(version),
        "name": body.get("name") or state.get("name") or data.get("name"),
        "terms": terms_of(data),
        "rules_sha": digest,
        "synced_at": now or utc_now(),
    }
    Path(state_path).parent.mkdir(parents=True, exist_ok=True)
    Path(state_path).write_text(json.dumps(written, ensure_ascii=False, indent=1), encoding="utf-8")
    return {**written, "changed": True}
