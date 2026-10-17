"""Offline regressions for the Supernova pre-purchase audit deadlock."""

import pytest
from app.media import prompt_audit
from app.media.markings import markings_note
from app.services import append_event
from sqlalchemy.orm import Session


@pytest.mark.parametrize("markings", [(), ("ruler",), ("thermometer", "gauge")])
def test_audit_explains_instrument_markings_and_still_framing(monkeypatch, markings):
    calls = []

    def capture(*args, **kwargs):
        calls.append(args[4])
        return (
            prompt_audit.PromptAudit(
                scenes=[prompt_audit.AuditedScene(scene_index=34, approved=False)]
            ),
            {},
            None,
        )

    monkeypatch.setattr("app.agents.structured.structured_run", capture)
    context = {
        "storyboard_id": "board",
        "package": {
            "still_prompt": "Wide establishing shot, 85mm lens. A cool blue-white smudge.",
            "motion_prompt": "Dolly in toward the smudge.",
        },
        "markings": markings,
    }
    parsed, _ = prompt_audit._ask(
        None,
        None,
        director_id="director",
        layer="still",
        contexts={34: context},
        lessons=["Keep every camera word out of the picture's words."],
        correlation_id="c",
    )
    assert parsed is not None
    prompt = calls[0]
    assert "Shot size, lens, angle and framing distance are valid" in prompt
    assert "every camera word out of the picture's words by rule" not in prompt
    assert "must not override these rules" in prompt
    assert "wherever they occur in words_to_send" in prompt
    assert "A picture has no camera move" in prompt
    assert "no text, subtitle, caption, logo or" in prompt
    assert "markings_policy" in prompt
    assert "still framing contract takes precedence" in prompt
    if markings:
        assert markings_note(markings) in prompt
    else:
        assert "The plan asks for a ruler:" not in prompt


@pytest.mark.parametrize(
    "old_version",
    ["director_prompt_audit-v5", "director_prompt_audit-v6", "director_prompt_audit-v7"],
)
def test_old_contradictory_audit_cannot_hold_but_new_refusal_still_can(engine, old_version):
    payload = {
        "scene_index": 15,
        "layer": "still",
        "digest": "d" * 64,
        "verdict": prompt_audit.TOOL_DEFECT,
        "guard": prompt_audit.GUARD_VERSION,
        "instructions": old_version,
        "reason": "Ruler markings are forbidden",
    }
    with Session(engine) as session, session.begin():
        append_event(session, prompt_audit.AUDIT_EVENT, "storyboard", "board", 1, payload, "c")
    with Session(engine) as session:
        assert prompt_audit.tool_defect_on(session, "board", 15, "still", payload["digest"]) is None
        assert not prompt_audit.approved_words(session, "board", 15, "still", payload["digest"])
    with Session(engine) as session, session.begin():
        append_event(
            session,
            prompt_audit.AUDIT_EVENT,
            "storyboard",
            "board",
            2,
            {**payload, "instructions": prompt_audit.AUDIT_TEMPLATE},
            "c",
        )
    with Session(engine) as session:
        assert prompt_audit.tool_defect_on(session, "board", 15, "still", payload["digest"])
        assert not prompt_audit.approved_words(session, "board", 15, "still", payload["digest"])


@pytest.mark.parametrize("text", ["{}", '{"scenes": []}', '{"scene_index": 15, "approved": true}'])
def test_an_empty_or_nested_audit_is_refused_for_a_corrected_answer(text):
    from app.agents.identity import read_structured

    parsed, reason = read_structured(text, prompt_audit.PromptAudit)
    assert parsed is None
    assert reason is not None and "scenes" in reason


def test_specific_unmarked_ruler_does_not_get_automatic_graduations():
    from app.media.markings import planned_markings
    from app.media.prompt_agent import compile_prompts

    package = {
        "subject": "A glowing ruler stretching between galaxies",
        "environment": "void black deep space",
        "camera": "Medium shot, 50mm lens",
        "avoid": ["numbers or labels on the ruler"],
    }
    assert planned_markings(package["subject"], excluded=package["avoid"]) == ()
    assert "own scale and markings" not in compile_prompts(package, {})["still_prompt"]
    assert planned_markings("a thermometer", excluded=["on-screen text or captions"]) == (
        "thermometer",
    )


def test_frame_size_does_not_come_from_later_subject_adjectives():
    from app.media.prompt_agent import shot_frame

    size, frame = shot_frame(
        "Medium shot, vertical frame, the galaxy wide with the smudge small in the upper two thirds"
    )
    assert size == "medium" and frame.startswith("Medium shot")


