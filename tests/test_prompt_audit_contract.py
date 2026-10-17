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
    if markings:
        assert markings_note(markings) in prompt
    else:
        assert "The plan asks for a ruler:" not in prompt


def test_old_contradictory_audit_cannot_hold_but_new_refusal_still_can(engine):
    payload = {
        "scene_index": 15,
        "layer": "still",
        "digest": "d" * 64,
        "verdict": prompt_audit.TOOL_DEFECT,
        "guard": prompt_audit.GUARD_VERSION,
        "instructions": "director_prompt_audit-v5",
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
