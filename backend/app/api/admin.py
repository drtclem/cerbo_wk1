from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Product, User
from app.seams.auth import APIError, require_role
from app.services.admin import UnknownProduct, list_admin_products, update_admin_product

router = APIRouter()

_SQLITE_MAX_INT = 9_223_372_036_854_775_807


class AdminProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    unit_cogs_cents: int
    suggested_price_cents: int
    stock_qty: int


class AdminProductUpdate(BaseModel):
    model_config = ConfigDict(strict=True)

    stock_qty: int | None = None
    unit_cogs_cents: int | None = None

    @model_validator(mode="after")
    def _bounds(self) -> "AdminProductUpdate":
        if self.stock_qty is None and self.unit_cogs_cents is None:
            raise ValueError("empty")
        if self.stock_qty is not None and not 0 <= self.stock_qty <= _SQLITE_MAX_INT:
            raise ValueError("stock")
        if self.unit_cogs_cents is not None and not 1 <= self.unit_cogs_cents <= _SQLITE_MAX_INT:
            raise ValueError("cogs")
        return self


@router.get("/admin/products", response_model=list[AdminProductResponse])
def get_admin_products(
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[User, Depends(require_role("admin"))],
) -> list[Product]:
    return list_admin_products(session)


@router.put("/admin/products/{product_id}", response_model=AdminProductResponse)
def put_admin_product(
    product_id: int,
    body: AdminProductUpdate,
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[User, Depends(require_role("admin"))],
) -> Product:
    try:
        return update_admin_product(
            session,
            product_id,
            stock_qty=body.stock_qty,
            unit_cogs_cents=body.unit_cogs_cents,
        )
    except UnknownProduct:
        raise APIError(404, "NOT_FOUND", "Not found") from None
