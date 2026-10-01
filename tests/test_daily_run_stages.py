"""The runbook's stages, with real work behind them.

Before this, `execute_daily_run` walked twelve stages and nothing in the application supplied the
work for any of them: every run recorded preflight and then eleven SKIPPED. The runbook was
truthful and idle.

These tests hold the wiring to two things. First, that each stage does the real operation against
the real services — a claim is verified by an agent, a file is measured by ffprobe, a publication
passes the same five-point gate as a manual one. Second, and just as important, that a stage which
cannot run says so instead of reporting a success it did not have: the distinction between
COMPLETED with a count of zero and SKIPPED with a reason is the whole difference between "we
looked and there was nothing" and "we could not look".
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from app.factual.models import FactualClaim, TopicIdea
from app.factual.services import TopicNotProducible, select_topic
from app.media.toolchain import find_ffmpeg
from app.providers.registry import ProviderRegistry
from app.runbook.stages import build_stage_runners
from app.services import utc_now
from sqlalchemy.orm import Session


@pytest.fixture
def empty_registry() -> ProviderRegistry:
    """A registry with no language model, as a studio has before any provider is verified."""
    return ProviderRegistry()


@pytest.fixture
def runners(engine, settings, empty_registry):
    from pathlib import Path

    from app.integrations.vault import CredentialVault

    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    return build_stage_runners(engine, settings, vault, empty_registry)


def _topic(engine, *, status: str = "PROPOSED") -> str:
    topic_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            TopicIdea(
                id=topic_id,
                title="Un subiect de probă",
                topic="Test",
                angle="Test",
                target_audience="test",
                novelty_score=0.9,
                status=status,
                created_at=utc_now(),
            )
        )
    return topic_id


def _claim(engine, topic_id: str, *, status: str) -> str:
    claim_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            FactualClaim(
                id=claim_id,
                topic_id=topic_id,
                claim_text="O afirmație de probă.",
                claim_type="SCIENTIFIC_FACT",
                importance="CRITICAL",
                status=status,
                confidence=0.9,
                created_at=utc_now(),
            )
        )
    return claim_id


# ------------------------------------------------------------------ the two outcomes --


def test_a_stage_that_cannot_run_is_skipped_with_the_reason(runners):
    """No language model means the agent stages could not look, not that they found nothing."""
    for name in ("research_and_verification", "script_and_storyboard", "serial_queue"):
        outcome = runners[name]()
        assert outcome["status"] == "SKIPPED", name
        assert "model de limbaj" in outcome["reason"], name


def test_a_stage_that_ran_and_found_nothing_is_completed_with_a_count(runners, engine):
    """Looking and finding nothing is work done, and must not read as work skipped."""
    outcome = runners["edit_and_qc"]()
    assert outcome["status"] == "COMPLETED"
    assert outcome["artefacts"]["checked"] == 0

    selection = runners["selection"]()
    assert selection["status"] == "COMPLETED"
    assert "nimic adevărat de produs" in selection["reason"]


def test_publishing_is_skipped_when_no_channel_is_connected(runners):
    outcome = runners["publish"]()
    assert outcome["status"] == "SKIPPED"
    # No channel row at all in this fixture: the studio says so rather than naming a binding
    # that could not exist yet.
    assert "Niciun canal configurat" in outcome["reason"]


def test_performance_intake_is_skipped_without_an_analytics_account(runners):
    outcome = runners["performance_intake"]()
    assert outcome["status"] == "SKIPPED"
    assert "analytics" in outcome["reason"]


# --------------------------------------------------------------------- the selection --


def test_selection_takes_a_topic_that_has_something_verified_to_say(runners, engine):
    topic_id = _topic(engine)
    _claim(engine, topic_id, status="SUPPORTED")

    outcome = runners["selection"]()

    assert outcome["status"] == "COMPLETED"
    assert outcome["artefacts"]["topic_id"] == topic_id
    with Session(engine) as session:
        assert session.get(TopicIdea, topic_id).status == "SELECTED"


def test_selection_refuses_a_topic_whose_claims_are_all_unverified(engine):
    """Selecting it would only move the refusal one stage later, and imply the day had work."""
    topic_id = _topic(engine)
    _claim(engine, topic_id, status="UNVERIFIED")

    with pytest.raises(TopicNotProducible, match="SUPPORTED"):
        select_topic(engine, topic_id, str(uuid4()))


def test_selecting_the_same_topic_twice_does_not_record_a_second_decision(engine):
    from app.models import DomainEvent
    from sqlalchemy import func, select

    topic_id = _topic(engine)
    _claim(engine, topic_id, status="SUPPORTED")

    select_topic(engine, topic_id, str(uuid4()))
    select_topic(engine, topic_id, str(uuid4()))

    with Session(engine) as session:
        events = session.scalar(
            select(func.count())
            .select_from(DomainEvent)
            .where(
                DomainEvent.event_type == "factual.topic_selected",
                DomainEvent.aggregate_id == topic_id,
            )
        )
    assert events == 1


def test_selection_leaves_an_existing_production_alone(runners, engine):
    """A day that starts with work in progress does not start a second piece of work."""
    first = _topic(engine, status="SELECTED")
    second = _topic(engine)
    _claim(engine, second, status="SUPPORTED")

    outcome = runners["selection"]()

    assert outcome["artefacts"]["topic_id"] == first
    with Session(engine) as session:
        assert session.get(TopicIdea, second).status == "PROPOSED"


# ------------------------------------------------------------- research, for real --


class _ScriptedModel:
    """A language model that answers exactly what the agent pipeline asks it for.

    It is not pretending to be intelligent. It returns one extraction and one verdict, and the
    verdict's evidence quote is copied out of the source — which is the part that matters, because
    the pipeline rejects any verdict whose quote does not appear in the source verbatim. A stub
    that could not quote correctly would prove nothing about the wiring.
    """

    def __init__(self, quote: str) -> None:
        self.quote = quote
        self.prompts: list[str] = []

    async def health_check(self):
        from app.providers.base import HealthResult

        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        from app.providers.base import GenerateResult

        self.prompts.append(prompt)
        if "verdict" in prompt.lower() or "evidence_quote" in prompt:
            body = (
                '{"status": "SUPPORTED", "confidence": 0.9, "evidence_quote": '
                f'"{self.quote}", "notes": "Sursa confirma afirmatia."}}'
            )
        else:
            body = (
                '[{"claim_text": "' + self.quote + '", "claim_type": "SCIENTIFIC_FACT", '
                '"importance": "CRITICAL", "confidence": 0.9}]'
            )
        return GenerateResult(body, 10, 40, None)


def test_research_reads_a_source_and_a_second_agent_checks_the_result(engine, settings):
    """The stage runs the real pipeline: extraction, then verification with the quote check."""
    from pathlib import Path as _Path

    from app.agents.models import Agent, ModelRecord
    from app.agents.services import seed_initial_workforce
    from app.factual.services import ingest_source_snapshot
    from app.integrations.vault import CredentialVault
    from app.models import OwnerPolicy
    from sqlalchemy import select

    quote = "Telescopul observa in infrarosu."
    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        provider_id = session.scalar(select(Agent)).provider_id

    ingest_source_snapshot(
        engine,
        url="https://www.iana.org/help/example-domains",
        title="Sursa de proba",
        publisher="www.iana.org",
        author=None,
        raw_content=quote,
        credibility_score=0.9,
        correlation_id=str(uuid4()),
    )

    registry = ProviderRegistry()
    model = _ScriptedModel(quote)
    registry.register(provider_id, model)

    vault = CredentialVault(_Path(str(engine.url.database)).with_suffix(".credentials.key"))
    stage = build_stage_runners(engine, settings, vault, registry)["research_and_verification"]
    outcome = stage()

    assert outcome["status"] == "COMPLETED"
    assert outcome["artefacts"]["sources_read"] == 1
    # Called at least twice: once to extract, once to verify. Two different agents, by design.
    assert len(model.prompts) >= 2

    with Session(engine) as session:
        claims = list(session.scalars(select(FactualClaim)))
    assert claims, "the stage stored no claim"
    assert any(claim.status == "SUPPORTED" for claim in claims), [c.status for c in claims]


# ------------------------------------------------------- refusals are not failures --


def test_a_rejected_script_does_not_take_the_day_down_with_it(engine, settings, monkeypatch):
    """A model that writes unattributable narration is a content problem, not a run failure.

    Letting it raise would mark the stage FAILED, and the runbook stops the day at the first
    FAILED stage — so the daily log would never be closed and every later stage would be BLOCKED,
    over an outcome the pipeline handled exactly right by refusing to store the draft.
    """
    from pathlib import Path as _Path

    from app.factual.agent_pipeline import ScriptRejected
    from app.integrations.vault import CredentialVault

    topic_id = _topic(engine, status="SELECTED")
    _claim(engine, topic_id, status="SUPPORTED")

    registry = ProviderRegistry()
    registry.register("any", object())

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise ScriptRejected("scena 1 citează afirmații care nu există")

    monkeypatch.setattr("app.runbook.stages.agent_write_script", refuse)
    vault = CredentialVault(_Path(str(engine.url.database)).with_suffix(".credentials.key"))
    outcome = build_stage_runners(engine, settings, vault, registry)["script_and_storyboard"]()

    assert outcome["status"] == "COMPLETED"
    assert outcome["artefacts"]["scripts"] == 0
    assert len(outcome["artefacts"]["rejected"]) == 1
    # One rejected script: «1 respins» — the count agrees with «scenariu».
    assert "1 respins:" in outcome["reason"]


def test_quality_control_selects_files_by_what_they_are_not_by_their_label(
    engine, settings, tmp_path
):
    """The renderer writes RENDERED_VIDEO and the fixtures write VIDEO_COMPOSED.

    Keying quality control to either name would leave real renders unmeasured, and an unmeasured
    file is exactly what the publishing gate is supposed to stop.
    """
    from hashlib import sha256
    from pathlib import Path as _Path

    from app.integrations.vault import CredentialVault
    from app.media.models import MediaAsset

    video = tmp_path / "render.mp4"
    video.write_bytes(b"\x00" * 4096)
    asset_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="RENDERED_VIDEO",
                uri_or_path=str(video),
                file_size_bytes=video.stat().st_size,
                mime_type="video/mp4",
                width=1080,
                height=1920,
                duration_seconds=12.0,
                provider_name="test",
                license_status="OWNED_INTERNAL",
                provenance_hash=sha256(video.read_bytes()).hexdigest(),
                created_at=utc_now(),
            )
        )

    vault = CredentialVault(_Path(str(engine.url.database)).with_suffix(".credentials.key"))
    outcome = build_stage_runners(engine, settings, vault, ProviderRegistry())["edit_and_qc"]()

    assert outcome["status"] == "COMPLETED"
    # It was measured. Whether it passed is QC's business; that it was looked at is this test's.
    assert outcome["artefacts"]["passed"] + outcome["artefacts"]["failed"] == 1


# ------------------------------------------------------- one channel per film, by policy --


def _seeded_channels(engine) -> dict[str, dict]:
    from app.publishing.services import list_channels, seed_default_channels

    seed_default_channels(engine)
    return {c["channel_type"]: c for c in list_channels(engine)}


def _connected(engine, name: str) -> str:
    from app.youtube.models import YouTubeConnection

    connection_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            YouTubeConnection(
                id=connection_id,
                name=name,
                client_id="client-id",
                redirect_uri="http://localhost/callback",
                encrypted_secrets="opaque",
                secret_fields=["client_secret", "refresh_token"],
                status="CONNECTED",
                remote_channel_id=f"UC_{connection_id[:8]}",
                remote_channel_title=name,
                channel_snapshot={},
                created_at=utc_now(),
            )
        )
    return connection_id


def _bound(engine, channel_id: str, connection_id: str) -> None:
    from app.publishing.models import ChannelRecord

    with Session(engine) as session, session.begin():
        session.get(
            ChannelRecord, channel_id
        ).credentials_ref = f"youtube_connection:{connection_id}"


def _serial_film(engine, tmp_path) -> dict:
    """A QC-passed film whose storyboard says it was produced for the office serial."""
    from app.media.models import Storyboard
    from sqlalchemy import select
    from test_phase6_publishing import _create_verified_asset_bundle

    bundle = _create_verified_asset_bundle(engine, tmp_path)
    with Session(engine) as session, session.begin():
        board = session.scalars(
            select(Storyboard).where(Storyboard.script_draft_id == bundle["script_id"])
        ).one()
        board.series_key = "office_serial"
    return bundle


class _RecordingPublisher:
    """The simulator, remembering the visibility it was asked for."""

    def __init__(self) -> None:
        from app.providers.deterministic_pub import DeterministicPublishingAdapter

        self.inner = DeterministicPublishingAdapter()
        self.uploads: list[dict[str, Any]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    async def upload_video(self, file_path: Any, **kwargs: Any) -> Any:
        self.uploads.append(dict(kwargs))
        return await self.inner.upload_video(file_path, **kwargs)


def _director_and_publisher_agree(monkeypatch) -> None:
    """The Director has approved the film and the Publisher's metadata is READY: the
    stage's own concern here is which channel, at which visibility."""
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.runbook.stages.latest_editorial",
        lambda session, asset_id: SimpleNamespace(verdict="APPROVE", reasons_json=[]),
    )
    monkeypatch.setattr(
        "app.runbook.stages.approved_metadata",
        lambda session, asset_id: {
            "title": "Office serial, episode one",
            "description": "A day at the studio.",
            "tags": ["office_serial"],
        },
    )


