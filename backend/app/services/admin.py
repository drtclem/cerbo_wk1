from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.models import Product

_SQLITE_MAX_INT = 9_223_372_036_854_775_807


class UnknownProduct(Exception):
    pass


def list_admin_products(session: Session) -> list[Product]:
    """Read the catalog. Does not write."""
    return list(session.scalars(select(Product).order_by(Product.id)))


def update_admin_product(
    session: Session,
    product_id: int,
    *,
    stock_qty: int | None,
    unit_cogs_cents: int | None,
) -> Product:
    """Update only the columns the admin sent. Does not touch orders or prices."""
    if not 1 <= product_id <= _SQLITE_MAX_INT:
        raise UnknownProduct
    values: dict[str, int] = {}
    if stock_qty is not None:
        values["stock_qty"] = stock_qty
    if unit_cogs_cents is not None:
        values["unit_cogs_cents"] = unit_cogs_cents
    updated = cast(
        CursorResult[Any],
        session.execute(
            update(Product)
            .where(Product.id == product_id)
            .values(**values)
            .execution_options(synchronize_session=False)
        ),
    )
    if updated.rowcount != 1:
        session.rollback()
        raise UnknownProduct
    session.commit()
    session.expire_all()
    product = session.get(Product, product_id)
    if product is None:
        raise UnknownProduct
    return product
