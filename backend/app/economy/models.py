"""Phase 11 tables: real-world financial evidence, and the virtual books built from it.

`../architecture/66_VIRTUAL_REAL_ECONOMY_ENGINE.md` separates three layers, and the schema keeps
them separate on purpose:

  External Evidence  what really happened outside the application — a settlement, a donation,
                     an Owner transfer, a provider invoice. Recorded, never invented.
  VR Ledger          immutable double-entry books denominated in VR$, posted only from evidence
                     that is eligible.
  Forecast           estimates. They live as evidence rows that are *not* settled, so they are
                     visible without ever becoming spendable.

Two rules are enforced by the schema rather than by convention, because both are the kind of
mistake that is invisible until the numbers are already wrong:

  * **Money is integers.** Every amount is stored in micros (1 VR$ = 1_000_000 micros). Floating
    point cannot represent a cent exactly, and a ledger that drifts by a fraction stops balancing
    after enough postings.
  * **A ledger line is either a debit or a credit, never both and never neither.** A check
    constraint says so, so a malformed entry cannot reach the table even through a direct write.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base

#: One VR$ in micros. VR$ is anchored 1:1 to a verified USD, so this is also one USD.
MICROS = 1_000_000


class LedgerAccount(Base):
    """One account in the virtual chart of accounts.

    Accounts are seeded, not created by agents: a book whose structure can change underneath it
    cannot be compared across time. ``money_class`` is what the interface reads to label a figure
    as spendable cash, restricted, receivable or debt, so the classification lives with the
    account instead of being re-derived by every caller.
    """

    __tablename__ = "ledger_account"
    __table_args__ = (
        CheckConstraint(
            "account_type IN ('ASSET','LIABILITY','EQUITY','REVENUE','EXPENSE')",
            name="ck_account_type",
        ),
        CheckConstraint("normal_balance IN ('DEBIT','CREDIT')", name="ck_account_normal_balance"),
    )

    #: Stable numeric code, e.g. "1000". Referenced by entries instead of a surrogate id so a
    #: posting stays readable in the database without a join.
    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    account_type: Mapped[str] = mapped_column(String(12), nullable=False)
    normal_balance: Mapped[str] = mapped_column(String(6), nullable=False)
    #: VR_CASH | VR_RESTRICTED | VR_RECEIVABLE | VR_DEBT | NULL for accounts that are not a
    #: treasury position at all (revenue, expenses, equity).
    money_class: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: Why this account exists, in the Owner's language, for the interface and for later readers.
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")


class FXSnapshot(Base):
    """One observed exchange rate, with where it came from and when.

    The spec forbids fabricating FX rates. Conversion therefore refuses to proceed unless a
    snapshot exists for the currency pair, and the snapshot that was used is pinned to the
    evidence row — so a converted figure can always be traced back to the rate that produced it,
    even after rates move.
    """

    __tablename__ = "fx_snapshot"
    __table_args__ = (
        CheckConstraint("rate_micros > 0", name="ck_fx_rate_positive"),
        Index("ix_fx_pair_observed", "base_currency", "quote_currency", "observed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    #: Currency being converted from, ISO 4217, e.g. "EUR".
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    #: Currency being converted to. In practice always "USD"; stored so the row is self-describing.
    quote_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    #: How many micro-units of quote currency one unit of base currency buys.
    rate_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: Where the rate was read. Free text on purpose: naming the provider is more useful to an
    #: auditor than an enum the application would have to keep in step with the outside world.
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    observed_at: Mapped[str] = mapped_column(String(40), nullable=False)
    recorded_at: Mapped[str] = mapped_column(String(40), nullable=False)
    #: The event that introduced this rate. Nullable because rows written before 0018 have none,
    #: which is the truth about them rather than a value worth inventing.
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )


class RevenueEvidence(Base):
    """A real-world economic fact the studio has been told about.

    Recording evidence mints nothing. Minting is a separate, explicit step that only succeeds for
    a settled row, which is what keeps a forecast visible in the interface while remaining
    unspendable — the distinction `66_VIRTUAL_REAL_ECONOMY_ENGINE.md` calls the difference
    between PENDING_EXTERNAL/FORECAST and VERIFIED_EXTERNAL.

    ``(source, external_reference)`` is unique. That single constraint is what makes "exactly one
    VR$ per verified dollar" true under retries, concurrent writes and re-imports: the same
    payout cannot be recorded twice, so it cannot be minted twice.
    """

    __tablename__ = "revenue_evidence"
    __table_args__ = (
        UniqueConstraint("source", "external_reference", name="uq_evidence_reference"),
        CheckConstraint(
            "status IN ('ESTIMATED','PENDING_PAYOUT','SETTLED','REVERSED')",
            name="ck_evidence_status",
        ),
        CheckConstraint("original_amount_micros >= 0", name="ck_evidence_amount_positive"),
        Index("ix_evidence_status", "status", "recorded_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    #: YOUTUBE | DONATION | SPONSORSHIP | OTHER. Which real-world channel the money came through.
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    #: The payout/transaction id at that source. Unique per source; this is the idempotency key.
    external_reference: Mapped[str] = mapped_column(String(120), nullable=False)
    #: ESTIMATED and PENDING_PAYOUT are never spendable; SETTLED is eligible to mint once.
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    original_amount_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    original_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    #: The USD value, and therefore the VR$ value, after conversion. Equal to the original amount
    #: when the currency is already USD.
    usd_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: The rate used, when one was needed. NULL for USD evidence, which needs no conversion.
    fx_snapshot_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("fx_snapshot.id"), nullable=True
    )
    #: What the source said about itself: payout period, invoice number, note. Kept verbatim.
    detail_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: Set once, when the row is minted. Its presence is the proof that minting already happened.
    minted_transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ledger_transaction.id"), nullable=True
    )
    recorded_at: Mapped[str] = mapped_column(String(40), nullable=False)
    settled_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )


class OwnerFundingEvent(Base):
    """Money the Owner put into the virtual company, and on what terms.

    `58_FINANCE_ACCOUNTING_FINOPS.md` keeps two kinds apart because they are not the same promise:
    a capital contribution increases equity and is never repaid, while an Owner loan increases a
    liability, carries a rate and accrues interest. Storing them in one table with a discriminator
    keeps the funding history in one place; the ledger postings differ.

    The application records that this happened. It never moves real money.
    """

    __tablename__ = "owner_funding_event"
    __table_args__ = (
        CheckConstraint(
            "funding_type IN ('CAPITAL_CONTRIBUTION','OWNER_LOAN')", name="ck_funding_type"
        ),
        CheckConstraint("amount_micros > 0", name="ck_funding_amount_positive"),
        # A loan without terms is not a loan. Enforce the pairing rather than trusting callers.
        CheckConstraint(
            "funding_type <> 'OWNER_LOAN' OR "
            "(annual_rate_bps IS NOT NULL AND maturity_date IS NOT NULL)",
            name="ck_loan_has_terms",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    funding_type: Mapped[str] = mapped_column(String(24), nullable=False)
    amount_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    usd_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fx_snapshot_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("fx_snapshot.id"), nullable=True
    )
    #: Basis points per year, so a rate is an integer and cannot drift. 500 = 5.00%.
    annual_rate_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    maturity_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ledger_transaction.id"), nullable=True
    )
    recorded_at: Mapped[str] = mapped_column(String(40), nullable=False)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )


class ProviderCostRecord(Base):
    """A real external bill — model, render, TTS or hosting — mirrored into the virtual books.

    The 1:1 rule has two sides. A verified dollar in becomes a VR$; a dollar the studio actually
    spends with a provider becomes a VR$ out. Costs are recorded the same way revenue is, and for
    the same reason: an estimate is visible but does not touch the ledger, and only a real bill
    posts. Without this, the treasury would show income with no cost of running the studio, which
    is a flattering number rather than a true one.

    ``(provider, external_reference)`` is unique, so re-importing an invoice cannot charge twice.
    """

    __tablename__ = "provider_cost_record"
    __table_args__ = (
        UniqueConstraint("provider", "external_reference", name="uq_provider_cost_reference"),
        CheckConstraint("status IN ('ESTIMATED','BILLED')", name="ck_provider_cost_status"),
        CheckConstraint("amount_micros > 0", name="ck_provider_cost_positive"),
        Index("ix_provider_cost_status", "status", "recorded_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    #: Who billed: "openai", "ollama-cloud", "elevenlabs", a hosting provider. Free text, because
    #: the set of providers changes faster than an enum could be kept correct.
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    #: The provider's own invoice or usage-record id. The idempotency key.
    external_reference: Mapped[str] = mapped_column(String(120), nullable=False)
    #: ESTIMATED is tracked and never posted; BILLED posts to the ledger.
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    amount_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    usd_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fx_snapshot_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("fx_snapshot.id"), nullable=True
    )
    #: What the spend was for: agent id, workflow, content item. Kept so cost can be attributed
    #: later without re-deriving it from timestamps.
    attribution_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ledger_transaction.id"), nullable=True
    )
    recorded_at: Mapped[str] = mapped_column(String(40), nullable=False)
    billed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )
    #: The cost of a render the vendor may have charged for and the studio never brought
    #: home (a MediaProviderError midway). Counted by budgets like any estimate: the money is
    #: as gone as if the film had been finished.
    failed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class LedgerTransaction(Base):
    """One balanced posting to the virtual books.

    Transactions are append-only. A mistake is corrected by posting a reversing transaction that
    points back at the original through ``reverses_transaction_id``, never by editing or deleting
    the original — so the books read later show both what was believed at the time and what
    corrected it. ``uq_reversal_once`` makes the correction itself idempotent: a transaction can
    be reversed at most once, so a retried request cannot double-reverse a chargeback.
    """

    __tablename__ = "ledger_transaction"
    __table_args__ = (
        UniqueConstraint("reverses_transaction_id", name="uq_reversal_once"),
        Index("ix_ledger_transaction_posted", "posted_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    #: MINT | REVERSAL | OWNER_CAPITAL | OWNER_LOAN | PROVIDER_COST | ADJUSTMENT
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    #: One line the Owner can read, e.g. "YouTube payout 2026-08, ref PAY-8813".
    memo: Mapped[str] = mapped_column(Text, nullable=False)
    posted_at: Mapped[str] = mapped_column(String(40), nullable=False)
    #: Set only on a REVERSAL, naming the transaction being undone.
    reverses_transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ledger_transaction.id"), nullable=True
    )
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )


class LedgerEntry(Base):
    """One debit or credit line belonging to a transaction."""

    __tablename__ = "ledger_entry"
    __table_args__ = (
        # Exactly one side carries the amount. Both-or-neither is a malformed line, and a table
        # that accepts one will eventually be asked to explain a book that does not balance.
        CheckConstraint("(debit_micros = 0) <> (credit_micros = 0)", name="ck_entry_one_sided"),
        CheckConstraint("debit_micros >= 0 AND credit_micros >= 0", name="ck_entry_non_negative"),
        Index("ix_ledger_entry_account", "account_code"),
        Index("ix_ledger_entry_transaction", "transaction_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    transaction_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ledger_transaction.id"), nullable=False
    )
    account_code: Mapped[str] = mapped_column(
        String(8), ForeignKey("ledger_account.code"), nullable=False
    )
    debit_micros: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    credit_micros: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class SpendingBudget(Base):
    """How much the studio may spend in a period, set by the Owner (see economy/budget.py).

    One active row per period; a new limit deactivates the previous one and keeps it, so the
    books can say what the allowance was on any given day. Amounts in USD micros, like every
    other figure here.
    """

    __tablename__ = "spending_budget"
    __table_args__ = (
        CheckConstraint("period IN ('DAILY','MONTHLY')", name="ck_spending_budget_period"),
        CheckConstraint("limit_usd_micros > 0", name="ck_spending_budget_positive"),
        Index("ix_spending_budget_active", "period", "active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    period: Mapped[str] = mapped_column(String(10), nullable=False)
    limit_usd_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    warn_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    set_by: Mapped[str] = mapped_column(String(100), nullable=False, default="owner")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    replaced_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )


#: The units a price can be quoted in. Every adapter that costs a call names one of these
#: and multiplies by what it measured — characters sent, tokens counted, seconds bought.
PRICE_UNITS = (
    "per_1k_characters",
    "per_1m_input_tokens",
    "per_1m_output_tokens",
    "per_second",
    "per_generation",
)

#: Where a price came from, dearest evidence last: what the Owner typed, what a public price
#: list documents, what a vendor quoted before generating, what an invoice said.
PRICE_PROVENANCES = ("OWNER", "DOCUMENTED", "QUOTED", "BILLED")


class ProviderPrice(Base):
    """What one unit of a provider's resource costs, as the Owner supplied it.

    One active row per ``(provider_kind, resource, unit)``; a new price deactivates the
    previous one and keeps it, versioned, so the books can say what a token cost on any day.
    ``resource`` is the model id the adapter reports; ``"*"`` prices every resource of the kind
    that has no row of its own. Written only by the Owner's command (``PUT /economy/prices``)
    or a documented seed marked as such; never by an agent, a search result or a vendor page.
    """

    __tablename__ = "provider_price"
    __table_args__ = (
        CheckConstraint(
            "unit IN ('per_1k_characters','per_1m_input_tokens','per_1m_output_tokens',"
            "'per_second','per_generation')",
            name="ck_provider_price_unit",
        ),
        CheckConstraint(
            "provenance IN ('OWNER','DOCUMENTED','QUOTED','BILLED')",
            name="ck_provider_price_provenance",
        ),
        CheckConstraint("usd_micros >= 0", name="ck_provider_price_non_negative"),
        UniqueConstraint(
            "provider_kind", "resource", "unit", "version", name="uq_provider_price_version"
        ),
        Index("ix_provider_price_lookup", "provider_kind", "resource", "unit", "active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    #: The catalogue kind of the connection: "ollama", "openai", "anthropic", "elevenlabs".
    provider_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    resource: Mapped[str] = mapped_column(String(200), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    usd_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    provenance: Mapped[str] = mapped_column(String(12), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    set_by: Mapped[str] = mapped_column(String(100), nullable=False, default="owner")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    set_at: Mapped[str] = mapped_column(String(40), nullable=False)
    replaced_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )


class SpendReservation(Base):
    """A sum held against the period's budget while a film is being made.

    RESERVED counts in every budget check exactly like a recorded cost, so two films started
    together cannot both fit on the last ten dollars. It ends one of two ways: SETTLED when
    the real cost rows replace it, or RELEASED when the film was not made — or when the
    watchdog finds it older than the reservation TTL, left by a process that died under it.
    """

    __tablename__ = "spend_reservation"
    __table_args__ = (
        CheckConstraint(
            "status IN ('RESERVED','RELEASED','SETTLED')", name="ck_spend_reservation_status"
        ),
        CheckConstraint("usd_micros > 0", name="ck_spend_reservation_positive"),
        Index("ix_spend_reservation_status", "status", "reserved_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(200), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    usd_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="RESERVED")
    reserved_at: Mapped[str] = mapped_column(String(40), nullable=False)
    released_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: What replaced or released it: the render job's id, or the watchdog's reason.
    settled_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )
