"""The same-day re-attempt, on the real day: it finishes what was bought and buys nothing twice.

Since 2026-09-18 the re-attempt follows only a transient fault that cost a film
(`PRODUCTION_STAGES`), and it re-runs the whole day. A fault after the media stage has bought
its shots is exactly such a fault, and what the second pass does with a film already
rendered is what this file measures. Measured by the verifier on 2026-09-19, before
`serial_stage.pending_log` took only a day that is over: the first attempt closed today's log
at its end, and the re-attempt's serial stage filmed an episode of today — one more render
and one more paid shot that the first attempt, finding yesterday quiet, had never decided on.

The studio is the end-to-end fixture with a video connection, so the shots are chosen by the
studio's own router and made by the fake. Quality control is the stage that fails: it runs
after the money is spent and before anything is published. The upload is not the failing
stage here because the YouTube adapter never raises on transport: it answers FAILED or
UNKNOWN, and an UNKNOWN upload is reconciled, never repeated. Nothing here reaches a vendor.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.economy.models import ProviderCostRecord
from app.factual.models import ScriptDraft
from app.media.models import Storyboard, VideoRenderJob
from app.publishing.models import PublicationRecord
from app.runbook.models import DailyRun
from app.runbook.stages import build_stage_runners
from app.story.services import business_date
from app.workflows.models import TaskQueueItem
from app.workflows.worker import build_task_handlers, worker_pass
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_autonomous_day_end_to_end import (  # noqa: F401 - the fixture is used by name
    TZ,
    _due_daily_job,
    _video_connection,
    requires_ffmpeg,
    studio,
)


def _count(engine, model) -> int:
    with Session(engine) as session:
        return len(list(session.scalars(select(model))))


@requires_ffmpeg
def test_a_re_attempt_after_paid_work_finishes_the_films_already_bought_and_buys_nothing(
    engine,
    settings,
    studio,  # noqa: F811 - the end-to-end fixture, imported by name
    no_network,
):
    from app.integrations.vault import CredentialVault
    from app.workflows.services import scheduler_tick

    _video_connection(engine)
    settings.daily_max_attempts = 3
    settings.stage_retry_backoff_seconds = 0

    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    runners = build_stage_runners(engine, settings, vault, studio["registry"])
    real_qc = runners["edit_and_qc"]
    first_day = {"failing": True}

    def qc_down_all_morning() -> dict[str, Any]:
        if first_day["failing"]:
            raise ConnectionResetError("the quality-control process lost its connection")
        return real_qc()

    runners["edit_and_qc"] = qc_down_all_morning
    handlers = build_task_handlers(engine, settings, vault, runners, studio["registry"])
    _due_daily_job(engine)
    assert len(scheduler_tick(engine)) == 1
    first = worker_pass(engine, handlers, registry=studio["registry"])

    (ran,) = first["ran"]
    with Session(engine) as session:
        run = session.scalars(select(DailyRun)).one()
        stages = {stage["stage"]: stage for stage in run.stages_json}
    # The films were bought and then lost to a transient fault, so the clock may try again.
    assert stages["media"]["status"] == "COMPLETED", stages["media"]["reason"]
    assert stages["edit_and_qc"]["status"] == "FAILED", stages["edit_and_qc"]
    assert stages["edit_and_qc"]["fault_class"] == "TRANSIENT", stages["edit_and_qc"]
    assert stages["publish"]["status"] == "BLOCKED", stages["publish"]
    assert stages["post_run"]["status"] != "BLOCKED" and stages["daily_log"]["status"] != "BLOCKED"
    assert run.status == "FAILED", run.status
    retry_id = ran["outcome"].get("retry_task_id")
    assert retry_id, ran["outcome"]
    assert _count(engine, PublicationRecord) == 0

    bought = {
        "renders": _count(engine, VideoRenderJob),
        "costs": _count(engine, ProviderCostRecord),
        "scripts": _count(engine, ScriptDraft),
        "storyboards": _count(engine, Storyboard),
        "shots_asked": len(studio["motion"].asked),
    }
    assert bought["shots_asked"] >= 1, "no shot was bought; the test would prove nothing"
    assert bought["renders"] >= 1

    # The re-attempt, due now instead of in half an hour, with quality control back.
    first_day["failing"] = False
    with Session(engine) as session, session.begin():
        session.get(TaskQueueItem, retry_id).next_attempt_at = (
            datetime.now(UTC) - timedelta(seconds=1)
        ).isoformat()
    second = worker_pass(engine, handlers, registry=studio["registry"])
    assert second["ran"], "the re-attempt did not run"

    # Nothing was bought or written twice: the same renders, the same books, no second
    # script or storyboard, no shot asked of the vendor again.
    assert _count(engine, VideoRenderJob) == bought["renders"]
    assert _count(engine, ProviderCostRecord) == bought["costs"]
    assert _count(engine, ScriptDraft) == bought["scripts"]
    assert _count(engine, Storyboard) == bought["storyboards"]
    assert len(studio["motion"].asked) == bought["shots_asked"]
    # And what was lost is recovered: every film the first pass rendered goes out, once.
    with Session(engine) as session:
        publications = list(session.scalars(select(PublicationRecord)))
        rendered = {
            job.output_asset_id
            for job in session.scalars(select(VideoRenderJob))
            if job.status == "COMPLETED"
        }
        runs = list(session.scalars(select(DailyRun).order_by(DailyRun.started_at)))
    assets = [record.media_asset_id for record in publications]
    assert len(assets) == len(set(assets)), "a film went out twice"
    assert set(assets) == rendered, (assets, rendered)
    assert len(runs) == 2 and runs[-1].business_date == business_date(TZ)
    assert runs[-1].status in ("COMPLETED", "PARTIAL"), runs[-1].stop_reason
    assert no_network.refused == [], no_network.refused
