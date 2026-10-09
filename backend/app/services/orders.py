import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.domain.money import (
    DONATION_BPS_OFF,
    DONATION_BPS_ON,
    FEE_BPS_DEFAULT,
    LineInput,
    OrderSplit,
    line_amounts,
    validate_order,
)
from app.models import Order, OrderLine, Product, ProviderProduct, ResearchFund, User
from app.seams.notifier import Notifier

_SQLITE_MAX_INT = 9_223_372_036_854_775_807
logger = logging.getLogger(__name__)


class ProductUnavailable(Exception):
    def __init__(self, line_index: int) -> None:
        self.line_index = line_index
        super().__init__(line_index)


class InvalidPatient(Exception):
    pass


class OrderNotFound(Exception):
    pass


class OrderNotCancellable(Exception):
    pass


@dataclass(frozen=True)
class PreviewLine:
    product_id: int
    qty: int
    unit_price_cents: int


@dataclass(frozen=True)
class CreateLine:
    product_id: int
    qty: int
    unit_price_cents: int
    dosing: str
    note: str | None


@dataclass(frozen=True)
class FundSnapshot:
    fund_id: int
    fund_name: str
    fund_url: str
    fund_description: str


@dataclass(frozen=True)
class PreviewLineExtra:
    stock_available: int
    fund: FundSnapshot | None


@dataclass(frozen=True)
class PreviewResult:
    split: OrderSplit
    line_extras: tuple[PreviewLineExtra, ...]


@dataclass(frozen=True)
class OrderLineView:
    product_id: int
    product_name: str
    qty: int
    unit_price_cents: int
    unit_cogs_cents: int
    line_total_cents: int
    line_cogs_cents: int
    line_margin_cents: int
    dosing: str
    note: str | None
    donation_cents: int
    fund_id: int | None
    fund_name: str | None
    fund_url: str | None
    fund_description: str | None


@dataclass(frozen=True)
class OrderView:
    id: int
    provider_id: int
    patient_id: int
    status: str
    patient_link: str
    created_at: str
    paid_at: str | None
    cancelled_at: str | None
    payment_ref: str | None
    lines: tuple[OrderLineView, ...]
    subtotal_cents: int
    cogs_total_cents: int
    fee_bps: int
    platform_fee_cents: int
    donation_bps: int
    donation_cents: int
    provider_payout_cents: int


def donation_bps_for(donate: bool) -> int:
    return DONATION_BPS_ON if donate else DONATION_BPS_OFF


def preview_order(
    session: Session,
    provider_id: int,
    lines: Sequence[PreviewLine],
    donate: bool = False,
) -> PreviewResult:
    """Validate and price a provider's lines. Does not write."""
    donation_bps = donation_bps_for(donate)
    resolved: list[LineInput] = []
    extras: list[PreviewLineExtra] = []
    for index, line in enumerate(lines):
        priced = _enabled_line(session, provider_id, line)
        if priced is None:
            if resolved:
                validate_order(resolved, FEE_BPS_DEFAULT, donation_bps)
            raise ProductUnavailable(index)
        line_input, stock, fund = priced
        resolved.append(line_input)
        extras.append(PreviewLineExtra(stock_available=stock, fund=fund))
    return PreviewResult(
        split=validate_order(resolved, FEE_BPS_DEFAULT, donation_bps),
        line_extras=tuple(extras),
    )


def create_order(
    session: Session,
    provider_id: int,
    patient_id: int,
    lines: Sequence[CreateLine],
    notifier: Notifier,
    donate: bool = False,
) -> OrderView:
    """Snapshot a validated order. Notifies only after the commit succeeds."""
    _require_patient(session, patient_id)
    priced_lines = tuple(
        PreviewLine(
            product_id=line.product_id,
            qty=line.qty,
            unit_price_cents=line.unit_price_cents,
        )
        for line in lines
    )
    preview = preview_order(session, provider_id, priced_lines, donate=donate)
    split = preview.split
    names = _product_names(session, priced_lines)

    created_at = _utc_now()
    order = Order(
        provider_id=provider_id,
        patient_id=patient_id,
        status="pending_payment",
        fee_bps=split.fee_bps,
        donation_bps=split.donation_bps,
        subtotal_cents=split.subtotal_cents,
        cogs_total_cents=split.cogs_total_cents,
        platform_fee_cents=split.platform_fee_cents,
        donation_cents=split.donation_cents,
        provider_payout_cents=split.provider_payout_cents,
        payment_ref=None,
        created_at=created_at,
        paid_at=None,
        cancelled_at=None,
    )
    session.add(order)
    session.flush()
    stored_lines: list[OrderLine] = []
    for name, priced, source, extra in zip(
        names, split.lines, lines, preview.line_extras, strict=True
    ):
        fund = extra.fund
        stored = OrderLine(
            order_id=order.id,
            product_id=priced.product_id,
            product_name=name,
            qty=priced.qty,
            unit_price_cents=priced.unit_price_cents,
            unit_cogs_cents=priced.unit_cogs_cents,
            dosing=source.dosing,
            note=source.note,
            donation_cents=priced.donation_cents,
            fund_id=fund.fund_id if fund is not None else None,
            fund_name=fund.fund_name if fund is not None else None,
            fund_url=fund.fund_url if fund is not None else None,
        )
        session.add(stored)
        stored_lines.append(stored)
    session.commit()

    patient_link = _patient_link(order.id)
    try:
        notifier.order_created(order, patient_link)
    except Exception:
        logger.exception("notifier failed after order %s was created", order.id)
    return _present(session, order, stored_lines)


