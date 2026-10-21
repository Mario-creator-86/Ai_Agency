"""MODEL_CATALOG: the per-scene cheapest-capable choice works on the Owner's REAL catalogue.

Before this, nothing filled the research fields of the Runway models (need_quality, camera
moves) and the only quality scores in the catalogue were a steward's unsourced guesses, so the
planner could not tell which model films people or water well. config/film_models.json now
holds what the vendors document and what the Artificial Analysis silent boards measured
(2026-10-01), with its sources; production_policy reads a model's own catalogue row first
when that row is measured or sourced, and the file otherwise. The Owner's allowed set, the
HERO threshold and the premium reference live in the same file and are his.

Every model id, ratio and duration below is the real Runway catalogue as the studio's copy of
the database recorded it (image_to_video models, 2026-09-26). No provider is called.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.media import cost_plan
from app.media import production_policy as policy
from app.media.production_policy import (
    SCENE_NEEDS,
    load_film_models,
    need_from_scene,
    plan_scene_models,
    required_quality,
    scene_model_capabilities,
)
from app.media.prompt_lint import CAMERA_MOVES

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "config" / "film_models.json"
NEPAL = Path(__file__).parent / "fixtures" / "nepal_1d530880" / "prompts.json"
TABLE = cost_plan.load_price_table()

#: (remote_id, production_status, tasks, image_to_video ratios, image_to_video durations,
#: capabilities as the steward left them: unsourced guesses, some plainly wrong).
REAL_RUNWAY_CATALOGUE: tuple[tuple[Any, ...], ...] = (
    (
        "gemini_omni_flash",
        "PRODUCTION",
        ["image_to_video", "text_to_video", "video_to_video"],
        ["1280:720", "720:1280"],
        {"min": 3, "max": 10},
        {"quality_score": 0.5, "notes": "No pricing or resolution details provided."},
    ),
    (
        "gemini_omni_flash_1.1",
        "PRODUCTION",
        ["image_to_video", "text_to_video", "video_to_video"],
        ["1080:1920", "1280:720", "1920:1080", "2160:3840", "360:640", "3840:2160", "640:360"]
        + ["720:1280"],
        None,
        {"quality_score": 0.5, "notes": "No pricing or resolution details provided."},
    ),
    (
        "gen4.5",
        "PRODUCTION",
        ["image_to_video", "text_to_video"],
        ["1104:832", "1280:720", "1584:672", "720:1280", "832:1104", "960:960"],
        {"min": 2, "max": 10},
        {"quality_score": 0.9, "notes": "1080p, text-to-video and image-to-video."},
    ),
    (
        "gen4_turbo",
        "PRODUCTION",
        ["image_to_video"],
        ["1104:832", "1280:720", "1584:672", "720:1280", "832:1104", "960:960"],
        {"min": 2, "max": 10},
        {"quality_score": 0.85, "notes": "Image-to-video only, 1080p."},
    ),
    (
        "grok_imagine_1_5",
        "PRODUCTION",
        ["image_to_video", "text_to_video"],
        None,
        {"min": 1, "max": 15},
        {"quality_score": 0.5, "notes": "No pricing or resolution details provided."},
    ),
    (
        "h3_max",
        "PRODUCTION",
        ["image_to_video", "text_to_video"],
        None,
        {"min": 5, "max": 15},
        {"quality_score": 0.5, "notes": "No pricing or resolution details provided."},
    ),
    (
        "hailuo3",
        "PRODUCTION",
        ["image_to_video", "text_to_video", "video_to_video"],
        ["16:9", "1:1", "21:9", "3:4", "4:3", "9:16", "adaptive"],
        {"min": 5, "max": 15},
        {"quality_score": 0.5, "notes": "No pricing or resolution details provided."},
    ),
    (
        "happyhorse_1_0",
        "PRODUCTION",
        ["image_to_video", "text_to_video"],
        None,
        {"min": 3, "max": 15},
        {"quality_score": 0.5, "notes": "No pricing or resolution details provided."},
    ),
    (
        "seedance2",
        "PRODUCTION",
        ["image_to_video", "text_to_video", "video_to_video"],
        ["1080:1920", "1112:834", "1248:1664", "1280:720", "1440:1440", "1470:630"]
        + ["1664:1248", "1920:1080", "2160:3840", "2206:946", "2880:3840", "3840:1646"]
        + ["3840:2160", "3840:2880", "3840:3840", "496:864", "560:752", "640:640"]
        + ["720:1280", "752:560", "834:1112", "864:496", "960:960", "992:432"],
        None,
        {"quality_score": 0.8, "notes": "1080p, 4-second clips, priced at $0.02/s."},
    ),
    (
        "seedance2_5",
        "PRODUCTION",
        ["image_to_video", "text_to_video", "video_to_video"],
        ["1080:1920", "1112:834", "1248:1664", "1280:720", "1440:1440", "1470:630"]
        + ["1664:1248", "1920:1080", "2206:946", "480:854", "560:752", "640:640"]
        + ["720:1280", "752:560", "834:1112", "854:480", "960:960", "992:432"],
        None,
        {"quality_score": 0.9, "notes": "1080p, up to 30 seconds, cinematic quality."},
    ),
    (
        "seedance2_fast",
        "PRODUCTION",
        ["image_to_video", "text_to_video", "video_to_video"],
        ["1112:834", "1280:720", "1470:630", "496:864", "560:752", "640:640", "720:1280"]
        + ["752:560", "834:1112", "864:496", "960:960", "992:432"],
        None,
        {"quality_score": 0.75, "notes": "1080p, faster generation."},
    ),
    (
        "seedance2_mini",
        "PRODUCTION",
        ["image_to_video", "text_to_video", "video_to_video"],
        ["1112:834", "1280:720", "1470:630", "496:864", "560:752", "640:640", "720:1280"]
        + ["752:560", "834:1112", "864:496", "960:960", "992:432"],
        None,
        {"quality_score": 0.7, "notes": "1080p, faster and cheaper than seedance2."},
    ),
    (
        "veo3.1",
        "PRODUCTION",
        ["image_to_video", "text_to_video"],
        ["1080:1920", "1280:720", "1920:1080", "720:1280"],
        [4, 6, 8],
        {"quality_score": 0.85, "notes": "1080p, cinematic quality."},
    ),
    (
        "veo3.1_fast",
        "PRODUCTION",
        ["image_to_video", "text_to_video"],
        ["1080:1920", "1280:720", "1920:1080", "720:1280"],
        [4, 6, 8],
        {"quality_score": 0.8, "notes": "1080p, faster generation."},
    ),
    (
        "wan3",
        "PRODUCTION",
        ["image_to_video", "text_to_video"],
        ["1080:1920", "1104:832", "1248:1648", "1280:720", "1440:1440", "1648:1248"]
        + ["1920:1080", "480:832", "544:720", "624:624", "720:1280", "720:544", "832:1104"]
        + ["832:480", "960:960", "auto_1080p", "auto_480p", "auto_720p"],
        {"min": 2, "max": 30},
        {"quality_score": 0.75, "notes": "1080p, priced at $0.015/s."},
    ),
    (
        "wan3_prime",
        "PRODUCTION",
        ["image_to_video", "text_to_video"],
        ["1080:1920", "1104:832", "1248:1648", "1280:720", "1440:1440", "1648:1248"]
        + ["1920:1080", "480:832", "544:720", "624:624", "720:1280", "720:544", "832:1104"]
        + ["832:480", "960:960", "auto_1080p", "auto_480p", "auto_720p"],
        {"min": 2, "max": 30},
        {"quality_score": 0.8, "notes": "1080p, higher quality than wan3."},
    ),
)


def raw_catalogue() -> dict[str, Any]:
    return json.loads(CATALOGUE.read_text(encoding="utf-8"))


def use_catalogue(monkeypatch, tmp_path: Path, **changes: Any) -> dict[str, Any]:
    """A copy of the real file with the Owner's fields changed, read by the planner."""
    data = raw_catalogue()
    data.update(changes)
    path = tmp_path / "film_models.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(policy, "FILM_MODELS_FILE", path)
    return data


