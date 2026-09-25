"""What the Phase D/G closure left open, attacked from the outside.

The closure gave the Owner a route to answer an approval, a column to spend it once, and a
stage that reads the answer. Each of those was proved by its author, at the level it was
written: `tests/test_approvals.py` holds `may_act` to the rule, and `tests/test_daily_run_
stages.py` holds the publish stage to it. These tests take the other side, and every one of
them is a place where the two levels could disagree:

- the Owner's yes is carried *into the stage* and the hard gates above it — the Director's
  verdict, the publishing gate's autonomy check, an incident — are each asked to let a film
  past on it. They must refuse, and each refusal must leave the yes unspent, because none of
  them is the Owner changing his mind;
- the stop is deliberately not read by `mode_refusal`, which is the one place in the tree
  where a stop is reported as no refusal. That is only safe because something below it reads
  the stop, so the stage is run under a stop with an approval in hand and asked to upload;
- who may write an answer is proved by a *whole-tree* scan rather than by the two routes that
  exist today, so a third writer added later cannot pass by not being on a list;
- a question the Owner is shown must describe the state the studio is actually in, or he
  answers one thing and the studio discards his answer for another;
- the Runway image adapter's own transport is held against the loopback guard, with an
  address that needs no DNS, so the proof costs nothing and touches nobody.

Nothing here contacts a provider, renders, uploads or spends: every vendor is faked at its
transport and `tests/conftest.py` refuses every non-loopback socket.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.agents.models import Capability, ModelCapability
from app.models import ApprovalRequest, OwnerPolicy
from app.providers.registry import ProviderRegistry
from app.providers.runway import RunwayImageAdapter
from app.runbook.models import SafeModeRecord
from app.runbook.stages import build_stage_runners
from app.schemas import ApprovalDecisionCommand, PolicyCommand
from app.services import change_stop, decide_approval, may_act, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_daily_run_stages import (
    _autonomy_on,
    _bound,
    _connected,
    _director_and_publisher_agree,
    _mode,
    _RecordingPublisher,
    _seeded_channels,
    _serial_film,
    _vault,
)

ROOT = Path(__file__).resolve().parents[1]
APPLICATION = ROOT / "backend" / "app"

PUBLISH = "publishing.public_publish"


# --------------------------------------------------------------------------- the fixtures --


def _supervised_studio(engine, settings, tmp_path, monkeypatch):
    """A SUPERVISED studio with one QC-passed film and its slot bound, and the runners the
    daily run would call. The same state `tests/test_daily_run_stages.py` builds; it is
    rebuilt here rather than imported so a change there cannot quietly weaken these."""
    _autonomy_on(engine)
    _mode(engine, "SUPERVISED")
    channels = _seeded_channels(engine)
    bundle = _serial_film(engine, tmp_path)
    _bound(engine, channels["OFFICE_SERIAL"]["id"], _connected(engine, "Serial account"))
    publisher = _RecordingPublisher()
    monkeypatch.setattr("app.runbook.stages.selected_youtube", lambda *a, **k: publisher)
    _director_and_publisher_agree(monkeypatch)
    runners = build_stage_runners(engine, settings, _vault(engine), ProviderRegistry())
    return runners, publisher, bundle


def _approvals(engine) -> list[ApprovalRequest]:
    with Session(engine) as session:
        return list(session.scalars(select(ApprovalRequest)))


def _the_owner_says_yes(engine, runners) -> ApprovalRequest:
    """One run of the publish stage to raise the question, and the Owner's APPROVED answer."""
    runners["publish"]()
    (request,) = _approvals(engine)
    decide_approval(
        engine,
        ApprovalDecisionCommand(command_id=uuid4(), approval_id=request.id, decision="APPROVED"),
    )
    return request


def _unspent(engine, approval_id: str) -> bool:
    with Session(engine) as session:
        request = session.get(ApprovalRequest, approval_id)
        return request.result == "APPROVED" and request.consumed_at is None


# ------------------------------------- an approval never opens a gate above it, in the stage --


