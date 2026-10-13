"""Which weights a RunPod worker really loaded, checked from what it reports (2026-10-09).

The Owner's cards: the weights live in RunPod CACHED MODELS, one cached model per endpoint
(stills <- his private Hugging Face mirror of the stills files, motion <- his mirror of the
motion files). RunPod's REST v2 has no field for an endpoint's cached model: it is set only in
the console («Manage → Edit Endpoint → Model»), and the studio cannot read it either. So the
check is on the results: the worker reports ``weights_revision`` (the mirror commit its snapshot
resolved to) and the stable codes ``MODELS_MISSING`` / ``WRONG_REVISION`` when it could not
prepare them (the worker's `runpod_worker.weights`, a separate change).

* What the studio expects is the integration's mirror (his settings; the copy pod writes the
  revision) or else the worker's own pin, backend/runpod_worker/mirrors.lock.json
  (`expected_weights`). A result whose ``weights_revision`` differs from it, or either code, is
  a `WeightsProblem`: the step sends no
  further round, its GPU session closes (workers.max=0), and a card goes to his Decisions window
  saying which endpoint, what is expected and the console step (`raise_weights_card`).
* While that card is open, or he chose to keep the GPU off on it, the endpoint is HELD: a paid
  step refuses before his yes is spent (`weights_hold`). His DONE on the card, or a new expected
  revision (a new copy), releases it.
* A job still IN_QUEUE is a worker RunPod has not started: on a cache miss it waits for the model
  download, unbilled. The GPU switch then says «aștept descărcarea modelului (neplătită)»
  (`note_queue` / `model_wait`).

The cache read speed and the blob naming are UNPROVEN until the paid bake-off measures them.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from app.providers.runpod.config import RunPodConfig

logger = logging.getLogger("studio.runpod")

#: The worker's stable codes for weights it could not prepare (ComfyUI is then never started);
#: MODEL_REVISION_MISMATCH is the research's name for WRONG_REVISION, read as the same.
WEIGHTS_CODES = ("MODELS_MISSING", "WRONG_REVISION", "MODEL_REVISION_MISMATCH")
_CODE = re.compile(r"\b(" + "|".join(WEIGHTS_CODES) + r")\b")
_REVISION = re.compile(r"^[0-9a-f]{40}$")

#: The console step: the cached-model field cannot be set through the API (research 2026-10-09).
CONSOLE_STEP_RO = "Manage → Edit Endpoint → Model"
#: The worker's own pin of the mirror, read from the endpoint's environment (an env change is a
#: RunPod release, so the studio never PATCHes it: his console step, with the exact values).
ENV_STEP_RO = "Manage → Edit Endpoint → Environment Variables"


def endpoint_pin_ro(repo: str | None, revision: str | None) -> str:
    """The two endpoint variables the worker reads its mirror pin from, with their values."""
    return (
        f"AMN_MIRROR_REPO = {repo or '(depozitul copiei tale)'} și "
        f"AMN_MIRROR_REVISION = {revision or '(revizia copiei tale)'}"
    )


#: What the page says while a job waits for RunPod to start a worker (a cache miss).
WAIT_WORDS_RO = "aștept descărcarea modelului (neplătită)"
#: The purposes as he reads them.
PURPOSE_RO = {"image": "imagini", "video": "clipuri"}


@dataclass(frozen=True)
class WeightsProblem:
    """A result that proves the endpoint's weights are not the ones the studio expects."""

    purpose: Literal["image", "video"]
    endpoint_id: str | None
    code: str
    expected_repo: str | None
    expected_revision: str | None
    reported_revision: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def words_ro(self) -> str:
        where = f"endpoint-ul RunPod pentru {PURPOSE_RO[self.purpose]} ({self.endpoint_id})"
        expected = (
            f"copia ta {self.expected_repo or '(nesetată)'} la revizia "
            f"{(self.expected_revision or 'nesetată')[:12]}"
        )
        if self.code == "MODELS_MISSING":
            found = "lucrătorul nu a găsit modelele în cache"
        elif self.reported_revision:
            found = f"lucrătorul a încărcat revizia {self.reported_revision[:12]}"
        else:
            found = "lucrătorul a încărcat altă revizie decât cea așteptată"
        return (
            f"Modelele de pe {where} nu sunt cele așteptate: {found}, iar studioul așteaptă "
            f"{expected}. Nu mai trimit nicio rundă pe acest endpoint și GPU-ul s-a oprit. "
            f"Pasul tău în consola RunPod: endpoint-ul {self.endpoint_id} → «{CONSOLE_STEP_RO}» "
            "→ alege copia ta de pe Hugging Face (câmpul nu se poate seta prin API), apoi la "
            f"«{ENV_STEP_RO}» pune "
            f"{endpoint_pin_ro(self.expected_repo, self.expected_revision)}."
        )