def everything_allowed(monkeypatch, tmp_path: Path, **changes: Any) -> dict[str, Any]:
    return use_catalogue(
        monkeypatch, tmp_path, allowed=sorted(raw_catalogue()["models"]), **changes
    )


def add_connection(
    engine,
    rows: tuple[tuple[Any, ...], ...] = REAL_RUNWAY_CATALOGUE,
    capabilities: dict[str, dict[str, Any]] | None = None,
) -> str:
    """The real Runway catalogue as a connection's discovered models (no provider call)."""
    from app.integrations.models import Integration, ProviderResource
    from app.services import append_event, utc_now
    from sqlalchemy.orm import Session

    integration_id = str(uuid4())
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "settings.integration_saved", "integration", integration_id, 1, {}, "t"
        )
        session.add(
            Integration(
                id=integration_id,
                kind="runway",
                name="runway",
                config={},
                encrypted_secrets="",
                secret_fields=[],
                version=1,
                status="ACCESS_VERIFIED",
                checked_at=None,
                event_id=event.event_id,
            )
        )
        session.flush()
        for remote_id, status, tasks, ratios, durations, caps in rows:
            meta: dict[str, Any] = {"tasks": tasks}
            if ratios is not None:
                meta["ratios"] = {"image_to_video": ratios}
            meta["durations"] = {"image_to_video": durations} if durations is not None else {}
            session.add(
                ProviderResource(
                    id=str(uuid4()),
                    integration_id=integration_id,
                    resource_type="MODEL",
                    remote_id=remote_id,
                    name=remote_id,
                    api_metadata=meta,
                    api_available=True,
                    last_seen_at=utc_now(),
                    capabilities=(capabilities or {}).get(remote_id, caps),
                    production_status=status,
                    metadata_version=1,
                )
            )
    return integration_id


