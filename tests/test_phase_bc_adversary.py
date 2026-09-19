"""Phase B/C tried as an adversary: the rules the delivery and the serial must keep.

Each test here starts from a way the rule could be broken, not from what the code does:

- visibility: under the default policy both channels upload private, and a policy that says
  otherwise is honoured only in PRODUCTION — "unlisted" included, because an unlisted film
  is a film anyone with the link can watch; the old `upload_privacy_default` column a form
  fills is not the policy; the command cannot bring "public" back in TEST through the flag
  alone once the privacy already reads "public";
- routing: a storyboard that names Channel A by id while its series key says the serial is
  a contradiction and goes nowhere, in either direction;
- privacy: a price written currency-first, a link without a scheme and an uppercase key in
  a *safe* payload field never reach the showrunner; a leak in the episode's summary or an
  opened thread fails the Director's privacy check before it can enter canon and the next
  prompt;
- the Owner's leave: the flag on the factual channel is not the serial's;
- the stop: pressed while the factual film renders, the serial is not started;
- the budget: asked once per film;
- a closed log: new events on its date change nothing;
- the Director: a blank frame rejects a serial film as it rejects a factual one;
- quality control: loudness without a loudnorm-capable encoder and captions that break the
  rules fail the film, with the cause named.

Nothing here contacts a provider: the camera, the publisher and every model are faked at
the boundary the stage already uses, and `tests/conftest.py` refuses any socket that is not
loopback for the whole suite.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.agents.editorial import editorial_review, instructions_for
from app.agents.services import seed_initial_workforce
from app.media.models import Storyboard
from app.media.qc import evaluate_media_qc
from app.media.services import seed_default_character_bibles
from app.media.toolchain import find_ffmpeg
from app.models import DomainEvent, OwnerPolicy
from app.publishing.models import ChannelRecord
from app.publishing.services import (
    ROUTE_SELECTED,
    ROUTE_SKIPPED,
    PublishPolicyError,
    change_publish_policy,
    configure_channel,
    resolve_publish_visibility,
    seed_default_channels,
    select_channel_for,
)
from app.runbook import stages
from app.runbook.services import OWNER_STOP_REASON
from app.schemas import EnvironmentCommand
from app.services import change_environment
from app.story.models import DailyStudioLog, StoryEpisode
from app.story.review import review_episode
from app.story.serial_stage import run_serial_stage
from app.story.services import close_daily_log, ensure_projection, get_continuity, write_episode
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_daily_run_stages import (
    _approved_board,
    _bound,
    _connected,
    _director_and_publisher_agree,
    _media_stage_with_a_fake_camera,
    _RecordingPublisher,
    _seeded_channels,
    _serial_film,
)
from test_editorial import ENGLISH, EPISODE, a_film, registry_with
from test_phase6_publishing import _create_verified_asset_bundle
from test_publish_policy import _command, _to_production
from test_serial_pipeline import (
    FAKE_KEY,
    PRICE,
    TZ,
    URL,
    YESTERDAY_NOON,
    a_day,
    add_event,
    beats_for,
    episode_answer,
    fake_director,
    fake_showrunner,
    projected,
    registry,
    roster_names,
)

# ----------------------------------------------------------------------------- helpers --


@pytest.fixture
def serial_studio(engine):
    """The staffed studio of the serial tests: workforce, bibles, channels, autonomy on."""
    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    seed_default_channels(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    return engine


@pytest.fixture
def film_studio(engine):
    """The staffed studio of the editorial tests, with every model marked available."""
    from app.agents.models import Agent, ModelRecord, Role

    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        agents = {
            role.name: agent
            for agent, role in session.execute(
                select(Agent, Role).join(Role, Agent.role_id == Role.id)
            ).all()
        }
        provider_id = next(iter(agents.values())).provider_id
        session.expunge_all()
    return {"agents": agents, "provider_id": provider_id}


def _to_test(engine) -> None:
    with Session(engine) as session:
        version = session.get(OwnerPolicy, 1).version
    change_environment(
        engine, EnvironmentCommand(command_id=uuid4(), expected_version=version, environment="TEST")
    )


def _pin(engine, script_id: str, channel_id: str | None) -> None:
    """Set a storyboard's channel by id, as nothing in production does except the serial."""
    with Session(engine) as session, session.begin():
        board = session.scalars(
            select(Storyboard).where(Storyboard.script_draft_id == script_id)
        ).one()
        board.channel_id = channel_id


