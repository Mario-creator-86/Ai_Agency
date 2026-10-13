"""The Owner's «Oprește GPU acum» holds until he allows the GPU again (2026-10-12).

16:52:08 he pressed it while the Director's repair of Higgs-2's scene 5 was buying a clip; the
clip was cancelled and 25 s later the same walk opened a new GPU session and bought the same clip
again. Now his press is a hold: no paid step switches the GPU on (precheck and open_session refuse
OWNER_HOLD, nothing sent), his card «Permite din nou pașii plătiți» is the one way back, and a
simulation is never held (it switches nothing on). Every RunPod call goes to a fake transport."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.decisions.models import OwnerDecision
from app.decisions.producers.gpu_hold import DEDUPE_KEY, KIND
from app.decisions.services import DecideCommand, condition_reading, decide_owner_decision
from app.providers.runpod import gpu_session
from app.providers.runpod.gpu_session import (
    OWNER_HOLD,
    GpuSessionRefused,
    open_session,
    owner_hold_active,
    precheck,
)
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_runpod_gpu_control import (  # noqa: F401 - fixtures
    Fake,
    adapter,
    no_wait,
    permit,
    rows,
    running_studio,
    studio_integration,
)
from test_runpod_gpu_policy import runpod


def _card(engine) -> OwnerDecision | None:
    with Session(engine) as session:
        row = session.scalar(
            select(OwnerDecision).where(
                OwnerDecision.kind == KIND, OwnerDecision.dedupe_key == DEDUPE_KEY
            )
        )
        if row is not None:
            session.expunge(row)
        return row


def test_his_press_holds_and_no_paid_step_switches_the_gpu_on(
    client, headers, engine, tmp_path, monkeypatch
):
    vault, identifier = runpod(engine, monkeypatch, allow=True)
    fake = Fake(workers_max=1)
    real = gpu_session.EndpointControl

    def faked(config, endpoint_id, transport=None, **kwargs):
        return real(config, endpoint_id, fake, **kwargs)

    monkeypatch.setattr(gpu_session, "EndpointControl", faked)
    assert not owner_hold_active(engine)

    command = {"schema_version": 1, "command_id": str(uuid4())}
    pressed = client.post("/api/v1/runpod/gpu/off", headers=headers, json=command)
    assert pressed.status_code == 200, pressed.text
    answer = pressed.json()
    assert answer["hold"] is True and answer["card_id"]
    assert "până permiți din nou" in answer["words_ro"]
    assert owner_hold_active(engine)

    # The walk's next paid step: refused before anything is asked, sent or switched on.
    calls = len(fake.calls)
    with pytest.raises(GpuSessionRefused) as refused:
        precheck(engine, adapter(identifier), purpose="video", integration_id=identifier)
    assert refused.value.code == OWNER_HOLD
    with pytest.raises(GpuSessionRefused) as refused:
        open_session(
            engine, adapter(identifier), purpose="video", permit=permit(identifier), transport=fake
        )
    assert refused.value.code == OWNER_HOLD and "permiți din nou" in refused.value.reason_ro
    assert len(fake.calls) == calls, "a held step reached RunPod"
    assert rows(engine) == [], "a held step opened a GPU session"

    # His card: one way back, and it closes itself once the hold is lifted.
    card = _card(engine)
    assert card is not None and card.status == "PENDING"
    assert [option["key"] for option in card.options] == ["allow"]
    with Session(engine) as session:
        assert condition_reading(session, card, None) != "MET"
    done = decide_owner_decision(
        engine,
        card.id,
        DecideCommand(
            command_id=uuid4(), expected_version=card.version, decision="ACCEPT", option_key="allow"
        ),
        issued_by="owner",
    )
    assert done["decision"]["status"] in ("APPLIED", "DONE", "COMPLETED", "ACCEPTED"), done
    assert not owner_hold_active(engine)
    session = open_session(
        engine, adapter(identifier), purpose="video", permit=permit(identifier), transport=fake
    )
    assert session.endpoint_id == "ep-motion"


def test_the_switch_names_the_film_the_scene_and_the_take(engine):
    """«GPU pornit, worker activ · pas: scene_redo» — «Ce lucrează? Pentru ce film, ce cadru?»"""
    from app.media.models import SceneTake, Storyboard
    from app.providers.runpod.gpu_session import GpuSessionRow, _session_words
    from app.services import utc_now
    from test_director_decides_qc import failed_film

    film = failed_film(engine, local_move=False)
    now = utc_now()
    with Session(engine) as session, session.begin():
        session.get(Storyboard, film["board"]).title = "Storyboard: The Particle"
        session.add(
            SceneTake(
                id=str(uuid4()),
                storyboard_id=film["board"],
                scene_number=5,
                kind="motion",
                prompt_hash=uuid4().hex,
                model_id="LTX-2.5",
                resolution="1080:1920",
                status="SUBMITTED",
                created_at=now,
                updated_at=now,
            )
        )
    row = GpuSessionRow(step="scene_redo", storyboard_id=film["board"])
    with Session(engine) as session:
        assert _session_words(session, row) == "«The Particle»: refacerea — clipul scenei 5"
        assert _session_words(session, GpuSessionRow(step="stills", storyboard_id=None)) == (
            "imaginile"
        )


def test_a_simulation_is_never_held(engine):
    gpu_session.set_owner_hold(engine, True, by="owner", command_id=str(uuid4()))
    session = open_session(
        engine, adapter(None, mock=True), purpose="image", permit=permit(None), transport=None
    )
    assert session.mock
    precheck(engine, adapter(None, mock=True), purpose="image")  # nothing raised


def test_his_allow_on_the_switch_lifts_the_hold_like_the_card(client, headers, engine, monkeypatch):
    """«De unde îl pornesc? Din același loc din care îl opresc!» (the Owner, 2026-10-12)."""
    vault, identifier = runpod(engine, monkeypatch, allow=True)
    fake = Fake(workers_max=1)
    real = gpu_session.EndpointControl

    def faked(config, endpoint_id, transport=None, **kwargs):
        return real(config, endpoint_id, fake, **kwargs)

    monkeypatch.setattr(gpu_session, "EndpointControl", faked)
    off = client.post(
        "/api/v1/runpod/gpu/off",
        headers=headers,
        json={"schema_version": 1, "command_id": str(uuid4())},
    ).json()
    assert off["hold"] is True and "Permite GPU din nou" in off["words_ro"]
    assert owner_hold_active(engine)
    assert client.get("/api/v1/runpod/gpu", headers=headers).json()["owner_hold"] is True

    status = client.get("/api/v1/runpod/gpu", headers=headers).json()
    assert status["owner_hold_since"] and status["allow_after_stop_seconds"] == 20

    # 19:48 UTC, 2026-10-12: a second press 7 s after his stop lifted the hold and the refused clip
    # was bought again. Within 20 s of a stop, the allow is refused and nothing is recorded.
    command = {"schema_version": 1, "command_id": str(uuid4())}
    too_soon = client.post("/api/v1/runpod/gpu/allow", headers=headers, json=command)
    assert too_soon.status_code == 409, too_soon.text
    assert "20" in too_soon.json()["detail"] or "peste" in too_soon.json()["detail"]
    assert owner_hold_active(engine)

    # 30 s later (the record is immutable: the clock moves instead), his press is a new decision
    later = datetime.now(UTC) + timedelta(seconds=30)
    from app.providers.runpod import router as runpod_router

    monkeypatch.setattr(
        runpod_router,
        "seconds_since_hold",
        lambda engine: gpu_session.seconds_since_hold(engine, later),
    )
    command = {"schema_version": 1, "command_id": str(uuid4())}
    calls = len(fake.calls)
    allowed = client.post("/api/v1/runpod/gpu/allow", headers=headers, json=command)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["hold"] is False and "Ai permis din nou" in allowed.json()["words_ro"]
    assert len(fake.calls) == calls, "allowing switched something on at RunPod"
    assert not owner_hold_active(engine)
    assert client.get("/api/v1/runpod/gpu", headers=headers).json()["owner_hold"] is False
    # the same press again answers the same, and the card closes by its own condition
    again = client.post("/api/v1/runpod/gpu/allow", headers=headers, json=command)
    assert again.json() == allowed.json()
    card = _card(engine)
    with Session(engine) as session:
        assert condition_reading(session, card, None) == "MET"
    # the next paid step may switch the GPU on again
    session = open_session(
        engine, adapter(identifier), purpose="video", permit=permit(identifier), transport=fake
    )
    assert session.endpoint_id == "ep-motion"


def test_allow_needs_the_owner(client, engine):
    answer = client.post(
        "/api/v1/runpod/gpu/allow", json={"schema_version": 1, "command_id": str(uuid4())}
    )
    assert answer.status_code in (401, 403)


def test_a_second_press_keeps_one_card(client, headers, engine, monkeypatch):
    runpod(engine, monkeypatch, allow=True)
    fake = Fake(workers_max=0)
    real = gpu_session.EndpointControl

    def faked(config, endpoint_id, transport=None, **kwargs):
        return real(config, endpoint_id, fake, **kwargs)

    monkeypatch.setattr(gpu_session, "EndpointControl", faked)
    first = client.post(
        "/api/v1/runpod/gpu/off",
        headers=headers,
        json={"schema_version": 1, "command_id": str(uuid4())},
    ).json()
    second = client.post(
        "/api/v1/runpod/gpu/off",
        headers=headers,
        json={"schema_version": 1, "command_id": str(uuid4())},
    ).json()
    assert first["card_id"] == second["card_id"]
    assert owner_hold_active(engine)
