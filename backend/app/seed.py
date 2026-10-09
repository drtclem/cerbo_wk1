from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Product, ProviderProduct, User

_USERS = (
    ("Dr. Maya Patel", "provider"),
    ("Jane Doe", "patient"),
    ("Sam Lee", "patient"),
    ("Cerbo Admin", "admin"),
)

_DEFAULT_DOSING = "Example: 1 capsule daily with a meal"

_PRODUCTS = (
    ("MAG-GLY", "Magnesium Glycinate", 1200, 2400, 50, _DEFAULT_DOSING),
    ("D3-K2", "Vitamin D3 + K2", 900, 1800, 40, _DEFAULT_DOSING),
    ("OMEGA3", "Omega-3 Fish Oil", 1850, 3600, 25, _DEFAULT_DOSING),
    ("PROBIO50", "Probiotic 50B", 2100, 4200, 1, _DEFAULT_DOSING),
)

_PROVIDER_NAME = "Dr. Maya Patel"


def seed(session: Session) -> None:
    """Insert seed rows that are not already present. Does not commit."""
    for name, role in _USERS:
        if session.scalar(select(User).where(User.name == name)) is None:
            session.add(User(name=name, role=role))

    provider = session.scalar(select(User).where(User.name == _PROVIDER_NAME))
    if provider is None:
        return

    for sku, name, cogs_cents, suggested_cents, stock_qty, default_dosing in _PRODUCTS:
        product = session.scalar(select(Product).where(Product.sku == sku))
        if product is None:
            product = Product(
                sku=sku,
                name=name,
                unit_cogs_cents=cogs_cents,
                suggested_price_cents=suggested_cents,
                stock_qty=stock_qty,
                default_dosing=default_dosing,
            )
            session.add(product)
            session.flush()

        already_offered = session.scalar(
            select(ProviderProduct).where(
                ProviderProduct.provider_id == provider.id,
                ProviderProduct.product_id == product.id,
            )
        )
        if already_offered is None:
            session.add(
                ProviderProduct(
                    provider_id=provider.id,
                    product_id=product.id,
                    enabled=1,
                    default_price_cents=product.suggested_price_cents,
                )
            )