def _autonomy_on(engine) -> None:
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False


# ------------------------------------------------------------ (1) private on both channels --


def test_the_run_uploads_private_to_both_channels_and_a_visible_policy_needs_production(
    engine, tmp_path, monkeypatch
):
    """Two films, two bound slots, every default: both uploads private. The column a form
    used to fill (`upload_privacy_default`) is set to "public" first and read by nobody. Then
    the one thing that could make a film visible — the Owner's policy — is set to "unlisted"
    on Channel A while the studio is in TEST, and to "public" on Channel B in PRODUCTION
    with the studio moved back to TEST: both films still go out private, and say why."""
    _autonomy_on(engine)
    channels = _seeded_channels(engine)
    main, serial = channels["MAIN_FACTUAL"]["id"], channels["OFFICE_SERIAL"]["id"]
    _bound(engine, main, _connected(engine, "Main account"))
    _bound(engine, serial, _connected(engine, "Serial account"))
    for channel_id in (main, serial):
        configure_channel(engine, channel_id, None, None, None, "public", str(uuid4()))
    _create_verified_asset_bundle(engine, tmp_path / "factual-1")
    _serial_film(engine, tmp_path / "serial-1")
    publisher = _RecordingPublisher()
    monkeypatch.setattr("app.runbook.stages.selected_youtube", lambda *a, **k: publisher)
    _director_and_publisher_agree(monkeypatch)

    outcome = stages._publish(engine, None)

    assert outcome["status"] == "COMPLETED", outcome
    published = outcome["artefacts"]["published"]
    assert {p["channel_id"] for p in published} == {main, serial}
    assert {u["privacy_status"] for u in publisher.uploads} == {"private"}
    assert all(u.get("scheduled_publish_time") in (None, "") for u in publisher.uploads)
    assert all(p["release_privacy"] == "private" and p["publish_at"] is None for p in published)

    # An unlisted policy set in TEST resolves private until the studio is in PRODUCTION.
    change_publish_policy(engine, main, _command(autonomous_privacy="unlisted"))
    # A public policy set in PRODUCTION, with the studio then moved back to TEST.
    _to_production(engine)
    change_publish_policy(
        engine, serial, _command(autonomous_privacy="public", public_publish_enabled=True)
    )
    _to_test(engine)
    _create_verified_asset_bundle(engine, tmp_path / "factual-2")
    _serial_film(engine, tmp_path / "serial-2")
    publisher.uploads.clear()

    outcome = stages._publish(engine, None)

    assert outcome["status"] == "COMPLETED", outcome
    published = {p["channel_id"]: p for p in outcome["artefacts"]["published"]}
    assert set(published) == {main, serial}
    assert {u["privacy_status"] for u in publisher.uploads} == {"private"}
    for record in published.values():
        assert record["release_privacy"] == "private" and record["publish_at"] is None
        assert "TEST" in record["visibility_reason"]
    assert published[main]["policy_version"] == 2 and published[serial]["policy_version"] == 2


