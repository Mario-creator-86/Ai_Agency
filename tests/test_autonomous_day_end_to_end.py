"""One scheduled day, from the clock to a published film — the test the project never had.

Every other test in this suite holds one piece: a stage, a gate, a ledger, a queue. Nothing
held the whole day together, so the studio could pass a thousand tests and still fail at the
seam between two of them — which is where a day actually breaks. This drives the real thing:
the scheduler fires the daily job, the queue hands the task to the worker, and the worker
executes the runbook with the real stage runners, twelve stages in order, against a
temporary database.

WHAT IS REAL HERE: the scheduler, the task queue and its idempotency key, the runbook and
its stage order, the Policy Kernel and every gate it runs, the factual gate, the story
review and the Director's approval, the budget hold and its settlement, FFmpeg encoding two
real films, quality control measuring the encoded files, the publishing gate's five checks,
the channel routing and the Owner's visibility policy, the serial's projection, grounding
and continuity, and the day's own log.

WHAT IS FAKED, and nothing else: the vendors. One language model stands in for every
employee's model and answers each prompt with output valid for that prompt's schema — it is
not pretending to be intelligent, only to be well-formed, and the studio's own checks (the
quote must appear in the source, the claim ids must be the ones supplied, the beats must
cite events that happened) are what make its answers usable or not. The picture and the
voice come from the deterministic local adapters under a test provider name, so the frames
and the audio are real files that FFmpeg and FFprobe measure, bought from nobody. The
publisher is the deterministic simulator, injected. No socket leaves this machine
(tests/conftest.py refuses one), and so the Owner's rule holds: nothing here costs money.
"""

from __future__ import annotations

import json
import random
import re
import shutil
import struct
import zlib
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.agents.services import seed_initial_workforce
from app.factual.models import TopicIdea
from app.factual.services import ingest_source_snapshot
from app.media.models import QualityControlReport, Storyboard
from app.media.toolchain import find_ffmpeg
from app.models import DomainEvent, OwnerPolicy
from app.providers.base import GenerateResult, HealthResult
from app.providers.deterministic_media import DeterministicTTSAdapter, DeterministicVisualAdapter
from app.providers.registry import ProviderRegistry
from app.publishing.models import ChannelRecord, PublicationRecord
from app.runbook.models import DailyRun
from app.runbook.services import STAGES
from app.runbook.stages import build_stage_runners
from app.services import utc_now
from app.story.models import StoryEpisode
from app.story.services import business_date
from app.workflows.models import TaskQueueItem
from app.workflows.services import ensure_scheduled_job, scheduler_tick
from app.workflows.worker import DAILY_RUN, build_task_handlers, worker_pass
from sqlalchemy import select
from sqlalchemy.orm import Session

# The studio refuses to fake a render, so without an encoder there is no film to measure,
# no quality control verdict and nothing to publish: the day would be honest and empty,
# which is not what this test is about.
requires_ffmpeg = pytest.mark.skipif(
    find_ffmpeg() is None, reason="FFmpeg not installed; a day cannot be filmed"
)

TZ = "Europe/Bucharest"

#: The one fact the studio is allowed to say today. The verifier's quote is checked against
#: the stored source verbatim, so the source, the claim and the quote are the same sentence.
FACT = "The James Webb telescope observes the universe in infrared light."

#: A beat's dialogue: three of these are about 130 spoken words, inside the serial's own
#: 45-70 second window. Nothing in it is a price, a model name or an address, because the
#: episode's privacy check reads every line.
BEAT_LINE = (
    "Sarah opens the board and asks for the number before anyone says good morning. "
    "Aris answers with the evidence first and the opinion never, which is his whole style. "
    "The room laughs, the cup goes down, and the day has officially started in here."
)

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


# --------------------------------------------------------------------- the faked vendors --


