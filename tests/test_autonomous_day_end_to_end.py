"""One scheduled day, from the clock to a published film — the test the project never had.

Every other test in this suite holds one piece: a stage, a gate, a ledger, a queue. Nothing
held the whole day together, so the studio could pass a thousand tests and still fail at the
seam between two of them — which is where a day actually breaks. This drives the real thing:
the scheduler fires the daily job, the queue hands the task to the worker, and the worker
executes the runbook with the real stage runners, thirteen stages in order, against a
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
from zoneinfo import ZoneInfo

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

#: A beat's two lines, ten spoken words each: six beats of them are 120 words, inside the
#: serial's own 45-70 second window and the brief's 8-22 words a beat. Nothing in them is a
#: price, a model name or an address, because the episode's privacy check reads every line.
BEAT_LINES = (
    "Right, where are we with the number this morning, everyone?",
    "The evidence first, then the opinion, and never the reverse.",
)
#: The structure the brief (v3) asks for, over six beats.
BEAT_PARTS = ("hook", "situation", "situation", "turn", "payoff", "button")

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


# --------------------------------------------------------------------- the faked vendors --


#: The episode the stand-in showrunner writes; the Publisher knows the serial by it.
EPISODE_TITLE = "The number before good morning"


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
        # The shot brief carries the film's story and its visual bible (core_message,
        # continuity_rules), so it is told apart first, by the shape it asks to be returned.
        # Asked in the old order, this stand-in answered the shot plan with a script, and the
        # film went on from template prompts in silence - which is now a lost plan, waiting as
        # NEEDS_SHOT_PLAN (SHOT_PLAN_PARSE, 2026-09-27).
        if '"shots": [' in prompt:
            return self._shots(prompt)
        if '"punchline": {' in prompt:
            # The Director's editorial judgement (2026-10-11) of the script or the episode as a
            # stranger meets it: five 0-10 scores, the two weakest, a brief. Told apart before
            # the episode and the script, whose shapes its payload may carry as data. The
            # stand-in finds every version good enough to ship, so the day keeps one episode
            # a day and one script a topic; the judgement's own loop has its own tests.
            return json.dumps(
                {
                    **{
                        key: {"score": 8, "reason": "The first line already asks a question."}
                        for key in ("hook", "clarity", "moment", "punchline", "follow")
                    },
                    "weakest": ["moment", "follow"],
                    "brief": {"keep": "the opening", "change": "", "avoid": ""},
                }
            )
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
            # Each film is described from its own prompt, as a real Publisher would. The
            # rehearsal of 2026-09-18 ran with one fixed answer here, and both films went up
            # as 'Infrared light and what it shows': the stand-in's limit, not the studio's
            # (tests/test_publication_metadata_per_film.py), and now a HOLD for the episode.
            if EPISODE_TITLE in prompt:
                return json.dumps(
                    {
                        "verdict": "READY",
                        "title": "The number before good morning",
                        "description": "Sarah asks for the number; Aris brings the evidence.",
                        "tags": ["office serial", "studio"],
                        "hold_reasons": [],
                    }
                )
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
            # The episode review v2 asks for the rubric; a PASS without all six scores is
            # no verdict, so the stand-in scores every part as working.
            return json.dumps(
                {
                    "verdict": "PASS",
                    "scores": {
                        part: 4
                        for part in ("hook", "situation", "turn", "payoff", "voices", "button")
                    },
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
        # Written as the brief (v3) asks, from its data alone: the names from ALLOWED_NAMES,
        # the rooms from LOCATIONS, the events and who acts in them from EVENTS. The speakers
        # are two who act in the cited events, as the Owner's cast rule asks; anyone else
        # stands in the background of the first beat.
        allowed = re.search(r"^ALLOWED_NAMES: (\[.*\])$", prompt, re.MULTILINE)
        names = json.loads(allowed.group(1)) if allowed else []
        rooms_block = prompt.split("LOCATIONS (", 1)[-1].split("EVENTS OF", 1)[0]
        rooms = re.findall(r"^- ([a-z0-9_-]+): ", rooms_block, re.MULTILINE)
        events_block = prompt.split("EVENTS OF", 1)[-1].split("PREVIOUSLY:", 1)[0]
        events = [
            json.loads(row)
            for row in events_block.splitlines()
            if row.startswith('{"id"') and _UUID.search(row)
        ]
        if not events or len(names) < 2 or not rooms:
            return "Nu am din ce scrie episodul."
        planned = "Written with Ep." in prompt
        cited = [events[index % len(events)] for index in range(len(BEAT_PARTS))]
        acting = list(dict.fromkeys(name for event in cited for name in event["who"]))
        speakers = (acting + [name for name in names if name not in acting])[:2]
        beats = [
            {
                "part": part,
                "location": rooms[0],
                "scene": f"The studio in the morning, scene {index + 1}, {speakers[0]} at a desk.",
                "lines": [
                    {"speaker": speakers[0], "text": BEAT_LINES[0]},
                    {"speaker": speakers[1], "text": BEAT_LINES[1]},
                ],
                "background": [n for n in names if n not in speakers] if index == 0 else [],
                "event_ids": [cited[index]["id"]],
            }
            for index, part in enumerate(BEAT_PARTS)
        ]
        return json.dumps(
            {
                "title": EPISODE_TITLE,
                "beats": beats,
                "summary": "Sarah asked for the number; Aris brought the evidence first.",
                "threads_continued": [],
                "threads_closed": [],
                "threads_opened": ["whether anyone will ever bring the number first"],
                "recurring": ["the espresso cup"],
                # The plan for the next episode, and what became of the one this brief
                # carried (a plan is offered only once an episode is in canon).
                "next_episode": {
                    "premise": "Aris brings the number before Sarah can ask for it.",
                    "cold_open_line": "Before you ask, the number is already on your desk.",
                    "open_question": "Will Sarah trust a number she did not ask for?",
                    "threads_to_pay_off": [],
                },
                "plan_kept": False if planned else None,
                "plan_note": "The day did not bring the number first." if planned else "",
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


@lru_cache(maxsize=16)
def _test_clip(seconds: float) -> bytes:
    """A real h264 clip of the asked length, made locally by the encoder the day requires.

    A moving test pattern, not a flat colour: quality control reads motion and structure,
    and a blank clip would be refused for the right reason and prove nothing.
    """
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "shot.mp4"
        subprocess.run(
            [
                find_ffmpeg(),
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"testsrc2=s=540x960:r=25:d={max(0.5, seconds):.3f}",
                "-pix_fmt",
                "yuv420p",
                str(target),
            ],
            check=True,
            capture_output=True,
        )
        return target.read_bytes()


class FakeMotion:
    """The fake video model: a real clip for each shot, and the credits a vendor would name.

    It carries the model the studio's own chooser picked and the connection it belongs to, so
    the render, the model outcomes and the books see exactly what they would see from the
    vendor — the credits Runway states for a task are its catalogue price for those seconds,
    in the connection's own credits — while nothing is asked of anyone.
    """

    PROVIDER_NAME = "TEST_VIDEO_PROVIDER"

    def __init__(self, model: str, integration_id: str, credits_per_second: float | None) -> None:
        self.model = model
        self.integration_id = integration_id
        self.credits_per_second = credits_per_second
        self.last_estimated_credits: float | None = None
        self.jobs: dict[str, float] = {}

    async def health_check(self) -> dict[str, Any]:
        return {"status": "HEALTHY"}

    async def create_generation(
        self,
        prompt: str,
        *,
        image_ref: bytes | None = None,
        duration_seconds: float = 4.0,
        aspect_ratio: str = "9:16",
        extra: dict[str, Any] | None = None,
    ) -> str:
        job_id = f"test-task-{uuid4()}"
        self.jobs[job_id] = float(duration_seconds)
        if self.credits_per_second is not None:
            self.last_estimated_credits = round(
                float(duration_seconds) * self.credits_per_second, 3
            )
        return job_id

    async def get_generation_status(self, job_id: str) -> Any:
        from app.providers.media_base import VideoGenerationResult

        return VideoGenerationResult(
            job_id=job_id,
            status="COMPLETED",
            video_bytes=_test_clip(round(self.jobs[job_id], 3)),
            raw_response={"task_status": "SUCCEEDED", "engine": "test"},
        )


class FakeMotionChooser:
    """`factory.motion_for_scene`, with the vendor taken out and the decision left in.

    The studio's own router still decides — the selected video connection, the TEST task,
    the tier, the ceilings, `choose_model` over the catalogue rows — so a day with a video
    connection is held to the Owner's terms exactly as it would be. Only the adapter is
    replaced: the fake above, never `video_provider_for`, which builds the vendor's. A
    studio with no video connection gets the answer the real one gives, and no shot.
    Remembers every question put to a connection and every shot it handed out.
    """

    def __init__(self) -> None:
        self.asked: list[dict[str, Any]] = []
        self.delivered: list[FakeMotion] = []

    def __call__(
        self,
        engine: Any,
        vault: Any,
        scene: dict,
        *,
        environment: str,
        tier: str = "STANDARD",
        seconds: float = 0.0,
        budget_usd: float | None = None,
        forced_model: str | None = None,
        exclude: tuple[str, ...] = (),
        max_usd_per_second: float | None = None,
    ) -> tuple[FakeMotion | None, dict]:
        from app.integrations.models import Integration, ProviderResource, ServiceSelection
        from app.media.factory import VERIFIED_STATUSES
        from app.media.production_policy import (
            PROMPT_TO_VIDEO,
            SceneRequirement,
            choose_model,
            credit_usd,
        )

        with Session(engine) as session:
            selection = session.get(ServiceSelection, "video")
            row = (
                session.get(Integration, selection.integration_id)
                if selection is not None and selection.integration_id
                else None
            )
            if row is None or row.status not in VERIFIED_STATUSES:
                return None, {"model_id": None, "reason": "No connection is selected for video."}
            self.asked.append(
                {
                    "integration_id": row.id,
                    "scene_index": scene.get("scene_index"),
                    "tier": tier,
                    "seconds": seconds,
                    "budget_usd": budget_usd,
                }
            )
            requirement = SceneRequirement(
                purpose="video",
                tasks=(PROMPT_TO_VIDEO,) if environment == "TEST" else ("image_to_video",),
                tier=tier,
                scene_category=str(scene.get("scene_category") or "GENERAL"),
                seconds=seconds,
                budget_usd=budget_usd,
                max_usd_per_second=max_usd_per_second,
            )
            decision = choose_model(
                session,
                row.id,
                requirement,
                environment=environment,
                exclude=exclude,
                forced=forced_model,
            )
            if not decision.get("model_id"):
                return None, decision
            # The credits a vendor names for a task are its catalogue price for those
            # seconds, in the connection's own credits. A model priced some other way names
            # none, and the books fall back to what they know, as they would for the vendor.
            resource = session.scalar(
                select(ProviderResource).where(
                    ProviderResource.integration_id == row.id,
                    ProviderResource.resource_type == "MODEL",
                    ProviderResource.remote_id == decision["model_id"],
                )
            )
            pricing = resource.pricing if resource and isinstance(resource.pricing, dict) else {}
            per_second = pricing.get("per_second_usd")
            per_credit = credit_usd(session, row.id)
            shot = FakeMotion(
                decision["model_id"],
                row.id,
                float(per_second) / per_credit
                if isinstance(per_second, int | float) and per_credit
                else None,
            )
        self.delivered.append(shot)
        return shot, decision


class UnmeasuredAnalytics:
    """YouTube Analytics with nothing to say: every video is unmeasurable, no number made up.

    The slot's real binding lookup still runs first, so an unbound or disconnected slot is
    skipped with the studio's own reason; only the adapter that would ask Google is replaced.
    """

    PROVIDER_NAME = "TEST_ANALYTICS"

    def __init__(self, channel_id: str | None = None) -> None:
        self.channel_id = channel_id

    async def fetch_video_metrics(self, remote_video_id: str, window: str = "LIFETIME") -> Any:
        from app.analytics.services import MetricsUnavailable

        raise MetricsUnavailable("test: no platform is asked, so no number exists")

    async def fetch_channel_metrics(self, remote_channel_id: str, window: str = "LIFETIME") -> Any:
        from app.analytics.services import MetricsUnavailable

        raise MetricsUnavailable("test: no platform is asked, so no number exists")


#: Every paid boundary a day can reach, as the (module, attribute) the fakes replace. The
#: attribute is patched where the day reads it: `stages` imported `selected_youtube` and
#: `analytics_provider_for_channel` at its top, so they are replaced on `stages`; the
#: others are imported inside the function that calls them, so they are replaced on the
#: module that defines them. tests/test_no_paid_path_escapes.py reads this list and fails
#: when a paid call site the day can reach is not behind one of these.
VENDOR_FAKES = (
    ("app.media.factory", "image_provider"),
    ("app.media.factory", "tts_provider"),
    ("app.media.factory", "render_plan"),
    ("app.media.factory", "motion_for_scene"),
    ("app.runbook.stages", "selected_youtube"),
    ("app.runbook.stages", "analytics_provider_for_channel"),
    ("app.economy.credits", "credit_balances"),
    ("app.research.service", "verified_search_provider"),
    # The PRODUCTION staircase's wiring (the Runway connection, its balance and adapters)
    # and the sheet's reference-image flag: the day reaches both once it climbs a sheet.
    ("app.runbook.stages", "sheet_wiring"),
    ("app.media.shooting_sheet", "_reference_verified"),
)


def install_vendor_fakes(monkeypatch, *, publisher: Any, motion: FakeMotionChooser) -> None:
    """Replace every name in VENDOR_FAKES — the end-to-end studio and the rehearsal alike.

    One list, one installer: a rehearsal that kept its own copy of the fakes was one boundary
    short of this fixture and bought nothing only because its network guard refused the
    purchase. The dictionary must name exactly the list, so the two cannot drift apart.
    """
    import importlib

    from app.analytics.services import analytics_provider_for_channel

    def analytics(engine_: Any, vault: Any, channel_id: str) -> tuple[Any, str]:
        provider, reason = analytics_provider_for_channel(engine_, vault, channel_id)
        if provider is None:
            return None, reason
        return UnmeasuredAnalytics(getattr(provider, "channel_id", None)), ""

    fakes = {
        ("app.media.factory", "image_provider"): lambda *a, **k: TestImages(),
        ("app.media.factory", "tts_provider"): lambda *a, **k: TestVoice(),
        # The plan is the plain one a studio with no connections resolves to.
        ("app.media.factory", "render_plan"): lambda engine_, vault, board: {
            "image": TestImages(),
            "tts_for_scene": lambda *a: TestVoice(),
            "video_for_scene": lambda *a: None,
            "plan": {},
        },
        ("app.media.factory", "motion_for_scene"): motion,
        ("app.runbook.stages", "selected_youtube"): lambda *a, **k: publisher,
        ("app.runbook.stages", "analytics_provider_for_channel"): analytics,
        # What the vendors say the account holds: nobody is asked, so nothing is measured,
        # and the books fall back to the credits each shot named, as they do when a vendor
        # does not answer.
        ("app.economy.credits", "credit_balances"): lambda *a, **k: {},
        # No web search engine, as in a studio that never connected one.
        ("app.research.service", "verified_search_provider"): lambda *a, **k: None,
        # A staircase with no Runway connection: no balance, no motion adapter, local stills.
        ("app.runbook.stages", "sheet_wiring"): lambda *a, **k: {
            "integration_id": None,
            "capabilities": [],
            "image_adapter": TestImages(),
            "account": None,
            "adapter_for_model": None,
            "resolution": None,
            "storage_root": None,
        },
        ("app.media.shooting_sheet", "_reference_verified"): lambda: False,
    }
    assert set(fakes) == set(VENDOR_FAKES), set(fakes) ^ set(VENDOR_FAKES)
    for (module, attribute), fake in fakes.items():
        monkeypatch.setattr(importlib.import_module(module), attribute, fake)


# ------------------------------------------------------------------------ the studio --


def _yesterdays_events(engine) -> None:
    """Three things that happened yesterday, of the kinds the serial may retell.

    Yesterday on the studio's clock (TZ), at its noon. It was noon of yesterday in UTC, which
    between 00:00 and 03:00 in Bucharest is the day before yesterday: the verifier's suite
    run of 2026-09-19 started at 00:10 local, the serial found yesterday quiet, and three
    tests of this file failed on the hour alone.
    """
    local = datetime.now(UTC).astimezone(ZoneInfo(TZ)) - timedelta(days=1)
    moment = local.replace(hour=12, minute=0, second=0, microsecond=0).astimezone(UTC).isoformat()
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
    from app.media.services import seed_default_character_bibles
    from app.publishing.services import list_channels, seed_default_channels

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

    # The vendors, every one of them (VENDOR_FAKES): the picture and the voice are local
    # files under a test name, the moving shots a local test pattern on the model the
    # studio's own router chose, the publisher the simulator, the analytics an account with
    # no numbers, the balances unread and the search engine absent. Everything between them
    # is the studio's own code.
    publisher = RecordingPublisher()
    motion = FakeMotionChooser()
    install_vendor_fakes(monkeypatch, publisher=publisher, motion=motion)

    model = StudioModel()
    registry = ProviderRegistry()
    registry.register(provider_id, model)
    return {
        "registry": registry,
        "model": model,
        "publisher": publisher,
        "motion": motion,
        "topic_id": topic_id,
    }


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


# The one day kept on the production encode (x264 slow): the other days use the suite's quick
# preset (tests/conftest.py quick_final_encode), and this one proves QC passes the real file.
@pytest.mark.real_encode
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
    # 2. Thirteen stages, each with its own recorded outcome — never a stage left out.
    names = [stage["stage"] for stage in stages_ran]
    assert names == list(STAGES), names
    assert run.stages_total == 13
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
    # Each upload carries its own film's title, never the other channel's.
    assert len({upload["title"] for upload in studio["publisher"].uploads}) == 2
    assert {upload["privacy_status"] for upload in studio["publisher"].uploads} == {"private"}

    # 5. The serial filmed yesterday's episode — the day that is over — and wrote today's
    #    for tomorrow, which nothing films today.
    assert episodes, by_name["serial_queue"]["reason"]
    with Session(engine) as session:
        from app.story.models import DailyStudioLog

        dated = {session.get(DailyStudioLog, e.log_id).business_date: e for e in episodes}
    assert len(episodes) == 2, sorted(dated)
    episode = dated[business_date(TZ, datetime.now(UTC) - timedelta(days=1))]
    # Grounded in yesterday's events, read by the Director, and approved by her because the
    # Owner's policy on Channel B lets her — the whole chain, in one run.
    assert episode.status == "APPROVED", (episode.status, episode.review_json)
    assert episode.grounded_event_ids_json, "the episode cited nothing that happened"
    assert episode.storyboard_id
    tomorrows = dated[business_date(TZ)]
    assert by_name["serial_next"]["status"] == "COMPLETED", by_name["serial_next"]["reason"]
    assert tomorrows.status == "APPROVED", (tomorrows.status, tomorrows.review_json)
    # Readied the same evening (2026-10-11) and not filmed today: its day is not over, and in
    # TEST nothing continues tonight (the two uploads above are yesterday's films).
    assert tomorrows.storyboard_id and tomorrows.storyboard_id != episode.storyboard_id
    assert tomorrows.continuity_json["next_episode"]["status"] == "PLANNED"
    # Three storyboards: the factual film's and the serial's, both filmed in the same day,
    # and tomorrow's film's, readied tonight.
    assert len(boards) == 3, [board.title for board in boards]
    assert sum(board.series_key == "office_serial" for board in boards) == 2

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
    """The scheduler's tick, the queue, the worker and the thirteen stages — the real day."""
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
        # The mode is named in words in the reason; its code is the preflight's artefact.
        assert "este manual" in by_name[stage]["reason"], by_name[stage]["reason"]
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
    film is made and nothing is uploaded, which is the whole point of the mode.

    One request per film, not one for the stage. The day makes two — the factual short and
    the serial's episode — and each is asked about by name: keyed by the action alone, the
    second film reused the first film's row, so the Owner would have answered once about a
    question carrying the other film's evidence."""
    _set_mode(engine, "SUPERVISED")

    by_name = _run_a_day(engine, settings, studio)

    assert by_name["preflight"]["artefacts"]["autonomy_mode"] == "SUPERVISED"
    assert by_name["media"]["status"] == "COMPLETED", by_name["media"]["reason"]
    assert by_name["media"]["artefacts"]["assets"], by_name["media"]["reason"]
    assert by_name["publish"]["status"] == "SKIPPED", by_name["publish"]["reason"]
    assert "supravegheat" in by_name["publish"]["reason"]
    requests = _approval_requests(engine)
    assert len(requests) == 2, [(r.action, r.subject) for r in requests]
    assert {(r.action, r.risk_tier, r.result) for r in requests} == {
        ("publishing.public_publish", "T3", "PENDING")
    }
    # Each film is its own question, and each question names the film it is about.
    assert len({request.subject for request in requests}) == 2
    assert all(request.subject for request in requests)
    assert by_name["publish"]["artefacts"]["approval_id"] in {r.id for r in requests}
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