@pytest.mark.parametrize("environment", ["TEST", "PRODUCTION"])
def test_unlisted_is_a_visible_release_and_needs_production_like_public(environment):
    from types import SimpleNamespace

    channel = SimpleNamespace(
        autonomous_privacy="unlisted",
        public_publish_enabled=False,
        publish_delay_minutes=0,
        policy_version=4,
    )
    resolved = resolve_publish_visibility(channel, environment)
    expected = "unlisted" if environment == "PRODUCTION" else "private"
    assert resolved["privacy_status"] == expected
    assert resolved["release_privacy"] == expected
    assert resolved["publish_at"] is None and resolved["policy_version"] == 4
    if environment == "TEST":
        assert "TEST" in resolved["reason"]


# --------------------------------------------------------------- (2) the command's limits --


def test_public_cannot_come_back_in_test_through_the_flag_alone(engine):
    """ "public" needs PRODUCTION. Set in PRODUCTION, switched off through the flag, the
    studio moved to TEST: turning the flag on again would make the policy public in TEST
    without the word "public" ever appearing in the command. Refused, nothing recorded."""
    channels = _seeded_channels(engine)
    main = channels["MAIN_FACTUAL"]["id"]
    _to_production(engine)
    change_publish_policy(
        engine, main, _command(autonomous_privacy="public", public_publish_enabled=True)
    )
    change_publish_policy(engine, main, _command(expected_version=2, public_publish_enabled=False))
    _to_test(engine)

    with pytest.raises(PublishPolicyError, match="TEST"):
        change_publish_policy(
            engine, main, _command(expected_version=3, public_publish_enabled=True)
        )
    with Session(engine) as session:
        row = session.get(ChannelRecord, main)
        assert row.policy_version == 3 and row.public_publish_enabled is False
        events = list(
            session.scalars(
                select(DomainEvent).where(
                    DomainEvent.event_type == "publishing.channel_policy_changed"
                )
            )
        )
        assert len(events) == 2
        # Leaving a public policy alone in TEST still resolves private.
        assert resolve_publish_visibility(row, "TEST")["privacy_status"] == "private"

    # Other fields of the same channel can still be set in TEST; the flag stays off.
    delayed = change_publish_policy(
        engine, main, _command(expected_version=3, publish_delay_minutes=15)
    )
    assert delayed["status"] == "COMMITTED"
    assert delayed["channel"]["public_publish_enabled"] is False


def test_the_old_privacy_column_and_the_series_rules_cannot_set_the_policy(engine):
    channels = _seeded_channels(engine)
    for channel in channels.values():
        configure_channel(engine, channel["id"], None, None, None, "public", str(uuid4()))
    with Session(engine) as session:
        for channel in channels.values():
            row = session.get(ChannelRecord, channel["id"])
            assert row.upload_privacy_default == "public"
            assert row.autonomous_privacy == "private" and row.policy_version == 1
            assert row.director_may_approve_episodes is False
            assert resolve_publish_visibility(row, "PRODUCTION")["privacy_status"] == "private"


# ------------------------------------------------- (3) a film goes to its channel or nowhere --


def test_a_storyboard_whose_id_and_series_key_disagree_goes_nowhere(engine, tmp_path):
    """The media stage calls a film the serial's by its series key; the publish routing read
    the storyboard's `channel_id` first. A serial-keyed storyboard pinned to Channel A would
    have been filmed as the serial and sent to the factual channel. A contradiction is a
    refusal, in both directions; a pin that agrees with the key routes as before."""
    channels = _seeded_channels(engine)
    main, serial = channels["MAIN_FACTUAL"]["id"], channels["OFFICE_SERIAL"]["id"]
    _bound(engine, main, _connected(engine, "Main account"))
    _bound(engine, serial, _connected(engine, "Serial account"))

    episode = _serial_film(engine, tmp_path / "serial")
    _pin(engine, episode["script_id"], main)
    route = select_channel_for(engine, episode["asset_id"])
    assert route["status"] == ROUTE_SKIPPED, route
    assert route["youtube_connection_id"] is None
    assert route["channel_id"] != main

    factual = _create_verified_asset_bundle(engine, tmp_path / "factual")
    _pin(engine, factual["script_id"], serial)
    route = select_channel_for(engine, factual["asset_id"])
    assert route["status"] == ROUTE_SKIPPED, route
    assert route["youtube_connection_id"] is None
    assert route["channel_id"] != serial

    _pin(engine, episode["script_id"], serial)
    route = select_channel_for(engine, episode["asset_id"])
    assert route["status"] == ROUTE_SELECTED and route["channel_id"] == serial
    _pin(engine, factual["script_id"], None)
    route = select_channel_for(engine, factual["asset_id"])
    assert route["status"] == ROUTE_SELECTED and route["channel_id"] == main


