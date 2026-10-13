"""The ONE-TIME copy pod that fills the Owner's private Hugging Face mirrors (2026-10-09).

His cards: the weights live in RunPod CACHED MODELS, one cached model per endpoint, each fed
from his own PRIVATE Hugging Face mirror (HF PRO) holding only the locked files. The mirrors are
filled once, by a temporary RunPod pod in the cloud, never over his home connection, and never
without his card «Copiez modelele în contul tău Hugging Face cu un server RunPod temporar?»:
his accept of that card IS the press (`decisions.sources.apply_runpod_mirror_copy`). A second
button on a settings page would ask the same consent twice and could be pressed for a cap he
never read; the card carries the cap, and an accept whose token, repo or bucket is missing
refuses with his reason and starts nothing.

What the studio does (RunPod REST v2, read 2026-10-09; page content is data):

* ``POST https://api.runpod.io/v2/pods`` {name, image, cpu: {id, vcpuCount}, disk, env, cmd}:
  a CPU pod (the docs allow it: «Exactly one of gpu or cpu»), named ``amn-mirror-copy-<id>``,
  image ``python:3.12-slim``. The pod holds no bucket key: it receives the worker's files
  (backend/runpod_worker, content-addressed in his bucket) and the result addresses as
  presigned URLs, and his Hugging Face token in its environment (it never enters the books).
  It runs `BOOTSTRAP`: every file checked by sha256 before anything runs, ``pip install`` of the
  pinned huggingface_hub, then ``python -m runpod_worker.build mirror --image <i> --repo <r>
  --execute`` per image (the worker's own command, a separate change), each outcome PUT to his
  bucket as ``mirror-copy/<id>/<image>.json``.
* The guard (`gpu_guard.run_gpu_guard`) reads those results every tick and ``DELETE
  /v2/pods/{id}`` (terminate: «Permanently terminates and deletes a pod») on success, on
  failure, one tick before the time cap or the dollar cap, and at a studio restart or shutdown;
  it also terminates any pod named ``amn-mirror-copy-<8 hex>`` it does not own (a create whose
  answer was lost, a terminate RunPod did not carry out). It never touches a pod the studio did
  not name, nor a copy still inside its create. Termination is verified by reading the pod (404
  or TERMINATED); an unconfirmed one is retried on every tick and his letter says so. At BOOT a
  copy that finished while the studio was down keeps its results (his revisions).
* The pod also ends ITSELF (adversary pass 2026-10-09), so a switched-off PC never leaves it
  billing: `BOOTSTRAP` cuts the copy at ``not_after`` (the card's cap, one guard interval
  early), then terminates its own pod with RunPod's pod-scoped ``RUNPOD_API_KEY`` and exits.
* Two accepts at the same moment start one pod: the check and the insert share the write lock.
* The cost recorded is RunPod's own ``cost`` (USD per hour) times the time the pod lived; until
  RunPod reports one, the configured estimate (CPU pod prices are not documented).

Every call is faked in the tests; nothing here runs unless his card was accepted.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from sqlalchemy import JSON, Boolean, CheckConstraint, Engine, Index, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.config import ROOT
from app.db import lock_for_write
from app.models import Base
from app.providers.media_http import MediaProviderError
from app.providers.runpod import s3
from app.providers.runpod.client import Transport, backoff_seconds
from app.providers.runpod.config import RunPodConfig
from app.providers.runpod.weights import expected_weights

if TYPE_CHECKING:
    from app.integrations.vault import CredentialVault

logger = logging.getLogger("studio.runpod")

#: Every copy pod's name starts with this; the guard terminates any such pod it does not own.
COPY_PREFIX = "amn-mirror-copy"
#: The exact names the studio gives (``amn-mirror-copy-`` + the copy id's first 8 hex digits):
#: a pod of his whose name only starts alike is never touched.
COPY_NAME = re.compile(r"^amn-mirror-copy-[0-9a-f]{8}$")
#: A copy younger than this may still be inside its create (files going to his bucket, RunPod
#: answering): a tick leaves it and its pod alone. An older one was left by a dead studio.
CREATING_GRACE = timedelta(minutes=15)
CREATING, RUNNING = "CREATING", "RUNNING"
SUCCEEDED, FAILED, TIMED_OUT, OVER_COST, STOPPED = (
    "SUCCEEDED",
    "FAILED",
    "TIMED_OUT",
    "OVER_COST",
    "STOPPED",
)
LIVE = (CREATING, RUNNING)
COPY_STATUSES = (CREATING, RUNNING, SUCCEEDED, FAILED, TIMED_OUT, OVER_COST, STOPPED)
MANAGEMENT_HOST = "api.runpod.io"
#: The worker's images and the endpoint purpose each mirror feeds.
IMAGES: dict[str, Literal["image", "video"]] = {"stills": "image", "motion": "video"}
WORKER_DIR = ROOT / "backend" / "runpod_worker"
#: RunPod refuses a create body above 102400 bytes (413); the studio stays well under it.
MAX_BODY = 90_000
#: The pod's states after which it bills nothing more (its container ended).
ENDED_POD_STATES = ("EXITED", "ERROR", "TERMINATED")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_TOKEN = re.compile(r"hf_[A-Za-z0-9]{20,}")
COPY_CARD_KIND = "runpod_mirror_copy"

#: Run by the pod (python -c): standard library only; the plan comes in AMN_MIRROR_PLAN.
#:
#: The pod never needs the studio to stop billing (adversary pass 2026-10-09): the plan carries
#: ``not_after`` (the card's cap as a wall-clock time, one guard interval early); every step
#: gets only the time left, and at the deadline the copy is cut and reported as DEADLINE. Then,
#: finished, failed or cut, the pod ends ITSELF: ``DELETE /v2/pods/$RUNPOD_POD_ID`` with the
#: pod-scoped ``RUNPOD_API_KEY`` RunPod gives every pod (docs: environment variables), and its
#: process exits (an EXITED pod reads cost 0.0). A restarted container first reads its results
#: (presigned GET) and never copies again once they say finished. UNPROVEN until the paid run:
#: whether the pod-scoped key may terminate its own pod; the studio's guard stays the primary
#: stop and terminates it either way.
BOOTSTRAP = r"""
import hashlib, json, os, re, subprocess, sys, time, urllib.request