class StudioModel:
    """One language model for every employee, answering each prompt in that prompt's schema.

    It reads the prompt for the shape it is being asked for and fills it from what the prompt
    itself carries — the claim ids the writer was given, the event ids of the day, the cast.
    An answer that invented an identifier would be refused by the studio, which is the point:
    what makes this stand-in usable is the same thing that makes a real model usable.
    """

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def health_check(self) -> HealthResult:
        return HealthResult("HEALTHY")

    async def list_models(self) -> list[dict[str, Any]]:
        return []

    async def generate(self, model: str, prompt: str, **kwargs: Any) -> GenerateResult:
        self.prompts.append(prompt)
        return GenerateResult(self._answer(prompt), 12, 48, None)

    # -- the shapes, most specific marker first ---------------------------------------

    def _answer(self, prompt: str) -> str:
        if "evidence_quote" in prompt:
            return json.dumps(
                {
                    "status": "SUPPORTED",
                    "confidence": 0.95,
                    "evidence_quote": FACT,
                    "notes": "Sursa afirmă exact acest lucru.",
                }
            )
        if "claim_type" in prompt:
            return json.dumps(
                [
                    {
                        "claim_text": FACT,
                        "claim_type": "SCIENTIFIC_FACT",
                        "importance": "CRITICAL",
                        "confidence": 0.95,
                    }
                ]
            )
        if "core_message" in prompt:
            return self._script(prompt)
        if "hook_strength" in prompt:
            return json.dumps(
                {
                    "verdict": "PASS",
                    "hook_strength": 82,
                    "clarity": 85,
                    "payoff": 80,
                    "cta_fit": 78,
                    "retention": {"at_0": 100, "at_3": 88, "at_end": 61, "collapse_at": "none"},
                    "notes": [],
                }
            )
        if "continuity_rules" in prompt:
            return json.dumps(
                {
                    "style": "documentary photography, restrained",
                    "realism": "photoreal",
                    "period": "present day",
                    "world": "an observatory at night and the sky it watches",
                    "palette": "deep blue, warm amber highlights",
                    "lighting": "low key, one warm source",
                    "camera_language": "slow, deliberate, mostly static",
                    "weather": "clear",
                    "continuity_rules": ["the same night sky in every shot"],
                    "avoid": ["written text of any kind"],
                }
            )
        if "ending_frame" in prompt:
            return self._shots(prompt)
        if "pronunciation" in prompt:
            return json.dumps({"verdict": "PASS", "notes": [], "pronunciation": []})
        if "hold_reasons" in prompt:
            return json.dumps(
                {
                    "verdict": "READY",
                    "title": "Infrared light and what it shows",
                    "description": "What a telescope sees when it looks in infrared.",
                    "tags": ["space", "astronomy"],
                    "hold_reasons": [],
                }
            )
        if "notes_for" in prompt:
            return json.dumps(
                {
                    "verdict": "APPROVE",
                    "story": "One idea, carried to its end.",
                    "reasons": ["The narration rests on the verified claim."],
                    "notes_for": {},
                }
            )
        if "event_ids" in prompt:
            return self._episode(prompt)
        if '"verdict": "PASS" | "FAIL"' in prompt:
            return json.dumps(
                {
                    "verdict": "PASS",
                    "reasons": ["One situation, a turn, a payoff."],
                    "notes": "",
                    "story": "A morning in the office, told once.",
                }
            )
        if "assign_to_role" in prompt:
            return self._director(prompt)
        # Anything not asked for above is answered in prose, which every caller treats as an
        # answer it could not parse — and none of them may take the day down for it.
        return "Nimic de raportat."

    def _script(self, prompt: str) -> str:
        claim_ids = sorted(set(_UUID.findall(prompt)))
        narration = [
            (
                "Most of what the universe is doing happens in light your eyes will never "
                "catch, and that is where this story starts tonight."
            ),
            (
                "The James Webb telescope observes the universe in infrared light, which is "
                "the part of the spectrum that carries heat rather than colour."
            ),
            (
                "So the dust that hides a young star from us is no longer a wall, and the "
                "picture underneath it finally arrives."
            ),
            (
                "Look up tonight and remember that the dark you see is only the part of the "
                "sky your eyes were built for."
            ),
        ]
        purposes = ["HOOK", "EVIDENCE", "PAYOFF", "ENDING"]
        visuals = [
            "a dark sky over a silent observatory dome",
            "the telescope's mirror, cold and segmented, filling the frame",
            "dust clearing from around a young star",
            "a person looking up from a field at night",
        ]
        return json.dumps(
            {
                "title": "The light your eyes were not built for",
                "core_message": "Infrared shows what visible light hides.",
                "takeaway": "The sky is not as empty as it looks.",
                "hook": narration[0],
                "ending": narration[-1],
                "cta": "Look up tonight and ask what else is hiding.",
                "cta_kind": "CURIOSITY",
                "scenes": [
                    {
                        "narration": line,
                        "visual": visual,
                        "purpose": purpose,
                        "claim_ids": claim_ids[:1],
                    }
                    for line, visual, purpose in zip(narration, visuals, purposes, strict=True)
                ],
            }
        )

    def _shots(self, prompt: str) -> str:
        indices = sorted({int(n) for n in re.findall(r'"scene_index":\s*(\d+)', prompt)}) or [1]
        return json.dumps(
            {
                "shots": [
                    {
                        "scene_index": index,
                        "story_purpose": "EVIDENCE",
                        "subject": "the observatory dome against the night",
                        "action": "the dome turns slowly, its shutter opening on the sky",
                        "environment": "a cold hillside under clear stars",
                        "camera": "wide, low angle, static",
                        "lighting": "moonlight from the left, one warm lamp behind",
                        "composition": "vertical, the dome low in frame",
                        "motion": "slow rotation, nothing else moves",
                        "emotion": "quiet anticipation",
                        "background": "stars, unmoving",
                        "continuity": "the same sky as the previous shot",
                        "ending_frame": "the open shutter, centred",
                        "audio_intent": "wind, distant",
                        "transition": "cut",
                        "avoid": ["text of any kind"],
                    }
                    for index in indices
                ]
            }
        )

    def _episode(self, prompt: str) -> str:
        # The cast is read from the cast section alone and the events from theirs: a name
        # lifted out of an event's description would put someone in a room the record says
        # they were not in, and the episode's own grounding check would refuse the episode.
        cast_block = prompt.split("DISTRIBUȚIA DE AZI", 1)[-1].split("EVENIMENTELE DE AZI", 1)[0]
        events_block = prompt.split("EVENIMENTELE DE AZI", 1)[-1]
        events = re.findall(r"^- (" + _UUID.pattern + r"): ", events_block, re.MULTILINE)
        # A cast line reads "- Sarah (Director) (Director/CEO, ACTIVE) — who she is": the
        # display name carries brackets of its own, so the name is what stands before the
        # bracket that holds the role and the lifecycle, not before the first bracket.
        names = re.findall(r"^- (.+?) \([^()]+, [A-Z]+\)", cast_block, re.MULTILINE)
        if not events or not names:
            return "Nu am din ce scrie episodul."
        beats = [
            {
                "scene": f"Redacția, dimineața. Scena {index + 1}.",
                "dialogue": BEAT_LINE,
                "event_ids": [events[index % len(events)]],
                # Everyone on today's cast is in the first beat: the episode's own check
                # refuses a day in which someone who was there never appears.
                "characters": names if index == 0 else names[:1],
            }
            for index in range(3)
        ]
        return json.dumps(
            {
                "title": "The number before good morning",
                "beats": beats,
                "summary": "Sarah asked for the number; Aris brought the evidence first.",
                "threads_continued": [],
                "threads_closed": [],
                "threads_opened": ["whether anyone will ever bring the number first"],
                "recurring": ["the espresso cup"],
            }
        )

    def _director(self, prompt: str) -> str:
        ids = re.findall(r'"message_id":\s*"([^"]+)"', prompt) or re.findall(
            r'"id":\s*"(' + _UUID.pattern + r')"', prompt
        )
        return json.dumps(
            {
                "summary": "Ziua a mers; nimic nu cere decizia Owner-ului.",
                "decisions": [
                    {"message_id": message_id, "action": "ACKNOWLEDGE", "note": "Citit."}
                    for message_id in sorted(set(ids))[:20]
                ],
                "priorities": ["Ține ritmul zilnic."],
            }
        )