# ------------------------------------------------------ (4) nothing private reaches the serial --


@pytest.mark.parametrize(
    "planted",
    [
        "USD 12.50",  # a price written currency-first
        "EUR 12",
        "youtu.be/sDEtt-WQGh8",  # a link without a scheme
        "studio.example.com/invoices",
        "AKIAIOSFODNN7EXAMPLE",  # an uppercase key id
    ],
)
def test_a_price_a_link_or_a_key_in_a_safe_field_never_reaches_the_showrunner(
    engine, serial_studio, monkeypatch, planted
):
    """The redaction pass guards the values of the *safe* keys too. A title carrying one of
    these shapes loses it before the projection is stored, and the prompt never sees it."""
    safe = add_event(
        engine, "factual.topic_selected", payload={"title": f"Apa de pe GJ 486 b {planted}"}
    )
    log = close_daily_log(engine, TZ)
    assert planted not in projected(log, safe)["description"]

    seen: list[str] = []
    names = roster_names(engine, log["id"])
    fake_showrunner(monkeypatch, episode_answer(beats_for([safe], names)), seen)
    write_episode(engine, registry(), log["id"], str(uuid4()))
    (prompt,) = seen
    assert planted not in prompt
    assert safe in prompt


def test_a_leak_in_the_summary_or_a_thread_never_reaches_canon_or_the_next_prompt(
    engine, serial_studio, monkeypatch
):
    """The beats are checked for leaks; the summary and the opened threads are what canon
    keeps and hands to every later episode's prompt. A key, a price or a URL there fails the
    privacy check before the Director is asked, and canon does not move."""
    with Session(engine) as session, session.begin():
        channel = session.scalar(
            select(ChannelRecord).where(ChannelRecord.channel_type == "OFFICE_SERIAL")
        )
        channel.director_may_approve_episodes = True
    log, ids = a_day(engine)
    names = roster_names(engine, log["id"])
    fake_showrunner(
        monkeypatch,
        episode_answer(
            beats_for(ids, names),
            summary=f"Sarah paid {PRICE} with the card ({FAKE_KEY}).",
            threads_opened=[f"the invoice at {URL}"],
        ),
    )
    episode = write_episode(engine, registry(), log["id"], str(uuid4()))["episode"]
    calls: list[str] = []
    fake_director(monkeypatch, "PASS", calls=calls)

    review = review_episode(engine, registry(), episode["id"])

    assert review["verdict"] == "FAIL"
    assert review["checks"]["privacy"]["passed"] is False
    assert review["model_used"] is False and calls == []
    with Session(engine) as session:
        assert session.get(StoryEpisode, episode["id"]).status == "REJECTED"
    continuity = get_continuity(engine)
    assert continuity["canon_episode_number"] == 0
    assert continuity["summaries"] == [] and continuity["threads"] == []


# ------------------------------------------------------------ (5) the Owner's leave, per channel --


