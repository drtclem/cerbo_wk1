from collections.abc import Sequence
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Order, User
from app.seams.auth import APIError, require_order_access, require_role
from app.seams.fulfillment import Fulfillment
from app.seams.notifier import Notifier
from app.seams.payment_provider import PaymentProvider
from app.services.orders import (
    InvalidPatient,
    OrderLineView,
    OrderNotCancellable,
    OrderNotFound,
    OrderView,
    PreviewLine,
    PreviewResult,
    ProductUnavailable,
    cancel_order,
    create_order,
    get_order,
    list_patient_orders,
    order_lines,
    present_order,
    preview_order,
)
from app.services.payments import OrderNotPayable, OutOfStock, PaymentDeclined, pay_order

router = APIRouter()

_UNAVAILABLE = "Product is not available for this provider."
_DUPLICATE = "Each product may appear on only one line."
_QTY_MAX = 1_000
_PRICE_MAX = 1_000_000


class PreviewLineRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    product_id: int
    qty: int = Field(ge=1, le=_QTY_MAX)
    unit_price_cents: int = Field(le=_PRICE_MAX)


class PreviewRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    lines: list[PreviewLineRequest]


class PreviewLineResponse(BaseModel):
    product_id: int
    qty: int
    unit_price_cents: int
    unit_cogs_cents: int
    line_total_cents: int
    line_cogs_cents: int
    line_margin_cents: int
    stock_available: int


class PreviewResponse(BaseModel):
    lines: list[PreviewLineResponse]
    subtotal_cents: int
    cogs_total_cents: int
    fee_bps: int
    platform_fee_cents: int
    provider_payout_cents: int


def _preview_lines(lines: Sequence[PreviewLineRequest]) -> list[PreviewLine]:
    seen: set[int] = set()
    preview: list[PreviewLine] = []
    for index, line in enumerate(lines):
        if line.product_id in seen:
            raise APIError(422, "DUPLICATE_PRODUCT", _DUPLICATE, index)
        seen.add(line.product_id)
        preview.append(
            PreviewLine(
                product_id=line.product_id,
                qty=line.qty,
                unit_price_cents=line.unit_price_cents,
            )
        )
    return preview


def _response(result: PreviewResult) -> PreviewResponse:
    split = result.split
    return PreviewResponse(
        lines=[
            PreviewLineResponse(
                product_id=line.product_id,
                qty=line.qty,
                unit_price_cents=line.unit_price_cents,
                unit_cogs_cents=line.unit_cogs_cents,
                line_total_cents=line.line_total_cents,
                line_cogs_cents=line.line_cogs_cents,
                line_margin_cents=line.line_margin_cents,
                stock_available=stock,
            )
            for line, stock in zip(split.lines, result.stock_available, strict=True)
        ],
        subtotal_cents=split.subtotal_cents,
        cogs_total_cents=split.cogs_total_cents,
        fee_bps=split.fee_bps,
        platform_fee_cents=split.platform_fee_cents,
        provider_payout_cents=split.provider_payout_cents,
    )


@router.post("/orders/preview", response_model=PreviewResponse)
def post_order_preview(
    body: PreviewRequest,
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(require_role("provider"))],
) -> PreviewResponse:
    try:
        result = preview_order(session, user.id, _preview_lines(body.lines))
    except ProductUnavailable as exc:
        raise APIError(422, "PRODUCT_UNAVAILABLE", _UNAVAILABLE, exc.line_index) from None
    return _response(result)


class CreateOrderRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    patient_id: int
    lines: list[PreviewLineRequest]


class PayRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    payment_method: Literal["fake_card_ok", "fake_card_decline"]


class OrderLineResponse(BaseModel):
    product_id: int
    product_name: str
    qty: int
    unit_price_cents: int
    unit_cogs_cents: int
    line_total_cents: int
    line_cogs_cents: int
    line_margin_cents: int


class OrderResponse(BaseModel):
    id: int
    provider_id: int
    patient_id: int
    status: str
    patient_link: str
    created_at: str
    paid_at: str | None
    cancelled_at: str | None
    payment_ref: str | None
    lines: list[OrderLineResponse]
    subtotal_cents: int
    cogs_total_cents: int
    fee_bps: int
    platform_fee_cents: int
    provider_payout_cents: int


def get_notifier(request: Request) -> Notifier:
    notifier: Notifier = request.app.state.notifier
    return notifier


def get_payment_provider(request: Request) -> PaymentProvider:
    provider: PaymentProvider = request.app.state.payment_provider
    return provider


def get_fulfillment(request: Request) -> Fulfillment:
    fulfillment: Fulfillment = request.app.state.fulfillment
    return fulfillment


def _line_response(line: OrderLineView) -> OrderLineResponse:
    return OrderLineResponse(
        product_id=line.product_id,
        product_name=line.product_name,
        qty=line.qty,
        unit_price_cents=line.unit_price_cents,
        unit_cogs_cents=line.unit_cogs_cents,
        line_total_cents=line.line_total_cents,
        line_cogs_cents=line.line_cogs_cents,
        line_margin_cents=line.line_margin_cents,
    )


def _order_response(view: OrderView) -> OrderResponse:
    return OrderResponse(
        id=view.id,
        provider_id=view.provider_id,
        patient_id=view.patient_id,
        status=view.status,
        patient_link=view.patient_link,
        created_at=view.created_at,
        paid_at=view.paid_at,
        cancelled_at=view.cancelled_at,
        payment_ref=view.payment_ref,
        lines=[_line_response(line) for line in view.lines],
        subtotal_cents=view.subtotal_cents,
        cogs_total_cents=view.cogs_total_cents,
        fee_bps=view.fee_bps,
        platform_fee_cents=view.platform_fee_cents,
        provider_payout_cents=view.provider_payout_cents,
    )


def _load_order(session: Session, order_id: int) -> Order:
    try:
        return get_order(session, order_id)
    except OrderNotFound:
        raise APIError(404, "NOT_FOUND", "Not found") from None


@router.post("/orders", response_model=OrderResponse)
def post_order(
    body: CreateOrderRequest,
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(require_role("provider"))],
    notifier: Annotated[Notifier, Depends(get_notifier)],
) -> OrderResponse:
    try:
        view = create_order(
            session,
            user.id,
            body.patient_id,
            _preview_lines(body.lines),
            notifier,
        )
    except InvalidPatient:
        raise APIError(422, "INVALID_PATIENT", "Patient must be a patient user.") from None
    except ProductUnavailable as exc:
        raise APIError(422, "PRODUCT_UNAVAILABLE", _UNAVAILABLE, exc.line_index) from None
    return _order_response(view)


@router.get("/orders/{order_id}", response_model=OrderResponse)
def get_order_detail(
    order_id: int,
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(require_role("provider", "patient"))],
) -> OrderResponse:
    order = _load_order(session, order_id)
    require_order_access(order, user)
    return _order_response(present_order(order, order_lines(session, order.id)))


@router.get("/patient/orders", response_model=list[OrderResponse])
def get_patient_orders(
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(require_role("patient"))],
) -> list[OrderResponse]:
    views: list[OrderResponse] = []
    for order in list_patient_orders(session, user.id):
        require_order_access(order, user)
        views.append(_order_response(present_order(order, order_lines(session, order.id))))
    return views


@router.post("/orders/{order_id}/cancel", response_model=OrderResponse)
def post_cancel_order(
    order_id: int,
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(require_role("provider"))],
) -> OrderResponse:
    order = _load_order(session, order_id)
    require_order_access(order, user)
    try:
        return _order_response(cancel_order(session, order))
    except OrderNotCancellable:
        raise APIError(409, "ORDER_NOT_CANCELLABLE", "Order cannot be cancelled.") from None


@router.post("/orders/{order_id}/pay", response_model=OrderResponse)
def post_pay_order(
    order_id: int,
    body: PayRequest,
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(require_role("patient"))],
    payment_provider: Annotated[PaymentProvider, Depends(get_payment_provider)],
    fulfillment: Annotated[Fulfillment, Depends(get_fulfillment)],
) -> OrderResponse:
    order = _load_order(session, order_id)
    require_order_access(order, user)
    try:
        view = pay_order(
            session,
            order.id,
            body.payment_method,
            payment_provider,
            fulfillment,
        )
    except OrderNotPayable:
        raise APIError(409, "ORDER_NOT_PAYABLE", "Order cannot be paid.") from None
    except OutOfStock:
        raise APIError(409, "OUT_OF_STOCK", "Not enough stock.") from None
    except PaymentDeclined:
        raise APIError(
            402, "PAYMENT_DECLINED", "Payment was declined. Try a different card."
        ) from None
    return _order_response(view)
