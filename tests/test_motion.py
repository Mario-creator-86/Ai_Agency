"""A short that moves, and the books that know what it cost.

What is asserted: every scene becomes a shot of its own length and the shots dissolve into
one another, with each dissolve consuming only the overlap so the picture never drifts from
the voice; a scene's approved still is the first frame of its generated clip; a model that
refuses leaves that scene as a slow push and the film is still made; what each shot cost —
narration by the character, still by the image, motion by the second — reaches the books.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from app.media.assembler import TRANSITION_SECONDS, assemble_video_job
from app.media.models import VideoRenderJob
from app.media.toolchain import find_ffmpeg
from app.providers.media_base import ImageResult, VideoGenerationResult
from app.providers.media_http import MediaProviderError
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_media_providers import png_bytes

SCENES = [
    {"scene_index": 1, "duration_seconds": 4.0, "visual_prompt": "a starry sky"},
    {"scene_index": 2, "duration_seconds": 6.0, "visual_prompt": "a spinning galaxy"},
    {"scene_index": 3, "duration_seconds": 5.0, "visual_prompt": "a collider tunnel"},
]


class StubImages:
    PROVIDER_NAME = "TEST_IMAGE_PROVIDER"
    model = "test-stills"
    integration_id = "conn-1"

    async def health_check(self):
        return {"status": "HEALTHY"}

    async def generate_image(self, prompt, **kwargs):
        return ImageResult(
            image_bytes=png_bytes(1024, 1536), format="png", width=1024, height=1536, prompt=prompt
        )


class StubMotion:
    """A video model that returns one tiny real clip, or refuses the scenes it is told to."""

    PROVIDER_NAME = "TEST_VIDEO_PROVIDER"
    model = "test-motion"
    integration_id = "conn-1"

    def __init__(self, clip: bytes, refuse: set[int] | None = None):
        self.clip = clip
        self.refuse = refuse or set()
        self.asked: list[dict] = []

    async def health_check(self):
        return {"status": "HEALTHY"}

    async def create_generation(
        self, prompt, *, image_ref=None, duration_seconds=4.0, aspect_ratio="9:16", extra=None
    ):
        self.asked.append(
            {
                "prompt": prompt,
                "seconds": duration_seconds,
                "first_frame_bytes": len(image_ref or b""),
                "ratio": aspect_ratio,
            }
        )
        if len(self.asked) in self.refuse:
            raise MediaProviderError("the model refused this shot")
        return f"task-{len(self.asked)}"

    async def get_generation_status(self, job_id):
        return VideoGenerationResult(
            job_id=job_id, status="COMPLETED", video_bytes=self.clip, raw_response={"task": job_id}
        )


def a_clip(tmp_path: Path) -> bytes:
    """Two seconds of real h264, made by the encoder the studio already requires."""
    import subprocess

    target = tmp_path / "stub_clip.mp4"
    subprocess.run(
        [
            find_ffmpeg(),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=navy:s=540x960:d=2",
            "-pix_fmt",
            "yuv420p",
            str(target),
        ],
        check=True,
        capture_output=True,
    )
    return target.read_bytes()


def test_the_shots_dissolve_and_the_picture_never_drifts_from_the_voice():
    """Each shot is one transition longer than its narration and each dissolve eats exactly
    that overlap, so shot N starts where scene N's words start."""
    from app.media.assembler import _dissolve_command

    shots = [Path(f"shot_{i:02d}.mp4") for i in (1, 2, 3)]
    args = _dissolve_command("ffmpeg", shots, SCENES, Path("audio.wav"), Path("out.mp4"))
    chain = args[args.index("-filter_complex") + 1]
    # Offsets are the cumulative narration lengths: 4.0 and 10.0, not 4.0 and 9.6.
    assert "offset=4.000" in chain and "offset=10.000" in chain
    assert chain.count("xfade=transition=fade") == 2
    assert f"duration={TRANSITION_SECONDS:.3f}" in chain
    # The film is exactly as long as the narration it carries (the output -t, after -map).
    tail = args[args.index("-map") :]
    assert "trim=duration=15.000" in chain and tail[tail.index("-t") + 1] == "15.000"
    # Every scene is a shot file of its own, plus the audio.
    assert args.count("-i") == 4
    assert all(str(shot) in args for shot in shots)
    # And a shot is built from the still with a push, or from the clip, each on its own.
    from app.media.assembler import _shot_command

    push = _shot_command("ffmpeg", Path("scene_01.png"), None, 4.4, Path("shot_01.mp4"))
    assert "zoompan" in " ".join(push) and "-loop" in push
    moved = _shot_command("ffmpeg", Path("scene_01.png"), Path("motion_01.mp4"), 4.4, Path("s.mp4"))
    assert "motion_01.mp4" in moved and "tpad=stop_mode=clone:stop_duration=4.400" in " ".join(
        moved
    )


@pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")
def test_the_still_becomes_the_first_frame_of_a_generated_shot(engine, tmp_path):
    from test_phase5_media import _seeded_storyboard

    storyboard_id, _ = _seeded_storyboard(engine, tmp_path)
    motion = StubMotion(a_clip(tmp_path))

    render = assemble_video_job(
        engine,
        storyboard_id,
        str(uuid4()),
        storage_root=tmp_path / "media",
        image_adapter=StubImages(),
        video_adapter_for_scene=lambda scene: motion,
    )

    assert motion.asked, "the motion model must actually have been asked"
    first = motion.asked[0]
    assert first["first_frame_bytes"] > 0 and first["ratio"] == "9:16"
    assert first["seconds"] > 0
    with Session(engine) as session:
        job = session.get(VideoRenderJob, render["job_id"])
        production = job.production_json
    assert production["motion"]["clips"] == production["motion"]["scenes"] >= 1
    assert production["motion"]["seconds"] > 0
    made = [s for s in production["scenes"] if (s.get("motion") or {}).get("bytes")]
    assert len(made) == production["motion"]["scenes"]
    assert Path(render["file_path"] if "file_path" in render else render["output_asset_id"])
    assert render["duration_seconds"] > 0


@pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")
def test_a_model_that_refuses_one_shot_leaves_a_push_and_the_film_is_made(engine, tmp_path):
    from test_phase5_media import _seeded_storyboard

    storyboard_id, _ = _seeded_storyboard(engine, tmp_path)
    motion = StubMotion(a_clip(tmp_path), refuse={1})

    render = assemble_video_job(
        engine,
        storyboard_id,
        str(uuid4()),
        storage_root=tmp_path / "media",
        image_adapter=StubImages(),
        video_adapter_for_scene=lambda scene: motion,
    )

    with Session(engine) as session:
        production = session.get(VideoRenderJob, render["job_id"]).production_json
    refused = [s for s in production["scenes"] if (s.get("motion") or {}).get("refused")]
    assert refused and "refused this shot" in refused[0]["motion"]["refused"]
    assert production["motion"]["clips"] < production["motion"]["scenes"]
    assert render["duration_seconds"] > 0  # the film exists all the same


