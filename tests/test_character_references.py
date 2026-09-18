"""A character's reference pictures: produced once, by the Owner, and used afterwards.

`CharacterBible.reference_assets_json` declared five slots and every one of them was null in
every studio that ever ran, so each generated picture of Sarah was a fresh invention and the
picture check had nothing to compare against. The slots are filled here — by real files with
real provenance, never by a description standing in for an image.

It costs image credits, so it is an Owner's act: it asks the budget before the first slot, it
refuses under STOP AUTONOMY, and nothing in the day's run calls it. Under the Owner's rule
(2026-09-17) no test generates anything: the image adapter is faked at the same boundary the
render tests fake it at, and `tests/conftest.py` refuses every non-loopback socket besides.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from uuid import uuid4

import pytest
from app.economy.budget import BudgetCommand, set_budget
from app.economy.models import ProviderCostRecord, SpendReservation
from app.integrations.models import Integration, ProviderResource, ServiceSelection
from app.integrations.vault import CredentialVault
from app.media.models import CharacterBible, MediaAsset
from app.media.services import (
    REFERENCE_SLOTS,
    ReferenceRequired,
    ReferenceSetError,
    generate_character_reference_set,
    image_reference_for_scene,
    seed_default_character_bibles,
)
from app.models import OwnerPolicy
from app.providers.media_base import ImageResult
from app.providers.media_http import MediaProviderError
from app.services import append_event, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session

# --------------------------------------------------------------------------- fixtures


def png_bytes(width: int, height: int) -> bytes:
    """A structurally valid PNG, so the dimensions the studio records are measured ones."""

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


class FakeImages:
    """The image vendor, faked at the adapter boundary. It never opens a socket."""

    PROVIDER_NAME = "TEST_IMAGE_PROVIDER"

    def __init__(self, integration_id: str, model: str, refuse: set[str] | None = None) -> None:
        self.integration_id = integration_id
        self.model = model
        self.refuse = refuse or set()
        self.prompts: list[str] = []
        self.extras: list[dict | None] = []

    async def health_check(self) -> dict:
        return {"status": "HEALTHY", "detail": ""}

    async def generate_image(
        self, prompt, *, width=1080, height=1920, style=None, seed=None, extra=None
    ):
        self.prompts.append(prompt)
        self.extras.append(extra)
        slot = (extra or {}).get("reference_slot")
        if slot in self.refuse:
            raise MediaProviderError(f"the vendor refused the {slot} reference")
        return ImageResult(
            image_bytes=png_bytes(64, 96), format="png", width=64, height=96, prompt=prompt
        )


@pytest.fixture
def vault(tmp_path):
    return CredentialVault(tmp_path / "test.credentials.key")


def image_connection(engine, vault, *, per_image_usd: float | None = None) -> str:
    """A verified image connection selected for the `image` purpose, optionally priced."""
    identifier = str(uuid4())
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "settings.integration_saved", "integration", identifier, 1, {}, str(uuid4())
        )
        session.add(
            Integration(
                id=identifier,
                kind="openai_media",
                name="Image account",
                config={"model": "test-image-model"},
                encrypted_secrets=vault.encrypt({"api_key": "k"}),
                secret_fields=["api_key"],
                version=1,
                status="VERIFIED",
                checked_at=None,
                event_id=event.event_id,
            )
        )
        session.merge(
            ServiceSelection(
                purpose="image", integration_id=identifier, version=1, event_id=event.event_id
            )
        )
        if per_image_usd is not None:
            session.add(
                ProviderResource(
                    id=str(uuid4()),
                    integration_id=identifier,
                    resource_type="MODEL",
                    remote_id="test-image-model",
                    name="test-image-model",
                    api_available=True,
                    last_seen_at=utc_now(),
                    api_metadata={},
                    pricing={"per_image_usd": per_image_usd},
                )
            )
    return identifier


def a_character(engine) -> str:
    seed_default_character_bibles(engine)
    with Session(engine) as session:
        return session.scalar(select(CharacterBible.id).order_by(CharacterBible.canonical_name))


def autonomy(engine, *, stopped: bool) -> None:
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = stopped


# --------------------------------------------------------------------------- the set


def test_the_reference_set_writes_asset_ids_into_the_slots_the_model_declares(
    engine, vault, tmp_path
):
    autonomy(engine, stopped=False)
    integration = image_connection(engine, vault, per_image_usd=0.04)
    character_id = a_character(engine)
    adapter = FakeImages(integration, "test-image-model")

    answer = generate_character_reference_set(
        engine,
        vault,
        character_id,
        str(uuid4()),
        image_adapter=adapter,
        storage_root=tmp_path / "references",
    )

    assert set(answer["slots"]) == set(REFERENCE_SLOTS)
    assert answer["failed"] == []
    assert len(adapter.prompts) == len(REFERENCE_SLOTS)
    # Each slot asked for its own framing, and every prompt carried the bible's own words.
    assert len({p for p in adapter.prompts}) == len(REFERENCE_SLOTS)

    with Session(engine) as session:
        row = session.get(CharacterBible, character_id)
        assert set(row.reference_assets_json) == set(REFERENCE_SLOTS)
        for slot, asset_id in row.reference_assets_json.items():
            assert asset_id == answer["slots"][slot]
            asset = session.get(MediaAsset, asset_id)
            assert asset is not None, f"{slot} names an asset that does not exist"
            assert asset.asset_type == "IMAGE"
            assert asset.provider_name == "TEST_IMAGE_PROVIDER"
            assert asset.license_status == "ORIGINAL_AI_GENERATED"
            # A slot holds a file, not a description: the bytes are on disk and hashed.
            stored = Path(asset.uri_or_path)
            assert stored.is_file() and stored.read_bytes() == png_bytes(64, 96)
            assert len(asset.provenance_hash) == 64
            assert (asset.width, asset.height) == (64, 96)


def test_the_set_is_refused_under_stop_autonomy_and_nothing_is_generated(engine, vault, tmp_path):
    autonomy(engine, stopped=True)
    integration = image_connection(engine, vault)
    character_id = a_character(engine)
    adapter = FakeImages(integration, "test-image-model")

    with pytest.raises(ReferenceSetError) as refusal:
        generate_character_reference_set(
            engine,
            vault,
            character_id,
            str(uuid4()),
            image_adapter=adapter,
            storage_root=tmp_path / "references",
        )

    assert refusal.value.reason == "AUTONOMY_STOPPED"
    assert adapter.prompts == [], "STOP is read before the first credit is spent"
    with Session(engine) as session:
        row = session.get(CharacterBible, character_id)
        assert all(value is None for value in row.reference_assets_json.values())


def test_a_slot_whose_generation_failed_stays_null_and_the_answer_names_it(engine, vault, tmp_path):
    autonomy(engine, stopped=False)
    integration = image_connection(engine, vault)
    character_id = a_character(engine)
    adapter = FakeImages(integration, "test-image-model", refuse={"side"})

    answer = generate_character_reference_set(
        engine,
        vault,
        character_id,
        str(uuid4()),
        image_adapter=adapter,
        storage_root=tmp_path / "references",
    )

    assert answer["slots"]["side"] is None
    assert [failure["slot"] for failure in answer["failed"]] == ["side"]
    assert answer["failed"][0]["reason"]
    with Session(engine) as session:
        row = session.get(CharacterBible, character_id)
        assert row.reference_assets_json["side"] is None
        assert row.reference_assets_json["portrait"] is not None


def test_the_budget_is_asked_before_the_first_slot_and_can_refuse_the_whole_set(
    engine, vault, tmp_path
):
    autonomy(engine, stopped=False)
    integration = image_connection(engine, vault, per_image_usd=0.04)
    character_id = a_character(engine)
    adapter = FakeImages(integration, "test-image-model")
    # Five slots at four cents is twenty; the day allows ten.
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="0.10"))

    with pytest.raises(ReferenceSetError) as refusal:
        generate_character_reference_set(
            engine,
            vault,
            character_id,
            str(uuid4()),
            image_adapter=adapter,
            storage_root=tmp_path / "references",
        )

    assert refusal.value.reason == "BUDGET"
    assert adapter.prompts == []
    with Session(engine) as session:
        assert session.scalars(select(SpendReservation)).all() == []


def test_a_produced_set_holds_its_money_settles_it_and_records_what_it_cost(
    engine, vault, tmp_path
):
    autonomy(engine, stopped=False)
    integration = image_connection(engine, vault, per_image_usd=0.04)
    character_id = a_character(engine)
    adapter = FakeImages(integration, "test-image-model")

    answer = generate_character_reference_set(
        engine,
        vault,
        character_id,
        str(uuid4()),
        image_adapter=adapter,
        storage_root=tmp_path / "references",
    )

    assert answer["cost"]["priced"] is True
    assert answer["cost"]["recorded"] == len(REFERENCE_SLOTS)
    with Session(engine) as session:
        holds = session.scalars(select(SpendReservation)).all()
        assert [h.status for h in holds] == ["SETTLED"]
        costs = session.scalars(select(ProviderCostRecord)).all()
        assert len(costs) == len(REFERENCE_SLOTS)
        assert {c.status for c in costs} == {"ESTIMATED"}


def test_a_set_whose_model_has_no_price_reports_none_and_never_zero(engine, vault, tmp_path):
    autonomy(engine, stopped=False)
    integration = image_connection(engine, vault)  # no pricing row at all
    character_id = a_character(engine)
    adapter = FakeImages(integration, "test-image-model")

    answer = generate_character_reference_set(
        engine,
        vault,
        character_id,
        str(uuid4()),
        image_adapter=adapter,
        storage_root=tmp_path / "references",
    )

    assert answer["cost"]["usd"] is None
    assert answer["cost"]["priced"] is False
    assert answer["cost"]["recorded"] == 0


def test_without_a_verified_image_provider_the_set_is_refused_rather_than_drawn_by_a_placeholder(
    engine, vault, tmp_path
):
    autonomy(engine, stopped=False)
    character_id = a_character(engine)

    with pytest.raises(ReferenceSetError) as refusal:
        generate_character_reference_set(
            engine, vault, character_id, str(uuid4()), storage_root=tmp_path / "references"
        )

    assert refusal.value.reason == "NO_IMAGE_PROVIDER"


def test_the_days_run_never_produces_a_reference_set():
    """It spends image credits, so it is the Owner's act. The runbook must not name it."""
    root = Path(__file__).resolve().parents[1] / "backend" / "app"
    for module in ("runbook/stages.py", "runbook/services.py", "workflows/services.py"):
        text = (root / module).read_text(encoding="utf-8")
        assert "generate_character_reference_set" not in text, module


