"""Free Director work proceeds during GPU waiting; no extra queue worker or paid call."""

from app.config import Settings
from app.models import OwnerPolicy
from app.workflows.director_upkeep import director_wait_work
from sqlalchemy.orm import Session


def callback(engine, monkeypatch, *, fails=False):
    calls = []
    moment = [0.0]
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False

    def manage(*args, **kwargs):
        calls.append("management")
        if fails:
            raise RuntimeError("temporary failure")
        return {"status": "COMPLETED"}

    def mail(*args, **kwargs):
        assert kwargs["limit"] == 1
        calls.append("mail")
        return {"answered": []}

    monkeypatch.setattr("app.agents.command.direct_company", manage)
    monkeypatch.setattr("app.agents.mail.correspondence_round", mail)
    check = director_wait_work(
        engine,
        object(),
        settings=Settings(worker_enabled=True, director_check_interval_seconds=30),
        clock=lambda: moment[0],
        background=False,
    )
    assert check is not None
    return check, calls, moment


def test_the_free_work_runs_beside_the_poll_and_a_long_round_is_not_queued_twice(
    engine, monkeypatch
):
    """2026-10-15 16:49Z, a4ecf40a: the Director's company call ran past ten minutes inside
    the motion step's wait; the poll could not collect scene 8 nor renew the GPU session, and
    the guard turned the idle worker off. The free work runs on its own thread: the poll's
    check returns at once, and while a round is still running the next interval starts
    nothing new."""
    import threading

    calls = []
    gate = threading.Event()
    moment = [0.0]
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False

    def manage(*args, **kwargs):
        calls.append("management")
        gate.wait(timeout=10)  # the model's long answer
        return {"status": "COMPLETED"}

    monkeypatch.setattr("app.agents.command.direct_company", manage)
    monkeypatch.setattr(
        "app.agents.mail.correspondence_round", lambda *a, **k: calls.append("mail")
    )
    check = director_wait_work(
        engine,
        object(),
        settings=Settings(worker_enabled=True, director_check_interval_seconds=30),
        clock=lambda: moment[0],
    )
    assert check is not None
    moment[0] = 30
    check()  # returns at once, the round runs beside it
    assert check.running()
    moment[0] = 60
    check()  # the round is still at the model: nothing new starts
    assert calls == ["management"]
    gate.set()
    for _ in range(100):
        if not check.running():
            break
        threading.Event().wait(0.05)
    assert not check.running() and calls == ["management", "mail"]
    moment[0] = 90
    check()
    for _ in range(100):
        if not check.running():
            break
        threading.Event().wait(0.05)
    assert calls == ["management", "mail"] * 2


def test_wait_work_checks_the_backlog_at_its_configured_interval(engine, monkeypatch):
    check, calls, moment = callback(engine, monkeypatch)
    check()
    assert not calls
    moment[0] = 30
    check()
    check()
    assert calls == ["management", "mail"]
    moment[0] = 60
    check()
    assert calls == ["management", "mail"] * 2


def test_owner_autonomy_stop_prevents_all_wait_work(engine, monkeypatch):
    check, calls, moment = callback(engine, monkeypatch)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = True
    moment[0] = 30
    check()
    assert not calls


def test_a_free_management_failure_does_not_fail_the_purchase_or_hide_mail(engine, monkeypatch):
    check, calls, moment = callback(engine, monkeypatch, fails=True)
    moment[0] = 30
    check()
    assert calls == ["management", "mail"]


def test_shutdown_prevents_wait_work(engine, monkeypatch):
    check, calls, moment = callback(engine, monkeypatch)
    monkeypatch.setattr("app.workflows.director_upkeep.shutdown_requested", lambda engine: True)
    moment[0] = 30
    check()
    assert not calls


def test_disabled_worker_or_no_registry_cannot_start_wait_work(engine):
    assert director_wait_work(engine, None) is None
    assert director_wait_work(engine, object(), settings=Settings(worker_enabled=False)) is None


def test_the_new_check_cadence_updates_the_existing_job_without_activating_it(engine):
    from app.workflows.services import ensure_scheduled_job

    first = ensure_scheduled_job(
        engine,
        name="director_loop",
        workflow_type="DIRECTOR_LOOP",
        interval_seconds=21600,
        active=False,
    )
    current = ensure_scheduled_job(
        engine,
        name="director_loop",
        workflow_type="DIRECTOR_LOOP",
        interval_seconds=300,
        active=True,
        follow_interval=True,
    )
    assert current["id"] == first["id"] and current["is_active"] is False
    assert current["interval_seconds"] == 300


def test_runpod_polling_performs_free_work_before_the_requested_image_arrives(
    engine,
    tmp_path,
    monkeypatch,
    fake_session,  # noqa: F811 - shared fixture
):
    from test_runpod_batch import Cloud, adapter, request, rounds

    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    waiting = []

    def free_work():
        waiting.append("director checked backlog")
        for job in cloud.jobs:
            cloud.finish(job, 0)

    summary, meter, outcomes = rounds(engine, made, [request("1")], on_wait=free_work)
    assert waiting
    assert len(cloud.jobs) == 1 and summary["items_sent"] == 1
    assert len(outcomes) == 1 and meter.attempts == 1


from test_runpod_batch import fake_session  # noqa: E402,F401 - shared fixture