def test_the_books_price_narration_by_the_character_a_still_by_the_image_and_motion_by_the_second(
    engine, tmp_path
):
    """One scene can be bought three ways. A unit with no recorded price is reported as
    unpriced instead of counted as free."""
    from app.economy.accountant import record_render_costs
    from app.integrations.models import Integration, ProviderResource
    from app.integrations.vault import CredentialVault
    from app.media.production_policy import estimate_cost_usd
    from app.services import append_event, utc_now

    integration_id = str(uuid4())
    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    with Session(engine) as session, session.begin():
        event = append_event(
            session,
            "settings.integration_saved",
            "integration",
            integration_id,
            1,
            {},
            str(uuid4()),
        )
        session.add(
            Integration(
                id=integration_id,
                kind="runway",
                name="runway",
                config={},
                encrypted_secrets=vault.encrypt({"api_key": "k"}),
                secret_fields=["api_key"],
                version=1,
                status="VERIFIED",
                checked_at=utc_now(),
                event_id=event.event_id,
            )
        )
        session.flush()
        for remote_id, pricing in (
            ("a-voice", {"per_1k_characters_usd": 0.30}),
            ("a-still", {"per_image_usd": 0.01}),
            ("a-motion", {"per_second_usd": 0.025}),
            ("unpriced", {}),
        ):
            session.add(
                ProviderResource(
                    id=str(uuid4()),
                    integration_id=integration_id,
                    resource_type="MODEL",
                    remote_id=remote_id,
                    name=remote_id,
                    api_metadata={},
                    api_available=True,
                    last_seen_at=utc_now(),
                    pricing=pricing,
                    capabilities={},
                    metadata_version=1,
                )
            )

    with Session(engine) as session:
        assert estimate_cost_usd(session, integration_id, "a-voice", characters=500) == 0.15
        assert estimate_cost_usd(session, integration_id, "a-still", images=1) == 0.01
        assert estimate_cost_usd(session, integration_id, "a-motion", seconds=4.4) == 0.11
        assert estimate_cost_usd(session, integration_id, "unpriced", seconds=4.4) is None
        # A unit the model has no price for does not silently become zero.
        assert estimate_cost_usd(session, integration_id, "a-still", seconds=4.4) is None

    from test_phase5_media import _seeded_storyboard

    storyboard_id, _ = _seeded_storyboard(engine, tmp_path)
    job_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            VideoRenderJob(
                id=job_id,
                storyboard_id=storyboard_id,
                status="COMPLETED",
                started_at=utc_now(),
                production_json={
                    "image": {"integration_id": integration_id, "model": "a-still"},
                    "scenes": [
                        {
                            "scene_index": 1,
                            "integration_id": integration_id,
                            "model_id": "a-voice",
                            "characters": 500,
                            "motion": {
                                "integration_id": integration_id,
                                "model": "a-motion",
                                "asked_seconds": 4.4,
                            },
                        }
                    ],
                },
            )
        )

    result = record_render_costs(engine, job_id, str(uuid4()))
    assert result["recorded"] == 3  # narration, still, motion — each once, each referenced


@pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")
def test_a_film_whose_picture_ends_early_is_not_recorded(engine, tmp_path, monkeypatch):
    """Six seconds of picture under forty-six of narration passed quality control once,
    because a container is as long as its longest stream. The render measures the picture
    stream itself and fails rather than record a film that is mostly silence to look at."""
    from app.media import assembler
    from app.media.models import MediaAsset
    from test_phase5_media import _seeded_storyboard

    storyboard_id, _ = _seeded_storyboard(engine, tmp_path)
    monkeypatch.setattr(assembler, "_video_stream_seconds", lambda exe, path: 1.0)

    with pytest.raises(assembler.RenderEngineUnavailable) as excinfo:
        assembler.assemble_video_job(
            engine,
            storyboard_id,
            str(uuid4()),
            storage_root=tmp_path / "media",
            image_adapter=StubImages(),
        )
    assert "picture is 1.00s" in str(excinfo.value)
    with Session(engine) as session:
        assert session.query(MediaAsset).count() == 0


@pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")
def test_quality_control_measures_the_picture_not_the_container(tmp_path):
    """What ffprobe is asked for: the video stream's own length, frames and rate."""
    import subprocess

    from app.media.qc import probe_media_file

    film = tmp_path / "short.mp4"
    subprocess.run(
        [
            find_ffmpeg(),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=108x192:d=3",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            str(film),
        ],
        check=True,
        capture_output=True,
    )
    probe = probe_media_file(film, find_ffmpeg())
    assert probe["ok"] and probe["has_audio"]
    assert probe["video_frames"] and probe["video_fps"]
    assert 2.5 <= probe["video_duration_seconds"] <= 3.5


def test_the_render_records_the_credits_the_vendor_named(engine, tmp_path):
    """Runway answers a new task with the credits it may charge. That number is the only
    thing the vendor says about the money, so the render keeps it per scene and in total —
    a render that spent credits can be read back even when no dollar price is recorded."""
    from test_phase5_media import _seeded_storyboard

    storyboard_id, _ = _seeded_storyboard(engine, tmp_path)

    class Priced(StubMotion):
        def __init__(self, clip):
            super().__init__(clip)
            self.last_estimated_credits = None

        async def create_generation(self, prompt, **kwargs):
            job = await super().create_generation(prompt, **kwargs)
            self.last_estimated_credits = 48.0
            return job

    motion = Priced(a_clip(tmp_path)) if find_ffmpeg() else None
    if motion is None:
        pytest.skip("ffmpeg not installed")
    render = assemble_video_job(
        engine,
        storyboard_id,
        str(uuid4()),
        storage_root=tmp_path / "media",
        image_adapter=StubImages(),
        video_adapter_for_scene=lambda scene: motion,
    )
    with Session(engine) as session:
        production = session.get(VideoRenderJob, render["job_id"]).production_json
    scenes = production["scenes"]
    assert all(s["motion"]["estimated_credits"] == 48.0 for s in scenes)
    assert production["motion"]["estimated_credits"] == 48.0 * len(scenes)
    # And the connection behind the voice is named, so narration can be priced at all.
    assert "integration_id" in production["voice"]


@pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")
def test_a_ceiling_stops_the_motion_pass_and_a_test_renders_the_minimum(engine, tmp_path):
    """Twenty-one dollars went on one film while the daily budget read zero, because
    nothing priced a shot. A render now carries what it may spend and how many scenes may
    be generated; both stop the pass rather than letting it run to the end of the money."""
    from test_phase5_media import _seeded_storyboard

    storyboard_id, _ = _seeded_storyboard(engine, tmp_path)

    class Costly(StubMotion):
        def __init__(self, clip):
            super().__init__(clip)
            self.last_estimated_credits = None

        async def create_generation(self, prompt, **kwargs):
            job = await super().create_generation(prompt, **kwargs)
            self.last_estimated_credits = 260.0  # what a six-second shot really cost
            return job

    # One scene only: what a test render asks for.
    limited = Costly(a_clip(tmp_path))
    render = assemble_video_job(
        engine,
        storyboard_id,
        str(uuid4()),
        storage_root=tmp_path / "media",
        image_adapter=StubImages(),
        video_adapter_for_scene=lambda scene: limited,
        motion_scene_limit=1,
    )
    with Session(engine) as session:
        production = session.get(VideoRenderJob, render["job_id"]).production_json
    assert len(limited.asked) == 1 and production["motion"]["clips"] == 1
    assert production["motion"]["scene_limit"] == 1
    assert any("test limit" in note for note in production.get("motion_notes", []))

    # And a ceiling. It bites only because a credit has a price: the studio must know what
    # the vendor's credits cost before it can stop at a number of dollars.
    from app.integrations.models import Integration
    from app.integrations.vault import CredentialVault
    from app.services import append_event, utc_now

    integration_id = str(uuid4())
    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    with Session(engine) as session, session.begin():
        event = append_event(
            session,
            "settings.integration_saved",
            "integration",
            integration_id,
            1,
            {},
            str(uuid4()),
        )
        session.add(
            Integration(
                id=integration_id,
                kind="runway",
                name="runway",
                config={"credit_usd": "0.01"},
                encrypted_secrets=vault.encrypt({"api_key": "k"}),
                secret_fields=["api_key"],
                version=1,
                status="VERIFIED",
                checked_at=utc_now(),
                event_id=event.event_id,
            )
        )

    # The model this connection offers, as a catalog refresh would have written it: newly
    # seen, so it is waiting outside production and a test of it is its benchmark.
    from app.integrations.models import ModelOutcome, ProviderResource

    with Session(engine) as session, session.begin():
        session.add(
            ProviderResource(
                id=str(uuid4()),
                integration_id=integration_id,
                resource_type="MODEL",
                remote_id="test-motion",
                name="test-motion",
                api_metadata={"tasks": ["image_to_video"]},
                api_available=True,
                last_seen_at=utc_now(),
                pricing={"per_second_usd": 0.43, "unit": "per second of video"},
                capabilities={"quality_score": 0.8},
                metadata_version=1,
                production_status="QUARANTINE",
            )
        )

    storyboard_two, _ = _seeded_storyboard(engine, tmp_path / "two")
    capped = Costly(a_clip(tmp_path))
    capped.integration_id = integration_id
    render_two = assemble_video_job(
        engine,
        storyboard_two,
        str(uuid4()),
        storage_root=tmp_path / "media2",
        image_adapter=StubImages(),
        video_adapter_for_scene=lambda scene: capped,
        motion_budget_usd=3.0,  # one shot at 2.60, then the line is crossed
        environment="TEST",
    )
    with Session(engine) as session:
        production_two = session.get(VideoRenderJob, render_two["job_id"]).production_json
    assert len(capped.asked) == 1, "the second shot must not be generated"
    assert production_two["motion"]["estimated_usd"] == 2.6
    assert any("motion budget" in note for note in production_two.get("motion_notes", []))
    assert production_two["motion"]["clips"] == 1

    # And what the shot did is recorded against the model, in the kind of run it was. A
    # model the studio has not admitted yet is being benchmarked by this very test —
    # otherwise a new model could never earn its way into production, because it is not
    # allowed to film production until it has results.
    with Session(engine) as session:
        outcomes = session.scalars(select(ModelOutcome)).all()
        assert len(outcomes) == 1
        outcome = outcomes[0]
        assert outcome.remote_id == "test-motion"
        assert outcome.environment == "TEST"
        assert outcome.run_kind == "TEST_BENCHMARK"
        assert outcome.accepted and outcome.first_pass
        assert outcome.credits == 260.0
        assert outcome.usd == 2.6


@pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")
def test_a_still_of_stripes_or_of_nothing_is_caught_and_a_real_picture_is_not(tmp_path):
    """The ATLAS payoff was eleven seconds of vertical stripes, scored 1.0 by quality control."""
    import subprocess

    from app.media.qc import still_is_degenerate

    ffmpeg = find_ffmpeg()

    def make(name: str, source: str):
        path = tmp_path / name
        subprocess.run(
            [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", source, "-frames:v", "1", str(path)],
            check=True,
            capture_output=True,
        )
        return path

    stripes = make("stripes.png", "nullsrc=s=540x960,format=gray,geq=lum='128+100*sin(X/4)'")
    blank = make("blank.png", "color=c=white:s=540x960")
    noise = make("scene.png", "life=s=540x960:ratio=0.5:random_seed=7,format=rgb24")

    assert "stripes" in (still_is_degenerate(ffmpeg, stripes) or "")
    assert "blank" in (still_is_degenerate(ffmpeg, blank) or "")
    assert still_is_degenerate(ffmpeg, noise) is None
    assert still_is_degenerate(None, noise) is None  # unmeasurable is not a refusal


@pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")
def test_the_director_sees_a_frame_from_every_scene(tmp_path):
    import subprocess

    from app.agents.editorial import frames_for

    ffmpeg = find_ffmpeg()
    film = tmp_path / "film.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=180x320:r=10",
            "-t",
            "10",
            "-pix_fmt",
            "yuv420p",
            str(film),
        ],
        check=True,
        capture_output=True,
    )
    assert len(frames_for(str(film), ffmpeg, 10.0, scene_seconds=[2, 2, 2, 2, 2])) == 5
    assert len(frames_for(str(film), ffmpeg, 10.0)) == 3  # no scenes known: the old three