# --------------------------------------------------------------------------- in a scene


def reference_the_character(engine, character_id, *, slot: str = "portrait") -> str:
    """One stored reference asset for a character, without generating anything."""
    asset_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="IMAGE",
                uri_or_path="/nowhere/portrait.png",
                file_size_bytes=10,
                mime_type="image/png",
                width=64,
                height=96,
                provider_name="TEST_IMAGE_PROVIDER",
                license_status="ORIGINAL_AI_GENERATED",
                provenance_hash="0" * 64,
                created_at=utc_now(),
            )
        )
        row = session.get(CharacterBible, character_id)
        slots = dict(row.reference_assets_json or {})
        slots[slot] = asset_id
        row.reference_assets_json = slots
    return asset_id


def lock_the_look(engine, character_id) -> None:
    with Session(engine) as session, session.begin():
        row = session.get(CharacterBible, character_id)
        row.identity_locks_json = {**(row.identity_locks_json or {}), "visual": True}


def test_a_scene_that_names_a_character_with_a_reference_carries_it(engine):
    character_id = a_character(engine)
    asset_id = reference_the_character(engine, character_id)

    reference = image_reference_for_scene(engine, [character_id])

    assert reference is not None
    assert reference["asset_id"] == asset_id
    assert reference["slot"] == "portrait"
    assert reference["character_id"] == character_id


