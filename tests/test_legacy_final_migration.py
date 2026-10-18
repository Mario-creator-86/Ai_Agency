"""Requested legacy rewrites must use Kael's finals, never the legacy compiler."""

from copy import deepcopy

import pytest
from app.media.final_prompts import EDITOR_FINAL, FinalPromptError
from app.media.prompt_agent import ShotPrompt
from app.media.scene_rewrite import MOTION, STILL, rewritten_package, shot_schema

STILL_TEXT = (
    "Three scientists stand three-quarters frontal on a single awards stage, "
    "faces and gold medals on their chests visible. Natural anatomy, warm cinematic light."
)
MOTION_TEXT = "Static camera; the three scientists smile gently, their medals remain visible."


def context():
    return {
        "scene_index": 19,
        "scene": {"scene_index": 19, "seconds": 5},
        "package": {
            "subject": "Three scientists",
            "action": "Receive gold medals",
            "camera_move": "static",
            "still_prompt": "Previously purchased still",
            "motion_prompt": "Old motion",
            "avoid": ["faces", "watermarks"],
            "continuity": "No human faces appear; Keep medal positions consistent.",
        },
        "visual_prompt": "Previously purchased still",
        "bible": {"face_policy": "ALLOW"},
        "allowed": "",
        "previous_ending": "",
        "previous_moves": [],
        "shot_type": "medium",
    }


def shot(**changes):
    return ShotPrompt(
        scene_index=19,
        camera_move="static",
        **{
            "still_prompt": STILL_TEXT,
            "motion_prompt": MOTION_TEXT,
            **changes,
        },
    )


def test_legacy_is_migrated_only_by_complete_rewrite():
    ctx = context()
    before = deepcopy(ctx)
    out = rewritten_package(ctx, shot(), STILL, {})
    assert out["prompt_format"] == EDITOR_FINAL
    assert out["still_prompt"] == STILL_TEXT
    assert out["motion_prompt"] == MOTION_TEXT
    assert ctx == before
    assert out["legacy_migration"]["from_format"] == "legacy"


@pytest.mark.parametrize("missing", ["still_prompt", "motion_prompt"])
def test_invalid_kael_answer_never_falls_back_to_python(missing):
    with pytest.raises(FinalPromptError):
        rewritten_package(context(), shot(**{missing: ""}), STILL, {})


def test_motion_migration_requires_kael_to_preserve_paid_still():
    ctx = context()
    with pytest.raises(FinalPromptError, match="still"):
        rewritten_package(ctx, shot(), MOTION, {})
    out = rewritten_package(ctx, shot(still_prompt=ctx["package"]["still_prompt"]), MOTION, {})
    assert out["still_prompt"] == ctx["package"]["still_prompt"]
    assert out["motion_prompt"] == MOTION_TEXT


def test_allow_neutralizes_only_blanket_bans_with_original_history():
    out = rewritten_package(context(), shot(), STILL, {})
    assert out["avoid"] == ["watermarks"]
    assert out["continuity"] == "Keep medal positions consistent."
    retired = out["legacy_migration"]["retired_restrictions"]
    assert {r["original"] for r in retired} == {"faces", "No human faces appear"}
    assert all(r["reason"] for r in retired)


def test_valid_artistic_back_view_is_preserved_under_allow():
    ctx = context()
    ctx["package"]["avoid"] = ["crowds", "modern clothing"]
    ctx["package"]["continuity"] = "Rear view of the scientist watching the telescope."
    out = rewritten_package(ctx, shot(), STILL, {})
    assert out["avoid"] == ctx["package"]["avoid"]
    assert out["continuity"] == ctx["package"]["continuity"]


def test_migration_metadata_is_idempotent():
    ctx = context()
    once = rewritten_package(ctx, shot(), STILL, {})
    ctx["package"] = once
    twice = rewritten_package(ctx, shot(), STILL, {})
    assert twice == once


