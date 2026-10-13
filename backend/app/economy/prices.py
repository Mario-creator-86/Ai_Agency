"""Prices the Owner supplies, and the cost of a call computed from them.

Measured on a copy of the live database (2026-09-18): 391 `agent_run` rows on Ollama Cloud
with `cost_vr` NULL, because every LLM adapter said "local, no cost"; nine ElevenLabs models
with `pricing {}`, so a render's narration was "unpriced" in every budget. The books could
not see the cost of a day because nobody had told them what a token or a character costs.

A `ProviderPrice` is that fact, typed by the Owner (`PUT /economy/prices`) and nowhere
else: no agent, no search result and no vendor page can write one. Each row names the
provider kind, the resource (a model id, or ``"*"`` for every resource of the kind), the
unit the vendor bills in, the price in USD micros and where it came from. The adapters read
it through a plain callable — resource and unit in, micros out — and multiply by what they
measured: tokens counted by the provider, characters actually sent. When no price covers
what a call used, the cost is None, as it always was, never zero: half a price would
understate a run and teach the budget to trust a figure that is missing a side.

A DOCUMENTED default may be seeded for ElevenLabs from its public price list, marked as
such, so narration is never read as free while the Owner has not typed his plan. Ollama
Cloud prices are never seeded: the Owner's plan is the only source, and a guess in the
books is worse than a gap the Accountant reports.

A resource is a model id, a family (a prefix ending in ``"*"``, such as
``"eleven_flash_*"``), or ``"*"`` for the whole kind. Any price the Owner typed outranks every
DOCUMENTED one, however specific; within each, the model's own row outranks its family, the
longer family the shorter, and the family the kind's ``"*"``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db import lock_for_write
from app.economy.models import MICROS, PRICE_PROVENANCES, PRICE_UNITS, ProviderPrice
from app.economy.services import EconomyError, format_micros, to_micros
from app.services import append_event, command_hash, recall_command, remember_command, utc_now

#: A price lookup an adapter holds: ``(resource, unit) -> usd_micros | None``. A callable
#: rather than an engine so the adapters stay free of the database and a test can hand one a
#: table.
PriceLookup = Callable[[str, str], int | None]

#: The resource that prices every resource of a kind that has no row of its own.
ANY_RESOURCE = "*"


class PriceCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    provider_kind: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_-]*$")
    #: A model id, a family ending in «*», or «*». Something besides blanks: a resource of
    #: spaces was a 409 conflict with an English sentence until W34, and is a field the price
    #: form marks, like every other malformed field (422, ``loc`` = ["body", "resource"]).
    resource: str = Field(min_length=1, max_length=200, pattern=r"\S")
    unit: str = Field(pattern="^(" + "|".join(PRICE_UNITS) + ")$")
    #: The price in USD for one unit, as a decimal string; "0" records that a unit is free
    #: (a local model), which is a fact, unlike a missing row.
    usd: str = Field(pattern=r"^\d{1,9}(\.\d{1,6})?$", max_length=20)
    provenance: str = Field(default="OWNER", pattern="^(" + "|".join(PRICE_PROVENANCES) + ")$")
    #: The version the Owner believes he is replacing; a stale one is refused, like the
    #: publish policy's. Optional, because the first price has nothing to replace.
    expected_version: int | None = Field(default=None, ge=1)
    notes: str | None = Field(default=None, max_length=2000)


def _view(row: ProviderPrice) -> dict[str, Any]:
    return {
        "id": row.id,
        "provider_kind": row.provider_kind,
        "resource": row.resource,
        "unit": row.unit,
        "usd": format_micros(row.usd_micros),
        "usd_micros": row.usd_micros,
        "provenance": row.provenance,
        "version": row.version,
        "active": bool(row.active),
        "set_by": row.set_by,
        "notes": row.notes,
        "set_at": row.set_at,
        "replaced_at": row.replaced_at,
    }


def set_price(
    engine: Engine,
    command: PriceCommand,
    *,
    set_by: str = "owner",
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Set the price of one unit of one resource. The previous price is kept, replaced.

    Idempotent by command id: the same command again returns the original answer; the same
    id with another figure is a conflict, because guessing which was meant is not on offer.
    """
    correlation = correlation_id or str(uuid4())
    resource = command.resource.strip()
    if not resource:
        raise EconomyError("Numește modelul (sau familia de modele) pentru care este prețul.")
    usd_micros = to_micros(command.usd)
    fingerprint = command_hash(
        {
            "provider_kind": command.provider_kind,
            "resource": resource,
            "unit": command.unit,
            "usd": command.usd,
            "provenance": command.provenance,
            "expected_version": command.expected_version,
            "notes": (command.notes or "").strip(),
        }
    )
    with Session(engine) as session, session.begin():
        # A reader that will write: the lock first, so two Owners' tabs cannot both make
        # version 2 (the unique constraint would refuse one with an error, not an answer).
        lock_for_write(session)
        already = recall_command(session, str(command.command_id), fingerprint)
        if already is not None:
            return already
        current = session.scalar(
            select(ProviderPrice).where(
                ProviderPrice.provider_kind == command.provider_kind,
                ProviderPrice.resource == resource,
                ProviderPrice.unit == command.unit,
                ProviderPrice.active.is_(True),
            )
        )
        if command.expected_version is not None:
            actual = current.version if current is not None else None
            if actual != command.expected_version:
                raise EconomyError(
                    f"Prețul are versiunea {actual if actual is not None else 'nesetată'}, "
                    f"nu {command.expected_version}; recitește-l înainte să-l schimbi."
                )
        now = utc_now()
        version = 1
        if current is not None:
            current.active = False
            current.replaced_at = now
            version = int(current.version) + 1
        row = ProviderPrice(
            id=str(uuid4()),
            provider_kind=command.provider_kind,
            resource=resource,
            unit=command.unit,
            usd_micros=usd_micros,
            provenance=command.provenance,
            version=version,
            active=True,
            set_by=set_by[:100],
            notes=(command.notes or "").strip()[:2000] or None,
            set_at=now,
        )
        session.add(row)
        session.flush()
        event = append_event(
            session,
            "economy.price_set",
            "provider_price",
            row.id,
            version,
            {
                "provider_kind": row.provider_kind,
                "resource": row.resource,
                "unit": row.unit,
                "usd": format_micros(usd_micros),
                "was_usd": format_micros(current.usd_micros) if current is not None else None,
                "provenance": row.provenance,
                "set_by": set_by,
            },
            correlation,
        )
        row.event_id = event.event_id
        view = _view(row)
        remember_command(session, str(command.command_id), "SetProviderPrice", fingerprint, view)
        return view


