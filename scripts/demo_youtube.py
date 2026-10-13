"""Bring up an isolated studio holding YouTube connections in every state worth looking at.

Why a separate database: the Owner's real studio must not gain invented OAuth grants, and a
throwaway one can be filled honestly. The connections here are produced by the *real* service
code — the same functions the callback route calls — with only the HTTP transport to Google
replaced, so what the interface then renders is the genuine result of the flow rather than rows
typed into a table.

Nothing here touches the network, and no credential in it is real.

    uv run python scripts/demo_youtube.py --keep-running
"""

from __future__ import annotations

import argparse
import json
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from tempfile import mkdtemp
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# The Windows console defaults to cp1252, which cannot encode Romanian diacritics; without
# this a successful run ends in a UnicodeEncodeError on its own summary.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#: Obviously invented. Real values never appear in a script that is committed.
FAKE_SECRET = "demo-client-secret-not-real"  # pragma: allowlist secret
FAKE_REFRESH = "demo-refresh-token-not-real"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def channel(channel_id: str, title: str, subs: str, videos: str, views: str) -> dict:
    return {
        "id": channel_id,
        "snippet": {
            "title": title,
            "customUrl": f"@{title.lower().replace(' ', '')}",
            "description": "Demo channel",
            "publishedAt": "2026-02-01T00:00:00Z",
            "country": "RO",
            "thumbnails": {"default": {"url": "/amn-ai-mark.png"}},
        },
        "contentDetails": {"relatedPlaylists": {"uploads": f"UU{channel_id[2:]}"}},
        "statistics": {"subscriberCount": subs, "videoCount": videos, "viewCount": views},
    }


def seed(database_url: str, redirect_uri: str) -> None:
    """Run the real flow against the isolated database, with Google stubbed out."""
    from app.db import create_db_engine
    from app.integrations.vault import CredentialVault
    from app.youtube import services

    engine = create_db_engine(database_url)
    vault = CredentialVault(
        Path(database_url.replace("sqlite:///", "")).with_suffix(".credentials.key")
    )

    answer = {"channel": None, "refresh_token": FAKE_REFRESH}

    def post_form(url, form, timeout=20):
        if url == services.GOOGLE_TOKEN_URL:
            reply = {"access_token": "demo-access", "scope": services.SCOPES}
            if answer["refresh_token"]:
                reply["refresh_token"] = answer["refresh_token"]
            return reply
        return {}

    def get_json(url, access_token, timeout=20):
        return {"items": [answer["channel"]]}

    services._post_form = post_form  # noqa: SLF001
    services._get_json = get_json  # noqa: SLF001

    def connect(name: str, client_id: str, item: dict) -> None:
        connection = services.create_connection(
            engine,
            vault,
            name=name,
            client_id=client_id,
            client_secret=FAKE_SECRET,
            redirect_uri=redirect_uri,
            correlation_id=str(uuid4()),
        )
        answer["channel"] = item
        started = services.begin_authorization(
            engine, connection["id"], correlation_id=str(uuid4())
        )
        state = parse_qs(urlparse(started["authorization_url"]).query)["state"][0]
        services.complete_authorization(
            engine, vault, code="demo-code", state=state, correlation_id=str(uuid4())
        )

    # One connected channel, a second connected channel, and one that only has credentials —
    # the three states the panel has to tell apart.
    connect(
        "Canal principal",
        "demo-alpha.apps.googleusercontent.com",
        channel("UCdemoAlpha0000000000001", "Canal principal demo", "12400", "86", "2140000"),
    )
    connect(
        "Canal secundar",
        "demo-beta.apps.googleusercontent.com",
        channel("UCdemoBeta00000000000002", "Canal secundar demo", "318", "12", "40100"),
    )
    services.create_connection(
        engine,
        vault,
        name="Canal nepornit",
        client_id="demo-gamma.apps.googleusercontent.com",
        client_secret=FAKE_SECRET,
        redirect_uri=redirect_uri,
        correlation_id=str(uuid4()),
    )
    engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-running", action="store_true")
    args = parser.parse_args()

    port = free_port()
    workspace = Path(mkdtemp(prefix="amn-youtube-"))
    token = secrets.token_urlsafe(48)
    database_url = f"sqlite:///{(workspace / 'demo.db').as_posix()}"
    redirect_uri = f"http://127.0.0.1:{port}/auth/youtube/callback"
    env = {
        **dict(__import__("os").environ),
        "STUDIO_OWNER_TOKEN": token,
        "STUDIO_DATABASE_URL": database_url,
        "STUDIO_PORT": str(port),
        "STUDIO_ALLOWED_HOSTS": '["localhost","127.0.0.1"]',
    }

    print(f"Isolated studio in {workspace}")
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "bootstrap.py")], cwd=ROOT, env=env, check=True
    )
    seed(database_url, redirect_uri)

    server = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "run.py")],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health/live", timeout=2)
                break
            except OSError:
                time.sleep(0.5)
        else:
            raise SystemExit("The isolated studio did not come up.")

        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/v1/youtube/connections",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            listed = json.loads(response.read())["connections"]
        for item in listed:
            channel_title = (item["channel"] or {}).get("title", "—")
            print(f"  {item['name']:<18} {item['status']:<14} {channel_title}")

        print(f"\nOwner token: {token}")
        print(f"Open http://127.0.0.1:{port}, press Settings, then Conturi și e-mail.")
        if args.keep_running:
            server.wait()
        return 0
    finally:
        if not args.keep_running:
            server.terminate()
            server.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