def test_publishing_routes_a_serial_film_to_its_own_slot_and_never_to_channel_a(
    runners, engine, tmp_path, monkeypatch
):
    """`ready[0]` used to be the first bound slot whatever film it held. A serial film with
    only the main channel bound goes nowhere — and says which slot to bind."""
    from app.publishing.models import PublicationRecord
    from sqlalchemy import select

    channels = _seeded_channels(engine)
    _serial_film(engine, tmp_path)
    _bound(engine, channels["MAIN_FACTUAL"]["id"], _connected(engine, "Main account"))
    publisher = _RecordingPublisher()
    monkeypatch.setattr("app.runbook.stages.selected_youtube", lambda *a, **k: publisher)
    _director_and_publisher_agree(monkeypatch)

    refused = runners["publish"]()

    assert refused["status"] == "SKIPPED", refused
    assert channels["OFFICE_SERIAL"]["channel_name"] in refused["reason"]
    assert publisher.uploads == []
    with Session(engine) as session:
        assert session.scalars(select(PublicationRecord)).all() == []

    _bound(engine, channels["OFFICE_SERIAL"]["id"], _connected(engine, "Serial account"))
    published = runners["publish"]()

    assert published["status"] == "COMPLETED", published
    assert len(publisher.uploads) == 1
    assert publisher.uploads[0]["privacy_status"] == "private"
    (record,) = published["artefacts"]["published"]
    assert record["channel_id"] == channels["OFFICE_SERIAL"]["id"]
    assert record["policy_version"] == 1
    with Session(engine) as session:
        row = session.scalars(select(PublicationRecord)).one()
        assert row.channel_id == channels["OFFICE_SERIAL"]["id"]
        assert row.policy_version == 1


def test_publishing_visibility_is_the_channel_policy_and_the_stamp_is_its_version(
    runners, engine, tmp_path, monkeypatch
):
    """The constant "private" is gone: the Owner's policy on the routed channel decides, and
    the publication carries the version of the policy that decided it."""
    from app.publishing.models import PublicationRecord
    from app.publishing.schemas import PublishPolicyCommand
    from app.publishing.services import change_publish_policy
    from sqlalchemy import select
    from test_publish_policy import _to_production

    channels = _seeded_channels(engine)
    _serial_film(engine, tmp_path)
    serial = channels["OFFICE_SERIAL"]["id"]
    _bound(engine, serial, _connected(engine, "Serial account"))
    # A visible release exists only in PRODUCTION; in TEST the same policy uploads private.
    _to_production(engine)
    change_publish_policy(
        engine,
        serial,
        PublishPolicyCommand(command_id=uuid4(), expected_version=1, autonomous_privacy="unlisted"),
    )
    publisher = _RecordingPublisher()
    monkeypatch.setattr("app.runbook.stages.selected_youtube", lambda *a, **k: publisher)
    _director_and_publisher_agree(monkeypatch)

    outcome = runners["publish"]()

    assert outcome["status"] == "COMPLETED", outcome
    assert publisher.uploads[0]["privacy_status"] == "unlisted"
    (record,) = outcome["artefacts"]["published"]
    assert record["release_privacy"] == "unlisted"
    assert record["policy_version"] == 2
    assert "nelistat" in record["visibility_reason"]
    with Session(engine) as session:
        row = session.scalars(select(PublicationRecord)).one()
        assert row.privacy_status == "unlisted" and row.policy_version == 2


def test_performance_intake_asks_each_channel_through_its_own_account(
    runners, engine, tmp_path, monkeypatch
):
    """Two channels, one bound: the bound one is measured through its own publications, the
    unbound one is named in the outcome, and nothing is measured through a wrong account."""
    from app.providers.analytics_base import VideoMetrics
    from app.publishing.models import PublicationRecord
    from test_phase6_publishing import _create_verified_asset_bundle

    channels = _seeded_channels(engine)
    main, serial = channels["MAIN_FACTUAL"]["id"], channels["OFFICE_SERIAL"]["id"]
    for channel_id, asset_dir, video in ((main, "a", "main-video"), (serial, "b", "serial-video")):
        asset_id = _create_verified_asset_bundle(engine, tmp_path / asset_dir)["asset_id"]
        with Session(engine) as session, session.begin():
            session.add(
                PublicationRecord(
                    id=str(uuid4()),
                    channel_id=channel_id,
                    media_asset_id=asset_id,
                    title="t",
                    description="d",
                    tags_json=[],
                    privacy_status="private",
                    status="PUBLISHED",
                    remote_video_id=video,
                    remote_url=f"https://youtube.example/{video}",
                    idempotency_key=str(uuid4()),
                    created_at=utc_now(),
                    published_at=utc_now(),
                )
            )

    class Analytics:
        def __init__(self) -> None:
            self.asked: list[str] = []

        async def fetch_video_metrics(self, video_id: str, window: str = "LIFETIME"):
            self.asked.append(video_id)
            return VideoMetrics(
                remote_video_id=video_id,
                views=10,
                watch_time_seconds=30.0,
                average_view_percentage=50.0,
                impressions=100,
                ctr_percentage=5.0,
                likes=1,
                comments=0,
                shares=0,
                subscribers_gained=0,
                subscribers_lost=0,
                window=window,
                raw={},
            )

    provider = Analytics()

    def per_channel(engine_, vault, channel_id):
        if channel_id == main:
            return provider, ""
        return None, "Slotul serialului nu este legat de un cont YouTube."

    monkeypatch.setattr("app.runbook.stages.analytics_provider_for_channel", per_channel)

    outcome = runners["performance_intake"]()

    assert outcome["status"] == "COMPLETED", outcome
    assert provider.asked == ["main-video"]
    assert outcome["artefacts"]["measured"] == 1
    assert outcome["artefacts"]["channels"][main]["measured"] == 1
    assert "serialului" in outcome["artefacts"]["skipped"][serial]


# ------------------------------------------------ the serial is filmed in the same run --


def _approved_board(engine, title: str, *, serial: bool = False) -> str:
    from app.factual.models import ScriptDraft
    from app.media.models import Storyboard, StoryboardScene

    topic_id = _topic(engine, status="SELECTED")
    script_id, board_id, now = str(uuid4()), str(uuid4()), utc_now()
    with Session(engine) as session, session.begin():
        session.add(
            ScriptDraft(
                id=script_id,
                topic_id=topic_id,
                version=1,
                title=title,
                target_duration_seconds=12,
                voiceover_full_text="One line. Another line.",
                scenes_json=[],
                status="APPROVED",
                claim_ids_json=[],
                unverified_claim_ids_json=[],
                created_at=now,
            )
        )
        session.add(
            Storyboard(
                id=board_id,
                script_draft_id=script_id,
                title=title,
                visual_style="MOTION_GRAPHIC",
                aspect_ratio="9:16",
                target_duration_seconds=12,
                status="APPROVED",
                total_scenes=2,
                series_key="office_serial" if serial else None,
                created_at=now,
            )
        )
        for index, line in enumerate(("One line.", "Another line."), start=1):
            session.add(
                StoryboardScene(
                    id=str(uuid4()),
                    storyboard_id=board_id,
                    scene_index=index,
                    visual_prompt=f"scene {index}",
                    visual_type="MOTION_GRAPHIC",
                    duration_seconds=6.0,
                    voiceover_segment=line,
                    shot_type="MEDIUM",
                    transition_in="CUT",
                    character_ids_json=[],
                    claim_ids_json=[],
                    created_at=now,
                )
            )
    return board_id


def _autonomy_on(engine) -> None:
    """The studio as the runbook finds it before the media stage: the Owner's switch off.

    Bootstrap seeds the stop on; the stage now reads the switch before each film, so a test
    that calls it directly starts from the state the runbook would have reached."""
    from app.models import OwnerPolicy

    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False


def _media_stage_with_a_fake_camera(monkeypatch, rendered: list[str]):
    """Everything around the render is real; the render itself only records its order."""
    from app.runbook import stages

    monkeypatch.setattr(stages, "story_gate", lambda session, script_id: (True, ""))
    monkeypatch.setattr(
        "app.media.factory.render_plan",
        lambda engine_, vault, board: {
            "image": None,
            "tts_for_scene": lambda *a: None,
            "video_for_scene": lambda *a: None,
            "plan": {},
        },
    )

    def camera(engine_, storyboard_id, correlation_id, **kwargs):
        rendered.append(storyboard_id)
        return {"output_asset_id": f"asset-{storyboard_id[:8]}", "job_id": str(uuid4())}

    monkeypatch.setattr("app.media.assembler.assemble_video_job", camera)


def test_media_renders_the_factual_film_first_and_the_serial_second(engine, settings, monkeypatch):
    from app.runbook import stages

    _autonomy_on(engine)
    serial = _approved_board(engine, "Office serial", serial=True)
    factual = _approved_board(engine, "A factual short")
    rendered: list[str] = []
    _media_stage_with_a_fake_camera(monkeypatch, rendered)

    outcome = stages._media(engine, settings, None, None)

    assert outcome["status"] == "COMPLETED", outcome
    assert rendered == [factual, serial]
    assert outcome["artefacts"]["serial_assets"] == [f"asset-{serial[:8]}"]


def test_a_budget_refusal_after_the_factual_film_skips_the_serial_and_says_so(
    engine, settings, monkeypatch
):
    """The serial goes through the same budget check as the factual film — asked again after
    the factual film spent, and refused for the serial alone when the day's money is gone."""
    from app.runbook import stages

    _autonomy_on(engine)
    serial = _approved_board(engine, "Office serial", serial=True)
    factual = _approved_board(engine, "A factual short")
    rendered: list[str] = []
    _media_stage_with_a_fake_camera(monkeypatch, rendered)
    answers = iter(
        [
            {"allowed": True, "period": None, "reason": "", "reservation_id": None},
            {
                "allowed": False,
                "period": "DAILY",
                "reason": "Bugetul zilnic ar fi depășit.",
                "reservation_id": None,
            },
        ]
    )
    # The stage now *holds* the money instead of reading a snapshot; what is stubbed here is
    # the verdict, so this test stays about the order of the two films. The hold itself, the
    # settlement and the Accountant's letter are the three tests below.
    monkeypatch.setattr(stages, "reserve_spend", lambda *a, **k: next(answers))

    outcome = stages._media(engine, settings, None, None)

    assert outcome["status"] == "COMPLETED", outcome
    assert rendered == [factual]
    assert outcome["artefacts"]["skipped_for_budget"] == [serial]
    assert "serial" in outcome["reason"].lower() and "Bugetul" in outcome["reason"]


# ------------------------------------------- the money is held before it is spent --


def _daily_budget(engine, usd: str) -> None:
    """The Owner's own command, as the books' route would write it."""
    from app.economy.budget import BudgetCommand, set_budget

    set_budget(engine, BudgetCommand(period="DAILY", limit_usd=usd))


def _reservations(engine) -> list[Any]:
    from app.economy.models import SpendReservation
    from sqlalchemy import select

    with Session(engine) as session:
        return list(session.scalars(select(SpendReservation)))


def test_the_film_holds_its_estimated_cost_and_settles_the_hold_when_it_is_made(
    engine, settings, monkeypatch
):
    """The check before a render used to be `may_spend(engine, 0)`: a day at 14.99 of 15 USD
    started a full film, and two films asked in the same second were both told the last ten
    dollars were free. The plan is now priced, the sum held, and the hold settled once the
    render is in the books."""
    from app.runbook import stages

    _autonomy_on(engine)
    _approved_board(engine, "A factual short")
    _media_stage_with_a_fake_camera(monkeypatch, [])

    outcome = stages._media(engine, settings, None, None)

    assert outcome["status"] == "COMPLETED", outcome
    (hold,) = _reservations(engine)
    assert hold.usd_micros > 0, "the plan was costed at nothing"
    assert hold.status == "SETTLED"
    assert hold.settled_reference.startswith("render:")


