"""A character's reference set is a paid act under the Policy Kernel, priced and booked (MONEY-13).

`generate_character_reference_set` spent image credits with only a STOP check: the action
`media.character_reference_set` had a label but no risk tier, so `may_act` would have refused
it as unclassified had anything asked; nothing read the vendor's balance; and a model with no
catalogue price (Runway's seedream has none) reserved 0 and booked nothing.

Now the route goes through `may_act` (T2): the stop and safe mode refuse it like any money,
and the mode, which governs what agents do unasked, does not stand between the Owner and his
own press. The slots are priced from the published Runway table (`cost_plan.price_still`)
when the catalogue has no price, the balance is read before the first slot, and one cost row
is written per produced slot.

The image vendor is faked at the adapter boundary; no socket is opened.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from app.economy.models import ProviderCostRecord, SpendReservation
from app.integrations.models import Integration, ServiceSelection
from app.integrations.vault import CredentialVault
from app.media.cost_plan import STILLS_RESOLUTION, price_still
from app.media.services import (
    REFERENCE_SLOTS,
    ReferenceSetError,
    generate_character_reference_set,
)
from app.models import OwnerPolicy
from app.runbook.models import SafeModeRecord
from app.services import ACTION_RISK_TIERS, append_event, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_character_references import FakeImages, a_character, autonomy

ACTION = "media.character_reference_set"


class RunwayImages(FakeImages):
    """Runway's image model, faked, with the account's balance read beside it."""

    def __init__(self, integration_id: str, balance: float = 10_000.0, **kwargs) -> None:
        super().__init__(integration_id, "seedream5_pro", **kwargs)
        self.balance = balance
        self.reads = 0

    async def credit_balance(self):
        self.reads += 1
        return self.balance


@pytest.fixture
def vault(tmp_path):
    return CredentialVault(tmp_path / "reference.credentials.key")


def runway_images(engine, vault) -> str:
    """A verified Runway connection selected for pictures, with no catalogue price."""
    identifier = str(uuid4())
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "settings.integration_saved", "integration", identifier, 1, {}, str(uuid4())
        )
        session.add(
            Integration(
                id=identifier,
                kind="runway",
                name="Runway",
                config={"credit_usd": 0.01},
                encrypted_secrets=vault.encrypt({"api_key": "k"}),
                secret_fields=["api_key"],
                version=1,
                status="ACCESS_VERIFIED",
                checked_at=None,
                event_id=event.event_id,
            )
        )
        session.merge(
            ServiceSelection(
                purpose="image", integration_id=identifier, version=1, event_id=event.event_id
            )
        )
    return identifier


def produce(engine, vault, character_id: str, adapter, tmp_path: Path) -> dict:
    return generate_character_reference_set(
        engine,
        vault,
        character_id,
        str(uuid4()),
        image_adapter=adapter,
        storage_root=tmp_path / "references",
    )


def test_the_reference_set_has_a_tier_and_the_route_goes_through_may_act(
    client, headers, engine, vault, monkeypatch, tmp_path
):
    import app.services as kernel
    from app.media import router as media_router

    assert ACTION_RISK_TIERS[ACTION] == "T2"
    integration = runway_images(engine, vault)
    character_id = a_character(engine)
    client.app.app.state.image_adapter = RunwayImages(integration)
    monkeypatch.setattr(media_router, "REFERENCE_STORAGE_ROOT", tmp_path / "references")
    autonomy(engine, stopped=False)
    asked: list[dict] = []
    real = kernel.may_act

    def spy(session, action, *args, **kwargs):
        verdict = real(session, action, *args, **kwargs)
        asked.append({"action": action, "tier": verdict["tier"], "subject": kwargs.get("subject")})
        return verdict

    monkeypatch.setattr(kernel, "may_act", spy)

    produced = client.post(
        f"/api/v1/media/characters/{character_id}/reference-set", headers=headers
    )

    assert produced.status_code == 201, produced.text
    assert asked == [{"action": ACTION, "tier": "T2", "subject": character_id}]


def test_safe_mode_refuses_the_set_before_any_credit(engine, vault, tmp_path):
    integration = runway_images(engine, vault)
    character_id = a_character(engine)
    adapter = RunwayImages(integration)
    autonomy(engine, stopped=False)
    with Session(engine) as session, session.begin():
        session.add(
            SafeModeRecord(
                id=str(uuid4()),
                reason="Un incident ține studioul în SAFE_MODE.",
                trigger="STAGE_FAILURE",
                run_id=None,
                entered_at=utc_now(),
                cleared_at=None,
                cleared_notes=None,
                event_id=None,
            )
        )

    with pytest.raises(ReferenceSetError) as refused:
        produce(engine, vault, character_id, adapter, tmp_path)

    assert refused.value.reason == "BLOCKED_SAFE_MODE"
    assert adapter.prompts == []


def test_the_owners_press_is_not_refused_by_a_mode_that_governs_agents(engine, vault, tmp_path):
    """MANUAL lets agents do T1 alone; the Owner's own press is not an agent acting."""
    integration = runway_images(engine, vault)
    character_id = a_character(engine)
    autonomy(engine, stopped=False)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_mode = "MANUAL"

    answer = produce(engine, vault, character_id, RunwayImages(integration), tmp_path)

    assert all(answer["slots"][slot] for slot in REFERENCE_SLOTS)


def test_each_produced_slot_is_booked_at_the_published_runway_price(engine, vault, tmp_path):
    integration = runway_images(engine, vault)
    character_id = a_character(engine)
    adapter = RunwayImages(integration, refuse={"side"})
    autonomy(engine, stopped=False)
    per_image_usd = price_still("seedream5_pro", STILLS_RESOLUTION, 1) * 0.01

    answer = produce(engine, vault, character_id, adapter, tmp_path)

    produced = [slot for slot in REFERENCE_SLOTS if slot != "side"]
    assert answer["cost"]["priced"] is True
    assert answer["cost"]["per_image_usd"] == pytest.approx(per_image_usd)
    assert answer["cost"]["recorded"] == len(produced)
    assert adapter.reads >= 1, "the balance was not read before the first slot"
    with Session(engine) as session:
        rows = session.scalars(select(ProviderCostRecord)).all()
        assert len(rows) == len(produced)
        assert {row.provider for row in rows} == {"runway"}
        assert {row.attribution_json["slot"] for row in rows} == set(produced)
        assert {row.usd_micros for row in rows} == {round(per_image_usd * 1_000_000)}
        holds = session.scalars(select(SpendReservation)).all()
        assert [hold.status for hold in holds] == ["SETTLED"]
        assert holds[0].usd_micros == round(per_image_usd * len(REFERENCE_SLOTS) * 1_000_000)


def test_a_balance_below_the_set_is_refused_before_the_first_slot(engine, vault, tmp_path):
    integration = runway_images(engine, vault)
    character_id = a_character(engine)
    # Five slots at 9 credits plus the 15% margin is 51.75 credits; the account holds 40.
    adapter = RunwayImages(integration, balance=40)
    autonomy(engine, stopped=False)

    with pytest.raises(ReferenceSetError) as refused:
        produce(engine, vault, character_id, adapter, tmp_path)

    assert refused.value.reason == "LOW_BALANCE"
    assert "40" in str(refused.value)
    assert adapter.prompts == []
    with Session(engine) as session:
        assert session.scalars(select(ProviderCostRecord)).all() == []
        assert all(h.status != "RESERVED" for h in session.scalars(select(SpendReservation)))