# ------------------------------------------------------ a studio with a video connection --


#: Two video models on the test connection, priced and shaped the way the Owner's Runway
#: catalogue rows are (2026-09-18 copy: per-second prices, the tasks and the vertical ratio
#: the contract lists, admitted to PRODUCTION). The ids are the test's own, not a vendor's.
TEST_VIDEO_MODELS = {
    "test-motion-cheap": {"per_second_usd": 0.02, "quality": 0.6},
    "test-motion-dearer": {"per_second_usd": 0.03, "quality": 0.7},
}


def _video_connection(engine) -> str:
    """A verified video connection selected for "video", as the Owner's data has one.

    His copy holds a runway integration (VERIFIED, credit_usd "0.01"), a service_selection
    row naming it for video, and discovered MODEL rows with a per-second price. This builds
    the same rows. The key is a test string sealed in the test's own vault: nothing here
    could authenticate anywhere, and nothing is asked to.
    """
    from app.integrations.models import Integration, ProviderResource, ServiceSelection
    from app.integrations.vault import CredentialVault
    from app.services import append_event

    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    identifier = str(uuid4())
    ratios = ["720:1280", "1280:720"]
    with Session(engine) as session, session.begin():
        saved = append_event(
            session, "settings.integration_saved", "integration", identifier, 1, {}, str(uuid4())
        )
        session.add(
            Integration(
                id=identifier,
                kind="runway",
                name="Test video connection",
                config={"credit_usd": "0.01"},
                encrypted_secrets=vault.encrypt({"api_key": "test-not-a-key"}),
                secret_fields=["api_key"],
                version=1,
                status="VERIFIED",
                checked_at=utc_now(),
                event_id=saved.event_id,
            )
        )
        session.flush()
        selected = append_event(
            session, "settings.service_selected", "integration", identifier, 2, {}, str(uuid4())
        )
        session.add(
            ServiceSelection(
                purpose="video", integration_id=identifier, version=1, event_id=selected.event_id
            )
        )
        for remote_id, terms in TEST_VIDEO_MODELS.items():
            session.add(
                ProviderResource(
                    id=str(uuid4()),
                    integration_id=identifier,
                    resource_type="MODEL",
                    remote_id=remote_id,
                    name=remote_id,
                    api_metadata={
                        "tasks": ["image_to_video", "text_to_video"],
                        "ratios": {"image_to_video": ratios, "text_to_video": ratios},
                        "durations": {},
                        "needs_references": {"image_to_video": False, "text_to_video": False},
                    },
                    api_available=True,
                    last_seen_at=utc_now(),
                    pricing={
                        "per_second_usd": terms["per_second_usd"],
                        "unit": "per second of video",
                    },
                    capabilities={"quality_score": terms["quality"], "reliability_score": 0.8},
                    metadata_version=1,
                    production_status="PRODUCTION",
                )
            )
    return identifier


