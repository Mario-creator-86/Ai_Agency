"""The demo: the studio's whole day on a separate database, with every vendor simulated (SELL-03).

`scripts/start.py --demo` starts it. What is real: the runbook and its stages, the Policy
Kernel, the factual gate, the story review, the renderer (FFmpeg makes a real MP4), quality
control and the page. What is simulated, and nothing else: the vendors. The seams replaced are
exactly the ones the end-to-end test proves are every paid boundary a day can reach
(tests/test_autonomous_day_end_to_end.py VENDOR_FAKES; tests/test_demo_mode.py holds the two
lists equal). The pictures and the voice are the local deterministic adapters, the language
model is `DemoModel`, a stand-in that answers each prompt in the schema the studio asks for and
reads every identifier it uses out of the prompt itself; there is no motion vendor, no
YouTube, no search engine, no balance and no analytics.

What the demo never does: buy, publish, connect an account, or mark a provider working. The
publishing, payment, connection and network-reading routes answer 403 (`demo_refusal`), the
page carries a permanent banner, the seeded Ollama endpoint stays NOT_CONFIGURED with no
health stamp, and the demo refuses to start on the real studio's database (`DemoRefused`).
"""

from __future__ import annotations

import importlib
import ipaddress
import json
import re
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import ROOT, Settings
from app.providers.base import GenerateResult, HealthResult
from app.providers.deterministic_media import DeterministicPictureAdapter, DeterministicTTSAdapter

#: The vendor boundaries the demo replaces: (module, attribute), patched where the day reads
#: them. Kept equal to the end-to-end test's VENDOR_FAKES by tests/test_demo_mode.py.
DEMO_VENDOR_SEAMS: tuple[tuple[str, str], ...] = (
    ("app.media.factory", "image_provider"),
    ("app.media.factory", "tts_provider"),
    ("app.media.factory", "render_plan"),
    ("app.media.factory", "motion_for_scene"),
    ("app.runbook.stages", "selected_youtube"),
    ("app.runbook.stages", "analytics_provider_for_channel"),
    ("app.economy.credits", "credit_balances"),
    ("app.research.service", "verified_search_provider"),
    ("app.runbook.stages", "sheet_wiring"),
    ("app.media.shooting_sheet", "_reference_verified"),
)

#: The words a refused route answers with, in the Owner's language.
DEMO_REFUSAL_RO = (
    "DEMO: studioul rulează cu furnizori simulați; nimic nu se publică, nu se plătește și nu "
    "se conectează niciun cont. Acțiunea aceasta nu este disponibilă în demo."
)

#: Writes the demo refuses (any method but GET/HEAD/OPTIONS): publishing and YouTube, the
#: books and budgets, connecting vendors and models, the Owner's environment and paid-step
#: rule, the shooting sheet's paid steps and redos, the reference set, and every route that
#: would read the network (a page, a search host, the trends feed, a channel's numbers).
DEMO_REFUSED_PATHS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        r"^/api/v1/publishing/",
        r"^/api/v1/youtube/",
        r"^/api/v1/economy/",
        r"^/api/v1/settings/",
        r"^/api/v1/providers/",
        r"^/api/v1/owner/(environment|paid-media-approval)$",
        r"^/api/v1/media/storyboards/[^/]+/(steps/[^/]+|redo|adopt-existing-files)$",
        r"^/api/v1/media/characters/[^/]+/reference-set$",
        r"^/api/v1/factual/sources/(retrieve|allowed-hosts/)",
        r"^/api/v1/factual/research/",
        r"^/api/v1/analytics/(trends/refresh|ingest/)",
    )
)

#: The one fact the demo's film is about, and the source text that carries it verbatim: the
#: verifier refuses a quote that is not in the source, so they are the same sentence.
DEMO_FACT = "The James Webb telescope observes the universe in infrared light."
DEMO_SOURCE_URL = "https://example.com/amn-ai-demo/infrared"
DEMO_TOPIC_TITLE = "Infrared light and what it shows"

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class DemoRefused(RuntimeError):
    """The demo was asked to run on something that is not a demo database."""


