"""Runway video generation adapter.

Uses the documented REST API at https://docs.dev.runwayml.com/ (API version 2024-11-06):

  GET  /v1/organization     -> credit balance, and per-model tier limits and usage for this key
  POST /v1/text_to_image    -> a still from a prompt, and from the pictures it is given
  POST /v1/text_to_video    -> a generation task from a prompt
  POST /v1/image_to_video   -> a generation task from a first frame and a prompt
  GET  /v1/tasks/{id}       -> task status and, once finished, the output URLs

Runway has no model-listing endpoint. The models this account may call are the keys of
``tier.models`` in the organization response. Which task endpoint each model serves, and the
ratios and durations it accepts, come from the vendor's published OpenAPI contract for the
same API version (``https://docs.dev.runwayml.com/openapi.json``). No model name, ratio or
duration is written in this file: a model the account gains or loses appears or disappears at
the next catalog refresh, and a model whose contract changed is generated with the new terms.
"""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import math
import re
import time
from collections.abc import Callable, Iterator, Sequence
from typing import Any
from urllib.parse import quote, urlsplit

from app.providers.media_base import (
    ImageProvider,
    ImageResult,
    VideoGenerationResult,
    VideoProvider,
)
from app.providers.media_http import (
    MediaProviderError,
    MediaProviderNotConfigured,
    TaskStillOpen,
    image_dimensions,
    request,
    retrying,
    sanitise_vendor_text,
)
from app.wording import settings_place

HOST = "api.dev.runwayml.com"
DOCS_HOST = "docs.dev.runwayml.com"
CONTRACT_PATH = "/openapi.json"
API_VERSION = "2024-11-06"

#: Task endpoints whose output is a video clip. Endpoint names are part of the API contract
#: (the paths above), not model names; a model serves a task only if the contract says so.
VIDEO_TASKS = ("text_to_video", "image_to_video", "video_to_video", "character_performance")
#: Task endpoints whose output is a still image.
IMAGE_TASKS = ("text_to_image",)
#: How long a still may take. Runway queues tasks; polling stops at the deadline, and a task
#: still running then is reported as such rather than waited for indefinitely.
IMAGE_DEADLINE_SECONDS = 240
IMAGE_POLL_SECONDS = 3.0

#: Host suffixes a task's output may be downloaded from. Runway's docs
#: (https://docs.dev.runwayml.com/assets/outputs/, read 2026-10-01) show one example output
#: URL on a CloudFront host but publish no list of output domains, and pinning a domain read
#: off an example would refuse - and so lose - a paid output the day the vendor serves it
#: elsewhere. So the tuple is empty (no suffix is required) and what is enforced is that the
#: address is public: `_vet_output_host` before any socket, and `public_only` at the
#: connection. A domain the vendor documents later goes here.
OUTPUT_HOST_SUFFIXES: tuple[str, ...] = ()
#: Names that are private by definition (RFC 6761, RFC 6762, RFC 8375 and the common
#: internal-only conventions): refused without asking any resolver.
PRIVATE_NAME_SUFFIXES: tuple[str, ...] = (
    "localhost",
    "local",
    "internal",
    "intranet",
    "lan",
    "home.arpa",
    "corp",
    "private",
    "invalid",
)

#: Runway task states -> the studio's VideoGenerationResult states.
TASK_STATES = {
    "PENDING": "PENDING",
    "THROTTLED": "PENDING",
    "RUNNING": "PROCESSING",
    "SUCCEEDED": "COMPLETED",
    "FAILED": "FAILED",
    "CANCELLED": "FAILED",
}

#: The prompt length a task takes when its contract states none (the API's documented cap
#: for promptText), in UTF-16 code units, which is how the vendor counts.
DEFAULT_PROMPT_MAX = 1000
#: A duration within this much of a whole second is that second. Float noise in a span
#: (5.0000001 s) must not buy the next legal length.
DURATION_TOLERANCE_SECONDS = 1e-3
#: `auto_1080p`: the vendor keeps the first frame's own ratio at that resolution.
_AUTO_RATIO = re.compile(r"^auto(?:_(\d+)p)?$")


def estimated_credits(value: Any) -> float | None:
    """The credits in a Runway `estimatedCost`, or None when it states none.

    The contract's shape is ``{"credits": n}``; a bare number is still read. Anything else
    (absent, a string, a boolean) is unknown, never 0: a price nobody stated is not free.
    """
    if isinstance(value, dict):
        value = value.get("credits")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if not math.isfinite(float(value)) or value < 0:
        return None
    return float(value)


def _utf16_units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def fit_prompt(text: str, limit: int) -> str:
    """The prompt on one line, within `limit` UTF-16 units, cut at a sentence if it must be.

    A prompt sliced at a character count ends mid-word, and the model reads the fragment
    as an instruction. Cut at the last sentence end that fits; with none, at the last whole
    word; only a single word longer than the cap is cut inside itself.
    """
    words = " ".join(str(text).split())
    if limit <= 0:
        return ""
    if _utf16_units(words) <= limit:
        return words
    used = 0
    end = 0
    for index, char in enumerate(words):
        used += _utf16_units(char)
        if used > limit:
            break
        end = index + 1
    head = words[:end]
    sentence_end = max(
        (
            i + 1
            for i, char in enumerate(head)
            if char in ".!?" and words[i + 1 : i + 2] in ("", " ")
        ),
        default=0,
    )
    if sentence_end:
        return head[:sentence_end]
    if words[end : end + 1] == " ":
        return head.rstrip()
    if " " in head:
        return head.rsplit(" ", 1)[0].rstrip(" ,;:")
    return head


