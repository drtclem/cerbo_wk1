import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.db import make_engine
from app.models import LedgerEntry, Order, OrderLine, Product, ProviderProduct, User
from app.seed import seed

_CREATED_AT = "2026-10-05T15:00:00Z"
_EXPECTED_USERS = {
    ("Dr. Maya Patel", "provider"),
    ("Jane Doe", "patient"),
    ("Sam Lee", "patient"),
    ("Cerbo Admin", "admin"),
}
_EXPECTED_PRODUCTS = {
    ("MAG-GLY", "Magnesium Glycinate", 1200, 2400, 50, "Example: 1 capsule daily with a meal"),
    ("D3-K2", "Vitamin D3 + K2", 900, 1800, 40, "Example: 1 capsule daily with a meal"),
    ("OMEGA3", "Omega-3 Fish Oil", 1850, 3600, 25, "Example: 1 capsule daily with a meal"),
    ("PROBIO50", "Probiotic 50B", 2100, 4200, 1, "Example: 1 capsule daily with a meal"),
}


def _assert_int(value: object) -> None:
    assert isinstance(value, int) and not isinstance(value, bool)


def _engine(session: Session) -> Engine:
    bind = session.get_bind()
    if isinstance(bind, Connection):
        return bind.engine
    return bind


def _commit_provider_patient_product(session: Session) -> tuple[int, int, int]:
    provider = User(name="Dr. Maya Patel", role="provider")
    patient = User(name="Jane Doe", role="patient")
    product = Product(
        sku="MAG-GLY",
        name="Magnesium Glycinate",
        unit_cogs_cents=1200,
        suggested_price_cents=2400,
        stock_qty=50,
        default_dosing="Example: 1 capsule daily with a meal",
    )
    session.add_all([provider, patient, product])
    session.commit()
    return provider.id, patient.id, product.id


def _add_pending_order(session: Session, provider_id: int, patient_id: int) -> Order:
    order = Order(
        provider_id=provider_id,
        patient_id=patient_id,
        status="pending_payment",
        fee_bps=75,
        subtotal_cents=100,
        cogs_total_cents=40,
        platform_fee_cents=10,
        provider_payout_cents=50,
        created_at=_CREATED_AT,
    )
    session.add(order)
    return order


def test_seed_creates_architecture_section_5_data_and_a_second_seed_does_not_duplicate(
    db_session: Session,
) -> None:
    seed(db_session)
    db_session.commit()
    seed(db_session)
    db_session.commit()

    users = db_session.scalars(select(User)).all()
    assert len(users) == 4
    assert {(user.name, user.role) for user in users} == _EXPECTED_USERS

    products = db_session.scalars(select(Product)).all()
    assert len(products) == 4
    assert {
        (
            product.sku,
            product.name,
            product.unit_cogs_cents,
            product.suggested_price_cents,
            product.stock_qty,
            product.default_dosing,
        )
        for product in products
    } == _EXPECTED_PRODUCTS
    for product in products:
        _assert_int(product.unit_cogs_cents)
        _assert_int(product.suggested_price_cents)
        _assert_int(product.stock_qty)
        assert product.default_dosing == "Example: 1 capsule daily with a meal"

    provider = db_session.scalars(select(User).where(User.name == "Dr. Maya Patel")).one()
    links = db_session.scalars(
        select(ProviderProduct).where(ProviderProduct.provider_id == provider.id)
    ).all()
    suggested_by_product_id = {product.id: product.suggested_price_cents for product in products}
    assert len(links) == 4
    assert len(db_session.scalars(select(ProviderProduct)).all()) == 4
    assert {link.product_id for link in links} == set(suggested_by_product_id)
    for link in links:
        assert link.enabled == 1
        _assert_int(link.default_price_cents)
        assert link.default_price_cents == suggested_by_product_id[link.product_id]


def test_seed_does_not_commit_by_itself(db_session: Session) -> None:
    # A second connection cannot read while this transaction holds BEGIN IMMEDIATE.
    # Rollback is the proof the inserts are still uncommitted.
    seed(db_session)
    db_session.rollback()
    assert db_session.scalars(select(User)).all() == []

    seed(db_session)
    db_session.commit()
    assert {(user.name, user.role) for user in db_session.scalars(select(User)).all()} == (
        _EXPECTED_USERS
    )