def _database_file(url: str) -> Path | None:
    if not url.startswith("sqlite:///"):
        return None
    raw = url.removeprefix("sqlite:///")
    if raw in ("", ":memory:"):
        return None
    path = Path(raw)
    return (path if path.is_absolute() else ROOT / path).resolve()


def guard_demo_database(settings: Settings) -> None:
    """Refuse the demo on the studio's own database (data/studio.db), or on no file at all."""
    target = _database_file(settings.database_url)
    real = (ROOT / "data" / "studio.db").resolve()
    if target is None or target == real:
        raise DemoRefused(
            "DEMO: modul demo pornește doar pe o bază de date separată (scripts/start.py --demo "
            "folosește data/demo/demo.db), niciodată pe baza de date a studioului."
        )


# --------------------------------------------------------------------------- the vendors --


class DemoVoice(DeterministicTTSAdapter):
    """The local synthetic voice, named as the demo's."""

    PROVIDER_NAME = "DEMO_LOCAL_VOICE"
    model = "demo-local-voice"
    integration_id = None


def _no_motion(*args: Any, **kwargs: Any) -> tuple[None, dict]:
    return None, {"model_id": None, "reason": "DEMO: niciun furnizor video; scena rămâne imagine."}


def _no_analytics(*args: Any, **kwargs: Any) -> tuple[None, str]:
    return None, "DEMO: nicio platformă nu este întrebată."


def demo_vendor_fakes() -> dict[tuple[str, str], Any]:
    """The replacement for every seam in DEMO_VENDOR_SEAMS."""
    fakes: dict[tuple[str, str], Any] = {
        ("app.media.factory", "image_provider"): lambda *a, **k: DeterministicPictureAdapter(),
        ("app.media.factory", "tts_provider"): lambda *a, **k: DemoVoice(),
        # The plan a studio with no connections resolves to, as the end-to-end day has it.
        ("app.media.factory", "render_plan"): lambda engine, vault, board: {
            "image": DeterministicPictureAdapter(),
            "tts_for_scene": lambda *a: DemoVoice(),
            "video_for_scene": lambda *a: None,
            "plan": {},
        },
        ("app.media.factory", "motion_for_scene"): _no_motion,
        ("app.runbook.stages", "selected_youtube"): lambda *a, **k: None,
        ("app.runbook.stages", "analytics_provider_for_channel"): _no_analytics,
        ("app.economy.credits", "credit_balances"): lambda *a, **k: {},
        ("app.research.service", "verified_search_provider"): lambda *a, **k: None,
        ("app.runbook.stages", "sheet_wiring"): lambda *a, **k: {
            "integration_id": None,
            "capabilities": [],
            "image_adapter": DeterministicPictureAdapter(),
            "account": None,
            "adapter_for_model": None,
            "resolution": None,
            "storage_root": None,
        },
        ("app.media.shooting_sheet", "_reference_verified"): lambda: False,
    }
    if set(fakes) != set(DEMO_VENDOR_SEAMS):
        raise RuntimeError("demo fakes and seams disagree")
    return fakes


@contextmanager
def demo_vendors() -> Iterator[None]:
    """Replace every vendor seam for the length of the block, and put each one back after."""
    originals: list[tuple[Any, str, Any]] = []
    try:
        for (module_name, attribute), fake in demo_vendor_fakes().items():
            module = importlib.import_module(module_name)
            originals.append((module, attribute, getattr(module, attribute)))
            setattr(module, attribute, fake)
        yield
    finally:
        for module, attribute, original in reversed(originals):
            setattr(module, attribute, original)


# ----------------------------------------------------------------------- the language model --


class DemoModel:
    """One stand-in model for every employee, answering each prompt in that prompt's schema.

    It reads the prompt for the shape it is asked for and fills it from what the prompt itself
    carries: the claim ids the writer was given, the event ids of the day, the cast. An answer
    that invented an identifier would be refused by the studio, so what makes this stand-in
    usable is the same thing that makes a real model usable. It is not intelligent and does not
    pretend to be: every film it writes is the same film about one sentence.
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

    def _answer(self, prompt: str) -> str:  # noqa: C901, PLR0911 - one branch per schema
        # Inbox reports contain other departments' schema words. The requested decision
        # schema wins over incidental words such as pronunciation in those reports.
        if '"assign_to_role"' in prompt and '"decisions"' in prompt:
            return self._director(prompt)
        if '"shots": [' in prompt or "ending_frame" in prompt:
            return self._shots(prompt)
        if "evidence_quote" in prompt:
            return json.dumps(
                {
                    "status": "SUPPORTED",
                    "confidence": 0.95,
                    "evidence_quote": DEMO_FACT,
                    "notes": "Sursa afirmă exact acest lucru.",
                }
            )
        if "claim_type" in prompt:
            return json.dumps(
                [
                    {
                        "claim_text": DEMO_FACT,
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
        if "pronunciation" in prompt:
            return json.dumps({"verdict": "PASS", "notes": [], "pronunciation": []})
        if "hold_reasons" in prompt:
            return json.dumps(
                {
                    "verdict": "READY",
                    "title": "The light your eyes were not built for",
                    "description": "What a telescope sees when it looks in infrared.",
                    "tags": ["space", "astronomy", "infrared"],
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
        if "assign_to_role" in prompt:
            return self._director(prompt)
        # Anything else is answered in prose, which every caller treats as an answer it could
        # not parse, and none of them may take the day down for it.
        return "DEMO: nimic de raportat."

    def _script(self, prompt: str) -> str:
        claim_ids = sorted(set(_UUID.findall(prompt)))
        narration = [
            "Most of what the universe is doing happens in light your eyes will never "
            "catch, and that is where this story starts tonight.",
            "The James Webb telescope observes the universe in infrared light, which is "
            "the part of the spectrum that carries heat rather than colour.",
            "So the dust that hides a young star from us is no longer a wall, and the "
            "picture underneath it finally arrives.",
            "Look up tonight and remember that the dark you see is only the part of the "
            "sky your eyes were built for.",
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
        """Return complete model-owned still/video prompts for the fixed DEMO astronomy film.

        The live editor no longer accepts a list of component hints as a shot plan: it
        needs the exact vendor texts and a recognized camera move. The demo's local
        still-image renderer never purchases those video prompts, but its real lint and
        storyboard gates check them just as they would check a paid film.
        """
        indices = sorted({int(n) for n in re.findall(r'"scene_index":\s*(\d+)', prompt)}) or [1]
        frames = (
            (
                "a wide, low angle, 24mm lens",
                "the observatory dome on a cold hillside at night",
                "the dome turns slowly, its shutter opening",
            ),
            (
                "a medium shot, eye-level, 50mm lens",
                "the segmented golden mirror of a telescope",
                "a faint reflection drifts across the segments",
            ),
            (
                "a detail shot, macro, 85mm lens",
                "a cloud of red dust around a young star",
                "the dust thins slowly and light shows through",
            ),
            (
                "an aerial shot, high angle",
                "an empty field under a clear starry sky",
                "the stars wheel slowly overhead",
            ),
        )
        moves = ("dolly in", "tracking left", "crane up", "slow pan right")
        shots = []
        for index in indices:
            camera, subject, action = frames[(index - 1) % len(frames)]
            move = moves[(index - 1) % len(moves)]
            ending_frame = f"{subject}, centred"
            still = (
                f"Documentary photograph, {camera}. The first instant shows {subject} "
                "at a remote observatory beneath a dark, clear sky. Cold moonlight "
                "illuminates the foreground, with one warm lamp behind the subject. "
                "A single continuous vertical 9:16 frame, carefully composed."
            )
            motion = (
                f"A steady {move} at a measured pace while {action}. "
                "The world and subject remain consistent in one uninterrupted shot. "
                f"The shot ends on {ending_frame}."
            )
            shots.append(
                {
                    "scene_index": index,
                    "story_purpose": "EVIDENCE",
                    "subject": subject,
                    "action": action,
                    "environment": "a remote observatory far from any city",
                    "camera": camera,
                    "camera_move": move,
                    "lighting": "moonlight from the left, one warm lamp behind",
                    "composition": "vertical, the subject in the lower third",
                    "motion": action,
                    "emotion": "quiet anticipation",
                    "background": "stars, unmoving",
                    "continuity": "the same night sky as the previous shot",
                    "ending_frame": ending_frame,
                    "audio_intent": "wind, distant",
                    "transition": "cut",
                    "avoid": ["text of any kind"],
                    "still_prompt": still,
                    "motion_prompt": motion,
                    "negative_prompt": "letters, logos",
                }
            )
        return json.dumps({"shots": shots})

    def _director(self, prompt: str) -> str:
        ids: list[str] = []
        for boundary in re.findall(
            r"<untrusted_source_evidence[^>]*>(.*?)</untrusted_source_evidence>",
            prompt,
            re.DOTALL,
        ):
            try:
                facts = json.loads(boundary)
            except json.JSONDecodeError:
                continue
            if isinstance(facts, dict) and isinstance(facts.get("inbox"), list):
                ids = [
                    str(item["id"])
                    for item in facts["inbox"]
                    if isinstance(item, dict) and item.get("id")
                ]
                break
        return json.dumps(
            {
                "summary": "DEMO: ziua a mers; nimic nu cere decizia Proprietarului.",
                "decisions": [
                    {"message_id": message_id, "action": "ACKNOWLEDGE", "note": "Citit."}
                    for message_id in sorted(set(ids))[:20]
                ],
                "priorities": ["Ține ritmul zilnic."],
            }
        )


def register_demo_models(engine: Engine, registry: Any) -> DemoModel:
    """Register one DemoModel for every provider the studio has, replacing any adapter."""
    from app.agents.models import ProviderRecord  # noqa: PLC0415

    model = DemoModel()
    with Session(engine) as session:
        for provider_id in session.scalars(select(ProviderRecord.id)):
            registry.register(provider_id, model)
    return model


def demo_registry(engine: Engine) -> Any:
    """A fresh registry holding only the demo's model."""
    from app.providers.registry import ProviderRegistry  # noqa: PLC0415

    registry = ProviderRegistry()
    register_demo_models(engine, registry)
    return registry