def get_order(session: Session, order_id: int) -> Order:
    if not 1 <= order_id <= _SQLITE_MAX_INT:
        raise OrderNotFound
    order = session.get(Order, order_id)
    if order is None:
        raise OrderNotFound
    return order


def order_lines(session: Session, order_id: int) -> list[OrderLine]:
    return list(
        session.scalars(
            select(OrderLine).where(OrderLine.order_id == order_id).order_by(OrderLine.id)
        )
    )


def present_order(session: Session, order: Order, lines: Sequence[OrderLine]) -> OrderView:
    """Read stored money. Line display amounts come from the snapshot, not the catalog."""
    return _present(session, order, lines)


def list_patient_orders(session: Session, patient_id: int) -> list[Order]:
    return list(
        session.scalars(select(Order).where(Order.patient_id == patient_id).order_by(Order.id))
    )


def cancel_order(session: Session, order: Order) -> OrderView:
    """Cancel only a pending order. A lost race leaves the committed row alone."""
    cancelled = cast(
        CursorResult[Any],
        session.execute(
            update(Order)
            .where(Order.id == order.id, Order.status == "pending_payment")
            .values(status="cancelled", cancelled_at=_utc_now())
            .execution_options(synchronize_session=False)
        ),
    )
    if cancelled.rowcount != 1:
        session.rollback()
        raise OrderNotCancellable
    session.commit()
    session.expire(order)
    fresh = session.get(Order, order.id)
    if fresh is None:
        raise OrderNotCancellable
    return present_order(session, fresh, order_lines(session, fresh.id))


def _require_patient(session: Session, patient_id: int) -> None:
    if not 1 <= patient_id <= _SQLITE_MAX_INT:
        raise InvalidPatient
    user = session.get(User, patient_id)
    if user is None or user.role != "patient":
        raise InvalidPatient


def _product_names(session: Session, lines: Sequence[PreviewLine]) -> list[str]:
    names: list[str] = []
    for index, line in enumerate(lines):
        product = session.get(Product, line.product_id)
        if product is None:
            raise ProductUnavailable(index)
        names.append(product.name)
    return names


def _fund_descriptions(
    session: Session, lines: Sequence[OrderLine]
) -> dict[int, str]:
    fund_ids = {line.fund_id for line in lines if line.fund_id is not None}
    if not fund_ids:
        return {}
    funds = session.scalars(select(ResearchFund).where(ResearchFund.id.in_(fund_ids)))
    return {fund.id: fund.description for fund in funds}


def _present(session: Session, order: Order, lines: Sequence[OrderLine]) -> OrderView:
    descriptions = _fund_descriptions(session, lines)
    presented: list[OrderLineView] = []
    for line in lines:
        line_total_cents, line_cogs_cents, line_margin_cents = line_amounts(
            line.unit_price_cents, line.unit_cogs_cents, line.qty
        )
        presented.append(
            OrderLineView(
                product_id=line.product_id,
                product_name=line.product_name,
                qty=line.qty,
                unit_price_cents=line.unit_price_cents,
                unit_cogs_cents=line.unit_cogs_cents,
                line_total_cents=line_total_cents,
                line_cogs_cents=line_cogs_cents,
                line_margin_cents=line_margin_cents,
                dosing=line.dosing,
                note=line.note,
                donation_cents=line.donation_cents,
                fund_id=line.fund_id,
                fund_name=line.fund_name,
                fund_url=line.fund_url,
                fund_description=(
                    descriptions.get(line.fund_id) if line.fund_id is not None else None
                ),
            )
        )
    return OrderView(
        id=order.id,
        provider_id=order.provider_id,
        patient_id=order.patient_id,
        status=order.status,
        patient_link=_patient_link(order.id),
        created_at=order.created_at,
        paid_at=order.paid_at,
        cancelled_at=order.cancelled_at,
        payment_ref=order.payment_ref,
        lines=tuple(presented),
        subtotal_cents=order.subtotal_cents,
        cogs_total_cents=order.cogs_total_cents,
        fee_bps=order.fee_bps,
        platform_fee_cents=order.platform_fee_cents,
        donation_bps=order.donation_bps,
        donation_cents=order.donation_cents,
        provider_payout_cents=order.provider_payout_cents,
    )


def _patient_link(order_id: int) -> str:
    return f"/orders/{order_id}"


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fund_for_product(session: Session, product: Product) -> FundSnapshot | None:
    if product.research_fund_id is None:
        return None
    fund = session.get(ResearchFund, product.research_fund_id)
    if fund is None:
        return None
    return FundSnapshot(
        fund_id=fund.id,
        fund_name=fund.name,
        fund_url=fund.url,
        fund_description=fund.description,
    )


def _enabled_line(
    session: Session,
    provider_id: int,
    line: PreviewLine,
) -> tuple[LineInput, int, FundSnapshot | None] | None:
    if not 1 <= line.product_id <= _SQLITE_MAX_INT:
        return None
    link = session.get(ProviderProduct, (provider_id, line.product_id))
    if link is None or link.enabled != 1:
        return None
    product = session.get(Product, line.product_id)
    if product is None:
        return None
    fund = _fund_for_product(session, product)
    return (
        LineInput(
            product_id=line.product_id,
            qty=line.qty,
            unit_price_cents=line.unit_price_cents,
            unit_cogs_cents=product.unit_cogs_cents,
            has_research_fund=fund is not None,
        ),
        product.stock_qty,
        fund,
    )