def test_a_render_that_was_refused_lets_its_hold_go(engine, settings, monkeypatch):
    """A hold is money pledged to a film. The film was not made, so the day gets it back at
    once — not in six hours when the watchdog sweeps."""
    from app.providers.media_http import MediaProviderError
    from app.runbook import stages

    _autonomy_on(engine)
    _approved_board(engine, "A factual short")
    _media_stage_with_a_fake_camera(monkeypatch, [])

    def refuses(*args: Any, **kwargs: Any) -> None:
        raise MediaProviderError("the model refused this shot")

    monkeypatch.setattr("app.media.assembler.assemble_video_job", refuses)

    outcome = stages._media(engine, settings, None, None)

    assert outcome["status"] == "COMPLETED", outcome
    assert "refuzată de furnizor" in outcome["reason"]
    (hold,) = _reservations(engine)
    assert hold.status == "RELEASED"
    assert "refuzat" in (hold.settled_reference or "")


def test_a_budget_that_cannot_pay_for_the_film_refuses_it_and_the_owner_is_told(
    engine, settings, monkeypatch
):
    """A budget refusal used to be a SKIPPED line in a run summary nobody reads by itself.
    The Accountant writes to the Owner the same day, once, with the figures and the one
    decision only he can take."""
    from app.agents.models import AgentMessage
    from app.agents.services import seed_initial_workforce
    from app.runbook import stages
    from sqlalchemy import select

    _autonomy_on(engine)
    seed_initial_workforce(engine)
    _approved_board(engine, "A factual short")
    rendered: list[str] = []
    _media_stage_with_a_fake_camera(monkeypatch, rendered)
    _daily_budget(engine, "0.10")  # less than any film the studio can plan

    outcome = stages._media(engine, settings, None, None)

    assert outcome["status"] == "SKIPPED", outcome
    assert "Bugetul" in outcome["reason"]
    assert rendered == [], "money was refused and the camera still rolled"
    assert _reservations(engine) == [], "a refused film holds nothing"
    with Session(engine) as session:
        letters = [
            message
            for message in session.scalars(
                select(AgentMessage).where(AgentMessage.to_agent_id.is_(None))
            )
            if (message.body_json or {}).get("kind") == "budget_refusal"
        ]
    assert len(letters) == 1, "the Owner was not told, or was told twice"
    assert "bugetul" in letters[0].body_text.lower()


# --------------------------------------------------- the Owner's stop between two scenes --


def test_the_render_stops_between_scenes_when_the_owner_stops_autonomy(engine, tmp_path):
    """A render of eight scenes used to run to its end after the Owner pressed STOP: the
    switch was read between stages only. The assembler now reads it between scenes and
    fails the job cleanly — the reason names the stop, nothing is recorded, no safe mode."""
    from app.media.assembler import RenderStopped, assemble_video_job
    from app.media.models import MediaAsset, VideoRenderJob
    from app.models import OwnerPolicy
    from app.providers.deterministic_media import DeterministicTTSAdapter
    from app.runbook.services import safe_mode_state
    from sqlalchemy import select

    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    board_id = _approved_board(engine, "Stopped mid-way")

    class VoiceThenStop(DeterministicTTSAdapter):
        PROVIDER_NAME = "test_voice"
        calls = 0

        async def synthesize(self, text: str, **kwargs: Any):
            type(self).calls += 1
            result = await super().synthesize(text, **kwargs)
            with Session(engine) as session, session.begin():
                session.get(OwnerPolicy, 1).autonomy_stopped = True
            return result

    with pytest.raises(RenderStopped, match="AUTONOMIE OPRITĂ"):
        assemble_video_job(
            engine,
            board_id,
            str(uuid4()),
            storage_root=tmp_path / "media",
            tts_adapter=VoiceThenStop(),
        )

    assert VoiceThenStop.calls == 1, "the second scene was never started"
    with Session(engine) as session:
        job = session.scalars(select(VideoRenderJob)).one()
        assert job.status == "FAILED"
        assert "AUTONOMIE OPRITĂ" in job.execution_log
        assert session.scalars(select(MediaAsset)).all() == []
    assert safe_mode_state(engine)["active"] is False


def test_the_media_stage_reports_the_stop_as_blocked_not_failed(engine, settings, monkeypatch):
    from app.media.assembler import RenderStopped
    from app.runbook import stages
    from app.runbook.services import OWNER_STOP_REASON

    # The switch is off when the film starts; the render itself meets the stop between
    # scenes, which is the path this test holds (the stage's own read before each film is
    # tests/test_phase_bc_adversary.py's).
    _autonomy_on(engine)
    _approved_board(engine, "A factual short")
    rendered: list[str] = []
    _media_stage_with_a_fake_camera(monkeypatch, rendered)

    def stopped(engine_, storyboard_id, correlation_id, **kwargs):
        raise RenderStopped("Randarea s-a oprit între scene: AUTONOMIE OPRITĂ.")

    monkeypatch.setattr("app.media.assembler.assemble_video_job", stopped)

    outcome = stages._media(engine, settings, None, None)

    assert outcome["status"] == "BLOCKED"
    assert OWNER_STOP_REASON in outcome["reason"]


# ------------------------------------- the pictures, the second vendor, the Owner's mode --


def _rendered_video(engine, path) -> str:
    """A file the quality-control stage will pick up, recorded as the renderer records one."""
    from hashlib import sha256

    from app.media.models import MediaAsset

    path.write_bytes(b"\x00" * 4096)
    asset_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="RENDERED_VIDEO",
                uri_or_path=str(path),
                file_size_bytes=path.stat().st_size,
                mime_type="video/mp4",
                width=1080,
                height=1920,
                duration_seconds=12.0,
                provider_name="test",
                license_status="OWNED_INTERNAL",
                provenance_hash=sha256(path.read_bytes()).hexdigest(),
                created_at=utc_now(),
            )
        )
    return asset_id


def _vault(engine):
    from pathlib import Path

    from app.integrations.vault import CredentialVault

    return CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))


def test_quality_control_is_given_what_it_takes_to_look_at_the_pictures(
    engine, settings, tmp_path, monkeypatch
):
    """The picture and character checks are a model run over frames cut from the film, so the
    stage has to hand quality control the registry it already holds and the encoder's path.
    Without them `evaluate_media_qc` can only measure the container, and the two checks
    report NOT_APPLICABLE forever while the stage sits on everything they needed."""
    from app.runbook import stages

    captured: dict[str, Any] = {}

    def fake_qc(engine_, asset_id, correlation, settings=None, **kwargs):
        captured.update(kwargs)
        return {"id": str(uuid4()), "status": "PASSED"}

    monkeypatch.setattr(stages, "evaluate_media_qc", fake_qc)
    _rendered_video(engine, tmp_path / "render.mp4")
    registry = ProviderRegistry()

    outcome = build_stage_runners(engine, settings, _vault(engine), registry)["edit_and_qc"]()

    assert outcome["status"] == "COMPLETED", outcome
    assert captured["registry"] is registry
    assert captured["ffmpeg_path"] == settings.ffmpeg_path


def test_a_picture_check_that_could_not_look_leaves_the_films_verdict_exactly_as_it_was(
    engine, settings, tmp_path
):
    """A studio with no vision-capable model must measure the same film the same way it did
    before the check existed: NOT_APPLICABLE with a reason, `passed` None, no failure added.
    Two identical files, one measured through the stage and one measured the way the rest of
    the studio measures, come to the same verdict for the same reasons."""
    from app.media.models import QualityControlReport
    from app.media.qc import evaluate_media_qc
    from sqlalchemy import select

    through_the_stage = _rendered_video(engine, tmp_path / "one.mp4")
    on_its_own = _rendered_video(engine, tmp_path / "two.mp4")

    build_stage_runners(engine, settings, _vault(engine), ProviderRegistry())["edit_and_qc"]()
    alone = evaluate_media_qc(engine, on_its_own, str(uuid4()), settings=settings)

    with Session(engine) as session:
        report = session.scalars(
            select(QualityControlReport).where(
                QualityControlReport.media_asset_id == through_the_stage
            )
        ).one()
        checks = dict(report.checks_json)
        status, reasons = report.status, list(report.failure_reasons_json or [])
    assert checks["picture_qc"]["status"] == "NOT_APPLICABLE", checks["picture_qc"]
    assert checks["picture_qc"]["passed"] is None
    assert checks["character_drift_qc"]["passed"] is None
    # The check certified nothing, so it changed nothing: the same verdict for the same
    # number of reasons, and not one of them about a picture. (The reasons themselves carry
    # the encoder's message about each file, which names the file, so they are counted
    # rather than compared word for word.)
    assert status == alone["status"]
    assert len(reasons) == len(alone["failure_reasons_json"])
    assert not [line for line in reasons if "imagin" in line.lower() or "scen" in line.lower()]