def test_a_scene_with_no_character_asks_for_no_reference(engine):
    assert image_reference_for_scene(engine, []) is None


def test_a_character_without_a_reference_simply_has_none(engine):
    character_id = a_character(engine)
    assert image_reference_for_scene(engine, [character_id]) is None


def test_a_locked_character_with_no_reference_is_refused_rather_than_invented(engine):
    character_id = a_character(engine)
    lock_the_look(engine, character_id)

    with pytest.raises(ReferenceRequired) as refusal:
        image_reference_for_scene(engine, [character_id])

    assert character_id in str(refusal.value) or "referin" in str(refusal.value).lower()


def test_a_locked_character_with_a_reference_uses_it(engine):
    character_id = a_character(engine)
    lock_the_look(engine, character_id)
    asset_id = reference_the_character(engine, character_id, slot="full_body")

    reference = image_reference_for_scene(engine, [character_id])

    assert reference["asset_id"] == asset_id
    assert reference["required"] is True


# --------------------------------------------------------------------------- the route


def test_the_owner_route_produces_the_set_and_refuses_under_stop(
    client, headers, engine, vault, monkeypatch, tmp_path
):
    from app.media import router as media_router

    integration = image_connection(engine, vault)
    character_id = a_character(engine)
    adapter = FakeImages(integration, "test-image-model")
    monkeypatch.setattr(media_router, "REFERENCE_STORAGE_ROOT", tmp_path / "references")
    client.app.app.state.image_adapter = adapter

    autonomy(engine, stopped=True)
    stopped = client.post(f"/api/v1/media/characters/{character_id}/reference-set", headers=headers)
    assert stopped.status_code == 409, stopped.text

    autonomy(engine, stopped=False)
    produced = client.post(
        f"/api/v1/media/characters/{character_id}/reference-set", headers=headers
    )
    assert produced.status_code == 201, produced.text
    assert set(produced.json()["slots"]) == set(REFERENCE_SLOTS)


