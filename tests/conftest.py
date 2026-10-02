import ipaddress
import os
import secrets
import socket
import traceback
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from app.config import Settings
from app.db import create_db_engine, migrate
from app.main import create_app
from app.services import bootstrap_studio
from fastapi.testclient import TestClient
from suite_switches import mark_lanes
from suite_switches import pytest_runtest_makereport as pytest_runtest_makereport  # noqa: F401

#: Test modules that measure the production encode itself, so they keep it whole.
REAL_ENCODE_MODULES = frozenset({"test_encode_spec.py"})
#: The quick final encode's preset. veryfast keeps CABAC and the 8x8 transform, so the stream
#: stays High profile (ultrafast would drop to Constrained Baseline and fail QC's delivery
#: check), and at the same CRF its bitrate is a little higher, never under QC's 6 Mbps floor.
QUICK_FINAL_PRESET = "veryfast"


def pytest_collection_modifyitems(config, items):
    """Lanes (film, slow) and the modules kept on the production encode."""
    mark_lanes(items)
    for item in items:
        if item.path.name in REAL_ENCODE_MODULES:
            item.add_marker(pytest.mark.real_encode)


@pytest.fixture(autouse=True)
def quick_final_encode(request, monkeypatch):
    """The film's final encode on the veryfast preset, unless the test is about the encode.

    Measured 2026-10-01: the six end-to-end days took 491 s of a 1,717 s run, and the final
    encode is x264 on the slow preset at 1080x1920. Everything else in the delivery spec is
    kept (High 4.2, CRF 17, the 14 Mbps cap, the GOP, BT.709, faststart), so QC measures the
    same kind of file. Kept whole for a test marked real_encode (the encode spec, and one
    end-to-end day), and for every test when STUDIO_REAL_ENCODE=1.
    """
    if request.node.get_closest_marker("real_encode"):
        return
    if os.environ.get("STUDIO_REAL_ENCODE", "").strip() == "1":
        return
    from app.media import assembler

    production = assembler.final_video_args

    def quick(*args, **kwargs):
        encode = list(production(*args, **kwargs))
        if "-preset" in encode:
            encode[encode.index("-preset") + 1] = QUICK_FINAL_PRESET
        return encode

    monkeypatch.setattr(assembler, "final_video_args", quick)


