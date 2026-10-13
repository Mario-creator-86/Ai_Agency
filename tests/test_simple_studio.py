"""The simplified product retires virtual finance without removing spend safeguards."""

from uuid import uuid4

import pytest
from app.economy.services import seed_chart_of_accounts, treasury_snapshot


@pytest.mark.parametrize(
    "path",
    ["treasury", "accounts", "ledger", "evidence", "owner-funding", "as-of", "fx"],
)
def test_virtual_finance_is_absent_from_the_public_contract(client, path):
    schema = client.app.app.openapi()
    assert f"/api/v1/economy/{path}" not in schema["paths"]


def test_finance_commands_cannot_mutate_preserved_books(client, headers, engine):
    seed_chart_of_accounts(engine)
    before = treasury_snapshot(engine)
    for path in ("evidence", "owner-funding", "evidence/example/mint", "fx"):
        response = client.post(
            f"/api/v1/economy/{path}",
            headers=headers,
            json={"command_id": str(uuid4()), "amount": "100"},
        )
        assert response.status_code in (404, 405)
    assert treasury_snapshot(engine) == before


@pytest.mark.parametrize("path", ["budget", "prices", "provider-costs", "reconciliations"])
def test_real_cost_settings_remain_owner_only(client, headers, path):
    assert client.get(f"/api/v1/economy/{path}").status_code == 401
    response = client.get(f"/api/v1/economy/{path}", headers=headers)
    assert response.status_code == 200, response.text


def test_snapshot_lists_only_active_product_features(client, headers):
    response = client.get("/api/v1/snapshot", headers=headers)
    assert response.status_code == 200
    modules = response.json()["modules"]
    assert {"agents", "providers", "workflows", "media", "publishing", "settings"} <= set(modules)
    assert not {"treasury", "financing", "procurement"} & set(modules)


def test_invalid_usd_budget_is_rejected_before_mutation(client, headers):
    before = client.get("/api/v1/economy/budget", headers=headers).json()
    response = client.put(
        "/api/v1/economy/budget",
        headers=headers,
        json={"command_id": str(uuid4()), "period": "DAILY", "limit_usd": "1,000.00"},
    )
    assert response.status_code == 422
    after = client.get("/api/v1/economy/budget", headers=headers).json()
    before.pop("measured_at")
    after.pop("measured_at")
    assert after == before