def capabilities_of(engine, integration_id: str) -> dict[str, Any]:
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        return {c.model_id: c for c in scene_model_capabilities(session, integration_id)}


def nepal_needs() -> list[policy.SceneNeed]:
    """The Nepal storyboard's scenes as the planner reads them: four LIVE, a card, black."""
    board = json.loads(NEPAL.read_text(encoding="utf-8"))
    kinds = {5: "DATA_CARD", 6: "BLACK"}
    scenes = board["scenes"]
    return [
        need_from_scene(
            {
                "scene_index": s["scene_index"],
                "scene_kind": kinds.get(s["scene_index"], "LIVE"),
                "duration_seconds": s["duration_seconds"],
                "prompt_json": {
                    "still_prompt": s["still_prompt"],
                    "motion_prompt": s["motion_prompt"],
                },
            },
            len(scenes),
        )
        for s in scenes
    ]


def scene(plan: dict, index: int) -> dict:
    return next(s for s in plan["scenes"] if s["scene_index"] == index)


# ------------------------------------------------------------------ 1. the file is honest


def test_every_documented_number_carries_its_sources_and_no_invented_precision():
    data = raw_catalogue()
    assert data["scale"]["basis"] == "documented" and data["scale"]["sources"]
    assert data["scale"]["method"] and data["scale"]["precision"]
    for model_id, entry in data["models"].items():
        assert entry["basis"] == "documented", model_id
        assert entry["sources"], model_id
        assert all(re.match(r"^https://", url) for url in entry["sources"]), model_id
        assert entry["notes"], model_id
        score = entry["quality_score"]
        if score is not None:
            assert 0.0 <= score <= 1.0 and round(score, 2) == score, model_id
        for need, value in entry["need_quality"].items():
            assert need in SCENE_NEEDS, (model_id, need)
            assert 0.0 <= value <= 1.0 and round(value, 2) == value, (model_id, need)
        if entry["camera_moves"] is not None:
            assert set(entry["camera_moves"]) <= set(CAMERA_MOVES), model_id


def test_every_priced_motion_model_is_documented_and_the_owners_fields_are_well_formed():
    data = raw_catalogue()
    priced_video = {row.model_id for row in TABLE.rows if row.kind == "video"}
    assert priced_video <= set(data["models"])
    # Every image_to_video model of the real connection is in the file.
    assert {row[0] for row in REAL_RUNWAY_CATALOGUE} <= set(data["models"])
    # Default: he allows every model the file documents; he edits it.
    assert set(data["allowed"]) == set(data["models"])
    assert 0.0 < data["hero_threshold"] <= 1.0
    reference = data["premium_reference"]
    assert TABLE.row(reference["model_id"], reference["resolution"]).kind == "video"

    loaded = load_film_models()
    assert loaded.allowed == frozenset(data["allowed"])
    assert loaded.hero_threshold == data["hero_threshold"]
    assert loaded.premium_reference == (reference["model_id"], reference["resolution"])
    assert required_quality("HERO") == data["hero_threshold"]