def _deref(spec: dict, node: Any) -> Any:
    """Follow ``$ref`` pointers in the document; a cycle or a bad pointer is a contract error."""
    for _ in range(32):
        if not isinstance(node, dict) or "$ref" not in node:
            return node
        cursor: Any = spec
        for part in str(node["$ref"]).lstrip("#/").split("/"):
            if not isinstance(cursor, dict) or part not in cursor:
                raise MediaProviderError("Runway's API contract has an unresolved reference")
            cursor = cursor[part]
        node = cursor
    raise MediaProviderError("Runway's API contract references itself without end")


def _branches(spec: dict, schema: Any, depth: int = 0) -> Iterator[dict[str, Any]]:
    """Yield every concrete request shape of a schema (its oneOf/anyOf alternatives)."""
    schema = _deref(spec, schema)
    if not isinstance(schema, dict) or depth > 8:
        return
    alternatives = [s for key in ("oneOf", "anyOf") for s in schema.get(key, [])]
    if alternatives:
        for alternative in alternatives:
            yield from _branches(spec, alternative, depth + 1)
        return
    if "allOf" in schema:
        merged: dict[str, Any] = {}
        for part in schema["allOf"]:
            for branch in _branches(spec, part, depth + 1):
                merged.update(branch.get("properties", {}))
        yield {"properties": merged}
        return
    if isinstance(schema.get("properties"), dict):
        yield schema


def _values(spec: dict, node: Any) -> list[Any]:
    node = _deref(spec, node)
    if not isinstance(node, dict):
        return []
    if "const" in node:
        return [node["const"]]
    if isinstance(node.get("enum"), list):
        return list(node["enum"])
    return [v for key in ("oneOf", "anyOf") for s in node.get(key, []) for v in _values(spec, s)]


def _bounds(spec: dict, node: Any, depth: int = 0) -> dict[str, float]:
    """{"min", "max"} of a numeric schema, looking inside its oneOf/anyOf alternatives.

    The newer models publish `duration` as ``anyOf: [{integer, minimum, maximum}, null]``;
    read only at the top, the bounds were lost and the request fell back to a guess.
    """
    node = _deref(spec, node)
    if not isinstance(node, dict) or depth > 8:
        return {}
    lows: list[float] = []
    highs: list[float] = []
    if isinstance(node.get("minimum"), int | float):
        lows.append(node["minimum"])
    if isinstance(node.get("maximum"), int | float):
        highs.append(node["maximum"])
    for key in ("oneOf", "anyOf", "allOf"):
        for alternative in node.get(key, []) or []:
            inner = _bounds(spec, alternative, depth + 1)
            if "min" in inner:
                lows.append(inner["min"])
            if "max" in inner:
                highs.append(inner["max"])
    bounds: dict[str, float] = {}
    if lows:
        bounds["min"] = min(lows)
    if highs:
        bounds["max"] = max(highs)
    return bounds


def _max_length(spec: dict, node: Any, depth: int = 0) -> int | None:
    """The largest `maxLength` a string schema allows, inside its alternatives too."""
    node = _deref(spec, node)
    if not isinstance(node, dict) or depth > 8:
        return None
    found = [node["maxLength"]] if isinstance(node.get("maxLength"), int) else []
    for key in ("oneOf", "anyOf", "allOf"):
        for alternative in node.get(key, []) or []:
            inner = _max_length(spec, alternative, depth + 1)
            if inner is not None:
                found.append(inner)
    return max(found) if found else None


def parse_model_contract(spec: Any) -> dict[str, dict[str, Any]]:
    """Which task endpoint accepts each model, and the ratios and durations it takes.

    Read from the OpenAPI document Runway publishes for the API version the adapter sends.
    Only single-segment ``/v1/{task}`` POST endpoints count as tasks; per model the result is
    ``{"tasks": [...], "ratios": {task: [...]}, "durations": {task: [...] | {"min","max"}}}``.
    """
    if not isinstance(spec, dict) or not isinstance(spec.get("paths"), dict):
        raise MediaProviderError("Runway's API contract could not be read")
    contract: dict[str, dict[str, Any]] = {}
    for path, operations in spec["paths"].items():
        if not isinstance(path, str) or not path.startswith("/v1/") or path.count("/") != 2:
            continue
        post = operations.get("post") if isinstance(operations, dict) else None
        if not isinstance(post, dict):
            continue
        content = post.get("requestBody", {}).get("content", {}).get("application/json", {})
        if not isinstance(content, dict) or "schema" not in content:
            continue
        task = path[len("/v1/") :]
        for branch in _branches(spec, content["schema"]):
            properties = branch.get("properties", {})
            if not isinstance(properties, dict) or "model" not in properties:
                continue
            models = [m for m in _values(spec, properties["model"]) if isinstance(m, str) and m]
            if not models:
                continue
            ratios = [r for r in _values(spec, properties.get("ratio")) if isinstance(r, str)]
            duration_node = _deref(spec, properties.get("duration"))
            durations: Any = [
                d
                for d in _values(spec, duration_node)
                if isinstance(d, int | float) and not isinstance(d, bool)
            ]
            if durations:
                durations = sorted(set(durations))
            else:
                durations = _bounds(spec, duration_node) or None
            prompt_max = _max_length(spec, properties.get("promptText"))
            # What the model must be given besides words. gen4_image_turbo lists
            # referenceImages as required: an editing model, not a text-to-image one, and a
            # studio that generates stills from a prompt alone cannot use it — a fact the
            # contract states per model, and the choice of a model has to read.
            required = branch.get("required")
            needs_references = isinstance(required, list) and "referenceImages" in required
            # Whether this task can be asked what it would cost without being asked to do
            # it. Only the vendor's own contract may say so: sending a flag the API does
            # not declare risks submitting a real, billed task by accident.
            dry_run = any(str(name).lower() == "dryrun" for name in properties)
            for model in models:
                entry = contract.setdefault(
                    model,
                    {
                        "tasks": [],
                        "ratios": {},
                        "durations": {},
                        "needs_references": {},
                        "dry_run": {},
                    },
                )
                if task not in entry["tasks"]:
                    entry["tasks"].append(task)
                if ratios:
                    entry["ratios"][task] = sorted(set(ratios) | set(entry["ratios"].get(task, [])))
                if durations and task not in entry["durations"]:
                    entry["durations"][task] = durations
                entry.setdefault("needs_references", {})[task] = needs_references
                entry.setdefault("dry_run", {})[task] = dry_run
                # The fields this task declares. An optional one (audio, negativePrompt,
                # seed) is sent only to a model whose contract takes it: an undeclared
                # field is a refusal at best, and at worst read some other way.
                declared = set(entry.setdefault("fields", {}).get(task, []))
                entry["fields"][task] = sorted(declared | {str(name) for name in properties})
                if prompt_max is not None:
                    entry.setdefault("prompt_max", {})[task] = prompt_max
    for entry in contract.values():
        entry["tasks"].sort()
    return contract


