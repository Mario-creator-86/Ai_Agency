"""The rights gate reads evidence, not a stamp the studio writes on itself (AR-15).

Every rendered film used to be stamped PROPRIETARY_STUDIO and quality control passed it
because the stamp was on the list. Nothing recorded whether the narration's plan, the
pictures' plan, the fonts or a music track allowed commercial use.

Now each component of a film carries its licence: the vendor's from the connection the Owner
configured (Setări → the connection's "folosire comercială" and plan), the fonts' from the OFL
shipped beside them, a music track's from the library entry. The film is LICENSED only when
every component carries commercial-use evidence; otherwise NEEDS_REVIEW, which keeps the
film private: the publishing gate refuses it public or unlisted, never private.

No provider is called; the vendors are fakes and the connections are rows the test writes.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from app.integrations.models import Integration
from app.media import music_library
from app.media.assembler import assemble_video_job, film_licences
from app.media.models import MediaAsset, SceneTake
from app.media.qc import audio_mix_verdict, rights_verdict
from app.media.toolchain import find_ffmpeg
from app.publishing.services import evaluate_publishing_gate, with_attributions
from app.services import append_event, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session

requires_ffmpeg = pytest.mark.skipif(find_ffmpeg() is None, reason="FFmpeg is not installed")


def _connection(engine, integration_id: str, kind: str, config: dict) -> None:
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "settings.integration_saved", "integration", integration_id, 1, {}, "c"
        )
        session.add(
            Integration(
                id=integration_id,
                kind=kind,
                name=kind,
                config=config,
                encrypted_secrets="",
                secret_fields=["api_key"],
                version=1,
                status="VERIFIED",
                checked_at=utc_now(),
                event_id=event.event_id,
            )
        )


def _render(engine, tmp_path: Path, monkeypatch) -> dict:
    from test_motion import StubImages
    from test_phase5_media import AlignedVoice, _seeded_storyboard

    library = tmp_path / "music_library.json"
    library.write_text('{"tracks": []}', encoding="utf-8")
    monkeypatch.setattr(music_library, "LIBRARY_PATH", library)
    sb_id, _ = _seeded_storyboard(engine, tmp_path, scenes=2)
    return assemble_video_job(
        engine,
        sb_id,
        str(uuid4()),
        storage_root=tmp_path / "media",
        image_adapter=StubImages(),  # connection "conn-1"
        tts_adapter=AlignedVoice(aligned=True),  # connection "conn-voice"
        environment="TEST",
    )


COMMERCIAL = {"commercial_use": "da", "licence_terms": "Plan Standard, termeni 2026-05"}


@requires_ffmpeg
def test_a_film_whose_components_all_carry_commercial_evidence_is_licensed(
    engine, tmp_path: Path, monkeypatch
):
    _connection(engine, "conn-1", "runway", COMMERCIAL)
    _connection(engine, "conn-voice", "elevenlabs", {**COMMERCIAL, "licence_terms": "Creator"})
    render = _render(engine, tmp_path, monkeypatch)
    licences = render["production"]["licences"]
    assert licences["status"] == "LICENSED", licences
    kinds = {component["component"] for component in licences["components"]}
    assert {"still", "narration", "fonts"} <= kinds
    assert all(component["commercial_use"] is True for component in licences["components"])
    with Session(engine) as session:
        asset = session.get(MediaAsset, render["output_asset_id"])
        assert asset.license_status == "LICENSED"
        # The evidence is on each take the film used, read from the connection then.
        takes = session.scalars(
            select(SceneTake).where(SceneTake.storyboard_id == asset_storyboard(session, asset))
        ).all()
        used = {
            scene["still_take"]["take_id"]
            for scene in render["production"]["scenes"]
            if scene.get("still_take")
        }
        stills = [take for take in takes if take.id in used]
        assert len(stills) == 2 and all(take.commercial_use is True for take in stills)
        assert {take.licence_vendor for take in stills} == {"runway"}
        assert {take.licence_terms for take in stills} == {COMMERCIAL["licence_terms"]}
        narration = [take for take in takes if take.kind == "narration"]
        assert narration and all(take.licence_terms == "Creator" for take in narration)


def asset_storyboard(session: Session, asset: MediaAsset) -> str:
    from app.media.models import VideoRenderJob

    job = session.scalar(select(VideoRenderJob).where(VideoRenderJob.output_asset_id == asset.id))
    return job.storyboard_id


@requires_ffmpeg
def test_a_component_without_evidence_makes_the_film_need_review(
    engine, tmp_path: Path, monkeypatch
):
    _connection(engine, "conn-1", "runway", COMMERCIAL)
    # The narration's connection says nothing about commercial use.
    _connection(engine, "conn-voice", "elevenlabs", {})
    render = _render(engine, tmp_path, monkeypatch)
    licences = render["production"]["licences"]
    assert licences["status"] == "NEEDS_REVIEW"
    assert any("narațiun" in reason for reason in licences["missing_ro"]), licences
    with Session(engine) as session:
        assert session.get(MediaAsset, render["output_asset_id"]).license_status == "NEEDS_REVIEW"


def test_the_ledger_is_licensed_only_when_every_component_says_so():
    yes = {"component": "still", "scene_index": 1, "commercial_use": True}
    unknown = {"component": "motion", "scene_index": 1, "commercial_use": None}
    assert film_licences([yes])["status"] == "LICENSED"
    assert film_licences([yes, unknown])["status"] == "NEEDS_REVIEW"
    assert film_licences([])["status"] == "NEEDS_REVIEW"  # nothing proven is not proof


def _asset(engine, license_status: str) -> str:
    asset_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="RENDERED_VIDEO",
                uri_or_path=str(Path(__file__)),
                file_size_bytes=1,
                mime_type="video/mp4",
                license_status=license_status,
                provenance_hash="0" * 64,
                created_at=utc_now(),
            )
        )
    return asset_id


@pytest.mark.parametrize("privacy", ["public", "unlisted"])
def test_a_film_needing_review_is_refused_public_and_unlisted(engine, privacy):
    from app.publishing.models import ChannelRecord
    from app.publishing.services import seed_default_channels

    seed_default_channels(engine)
    asset_id = _asset(engine, "NEEDS_REVIEW")
    with Session(engine) as session:
        channel = session.scalars(select(ChannelRecord)).first()
        channel_id, version = channel.id, channel.policy_version
    gate = evaluate_publishing_gate(
        engine, asset_id, channel_id, privacy_status=privacy, policy_version=version
    )
    assert "RIGHTS_NEEDS_REVIEW" in gate["reason_codes"]
    rights = next(c for c in gate["checks"] if c["check_name"] == "RIGHTS_GATE")
    assert rights["passed"] is False
    assert "licen" in rights["detail"]


def test_a_film_needing_review_may_still_be_uploaded_private(engine):
    from app.publishing.models import ChannelRecord
    from app.publishing.services import seed_default_channels

    seed_default_channels(engine)
    asset_id = _asset(engine, "NEEDS_REVIEW")
    with Session(engine) as session:
        channel_id = session.scalars(select(ChannelRecord)).first().id
    gate = evaluate_publishing_gate(engine, asset_id, channel_id, privacy_status="private")
    assert "RIGHTS_NEEDS_REVIEW" not in gate["reason_codes"]


def test_a_licensed_film_passes_the_rights_gate_when_public(engine):
    from app.publishing.models import ChannelRecord
    from app.publishing.services import seed_default_channels

    seed_default_channels(engine)
    asset_id = _asset(engine, "LICENSED")
    with Session(engine) as session:
        channel = session.scalars(select(ChannelRecord)).first()
        channel_id, version = channel.id, channel.policy_version
    gate = evaluate_publishing_gate(
        engine, asset_id, channel_id, privacy_status="public", policy_version=version
    )
    assert "RIGHTS_NEEDS_REVIEW" not in gate["reason_codes"]


def test_quality_control_passes_a_film_needing_review_for_a_private_upload_only():
    verdict = rights_verdict("NEEDS_REVIEW", {"licences": {"missing_ro": ["narațiunea"]}})
    assert verdict["passed"] is True
    assert verdict["public_allowed"] is False
    assert verdict["missing_ro"] == ["narațiunea"]
    assert rights_verdict("LICENSED", {})["public_allowed"] is True
    assert rights_verdict("SOMETHING_ELSE", {})["passed"] is False


def test_quality_control_refuses_a_music_file_without_a_manifest_entry(tmp_path, monkeypatch):
    library = tmp_path / "music_library.json"
    library.write_text('{"tracks": []}', encoding="utf-8")
    monkeypatch.setattr(music_library, "LIBRARY_PATH", library)
    verdict = audio_mix_verdict(
        {
            "audio": {
                "bed": {
                    "track_id": "ghost",
                    "sha256": "0" * 64,
                    "measured_lu_under_voice": 20.0,
                }
            }
        }
    )
    assert verdict["passed"] is False
    assert any("ghost" in reason for reason in verdict["reasons_ro"])


def test_quality_control_refuses_a_bed_too_loud_under_the_voice(tmp_path, monkeypatch):
    data = b"bed-bytes"
    import hashlib
    import json

    (tmp_path / "bed.wav").write_bytes(data)
    entry = {
        "id": "bed",
        "kind": "music",
        "file": "bed.wav",
        "sha256": hashlib.sha256(data).hexdigest(),
        "licence": "Licență (test)",
        "commercial_ok": True,
    }
    library = tmp_path / "music_library.json"
    library.write_text(json.dumps({"tracks": [entry]}), encoding="utf-8")
    monkeypatch.setattr(music_library, "LIBRARY_PATH", library)
    bed = {"track_id": "bed", "sha256": entry["sha256"], "measured_lu_under_voice": 9.0}
    verdict = audio_mix_verdict({"audio": {"bed": bed}})
    assert verdict["passed"] is False
    assert any("sub voce" in reason for reason in verdict["reasons_ro"])
    bed["measured_lu_under_voice"] = 20.0
    assert audio_mix_verdict({"audio": {"bed": bed}})["passed"] is True
    # A film without a bed passes, with the advisory carried.
    assert audio_mix_verdict({"audio": {"bed": None, "advisory": "x"}})["passed"] is True


def test_a_required_attribution_is_written_once_above_the_studios_block():
    footer = "Disclosure: this video was produced with generative AI by the AMN-AI studio."
    body = f"About the film.\n\n{footer}"
    once = with_attributions(body, ["Music: Track by Someone (CC BY 4.0)"])
    assert once.index("Music: Track") < once.index("Disclosure:")
    assert with_attributions(once, ["Music: Track by Someone (CC BY 4.0)"]) == once
    assert with_attributions(body, []) == body


def test_migration_0051_adds_the_licence_columns_and_takes_them_back(tmp_path):
    import sqlite3

    from app.db import create_db_engine, migrate
    from test_migrations_0049 import _downgrade

    path = tmp_path / "studio.db"
    engine = create_db_engine(f"sqlite:///{path.as_posix()}")
    migrate(engine)

    def columns() -> set[str]:
        with sqlite3.connect(path) as raw:
            return {row[1] for row in raw.execute("PRAGMA table_info(scene_take)")}

    licence = {"licence_vendor", "licence_terms", "commercial_use"}
    assert licence <= columns()
    _downgrade(engine, "0050_film_purchase_lease")
    assert not licence & columns()
    migrate(engine)
    assert licence <= columns()
    engine.dispose()
