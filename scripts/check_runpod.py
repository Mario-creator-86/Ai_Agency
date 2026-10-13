"""RunPod checks. By default OFFLINE: the configuration (RUNPOD_* in .env) is read and judged,
nothing is sent. ``--mock`` runs a fully offline image and 5-second video exercise. ``--live``
makes read-only calls (queue health, the endpoints' settings and /health) - it never sends
/run, never PATCHes, and is never run by the test suite."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db import create_db_engine, migrate  # noqa: E402
from app.providers.media_http import MediaProviderError  # noqa: E402
from app.providers.runpod.adapters import RunPodImageAdapter, RunPodVideoAdapter  # noqa: E402
from app.providers.runpod.config import RunPodConfig  # noqa: E402
from app.providers.runpod.provider import RunPodGenerationProvider  # noqa: E402


async def mock_check(folder: Path) -> dict:
    # Override all cloud and infrastructure switches, regardless of the operator's .env.
    config = RunPodConfig(
        enabled=True,
        mock=True,
        auto_start=False,
        auto_stop=False,
        allow_infra_actions=False,
        poll_interval=0.01,
        mode="pod",
    )
    engine = create_db_engine("sqlite:///" + str(folder / "journal.db"))
    migrate(engine)
    try:
        image = RunPodImageAdapter(config, engine, storage_root=folder / "assets")
        image.bind_scene(project_id="offline-check", scene_id="1", operation="image")
        first = await image.generate_image("Offline synthetic image; no production output", seed=7)
        image.core.record_quality(
            first.raw_response["job_id"],
            accepted=False,
            reason="Synthetic QA rejection for recovery verification",
        )
        second = await image.generate_image("Offline synthetic image with QA correction", seed=8)
        image.core.record_quality(second.raw_response["job_id"], accepted=True)
        video = RunPodVideoAdapter(config, engine, model="LTX-2.5", storage_root=folder / "assets")
        video.bind_scene(project_id="offline-check", scene_id="1", operation="video")
        job_id = await video.create_generation(
            "Offline synthetic motion",
            image_ref=second.image_bytes,
            duration_seconds=5,
            extra={"seed": 8},
        )
        # Rebuild the adapter to simulate restart, then recover by the saved remote id.
        restarted = RunPodVideoAdapter(
            config, engine, model="LTX-2.5", storage_root=folder / "assets"
        )
        await restarted.core.wait(job_id)
        result = await restarted.get_generation_status(job_id)
        restarted.core.record_quality(job_id, accepted=True)
        return {
            "mode": "MOCK_NO_GPU",
            "health": await image.core.health(),
            "models": await image.list_models(),
            "image_path": second.raw_response["asset_path"],
            "video_path": result.video_path,
            "video_seconds": result.duration_seconds,
            "video_bytes": len(result.video_bytes or b""),
            "restart_recovered": True,
            "qa": "synthetic rejection then acceptance; existing QA is tested separately",
            "metrics": restarted.core.metrics("offline-check", finished=True),
        }
    finally:
        engine.dispose()


def config_check(config: RunPodConfig) -> dict:
    """The configuration judged offline: what the GPU switch and the steps would use, and what
    is missing, in the Owner's words. No secret is ever part of the report."""
    problems: list[str] = []
    endpoints = {
        purpose: config.endpoint_for(purpose)  # type: ignore[arg-type]
        for purpose in ("image", "video")
    }
    if config.mode == "serverless" and not config.mock:
        if not config.api_key.get_secret_value():
            problems.append("Lipsește cheia API RunPod.")
        if not any(endpoints.values()):
            problems.append("Lipsește ID-ul endpointului Serverless (imagini și/sau mișcare).")
        if config.bucket() is None:
            problems.append(
                "Bucketul pentru rezultate nu este complet (adresă, nume și cele două chei)."
            )
    return {
        "mode": config.mode,
        "mock": config.mock,
        "enabled": config.enabled,
        "rate_usd_per_hour": f"{config.hourly_rate:.2f}",
        "endpoints": {k: v for k, v in endpoints.items() if v},
        "bucket_configured": config.bucket() is not None,
        "bucket_prefix": config.s3_prefix,
        "idle_timeout_seconds": config.idle_timeout_seconds,
        "max_workers": config.max_workers,
        "flashboot": config.flashboot,
        "endpoint_timeout_ms": config.endpoint_timeout_ms,
        "cold_start_seconds": config.cold_start_seconds,
        "problems": problems,
        "ready": config.ready_for_generation and not problems,
    }


async def endpoint_check(config: RunPodConfig) -> dict:
    """Read-only: each endpoint's settings and /health (GET only)."""
    from app.providers.runpod.endpoint import EndpointControl, is_off  # noqa: PLC0415

    report: dict = {}
    for purpose, endpoint_id in config.endpoints():
        control = EndpointControl(config, endpoint_id)
        settings, health = await control.read()
        report[endpoint_id] = {
            "purpose": purpose,
            "workers": [settings.workers_min, settings.workers_max, settings.idle_timeout],
            "flashboot": settings.flashboot,
            "timeout_ms": settings.timeout_ms,
            "running": health.running,
            "idle": health.idle,
            "in_queue": health.in_queue,
            "in_progress": health.in_progress,
            "off": is_off(settings, health),
        }
    return report


async def connection_check() -> dict:
    with tempfile.TemporaryDirectory(prefix="agency-runpod-health-") as temporary:
        engine = create_db_engine("sqlite:///" + str(Path(temporary) / "health.db"))
        try:
            provider = RunPodGenerationProvider(RunPodConfig(), engine)
            report = await provider.health()
            report["available_models"] = []
            if report["authenticated"] and report["cloud_backend_healthy"]:
                report["available_models"] = await provider.available_models()
            return report
        finally:
            engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mock", action="store_true", help="Offline only; creates synthetic assets"
    )
    parser.add_argument(
        "--live", action="store_true", help="Read-only calls to RunPod (GET only; never /run)"
    )
    args = parser.parse_args()
    try:
        if args.mock:
            folder = ROOT / "data" / "runpod-mock-check" / str(uuid4())
            folder.mkdir(parents=True)
            report = asyncio.run(mock_check(folder))
            (folder / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        elif args.live:
            config = RunPodConfig()
            report = {
                "config": config_check(config),
                "queue": asyncio.run(connection_check()),
                "endpoints": asyncio.run(endpoint_check(config)),
            }
        else:
            report = config_check(RunPodConfig())
        print(json.dumps(report, indent=2))
        return 0
    except MediaProviderError as exc:
        # Never print vendor bodies, request payloads, signed asset URLs or credentials.
        print(
            json.dumps(
                {"status": "FAILED", "error": type(exc).__name__, "http_status": exc.http_status}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