def _loopback(host: object) -> bool:
    """localhost, or an address literal that is loopback; nothing that needs a lookup."""
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str):
        return False
    name = host.strip().strip("[]").lower()
    if name in ("", "localhost", "localhost."):
        return True
    try:
        return ipaddress.ip_address(name.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _local(address: object) -> bool:
    if isinstance(address, (str, bytes)):
        return True  # a Unix socket path
    return isinstance(address, tuple) and bool(address) and _loopback(address[0])


class NetworkGuard:
    """What `no_network` refused, and how a refusal is raised.

    ``loud`` (the suite's default) raises AssertionError, which no vendor client catches as
    a network fault, so a fake wired one call short fails the test. The rehearsal sets it
    to False: the refusal is then an OSError, as a real outage would be, so the day meets
    it exactly where it would meet the outage and goes on — the list is its evidence.
    """

    def __init__(self) -> None:
        self.refused: list[dict] = []
        self.loud = True

    def refuse(self, kind: str, target: object) -> BaseException:
        frames = traceback.extract_stack()[:-2]
        self.refused.append(
            {
                "kind": kind,
                "target": repr(target)[:200],
                "studio_frames": [
                    f"{frame.filename.split('backend')[-1]}:{frame.lineno} in {frame.name}"
                    for frame in frames
                    if "backend" in frame.filename and "app" in frame.filename
                ],
            }
        )
        message = (
            f"a test tried to reach {target!r} ({kind}); every provider must be faked at its "
            "transport (the Owner's rule: nothing costs money in a test)"
        )
        if self.loud:
            return AssertionError(message)
        if kind in ("getaddrinfo", "gethostbyname", "gethostbyname_ex"):
            return socket.gaierror(socket.EAI_NONAME, message)
        return ConnectionRefusedError(message)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """No test reaches a real provider: a socket, a name lookup or an asyncio connect to
    anything but loopback is refused.

    The Owner's rule (2026-09-17): models, voices, video and uploads cost money and happen
    only when everything is proven, so every adapter is faked at its transport. This
    fixture is the proof rather than the promise — a fake wired one call short fails here
    with the address it tried instead of spending at a vendor. Loopback stays open for a
    test that serves itself; a Unix socket is a local path by definition.

    DNS is refused like a socket (measured 2026-09-18: the guard refused `connect` only, so a
    public name was resolved before the refusal, and on Windows the proactor connects with
    ConnectEx, past `socket.connect` altogether). A test that answers `getaddrinfo` itself
    still can: its own monkeypatch is applied after this autouse fixture's and wins, and is
    undone before this one's.
    """
    import asyncio.proactor_events
    import asyncio.selector_events

    guard = NetworkGuard()
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def guarded_connect(self, address):
        if not _local(address):
            raise guard.refuse("connect", address)
        return real_connect(self, address)

    def guarded_connect_ex(self, address):
        if not _local(address):
            raise guard.refuse("connect_ex", address)
        return real_connect_ex(self, address)

    def guarded_lookup(real):
        def resolve(host, *args, **kwargs):
            # None is a passive lookup (a local bind), never a name on the network.
            if host is not None and not _loopback(host):
                raise guard.refuse(real.__name__, host)
            return real(host, *args, **kwargs)

        resolve.__name__ = f"guarded_{real.__name__}"
        return resolve

    def guarded_sock_connect(real):
        async def sock_connect(self, sock, address):
            if not _local(address):
                raise guard.refuse("asyncio.sock_connect", address)
            return await real(self, sock, address)

        return sock_connect

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    for name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex"):
        monkeypatch.setattr(socket, name, guarded_lookup(getattr(socket, name)))
    for loop_class in (
        asyncio.proactor_events.BaseProactorEventLoop,
        asyncio.selector_events.BaseSelectorEventLoop,
    ):
        monkeypatch.setattr(
            loop_class, "sock_connect", guarded_sock_connect(loop_class.sock_connect)
        )
    return guard


# The studio's own media folders. A render with no storage_root writes under them, so every
# test gets its own instead (measured 2026-10-01: the suite had left about 1,000 test films,
# 300 GB, among the Owner's real ones, about 1.1 GB per film once intermediates were lossless).
_STORAGE_NAMES = ("DEFAULT_STORAGE_ROOT", "REFERENCE_STORAGE_ROOT")
_STORAGE_MODULES = (
    "app.media.assembler",
    "app.media.services",
    "app.media.router",
    "app.media.stills_stage",
    "app.media.shooting_sheet",
    "app.media.rehearsal",
)


def _real_media_entries() -> set[str]:
    from pathlib import Path

    folder = Path(__file__).resolve().parents[1] / "backend" / "storage" / "media"
    return {child.name for child in folder.iterdir()} if folder.is_dir() else set()


def pytest_sessionstart(session):
    session.config._real_media_before = _real_media_entries()


def pytest_sessionfinish(session, exitstatus):
    """A run that left anything in the studio's real media folder fails, naming it."""
    before = getattr(session.config, "_real_media_before", None)
    if before is None:
        return
    leaked = sorted(_real_media_entries() - before)
    if leaked:
        print(f"\nTests wrote into backend/storage/media: {leaked[:10]} ({len(leaked)} entries)")
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.fixture(autouse=True)
def private_media_storage(monkeypatch, tmp_path_factory):
    """Every module that names the studio's media folders sees a per-test folder instead.

    Patched by name in each module, because the routers and stages import the constant
    rather than reading it through the assembler. A test that sets its own folder still
    can: its monkeypatch is applied after this one's and wins.
    """
    import importlib
    import sys

    base = tmp_path_factory.mktemp("studio_storage")
    folders = {
        "DEFAULT_STORAGE_ROOT": base / "media",
        "REFERENCE_STORAGE_ROOT": base / "character_references",
    }
    for module_name in _STORAGE_MODULES:
        importlib.import_module(module_name)
    for module_name, module in list(sys.modules.items()):
        if not module_name.startswith("app.") or module is None:
            continue
        for name in _STORAGE_NAMES:
            if hasattr(module, name):
                monkeypatch.setattr(module, name, folders[name])
    return folders


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        owner_token=secrets.token_urlsafe(48),
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        allowed_hosts=["testserver", "127.0.0.1"],
        # A background loop that starts the day on its own would make every other test's
        # timing a coincidence. The worker has its own tests, which drive it by hand.
        worker_enabled=False,
        provider_catalog_refresh_enabled=False,
    )