def test_the_owners_yes_does_not_carry_a_film_past_the_directors_refusal(
    engine, settings, tmp_path, monkeypatch
):
    """31: an approval lets a permitted action happen; it never turns a refusal into a pass.

    The Director is asked before the mode ever is, so her refusal returns before the answer
    is even looked for — which is why the yes is still his afterwards. A stage that had read
    the approval first would have spent it on a film that never left the studio.
    """
    runners, publisher, _ = _supervised_studio(engine, settings, tmp_path, monkeypatch)
    request = _the_owner_says_yes(engine, runners)

    monkeypatch.setattr(
        "app.runbook.stages.latest_editorial",
        lambda session, asset_id: SimpleNamespace(
            verdict="REJECT", reasons_json=["Cadrul final este negru."]
        ),
    )
    refused = runners["publish"]()

    assert publisher.uploads == []
    assert refused["status"] == "COMPLETED", refused
    assert "Directorul" in refused["reason"]
    assert _unspent(engine, request.id), "the Director's refusal is not the Owner's answer"


def test_a_stop_after_the_owners_yes_still_refuses_the_upload_in_the_stage(
    engine, settings, tmp_path, monkeypatch
):
    """STOP AUTONOMY outranks everything and is never bypassable — including here, where
    `mode_refusal` deliberately reports a stop as no refusal so that the stop is not read in
    a wrapper alone. What makes that safe is the publishing gate's own first check, so the
    stage is run under a stop with an approved film in hand and asked to upload it.
    """
    runners, publisher, _ = _supervised_studio(engine, settings, tmp_path, monkeypatch)
    request = _the_owner_says_yes(engine, runners)

    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = True
    stopped = runners["publish"]()

    assert publisher.uploads == []
    assert stopped["status"] == "COMPLETED", stopped
    assert "Poarta de publicare" in stopped["reason"]
    assert "autonomy stop" in stopped["reason"].lower()
    # The stop pauses the studio; it does not retract what the Owner decided.
    assert _unspent(engine, request.id)


def test_an_incident_after_the_owners_yes_leaves_the_film_and_the_answer_where_they_are(
    engine, settings, tmp_path, monkeypatch
):
    """SAFE_MODE is for hard faults and allows T1: an upload is T3 whatever the Owner said
    about it. The refusal lands in the stage wrapper, above the stage, so the film is never
    even looked at — and the yes is untouched when the incident closes."""
    runners, publisher, _ = _supervised_studio(engine, settings, tmp_path, monkeypatch)
    request = _the_owner_says_yes(engine, runners)

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
    halted = runners["publish"]()

    assert publisher.uploads == []
    assert halted["status"] == "SKIPPED", halted
    assert "modul sigur" in halted["reason"]
    assert _unspent(engine, request.id)


# ------------------------------------------------- who may write an answer, across the tree --


def test_only_the_owners_command_module_reaches_an_approval_row():
    """A whole-tree scan rather than the two routes that exist today.

    The answer and its spending are what decide whether a film goes out on the Owner's
    authority. `backend/app/services.py` is where his versioned commands live, `models.py` is
    where the table is declared, and nothing else in the application may name the row at all
    — a writer added later in a router, an agent or a stage would be an authority nobody
    granted, and it would pass a test that only listed the writers of the day it was written.
    """
    readers = set()
    for path in APPLICATION.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "ApprovalRequest" not in source:
            continue
        # The scan reads the parsed module rather than its characters: a docstring that
        # explains where the Owner's question keeps its cost names the class without
        # reaching the row, and a test that could not tell the two apart would make the
        # invariant unwritable in prose. Names in code — an import, an attribute, a call —
        # are what would be an authority nobody granted.
        tree = ast.parse(source)
        for node in ast.walk(tree):
            named = (
                (isinstance(node, ast.ClassDef) and node.name == "ApprovalRequest")
                or (isinstance(node, ast.Name) and node.id == "ApprovalRequest")
                or (isinstance(node, ast.Attribute) and node.attr == "ApprovalRequest")
                or (
                    isinstance(node, ast.ImportFrom)
                    and any(alias.name == "ApprovalRequest" for alias in node.names)
                )
            )
            if named:
                readers.add(path.relative_to(ROOT).as_posix())
                break
    assert readers == {"backend/app/models.py", "backend/app/services.py"}, readers


def test_nothing_but_the_owners_command_reaches_the_decision_or_the_mode():
    """The two entry points that can move the Owner's own state, named once.

    `decide_approval` and `change_autonomy_mode` are called from `backend/app/main.py`, where
    the Owner's door is, and from nowhere else in the application. An agent, a stage or a
    seed that called either would be promoting itself.
    """
    callers = {
        path.relative_to(ROOT).as_posix()
        for path in APPLICATION.rglob("*.py")
        if any(
            name in path.read_text(encoding="utf-8")
            for name in ("decide_approval", "change_autonomy_mode")
        )
    }
    assert callers == {"backend/app/main.py", "backend/app/services.py"}, callers


