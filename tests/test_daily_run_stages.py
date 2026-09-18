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

from typing import Any
from uuid import uuid4

import pytest
from app.factual.models import FactualClaim, TopicIdea
from app.factual.services import TopicNotProducible, select_topic
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
    assert "respinse" in outcome["reason"]


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
    assert "refuzate de furnizor" in outcome["reason"]
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
