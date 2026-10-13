"""prompt_lint: the prompts are read before a credit is priced or spent.

The Nepal film (storyboard 0000003f) is the fixture: its six as-sent prompts pasted enum
codes and hex palettes into the image model's prompt, gave every scene the same camera,
asked a photo model for a bar chart and a black screen, and never told it "no faces".
Nothing here calls a provider; the linter is pure text.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.media import prompt_lint
from app.media.prompt_lint import (
    BLOCK,
    WARN,
    Finding,
    LintScene,
    has_block,
    lint_film,
    lint_motion_prompt,
    lint_still_prompt,
)

FIXTURE = Path(__file__).parent / "fixtures" / "factual_sample" / "prompts.json"
ROMANIAN_MARKS = set("ăâîșțĂÂÎȘȚ")

GOOD_STILL = (
    "Overcast monsoon afternoon in the Kathmandu hills, soft diffuse light from the left, "
    "muted greens and slate blue, wet earth browns, 35 mm lens feel, fine film grain. "
    "A wide view of terraced rice fields stepping down a steep valley, a farmer small and "
    "distant, seen from behind, faces not visible, carrying a basket along a stone path. "
    "Vertical frame with the terraces leading the eye upward and the lower quarter calm "
    "open grass. Low cloud rests on the ridge above, light even and quiet. No text, no logo."
)
GOOD_MOTION = (
    "Slow push-in toward the terraces while low cloud drifts across the ridge and wind "
    "moves gently through the rice. Gentle, steady pace. "
    "Continuous, seamless shot. No subtitles, no on-screen text."
)


def _nepal() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _nepal_scenes() -> list[LintScene]:
    return [
        LintScene(
            scene=item["scene_index"],
            kind=item["kind_as_sent"],
            still_prompt=item["still_prompt"],
            motion_prompt=item["motion_prompt"],
        )
        for item in _nepal()["scenes"]
    ]


def _codes(findings: list[Finding]) -> set[str]:
    return {finding.code for finding in findings}


def _by_code(findings: list[Finding], code: str) -> list[Finding]:
    return [finding for finding in findings if finding.code == code]


# --- the six as-sent Nepal prompts ---------------------------------------------------------


@pytest.mark.parametrize("index", range(6))
def test_every_nepal_prompt_blocks_on_enum_and_hex(index: int) -> None:
    data = _nepal()
    scene = data["scenes"][index]
    findings = lint_still_prompt(
        scene["still_prompt"], scene=scene["scene_index"], bible=data["visual_bible"]
    )
    enum = _by_code(findings, "ENUM_CODE")
    hexes = _by_code(findings, "HEX_CODE")
    assert enum and all(f.severity == BLOCK for f in enum)
    assert hexes and all(f.severity == BLOCK for f in hexes)
    assert len(findings) >= 3
    assert enum[0].evidence in scene["still_prompt"]
    assert hexes[0].evidence.startswith("#")


def test_nepal_chart_and_black_screen_are_kind_mismatches() -> None:
    data = _nepal()
    for scene in data["scenes"]:
        findings = lint_still_prompt(
            scene["still_prompt"], scene=scene["scene_index"], bible=data["visual_bible"]
        )
        mismatch = _by_code(findings, "KIND_MISMATCH")
        if scene["scene_index"] in (5, 6):
            assert mismatch and mismatch[0].severity == BLOCK
            assert mismatch[0].evidence.lower() in scene["still_prompt"].lower()
        else:
            assert not mismatch, scene["scene_index"]


def test_nepal_every_scene_misses_the_no_faces_rule() -> None:
    data = _nepal()
    rule = next(r for r in data["visual_bible"]["continuity_rules"] if "No human faces" in r)
    for scene in data["scenes"]:
        findings = lint_still_prompt(
            scene["still_prompt"], scene=scene["scene_index"], bible=data["visual_bible"]
        )
        missing = _by_code(findings, "BIBLE_RULE_MISSING")
        faces = [f for f in missing if "No human faces" in f.evidence]
        assert faces, scene["scene_index"]
        assert faces[0].evidence == rule
        assert faces[0].severity == BLOCK


def test_nepal_people_scenes_break_forbidden_faces() -> None:
    data = _nepal()
    blocked = set()
    for scene in data["scenes"]:
        findings = lint_still_prompt(
            scene["still_prompt"], scene=scene["scene_index"], bible=data["visual_bible"]
        )
        if _by_code(findings, "FORBIDDEN_FACES"):
            blocked.add(scene["scene_index"])
    # scene 3: "people salvaging belongings"; scene 4: "A farmer working".
    assert blocked == {3, 4}


def test_nepal_template_labels_and_avoid_list_block() -> None:
    data = _nepal()
    scene = data["scenes"][0]
    findings = lint_still_prompt(scene["still_prompt"], scene=1, bible=data["visual_bible"])
    codes = _codes(findings)
    assert "TEMPLATE_LABEL" in codes
    assert "AVOID_LIST" in codes
    label = _by_code(findings, "TEMPLATE_LABEL")[0]
    assert label.evidence in scene["still_prompt"]


def test_lint_film_on_nepal_finds_the_same_camera_everywhere() -> None:
    data = _nepal()
    findings = lint_film(_nepal_scenes(), bible=data["visual_bible"])
    same = _by_code(findings, "SAME_CAMERA_EVERY_SCENE")
    assert same and same[0].severity == BLOCK
    assert same[0].scene is None
    assert has_block(findings)
    # The per-scene findings are part of the film's list too.
    assert {f.scene for f in _by_code(findings, "ENUM_CODE")} == {1, 2, 3, 4, 5, 6}
    # The same text went to image and motion: every scene says so.
    assert {f.scene for f in _by_code(findings, "MOTION_EQUALS_STILL")} == {1, 2, 3, 4, 5, 6}


# --- faces ---------------------------------------------------------------------------------

FACELESS_BIBLE = {"continuity_rules": ["No human faces appear"], "avoid": []}


def test_farmer_from_behind_passes_forbidden_faces() -> None:
    findings = lint_still_prompt(
        "a farmer seen from behind, distant, indistinct", scene=1, bible=FACELESS_BIBLE
    )
    assert not _by_code(findings, "FORBIDDEN_FACES")
    assert not _by_code(findings, "BIBLE_RULE_MISSING")


def test_a_scene_of_objects_carries_the_face_rule_with_the_compilers_positive_sentence() -> None:
    """2026-10-12: «There are no people in the frame.» drew people (the Director's briefs
    asked five times for it to go); the compiler now says what is there, and the linter reads
    that sentence as the rule kept."""
    from app.media.prompt_agent import NO_PEOPLE_SENTENCE

    assert "people" not in NO_PEOPLE_SENTENCE.lower()
    findings = lint_still_prompt(
        f"A brass ring on a wooden desk under one lamp, 50 mm lens. {NO_PEOPLE_SENTENCE}",
        scene=1,
        bible=FACELESS_BIBLE,
    )
    assert not _by_code(findings, "BIBLE_RULE_MISSING")
    assert not _by_code(findings, "FORBIDDEN_FACES")
    # The older sentence still counts for the prompts written before.
    old = lint_still_prompt(
        "A brass ring on a wooden desk under one lamp. There are no people in the frame.",
        scene=1,
        bible=FACELESS_BIBLE,
    )
    assert not _by_code(old, "BIBLE_RULE_MISSING")


def test_farmer_face_visible_fails_forbidden_faces() -> None:
    findings = lint_still_prompt("a farmer, face visible", scene=1, bible=FACELESS_BIBLE)
    faces = _by_code(findings, "FORBIDDEN_FACES")
    assert faces and faces[0].severity == BLOCK
    assert faces[0].evidence in "a farmer, face visible"


def test_faces_allowed_when_the_bible_does_not_forbid_them() -> None:
    findings = lint_still_prompt("a farmer, face visible", scene=1, bible={})
    assert not _by_code(findings, "FORBIDDEN_FACES")
    assert not _by_code(findings, "BIBLE_RULE_MISSING")


def test_good_still_prompt_has_no_block() -> None:
    findings = lint_still_prompt(GOOD_STILL, scene=1, bible=FACELESS_BIBLE)
    assert not has_block(findings), findings


# --- motion prompts ------------------------------------------------------------------------


def test_motion_equal_to_still_is_blocked() -> None:
    findings = lint_motion_prompt(GOOD_STILL, scene=2, still_prompt=GOOD_STILL)
    same = _by_code(findings, "MOTION_EQUALS_STILL")
    assert same and same[0].severity == BLOCK


def test_motion_contained_in_still_is_blocked() -> None:
    part = "A wide view of terraced rice fields stepping down a steep valley"
    findings = lint_motion_prompt(part, scene=2, still_prompt=GOOD_STILL)
    assert _by_code(findings, "MOTION_EQUALS_STILL")


def test_good_motion_prompt_has_no_block() -> None:
    findings = lint_motion_prompt(
        GOOD_MOTION, scene=1, still_prompt=GOOD_STILL, model_id="seedance2_5"
    )
    assert not has_block(findings), findings


def test_zero_camera_moves_is_blocked() -> None:
    text = GOOD_MOTION.replace("Slow push-in toward the terraces while", "As")
    findings = lint_motion_prompt(text, scene=3, still_prompt=GOOD_STILL)
    count = _by_code(findings, "CAMERA_COUNT")
    assert count and count[0].severity == BLOCK


def test_two_camera_moves_is_blocked() -> None:
    text = GOOD_MOTION.replace("Slow push-in", "Slow push-in and a slow pan left")
    findings = lint_motion_prompt(text, scene=3, still_prompt=GOOD_STILL)
    count = _by_code(findings, "CAMERA_COUNT")
    assert count and count[0].severity == BLOCK
    assert "slow pan left" in count[0].evidence.lower()


def test_then_chain_on_seedance_is_blocked() -> None:
    text = GOOD_MOTION.replace(
        "Gentle, steady pace.", "Gentle, steady pace, then the cloud clears."
    )
    findings = lint_motion_prompt(text, scene=4, still_prompt=GOOD_STILL, model_id="seedance2")
    chain = _by_code(findings, "THEN_CHAIN")
    assert chain and chain[0].severity == BLOCK
    assert chain[0].evidence.lower() == "then"
    # veo reads a sequence well; the same text is not a chain finding there.
    veo = lint_motion_prompt(text, scene=4, still_prompt=GOOD_STILL, model_id="veo3.1")
    assert not _by_code(veo, "THEN_CHAIN")


def test_veo_prompt_text_carries_no_negation() -> None:
    findings = lint_motion_prompt(
        GOOD_MOTION, scene=1, still_prompt=GOOD_STILL, model_id="veo3.1_fast"
    )
    neg = _by_code(findings, "NEGATION_IN_PROMPT")
    assert neg and neg[0].severity == BLOCK
    veo_text = GOOD_MOTION.replace(" No subtitles, no on-screen text.", "")
    clean = lint_motion_prompt(veo_text, scene=1, still_prompt=GOOD_STILL, model_id="veo3.1_fast")
    assert not has_block(clean), clean


def test_motion_without_closing_line_is_flagged() -> None:
    text = GOOD_MOTION.replace(" Continuous, seamless shot. No subtitles, no on-screen text.", "")
    findings = lint_motion_prompt(text, scene=1, still_prompt=GOOD_STILL, model_id="seedance2_5")
    assert _by_code(findings, "MOTION_CLOSING")


# --- quoted text and caps ------------------------------------------------------------------


def test_quoted_string_in_live_still_is_blocked() -> None:
    text = GOOD_STILL.replace("carrying a basket", 'carrying a sign reading "HELP"')
    findings = lint_still_prompt(text, scene=1, bible=FACELESS_BIBLE)
    quoted = _by_code(findings, "QUOTED_TEXT")
    assert quoted and quoted[0].severity == BLOCK
    assert quoted[0].evidence == '"HELP"'


def test_apostrophe_is_not_a_quoted_string() -> None:
    text = GOOD_STILL.replace("A wide view", "Nepal's wide view")
    assert not _by_code(lint_still_prompt(text, scene=1, bible=FACELESS_BIBLE), "QUOTED_TEXT")


def test_over_the_contract_cap_is_flagged_and_never_sliced() -> None:
    text = GOOD_STILL
    cap = 200
    findings = lint_still_prompt(
        text, scene=1, bible=FACELESS_BIBLE, contract={"prompt_max_utf16": cap}
    )
    over = _by_code(findings, "OVER_CAP")
    assert over and over[0].severity == BLOCK
    # The evidence is the part that does not fit, the prompt itself is left whole.
    assert over[0].evidence == text[cap:]
    assert text == GOOD_STILL


def test_cap_counts_utf16_units() -> None:
    # One astral character is two UTF-16 units: 499 of them are 998 units, 501 are 1002.
    assert prompt_lint.utf16_units("\U0001f600" * 499) == 998
    assert not _by_code(
        lint_motion_prompt("\U0001f600" * 499, scene=1, model_id="veo3.1"), "OVER_CAP"
    )
    assert _by_code(lint_motion_prompt("\U0001f600" * 501, scene=1, model_id="veo3.1"), "OVER_CAP")


# --- film-level camera language ------------------------------------------------------------


def _live(scene: int, move: str, size: str) -> LintScene:
    return LintScene(
        scene=scene,
        kind="LIVE",
        still_prompt=GOOD_STILL.replace("A wide view", f"A {size} view"),
        motion_prompt=GOOD_MOTION.replace("Slow push-in", move.capitalize()),
    )


def test_three_consecutive_same_move_warns() -> None:
    scenes = [
        _live(1, "slow push-in", "wide"),
        _live(2, "slow push-in", "medium"),
        _live(3, "slow push-in", "wide"),
        _live(4, "slow pan left", "medium"),
    ]
    findings = lint_film(scenes, bible=FACELESS_BIBLE)
    run = _by_code(findings, "SAME_CAMERA_RUN")
    assert run and run[0].severity == WARN
    assert not _by_code(findings, "SAME_CAMERA_EVERY_SCENE")


def test_varied_camera_language_is_clean() -> None:
    scenes = [
        _live(1, "slow push-in", "wide"),
        _live(2, "slow pan left", "medium"),
        _live(3, "tilt up", "wide"),
        LintScene(scene=4, kind="DATA_CARD"),
        _live(5, "slow pull-back", "detail"),
    ]
    findings = lint_film(scenes, bible=FACELESS_BIBLE)
    assert not _by_code(findings, "SAME_CAMERA_RUN")
    assert not _by_code(findings, "SAME_CAMERA_EVERY_SCENE")


def test_card_scene_with_a_paid_prompt_is_blocked() -> None:
    findings = lint_film(
        [LintScene(scene=5, kind="DATA_CARD", still_prompt="Two vertical bars side by side")],
        bible=FACELESS_BIBLE,
    )
    paid = _by_code(findings, "CARD_HAS_PROMPT")
    assert paid and paid[0].severity == BLOCK and paid[0].scene == 5


# --- the shape of every finding ------------------------------------------------------------


def test_every_finding_carries_code_severity_scene_evidence_and_romanian() -> None:
    data = _nepal()
    findings = lint_film(_nepal_scenes(), bible=data["visual_bible"])
    extra = lint_motion_prompt(
        "Slow push-in and slow orbit, then fast pan right.",
        scene=7,
        still_prompt="",
        model_id="seedance2",
    )
    findings += extra
    assert findings
    for finding in findings:
        assert finding.code and finding.code.upper() == finding.code
        assert finding.severity in (BLOCK, WARN)
        assert finding.scene is None or isinstance(finding.scene, int)
        assert finding.evidence.strip()
        assert finding.message_ro.strip()
        assert ROMANIAN_MARKS & set(finding.message_ro), finding.message_ro
        assert "„" in finding.message_ro and "”" in finding.message_ro
        as_dict = finding.as_dict()
        assert set(as_dict) == {"code", "severity", "scene", "evidence", "message_ro"}
    scene_findings = [f for f in findings if f.scene in range(1, 7)]
    by_scene = {item["scene_index"]: item for item in data["scenes"]}
    for finding in scene_findings:
        if finding.code in {"BIBLE_RULE_MISSING", "CAMERA_COUNT", "MOTION_CLOSING"}:
            continue
        prompt = by_scene[finding.scene]["still_prompt"]
        assert finding.evidence.lower() in prompt.lower(), finding


def test_codes_outside_the_nepal_set_are_told_in_romanian_too() -> None:
    crowded = GOOD_STILL.replace("No text, no logo.", "No text, no logo, no birds, no roads.")
    findings = [
        *lint_still_prompt(
            GOOD_STILL.replace("carrying a basket", 'carrying a sign reading "HELP"'),
            scene=1,
            bible=FACELESS_BIBLE,
        ),
        *lint_still_prompt(GOOD_STILL, scene=1, contract={"prompt_max_utf16": 200}),
        *lint_still_prompt(crowded, scene=1, bible=FACELESS_BIBLE),
        *lint_still_prompt("a close-up of her face, distant hills", scene=2, bible=FACELESS_BIBLE),
        *lint_motion_prompt(GOOD_STILL[:200] + " slow push-in", scene=3, still_prompt=GOOD_STILL),
        *lint_film(
            [
                LintScene(scene=1, kind="LIVE"),
                LintScene(scene=2, kind="POSTER"),
                LintScene(scene=3, kind="BLACK", motion_prompt="Slow fade to black."),
            ]
        ),
        *lint_film(
            [
                _live(1, "slow push-in", "wide"),
                _live(2, "slow push-in", "medium"),
                _live(3, "slow push-in", "wide"),
                _live(4, "tilt up", "medium"),
            ],
            bible=FACELESS_BIBLE,
        ),
    ]
    codes = _codes(findings)
    for code in (
        "QUOTED_TEXT",
        "OVER_CAP",
        "TOO_MANY_EXCLUSIONS",
        "FORBIDDEN_FACES",
        "MOTION_REDESCRIBES",
        "PROMPT_MISSING",
        "KIND_UNKNOWN",
        "CARD_HAS_PROMPT",
        "SAME_CAMERA_RUN",
    ):
        assert code in codes, code
    for finding in findings:
        assert finding.evidence.strip()
        assert ROMANIAN_MARKS & set(finding.message_ro), finding
        assert "„" in finding.message_ro and "”" in finding.message_ro, finding


def test_explicit_face_close_up_blocks_even_beside_a_distant_word() -> None:
    findings = lint_still_prompt(
        "a close-up of her face, distant hills", scene=2, bible=FACELESS_BIBLE
    )
    faces = _by_code(findings, "FORBIDDEN_FACES")
    assert faces and faces[0].evidence == "close-up of her face"
    assert _by_code(findings, "BIBLE_RULE_MISSING")


def test_an_empty_landscape_that_says_no_people_carries_the_rule() -> None:
    text = "An empty terraced valley under low cloud, no people, soft overcast light."
    findings = lint_still_prompt(text, scene=1, bible=FACELESS_BIBLE)
    assert not _by_code(findings, "BIBLE_RULE_MISSING")
    assert not _by_code(findings, "FORBIDDEN_FACES")


def test_the_avoid_list_face_rule_is_read_but_morphing_is_not_a_face_ban() -> None:
    assert prompt_lint.bible_face_rule({"avoid": ["human faces"]}) == "human faces"
    assert prompt_lint.bible_face_rule({"avoid": ["faces or bodies morphing mid-shot"]}) is None
    assert prompt_lint.bible_face_rule(None) is None


def test_kind_phrases_force_the_right_kind() -> None:
    assert prompt_lint.classify_kind_phrase("a bar chart of aid") == ("DATA_CARD", "bar chart")
    for phrase, kind in (
        ("only 83% arrived", "DATA_CARD"),
        ("the image fades to black", "BLACK"),
        ("a title card: Nepal", "TITLE_CARD"),
    ):
        forced = prompt_lint.classify_kind_phrase(phrase)
        assert forced is not None and forced[0] == kind, (phrase, forced)
    assert prompt_lint.classify_kind_phrase(GOOD_STILL) is None
    # A card scene is never linted as a photograph.
    assert not lint_still_prompt("", scene=5, kind="DATA_CARD")


def test_contract_cap_is_read_per_task_and_defaults_to_runway_1000() -> None:
    assert prompt_lint.prompt_cap(None, "motion") == 1000
    per_task = {"prompt_max": {"text_to_image": 300, "image_to_video": 1000}}
    assert prompt_lint.prompt_cap(per_task, "still") == 300
    assert prompt_lint.prompt_cap(per_task, "motion") == 1000
    assert prompt_lint.prompt_cap({"prompt_max": True}, "still") == 1000


def test_require_no_block_stops_pricing_with_a_romanian_reason() -> None:
    data = _nepal()
    findings = lint_film(_nepal_scenes(), bible=data["visual_bible"])
    with pytest.raises(prompt_lint.PromptLintBlocked) as caught:
        prompt_lint.require_no_block(findings)
    assert caught.value.findings and all(f.severity == BLOCK for f in caught.value.findings)
    assert "blocaje" in str(caught.value)
    prompt_lint.require_no_block(
        lint_motion_prompt(GOOD_MOTION, scene=1, still_prompt=GOOD_STILL, model_id="seedance2_5")
    )


def test_prompt_lint_is_pure_text() -> None:
    source = Path(prompt_lint.__file__).read_text(encoding="utf-8")
    for forbidden in ("sqlalchemy", "httpx", "providers", "import requests", "sqlite"):
        assert forbidden not in source, forbidden


# --- a still is one moment (film babcf272, 2026-10-09) ---------------------------------------

#: Scene 5's still prompt as it was stored and bought: three moments, drawn as three panels.
BABCF272_SCENE_5 = (
    "Documentary photograph, natural and unposed, true-to-life colour. The film exists in two "
    "interconnected spaces: the, The setting is entirely, None, The environment is a "
    "controlled. In the tunnel, lighting is practical and industrial. Muted natural palette of "
    "A core palette of deep charcoal and slate. Natural 35mm lens perspective with gentle depth "
    "of field, fine film grain and crisp detail. Wide establishing shot, 85mm lens. Glowing "
    "white spheres clustered and holding together as atoms, then the empty accelerator tunnel "
    "from scene 1. First the near-black void of scenes 2 and 3, then the identical tunnel from "
    "scene 1. Vertical 9:16 frame, main subject in the upper two thirds, lower quarter calm and "
    "uncluttered. No text, no logo."
)


def test_the_babcf272_scene_5_still_warns_of_a_sequence_and_a_scene_reference() -> None:
    findings = lint_still_prompt(BABCF272_SCENE_5, scene=5)
    sequence = _by_code(findings, "STILL_SEQUENCE")
    pointer = _by_code(findings, "SCENE_REFERENCE")
    assert len(sequence) == 1 and sequence[0].evidence == "then"
    assert len(pointer) == 1 and pointer[0].evidence == "scene 1"
    for finding in (*sequence, *pointer):
        # WARN, never BLOCK: a BLOCK on a stored prompt would make the sheet LINT_BLOCKED and
        # its repair would rewrite every scene's package, orphaning the takes already bought.
        assert finding.severity == WARN
        assert finding.scene == 5
        assert ROMANIAN_MARKS & set(finding.message_ro)
        assert f"„{finding.evidence}”" in finding.message_ro
    assert "un singur moment" in sequence[0].message_ro and "„apoi”" in sequence[0].message_ro
    assert "„scena N”" in pointer[0].message_ro
    assert not has_block(_by_code(findings, "STILL_SEQUENCE") + pointer)


@pytest.mark.parametrize(
    ("text", "evidence"),
    [
        ("A quiet street at dawn. Later, a crowd fills it.", "Later"),
        ("Snow on the ridge, eventually melting into the valley.", "eventually"),
        ("The glow softens and dissolves into the tunnel view.", "dissolves into"),
        ("A frozen lake. Moments later the ice cracks.", "Moments later"),
        ("The harbour at dusk. At the end of the shot, the boat is gone.", "At the end"),
    ],
)
def test_later_moments_in_a_still_are_a_sequence(text: str, evidence: str) -> None:
    findings = _by_code(lint_still_prompt(text, scene=1), "STILL_SEQUENCE")
    assert findings and findings[0].evidence == evidence, findings


@pytest.mark.parametrize(
    "text",
    [
        GOOD_STILL,
        "A door at the end of the corridor, first light on the wall.",
        "Hills fading into the distance under low cloud.",
        "The forest gives way to rocky slopes above the village.",
    ],
)
def test_one_moment_described_is_not_a_sequence(text: str) -> None:
    codes = _codes(lint_still_prompt(text, scene=1))
    assert "STILL_SEQUENCE" not in codes and "SCENE_REFERENCE" not in codes


def test_any_pointer_at_another_scene_is_named() -> None:
    for text, evidence in (
        ("The same void as scenes 2 and 3.", "scenes 2 and 3"),
        ("The tunnel, as in scene four.", "scene four"),
        ("The street from the previous scene.", "previous scene"),
    ):
        found = _by_code(lint_still_prompt(text, scene=4), "SCENE_REFERENCE")
        assert found and found[0].evidence == evidence, (text, found)
    # The motion prompt is not a picture: the still rule does not read it.
    assert not _by_code(
        lint_motion_prompt(GOOD_MOTION, scene=1, model_id="seedance2_5"), "STILL_SEQUENCE"
    )


@pytest.mark.parametrize(
    ("text", "evidence"),
    [
        ("Split screen of the dense forest and the cleared land.", "Split screen"),
        ("Before: a dense rainforest canopy. After: a bare clearing of stumps.", "Before:"),
        ("Top half: a glacier in 1990. Bottom half: bare rock today.", "Top half:"),
        ("A triptych of the valley at dawn.", "triptych"),
        ("The street before and after the flood.", "before and after"),
        ("The two glaciers shown side by side.", "shown side by side"),
    ],
)
def test_a_still_that_asks_for_several_pictures_in_one_is_named(text: str, evidence: str) -> None:
    found = _by_code(lint_still_prompt(text, scene=3), "STILL_PANELS")
    assert found and found[0].evidence == evidence, found
    assert found[0].severity == WARN and found[0].scene == 3
    assert ROMANIAN_MARKS & set(found[0].message_ro)
    assert f"„{evidence}”" in found[0].message_ro


@pytest.mark.parametrize(
    "text",
    [
        GOOD_STILL,
        "Two boats moored side by side in the harbour.",
        "Solar panels on a roof, a control panel glowing in the dark.",
        "Rainforest replaced by palm oil plantations.",
        "An old textile mill transformed into a museum.",
        "Wind turbines marking the transition to renewable energy.",
        "A mother elephant followed by her calf, crossing the river.",
        "The city has grown since then. A chair next to the window.",
        "The opening shot shows a glacier at dawn.",
    ],
)
def test_one_present_picture_is_neither_panels_nor_a_sequence(text: str) -> None:
    codes = _codes(lint_still_prompt(text, scene=1))
    assert not codes & {"STILL_PANELS", "STILL_SEQUENCE", "SCENE_REFERENCE"}, codes
