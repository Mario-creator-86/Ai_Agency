"""The worker's port to its own local ComfyUI (http://127.0.0.1:8188 inside the container).

Stdlib only. ComfyUI's HTTP API: POST /prompt (API-format graph) -> {prompt_id, node_errors};
GET /history/{prompt_id} -> {prompt_id: {outputs, status}}; POST /upload/image (multipart)
-> {name, subfolder, type}; GET /system_stats answers once the server is up.

The result is read from the declared output node's entry of type ``output`` (a Save node),
never from ``temp`` (preview nodes): the stock worker-comfyui handler skips temp outputs, and
a preview file is not the delivered take.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

DEFAULT_HOST = "127.0.0.1:8188"
DEFAULT_DIR = Path("/comfyui")
LOOPBACK = ("127.0.0.1", "localhost", "[::1]")
MAX_RESPONSE = 32 * 1024 * 1024


class ComfyUnavailable(RuntimeError):
    """ComfyUI does not answer: the rest of the batch fails ``COMFY_DOWN``."""


class ComfyFailed(RuntimeError):
    """One prompt failed; ``code`` is the item's error code."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


Opener = Callable[..., Any]


def find_output(history: Mapping[str, Any], node_id: str, output_dir: Path) -> Path:
    """The file the output node saved, of type ``output``; never temp/preview, never a path
    outside ComfyUI's output folder."""
    outputs = history.get("outputs")
    node = outputs.get(node_id) if isinstance(outputs, Mapping) else None
    if not isinstance(node, Mapping):
        raise ComfyFailed("NO_OUTPUT", f"node {node_id} produced nothing")
    root = output_dir.resolve()
    for value in node.values():
        if not isinstance(value, list):
            continue
        for entry in value:
            if not isinstance(entry, Mapping) or entry.get("type") != "output":
                continue
            filename = entry.get("filename")
            if not isinstance(filename, str) or not filename:
                continue
            subfolder = entry.get("subfolder") or ""
            path = (root / str(subfolder) / filename).resolve()
            if not path.is_relative_to(root):
                raise ComfyFailed("NO_OUTPUT", "output outside the output folder")
            return path
    raise ComfyFailed("NO_OUTPUT", f"node {node_id} saved no file of type output")