def test_the_owners_two_approval_routes_are_his_alone(client, engine):
    """Without his key the list is not readable and no answer can be written. Asked here as
    well as in `tests/test_approvals.py` because a route moved out from behind
    `require_owner` would still pass a test that only checked the happy path."""
    assert client.get("/api/v1/owner/approvals").status_code in (401, 403)
    answer = client.post(
        "/api/v1/owner/approvals/decision",
        json={
            "schema_version": 1,
            "command_id": str(uuid4()),
            "approval_id": str(uuid4()),
            "decision": "APPROVED",
        },
    )
    assert answer.status_code in (401, 403)
    assert _approvals(engine) == []


# ------------------------------------------- the question he is shown describes the present --


def test_a_standing_question_is_reasked_when_the_state_it_named_has_moved(engine):
    """He must never be asked about a state the studio has left.

    A question stands for a day, and the channel policy can move inside that day. Keyed by
    the action and the subject alone, the standing PENDING row was handed back unchanged, so
    the Owner read a question naming the old policy version and the old visibility — and his
    answer to it was then discarded by `_answered_approval`, because the yes had been given
    about something else. Two wrongs that cancel into a safe outcome are still a question he
    answered for nothing. The row that named the stale state is closed and a fresh question
    naming the present one is raised instead.
    """
    change_stop(engine, PolicyCommand(command_id=uuid4(), expected_version=1, stopped=False))
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_mode = "SUPERVISED"

    def ask(policy_version: int, privacy: str) -> dict:
        with Session(engine) as session, session.begin():
            return may_act(
                session,
                PUBLISH,
                requester="publisher",
                subject="asset-1",
                evidence=f"Un film → Canal A ({privacy})",
                context={
                    "channel_id": "A",
                    "policy_version": policy_version,
                    "privacy_status": privacy,
                },
            )

    first = ask(1, "private")
    second = ask(2, "public")

    assert first["approval_id"] != second["approval_id"]
    with Session(engine) as session:
        stale = session.get(ApprovalRequest, first["approval_id"])
        fresh = session.get(ApprovalRequest, second["approval_id"])
    assert stale.result != "PENDING", "a question naming a state the studio has left still stands"
    assert fresh.result == "PENDING"
    assert fresh.proposed_diff["policy_version"] == 2
    assert fresh.proposed_diff["privacy_status"] == "public"


def test_the_same_question_about_the_same_state_is_still_one_question(engine):
    """And the other half of it: a day that asks twice about an unchanged film must not fill
    the Owner's list with copies of one decision."""
    change_stop(engine, PolicyCommand(command_id=uuid4(), expected_version=1, stopped=False))
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_mode = "SUPERVISED"

    def ask() -> dict:
        with Session(engine) as session, session.begin():
            return may_act(
                session,
                PUBLISH,
                requester="publisher",
                subject="asset-1",
                context={"channel_id": "A", "policy_version": 1, "privacy_status": "private"},
            )

    assert ask()["approval_id"] == ask()["approval_id"]
    assert len(_approvals(engine)) == 1


# ------------------------------------------------------ the vendor is never reached, still --


def test_the_loopback_guard_covers_the_runway_image_adapters_reference_transport(monkeypatch):
    """Invariant seven, for the path Phase D/G opened.

    `RunwayImageAdapter.generate_image` can now carry a character's reference sheet, which is
    the one new thing in the tree that could put a picture on the wire. The host is replaced
    with TEST-NET-3 (RFC 5737) for the length of the test, so nothing is resolved and the
    vendor cannot be reached even if the guard were gone: the point is that the adapter's
    transport goes through the socket `tests/conftest.py` holds, and that an unfaked call
    fails loudly with the address it tried. A `MediaProviderError` here would mean the guard
    had been swallowed by the retry policy as an ordinary network failure, and a real key
    could have gone out on a real run.
    """
    import asyncio

    monkeypatch.setattr("app.providers.runway.HOST", "203.0.113.9")
    adapter = RunwayImageAdapter(
        "k-never-sent",
        "gen4_image",
        {"tasks": ["text_to_image"], "ratios": {"text_to_image": ["1080:1920"]}},
    )
    with pytest.raises(AssertionError, match="must be faked at its transport"):
        asyncio.run(
            adapter.generate_image(
                "un birou la apus",
                extra={"reference_image": {"bytes": b"\x89PNG\r\n\x1a\n" + b"0" * 32}},
            )
        )