# ---------------------------------------------------------------------------- the studio --


def prepare_demo_studio(engine: Engine, settings: Settings) -> dict[str, Any]:
    """Seed the demo studio once: the workforce, the channels, one topic and one source.

    Idempotent: a second call changes nothing. Writes only to the demo's own database (it
    refuses the studio's). The demo studio starts the way a day can run in it: the stop
    released, AUTONOMOUS_CEO, TEST, its seeded models usable by the stand-in. It is the
    demo's database only; a buyer's real install starts MANUAL and stopped.
    """
    guard_demo_database(settings)
    from app.agents.models import ModelRecord  # noqa: PLC0415
    from app.agents.services import seed_initial_workforce  # noqa: PLC0415
    from app.factual.models import TopicIdea  # noqa: PLC0415
    from app.factual.services import ingest_source_snapshot  # noqa: PLC0415
    from app.media.services import seed_default_character_bibles  # noqa: PLC0415
    from app.models import OwnerPolicy  # noqa: PLC0415
    from app.publishing.services import seed_default_channels  # noqa: PLC0415
    from app.services import append_event, utc_now  # noqa: PLC0415

    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    seed_default_channels(engine)
    with Session(engine) as session, session.begin():
        if session.scalar(select(TopicIdea.id).limit(1)) is not None:
            return {"prepared": False}
        policy = session.get(OwnerPolicy, 1)
        if policy is None:
            raise DemoRefused("DEMO: studioul demo nu este inițializat (rulează bootstrap).")
        policy.autonomy_stopped = False
        policy.autonomy_mode = "AUTONOMOUS_CEO"
        policy.environment = "TEST"
        policy.version += 1
        for record in session.scalars(select(ModelRecord)):
            # Usable by the stand-in only. The provider row stays NOT_CONFIGURED with no
            # health stamp: nothing here claims that a real model answered.
            record.is_available = True
            record.notes = "DEMO: răspunde DemoModel (simulat); nu a fost verificat la furnizor."
        topic_id = str(uuid4())
        session.add(
            TopicIdea(
                id=topic_id,
                title=DEMO_TOPIC_TITLE,
                topic="Astronomy",
                angle="What a telescope sees that eyes cannot",
                target_audience="science_enthusiasts",
                novelty_score=0.92,
                status="PROPOSED",
                created_at=utc_now(),
            )
        )
        append_event(
            session,
            "demo.prepared",
            "studio",
            "1",
            policy.version,
            {"topic_id": topic_id, "note": "DEMO: furnizori simulați"},
            str(uuid4()),
        )
    ingest_source_snapshot(
        engine,
        url=DEMO_SOURCE_URL,
        title="Text demonstrativ (demo, nu este o sursă reală)",
        publisher="example.com",
        author=None,
        raw_content=DEMO_FACT,
        credibility_score=0.9,
        correlation_id=str(uuid4()),
        topic_id=topic_id,
    )
    return {"prepared": True, "topic_id": topic_id}