class ComfyClient:
    """The real port. One instance per worker process."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        *,
        output_dir: Path = DEFAULT_DIR / "output",
        poll_seconds: float = 0.5,
        request_timeout: float = 30.0,
        opener: Opener | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        name = host.rsplit(":", 1)[0]
        if name not in LOOPBACK:
            # The worker's ComfyUI runs in the same container; anything else is a mistake.
            raise ValueError("COMFY_HOST must be a loopback address")
        self.base = f"http://{host}"
        self.output_dir = output_dir
        self.poll_seconds = poll_seconds
        self.request_timeout = request_timeout
        self.opener = opener or urllib.request.urlopen
        self.sleep = sleep
        self.clock = clock
        self.client_id = str(uuid.uuid4())

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ComfyClient:
        values = os.environ if env is None else env
        comfy_dir = Path(values.get("COMFY_DIR", str(DEFAULT_DIR)))
        return cls(
            values.get("COMFY_HOST", DEFAULT_HOST),
            output_dir=Path(values.get("COMFY_OUTPUT_DIR", str(comfy_dir / "output"))),
        )

    def _call(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        request = urllib.request.Request(
            self.base + path, data=body, method=method, headers=dict(headers or {})
        )
        try:
            with self.opener(request, timeout=self.request_timeout) as response:
                raw = response.read(MAX_RESPONSE + 1)
        except urllib.error.HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", "replace")
            raise ComfyFailed("COMFY_REJECTED", f"HTTP {exc.code} {detail[:500]}") from exc
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
            raise ComfyUnavailable(f"ComfyUI does not answer: {type(exc).__name__}") from exc
        if len(raw) > MAX_RESPONSE:
            raise ComfyFailed("COMFY_FAILED", "ComfyUI answer too large")
        try:
            return json.loads(raw) if raw else {}
        except ValueError as exc:
            raise ComfyFailed("COMFY_FAILED", "ComfyUI answered no JSON") from exc

    def wait_ready(self, timeout: float) -> float:
        """Seconds waited until ComfyUI answers; :class:`ComfyUnavailable` after ``timeout``."""
        started = self.clock()
        while True:
            try:
                self._call("GET", "/system_stats")
                return self.clock() - started
            except ComfyUnavailable:
                if self.clock() - started >= timeout:
                    raise
                self.sleep(self.poll_seconds)

    def upload_input(self, name: str, data: bytes) -> str:
        """Put an input picture into ComfyUI's input folder; returns the name LoadImage takes."""
        boundary = "amn" + uuid.uuid4().hex
        parts = [
            f'--{boundary}\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n',
            f'--{boundary}\r\nContent-Disposition: form-data; name="type"\r\n\r\ninput\r\n',
            (
                f"--{boundary}\r\nContent-Disposition: form-data; "
                f'name="image"; filename="{name}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            ),
        ]
        body = "".join(parts).encode() + data + f"\r\n--{boundary}--\r\n".encode()
        answer = self._call(
            "POST",
            "/upload/image",
            body,
            {"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        stored = answer.get("name") if isinstance(answer, Mapping) else None
        if not isinstance(stored, str) or not stored:
            raise ComfyFailed("COMFY_FAILED", "upload answered no name")
        subfolder = answer.get("subfolder") or ""
        return f"{subfolder}/{stored}" if subfolder else stored

    def queue(self, graph: dict[str, Any]) -> str:
        body = json.dumps({"prompt": graph, "client_id": self.client_id}).encode()
        answer = self._call("POST", "/prompt", body, {"Content-Type": "application/json"})
        if not isinstance(answer, Mapping):
            raise ComfyFailed("COMFY_FAILED", "queue answer is not an object")
        if answer.get("node_errors"):
            raise ComfyFailed("COMFY_REJECTED", json.dumps(answer["node_errors"])[:500])
        prompt_id = answer.get("prompt_id")
        if not isinstance(prompt_id, str) or not prompt_id:
            raise ComfyFailed("COMFY_FAILED", "queue answered no prompt_id")
        return prompt_id

    def wait(self, prompt_id: str, timeout: float) -> dict[str, Any]:
        """The prompt's history entry once it finished; ``COMFY_TIMEOUT`` interrupts it."""
        started = self.clock()
        while True:
            answer = self._call("GET", "/history/" + prompt_id)
            entry = answer.get(prompt_id) if isinstance(answer, Mapping) else None
            if isinstance(entry, Mapping):
                status = entry.get("status")
                state = status.get("status_str") if isinstance(status, Mapping) else None
                if state == "error":
                    raise ComfyFailed("COMFY_FAILED", "the graph failed")
                completed = status.get("completed") if isinstance(status, Mapping) else True
                if completed is not False:
                    return dict(entry)
            if self.clock() - started >= timeout:
                try:
                    self._call("POST", "/interrupt", b"{}", {"Content-Type": "application/json"})
                except (ComfyFailed, ComfyUnavailable):
                    pass
                raise ComfyFailed("COMFY_TIMEOUT", f"no result in {timeout:.0f} s")
            self.sleep(self.poll_seconds)

    def output_path(self, history: dict[str, Any], node_id: str) -> Path:
        return find_output(history, node_id, self.output_dir)


def start_server(env: Mapping[str, str] | None = None) -> subprocess.Popen[bytes] | None:
    """Start the container's ComfyUI in the background (the stock /start.sh is replaced).

    Unlike the stock start script, ComfyUI runs without ``--disable-metadata``: the LTX-2.x
    licence forbids removing provenance metadata, so nothing is stripped knowingly.
    ``AMN_START_COMFY=0`` skips it (a ComfyUI already running).
    """
    values = os.environ if env is None else env
    if values.get("AMN_START_COMFY", "1") == "0":
        return None
    comfy_dir = Path(values.get("COMFY_DIR", str(DEFAULT_DIR)))
    host, _, port = values.get("COMFY_HOST", DEFAULT_HOST).rpartition(":")
    args = [
        sys.executable,
        "-u",
        str(comfy_dir / "main.py"),
        "--disable-auto-launch",
        "--listen",
        host.strip("[]") or "127.0.0.1",
        "--port",
        port or "8188",
    ]
    args += values.get("AMN_COMFY_EXTRA_ARGS", "").split()
    return subprocess.Popen(args, cwd=str(comfy_dir))
