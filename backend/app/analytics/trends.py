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
    """Read today's trends for the studio's country and keep them. Says what happened."""
    if not settings.trends_enabled:
        return {"status": "SKIPPED", "reason": "Tendințele sunt oprite în configurație."}
    geo = settings.trends_geo
    correlation = correlation_id or str(uuid4())
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


def is_fresh(engine: Engine, geo: str, hours: int = 20) -> bool:
    since = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    with Session(engine) as session:
        return (
            session.scalar(
                select(TrendSnapshot.id)
                .where(TrendSnapshot.geo == geo, TrendSnapshot.fetched_at >= since)
                .limit(1)
            )
            is not None
        )


def trending_now(
    engine: Engine, geo: str, hours: int = 48, limit: int = PROMPT_LIMIT
) -> list[dict[str, Any]]:
    """The strongest recent trends, one line each, for a prompt or the page."""
    since = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    with Session(engine) as session:
        rows = session.scalars(
            select(TrendSnapshot)
            .where(TrendSnapshot.geo == geo, TrendSnapshot.fetched_at >= since)
            .order_by(TrendSnapshot.fetched_at.desc())
        ).all()
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for row in rows:
        if row.title in seen:
            continue
        seen.add(row.title)
        news = row.news_json if isinstance(row.news_json, list) else []
        items.append(
            {
                "title": row.title,
                "approx_traffic": row.approx_traffic,
                "news": [n.get("title", "") for n in news if isinstance(n, dict)][:2],
                "seen_at": row.fetched_at,
            }
        )
    items.sort(key=lambda t: -(t["approx_traffic"] or 0))
    return items[:limit]


def trends_as_text(items: list[dict[str, Any]], geo: str) -> str:
    if not items:
        return f"Tendințe ({geo}): nimic înregistrat încă."
    lines = [f"Tendințe acum ({geo}), după căutări:"]
    for item in items:
        traffic = f" (~{item['approx_traffic']:,} căutări)" if item["approx_traffic"] else ""
        news = f" — {'; '.join(n for n in item['news'] if n)}" if item["news"] else ""
        lines.append(f"- {item['title']}{traffic}{news}")
    return "\n".join(lines)
