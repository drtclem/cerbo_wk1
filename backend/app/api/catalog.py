from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Product, User
from app.seams.auth import APIError, require_role
from app.services.catalog import (
    ProviderProductView,
    UnknownProduct,
    list_products,
    list_provider_products,
    update_provider_product,
)

router = APIRouter()


class CatalogProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    unit_cogs_cents: int
    suggested_price_cents: int
    stock_qty: int


class ProviderProductResponse(BaseModel):
    product_id: int
    sku: str
    name: str
    enabled: bool
    default_price_cents: int
    unit_cogs_cents: int
    stock_qty: int


class ProviderProductUpdate(BaseModel):
    model_config = ConfigDict(strict=True)

    enabled: bool
    default_price_cents: int


@router.get("/products", response_model=list[CatalogProductResponse])
def get_products(
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[User, Depends(require_role("provider", "admin"))],
) -> list[Product]:
    return list_products(session)


@router.get("/provider/products", response_model=list[ProviderProductResponse])
def get_provider_products(
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(require_role("provider"))],
) -> list[ProviderProductView]:
    return list_provider_products(session, user.id)


@router.put("/provider/products/{product_id}", response_model=ProviderProductResponse)
def put_provider_product(
    product_id: int,
    body: ProviderProductUpdate,
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(require_role("provider"))],
) -> ProviderProductView:
    try:
        return update_provider_product(
            session,
            user.id,
            product_id,
            enabled=body.enabled,
            default_price_cents=body.default_price_cents,
        )
    except UnknownProduct:
        raise APIError(404, "NOT_FOUND", "Not found") from None