#: The worker's own pin of each mirror (baked into its small image).
MIRRORS_LOCK = Path(__file__).resolve().parents[3] / "runpod_worker" / "mirrors.lock.json"
IMAGE_OF = {"image": "stills", "video": "motion"}


@lru_cache(maxsize=4)
def _worker_pins(path: str) -> dict[str, tuple[str | None, str | None]]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    pins: dict[str, tuple[str | None, str | None]] = {}
    for image in ("stills", "motion"):
        entry = data.get(image) if isinstance(data, dict) else None
        entry = entry if isinstance(entry, dict) else {}
        repo, revision = entry.get("repo"), entry.get("revision")
        pins[image] = (
            repo if isinstance(repo, str) and repo else None,
            revision if isinstance(revision, str) and _REVISION.fullmatch(revision) else None,
        )
    return pins


def expected_weights(
    config: RunPodConfig, purpose: Literal["image", "video"]
) -> tuple[str | None, str | None]:
    """(his mirror repo, the revision its workers must report): his settings first (the copy
    pod writes them), else the worker image's own pin (mirrors.lock.json)."""
    repo, revision = config.mirror_for(purpose)
    pinned_repo, pinned_revision = _worker_pins(str(MIRRORS_LOCK)).get(
        IMAGE_OF[purpose], (None, None)
    )
    if repo is None:
        return pinned_repo, revision or pinned_revision
    return repo, revision or (pinned_revision if pinned_repo == repo else None)


def console_steps_ro(config: RunPodConfig) -> list[str]:
    """His one-time console steps after a copy: per endpoint whose mirror is known, the Model
    field (no API for it) and the env pin the worker reads (an env change is a release)."""
    steps: list[str] = []
    for purpose in ("image", "video"):
        endpoint_id = config.endpoint_for(purpose)  # type: ignore[arg-type]
        repo, revision = expected_weights(config, purpose)  # type: ignore[arg-type]
        if not (endpoint_id and repo and revision):
            continue
        steps.append(
            f"Endpoint-ul {endpoint_id} ({PURPOSE_RO[purpose]}): «{CONSOLE_STEP_RO}» = {repo} "
            f"(cu tokenul tău Hugging Face de citire); la «{ENV_STEP_RO}»: "
            f"{endpoint_pin_ro(repo, revision)}; salvează."
        )
    return steps


def readiness_problem(config: RunPodConfig, purpose: Literal["image", "video"]) -> str | None:
    """Why a paid step on this endpoint cannot be sent yet, or None. Under the cached-model
    source the endpoint reads his mirror: until its repo and revision are known (the copy pod
    writes them), a round would only buy a worker that fails to find its models."""
    if config.mock or config.model_source != "cache":
        return None
    repo, revision = expected_weights(config, purpose)
    if repo and revision:
        return None
    what = "imaginilor" if purpose == "image" else "clipurilor"
    return (
        f"Modelele {what} nu sunt încă copiate în contul tău Hugging Face (lipsește "
        f"{'depozitul' if not repo else 'revizia'} copiei), iar endpoint-ul RunPod le citește "
        "din cache-ul acelei copii: GPU-ul nu se pornește și nu se cumpără nimic. Cardul "
        "«Copiez modelele în contul tău Hugging Face …» din fereastra Decizii o face."
    )


def reported_revision(raw: Mapping[str, Any] | None) -> str | None:
    value = (raw or {}).get("weights_revision")
    return value if isinstance(value, str) and _REVISION.fullmatch(value) else None


def _code(error: Any) -> str | None:
    if not isinstance(error, str):
        return None
    found = _CODE.search(error)
    return found.group(1) if found else None