def test_db_rejects_stock_qty_of_negative_one(db_session: Session) -> None:
    db_session.add(
        Product(
            sku="BAD",
            name="Bad",
            unit_cogs_cents=100,
            suggested_price_cents=200,
            stock_qty=-1,
            default_dosing="Example: 1 capsule daily with a meal",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_db_rejects_order_line_qty_zero(db_session: Session) -> None:
    provider_id, patient_id, product_id = _commit_provider_patient_product(db_session)
    order = _add_pending_order(db_session, provider_id, patient_id)
    db_session.flush()
    db_session.add(
        OrderLine(
            order_id=order.id,
            product_id=product_id,
            product_name="Magnesium Glycinate",
            qty=0,
            unit_price_cents=200,
            unit_cogs_cents=100,
        dosing="Example: 1 capsule daily with a meal",
        note=None,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_db_rejects_order_line_unit_price_below_unit_cogs(db_session: Session) -> None:
    provider_id, patient_id, product_id = _commit_provider_patient_product(db_session)
    order = _add_pending_order(db_session, provider_id, patient_id)
    db_session.flush()
    db_session.add(
        OrderLine(
            order_id=order.id,
            product_id=product_id,
            product_name="Magnesium Glycinate",
            qty=1,
            unit_price_cents=100,
            unit_cogs_cents=200,
        dosing="Example: 1 capsule daily with a meal",
        note=None,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_db_rejects_order_whose_split_does_not_add_up(db_session: Session) -> None:
    provider_id, patient_id, _product_id = _commit_provider_patient_product(db_session)
    db_session.add(
        Order(
            provider_id=provider_id,
            patient_id=patient_id,
            status="pending_payment",
            fee_bps=75,
            subtotal_cents=100,
            cogs_total_cents=40,
            platform_fee_cents=10,
            provider_payout_cents=40,
            created_at=_CREATED_AT,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_db_rejects_negative_payout_that_still_sums(db_session: Session) -> None:
    provider_id, patient_id, _product_id = _commit_provider_patient_product(db_session)
    db_session.add(
        Order(
            provider_id=provider_id,
            patient_id=patient_id,
            status="pending_payment",
            fee_bps=75,
            subtotal_cents=100,
            cogs_total_cents=50,
            platform_fee_cents=51,
            provider_payout_cents=-1,
            created_at=_CREATED_AT,
        )
    )
    with pytest.raises(IntegrityError) as raised:
        db_session.commit()
    cause = raised.value.orig
    assert cause is not None
    detail = str(cause)
    assert "payout" in detail
    assert "+" not in detail


def test_db_rejects_second_cerbo_fee_ledger_row_for_the_same_order(db_session: Session) -> None:
    provider_id, patient_id, _product_id = _commit_provider_patient_product(db_session)
    order = _add_pending_order(db_session, provider_id, patient_id)
    db_session.flush()
    db_session.add(
        LedgerEntry(
            order_id=order.id,
            entry_type="cerbo_fee",
            amount_cents=10,
            created_at=_CREATED_AT,
        )
    )
    db_session.flush()
    db_session.add(
        LedgerEntry(
            order_id=order.id,
            entry_type="cerbo_fee",
            amount_cents=10,
            created_at=_CREATED_AT,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_db_rejects_unknown_role(db_session: Session) -> None:
    db_session.add(User(name="Nope", role="nope"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_db_rejects_unknown_order_status(db_session: Session) -> None:
    provider_id, patient_id, _product_id = _commit_provider_patient_product(db_session)
    db_session.add(
        Order(
            provider_id=provider_id,
            patient_id=patient_id,
            status="shipped",
            fee_bps=75,
            subtotal_cents=100,
            cogs_total_cents=40,
            platform_fee_cents=10,
            provider_payout_cents=50,
            created_at=_CREATED_AT,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_db_rejects_unknown_ledger_entry_type(db_session: Session) -> None:
    provider_id, patient_id, _product_id = _commit_provider_patient_product(db_session)
    order = _add_pending_order(db_session, provider_id, patient_id)
    db_session.flush()
    db_session.add(
        LedgerEntry(
            order_id=order.id,
            entry_type="refund",
            amount_cents=10,
            created_at=_CREATED_AT,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_db_rejects_non_integer_money_value(db_session: Session) -> None:
    engine = _engine(db_session)
    with engine.connect() as connection:
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                "INSERT INTO products "
                "(sku, name, unit_cogs_cents, suggested_price_cents, stock_qty) "
                "VALUES ('BAD', 'Bad', 1.5, 100, 1)"
            )
            connection.commit()


def test_foreign_keys_reject_order_line_whose_order_does_not_exist(
    db_session: Session,
) -> None:
    _provider_id, _patient_id, product_id = _commit_provider_patient_product(db_session)
    db_session.add(
        OrderLine(
            order_id=999_999,
            product_id=product_id,
            product_name="Magnesium Glycinate",
            qty=1,
            unit_price_cents=2400,
            unit_cogs_cents=1200,
        dosing="Example: 1 capsule daily with a meal",
        note=None,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_begin_immediate_holds_the_write_lock(db_session: Session) -> None:
    engine_b: Engine | None = None
    connection_b: Connection | None = None
    try:
        db_session.begin()
        db_session.execute(text("SELECT 1"))
        engine_b = make_engine(str(_engine(db_session).url))
        connection_b = engine_b.connect()
        raw = connection_b.connection.driver_connection
        assert raw is not None
        cursor = raw.cursor()
        cursor.execute("PRAGMA busy_timeout=300")
        cursor.close()
        with pytest.raises(OperationalError, match="locked"):
            connection_b.exec_driver_sql(
                "INSERT INTO users (name, role) VALUES ('Other', 'patient')"
            )
            connection_b.commit()
    finally:
        if connection_b is not None:
            connection_b.close()
        if engine_b is not None:
            engine_b.dispose()
        db_session.close()