def list_prices(
    engine: Engine, *, provider_kind: str | None = None, active_only: bool = True
) -> list[dict[str, Any]]:
    query = select(ProviderPrice).order_by(
        ProviderPrice.provider_kind,
        ProviderPrice.resource,
        ProviderPrice.unit,
        ProviderPrice.version,
    )
    if provider_kind:
        query = query.where(ProviderPrice.provider_kind == provider_kind)
    if active_only:
        query = query.where(ProviderPrice.active.is_(True))
    with Session(engine) as session:
        return [_view(row) for row in session.scalars(query)]


def _specificity(pattern: str, resource: str) -> int | None:
    """How closely a price's resource names this one: the length of what it matched, the
    exact id above every family, or None when it does not cover the resource at all."""
    if pattern == resource:
        return len(resource) + 1
    if pattern.endswith(ANY_RESOURCE) and resource.startswith(pattern[: -len(ANY_RESOURCE)]):
        return len(pattern) - len(ANY_RESOURCE)
    return None


def price_row(
    session: Session, provider_kind: str, resource: str, unit: str
) -> ProviderPrice | None:
    """The active price that covers this resource: the Owner's before any DOCUMENTED one,
    and within each the most specific - the model, its longest family, the kind's '*'.

    The provenance comes first because a documented family row is more specific than the
    Owner's '*' and would otherwise overrule the plan he typed with a price-list figure.
    """
    rows = session.scalars(
        select(ProviderPrice).where(
            ProviderPrice.provider_kind == provider_kind,
            ProviderPrice.unit == unit,
            ProviderPrice.active.is_(True),
        )
    ).all()
    ranked = [
        (row.provenance != "DOCUMENTED", specificity, row)
        for row in rows
        if (specificity := _specificity(str(row.resource), resource)) is not None
    ]
    if not ranked:
        return None
    return max(ranked, key=lambda item: (item[0], item[1]))[2]


