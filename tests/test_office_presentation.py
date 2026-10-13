from copy import deepcopy

import pytest
from app.office.presentation import agent_presentation, monitor_media


@pytest.mark.parametrize(
    "state,action",
    [
        ("IDLE", "coffee"),
        ("WORKING", "type"),
        ("THINKING", "think"),
        ("REVIEWING", "read"),
        ("ERROR", "frustrated"),
        ("BLOCKED", "frustrated"),
    ],
)
def test_presentation_follows_actual_state_and_never_mutates_it(state, action):
    agent = {
        "agent_id": "test-employee",
        "runtime_state": state,
        "lifecycle": "ACTIVE",
        "version": 9,
    }
    original = deepcopy(agent)
    plan = agent_presentation(agent, 100000)
    assert plan["runtime_state"] == state and plan["version"] == 9
    assert action in [a[0] for a in plan["cycle"]]
    assert plan["kind"] == "presentation_only"
    assert (
        "frustrated" not in [a[0] for a in plan["cycle"]]
        if state not in ["ERROR", "BLOCKED"]
        else True
    )
    assert agent == original


@pytest.mark.parametrize(
    "lifecycle,state",
    [("PAUSED", "WORKING"), ("SUSPENDED", "THINKING"), ("HIRED", "IDLE"), ("ACTIVE", "UNKNOWN")],
)
def test_unknown_or_paused_has_no_fabricated_work(lifecycle, state):
    plan = agent_presentation(
        {"agent_id": "test", "runtime_state": state, "lifecycle": lifecycle}, 1000
    )
    assert plan["cycle"] == [] and plan["monitor"] == "off"


def test_each_employee_has_a_stable_individual_phase():
    def plan(i, at):
        return agent_presentation(
            {"agent_id": str(i), "runtime_state": "IDLE", "lifecycle": "ACTIVE"}, at
        )

    phases = [plan(i, 123456)["phase_ms"] for i in range(8)]
    assert len(set(phases)) == 8
    total = sum(ms for _, ms in plan(0, 0)["cycle"])
    for i in range(8):
        assert plan(i, 124456)["phase_ms"] == (phases[i] + 1000) % total


def test_endpoint_is_owner_only_and_read_only(client, headers):
    assert client.get("/api/v1/office/presentation").status_code == 401
    before = client.get("/api/v1/office/layout", headers=headers).json()["assignments"]
    response = client.get("/api/v1/office/presentation", headers=headers)
    assert response.status_code == 200
    snapshot = response.json()
    assert snapshot["schema"] == 1 and snapshot["valid_ms"] > 10000
    assert {a["agent_id"] for a in snapshot["agents"]} == {a["agent_id"] for a in before}
    assert client.get("/api/v1/office/layout", headers=headers).json()["assignments"] == before
    assert snapshot["media"]["youtube"] == []


def test_snapshot_does_not_call_weather_or_external_media(client, headers, no_network):
    response = client.get("/api/v1/office/presentation", headers=headers)
    assert response.status_code == 200
    assert not no_network.refused


def test_monitor_library_refuses_missing_outside_fake_and_oversized_files(engine, tmp_path):
    from app.media.models import MediaAsset
    from sqlalchemy.orm import Session

    allowed = tmp_path / "media"
    allowed.mkdir()
    good = allowed / "local.mp4"
    good.write_bytes(b"fixture-video-bytes")
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"not-shareable")
    oversized = allowed / "oversized.mp4"
    with oversized.open("wb") as file:
        file.truncate(64 * 1024 * 1024 + 1)
    with Session(engine) as session, session.begin():
        for i, path, provider in [
            ("good", good, "STUDIO_INTERNAL"),
            ("outside", outside, "STUDIO_INTERNAL"),
            ("fake", good, "FAKE"),
            ("missing", allowed / "gone.mp4", "STUDIO_INTERNAL"),
        ]:
            session.add(
                MediaAsset(
                    id=i,
                    asset_type="RENDERED_VIDEO",
                    uri_or_path=str(path),
                    mime_type="video/mp4",
                    file_size_bytes=1,
                    provider_name=provider,
                    provenance_hash="0" * 64,
                    created_at="2026-10-09T12:00:00Z",
                )
            )
        session.add(
            MediaAsset(
                id="oversized",
                asset_type="RENDERED_VIDEO",
                uri_or_path=str(oversized),
                mime_type="video/mp4",
                file_size_bytes=1,
                provider_name="STUDIO_INTERNAL",
                provenance_hash="0" * 64,
                created_at="2026-10-09T12:00:00Z",
            )
        )
    result = monitor_media(engine, [allowed])
    assert [a["id"] for a in result["local"]] == ["good"]
    assert result["local"][0]["size"] == good.stat().st_size
    assert str(allowed) not in str(result)


def test_iframe_csp_is_restricted_to_real_youtube_player(client):
    response = client.get("/health/live")
    policy = response.headers["Content-Security-Policy"]
    assert "frame-src https://www.youtube-nocookie.com;" in policy
    assert "script-src 'self';" in policy and "frame-ancestors 'none';" in policy