def test_the_render_is_offered_the_second_vendor_and_the_scenes_reference(
    engine, settings, monkeypatch
):
    """The plan resolves the Owner's approved alternative and the character's reference
    picture; a render that is never handed either draws every scene with the first vendor
    and invents the face of a character whose look is locked."""
    from app.runbook import stages

    _autonomy_on(engine)
    board = _approved_board(engine, "A factual short")
    chain = [object(), object()]

    def reference_for_scene(scene: dict) -> None:
        return None

    monkeypatch.setattr(stages, "story_gate", lambda session, script_id: (True, ""))
    monkeypatch.setattr(
        "app.media.factory.render_plan",
        lambda engine_, vault, board_id: {
            "image": chain[0],
            "image_chain": chain,
            "reference_for_scene": reference_for_scene,
            "tts_for_scene": lambda *a: None,
            "video_for_scene": lambda *a: None,
            "plan": {},
        },
    )
    captured: dict[str, Any] = {}

    def camera(engine_, storyboard_id, correlation_id, **kwargs):
        captured.update(kwargs)
        return {"output_asset_id": f"asset-{storyboard_id[:8]}", "job_id": str(uuid4())}

    monkeypatch.setattr("app.media.assembler.assemble_video_job", camera)

    outcome = stages._media(engine, settings, None, None)

    assert outcome["status"] == "COMPLETED", outcome
    assert outcome["artefacts"]["assets"] == [f"asset-{board[:8]}"]
    assert captured["image_chain"] is chain
    assert captured["reference_for_scene"] is reference_for_scene


def test_a_locked_character_without_a_reference_refuses_the_film_and_lets_the_hold_go(
    engine, settings, monkeypatch
):
    """A refusal to invent a locked character's face is not a vendor error and not a fault:
    the film is not made, the money pledged to it goes back the same second, and the stage
    names the character rather than drawing somebody else."""
    from app.media.services import ReferenceRequired
    from app.runbook import stages

    _autonomy_on(engine)
    _approved_board(engine, "A factual short")
    _media_stage_with_a_fake_camera(monkeypatch, [])

    def refuses(*args: Any, **kwargs: Any) -> None:
        raise ReferenceRequired("Sarah are înfățișarea blocată și nu are imagine de referință.")

    monkeypatch.setattr("app.media.assembler.assemble_video_job", refuses)

    outcome = stages._media(engine, settings, None, None)

    assert outcome["status"] == "COMPLETED", outcome
    assert "Sarah" in outcome["reason"]
    (hold,) = _reservations(engine)
    assert hold.status == "RELEASED"


# ------------------------------------------------- the day's stages, by the Owner's mode --


def _mode(engine, mode: str) -> None:
    """The Owner's mode, written as his command writes it (the command itself is tested in
    tests/test_autonomy_modes.py; this is the state the stages then read)."""
    from app.models import OwnerPolicy

    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_mode = mode


def _approvals(engine) -> list[Any]:
    from app.models import ApprovalRequest
    from sqlalchemy import select

    with Session(engine) as session:
        return list(session.scalars(select(ApprovalRequest)))


def test_every_stage_of_the_day_carries_a_risk_tier_and_the_two_tables_agree():
    """A stage with no tier is a stage no mode can reason about, and a tier that disagrees
    with the governance table is two answers to one question."""
    from app.runbook.services import STAGES
    from app.runbook.stages import STAGE_ACTIONS
    from app.services import ACTION_RISK_TIERS

    # Preflight reads the studio's own state and the daily log is the run's own record;
    # neither is an action an agent takes, and neither has a runner.
    assert set(STAGE_ACTIONS) == set(STAGES) - {"preflight", "daily_log"}
    for stage, (action, tier) in STAGE_ACTIONS.items():
        assert tier in ("T0", "T1", "T2", "T3"), stage
        known = ACTION_RISK_TIERS.get(action)
        assert known in (None, tier), (stage, action, known, tier)


def test_a_manual_studio_films_nothing_and_publishes_nothing_on_its_own(
    engine, settings, tmp_path, monkeypatch
):
    """MANUAL is 51's "agents may draft/analyze": a paid render (T2) and an upload (T3) are
    both above what the mode allows, so both stages report that they could not run and say
    whose decision it is."""
    from app.publishing.models import PublicationRecord
    from sqlalchemy import select

    _autonomy_on(engine)
    _mode(engine, "MANUAL")
    _seeded_channels(engine)
    _serial_film(engine, tmp_path)
    _approved_board(engine, "A factual short")
    _media_stage_with_a_fake_camera(monkeypatch, [])
    runners = build_stage_runners(engine, settings, _vault(engine), ProviderRegistry())

    media = runners["media"]()
    publish = runners["publish"]()

    assert media["status"] == "SKIPPED", media
    # The mode in words; the code is the preflight artefact's.
    assert "este manual" in media["reason"]
    assert publish["status"] == "SKIPPED", publish
    assert "este manual" in publish["reason"]
    assert _reservations(engine) == [], "a film the mode forbids must not hold money"
    with Session(engine) as session:
        assert session.scalars(select(PublicationRecord)).all() == []


def test_a_supervised_studio_asks_the_owner_instead_of_publishing(
    engine, settings, tmp_path, monkeypatch
):
    """SUPERVISED runs the routine internal stages and turns the external write into the
    Approval object of 31 — one row, with the tier and the requester on it, not a silent
    skip and not an upload."""
    from app.publishing.models import PublicationRecord
    from sqlalchemy import select

    _autonomy_on(engine)
    _mode(engine, "SUPERVISED")
    channels = _seeded_channels(engine)
    _serial_film(engine, tmp_path)
    _bound(engine, channels["OFFICE_SERIAL"]["id"], _connected(engine, "Serial account"))
    publisher = _RecordingPublisher()
    monkeypatch.setattr("app.runbook.stages.selected_youtube", lambda *a, **k: publisher)
    _director_and_publisher_agree(monkeypatch)
    runners = build_stage_runners(engine, settings, _vault(engine), ProviderRegistry())

    outcome = runners["publish"]()

    assert outcome["status"] == "SKIPPED", outcome
    assert "este supravegheat" in outcome["reason"]
    assert publisher.uploads == []
    (request,) = _approvals(engine)
    assert (request.action, request.risk_tier, request.result) == (
        "publishing.public_publish",
        "T3",
        "PENDING",
    )
    with Session(engine) as session:
        assert session.scalars(select(PublicationRecord)).all() == []


def test_a_film_dearer_than_the_owners_threshold_is_his_decision_even_in_supervised(
    engine, settings, monkeypatch
):
    """A paid render inside the Owner's budget is T2 and SUPERVISED performs it; 31 reserves
    T3 for "paid generation beyond threshold", so the film whose estimate passes his line is
    asked about rather than bought — and nothing is held for it."""
    from app.runbook import stages

    _autonomy_on(engine)
    _mode(engine, "SUPERVISED")
    settings.paid_generation_approval_threshold_usd = 0.0
    _approved_board(engine, "A factual short")
    rendered: list[str] = []
    _media_stage_with_a_fake_camera(monkeypatch, rendered)

    outcome = stages._media(engine, settings, None, None)

    assert outcome["status"] == "SKIPPED", outcome
    assert rendered == []
    assert _reservations(engine) == []
    (request,) = _approvals(engine)
    assert request.action == "media.paid_generation_over_threshold"
    assert request.risk_tier == "T3"
    # The estimate is what the Owner is being asked about; None would be a question with no
    # figure in it, and zero would be a lie about a film that costs money.
    assert request.cost_usd is not None and request.cost_usd > 0


# ------------------------------------------------ the Owner answers, and the day acts on it --


def _answer(engine, approval_id: str, decision: str, note: str | None = None) -> None:
    """The Owner's command, as his route calls it (the command itself is held by
    tests/test_approvals.py; here it is the answer the stage then reads)."""
    from app.schemas import ApprovalDecisionCommand
    from app.services import decide_approval

    decide_approval(
        engine,
        ApprovalDecisionCommand(
            command_id=uuid4(), approval_id=approval_id, decision=decision, note=note
        ),
    )