def pick_ratio(ratios: list[str] | None, aspect_ratio: str, *, follows_image: bool = False) -> str:
    """The contract ratio closest to the requested aspect ("9:16", "16:9", "1:1").

    Among ratios of the same aspect the largest wins (1080:1920 over 720:1280). With a first
    frame (`follows_image`), an ``auto_<N>p`` ratio keeps the frame's own framing at N; it
    is chosen when no explicit ratio of the wanted aspect reaches that resolution — wan
    offers 9:16 only at 720p explicitly, and ``auto_1080p`` at 1080p.
    """
    if not ratios:
        raise MediaProviderError(
            "The ratios this Runway model accepts are not known; refresh the catalog first"
        )
    try:
        w, h = (float(part) for part in str(aspect_ratio).replace("x", ":").split(":", 1))
        wanted = w / h
    except (ValueError, ZeroDivisionError):
        raise MediaProviderError(f"Unrecognised aspect ratio {aspect_ratio!r}") from None
    scored: list[tuple[float, float, str]] = []
    autos: list[tuple[int, str]] = []
    for ratio in ratios:
        auto = _AUTO_RATIO.match(str(ratio))
        if auto:
            autos.append((int(auto.group(1) or 1), str(ratio)))
            continue
        try:
            rw, rh = (float(part) for part in ratio.split(":", 1))
            scored.append((round(abs(rw / rh - wanted), 3), -min(rw, rh), ratio))
        except (ValueError, ZeroDivisionError):
            continue
    best = min(scored) if scored else None
    if follows_image and autos:
        exact_side = -best[1] if best is not None and best[0] <= 0.01 else 0
        side, auto_ratio = max(autos)
        if side > exact_side:
            return auto_ratio
    if best is None:
        raise MediaProviderError("The Runway contract lists no usable ratios for this model")
    return best[2]


def pick_duration(durations: Any, seconds: float) -> int:
    """The shortest legal duration that covers the request: rounded UP, never down.

    A clip shorter than its span freezes on its last frame under the next dissolve (the
    Nepal film: 4.4 s bought as 4). The assembler trims a longer clip; it never pads one.
    Above the longest legal duration, the longest; below the shortest, the shortest.
    """
    wanted = max(1, math.ceil(float(seconds) - DURATION_TOLERANCE_SECONDS))
    if isinstance(durations, list) and durations:
        legal = sorted(int(d) for d in durations)
        covering = [d for d in legal if d >= wanted]
        return covering[0] if covering else legal[-1]
    if isinstance(durations, dict):
        low = durations.get("min")
        high = durations.get("max")
        if isinstance(low, int | float):
            wanted = max(wanted, math.ceil(low))
        if isinstance(high, int | float):
            wanted = min(wanted, math.floor(high))
    return wanted


#: Runway refuses a picture sent inside a request whose data URI passes 5 MB: "Data URI is too
#: large: 8.6MB exceeds the 5MB limit" (the Owner's sheet, 2026-10-03, a 2K still sent as the
#: film's reference). A picture whose URI stays under the first figure goes as it is; a larger
#: one is re-encoded to JPEG, smaller if it must be, until its URI is under the second.
DATA_URI_SAFE_CHARS = 4_500_000
DATA_URI_TARGET_CHARS = 3_500_000
#: JPEG qualities tried in turn; after each one that is still too large the picture is scaled
#: to 80 % of its sides. A reference carries light, palette and faces, not fine grain.
_FIT_QUALITIES = (92, 90, 88, 85, 82, 80)


