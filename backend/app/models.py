from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('provider', 'patient', 'admin')"),
        {"sqlite_strict": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)


class ResearchFund(Base):
    __tablename__ = "research_funds"
    __table_args__ = ({"sqlite_strict": True},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("unit_cogs_cents > 0"),
        CheckConstraint("suggested_price_cents > 0"),
        CheckConstraint("stock_qty >= 0"),
        CheckConstraint("length(default_dosing) >= 1 AND length(default_dosing) <= 200"),
        {"sqlite_strict": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    unit_cogs_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    suggested_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    stock_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    default_dosing: Mapped[str] = mapped_column(Text, nullable=False)
    research_fund_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_funds.id"), nullable=True
    )


class ProviderProduct(Base):
    __tablename__ = "provider_products"
    __table_args__ = (
        CheckConstraint("enabled IN (0, 1)"),
        CheckConstraint("default_price_cents > 0"),
        {"sqlite_strict": True},
    )

    provider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), primary_key=True)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False)
    default_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("status IN ('pending_payment', 'paid', 'cancelled')"),
        CheckConstraint("fee_bps >= 0"),
        CheckConstraint("donation_bps IN (0, 500)"),
        CheckConstraint("subtotal_cents > 0"),
        CheckConstraint("cogs_total_cents > 0"),
        CheckConstraint("platform_fee_cents >= 0"),
        CheckConstraint("donation_cents >= 0"),
        CheckConstraint("provider_payout_cents >= 0"),
        CheckConstraint(
            "subtotal_cents = cogs_total_cents + platform_fee_cents "
            "+ donation_cents + provider_payout_cents"
        ),
        {"sqlite_strict": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    fee_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    donation_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    subtotal_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    cogs_total_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    platform_fee_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    donation_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_payout_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    paid_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class OrderLine(Base):
    __tablename__ = "order_lines"
    __table_args__ = (
        CheckConstraint("qty >= 1"),
        CheckConstraint("unit_price_cents > 0"),
        CheckConstraint("unit_cogs_cents > 0"),
        CheckConstraint("unit_price_cents >= unit_cogs_cents"),
        CheckConstraint("donation_cents >= 0"),
        CheckConstraint(
            "(fund_id IS NULL AND donation_cents = 0) OR (fund_id IS NOT NULL)"
        ),
        CheckConstraint("length(dosing) >= 1 AND length(dosing) <= 200"),
        CheckConstraint("note IS NULL OR length(note) <= 500"),
        {"sqlite_strict": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    product_name: Mapped[str] = mapped_column(Text, nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cogs_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    dosing: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    donation_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    fund_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_funds.id"), nullable=True
    )
    fund_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    fund_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    removed_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        CheckConstraint(
            "entry_type IN ('patient_payment', 'cerbo_cogs', 'cerbo_fee', "
            "'provider_payable', 'research_donation')"
        ),
        CheckConstraint("amount_cents >= 0"),
        CheckConstraint(
            "(entry_type = 'research_donation' AND fund_id IS NOT NULL) OR "
            "(entry_type != 'research_donation' AND fund_id IS NULL)"
        ),
        Index(
            "uq_ledger_order_entry_type_non_donation",
            "order_id",
            "entry_type",
            unique=True,
            sqlite_where=text("entry_type != 'research_donation'"),
        ),
        Index(
            "uq_ledger_order_fund_donation",
            "order_id",
            "fund_id",
            unique=True,
            sqlite_where=text("entry_type = 'research_donation'"),
        ),
        {"sqlite_strict": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    entry_type: Mapped[str] = mapped_column(Text, nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    fund_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_funds.id"), nullable=True
    )