@requires_ffmpeg
def test_a_test_day_with_a_video_connection_buys_its_shots_only_through_the_fake(
    engine, settings, studio, no_network
):
    """On the Owner's data the day meets the motion chooser, and until 2026-09-18 no fake
    stood in front of it: a TEST day on a copy of his studio chose two models per film and
    tried four paid text_to_video calls, three times each, which only the rehearsal's DNS
    guard refused. Here the studio has the same kind of video connection, the chooser is
    the fixture's fake, and the day is held to the Owner's TEST terms: at most
    `test_motion_scenes` shots per film, every one of them asked of the fake, and the books
    charging exactly the shots that were delivered, at the credits the fake named."""
    from app.economy.models import ProviderCostRecord, SpendReservation
    from app.media.models import VideoRenderJob
    from app.services import studio_environment

    connection = _video_connection(engine)
    assert studio_environment(engine) == "TEST"
    limit = settings.test_motion_scenes
    assert limit >= 1

    by_name = _run_a_day(engine, settings, studio)

    assert by_name["media"]["status"] == "COMPLETED", by_name["media"]["reason"]
    with Session(engine) as session:
        jobs = [
            job
            for job in session.scalars(select(VideoRenderJob))
            if isinstance(job.production_json, dict)
        ]
        costs = list(session.scalars(select(ProviderCostRecord)))
        holds = list(session.scalars(select(SpendReservation)))
    assert len(jobs) == 2, [job.status for job in jobs]  # the factual short and the episode

    motion = studio["motion"]
    # The path was really taken: the chooser was asked, and it chose from this connection.
    assert motion.asked, "the day never asked for a moving shot; the test proves nothing"
    assert {ask["integration_id"] for ask in motion.asked} == {connection}
    shots = []
    for job in jobs:
        production = job.production_json
        records = [
            (scene["scene_index"], scene["motion"])
            for scene in production["scenes"]
            if isinstance(scene.get("motion"), dict)
        ]
        # The TEST limit, per film: never more shots asked for than the Owner allows.
        assert production["motion"]["scene_limit"] == limit
        assert 1 <= len(records) <= limit, records
        for scene_index, record in records:
            # Every shot was the fake's, on one of this connection's models.
            assert record["provider"] == FakeMotion.PROVIDER_NAME, record
            assert record["model"] in TEST_VIDEO_MODELS, record
            assert record["integration_id"] == connection, record
            shots.append((job.id, scene_index, record))
    assert len(motion.delivered) == len(shots) == len(motion.asked)
    assert all(record.get("bytes") for *_, record in shots), "a shot the fake made never landed"

    # The books: one motion row per shot delivered, at the credits the fake named times the
    # connection's credit price, which is the catalogue's price per second because the fake
    # names credits the way the vendor does. Nothing else is charged for motion.
    motion_rows = [row for row in costs if (row.attribution_json or {}).get("unit") == "motion"]
    assert len(motion_rows) == len(shots), [row.attribution_json for row in motion_rows]
    for job_id, scene_index, record in shots:
        (row,) = [
            r
            for r in motion_rows
            if r.attribution_json["render_job_id"] == job_id
            and r.attribution_json["scene_index"] == scene_index
        ]
        assert row.attribution_json["model_id"] == record["model"]
        assert row.attribution_json["credits"] == record["estimated_credits"]
        expected = record["estimated_credits"] * 0.01
        per_second = TEST_VIDEO_MODELS[record["model"]]["per_second_usd"]
        assert abs(expected - record["asked_seconds"] * per_second) < 0.011
        assert row.provider == "runway" and row.status == "ESTIMATED" and not row.failed
        assert abs(row.usd_micros - round(expected * 1_000_000)) <= 1, (row.usd_micros, expected)
    # Within the Owner's TEST ceiling per film, and every hold closed against the books.
    for job in jobs:
        spent = sum(
            r.usd_micros for r in motion_rows if r.attribution_json["render_job_id"] == job.id
        )
        assert spent <= round(settings.test_max_cost_per_generation_usd * 1_000_000), spent
    assert holds and all(hold.status in ("SETTLED", "RELEASED") for hold in holds)

    # And nothing left the machine, or even tried to: no refusal was needed.
    assert no_network.refused == [], no_network.refused


