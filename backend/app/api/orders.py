from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.money import OrderSplit
from app.models import User
from app.seams.auth import APIError, require_role
from app.services.orders import PreviewLine, ProductUnavailable, preview_order

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
