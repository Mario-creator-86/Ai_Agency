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
        return prompt_audit.PromptAudit(), {}, None

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
