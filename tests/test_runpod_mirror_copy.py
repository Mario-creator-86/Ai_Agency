"""The ONE-TIME copy pod that fills the Owner's private Hugging Face mirrors (his cards,
2026-10-09: weights live in RunPod CACHED MODELS fed from his private HF PRO mirrors).

Nothing starts without his card «Copiez modelele în contul tău Hugging Face cu un server RunPod
temporar?»: his accept IS the press (one step, the cap written on it). The studio then creates a
temporary CPU pod, hands it the worker's files and the result addresses through his bucket
(presigned, so the pod holds no bucket key), and the guard TERMINATES it on success, failure,
the time cap, the dollar cap, or a studio restart - also any pod named amn-mirror-copy it does
not know. Every RunPod, bucket and Hugging Face call is faked."""

from __future__ import annotations

import hashlib
import json
import sys
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from app.decisions.models import OwnerDecision
from app.decisions.services import OWNER, DecideCommand, decide_owner_decision
from app.integrations.models import Integration
from app.models import DomainEvent
from app.providers.media_http import MediaProviderError
from app.providers.runpod import pods
from sqlalchemy import select
from sqlalchemy.orm import Session

HF_TOKEN = "hf_syntheticTokenForTestsOnly000000"  # pragma: allowlist secret - synthetic
STILLS_REPO = "mario/amn-stills"
MOTION_REPO = "mario/amn-motion"
COMMIT_S = "1" * 40
COMMIT_M = "2" * 40