def test_migration_schema_requires_both_finals_even_for_motion():
    schema = shot_schema(19, MOTION, editor_final=True, migrating=True)
    with pytest.raises(ValueError, match="still_prompt"):
        schema.model_validate({"motion_prompt": MOTION_TEXT, "camera_move": "static"})


def test_negative_change_invalidates_approval_identity():
    from app.media.prompt_audit import approval_digest

    package = {
        "prompt_format": EDITOR_FINAL,
        "still_prompt": STILL_TEXT,
        "motion_prompt": MOTION_TEXT,
        "negative_prompt": "logos",
    }
    assert approval_digest(package, STILL) != approval_digest(
        {**package, "negative_prompt": "faces"}, STILL
    )
    assert approval_digest(package, MOTION) != approval_digest(
        {**package, "motion_prompt": MOTION_TEXT + " "}, MOTION
    )


def test_sarah_receives_current_policy_and_final_motion_contract(monkeypatch):
    from app.media import prompt_audit

    captured = []

    def capture(*args, **kwargs):
        captured.append(args[4])
        return None, {}, None

    monkeypatch.setattr("app.agents.structured.structured_run", capture)
    ctx = context()
    ctx["package"] = rewritten_package(ctx, shot(), STILL, {})
    ctx["bible"] = {"face_policy": "ALLOW", "avoid": ["faces", "watermarks"]}
    prompt_audit._ask(
        None,
        None,
        director_id="sarah",
        layer=MOTION,
        contexts={19: ctx},
        lessons=[],
        correlation_id="c",
    )
    text = captured[0]
    assert '"face_policy": "ALLOW"' in text
    assert '"words_to_send": "' + MOTION_TEXT in text
    assert '"negative_prompt"' in text
    assert "it is the composer's and no rewrite changes it" not in text
    assert '"avoid": ["faces"' not in text


def test_director_brief_context_carries_policy_without_changing_db_plan():
    from app.media.scene_rewrite import _data

    ctx = {**context(), "title": "Supernova", "story": {}, "failures": [], "briefs": []}
    ctx["bible"] = {
        "face_policy": "ALLOW",
        "continuity_rules": ["No human faces appear", "Keep light warm"],
    }
    shown = _data(ctx)
    assert shown["visual_bible"]["face_policy"] == "ALLOW"
    assert shown["visual_bible"]["continuity_rules"] == ["Keep light warm"]
    assert ctx["package"]["avoid"] == ["faces", "watermarks"]


def test_final_validation_does_not_apply_legacy_field_coverage_rules(monkeypatch):
    from app.media import scene_rewrite

    ctx = context()
    out = rewritten_package(ctx, shot(), STILL, {})

    def forbidden(*args, **kwargs):
        pytest.fail("Legacy field coverage is not a final prompt validator")

    monkeypatch.setattr("app.media.prompt_agent.composition_issues", forbidden)
    scene_rewrite._lint_blocks(ctx, out, STILL_TEXT, layer=STILL)


def test_scene19_conflict_requires_sarah_editorial_plan():
    ctx = context()
    ctx["package"]["subject"] = "Backs of three heads with medals in front of their chests"
    with pytest.raises(FinalPromptError, match="PLAN_CONFLICT"):
        rewritten_package(ctx, shot(), STILL, {})
    ctx["editorial_visual_intent"] = STILL_TEXT
    out = rewritten_package(ctx, shot(), STILL, {})
    assert out["editorial_visual_intent"] == STILL_TEXT
    assert out["writer_visual"] == STILL_TEXT
    assert ctx["package"]["subject"].startswith("Backs")


def test_still_purchase_adds_no_reference_or_reroll_prose_to_editor_final():
    from app.media.stills_stage import _prompt, _Scene, still_negative

    package = {"prompt_format": EDITOR_FINAL, "negative_prompt": "logos"}
    assert still_negative(package, {"avoid": ["faces"]}) == "logos"
    scene = _Scene(
        index=19,
        kind="LIVE",
        words=STILL_TEXT,
        identity={},
        look_block="",
        camera_move="static",
        source="model",
        prompt_format=EDITOR_FINAL,
        reference={"canonical_name": "Scientist"},
    )
    assert _prompt(scene, "injected instruction", True, with_character=True) == STILL_TEXT