@pytest.fixture
def engine(settings):
    engine = create_db_engine(settings.database_url)
    migrate(engine)
    # The suite's studio is the Owner's own, which runs AUTONOMOUS_CEO; a buyer's fresh install
    # starts MANUAL (AR-09, services.NEW_STUDIO_AUTONOMY_MODE).
    bootstrap_studio(engine, settings, autonomy_mode="AUTONOMOUS_CEO")
    yield engine
    engine.dispose()


@pytest.fixture
def headers(settings):
    return {"Authorization": f"Bearer {settings.owner_token.get_secret_value()}"}


@pytest.fixture
def client(engine, settings):
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture
def elevenlabs_api(monkeypatch):
    """Stub only the HTTPS boundary; IDs are test-generated, not real provider claims."""
    from app.providers import elevenlabs

    fake = SimpleNamespace(
        models=[
            {
                "model_id": f"test-model-{uuid4()}",
                "name": "Test TTS model",
                "can_do_text_to_speech": True,
            }
        ],
        voices=[
            {"voice_id": f"test-voice-{uuid4()}", "name": "Test voice one"},
            {"voice_id": f"test-voice-{uuid4()}", "name": "Test voice two"},
        ],
        calls=[],
        fail=None,
        before_response=None,
    )

    def transport(host, method, path, headers, *args, **kwargs):
        assert host == "api.elevenlabs.io" and method == "GET"
        assert headers["xi-api-key"]
        fake.calls.append(path)
        if fake.before_response:
            fake.before_response(path)
        if fake.fail:
            fake.fail(path)
        parsed = urlsplit(path)
        if parsed.path == "/v1/user":
            payload = {"user_id": "test-account"}
        elif parsed.path == "/v1/models":
            payload = fake.models
        elif parsed.path == "/v2/voices":
            second = parse_qs(parsed.query).get("next_page_token") == ["second-page"]
            payload = {
                "voices": fake.voices[1:] if second else fake.voices[:1],
                "has_more": not second and len(fake.voices) > 1,
                "next_page_token": "second-page" if not second and len(fake.voices) > 1 else None,
            }
        else:
            raise AssertionError(path)
        return payload, b"", "application/json"

    monkeypatch.setattr(elevenlabs, "request", transport)
    return fake