# ----------------------------------------------- one click, today's film and tomorrow's --


class _Tomorrow(datetime):
    """The studio's calendar one day on: what `business_date` and the day's closes read.

    Only the calendar moves. Every event the run writes keeps the real clock's timestamp, so
    the next day's own log holds none of them: a quiet day, which is what a run at dawn sees.
    """

    @classmethod
    def now(cls, tz: Any = None) -> Any:  # type: ignore[override]
        return datetime.now(tz) + timedelta(days=1)


def _the_serial(engine) -> dict[str, dict[str, Any]]:
    """Each episode by the day it tells: its status, storyboard and whether it was filmed."""
    from app.media.models import VideoRenderJob
    from app.story.models import DailyStudioLog

    with Session(engine) as session:
        told: dict[str, dict[str, Any]] = {}
        for episode in session.scalars(select(StoryEpisode)):
            date = session.get(DailyStudioLog, episode.log_id).business_date
            assert date not in told, f"two episodes for {date}"
            filmed = episode.storyboard_id is not None and (
                session.scalar(
                    select(VideoRenderJob.id).where(
                        VideoRenderJob.storyboard_id == episode.storyboard_id,
                        VideoRenderJob.status == "COMPLETED",
                    )
                )
                is not None
            )
            told[date] = {
                "id": episode.id,
                "status": episode.status,
                "storyboard_id": episode.storyboard_id,
                "filmed": filmed,
                "plan": (episode.continuity_json or {}).get("plan"),
                "verdict": (episode.review_json or {}).get("verdict"),
                "scores": (episode.review_json or {}).get("scores"),
            }
        return told