def test_selected_vendor_caps_apply_per_layer_without_truncation():
    from app.media.prompt_agent import compile_prompts, motion_prompt_for

    long_still = "A scientist with a medal. " * 80 + "One scene."
    package = {
        "prompt_format": EDITOR_FINAL,
        "still_prompt": long_still,
        "motion_prompt": MOTION_TEXT,
        "camera_move": "static",
    }
    contract = {"prompt_max_utf16": {"text_to_image": 20000, "image_to_video": 1000}}
    out = compile_prompts(package, {"face_policy": "ALLOW"}, contract=contract)
    assert out["still_prompt"] == long_still
    assert motion_prompt_for(package, "runway", contract)[0] == MOTION_TEXT
    with pytest.raises(FinalPromptError):
        compile_prompts(package, {}, contract={"prompt_max_utf16": 1000})


def test_runway_exact_mode_never_normalizes_or_shortens_reviewed_text():
    from app.providers.runway import MediaProviderError, fit_prompt

    assert (
        fit_prompt("One  scene.\nNatural light.", 1000, exact=True) == "One  scene.\nNatural light."
    )
    with pytest.raises(MediaProviderError):
        fit_prompt("A reviewed prompt exceeds this cap.", 5, exact=True)


def test_motion_request_never_prepends_the_still_for_editor_final():
    from types import SimpleNamespace

    from app.media.assembler import motion_request

    package = rewritten_package(context(), shot(), STILL, {})
    adapter = SimpleNamespace(model="seedance2_5", model_metadata={"prompt_max_chars": 1000})
    words, extra = motion_request(
        adapter, {"prompt_json": package, "visual_prompt": STILL_TEXT}, from_still=False
    )
    assert words == MOTION_TEXT
    assert extra["prompt_format"] == EDITOR_FINAL


def test_purchase_boundary_requires_current_positive_negative_and_policy(engine, monkeypatch):
    from app.media import prompt_audit

    ctx = context()
    ctx["package"] = rewritten_package(ctx, shot(), STILL, {})
    monkeypatch.setattr("app.media.scene_rewrite.scene_context", lambda *a: deepcopy(ctx))
    assert prompt_audit.purchase_approval_gaps(engine, "board", "stills", [19]) == [19]
    prompt_audit._record(
        engine,
        storyboard_id="board",
        scene=19,
        layer=STILL,
        digest=prompt_audit.approval_digest(ctx["package"], STILL, ctx["bible"]),
        verdict=prompt_audit.APPROVED,
        reason="Sarah reviewed exact text",
        run_id=None,
        correlation_id="test",
    )
    assert prompt_audit.purchase_approval_gaps(engine, "board", "stills", [19]) == []
    for key, value in (
        ("still_prompt", STILL_TEXT.replace("Three", "Three  ")),
        ("negative_prompt", "faces"),
        ("still_prompt", ""),
    ):
        before = deepcopy(ctx["package"])
        ctx["package"][key] = value
        assert prompt_audit.purchase_approval_gaps(engine, "board", "stills", [19]) == [19]
        ctx["package"] = before
    ctx["bible"]["face_policy"] = "HIDE"
    assert prompt_audit.purchase_approval_gaps(engine, "board", "stills", [19]) == [19]


