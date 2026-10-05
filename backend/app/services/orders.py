from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.domain.money import FEE_BPS_DEFAULT, LineInput, OrderSplit, validate_order
from app.models import Product, ProviderProduct

_SQLITE_MAX_INT = 9_223_372_036_854_775_807


class ProductUnavailable(Exception):
    def __init__(self, line_index: int) -> None:
        self.line_index = line_index
        super().__init__(line_index)


@dataclass(frozen=True)
class PreviewLine:
    product_id: int
    qty: int
    unit_price_cents: int


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
