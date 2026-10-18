"""Face policy regression tests: preserve legacy films while allowing new visual bibles."""

from app.media.prompt_lint import bible_face_rule, lint_still_prompt


def test_explicit_allow_overrides_legacy_no_faces_prose():
    bible = {
        "face_policy": "ALLOW",
        "continuity_rules": ["No human faces appear", "Keep lighting consistent"],
        "avoid": ["faces", "watermarks or logos"],
    }
    assert bible_face_rule(bible) is None
    findings = lint_still_prompt(
        "A cinematic portrait of a fictional scientist smiling into the camera.",
        scene=1,
        bible=bible,
    )
    assert not any(f.code in ("FORBIDDEN_FACES", "BIBLE_RULE_MISSING") for f in findings)


def test_explicit_require_allows_faces_and_legacy_remains_restricted():
    bible = {"continuity_rules": ["No human faces appear"]}
    assert bible_face_rule(bible) == "No human faces appear"
    assert bible_face_rule({**bible, "face_policy": "REQUIRE"}) is None


def test_explicit_hide_restricts_even_without_ban_in_prose():
    assert bible_face_rule({"face_policy": "HIDE"}) is not None
    assert bible_face_rule({"face_policy": "HIDE", "avoid": []}) is not None


def test_no_policy_no_prohibition():
    assert bible_face_rule({"continuity_rules": ["Faces remain consistent"]}) is None
    assert bible_face_rule({}) is None