def run_demo_day(engine: Engine, settings: Settings, vault: Any, registry: Any) -> dict:
    """One day of the demo studio, every stage the real one runs, on the replaced vendors.

    The caller holds `demo_vendors()` around it (the app does for its whole life).
    """
    guard_demo_database(settings)
    from app.runbook.services import execute_daily_run  # noqa: PLC0415
    from app.runbook.stages import build_stage_runners  # noqa: PLC0415

    runners = build_stage_runners(engine, settings, vault, registry)
    return execute_daily_run(engine, settings, vault, stage_runners=runners)


def demo_refusal(method: str, path: str) -> str | None:
    """The Owner's words for a request the demo refuses, or None when it may run."""
    if method.upper() in ("GET", "HEAD", "OPTIONS"):
        return None
    if any(pattern.match(path) for pattern in DEMO_REFUSED_PATHS):
        return DEMO_REFUSAL_RO
    return None


class DemoNetworkRefused(ConnectionRefusedError):
    """The demo process tried to reach another machine."""


def _local_address(address: object) -> bool:
    if isinstance(address, str):  # a Unix socket path
        return True
    host = address[0] if isinstance(address, tuple) and address else address
    try:
        return ipaddress.ip_address(str(host).split("%")[0]).is_loopback
    except ValueError:
        return str(host).lower() in ("localhost", "")


@contextmanager
def no_outbound_network() -> Iterator[None]:
    """For the life of the block, no socket of this process connects beyond this machine.

    A belt beside the replaced vendors: should any path the seams do not cover try the
    network, the demo refuses it instead of reaching a real service. Listening and loopback
    connections (the page, the studio's own sockets) are untouched.
    """
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def connect(self: socket.socket, address: Any) -> None:
        if not _local_address(address):
            raise DemoNetworkRefused(
                f"DEMO: nicio conexiune în afara acestui calculator ({address!r})"
            )
        real_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        if not _local_address(address):
            raise DemoNetworkRefused(
                f"DEMO: nicio conexiune în afara acestui calculator ({address!r})"
            )
        return real_connect_ex(self, address)

    socket.socket.connect = connect  # type: ignore[method-assign, assignment]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign, assignment]
    try:
        yield
    finally:
        socket.socket.connect = real_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = real_connect_ex  # type: ignore[method-assign]


def demo_settings(settings: Settings) -> Settings:
    """The settings a demo app runs on: every switch that would reach the network turned off."""
    guard_demo_database(settings)
    return settings.model_copy(
        update={
            "trends_enabled": False,
            "provider_catalog_refresh_enabled": False,
            "office_weather_host": None,
            "office_stream_signalling_url": None,
            "office_unreal_remote_url": None,
            "research_allowed_hosts": [],
            "youtube_client_id": None,
            "youtube_client_secret": None,
            "youtube_refresh_token": None,
        }
    )