@lru_cache(maxsize=8)
def _noise_png(seed: int, width: int = 270, height: int = 480) -> bytes:
    """A small PNG with structure in both directions, made from nothing but a seed.

    Quality control refuses a still that survives being flattened along either axis —
    stripes, bands, a blank field — because eleven seconds of beige bars once passed as a
    film. A flat test picture would be refused by that check and rightly so, so the fake
    camera returns noise: no vendor, no opinion, and a real picture by that measurement.
    """
    rows = random.Random(seed)
    raw = b"".join(
        bytes([0]) + bytes(rows.randrange(256) for _ in range(width * 3)) for _ in range(height)
    )

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    return (
        bytes.fromhex("89504e470d0a1a0a")
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


class TestImages(DeterministicVisualAdapter):
    """The fake camera: a real PNG per shot, under a provider name that is not PLACEHOLDER.

    Quality control refuses placeholder frames from publication, and it is right to: the
    Owner must never see a slideshow of cards uploaded as a film. Here the frames are real
    PNGs the encoder puts on a real timeline, and the name says which fake made them.
    """

    PROVIDER_NAME = "TEST_IMAGE_PROVIDER"
    model = "test-stills"
    integration_id = None

    async def generate_image(self, prompt: str, **kwargs: Any) -> Any:
        from app.providers.media_base import ImageResult

        index = int((kwargs.get("extra") or {}).get("scene_index") or 1)
        return ImageResult(
            image_bytes=_noise_png(index),
            format="png",
            width=270,
            height=480,
            prompt=prompt,
            cost_vr="0.00",
            raw_response={"engine": "test"},
        )


class TestVoice(DeterministicTTSAdapter):
    PROVIDER_NAME = "TEST_VOICE_PROVIDER"
    model = "test-voice"
    integration_id = None


class RecordingPublisher:
    """The deterministic publishing simulator, remembering what it was asked to upload."""

    def __init__(self) -> None:
        from app.providers.deterministic_pub import DeterministicPublishingAdapter

        self.inner = DeterministicPublishingAdapter()
        self.uploads: list[dict[str, Any]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    async def upload_video(self, file_path: Any, **kwargs: Any) -> Any:
        self.uploads.append(dict(kwargs))
        return await self.inner.upload_video(file_path, **kwargs)


# ------------------------------------------------------------------------ the studio --


def _yesterdays_events(engine) -> None:
    """Three things that happened yesterday, of the kinds the serial may retell."""
    moment = (datetime.now(UTC) - timedelta(days=1)).replace(hour=12).isoformat()
    for event_type, payload in (
        ("factual.topic_selected", {"title": "Infrared light"}),
        ("factual.script_approved", {"claims_count": 1}),
        ("media.video_rendered", {"file_size_bytes": 1}),
    ):
        with Session(engine) as session, session.begin():
            session.add(
                DomainEvent(
                    event_id=str(uuid4()),
                    event_type=event_type,
                    timestamp=moment,
                    aggregate_type="agent",
                    aggregate_id=str(uuid4()),
                    aggregate_version=1,
                    correlation_id=str(uuid4()),
                    causation_id=None,
                    schema_version=1,
                    visibility="OWNER",
                    payload=payload,
                )
            )


@pytest.fixture
def studio(engine, settings, monkeypatch, connect_youtube):
    """A studio that has everything a day needs, and nothing that costs money."""
    from app.media import factory
    from app.media.services import seed_default_character_bibles
    from app.publishing.services import list_channels, seed_default_channels
    from app.runbook import stages

    settings.timezone = TZ
    settings.ffmpeg_path = settings.ffmpeg_path or shutil.which("ffmpeg")
    # The trends feed is the one thing in the day that would reach outside on its own.
    settings.trends_enabled = False

    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    seed_default_channels(engine)
    with Session(engine) as session, session.begin():
        from app.agents.models import ModelRecord

        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for record in session.scalars(select(ModelRecord)):
            record.is_available = True
        # The Owner's standing decision on Channel B: the Director may approve an episode
        # of the serial without him. Written here as his command writes it.
        for channel in session.scalars(
            select(ChannelRecord).where(ChannelRecord.channel_type == "OFFICE_SERIAL")
        ):
            channel.director_may_approve_episodes = True
    with Session(engine) as session:
        from app.agents.models import Agent

        provider_id = session.scalar(select(Agent.provider_id))

    # Two accounts, connected through the real OAuth code path with only Google's HTTP
    # boundary replaced (the `connect_youtube` fixture), and one bound to each channel slot:
    # publishing and analytics both refuse to guess whose numbers are whose.
    channels = {c["channel_type"]: c for c in list_channels(engine)}
    for channel_type, account in (
        ("MAIN_FACTUAL", "Main account"),
        ("OFFICE_SERIAL", "Serial account"),
    ):
        connection_id, _vault = connect_youtube(
            name=account, channel_id=f"UC{uuid4().hex[:16]}", title=account
        )
        with Session(engine) as session, session.begin():
            row = session.get(ChannelRecord, channels[channel_type]["id"])
            row.credentials_ref = f"youtube_connection:{connection_id}"

    # The day's subject, and one page the studio has already read about it. Nothing is
    # verified in advance: the research stage extracts the claim from this source and a
    # second employee checks it against the same text, so the film rests on a claim that
    # went through the real pipeline and carries a source the Director can follow.
    topic_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            TopicIdea(
                id=topic_id,
                title="Infrared light and what it shows",
                topic="Astronomy",
                angle="What a telescope sees that eyes cannot",
                target_audience="science_enthusiasts",
                novelty_score=0.92,
                status="PROPOSED",
                created_at=utc_now(),
            )
        )
    ingest_source_snapshot(
        engine,
        url="https://www.iana.org/help/example-domains",
        title="A page about infrared astronomy",
        publisher="www.iana.org",
        author=None,
        raw_content=FACT,
        credibility_score=0.9,
        correlation_id=str(uuid4()),
        topic_id=topic_id,
    )
    _yesterdays_events(engine)

    # The vendors. The picture and the voice are local files under a test name; the
    # publisher is the simulator; the plan is the plain one a studio with no connections
    # resolves to. Everything between them is the studio's own code.
    publisher = RecordingPublisher()
    monkeypatch.setattr(factory, "image_provider", lambda *a, **k: TestImages())
    monkeypatch.setattr(factory, "tts_provider", lambda *a, **k: TestVoice())
    monkeypatch.setattr(
        factory,
        "render_plan",
        lambda engine_, vault, board: {
            "image": TestImages(),
            "tts_for_scene": lambda *a: TestVoice(),
            "video_for_scene": lambda *a: None,
            "plan": {},
        },
    )
    monkeypatch.setattr(stages, "selected_youtube", lambda *a, **k: publisher)

    model = StudioModel()
    registry = ProviderRegistry()
    registry.register(provider_id, model)
    return {"registry": registry, "model": model, "publisher": publisher, "topic_id": topic_id}


def _due_daily_job(engine) -> str:
    job = ensure_scheduled_job(
        engine, name="daily_main", workflow_type=DAILY_RUN, interval_seconds=86400
    )
    with Session(engine) as session, session.begin():
        from app.workflows.models import ScheduledJob

        session.get(ScheduledJob, job["id"]).next_run_at = (
            datetime.now(UTC) - timedelta(minutes=5)
        ).isoformat()
    return job["id"]


# ------------------------------------------------------------------------- the day --


@requires_ffmpeg
def test_the_clock_starts_a_day_that_ends_in_a_published_film_and_an_episode(
    engine, settings, studio, tmp_path
):
    """The whole day, once, from the scheduler's tick to the film on the channel."""
    from app.integrations.vault import CredentialVault

    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    runners = build_stage_runners(engine, settings, vault, studio["registry"])
    handlers = build_task_handlers(engine, settings, vault, runners, studio["registry"])

    job_id = _due_daily_job(engine)
    triggered = scheduler_tick(engine)
    assert len(triggered) == 1 and triggered[0]["job_id"] == job_id

    result = worker_pass(engine, handlers, registry=studio["registry"])

    # 1. The day ran because the clock said so, and the queue can prove which slot it was.
    (ran,) = [item for item in result["ran"] if item["status"] == "COMPLETED"]
    with Session(engine) as session:
        task = session.get(TaskQueueItem, ran["task_id"])
        assert task.idempotency_key.startswith("scheduled:"), task.idempotency_key
        run = session.scalars(select(DailyRun)).one()
        stages_ran = list(run.stages_json)
    # A failed day names the stage and the reason: read them here, or the assertion below
    # says only that the day did not work.
    assert ran["outcome"]["status"] in ("COMPLETED", "PARTIAL"), (
        run.stopped_at_stage,
        run.stop_reason,
        [(stage["stage"], stage["status"], stage["reason"][:200]) for stage in stages_ran],
    )
    assert run.business_date == business_date(TZ)
    # 2. Twelve stages, each with its own recorded outcome — never a stage left out.
    names = [stage["stage"] for stage in stages_ran]
    assert names == list(STAGES), names
    assert run.stages_total == 12
    by_name = {stage["stage"]: stage for stage in stages_ran}
    for name in ("research_and_verification", "selection", "script_and_storyboard", "media"):
        assert by_name[name]["status"] == "COMPLETED", (name, by_name[name]["reason"])

    with Session(engine) as session:
        # 3. A film was filmed and measured. Quality control ran on the encoded file; what
        #    it says is its own business, that it was said is this test's.
        reports = list(session.scalars(select(QualityControlReport)))
        boards = list(session.scalars(select(Storyboard)))
        publications = list(session.scalars(select(PublicationRecord)))
        episodes = list(session.scalars(select(StoryEpisode)))
        channels = {c.id: c for c in session.scalars(select(ChannelRecord))}
    assert reports, by_name["media"]["reason"]
    assert any(report.status == "PASSED" for report in reports), [
        (r.status, r.failure_reasons_json) for r in reports
    ]

    # 4. The film went out on the channel its storyboard belongs to, at the visibility the
    #    Owner's policy allows in TEST — private, whatever the policy says elsewhere.
    assert publications, by_name["publish"]["reason"]
    # Both films went out, each to its own slot: the factual short to Channel A and the
    # serial's episode to Channel B, never one account's film through the other's binding.
    routed = {channels[record.channel_id].channel_type for record in publications}
    assert routed == {"MAIN_FACTUAL", "OFFICE_SERIAL"}, routed
    published = publications[0]
    # PUBLISHED_SIMULATED, not PUBLISHED: the record says the upload went to the simulator,
    # because a studio that wrote "published" for a film no platform received would be
    # lying in its own books. That distinction is the one this test most wants kept.
    assert published.status == "PUBLISHED_SIMULATED"
    assert published.privacy_status == "private"
    assert all(record.privacy_status == "private" for record in publications)
    assert len(studio["publisher"].uploads) == 2, studio["publisher"].uploads
    assert {upload["privacy_status"] for upload in studio["publisher"].uploads} == {"private"}

    # 5. The serial wrote yesterday's episode — the day that is over, never today's.
    assert episodes, by_name["serial_queue"]["reason"]
    (episode,) = episodes
    # Grounded in yesterday's events, read by the Director, and approved by her because the
    # Owner's policy on Channel B lets her — the whole chain, in one run.
    assert episode.status == "APPROVED", (episode.status, episode.review_json)
    assert episode.grounded_event_ids_json, "the episode cited nothing that happened"
    with Session(engine) as session:
        from app.story.models import DailyStudioLog

        log = session.get(DailyStudioLog, episode.log_id)
    assert log.business_date == business_date(TZ, datetime.now(UTC) - timedelta(days=1))
    # Two storyboards: the factual film's and the serial's, both filmed in the same day.
    assert len(boards) == 2, [board.title for board in boards]
    assert any(board.series_key == "office_serial" for board in boards)

    # 6. And the day is done: a second tick on the same date starts nothing.
    assert scheduler_tick(engine) == []
    again = worker_pass(engine, handlers, registry=studio["registry"])
    assert [item for item in again["ran"] if item["task_id"] == ran["task_id"]] == []
    with Session(engine) as session:
        assert len(list(session.scalars(select(DailyRun)))) == 1


@requires_ffmpeg
def test_the_films_money_is_held_before_it_is_spent_and_settled_when_it_is(
    engine, settings, studio
):
    """The day's books, from the same run: what a film was expected to cost is held against
    the budget before a single frame is generated, and the hold is closed once the real cost
    rows are written. Nothing is left pledged to a film that was made."""
    from app.economy.models import SpendReservation
    from app.integrations.vault import CredentialVault

    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    runners = build_stage_runners(engine, settings, vault, studio["registry"])
    handlers = build_task_handlers(engine, settings, vault, runners, studio["registry"])
    _due_daily_job(engine)
    scheduler_tick(engine)

    worker_pass(engine, handlers, registry=studio["registry"])

    with Session(engine) as session:
        holds = list(session.scalars(select(SpendReservation)))
    assert holds, "the film was rendered without holding what it would cost"
    assert all(hold.status in ("SETTLED", "RELEASED") for hold in holds), [
        (h.purpose, h.status) for h in holds
    ]
    assert any(hold.status == "SETTLED" for hold in holds), "a film was made and nothing settled"


# ------------------------------------------------------- the same day, under each mode --


def _set_mode(engine, mode: str) -> None:
    """The Owner's autonomy mode, as his command writes it into the policy row."""
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_mode = mode


def _run_a_day(engine, settings, studio):
    """The scheduler's tick, the queue, the worker and the twelve stages — the real day."""
    from app.integrations.vault import CredentialVault

    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    runners = build_stage_runners(engine, settings, vault, studio["registry"])
    handlers = build_task_handlers(engine, settings, vault, runners, studio["registry"])
    _due_daily_job(engine)
    assert len(scheduler_tick(engine)) == 1
    worker_pass(engine, handlers, registry=studio["registry"])
    with Session(engine) as session:
        run = session.scalars(select(DailyRun)).one()
        return {stage["stage"]: stage for stage in run.stages_json}


def _publications(engine):
    with Session(engine) as session:
        return list(session.scalars(select(PublicationRecord)))


def _approval_requests(engine):
    from app.models import ApprovalRequest

    with Session(engine) as session:
        return list(session.scalars(select(ApprovalRequest)))


@requires_ffmpeg
def test_a_manual_day_prepares_and_stops_there(engine, settings, studio):
    """MANUAL is 51's "agents may draft/analyze, the Owner approves the stage transitions".
    The clock still starts the day and the day still runs — it simply does not fetch a page,
    buy a shot or upload a film, and every one of those stages says which decision is
    missing. Nothing is asked of the Owner either: MANUAL is his answer already."""
    _set_mode(engine, "MANUAL")

    by_name = _run_a_day(engine, settings, studio)

    assert by_name["preflight"]["artefacts"]["autonomy_mode"] == "MANUAL"
    for stage in ("research_and_verification", "media", "publish"):
        assert by_name[stage]["status"] == "SKIPPED", (stage, by_name[stage]["reason"])
        assert "MANUAL" in by_name[stage]["reason"], by_name[stage]["reason"]
    # The internal work of the day still happened: the serial's episode is drafting, which is
    # T1 and reversible, and nothing about it leaves the studio.
    assert by_name["serial_queue"]["status"] == "COMPLETED", by_name["serial_queue"]["reason"]
    assert studio["publisher"].uploads == []
    assert _publications(engine) == []
    assert _approval_requests(engine) == [], "MANUAL refuses; it does not queue a question"
    with Session(engine) as session:
        from app.economy.models import SpendReservation

        assert session.scalars(select(SpendReservation)).all() == [], (
            "a day that may not buy a shot must not hold the money for one"
        )


@requires_ffmpeg
def test_a_supervised_day_films_the_work_and_asks_before_it_uploads(engine, settings, studio):
    """SUPERVISED runs the routine internal stages by itself — research, script, the film and
    its measurement — and turns the one external write into the Approval object of 31: a row
    with the action, the tier and the requester on it, standing until the Owner answers. The
    film is made and nothing is uploaded, which is the whole point of the mode."""
    _set_mode(engine, "SUPERVISED")

    by_name = _run_a_day(engine, settings, studio)

    assert by_name["preflight"]["artefacts"]["autonomy_mode"] == "SUPERVISED"
    assert by_name["media"]["status"] == "COMPLETED", by_name["media"]["reason"]
    assert by_name["media"]["artefacts"]["assets"], by_name["media"]["reason"]
    assert by_name["publish"]["status"] == "SKIPPED", by_name["publish"]["reason"]
    assert "SUPERVISED" in by_name["publish"]["reason"]
    (request,) = _approval_requests(engine)
    assert (request.action, request.risk_tier, request.result) == (
        "publishing.public_publish",
        "T3",
        "PENDING",
    )
    assert by_name["publish"]["artefacts"]["approval_id"] == request.id
    assert studio["publisher"].uploads == []
    assert _publications(engine) == []


@requires_ffmpeg
def test_an_autonomous_ceo_day_publishes_under_the_channels_own_policy(engine, settings, studio):
    """AUTONOMOUS_CEO is what the studio has been doing: the Director executes T0-T3 within
    policy. The film goes out at the visibility the channel's policy allows — private here,
    because the studio is in TEST — and the record says the upload went to the simulator."""
    _set_mode(engine, "AUTONOMOUS_CEO")

    by_name = _run_a_day(engine, settings, studio)

    assert by_name["preflight"]["artefacts"]["autonomy_mode"] == "AUTONOMOUS_CEO"
    assert by_name["publish"]["status"] == "COMPLETED", by_name["publish"]["reason"]
    published = _publications(engine)
    assert published, by_name["publish"]["reason"]
    assert {record.status for record in published} == {"PUBLISHED_SIMULATED"}
    assert {record.privacy_status for record in published} == {"private"}
    # Nothing was asked of the Owner: in this mode a T3 within policy is the Director's.
    assert _approval_requests(engine) == []
