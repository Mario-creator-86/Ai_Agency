"""What a browser may keep of the page, and what it may never keep (W13, 2026-09-24).

Until this change every response said ``no-store``, so each visit downloaded the page's 8.7 MB
of art again before its first picture. The API still says ``no-store``: it carries the Owner's
studio. The built files carry a policy they can bear: a file Vite named by its content is kept
for a year, and everything else is kept but asked about each time (a 304 when unchanged).
"""

import pytest
from app.config import ROOT
from app.main import IMMUTABLE, REVALIDATE, static_cache_control

DIST = ROOT / "frontend/dist"


def test_the_policy_by_path():
    assert static_cache_control("assets/index-D49zCqy2.js") == IMMUTABLE
    assert static_cache_control("assets/office_scene-Bv05Fs5c.css") == IMMUTABLE
    # public art keeps its own names: never "immutable", or a rebuilt plate would never be seen
    assert static_cache_control("assets/hq/plates/day_city.webp") == REVALIDATE
    assert static_cache_control("assets/hq/scene.json") == REVALIDATE
    assert static_cache_control("index.html") == REVALIDATE
    assert static_cache_control(".") == REVALIDATE
    assert static_cache_control("favicon.ico") == REVALIDATE


def test_the_api_is_never_kept(client, headers):
    for path in ("/api/v1/snapshot", "/api/v1/events"):
        answer = client.get(path, headers=headers)
        assert answer.status_code == 200
        assert answer.headers["Cache-Control"] == "no-store", path
    # refused and missing answers are not kept either
    assert client.get("/api/v1/snapshot").headers["Cache-Control"] == "no-store"
    assert client.get("/api/v1/no-such-route", headers=headers).headers["Cache-Control"] == (
        "no-store"
    )
    assert client.get("/health/live").headers["Cache-Control"] == "no-store"


@pytest.mark.skipif(not (DIST / "assets").is_dir(), reason="the page has not been built")
def test_hashed_assets_are_immutable_and_the_rest_revalidates(client):
    built = sorted(p.name for p in (DIST / "assets").iterdir() if p.suffix in {".js", ".css"})
    assert built, "a built page has its hashed bundles"
    for name in built:
        answer = client.get(f"/assets/{name}")
        assert answer.status_code == 200, name
        assert answer.headers["Cache-Control"] == IMMUTABLE, name
    page = client.get("/")
    assert page.headers["Cache-Control"] == REVALIDATE
    # the security headers are still on the page
    assert "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]
    scene = client.get("/assets/hq/scene.json")
    assert scene.status_code == 200
    assert scene.headers["Cache-Control"] == REVALIDATE
    # a return visit that already holds the file gets a 304 and no body
    again = client.get("/assets/hq/scene.json", headers={"If-None-Match": scene.headers["ETag"]})
    assert again.status_code == 304
    assert again.headers["Cache-Control"] == REVALIDATE
    assert not again.content
    # a file that is not there is not kept
    assert client.get("/assets/nope-12345678.js").headers["Cache-Control"] == "no-store"