def _a_supervised_studio_with_one_film_ready(engine, settings, tmp_path, monkeypatch):
    """A SUPERVISED studio with a QC-passed serial episode and its slot bound: the exact
    state in which the publish stage asks the Owner instead of uploading."""
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


def test_the_owners_approval_lets_the_film_out_and_the_yes_is_spent_on_it(
    engine, settings, tmp_path, monkeypatch
):
    """The half of SUPERVISED that did not exist: the stage asked, and nothing ever came
    back. The next run finds the answer, uploads the film it was about, and marks the yes
    spent so no second film and no second day can ride on it."""
    from app.models import ApprovalRequest

    runners, publisher, _ = _a_supervised_studio_with_one_film_ready(
        engine, settings, tmp_path, monkeypatch
    )

    asked = runners["publish"]()
    (request,) = _approvals(engine)
    assert asked["status"] == "SKIPPED" and publisher.uploads == []
    assert asked["artefacts"]["approval_id"] == request.id

    _answer(engine, request.id, "APPROVED")
    published = runners["publish"]()

    assert published["status"] == "COMPLETED", published
    assert len(publisher.uploads) == 1
    with Session(engine) as session:
        spent = session.get(ApprovalRequest, request.id)
        assert spent.consumed_at is not None
        assert spent.subject == request.subject != ""
    # And no new question was raised for a film that has now gone out.
    assert [row.id for row in _approvals(engine)] == [request.id]


def test_a_film_the_owner_refused_stays_qc_passed_and_unpublished_and_is_not_asked_again(
    engine, settings, tmp_path, monkeypatch
):
    """A refusal is the day's work done and the answer being no — the same shape as the
    Director's refusal — so the stage is COMPLETED, says in Romanian that the Owner refused,
    and leaves the film exactly where it was."""
    from app.media.models import QualityControlReport
    from app.publishing.models import PublicationRecord
    from sqlalchemy import select

    runners, publisher, _ = _a_supervised_studio_with_one_film_ready(
        engine, settings, tmp_path, monkeypatch
    )

    runners["publish"]()
    (request,) = _approvals(engine)
    _answer(engine, request.id, "REFUSED", note="Nu episodul acesta pe canal.")
    refused = runners["publish"]()
    again = runners["publish"]()

    assert refused["status"] == "COMPLETED", refused
    assert "refuzat" in refused["reason"].lower()
    assert "Nu episodul acesta pe canal." in refused["reason"]
    assert publisher.uploads == []
    with Session(engine) as session:
        assert session.scalars(select(PublicationRecord)).all() == []
        # The film keeps the verdict quality control gave it: the Owner said no to sending
        # it out, not that there is anything wrong with it.
        assert {report.status for report in session.scalars(select(QualityControlReport))} == {
            "PASSED"
        }
    # Nothing asks him again the same day: one row, still his refusal.
    assert [(row.id, row.result) for row in _approvals(engine)] == [(request.id, "REFUSED")]
    assert again["status"] == "COMPLETED"


# ----------------- the day tells him the moment it stops, and with a figure that is honest --


def _owner_letters(engine, kind: str) -> list[Any]:
    from app.agents.models import AgentMessage
    from sqlalchemy import select

    with Session(engine) as session:
        return [
            message
            for message in session.scalars(select(AgentMessage))
            if isinstance(message.body_json, dict) and message.body_json.get("kind") == kind
        ]


def test_the_owner_is_told_when_the_media_stage_stops_and_not_only_at_the_days_close(
    engine, settings, monkeypatch
):
    """Measured before this: `waiting_approvals_letter` was called only from `reconcile_day`,
    which runs inside `_post_run` — the last working stage of the day. A media stage that
    stopped at 05:30 under SUPERVISED left its question in a page nobody was told to open,
    and a run that never reached `_post_run` left it there until it expired twenty-four hours
    later and the film was never made. The letter is now written where the question is born,
    and the once-a-day idempotency keeps the day's close from writing a second one.
    """
    from app.agents.services import seed_initial_workforce
    from app.runbook import stages

    _autonomy_on(engine)
    _mode(engine, "SUPERVISED")
    seed_initial_workforce(engine)
    settings.paid_generation_approval_threshold_usd = 0.0
    _approved_board(engine, "A factual short")
    rendered: list[str] = []
    _media_stage_with_a_fake_camera(monkeypatch, rendered)

    outcome = stages._media(engine, settings, None, None)

    assert outcome["status"] == "SKIPPED" and rendered == []
    (request,) = _approvals(engine)
    letters = _owner_letters(engine, "owner_waiting")
    assert len(letters) == 1, "the stage that raised the question also wrote the letter"
    assert [q["id"] for q in letters[0].body_json["questions"]] == [request.id]

    # The same day again — the run retried, or the close reaching `reconcile_day` — is still
    # one letter: the Owner must not be taught that this letter is noise.
    stages._media(engine, settings, None, None)
    from app.economy.accountant import waiting_approvals_letter

    waiting_approvals_letter(engine, str(uuid4()))
    assert [m.id for m in _owner_letters(engine, "owner_waiting")] == [letters[0].id]


def test_the_question_carries_the_same_caveat_as_the_figure_it_asks_about(
    engine, settings, monkeypatch
):
    """The estimate the Owner answers is the one `estimate_film_cost_micros` computed, so
    where that figure counted the narration as nothing the question says so. Before this the
    caveat reached the reservation's note — a row he never reads — and never the question."""
    from app.economy.budget import UNPRICED_CAVEAT_PREFIX
    from app.runbook import stages

    _autonomy_on(engine)
    _mode(engine, "SUPERVISED")
    settings.paid_generation_approval_threshold_usd = 0.0
    _approved_board(engine, "A factual short")
    _media_stage_with_a_fake_camera(monkeypatch, [])

    stages._media(engine, settings, None, None)

    (request,) = _approvals(engine)
    assert UNPRICED_CAVEAT_PREFIX in (request.evidence or ""), request.evidence
    assert "narația" in (request.evidence or "")


def test_a_hold_taken_on_an_incomplete_estimate_says_so_in_its_own_note(
    engine, settings, monkeypatch
):
    """The note the books keep beside the money says what the figure was missing, in the
    same words the question and the letter use."""
    from app.economy.budget import unpriced_caveat
    from app.runbook import stages

    _autonomy_on(engine)
    _approved_board(engine, "A factual short")
    _media_stage_with_a_fake_camera(monkeypatch, [])

    stages._media(engine, settings, None, None)

    (hold,) = _reservations(engine)
    assert unpriced_caveat(["narration"]) in (hold.note or ""), hold.note


# ------------------------------------------- the content gate refuses one storyboard --


def _approved_script(engine, title: str) -> str:
    """An APPROVED script with no storyboard yet, as the Director's approval leaves it."""
    from app.factual.models import ScriptDraft

    topic_id = _topic(engine, status="SELECTED")
    script_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            ScriptDraft(
                id=script_id,
                topic_id=topic_id,
                version=1,
                title=title,
                target_duration_seconds=12,
                voiceover_full_text="One line.",
                scenes_json=[],
                status="APPROVED",
                claim_ids_json=[],
                unverified_claim_ids_json=[],
                created_at=utc_now(),
            )
        )
    return script_id


def test_a_storyboard_the_content_gate_refuses_is_named_and_the_day_goes_on(
    engine, settings, monkeypatch
):
    """A card whose numbers no SUPPORTED claim states stops its storyboard (SCENE_KINDS); the
    stage names it in the day's reason and storyboards the other approved script."""
    from app.factual.services import FactualGateError
    from app.runbook import stages

    gated = _approved_script(engine, "A chart with a false bar")
    kept = _approved_script(engine, "A film whose numbers hold")
    styles: list[Any] = []

    def storyboard(engine_, script_id, style, ratio, correlation):
        styles.append(style)
        if script_id == gated:
            raise FactualGateError(
                "Poarta de conținut a oprit storyboardul: Scena 5: valoarea 89 nu este "
                "a niciunei afirmații SUPPORTED.",
                [],
            )
        return {"id": str(uuid4()), "script_draft_id": kept}

    passed = SimpleNamespace(verdict="PASS", notes_json={})
    monkeypatch.setattr(stages, "latest_review", lambda session, script_id: passed)
    monkeypatch.setattr(stages, "generate_storyboard_from_script", storyboard)
    monkeypatch.setattr(stages, "write_shot_prompts", lambda *a, **k: {"shots": [1, 2]})
    registry = ProviderRegistry()
    registry.register("any", object())

    outcome = stages._script_and_storyboard(engine, registry)

    assert outcome["status"] == "COMPLETED", outcome
    assert outcome["artefacts"]["storyboards"] == 1
    (refused,) = outcome["artefacts"]["storyboards_gated"]
    assert refused.startswith(gated[:8]) and "Scena 5" in refused
    assert "1 storyboard oprit la poarta de conținut" in outcome["reason"]
    # No style is named for the film: each scene carries its own kind.
    assert styles == [None, None]


