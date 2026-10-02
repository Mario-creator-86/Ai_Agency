"""Every route in the API, called without a credential, from the outside.

Introspecting dependency trees proves what the code says. This calls the application instead, so
it proves what the application does — including for any route added later, since the list comes
from the OpenAPI surface rather than from a hand-written inventory.

Four routes are public by design and are named here so that adding a fifth is a deliberate act:
the two health probes, which must answer a load balancer, the OAuth callback, which Google
redirects a browser to and which therefore cannot carry the Owner credential, and the reading of
the studio's kept frame of its live building (W24), which the title shows before the sign-in and
which carries only that picture. The callback's own protection is the single-use state, covered in
`test_youtube_connections.py`; the kept frame is written only with the Owner's key
(`test_office_kept_frame.py`).
"""

from __future__ import annotations

import logging

import pytest

#: Public on purpose. Anything else answering an anonymous caller is a defect.
PUBLIC = {
    ("GET", "/health/live"),
    ("GET", "/health/ready"),
    ("GET", "/auth/youtube/callback"),
    ("GET", "/api/v1/office/kept-frame"),
}

#: Rejections. 401 and 403 are the credential refusing; 405 is a method the route does not take.
REFUSALS = {401, 403}


def _fill(path: str) -> str:
    """Give every path parameter a syntactically plausible value."""
    out = []
    for part in path.split("/"):
        if part.startswith("{") and part.endswith("}"):
            name = part[1:-1]
            out.append(
                "1"
                if name.endswith(("_version", "_number"))
                else "11111111-1111-4111-8111-111111111111"
            )
        else:
            out.append(part)
    return "/".join(out)


def _operations(client) -> list[tuple[str, str]]:
    schema = client.app.app.openapi()
    return [
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        for method in operations
        if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    ]


def test_every_route_is_owner_only_except_the_four_that_cannot_be(client):
    operations = _operations(client)
    # A guard against the audit silently covering nothing if the schema shape ever changes.
    assert len(operations) > 50, f"only {len(operations)} operations found"

    leaks = []
    for method, path in operations:
        if (method, path) in PUBLIC:
            continue
        response = client.request(method, _fill(path))
        if response.status_code not in REFUSALS:
            leaks.append(f"{method} {path} -> {response.status_code}")
    assert not leaks, "routes answered an anonymous caller:\n" + "\n".join(leaks)


def test_the_public_routes_are_still_reachable(client):
    """The other half of the same claim: the exceptions above are exceptions, not dead routes."""
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code in {200, 503}
    # nothing kept yet: an empty answer, never a picture made up for the title
    assert client.get("/api/v1/office/kept-frame").status_code == 204
    # The callback answers a browser, so every outcome must be a readable HTML page rather than
    # a JSON error or a stack trace — including the ones that are nobody's fault.
    for query, expected in [
        ("", 400),  # someone typed the URL
        ("?error=access_denied&state=x", 400),  # consent refused
        ("?code=abc", 400),  # a code with no state
    ]:
        page = client.get("/auth/youtube/callback" + query)
        assert page.status_code == expected, query
        assert page.headers["content-type"].startswith("text/html"), query
        assert "<h1>" in page.text, query


@pytest.mark.parametrize("credential", ["", "Bearer ", "Bearer wrong-token", "Basic abc"])
def test_a_wrong_credential_is_refused_everywhere_it_matters(client, credential):
    headers = {"Authorization": credential} if credential else {}
    response = client.get("/api/v1/settings", headers=headers)
    assert response.status_code in REFUSALS


# ---------------------------------------------------------------------------------------------
# SEC-07: a wrong key is logged (where it came from and which path, never the header), and a
# client that keeps presenting wrong keys is answered 429 after REFUSALS_PER_MINUTE of them in a
# minute. The Owner's own key still passes from the same address: the studio runs on his machine,
# where a prober and his page share 127.0.0.1, and a lock-out would be a lock-out of him. The key
# itself (64 characters) is what makes guessing impractical; this makes the guessing visible.
# ---------------------------------------------------------------------------------------------


class _Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_wrong_keys_are_logged_then_slowed_and_the_right_key_still_passes(client, headers):
    from app.security import REFUSALS_PER_MINUTE

    seen = _Records()
    security_log = logging.getLogger("studio.security")
    security_log.addHandler(seen)
    try:
        wrong = [f"wrong-key-{n}-{'x' * 20}" for n in range(REFUSALS_PER_MINUTE + 5)]
        codes = [
            client.get("/api/v1/settings", headers={"Authorization": f"Bearer {key}"}).status_code
            for key in wrong
        ]
        assert codes[:REFUSALS_PER_MINUTE] == [401] * REFUSALS_PER_MINUTE, codes
        assert set(codes[REFUSALS_PER_MINUTE:]) == {429}, codes
        slowed = client.get("/api/v1/settings", headers={"Authorization": "Bearer nope"})
        assert slowed.status_code == 429 and int(slowed.headers["Retry-After"]) >= 1
        assert client.get("/api/v1/settings", headers=headers).status_code == 200
    finally:
        security_log.removeHandler(seen)
    refused = [r for r in seen.records if r.getMessage() == "owner_auth_refused"]
    assert len(refused) == REFUSALS_PER_MINUTE
    assert refused[0].host == "testclient" and refused[0].path == "/api/v1/settings"
    assert [r.getMessage() for r in seen.records].count("owner_auth_throttled") == 1
    text = " ".join(repr(r.__dict__) for r in seen.records)
    assert "wrong-key" not in text and "Bearer" not in text and "nope" not in text


def test_a_missing_key_is_refused_without_counting_as_a_guess(client, headers):
    from app.security import REFUSALS_PER_MINUTE

    for _ in range(REFUSALS_PER_MINUTE + 5):
        assert client.get("/api/v1/settings").status_code == 401
    assert client.get("/api/v1/settings", headers={"Authorization": "Bearer x"}).status_code == 401