def _image_mime(image: bytes, what: str) -> str:
    if image[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        return "image/webp"
    raise MediaProviderError(f"The {what} must be a PNG, JPEG or WebP image")


def _uri_chars(size: int, mime: str) -> int:
    """The length of the data URI of ``size`` bytes of ``mime`` (base64: 4 per 3, padded)."""
    return len(f"data:{mime};base64,") + 4 * ((size + 2) // 3)


def fit_request_image(image: bytes, what: str = "picture") -> bytes:
    """The picture as it can travel inside a Runway request: itself when it fits, else the
    same picture re-encoded to JPEG (and scaled down, keeping its proportions) under
    ``DATA_URI_TARGET_CHARS``. A picture too large that cannot be read is refused here, before
    the request is sent and before anything is paid."""
    mime = _image_mime(image, what)
    if _uri_chars(len(image), mime) <= DATA_URI_SAFE_CHARS:
        return image
    import cv2  # noqa: PLC0415 - only a picture too large to send needs the decoder
    import numpy as np  # noqa: PLC0415

    picture = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_COLOR)
    if picture is None:
        raise MediaProviderError(
            f"The {what} is too large to send to Runway (over 5 MB inside the request) and "
            "could not be read to make it smaller"
        )
    for quality in _FIT_QUALITIES:
        ok, encoded = cv2.imencode(".jpg", picture, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if ok and _uri_chars(len(encoded), "image/jpeg") <= DATA_URI_TARGET_CHARS:
            return bytes(encoded.tobytes())
        height, width = picture.shape[:2]
        picture = cv2.resize(
            picture,
            (max(1, round(width * 0.8)), max(1, round(height * 0.8))),
            interpolation=cv2.INTER_AREA,
        )
    raise MediaProviderError(
        f"The {what} could not be made small enough to send to Runway (5 MB inside the request)"
    )


def _image_data_uri(image: bytes, what: str = "first frame") -> str:
    fitted = fit_request_image(image, what)
    return f"data:{_image_mime(fitted, what)};base64," + base64.b64encode(fitted).decode("ascii")


def _reference_image(extra: dict[str, Any] | None) -> bytes | None:
    """The reference picture the caller handed over, as bytes.

    A path, an asset id or a description is refused here rather than submitted: Runway would
    answer 400 for the whole task, and the studio would have told the Owner it was drawing
    the character from their sheet while it was drawing them from the words.
    """
    reference = (extra or {}).get("reference_image")
    if not reference:
        return None
    if not isinstance(reference, dict):
        raise MediaProviderError("The reference image must be given as bytes, not as a name")
    payload = reference.get("bytes")
    if not isinstance(payload, bytes | bytearray) or not payload:
        raise MediaProviderError("The reference image must be given as bytes, not as a name")
    return bytes(payload)


def _vet_output_host(hostname: str) -> str:
    """The output host, if it may be asked at all; MediaProviderError before any socket if not.

    No headers go to an output host (the key never leaves for it), but a confused or
    compromised answer could still point the studio at an address inside the Owner's
    network. Refused here without a lookup: an IP literal that is not global, a single-label
    name and a private-use name. The resolved addresses are checked at the connection.
    """
    host = hostname.strip().rstrip(".").lower()
    try:
        literal = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        literal = None
    if literal is not None:
        if not literal.is_global:
            raise MediaProviderError("Runway named an output on a private address; not fetched")
        return host
    if "." not in host or any(
        host == suffix or host.endswith("." + suffix) for suffix in PRIVATE_NAME_SUFFIXES
    ):
        raise MediaProviderError("Runway named an output on a private host; not fetched")
    if OUTPUT_HOST_SUFFIXES and not any(
        host == suffix or host.endswith("." + suffix) for suffix in OUTPUT_HOST_SUFFIXES
    ):
        raise MediaProviderError("Runway named an output outside its documented hosts")
    return host


class _RunwayClient:
    """What every Runway adapter shares: the key, the model's contract, the task plumbing."""

    PROVIDER_NAME = "RUNWAY"
    ADAPTER_VERSION = "1.0.0"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        model_metadata: dict[str, Any] | None = None,
    ) -> None:
        if not api_key:
            raise MediaProviderNotConfigured("Runway needs an API key")
        self.api_key = api_key
        self.model = model or ""
        #: The discovered contract for `model` (tasks, ratios, durations), from the catalog.
        self.model_metadata: dict[str, Any] = dict(model_metadata or {})
        #: Set by list_models() when the account answered but the contract could not be read.
        self.capabilities_warning: str | None = None
        #: The credits the vendor said the last submitted task may cost, when it said. Reset
        #: at every submit: a task the vendor priced at nothing is unknown, never the price
        #: of the shot before it.
        self.last_estimated_credits: float | None = None
        #: The id of the last task this adapter submitted; a poll of that task may carry
        #: the price the submit answer left out.
        self.last_task_id: str | None = None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": "Bearer " + self.api_key,
            "X-Runway-Version": API_VERSION,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _require_task(self, task: str) -> None:
        if not self.model:
            raise MediaProviderNotConfigured(
                f"Niciun model Runway ales; alege unul în {settings_place('media')}"
            )
        tasks = self.model_metadata.get("tasks")
        if isinstance(tasks, list) and task not in tasks:
            raise MediaProviderError(
                f"Model {self.model} does not serve {task} according to Runway's contract"
            )

    def _ratio_for(self, task: str, aspect_ratio: str, *, follows_image: bool = False) -> str:
        ratios = self.model_metadata.get("ratios", {})
        return pick_ratio(
            ratios.get(task) if isinstance(ratios, dict) else None,
            aspect_ratio,
            follows_image=follows_image,
        )

    def _fields(self, task: str) -> set[str] | None:
        """The fields the contract says `task` takes for this model, or None if unknown."""
        fields = self.model_metadata.get("fields")
        declared = fields.get(task) if isinstance(fields, dict) else None
        return {str(f) for f in declared} if isinstance(declared, list) else None

    def _prompt_max(self, task: str) -> int:
        limits = self.model_metadata.get("prompt_max")
        limit = limits.get(task) if isinstance(limits, dict) else None
        return limit if isinstance(limit, int) and limit > 0 else DEFAULT_PROMPT_MAX

    async def organization(self) -> dict[str, Any]:
        data, _, _ = await asyncio.to_thread(
            retrying, request, HOST, "GET", "/v1/organization", self._headers(), timeout=20
        )
        if not isinstance(data, dict) or not isinstance(data.get("tier"), dict):
            raise MediaProviderError("Runway did not describe the organization")
        return data

    async def credit_balance(self) -> float | None:
        """The credits the account holds now, read from GET /v1/organization.

        A free read: it buys nothing and is asked before every paid step and every shot. A
        balance the vendor did not state is None, never 0; a vendor that cannot answer
        raises, and the caller that was about to buy stops.
        """
        data = await self.organization()
        return estimated_credits(data.get("creditBalance"))

    async def _submit(self, task: str, body: dict[str, Any]) -> str:
        self.last_estimated_credits = None
        self.last_task_id = None
        data, _, _ = await asyncio.to_thread(
            retrying,
            request,
            HOST,
            "POST",
            f"/v1/{task}",
            self._headers(),
            json.dumps(body).encode("utf-8"),
            timeout=60,
        )
        # Runway answers a new task with the most it may charge, as {"credits": n}. It is
        # the only number the vendor states about the money, so it is kept for the books
        # rather than dropped in favour of a price someone wrote down elsewhere. Read as a
        # bare number only, it was lost: the Nepal film's books showed 0.74 USD for two
        # whole films.
        if isinstance(data, dict):
            self.last_estimated_credits = estimated_credits(data.get("estimatedCost"))
        task_id = data.get("id") if isinstance(data, dict) else None
        if not isinstance(task_id, str) or not task_id:
            raise MediaProviderError("Runway did not return a task id")
        self.last_task_id = task_id
        return task_id

    async def _quote(self, task: str, body: dict[str, Any]) -> float | None:
        """What the vendor says this task would cost, without generating anything.

        Only asked when the vendor's published contract declares that the task accepts a
        dry run. The answer is in credits — the only number the vendor states about money —
        and a vendor that answers with a task id anyway has it cancelled at once, because a
        question about a price must never become a purchase.
        """
        declared = self.model_metadata.get("dry_run")
        if not isinstance(declared, dict) or not declared.get(task):
            return None
        try:
            data, _, _ = await asyncio.to_thread(
                retrying,
                request,
                HOST,
                "POST",
                f"/v1/{task}",
                self._headers(),
                json.dumps({**body, "dryRun": True}).encode("utf-8"),
                timeout=60,
            )
        except MediaProviderError:
            # A refused question costs nothing and teaches nothing; the studio keeps the
            # price it measured.
            return None
        if not isinstance(data, dict):
            return None
        started = data.get("id")
        if isinstance(started, str) and started:
            await self._cancel(started)
        return estimated_credits(data.get("estimatedCost"))

    async def _cancel(self, job_id: str) -> None:
        """Cancel a task. Used when a dry run created one anyway; failure is logged, not raised."""
        try:
            await asyncio.to_thread(
                retrying,
                request,
                HOST,
                "DELETE",
                f"/v1/tasks/{quote(job_id, safe='')}",
                self._headers(),
                timeout=30,
                expect_json=False,
            )
        except MediaProviderError:
            return

    async def _task(self, job_id: str) -> dict[str, Any]:
        data, _, _ = await asyncio.to_thread(
            retrying,
            request,
            HOST,
            "GET",
            f"/v1/tasks/{quote(job_id, safe='')}",
            self._headers(),
            timeout=30,
        )
        if not isinstance(data, dict) or not isinstance(data.get("status"), str):
            raise MediaProviderError("Runway did not return the task status")
        # The submit answer may leave the price out; the task states it while it waits.
        # Only the task this adapter last submitted may set it: a poll of an older task is
        # about another shot's money.
        if job_id == self.last_task_id:
            credits = estimated_credits(data.get("estimatedCost"))
            if credits is not None:
                self.last_estimated_credits = credits
        return data

    async def collect_task(self, task_id: str) -> dict[str, Any]:
        """What became of a task this studio submitted earlier, asked by its id. Free.

        GET /v1/tasks/{id} only: nothing is generated, nothing is bought. Returns ``state``
        (RUNNING while the vendor works or queues, SUCCEEDED, FAILED), the outputs downloaded
        as ``(bytes, content_type)`` when it succeeded, and the vendor's failure code and
        sanitised reason when it failed. A poll or a download that fails raises; the caller
        leaves the task open and asks again later.
        """
        data = await self._task(task_id)
        remote = str(data["status"])
        failure = data.get("failure")
        code = data.get("failureCode")
        result: dict[str, Any] = {
            "task_id": task_id,
            "task_status": remote,
            "state": {"SUCCEEDED": "SUCCEEDED", "FAILED": "FAILED", "CANCELLED": "FAILED"}.get(
                remote, "RUNNING"
            ),
            "outputs": [],
            "failure_code": code if isinstance(code, str) and code else None,
            "failure_detail": sanitise_vendor_text(failure)
            if isinstance(failure, str) and failure.strip()
            else None,
            "estimated_credits": estimated_credits(data.get("estimatedCost")),
        }
        if result["state"] == "SUCCEEDED":
            outputs = data.get("output")
            urls = [u for u in outputs if isinstance(u, str)] if isinstance(outputs, list) else []
            if not urls:
                raise MediaProviderError("Runway reported success without an output")
            result["outputs"] = [await self._download(url) for url in urls]
        return result

    async def _download(self, url: str) -> tuple[bytes, str]:
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname:
            raise MediaProviderError("Runway returned an output that is not an HTTPS URL")
        host = _vet_output_host(parts.hostname)
        path = parts.path + ("?" + parts.query if parts.query else "")
        _, payload, content_type = await asyncio.to_thread(
            retrying,
            request,
            host,
            "GET",
            path,
            {},
            timeout=120,
            expect_json=False,
            public_only=True,
        )
        if not payload:
            raise MediaProviderError("Runway's output could not be downloaded")
        return payload, content_type


class RunwayImageAdapter(_RunwayClient, ImageProvider):
    """Stills through Runway's text_to_image task, with the model's contract for the ratio.

    A task is queued and polled; the still comes back as the bytes Runway served, measured
    from those bytes. A task that has not finished by the deadline raises — nothing invents
    a picture for a scene.
    """

    PROVIDER_NAME = "RUNWAY_IMAGES"

    #: The text_to_image task publishes `referenceImages`, so the studio may hand this adapter
    #: a character's reference sheet instead of describing the face again every scene. It is a
    #: statement about the code, not about the account: `REFERENCE_IMAGE_VERIFIED` stays False
    #: until an Owner-approved run has actually drawn a scene this way, because no test may
    #: spend a credit to find out. Runway has never answered a request with this field in it.
    ACCEPTS_REFERENCE_IMAGE = True
    REFERENCE_IMAGE_VERIFIED = False

    async def health_check(self) -> dict[str, Any]:
        try:
            data, _, _ = await asyncio.to_thread(
                retrying, request, HOST, "GET", "/v1/organization", self._headers(), timeout=20
            )
        except MediaProviderError as exc:
            return {"status": "OFFLINE", "detail": str(exc), "code": exc.code}
        if not isinstance(data, dict) or not isinstance(data.get("tier"), dict):
            return {"status": "OFFLINE", "detail": "Runway did not describe the organization"}
        return {"status": "HEALTHY", "detail": ""}

    async def _image_outputs(self, job_id: str) -> list[str]:
        """Poll a text_to_image task until it ends; the output URLs it served, in order.

        The task exists and may be billed from its submit on: a poll the vendor does not
        answer and the deadline are TaskStillOpen (collect it later), never a refusal. Only
        the vendor's own FAILED or CANCELLED is a refusal."""
        deadline = time.monotonic() + IMAGE_DEADLINE_SECONDS
        while True:
            try:
                data = await self._task(job_id)
            except MediaProviderError as exc:
                raise TaskStillOpen(
                    "Runway did not answer about an image task it accepted", task_id=job_id
                ) from exc
            remote = data["status"]
            if remote == "SUCCEEDED":
                break
            if remote in ("FAILED", "CANCELLED"):
                code = data.get("failureCode")
                failure = data.get("failure")
                raise MediaProviderError(
                    f"Runway image task {remote.lower()}",
                    code=code if isinstance(code, str) else None,
                    detail=sanitise_vendor_text(failure) if isinstance(failure, str) else None,
                )
            if time.monotonic() >= deadline:
                raise TaskStillOpen(
                    "Runway image task did not finish before the deadline", task_id=job_id
                )
            await asyncio.sleep(IMAGE_POLL_SECONDS)
        outputs = data.get("output")
        urls = [url for url in outputs if isinstance(url, str)] if isinstance(outputs, list) else []
        if not urls:
            raise MediaProviderError("Runway reported success without an output")
        return urls

    async def generate_candidates(
        self,
        prompt: str,
        *,
        ratio: str,
        count: int = 2,
        references: Sequence[bytes] = (),
        seed: int | None = None,
        on_submitted: Callable[[str], None] | None = None,
    ) -> list[ImageResult]:
        """``count`` candidate stills of one prompt, at exactly ``ratio``, in one purchase.

        The stills step buys two candidates per scene at 2K (1530:2720) and keeps the better
        one; the vendor's ``outputCount`` returns both from one task. A contract that lists
        the task's fields without ``outputCount`` gets one task per candidate instead, which
        costs the same per image. The ratio is the one asked, never the nearest: a 2K still is
        priced as 2K, and a ratio the contract does not list is refused before any call.

        ``references`` are pictures the prompt names as "Figure 1", "Figure 2"... (the film's
        first approved still, for its light, palette and grain). They go as data URIs, in
        order. ``REFERENCE_IMAGE_VERIFIED`` rides on every result: until an Owner-approved
        run has drawn with them, the sheet says the field is unverified.

        ``last_estimated_credits`` is the vendor's price for everything bought by this call
        (the sum over its tasks), or None when any task left it unstated.

        ``on_submitted(task_id)`` hears each task the moment the vendor accepts it, before any
        poll: that is when the purchase starts to cost money, and the caller writes it down
        then. A task whose output does not arrive raises TaskStillOpen with its id.
        """
        task = "text_to_image"
        self._require_task(task)
        wanted = max(1, int(count))
        pictures = [bytes(picture) for picture in references if picture]
        needs = self.model_metadata.get("needs_references", {})
        if not pictures and isinstance(needs, dict) and needs.get(task):
            raise MediaProviderError(
                f"{self.model} are nevoie de imagini de referință și nu poate desena o imagine "
                "doar din text",
                code="reference_images_required",
            )
        ratios = self.model_metadata.get("ratios", {})
        listed = ratios.get(task) if isinstance(ratios, dict) else None
        if not isinstance(listed, list) or not listed:
            raise MediaProviderError(
                "The ratios this Runway model accepts are not known; refresh the catalog first"
            )
        if ratio not in listed:
            raise MediaProviderError(
                f"Model {self.model} does not take ratio {ratio} for {task} according to "
                "Runway's contract"
            )
        described = fit_prompt(prompt, self._prompt_max(task))
        if not described:
            raise MediaProviderError("There is no prompt to generate an image from")
        body: dict[str, Any] = {"model": self.model, "promptText": described, "ratio": ratio}
        fields = self._fields(task)
        if isinstance(seed, int) and (fields is None or "seed" in fields):
            body["seed"] = seed
        if pictures:
            body["referenceImages"] = [
                {"uri": _image_data_uri(picture, "reference image")} for picture in pictures
            ]
        in_one = wanted > 1 and (fields is None or "outputCount" in fields)
        if in_one:
            body["outputCount"] = wanted
        tasks = 1 if in_one or wanted == 1 else wanted

        served: list[tuple[str, str]] = []
        prices: list[float | None] = []
        for _ in range(tasks):
            job_id = await self._submit(task, body)
            if on_submitted is not None:
                on_submitted(job_id)
            urls = await self._image_outputs(job_id)
            prices.append(self.last_estimated_credits)
            served += [(job_id, url) for url in urls]
        self.last_estimated_credits = (
            None if any(price is None for price in prices) else float(sum(p or 0 for p in prices))
        )
        results: list[ImageResult] = []
        for index, (job_id, url) in enumerate(served[:wanted]):
            try:
                image, content_type = await self._download(url)
            except MediaProviderError as exc:
                raise TaskStillOpen(
                    "Runway's still could not be downloaded", task_id=job_id
                ) from exc
            fmt, actual_width, actual_height = image_dimensions(image, content_type)
            results.append(
                ImageResult(
                    image_bytes=image,
                    format=fmt,
                    width=actual_width,
                    height=actual_height,
                    seed=seed if isinstance(seed, int) else None,
                    prompt=described,
                    raw_response={
                        "provider": self.PROVIDER_NAME,
                        "model": self.model,
                        "task_id": job_id,
                        "ratio": ratio,
                        "content_type": content_type,
                        "output_index": index,
                        "output_count": wanted,
                        "reference_images": len(pictures),
                        "reference_verified": self.REFERENCE_IMAGE_VERIFIED,
                        "bytes": len(image),
                    },
                )
            )
        return results

    async def generate_image(
        self,
        prompt: str,
        *,
        width: int = 1080,
        height: int = 1920,
        style: str | None = None,
        seed: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> ImageResult:
        task = "text_to_image"
        self._require_task(task)
        # Refused before the task is submitted, as a bad first frame is: a reference given as
        # a path or a description would be sent as a string where the API wants a URI.
        reference = _reference_image(extra)
        needs = self.model_metadata.get("needs_references", {})
        if reference is None and isinstance(needs, dict) and needs.get(task):
            # Known from the contract before any call: gen4_image_turbo edits pictures it is
            # given and cannot draw one from words alone. Runway answered HTTP 400 to every
            # scene of a day before this was read. The refusal is about the missing picture,
            # not about the model — with a character's sheet the same model draws — but the
            # catalog still keeps such a model out of the "image" purpose, so nothing in the
            # studio chooses one for a storyboard whose scenes may have nobody in them.
            raise MediaProviderError(
                f"{self.model} are nevoie de imagini de referință și nu poate desena o imagine "
                "doar din text; alege un model care desenează din text în "
                f"{settings_place('media')}",
                code="reference_images_required",
            )
        described = fit_prompt(f"{prompt} {style or ''}", self._prompt_max(task))
        if not described:
            raise MediaProviderError("There is no prompt to generate an image from")
        body: dict[str, Any] = {
            "model": self.model,
            "promptText": described,
            "ratio": self._ratio_for(task, f"{width}:{height}"),
        }
        if isinstance(seed, int):
            body["seed"] = seed
        if reference is not None:
            # `referenceImages` is an array of objects whose one required member is a URI —
            # an HTTPS address the vendor fetches, or the picture inline. The studio holds the
            # bytes of the sheet it produced and not a URL anybody else can read, so it is the
            # data-URI form. No tag is sent: a tag means something only when the prompt names
            # it as `@tag`, and inventing one would change the words the Director approved.
            body["referenceImages"] = [{"uri": _image_data_uri(reference, "reference image")}]
        job_id = await self._submit(task, body)
        url = (await self._image_outputs(job_id))[0]
        image, content_type = await self._download(url)
        fmt, actual_width, actual_height = image_dimensions(image, content_type)
        return ImageResult(
            image_bytes=image,
            format=fmt,
            width=actual_width,
            height=actual_height,
            seed=seed if isinstance(seed, int) else None,
            prompt=described,
            raw_response={
                "provider": self.PROVIDER_NAME,
                "model": self.model,
                "task_id": job_id,
                "ratio": body["ratio"],
                "content_type": content_type,
                # How many references this still was actually drawn from, so a render's record
                # says whether the character's face came from their sheet or from the words.
                "reference_images": 0 if reference is None else 1,
                "bytes": len(image),
            },
        )


class RunwayVideoAdapter(_RunwayClient, VideoProvider):
    async def health_check(self) -> dict[str, Any]:
        """Ask the API which organization this key belongs to. Reachability is never assumed."""
        try:
            data = await self.organization()
        except MediaProviderError as exc:
            return {
                "status": "OFFLINE",
                "detail": str(exc),
                "code": exc.code,
                "http_status": exc.http_status,
            }
        return {"status": "HEALTHY", "detail": "", "credit_balance": data.get("creditBalance")}

    async def model_contract(self) -> dict[str, dict[str, Any]]:
        data, _, _ = await asyncio.to_thread(
            retrying,
            request,
            DOCS_HOST,
            "GET",
            CONTRACT_PATH,
            {"Accept": "application/json"},
            timeout=30,
        )
        return parse_model_contract(data)

    async def list_models(self) -> list[dict[str, Any]]:
        """The models this organization may call, with their limits, usage and contract."""
        data = await self.organization()
        tier_models = data["tier"].get("models")
        if not isinstance(tier_models, dict):
            raise MediaProviderError("Runway did not return the organization's model limits")
        usage = data["usage"].get("models", {}) if isinstance(data.get("usage"), dict) else {}
        try:
            contract = await self.model_contract()
            self.capabilities_warning = None
        except MediaProviderError:
            contract = {}
            self.capabilities_warning = (
                "Contractul API Runway nu a putut fi citit, așa că sarcinile și formatele "
                "modelelor nu sunt cunoscute încă; reîncearcă actualizarea mai târziu."
            )
        items: list[dict[str, Any]] = []
        for model_id, limits in tier_models.items():
            if not isinstance(model_id, str) or not model_id.strip() or len(model_id) > 200:
                raise MediaProviderError("Runway returned a model without a valid ID")
            limits = limits if isinstance(limits, dict) else {}
            used = usage.get(model_id) if isinstance(usage, dict) else None
            item: dict[str, Any] = {
                "model_id": model_id,
                "name": model_id,
                "max_concurrent_generations": limits.get("maxConcurrentGenerations"),
                "max_daily_generations": limits.get("maxDailyGenerations"),
                "daily_generations": (
                    used.get("dailyGenerations") if isinstance(used, dict) else None
                ),
            }
            if model_id in contract:
                item.update(contract[model_id])
            items.append(item)
        return items

    def _video_body(
        self,
        task: str,
        prompt: str,
        image_ref: bytes | None,
        duration_seconds: float,
        aspect_ratio: str,
        extra: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """The request body for one shot, built from this model's contract.

        The same body is bought and quoted, so a quote is about this shot. Optional fields
        follow the contract: `audio` is sent, as False, to a model that declares it (the
        narration is the film's only sound, and a generated soundtrack is paid for and
        thrown away); `negativePrompt` only to one that declares it (veo); `seed` — the
        film's one seed — to a model that declares it, or when the contract's fields are
        not known, as before.
        """
        wanted = extra if isinstance(extra, dict) else {}
        fields = self._fields(task)
        cap = self._prompt_max(task)
        body: dict[str, Any] = {
            "model": self.model,
            "promptText": fit_prompt(prompt, cap),
            "ratio": self._ratio_for(task, aspect_ratio, follows_image=bool(image_ref)),
            "duration": pick_duration(self._durations(task), duration_seconds),
        }
        if image_ref:
            # The assembler hands over the still as a high-quality JPEG: a PNG of a
            # 1080x1920 frame, base64-encoded, runs past what a data URI may carry.
            body["promptImage"] = _image_data_uri(image_ref)
        seed = wanted.get("seed")
        if isinstance(seed, int) and not isinstance(seed, bool):
            if fields is None or "seed" in fields:
                body["seed"] = seed
        if fields is not None and "audio" in fields:
            body["audio"] = wanted.get("audio") is True
        negative = wanted.get("negative_prompt")
        if fields is not None and "negativePrompt" in fields and isinstance(negative, str):
            fitted = fit_prompt(negative, cap)
            if fitted:
                body["negativePrompt"] = fitted
        return body

    def _durations(self, task: str) -> Any:
        durations = self.model_metadata.get("durations", {})
        return durations.get(task) if isinstance(durations, dict) else None

    async def create_generation(
        self,
        prompt: str,
        *,
        image_ref: bytes | None = None,
        duration_seconds: float = 4.0,
        aspect_ratio: str = "9:16",
        extra: dict[str, Any] | None = None,
    ) -> str:
        if not self.model:
            raise MediaProviderNotConfigured(
                f"Niciun model video Runway ales; alege unul în {settings_place('media')}"
            )
        task = "image_to_video" if image_ref else "text_to_video"
        self._require_task(task)
        body = self._video_body(task, prompt, image_ref, duration_seconds, aspect_ratio, extra)
        if not body["promptText"] and task == "text_to_video":
            raise MediaProviderError("There is no prompt text to generate a video from")
        return await self._submit(task, body)

    async def estimate_generation(
        self,
        prompt: str,
        *,
        image_ref: bytes | None = None,
        duration_seconds: float = 4.0,
        aspect_ratio: str = "9:16",
        extra: dict[str, Any] | None = None,
    ) -> float | None:
        """The credits this exact shot would cost, asked of the vendor, or None if it will not say.

        The same body the real request would send, so the answer is about this shot and not
        about a model in general: a price per second written down somewhere is a guess about
        a length, a resolution and a task all at once.
        """
        if not self.model:
            return None
        task = "image_to_video" if image_ref else "text_to_video"
        tasks = self.model_metadata.get("tasks")
        if isinstance(tasks, list) and task not in tasks:
            return None
        try:
            body = self._video_body(task, prompt, image_ref, duration_seconds, aspect_ratio, extra)
        except MediaProviderError:
            return None
        return await self._quote(task, body)

    async def get_generation_status(self, job_id: str) -> VideoGenerationResult:
        data = await self._task(job_id)
        remote = data["status"]
        status = TASK_STATES.get(remote)
        if status is None:
            raise MediaProviderError(f"Runway returned an unknown task state {remote!r}")
        raw = {
            "provider": self.PROVIDER_NAME,
            "model": self.model,
            "task_id": job_id,
            "task_status": remote,
            "failure_code": data.get("failureCode"),
        }
        failure = data.get("failure")
        if isinstance(failure, str) and failure.strip():
            # The vendor's reason in its own words, sanitised: a refused input can be
            # echoed back as a signed URL or the picture itself.
            raw["failure"] = sanitise_vendor_text(failure)
        video: bytes | None = None
        if status == "COMPLETED":
            outputs = data.get("output")
            url = outputs[0] if isinstance(outputs, list) and outputs else None
            if not isinstance(url, str):
                raise MediaProviderError("Runway reported success without an output")
            video, content_type = await self._download(url)
            raw["content_type"] = content_type
            raw["bytes"] = len(video)
        return VideoGenerationResult(
            job_id=job_id,
            status=status,
            video_bytes=video,
            # Not measured here: the assembler probes the file it writes, and a number derived
            # from the request would describe what was asked for, not what came back.
            duration_seconds=None,
            raw_response=raw,
        )
