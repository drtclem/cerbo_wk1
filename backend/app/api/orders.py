from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.money import OrderSplit
from app.models import Order, User
from app.seams.auth import APIError, require_order_access, require_role
from app.seams.notifier import Notifier
from app.services.orders import (
    InvalidPatient,
    OrderLineView,
    OrderNotCancellable,
    OrderNotFound,
    OrderView,
    PreviewLine,
    ProductUnavailable,
    cancel_order,
    create_order,
    get_order,
    list_patient_orders,
    order_lines,
    present_order,
    preview_order,
)

router = APIRouter()

_UNAVAILABLE = "Product is not available for this provider."


class PreviewLineRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    product_id: int
    qty: int
    unit_price_cents: int


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


class PreviewResponse(BaseModel):
    lines: list[PreviewLineResponse]
    subtotal_cents: int
    cogs_total_cents: int
    fee_bps: int
    platform_fee_cents: int
    provider_payout_cents: int


def _response(split: OrderSplit) -> PreviewResponse:
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
            )
            for line in split.lines
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
        split = preview_order(
            session,
            user.id,
            [
                PreviewLine(
                    product_id=line.product_id,
                    qty=line.qty,
                    unit_price_cents=line.unit_price_cents,
                )
                for line in body.lines
            ],
        )
    except ProductUnavailable as exc:
        raise APIError(422, "PRODUCT_UNAVAILABLE", _UNAVAILABLE, exc.line_index) from None
    return _response(split)


class CreateOrderRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    patient_id: int
    lines: list[PreviewLineRequest]


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


def _preview_lines(lines: list[PreviewLineRequest]) -> list[PreviewLine]:
    return [
        PreviewLine(
            product_id=line.product_id,
            qty=line.qty,
            unit_price_cents=line.unit_price_cents,
        )
        for line in lines
    ]


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
