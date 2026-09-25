"""The two routes the page's new controls call, as the page will call them (W34).

The price form in Trezorerie → Prețurile modelelor calls ``PUT /economy/prices``; the switch
for the Director's leave in Setări → Canale calls ``POST /publishing/channels/{id}/publish-
policy``. Until W33 neither had a control, so neither route had been read for what a page
shows: their refusals said «Command ID already used with different input», «Name the resource
the price is for.», named the field ``public_publish_enabled`` and sent the Owner to «pagina
Owner», which the page does not have. Asserted here: the request and answer shapes the page is
built against, the versioning (a stale version and a reused command id are both 409, in
Romanian), and that a price typed and a leave given turn their preflight lines green.
"""

from __future__ import annotations

from uuid import uuid4

from app.agents.services import seed_initial_workforce
from app.integrations.vault import CredentialVault
from app.models import OwnerPolicy
from app.publishing.services import list_channels, seed_default_channels
from app.runbook.preflight import run_preflight
from app.wording import COMMAND_REUSED
from sqlalchemy.orm import Session

PRICE_VIEW = {
    "id",
    "provider_kind",
    "resource",
    "unit",
    "usd",
    "usd_micros",
    "provenance",
    "version",
    "active",
    "set_by",
    "notes",
    "set_at",
    "replaced_at",
}


def _line(engine, settings, tmp_path, name: str) -> dict:
    vault = CredentialVault(tmp_path / "routes.credentials.key")
    result = run_preflight(engine, settings, vault)
    return next(c for c in result["checks"] if c["name"] == name)


def _romanian(detail: object) -> None:
    text = str(detail)
    assert "Command ID" not in text and "different input" not in text, text
    assert any(mark in text for mark in "ăâîșț"), text


# ------------------------------------------------------------------ PUT /economy/prices


def test_the_price_form_types_both_sides_and_the_line_turns_green(
    client, headers, engine, settings, tmp_path
):
    seed_initial_workforce(engine)
    unpriced = _line(engine, settings, tmp_path, "model_prices")["value"]["unpriced"]
    assert unpriced
    for model in unpriced:
        for unit in model["missing_units"]:
            answer = client.put(
                "/api/v1/economy/prices",
                headers=headers,
                json={
                    "command_id": str(uuid4()),
                    "provider_kind": model["provider_kind"],
                    "resource": model["resource"],
                    "unit": unit,
                    "usd": "0.15",
                },
            )
            assert answer.status_code == 200, answer.text
            view = answer.json()
            assert set(view) == PRICE_VIEW
            assert (view["version"], view["provenance"], view["active"]) == (1, "OWNER", True)
            assert view["usd"] == "0.15" and view["usd_micros"] == 150_000
            assert view["set_by"] == "owner" and view["replaced_at"] is None
    listed = client.get("/api/v1/economy/prices", headers=headers).json()
    assert set(listed) == {"prices"}
    assert all(set(row) == PRICE_VIEW for row in listed["prices"])
    prices = _line(engine, settings, tmp_path, "model_prices")
    assert prices["ok"] is True and prices["value"]["unpriced"] == []


def test_a_price_changed_twice_from_one_screen_is_refused_in_romanian(client, headers):
    body = {
        "command_id": str(uuid4()),
        "provider_kind": "ollama",
        "resource": "gpt-oss:120b-cloud",
        "unit": "per_1m_output_tokens",
        "usd": "0.6",
    }
    assert client.put("/api/v1/economy/prices", headers=headers, json=body).status_code == 200

    reused = client.put("/api/v1/economy/prices", headers=headers, json={**body, "usd": "0.7"})
    assert reused.status_code == 409
    assert reused.json()["detail"] == COMMAND_REUSED
    _romanian(reused.json()["detail"])

    stale = client.put(
        "/api/v1/economy/prices",
        headers=headers,
        json={**body, "command_id": str(uuid4()), "usd": "0.7", "expected_version": 2},
    )
    assert stale.status_code == 409
    assert "versiunea 1" in stale.json()["detail"]
    _romanian(stale.json()["detail"])

    first_of_its_kind = client.put(
        "/api/v1/economy/prices",
        headers=headers,
        json={**body, "command_id": str(uuid4()), "resource": "new-model", "expected_version": 1},
    )
    assert first_of_its_kind.status_code == 409
    assert "nesetată" in first_of_its_kind.json()["detail"]


