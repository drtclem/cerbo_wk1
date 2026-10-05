from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.money import FEE_BPS_DEFAULT, LineInput, validate_order
from app.models import Product, ProviderProduct


class UnknownProduct(Exception):
    pass


@dataclass(frozen=True)
class ProviderProductView:
    product_id: int
    sku: str
    name: str
    enabled: bool
    default_price_cents: int
    unit_cogs_cents: int
    stock_qty: int


def list_products(session: Session) -> list[Product]:
    return list(session.scalars(select(Product).order_by(Product.id)))


def list_provider_products(session: Session, provider_id: int) -> list[ProviderProductView]:
    rows = session.execute(
        select(ProviderProduct, Product)
        .join(Product, Product.id == ProviderProduct.product_id)
        .where(ProviderProduct.provider_id == provider_id)
        .order_by(Product.id)
    ).all()
    return [_view(link, product) for link, product in rows]


def update_provider_product(
    session: Session,
    provider_id: int,
    product_id: int,
    *,
    enabled: bool,
    default_price_cents: int,
) -> ProviderProductView:
    product = session.get(Product, product_id)
    if product is None:
        raise UnknownProduct

    validate_order(
        (
            LineInput(
                product_id=product.id,
                qty=1,
                unit_price_cents=default_price_cents,
                unit_cogs_cents=product.unit_cogs_cents,
            ),
        ),
        FEE_BPS_DEFAULT,
    )

    link = session.get(ProviderProduct, (provider_id, product_id))
    enabled_value = 1 if enabled else 0
    if link is None:
        link = ProviderProduct(
            provider_id=provider_id,
            product_id=product_id,
            enabled=enabled_value,
            default_price_cents=default_price_cents,
        )
        session.add(link)
    else:
        link.enabled = enabled_value
        link.default_price_cents = default_price_cents
    session.commit()
    return _view(link, product)


def _view(link: ProviderProduct, product: Product) -> ProviderProductView:
    return ProviderProductView(
        product_id=product.id,
        sku=product.sku,
        name=product.name,
        enabled=link.enabled == 1,
        default_price_cents=link.default_price_cents,
        unit_cogs_cents=product.unit_cogs_cents,
        stock_qty=product.stock_qty,
    )
