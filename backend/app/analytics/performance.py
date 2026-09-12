"""What each film actually did, in numbers that mean something next to each other.

The studio measured its videos and could not read them. A snapshot said "10 000 views" and
nothing said whether that was good: a film thirty days old and a film four hours old were the
same row, a channel whose median is 8 000 and one whose median is 150 000 were the same
scale, and a video that brought three hundred subscribers from thirty thousand views looked
worse than one that brought two hundred from a hundred thousand.

So this module does four things, all of them reads over rows the studio already stores:

- **Normalises.** Views per hour and per day beside the totals, subscriber conversion,
  engagement, cost per thousand views — because a lifetime total is not a rate.
- **Builds a baseline.** Rolling medians per channel, and only from at least three measured
  films: below that the honest answer is that the channel has no baseline yet.
- **Classifies against that baseline, with a confidence.** A winner or an underperformer is a
  statement about a film relative to its own channel, never an absolute number, and never
  from one sample or from four hours of data.
- **Diagnoses.** Where the number actually points: reach, retention, conversion, or not
  enough data to say. Impressions and click-through separate "nobody saw it" from "they saw
  it and left", which is the difference between two completely different assignments.

Two rules hold everywhere. **Nothing is invented**: a metric the platform did not report is
`None`, not zero, and a verdict without evidence is `INSUFFICIENT_DATA`. And **one video is
never a conclusion about a category** — the sample size travels with every judgement.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from statistics import median
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.analytics.models import AnalyticsSnapshot
from app.economy.models import ProviderCostRecord
from app.media.models import VideoRenderJob
from app.publishing.models import ChannelRecord, PublicationRecord

logger = logging.getLogger("studio.performance")

#: How many measured films a channel needs before it has a baseline at all. The same three the
#: database already demands of a recommendation (`ck_recommendation_has_evidence`): two films
#: are an anecdote, and a median of one is that one film.
MINIMUM_BASELINE = 3

#: How long a film must have been public before its numbers mean anything. YouTube's own
#: reporting lags, and a short's first hour is mostly the platform deciding who to show it to.
MINIMUM_JUDGEMENT_HOURS = 24.0

#: The windows the studio's YouTube integration can actually ask for. Anything else would be
#: a label over a period nobody reported — the bug this studio already had once.
AVAILABLE_WINDOWS = ("1h", "24h", "7d", "28d", "LIFETIME")

#: How far back a rolling baseline looks. Long enough to hold a few films, short enough that a
#: channel is not forever compared with the week it was born.
BASELINE_DAYS = 90

#: What counts as a winner or an underperformer, as a multiple of the channel's own median.
WINNER_RATIO = 3.0
PROMISING_RATIO = 1.5
UNDERPERFORMER_RATIO = 0.6
FAILED_RATIO = 0.3

VERDICTS = (
    "STRONG_WINNER",
    "PROMISING",
    "NORMAL",
    "UNDERPERFORMER",
    "FAILED_EXPERIMENT",
    "INSUFFICIENT_DATA",
)

FAILURE_KINDS = (
    "REACH_FAILURE",
    "HOOK_OR_RETENTION_FAILURE",
    "CONVERSION_FAILURE",
    "TOPIC_FAILURE",
    "INSUFFICIENT_DATA",
)


def _hours_since(stamp: str | None) -> float | None:
    """Hours between an ISO timestamp and now, or None when there is no timestamp."""
    if not stamp:
        return None
    try:
        moment = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    delta = (datetime.now(UTC) - moment).total_seconds() / 3600.0
    return round(delta, 3) if delta >= 0 else None


def _ratio(top: float | None, bottom: float | None) -> float | None:
    if not isinstance(top, int | float) or not isinstance(bottom, int | float):
        return None
    return round(float(top) / float(bottom), 4) if bottom else None


def _percent(part: float | None, whole: float | None) -> float | None:
    share = _ratio(part, whole)
    return round(share * 100.0, 4) if share is not None else None


def _latest_snapshots(session: Session, publication_id: str) -> dict[str, AnalyticsSnapshot]:
    """The most recent snapshot per window for one publication."""
    rows = session.scalars(
        select(AnalyticsSnapshot)
        .where(AnalyticsSnapshot.publication_id == publication_id)
        .order_by(AnalyticsSnapshot.snapshot_at.asc())
    )
    return {row.window: row for row in rows}


def _cost_and_time(session: Session, media_asset_id: str) -> tuple[float | None, float | None]:
    """What this film cost and how long its render took, from the books and the render job.

    Cost is the sum of the provider records attributed to the render, in dollars. A film with
    no priced usage returns None rather than zero: unpriced is not free, and the studio has
    been bitten by exactly that reading before.
    """
    job = session.scalar(
        select(VideoRenderJob).where(VideoRenderJob.output_asset_id == media_asset_id)
    )
    if job is None:
        return None, None
    micros = 0
    found = False
    for row in session.scalars(select(ProviderCostRecord)):
        attribution = row.attribution_json if isinstance(row.attribution_json, dict) else {}
        if attribution.get("render_job_id") == job.id:
            micros += int(row.usd_micros or 0)
            found = True
    minutes = round(float(job.duration_ms) / 60000.0, 2) if job.duration_ms else None
    return (round(micros / 1_000_000, 4) if found else None), minutes


def video_performance(engine: Engine, channel_id: str | None = None) -> list[dict[str, Any]]:
    """Every published film with its numbers normalised, newest first.

    Only publications the platform actually serves: a simulated upload has no audience, and a
    row with no remote id has nothing to measure. What was not reported is None.
    """
    out: list[dict[str, Any]] = []
    with Session(engine) as session:
        query = select(PublicationRecord).where(
            PublicationRecord.status == "PUBLISHED",
            PublicationRecord.remote_video_id.is_not(None),
        )
        if channel_id:
            query = query.where(PublicationRecord.channel_id == channel_id)
        for pub in session.scalars(query.order_by(PublicationRecord.published_at.desc())):
            windows = _latest_snapshots(session, pub.id)
            latest = windows.get("LIFETIME") or (
                max(windows.values(), key=lambda s: s.snapshot_at) if windows else None
            )
            age = _hours_since(pub.published_at)
            cost, minutes = _cost_and_time(session, pub.media_asset_id)
            views = int(latest.views) if latest else None
            entry: dict[str, Any] = {
                "publication_id": pub.id,
                "channel_id": pub.channel_id,
                "title": pub.title,
                "published_at": pub.published_at,
                "age_hours": age,
                "measured": latest is not None,
                "windows_measured": sorted(windows),
                "views": views,
                # A rate, not a total: a film four hours old and one thirty days old are not
                # comparable any other way. Below an hour the rate is noise, so it is not given.
                "views_per_hour": (_ratio(views, age) if age is not None and age >= 1.0 else None),
                "views_per_day": (
                    round(float(_ratio(views, age) or 0) * 24.0, 2)
                    if age is not None and age >= 1.0 and views is not None
                    else None
                ),
                "watch_time_seconds": float(latest.watch_time_seconds) if latest else None,
                "average_view_percentage": (
                    float(latest.average_view_percentage) if latest else None
                ),
                "impressions": int(latest.impressions) if latest else None,
                "ctr_percentage": float(latest.ctr_percentage) if latest else None,
                "likes": int(latest.likes) if latest else None,
                "comments": int(latest.comments) if latest else None,
                "shares": int(latest.shares) if latest else None,
                "subscribers_gained": int(latest.subscribers_gained) if latest else None,
                "subscriber_conversion_percentage": (
                    _percent(latest.subscribers_gained, latest.views) if latest else None
                ),
                "engagement_percentage": (
                    _percent(
                        (latest.likes + latest.comments + latest.shares),
                        latest.views,
                    )
                    if latest
                    else None
                ),
                "cost_usd": cost,
                "production_minutes": minutes,
                "views_per_dollar": _ratio(views, cost),
                "subscribers_per_dollar": (
                    _ratio(latest.subscribers_gained, cost) if latest else None
                ),
                "cost_per_thousand_views": (
                    round(float(cost) / (float(views) / 1000.0), 4)
                    if cost and views and views >= 1
                    else None
                ),
            }
            out.append(entry)
    return out


def channel_baselines(engine: Engine, channel_id: str) -> dict[str, Any]:
    """The channel's own rolling medians, or an honest statement that it has none yet.

    Everything is compared against this and never against an absolute number: 48 000 views is
    a triumph on a channel whose median is 8 000 and a disappointment on one whose median is
    150 000. Below three measured films there is no median worth the name.
    """
    films = [
        film
        for film in video_performance(engine, channel_id)
        if film["measured"] and (film["age_hours"] or 0) <= BASELINE_DAYS * 24
    ]

    def med(key: str) -> float | None:
        values = [f[key] for f in films if isinstance(f.get(key), int | float)]
        return round(median(values), 4) if len(values) >= MINIMUM_BASELINE else None

    return {
        "channel_id": channel_id,
        "sample_size": len(films),
        "window_days": BASELINE_DAYS,
        "has_baseline": len(films) >= MINIMUM_BASELINE,
        "median_views": med("views"),
        "median_views_per_hour": med("views_per_hour"),
        "median_view_percentage": med("average_view_percentage"),
        "median_subscriber_conversion": med("subscriber_conversion_percentage"),
        "median_engagement": med("engagement_percentage"),
        "median_ctr": med("ctr_percentage"),
        "median_cost_usd": med("cost_usd"),
        "median_production_minutes": med("production_minutes"),
        "note": (
            f"{len(films)} measured films; a baseline needs {MINIMUM_BASELINE}"
            if len(films) < MINIMUM_BASELINE
            else f"rolling medians over {len(films)} measured films"
        ),
    }


def _confidence(sample_size: int, age_hours: float | None) -> str:
    """How much weight a verdict about one film deserves."""
    if age_hours is None or age_hours < MINIMUM_JUDGEMENT_HOURS or sample_size < MINIMUM_BASELINE:
        return "LOW"
    if sample_size >= 10 and age_hours >= 72:
        return "HIGH"
    return "MEDIUM"


def classify(film: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Where this film stands against its own channel, and how sure that is.

    A verdict needs three things: the channel must have a baseline, the film must be old
    enough for its numbers to mean something, and the comparison must be a rate rather than a
    total. Missing any of them, the answer is INSUFFICIENT_DATA — which is a real answer, and
    the one the studio used to skip by treating zero as a measurement.
    """
    age = film.get("age_hours")
    if not film.get("measured"):
        return _verdict("INSUFFICIENT_DATA", "LOW", "Nothing measured for this film yet.", {})
    if not baseline.get("has_baseline"):
        return _verdict(
            "INSUFFICIENT_DATA",
            "LOW",
            f"The channel has {baseline.get('sample_size', 0)} measured films; a baseline "
            f"needs {MINIMUM_BASELINE}. Until then a film is judged on editorial grounds, "
            "not against a median that does not exist.",
            {"sample_size": baseline.get("sample_size", 0)},
        )
    if age is None or age < MINIMUM_JUDGEMENT_HOURS:
        return _verdict(
            "INSUFFICIENT_DATA",
            "LOW",
            f"Published {age if age is not None else 'an unknown time'} hours ago; a verdict "
            f"waits for {MINIMUM_JUDGEMENT_HOURS:.0f}.",
            {"age_hours": age},
        )

    rate = film.get("views_per_hour")
    ratio = _ratio(rate, baseline.get("median_views_per_hour")) or _ratio(
        film.get("views"), baseline.get("median_views")
    )
    if ratio is None:
        return _verdict(
            "INSUFFICIENT_DATA", "LOW", "No comparable rate for this film.", {"ratio": None}
        )

    retention = film.get("average_view_percentage")
    median_retention = baseline.get("median_view_percentage")
    retention_ratio = _ratio(retention, median_retention)
    confidence = _confidence(int(baseline.get("sample_size") or 0), age)
    evidence = {
        "views_ratio_to_median": ratio,
        "retention_ratio_to_median": retention_ratio,
        "sample_size": baseline.get("sample_size"),
        "age_hours": age,
        "subscriber_conversion_percentage": film.get("subscriber_conversion_percentage"),
        "median_subscriber_conversion": baseline.get("median_subscriber_conversion"),
    }

    if ratio <= FAILED_RATIO and (retention_ratio is not None and retention_ratio < 0.7):
        return _verdict(
            "FAILED_EXPERIMENT",
            confidence,
            f"{ratio:.2f}x the channel's own view rate and {retention_ratio:.2f}x its "
            "retention: the film reached fewer people and held them less well.",
            evidence,
        )
    if ratio < UNDERPERFORMER_RATIO:
        return _verdict(
            "UNDERPERFORMER",
            confidence,
            f"{ratio:.2f}x the channel's own view rate.",
            evidence,
        )
    if ratio >= WINNER_RATIO and (retention_ratio is None or retention_ratio >= 1.0):
        return _verdict(
            "STRONG_WINNER",
            confidence,
            f"{ratio:.2f}x the channel's own view rate at or above its retention.",
            evidence,
        )
    if ratio >= PROMISING_RATIO:
        return _verdict(
            "PROMISING", confidence, f"{ratio:.2f}x the channel's own view rate.", evidence
        )
    return _verdict("NORMAL", confidence, f"{ratio:.2f}x the channel's own view rate.", evidence)


