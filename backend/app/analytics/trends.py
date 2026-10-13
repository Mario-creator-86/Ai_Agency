"""What the audience is looking up right now — Google Trends, recorded as a signal.

The Owner asked that the studio adapt to what is in vogue and to what its own numbers say,
and that the machinery exist before the numbers do. This is the outside half: Google's
public "trending now" feed for the studio's country, fetched once a day and kept as rows
(`trend_snapshot`), so the Researcher's proposals and the Director's weekly review can read
"what people search for today" beside "what our videos measured".

A trend is a hook, never a fact: nothing here becomes a source or a claim. The feed is
read over pinned HTTPS to the host's public address, like every other page the studio
fetches, and a day when the feed cannot be read is recorded as such — no trends are made up.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.analytics.models import TrendSnapshot
from app.config import Settings
from app.research.retrieval import RetrievalError, _PinnedHTTPS, resolve_public
from app.services import append_event, utc_now

logger = logging.getLogger("studio.trends")

TRENDS_HOST = "trends.google.com"
MAX_BYTES = 2_000_000
#: How many trends one refresh keeps, and how many a prompt is given.
KEEP_PER_REFRESH = 25
PROMPT_LIMIT = 12


class TrendsUnavailable(RuntimeError):
    """The feed could not be read; nothing was recorded as a trend."""


def trends_url(geo: str) -> str:
    return f"https://{TRENDS_HOST}/trending/rss?{urlencode({'geo': geo})}"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_trends_rss(payload: bytes) -> list[dict[str, Any]]:
    """The feed's items as plain records. Namespaces are matched by local name, so a change
    of namespace URI on Google's side does not silently empty the studio's view."""
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise TrendsUnavailable(f"Feed-ul nu este XML valid: {exc}") from exc
    items: list[dict[str, Any]] = []
    for item in root.iter():
        if _local(item.tag) != "item":
            continue
        title, traffic, published, news = "", None, "", []
        for child in item:
            name = _local(child.tag)
            text = (child.text or "").strip()
            if name == "title":
                title = text
            elif name == "approx_traffic":
                digits = re.sub(r"[^\d]", "", text)
                traffic = int(digits) if digits else None
            elif name == "pubDate":
                published = text
            elif name == "news_item":
                entry = {"title": "", "url": "", "source": ""}
                for part in child:
                    key = _local(part.tag)
                    if key == "news_item_title":
                        entry["title"] = (part.text or "").strip()
                    elif key == "news_item_url":
                        entry["url"] = (part.text or "").strip()
                    elif key == "news_item_source":
                        entry["source"] = (part.text or "").strip()
                if entry["title"]:
                    news.append(entry)
        if title:
            items.append(
                {
                    "title": title[:200],
                    "approx_traffic": traffic,
                    "news": news[:3],
                    "published_at": published[:60],
                }
            )
    return items


def fetch_trends_feed(geo: str, timeout: float = 15) -> bytes:
    """The feed's bytes, from the host's public address, capped."""
    try:
        address = resolve_public(TRENDS_HOST)
    except (RetrievalError, OSError) as exc:
        raise TrendsUnavailable(f"{TRENDS_HOST} nu poate fi rezolvat public: {exc}") from exc
    connection = _PinnedHTTPS(TRENDS_HOST, address, timeout)
    try:
        connection.request(
            "GET",
            f"/trending/rss?{urlencode({'geo': geo})}",
            headers={
                "Accept": "application/rss+xml, application/xml, text/xml",
                "Accept-Encoding": "identity",
                "User-Agent": "AutonomousAIStudio-Trends/1.0",
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            raise TrendsUnavailable(f"Feed-ul a răspuns HTTP {response.status}")
        if "xml" not in (response.headers.get_content_type() or ""):
            raise TrendsUnavailable("Feed-ul nu a răspuns cu XML")
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise TrendsUnavailable("Feed-ul depășește limita de dimensiune")
        return body
    except OSError as exc:
        raise TrendsUnavailable(f"Feed-ul nu a putut fi citit: {exc}") from exc
    finally:
        connection.close()


def refresh_trends(
    engine: Engine,
    settings: Settings,
    correlation_id: str | None = None,
    fetcher: Any = None,
) -> dict[str, Any]:
    """Read today's trends for the studio's countries and keep them. Says what happened.

    One country (the setting as it was until 2026-10-11) answers as before: ``geo``, ``count``
    and ``seen``. Several (``STUDIO_TRENDS_GEO=US,GB,CA,AU``: the audience's countries, the
    Owner's choice of 2026-10-11) are read one after the other, each kept under its own code;
    the answer adds ``by_geo``, and is COMPLETED when at least one feed answered."""
    if not settings.trends_enabled:
        return {"status": "SKIPPED", "reason": "Tendințele sunt oprite în configurație."}
    geos = geos_of(settings.trends_geo)
    correlation = correlation_id or str(uuid4())
    results = [_refresh_one(engine, geo, correlation, fetcher) for geo in geos]
    if len(results) == 1:
        return results[0]
    answered = [item for item in results if item["status"] == "COMPLETED"]
    return {
        "status": "COMPLETED" if answered else "FAILED",
        "geo": settings.trends_geo,
        "count": sum(int(item.get("count") or 0) for item in answered),
        "seen": sum(int(item.get("seen") or 0) for item in answered),
        "by_geo": results,
    }


def geos_of(geo: str | Sequence[str]) -> list[str]:
    """The country codes of a setting ("US,GB") or a list, upper-cased, each once."""
    parts = geo.split(",") if isinstance(geo, str) else list(geo)
    codes: list[str] = []
    for part in parts:
        code = str(part).strip().upper()
        if code and code not in codes:
            codes.append(code)
    return codes


def _refresh_one(engine: Engine, geo: str, correlation: str, fetcher: Any = None) -> dict[str, Any]:
    """One country's feed read and kept; its own event either way."""
    try:
        payload = (fetcher or fetch_trends_feed)(geo)
        items = parse_trends_rss(payload)
    except TrendsUnavailable as exc:
        with Session(engine) as session, session.begin():
            append_event(
                session,
                "trends.unavailable",
                "trend_snapshot",
                geo,
                1,
                {"geo": geo, "reason": str(exc)[:300]},
                correlation,
            )
        logger.info("trends_unavailable", extra={"geo": geo})
        return {"status": "FAILED", "geo": geo, "reason": str(exc)[:300]}
    now = utc_now()
    today = now[:10]
    kept: list[str] = []
    with Session(engine) as session, session.begin():
        already = {
            row.title
            for row in session.scalars(
                select(TrendSnapshot).where(
                    TrendSnapshot.geo == geo, TrendSnapshot.fetched_at >= today
                )
            )
        }
        for item in items[:KEEP_PER_REFRESH]:
            if item["title"] in already:
                continue
            session.add(
                TrendSnapshot(
                    id=str(uuid4()),
                    geo=geo,
                    title=item["title"],
                    approx_traffic=item["approx_traffic"],
                    news_json=item["news"],
                    published_at=item["published_at"] or None,
                    fetched_at=now,
                )
            )
            kept.append(item["title"])
        append_event(
            session,
            "trends.snapshot_recorded",
            "trend_snapshot",
            geo,
            1,
            {"geo": geo, "count": len(kept), "seen": len(items), "top": kept[:5]},
            correlation,
        )
    return {"status": "COMPLETED", "geo": geo, "count": len(kept), "seen": len(items)}


def is_fresh(engine: Engine, geo: str | Sequence[str], hours: int = 20) -> bool:
    """Whether every country of ``geo`` ("US,GB" or a list) was read in the last ``hours``."""
    since = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    with Session(engine) as session:
        return all(
            session.scalar(
                select(TrendSnapshot.id)
                .where(TrendSnapshot.geo == code, TrendSnapshot.fetched_at >= since)
                .limit(1)
            )
            is not None
            for code in geos_of(geo)
        )


def trending_now(
    engine: Engine, geo: str | Sequence[str], hours: int = 48, limit: int = PROMPT_LIMIT
) -> list[dict[str, Any]]:
    """The strongest recent trends of the studio's countries, one line each, for a prompt or
    the page. A trend seen in several countries is one line carrying them all (``geos``)."""
    since = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    codes = geos_of(geo)
    with Session(engine) as session:
        rows = session.scalars(
            select(TrendSnapshot)
            .where(TrendSnapshot.geo.in_(codes), TrendSnapshot.fetched_at >= since)
            .order_by(TrendSnapshot.fetched_at.desc())
        ).all()
    by_title: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = by_title.get(row.title)
        if item is not None:
            if row.geo not in item["geos"]:
                item["geos"].append(row.geo)
            item["approx_traffic"] = max(item["approx_traffic"] or 0, row.approx_traffic or 0)
            continue
        news = row.news_json if isinstance(row.news_json, list) else []
        by_title[row.title] = {
            "title": row.title,
            "approx_traffic": row.approx_traffic,
            "news": [n.get("title", "") for n in news if isinstance(n, dict)][:2],
            "seen_at": row.fetched_at,
            "geos": [row.geo],
        }
    items = list(by_title.values())
    for item in items:
        # In the order the setting names the countries, not the order the feeds answered.
        item["geos"].sort(key=codes.index)
    items.sort(key=lambda t: -(t["approx_traffic"] or 0))
    return items[:limit]


def _country_codes(geo: str | Sequence[str]) -> bool:
    parts = geo.split(",") if isinstance(geo, str) else list(geo)
    return bool(parts) and all(
        re.fullmatch(r"\s*[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,4})?\s*", str(part)) for part in parts
    )


def trends_as_text(items: list[dict[str, Any]], geo: str | Sequence[str]) -> str:
    # The weekly digest labels its list in words («săptămâna aceasta»); only country codes
    # are read as such.
    codes = geos_of(geo) if _country_codes(geo) else []
    label = ", ".join(codes) if codes else str(geo)
    if not items:
        return f"Tendințe ({label}): nimic înregistrat încă."
    lines = [f"Tendințe acum ({label}), după căutări:"]
    for item in items:
        traffic = f" (~{item['approx_traffic']:,} căutări)" if item["approx_traffic"] else ""
        news = f" — {'; '.join(n for n in item['news'] if n)}" if item["news"] else ""
        where = ""
        if len(codes) > 1 and item.get("geos"):
            where = f" [{', '.join(item['geos'])}]"
        lines.append(f"- {item['title']}{where}{traffic}{news}")
    return "\n".join(lines)