def test_identical_refusals_stop_with_persistent_technical_diagnostic(engine):
    from app.media import prompt_audit
    from sqlalchemy.orm import Session

    for _ in range(2):
        prompt_audit._record(
            engine,
            storyboard_id="board",
            scene=19,
            layer=STILL,
            digest="old",
            verdict=prompt_audit.REWRITE,
            reason="Chest medals cannot be visible from behind",
            finding="Chest medals cannot be visible from behind",
            run_id=None,
            correlation_id="test",
        )
    result = {"held": []}
    assert prompt_audit._repeated_finding(
        engine,
        result=result,
        item=prompt_audit.AuditedScene(
            scene_index=19, approved=False, reason="Chest medals cannot be visible from behind"
        ),
        storyboard_id="board",
        scene=19,
        layer=STILL,
        digest="current",
        run_id=None,
        correlation_id="test",
    )
    assert result["held"][0]["developer_defect"]
    with Session(engine) as session:
        assert prompt_audit.tool_defect_on(session, "board", 19, STILL, "current")
        assert not prompt_audit.approved_for_purchase(session, "board", 19, STILL, "current")


def test_final_refusal_requires_evidence_and_responsibility():
    from app.media.prompt_audit import final_audit_schema

    schema = final_audit_schema({19: STILL_TEXT})
    raw = {
        "scenes": [
            {
                "scene_index": 19,
                "approved": False,
                "reason": "Wrong pose",
                "brief": {
                    "diagnosis": "Wrong pose",
                    "layer": "still",
                    "summary_ro": "Corecteaza orientarea",
                },
            }
        ]
    }
    with pytest.raises(ValueError):
        schema.model_validate(raw)
    raw["scenes"][0]["brief"].update(
        {
            "defect_words": "three-quarters frontal",
            "responsible": "plan",
            "change": ["Use the agreed editorial orientation"],
            "keep": ["three scientists"],
        }
    )
    assert schema.model_validate(raw)
    raw["scenes"][0]["brief"]["defect_words"] = "phrase absent from actual words"
    with pytest.raises(ValueError):
        schema.model_validate(raw)


def test_sheet_and_still_reader_preserve_the_actual_vendor_words(engine, tmp_path):
    from app.media.models import Storyboard, StoryboardScene
    from app.media.shooting_sheet import build_sheet
    from app.media.stills_stage import _read_scenes
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from test_film_costing import SEEDANCE, a_film

    board_id = a_film(engine, tmp_path, scenes=1)
    exact = STILL_TEXT.replace("Three scientists", "Three  scientists")
    with Session(engine) as session, session.begin():
        session.get(Storyboard, board_id).visual_bible_json = {"face_policy": "ALLOW"}
        row = session.scalar(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == board_id)
        )
        row.prompt_json = {
            "subject": "scientists",
            "source": "model",
            "scene_kind": "LIVE",
            "prompt_format": EDITOR_FINAL,
            "still_prompt": exact,
            "motion_prompt": MOTION_TEXT,
            "negative_prompt": "logos",
            "camera_move": "static",
        }
        row.visual_prompt = exact
    sheet = build_sheet(engine, board_id, capabilities=[SEEDANCE], read_live=False)
    assert sheet["scenes"][0]["still_prompt"] == exact
    _, scenes = _read_scenes(engine, board_id)
    assert scenes[0].words == exact
    assert scenes[0].negative == "logos"


def test_existing_owner_plan_receipt_is_shared_without_live_migration(engine, tmp_path):
    from app.media.models import Storyboard, StoryboardScene
    from app.media.scene_rewrite import _data, scene_context
    from app.services import append_event
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from test_film_costing import a_film

    board_id = a_film(engine, tmp_path, scenes=1)
    old = context()["package"]
    old["subject"] = "Backs of three heads, gold medals in front of their chests"
    with Session(engine) as session, session.begin():
        session.get(Storyboard, board_id).visual_bible_json = {"face_policy": "ALLOW"}
        row = session.scalar(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == board_id)
        )
        row.prompt_json = old
        receipt = append_event(
            session,
            "media.owner_physical_prompt_repair",
            "storyboard",
            board_id,
            1,
            {
                "scene_index": 1,
                "reason": "Owner-approved physical composition repair",
                "package": {"writer_visual": STILL_TEXT},
            },
            "test",
        )
        event_id = receipt.event_id
    ctx = scene_context(engine, board_id, 1)
    assert ctx["editorial_visual_intent"] == STILL_TEXT
    assert _data(ctx)["editorial_authority"]["event_id"] == event_id
    out = rewritten_package(ctx, shot(), STILL, {})
    assert out["editorial_visual_intent"] == STILL_TEXT
    assert out["editorial_authority"]["event_id"] == event_id
    with Session(engine) as session:
        row = session.scalar(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == board_id)
        )
        assert row.prompt_json == old
        assert row.prompt_json.get("prompt_format") is None