def _verdict(
    verdict: str, confidence: str, reason: str, evidence: dict[str, Any]
) -> dict[str, Any]:
    return {
        "verdict": verdict,
        "confidence": confidence,
        "reason": reason,
        "evidence": evidence,
    }


def diagnose(film: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Why a film underperformed, as far as the available numbers can say.

    Impressions and click-through separate "nobody was shown it" from "they were shown it and
    did not watch", which are two different assignments to two different departments. What the
    studio cannot see is where inside the film they left: YouTube's retention curve is not in
    the integration, so the honest answer names retention without pretending to localise it.
    """
    if not film.get("measured") or not baseline.get("has_baseline"):
        return {
            "kind": "INSUFFICIENT_DATA",
            "reason": "Not enough measured history to diagnose anything.",
            "assign_to": None,
            "evidence": {},
        }
    views_ratio = _ratio(film.get("views_per_hour"), baseline.get("median_views_per_hour"))
    retention_ratio = _ratio(
        film.get("average_view_percentage"), baseline.get("median_view_percentage")
    )
    conversion_ratio = _ratio(
        film.get("subscriber_conversion_percentage"),
        baseline.get("median_subscriber_conversion"),
    )
    ctr_ratio = _ratio(film.get("ctr_percentage"), baseline.get("median_ctr"))
    evidence = {
        "views_ratio": views_ratio,
        "retention_ratio": retention_ratio,
        "conversion_ratio": conversion_ratio,
        "ctr_ratio": ctr_ratio,
        "impressions": film.get("impressions"),
    }

    # Shown to few people, or shown and not clicked: a reach problem, not a story problem.
    if (ctr_ratio is not None and ctr_ratio < 0.7) or (
        film.get("impressions") == 0 and (film.get("views") or 0) < 10
    ):
        return {
            "kind": "REACH_FAILURE",
            "reason": (
                "The film was served but not chosen: click-through is below the channel's "
                "own median. The opening frame and the title are what a viewer chooses from."
            ),
            "assign_to": "VideoEditor",
            "evidence": evidence,
        }
    if retention_ratio is not None and retention_ratio < 0.8:
        return {
            "kind": "HOOK_OR_RETENTION_FAILURE",
            "reason": (
                "People were shown it and did not stay: retention is below the channel's own "
                "median. Where inside the film they left is not in the available analytics, "
                "so the opening and the pacing are what to test first."
            ),
            "assign_to": "ScriptWriter",
            "evidence": evidence,
        }
    if (
        conversion_ratio is not None
        and conversion_ratio < 0.6
        and (views_ratio or 0) >= UNDERPERFORMER_RATIO
    ):
        return {
            "kind": "CONVERSION_FAILURE",
            "reason": (
                "They watched and did not subscribe: the film worked and the channel's "
                "promise did not land. The ending and the closing question are where that is."
            ),
            "assign_to": "ScriptWriter",
            "evidence": evidence,
        }
    if views_ratio is not None and views_ratio < UNDERPERFORMER_RATIO:
        return {
            "kind": "TOPIC_FAILURE",
            "reason": (
                "Reach and retention are ordinary but the film found fewer people: the "
                "subject drew less interest than this channel's usual. One film is not a "
                "verdict on the category."
            ),
            "assign_to": "LeadResearcher",
            "evidence": evidence,
        }
    return {
        "kind": "INSUFFICIENT_DATA",
        "reason": "Nothing in the available numbers stands out as the cause.",
        "assign_to": None,
        "evidence": evidence,
    }


def channel_health(engine: Engine, channel_id: str) -> dict[str, Any]:
    """One channel, with the context a number needs: what changed, and how fast.

    "Subscribers: 10 500" says nothing. Beside the last seven days and the seven before them
    it says whether the channel is accelerating, which is the only version worth a decision.
    """
    films = video_performance(engine, channel_id)
    measured = [f for f in films if f["measured"]]
    recent = [f for f in measured if (f["age_hours"] or 1e9) <= 168]
    previous = [f for f in measured if 168 < (f["age_hours"] or 1e9) <= 336]

    def total(rows: list[dict[str, Any]], key: str) -> int | float | None:
        values = [r[key] for r in rows if isinstance(r.get(key), int | float)]
        return round(sum(values), 4) if values else None

    recent_views = total(recent, "views")
    previous_views = total(previous, "views")
    recent_subs = total(recent, "subscribers_gained")
    previous_subs = total(previous, "subscribers_gained")
    with Session(engine) as session:
        channel = session.get(ChannelRecord, channel_id)
        name = channel.channel_name if channel else channel_id
        kind = channel.channel_type if channel else None
    baseline = channel_baselines(engine, channel_id)
    return {
        "channel_id": channel_id,
        "channel_name": name,
        "channel_type": kind,
        "published": len(films),
        "measured": len(measured),
        "published_last_7_days": len(recent),
        "views_last_7_days": recent_views,
        "views_previous_7_days": previous_views,
        "views_change_percentage": (
            round((recent_views - previous_views) / previous_views * 100.0, 2)
            if isinstance(recent_views, int | float)
            and isinstance(previous_views, int | float)
            and previous_views
            else None
        ),
        "subscribers_last_7_days": recent_subs,
        "subscribers_previous_7_days": previous_subs,
        "cost_last_7_days": total(recent, "cost_usd"),
        "baseline": baseline,
        "note": (
            "nothing measured on this channel yet"
            if not measured
            else f"{len(measured)} measured films; deltas compare the last seven days with "
            "the seven before them"
        ),
    }


def growth_diagnosis(engine: Engine, channel_id: str) -> dict[str, Any]:
    """What is preventing faster growth on this channel, and who should act.

    The Owner's question, answered from the rows: not "we need more views" but which of reach,
    retention, conversion, consistency or evidence is the binding constraint right now. With
    no measured history the answer says so and points at the editorial route instead of
    inventing a cause.
    """
    health = channel_health(engine, channel_id)
    baseline = health["baseline"]
    films = [f for f in video_performance(engine, channel_id) if f["measured"]]
    if len(films) < MINIMUM_BASELINE:
        return {
            "channel_id": channel_id,
            "constraint": "NO_DATA",
            "confidence": "LOW",
            "reason": (
                f"{len(films)} measured films. Nothing about this audience is known yet, so "
                "growth is a matter of publishing good work and measuring it, not of "
                "optimising a number that does not exist."
            ),
            "assign_to": "LeadResearcher",
            "evidence": {"measured": len(films)},
        }

    judged = [diagnose(film, baseline) for film in films[:10]]
    counts: dict[str, int] = {}
    for entry in judged:
        counts[entry["kind"]] = counts.get(entry["kind"], 0) + 1
    worst = max(
        (k for k in counts if k != "INSUFFICIENT_DATA"),
        key=lambda k: counts[k],
        default=None,
    )
    if worst is None:
        return {
            "channel_id": channel_id,
            "constraint": "NONE_VISIBLE",
            "confidence": "MEDIUM",
            "reason": "No single cause repeats across the recent films.",
            "assign_to": None,
            "evidence": {"kinds": counts, "sample": len(judged)},
        }
    mapping = {
        "REACH_FAILURE": ("REACH", "VideoEditor"),
        "HOOK_OR_RETENTION_FAILURE": ("RETENTION", "ScriptWriter"),
        "CONVERSION_FAILURE": ("CONVERSION", "ScriptWriter"),
        "TOPIC_FAILURE": ("TOPIC_SELECTION", "LeadResearcher"),
    }
    constraint, role = mapping[worst]
    return {
        "channel_id": channel_id,
        "constraint": constraint,
        "confidence": "HIGH" if counts[worst] >= 3 else "MEDIUM",
        "reason": (
            f"{counts[worst]} of the last {len(judged)} measured films point at the same "
            f"cause: {worst.replace('_', ' ').lower()}."
        ),
        "assign_to": role,
        "evidence": {"kinds": counts, "sample": len(judged), "health": health["note"]},
    }


def anomalies(engine: Engine) -> list[dict[str, Any]]:
    """Unusual changes worth investigating, each with the numbers that make it unusual.

    An anomaly is not a verdict; it is a reason to look. Nothing here fires on a single film
    unless the change is large enough that ignoring it would be the strange choice.
    """
    found: list[dict[str, Any]] = []
    with Session(engine) as session:
        channel_ids = [row.id for row in session.scalars(select(ChannelRecord))]
    for channel_id in channel_ids:
        baseline = channel_baselines(engine, channel_id)
        if not baseline["has_baseline"]:
            continue
        films = [f for f in video_performance(engine, channel_id) if f["measured"]]
        recent = films[:3]
        retentions = [
            f["average_view_percentage"]
            for f in recent
            if isinstance(f.get("average_view_percentage"), int | float)
        ]
        if len(retentions) >= 3 and baseline["median_view_percentage"]:
            mean_recent = sum(retentions) / len(retentions)
            drop = (baseline["median_view_percentage"] - mean_recent) / baseline[
                "median_view_percentage"
            ]
            if drop >= 0.15:
                found.append(
                    {
                        "kind": "RETENTION_DROP",
                        "channel_id": channel_id,
                        "detail": (
                            f"the last three films averaged {mean_recent:.1f}% viewed against "
                            f"a median of {baseline['median_view_percentage']:.1f}%"
                        ),
                        "assign_to": "ScriptWriter",
                    }
                )
        for film in recent:
            ratio = _ratio(film.get("views_per_hour"), baseline["median_views_per_hour"])
            if ratio is not None and ratio >= WINNER_RATIO:
                found.append(
                    {
                        "kind": "VIEW_SPIKE",
                        "channel_id": channel_id,
                        "detail": f"«{film['title'][:60]}» is at {ratio:.1f}x the view rate",
                        "assign_to": "LeadResearcher",
                    }
                )
            if (
                isinstance(film.get("cost_usd"), int | float)
                and baseline["median_cost_usd"]
                and film["cost_usd"] >= baseline["median_cost_usd"] * 2
            ):
                found.append(
                    {
                        "kind": "COST_SPIKE",
                        "channel_id": channel_id,
                        "detail": (
                            f"«{film['title'][:60]}» cost {film['cost_usd']:.2f} USD against a "
                            f"median of {baseline['median_cost_usd']:.2f}"
                        ),
                        "assign_to": "VideoEditor",
                    }
                )
    return found