def price_for(session: Session, provider_kind: str, resource: str, unit: str) -> int | None:
    row = price_row(session, provider_kind, resource, unit)
    return int(row.usd_micros) if row is not None else None


def price_lookup(engine: Engine, provider_kind: str) -> PriceLookup:
    """The lookup an adapter of this kind holds. One short read per call; a price the
    Owner types this afternoon costs this evening's runs without a restart."""

    def lookup(resource: str, unit: str) -> int | None:
        with Session(engine) as session:
            return price_for(session, provider_kind, resource, unit)

    return lookup


# ----------------------------------------------------------------------------- the arithmetic


def _cost(micros: int) -> str:
    """Micros as the decimal string `cost_vr` stores; at most six decimals, trailing zeros cut."""
    return format_micros(micros)


def llm_cost_vr(
    lookup: PriceLookup | None,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> str | None:
    """What a generation cost, from the tokens the provider counted and the prices per
    million. Both sides must be priced and both counts known; otherwise None — a run
    priced on one side only would be read by the budget as cheaper than it was."""
    if lookup is None or prompt_tokens is None or completion_tokens is None:
        return None
    per_input = lookup(model, "per_1m_input_tokens")
    per_output = lookup(model, "per_1m_output_tokens")
    if per_input is None or per_output is None:
        return None
    # Integer arithmetic in micros, rounded half up on the last micro: a cost row is money.
    total = int(prompt_tokens) * per_input + int(completion_tokens) * per_output
    return _cost((total + 500_000) // MICROS)


def tts_cost_vr(lookup: PriceLookup | None, model: str, characters: int) -> str | None:
    """What a narration cost: the characters sent at the per-thousand price of the model."""
    if lookup is None or characters <= 0:
        return None
    per_1k = lookup(model, "per_1k_characters")
    if per_1k is None:
        return None
    return _cost((int(characters) * per_1k + 500) // 1000)


def usd_from_micros(micros: int) -> float:
    return micros / MICROS


# ----------------------------------------------------------------------------- documented seed


def seed_documented_prices(engine: Engine, *, correlation_id: str | None = None) -> dict[str, Any]:
    """Seed the documented defaults (`integrations.catalog.DOCUMENTED_PRICES`), marked
    DOCUMENTED, where no price of any provenance exists for the resource and unit. Never
    overrides a row the Owner typed, and seeds nothing his own '*' for the unit already
    outranks, since `price_row` would never read it; running it twice adds nothing."""
    from app.integrations.catalog import DOCUMENTED_PRICES  # noqa: PLC0415

    correlation = correlation_id or str(uuid4())
    seeded: list[dict[str, Any]] = []
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        now = utc_now()
        for entry in DOCUMENTED_PRICES:
            exists = session.scalar(
                select(ProviderPrice).where(
                    ProviderPrice.provider_kind == entry["provider_kind"],
                    ProviderPrice.resource == entry["resource"],
                    ProviderPrice.unit == entry["unit"],
                )
            )
            if exists is not None:
                continue
            owners_wildcard = session.scalar(
                select(ProviderPrice.id).where(
                    ProviderPrice.provider_kind == entry["provider_kind"],
                    ProviderPrice.resource == ANY_RESOURCE,
                    ProviderPrice.unit == entry["unit"],
                    ProviderPrice.active.is_(True),
                    ProviderPrice.provenance != "DOCUMENTED",
                )
            )
            if owners_wildcard is not None:
                continue
            row = ProviderPrice(
                id=str(uuid4()),
                provider_kind=entry["provider_kind"],
                resource=entry["resource"],
                unit=entry["unit"],
                usd_micros=to_micros(entry["usd"]),
                provenance="DOCUMENTED",
                version=1,
                active=True,
                set_by="seed",
                notes=entry["notes"],
                set_at=now,
            )
            session.add(row)
            session.flush()
            event = append_event(
                session,
                "economy.price_set",
                "provider_price",
                row.id,
                1,
                {
                    "provider_kind": row.provider_kind,
                    "resource": row.resource,
                    "unit": row.unit,
                    "usd": entry["usd"],
                    "provenance": "DOCUMENTED",
                    "set_by": "seed",
                },
                correlation,
            )
            row.event_id = event.event_id
            seeded.append(_view(row))
    return {"seeded": len(seeded), "prices": seeded}
