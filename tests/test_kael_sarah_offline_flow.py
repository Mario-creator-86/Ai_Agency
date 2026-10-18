"""Offline contract: Kael -> Sarah review -> rewrite -> final approval, 0 media requests.

A skipped pre-purchase audit must never turn into a paid PRODUCTION request. The
model actors below are deterministic local fakes; no RunPod or network call occurs.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.media import prompt_audit
from app.media.assembler import SCENE_PROMPTS_REWRITTEN_EVENT
from app.media.prompt_audit import approved_words, prompt_digest, prompt_text
from app.media.toolchain import find_ffmpeg
from app.providers.base import GenerateResult
from app.runbook import stages
from sqlalchemy.orm import Session
from test_clip_qc_wiring import events
from test_director_rewrites_failed_scene import (
    Agents,
    a_planned_film,
    agents_say,
    scene,
    studio,  # noqa: F401 - pytest fixture
)


@pytest.mark.skipif(find_ffmpeg() is None, reason="local video fixtures need FFmpeg")
def test_kael_sarah_rewrite_then_approve_without_any_video_purchase(
    engine, tmp_path, studio
):
    """Sarah refuses old words; Kael fixes one scene; Sarah verifies and approves exact new words."""
    board = a_planned_film(engine, tmp_path)
    original = dict(scene(engine, board).prompt_json)

    class DirectorAndEditor(Agents):
        def __init__(self):
            super().__init__()
            self.audits = []

        async def generate(self, model, prompt, **kwargs):
            if '"prompt-audit"' in prompt:
                self.audits.append(prompt)
                first = len(self.audits) == 1
                return GenerateResult(
                    json.dumps({
                        "scenes": [{
                            "scene_index": 1,
                            "approved": not first,
                            "reason": (
                                "The motion is too vague to guarantee a visible moving cloud."
                                if first else "The revised movement is visible and consistent."
                            ),
                            **({
                                "brief": {
                                    "action": "rewrite",
                                    "diagnosis": "The cloud motion needs a clear direction.",
                                    "layer": "motion",
                                    "avoid": ["a frozen, almost still frame"],
                                    "keep": ["the village on the terraced slope"],
                                    "change": ["cloud rolls across the ridges from left to right"],
                                    "summary_ro": "Clarifică mișcarea norilor înainte de cumpărare.",
                                },
                            } if first else {}),
                        }],
                    }),
                    10, 40, None,
                )
            return await super().generate(model, prompt, **kwargs)

    fake = DirectorAndEditor()
    registry = agents_say(studio, fake)
    first = prompt_audit.audit_before_purchase(
        engine, registry, storyboard_id=board, step="test_shot",
        scenes=[1], correlation_id=str(uuid4()),
    )
    assert first["asked"] is True and first["approved"] == []
    assert first["rewritten"] == [1] and first["held"] == []
    assert len(fake.audits) == 1
    assert len(fake.rewrites) == 1 and len(fake.reviews) == 1
    rewritten = scene(engine, board).prompt_json
    assert rewritten["still_prompt"] == original["still_prompt"]
    assert rewritten["motion_prompt"] != original["motion_prompt"]
    (event,) = events(engine, SCENE_PROMPTS_REWRITTEN_EVENT, board)
    assert event.payload["review"]["verdict"] == "TREATS"
    with Session(engine) as session:
        old = prompt_text(original, "motion")
        assert not approved_words(session, board, 1, "motion", prompt_digest(old))

    second = prompt_audit.audit_before_purchase(
        engine, registry, storyboard_id=board, step="test_shot",
        scenes=[1], correlation_id=str(uuid4()),
    )
    assert second["approved"] == [1] and second["held"] == []
    assert second["rewritten"] == []
    assert len(fake.audits) == 2
    with Session(engine) as session:
        words = prompt_text(rewritten, "motion")
        digest = prompt_digest(
            words, exact=rewritten.get("prompt_format") == "editor_final_v1"
        )
        assert approved_words(session, board, 1, "motion", digest)
        assert not approved_words(session, board, 1, "motion", prompt_digest(words + " changed"))
    # Re-reading the same approved text does not spend LLM tokens again.
    cached = prompt_audit.audit_before_purchase(
        engine, registry, storyboard_id=board, step="test_shot",
        scenes=[1], correlation_id=str(uuid4()),
    )
    assert cached["approved"] == [1] and cached["asked"] is False
    assert len(fake.audits) == 2


@pytest.mark.parametrize("missing", ["registry", "director", "partial"])
def test_production_refuses_a_paid_step_without_every_scene_approved(monkeypatch, missing):
    """No missing actor, empty audit, or partial approval can ever reach the purchase hook."""
    from app.media import factory, fix_check, shooting_sheet

    monkeypatch.setattr(
        factory, "reference_image_adapter",
        lambda *args, **kwargs: SimpleNamespace(model="test"),
    )
    monkeypatch.setattr(
        fix_check, "restore_sent_back_scenes",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        shooting_sheet, "recover_paid_takes",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        shooting_sheet, "build_sheet",
        lambda *args, **kwargs: {
            "sheet_hash": "offline",
            "steps": {
                "stills": {"to_buy": [1, 2], "held": [], "needs_reference": []},
                "test_shot": {"to_buy": [], "held": []},
                "motion": {"to_buy": [], "held": []},
                "assemble": {"blocked": []},
            },
        },
    )

    def forbidden_purchase(*args, **kwargs):
        pytest.fail("production bought media without Sarah's approval")

    monkeypatch.setattr(shooting_sheet, "run_sheet_step", forbidden_purchase)
    audits = []
    def audit(*args, **kwargs):
        audits.append(kwargs)
        approved = [1] if missing == "partial" else []
        return {
            "approved": approved, "rewritten": [],
            "held": [], "skipped": [2] if approved else [1, 2],
            "asked": missing == "partial",
        }

    monkeypatch.setattr(prompt_audit, "audit_before_purchase", audit)
    registry = None if missing == "registry" else object()
    result = stages._walk_staircase(
        object(),
        SimpleNamespace(ffmpeg_path=None, motion_resolution="1080p"),
        registry,
        "board",
        {"image_adapter": None},
        "PRODUCTION",
        "offline-correlation",
    )
    assert result["status"] == "WAITING"
    assert result["refusal"] == prompt_audit.NEEDS_PROMPT_APPROVAL
    assert result["bought"] == []
    assert result["scenes"] == ([2] if missing == "partial" else [1, 2])
    assert len(audits) == (0 if missing == "registry" else 1)
