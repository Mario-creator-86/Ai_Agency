"""The studio's ElevenLabs pronunciation dictionary (2026-10-12, the Owner's yes).

Rolf Widerøe was said «Wideroe» in the cyclotron film; names and acronyms now go through a
dictionary the studio keeps in his account. It is sent only with words that contain one of its
terms, so no narration made before it changes identity or is bought again. Every vendor call
here goes to a fake transport."""

from __future__ import annotations

import json

from app.providers import elevenlabs_lexicon as lexicon
from app.providers.elevenlabs import ElevenLabsTTSAdapter

LOCATOR = {"pronunciation_dictionary_id": "dict-1", "version_id": "v-1"}


def adapter(**studio) -> ElevenLabsTTSAdapter:
    voice = ElevenLabsTTSAdapter("key", "voice-1", "eleven_flash_v2")
    voice.studio_dictionaries = [{**LOCATOR, "terms": ["CERN", "Widerøe", "GeV"], **studio}]
    return voice


def test_the_committed_rules_are_usable_and_cover_the_proven_name():
    data = lexicon.load_rules()
    terms = lexicon.terms_of(data)
    assert "Widerøe" in terms and "CERN" in terms
    rules = lexicon.vendor_rules(data)
    assert all(r["case_sensitive"] and r["word_boundaries"] for r in rules)
    widerøe = next(r for r in rules if r["string_to_replace"] == "Widerøe")
    assert widerøe["type"] == "phoneme" and widerøe["alphabet"] == "ipa" and widerøe["phoneme"]
    assert set(widerøe) == {
        "type",
        "string_to_replace",
        "case_sensitive",
        "word_boundaries",
        "phoneme",
        "alphabet",
    }, "only the vendor's fields, never the file's «why»"
    # numbers and units are the vendor's text normalisation, never a rule here
    assert not any(any(ch.isdigit() for ch in term) for term in terms)


def test_a_term_is_matched_as_the_vendor_matches_it():
    assert lexicon.mentions("Inside CERN's tunnel", ["CERN"])
    assert lexicon.mentions("Rolf Widerøe drew it", ["Widerøe"])
    assert not lexicon.mentions("the cern of it", ["CERN"]), "case-sensitive"
    assert not lexicon.mentions("CERNY was there", ["CERN"]), "whole words only"


def test_the_dictionary_joins_only_words_that_need_it_and_never_the_identity():
    voice = adapter()
    # the identity read (no words): exactly what it always was
    assert "pronunciation_dictionary_locators" not in voice.request_settings()
    # words without a term: the request is unchanged
    assert "pronunciation_dictionary_locators" not in voice.request_settings("A brass chamber.")
    # words with a term: the dictionary is sent
    asked = voice.request_settings("A Norwegian, Rolf Widerøe, sketched it first.")
    assert asked["pronunciation_dictionary_locators"] == [LOCATOR]


def test_a_binding_dictionary_is_kept_and_three_locators_at_most():
    voice = adapter()
    voice.pronunciation_locators = [
        {"pronunciation_dictionary_id": f"b-{i}", "version_id": "v"} for i in range(3)
    ]
    asked = voice.request_settings("At CERN.")
    assert len(asked["pronunciation_dictionary_locators"]) == 3
    assert asked["pronunciation_dictionary_locators"][0]["pronunciation_dictionary_id"] == "b-0"
    assert voice.request_settings()["pronunciation_dictionary_locators"][0][
        "pronunciation_dictionary_id"
    ] == ("b-0"), "a character's own dictionaries are sent as before"


def test_sync_creates_once_then_replaces_only_when_the_rules_change(tmp_path):
    rules = tmp_path / "pronunciation.json"
    state = tmp_path / "state.json"
    rules.write_text(
        json.dumps(
            {
                "name": "AMN-AI narration",
                "rules": [{"type": "alias", "string_to_replace": "CERN", "alias": "Sern"}],
            }
        ),
        encoding="utf-8",
    )
    calls: list[tuple[str, str, dict]] = []

    def fake(host, method, path, headers, body=None, **kwargs):
        calls.append((method, path, json.loads(body)))
        assert headers["xi-api-key"] == "key"
        return {"id": "dict-9", "version_id": f"v-{len(calls)}"}, b"", "application/json"

    first = lexicon.sync_dictionary("key", rules_path=rules, state_path=state, transport=fake)
    assert first["changed"] and first["pronunciation_dictionary_id"] == "dict-9"
    assert calls[0][1] == "/v1/pronunciation-dictionaries/add-from-rules"
    assert calls[0][2]["rules"] == [
        {
            "type": "alias",
            "string_to_replace": "CERN",
            "case_sensitive": True,
            "word_boundaries": True,
            "alias": "Sern",
        }
    ]
    # unchanged rules: nothing is sent
    again = lexicon.sync_dictionary("key", rules_path=rules, state_path=state, transport=fake)
    assert not again["changed"] and len(calls) == 1
    # a new rule: the same dictionary, its rules replaced, a new version
    data = json.loads(rules.read_text(encoding="utf-8"))
    data["rules"].append({"type": "alias", "string_to_replace": "ATLAS", "alias": "Atlas"})
    rules.write_text(json.dumps(data), encoding="utf-8")
    changed = lexicon.sync_dictionary("key", rules_path=rules, state_path=state, transport=fake)
    assert calls[1][1] == "/v1/pronunciation-dictionaries/dict-9/set-rules"
    assert changed["version_id"] == "v-2" and changed["terms"] == ["CERN", "ATLAS"]
    # what the adapter reads
    assert lexicon.studio_dictionaries(state) == [
        {
            "pronunciation_dictionary_id": "dict-9",
            "version_id": "v-2",
            "terms": ["CERN", "ATLAS"],
        }
    ]


def test_no_synced_dictionary_sends_what_was_always_sent(tmp_path):
    assert lexicon.studio_dictionaries(tmp_path / "missing.json") == []
