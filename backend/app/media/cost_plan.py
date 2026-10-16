"""What a film will cost before a credit is spent: the published table and pure arithmetic.

The Nepal film (2026-09-26) cost over a thousand credits while the books said 0.74 USD: the
price Runway sent back was never read, and nothing priced a film from the vendor's own table
before buying it. This module is that table and nothing else. It reads
``config/runway_prices.json`` (each row with the page it was read from, the day it was read
and whether it is DOCUMENTED or MEASURED) and does arithmetic: no database, no network, so the
shooting sheet can price a whole film at zero credits.

Three rules shape the numbers:

* A span is billed at the whole seconds the request will ask for, rounded UP to the smallest
  length the model accepts (seedance 4..30, veo 4/6/8). 4.4 s is a 5 s shot; rounding down is
  what froze frames under the Nepal dissolves.
* The model is chosen PER SCENE (Owner, 2026-09-27: "Nu trebuie un singur model pe tot filmul!
  Trebuie sa optimizam costurile!"). A film costs the sum of its scenes' own choices, and the
  plan says how much that saved against the premium model everywhere.
* A model or resolution the table does not list is unpriced, never guessed: ``UnpricedError``.

What the account was actually charged outranks the page. ``attribute_measured_credits`` shares
a measured balance drop across what was bought, and ``apply_measured`` lays those MEASURED rows
over the documented table without changing it; ``app.economy.credits`` writes them back.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import ROOT

PRICE_FILE = ROOT / "config" / "runway_prices.json"

#: A published price older than this is shown to the Owner as "nevalidat".
STALE_AFTER_DAYS = 30
DOCUMENTED = "DOCUMENTED"
MEASURED = "MEASURED"
#: The studio's own forecast, not a vendor's published tariff: RunPod Serverless is priced
#: from estimated GPU-seconds x the budget rate (config/runpod_models.json) until the paid
#: bake-off measures it. The Owner reads it as an estimate, never as «tarif publicat».
ESTIMATED = "ESTIMATED"

#: The stills every LIVE scene buys before any motion: ONE candidate at 2K (1530:2720).
#: Two until 2026-10-15 21:10Z — the Owner, watching the Speed of Light film buy ten images
#: for five scenes: «ne costă bani pentru că facem câte două imagini, vreau să facem doar 1».
#: The prompt is approved by the Director before the purchase, so one picture is the bet; a
#: refused one is redone on a reviewed prompt under the renders cap, never bought twice blind.
STILLS_MODEL = "seedream5_pro"
STILLS_RESOLUTION = "2K"
STILL_CANDIDATES = 1

#: What "the premium model everywhere" means when the plan reports its saving.
PREMIUM_REFERENCE = ("seedance2_5", "1080p")

#: The whole-film alternatives the sheet prices side by side. ``None`` keeps each scene's
#: own model and changes only the resolution.
ALTERNATIVES: tuple[tuple[str | None, str], ...] = (
    (None, "720p"),
    ("seedance2", "1080p"),
    ("veo3.1_fast", "1080p"),
)

#: Scene kinds composed locally: no still, no motion, no credit.
LIVE = "LIVE"

#: How much longer than its clip a shot may be and still be filled by slowing the clip down
#: locally at assembly (the Owner's «Încetinește local», 2026-10-09: a 5.0 s clip covers a
#: span of up to 6.25 s). Here because the planner prices a scene longer than its model's
#: longest clip at that clip when the slow-down fills it (`slowed_clip_seconds`); the
#: assembler, which does the slowing, reads the same number.
SLOWDOWN_ALLOWANCE = 0.25

_EPSILON = 1e-9


class UnpricedError(ValueError):
    """The table cannot price this: an unknown model, resolution or length. Never a guess."""


@dataclass(frozen=True)
class PriceRow:
    model_id: str
    kind: str  # "video" | "image"
    resolution: str  # "*" when the page gives one price for every resolution
    source_url: str
    date: str  # ISO day the price was read or measured
    provenance: str  # DOCUMENTED | MEASURED | ESTIMATED
    credits_per_second: float | None = None
    credits_per_second_audio: float | None = None
    credits_per_image: float | None = None
    minimum_credits: int = 0
    documented_credits_per_second: float | None = None
    documented_credits_per_image: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PriceTable:
    credit_usd: float
    rows: tuple[PriceRow, ...]
    seconds: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    stills_model: str = STILLS_MODEL
    #: What one paid ROUND costs besides its items, per purpose ("image", "video"): on RunPod
    #: Serverless a round is one batch job whose worker loads its models (the cold start) and
    #: idles 1 s before it scales to zero, all billed (`providers.runpod.pricing`). Empty for a
    #: vendor that bills per item only (Runway): 0.
    overhead_credits_per_round: Mapping[str, float] = field(default_factory=dict)
    #: The models whose purchases are priced per round (their overhead applies), e.g. the
    #: RunPod catalogue; a Runway model of the same table never carries it.
    round_models: frozenset[str] = frozenset()

    def round_overhead(self, purpose: str, model_id: str | None) -> int:
        """Whole credits one round of ``model_id`` adds (0 for a per-item vendor)."""
        if model_id is None or model_id not in self.round_models:
            return 0
        return _credits(float(self.overhead_credits_per_round.get(purpose) or 0.0))

    def row(self, model_id: str, resolution: str) -> PriceRow:
        """The row for this model at this resolution, or its any-resolution row."""
        for wanted in (resolution, "*"):
            for row in self.rows:
                if row.model_id == model_id and row.resolution == wanted:
                    return row
        raise UnpricedError(f"{model_id} la {resolution}: niciun preț publicat în tabel")


def _row_from_json(raw: Mapping[str, Any]) -> PriceRow:
    per_second = raw.get("credits_per_second")
    per_image = raw.get("credits_per_image")
    return PriceRow(
        model_id=str(raw["model_id"]),
        kind=str(raw.get("kind") or ("image" if per_image is not None else "video")),
        resolution=str(raw.get("resolution") or "*"),
        source_url=str(raw["source_url"]),
        date=str(raw["date"]),
        provenance=str(raw.get("provenance") or DOCUMENTED),
        credits_per_second=None if per_second is None else float(per_second),
        credits_per_second_audio=(
            None
            if raw.get("credits_per_second_audio") is None
            else float(raw["credits_per_second_audio"])
        ),
        credits_per_image=None if per_image is None else float(per_image),
        minimum_credits=int(raw.get("minimum_credits") or 0),
        documented_credits_per_second=(
            None
            if raw.get("documented_credits_per_second", per_second) is None
            else float(raw.get("documented_credits_per_second", per_second))
        ),
        documented_credits_per_image=(
            None
            if raw.get("documented_credits_per_image", per_image) is None
            else float(raw.get("documented_credits_per_image", per_image))
        ),
    )


@lru_cache(maxsize=4)
def _load(path: str) -> PriceTable:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return PriceTable(
        credit_usd=float(raw["credit_usd"]),
        rows=tuple(_row_from_json(row) for row in raw["rows"]),
        seconds={str(k): dict(v) for k, v in (raw.get("seconds") or {}).items()},
    )


def load_price_table(path: Path | None = None) -> PriceTable:
    """The published table. Immutable; a measured overlay is a new table."""
    return _load(str(path or PRICE_FILE))


def _table(table: PriceTable | None) -> PriceTable:
    return table if table is not None else load_price_table()


# ------------------------------------------------------------------------ seconds and prices


def billable_seconds(
    model_id: str,
    seconds: float,
    *,
    table: PriceTable | None = None,
    contract: Mapping[str, Any] | None = None,
) -> int:
    """The whole seconds the request will ask for: rounded UP to a length the model accepts.

    ``contract`` (``{"min", "max"}`` or ``{"values"}``) is the live model contract when the
    caller has it; otherwise the documented rule in the table; otherwise any whole second.
    """
    whole = max(1, math.ceil(float(seconds) - _EPSILON))
    rule = contract if contract is not None else _table(table).seconds.get(model_id)
    if not rule:
        return whole
    values = rule.get("values")
    if values:
        legal = sorted(int(v) for v in values if int(v) >= whole)
        if not legal:
            raise UnpricedError(
                f"{model_id} nu acceptă {whole} s într-un singur cadru "
                f"(lungimi: {', '.join(str(int(v)) for v in values)})"
            )
        return legal[0]
    low = int(rule.get("min") or 1)
    high = rule.get("max")
    whole = max(whole, low)
    if high is not None and whole > int(high):
        raise UnpricedError(f"{model_id} nu acceptă {whole} s într-un singur cadru (max {high})")
    return whole


def longest_seconds(
    model_id: str,
    *,
    table: PriceTable | None = None,
    contract: Mapping[str, Any] | None = None,
) -> int | None:
    """The longest single clip the model accepts (its contract's ``max``, or its longest
    ``values``), read like `billable_seconds` reads it; None when the rule sets no maximum."""
    rule = contract if contract is not None else _table(table).seconds.get(model_id)
    if not rule:
        return None
    values = rule.get("values")
    if values:
        return max(int(v) for v in values)
    high = rule.get("max")
    return int(high) if high is not None else None


def slowed_clip_seconds(
    model_id: str,
    seconds: float,
    *,
    table: PriceTable | None = None,
    contract: Mapping[str, Any] | None = None,
) -> int | None:
    """The clip to buy for a shot of ``seconds`` longer than the model's longest clip: that
    longest clip, when slowed down locally by at most SLOWDOWN_ALLOWANCE it fills the shot;
    None when even that is too short (or the model has no maximum).

    2026-10-10 (film «How NASA Keeps a Space Telescope Alive With Frozen Fuel»): scenes 3 and
    4 needed 11.1 s and 12.5 s of LTX-2.5, whose clips end at 10 s. The sheet held them for the
    Owner while the steps bought the other scenes' stills, test shot and clips, and the film
    could never be assembled. A 10 s clip slowed by 25% fills 12.5 s at 0 USD, so that is the
    clip the planner prices and the step buys."""
    longest = longest_seconds(model_id, table=table, contract=contract)
    if longest is None or float(seconds) > longest * (1.0 + SLOWDOWN_ALLOWANCE) + _EPSILON:
        return None
    return longest


def _credits(amount: float) -> int:
    """Credits are whole; a fractional (measured) rate is rounded up, never down."""
    return math.ceil(amount - _EPSILON)


def price_shot(
    model_id: str,
    resolution: str,
    seconds: float,
    *,
    audio: bool = False,
    table: PriceTable | None = None,
    contract: Mapping[str, Any] | None = None,
) -> int:
    """Credits for one generated shot of ``seconds`` at ``resolution``."""
    prices = _table(table)
    row = prices.row(model_id, resolution)
    rate = row.credits_per_second_audio if audio else row.credits_per_second
    if audio and rate is None:
        # The page gives one price, audio or not.
        rate = row.credits_per_second
    if rate is None:
        raise UnpricedError(f"{model_id} nu are preț pe secundă în tabel")
    billed = billable_seconds(model_id, seconds, table=prices, contract=contract)
    return max(_credits(rate * billed), row.minimum_credits)


def price_still(
    model_id: str, resolution: str, count: int, *, table: PriceTable | None = None
) -> int:
    """Credits for ``count`` generated images at ``resolution``."""
    row = _table(table).row(model_id, resolution)
    if row.credits_per_image is None:
        raise UnpricedError(f"{model_id} nu are preț pe imagine în tabel")
    return _credits(row.credits_per_image * int(count))


def credits_to_micros(credits: float, credit_usd: float) -> int:
    """Credits to USD micros, exactly (Decimal, half up), like every amount in the books."""
    micros = Decimal(str(credits)) * Decimal(str(credit_usd)) * Decimal(1_000_000)
    return int(micros.quantize(Decimal(1), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------- how old is a price


def row_status(row: PriceRow, *, today: date | None = None) -> str:
    """'validat' within 30 days of the day the price was read or measured, else 'nevalidat'."""
    day = today or date.today()
    age = (day - date.fromisoformat(row.date)).days
    return "nevalidat" if age > STALE_AFTER_DAYS else "validat"


def source_label(row: PriceRow, *, today: date | None = None) -> str:
    """What the Owner reads beside a price: 'tarif publicat 26.09', 'măsurat' or 'nevalidat'."""
    if row_status(row, today=today) == "nevalidat":
        return "nevalidat"
    if row.provenance == MEASURED:
        return "măsurat"
    if row.provenance == ESTIMATED:
        return f"estimare GPU nemăsurată {date.fromisoformat(row.date):%d.%m}"
    return f"tarif publicat {date.fromisoformat(row.date):%d.%m}"


def _film_source(rows: Iterable[PriceRow], today: date | None) -> str:
    used = list(rows)
    if not used:
        return ""
    labels = [source_label(row, today=today) for row in used]
    if "nevalidat" in labels:
        return "nevalidat"
    documented = [row for row in used if row.provenance != MEASURED]
    if not documented:
        return "măsurat"
    oldest = min(documented, key=lambda row: row.date)
    return source_label(oldest, today=today)


# ------------------------------------------------------------------------------ a whole film


def _scenes(
    scenes: Sequence[float | Mapping[str, Any]],
    model_id: str | None,
    resolution: str | None,
) -> list[dict[str, Any]]:
    normalised: list[dict[str, Any]] = []
    for position, scene in enumerate(scenes, start=1):
        base: dict[str, Any] = {
            "scene_index": position,
            "kind": LIVE,
            "model_id": model_id,
            "resolution": resolution,
            "audio": False,
            "hero": False,
        }
        if isinstance(scene, Mapping):
            base.update({k: v for k, v in scene.items() if v is not None})
        else:
            base["seconds"] = float(scene)
        base["kind"] = str(base.get("kind") or LIVE).upper()
        normalised.append(base)
    return normalised


def _price_scenes(
    scenes: list[dict[str, Any]],
    table: PriceTable,
    *,
    stills_model: str,
    stills_resolution: str,
    candidates: int,
    override: tuple[str | None, str] | None = None,
) -> tuple[list[dict[str, Any]], list[PriceRow]]:
    priced: list[dict[str, Any]] = []
    used: list[PriceRow] = []
    for scene in scenes:
        entry = {
            "scene_index": int(scene["scene_index"]),
            "kind": scene["kind"],
            "seconds": float(scene.get("seconds") or 0.0),
            "hero": False,
        }
        if scene["kind"] != LIVE:
            entry.update(
                model_id=None, resolution=None, billed_seconds=0, credits=0, still_credits=0
            )
            priced.append(entry)
            continue
        model = scene.get("model_id")
        resolution = scene.get("resolution")
        if override is not None:
            model = override[0] or model
            resolution = override[1]
        if not model or not resolution:
            raise UnpricedError(f"scena {entry['scene_index']} nu are model sau rezoluție")
        row = table.row(str(model), str(resolution))
        still_row = table.row(stills_model, stills_resolution)
        used.extend((row, still_row))
        entry.update(
            model_id=str(model),
            resolution=str(resolution),
            billed_seconds=billable_seconds(str(model), entry["seconds"], table=table),
            credits=price_shot(
                str(model),
                str(resolution),
                entry["seconds"],
                audio=bool(scene.get("audio")),
                table=table,
            ),
            still_credits=price_still(stills_model, stills_resolution, candidates, table=table),
            price_source=source_label(row),
        )
        priced.append(entry)
    return priced, used


def plan_film(
    scenes: Sequence[float | Mapping[str, Any]],
    *,
    model_id: str | None = None,
    resolution: str | None = None,
    table: PriceTable | None = None,
    stills_model: str = STILLS_MODEL,
    stills_resolution: str = STILLS_RESOLUTION,
    candidates: int | None = None,
    premium: tuple[str, str] = PREMIUM_REFERENCE,
    alternatives: Sequence[tuple[str | None, str]] = ALTERNATIVES,
    today: date | None = None,
) -> dict[str, Any]:
    """The money staircase of one film: stills, then the hero test shot, then the rest.

    ``scenes`` are either spans in seconds (every one LIVE on ``model_id`` at ``resolution``)
    or one mapping per scene: ``{scene_index, seconds, kind, model_id, resolution, audio,
    hero}``. Each LIVE scene carries its OWN model; a card or black scene costs nothing. The
    hero is the scene marked ``hero``, else the first LIVE scene; it is kept in the film.

    The hard cap is the total plus one full redo of the dearest single shot plus one more
    round of stills: the most the motion loop may ever spend on this sheet.
    """
    prices = _table(table)
    normalised = _scenes(scenes, model_id, resolution)

    def price(override: tuple[str | None, str] | None) -> tuple[list[dict[str, Any]], list]:
        return _price_scenes(
            normalised,
            prices,
            stills_model=stills_model,
            stills_resolution=stills_resolution,
            # Read when the plan is made, not when this function was defined: a default
            # bound at import kept 2 after the Owner's one still per scene (2026-10-15).
            candidates=STILL_CANDIDATES if candidates is None else candidates,
            override=override,
        )

    priced, used = price(None)

    live = [scene for scene in priced if scene["kind"] == LIVE]
    marked = [
        scene
        for scene, raw in zip(priced, normalised, strict=True)
        if scene["kind"] == LIVE and raw.get("hero")
    ]
    hero: dict[str, Any] | None = (marked or live)[0] if (marked or live) else None
    if hero is not None:
        hero["hero"] = True

    stills = sum(int(scene["still_credits"]) for scene in live)
    hero_credits = int(hero["credits"]) if hero is not None else 0
    motion = sum(int(scene["credits"]) for scene in live)
    total = stills + motion
    dearest = max((int(scene["credits"]) for scene in live), default=0)
    cap = total + dearest + stills if live else 0
    models = sorted({str(scene["model_id"]) for scene in live})

    def whole_film(override: tuple[str | None, str]) -> int:
        again, _ = price(override)
        return sum(int(s["credits"]) + int(s["still_credits"]) for s in again)

    offered: list[dict[str, Any]] = []
    for alt_model, alt_resolution in alternatives if live else ():
        if all(
            (alt_model or scene["model_id"]) == scene["model_id"]
            and alt_resolution == scene["resolution"]
            for scene in live
        ):
            continue
        try:
            alt_total = whole_film((alt_model, alt_resolution))
        except UnpricedError:
            continue
        offered.append(
            {
                "model_id": alt_model or (models[0] if len(models) == 1 else "mixt"),
                "resolution": alt_resolution,
                "total_credits": alt_total,
                "total_usd_micros": credits_to_micros(alt_total, prices.credit_usd),
            }
        )

    try:
        premium_total = whole_film(premium) if live else 0
    except UnpricedError:
        premium_total = total

    def usd(credits: int) -> int:
        return credits_to_micros(credits, prices.credit_usd)

    return {
        "scenes": priced,
        "model_id": None if not models else models[0] if len(models) == 1 else "mixt",
        "models": models,
        "hero_scene": hero["scene_index"] if hero is not None else None,
        "stills_credits": stills,
        "hero_credits": hero_credits,
        "rest_credits": motion - hero_credits,
        "total_credits": total,
        "cap_credits": cap,
        "stills_usd_micros": usd(stills),
        "hero_usd_micros": usd(hero_credits),
        "rest_usd_micros": usd(motion - hero_credits),
        "total_usd_micros": usd(total),
        "cap_usd_micros": usd(cap),
        "premium_credits": premium_total,
        "saved_credits": max(0, premium_total - total),
        "credit_usd": prices.credit_usd,
        "price_source": _film_source(used, today),
        "alternatives": offered,
    }


# ------------------------------------------------------------- measured over documented


def attribute_measured_credits(
    measured_credits: float,
    takes: Sequence[Mapping[str, Any]],
    *,
    table: PriceTable | None = None,
    measured_on: date | None = None,
) -> dict[str, Any]:
    """Share a measured balance drop across what was bought, and make MEASURED rows of it.

    ``takes`` are ``{"kind": "still", model_id, resolution, count}`` or
    ``{"kind": "motion"|"test_shot", model_id, resolution, seconds, audio}``. With one model
    and resolution bought the drop is its price exactly; with several it is shared in
    proportion to the published prices, and said to be (``attribution: proportional``).
    """
    prices = _table(table)
    day = (measured_on or date.today()).isoformat()
    groups: dict[tuple[str, str, str, bool], dict[str, Any]] = {}
    for take in takes:
        model, resolution = str(take["model_id"]), str(take["resolution"])
        if str(take.get("kind")) == "still":
            key = ("image", model, resolution, False)
            quoted = price_still(model, resolution, int(take.get("count") or 1), table=prices)
            units = float(int(take.get("count") or 1))
        else:
            audio = bool(take.get("audio"))
            key = ("video", model, resolution, audio)
            seconds = float(take["seconds"])
            quoted = price_shot(model, resolution, seconds, audio=audio, table=prices)
            units = float(billable_seconds(model, seconds, table=prices))
        group = groups.setdefault(key, {"quoted": 0, "units": 0.0})
        group["quoted"] += quoted
        group["units"] += units

    total_quoted = sum(int(g["quoted"]) for g in groups.values())
    result: dict[str, Any] = {
        "measured_credits": float(measured_credits),
        "quoted_credits": total_quoted,
        "attribution": "exact" if len(groups) == 1 else "proportional",
        "rows": [],
        "shares": [],
    }
    if total_quoted <= 0 or measured_credits <= 0:
        return result

    rows: list[PriceRow] = []
    for (kind, model, resolution, audio), group in groups.items():
        share = float(measured_credits) * int(group["quoted"]) / total_quoted
        rate = share / float(group["units"]) if group["units"] else 0.0
        documented = prices.row(model, resolution)
        changes: dict[str, Any] = {"provenance": MEASURED, "date": day}
        if kind == "image":
            changes["credits_per_image"] = rate
        elif audio:
            changes["credits_per_second_audio"] = rate
        else:
            changes["credits_per_second"] = rate
        rows.append(replace(documented, **changes))
        result["shares"].append(
            {
                "kind": kind,
                "model_id": model,
                "resolution": resolution,
                "audio": audio,
                "quoted_credits": int(group["quoted"]),
                "measured_credits": round(share, 4),
                "units": group["units"],
            }
        )
    result["rows"] = rows
    return result


def apply_measured(table: PriceTable, rows: Iterable[PriceRow]) -> PriceTable:
    """A new table with MEASURED rows laid over the documented ones they measured."""
    measured = {(row.model_id, row.resolution, row.kind): row for row in rows}
    merged = tuple(
        measured.pop((row.model_id, row.resolution, row.kind), row) for row in table.rows
    )
    return replace(table, rows=merged + tuple(measured.values()))