def test_the_factual_channels_grant_does_not_let_the_director_approve_the_serial(
    engine, serial_studio, settings, monkeypatch
):
    channels = {c.channel_type: c.id for c in _rows(engine)}
    change_publish_policy(
        engine, channels["MAIN_FACTUAL"], _command(director_may_approve_episodes=True)
    )
    log, ids = a_day(engine, YESTERDAY_NOON())
    names = roster_names(engine, log["id"])
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names)))
    fake_director(monkeypatch, "PASS")

    outcome = run_serial_stage(engine, registry(), settings)

    assert outcome["status"] == "COMPLETED", outcome
    assert "aprobarea ta" in outcome["reason"]
    assert outcome["artefacts"]["storyboard_id"] is None
    with Session(engine) as session:
        assert session.get(StoryEpisode, outcome["artefacts"]["episode_id"]).status == "DRAFT"
        assert session.scalars(select(Storyboard)).all() == []
    assert get_continuity(engine)["canon_episode_number"] == 0


def _rows(engine) -> list[ChannelRecord]:
    with Session(engine) as session:
        rows = list(session.scalars(select(ChannelRecord)))
        session.expunge_all()
    return rows


# ------------------------------------------------------------- (6) a closed log never changes --


def test_a_closed_log_never_changes_when_its_date_gets_new_events(engine, serial_studio):
    log, ids = a_day(engine)
    late = add_event(engine, "factual.topic_selected", payload={"title": "O temă întârziată"})

    again = close_daily_log(engine, TZ)

    assert again["id"] == log["id"]
    assert again["event_counts"] == log["event_counts"]
    assert again["total_events"] == log["total_events"]
    assert again["narrative_projection"] == log["narrative_projection"]
    assert late not in {item["event_id"] for item in again["narrative_projection"]}
    with Session(engine) as session:
        row = session.get(DailyStudioLog, log["id"])
        stored = ensure_projection(session, row)
        assert stored == log["narrative_projection"]
        assert late not in {item["event_id"] for item in stored}


# ------------------------------------------------ (7) the stop between the day's two films --


def test_the_stop_pressed_during_the_factual_film_leaves_the_serial_unfilmed(
    engine, settings, monkeypatch
):
    """The render polls the switch between scenes and the runbook between stages; the
    media stage read it once, before the first film. A stop set during the factual film's
    last scene used to start the serial's render anyway. The stage asks before each film."""
    _autonomy_on(engine)
    serial = _approved_board(engine, "Office serial", serial=True)
    factual = _approved_board(engine, "A factual short")
    rendered: list[str] = []
    _media_stage_with_a_fake_camera(monkeypatch, rendered)

    def camera_then_stop(engine_, storyboard_id, correlation_id, **kwargs):
        rendered.append(storyboard_id)
        with Session(engine) as session, session.begin():
            session.get(OwnerPolicy, 1).autonomy_stopped = True
        return {"output_asset_id": f"asset-{storyboard_id[:8]}", "job_id": str(uuid4())}

    monkeypatch.setattr("app.media.assembler.assemble_video_job", camera_then_stop)

    outcome = stages._media(engine, settings, None, None)

    assert rendered == [factual], rendered
    assert outcome["status"] == "BLOCKED", outcome
    assert OWNER_STOP_REASON in outcome["reason"]
    assert outcome["artefacts"]["assets"] == [f"asset-{factual[:8]}"]
    assert outcome["artefacts"]["serial_assets"] == []
    assert outcome["artefacts"]["stopped_storyboard"] == serial


def test_the_budget_is_asked_once_per_film(engine, settings, monkeypatch):
    """And asked with a figure, not with zero: each film is costed from its own plan and
    the sum is held before a frame is generated, so what the first film took is against the
    budget by the time the second is asked about."""
    from app.economy.models import SpendReservation

    _autonomy_on(engine)
    _approved_board(engine, "Office serial", serial=True)
    _approved_board(engine, "A factual short")
    rendered: list[str] = []
    _media_stage_with_a_fake_camera(monkeypatch, rendered)
    asked: list[int] = []
    take = stages.reserve_spend

    def watched(engine_, usd_micros, purpose, correlation, **kwargs):
        asked.append(usd_micros)
        return take(engine_, usd_micros, purpose, correlation, **kwargs)

    monkeypatch.setattr(stages, "reserve_spend", watched)

    outcome = stages._media(engine, settings, None, None)

    assert outcome["status"] == "COMPLETED", outcome
    assert len(rendered) == 2 and len(asked) == 2
    assert all(usd_micros > 0 for usd_micros in asked), "a film was held at nothing"
    with Session(engine) as session:
        assert len(list(session.scalars(select(SpendReservation)))) == 2


