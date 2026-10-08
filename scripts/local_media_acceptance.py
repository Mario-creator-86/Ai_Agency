"""Operate the real Agency API with a resumable acceptance journal; never logs credentials.

Usage: python scripts/local_media_acceptance.py configure
       python scripts/local_media_acceptance.py call /factual/topics --body request.json
GETs may be repeated. Mutating calls are never retried automatically; keep command IDs.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import Settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("configure", "call"))
    parser.add_argument("route", nargs="?")
    parser.add_argument("--body", type=Path)
    parser.add_argument("--method")
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    settings = Settings()  # type: ignore[call-arg]
    journal = ROOT / "data" / "local-media-acceptance"
    journal.mkdir(parents=True, exist_ok=True)
    headers = {
        "Authorization": "Bearer " + settings.owner_token.get_secret_value(),
        "Content-Type": "application/json",
    }

    def call(method: str, route: str, body: dict | None = None) -> dict:
        request = urllib.request.Request(
            args.base + "/api/v1" + route,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=24000) as response:
            result = json.load(response)
            with (journal / "requests.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        {
                            "utc": datetime.now(UTC).isoformat(),
                            "method": method,
                            "route": route,
                            "status": response.status,
                            "command_id": (body or {}).get("command_id"),
                        }
                    )
                    + "\n"
                )
            return result

    try:
        if args.action == "call":
            if not args.route or not args.route.startswith("/"):
                parser.error("call requires an API route beginning with /")
            body = json.loads(args.body.read_text(encoding="utf-8")) if args.body else None
            result = call(args.method or ("POST" if body else "GET"), args.route, body)
        else:
            from sqlalchemy.engine import make_url  # noqa: PLC0415

            database = make_url(settings.database_url).database
            if database:
                backup = journal / "before-local-defaults.db"
                if not backup.exists():
                    with sqlite3.connect(database) as source, sqlite3.connect(backup) as dest:
                        source.backup(dest)
            current = call("GET", "/settings")
            existing = next((x for x in current["integrations"] if x["kind"] == "comfyui"), None)
            identifier = existing["id"] if existing else str(uuid4())
            config = dict(existing["config"]) if existing else {}
            config["base_url"] = args.comfy_url
            saved = call(
                "PUT",
                f"/settings/integrations/{identifier}",
                {
                    "kind": "comfyui",
                    "name": "Studio local · RX 9070",
                    "config": config,
                    "secrets": {},
                    "expected_version": existing["version"] if existing else 0,
                },
            )
            if saved["status"] != "VERIFIED":
                raise RuntimeError("Studio local failed verification; defaults were not changed")
            version = saved["catalog"]["production"]["version"]
            call(
                "PUT",
                f"/settings/integrations/{identifier}/production",
                {
                    "expected_version": version,
                    "model_id": "I2V_HERO_RX9070",
                    "image_model_id": "SDXL_LOCAL",
                    "allow_production_override": False,
                },
            )
            for purpose in ("image", "video"):
                selection = current["selections"].get(purpose, {})
                call(
                    "PUT",
                    f"/settings/selections/{purpose}",
                    {"integration_id": identifier, "expected_version": selection.get("version", 0)},
                )
            updated = call("GET", "/settings")
            result = {
                "local_integration_id": identifier,
                "before": current["selections"],
                "after": updated["selections"],
                "voice_unchanged": current["selections"].get("voice")
                == updated["selections"].get("voice"),
            }
        output = args.output or journal / (args.action + "-latest.json")
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(str(output))
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        error = {"status": exc.code, "response": message}
        (journal / "last-error.json").write_text(json.dumps(error, indent=2), encoding="utf-8")
        print(f"HTTP {exc.code}; details saved in acceptance/last-error.json", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
