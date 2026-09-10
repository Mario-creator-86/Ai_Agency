"""Bring up an isolated studio and walk one full economic cycle through the public API.

Why a separate database: the Owner's real books must never contain invented payouts. Recording
sample evidence there and reversing it afterwards would still leave fabricated history in an
append-only audit trail, which is exactly what the economy is built to prevent. So this script
creates its own throwaway database, exercises the API against it, prints what it did, and leaves
the real studio untouched.

Run it with the port of your choice::

    uv run python scripts/demo_treasury.py --port 8011 --keep-running

Every figure it produces comes from a real API call, not from a fixture written into the page.
"""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import mkdtemp
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def call(base: str, token: str, method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{base}{path}",
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{method} {path} -> {exc.code}: {exc.read().decode()[:400]}") from None


def free_port(requested: int | None) -> int:
    """Pick a port nothing is listening on.

    A leftover server from an earlier session silently answers health checks on the port you
    expected to own, and then every call goes to the wrong application. Binding first turns that
    into an immediate, obvious failure instead of a confusing 405 half a minute later.
    """
    import socket

    with socket.socket() as probe:
        if requested:
            try:
                probe.bind(("127.0.0.1", requested))
            except OSError:
                raise SystemExit(
                    f"Port {requested} is already in use by another process. "
                    "Stop it, or omit --port to let this script choose a free one."
                ) from None
            return requested
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port", type=int, default=None, help="Defaults to any free port on the loopback."
    )
    parser.add_argument("--keep-running", action="store_true", help="Leave the server up.")
    parser.add_argument(
        "--empty",
        action="store_true",
        help="Start the studio without recording anything, for driving the UI by hand.",
    )
    args = parser.parse_args()
    args.port = free_port(args.port)

    workspace = Path(mkdtemp(prefix="amn-treasury-"))
    token = secrets.token_urlsafe(48)
    env = {
        **dict(__import__("os").environ),
        "STUDIO_OWNER_TOKEN": token,
        "STUDIO_DATABASE_URL": f"sqlite:///{(workspace / 'demo.db').as_posix()}",
        "STUDIO_PORT": str(args.port),
        "STUDIO_ALLOWED_HOSTS": '["localhost","127.0.0.1"]',
    }

    print(f"Isolated studio in {workspace}")
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "bootstrap.py")], cwd=ROOT, env=env, check=True
    )
    server = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "run.py")],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{args.port}/api/v1"
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{args.port}/health/live", timeout=2)
                break
            except OSError:
                time.sleep(0.5)
        else:
            raise SystemExit("The isolated studio did not come up.")

        if args.empty:
            print(f"\nEmpty studio ready. Owner token: {token}")
            print(f"Open http://127.0.0.1:{args.port} and press Trezorerie.")
            if args.keep_running:
                server.wait()
            return 0

        # 1. A platform payout that has not settled yet: visible, and not spendable.
        pending = call(base, token, "POST", "/economy/evidence", {
            "command_id": str(uuid4()),
            "source": "YOUTUBE",
            "external_reference": "PAY-2026-08",
            "status": "PENDING_PAYOUT",
            "amount": "734.22",
            "currency": "USD",
            "detail": {"period": "2026-08", "note": "estimated payout, not yet paid"},
        })
        # 2. It settles, then is minted: 734.22 verified dollars become 734.22 VR$.
        call(base, token, "POST", f"/economy/evidence/{pending['id']}/settle")
        call(base, token, "POST", f"/economy/evidence/{pending['id']}/mint")

        # 3. A forecast for next month. Recorded, never minted.
        call(base, token, "POST", "/economy/evidence", {
            "command_id": str(uuid4()),
            "source": "YOUTUBE",
            "external_reference": "EST-2026-09",
            "status": "ESTIMATED",
            "amount": "900",
            "currency": "USD",
        })
        # 4. A sponsorship in euros, converted at a rate that is recorded, not invented.
        fx = call(base, token, "POST", "/economy/fx", {
            "command_id": str(uuid4()),
            "base_currency": "EUR",
            "quote_currency": "USD",
            "rate": "1.08",
            "source": "ECB reference rate",
            "observed_at": "2026-09-10T12:00:00+00:00",
        })
        sponsor = call(base, token, "POST", "/economy/evidence", {
            "command_id": str(uuid4()),
            "source": "SPONSORSHIP",
            "external_reference": "INV-2026-09-03",
            "status": "SETTLED",
            "amount": "500",
            "currency": "EUR",
            "fx_snapshot_id": fx["id"],
        })
        call(base, token, "POST", f"/economy/evidence/{sponsor['id']}/mint")

        # 5. The Owner puts money in: a contribution and a loan, which post differently.
        call(base, token, "POST", "/economy/owner-funding", {
            "command_id": str(uuid4()),
            "funding_type": "CAPITAL_CONTRIBUTION",
            "amount": "1000",
            "currency": "USD",
            "note": "Seed capital",
        })
        call(base, token, "POST", "/economy/owner-funding", {
            "command_id": str(uuid4()),
            "funding_type": "OWNER_LOAN",
            "amount": "2000",
            "currency": "USD",
            "annual_rate_bps": 500,
            "maturity_date": "2027-09-10",
            "note": "Owner loan at 5%",
        })
        # 6. What the studio actually spent on models, and one estimate not yet invoiced.
        call(base, token, "POST", "/economy/provider-costs", {
            "command_id": str(uuid4()),
            "provider": "openai",
            "external_reference": "INV-2026-08",
            "status": "BILLED",
            "amount": "218.40",
            "attribution": {"workflow": "daily-short"},
        })
        call(base, token, "POST", "/economy/provider-costs", {
            "command_id": str(uuid4()),
            "provider": "elevenlabs",
            "external_reference": "USAGE-2026-09",
            "status": "ESTIMATED",
            "amount": "46.10",
        })

        treasury = call(base, token, "GET", "/economy/treasury")
        print("\nSpendable      :", treasury["spendable"]["amount"], "VR$")
        for row in treasury["positions"] + treasury["not_spendable"]:
            print(f"  {row['money_class']:<18} {row['amount']:>10} VR$  {row['label']}")
        print("  unbilled costs    ", treasury["unbilled_provider_costs"]["amount"], "VR$")
        print("Trial balance  :", treasury["trial_balance"])
        print(f"\nOwner token for this isolated studio: {token}")
        print(f"Open http://127.0.0.1:{args.port} and press Trezorerie.")

        if args.keep_running:
            print("Server left running; stop it with Ctrl+C or by killing the process.")
            server.wait()
        return 0
    finally:
        if not args.keep_running:
            server.terminate()
            server.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