STOP_API = "https://api.runpod.io/v2/pods/"


class _Deadline(Exception):
    pass


def _send(url, data, kind, attempts=5):
    request = urllib.request.Request(url, data=data, method="PUT", headers={"Content-Type": kind})
    for attempt in range(attempts):
        try:
            urllib.request.urlopen(request, timeout=120).read()
            return
        except Exception:
            time.sleep(2 * (attempt + 1))


def _read(url):
    try:
        return json.loads(urllib.request.urlopen(url, timeout=60).read())
    except Exception:
        return None


def _scrub(text, secret):
    if secret:
        text = text.replace(secret, "[hf_token]")
    return re.sub(r"hf_[A-Za-z0-9]{20,}", "[hf_token]", text)


def _command(parts):
    return [sys.executable if part == "{python}" else part for part in parts]


def _left(plan):
    # Seconds left before the card's cap (None: no deadline); _Deadline once it passed.
    not_after = plan.get("not_after")
    if not not_after:
        return None
    left = float(not_after) - time.time()
    if left <= 0:
        raise _Deadline()
    return left


def _report(job, payload, attempts=5):
    body = {"image": job["image"], "repo": job.get("repo"), **payload}
    _send(job["result_url"], json.dumps(body).encode("utf-8"), "application/json", attempts)


def _finished_before(plan):
    # A restarted container: its results already say finished (or failed) - copy nothing again.
    jobs = [job for job in plan["images"] if job.get("result_get_url")]
    if not jobs or len(jobs) != len(plan["images"]):
        return False
    results = [_read(job["result_get_url"]) for job in jobs]
    if any(isinstance(r, dict) and (r.get("exit_code") != 0 or r.get("error")) for r in results):
        return True
    return all(isinstance(r, dict) and r.get("commit") for r in results)


def _stop_self(plan):
    # The pod terminates itself with its own pod-scoped key; never another pod.
    pod_id = os.environ.get("RUNPOD_POD_ID", "")
    key = os.environ.get("RUNPOD_API_KEY", "")
    if not pod_id or not key:
        return False
    url = plan.get("stop_api") or STOP_API
    for attempt in range(3):
        request = urllib.request.Request(
            url + pod_id, method="DELETE", headers={"Authorization": "Bearer " + key}
        )
        try:
            urllib.request.urlopen(request, timeout=30).read()
            return True
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return True
            time.sleep(3 * (attempt + 1))
        except Exception:
            time.sleep(3 * (attempt + 1))
    return False


def _work(plan, secret, reported):
    root = plan["root"]
    fetched = []
    for entry in plan["files"]:
        _left(plan)
        data = urllib.request.urlopen(entry["url"], timeout=300).read()
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError("sha256 mismatch for " + entry["path"])
        fetched.append((entry["path"], data))
    for relative, data in fetched:
        target = os.path.join(root, relative)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(data)
    if plan.get("pip"):
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-cache-dir", *plan["pip"]],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=_left(plan),
        )
    for step in plan.get("pre", []):
        done = subprocess.run(
            _command(step["command"]), cwd=root, capture_output=True, text=True, timeout=_left(plan)
        )
        if done.returncode != 0:
            failed = _scrub(done.stdout + done.stderr, secret)[-500:]
            raise RuntimeError("pre step failed: " + failed)
    if plan.get("lock_url") and plan.get("lock_path"):
        with open(os.path.join(root, plan["lock_path"]), "rb") as handle:
            _send(plan["lock_url"], handle.read(), "application/json")
    for job in plan["images"]:
        done = subprocess.run(
            _command(job["command"]), cwd=root, capture_output=True, text=True, timeout=_left(plan)
        )
        output = _scrub(done.stdout, secret)
        commits = re.findall(r"\b[0-9a-f]{40}\b", output)
        _report(
            job,
            {
                "exit_code": done.returncode,
                "commit": commits[-1] if commits and done.returncode == 0 else None,
                "tail": _scrub(done.stdout + done.stderr, secret)[-2000:],
            },
        )
        reported.add(job["image"])
        if done.returncode != 0:
            break


def _main():
    plan = json.loads(os.environ["AMN_MIRROR_PLAN"])
    secret = os.environ.get("HF_TOKEN", "")
    reported = set()
    error, attempts = None, 5
    try:
        _left(plan)
        if not _finished_before(plan):
            _work(plan, secret, reported)
    except (_Deadline, subprocess.TimeoutExpired):
        error, attempts = "DEADLINE: the card's time or dollar cap was reached on the pod", 2
    except Exception as exc:
        error = _scrub(type(exc).__name__ + ": " + str(exc), secret)[:500]
    if error is not None:
        for job in plan["images"]:
            if job["image"] not in reported:
                _report(job, {"exit_code": -1, "commit": None, "error": error}, attempts)
    _stop_self(plan)
    while plan.get("linger", False):
        time.sleep(3600)


if __name__ == "__main__":
    _main()