def test_the_route_is_owner_only(client, engine):
    character_id = a_character(engine)
    anonymous = client.post(f"/api/v1/media/characters/{character_id}/reference-set")
    assert anonymous.status_code in (401, 403)


# ------------------------------------------------- from the slot to the vendor's request


def test_the_reference_reaches_the_render_path_as_bytes(engine, vault, tmp_path):
    """What the assembler hands an adapter is the picture itself, not the path to it."""
    from app.media.factory import reference_payload

    autonomy(engine, stopped=False)
    integration = image_connection(engine, vault)
    character_id = a_character(engine)
    generate_character_reference_set(
        engine,
        vault,
        character_id,
        str(uuid4()),
        image_adapter=FakeImages(integration, "test-image-model"),
        storage_root=tmp_path / "references",
    )

    payload = reference_payload(engine, [character_id])

    assert payload["bytes"] == png_bytes(64, 96)
    assert payload["slot"] == "portrait"
    assert payload["required"] is False


def test_a_reference_whose_file_is_gone_is_refused_for_a_locked_character(engine):
    """A row pointing at a file nobody can read is not a reference, and the lock still holds."""
    from app.media.factory import reference_payload

    character_id = a_character(engine)
    lock_the_look(engine, character_id)
    reference_the_character(engine, character_id)  # the asset names a path that does not exist

    with pytest.raises(ReferenceRequired):
        reference_payload(engine, [character_id])


def test_an_adapter_that_cannot_take_a_reference_is_never_told_it_drew_from_one(engine, vault):
    """The still is still drawn — from the words — and the attempt says so rather than
    reporting a continuity the render never had."""
    import asyncio

    from app.media.factory import still_from_chain

    integration = image_connection(engine, vault)
    adapter = FakeImages(integration, "test-image-model")
    assert not getattr(adapter, "ACCEPTS_REFERENCE_IMAGE", False)

    _result, attempts = asyncio.run(
        still_from_chain(
            engine,
            [adapter],
            "Sarah at her desk",
            extra={"reference_image": {"bytes": png_bytes(8, 8), "mime_type": "image/png"}},
        )
    )

    assert attempts[0]["reference_image"] is False
    assert "reference_image" not in (adapter.extras[0] or {})


def test_an_adapter_that_takes_a_reference_is_given_it(engine, vault):
    import asyncio

    from app.media.factory import still_from_chain

    class Capable(FakeImages):
        ACCEPTS_REFERENCE_IMAGE = True

    integration = image_connection(engine, vault)
    adapter = Capable(integration, "test-image-model")
    reference = {"bytes": png_bytes(8, 8), "mime_type": "image/png"}

    _result, attempts = asyncio.run(
        still_from_chain(
            engine, [adapter], "Sarah at her desk", extra={"reference_image": reference}
        )
    )

    assert attempts[0]["reference_image"] is True
    assert adapter.extras[0]["reference_image"] is reference


