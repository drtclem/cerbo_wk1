import logging
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.models import LedgerEntry, Order, OrderLine, Product
from app.seams.fulfillment import Fulfillment
from app.seams.payment_provider import PaymentProvider
from app.services.orders import OrderView, order_lines, present_order

logger = logging.getLogger(__name__)

_CLAIM_ATTEMPTS = 3


class OrderNotPayable(Exception):
    pass


class OutOfStock(Exception):
    pass


class PaymentDeclined(Exception):
    pass


def pay_order(
    session: Session,
    order_id: int,
    payment_method: str,
    payment_provider: PaymentProvider,
    fulfillment: Fulfillment,
) -> OrderView:
    """Claim, take stock, charge, then commit. Ship only after that commit."""
    for _ in range(_CLAIM_ATTEMPTS):
        order = session.get(Order, order_id)
        if order is None:
            session.rollback()
            raise OrderNotPayable
        if order.status == "paid":
            view = present_order(session, order, order_lines(session, order.id))
            session.rollback()
            return view
        if order.status != "pending_payment":
            session.rollback()
            raise OrderNotPayable

        claimed = cast(
            CursorResult[Any],
            session.execute(
                update(Order)
                .where(Order.id == order_id, Order.status == "pending_payment")
                .values(status="paid")
                .execution_options(synchronize_session=False)
            ),
        )
        if claimed.rowcount != 1:
            session.rollback()
            session.expire_all()
            continue

        lines = order_lines(session, order.id)
        if not _take_stock(session, lines):
            session.rollback()
            raise OutOfStock

        charged = payment_provider.charge(
            amount_cents=order.subtotal_cents,
            idempotency_key=str(order.id),
            payment_method=payment_method,
        )
        if not charged.approved or charged.ref is None:
            session.rollback()
            raise PaymentDeclined

        paid_at = _utc_now()
        session.expire(order)
        paid = session.get(Order, order_id)
        if paid is None or paid.status != "paid":
            session.rollback()
            raise OrderNotPayable
        paid.payment_ref = charged.ref
        paid.paid_at = paid_at
        _write_ledger(session, paid, lines, paid_at)
        session.commit()
        _ship(fulfillment, paid)
        return present_order(session, paid, lines)

    session.rollback()
    raise OrderNotPayable


def _take_stock(session: Session, lines: list[OrderLine]) -> bool:
    for line in lines:
        taken = cast(
            CursorResult[Any],
            session.execute(
                update(Product)
                .where(Product.id == line.product_id, Product.stock_qty >= line.qty)
                .values(stock_qty=Product.stock_qty - line.qty)
                .execution_options(synchronize_session=False)
            ),
        )
        if taken.rowcount != 1:
            return False
    return True


def _write_ledger(
    session: Session, order: Order, lines: list[OrderLine], paid_at: str
) -> None:
    amounts = (
        ("patient_payment", order.subtotal_cents, None),
        ("cerbo_cogs", order.cogs_total_cents, None),
        ("cerbo_fee", order.platform_fee_cents, None),
        ("provider_payable", order.provider_payout_cents, None),
    )
    for entry_type, amount_cents, fund_id in amounts:
        session.add(
            LedgerEntry(
                order_id=order.id,
                entry_type=entry_type,
                amount_cents=amount_cents,
                created_at=paid_at,
                fund_id=fund_id,
            )
        )
    by_fund: dict[int, int] = defaultdict(int)
    for line in lines:
        if line.donation_cents > 0 and line.fund_id is not None:
            by_fund[line.fund_id] += line.donation_cents
    for fund_id in sorted(by_fund):
        session.add(
            LedgerEntry(
                order_id=order.id,
                entry_type="research_donation",
                amount_cents=by_fund[fund_id],
                created_at=paid_at,
                fund_id=fund_id,
            )
        )


def _ship(fulfillment: Fulfillment, order: Order) -> None:
    try:
        fulfillment.ship(order)
    except Exception:
        logger.exception("fulfillment failed after order %s was paid", order.id)


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