"""


class CopyPodRow(Base):
    """One copy pod: what his card allowed, what RunPod did, what it cost."""

    __tablename__ = "runpod_copy_pod"
    __table_args__ = (
        CheckConstraint(
            "status IN ('CREATING','RUNNING','SUCCEEDED','FAILED','TIMED_OUT','OVER_COST',"
            "'STOPPED')",
            name="ck_runpod_copy_pod_status",
        ),
        Index("ix_runpod_copy_pod_status", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    integration_id: Mapped[str] = mapped_column(String(36), nullable=False)
    decision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    #: The inner command id of his accept: a retried accept finds this row, never a 2nd pod.
    decision_inner: Mapped[str | None] = mapped_column(String(36), nullable=True)
    pod_name: Mapped[str] = mapped_column(String(100), nullable=False)
    pod_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    images: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    repos: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    max_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    max_usd: Mapped[str] = mapped_column(String(20), nullable=False)
    rate_usd_per_hour: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    started_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    terminated_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    terminate_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    cost_usd: Mapped[str | None] = mapped_column(String(20), nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)


class CopyRefused(Exception):
    """Nothing was started; ``reason_ro`` says why, in his words."""

    def __init__(self, reason_ro: str) -> None:
        super().__init__(reason_ro)
        self.reason_ro = reason_ro


def default_transport() -> Transport:
    from app.providers.media_http import request  # noqa: PLC0415

    return request


def _now() -> datetime:
    return datetime.now(UTC)


def _when(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _decimal(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() and number >= 0 else None


# ------------------------------------------------------------------------------ the pod API


class PodControl:
    """RunPod's pod endpoints (REST v2). GET and DELETE are retried on a passing failure; the
    create is sent once (an unanswered create is swept by its name)."""

    def __init__(self, config: RunPodConfig, transport: Transport | None = None) -> None:
        self.config = config
        self.transport = transport or default_transport()

    async def _call(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
        *,
        retry: bool = True,
    ) -> Any:
        headers = {
            "Authorization": "Bearer " + self.config.api_key.get_secret_value(),
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        body = json.dumps(data, allow_nan=False).encode() if data is not None else None
        attempts = self.config.max_retries + 1 if retry else 1
        for attempt in range(attempts):
            try:
                value, _raw, _kind = await asyncio.to_thread(
                    self.transport,
                    MANAGEMENT_HOST,
                    method,
                    path,
                    headers,
                    body,
                    timeout=self.config.request_timeout,
                    total_seconds=self.config.request_timeout,
                    allowed_statuses=(200, 201, 202, 204),
                    connect_before_send=method == "POST",
                    expect_json=method != "DELETE",
                )
                return value
            except MediaProviderError as exc:
                transient = (
                    exc.unsent
                    or exc.http_status in (429, 500, 502, 503, 504)
                    or (exc.unanswered and method != "POST")
                )
                if not transient or attempt >= attempts - 1:
                    raise
                await asyncio.sleep(min(30.0, max(backoff_seconds(attempt), exc.retry_after or 0)))
        raise AssertionError("unreachable")

    async def create(self, body: dict[str, Any]) -> dict[str, Any]:
        value = await self._call("POST", "/v2/pods", body, retry=False)
        if not isinstance(value, dict) or not isinstance(value.get("id"), str):
            raise MediaProviderError("RunPod did not return a pod id", unanswered=True)
        return value

    async def get(self, pod_id: str) -> dict[str, Any] | None:
        try:
            value = await self._call("GET", "/v2/pods/" + pod_id)
        except MediaProviderError as exc:
            if exc.http_status == 404 and not exc.unanswered:
                return None
            raise
        return value if isinstance(value, dict) else None

    async def terminate(self, pod_id: str) -> bool:
        """DELETE the pod, then read it: True once RunPod no longer has it running."""
        try:
            await self._call("DELETE", "/v2/pods/" + pod_id)
        except MediaProviderError as exc:
            if exc.http_status != 404 or exc.unanswered:
                raise
        reading = await self.get(pod_id)
        return reading is None or str(reading.get("status")) == "TERMINATED"

    async def named(self, prefix: str) -> list[dict[str, Any]]:
        """Every pod of the account whose name starts with ``prefix``."""
        found: list[dict[str, Any]] = []
        cursor: str | None = None
        for _page in range(50):
            path = "/v2/pods" + (f"?cursor={cursor}" if cursor else "")
            value = await self._call("GET", path)
            pods = value.get("pods") if isinstance(value, dict) else None
            for pod in pods if isinstance(pods, list) else []:
                if isinstance(pod, dict) and str(pod.get("name") or "").startswith(prefix):
                    found.append(pod)
            pagination = value.get("pagination") if isinstance(value, dict) else None
            if not isinstance(pagination, dict) or not pagination.get("hasNextPage"):
                break
            cursor = str(pagination.get("nextCursor") or "") or None
            if cursor is None:
                break
        return found


# ---------------------------------------------------------------------------- his card


def _his_card(
    session: Session,
    integration_id: str,
    *,
    decision_id: str | None,
    decision_inner: str | None,
    max_minutes: int,
    max_usd: Decimal,
) -> Any:
    """The card that allows this copy, under the cap he read; CopyRefused otherwise. A card
    still PENDING counts only inside his accept (its inner command id is the proof)."""
    from app.decisions.models import OwnerDecision  # noqa: PLC0415
    from app.decisions.services import _inner_command_id  # noqa: PLC0415
    from app.decisions.sources import runpod_mirror_copy_key  # noqa: PLC0415

    query = select(OwnerDecision).where(
        OwnerDecision.dedupe_key == runpod_mirror_copy_key(integration_id)
    )
    if decision_id:
        query = query.where(OwnerDecision.id == decision_id)
    card = session.scalars(query.order_by(OwnerDecision.created_at.desc()).limit(1)).first()
    refused = CopyRefused(
        "Copierea modelelor pornește doar din cardul tău «Copiez modelele în contul tău "
        "Hugging Face cu un server RunPod temporar?»; nu s-a pornit nimic."
    )
    if card is None:
        raise refused
    yes = next(
        (
            option
            for option in card.options or []
            if (option.get("apply") or {}).get("type") == COPY_CARD_KIND
        ),
        None,
    )
    if yes is None:
        raise refused
    if card.status == "PENDING":
        if decision_inner != _inner_command_id(card.id, card.version, str(yes["key"])):
            raise refused
    elif not (
        card.status == "ACCEPTED"
        and isinstance(card.applied, dict)
        and card.applied.get("type") == COPY_CARD_KIND
    ):
        raise refused
    allowed_usd = _decimal(yes["apply"].get("max_usd")) or Decimal(0)
    allowed_minutes = int(yes["apply"].get("max_minutes") or 0)
    if max_usd > allowed_usd or max_minutes > allowed_minutes or max_usd <= 0 or max_minutes <= 0:
        raise CopyRefused(
            f"Plafonul cerut ({max_usd} USD, {max_minutes} minute) nu este cel de pe cardul tău "
            f"({allowed_usd} USD, {allowed_minutes} minute); nu s-a pornit nimic."
        )
    return card


# ------------------------------------------------------------------------- the copy plan


def _worker_files() -> list[tuple[str, bytes]]:
    files: list[tuple[str, bytes]] = []
    for path in sorted(WORKER_DIR.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        relative = path.relative_to(WORKER_DIR.parent).as_posix()
        files.append((relative, path.read_bytes()))
    return files


def _unpinned_motion() -> bool:
    """The gated LTX-2.5 files still have no sha256 in the lock: the pod pins them from the
    LFS metadata with his token (``build resolve``) before it copies (his licence accepted)."""
    try:
        lock = json.loads((WORKER_DIR / "models.lock.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    entries = (
        lock if isinstance(lock, list) else lock.get("files", []) if isinstance(lock, dict) else []
    )
    return any(
        isinstance(entry, dict) and entry.get("image") == "motion" and not entry.get("sha256")
        for entry in entries
    )


def result_key(prefix: str, copy_id: str, image: str) -> str:
    return f"{prefix}mirror-copy/{copy_id}/{image}.json"


async def _plan(
    config: RunPodConfig,
    bucket: s3.BucketConfig,
    copy_id: str,
    images: Sequence[str],
    repos: dict[str, str],
    lifetime: int,
    transport: Transport,
    not_after: float,
) -> dict[str, Any]:
    files = []
    for relative, content in _worker_files():
        sha = hashlib.sha256(content).hexdigest()
        key = f"{bucket.prefix}mirror-copy/src/{sha}"
        await s3.put_bytes(bucket, key, content, "application/octet-stream", transport)
        files.append(
            {"path": relative, "url": s3.presign(bucket, "GET", key, lifetime), "sha256": sha}
        )
    jobs = [
        {
            "image": image,
            "repo": repos[image],
            "command": [
                "{python}",
                "-m",
                "runpod_worker.build",
                "mirror",
                "--image",
                image,
                "--repo",
                repos[image],
                "--execute",
            ],
            "result_url": s3.presign(
                bucket, "PUT", result_key(bucket.prefix, copy_id, image), lifetime
            ),
            # A restarted container reads its own result first and never copies again.
            "result_get_url": s3.presign(
                bucket, "GET", result_key(bucket.prefix, copy_id, image), lifetime
            ),
        }
        for image in images
    ]
    pre = (
        [{"command": ["{python}", "-m", "runpod_worker.build", "resolve", "--image", "motion"]}]
        if "motion" in images and _unpinned_motion()
        else []
    )
    return {
        "root": "/amn",
        # The pod ends itself when done or at not_after; it never sits billing for the studio.
        "linger": False,
        "not_after": not_after,
        # The worker's own pin of its copy tools when it has one, else the configured one.
        "pip": ["-r", "runpod_worker/requirements-mirror.txt"]
        if (WORKER_DIR / "requirements-mirror.txt").is_file()
        else [config.mirror_pod_pip]
        if config.mirror_pod_pip
        else [],
        "files": files,
        "pre": pre,
        "lock_path": "runpod_worker/models.lock.json",
        "lock_url": s3.presign(
            bucket, "PUT", f"{bucket.prefix}mirror-copy/{copy_id}/models.lock.json", lifetime
        ),
        "images": jobs,
    }


# ------------------------------------------------------------------------------ start


def _integration(engine: Engine, vault: CredentialVault, integration_id: str) -> RunPodConfig:
    from app.integrations.models import Integration  # noqa: PLC0415

    with Session(engine) as session:
        row = session.get(Integration, integration_id)
        if row is None or row.kind != "runpod":
            raise CopyRefused("Conexiunea RunPod din card nu mai există; nu s-a pornit nimic.")
        config, encrypted = dict(row.config or {}), row.encrypted_secrets
    try:
        secrets = vault.decrypt(encrypted)
    except Exception:  # noqa: BLE001 - an unreadable vault is said, never raised raw
        raise CopyRefused(
            "Cheile conexiunii RunPod nu pot fi citite din seif; nu s-a pornit nimic."
        ) from None
    return RunPodConfig.from_integration(config, secrets)


def _missing(config: RunPodConfig, images: Sequence[str]) -> list[str]:
    missing: list[str] = []
    if config.mock:
        missing.append("conexiunea este o simulare (nu copiază nimic)")
    if not config.api_key.get_secret_value():
        missing.append("cheia API RunPod")
    if config.bucket() is None:
        missing.append("bucketul pentru rezultate")
    if not config.hf_token.get_secret_value():
        missing.append("tokenul Hugging Face (scriere în cele două copii)")
    for image in images:
        if not expected_weights(config, IMAGES[image])[0]:
            what = "imagini" if image == "stills" else "mișcare"
            missing.append(f"numele copiei Hugging Face pentru {what}")
    return missing


def _event(
    session: Session, kind: str, row: CopyPodRow, payload: dict[str, Any], correlation: str
) -> str:
    from app.services import append_event  # noqa: PLC0415 - services imports providers

    event = append_event(session, kind, "runpod_copy_pod", row.id, 1, payload, correlation[:100])
    return str(event.event_id)


def start_copy(
    engine: Engine,
    vault: CredentialVault,
    integration_id: str,
    *,
    max_minutes: int,
    max_usd: str,
    images: Sequence[str] | None = None,
    decision_id: str | None = None,
    decision_inner: str | None = None,
    transport: Transport | None = None,
) -> dict[str, Any]:
    """Start the copy pod his card allowed; CopyRefused (nothing started) otherwise."""
    usd = _decimal(max_usd)
    if usd is None:
        raise CopyRefused("Plafonul în USD din card nu este valid; nu s-a pornit nimic.")
    with Session(engine) as session:
        card = _his_card(
            session,
            integration_id,
            decision_id=decision_id,
            decision_inner=decision_inner,
            max_minutes=int(max_minutes),
            max_usd=usd,
        )
        card_id = str(card.id)
        try:
            _no_second_copy(session, decision_inner)
        except _SameCopy as same:
            return same.answer
    config = _integration(engine, vault, integration_id)
    wanted = list(images or [i for i, p in IMAGES.items() if not expected_weights(config, p)[1]])
    wanted = [image for image in wanted if image in IMAGES] or list(IMAGES)
    missing = _missing(config, wanted)
    if missing:
        raise CopyRefused(
            "Copia nu poate porni; lipsește: " + "; ".join(missing) + ". Completează conexiunea "
            "RunPod în Setări (tokenul Hugging Face este secret și stă în seif) și acceptă "
            "cardul din nou. Nu s-a pornit nimic."
        )
    bucket = config.bucket()
    assert bucket is not None  # _missing checked it
    repos = {image: str(expected_weights(config, IMAGES[image])[0]) for image in wanted}
    copy_id = str(uuid4())
    pod_name = f"{COPY_PREFIX}-{copy_id[:8]}"
    correlation = decision_inner or copy_id
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        # Looked at again under the write lock: two presses at the same moment both passed the
        # first look, and only one of them may write a copy (the other gets that same copy).
        try:
            _no_second_copy(session, decision_inner)
        except _SameCopy as same:
            return same.answer
        session.add(
            CopyPodRow(
                id=copy_id,
                integration_id=integration_id,
                decision_id=card_id,
                decision_inner=decision_inner,
                pod_name=pod_name,
                status=CREATING,
                images=wanted,
                repos=repos,
                max_minutes=int(max_minutes),
                max_usd=f"{usd:.2f}",
                created_at=_now().isoformat(),
            )
        )
    wire = transport or default_transport()
    lifetime = min(s3.MAX_EXPIRES, int(max_minutes) * 60 + 3600)
    not_after = _now().timestamp() + _cap_seconds(config, int(max_minutes), usd)
    try:
        plan = asyncio.run(_plan(config, bucket, copy_id, wanted, repos, lifetime, wire, not_after))
    except (MediaProviderError, ValueError, OSError) as exc:
        _close(engine, copy_id, FAILED, error="UPLOAD_FAILED", verified=True)
        raise CopyRefused(
            "Fișierele pentru serverul de copiere nu au putut fi urcate în bucketul tău; nu s-a "
            "pornit nimic."
        ) from exc
    body = {
        "name": pod_name,
        "image": config.mirror_pod_image,
        "cpu": {"id": config.mirror_pod_cpu_flavor, "vcpuCount": config.mirror_pod_vcpus},
        "disk": config.mirror_pod_disk_gb,
        "env": {
            "HF_TOKEN": config.hf_token.get_secret_value(),
            "AMN_MIRROR_HOST": "pod",
            "AMN_MIRROR_PLAN": json.dumps(plan, separators=(",", ":")),
            "PYTHONUNBUFFERED": "1",
        },
        "cmd": ["python", "-c", BOOTSTRAP],
    }
    if len(json.dumps(body).encode()) > MAX_BODY:
        _close(engine, copy_id, FAILED, error="BODY_TOO_LARGE", verified=True)
        raise CopyRefused("Cererea către RunPod ar fi prea mare; nu s-a pornit nimic.")
    control = PodControl(config, wire)
    try:
        answer = asyncio.run(control.create(body))
    except MediaProviderError as exc:
        proven = exc.unsent or (exc.http_status is not None and 400 <= exc.http_status < 500)
        if proven and not exc.unanswered:
            _close(
                engine, copy_id, FAILED, error=f"CREATE_REFUSED_{exc.http_status}", verified=True
            )
            reason = _vendor_reason(exc, config.hf_token.get_secret_value())
            logger.warning(
                "runpod_mirror_copy_refused",
                extra={"copy_id": copy_id, "http_status": exc.http_status, "reason": reason},
            )
            raise CopyRefused(
                f"RunPod a refuzat serverul de copiere (HTTP {exc.http_status}"
                + (f": {reason}" if reason else "")
                + "); nu s-a pornit nimic."
            ) from None
        # No answer: the pod may exist. The guard finds it by its name and terminates it.
        _close(engine, copy_id, FAILED, error="CREATE_UNCERTAIN", verified=False)
        try:
            asyncio.run(_sweep(control, owned=set()))
        except MediaProviderError:
            pass
        raise CopyRefused(
            "RunPod nu a răspuns la pornirea serverului de copiere; dacă a pornit totuși, "
            "paznicul îl găsește după nume și îl oprește definitiv. Acceptă cardul din nou mai "
            "târziu."
        ) from None
    # A pod still PROVISIONING reads cost 0.0: that is no price, the estimate stands.
    rate = _decimal(answer.get("cost")) or None
    started = _now()
    pod_id = str(answer["id"])[:100]
    event_id: str | None = None
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        row = session.get(CopyPodRow, copy_id)
        assert row is not None
        row.pod_id = pod_id
        stopped_meanwhile = row.status != CREATING
        if not stopped_meanwhile:
            row.status = RUNNING
            event_id = _started(session, row, started, rate, config, pod_name, card_id, correlation)
    if stopped_meanwhile:
        # The studio stopped (or restarted) while RunPod was answering: this pod is ended now,
        # never left to bill until the next start.
        verified = _end_unwanted(engine, control, copy_id, pod_id)
        raise CopyRefused(
            "Studioul s-a oprit chiar în timp ce porneam serverul de copiere; "
            + (
                "l-am oprit definitiv."
                if verified
                else f"oprirea serverului «{pod_name}» nu e confirmată încă: paznicul o "
                "reîncearcă, iar serverul se oprește singur la plafon."
            )
            + " Acceptă cardul din nou când vrei copia."
        )
    logger.info("runpod_mirror_copy_started", extra={"copy_id": copy_id, "images": wanted})
    return {"copy_id": copy_id, "pod_id": pod_id, "event_id": event_id}


def _started(
    session: Session,
    row: CopyPodRow,
    started: datetime,
    rate: Decimal | None,
    config: RunPodConfig,
    pod_name: str,
    card_id: str,
    correlation: str,
) -> str:
    """The copy is RUNNING: its start time, its price and the started event (inside the
    caller's write transaction)."""
    row.started_at = started.isoformat()
    row.rate_usd_per_hour = str(rate if rate is not None else config.mirror_pod_cost_per_hour)
    return _event(
        session,
        "runpod.mirror_copy_started",
        row,
        {
            "pod_id": row.pod_id,
            "pod_name": pod_name,
            "images": list(row.images),
            "repos": dict(row.repos),
            "max_minutes": row.max_minutes,
            "max_usd": row.max_usd,
            "rate_usd_per_hour": row.rate_usd_per_hour,
            "decision_id": card_id,
        },
        correlation,
    )


class _SameCopy(Exception):
    """His accept retried: the answer of the copy it already started."""

    def __init__(self, answer: dict[str, Any]) -> None:
        super().__init__("same copy")
        self.answer = answer


def _no_second_copy(session: Session, decision_inner: str | None) -> None:
    """_SameCopy when this accept already started a copy; CopyRefused while another copy is
    live. Called once on a plain read and again under the write lock, before the insert."""
    if decision_inner:
        earlier = session.scalars(
            select(CopyPodRow).where(CopyPodRow.decision_inner == decision_inner)
        ).first()
        if earlier is not None and earlier.status in (*LIVE, SUCCEEDED):
            # His accept retried after the pod started: the same copy, never a second pod.
            raise _SameCopy({"copy_id": earlier.id, "pod_id": earlier.pod_id, "event_id": None})
    if session.scalars(select(CopyPodRow).where(CopyPodRow.status.in_(LIVE))).first():
        raise CopyRefused("O copie a modelelor rulează deja; nu pornesc a doua.")


def _cap_seconds(config: RunPodConfig, max_minutes: int, max_usd: Decimal) -> float:
    """The pod's own deadline, in seconds from now: the card's time cap or the dollar cap at
    the configured price, whichever comes first, one guard interval early (as the guard)."""
    seconds = float(max_minutes * 60)
    estimate = config.mirror_pod_cost_per_hour
    if estimate > 0:
        seconds = min(seconds, float(max_usd / estimate * 3600))
    return max(60.0, seconds - float(config.guard_interval_seconds))


def _end_unwanted(engine: Engine, control: PodControl, copy_id: str, pod_id: str) -> bool:
    """Terminate a pod whose copy was stopped while RunPod created it; True once confirmed."""
    verified = False
    try:
        verified = asyncio.run(control.terminate(pod_id))
    except MediaProviderError as exc:
        logger.warning(
            "runpod_mirror_terminate_failed",
            extra={"copy_id": copy_id, "http_status": exc.http_status},
        )
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        row = session.get(CopyPodRow, copy_id)
        if row is not None:
            row.terminate_verified = verified
            row.terminated_at = _now().isoformat() if verified else None
    return verified


def _close(
    engine: Engine,
    copy_id: str,
    status: str,
    *,
    error: str | None = None,
    verified: bool | None = None,
    cost: Decimal | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        row = session.get(CopyPodRow, copy_id)
        if row is None:
            return
        row.status = status
        row.error_code = error
        row.finished_at = _now().isoformat()
        row.terminate_verified = verified
        if verified:
            row.terminated_at = row.finished_at
        if cost is not None:
            row.cost_usd = str(cost.quantize(Decimal("0.0001")))
        if result is not None:
            row.result = result


# ------------------------------------------------------------------------------ the watch


async def _sweep(
    control: PodControl, *, owned: set[str], spared: frozenset[str] = frozenset()
) -> tuple[list[str], set[str]]:
    """Terminate every pod the studio named (``amn-mirror-copy-`` + 8 hex digits, never a
    name of his that merely starts alike) that no live copy owns and that is not ``spared``
    (a copy still being created). Returns (pods whose end RunPod confirmed, ids still listed
    as not terminated). One pod RunPod will not end never shields the others."""
    ended: list[str] = []
    alive: set[str] = set()
    for pod in await control.named(COPY_PREFIX):
        pod_id, name = str(pod.get("id") or ""), str(pod.get("name") or "")
        if not pod_id or not COPY_NAME.fullmatch(name) or str(pod.get("status")) == "TERMINATED":
            continue
        alive.add(pod_id)
        if pod_id in owned or name in spared:
            continue
        try:
            confirmed = await control.terminate(pod_id)
        except MediaProviderError as exc:
            logger.warning(
                "runpod_mirror_sweep_terminate_failed",
                extra={"pod_id": pod_id, "http_status": exc.http_status},
            )
            continue
        if confirmed:
            ended.append(pod_id)
            alive.discard(pod_id)
    return ended, alive


def _vendor_reason(exc: MediaProviderError, secret: str) -> str:
    """RunPod's own words for a refused create: its ``detail`` and per-field ``issues``, already
    sanitised by ``media_http``, the token cut once more and capped. Without them a bare
    «HTTP 400» could be a bad field or a full data center (2026-10-09, his first accept)."""
    parts = [str(exc.detail or "").strip()]
    parts += [
        f"{issue.get('path', '')}: {issue.get('message', '')}".strip(": ") for issue in exc.issues
    ]
    text = " · ".join(part for part in parts if part)
    if secret:
        text = text.replace(secret, "[hf_token]")
    return _TOKEN.sub("[hf_token]", " ".join(text.split()))[:300]


def _scrubbed(value: Any, secret: str) -> Any:
    text = json.dumps(value, ensure_ascii=False)
    if secret:
        text = text.replace(secret, "[hf_token]")
    return json.loads(_TOKEN.sub("[hf_token]", text))


async def _results(
    bucket: s3.BucketConfig, row: CopyPodRow, transport: Transport
) -> dict[str, dict[str, Any] | None]:
    found: dict[str, dict[str, Any] | None] = {}
    for image in row.images:
        found[image] = await s3.get_json(
            bucket, result_key(bucket.prefix, row.id, image), transport
        )
    return found


def _verdict(results: dict[str, dict[str, Any] | None]) -> str | None:
    """SUCCEEDED when every image reported a commit, FAILED when one failed, else None."""
    if any(r is not None and (r.get("exit_code") != 0 or r.get("error")) for r in results.values()):
        return FAILED
    if results and all(
        r is not None and isinstance(r.get("commit"), str) and _REVISION.fullmatch(r["commit"])
        for r in results.values()
    ):
        return SUCCEEDED
    return None


def _record_revisions(
    session: Session, row: CopyPodRow, results: dict[str, dict[str, Any] | None]
) -> None:
    from app.integrations.models import Integration  # noqa: PLC0415

    integration = session.get(Integration, row.integration_id)
    if integration is None:
        return
    config = dict(integration.config or {})
    for image, result in results.items():
        if result is None:
            continue
        prefix = "stills" if image == "stills" else "motion"
        config[f"{prefix}_mirror_repo"] = row.repos.get(image)
        config[f"{prefix}_mirror_revision"] = result["commit"]
    integration.config = config
    integration.version += 1


def _console_steps(engine: Engine, integration_id: str) -> str:
    """His console steps after a successful copy (the public config only, no secret read)."""
    from app.integrations.models import Integration  # noqa: PLC0415
    from app.providers.runpod.weights import console_steps_ro  # noqa: PLC0415

    with Session(engine) as session:
        integration = session.get(Integration, integration_id)
        config = dict(integration.config or {}) if integration is not None else None
    if config is None:
        return ""
    steps = console_steps_ro(RunPodConfig.from_integration(config, {}))
    if not steps:
        return ""
    return (
        " Pașii tăi în consola RunPod, o singură dată, înainte de prima generare: "
        + " ".join(f"({n}) {step}" for n, step in enumerate(steps, 1))
        + " Câmpul Model și variabilele nu se pot seta prin API."
    )


def _follow_up(engine: Engine, row: CopyPodRow, status: str, cost: Decimal, verified: bool) -> None:
    """His letter, and on anything but success a fresh card (the same question again). The
    letter says «oprit definitiv» only when RunPod confirmed it; otherwise it names the pod and
    his own Terminate in the console."""
    from app.decisions.sources import (  # noqa: PLC0415
        _own_transaction,
        ask,
        runpod_mirror_copy_card,
    )
    from app.integrations.models import Integration  # noqa: PLC0415
    from app.providers.runpod.gpu_session import owner_letter  # noqa: PLC0415

    why = {
        SUCCEEDED: "Copia modelelor în contul tău Hugging Face este gata",
        FAILED: "Copia modelelor a eșuat",
        TIMED_OUT: "Copia modelelor a atins plafonul de timp",
        OVER_COST: "Copia modelelor a atins plafonul de cost",
        STOPPED: "Copia modelelor s-a oprit la repornirea studioului",
    }[status]
    ended = (
        "Serverul temporar RunPod a fost oprit definitiv"
        if verified
        else f"ATENȚIE: RunPod nu a confirmat încă oprirea serverului temporar «{row.pod_name}»; "
        "paznicul reîncearcă la fiecare trecere și serverul se oprește și singur la plafon. "
        "Dacă îl vezi pornit în consola RunPod (Pods), apasă tu Terminate"
    )
    # The worker reads the pin from each endpoint, not from the studio's settings: on success
    # his letter gives the one-time console steps with the exact values (2026-10-09).
    steps = _console_steps(engine, row.integration_id) if status == SUCCEEDED else ""
    owner_letter(
        engine,
        why,
        f"{why}. {ended}; cost estimat {cost:.2f} USD "
        f"(plafon {row.max_usd} USD, {row.max_minutes} minute).{steps}",
        "runpod_mirror_copy",
        row.id,
    )
    if status == SUCCEEDED:
        return
    stopped = (
        "serverul a fost oprit definitiv"
        if verified
        else f"oprirea serverului «{row.pod_name}» nu e confirmată încă"
    )

    def again(session: Session) -> Any:
        integration = session.get(Integration, row.integration_id)
        if integration is None:
            return None
        card = runpod_mirror_copy_card(
            integration,
            why_ro=f"{why}; {stopped} (cost estimat {cost:.2f} USD). "
            "Copiile nu au revizia scrisă, deci endpoint-urile nu pot genera. Poți porni din "
            "nou copia; fișierele deja urcate pe Hugging Face nu se plătesc a doua oară.",
        )
        return ask(session, source="stage:runpod_copy", **card)

    _own_transaction(engine, "runpod_mirror_copy", again)


def _finish(
    engine: Engine,
    row: CopyPodRow,
    status: str,
    *,
    control: PodControl,
    now: datetime,
    results: dict[str, dict[str, Any] | None] | None,
    secret: str,
    error: str | None = None,
) -> bool:
    """Terminate the pod, book its cost and outcome; True when RunPod confirmed it gone."""
    verified = False
    if row.pod_id:
        try:
            verified = asyncio.run(control.terminate(row.pod_id))
        except MediaProviderError as exc:
            logger.warning(
                "runpod_mirror_terminate_failed",
                extra={"copy_id": row.id, "http_status": exc.http_status},
            )
    started = _when(row.started_at) or _when(row.created_at) or now
    rate = _decimal(row.rate_usd_per_hour) or Decimal(0)
    seconds = max(0.0, (now - started).total_seconds())
    cost = rate * Decimal(str(seconds)) / Decimal(3600)
    kept = _scrubbed(results, secret) if results is not None else None
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        saved = session.get(CopyPodRow, row.id)
        if saved is None:
            return verified
        saved.status = status
        saved.error_code = error
        saved.finished_at = now.isoformat()
        # A pod that never got an id (a create cut short) is left to the sweep by its name.
        saved.terminate_verified = verified
        saved.terminated_at = now.isoformat() if verified else None
        saved.cost_usd = str(cost.quantize(Decimal("0.0001")))
        saved.result = kept
        if status == SUCCEEDED and results is not None:
            _record_revisions(session, saved, results)
        _event(
            session,
            "runpod.mirror_copy_finished",
            saved,
            {
                "status": status,
                "pod_id": saved.pod_id,
                "terminate_verified": saved.terminate_verified,
                "cost_usd": saved.cost_usd,
                "rate_usd_per_hour": saved.rate_usd_per_hour,
                "revisions": {
                    image: (r or {}).get("commit") for image, r in (results or {}).items()
                },
                "error": error,
            },
            saved.decision_inner or saved.id,
        )
    _follow_up(engine, row, status, cost, verified)
    return verified


def live_copy(engine: Engine) -> bool:
    with Session(engine) as session:
        return (
            session.scalars(
                select(CopyPodRow.id).where(CopyPodRow.status.in_(LIVE)).limit(1)
            ).first()
            is not None
        )


def watch_copies(
    engine: Engine,
    vault: CredentialVault,
    *,
    reason: Literal["TICK", "BOOT", "SHUTDOWN"],
    transport: Transport | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """One look at the copy pods (the guard's tick, its boot and the shutdown): see above."""
    moment = now or _now()
    summary: dict[str, Any] = {"terminated": [], "finished": [], "swept": []}
    wire = transport or default_transport()
    with Session(engine) as session:
        rows = list(session.scalars(select(CopyPodRow)))
        for row in rows:
            session.expunge(row)
    if not rows:
        return summary
    configs: dict[str, RunPodConfig] = {}
    for integration_id in {row.integration_id for row in rows}:
        try:
            configs[integration_id] = _integration(engine, vault, integration_id)
        except CopyRefused:
            continue
    spared: set[str] = set()
    for row in rows:
        config = configs.get(row.integration_id)
        if row.status not in LIVE or config is None:
            continue
        control = PodControl(config, wire)
        secret = config.hf_token.get_secret_value()
        if reason == "TICK" and row.status == CREATING and _creating_now(row, moment):
            # Still inside its create (start_copy is uploading or RunPod is answering): a tick
            # neither stops it nor sweeps its pod. BOOT and SHUTDOWN still stop it.
            spared.add(row.pod_name)
            continue
        if reason != "TICK" or row.status == CREATING:
            # A pod that finished on its own while the studio was down left its results in his
            # bucket: they are kept (his revisions recorded), never thrown away as STOPPED.
            ending: tuple[str, dict[str, dict[str, Any] | None] | None, str | None] = (
                STOPPED,
                None,
                None,
            )
            if row.status == RUNNING:
                ending = _reported(config, row, control)
            if _finish(
                engine,
                row,
                ending[0],
                control=control,
                now=moment,
                results=ending[1],
                secret=secret,
                error=ending[2],
            ):
                summary["terminated"].append(row.pod_id)
            continue
        status, results, error = _look(engine, config, row, control, moment)
        if status is None:
            continue
        if _finish(
            engine,
            row,
            status,
            control=control,
            now=moment,
            results=results,
            secret=secret,
            error=error,
        ):
            summary["terminated"].append(row.pod_id)
        summary["finished"].append({"copy_id": row.id, "status": status})
    # Any pod the studio named that no running copy owns is terminated (a create whose answer
    # was lost, a copy of a crashed studio, a terminate RunPod did not carry out): at every boot
    # and shutdown once a copy was ever made, and on a tick while a copy is less than two days
    # old (a cap is one day at most) or while a known pod's end is still unconfirmed.
    recent = moment - timedelta(days=2)
    for integration_id, config in configs.items():
        mine = [r for r in rows if r.integration_id == integration_id]
        unconfirmed = any(r.pod_id and r.terminate_verified is not True for r in mine)
        if (
            reason == "TICK"
            and not unconfirmed
            and not any((_when(r.created_at) or moment) >= recent for r in mine)
        ):
            continue
        with Session(engine) as session:
            owned = {
                str(r.pod_id)
                for r in session.scalars(
                    select(CopyPodRow).where(
                        CopyPodRow.integration_id == integration_id, CopyPodRow.status == RUNNING
                    )
                )
                if r.pod_id
            }
        try:
            swept, alive = asyncio.run(
                _sweep(PodControl(config, wire), owned=owned, spared=frozenset(spared))
            )
        except MediaProviderError as exc:
            logger.warning("runpod_mirror_sweep_failed", extra={"http_status": exc.http_status})
            continue
        summary["swept"] += swept
        _verify_rows(engine, integration_id, alive)
    return summary


def _reported(
    config: RunPodConfig, row: CopyPodRow, control: PodControl
) -> tuple[str, dict[str, dict[str, Any] | None] | None, str | None]:
    """At BOOT or SHUTDOWN: the copy's own verdict when its results already say it, else
    STOPPED."""
    bucket = config.bucket()
    if bucket is None:
        return STOPPED, None, None
    try:
        results = asyncio.run(_results(bucket, row, control.transport))
    except MediaProviderError:
        return STOPPED, None, None
    verdict = _verdict(results)
    if verdict is None:
        return STOPPED, results, None
    return verdict, results, None if verdict == SUCCEEDED else "COPY_FAILED"


def _creating_now(row: CopyPodRow, moment: datetime) -> bool:
    created = _when(row.created_at)
    return created is not None and moment - created < CREATING_GRACE


def _verify_rows(engine: Engine, integration_id: str, alive: set[str]) -> None:
    """After a complete listing: every ended copy whose pod RunPod no longer lists as live is
    confirmed terminated (swept now, or gone already)."""
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        for row in session.scalars(
            select(CopyPodRow).where(
                CopyPodRow.integration_id == integration_id,
                CopyPodRow.pod_id.is_not(None),
                CopyPodRow.status.not_in(LIVE),
            )
        ):
            if row.terminate_verified is not True and row.pod_id not in alive:
                row.terminate_verified = True
                row.terminated_at = row.terminated_at or _now().isoformat()


def _look(
    engine: Engine, config: RunPodConfig, row: CopyPodRow, control: PodControl, now: datetime
) -> tuple[str | None, dict[str, dict[str, Any] | None] | None, str | None]:
    """(the copy's end, its results, an error code) - (None, ...) while it should go on."""
    bucket = config.bucket()
    results: dict[str, dict[str, Any] | None] | None = None
    if bucket is not None:
        try:
            results = asyncio.run(_results(bucket, row, control.transport))
        except MediaProviderError as exc:
            logger.warning("runpod_mirror_results_unread", extra={"http_status": exc.http_status})
    verdict = _verdict(results or {}) if results is not None else None
    if verdict is not None:
        return verdict, results, None if verdict == SUCCEEDED else "COPY_FAILED"
    pod: dict[str, Any] | None = None
    if row.pod_id:
        try:
            pod = asyncio.run(control.get(row.pod_id))
        except MediaProviderError:
            pod = {"status": "UNKNOWN"}
        if pod is None or str(pod.get("status")) in ENDED_POD_STATES:
            return FAILED, results, "POD_ENDED"
        rate = _decimal(pod.get("cost"))
        if rate is not None and rate > 0 and str(rate) != row.rate_usd_per_hour:
            # RunPod's own number replaces the estimate (and a higher one tightens the cap).
            row.rate_usd_per_hour = str(rate)
            with Session(engine) as session, session.begin():
                lock_for_write(session)
                saved = session.get(CopyPodRow, row.id)
                if saved is not None:
                    saved.rate_usd_per_hour = str(rate)
    started = _when(row.started_at) or _when(row.created_at) or now
    elapsed = max(0.0, (now - started).total_seconds())
    # One guard interval ahead: the pod is ended BEFORE a cap, never one tick after it.
    ahead = elapsed + float(config.guard_interval_seconds)
    if ahead >= row.max_minutes * 60:
        return TIMED_OUT, results, "TIME_CAP"
    rate = _decimal(row.rate_usd_per_hour) or config.mirror_pod_cost_per_hour
    cap = _decimal(row.max_usd) or Decimal(0)
    if rate * Decimal(str(ahead)) / Decimal(3600) >= cap:
        return OVER_COST, results, "COST_CAP"
    return None, results, None


__all__ = [
    "BOOTSTRAP",
    "COPY_PREFIX",
    "CopyPodRow",
    "CopyRefused",
    "PodControl",
    "live_copy",
    "start_copy",
    "watch_copies",
]