def test_runway_is_a_vendor_the_chain_may_hand_a_reference_to(engine, vault, monkeypatch):
    """`RunwayImageAdapter` used to answer False to `accepts_reference_image`, so the chain
    dropped the character's sheet and a Runway-drawn still was honestly recorded as drawn from
    the words. The adapter sends `referenceImages` now, so the chain passes the picture and
    the attempt records the continuity the render actually had."""
    import asyncio
    import json as _json

    from app.media.factory import accepts_reference_image, still_from_chain
    from app.providers import runway
    from app.providers.runway import RunwayImageAdapter

    submitted: list[dict] = []

    def transport(host, method, path, headers, body=None, **kwargs):
        submitted.append({"host": host, "path": path, "body": body})
        if path == "/v1/text_to_image":
            return {"id": "task-1"}, b"", "application/json"
        if path.startswith("/v1/tasks/"):
            return (
                {"status": "SUCCEEDED", "output": ["https://files.test/still.png"]},
                b"",
                "application/json",
            )
        return None, png_bytes(64, 96), "image/png"

    monkeypatch.setattr(runway, "request", transport)
    adapter = RunwayImageAdapter(
        "key",
        "gen4_image",
        {"tasks": ["text_to_image"], "ratios": {"text_to_image": ["1080:1920"]}},
    )
    assert accepts_reference_image(adapter) is True

    reference = {"bytes": png_bytes(64, 96), "mime_type": "image/png"}
    _result, attempts = asyncio.run(
        still_from_chain(
            engine, [adapter], "Sarah at her desk", extra={"reference_image": reference}
        )
    )

    assert attempts[0]["reference_image"] is True
    assert len(_json.loads(submitted[0]["body"])["referenceImages"]) == 1
    # What the code does, not what the account has answered: no live run has ever posted this
    # field, so nothing here may be read as a verified integration.
    assert adapter.REFERENCE_IMAGE_VERIFIED is False


# ------------------------------------------------- and in the film the studio actually makes


def a_named_character(engine, canonical_name: str) -> str:
    """One of the seeded studio characters, by the name a scene would actually write."""
    seed_default_character_bibles(engine)
    with Session(engine) as session:
        return session.scalar(
            select(CharacterBible.id).where(CharacterBible.canonical_name == canonical_name)
        )


def a_factual_board(engine, plan: list[dict], title: str = "Reference") -> dict:
    """A factual storyboard built the way the studio builds one, from an APPROVED script."""
    from app.factual.models import ScriptDraft, TopicIdea
    from app.media.services import generate_storyboard_from_script

    topic_id, script_id, now = str(uuid4()), str(uuid4()), utc_now()
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        session.add(
            TopicIdea(
                id=topic_id,
                title=title,
                topic="space",
                angle="a",
                target_audience="g",
                novelty_score=0.9,
                status="SELECTED",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            ScriptDraft(
                id=script_id,
                topic_id=topic_id,
                title=title,
                voiceover_full_text=" ".join(str(s.get("narration") or "") for s in plan),
                scenes_json=plan,
                claim_ids_json=[],
                unverified_claim_ids_json=[],
                status="APPROVED",
                created_at=now,
            )
        )
    return generate_storyboard_from_script(
        engine, script_id, "GENERATED_IMAGE", "9:16", str(uuid4())
    )


def test_a_reference_set_finally_reaches_a_factual_film(engine):
    """The slots the Owner pays to fill were unreachable on the studio's main product.

    `image_reference_for_scene` reads a scene's cast, and until now every factual scene was
    written with an empty one — so a portrait the Owner had produced could only ever be used
    by the serial. A factual scene whose picture names the character now carries it, and the
    scene that shows a spectrum still carries nothing.
    """
    character_id = a_named_character(engine, "Sarah Executive")
    asset_id = reference_the_character(engine, character_id)

    board = a_factual_board(
        engine,
        [
            {
                "scene_index": 1,
                "visual_description": "Sarah at the studio window, mid-sentence",
                "narration": "The day starts with the numbers.",
            },
            {
                "scene_index": 2,
                "visual_description": "A spectrum with a water line marked",
                "narration": "A line of water.",
            },
        ],
    )

    first, second = board["scenes"][0], board["scenes"][1]
    assert first["character_ids_json"] == [character_id]
    reference = image_reference_for_scene(engine, first["character_ids_json"])
    assert reference is not None and reference["asset_id"] == asset_id
    assert second["character_ids_json"] == []
    assert image_reference_for_scene(engine, second["character_ids_json"]) is None


def test_a_locked_character_named_in_a_factual_scene_refuses_a_face_it_has_not_got(engine):
    """The lock rule now also holds on factual films, which is the point of recording a cast.

    A character whose look is locked and whose slots are empty refuses the scene rather than
    letting a face be invented. This was unreachable from a factual film while every factual
    scene listed nobody; a studio that locks a look must produce the reference set first.
    """
    character_id = a_named_character(engine, "Sarah Executive")
    lock_the_look(engine, character_id)

    board = a_factual_board(
        engine,
        [
            {
                "scene_index": 1,
                "visual_description": "Sarah at the studio window, mid-sentence",
                "narration": "The day starts with the numbers.",
            }
        ],
        title="Locked",
    )

    with pytest.raises(ReferenceRequired, match="referință"):
        image_reference_for_scene(engine, board["scenes"][0]["character_ids_json"])