def test_malformed_audit_gets_one_corrective_attempt_without_inventing_approval(monkeypatch):
    from app.agents import structured

    calls = []

    def answer(*args, **kwargs):
        calls.append(args[4])
        text = (
            '{"scenes": [{"scene_index": 15, "approved": false}}]}'
            if len(calls) == 1
            else '{"scenes": [{"scene_index": 15, "approved": false, "reason": "Fix the bar"}]}'
        )
        return {"status": "SUCCEEDED", "output_text": text}

    monkeypatch.setattr(structured, "_model_name", lambda *args: "model")
    monkeypatch.setattr(structured, "run_agent_task", answer)
    parsed, first, second = structured.structured_run(
        None,
        None,
        "director",
        "director_prompt_audit",
        "Judge scene 15",
        "v",
        "c",
        prompt_audit.PromptAudit,
        "",
        max_tokens=2400,
    )
    assert len(calls) == 2 and second is not None
    assert "scenes" in first["refusal"] and "previous answer was refused" in calls[1]
    assert parsed is not None and parsed.scenes[0].approved is False


@pytest.mark.parametrize("operation", ["writer", "review"])
@pytest.mark.parametrize("layer", ["still", "motion"])
def test_still_writer_and_review_receive_the_same_contract_over_obsolete_lessons(
    engine, monkeypatch, operation, layer
):
    from types import SimpleNamespace

    from app.media import prompt_agent, scene_rewrite

    class Captured(Exception):
        pass

    calls = []

    def capture(*args, **kwargs):
        calls.append(args[5] if operation == "writer" else args[4])
        raise Captured

    monkeypatch.setattr(scene_rewrite, "agent_for_role", lambda *args: SimpleNamespace(id="d"))
    monkeypatch.setattr(
        prompt_agent,
        "prompt_lessons",
        lambda *a, **k: ["Keep every camera word out of the picture's words. (unverified)"],
    )
    monkeypatch.setattr(scene_rewrite, "layer_terms", lambda *a, **k: {"fields_he_may_change": []})
    monkeypatch.setattr(scene_rewrite, "_data", lambda *a, **k: {})
    monkeypatch.setattr(scene_rewrite, "lock_texts", lambda *a, **k: [])
    monkeypatch.setattr(scene_rewrite, "review_schema", lambda *a, **k: prompt_audit.PromptAudit)
    monkeypatch.setattr(scene_rewrite, "_editor_rewrite", capture)
    monkeypatch.setattr("app.agents.structured.structured_run", capture)
    context = {
        "scene_index": 34,
        "title": "Supernova",
        "bible": {},
        "package": {"still_prompt": "Wide establishing shot."},
        "visual_prompt": "Wide establishing shot.",
    }
    brief = {"layer": layer, "diagnosis": "Wrong frame size", "source": "prompt_audit"}
    with pytest.raises(Captured):
        if operation == "writer":
            scene_rewrite.rewrite_scene(engine, object(), context, brief, "c")
        else:
            scene_rewrite.review_rewrite(
                engine, object(), context, brief, layer, {}, "Medium shot.", "c"
            )
    assert ("still framing contract takes precedence" in calls[0]) == (layer == "still")
    assert ("Judge whether the framing matches the requested scene" in calls[0]) == (
        layer == "still"
    )


@pytest.mark.parametrize("punctuation", ["sentences", "commas"])
def test_pasted_compiler_style_and_frame_are_said_once(punctuation):
    from app.media.prompt_agent import compile_prompts

    package = {
        "subject": "A faint cool blue-white smudge beside a spiral arm",
        "environment": "Void black deep space",
        "lighting": "cold light",
        "camera": "Medium shot, 85mm lens",
    }
    clean = compile_prompts(package, {})["still_prompt"]
    style = clean.split("Medium shot, 85mm lens.", 1)[0]
    if punctuation == "commas":
        style = style.replace(". ", ", ")
    polluted = {**package, "subject": style + package["subject"] + ". Medium shot, 85mm lens."}
    result = compile_prompts(polluted, {})["still_prompt"]
    assert result.count("Documentary photograph") == 1
    assert result.count("Medium shot, 85mm lens") == 1
    assert "faint cool blue-white smudge beside a spiral arm" in result


def test_removing_tempo_keeps_visible_glow_instead_of_dropping_the_clause():
    from app.media.prompt_agent import _clauses_of
    from app.media.prompt_lint import without_tempo

    assert without_tempo("the smudge glowing faintly and steadily") == "the smudge glowing faintly"
    assert _clauses_of("the smudge glowing faintly and steadily") == ["the smudge glowing faintly"]
    assert without_tempo("a steady blue glow beside the spiral arm") == (
        "a steady blue glow beside the spiral arm"
    )
