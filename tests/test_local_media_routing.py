"""The local selection reaches film planning without Runway billing or a cloud fallback."""

import json
import struct
from pathlib import Path
from uuid import uuid4

from app.integrations.discovery import ProductionCommand, refresh_catalog, save_production
from app.integrations.models import Integration, ServiceSelection
from app.integrations.services import SaveIntegration, save, select_service
from app.integrations.vault import CredentialVault
from app.media.factory import describe, image_provider, video_provider_for
from app.media.production_policy import SceneNeed, plan_scene_models
from app.media.shooting_sheet import (
    _read_balance,
    connection_account,
    connection_capabilities,
    price_table_for,
    runway_connection_id,
)
from app.providers import comfyui
from sqlalchemy import select
from sqlalchemy.orm import Session


def connect(engine, tmp_path, monkeypatch):
    vault = CredentialVault(tmp_path / "local.key")
    manifest = comfyui.load_manifest()
    nodes = {
        n["class_type"]: {"input": {"required": {}}}
        for m in manifest["models"]
        for n in m["graph"].values()
    }
    monkeypatch.setattr(
        comfyui,
        "_request",
        lambda base, method, route, body=None, *a: json.dumps(
            nodes if route == "/object_info" else {}
        ).encode(),
    )
    identifier = str(uuid4())
    save(
        engine,
        vault,
        identifier,
        SaveIntegration(
            kind="comfyui", name="Studio local", config={"base_url": "http://localhost:8188"}
        ),
    )
    result = refresh_catalog(
        engine, vault, identifier, interval_seconds=600, retry_seconds=60, force=True
    )
    assert result["status"] == "VERIFIED"
    save_production(
        engine,
        identifier,
        ProductionCommand(
            expected_version=0,
            model_id="I2V_HERO_RX9070",
            image_model_id="SDXL_LOCAL",
            allow_production_override=False,
        ),
    )
    for purpose in ("image", "video"):
        with Session(engine) as session:
            old = session.get(ServiceSelection, purpose)
            version = old.version if old else 0
        select_service(engine, purpose, identifier, version)
    return vault, identifier


def test_local_defaults_make_real_adapters_and_do_not_change_voice(engine, tmp_path, monkeypatch):
    with Session(engine) as session:
        voice = session.get(ServiceSelection, "voice")
        before = voice.integration_id if voice else None
    vault, identifier = connect(engine, tmp_path, monkeypatch)
    assert isinstance(image_provider(engine, vault), comfyui.ComfyImageAdapter)
    assert describe(engine, vault)["image_provider"] == "COMFYUI_IMAGES"
    assert isinstance(
        video_provider_for(
            engine,
            vault,
            {"valid": True, "integration_id": identifier, "model_id": "I2V_HERO_RX9070"},
        ),
        comfyui.ComfyVideoAdapter,
    )
    with Session(engine) as session:
        voice = session.get(ServiceSelection, "voice")
        assert (voice.integration_id if voice else None) == before
    assert runway_connection_id(engine) == identifier
    balance = _read_balance(connection_account(engine, vault, identifier))
    assert balance["applicable"] is False
    assert balance["credits"] is None  # no invented vendor balance


def test_local_sheet_uses_selected_profile_zero_cost_and_real_length_limit(
    engine, tmp_path, monkeypatch
):
    _vault, identifier = connect(engine, tmp_path, monkeypatch)
    table = price_table_for(engine, identifier)
    caps = connection_capabilities(engine, identifier)
    assert table.stills_model == "SDXL_LOCAL"
    need = SceneNeed(scene_index=1, kind="LIVE", seconds=4, tier="HERO")
    plan = plan_scene_models([need], caps, table=table)
    scene = plan["scenes"][0]
    assert scene["model_id"] == "I2V_HERO_RX9070"
    assert scene["status"] == "PLANNED", scene
    assert scene["quality"] is None  # choosing a profile does not manufacture a QC score
    assert scene["credits"] == 0 and plan["total_credits"] == 0
    long = SceneNeed(scene_index=1, kind="LIVE", seconds=8, tier="HERO")
    held = plan_scene_models([long], caps, table=table)["scenes"][0]
    assert held["status"] == "NEEDS_OWNER"
    assert held["model_id"] is None


