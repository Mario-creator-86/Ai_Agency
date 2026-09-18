"""Phase 11 routes: record real financial evidence, mint VR$ from it, read the books.

Every route is Owner-only. That is not a convenience: `66_VIRTUAL_REAL_ECONOMY_ENGINE.md` says
minting is a controlled ledger event and not an LLM action, so no agent-facing path exists here
at all — an agent cannot reach these endpoints because they require the Owner credential.

There is deliberately no endpoint that pays anyone, buys anything, or contacts a payment
provider. Recording that money arrived is the whole surface.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.economy.accountant import AccountantError, daily_figures, reconcile_day
from app.economy.budget import BudgetCommand, budget_status, set_budget
from app.economy.prices import PriceCommand, list_prices, set_price
from app.economy.services import (
    EconomyError,
    ReconciliationCommand,
    bill_provider_cost,
    list_accounts,
    list_evidence,
    list_owner_funding,
    list_provider_costs,
    list_reconciliations,
    list_transactions,
    mint_from_evidence,
    reconcile_provider_invoice,
    record_fx_snapshot,
    record_owner_funding,
    record_provider_cost,
    record_revenue_evidence,
    reverse_transaction,
    settle_evidence,
    treasury_snapshot,
)
from app.security import require_owner
from app.services import CommandConflict

#: Amounts arrive as strings so an exact decimal never passes through a float on the way in.
AMOUNT = Annotated[str, Field(pattern=r"^\d{1,12}(\.\d{1,6})?$", max_length=20)]
CURRENCY = Annotated[str, Field(pattern=r"^[A-Za-z]{3}$")]
UUID36 = Annotated[str, Path(min_length=36, max_length=36)]


class FXCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    base_currency: CURRENCY
    quote_currency: CURRENCY = "USD"
    rate: AMOUNT
    source: str = Field(min_length=1, max_length=120)
    observed_at: str = Field(min_length=4, max_length=40)


class EvidenceCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    source: Literal["YOUTUBE", "DONATION", "SPONSORSHIP", "OTHER"]
    external_reference: str = Field(min_length=1, max_length=120)
    #: SETTLED is the only status that can later be minted; the other two stay unspendable.
    status: Literal["ESTIMATED", "PENDING_PAYOUT", "SETTLED"]
    amount: AMOUNT
    currency: CURRENCY = "USD"
    fx_snapshot_id: str | None = Field(default=None, max_length=36)
    detail: dict = Field(default_factory=dict)


class ProviderCostCommand(BaseModel):
    """A real external bill. ESTIMATED is tracked only; BILLED posts against VR Cash."""

    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    provider: str = Field(min_length=1, max_length=60)
    external_reference: str = Field(min_length=1, max_length=120)
    status: Literal["ESTIMATED", "BILLED"]
    amount: AMOUNT
    currency: CURRENCY = "USD"
    fx_snapshot_id: str | None = Field(default=None, max_length=36)
    #: What the spend was for — agent, workflow, content item — so cost can be attributed later.
    attribution: dict = Field(default_factory=dict)


class ReversalCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    reason: str = Field(min_length=1, max_length=500)


class FundingCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    funding_type: Literal["CAPITAL_CONTRIBUTION", "OWNER_LOAN"]
    amount: AMOUNT
    currency: CURRENCY = "USD"
    fx_snapshot_id: str | None = Field(default=None, max_length=36)
    #: Basis points per year: 500 means 5.00%. Required for a loan, refused for a contribution.
    annual_rate_bps: int | None = Field(default=None, ge=0, le=100_000)
    maturity_date: str | None = Field(default=None, max_length=40)
    note: str = Field(default="", max_length=2000)


def create_economy_router() -> APIRouter:
    router = APIRouter(prefix="/economy", dependencies=[Depends(require_owner)])

    def _guard(call: Callable[[], dict]) -> dict:
        try:
            return call()
        except CommandConflict as exc:
            # A command id reused with different input: the caller has two different intents
            # under one identity, and guessing which one it meant is not available.
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except EconomyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @router.get("/treasury")
    def get_treasury(request: Request) -> dict:
        """Balances by money class, with every figure labelled and the trial balance attached."""
        return treasury_snapshot(request.app.state.engine)

    @router.get("/budget")
    def get_budget(request: Request) -> dict:
        """Active budgets against the period's spend, and the spend itself."""
        return budget_status(request.app.state.engine)

    @router.put("/budget")
    def put_budget(command: BudgetCommand, request: Request) -> dict:
        """Set or retire a period's budget. The previous limit is kept, marked replaced."""
        try:
            return set_budget(request.app.state.engine, command)
        except EconomyError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.get("/prices")
    def get_prices(
        request: Request,
        provider_kind: Annotated[str | None, Query(max_length=40)] = None,
    ) -> dict:
        """The active prices the adapters cost calls with, and where each came from."""
        return {"prices": list_prices(request.app.state.engine, provider_kind=provider_kind)}

    @router.put("/prices")
    def put_price(command: PriceCommand, request: Request) -> dict:
        """Set what one unit of a resource costs. The previous price is kept, replaced.

        The one way a price enters the books: the Owner's hand, with a command id (a retry
        returns the original answer) and, optionally, the version he believes he replaces.
        """
        return _guard(lambda: set_price(request.app.state.engine, command))

    @router.get("/books/daily")
    def get_daily_figures(request: Request) -> dict:
        """The figures the Accountant closes the day with, computed from the books."""
        return daily_figures(request.app.state.engine)

    @router.post("/books/close")
    def post_close_day(request: Request) -> dict:
        """The Owner asks for the Accountant's close now, outside the daily run."""
        try:
            return reconcile_day(request.app.state.engine, request.app.state.registry)
        except AccountantError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.get("/accounts")
    def get_accounts(request: Request) -> dict:
        return {"accounts": list_accounts(request.app.state.engine)}

    @router.get("/ledger")
    def get_ledger(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> dict:
        return {"transactions": list_transactions(request.app.state.engine, limit=limit)}

    @router.get("/evidence")
    def get_evidence(
        request: Request,
        status: Annotated[str | None, Query(max_length=20)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> dict:
        return {"evidence": list_evidence(request.app.state.engine, status=status, limit=limit)}

    @router.get("/owner-funding")
    def get_owner_funding(request: Request) -> dict:
        return {"funding": list_owner_funding(request.app.state.engine)}

    @router.get("/provider-costs")
    def get_provider_costs(
        request: Request,
        status: Annotated[str | None, Query(max_length=20)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> dict:
        return {"costs": list_provider_costs(request.app.state.engine, status=status, limit=limit)}

    @router.post("/provider-costs")
    def post_provider_cost(request: Request, cmd: ProviderCostCommand) -> dict:
        """Record what a provider actually charged. A BILLED cost reduces VR Cash."""
        return _guard(
            lambda: record_provider_cost(
                request.app.state.engine,
                provider=cmd.provider,
                external_reference=cmd.external_reference,
                status=cmd.status,
                amount=cmd.amount,
                currency=cmd.currency,
                fx_snapshot_id=cmd.fx_snapshot_id,
                attribution=cmd.attribution,
                correlation_id=str(cmd.command_id),
            )
        )

    @router.post("/provider-costs/{cost_id}/bill")
    def post_bill_cost(request: Request, cost_id: UUID36) -> dict:
        """Confirm an estimate became a real invoice, and post it once."""
        return _guard(
            lambda: bill_provider_cost(
                request.app.state.engine, cost_id, correlation_id=str(uuid4())
            )
        )

    @router.get("/reconciliations")
    def get_reconciliations(
        request: Request,
        provider: Annotated[str | None, Query(max_length=60)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> dict:
        """Every vendor invoice the Owner has reconciled, with what it could not match."""
        return {
            "reconciliations": list_reconciliations(
                request.app.state.engine, provider=provider, limit=limit
            )
        }

    @router.put("/reconciliations")
    def put_reconciliation(command: ReconciliationCommand, request: Request) -> dict:
        """Record what a vendor actually billed, and retire the estimates it covers.

        The only way a bill replaces an estimate: the Owner's hand, because only he sees the
        invoice. Shaped like `PUT /economy/prices` — a command id (a retry returns the original
        answer, the same id with another figure is a 409) and the version he believes he is
        correcting. What the invoice could not match comes back in the answer and stays on the
        row; nothing is dropped and nothing is quietly kept counting.
        """
        return _guard(lambda: reconcile_provider_invoice(request.app.state.engine, command))

    @router.post("/fx")
    def post_fx(request: Request, cmd: FXCommand) -> dict:
        """Record an observed exchange rate so a conversion can cite it."""
        return _guard(
            lambda: record_fx_snapshot(
                request.app.state.engine,
                base_currency=cmd.base_currency,
                quote_currency=cmd.quote_currency,
                rate=cmd.rate,
                source=cmd.source,
                observed_at=cmd.observed_at,
            )
        )

    @router.post("/evidence")
    def post_evidence(request: Request, cmd: EvidenceCommand) -> dict:
        """Record a real-world financial fact. This creates no VR$."""
        return _guard(
            lambda: record_revenue_evidence(
                request.app.state.engine,
                source=cmd.source,
                external_reference=cmd.external_reference,
                status=cmd.status,
                amount=cmd.amount,
                currency=cmd.currency,
                fx_snapshot_id=cmd.fx_snapshot_id,
                detail=cmd.detail,
                correlation_id=str(cmd.command_id),
            )
        )

    @router.post("/evidence/{evidence_id}/settle")
    def post_settle(request: Request, evidence_id: UUID36) -> dict:
        return _guard(
            lambda: settle_evidence(
                request.app.state.engine, evidence_id, correlation_id=str(uuid4())
            )
        )

    @router.post("/evidence/{evidence_id}/mint")
    def post_mint(request: Request, evidence_id: UUID36) -> dict:
        """Turn settled evidence into VR$, exactly once."""
        return _guard(
            lambda: mint_from_evidence(
                request.app.state.engine, evidence_id, correlation_id=str(uuid4())
            )
        )

    @router.post("/ledger/{transaction_id}/reverse")
    def post_reverse(request: Request, transaction_id: UUID36, cmd: ReversalCommand) -> dict:
        """Post the mirror of a transaction. The original stays in the books untouched."""
        return _guard(
            lambda: reverse_transaction(
                request.app.state.engine,
                transaction_id,
                reason=cmd.reason,
                correlation_id=str(cmd.command_id),
            )
        )

    @router.post("/owner-funding")
    def post_owner_funding(request: Request, cmd: FundingCommand) -> dict:
        """Record Owner money going in. The application never moves the actual money."""
        return _guard(
            lambda: record_owner_funding(
                request.app.state.engine,
                funding_type=cmd.funding_type,
                amount=cmd.amount,
                currency=cmd.currency,
                fx_snapshot_id=cmd.fx_snapshot_id,
                annual_rate_bps=cmd.annual_rate_bps,
                maturity_date=cmd.maturity_date,
                note=cmd.note,
                correlation_id=str(cmd.command_id),
                # The same command id twice is a retry, not a second contribution.
                command_id=str(cmd.command_id),
            )
        )

    return router
