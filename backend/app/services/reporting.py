from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.money import compute_fee, line_amounts, line_donation_cents
from app.models import LedgerEntry, Order, OrderLine, User

_PATIENT_PAYMENT = "patient_payment"
_CERBO_COGS = "cerbo_cogs"
_CERBO_FEE = "cerbo_fee"
_PROVIDER_PAYABLE = "provider_payable"
_RESEARCH_DONATION = "research_donation"


@dataclass(frozen=True)
class PaidOrderSummary:
    id: int
    paid_at: str
    patient_id: int
    patient_name: str
    subtotal_cents: int
    platform_fee_cents: int
    donation_cents: int
    provider_payout_cents: int
    audit_link: str


@dataclass(frozen=True)
class UnitSold:
    product_id: int
    product_name: str
    qty: int


@dataclass(frozen=True)
class PendingOrderSummary:
    id: int
    created_at: str
    patient_id: int
    patient_name: str


@dataclass(frozen=True)
class Dashboard:
    gmv_cents: int
    platform_fee_cents: int
    donation_cents: int
    earnings_cents: int
    paid_orders: tuple[PaidOrderSummary, ...]
    units_sold: tuple[UnitSold, ...]
    pending_orders: tuple[PendingOrderSummary, ...]


@dataclass(frozen=True)
class AuditLine:
    product_id: int
    product_name: str
    qty: int
    unit_price_cents: int
    unit_cogs_cents: int
    line_total_cents: int
    line_cogs_cents: int
    line_margin_cents: int
    donation_cents: int
    fund_id: int | None
    fund_name: str | None
    fund_url: str | None


@dataclass(frozen=True)
class AuditLedgerEntry:
    entry_type: str
    amount_cents: int
    created_at: str
    fund_id: int | None


@dataclass(frozen=True)
class OrderAudit:
    id: int
    status: str
    payment_ref: str | None
    paid_at: str | None
    lines: tuple[AuditLine, ...]
    subtotal_cents: int
    cogs_total_cents: int
    fee_bps: int
    platform_fee_cents: int
    donation_bps: int
    donation_cents: int
    provider_payout_cents: int
    ledger: tuple[AuditLedgerEntry, ...]
    recomputed_fee_matches: bool
    donation_matches_rate: bool
    split_adds_up: bool
    ledger_matches_split: bool


def provider_dashboard(session: Session, provider_id: int) -> Dashboard:
    """Read this provider's paid ledger totals. Does not write."""
    paid = _orders(session, provider_id, "paid")
    pending = _orders(session, provider_id, "pending_payment")
    names = _patient_names(session, [order.patient_id for order in (*paid, *pending)])
    gmv_cents, platform_fee_cents, donation_cents, earnings_cents = _headline_totals(
        session, paid
    )
    return Dashboard(
        gmv_cents=gmv_cents,
        platform_fee_cents=platform_fee_cents,
        donation_cents=donation_cents,
        earnings_cents=earnings_cents,
        paid_orders=tuple(_paid_summary(order, names) for order in paid),
        units_sold=tuple(_units_sold(session, provider_id)),
        pending_orders=tuple(_pending_summary(order, names) for order in pending),
    )


def order_audit(session: Session, order: Order) -> OrderAudit:
    """Read the stored split and ledger. The fee check uses compute_fee."""
    lines = list(
        session.scalars(
            select(OrderLine).where(OrderLine.order_id == order.id).order_by(OrderLine.id)
        )
    )
    ledger = list(
        session.scalars(
            select(LedgerEntry)
            .where(LedgerEntry.order_id == order.id)
            .order_by(LedgerEntry.id)
        )
    )
    return OrderAudit(
        id=order.id,
        status=order.status,
        payment_ref=order.payment_ref,
        paid_at=order.paid_at,
        lines=tuple(_audit_line(line) for line in lines),
        subtotal_cents=order.subtotal_cents,
        cogs_total_cents=order.cogs_total_cents,
        fee_bps=order.fee_bps,
        platform_fee_cents=order.platform_fee_cents,
        donation_bps=order.donation_bps,
        donation_cents=order.donation_cents,
        provider_payout_cents=order.provider_payout_cents,
        ledger=tuple(
            AuditLedgerEntry(
                entry_type=entry.entry_type,
                amount_cents=entry.amount_cents,
                created_at=entry.created_at,
                fund_id=entry.fund_id,
            )
            for entry in ledger
        ),
        recomputed_fee_matches=(
            compute_fee(order.subtotal_cents, order.fee_bps) == order.platform_fee_cents
        ),
        donation_matches_rate=_donation_matches_rate(order, lines),
        split_adds_up=_split_adds_up(order),
        ledger_matches_split=_ledger_matches_split(order, lines, ledger),
    )


def _orders(session: Session, provider_id: int, status: str) -> list[Order]:
    return list(
        session.scalars(
            select(Order)
            .where(Order.provider_id == provider_id, Order.status == status)
            .order_by(Order.id)
        )
    )


def _patient_names(session: Session, patient_ids: list[int]) -> dict[int, str]:
    unique_ids = list(set(patient_ids))
    if not unique_ids:
        return {}
    users = session.scalars(select(User).where(User.id.in_(unique_ids)))
    return {user.id: user.name for user in users}


def _headline_totals(
    session: Session, paid: list[Order]
) -> tuple[int, int, int, int]:
    if not paid:
        return 0, 0, 0, 0
    paid_ids = [order.id for order in paid]
    rows = session.scalars(select(LedgerEntry).where(LedgerEntry.order_id.in_(paid_ids)))
    gmv_cents = 0
    platform_fee_cents = 0
    donation_cents = 0
    earnings_cents = 0
    for entry in rows:
        if entry.entry_type == _PATIENT_PAYMENT:
            gmv_cents += entry.amount_cents
        elif entry.entry_type == _CERBO_FEE:
            platform_fee_cents += entry.amount_cents
        elif entry.entry_type == _RESEARCH_DONATION:
            donation_cents += entry.amount_cents
        elif entry.entry_type == _PROVIDER_PAYABLE:
            earnings_cents += entry.amount_cents
    return gmv_cents, platform_fee_cents, donation_cents, earnings_cents


def _paid_summary(order: Order, names: dict[int, str]) -> PaidOrderSummary:
    paid_at = order.paid_at if order.paid_at is not None else ""
    return PaidOrderSummary(
        id=order.id,
        paid_at=paid_at,
        patient_id=order.patient_id,
        patient_name=names[order.patient_id],
        subtotal_cents=order.subtotal_cents,
        platform_fee_cents=order.platform_fee_cents,
        donation_cents=order.donation_cents,
        provider_payout_cents=order.provider_payout_cents,
        audit_link=f"/orders/{order.id}/audit",
    )


def _pending_summary(order: Order, names: dict[int, str]) -> PendingOrderSummary:
    return PendingOrderSummary(
        id=order.id,
        created_at=order.created_at,
        patient_id=order.patient_id,
        patient_name=names[order.patient_id],
    )


def _units_sold(session: Session, provider_id: int) -> list[UnitSold]:
    lines = session.execute(
        select(OrderLine)
        .join(Order, Order.id == OrderLine.order_id)
        .where(Order.provider_id == provider_id, Order.status == "paid")
        .order_by(OrderLine.id)
    ).scalars()
    qty_by_product: dict[int, int] = {}
    name_by_product: dict[int, str] = {}
    for line in lines:
        qty_by_product[line.product_id] = qty_by_product.get(line.product_id, 0) + line.qty
        if line.product_id not in name_by_product:
            name_by_product[line.product_id] = line.product_name
    return [
        UnitSold(
            product_id=product_id,
            product_name=name_by_product[product_id],
            qty=qty_by_product[product_id],
        )
        for product_id in sorted(qty_by_product)
    ]


def _split_adds_up(order: Order) -> bool:
    return order.subtotal_cents == (
        order.cogs_total_cents
        + order.platform_fee_cents
        + order.donation_cents
        + order.provider_payout_cents
    )


def _donation_matches_rate(order: Order, lines: list[OrderLine]) -> bool:
    expected_total = 0
    for line in lines:
        _, _, margin = line_amounts(line.unit_price_cents, line.unit_cogs_cents, line.qty)
        expected = line_donation_cents(
            margin, order.donation_bps, line.fund_id is not None
        )
        if line.donation_cents != expected:
            return False
        expected_total += expected
    return expected_total == order.donation_cents


def _ledger_matches_split(
    order: Order, lines: list[OrderLine], ledger: list[LedgerEntry]
) -> bool:
    if order.status != "paid":
        return not ledger

    amounts: dict[str, int] = {}
    donation_by_fund: dict[int, int] = {}
    for entry in ledger:
        if entry.entry_type == _RESEARCH_DONATION:
            if entry.fund_id is None:
                return False
            if entry.fund_id in donation_by_fund:
                return False
            donation_by_fund[entry.fund_id] = entry.amount_cents
            continue
        if entry.entry_type in amounts:
            return False
        if entry.fund_id is not None:
            return False
        amounts[entry.entry_type] = entry.amount_cents

    expected = {
        _PATIENT_PAYMENT: order.subtotal_cents,
        _CERBO_COGS: order.cogs_total_cents,
        _CERBO_FEE: order.platform_fee_cents,
        _PROVIDER_PAYABLE: order.provider_payout_cents,
    }
    if amounts != expected:
        return False

    expected_donations: dict[int, int] = defaultdict(int)
    for line in lines:
        if line.donation_cents > 0 and line.fund_id is not None:
            expected_donations[line.fund_id] += line.donation_cents
    return dict(expected_donations) == donation_by_fund and sum(
        expected_donations.values()
    ) == order.donation_cents


def _audit_line(line: OrderLine) -> AuditLine:
    line_total_cents, line_cogs_cents, line_margin_cents = line_amounts(
        line.unit_price_cents, line.unit_cogs_cents, line.qty
    )
    return AuditLine(
        product_id=line.product_id,
        product_name=line.product_name,
        qty=line.qty,
        unit_price_cents=line.unit_price_cents,
        unit_cogs_cents=line.unit_cogs_cents,
        line_total_cents=line_total_cents,
        line_cogs_cents=line_cogs_cents,
        line_margin_cents=line_margin_cents,
        donation_cents=line.donation_cents,
        fund_id=line.fund_id,
        fund_name=line.fund_name,
        fund_url=line.fund_url,
    )