class Cloud:
    """RunPod's pod API and the Owner's bucket, faked at the transport boundary."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, Any]] = []
        self.objects: dict[str, bytes] = {}
        self.pods: dict[str, dict[str, Any]] = {}
        self.create_error: Exception | None = None
        self.cost = 0.4
        #: Adversary knobs: a DELETE that fails, or one RunPod accepts while the pod lives on.
        self.delete_error: Exception | None = None
        self.delete_ignored = False
        #: Called inside the create (the studio may stop while RunPod answers).
        self.during_create: Any = None

    def __call__(self, host, method, path, headers, body=None, **kwargs):
        data = json.loads(body) if body and host == "api.runpod.io" else body
        self.calls.append((host, method, path, data))
        parts = urlsplit(path)
        if host == "bucket.example":
            key = parts.path.removeprefix("/amn-out/")
            if method == "PUT":
                self.objects[key] = body
                return None, b"", "text/plain"
            if key not in self.objects:
                raise MediaProviderError("NoSuchKey", http_status=404)
            raw = self.objects[key]
            return json.loads(raw), raw, "application/json"
        assert host == "api.runpod.io", host
        if method == "POST" and parts.path == "/v2/pods":
            if self.create_error is not None:
                raise self.create_error
            pod_id = f"pod_{len(self.created())}"
            self.pods[pod_id] = {
                "id": pod_id,
                "name": data["name"],
                "status": "RUNNING",
                "cost": self.cost,
                "env": dict(data["env"]),  # RunPod returns the env, the token included
                "createdAt": datetime.now(UTC).isoformat(),
            }
            answer = dict(self.pods[pod_id])
            if self.during_create is not None:
                self.during_create()
            return answer, b"", "application/json"
        if method == "GET" and parts.path == "/v2/pods":
            return (
                {
                    "pods": [dict(p) for p in self.pods.values()],
                    "pagination": {"hasNextPage": False},
                },
                b"",
                "application/json",
            )
        pod_id = parts.path.rsplit("/", 1)[1]
        if method == "GET":
            if pod_id not in self.pods:
                raise MediaProviderError("Not Found", http_status=404)
            return dict(self.pods[pod_id]), b"", "application/json"
        if method == "DELETE":
            if self.delete_error is not None:
                raise self.delete_error
            if pod_id not in self.pods:
                raise MediaProviderError("Not Found", http_status=404)
            if self.delete_ignored:
                return None, b"", ""
            del self.pods[pod_id]
            return None, b"", ""
        raise AssertionError(f"unexpected {method} {path}")

    def created(self) -> list[dict[str, Any]]:
        return [c[3] for c in self.calls if c[1] == "POST" and c[2] == "/v2/pods"]

    def deleted(self) -> list[str]:
        return [c[2].rsplit("/", 1)[1] for c in self.calls if c[1] == "DELETE"]

    def finish(self, copy_id: str, image: str, *, exit_code: int = 0, commit: str | None = None):
        key = f"amn/mirror-copy/{copy_id}/{image}.json"
        self.objects[key] = json.dumps(
            {"image": image, "exit_code": exit_code, "commit": commit, "tail": "done"}
        ).encode()


@pytest.fixture
def cloud(monkeypatch) -> Cloud:
    fake = Cloud()
    monkeypatch.setattr(pods, "default_transport", lambda: fake)
    return fake


def studio(engine, monkeypatch, **values: str) -> tuple[Any, str]:
    from test_runpod_gpu_policy import runpod

    config = {"stills_mirror_repo": STILLS_REPO, "motion_mirror_repo": MOTION_REPO} | values
    vault, identifier = runpod(engine, monkeypatch, allow=True, **config)
    with Session(engine) as session, session.begin():
        row = session.get(Integration, identifier)
        secrets = vault.decrypt(row.encrypted_secrets)
        row.encrypted_secrets = vault.encrypt({**secrets, "hf_token": HF_TOKEN})
    return vault, identifier


def the_card(engine) -> OwnerDecision:
    from app.decisions.seed import seed_owner_decisions

    seed_owner_decisions(engine)
    with Session(engine) as session:
        card = session.scalars(
            select(OwnerDecision).where(OwnerDecision.kind == "runpod_mirror_copy")
        ).one()
        session.expunge(card)
        return card


def accept(engine, card: OwnerDecision) -> dict[str, Any]:
    return decide_owner_decision(
        engine,
        card.id,
        DecideCommand(command_id=uuid4(), expected_version=card.version, decision="ACCEPT"),
        issued_by=OWNER,
    )


def copy_row(engine) -> pods.CopyPodRow:
    with Session(engine) as session:
        row = session.scalars(select(pods.CopyPodRow)).one()
        session.expunge(row)
        return row


# ---------------------------------------------------------------------------- his card


def test_the_card_asks_with_the_cap_and_nothing_starts_until_he_accepts(engine, monkeypatch, cloud):
    studio(engine, monkeypatch)
    card = the_card(engine)
    assert card.title_ro == (
        "Copiez modelele în contul tău Hugging Face cu un server RunPod temporar?"
    )
    words = card.why_ro + card.effect_ro
    assert "5" in card.effect_ro and "240" in card.effect_ro  # the dollar and the time cap
    assert STILLS_REPO in words and MOTION_REPO in words
    yes = card.options[0]
    assert yes["recommended"] and yes["apply"]["type"] == "runpod_mirror_copy"
    assert yes["apply"]["max_usd"] == "5.00" and yes["apply"]["max_minutes"] == 240
    assert {o["key"] for o in card.options} == {"yes", "not_yet"}
    assert not cloud.calls  # proposing spends nothing


def test_his_accept_starts_one_cpu_pod_with_the_token_only_in_its_environment(
    engine, monkeypatch, cloud
):
    _vault, identifier = studio(engine, monkeypatch)
    answer = accept(engine, the_card(engine))
    assert answer["decision"]["status"] == "ACCEPTED"
    (body,) = cloud.created()
    assert body["name"].startswith("amn-mirror-copy-")
    assert body["cpu"] == {"id": "cpu5c", "vcpuCount": 4} and "gpu" not in body
    assert body["image"] == "python:3.12-slim"
    # The pod holds one weight at a time (build.py), and RunPod gives a cpu5c pod at most
    # 15 GB of container disk per vCPU: 200 GB was refused with HTTP 400 (2026-10-09).
    lock = json.loads((pods.WORKER_DIR / "models.lock.json").read_text(encoding="utf-8"))
    largest_gb = max(entry["size_bytes"] for entry in lock) / 1e9
    assert largest_gb + 10 <= body["disk"] <= 15 * body["cpu"]["vcpuCount"]
    assert body["env"]["HF_TOKEN"] == HF_TOKEN and body["env"]["AMN_MIRROR_HOST"] == "pod"
    plan = json.loads(body["env"]["AMN_MIRROR_PLAN"])
    assert [job["image"] for job in plan["images"]] == ["stills", "motion"]
    assert plan["images"][0]["command"][-5:] == [
        "--image",
        "stills",
        "--repo",
        STILLS_REPO,
        "--execute",
    ]
    assert any(f["path"] == "runpod_worker/build.py" for f in plan["files"])
    assert all(f["url"].startswith("https://bucket.example/amn-out/") for f in plan["files"])
    # The worker's files went to his bucket first, by content.
    uploaded = {k for k in cloud.objects if k.startswith("amn/mirror-copy/src/")}
    assert {f"amn/mirror-copy/src/{f['sha256']}" for f in plan["files"]} <= uploaded
    assert body["cmd"][0] == "python" and "AMN_MIRROR_PLAN" in body["cmd"][-1]
    row = copy_row(engine)
    assert row.status == "RUNNING" and row.pod_id == "pod_1" and row.integration_id == identifier
    assert row.max_minutes == 240 and row.max_usd == "5.00"
    # The token is never in the books.
    with Session(engine) as session:
        books = json.dumps(
            [e.payload for e in session.scalars(select(DomainEvent))], ensure_ascii=False
        )
    assert HF_TOKEN not in books and HF_TOKEN not in json.dumps(row.result or {})


def test_an_accept_without_the_token_or_a_repo_changes_nothing_and_says_why(
    engine, monkeypatch, cloud
):
    from test_runpod_gpu_policy import runpod

    runpod(engine, monkeypatch, allow=True)  # no repos, no token
    card = the_card(engine)
    from app.decisions.services import DecisionApplyFailed

    with pytest.raises(DecisionApplyFailed) as failed:
        accept(engine, card)
    assert "Hugging Face" in str(failed.value)
    assert not cloud.calls
    with Session(engine) as session:
        assert session.get(OwnerDecision, card.id).status == "PENDING"
        assert session.scalars(select(pods.CopyPodRow)).first() is None


def test_start_copy_refuses_without_his_card(engine, monkeypatch, cloud):
    vault, identifier = studio(engine, monkeypatch)
    with pytest.raises(pods.CopyRefused):
        pods.start_copy(
            engine,
            vault,
            identifier,
            max_minutes=240,
            max_usd="5.00",
            decision_id=str(uuid4()),
        )
    assert not cloud.calls


# ------------------------------------------------------------------- the guard ends it


def started(engine, monkeypatch, cloud) -> tuple[Any, str, pods.CopyPodRow]:
    vault, identifier = studio(engine, monkeypatch)
    accept(engine, the_card(engine))
    return vault, identifier, copy_row(engine)


def test_success_terminates_the_pod_and_records_the_revisions_and_the_cost(
    engine, monkeypatch, cloud
):
    vault, identifier, row = started(engine, monkeypatch, cloud)
    pods.watch_copies(engine, vault, reason="TICK")
    assert not cloud.deleted()  # still copying
    cloud.finish(row.id, "stills", commit=COMMIT_S)
    cloud.finish(row.id, "motion", commit=COMMIT_M)
    summary = pods.watch_copies(engine, vault, reason="TICK")
    assert cloud.deleted() == ["pod_1"] and summary["terminated"] == ["pod_1"]
    done = copy_row(engine)
    assert done.status == "SUCCEEDED" and done.terminate_verified is True
    assert done.cost_usd is not None and float(done.cost_usd) >= 0
    with Session(engine) as session:
        config = session.get(Integration, identifier).config
        assert config["stills_mirror_revision"] == COMMIT_S
        assert config["motion_mirror_revision"] == COMMIT_M
        card = session.scalars(
            select(OwnerDecision).where(OwnerDecision.kind == "runpod_mirror_copy")
        ).one()
        assert card.status == "ACCEPTED"
        kinds = [e.event_type for e in session.scalars(select(DomainEvent))]
        assert "runpod.mirror_copy_finished" in kinds


def test_a_failed_image_terminates_the_pod_and_records_nothing(engine, monkeypatch, cloud):
    vault, identifier, row = started(engine, monkeypatch, cloud)
    cloud.finish(row.id, "stills", exit_code=1)
    pods.watch_copies(engine, vault, reason="TICK")
    assert cloud.deleted() == ["pod_1"]
    assert copy_row(engine).status == "FAILED"
    with Session(engine) as session:
        assert "stills_mirror_revision" not in session.get(Integration, identifier).config


def test_the_time_cap_terminates_it(engine, monkeypatch, cloud):
    vault, _identifier, row = started(engine, monkeypatch, cloud)
    later = datetime.now(UTC) + timedelta(minutes=239, seconds=30)
    pods.watch_copies(engine, vault, reason="TICK", now=later)
    assert cloud.deleted() == ["pod_1"] and copy_row(engine).status == "TIMED_OUT"


def test_the_dollar_cap_terminates_it_before_it_is_reached(engine, monkeypatch, cloud):
    cloud.cost = 3.0  # USD per hour, as RunPod reports it
    vault, _identifier, _row = started(engine, monkeypatch, cloud)
    later = datetime.now(UTC) + timedelta(minutes=99)  # 4.95 USD, one tick from 5.00
    pods.watch_copies(engine, vault, reason="TICK", now=later)
    assert cloud.deleted() == ["pod_1"]
    stopped = copy_row(engine)
    assert stopped.status == "OVER_COST" and float(stopped.cost_usd) <= 5.0


def test_a_restart_terminates_a_live_copy_and_any_unknown_copy_pod(engine, monkeypatch, cloud):
    vault, _identifier, _row = started(engine, monkeypatch, cloud)
    cloud.pods["pod_orphan"] = {"id": "pod_orphan", "name": "amn-mirror-copy-0badc0de", "cost": 0.4}
    cloud.pods["pod_his"] = {"id": "pod_his", "name": "his-own-pod", "cost": 1.0}
    # A name that merely starts like ours is his, not the studio's (ours end in 8 hex digits).
    cloud.pods["pod_his_2"] = {"id": "pod_his_2", "name": "amn-mirror-copy-backup", "cost": 1.0}
    pods.watch_copies(engine, vault, reason="BOOT")
    assert sorted(cloud.deleted()) == ["pod_1", "pod_orphan"]
    assert "pod_his" in cloud.pods and "pod_his_2" in cloud.pods  # never a pod we did not name
    assert copy_row(engine).status == "STOPPED"


def test_an_unanswered_create_is_swept_by_its_name(engine, monkeypatch, cloud):
    cloud.create_error = MediaProviderError("no answer", unanswered=True)
    vault, identifier = studio(engine, monkeypatch)
    from app.decisions.services import DecisionApplyFailed

    with pytest.raises(DecisionApplyFailed):
        accept(engine, the_card(engine))
    row = copy_row(engine)
    assert row.status == "FAILED" and row.error_code == "CREATE_UNCERTAIN"
    # RunPod made it after all: the next tick finds it by name and terminates it.
    cloud.pods["pod_late"] = {"id": "pod_late", "name": row.pod_name, "cost": 0.4}
    pods.watch_copies(engine, vault, reason="TICK")
    assert cloud.deleted() == ["pod_late"]


def test_one_copy_at_a_time(engine, monkeypatch, cloud):
    vault, identifier, _row = started(engine, monkeypatch, cloud)
    with pytest.raises(pods.CopyRefused):
        pods.start_copy(
            engine,
            vault,
            identifier,
            max_minutes=240,
            max_usd="5.00",
            decision_id=the_decision(engine),
        )
    assert len(cloud.created()) == 1


def the_decision(engine) -> str:
    with Session(engine) as session:
        return session.scalars(
            select(OwnerDecision.id).where(OwnerDecision.kind == "runpod_mirror_copy")
        ).one()


def test_the_guard_keeps_its_short_interval_while_a_copy_runs(engine, monkeypatch, cloud):
    from app.providers.runpod.gpu_guard import next_interval

    assert next_interval(engine, (60, 600)) == 600
    started(engine, monkeypatch, cloud)
    assert next_interval(engine, (60, 600)) == 60


# -------------------------------------------------------------- the pod's own bootstrap


class _Bucket(BaseHTTPRequestHandler):
    store: dict[str, bytes] = {}

    def do_GET(self):  # noqa: N802 - the http.server name
        data = self.store.get(self.path)
        self.send_response(200 if data is not None else 404)
        self.end_headers()
        if data is not None:
            self.wfile.write(data)

    def do_PUT(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        self.store[self.path] = self.rfile.read(length)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


def test_the_bootstrap_checks_every_file_runs_each_image_and_reports(tmp_path, monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _Bucket)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    source = b"import sys\nprint('copied ' + sys.argv[-1])\nprint('" + COMMIT_S.encode() + b"')\n"
    _Bucket.store = {"/src/tool": source}
    plan = {
        "root": str(tmp_path / "amn"),
        "linger": False,
        "pip": [],
        "files": [
            {
                "path": "tool.py",
                "url": base + "/src/tool",
                "sha256": hashlib.sha256(source).hexdigest(),
            }
        ],
        "pre": [],
        "images": [
            {
                "image": "stills",
                "repo": STILLS_REPO,
                "command": ["{python}", "tool.py", "--execute"],
                "result_url": base + "/results/stills.json",
            }
        ],
    }
    monkeypatch.setenv("AMN_MIRROR_PLAN", json.dumps(plan))
    monkeypatch.setattr(sys, "argv", ["bootstrap"])
    namespace: dict[str, Any] = {"__name__": "__main__"}
    exec(compile(pods.BOOTSTRAP, "bootstrap", "exec"), namespace)  # noqa: S102 - our own text
    server.shutdown()
    result = json.loads(_Bucket.store["/results/stills.json"])
    assert result["exit_code"] == 0 and result["commit"] == COMMIT_S
    assert (Path(plan["root"]) / "tool.py").read_bytes() == source


def test_a_tampered_file_is_never_run(tmp_path, monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _Bucket)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    _Bucket.store = {"/src/tool": b"print('evil')"}
    plan = {
        "root": str(tmp_path / "amn"),
        "linger": False,
        "pip": [],
        "files": [{"path": "tool.py", "url": base + "/src/tool", "sha256": "0" * 64}],
        "pre": [],
        "images": [
            {
                "image": "stills",
                "repo": STILLS_REPO,
                "command": ["{python}", "tool.py"],
                "result_url": base + "/results/stills.json",
            }
        ],
    }
    monkeypatch.setenv("AMN_MIRROR_PLAN", json.dumps(plan))
    exec(compile(pods.BOOTSTRAP, "bootstrap", "exec"), {"__name__": "__main__"})  # noqa: S102
    server.shutdown()
    result = json.loads(_Bucket.store["/results/stills.json"])
    assert result["exit_code"] != 0 and "sha256" in result["error"]
    assert not (Path(plan["root"]) / "tool.py").exists()


def test_the_studio_stopping_terminates_a_running_copy(engine, monkeypatch, cloud):
    from app.providers.runpod import gpu_session

    vault, _identifier, _row = started(engine, monkeypatch, cloud)
    asked: list[str] = []
    real = pods.watch_copies

    def watching(engine_, vault_, *, reason, transport=None, now=None):
        asked.append(reason)
        return real(engine_, vault_, reason=reason, now=now)

    monkeypatch.setattr(pods, "watch_copies", watching)
    # The GPU part of the off is not under test here: no endpoint is listed for it.
    monkeypatch.setattr(gpu_session, "listed", lambda target: False)
    gpu_session.force_off(engine, vault, reason="OWNER_OFF")
    assert asked == [] and not cloud.deleted()  # his GPU button is not the copy's stop
    gpu_session.force_off(engine, vault, reason="SHUTDOWN")
    assert asked == ["SHUTDOWN"] and cloud.deleted() == ["pod_1"]
    assert copy_row(engine).status == "STOPPED"


# ------------------------------------------- adversary: the copy pod never keeps billing
#
# 2026-10-09 verification. Every RunPod, bucket and Hugging Face call is faked; a "refused"
# DELETE uses a 4xx status so the client does not sleep through its retries.


def letters_to_him(monkeypatch) -> list[str]:
    from app.providers.runpod import gpu_session

    sent: list[str] = []
    monkeypatch.setattr(
        gpu_session,
        "owner_letter",
        lambda engine, subject, text, kind, correlation: sent.append(subject + "\n" + text),
    )
    return sent


def pod_listings(cloud: Cloud) -> int:
    return len([c for c in cloud.calls if c[1] == "GET" and urlsplit(c[2]).path == "/v2/pods"])


def test_two_presses_at_the_same_moment_start_one_pod(engine, monkeypatch, cloud):
    from app.decisions.services import _inner_command_id

    vault, identifier = studio(engine, monkeypatch)
    card = the_card(engine)
    inner = _inner_command_id(card.id, card.version, "yes")
    both_looked = threading.Barrier(2, timeout=20)
    real = pods._integration

    def slow(*args: Any) -> Any:
        both_looked.wait()  # both presses passed their first look before either writes
        return real(*args)

    monkeypatch.setattr(pods, "_integration", slow)
    answers: list[dict[str, Any]] = []
    refusals: list[Exception] = []

    def press() -> None:
        try:
            answers.append(
                pods.start_copy(
                    engine,
                    vault,
                    identifier,
                    max_minutes=240,
                    max_usd="5.00",
                    decision_inner=inner,
                )
            )
        except pods.CopyRefused as exc:
            refusals.append(exc)

    threads = [threading.Thread(target=press) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert len(cloud.created()) == 1
    with Session(engine) as session:
        assert len(session.scalars(select(pods.CopyPodRow)).all()) == 1
    assert len({answer["copy_id"] for answer in answers}) == 1 and not refusals


def test_a_terminate_that_fails_is_said_and_retried_until_runpod_confirms(
    engine, monkeypatch, cloud
):
    sent = letters_to_him(monkeypatch)
    vault, _identifier, row = started(engine, monkeypatch, cloud)
    cloud.finish(row.id, "stills", exit_code=1)
    cloud.delete_error = MediaProviderError("Forbidden", http_status=403)
    pods.watch_copies(engine, vault, reason="TICK")
    failed = copy_row(engine)
    assert failed.status == "FAILED" and failed.terminate_verified is False
    assert "pod_1" in cloud.pods
    # His letter never says «stopped» while RunPod has not confirmed it, and names the pod.
    assert sent and "oprit definitiv" not in sent[-1]
    assert row.pod_name in sent[-1] and "Terminate" in sent[-1]
    # Three days later (past the two-day sweep window) RunPod answers again: still ended.
    cloud.delete_error = None
    later = datetime.now(UTC) + timedelta(days=3)
    pods.watch_copies(engine, vault, reason="TICK", now=later)
    assert "pod_1" not in cloud.pods
    assert copy_row(engine).terminate_verified is True
    # Once confirmed, an old copy costs the guard no more listing calls.
    listed = pod_listings(cloud)
    pods.watch_copies(engine, vault, reason="TICK", now=later + timedelta(minutes=1))
    assert pod_listings(cloud) == listed


def test_a_delete_runpod_accepts_but_does_not_carry_out_is_never_called_verified(
    engine, monkeypatch, cloud
):
    vault, _identifier, row = started(engine, monkeypatch, cloud)
    cloud.finish(row.id, "stills", exit_code=1)
    cloud.delete_ignored = True  # 204, yet the pod still reads RUNNING
    pods.watch_copies(engine, vault, reason="TICK")
    assert "pod_1" in cloud.pods
    assert copy_row(engine).terminate_verified is False
    cloud.delete_ignored = False
    pods.watch_copies(engine, vault, reason="TICK")
    assert "pod_1" not in cloud.pods and copy_row(engine).terminate_verified is True


def test_one_pod_that_cannot_be_ended_does_not_shield_the_others(engine, monkeypatch, cloud):
    vault, _identifier, _row = started(engine, monkeypatch, cloud)
    cloud.pods["pod_a"] = {"id": "pod_a", "name": "amn-mirror-copy-0000000a", "cost": 0.4}
    cloud.pods["pod_b"] = {"id": "pod_b", "name": "amn-mirror-copy-0000000b", "cost": 0.4}

    def stubborn(host, method, path, headers, body=None, **kwargs):
        if method == "DELETE" and path.endswith("/pod_a"):
            raise MediaProviderError("Forbidden", http_status=403)
        return cloud(host, method, path, headers, body, **kwargs)

    monkeypatch.setattr(pods, "default_transport", lambda: stubborn)
    pods.watch_copies(engine, vault, reason="BOOT")
    assert "pod_b" not in cloud.pods and "pod_1" not in cloud.pods
    assert "pod_a" in cloud.pods  # retried on the next pass


def test_a_tick_while_the_copy_is_being_created_leaves_it_alone(engine, monkeypatch, cloud):
    sent = letters_to_him(monkeypatch)
    vault, _identifier = studio(engine, monkeypatch)
    ticks: list[dict[str, Any]] = []
    cloud.during_create = lambda: ticks.append(pods.watch_copies(engine, vault, reason="TICK"))
    accept(engine, the_card(engine))
    assert ticks  # the guard did look in the middle of the create
    row = copy_row(engine)
    assert row.status == "RUNNING" and row.pod_id == "pod_1"
    assert "pod_1" in cloud.pods and not cloud.deleted()
    assert sent == []  # no «stopped» letter, no fresh card for a copy that is starting
    with Session(engine) as session:
        kinds = [e.event_type for e in session.scalars(select(DomainEvent))]
    assert "runpod.mirror_copy_finished" not in kinds


def test_a_create_left_hanging_is_stopped_and_its_pod_swept(engine, monkeypatch, cloud):
    vault, _identifier, row = started(engine, monkeypatch, cloud)
    with Session(engine) as session, session.begin():
        saved = session.get(pods.CopyPodRow, row.id)
        saved.status, saved.pod_id = "CREATING", None  # the studio died inside the create
        saved.created_at = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
    pods.watch_copies(engine, vault, reason="TICK")
    assert copy_row(engine).status == "STOPPED" and cloud.deleted() == ["pod_1"]


def test_the_studio_stopping_during_the_create_ends_the_new_pod_at_once(engine, monkeypatch, cloud):
    from app.decisions.services import DecisionApplyFailed

    vault, _identifier = studio(engine, monkeypatch)
    cloud.during_create = lambda: pods.watch_copies(engine, vault, reason="SHUTDOWN")
    with pytest.raises(DecisionApplyFailed):
        accept(engine, the_card(engine))
    row = copy_row(engine)
    assert row.status == "STOPPED" and row.pod_id == "pod_1"
    assert "pod_1" not in cloud.pods and row.terminate_verified is True


def test_a_zero_price_in_runpods_answer_keeps_the_estimate(engine, monkeypatch, cloud):
    cloud.cost = 0.0  # a pod still PROVISIONING reads cost 0.0
    _vault, _identifier, row = started(engine, monkeypatch, cloud)
    assert row.rate_usd_per_hour == "1.00"


def test_the_token_never_reaches_the_books_the_logs_or_his_letters(
    engine, monkeypatch, cloud, caplog
):
    import logging

    caplog.set_level(logging.DEBUG)
    sent = letters_to_him(monkeypatch)
    vault, _identifier, row = started(engine, monkeypatch, cloud)
    pods.watch_copies(engine, vault, reason="TICK")  # reads the pod: RunPod returns its env
    cloud.objects[f"amn/mirror-copy/{row.id}/stills.json"] = json.dumps(
        {"image": "stills", "exit_code": 1, "commit": None, "tail": f"401 for {HF_TOKEN}"}
    ).encode()
    pods.watch_copies(engine, vault, reason="TICK")
    with Session(engine) as session:
        books = json.dumps(
            [e.payload for e in session.scalars(select(DomainEvent))]
            + [
                [c.why_ro, c.effect_ro, c.apply_error_ro, c.applied]
                for c in session.scalars(select(OwnerDecision))
            ],
            ensure_ascii=False,
            default=str,
        )
    kept = json.dumps(copy_row(engine).result)
    assert "[hf_token]" in kept
    assert HF_TOKEN not in books + caplog.text + "\n".join(sent) + kept


def test_a_refused_create_that_echoes_the_body_leaks_no_token(engine, monkeypatch, cloud, caplog):
    import logging

    from app.decisions.services import DecisionApplyFailed

    caplog.set_level(logging.DEBUG)
    cloud.create_error = MediaProviderError(
        f'400 Bad Request: {{"env": {{"HF_TOKEN": "{HF_TOKEN}"}}}}', http_status=400
    )
    studio(engine, monkeypatch)
    card = the_card(engine)
    with pytest.raises(DecisionApplyFailed) as refused:
        accept(engine, card)
    assert HF_TOKEN not in str(refused.value) and HF_TOKEN not in caplog.text
    with Session(engine) as session:
        assert HF_TOKEN not in (session.get(OwnerDecision, card.id).apply_error_ro or "")


def test_a_refused_create_tells_him_runpods_own_reason(engine, monkeypatch, cloud, caplog):
    # 2026-10-09: his first accept met a bare «HTTP 400»; RunPod's reason was dropped, so
    # neither he nor the studio could tell a bad field from a full data center.
    import logging

    from app.decisions.services import DecisionApplyFailed

    caplog.set_level(logging.DEBUG)
    cloud.create_error = MediaProviderError(
        "api.runpod.io refused the request (HTTP 400)",
        http_status=400,
        detail=f"no cpu5c capacity for this disk, token {HF_TOKEN}",
        issues=[{"path": "/disk", "message": "must be at most 100"}],
    )
    studio(engine, monkeypatch)
    card = the_card(engine)
    with pytest.raises(DecisionApplyFailed) as refused:
        accept(engine, card)
    words = str(refused.value)
    assert "HTTP 400" in words and "no cpu5c capacity for this disk" in words
    assert "/disk: must be at most 100" in words
    assert HF_TOKEN not in words and HF_TOKEN not in caplog.text
    logged = [r for r in caplog.records if r.getMessage() == "runpod_mirror_copy_refused"]
    assert logged and "no cpu5c capacity" in logged[0].reason
    assert HF_TOKEN not in logged[0].reason
    assert copy_row(engine).error_code == "CREATE_REFUSED_400"


def test_the_card_tells_him_the_token_is_visible_in_the_runpod_console(engine, monkeypatch, cloud):
    studio(engine, monkeypatch)
    words = the_card(engine).effect_ro
    assert "consola RunPod" in words and "revocă" in words


# ----------------------------------------- adversary: the pod ends itself without the studio


class _Cloud(_Bucket):
    """The loopback bucket plus RunPod's DELETE of a pod (the pod's own stop)."""

    stopped: list[tuple[str, str | None]] = []

    def do_DELETE(self):  # noqa: N802
        self.stopped.append((self.path, self.headers.get("Authorization")))
        self.send_response(204)
        self.end_headers()


def run_bootstrap(tmp_path, monkeypatch, plan_extra: dict[str, Any], command: list[str]):
    server = HTTPServer(("127.0.0.1", 0), _Cloud)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    source = b"print('" + COMMIT_S.encode() + b"')\n"
    _Cloud.store = {"/src/tool": source}
    _Cloud.stopped = []
    plan = {
        "root": str(tmp_path / "amn"),
        "linger": False,
        "pip": [],
        "stop_api": base + "/v2/pods/",
        "files": [
            {
                "path": "tool.py",
                "url": base + "/src/tool",
                "sha256": hashlib.sha256(source).hexdigest(),
            }
        ],
        "pre": [],
        "images": [
            {
                "image": "stills",
                "repo": STILLS_REPO,
                "command": command,
                "result_url": base + "/results/stills.json",
                "result_get_url": base + "/results/stills.json",
            }
        ],
    } | plan_extra
    monkeypatch.setenv("AMN_MIRROR_PLAN", json.dumps(plan))
    monkeypatch.setenv("RUNPOD_POD_ID", "pod_self")
    monkeypatch.setenv("RUNPOD_API_KEY", "pod-scoped-key")  # pragma: allowlist secret
    namespace: dict[str, Any] = {"__name__": "bootstrap"}
    exec(compile(pods.BOOTSTRAP, "bootstrap", "exec"), namespace)  # noqa: S102 - our own text
    return server, namespace


def test_the_pod_stops_itself_at_its_deadline_even_with_no_studio(tmp_path, monkeypatch):
    import time

    server, namespace = run_bootstrap(
        tmp_path,
        monkeypatch,
        {"not_after": time.time() + 3},
        ["{python}", "-c", "import time; time.sleep(60)"],
    )
    began = time.monotonic()
    namespace["_main"]()
    server.shutdown()
    assert time.monotonic() - began < 30  # the copy was cut at the deadline, not after 60 s
    result = json.loads(_Cloud.store["/results/stills.json"])
    assert result["exit_code"] != 0 and "DEADLINE" in result["error"]
    assert _Cloud.stopped == [("/v2/pods/pod_self", "Bearer pod-scoped-key")]


def test_a_finished_copy_stops_its_own_pod(tmp_path, monkeypatch):
    server, namespace = run_bootstrap(
        tmp_path, monkeypatch, {}, ["{python}", "tool.py", "--execute"]
    )
    namespace["_main"]()
    server.shutdown()
    assert json.loads(_Cloud.store["/results/stills.json"])["commit"] == COMMIT_S
    assert _Cloud.stopped == [("/v2/pods/pod_self", "Bearer pod-scoped-key")]


def test_a_restarted_container_never_copies_again(tmp_path, monkeypatch):
    marker = tmp_path / "ran"
    server, namespace = run_bootstrap(
        tmp_path,
        monkeypatch,
        {},
        ["{python}", "-c", f"open({str(marker)!r}, 'w').write('x')"],
    )
    _Cloud.store["/results/stills.json"] = json.dumps(
        {"image": "stills", "exit_code": 0, "commit": COMMIT_S}
    ).encode()
    namespace["_main"]()
    server.shutdown()
    assert not marker.exists() and _Cloud.stopped  # it only stopped itself


def test_the_studio_gives_the_pod_its_deadline_and_no_linger(engine, monkeypatch, cloud):
    import time

    before = time.time()
    started(engine, monkeypatch, cloud)
    (body,) = cloud.created()
    plan = json.loads(body["env"]["AMN_MIRROR_PLAN"])
    assert plan["linger"] is False
    # 240 minutes on the card (5.00 USD at the 1.00 USD/h estimate is later), one guard
    # interval earlier, counted from before the create.
    assert before + 240 * 60 - 60 - 5 <= plan["not_after"] <= time.time() + 240 * 60 - 60
    for job in plan["images"]:
        assert job["result_get_url"].startswith("https://bucket.example/amn-out/")
        assert job["result_get_url"] != job["result_url"]


def test_a_copy_that_finished_while_the_studio_was_down_is_kept_at_boot(engine, monkeypatch, cloud):
    vault, identifier, row = started(engine, monkeypatch, cloud)
    cloud.finish(row.id, "stills", commit=COMMIT_S)  # the pod finished alone, PC switched off
    cloud.finish(row.id, "motion", commit=COMMIT_M)
    pods.watch_copies(engine, vault, reason="BOOT")
    done = copy_row(engine)
    assert done.status == "SUCCEEDED" and "pod_1" not in cloud.pods
    with Session(engine) as session:
        config = session.get(Integration, identifier).config
    assert config["stills_mirror_revision"] == COMMIT_S
    assert config["motion_mirror_revision"] == COMMIT_M


def test_his_success_letter_gives_the_console_steps_with_both_pins(engine, monkeypatch, cloud):
    # Completeness critic 2026-10-09: the studio writes the revisions into its own settings, but
    # the worker reads them from each endpoint (Model field + AMN_MIRROR_REPO/REVISION). His
    # letter is where he learns the exact values to put there.
    sent = letters_to_him(monkeypatch)
    vault, _identifier, row = started(engine, monkeypatch, cloud)
    cloud.finish(row.id, "stills", commit=COMMIT_S)
    cloud.finish(row.id, "motion", commit=COMMIT_M)
    pods.watch_copies(engine, vault, reason="TICK")
    (letter,) = [text for text in sent if "este gata" in text]
    for value in ("ep-stills", "ep-motion", STILLS_REPO, MOTION_REPO, COMMIT_S, COMMIT_M):
        assert value in letter
    assert "AMN_MIRROR_REVISION" in letter and "Model" in letter
    assert HF_TOKEN not in letter
