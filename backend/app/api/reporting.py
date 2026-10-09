from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import User
from app.seams.auth import APIError, require_order_access, require_role
from app.services.orders import OrderNotFound, get_order
from app.services.reporting import (
    AuditLedgerEntry,
    AuditLine,
    Dashboard,
    OrderAudit,
    PaidOrderSummary,
    PendingOrderSummary,
    UnitSold,
    order_audit,
    provider_dashboard,
)

router = APIRouter()


class PaidOrderResponse(BaseModel):
    id: int
    paid_at: str
    patient_id: int
    patient_name: str
    subtotal_cents: int
    platform_fee_cents: int
    donation_cents: int
    provider_payout_cents: int
    audit_link: str


class UnitSoldResponse(BaseModel):
    product_id: int
    product_name: str
    qty: int


class PendingOrderResponse(BaseModel):
    id: int
    created_at: str
    patient_id: int
    patient_name: str


class DashboardResponse(BaseModel):
    gmv_cents: int
    platform_fee_cents: int
    donation_cents: int
    earnings_cents: int
    paid_orders: list[PaidOrderResponse]
    units_sold: list[UnitSoldResponse]
    pending_orders: list[PendingOrderResponse]


class AuditLineResponse(BaseModel):
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


class AuditLedgerResponse(BaseModel):
    entry_type: str
    amount_cents: int
    created_at: str
    fund_id: int | None


class AuditResponse(BaseModel):
    id: int
    status: str
    payment_ref: str | None
    paid_at: str | None
    lines: list[AuditLineResponse]
    subtotal_cents: int
    cogs_total_cents: int
    fee_bps: int
    platform_fee_cents: int
    donation_bps: int
    donation_cents: int
    provider_payout_cents: int
    ledger: list[AuditLedgerResponse]
    recomputed_fee_matches: bool
    donation_matches_rate: bool
    split_adds_up: bool
    ledger_matches_split: bool


def _paid_order(item: PaidOrderSummary) -> PaidOrderResponse:
    return PaidOrderResponse(
        id=item.id,
        paid_at=item.paid_at,
        patient_id=item.patient_id,
        patient_name=item.patient_name,
        subtotal_cents=item.subtotal_cents,
        platform_fee_cents=item.platform_fee_cents,
        donation_cents=item.donation_cents,
        provider_payout_cents=item.provider_payout_cents,
        audit_link=item.audit_link,
    )


def _unit(item: UnitSold) -> UnitSoldResponse:
    return UnitSoldResponse(
        product_id=item.product_id,
        product_name=item.product_name,
        qty=item.qty,
    )


def _pending_order(item: PendingOrderSummary) -> PendingOrderResponse:
    return PendingOrderResponse(
        id=item.id,
        created_at=item.created_at,
        patient_id=item.patient_id,
        patient_name=item.patient_name,
    )


def _dashboard(view: Dashboard) -> DashboardResponse:
    return DashboardResponse(
        gmv_cents=view.gmv_cents,
        platform_fee_cents=view.platform_fee_cents,
        donation_cents=view.donation_cents,
        earnings_cents=view.earnings_cents,
        paid_orders=[_paid_order(item) for item in view.paid_orders],
        units_sold=[_unit(item) for item in view.units_sold],
        pending_orders=[_pending_order(item) for item in view.pending_orders],
    )


def _audit_line(line: AuditLine) -> AuditLineResponse:
    return AuditLineResponse(
        product_id=line.product_id,
        product_name=line.product_name,
        qty=line.qty,
        unit_price_cents=line.unit_price_cents,
        unit_cogs_cents=line.unit_cogs_cents,
        line_total_cents=line.line_total_cents,
        line_cogs_cents=line.line_cogs_cents,
        line_margin_cents=line.line_margin_cents,
        donation_cents=line.donation_cents,
        fund_id=line.fund_id,
        fund_name=line.fund_name,
        fund_url=line.fund_url,
    )


def _audit_entry(entry: AuditLedgerEntry) -> AuditLedgerResponse:
    return AuditLedgerResponse(
        entry_type=entry.entry_type,
        amount_cents=entry.amount_cents,
        created_at=entry.created_at,
        fund_id=entry.fund_id,
    )


def _audit(view: OrderAudit) -> AuditResponse:
    return AuditResponse(
        id=view.id,
        status=view.status,
        payment_ref=view.payment_ref,
        paid_at=view.paid_at,
        lines=[_audit_line(line) for line in view.lines],
        subtotal_cents=view.subtotal_cents,
        cogs_total_cents=view.cogs_total_cents,
        fee_bps=view.fee_bps,
        platform_fee_cents=view.platform_fee_cents,
        donation_bps=view.donation_bps,
        donation_cents=view.donation_cents,
        provider_payout_cents=view.provider_payout_cents,
        ledger=[_audit_entry(entry) for entry in view.ledger],
        recomputed_fee_matches=view.recomputed_fee_matches,
        donation_matches_rate=view.donation_matches_rate,
        split_adds_up=view.split_adds_up,
        ledger_matches_split=view.ledger_matches_split,
    )


@router.get("/provider/dashboard", response_model=DashboardResponse)
def get_provider_dashboard(
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(require_role("provider"))],
) -> DashboardResponse:
    return _dashboard(provider_dashboard(session, user.id))


@router.get("/orders/{order_id}/audit", response_model=AuditResponse)
def get_order_audit(
    order_id: int,
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(require_role("provider"))],
) -> AuditResponse:
    try:
        order = get_order(session, order_id)
    except OrderNotFound:
        raise APIError(404, "NOT_FOUND", "Not found") from None
    require_order_access(order, user)
    return _audit(order_audit(session, order))