# --------------------------------- the daily run follows the staircase (PRODUCTION) --
#
# In PRODUCTION the media stage no longer buys a whole film. It builds the shooting sheet
# (0 credits, one free balance read) and hands the first step that has something to buy to
# `run_sheet_step`, which asks the Owner (202) unless his yes for THIS sheet is standing, and
# then spends it and buys that step alone. The stage writes him the sheet and a letter and
# goes on. Every vendor below is a spy; the Owner's own database is never opened.

LIVE_DB = Path(__file__).resolve().parents[1] / "data" / "studio.db"


def _stamp(path: Path) -> tuple[int, int] | None:
    if not path.exists():
        return None
    stat = path.stat()
    return (stat.st_size, stat.st_mtime_ns)


#: The Owner's database as this module found it; no test here may change it.
LIVE_DB_AT_IMPORT = _stamp(LIVE_DB)

requires_ffmpeg = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")


def _production(engine, mode: str = "AUTONOMOUS_CEO") -> None:
    """The studio in PRODUCTION, autonomy on, in the Owner's mode, with its employees."""
    from app.agents.services import seed_initial_workforce
    from app.models import OwnerPolicy

    _autonomy_on(engine)
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.environment = "PRODUCTION"
        policy.autonomy_mode = mode
    seed_initial_workforce(engine)


def _bottom_of_the_staircase(engine, tmp_path, scenes: int = 2) -> str:
    """A film with model-written, lint-clean prompts and no still bought yet."""
    from app.media.models import SceneTake
    from sqlalchemy import select
    from test_film_costing import a_film

    storyboard_id = a_film(engine, tmp_path, scenes=scenes)
    with Session(engine) as session, session.begin():
        for take in session.scalars(
            select(SceneTake).where(SceneTake.storyboard_id == storyboard_id)
        ):
            session.delete(take)
    return storyboard_id