# ------------------------------------------------------- (8) a blank frame rejects both kinds --


@pytest.mark.parametrize("serial", [False, True])
def test_a_blank_frame_rejects_a_serial_film_as_it_rejects_a_factual_one(
    engine, film_studio, monkeypatch, serial
):
    assert "garbled writing in any of them means REJECT" in instructions_for(serial, "")
    # The factual film narrates what its claim says. Narrating the serial's dialogue under a
    # claim about Webb is refused by the grounding check before any model looks at a frame
    # (measured 2026-09-19), which is a different refusal from the one this test is about.
    ids = a_film(
        engine, voiceover=EPISODE if serial else ENGLISH, with_source=not serial, serial=serial
    )
    monkeypatch.setattr("app.agents.editorial.model_can_see", lambda session, agent_id: True)
    monkeypatch.setattr("app.agents.editorial.frames_for", lambda *a, **k: ["ZmFrZS1mcmFtZQ=="])

    def answer(prompt):
        return json.dumps(
            {
                "verdict": "REJECT",
                "story": "",
                "reasons": ["the frame from scene 1 is a blank field"],
                "notes_for": {"VideoEditor": "Regenerate scene 1; the still is empty."},
            }
        )

    registry_, model = registry_with(film_studio, answer)
    result = editorial_review(engine, registry_, ids["asset"], language="en")

    assert result["verdict"] == "REJECT" and result["frames_seen"] == 1
    assert model.calls and model.calls[0]["extra"]["images"] == ["ZmFrZS1mcmFtZQ=="]
    assert result["letters"] == 1
    with Session(engine) as session:
        assert session.get(Storyboard, ids["board"]).status == "REJECTED"


# ------------------------------------------------------------- (9) audio and captions QC --


@pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not on PATH")
def test_loudness_and_captions_qc_fail_the_film_and_name_the_cause(engine, tmp_path, monkeypatch):
    from app.media.assembler import assemble_video_job
    from test_phase5_media import _seeded_storyboard

    _autonomy_on(engine)
    sb_id, _ = _seeded_storyboard(engine, tmp_path)
    render = assemble_video_job(engine, sb_id, str(uuid4()), storage_root=tmp_path / "media")
    asset_id = render["output_asset_id"]
    srt = Path(render["production"]["captions"]["srt"])
    assert srt.is_file()

    # No loudnorm in the encoder: the film cannot be certified, the way a missing ffprobe
    # fails technical QC, and the reason says which tool is missing.
    monkeypatch.setattr("app.media.qc.has_filter", lambda ffmpeg, name: False)
    report = evaluate_media_qc(engine, asset_id, str(uuid4()))
    assert report["status"] == "FAILED"
    audio = report["checks_json"]["audio_qc"]
    assert audio["passed"] is False and "loudnorm" in audio["error"]
    assert any("loudnorm" in reason for reason in report["failure_reasons_json"])
    assert report["checks_json"]["captions_qc"]["passed"] is True
    monkeypatch.undo()

    # Captions that break the rules: three lines, an overlap, and a cue after the film.
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:04,000\none\ntwo\nthree\n\n"
        "2\n00:00:03,000 --> 00:59:00,000\nafter the film\n",
        encoding="utf-8",
    )
    report = evaluate_media_qc(engine, asset_id, str(uuid4()))
    assert report["status"] == "FAILED"
    captions = report["checks_json"]["captions_qc"]
    assert captions["passed"] is False and captions["covers_narration"] is False
    problems = " ".join(captions["problems"])
    assert "cue 1 has 3 lines, more than 2 lines" in problems
    assert "cue 2 overlaps the cue before it" in problems
    assert "after the film" in problems
    assert any(reason.startswith("Captions:") for reason in report["failure_reasons_json"])

    # No captions file at all: named, not passed.
    srt.unlink()
    report = evaluate_media_qc(engine, asset_id, str(uuid4()))
    assert report["status"] == "FAILED"
    assert "Captions are missing: no SRT beside the film" in report["failure_reasons_json"]

    # Captions that do not parse.
    srt.write_text("this is not an srt file", encoding="utf-8")
    report = evaluate_media_qc(engine, asset_id, str(uuid4()))
    reasons = report["failure_reasons_json"]
    assert any(reason.startswith("Captions do not parse") for reason in reasons)