def test_a_blank_resource_is_a_field_the_form_marks_not_a_conflict(client, headers):
    answer = client.put(
        "/api/v1/economy/prices",
        headers=headers,
        json={
            "command_id": str(uuid4()),
            "provider_kind": "ollama",
            "resource": "   ",
            "unit": "per_1m_input_tokens",
            "usd": "0.1",
        },
    )
    assert answer.status_code == 422
    (item,) = answer.json()["detail"]
    assert item["loc"] == ["body", "resource"]
    assert set(item) == {"type", "loc", "msg"}


def test_a_malformed_amount_or_unit_is_named_by_its_field(client, headers):
    body = {
        "command_id": str(uuid4()),
        "provider_kind": "ollama",
        "resource": "m",
        "unit": "per_1m_input_tokens",
        "usd": "0.1",
    }
    for field, bad in (
        ("usd", "1,5"),
        ("usd", "-1"),
        ("unit", "per_token"),
        ("provider_kind", "Ollama"),
    ):
        answer = client.put("/api/v1/economy/prices", headers=headers, json={**body, field: bad})
        assert answer.status_code == 422, (field, bad)
        assert [item["loc"] for item in answer.json()["detail"]] == [["body", field]]


# ------------------------------------------------------------------ POST .../publish-policy


def _serial(engine) -> dict:
    seed_default_channels(engine)
    return next(c for c in list_channels(engine) if c["channel_type"] == "OFFICE_SERIAL")


def test_the_leave_switch_is_one_field_and_answers_the_channel(client, headers, engine):
    serial = _serial(engine)
    assert serial["director_may_approve_episodes"] is False
    url = f"/api/v1/publishing/channels/{serial['id']}/publish-policy"
    body = {
        "command_id": str(uuid4()),
        "expected_version": serial["policy_version"],
        "director_may_approve_episodes": True,
    }
    given = client.post(url, headers=headers, json=body)
    assert given.status_code == 200, given.text
    answer = given.json()
    assert set(answer) == {"command_id", "status", "channel", "event_id"}
    assert answer["status"] == "COMMITTED" and answer["event_id"]
    assert answer["channel"]["director_may_approve_episodes"] is True
    assert answer["channel"]["policy_version"] == serial["policy_version"] + 1
    # Nothing else of the policy moved.
    for key in ("autonomous_privacy", "public_publish_enabled", "publish_delay_minutes"):
        assert answer["channel"][key] == serial[key], key

    # The same click again (a retry) is the same answer.
    assert client.post(url, headers=headers, json=body).json() == answer
    # The same command id taking the leave back is a mistake, said in Romanian.
    reused = client.post(
        url, headers=headers, json={**body, "director_may_approve_episodes": False}
    )
    assert reused.status_code == 409 and reused.json()["detail"] == COMMAND_REUSED
    # A screen that read version 1 cannot take it back after another screen gave it.
    stale = client.post(
        url,
        headers=headers,
        json={**body, "command_id": str(uuid4()), "director_may_approve_episodes": False},
    )
    assert stale.status_code == 409
    _romanian(stale.json()["detail"])
    # Taken back at the version it is now: COMMITTED, and the version moves again.
    back = client.post(
        url,
        headers=headers,
        json={
            "command_id": str(uuid4()),
            "expected_version": answer["channel"]["policy_version"],
            "director_may_approve_episodes": False,
        },
    )
    assert back.status_code == 200
    assert back.json()["channel"]["director_may_approve_episodes"] is False
    assert back.json()["channel"]["policy_version"] == serial["policy_version"] + 2


def test_the_public_refusals_name_the_pages_switch_and_no_field(client, headers, engine):
    _serial(engine)
    main = next(c for c in list_channels(engine) if c["channel_type"] == "MAIN_FACTUAL")
    url = f"/api/v1/publishing/channels/{main['id']}/publish-policy"
    in_test = client.post(
        url,
        headers=headers,
        json={
            "command_id": str(uuid4()),
            "expected_version": 1,
            "autonomous_privacy": "public",
            "public_publish_enabled": True,
        },
    )
    assert in_test.status_code == 422
    detail = in_test.json()["detail"]
    assert "comutatorul MEDIU" in detail and "pagina Owner" not in detail

    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).environment = "PRODUCTION"
    no_flag = client.post(
        url,
        headers=headers,
        json={"command_id": str(uuid4()), "expected_version": 1, "autonomous_privacy": "public"},
    )
    assert no_flag.status_code == 422
    assert "public_publish_enabled" not in no_flag.json()["detail"]
    _romanian(no_flag.json()["detail"])