def test_a_malformed_catalogue_is_refused_loudly_never_read_as_empty(monkeypatch, tmp_path):
    path = tmp_path / "film_models.json"
    monkeypatch.setattr(policy, "FILM_MODELS_FILE", path)
    path.write_text('{"allowed": ["wan3"], "models": {"wan3": {"quality_score": 1.7}}}', "utf-8")
    with pytest.raises(ValueError, match="quality_score"):
        load_film_models()
    path.write_text('{"allowed": "wan3", "models": {}}', "utf-8")
    with pytest.raises(ValueError, match="allowed"):
        load_film_models()
    path.write_text('{"hero_threshold": 1.5, "models": {}}', "utf-8")
    with pytest.raises(ValueError, match="hero_threshold"):
        load_film_models()
    path.write_text("{not json", "utf-8")
    with pytest.raises(ValueError, match="film_models"):
        load_film_models()


# ------------------------------------------------- 2. the real catalogue plans the Nepal film


def test_the_nepal_film_gets_a_model_for_every_live_scene_on_the_real_catalogue(
    engine, monkeypatch, tmp_path
):
    data = everything_allowed(monkeypatch, tmp_path)
    caps = capabilities_of(engine, add_connection(engine))
    needs = nepal_needs()
    assert [n.kind for n in needs] == ["LIVE", "LIVE", "LIVE", "LIVE", "DATA_CARD", "BLACK"]
    assert needs[0].tier == "HERO"
    assert needs[1].water and needs[2].people and needs[3].people
    # "Avoid: ... extra hands and fingers" names what must NOT be in frame: no people there.
    assert not needs[0].people and not needs[1].people

    plan = plan_scene_models(needs, caps, table=TABLE)

    for index in (1, 2, 3, 4):
        entry = scene(plan, index)
        assert entry["status"] == "PLANNED", entry["reason_ro"]
        assert entry["model_id"] in data["allowed"]
        assert entry["quality"] >= entry["required_quality"]
    for index in (5, 6):
        assert scene(plan, index)["status"] == "COMPOSED"
        assert scene(plan, index)["credits"] == 0

    # The hook meets the Owner's HERO threshold.
    hero = scene(plan, 1)
    assert hero["tier"] == "HERO"
    assert hero["required_quality"] == data["hero_threshold"]
    assert hero["quality"] >= data["hero_threshold"]

    # On today's documented research the cheapest capable model is also the best ranked one:
    # wan3 at 20 credits/s at 1080p (Wan 3.0 leads the silent boards). The steward's guess of
    # 0.75 for it was never evidence and no longer decides.
    assert {scene(plan, i)["model_id"] for i in (1, 2, 3, 4)} == {"wan3"}
    assert [scene(plan, i)["credits"] for i in (1, 2, 3, 4)] == [80, 120, 80, 120]

    # The film total and the saving against the premium reference, in credits and USD.
    stills = 4 * cost_plan.price_still("seedream5_pro", "2K", 2)
    assert plan["stills_credits"] == stills
    assert plan["total_credits"] == stills + 400
    premium = stills + sum(
        cost_plan.price_shot("seedance2_5", "1080p", n.seconds, table=TABLE)
        for n in needs
        if n.kind == "LIVE"
    )
    assert plan["premium_credits"] == premium
    assert plan["saved_credits"] == premium - plan["total_credits"] > 0
    assert plan["premium_reference"] == {"model_id": "seedance2_5", "resolution": "1080p"}
    assert "seedance2_5 la 1080p" in plan["summary_ro"]
    assert "economisește" in plan["summary_ro"]
    assert plan["total_credits"] <= plan["cap_credits"]
    assert plan["status"] == "READY" and plan["buyable"] is True


def test_the_hero_shows_the_owner_the_best_available_when_no_allowed_model_reaches_it(
    engine, monkeypatch, tmp_path
):
    # The Owner leaves wan3 out of his allowed set: the best remaining, seedance2_5, is
    # documented at 0.92 against a 0.93 threshold.
    allowed = [m for m in raw_catalogue()["models"] if m != "wan3"]
    use_catalogue(monkeypatch, tmp_path, allowed=allowed)
    caps = capabilities_of(engine, add_connection(engine))
    plan = plan_scene_models(nepal_needs(), caps, table=TABLE)

    for entry in plan["scenes"]:
        assert entry["model_id"] != "wan3"
    hero = scene(plan, 1)
    assert hero["status"] == "NEEDS_OWNER" and hero["model_id"] is None
    best = hero["best_available"]
    assert best["model_id"] == "seedance2_5"
    assert best["quality"] == pytest.approx(0.92)
    assert best["credits"] == cost_plan.price_shot("seedance2_5", "1080p", 4.0, table=TABLE)
    assert "seedance2_5" in hero["reason_ro"] and "0,93" in hero["reason_ro"]
    assert "HERO" in hero["reason_ro"]
    assert "aprobat" in {e["model_id"]: e["why_ro"] for e in hero["excluded"]}["wan3"]

    # The STANDARD scenes still find their cheapest capable model in his set.
    for index in (2, 3, 4):
        assert scene(plan, index)["model_id"] == "seedance2"
    assert plan["status"] == "NEEDS_OWNER" and plan["buyable"] is False
    assert plan["waiting"] == [1]