@pytest.mark.parametrize("valid,review", [(True, "TREATS"), (False, "TREATS"), (True, "MISSES")])
def test_transactional_migration_preserves_paid_records(
    engine, tmp_path, monkeypatch, valid, review
):
    from types import SimpleNamespace

    from app.media import scene_rewrite
    from app.media.models import StoryboardScene
    from app.models import DomainEvent
    from sqlalchemy import select, text
    from sqlalchemy.orm import Session
    from test_film_costing import a_film

    board_id = a_film(engine, tmp_path, scenes=1)
    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == board_id)
        )
        old = context()["package"]
        row.prompt_json = old
        row.visual_prompt = old["still_prompt"]

    def snapshot():
        with engine.connect() as conn:
            return {
                table: conn.execute(text("SELECT * FROM " + table)).all()
                for table in (
                    "scene_take",
                    "provider_cost_record",
                    "cloud_generation_job",
                    "publication_record",
                )
            }

    before = snapshot()
    ctx = {
        **context(),
        "scene_index": 1,
        "storyboard_id": board_id,
        "title": "Supernova",
        "story": {},
        "failures": [],
        "briefs": [],
    }
    ctx["package"] = deepcopy(old)
    monkeypatch.setattr(scene_rewrite, "agent_for_role", lambda *a: SimpleNamespace(id="kael"))
    monkeypatch.setattr("app.media.prompt_agent.prompt_lessons", lambda *a, **k: [])
    monkeypatch.setattr(scene_rewrite, "learn_from_review", lambda *a: (False, "test"))
    seen = []

    def actor(*args, **kwargs):
        if not valid:
            return None, {"status": "FAILED", "error_detail": "No valid Kael output"}, None
        payload = {
            "scene_index": 1,
            "still_prompt": STILL_TEXT,
            "motion_prompt": MOTION_TEXT,
            "camera_move": "static",
        }
        return args[7].model_validate(payload), {}, None

    monkeypatch.setattr("app.agents.structured.structured_run", actor)

    def sarah(*args, **kwargs):
        seen.append((args[5], args[6]))
        return {
            "verdict": review,
            "findings": [],
            "reason_ro": "concrete defect",
            "cause": "test",
            "lesson": "",
        }

    monkeypatch.setattr(scene_rewrite, "_reviewed", sarah)
    result = scene_rewrite.rewrite_scene(engine, object(), ctx, {"layer": STILL}, "test")
    assert result["rewritten"] is (valid and review == "TREATS")
    assert snapshot() == before
    with Session(engine) as session:
        row = session.scalar(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == board_id)
        )
        events = list(
            session.scalars(
                select(DomainEvent).where(
                    DomainEvent.aggregate_id == board_id,
                    DomainEvent.event_type == "media.prompts_rewritten",
                )
            )
        )
        if result["rewritten"]:
            assert row.prompt_json["prompt_format"] == EDITOR_FINAL
            assert row.visual_prompt == STILL_TEXT
            assert seen[0][0]["motion_prompt"] == MOTION_TEXT
            assert len(events) == 1
            assert events[0].payload["old_package"] == old
            # No migration on load/startup: only the explicit accepted rewrite writes.
            assert old.get("prompt_format") is None
        else:
            assert row.prompt_json == old
            assert not events