def test_no_reference_path_in_the_tree_claims_a_vendor_has_answered_it():
    """The Owner's rule: never mark a provider integration working on mocks. Every adapter
    that says it accepts a reference must also say the account has never confirmed it."""
    from app.providers.openai_media import OpenAIImageAdapter

    for adapter in (RunwayImageAdapter, OpenAIImageAdapter):
        assert getattr(adapter, "ACCEPTS_REFERENCE_IMAGE", False) is True
        assert getattr(adapter, "REFERENCE_IMAGE_VERIFIED", True) is False, (
            f"{adapter.__name__} claims a vendor has accepted a reference it has never sent"
        )


def test_the_suites_own_settings_can_never_name_the_owners_database(settings, engine):
    """No test may read or write the studio's real database.

    The `settings` fixture is where every engine in the suite comes from, and it is built
    with `_env_file=None` so a developer's own `.env` cannot reach into a test run. What this
    pins is the consequence: the database the suite migrates and bootstraps is under pytest's
    own tmp_path, and the application default — the studio's `data/` folder — is not it.
    """
    assert "/data/studio.db" not in settings.database_url.replace("\\", "/")
    assert engine.url.database is not None
    assert Path(engine.url.database).name == "test.db"


# ---------------------------- the Owner's own quality control certifies only what it measured --


def test_the_owners_own_quality_control_refuses_nothing_it_could_not_look_at(
    client, headers, engine, monkeypatch
):
    """The other half of the route that Phase D/G taught to see.

    Its author proved that the Owner's button now measures the pictures and fails a film
    whose third scene is a blank field. The rule 50 states is the other direction and is the
    one a caller is likely to break by accident: a check that could not run certifies
    nothing, so the verdict must be *exactly* what it would have been. This runs the same
    film three times through his own route — with a model that can see and says the pictures
    are right, with a registry whose model declares no vision, and with no registry at all —
    and holds the three verdicts against each other. The film this fixture builds fails on
    grounds that have nothing to do with the pictures — no file on disk, no captions — which
    is exactly why the comparison is the right shape: what must be identical is the status
    *and* the list of reasons, so the check is shown to add nothing in either direction
    whatever the film's own verdict is. A studio as `seed_initial_workforce` leaves it has no
    model declaring vision, so the second and third runs are what the Owner meets today.
    """
    from test_picture_qc import FRAMES, a_film, all_good, give_vision, registry_with, staff

    monkeypatch.setattr(
        "app.media.picture_qc.frames_for",
        lambda path, ffmpeg_path, duration, scene_seconds=None: list(FRAMES),
    )
    staffed = staff(engine)
    ids = a_film(engine)

    def qc() -> dict:
        response = client.post(f"/api/v1/media/qc/{ids['asset']}", headers=headers)
        assert response.status_code == 200, response.text
        return response.json()

    seeing, model = registry_with(staffed, lambda prompt: all_good())
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    client.app.app.state.registry = seeing
    measured = qc()

    blind, unused = registry_with(staff(engine), lambda prompt: all_good())
    with Session(engine) as session, session.begin():
        for capability in session.scalars(select(ModelCapability)):
            if session.get(Capability, capability.capability_id).name == "vision":
                session.delete(capability)
    client.app.app.state.registry = blind
    without_a_seeing_model = qc()

    client.app.app.state.registry = None
    without_a_registry = qc()

    assert measured["checks_json"]["picture_qc"]["status"] == "MEASURED"
    assert measured["checks_json"]["picture_qc"]["passed"] is True
    assert len(model.calls) == 1
    for stood_down in (without_a_seeing_model, without_a_registry):
        picture = stood_down["checks_json"]["picture_qc"]
        assert picture["status"] == "NOT_APPLICABLE", picture
        assert picture["passed"] is None and picture["detail"]
        assert stood_down["checks_json"]["character_drift_qc"]["passed"] is None
        # The whole of the invariant: the film's verdict is what the other gates left it.
        assert stood_down["status"] == measured["status"], stood_down["failure_reasons_json"]
        assert stood_down["failure_reasons_json"] == measured["failure_reasons_json"]
        assert not any(
            "Scene" in reason or "character" in reason
            for reason in stood_down["failure_reasons_json"]
        ), stood_down["failure_reasons_json"]
    # And nothing was asked of a model that cannot see.
    assert unused.calls == []
