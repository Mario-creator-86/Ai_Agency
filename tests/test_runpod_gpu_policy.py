"""The RunPod GPU in the Policy Kernel, the Owner's decision cards and his routes (2026-10-08).

Switching the GPU OFF is always allowed (T0, before the stop); switching it ON only inside a
paid step of a film the kernel already lets run, after the Owner accepted the card. Every RunPod
call goes to a fake transport."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.decisions.models import OwnerDecision
from app.decisions.seed import seed_owner_decisions
from app.decisions.services import DecideCommand, condition_reading, decide_owner_decision
from app.integrations.models import Integration
from app.integrations.services import SaveIntegration, save
from app.integrations.vault import CredentialVault
from app.models import ApprovalRequest, OwnerPolicy
from app.providers.runpod import gpu_session
from app.services import ACTION_RISK_TIERS, APPROVAL_ACTION_LABELS, may_act
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_runpod_gpu_control import KEY, S3_ID, S3_SECRET, Fake, running_studio  # noqa: F401


def runpod(
    engine, monkeypatch, *, allow: bool = False, **values: str
) -> tuple[CredentialVault, str]:
    monkeypatch.setenv("RUNPOD_ENABLED", "true")
    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    identifier = str(uuid4())
    save(
        engine,
        vault,
        identifier,
        SaveIntegration(
            kind="runpod",
            name="RunPod",
            config={
                "stills_endpoint_id": "ep-stills",
                "motion_endpoint_id": "ep-motion",
                "s3_endpoint_url": "https://bucket.example",
                "s3_bucket": "amn-out",
            }
            | values,
            secrets={  # type: ignore[arg-type]
                "api_key": KEY,
                "s3_access_key_id": S3_ID,
                "s3_secret_access_key": S3_SECRET,
            },
        ),
    )
    if allow:
        with Session(engine) as session, session.begin():
            row = session.get(Integration, identifier)
            row.config = {**row.config, "allow_infra_actions": "true"}
    return vault, identifier


def ask(engine, action: str, **context: Any) -> dict[str, Any]:
    with Session(engine) as session:
        verdict = may_act(
            session,
            action,
            subject="film-1",
            cost_usd=context.pop("cost_usd", 2.0),
            context=context or None,
            ask_owner=False,
        )
        session.rollback()
    return verdict


def policy(engine, **values: Any) -> None:
    with Session(engine) as session, session.begin():
        row = session.get(OwnerPolicy, 1)
        for key, value in values.items():
            setattr(row, key, value)


def gpu_on(identifier: str, **values: Any) -> dict[str, Any]:
    return {
        "step_action": "media.stills_purchase",
        "plan_hash": "plan-1",
        "approval_id": None,
        "owner_press": False,
        "integration_id": identifier,
    } | values


def test_tiers_and_labels():
    assert ACTION_RISK_TIERS["infra.gpu_off"] == "T0"
    assert ACTION_RISK_TIERS["infra.gpu_on"] == "T2"
    assert APPROVAL_ACTION_LABELS["infra.gpu_off"] == "Oprirea GPU-ului RunPod"
    assert "pas plătit aprobat" in APPROVAL_ACTION_LABELS["infra.gpu_on"]


def test_switching_off_is_allowed_under_stop_safe_mode_and_manual(engine):
    policy(engine, autonomy_stopped=True, autonomy_mode="MANUAL")
    verdict = ask(engine, "infra.gpu_off")
    assert verdict["allowed"] and verdict["status"] == "ALLOWED"
    assert "STOP AUTONOMIE" in verdict["reason"]


def test_switching_on_outside_a_paid_step_is_refused(engine, monkeypatch):
    _, identifier = runpod(engine, monkeypatch, allow=True)
    verdict = ask(engine, "infra.gpu_on", **gpu_on(identifier, step_action="media.paid_generation"))
    assert verdict["status"] == "BLOCKED_NOT_IN_STEP"
    assert ask(engine, "infra.gpu_on")["status"] == "BLOCKED_NOT_IN_STEP"


def test_switching_on_needs_the_owner_card(engine, monkeypatch):
    _, identifier = runpod(engine, monkeypatch, allow=False)
    policy(engine, paid_media_approval="MODE")
    verdict = ask(engine, "infra.gpu_on", **gpu_on(identifier))
    assert verdict["status"] == "BLOCKED_INFRA_DISABLED"
    assert "fereastra Decizii" in verdict["reason"]


def test_switching_on_follows_the_stop_first(engine, monkeypatch):
    _, identifier = runpod(engine, monkeypatch, allow=True)
    policy(engine, autonomy_stopped=True, paid_media_approval="MODE")
    assert ask(engine, "infra.gpu_on", **gpu_on(identifier))["status"] == "BLOCKED_STOP"


def test_switching_on_inside_a_step_the_mode_lets_run(engine, monkeypatch):
    _, identifier = runpod(engine, monkeypatch, allow=True)
    policy(engine, paid_media_approval="MODE")  # AUTONOMOUS_CEO + MODE: stills run unasked
    assert ask(engine, "infra.gpu_on", **gpu_on(identifier))["allowed"]
    policy(engine, autonomy_mode="MANUAL")
    refused = ask(engine, "infra.gpu_on", **gpu_on(identifier))
    assert refused["status"] == "BLOCKED_NOT_IN_STEP"
    # His own press on the sheet passes the mode's refusal, as the step itself does.
    assert ask(engine, "infra.gpu_on", **gpu_on(identifier, owner_press=True))["allowed"]


def test_switching_on_with_his_yes_for_this_plan(engine, monkeypatch):
    _, identifier = runpod(engine, monkeypatch, allow=True)
    # EVERY_PAID_STEP (the default): the step asks him; his yes for this plan opens the GPU.
    assert ask(engine, "infra.gpu_on", **gpu_on(identifier))["status"] == "BLOCKED_NOT_IN_STEP"
    approval_id = str(uuid4())
    now = datetime.now(UTC)
    with Session(engine) as session, session.begin():
        session.add(
            ApprovalRequest(
                id=approval_id,
                action="media.stills_purchase",
                subject="film-1",
                requester="director",
                risk_tier="T2",
                evidence=None,
                proposed_diff={"plan_hash": "plan-1", "step": "stills", "cap_credits": None},
                cost_usd=2.0,
                expires_at=(now + timedelta(hours=48)).isoformat(),
                result="APPROVED",
                created_at=now.isoformat(),
                consumed_at=now.isoformat(),
            )
        )
    assert ask(engine, "infra.gpu_on", **gpu_on(identifier, approval_id=approval_id))["allowed"]
    other_plan = gpu_on(identifier, approval_id=approval_id, plan_hash="plan-2")
    assert ask(engine, "infra.gpu_on", **other_plan)["status"] == "BLOCKED_NOT_IN_STEP"
    other_step = gpu_on(identifier, approval_id=approval_id, step_action="media.motion_purchase")
    assert ask(engine, "infra.gpu_on", **other_step)["status"] == "BLOCKED_NOT_IN_STEP"


def test_switching_on_writes_nothing_and_spends_nothing(engine, monkeypatch):
    _, identifier = runpod(engine, monkeypatch, allow=True)
    ask(engine, "infra.gpu_on", **gpu_on(identifier, owner_press=True))
    with Session(engine) as session:
        assert session.scalars(select(ApprovalRequest)).first() is None


# ------------------------------------------------------------------------------- the cards


def cards(engine, kind: str) -> list[OwnerDecision]:
    with Session(engine) as session:
        found = list(session.scalars(select(OwnerDecision).where(OwnerDecision.kind == kind)))
        for row in found:
            session.expunge(row)
        return found


def test_the_seed_asks_for_the_runpod_card_and_his_accept_enables_it(engine, monkeypatch):
    _, identifier = runpod(engine, monkeypatch)
    seed_owner_decisions(engine)
    (card,) = cards(engine, "runpod_infra_actions")
    assert card.dedupe_key == f"runpod_infra_actions:{identifier}"
    assert card.title_ro == "Agenții pot porni singuri GPU-ul RunPod în pașii plătiți aprobați?"
    assert "4 USD/oră" in card.effect_ro and "STOP AUTONOMIE" in card.effect_ro
    labels = [o["label_ro"] for o in card.options]
    assert labels == ["Da, doar în pașii aprobați", "Nu încă"]
    (ltx,) = cards(engine, "runpod_ltx_licence")
    assert "LTX-2.5" in ltx.title_ro and ltx.options[0]["apply"]["type"] == "guided"
    decide_owner_decision(
        engine,
        card.id,
        DecideCommand(
            command_id=uuid4(), expected_version=card.version, decision="ACCEPT", option_key="yes"
        ),
        issued_by="owner",
    )
    with Session(engine) as session:
        row = session.get(Integration, identifier)
        assert row.config["allow_infra_actions"] == "true"
        assert row.config["stills_endpoint_id"] == "ep-stills"
    with Session(engine) as session:
        done = session.get(OwnerDecision, card.id)
        assert condition_reading(session, done) == "MET"
    # A second seed does not ask again; a save of the form keeps his answer.
    seed_owner_decisions(engine)
    assert len(cards(engine, "runpod_infra_actions")) == 1
    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    with Session(engine) as session:
        version = session.get(Integration, identifier).version
    save(
        engine,
        vault,
        identifier,
        SaveIntegration(
            kind="runpod",
            name="RunPod",
            expected_version=version,
            config={"stills_endpoint_id": "ep-new"},
        ),
    )
    with Session(engine) as session:
        assert session.get(Integration, identifier).config["allow_infra_actions"] == "true"


def test_the_runpod_card_applier_is_idempotent(engine, monkeypatch):
    from app.decisions.sources import apply_runpod_infra

    _, identifier = runpod(engine, monkeypatch)
    inner = str(uuid4())
    spec = {"type": "runpod_infra", "to": True, "integration_id": identifier}
    first = apply_runpod_infra(engine, spec, inner, {})
    second = apply_runpod_infra(engine, spec, inner, {})
    assert first == second and first["command"] == "EnableRunPodInfra"
    with Session(engine) as session:
        assert session.get(Integration, identifier).version == 2


def test_no_card_for_a_simulation_or_an_enabled_connection(engine, monkeypatch):
    runpod(engine, monkeypatch, mock="true")
    runpod(engine, monkeypatch, allow=True)
    seed_owner_decisions(engine)
    assert cards(engine, "runpod_infra_actions") == []


def test_the_form_refuses_the_card_flag(engine, monkeypatch):
    with pytest.raises(ValueError):
        runpod(engine, monkeypatch, allow_infra_actions="true")


# ------------------------------------------------------------------------------- the routes


def test_routes_read_the_gpu_and_switch_it_off_once(client, headers, engine, monkeypatch):
    vault, _ = runpod(engine, monkeypatch, allow=True)
    fake = Fake(workers_max=1)
    real = gpu_session.EndpointControl

    def faked(config, endpoint_id, transport=None, **kwargs):
        return real(config, endpoint_id, fake, **kwargs)

    monkeypatch.setattr(gpu_session, "EndpointControl", faked)
    policy(engine, autonomy_stopped=True)
    status = client.get("/api/v1/runpod/gpu", headers=headers)
    assert status.status_code == 200
    body = status.json()
    assert body["configured"] and body["rate_usd_per_hour"] == "4.00"
    command = {"schema_version": 1, "command_id": str(uuid4())}
    first = client.post("/api/v1/runpod/gpu/off", headers=headers, json=command)
    assert first.status_code == 200, first.text
    answer = first.json()
    assert answer["verified"] and len(answer["readings"]) == 2
    assert answer["words_ro"]
    calls = len(fake.calls)
    again = client.post("/api/v1/runpod/gpu/off", headers=headers, json=command)
    assert again.json() == answer and len(fake.calls) == calls
    assert client.post("/api/v1/runpod/gpu/off", json=command).status_code in (401, 403)
    bad = client.post("/api/v1/runpod/gpu/off", headers=headers, json={"command_id": "x"})
    assert bad.status_code == 422