def _episode_prompts(studio) -> int:
    return sum(1 for prompt in studio["model"].prompts if "ALLOWED_NAMES:" in prompt)


@requires_ffmpeg
def test_one_click_films_one_episode_and_writes_the_next(engine, settings, studio, monkeypatch):
    """The Owner's done-condition (2026-09-24): one click creates today's episode and the
    script of the next one. Day D films the episode of D-1 and writes, reads and approves the
    one of D, with no storyboard; a second click on D films nothing of D; day D+1 films the
    episode of D without writing it again."""
    from app.integrations.vault import CredentialVault
    from app.runbook.services import execute_daily_run

    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    day_d = business_date(TZ)
    day_before = business_date(TZ, datetime.now(UTC) - timedelta(days=1))

    def click() -> dict[str, dict[str, Any]]:
        runners = build_stage_runners(engine, settings, vault, studio["registry"])
        result = execute_daily_run(engine, settings, vault, stage_runners=runners)
        return {stage["stage"]: stage for stage in result["stages"]}

    # Day D: yesterday's episode is written, approved, storyboarded and filmed; today's is
    # written, read, approved under the Owner's policy and readied (2026-10-11: the storyboard
    # the same evening; in TEST nothing continues tonight), and not filmed before D is over.
    first = click()
    serial = _the_serial(engine)
    assert sorted(serial) == [day_before, day_d], (first["serial_queue"], first["serial_next"])
    assert serial[day_before]["status"] == "APPROVED"
    assert serial[day_before]["filmed"], first["media"]["reason"]
    assert serial[day_d]["status"] == "APPROVED", first["serial_next"]["reason"]
    board_d = serial[day_d]["storyboard_id"]
    assert board_d and not serial[day_d]["filmed"]
    assert first["serial_queue"]["artefacts"]["told_date"] == day_before
    assert first["serial_queue"]["artefacts"]["storyboard_id"]
    tomorrow = first["serial_next"]["artefacts"]
    assert tomorrow["told_date"] == day_d
    assert tomorrow["storyboard_id"] == board_d and tomorrow["film_continue_task_id"] is None
    # Tomorrow's script was written once and read by the Director through the whole rubric,
    # on the same run that filmed yesterday's: the Owner's two halves in one click.
    assert tomorrow["written"] == tomorrow["reviewed"] == tomorrow["approved"] == 1, tomorrow
    assert serial[day_d]["verdict"] == "PASS" and len(serial[day_d]["scores"]) == 6
    assert first["media"]["status"] == "COMPLETED", first["media"]["reason"]
    # The next writer was handed the plan of the episode before and said what became of it.
    assert serial[day_d]["plan"]["from_episode_id"] == serial[day_before]["id"]
    assert serial[day_d]["plan"]["kept"] is False
    written_on_d = _episode_prompts(studio)
    assert written_on_d == 2

    # A second click the same day: nothing of D is storyboarded again, filmed or written again.
    again = click()
    serial = _the_serial(engine)
    assert sorted(serial) == [day_before, day_d]
    assert serial[day_d]["storyboard_id"] == board_d and not serial[day_d]["filmed"]
    assert again["serial_next"]["artefacts"]["written"] == 0, again["serial_next"]["reason"]
    assert _episode_prompts(studio) == written_on_d

    # Day D+1: the storyboard built on D is filmed; nothing is readied or written again, and
    # D+1 itself (quiet: nothing is timestamped on it) gets none.
    monkeypatch.setattr("app.story.services.datetime", _Tomorrow)
    assert business_date(TZ) != day_d
    next_day = click()
    serial = _the_serial(engine)
    assert sorted(serial) == [day_before, day_d], next_day["serial_next"]["reason"]
    assert next_day["serial_queue"]["artefacts"]["resumed"] is None
    assert next_day["serial_queue"]["artefacts"]["storyboard_id"] is None
    assert serial[day_d]["storyboard_id"] == board_d
    assert serial[day_d]["filmed"], next_day["media"]["reason"]
    assert _episode_prompts(studio) == written_on_d
    # D+1's own script is not written from a day with nothing on it, and the stage says so.
    assert next_day["serial_next"]["status"] == "COMPLETED", next_day["serial_next"]
    assert next_day["serial_next"]["artefacts"]["written"] == 0
    assert next_day["serial_next"]["reason"].strip()
