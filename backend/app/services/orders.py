import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.money import FEE_BPS_DEFAULT, LineInput, OrderSplit, line_amounts, validate_order
from app.models import Order, OrderLine, Product, ProviderProduct, User
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
class OrderLineView:
    product_id: int
    product_name: str
    qty: int
    unit_price_cents: int
    unit_cogs_cents: int
    line_total_cents: int
    line_cogs_cents: int
    line_margin_cents: int


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
    provider_payout_cents: int


def preview_order(
    session: Session,
    provider_id: int,
    lines: Sequence[PreviewLine],
) -> OrderSplit:
    """Validate and price a provider's lines. Does not write."""
    resolved: list[LineInput] = []
    for index, line in enumerate(lines):
        priced = _enabled_line(session, provider_id, line)
        if priced is None:
            if resolved:
                validate_order(resolved, FEE_BPS_DEFAULT)
            raise ProductUnavailable(index)
        resolved.append(priced)
    return validate_order(resolved, FEE_BPS_DEFAULT)


def create_order(
    session: Session,
    provider_id: int,
    patient_id: int,
    lines: Sequence[PreviewLine],
    notifier: Notifier,
) -> OrderView:
    """Snapshot a validated order. Notifies only after the commit succeeds."""
    _require_patient(session, patient_id)
    split = preview_order(session, provider_id, lines)
    names = _product_names(session, lines)

    created_at = _utc_now()
    order = Order(
        provider_id=provider_id,
        patient_id=patient_id,
        status="pending_payment",
        fee_bps=split.fee_bps,
        subtotal_cents=split.subtotal_cents,
        cogs_total_cents=split.cogs_total_cents,
        platform_fee_cents=split.platform_fee_cents,
        provider_payout_cents=split.provider_payout_cents,
        payment_ref=None,
        created_at=created_at,
        paid_at=None,
        cancelled_at=None,
    )
    session.add(order)
    session.flush()
    stored_lines: list[OrderLine] = []
    for name, priced in zip(names, split.lines, strict=True):
        stored = OrderLine(
            order_id=order.id,
            product_id=priced.product_id,
            product_name=name,
            qty=priced.qty,
            unit_price_cents=priced.unit_price_cents,
            unit_cogs_cents=priced.unit_cogs_cents,
        )
        session.add(stored)
        stored_lines.append(stored)
    session.commit()

    patient_link = _patient_link(order.id)
    try:
        notifier.order_created(order, patient_link)
    except Exception:
        logger.exception("notifier failed after order %s was created", order.id)
    return _present(order, stored_lines)


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


def present_order(order: Order, lines: Sequence[OrderLine]) -> OrderView:
    """Read stored money. Line display amounts come from the snapshot, not the catalog."""
    return _present(order, lines)


def list_patient_orders(session: Session, patient_id: int) -> list[Order]:
    return list(
        session.scalars(select(Order).where(Order.patient_id == patient_id).order_by(Order.id))
    )


def cancel_order(session: Session, order: Order) -> OrderView:
    if order.status != "pending_payment":
        raise OrderNotCancellable
    order.status = "cancelled"
    order.cancelled_at = _utc_now()
    session.commit()
    return present_order(order, order_lines(session, order.id))


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


def _present(order: Order, lines: Sequence[OrderLine]) -> OrderView:
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
        provider_payout_cents=order.provider_payout_cents,
    )


def _patient_link(order_id: int) -> str:
    return f"/orders/{order_id}"


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _enabled_line(
    session: Session,
    provider_id: int,
    line: PreviewLine,
) -> LineInput | None:
    if not 1 <= line.product_id <= _SQLITE_MAX_INT:
        return None
    link = session.get(ProviderProduct, (provider_id, line.product_id))
    if link is None or link.enabled != 1:
        return None
    product = session.get(Product, line.product_id)
    if product is None:
        return None
    return LineInput(
        product_id=line.product_id,
        qty=line.qty,
        unit_price_cents=line.unit_price_cents,
        unit_cogs_cents=product.unit_cogs_cents,
    )
