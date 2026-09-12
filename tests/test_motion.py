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

    stills = [Path(f"scene_{i}.png") for i in (1, 2, 3)]
    args = _dissolve_command(
        "ffmpeg", stills, [None, None, None], SCENES, Path("audio.wav"), Path("out.mp4")
    )
    chain = args[args.index("-filter_complex") + 1]
    # Offsets are the cumulative narration lengths: 4.0 and 10.0, not 4.0 and 9.6.
    assert "offset=4.000" in chain and "offset=10.000" in chain
    assert chain.count("xfade=transition=fade") == 2
    assert f"duration={TRANSITION_SECONDS:.3f}" in chain
    # The film is exactly as long as the narration it carries (the output -t, after -map).
    tail = args[args.index("-map") :]
    assert "trim=duration=15.000" in chain and tail[tail.index("-t") + 1] == "15.000"
    # Every scene is a shot: three inputs plus the audio.
    assert args.count("-i") == 4 and chain.count("zoompan") == 3


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