# ------------------------------------------------------------ (6b) yesterday's window is whole --


def test_yesterdays_close_counts_the_last_minute_of_the_day_and_not_the_first_of_today(
    engine, serial_studio, settings
):
    from zoneinfo import ZoneInfo

    from app.story.services import close_previous_day

    now = datetime.now(ZoneInfo(TZ))
    yesterday = now - timedelta(days=1)
    last_minute = yesterday.replace(hour=23, minute=59, second=30, microsecond=0)
    first_minute = now.replace(hour=0, minute=0, second=30, microsecond=0)
    inside = add_event(engine, "media.video_rendered", when=last_minute.astimezone(UTC))
    outside = add_event(engine, "factual.script_approved", when=first_minute.astimezone(UTC))

    log = close_previous_day(engine, settings)

    ids = {item["event_id"] for item in log["narrative_projection"]}
    assert inside in ids and outside not in ids
    assert log["business_date"] == yesterday.date().isoformat()


# ------------------------------------------------ (7b) the stop set right before the serial --


def test_the_stop_set_during_the_script_stage_leaves_the_serial_and_the_camera_untouched(
    engine, settings, tmp_path
):
    """STOP pressed while `script_and_storyboard` runs: the serial stage and the media
    stage are BLOCKED with the Owner's reason and their runners are never called, so no
    episode is written and no film is started."""
    import shutil

    from app.agents.models import ModelRecord
    from app.integrations.vault import CredentialVault
    from app.runbook.services import STAGES, execute_daily_run, stop_requested

    seed_initial_workforce(engine)
    _autonomy_on(engine)
    settings.ffmpeg_path = settings.ffmpeg_path or shutil.which("ffmpeg") or "ffmpeg-test-stub"
    with Session(engine) as session, session.begin():
        session.scalars(select(ModelRecord)).first().is_available = True
    ran: list[str] = []

    def stop_while_writing() -> dict:
        ran.append("script_and_storyboard")
        with Session(engine) as session, session.begin():
            session.get(OwnerPolicy, 1).autonomy_stopped = True
        return {"status": "COMPLETED", "reason": "scenariul scris"}

    runners = {
        name: (lambda n=name: ran.append(n) or {"status": "COMPLETED", "reason": "ok"})
        for name in STAGES[1:]
    }
    runners["script_and_storyboard"] = stop_while_writing

    result = execute_daily_run(
        engine, settings, CredentialVault(tmp_path / "run.credentials.key"), stage_runners=runners
    )

    assert stop_requested(engine) is True
    assert "serial_queue" not in ran and "media" not in ran and "publish" not in ran
    assert ran[-1] == "script_and_storyboard"
    by_name = {s["stage"]: s for s in result["stages"]}
    for name in ("serial_queue", "media", "edit_and_qc", "publish"):
        assert by_name[name]["status"] == "BLOCKED", name
        assert OWNER_STOP_REASON in by_name[name]["reason"], name
    assert result["status"] == "PARTIAL"
    assert result["stopped_at_stage"] == "serial_queue"