def test_the_owners_override_on_the_sheet_still_wins_outside_his_allowed_set(
    engine, monkeypatch, tmp_path
):
    allowed = [m for m in raw_catalogue()["models"] if m != "wan3"]
    use_catalogue(monkeypatch, tmp_path, allowed=allowed)
    caps = capabilities_of(engine, add_connection(engine))
    plan = plan_scene_models(nepal_needs(), caps, overrides={1: "seedance2_5"}, table=TABLE)
    hero = scene(plan, 1)
    assert hero["model_id"] == "seedance2_5" and hero["decided_by"] == "owner"
    assert hero["warnings_ro"]

    picked = plan_scene_models(nepal_needs(), caps, overrides={2: "wan3"}, table=TABLE)
    two = scene(picked, 2)
    assert two["model_id"] == "wan3" and two["decided_by"] == "owner"
    assert any("aprobat" in warning for warning in two["warnings_ro"])


def test_a_model_the_connection_lists_but_the_owner_never_allowed_is_never_planned(
    engine, monkeypatch, tmp_path
):
    everything_allowed(monkeypatch, tmp_path)
    shiny = (
        "shiny_new_model",
        "PRODUCTION",
        ["image_to_video"],
        ["1080:1920"],
        {"min": 2, "max": 30},
        {"quality_score": 1.0, "basis": "steward", "sources": ["https://example.org/x"]},
    )
    caps = capabilities_of(engine, add_connection(engine, REAL_RUNWAY_CATALOGUE + (shiny,)))
    assert caps["shiny_new_model"].owner_allowed is False
    assert caps["wan3"].owner_allowed is True
    # Even priced as the cheapest, it is excluded with the reason.
    table = cost_plan.PriceTable(
        credit_usd=TABLE.credit_usd,
        rows=TABLE.rows
        + (
            cost_plan.PriceRow(
                model_id="shiny_new_model",
                kind="video",
                resolution="*",
                credits_per_second=1,
                source_url="https://example.org/x",
                date=TABLE.rows[0].date,
                provenance=cost_plan.DOCUMENTED,
            ),
        ),
        seconds=TABLE.seconds,
    )
    plan = plan_scene_models(nepal_needs(), caps, table=table)
    for entry in plan["scenes"]:
        assert entry["model_id"] != "shiny_new_model"
    why = {e["model_id"]: e["why_ro"] for e in scene(plan, 2)["excluded"]}
    assert "aprobat" in why["shiny_new_model"]


# ------------------------------------------------- 3. what outranks what in the research


def test_the_stewards_unsourced_guesses_lose_to_the_documented_file(engine, monkeypatch, tmp_path):
    everything_allowed(monkeypatch, tmp_path)
    caps = capabilities_of(engine, add_connection(engine))
    documented = raw_catalogue()["models"]
    # The steward wrote 0.8 for seedance2 and 0.75 for wan3 with no source; the file wins.
    assert caps["seedance2"].quality == documented["seedance2"]["quality_score"]
    assert caps["wan3"].quality == documented["wan3"]["quality_score"]
    assert caps["wan3"].need_quality == documented["wan3"]["need_quality"]
    assert caps["wan3"].camera_moves == tuple(documented["wan3"]["camera_moves"])
    assert caps["wan3"].quality_source == "documentat"
    # A model the file knows nothing measurable about keeps the steward's figure, flagged.
    assert caps["seedance2_fast"].quality == 0.75
    assert caps["seedance2_fast"].quality_source == "estimat"