@pytest.fixture
def runway_api(monkeypatch):
    """Stub Runway's HTTPS boundary: the organization endpoint and the published contract.

    Model ids are test-generated. The stub account has two video models and one image model,
    and the stubbed contract says which task each serves, as the real one does.
    """
    import json

    from app.providers import runway
    from app.providers.media_http import MediaProviderError

    video_a, video_b = f"test-video-{uuid4()}", f"test-video-{uuid4()}"
    image = f"test-image-{uuid4()}"
    fake = SimpleNamespace(
        models={
            video_a: {"maxConcurrentGenerations": 2, "maxDailyGenerations": 50},
            video_b: {"maxConcurrentGenerations": 1, "maxDailyGenerations": 20},
            image: {"maxConcurrentGenerations": 4, "maxDailyGenerations": 500},
        },
        usage={video_a: {"dailyGenerations": 2}},
        tasks={
            video_a: ["text_to_video", "image_to_video"],
            video_b: ["image_to_video"],
            image: ["text_to_image"],
        },
        video_models=[video_a, video_b],
        image_model=image,
        calls=[],
        bodies=[],
        task=None,
        fail=None,
        spec_fail=False,
        #: {model_id: [task, ...]} — tasks the stubbed contract marks as needing reference
        #: images, the way Runway marks its editing models.
        needs_references={},
    )

    def contract():
        paths = {}
        for model_id, tasks in fake.tasks.items():
            for task in tasks:
                branch = {
                    "properties": {
                        "model": {"const": model_id},
                        "ratio": {"enum": ["1280:720", "720:1280"]},
                        "duration": {"enum": [5, 10]},
                    }
                }
                if task in fake.needs_references.get(model_id, []):
                    branch["properties"]["referenceImages"] = {"type": "array", "minItems": 1}
                    branch["required"] = ["model", "ratio", "referenceImages"]
                schema = paths.setdefault(
                    f"/v1/{task}", {"post": {"requestBody": {"content": {}}}}
                )["post"]["requestBody"]["content"].setdefault(
                    "application/json", {"schema": {"oneOf": []}}
                )["schema"]["oneOf"]
                schema.append(branch)
        return {"openapi": "3.1.0", "paths": paths}

    def transport(host, method, path, headers, body=None, **kwargs):
        fake.calls.append((host, method, path))
        if fake.fail:
            fake.fail(host, path)
        if host == "docs.dev.runwayml.com":
            assert method == "GET" and path == "/openapi.json"
            if fake.spec_fail:
                raise MediaProviderError("docs.dev.runwayml.com could not be reached")
            return contract(), b"", "application/json"
        if host == "files.test":
            if path.split("?", 1)[0].endswith(".png"):
                # A 720x1280 PNG header: enough for the adapter to measure, nothing more.
                import struct

                png = (
                    b"\x89PNG\r\n\x1a\n"
                    + b"\x00\x00\x00\x0dIHDR"
                    + struct.pack(">II", 720, 1280)
                    + b"\x08\x06\x00\x00\x00"
                )
                return None, png, "image/png"
            return None, b"MP4BYTES", "video/mp4"
        assert host == "api.dev.runwayml.com", host
        assert headers["Authorization"].startswith("Bearer ") and headers["X-Runway-Version"]
        if method == "GET" and path == "/v1/organization":
            payload = {
                "creditBalance": 1200,
                "tier": {"maxMonthlyCreditSpend": 100000, "models": fake.models},
                "usage": {"models": fake.usage},
            }
        elif method == "POST" and path in (
            "/v1/text_to_video",
            "/v1/image_to_video",
            "/v1/text_to_image",
        ):
            fake.bodies.append(json.loads(body))
            payload = {"id": "task-1", "estimatedCost": {"credits": 25}}
        elif method == "GET" and path.startswith("/v1/tasks/"):
            payload = fake.task or {
                "id": path.rsplit("/", 1)[1],
                "status": "PENDING",
                "createdAt": "2026-09-11T00:00:00Z",
                "estimatedCost": {"credits": 25},
            }
        else:
            raise AssertionError((method, path))
        return payload, b"", "application/json"

    monkeypatch.setattr(runway, "request", transport)
    return fake


@pytest.fixture
def connect_youtube(engine, monkeypatch):
    """Build CONNECTED YouTube connections through the real OAuth code path.

    Only the HTTP transport to Google is replaced. The state, the token exchange, the channel
    read and the vault write are the code that runs in production, so a test binding to one of
    these is binding to something the real flow could have produced.

    Returns ``connect(name=..., channel_id=..., title=...) -> (connection_id, vault)``.
    """
    from pathlib import Path
    from urllib.parse import parse_qs, urlparse
    from uuid import uuid4

    from app.integrations.vault import CredentialVault
    from app.youtube import services as youtube

    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))

    def connect(*, name, channel_id, title):
        def post_form(url, form, timeout=20):
            if url != youtube.GOOGLE_TOKEN_URL:
                return {}
            return {
                "access_token": "test-access-token",
                "refresh_token": f"test-refresh-{channel_id}",
                "scope": youtube.SCOPES,
            }

        def get_json(url, access_token, timeout=20):
            return {
                "items": [
                    {
                        "id": channel_id,
                        "snippet": {"title": title, "customUrl": "@" + channel_id.lower()},
                        "contentDetails": {"relatedPlaylists": {"uploads": "UU" + channel_id[2:]}},
                        "statistics": {
                            "subscriberCount": "1",
                            "videoCount": "1",
                            "viewCount": "1",
                        },
                    }
                ]
            }

        monkeypatch.setattr(youtube, "_post_form", post_form)
        monkeypatch.setattr(youtube, "_get_json", get_json)

        connection = youtube.create_connection(
            engine,
            vault,
            name=name,
            client_id=name.lower().replace(" ", "-") + ".apps.googleusercontent.com",
            client_secret=secrets.token_urlsafe(32),
            redirect_uri="http://127.0.0.1:8000/auth/youtube/callback",
            correlation_id=str(uuid4()),
        )
        started = youtube.begin_authorization(engine, connection["id"], correlation_id=str(uuid4()))
        state = parse_qs(urlparse(started["authorization_url"]).query)["state"][0]
        youtube.complete_authorization(
            engine, vault, code="test-code", state=state, correlation_id=str(uuid4())
        )
        return connection["id"], vault

    return connect
