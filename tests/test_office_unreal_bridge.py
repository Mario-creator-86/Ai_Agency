"""The live Unreal headquarters shows the employees the backend has, doing what it says."""

import json
from types import SimpleNamespace

import pytest
from app.office.unreal import (
    REFRESH_S,
    UnrealBridge,
    calls_for,
    desired_states,
    load_seats,
    remote_control_target,
)

SEATS = {
    "desk_director": {
        "actor": "/Game/HQ/HQ_Dusk.HQ_Dusk:PersistentLevel.BP_Sarah_C_0",
        "body": "/Game/HQ/HQ_Dusk.HQ_Dusk:PersistentLevel.BP_Sarah_C_0.Body",
        "animation": "/Game/AMN/People/Animations/Female_Sit_talk_Anim_MH.Female_Sit_talk_Anim_MH",
    },
    "desk_script": {
        "actor": "/Game/HQ/HQ_Dusk.HQ_Dusk:PersistentLevel.BP_Marcus_C_0",
        "body": "/Game/HQ/HQ_Dusk.HQ_Dusk:PersistentLevel.BP_Marcus_C_0.Body",
        "animation": "/Game/AMN/People/Animations/Male_Sit_talk_Anim_MH.Male_Sit_talk_Anim_MH",
    },
}


def layout(*assignments):
    return {"assignments": list(assignments)}


def agent(desk, runtime_state="IDLE", lifecycle="ACTIVE"):
    return {"desk_id": desk, "runtime_state": runtime_state, "lifecycle": lifecycle}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_a_desk_without_an_agent_shows_nobody():
    states = desired_states(layout(agent("desk_director", "WORKING")), SEATS)
    assert states == {
        "desk_director": {"visible": True, "moving": True},
        "desk_script": {"visible": False, "moving": False},
    }


@pytest.mark.parametrize(
    ("runtime_state", "lifecycle", "moving"),
    [
        ("WORKING", "ACTIVE", True),
        ("IDLE", "HIRED", True),
        ("WORKING", "PAUSED", False),
        ("THINKING", "SUSPENDED", False),
        (None, "ACTIVE", True),
    ],
)
def test_a_paused_or_suspended_agent_is_held_still(runtime_state, lifecycle, moving):
    states = desired_states(layout(agent("desk_script", runtime_state, lifecycle)), SEATS)
    assert states["desk_script"] == {"visible": True, "moving": moving}


def test_the_calls_hide_or_show_the_actor_and_set_the_body_moving_or_still():
    seat = SEATS["desk_director"]
    hidden = calls_for(seat, {"visible": False, "moving": False})
    assert hidden == [
        {
            "objectPath": seat["actor"],
            "functionName": "SetActorHiddenInGame",
            "parameters": {"bNewHidden": True},
            "generateTransaction": False,
        }
    ]
    still = calls_for(seat, {"visible": True, "moving": False})
    assert [c["functionName"] for c in still] == ["SetActorHiddenInGame", "SetPlayRate"]
    assert still[0]["parameters"] == {"bNewHidden": False}
    assert still[1] == {
        "objectPath": seat["body"],
        "functionName": "SetPlayRate",
        "parameters": {"Rate": 0.0},
        "generateTransaction": False,
    }
    assert calls_for(seat, {"visible": True, "moving": True})[1]["parameters"] == {"Rate": 1.0}


def test_only_what_changed_is_sent_again():
    sent = []
    clock = Clock()
    bridge = UnrealBridge(sent.append, clock)
    assert bridge.sync(layout(agent("desk_director", "WORKING")), SEATS) == 2
    assert len(sent) == 3  # director shown and moving; script desk hidden
    sent.clear()
    clock.now += 5
    assert bridge.sync(layout(agent("desk_director", "WORKING")), SEATS) == 0
    assert sent == []
    clock.now += 5
    assert bridge.sync(layout(agent("desk_director", "WORKING", "PAUSED")), SEATS) == 1
    assert [c["parameters"] for c in sent] == [{"bNewHidden": False}, {"Rate": 0.0}]


def test_after_unreal_fails_to_answer_everything_is_sent_again():
    sent = []
    down = {"now": True}

    def send(call):
        if down["now"]:
            raise ConnectionRefusedError("nothing on 30010")
        sent.append(call)

    clock = Clock()
    bridge = UnrealBridge(send, clock)
    assert bridge.sync(layout(agent("desk_director")), SEATS) == 0
    down["now"] = False
    clock.now += 5
    assert bridge.sync(layout(agent("desk_director")), SEATS) == 2
    assert len(sent) == 3


def test_everything_is_sent_again_after_a_while_in_case_unreal_restarted():
    sent = []
    clock = Clock()
    bridge = UnrealBridge(sent.append, clock)
    bridge.sync(layout(agent("desk_director")), SEATS)
    sent.clear()
    clock.now += REFRESH_S
    assert bridge.sync(layout(agent("desk_director")), SEATS) == 2


def test_the_seat_report_is_read_and_malformed_seats_are_ignored(tmp_path):
    report = tmp_path / "seat_report.json"
    report.write_text(
        json.dumps(
            {
                "level": "/Game/HQ/HQ_Dusk",
                "seats": [
                    {"desk": "desk_director", "name": "Sarah", **SEATS["desk_director"]},
                    {
                        "desk": "desk_audio",
                        "name": "Lyra",
                        "actor": "",
                        "body": "x",
                        "animation": "y",
                    },
                    "not a seat",
                ],
            }
        ),
        encoding="utf-8",
    )
    assert load_seats(report) == {"desk_director": SEATS["desk_director"]}
    assert load_seats(tmp_path / "missing.json") == {}
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    assert load_seats(tmp_path / "broken.json") == {}


def test_with_no_seats_nothing_is_sent():
    sent = []
    assert UnrealBridge(sent.append).sync(layout(agent("desk_director")), {}) == 0
    assert sent == []


@pytest.mark.parametrize(
    ("url", "target"),
    [
        ("http://127.0.0.1:30010", "http://127.0.0.1:30010"),
        (" http://127.0.0.1:30010/ ", "http://127.0.0.1:30010"),
        ("ws://127.0.0.1:30020", None),
        ("127.0.0.1:30010", None),
        ("", None),
        (None, None),
    ],
)
def test_only_an_http_address_counts_as_configured(url, target):
    assert remote_control_target(SimpleNamespace(office_unreal_remote_url=url)) == target
