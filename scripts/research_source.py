"""Retrieve an Owner-selected public source, optionally ingest through the authenticated API."""

import argparse
import http.client
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.research.retrieval import RetrievalPolicy, SourceRetriever  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--allow-host", action="append", required=True)
    parser.add_argument("--ingest", action="store_true", help="Write via the running Owner API")
    parser.add_argument("--topic-id")
    parser.add_argument(
        "--receipt", type=Path, help="Write retrieval provenance to a new JSON file"
    )
    args = parser.parse_args()
    try:
        source = SourceRetriever(RetrievalPolicy(tuple(args.allow_host))).fetch(args.url)
        receipt = source.receipt()
        if args.receipt:
            with args.receipt.open("x", encoding="utf-8") as handle:
                json.dump(receipt, handle, ensure_ascii=False, indent=2)
        if args.ingest:
            settings = Settings()  # type: ignore[call-arg]
            connection = http.client.HTTPConnection("127.0.0.1", settings.port, timeout=15)
            try:
                connection.request(
                    "POST",
                    "/api/v1/factual/sources/ingest",
                    body=source.ingest_command(args.topic_id).model_dump_json().encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {settings.owner_token.get_secret_value()}",
                    },
                )
                response = connection.getresponse()
                if response.status not in (200, 201):
                    raise ValueError(f"Owner API rejected ingestion (HTTP {response.status})")
                result = json.loads(response.read(1_000_000))
                receipt["source_id"] = result["id"]
            finally:
                connection.close()
        print(json.dumps(receipt, ensure_ascii=True, indent=2))
        return 0
    except (ValueError, OSError, http.client.HTTPException):
        # Do not print credentials, server response bodies or source-controlled error strings.
        print(
            "Research failed; no successful ingestion is claimed. Check source policy, "
            "connectivity and Owner API configuration.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