def _noise_stills(tmp_path) -> tuple[Path, Path]:
    """Two detailed 1080x1920 pictures with nobody in them: the stills gate's local checks
    (a real picture, sharpness, motion blur, YuNet) read them as good stills."""
    made = []
    for seed in (1, 2):
        path = tmp_path / f"noise_{seed}.jpg"
        subprocess.run(  # noqa: S603 - the local encoder, arguments built here
            [
                str(find_ffmpeg()),
                "-nostdin",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"color=c=gray:s=1080x1920,noise=alls=40:allf=t:all_seed={seed}",
                "-frames:v",
                "1",
                "-q:v",
                "3",
                "-y",
                str(path),
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
        made.append(path)
    return made[0], made[1]


def _staircase_world(engine, tmp_path, monkeypatch, *, stills=None) -> dict[str, Any]:
    """The vendors, faked, as the stage's wiring hands them over; the legacy render refuses."""
    from app.runbook import stages
    from test_film_costing import SEEDANCE, Account, Models, SpyVideo
    from test_stills_stage import SpyStills

    account = Account(10_000)
    pictures = (lambda prompt, call: list(stills)) if stills else None
    images = SpyStills(pictures=pictures, balance=10_000)
    models = Models(SpyVideo("seedance2_5", account))
    monkeypatch.setattr(stages, "story_gate", lambda session, script_id: (True, ""))
    monkeypatch.setattr(
        stages,
        "sheet_wiring",
        lambda engine_, vault, settings_: {
            "integration_id": None,
            "capabilities": [SEEDANCE],
            "image_adapter": images,
            "account": account,
            "adapter_for_model": models,
            "resolution": "1080p",
            "storage_root": tmp_path / "media",
        },
    )

    def legacy(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("the whole-film render ran in PRODUCTION")

    monkeypatch.setattr("app.media.assembler.assemble_video_job", legacy)
    return {"images": images, "models": models, "account": account}


def _judge_sees_good_stills(monkeypatch):
    """The vision model, faked (it is a paid agent run); every local check stays real."""
    import functools

    from app.media import shooting_sheet
    from test_stills_stage import SpyJudge

    judge = SpyJudge()
    monkeypatch.setattr(
        shooting_sheet,
        "run_stills_stage",
        functools.partial(shooting_sheet.run_stills_stage, judge=judge),
    )
    return judge


def _current_sheet_hash(engine, storyboard_id: str) -> str:
    from app.media.shooting_sheet import sheet_hash
    from test_film_costing import SEEDANCE

    return sheet_hash(
        engine,
        storyboard_id,
        capabilities=[SEEDANCE],
        resolution="1080p",
        stills_model="seedream5_pro",
    )


def _provider_costs(engine) -> list[Any]:
    from app.economy.models import ProviderCostRecord
    from sqlalchemy import select

    with Session(engine) as session:
        rows = list(session.scalars(select(ProviderCostRecord)))
        session.expunge_all()
        return rows


def test_in_autonomous_ceo_the_stage_asks_for_the_stills_writes_to_the_owner_and_moves_on(
    engine, settings, tmp_path, monkeypatch
):
    """EVERY_PAID_STEP (the default) asks in every mode, AUTONOMOUS_CEO included: the stage
    builds the sheet, raises the stills question bound to its hash, writes the Owner the sheet
    and a letter, and returns without a single paid call."""
    from app.runbook import stages

    _production(engine, "AUTONOMOUS_CEO")
    storyboard_id = _bottom_of_the_staircase(engine, tmp_path)
    world = _staircase_world(engine, tmp_path, monkeypatch)

    outcome = stages._media(engine, settings, None, None)

    assert outcome["status"] == "SKIPPED", outcome
    assert "așteaptă Proprietarul" in outcome["reason"]
    assert world["images"].asked == [] and world["models"].posts() == 0
    (question,) = _approvals(engine)
    assert question.action == "media.stills_purchase" and question.result == "PENDING"
    assert question.subject == storyboard_id
    plan_hash = _current_sheet_hash(engine, storyboard_id)
    assert question.proposed_diff["plan_hash"] == plan_hash
    assert question.proposed_diff["step"] == "stills"
    assert outcome["artefacts"]["awaiting_owner"][0]["approval_id"] == question.id
    assert outcome["artefacts"]["sheets"] == {storyboard_id: plan_hash}

    (letter,) = _owner_letters(engine, "owner_shooting_sheet")
    body = letter.body_json
    assert body["storyboard_id"] == storyboard_id and body["step"] == "stills"
    assert body["approval_id"] == question.id and body["sheet_hash"] == plan_hash
    assert body["sheet_url"].endswith(f"/media/storyboards/{storyboard_id}/shooting-sheet")
    assert "Foaia de filmare" in letter.subject
    # Two LIVE scenes, two candidates each at 9 credits: 36 credits, 0,36 USD.
    assert "36 de credite (0,36 USD)" in letter.body_text
    assert "așteaptă" in letter.body_text
    assert len(_owner_letters(engine, "owner_waiting")) == 1
    # Nothing was held and nothing was booked: nothing was bought.
    assert _reservations(engine) == [] and _provider_costs(engine) == []

    # The same day again: the same question stands, and the Owner gets no second letter.
    again = stages._media(engine, settings, None, None)
    assert again["status"] == "SKIPPED"
    assert [request.id for request in _approvals(engine)] == [question.id]
    assert len(_owner_letters(engine, "owner_shooting_sheet")) == 1
    assert world["images"].asked == [] and world["models"].posts() == 0


def test_a_film_without_the_models_shot_plan_stops_with_a_romanian_reason_and_spends_nothing(
    engine, settings, tmp_path, monkeypatch
):
    from app.media.models import Storyboard, StoryboardScene
    from app.runbook import stages
    from sqlalchemy import select

    _production(engine)
    storyboard_id = _bottom_of_the_staircase(engine, tmp_path)
    with Session(engine) as session, session.begin():
        row = session.scalars(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 2
            )
        ).one()
        row.prompt_json = {**dict(row.prompt_json), "source": "template"}
    world = _staircase_world(engine, tmp_path, monkeypatch)

    outcome = stages._media(engine, settings, None, None)

    assert outcome["status"] == "SKIPPED", outcome
    assert "planul de cadre" in outcome["reason"]
    assert world["images"].asked == [] and world["models"].posts() == 0
    assert world["account"].reads == 0, "not even the balance was read"
    assert _approvals(engine) == [] and _provider_costs(engine) == []
    with Session(engine) as session:
        assert session.get(Storyboard, storyboard_id).status == "NEEDS_SHOT_PLAN"


def test_a_film_whose_prompts_carry_a_lint_block_stops_before_the_owner_is_asked(
    engine, settings, tmp_path, monkeypatch
):
    from app.media.models import StoryboardScene
    from app.runbook import stages
    from sqlalchemy import select

    _production(engine)
    storyboard_id = _bottom_of_the_staircase(engine, tmp_path)
    with Session(engine) as session, session.begin():
        row = session.scalars(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 1
            )
        ).one()
        words = "Environment: NEPAL_CLIMATE_CRISIS. " + row.prompt_json["still_prompt"]
        row.visual_prompt = words
        row.prompt_json = {**dict(row.prompt_json), "still_prompt": words}
    world = _staircase_world(engine, tmp_path, monkeypatch)

    outcome = stages._media(engine, settings, None, None)

    assert outcome["status"] == "SKIPPED", outcome
    assert "NEPAL_CLIMATE_CRISIS" in outcome["reason"]
    assert "blocaj" in outcome["reason"]
    assert world["images"].asked == [] and world["models"].posts() == 0
    assert _approvals(engine) == [] and _provider_costs(engine) == []
    (letter,) = _owner_letters(engine, "owner_shooting_sheet")
    assert letter.body_json["status"] == "LINT_BLOCKED"
    assert "NEPAL_CLIMATE_CRISIS" in letter.body_text


@requires_ffmpeg
def test_after_the_stills_yes_the_stage_buys_the_stills_only_and_motion_waits_for_its_own_yes(
    engine, settings, tmp_path, monkeypatch
):
    from app.media.models import SceneTake
    from app.runbook import stages
    from sqlalchemy import select

    _production(engine)
    storyboard_id = _bottom_of_the_staircase(engine, tmp_path)
    world = _staircase_world(engine, tmp_path, monkeypatch, stills=_noise_stills(tmp_path))
    judge = _judge_sees_good_stills(monkeypatch)

    stages._media(engine, settings, None, None)
    (stills_question,) = _approvals(engine)
    _answer(engine, stills_question.id, "APPROVED", note="Da, imaginile.")

    bought = stages._media(engine, settings, None, None)

    assert bought["status"] == "COMPLETED", bought
    # The stills step alone: one request of two candidates per LIVE scene, each judged.
    assert [request["count"] for request in world["images"].asked] == [2, 2]
    assert len(judge.looked_at) == 4
    assert world["models"].posts() == 0, "a shot was bought on the stills' yes"
    with Session(engine) as session:
        stills = list(
            session.scalars(
                select(SceneTake).where(
                    SceneTake.storyboard_id == storyboard_id, SceneTake.status == "APPROVED"
                )
            )
        )
    assert sorted(take.scene_number for take in stills) == [1, 2]
    by_action = {request.action: request for request in _approvals(engine)}
    assert by_action["media.stills_purchase"].consumed_at is not None
    # The hero test shot is the next question, bound to the sheet as it is after the stills.
    hero_question = by_action["media.test_shot"]
    assert hero_question.result == "PENDING"
    assert hero_question.proposed_diff["plan_hash"] == _current_sheet_hash(engine, storyboard_id)
    assert "media.motion_purchase" not in by_action
    assert "așteaptă Proprietarul" in bought["reason"]
    # What the stills cost is in the books: the measured balance drop, 36 credits.
    (cost,) = _provider_costs(engine)
    assert cost.attribution_json["step"] == "stills"
    assert cost.attribution_json["credits"] == 36 and cost.usd_micros == 360_000

    # His yes to the hero buys the hero alone; the rest of the motion waits for his look at
    # it and for a yes of its own.
    _answer(engine, hero_question.id, "APPROVED", note="Da, cadrul de probă.")
    hero = stages._media(engine, settings, None, None)

    assert world["models"].posts() == 1, hero
    actions = [request.action for request in _approvals(engine)]
    assert "media.motion_purchase" not in actions
    assert "cadrul de probă" in hero["reason"] and "așteaptă Proprietarul" in hero["reason"]
    look = [
        letter
        for letter in _owner_letters(engine, "owner_shooting_sheet")
        if letter.body_json["status"] == "HERO_NOT_APPROVED"
    ]
    assert len(look) == 1 and "așteaptă decizia ta" in look[0].subject
    assert len(_provider_costs(engine)) == 2


def test_every_bought_step_leaves_the_film_to_be_assembled_from_its_takes(
    engine, settings, tmp_path, monkeypatch
):
    """When the sheet has nothing left to buy, the stage assembles the film from its takes:
    no image or video adapter is asked, and only the narration is held in the budget."""
    from app.runbook import stages

    _production(engine)
    storyboard_id = _bottom_of_the_staircase(engine, tmp_path)
    world = _staircase_world(engine, tmp_path, monkeypatch)
    monkeypatch.setattr(
        "app.media.shooting_sheet.build_sheet",
        _sheet_with_nothing_to_buy(storyboard_id),
    )
    assembled: list[dict[str, Any]] = []

    def from_takes(engine_, board, correlation, **render):
        assembled.append({"storyboard_id": board, **render})
        return {"output_asset_id": "asset-from-takes", "job_id": str(uuid4())}

    monkeypatch.setattr("app.media.assembler.assemble_from_takes", from_takes)
    monkeypatch.setattr(
        "app.media.factory.render_plan",
        lambda engine_, vault, board: {"tts_for_scene": lambda *a: None, "plan": {}},
    )
    monkeypatch.setattr("app.media.factory.tts_provider", lambda engine_, vault: None)

    outcome = stages._media(engine, settings, None, None)

    assert outcome["status"] == "COMPLETED", outcome
    assert outcome["artefacts"]["assets"] == ["asset-from-takes"]
    (call,) = assembled
    assert call["storyboard_id"] == storyboard_id
    assert "image_adapter" not in call and "motion_chooser" not in call
    assert world["images"].asked == [] and world["models"].posts() == 0
    assert _approvals(engine) == []


def _sheet_with_nothing_to_buy(storyboard_id: str):
    """build_sheet as it reads once every step is bought: nothing left on any stair."""

    def build(engine_, board, **_context):
        step = {"to_buy": [], "cost_credits": 0, "cap_credits": 0, "cost_usd": 0.0}
        return {
            "storyboard_id": board,
            "title": "A film",
            "sheet_hash": "f" * 64,
            "credit_usd": 0.01,
            "scenes": [],
            "steps": {"stills": step, "test_shot": step, "motion": step},
            "lint_blocked": False,
            "lint_summary_ro": "",
            "shot_plan_gaps": [],
            "footer": {
                "stills_credits": 36,
                "hero_credits": 340,
                "rest_credits": 340,
                "cap_credits": 1056,
                "total_credits": 716,
                "balance": {"credits": 9000.0, "read": True, "problem": None},
            },
        }

    return build


def test_the_daily_job_is_never_activated_by_any_test(engine, settings, tmp_path, monkeypatch):
    """The staircase stage runs on a temporary studio: no schedule wakes, no clock is started,
    and the Owner's own database is untouched by anything in this module."""
    from app.models import DomainEvent
    from app.runbook import stages
    from app.workflows.models import ScheduledJob
    from sqlalchemy import select

    _production(engine)
    _bottom_of_the_staircase(engine, tmp_path)
    _staircase_world(engine, tmp_path, monkeypatch)

    stages._media(engine, settings, None, None)

    with Session(engine) as session:
        assert not list(session.scalars(select(ScheduledJob).where(ScheduledJob.is_active)))
        assert not list(
            session.scalars(
                select(DomainEvent).where(DomainEvent.event_type == "workflow.job_activated")
            )
        )
    assert Path(str(engine.url.database)).resolve() != LIVE_DB.resolve()
    assert LIVE_DB.as_posix() not in settings.database_url
    assert _stamp(LIVE_DB) == LIVE_DB_AT_IMPORT
    source = Path(__file__).read_text(encoding="utf-8")
    for name in ("set_job_" + "active", "scheduler_" + "tick", "ensure_scheduled_" + "job"):
        assert name not in source, name