def test_a_still_redo_under_the_local_selection_is_priced_zero_not_unpriced(
    engine, tmp_path, monkeypatch
):
    """Owner 2026-10-05: «modifici costul modelelor locale ca fiind 0». The redo drawer read
    the RAW published table (no local rows), so «Refă imaginea» refused with «SDXL_LOCAL la
    2K: niciun preț publicat în tabel». redo_plan without a table prices through the same
    table the sheet uses: the local model costs 0 credits."""
    from app.media.assembler import redo_plan
    from test_scene_takes import nepal_like

    vault, _identifier = connect(engine, tmp_path, monkeypatch)
    adapter = image_provider(engine, vault)
    storyboard_id = nepal_like(engine, tmp_path)
    plan = redo_plan(engine, storyboard_id, "still", 1, stills_model=adapter.model)
    assert plan["model_id"] == "SDXL_LOCAL"
    assert plan["credits"] == 0 and plan["cap_credits"] == 0


def test_refa_imaginea_runs_on_the_local_comfyui_and_stores_the_picture(
    engine, tmp_path, monkeypatch
):
    """The Owner's press «Refă imaginea» under the local selection: the request goes to the
    studio's ComfyUI (POST /prompt with the SDXL workflow), the pictures it returns are
    stored as the scene's new takes, and the books move 0 credits."""
    from app.media.assembler import redo_plan, redo_scene
    from app.media.models import SceneTake
    from app.models import ApprovalRequest
    from test_scene_takes import nepal_like
    from test_stills_stage import SpyJudge, faces_in

    vault, _identifier = connect(engine, tmp_path, monkeypatch)
    storyboard_id = nepal_like(engine, tmp_path)
    monkeypatch.setattr(comfyui, "available_memory", lambda: 12 * 1024**3)
    monkeypatch.setattr(comfyui, "watch_job", lambda *a: None)
    posts: list[dict] = []
    png = b"\x89PNG\r\n\x1a\n" + b"\0" * 8 + struct.pack(">II", 768, 1344)

    def fake_comfy(base, method, route, body=None, *args):
        assert base == "http://127.0.0.1:8188"  # loopback only, never a vendor URL
        if route == "/queue":
            return b"{}"
        if route == "/prompt":
            posts.append(json.loads(body))
            return json.dumps({"prompt_id": str(uuid4())}).encode()
        if route.startswith("/history"):
            job = route.rsplit("/", 1)[-1]
            return json.dumps(
                {
                    job: {
                        "status": {"completed": True},
                        "outputs": {"7": {"images": [{"filename": "still.png", "type": "output"}]}},
                    }
                }
            ).encode()
        return png  # /view?... — the generated picture's bytes

    monkeypatch.setattr(comfyui, "_request", fake_comfy)

    adapter = image_provider(engine, vault)
    plan = redo_plan(engine, storyboard_id, "still", 1, stills_model=adapter.model)
    assert plan["credits"] == 0  # local: priced, never billed

    def press():
        return redo_scene(
            engine,
            storyboard_id,
            str(uuid4()),
            kind="still",
            scene_index=1,
            plan_hash=plan["plan_hash"],
            image_adapter=adapter,
            judge=SpyJudge(),
            face_counter=faces_in(),
            measure=("faces",),
            storage_root=tmp_path / "media",
        )

    # Owner 2026-10-05: a 0-credit local step is not «generare cu bani», so under the
    # autonomous CEO the very first press goes to the GPU — no card is written for him.
    result = press()
    with Session(engine) as session:
        assert session.scalar(select(ApprovalRequest)) is None, "a free redo asked the Owner"

    assert posts, "«Refă imaginea» a spus da dar ComfyUI n-a primit nicio cerere"
    assert all("prompt" in post for post in posts)  # the SDXL workflow, not a URL to a vendor
    assert result["still"]["status"] == "APPROVED"
    assert result["still"]["bought_images"] == 2
    assert result["still"]["spent_credits_quoted"] == 0.0
    with Session(engine) as session:
        made = list(
            session.scalars(
                select(SceneTake).where(
                    SceneTake.storyboard_id == storyboard_id,
                    SceneTake.scene_number == 1,
                    SceneTake.kind == "still",
                )
            )
        )
    assert [t.model_id for t in made] and {t.model_id for t in made} == {"SDXL_LOCAL"}
    path = Path(next(t for t in made if t.id == result["still"]["take_id"]).path)
    assert path.read_bytes() == png


def test_offline_local_selection_never_falls_back_to_verified_runway(engine, tmp_path, monkeypatch):
    _vault, identifier = connect(engine, tmp_path, monkeypatch)
    from test_shooting_sheet import runway_connection

    runway_connection(engine)
    with Session(engine) as session, session.begin():
        session.get(Integration, identifier).status = "FAILED"
    assert runway_connection_id(engine) is None