def check_result(
    config: RunPodConfig,
    purpose: Literal["image", "video"],
    raw: Mapping[str, Any] | None,
    *,
    error: Any = None,
) -> WeightsProblem | None:
    """One result (a job output, an item, a manifest) or a job error, checked. A worker that
    reports no revision is not called wrong (an old worker); a simulation is never checked."""
    if config.mock:
        return None
    repo, expected = expected_weights(config, purpose)
    endpoint_id = config.endpoint_for(purpose)
    code = _code(error) or _code((raw or {}).get("error"))
    reported = reported_revision(raw)
    if code is None and (
        config.model_source == "cache" and expected and reported and reported != expected
    ):
        code = "WRONG_REVISION"
    if code is None:
        return None
    return WeightsProblem(
        purpose=purpose,
        endpoint_id=endpoint_id,
        code=code,
        expected_repo=repo,
        expected_revision=expected,
        reported_revision=reported,
    )


# ---------------------------------------------------------------------- his card, the hold


def weights_key(integration_id: str | None, purpose: str) -> str:
    return f"runpod_weights:{integration_id or 'env'}:{purpose}"


def raise_weights_card(engine: Engine, problem: WeightsProblem, integration_id: str | None) -> None:
    """Put the card in his Decisions window (one open card per endpoint purpose)."""
    from app.decisions.sources import (  # noqa: PLC0415 - decisions read providers
        _own_transaction,
        ask,
        runpod_weights_card,
    )

    card = runpod_weights_card(problem, integration_id)
    _own_transaction(
        engine, "runpod_weights", lambda session: ask(session, source="stage:runpod", **card)
    )


def _holding(card: Any, expected: str | None) -> bool:
    from app.decisions.models import OPEN_STATUSES  # noqa: PLC0415

    applied = card.applied if isinstance(card.applied, dict) else {}
    kept_off = card.status == "REFUSED" or (
        card.status == "ACCEPTED" and applied.get("type") == "none"
    )
    if card.status not in OPEN_STATUSES and not kept_off:
        return False
    params = card.clears_when if isinstance(card.clears_when, dict) else {}
    # A new expected revision (a new copy) is a new question: the old card no longer holds.
    return params.get("expected_revision") == expected


def weights_hold(
    engine: Engine,
    integration_id: str | None,
    purpose: Literal["image", "video"],
    config: RunPodConfig,
) -> str | None:
    """His words when the endpoint is held by a weights card, else None."""
    from app.decisions.models import OwnerDecision  # noqa: PLC0415

    _repo, expected = expected_weights(config, purpose)
    with Session(engine) as session:
        card = session.scalars(
            select(OwnerDecision)
            .where(OwnerDecision.dedupe_key == weights_key(integration_id, purpose))
            .order_by(OwnerDecision.created_at.desc())
            .limit(1)
        ).first()
        if card is None or not _holding(card, expected):
            return None
        return (
            "Endpoint-ul RunPod are alte modele decât cele așteptate (cardul din fereastra "
            f"Decizii): pasul tău este «{CONSOLE_STEP_RO}» în consola RunPod, apoi «Am făcut-o» "
            "pe card. GPU-ul nu se pornește până atunci."
        )


# ------------------------------------------------------------------------ the unbilled wait

_WAITS_GUARD = threading.Lock()
#: endpoint_id -> (monotonic since, notice seconds)
_WAITS: dict[str, tuple[float, int]] = {}


def note_queue(endpoint_id: str, *, since: float, notice_seconds: int) -> None:
    """A job of this endpoint is still IN_QUEUE (RunPod has not started its worker)."""
    with _WAITS_GUARD:
        known = _WAITS.get(endpoint_id)
        start = min(since, known[0]) if known else since
        _WAITS[endpoint_id] = (start, int(notice_seconds))


def clear_queue(endpoint_id: str) -> None:
    with _WAITS_GUARD:
        _WAITS.pop(endpoint_id, None)


def forget_waits() -> None:
    with _WAITS_GUARD:
        _WAITS.clear()


def model_wait(endpoint_id: str) -> str | None:
    """«aștept descărcarea modelului (neplătită)» once a job waited past the notice."""
    with _WAITS_GUARD:
        known = _WAITS.get(endpoint_id)
    if known is None:
        return None
    since, notice = known
    return WAIT_WORDS_RO if time.monotonic() - since >= notice else None