def test_measured_capabilities_override_the_documented_ones(engine, monkeypatch, tmp_path):
    everything_allowed(monkeypatch, tmp_path)
    measured = {
        "wan3": {
            "basis": "measured",
            "quality_score": 0.7,
            "need_quality": {"people": 0.6},
            "camera_moves": ["static", "slow push-in"],
        },
        "seedance2": {
            "basis": "steward",
            "sources": ["https://help.runwayml.com/hc/en-us/articles/50488490233363"],
            "quality_score": 0.9,
        },
    }
    caps = capabilities_of(engine, add_connection(engine, capabilities=measured))
    documented = raw_catalogue()["models"]

    assert caps["wan3"].quality == 0.7
    assert caps["wan3"].quality_source == "măsurat"
    # Per need: the measured people figure, the documented water and fast-motion ones.
    assert caps["wan3"].need_quality == {
        **documented["wan3"]["need_quality"],
        "people": 0.6,
    }
    assert caps["wan3"].camera_moves == ("static", "slow push-in")
    # A steward's sourced research also outranks the file.
    assert caps["seedance2"].quality == 0.9

    plan = plan_scene_models(nepal_needs(), caps, table=TABLE)
    # wan3 measured below STANDARD no longer gets any scene; seedance2 (sourced 0.9) does.
    for index in (2, 3, 4):
        assert scene(plan, index)["model_id"] == "seedance2"
    why = {e["model_id"]: e["why_ro"] for e in scene(plan, 3)["excluded"]}
    assert "0,70" in why["wan3"]


def test_the_failure_history_per_model_and_kind_still_applies(engine, monkeypatch, tmp_path):
    from app.integrations.models import ModelOutcome
    from app.services import utc_now
    from sqlalchemy.orm import Session

    everything_allowed(monkeypatch, tmp_path)
    integration_id = add_connection(engine)
    # Nine good landscapes, then two of three shots with people refused at QC.
    history = [("general", True)] * 9 + [("people", False), ("people", False), ("people", True)]
    with Session(engine) as session, session.begin():
        for category, accepted in history:
            session.add(
                ModelOutcome(
                    id=str(uuid4()),
                    integration_id=integration_id,
                    remote_id="wan3",
                    purpose="video",
                    run_kind="PRODUCTION",
                    environment="PRODUCTION",
                    scene_category=category,
                    accepted=accepted,
                    failure_kind=None if accepted else "QUALITY",
                    created_at=utc_now(),
                )
            )
    caps = capabilities_of(engine, integration_id)
    assert caps["wan3"].failures["people"] == (2, 3)
    # Twelve judged shots: the studio's own acceptance (10 of 12) is now its quality.
    assert caps["wan3"].quality_source == "măsurat"
    assert caps["wan3"].quality == pytest.approx(10 / 12, abs=1e-3)
    plan = plan_scene_models(nepal_needs(), caps, table=TABLE)
    # Scenes with people leave wan3; the flood (water, no people) keeps it.
    assert scene(plan, 3)["model_id"] != "wan3" and scene(plan, 4)["model_id"] != "wan3"
    assert "2 din 3" in {e["model_id"]: e["why_ro"] for e in scene(plan, 3)["excluded"]}["wan3"]
    assert scene(plan, 2)["model_id"] == "wan3"


# ------------------------------------------------------- 4. the Owner's other two numbers


def test_the_hero_threshold_and_the_premium_reference_are_read_from_his_file(
    engine, monkeypatch, tmp_path
):
    allowed = [m for m in raw_catalogue()["models"] if m != "wan3"]
    use_catalogue(
        monkeypatch,
        tmp_path,
        allowed=allowed,
        hero_threshold=0.9,
        premium_reference={"model_id": "veo3.1", "resolution": "1080p"},
    )
    assert required_quality("HERO") == 0.9
    caps = capabilities_of(engine, add_connection(engine))
    needs = nepal_needs()
    plan = plan_scene_models(needs, caps, table=TABLE)
    # At 0.90 the hook can be filmed on seedance2_5 (0.92) without asking.
    hero = scene(plan, 1)
    assert (hero["model_id"], hero["status"]) == ("seedance2_5", "PLANNED")
    assert plan["premium_reference"] == {"model_id": "veo3.1", "resolution": "1080p"}
    expected = plan["stills_credits"] + sum(
        cost_plan.price_shot("veo3.1", "1080p", n.seconds, table=TABLE)
        for n in needs
        if n.kind == "LIVE"
    )
    assert plan["premium_credits"] == expected
    assert "veo3.1 la 1080p" in plan["summary_ro"]
